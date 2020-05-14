import time
import typing
import json
import math
import joblib
import pandas as pd

from django.db import models
from django.db import transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator

from core.libs.helpers.data_classes import *
from core.bot_mixin import BotCcxtMixin, NothingToExecuteException
from core.libs.helpers.data_classes import *
from core.libs.helpers.sizing import KellySizing, PercentSizing
from core.libs.helpers.risk import MaxDrawdownRiskManager
from core.libs.helpers.features import get_calc_features_fn

import logging

logging.basicConfig()
logging.getLogger().setLevel(settings.LOG_LEVEL)


class SaveLogMixin(models.Model):
    pass

    def save(self, *args, **kwargs):
        super(SaveLogMixin, self).save(*args, **kwargs)
        logging.info(f"{self._meta} // {self} // {self.pk}, {self.__dict__}")

    class Meta:
        abstract = True


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

    def __str__(self):
        return f"{self.base.slug}-{self.quote.slug}"

    def get_wrapper(self):
        return SymbolData(self.base.slug, self.quote.slug)

    def to_kaiko(self):
        return self.get_wrapper().to_kaiko()

    def to_binance(self):
        return self.get_wrapper().to_binance()

    def to_ccxt(self):
        return self.get_wrapper().to_ccxt()


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

    def get_kwargs_dict(self):
        return json.loads(self.init_kwargs)


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
        exposure, size = sizing_method(bot_signal)
        return exposure, round(size, bot_signal.bot.instrument.size_round_precision)

    ################################
    # Helper methods
    ################################

    def __get_kwargs(self):
        return json.loads(self.kwargs)

    def __get_sizing_method_by_type(self):
        method_name = f"__{self.get_type_display()}__"
        if hasattr(self, method_name):
            return getattr(self, method_name)

        raise Exception(f"Sizing type method `{self.type}` not exists.")

    @staticmethod
    def __get_market_info(bot):
        balance = bot.get_balance()
        ticker = bot.get_ticker()
        return balance, ticker

    ################################
    # Sizing methods
    ################################

    def __kelly__(self, bot_signal: "BotSignal"):
        # kwargs = dict(win_size: float, loss_size: float, divider: float = 1, direction=one_of("pos", "neg", "both"))
        kwargs = self.__get_kwargs()
        sizing = KellySizing(**kwargs)

        balance, ticker = self.__get_market_info(bot_signal.bot)

        # TODO: ticker price for limit order tupes should be swapped
        ticker_price = ticker.bid if bot_signal.signal > 0.5 else ticker.ask
        exposure = sizing.size(bot_signal.signal)
        return exposure, balance.amount_all * sizing.size(bot_signal.signal) / ticker_price

    # def __fixed__(self, bot_signal: "BotSignal"):
    #     kwargs = self.__get_kwargs()
    #     if bot_signal.signal > 0.5:
    #         signal = (bot_signal.signal - 0.5) * 2
    #     else:
    #         signal = (0.5 - (1 - bot_signal.signal)) * 2
    #
    #     balance, ticker = self.__get_market_info(bot_signal.bot)
    #
    #     if 'multiply_by_signal' in kwargs and kwargs['multiply_by_signal']:
    #         return kwargs['amount'] * signal
    #     else:
    #         return kwargs['amount'] * math.copysign(1, signal)

    # def __percent__(self, bot_signal: "BotSignal"):
    #     kwargs = self.__get_kwargs()
    #     sizing = PercentSizing(**kwargs)
    #     balance, ticker = self.__get_market_info(bot_signal.bot)
    #
    #     return sizing.size(bot_signal.signal)


class Risk(models.Model):
    TYPE_CHOICES = (
        ("MAX_DRAWDOWN", "max_drawdown"),
    )
    name = models.TextField(default="")
    type = models.TextField(choices=TYPE_CHOICES, default='fixed')
    kwargs = models.TextField(default="{}")

    def __str__(self):
        return self.name

    def __get_kwargs(self):
        return json.loads(self.kwargs)

    def __get_class(self):
        classes = dict(
            MAX_DRAWDOWN=MaxDrawdownRiskManager
        )
        return classes[self.type]

    def __get_risk_instance(self, bot: "Bot"):
        cls = self.__get_class()
        kwargs = self.__get_kwargs()
        return cls(bot, **kwargs)

    def get_risk_adjusted_target_size(self, target_state: "BotTargetState"):
        risk_obj = self.__get_risk_instance(target_state.bot)
        adjusted_exposure = risk_obj.get_risk_adjusted_exposure(target_state.instrument_target_exposure)
        return adjusted_exposure


