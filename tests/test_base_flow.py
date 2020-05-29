import re
import os
import json
import shutil
import logging
from pathlib import Path
from importlib import resources

import pytest
import numpy as np
import pandas as pd
from requests_mock import Mocker
from django.conf import settings
from django.core.files import File
from django.core.management import call_command

from core.models import *
from .utils import assert_dfs

use_db = pytest.mark.django_db

logging.getLogger('numba').setLevel(logging.WARNING)


TEST_CONSOLIDATED_TICKS = pd.DataFrame(
    dict(
        open=[100, 120, 160],
        high=[120, 160, 200],
        low=[110, 130, 180],
        close=[120, 160, 180],
        volume=[5.15, 22.30, 61.68]
    ),
    index=[1389303960, 1389304020, 1389304080]
)
TEST_CONSOLIDATED_PERCENTS = pd.DataFrame(
    dict(
        open=[100, 160],
        high=[120, 200],
        low=[110, 180],
        close=[160, 180],
        volume=[27.45, 61.68],
        f=[0, 1]
    ),
    index=[1389303960, 1389304080]
)


class MockedCcxtApi:
    created = False
    markets = {}

    def __init__(self, *args, **kwargs):
        MockedCcxtApi.created = True

    def fetch_balance(self):
        return {
            'info': [
                {'type': 'trading', 'currency': 'USD', 'amount': 100, 'available': 100}
            ]
        }

    def fetch_ticker(self, *args, **kwargs):
        return {
            'timestamp': int(TEST_CONSOLIDATED_PERCENTS.index.values[-1] * 1000),
            'ask': TEST_CONSOLIDATED_PERCENTS.iloc[-1].close,
            'bid': TEST_CONSOLIDATED_PERCENTS.iloc[-1].close,
            'average': TEST_CONSOLIDATED_PERCENTS.iloc[-1].close
        }

    def create_order(self, *args, **kwargs):
        return {'info': {'id': 21}}

    def load_markets(self):
        pass

    @staticmethod
    def private_post_positions():
        pass

    @staticmethod
    def private_post_order_status(self, params):
        pass


@pytest.fixture
def market_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('MARKET_CACHE_DIR', str(tmp_path.resolve()))
    yield


@use_db
def test_consolidate_ticks(requests_mock: Mocker, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'BARS_DIRECTORY', tmp_path.resolve())

    base_currency = Currency(name='BTC', slug='BTC')
    quote_currency = Currency(name='USD', slug='USD')
    exchange = Exchange(name='bitfinex', slug='bitfinex', exchange_email='test@mail.com')

    base_currency.save()
    quote_currency.save()
    exchange.save()

    symbol = Symbol(base=base_currency, quote=quote_currency)
    symbol.save()

    instrument = Instrument(
        exchange=exchange,
        symbol=symbol
    )
    instrument.save()

    consolidator = Consolidator(
        kwargs='{"time_frame_seconds": 60}',
        is_active=True,
        instrument=instrument
    )
    consolidator.save()
    with resources.open_text('tests.dataset', 'ticks.json') as file:
        ticks = json.load(file)
    requests_mock.get(re.compile('market-api.kaiko.io'), json={'data': ticks, 'result': ticks})

    call_command('consolidate_ticks', '--one-step')

    consolidator.refresh_from_db()

    df_path = tmp_path / f'{consolidator.id}.h5'
    assert df_path.exists()

    df: pd.DataFrame = pd.read_hdf(df_path, key='table')

    assert_dfs(TEST_CONSOLIDATED_TICKS, df)


@use_db
def test_consolidate_custom(requests_mock: Mocker, tmp_path: Path, monkeypatch):
    test_consolidate_ticks(requests_mock, tmp_path, monkeypatch)
    parent_consolidator: Consolidator = Consolidator.objects.first()

    consolidator = Consolidator(
        parent=parent_consolidator,
        instrument=parent_consolidator.instrument,
        type="PERCENT", # PERCENT
        is_active=True,
        kwargs='{ "bar_size": 0.0005 }'
    )
    consolidator.save()

    call_command('consolidate_custom', '--one-step')

    df_path = tmp_path / f'{consolidator.id}.h5'
    assert df_path.exists()

    df: pd.DataFrame = pd.read_hdf(df_path, key='table')

    assert_dfs(TEST_CONSOLIDATED_PERCENTS, df)


