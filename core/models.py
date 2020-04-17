import time
import json
import math
import joblib
import logging
import pandas as pd

from django.db import models
from django.db import transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator

from core.libs.helpers.data_classes import *
from core.libs.helpers.ccxt import CcxtBotExecutor
from core.libs.helpers.sizing import KellySizing, PercentSizing
from core.libs.helpers.features import get_calc_features_fn


class Exchange(models.Model):
    name = models.TextField(max_length=100)
    slug = models.TextField(max_length=30, default="bitfinex")
    exchange_email = models.EmailField()

    class Meta:
        unique_together = ('slug', 'exchange_email')

    def __str__(self):
        return f"{self.name} ({self.exchange_email})"


class Currency(models.Model):
    name = models.TextField(unique=True)
    slug = models.TextField(validators=[
        RegexValidator('^[A-Z]*$', 'Only uppercase letters are allowed.')])

    def __str__(self):
        return f"{self.slug} ({self.name})"


class Symbol(models.Model):
    base = models.ForeignKey(Currency, related_name="base", null=False, blank=False, on_delete=models.PROTECT)
    quote = models.ForeignKey(Currency, related_name="quote", null=False, blank=False, on_delete=models.PROTECT)

    def to_kaiko(self):
        return f"{self.base.slug.lower()}-{self.quote.slug.lower()}"

    def to_ccxt(self):
        return f"{self.base.slug}/{self.quote.slug}"

    def to_binance(self):
        return f"{self.base.slug.upper()}{self.quote.slug.upper()}"

    def __str__(self):
        return f"{self.base.slug}-{self.quote.slug}"


class Instrument(models.Model):
    TYPE_CHOICES = (
        ("SPOT", "spot"),
        ("MARGIN", "margin"),
        ("FUTURE", "future"),
    )

    exchange = models.ForeignKey(Exchange, null=False, blank=False, on_delete=models.PROTECT)
    symbol = models.ForeignKey(Symbol, on_delete=models.PROTECT)
    kaiko_type = models.TextField(choices=TYPE_CHOICES, default="SPOT")

    size_round_precision = models.IntegerField(default=9)

    def __str__(self):
        return f"{self.symbol} - {self.kaiko_type} on {self.exchange}"


@dataclass
class ConsolidatorBar:
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float


class Consolidator(models.Model):
    TYPE_CHOICES = (
        ("TIME", "time"),
        ("PERCENT", "percent"),
    )

    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    type = models.TextField(choices=TYPE_CHOICES, default="TIME")

    """
    Example kwargs per TYPE_CHOICE
        PERCENT -> { "percent": 0.0005 }
        TIME -> { "time_frame_seconds": 60 }
    """
    kwargs = models.TextField()

    update_timestamp = models.IntegerField(default=0)
    parent_update_timestamp = models.IntegerField(default=0)

    latest_bar_data = models.TextField(default=None, null=True, blank=True)
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.instrument} [{self.type}] // {self.kwargs}"

    def get_kwargs(self):
        return json.loads(self.kwargs)

    def new_bars_event(self, latest_bar_data):
        self.update_timestamp = latest_bar_data['timestamp']
        self.latest_bar_data = json.dumps(latest_bar_data)
        if self.parent is not None:
            self.parent_update_timestamp = self.parent.update_timestamp
        self.save()

    def get_last_bar(self) -> ConsolidatorBar:
        data = json.loads(self.latest_bar_data)
        return ConsolidatorBar(
            timestamp=data['timestamp'],
            open=data['open'],
            high=data['high'],
            low=data['low'],
            close=data['close'],
            volume=data['volume']
        )


class ExchangeCredentials(models.Model):
    name = models.TextField(max_length=200)
    exchange = models.ForeignKey(Exchange, on_delete=models.PROTECT)

    """
    plain CCXT init object in json (would be translated to dict through json.loads)
    {
      "apiKey": "XXX",
      "secret": "YYY",
      "timeout": 5000,  
      "enableRateLimit": true,
      "options": {
          "orderTypes": {
              "limit": "limit",
              "market": "market"
          }
      }
    }
    """
    init_kwargs = models.TextField()

    def __str__(self):
        return f"{self.name} for {self.exchange}"