class BotMlConfig(models.Model):
    name = models.TextField(max_length=100, unique=True)
    description = models.TextField()
    file = models.FileField(upload_to=f"{settings.MODELS_DIRECTORY}",
                            help_text="Model JobLib dump file")
    rows_count = models.IntegerField(default=-1,
                                  help_text="Minimal amount of rows to be fetched to calculate features")
    fn_tasks = models.TextField(help_text="JobManager fn_tasks JSON object")
    last_update_timestamp = models.IntegerField(default=0)

    def save(self, *args, **kwargs):
        self.last_update_timestamp = int(time.time())
        super().save(*args, **kwargs)

    # TODO: implement correct in-memory model caching (redis? need to research)
    cache = dict()

    def __get_from_cache__(self):
        # TODO: Remove. Added to review predictions without caching.
        self.cache = dict()

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


class BotSignal(SaveLogMixin, models.Model):
    bot = models.ForeignKey("Bot", on_delete=models.PROTECT)
    signal = models.FloatField(validators=[
        MinValueValidator(-1), MaxValueValidator(1)
    ])
    timestamp_consolidator = models.IntegerField()
    timestamp_real = models.IntegerField()
    is_active = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Disable latest active BotSignal
        BotSignal.objects.filter(bot=self.bot).update(is_active=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_active(cls, bot: "Bot"):
        try:
            return cls.objects.get(bot=bot, is_active=True)
        except cls.DoesNotExist:
            return None

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
        target_exposure, target_size = BotSizing.calc_size_for_signal(bot_signal)
        state_target_price = bot.data_feed.get_last_bar().close

        # Add new target state
        target_state = BotTargetState(
            bot=bot,
            bot_signal=bot_signal,
            instrument_target_size=target_size,
            instrument_target_exposure=target_exposure,
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


class BotTargetState(SaveLogMixin, models.Model):
    bot = models.ForeignKey("Bot", on_delete=models.PROTECT)
    bot_signal = models.ForeignKey("BotSignal", on_delete=models.PROTECT)

    # MaxValueValidator - max leverage in exchange prices
    # e.g. instrument_target=4 for BTCUSD means we should have 40k worth of BTC if we have 10k USD on exchange balance

    instrument_target_size = models.FloatField(default=0.0)
    instrument_target_exposure = models.FloatField(default=0.0, validators=[MinValueValidator(-3.5), MaxValueValidator(3.5)])
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

    def get_risk_adjusted_exposure(self):
        risk_adjusted_exposures = []
        for r in self.bot.risk_models.all():
            risk_adjusted_exposures.append(
                r.get_risk_adjusted_target_size(self))

        min_abs_exposure = risk_adjusted_exposures[0]
        for s in risk_adjusted_exposures:
            if abs(s) < abs(min_abs_exposure):
                min_abs_exposure = s

        return min_abs_exposure

    def exposure_to_size(self, exposure):
        balance = self.bot.get_balance()
        ticker = self.bot.get_ticker()

        # TODO: use bid ask instead of avg?
        ticker_price = ticker.price_avg
        size = balance.amount_all * exposure / ticker_price
        return round(size, self.bot.instrument.size_round_precision)

    # @transaction.atomic
    def execute(self):
        if self.is_active:
            exposure_risk_adjusted = self.get_risk_adjusted_exposure()
            size_risk_adjusted = self.exposure_to_size(exposure_risk_adjusted)

            order_result, bot_position, ex = self.bot.execute_desired_position(
                desired_base_size=size_risk_adjusted,
                desired_quote_price=self.instrument_target_execution_price,
                slippage_pct_position_increase=self.bot.slippage_pct_position_increase,
                slippage_pct_position_decrease=self.bot.slippage_pct_position_decrease,
                min_trade_amount=self.bot.min_trade_amount,
                max_trade_amount=self.bot.max_trade_amount,
                size_round_precision=self.bot.instrument.size_round_precision
            )

            if ex is not None:
                if isinstance(ex, NothingToExecuteException):
                    self.is_active = False

            if order_result is not None:
                self.log_order(order_result)

            if bot_position is not None:
                self.log_position(bot_position)

            self.save()

        return None

    def log_position(self, position: PositionData):
        pos_log = BotPositionLog(
            bot=self.bot,
            bot_target_state=self,
            timestamp=position.timestamp,
            price_avg=position.price_avg,
            size=position.size,
        )
        pos_log.save()

    def log_order(self, order_result: OrderResultData):
        order_log = BotOrderLog(
            bot=self.bot,
            bot_target_state=self,
            timestamp=order_result.timestamp,
            type=order_result.type,
            price_avg=order_result.price_avg,
            size=order_result.size
        )
        order_log.save()


class BotOrderLog(SaveLogMixin, models.Model):
    TYPE_CHOICES = (
        ("MARKET", "market"),
    )
    bot = models.ForeignKey("Bot", on_delete=models.PROTECT)
    bot_target_state = models.ForeignKey(BotTargetState, on_delete=models.PROTECT)
    type = models.TextField(choices=TYPE_CHOICES, default='market')
    price_avg = models.FloatField(default=None)
    size = models.FloatField(default=None)
    timestamp = models.FloatField(default=-1)


class BotPositionLog(SaveLogMixin, models.Model):
    bot = models.ForeignKey("Bot", on_delete=models.PROTECT)
    bot_target_state = models.ForeignKey(BotTargetState, on_delete=models.PROTECT, null=True, blank=True)
    price_avg = models.FloatField(default=None)
    size = models.FloatField(default=None)
    timestamp = models.FloatField(default=-1)


class BotPerformanceLog(SaveLogMixin, models.Model):
    bot = models.ForeignKey("Bot", on_delete=models.PROTECT, null=True, blank=True)
    bot_signal = models.ForeignKey(BotSignal, on_delete=models.CASCADE, null=True, blank=True)
    balance = models.FloatField()
    exposure = models.FloatField()
    unrealized_pnl = models.FloatField()
    timestamp = models.FloatField()

    @classmethod
    def fetch_and_log(cls, bot_signal: BotSignal):
        bot = bot_signal.bot

        bot_balance = bot.get_balance()
        bot_position = bot.get_position()

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


#
# Bot
#


class BotDataMixin(BotCcxtMixin):
    def get_performance(self) -> pd.DataFrame:
        logs = BotPerformanceLog.objects.filter(bot=self.id).order_by('id').prefetch_related('bot_signal')
        results = []

        for item in logs:
            results.append(dict(
                signal=item.bot_signal.signal,
                balance=item.balance,
                unrealized_pnl=item.unrealized_pnl,
                exposure=item.exposure,
                timestamp=int(item.timestamp)
            ))
        df = pd.DataFrame(results)
        df['equity'] = df['balance'] + df['unrealized_pnl']
        return df

    # def get_target_exposure(self, target_state=None) -> float:
    #     """
    #     Calculate desired exposure using target_state's size and price
    #                          and exchange `amount_all` (all available balance)
    #
    #     :param target_state: if None, then latest active target_state will be used
    #     :return: float
    #     """
    #     if target_state is None:
    #         target_state = BotTargetState.objects.get(is_active=True)
    #
    #     target_position_value = target_state.instrument_target_size * target_state.instrument_target_execution_price
    #     balance = target_state.bot.get_balance()
    #     return target_position_value / balance.amount_all

    def execute_desired_position(
            self,
            desired_base_size: float,
            desired_quote_price: float,
            slippage_pct_position_increase: float,
            slippage_pct_position_decrease: float,
            min_trade_amount: float,
            max_trade_amount: float,
            size_round_precision: int = 9
    ) -> (OrderResultData, PositionData, Exception):

        instrument_target_size = desired_base_size
        instrument_target_execution_price = desired_quote_price

        # return order_result or None
        order_results_response = None

        # indicates whether trade is allowed
        is_trade_allowed = False

        # calculated order size with min/max trade and slippage adjustments made
        order_size = 0

        bot_position = self.get_position()
        # bot_target.log_position(bot_position)

        if abs(bot_position.size - instrument_target_size) < min_trade_amount:
            return None, bot_position, NothingToExecuteException(
                "Desired position change is less then min_trade_amount (Position has benn reached already)")
        else:
            # is_position_side_changed is True if long changed to short or vice versa
            is_position_side_changed = instrument_target_size * bot_position.size > 0
            if is_position_side_changed or bot_position.size == 0:
                # only size is changed (position is the same)
                is_position_increase = abs(instrument_target_size) > abs(bot_position.size)
            else:
                # if position side changes
                # then position always decreasing, but there is a trick
                # when position crosses 0 (e.g. -0.1 -> 0.1 -> 0.5) it starts increasing
                is_position_increase = False

            # calculate order size
            order_size = round(instrument_target_size - bot_position.size,
                               size_round_precision)
            if abs(order_size) > max_trade_amount:
                # limit order size to bot max allowed trade size
                order_size = math.copysign(max_trade_amount, order_size)

            bot_ticker = self.get_ticker()

            is_trade_allowed = False
            is_long = order_size > 0

            # allowed slippage_pct is different when increasing and decreasing positions
            slippage_pct__allowed = slippage_pct_position_increase
            if not is_position_increase:
                slippage_pct__allowed = slippage_pct_position_decrease

            if is_long:
                # calculate current slippage between live price and state's target price
                price_pct_change_since_bar_open = bot_ticker.ask / instrument_target_execution_price - 1

                # negative slippage when price goes up
                if price_pct_change_since_bar_open <= slippage_pct__allowed:
                    # trading is allowed if current slippage is lower then allowed
                    is_trade_allowed = True
                else:
                    # current slippage if bigger then allowed, log information and do nothing
                    max_price = instrument_target_execution_price + \
                                instrument_target_execution_price * slippage_pct__allowed

                    logging.debug(f"[Long] Instrument price {bot_ticker.ask} is higher then "
                                  f"target price {instrument_target_execution_price} "
                                  f"(with slippage {slippage_pct__allowed}% == {max_price})")
            else:
                # calculate current slippage between live price and state's target price
                price_pct_change_since_bar_open = bot_ticker.bid / instrument_target_execution_price - 1

                # multiply slippage by -1 for shorts (negative slippage when price goes down)
                if -1 * price_pct_change_since_bar_open <= slippage_pct__allowed:
                    # trading is allowed if current slippage is lower then allowed
                    is_trade_allowed = True
                else:
                    # current slippage if bigger then allowed, log information and do nothing
                    min_price = instrument_target_execution_price - \
                                instrument_target_execution_price * slippage_pct__allowed

                    logging.debug(f"[Short] Instrument price {bot_ticker.ask} is lower then "
                                  f"target price {instrument_target_execution_price} "
                                  f"(with slippage {slippage_pct__allowed}% == {min_price})")

        if is_trade_allowed:
            # create order if trade allowed and log results
            order_result = self.create_order(order_size)
            order_results_response = order_result
            # if trade has been made we should refresh position info
            bot_position = self.get_position()

        return order_results_response, bot_position, None


class Bot(BotDataMixin, models.Model):
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

    risk_models = models.ManyToManyField(Risk, blank=True, null=True)

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

    @property
    def exchange_slug(self):
        return self.exchange_credentials.exchange.slug

    @property
    def exchange_credentials_dict(self):
        return self.exchange_credentials.get_kwargs_dict()

    @property
    def symbol(self):
        return self.instrument.symbol.get_wrapper()

    def datafeed_has_new_data_to_predict(self):
        data_feed = self.data_feed
        while True:
            if data_feed.parent is not None:
                data_feed = data_feed.parent
            else:
                break

        can_predict = time.time() - data_feed.update_timestamp < data_feed.get_kwargs()['time_frame_seconds'] * 2
        has_new_data = self.data_feed.update_timestamp > self.predict_timestamp

        # print(time.time() - data_feed.update_timestamp, data_feed.get_kwargs()['time_frame_seconds'],
        #       data_feed.get_kwargs()['time_frame_seconds'] * 2)
        # print(f"can_predict: {can_predict}, has_new_data: {has_new_data}")

        return can_predict and has_new_data

    def get_feed_dataframe(self, rows_count=None) -> pd.DataFrame:
        if rows_count == -1:
            rows_count = None

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
            bars = self.get_feed_dataframe(rows_count=self.ml_config.rows_count)
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