@use_db
def test_run_bot(requests_mock: Mocker, tmp_path: Path, monkeypatch, mocker, market_cache_dir):
    test_consolidate_custom(requests_mock, tmp_path, monkeypatch)
    monkeypatch.setattr(settings, 'MODELS_DIRECTORY', tmp_path.resolve())

    consolidator = Consolidator.objects.filter(type="PERCENT").first()

    bot_sizing = BotSizing(
        name='Fixed 0.00082 for testing',
        type="FIXED",
        kwargs= '{"amount": 0.00082, "multiply_by_signal": false}',
        is_short_allowed=True,
        is_long_allowed=True
    )
    bot_sizing.save()

    credentials = ExchangeCredentials(
        name="admin-rcdb-bitfinex",
        exchange=Exchange.objects.first(),
        init_kwargs='''
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
        '''
    )
    credentials.save()

    with resources.open_text('tests.dataset', 'fn_tasks.json') as f:
        ml_config = BotMlConfig(
            name='Model',
            description='',
            fn_tasks=f.read()
        )

        with resources.open_binary('tests.dataset', 'model.joblib') as f:
            ml_config.file.save('model', File(f))

        ml_config.save()

    with resources.path('tests.dataset', 'bars.hdf') as path:
        shutil.copyfile(path, os.path.join(settings.BARS_DIRECTORY, f'{consolidator.id}.h5'))

    bot = Bot(
        name="Bot 1 // 0.05%",
        exchange_credentials=credentials,
        instrument=consolidator.instrument,
        data_feed=consolidator,
        sizing=bot_sizing,
        is_active=True,
        min_trade_amount=0.00082,
        max_trade_amount=0.00082,
        slippage_pct_position_increase=0.001,
        slippage_pct_position_decrease=0.1,
        ml_config=ml_config
    )
    bot.save()

    mocker.patch('core.models.time.time', lambda: 0)

    MockedCcxtApi.private_post_positions = lambda *args, **kwargs: []
    mocker.patch('ccxt.bitfinex', MockedCcxtApi)

    call_command('run_bot', '--one-step')
    assert BotPerformanceLog.objects.count() == 1
    assert BotSignal.objects.count() == 1

    signal: BotSignal = BotSignal.objects.first()
    assert signal.signal > 0.5
    assert signal.bot == bot
    assert signal.timestamp_consolidator == 1389304080
    assert signal.timestamp_real == 0
    assert signal.is_active

    log: BotPerformanceLog = BotPerformanceLog.objects.first()
    assert log.bot == bot
    assert log.bot_signal == signal
    assert log.balance == 100
    assert log.exposure == 0
    assert log.unrealized_pnl == 0
    assert log.timestamp == 0

    assert BotTargetState.objects.count() == 1

    target_state: BotTargetState = BotTargetState.objects.first()
    assert target_state.bot == bot
    assert target_state.bot_signal == signal
    assert target_state.instrument_target_size == 0.00082
    assert target_state.instrument_target_execution_price == 180.
    assert target_state.is_active

    latest_bar = TEST_CONSOLIDATED_PERCENTS.iloc[-1].to_dict()
    del latest_bar['f']
    latest_bar = {**latest_bar, 'timestamp': TEST_CONSOLIDATED_TICKS.index.values[-1]}
    test_data_feed_info = {'data_feed__last_bar': latest_bar, 'data_feed_parent__last_bar': latest_bar}
    assert json.loads(target_state.data_feed_info) == test_data_feed_info


@use_db
def test_execute_target_entry_position(requests_mock: Mocker, tmp_path: Path, monkeypatch, mocker, market_cache_dir):
    test_run_bot(requests_mock, tmp_path, monkeypatch, mocker, market_cache_dir)

    MockedCcxtApi.private_post_positions = lambda *args, **kwargs: []
    MockedCcxtApi.private_post_order_status = lambda self, params: {
        'timestamp': time.time(),
        'executed_amount': 0.00082,
        'side': 'buy',
        'avg_execution_price': 180.
    }
    mocker.patch('ccxt.bitfinex', MockedCcxtApi)

    call_command('execute_target', '--one-step')

    assert BotOrderLog.objects.count() == 1

    order_log: BotOrderLog = BotOrderLog.objects.first()
    assert order_log.bot == Bot.objects.first()
    assert order_log.bot_target_state == BotTargetState.objects.first()
    assert order_log.timestamp == 0
    assert order_log.type == 'market'
    assert order_log.price_avg == 180.
    assert order_log.size == 0.00082

    assert BotTargetState.objects.first().is_active

    MockedCcxtApi.private_post_positions = lambda *args, **kwargs: [
        {
            'symbol': 'btcusd',
            'base': '180',
            'amount': 0.00082,
            'timestamp': time.time(),
            'pl': 1
        }
    ]
    call_command('execute_target', '--one-step')
    assert not BotTargetState.objects.first().is_active


@use_db
def test_execute_target_exit_position(requests_mock: Mocker, tmp_path: Path, monkeypatch, mocker, market_cache_dir):
    test_execute_target_entry_position(requests_mock, tmp_path, monkeypatch, mocker, market_cache_dir)
    BotSignal.push_signal(Bot.objects.first(), 0.4)

    assert BotTargetState.objects.filter(is_active=True).count() == 1
    target_state: BotTargetState = BotTargetState.objects.filter(is_active=True).first()
    assert target_state.instrument_target_size == -0.00082
    assert target_state.instrument_target_execution_price == 180.

    MockedCcxtApi.private_post_order_status = lambda self, params: {
        'timestamp': time.time(),
        'executed_amount': 0.00082,
        'side': 'sell',
        'avg_execution_price': 180.
    }
    MockedCcxtApi.private_post_positions = lambda *args, **kwargs: [
        {
            'symbol': 'btcusd',
            'base': '180',
            'amount': 0.00082,
            'timestamp': time.time(),
            'pl': 1
        }
    ]

    call_command('execute_target', '--one-step')

    order_log: BotOrderLog = BotOrderLog.objects.filter(bot_target_state=target_state).first()
    assert order_log.bot == Bot.objects.first()
    assert order_log.timestamp == 0
    assert order_log.type == 'market'
    assert order_log.price_avg == 180.
    assert order_log.size == -0.00082

    target_state.refresh_from_db()
    assert target_state.is_active

    MockedCcxtApi.private_post_positions = lambda *args, **kwargs: [
        {
            'symbol': 'btcusd',
            'base': '180',
            'amount': -0.0001,
            'timestamp': time.time(),
            'pl': 1
        }
    ]
    call_command('execute_target', '--one-step')

    target_state.refresh_from_db()
    assert not target_state.is_active
