import os
import time
import uuid
import copy
import json
import shutil
from importlib import resources
from types import SimpleNamespace
from dataclasses import dataclass, field

import pytest
import numpy as np
import pandas as pd
from joblib import load
from django.conf import settings
from django.core.files import File
from django.core.management import call_command
from rcdb_libs.bars import percent
from rcdb_libs.job_manager import JobManager
from rcdb_research.simulation_bt import get_trading_simulation
from rcdb_research.simulation import Bitfinex, KellySizing, Costs, NoFeex

from core.models import *
from core.libs.helpers.sizing import KellySizing
from .utils import assert_dfs

AMOUNT = 0.03
BASE_CURRENCY = 'ETH'
QUOTE_CURRENCY = 'USDT'
BALANCE = 1000000.
BAR_SIZE = 0.0005

use_db = pytest.mark.django_db

logging.basicConfig(level=logging.WARNING)
logging.getLogger('matplotlib').setLevel(logging.WARNING)
logging.getLogger('numba').setLevel(logging.WARNING)


@pytest.fixture
def market_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('MARKET_CACHE_DIR', str(tmp_path.resolve()))
    yield


class MockedCcxtApi:
    created = False
    markets = {}
    _orders = {}
    balance = BALANCE
    prev_balance = BALANCE
    prices = []

    price = None

    def __init__(self, *args, **kwargs):
        MockedCcxtApi.created = True

    @classmethod
    def fetch_balance(cls):
        return {
            'info': [
                {'type': 'trading', 'currency': QUOTE_CURRENCY, 'amount': cls.balance, 'available': cls.balance}
            ]
        }

    @staticmethod
    def private_post_positions():
        return []

    @staticmethod
    def load_markets():
        pass

    @staticmethod
    def fetch_ticker():
        pass

    @classmethod
    def create_order(cls, side, amount, *args, **kwargs):
        id = uuid.uuid4().hex
        t = time.time()

        cls.prev_balance = cls.balance
        cls.balance += (-1 if side == 'buy' else 1) * amount * cls.price
        cls.prices.append(cls.price)
        cls._orders[id] = dict(side=side, amount=amount, price=cls.price, timestamp=t)
        return dict(info=dict(id=id))

    @classmethod
    def private_post_order_status(cls, params):
        order = cls._orders[params['order_id']]
        return dict(
            timestamp=order['timestamp'],
            executed_amount=order['amount'],
            side=order['side'],
            avg_execution_price=order['amount']
        )