class BotSizing(models.Model):
    TYPE_CHOICES = (
        ("FIXED", "fixed"),
        ("PERCENT", "percent"),
        ("KELLY", "kelly")
    )
    name = models.TextField(default="")
    type = models.TextField(choices=TYPE_CHOICES, default='fixed')
    kwargs = models.TextField(default="{}")

    is_short_allowed = models.BooleanField(default=False)
    is_long_allowed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.type} // {self.name} // {self.kwargs}"

    @staticmethod
    def calc_size_for_signal(bot_signal: "BotSignal"):
        sizing_method = bot_signal.bot.sizing.__get_sizing_method_by_type()
        return round(sizing_method(bot_signal), bot_signal.bot.instrument.size_round_precision)

    ################################
    # Helper methods
    ################################

    def __get_sizing_kwargs(self):
        return json.loads(self.kwargs)

    def __get_sizing_method_by_type(self):
        method_name = f"__{self.get_type_display()}__"
        if hasattr(self, method_name):
            return getattr(self, method_name)

        raise Exception(f"Sizing type method `{self.type}` not exists.")

    ################################
    # Sizing methods
    ################################

    def __kelly__(self, bot_signal: "BotSignal"):
        # kwargs = dict(win_size: float, loss_size: float, divider: float = 1, direction=one_of("pos", "neg", "both"))
        kwargs = self.__get_sizing_kwargs()
        sizing = KellySizing(**kwargs)

        ccxt_manager = CcxtBotExecutor(bot_signal.bot)
        balance = ccxt_manager.get_balance()
        ticker = ccxt_manager.get_ticker()

        # TODO: ticker price for limit order tupes should be swapped
        ticker_price = ticker.bid if bot_signal.signal > 0.5 else ticker.ask

        return balance.amount_all * sizing.size(bot_signal.signal) / ticker_price

    def __fixed__(self, bot_signal: "BotSignal"):
        kwargs = self.__get_sizing_kwargs()
        if bot_signal.signal > 0.5:
            signal = (bot_signal.signal - 0.5) * 2
        else:
            signal = (0.5 - (1 - bot_signal.signal)) * 2

        if 'multiply_by_signal' in kwargs and kwargs['multiply_by_signal']:
            return kwargs['amount'] * signal
        else:
            return kwargs['amount'] * math.copysign(1, signal)

    def __percent__(self, bot_signal: "BotSignal"):
        # kwargs = dict(percent=0.5, threshold=0.6, direction=one_of("pos", "neg", "both"))
        kwargs = self.get_sizing_kwargs()
        sizing = PercentSizing(**kwargs)
        return sizing.size(bot_signal.signal)

        # kwargs = json.loads(self.kwargs)
        #
        # bot = bot_signal.bot
        #
        # ccxt_manager = CcxtBotExecutor(bot)
        # bot_balance = ccxt_manager.get_balance()
        # bot_position = ccxt_manager.get_position()
        #
        # signal = (bot_signal.signal - 0.5) * 2
        #
        # if not self.is_short_allowed:
        #     if signal < 0:
        #         signal = 0
        #
        # if not self.is_long_allowed:
        #     if signal > 0:
        #         signal = 0
        #
        # return kwargs['percent'] * bot_balance.amount_all * signal


class BotMlConfig(models.Model):
    name = models.TextField(max_length=100, unique=True)
    description = models.TextField()
    file = models.FileField(help_text="Model JobLib dump file", upload_to=f"{settings.MODELS_DIRECTORY}/models")
    fn_tasks = models.TextField(help_text="JobManager fn_tasks JSON object")
    last_update_timestamp = models.IntegerField(default=0)

    def save(self, *args, **kwargs):
        self.last_update_timestamp = int(time.time())
        super().save(*args, **kwargs)

    # TODO: implement correct in-memory model caching (redis? need to research)
    cache = dict()

    def __get_from_cache__(self):
        cache_key = f"{self.id}-{self.last_update_timestamp}"

        if cache_key not in self.cache:
            self.cache[cache_key] = dict(
                model=joblib.load(self.file.path),
                fn_tasks=json.loads(self.fn_tasks)
            )

        return self.cache[cache_key]

    def get_fn_tasks(self):
        return self.__get_from_cache__()['fn_tasks']

    def get_model(self):
        return self.__get_from_cache__()['model']


