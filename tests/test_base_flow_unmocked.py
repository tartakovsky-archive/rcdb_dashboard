import os
import io
import json
import shutil
import logging
from importlib import resources

import pytest
from django.conf import settings
from django.core.files import File
from sklearn.dummy import DummyClassifier
from django.core.management import call_command

from core.models import *
from core.libs.helpers.ccxt import CcxtBotExecutor

use_db = pytest.mark.django_db

logging.getLogger('numba').setLevel(logging.WARNING)

AMOUNT = 0.03
BASE_CURRENCY = 'ETH'
QUOTE_CURRENCY = 'USDT'


class Classifier(DummyClassifier):
    signal = None

    def predict_proba(self, X):
        return [[None, self.signal]]


def dump_model(signal):
    f = io.BytesIO()
    clf = Classifier()
    clf.signal = signal
    joblib.dump(clf, f)

    ml_config = BotMlConfig.objects.first()
    ml_config.file.save('model', File(f))
    ml_config.save()


@pytest.fixture
def market_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('MARKET_CACHE_DIR', str(tmp_path.resolve()))
    yield


EXCHANGE_CREDENTIALS = [
    p for p in
    [
        (os.environ.get('BITFINEX_KEY'), os.environ.get('BITFINEX_SECRET'), 'bitfinex'),
        (os.environ.get('BINANCE_KEY'), os.environ.get('BINANCE_SECRET'), 'binance')
    ]
    if all(p)
]


@pytest.fixture(params=EXCHANGE_CREDENTIALS, ids=list(map(lambda x: x[-1], EXCHANGE_CREDENTIALS)))
def init_db(tmp_path, monkeypatch, request):
    exchange_key, exchange_secret, exchange_name = request.param

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
        update_timestamp=time.time()
    )
    ticks_consolidator.save()

    percent_consolidator = Consolidator(
        parent=ticks_consolidator,
        instrument=instrument,
        type="PERCENT",  # PERCENT
        is_active=True,
        kwargs='{"bar_size": 0.0005}',
        update_timestamp=time.time(),
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

    if exchange_name == 'bitfinex':
        exchange_options = dict(orderTypes=dict(limit='limit', market='market'))
    else:
        exchange_options = dict(defaultType="future", defaultMarket="future")

    credentials = ExchangeCredentials(
        name="admin-rcdb-bitfinex",
        exchange=Exchange.objects.first(),
        init_kwargs=json.dumps(
            dict(
                apiKey=exchange_key,
                secret=exchange_secret,
                timeout=5000,
                enableRateLimit=True,
                options=exchange_options
                )
        )
    )
    credentials.save()

    with resources.open_text('tests.dataset', 'fn_tasks.json') as f:
        ml_config = BotMlConfig(name='Model', description='', fn_tasks=f.read())
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

    monkeypatch.setattr(settings, 'BARS_DIRECTORY', tmp_path.resolve())
    with resources.path('tests.dataset', 'bars.hdf') as path:
        shutil.copyfile(path, os.path.join(settings.BARS_DIRECTORY, f'{ticks_consolidator.id}.h5'))
        shutil.copyfile(path, os.path.join(settings.BARS_DIRECTORY, f'{percent_consolidator.id}.h5'))


@pytest.mark.skipif(
    not (os.environ.get('BITFINEX_KEY') and os.environ.get('BITFINEX_SECRET') or
            os.environ.get('BINANCE_KEY') and os.environ.get('BINANCE_SECRET')),
    reason='Exchange creds does not provide'
)
@use_db
def test(market_cache_dir, init_db):
    executor = CcxtBotExecutor(Bot.objects.first())
    logging.debug(f'BALANCE {executor.get_balance()} {executor.exchange_api.fetch_balance()["info"]}')
    logging.debug(f'TICKER {executor.get_ticker()}')
    logging.debug(f'POSTION {executor.get_position()}')

    ticker = executor.get_ticker()

    ask = ticker.ask

    Consolidator.objects.update(
        latest_bar_data=json.dumps(
            dict(timestamp=time.time(), open=ask, high=ask, low=ask, close=ask, volume=200)
        )
    )
    dump_model(0.7)
    call_command('run_bot', '--one-step')
    # BotSignal.push_signal(Bot.objects.first(), 0.7)
    entry_target: BotTargetState = BotTargetState.objects.first()
    assert entry_target.is_active
    call_command('execute_target', '--one-step')

    entry_order_log: BotOrderLog = BotOrderLog.objects.filter().first()
    assert time.time() - entry_order_log.timestamp < 10
    assert entry_order_log.type == 'market'
    assert entry_order_log.price_avg
    assert entry_order_log.size == AMOUNT

    dump_model(0.4)
    Consolidator.objects.update(update_timestamp=time.time())
    call_command('run_bot', '--one-step')
    # BotSignal.push_signal(Bot.objects.first(), 0.4)
    entry_target.refresh_from_db()
    assert not entry_target.is_active

    call_command('execute_target', '--one-step')

    exit_order_log: BotOrderLog = BotOrderLog.objects.exclude(id=entry_order_log.id).first()
    assert time.time() - exit_order_log.timestamp < 10
    assert exit_order_log.type == 'market'
    assert exit_order_log.price_avg
    assert exit_order_log.size == -AMOUNT