@pytest.fixture
def init_db(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr(settings, 'BARS_DIRECTORY', tmp_path.resolve())
    monkeypatch.setattr(settings, 'DATA_DIRECTORY', tmp_path.resolve())
    monkeypatch.setattr(settings, 'MODELS_DIRECTORY', tmp_path.resolve())
    mocker.patch('core.models.time.time', lambda: 0)
    mocker.patch('core.models.time.sleep', lambda: 0)
    mocker.patch('core.libs.helpers.ccxt.time.sleep', lambda: 0)
    mocker.patch('time.sleep', lambda: 0)
    mocker.patch('ccxt.bitfinex', MockedCcxtApi)
    mocker.patch('logging.debug', lambda x: None)
    mocker.patch('logging.info', lambda x: None)

    exchange_name = 'bitfinex'
    base_currency = Currency(name=BASE_CURRENCY, slug=BASE_CURRENCY)
    quote_currency = Currency(name=QUOTE_CURRENCY, slug=QUOTE_CURRENCY)
    exchange = Exchange(name=exchange_name, slug=exchange_name, exchange_email='test@mail.com')

    base_currency.save()
    quote_currency.save()
    exchange.save()

    symbol = Symbol(base=base_currency, quote=quote_currency)
    symbol.save()

    instrument = Instrument(exchange=exchange, symbol=symbol)
    instrument.save()

    ticks_consolidator = Consolidator(
        kwargs='{"time_frame_seconds": 60}',
        is_active=True,
        instrument=instrument,
    )
    ticks_consolidator.save()

    percent_consolidator = Consolidator(
        parent=ticks_consolidator,
        instrument=instrument,
        type="PERCENT",  # PERCENT
        is_active=True,
        kwargs=json.dumps(dict(bar_size=BAR_SIZE)),
    )
    percent_consolidator.save()

    bot_sizing = BotSizing(
        name='Kelly',
        type="KELLY",
        kwargs=json.dumps(
            dict(
                win_size=0.014,
                loss_size=0.022,
                divider=10,
                direction='both'
            )
        ),
        is_short_allowed=False,
        is_long_allowed=True
    )
    bot_sizing.save()

    credentials = ExchangeCredentials(
        name="admin-rcdb-binance",
        exchange=Exchange.objects.first(),
        init_kwargs=json.dumps(
            dict(
                apiKey='super secret',
                secret='super super secret',
                timeout=5000,
                enableRateLimit=True,
                options=dict(defaultType="future", defaultMarket="future")
                )
        )
    )
    credentials.save()

    with resources.open_binary('tests.dataset', 'model.joblib') as model_f,\
            resources.open_text('tests.dataset', 'fn_tasks.json') as f:
        ml_config = BotMlConfig(name='Model', description='', fn_tasks=f.read())
        ml_config.file.save('model', File(model_f))
        ml_config.save()

    bot = Bot(
        name="Bot 1 // 0.05%",
        exchange_credentials=credentials,
        instrument=instrument,
        data_feed=percent_consolidator,
        sizing=bot_sizing,
        is_active=True,
        min_trade_amount=AMOUNT,
        max_trade_amount=AMOUNT,
        slippage_pct_position_increase=0.001,
        slippage_pct_position_decrease=0.1,
        ml_config=ml_config
    )
    bot.save()
    yield


@dataclass
class MLPipeline:
    model: object
    fn_tasks: list
    threshold: float
    initial_bars: pd.DataFrame
    sizing: KellySizing
    ticker: object = None
    ticker_value: float = None
    probas: list = field(default_factory=list)
    sizes: list = field(default_factory=list)
    exposure: list = field(default_factory=list)
    latest_bars: pd.DataFrame = None
    sim_data: pd.DataFrame = field(default_factory=lambda: pd.DataFrame([]))
    first_change: bool = True

    def on_bar(self, bar: pd.Series):
        self.initial_bars = self.initial_bars.append(bar)
        if not self.build_percent_bars(self.initial_bars.copy()):
            return

        bars = self.latest_bars.tail(102)[:-1]
        X = self.prepare_bars_for_predict(bars)

        proba = self.predict_proba(X)
        self.probas.append(proba)

        size = self.get_size(proba)
        self.sizes.append(size)

        sim_data = self.latest_bars.tail(1)
        sim_data.index = pd.to_datetime(sim_data.index, unit='ms')
        sim_data['signal'] = sim_data['proba'] = proba
        self.sim_data = self.sim_data.append(sim_data)

    def prepare_bars_for_predict(self, bars):
        bars['timestamp'] = bars.index / 1000
        bars['direction'] = np.where(bars.open < bars.close, 1, np.where(bars.open > bars.close, -1, 0))
        jm = JobManager(bars, fn_tasks=copy.deepcopy(self.fn_tasks), n_jobs=1)
        job_results = jm.run_job()
        results = job_results.get_pandas()

        results['target'] = np.where(bars['direction'].shift(-1).fillna(0) == 1, 1, 0)

        results = results.replace([np.inf, -np.inf], 0)
        return results.tail(1).drop('target', axis=1)

    def predict_proba(self, X):
        return self.model.predict_proba(X)[0][1]

    def build_percent_bars(self, bars_minutes: pd.DataFrame):
        bars: pd.DataFrame = percent(bars_minutes, self.threshold)
        bars.index = bars.index.astype(int)

        has_new = self.latest_bars is None or bars.index.values[-1] > self.latest_bars.index.values[-1]
        self.latest_bars = bars

        return has_new

    def get_ticker_value(self):
        return self.ticker_value

    def get_size(self, signal):
        ticker_price = self.ticker.bid if signal > 0.5 else self.ticker.ask
        self.ticker_value = ticker_price
        balance = MockedCcxtApi.prev_balance
        # if MockedCcxtApi.balance != BALANCE:
        #     balance = MockedCcxtApi.balance
        #     if self.first_change:
        #         balance = BALANCE
        #         self.first_change = False

        exposure = self.sizing.size(signal)
        self.exposure.append(exposure)
        return balance * exposure / ticker_price

    def simulate(self):
        exchange = NoFeex()
        # exchange = Bitfinex(costs=Costs(
        #     taker_fee=-0.155 / 100,
        #     maker_fee=-0.2 / 100,
        #     drift=-0.0 / 100,
        #     impact=-0.1 / 100,
        # ))
        print(self.sim_data.shape)
        print(MockedCcxtApi.prices)
        trades, df_sim = get_trading_simulation(
            df_data=self.sim_data,
            sizing=self.sizing,
            exchange=exchange,
            use_worst_pnl=False
        )
        return trades, df_sim


@pytest.fixture
def minutes():
    with resources.path('tests.dataset', 'bars.hdf') as path:
        df: pd.DataFrame = pd.read_hdf(path, 'table')
        df.index = df.index * 1000
        df['volume'] = df.volume_sell + df.volume_buy

        return df[['open', 'high', 'low', 'close', 'volume']]


@use_db
def test(init_db, minutes):
    df = minutes
    ticks_consolidator = Consolidator.objects.get(parent__isnull=True)
    percent_consolidator = Consolidator.objects.get(parent__isnull=False)

    ticks_bars_path = os.path.join(settings.BARS_DIRECTORY, f'{ticks_consolidator.id}.h5')
    percent_bars_path = os.path.join(settings.BARS_DIRECTORY, f'{percent_consolidator.id}.h5')

    initial = 500
    from_, to = initial + 1, initial + 20

    bot: Bot = Bot.objects.first()

    ml_pipeline = MLPipeline(
        sizing=KellySizing(**json.loads(bot.sizing.kwargs)),
        model=bot.ml_config.get_model(),
        fn_tasks=bot.ml_config.get_fn_tasks(),
        threshold=BAR_SIZE,
        initial_bars=df[:initial]
    )

    ticker = df.close.values[from_]
    for i in range(from_, to):
        minute_bar = df.iloc[i, :]

        MockedCcxtApi.price = minute_bar.close
        MockedCcxtApi.fetch_ticker = lambda *args: dict(
            timestamp=int(df.index.values[i]),
            ask=ticker,
            bid=ticker,
            average=minute_bar.close
        )

        ml_pipeline.ticker = SimpleNamespace(ask=ticker, bid=ticker)
        ml_pipeline.on_bar(minute_bar)

        if os.path.exists(ticks_bars_path):
            os.remove(ticks_bars_path)

        df[:i + 1].to_hdf(ticks_bars_path, key='table')

        ticks_consolidator.latest_bar_data = json.dumps(
            {'timestamp': int(df.index.values[i]), **minute_bar.to_dict()})
        ticks_consolidator.update_timestamp = df.index.values[i]
        ticks_consolidator.save()

        call_command('consolidate_custom', '--one-step')
        call_command('run_bot', '--one-step')
        call_command('execute_target', '--one-step')

    assert ml_pipeline.probas and tuple(ml_pipeline.probas) == tuple(
        BotSignal.objects.values_list('signal', flat=True)), 'probas'
    assert ml_pipeline.sizes and tuple(map(lambda v: round(v, 9), ml_pipeline.sizes)) == tuple(
        BotTargetState.objects.values_list('instrument_target_size', flat=True)), 'sizing'

    trades, df_sim = ml_pipeline.simulate()
    assert np.array_equal(df_sim.exposure_desired, ml_pipeline.exposure)
