import os
import copy
import json
import shutil
from importlib import resources
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

from core.models import *
from .utils import assert_dfs

AMOUNT = 0.03
BASE_CURRENCY = 'ETH'
QUOTE_CURRENCY = 'USDT'

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

    def __init__(self, *args, **kwargs):
        MockedCcxtApi.created = True

    def fetch_balance(self):
        return {
            'info': [
                {'type': 'trading', 'currency': 'USDT', 'amount': 100, 'available': 100}
            ]
        }

    @staticmethod
    def private_post_positions():
        return []


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
        name=f'Fixed {AMOUNT} for testing',
        type="FIXED",
        kwargs=json.dumps(dict(amount=AMOUNT, multiply_by_signal=False)),
        is_short_allowed=True,
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


    # with resources.path('tests.dataset', 'bars.hdf') as path:
        # shutil.copyfile(path, os.path.join(settings.BARS_DIRECTORY, f'{ticks_consolidator.id}.h5'))
        # shutil.copyfile(path, os.path.join(settings.BARS_DIRECTORY, f'{percent_consolidator.id}.h5'))

    yield



@dataclass
class MLPipeline:
    model: object
    fn_tasks: list
    threshold: float
    initial_bars: pd.DataFrame
    latest_bars: pd.DataFrame = None
    probas: list = field(default_factory=list)

    def on_bar(self, bar: pd.Series):
        self.initial_bars = self.initial_bars.append(bar)
        if not self.build_percent_bars(self.initial_bars.copy()):
            return

        bars = self.latest_bars.tail(102)[:-1]
        X = self.prepare_bars_for_predict(bars)

        proba = self.predict_proba(X)
        self.probas.append(proba)

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


@pytest.fixture
def minutes():
    with resources.path('tests.dataset', 'bars.hdf') as path:
        df: pd.DataFrame = pd.read_hdf(path, 'table')
        df.index = df.index * 1000
        df['volume'] = df.volume_sell + df.volume_buy

        return df[['open', 'high', 'low', 'close', 'volume']]


@use_db
def test_compare_consolidation(init_db, minutes):
    df = minutes
    ticks_consolidator = Consolidator.objects.get(parent__isnull=True)
    percent_consolidator = Consolidator.objects.get(parent__isnull=False)

    ticks_bars_path = os.path.join(settings.BARS_DIRECTORY, f'{ticks_consolidator.id}.h5')
    percent_bars_path = os.path.join(settings.BARS_DIRECTORY, f'{percent_consolidator.id}.h5')

    initial = 500
    from_, to = initial + 1, initial + 20

    bot: Bot = Bot.objects.first()

    ml_pipeline = MLPipeline(
        model=bot.ml_config.get_model(),
        fn_tasks=bot.ml_config.get_fn_tasks(),
        threshold=0.0005,
        initial_bars=df[:initial]
    )

    for i in range(from_, to):
        ml_pipeline.on_bar(df.iloc[i, :])

        if os.path.exists(ticks_bars_path):
            os.remove(ticks_bars_path)

        df[:i + 1].to_hdf(ticks_bars_path, key='table')

        ticks_consolidator.latest_bar_data = json.dumps(
            {'timestamp': int(df.index.values[i]), **df.iloc[i, :].to_dict()})
        ticks_consolidator.update_timestamp = df.index.values[i]
        ticks_consolidator.save()

        call_command('consolidate_custom', '--one-step')
        call_command('run_bot', '--one-step')


    assert ml_pipeline.probas and tuple(ml_pipeline.probas) == tuple(BotSignal.objects.values_list('signal', flat=True))