class Bot(models.Model):
    # if parent is not null, then this is DummyBot
    # that receiving signals on parent.push_signal
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)

    name = models.TextField(max_length=200)
    exchange_credentials = models.ForeignKey(ExchangeCredentials, on_delete=models.PROTECT)
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)

    data_feed = models.ForeignKey(Consolidator, on_delete=models.PROTECT)
    predict_timestamp = models.IntegerField(default=0)

    sizing = models.ForeignKey(BotSizing, on_delete=models.PROTECT)

    ml_config = models.ForeignKey(BotMlConfig, on_delete=models.PROTECT, null=True)

    is_active = models.BooleanField(default=False)

    min_trade_amount = models.FloatField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Min trade size for the instrument, e.g. bitfinex BTCUSD = 0.00082, bitmex XBTUSD - 1")

    max_trade_amount = models.FloatField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Max trade size for the instrument, e.g. bitfinex BTCUSD = 0.00082, bitmex XBTUSD - 1")

    slippage_pct_position_increase = models.FloatField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(0.1)],
        help_text="Max diff between current price and target instrument execution price on position increase.")

    slippage_pct_position_decrease = models.FloatField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(0.1)],
        help_text="Max diff between current price and target instrument execution price on position decrease.")

    def datafeed_has_new_data_to_predict(self):
        return self.data_feed.update_timestamp > self.predict_timestamp

    def get_feed_dataframe(self, rows_count=None) -> pd.DataFrame:
        feed_id = self.data_feed.id
        file_path = f"{settings.BARS_DIRECTORY}/{feed_id}.h5"

        with pd.HDFStore(file_path, mode='r') as store:
            store_rows_count = store.get_storer('table').nrows
            if rows_count is None:
                df = store.select('table')
            else:
                if store_rows_count < rows_count:
                    raise Exception(f"Bars feed_id={feed_id} has {store_rows_count} bars in store "
                                    f"(less then requested amount {rows_count}).")
                df = store.select('table', start=store_rows_count - rows_count, stop=store_rows_count)

            return df

    @transaction.atomic
    def predict_and_push_signal(self):
        if not self.datafeed_has_new_data_to_predict():
            return None

        features_fn = get_calc_features_fn(fn_tasks=self.ml_config.get_fn_tasks())
        m = self.ml_config.get_model()

        bot_signal_latest = BotSignal.get_active(self)

        bot_signal = None
        if bot_signal_latest is None or \
                self.data_feed.update_timestamp > bot_signal_latest.timestamp_consolidator:
            # new bar exists, should be executed
            bars = self.get_feed_dataframe(rows_count=101)
            X, y, X_to_predict = features_fn(bars)
            y_pred = m.predict_proba(X_to_predict)
            # as long as X_to_predict is 1 bar only
            signal = y_pred[0][1]
            bot_signal = BotSignal.push_signal(self, signal)
            self.predict_timestamp = self.data_feed.update_timestamp
            self.save()

        return bot_signal

    def clean(self, *args, **kwargs):
        active_bots = Bot.objects.filter(exchange_credentials=self.exchange_credentials, is_active=True)
        if len(active_bots) != 0:
            if len(active_bots) == 1 and active_bots[0].id == self.id:
                return

            raise ValidationError(
                f"Only one active bot with same exchange_credentials is allowed."
                f" Disable other bots ({[str(b) for b in active_bots]})")

    def __str__(self):
        return f"{self.name} // {self.instrument}"

    def get_exposure(self, on_price=None):
        ccxt_manager = CcxtBotExecutor(self)
        bot_balance = ccxt_manager.get_balance()
        bot_position = ccxt_manager.get_position()
        position_price = on_price
        if position_price is None:
            position_price = bot_position.price_avg
        return bot_position.size * position_price / bot_balance.amount_all


class BotSignal(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.PROTECT)
    signal = models.FloatField(validators=[
        MinValueValidator(-1), MaxValueValidator(1)
    ])
    timestamp_consolidator = models.IntegerField()
    timestamp_real = models.IntegerField()
    is_active = models.BooleanField(default=False)

    @classmethod
    def get_active(cls, bot: Bot):
        try:
            return cls.objects.get(bot=bot, is_active=True)
        except cls.DoesNotExist:
            return None

    def save(self, *args, **kwargs):
        # Disable latest active BotSignal
        BotSignal.objects.filter(bot=self.bot).update(is_active=False)
        super().save(*args, **kwargs)

    @staticmethod
    def push_signal(bot: "Bot", signal: float):
        # Disable latest active Signal

        # Add new signal
        bot_signal = BotSignal(
            bot=bot,
            signal=signal,
            timestamp_consolidator=bot.data_feed.update_timestamp,
            timestamp_real=int(time.time()),
            is_active=True
        )
        bot_signal.save()

        logging.info(f"bot ({bot}) has new signal ({bot_signal})")

        # log bot performance
        BotPerformanceLog.fetch_and_log(bot_signal)

        # Get new target size
        state_target_size = BotSizing.calc_size_for_signal(bot_signal)
        state_target_price = bot.data_feed.get_last_bar().close

        # Add new target state
        target_state = BotTargetState(
            bot=bot,
            bot_signal=bot_signal,
            instrument_target_size=state_target_size,
            instrument_target_execution_price=state_target_price,
            is_active=True,
            data_feed_info=json.dumps(dict(
                data_feed__last_bar=bot.data_feed.get_last_bar().__dict__,
                data_feed_parent__last_bar=bot.data_feed.parent.get_last_bar().__dict__ if bot.data_feed.parent else None,
            ), indent=4)
        )
        target_state.save()

        # Push signals to children
        for child_bot in Bot.objects.filter(parent=bot, is_active=True):
            BotSignal.push_signal(bot=child_bot, signal=signal)

        logging.info(f"bot ({bot}) has new target state ({target_state})")

        return bot_signal


class BotTargetState(models.Model):
    bot = models.ForeignKey("Bot", on_delete=models.PROTECT)
    bot_signal = models.ForeignKey("BotSignal", on_delete=models.PROTECT)
    # MaxValueValidator - max leverage in exchange prices
    # e.g. instrument_target=4 for BTCUSD means we should have 40k worth of BTC if we have 10k USD on exchange balance
    instrument_target_size = models.FloatField(default=0.0, validators=[MinValueValidator(-5), MaxValueValidator(5)])
    instrument_target_execution_price = models.FloatField()

    is_active = models.BooleanField(default=False)

    data_feed_info = models.TextField(default=None, null=True, blank=True)

    def save(self, *args, **kwargs):
        # Disable latest active TargetState
        BotTargetState.objects.filter(bot=self.bot).update(is_active=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_active(cls):
        return cls.objects.get(is_active=True)

    def log_position(self, position: BotPosition):
        pos_log = BotPositionLog(
            bot=self.bot,
            bot_target_state=self,
            timestamp=position.timestamp,
            price_avg=position.price_avg,
            size=position.size,
        )
        pos_log.save()

    def log_order(self, order_result: BotOrderResult):
        order_log = BotOrderLog(
            bot=self.bot,
            bot_target_state=self,
            timestamp=order_result.timestamp,
            type=order_result.type,
            price_avg=order_result.price_avg,
            size=order_result.size
        )
        order_log.save()


class BotOrderLog(models.Model):
    TYPE_CHOICES = (
        ("MARKET", "market"),
    )
    bot = models.ForeignKey("Bot", on_delete=models.PROTECT)
    bot_target_state = models.ForeignKey(BotTargetState, on_delete=models.PROTECT)
    type = models.TextField(choices=TYPE_CHOICES, default='market')
    price_avg = models.FloatField(default=None)
    size = models.FloatField(default=None)
    timestamp = models.FloatField(default=-1)


class BotPositionLog(models.Model):
    bot = models.ForeignKey("Bot", on_delete=models.PROTECT)
    bot_target_state = models.ForeignKey(BotTargetState, on_delete=models.PROTECT, null=True, blank=True)
    price_avg = models.FloatField(default=None)
    size = models.FloatField(default=None)
    timestamp = models.FloatField(default=-1)


class BotPerformanceLog(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.PROTECT, null=True, blank=True)
    bot_signal = models.ForeignKey(BotSignal, on_delete=models.CASCADE, null=True, blank=True)
    balance = models.FloatField()
    exposure = models.FloatField()
    unrealized_pnl = models.FloatField()
    timestamp = models.FloatField()

    @classmethod
    def fetch_and_log(cls, bot_signal: BotSignal):
        ccxt_manager = CcxtBotExecutor(bot_signal.bot)
        bot_balance = ccxt_manager.get_balance()
        bot_position = ccxt_manager.get_position()

        balance = bot_balance.amount_all
        # unrealized_pnl = bot_balance.amount_all - bot_balance.amount_free
        unrealized_pnl = bot_position.pnl
        exposure = bot_position.price_avg * bot_position.size / balance

        log_entry = cls(
            bot=bot_signal.bot,
            bot_signal=bot_signal,
            balance=balance,
            unrealized_pnl=unrealized_pnl,
            exposure=exposure,
            timestamp=time.time()
        )

        log_entry.save()