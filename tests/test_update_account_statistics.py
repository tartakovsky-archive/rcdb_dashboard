import datetime
import pandas as pd
import pytest

from core.models import Bot
from core.services import update_account_statistics, df_from_list, df_to_list


use_db = pytest.mark.django_db


TEST_DF = pd.DataFrame([
    dict(
        timestamp=datetime.datetime(2020, 2, 18, 12, 0),
        symbol='BTC/USDT',
        volume_buy_usd=100,
        volume_sell_usd=10.5,
        trades_count_buy=10,
        trades_count_sell=5
    ),
    dict(
        timestamp=datetime.datetime(2020, 4, 18, 12, 0),
        symbol='BTC/USDT',
        volume_buy_usd=100,
        volume_sell_usd=10.5,
        trades_count_buy=10,
        trades_count_sell=5
    ),
    dict(
        timestamp=datetime.datetime(2020, 4, 19, 12, 0),
        symbol='BTC/USDT',
        volume_buy_usd=100,
        volume_sell_usd=10.5,
        trades_count_buy=10,
        trades_count_sell=5
    ),
    dict(
        timestamp=datetime.datetime(2020, 4, 23, 12, 0),
        symbol='BTC/USDT',
        volume_buy_usd=101,
        volume_sell_usd=10.5,
        trades_count_buy=12,
        trades_count_sell=5
    ),
    dict(
        timestamp=datetime.datetime(2020, 4, 23, 12, 50),
        symbol='BTC/USDT',
        volume_buy_usd=102,
        volume_sell_usd=10.5,
        trades_count_buy=11,
        trades_count_sell=5
    )
])
ADDITIONAL_DF = pd.DataFrame([
    dict(
        timestamp=datetime.datetime(2020, 4, 23, 12, 59),
        symbol='BTC/USDT',
        volume_buy_usd=1,
        volume_sell_usd=0,
        trades_count_buy=1,
        trades_count_sell=0
    )
])


def test_df_from_to_list():
    data = df_to_list(TEST_DF)
    df = df_from_list(data)
    assert TEST_DF.equals(df)


@use_db
def test_update_account_statistics_no_markets(bot: Bot):
    bot.exchange_credentials.meta = {}
    bot.exchange_credentials.save()

    update_account_statistics(None, bot.exchange_credentials)
    assert bot.exchange_credentials.statistics['updated']
    assert bot.exchange_credentials.statistics['h24_usd_volume'] is None
    assert bot.exchange_credentials.statistics['h24_trades_count'] is None
    assert bot.exchange_credentials.statistics['d7_usd_volume'] is None
    assert bot.exchange_credentials.statistics['d7_trades_count'] is None
    assert len(bot.exchange_credentials.statistics['trades']) == 0


@pytest.fixture
def mocked_dt(mocker):
    mocked_utc = mocker.patch('core.services.datetime')

    class FakeDatetime(datetime.datetime):
        @classmethod
        def utcnow(cls):
            return datetime.datetime(2020, 4, 23, 13)

    mocked_utc.datetime = FakeDatetime
    mocked_utc.timedelta = datetime.timedelta
    yield


@use_db
@pytest.mark.parametrize(
    ('results, df, init_trades'),
    [
        (
            {
                'h24_usd_volume': 224,
                'h24_trades_count': 33,
                'd7_usd_volume': 334.5,
                'd7_trades_count': 48,
                'trades': df_to_list(TEST_DF)[1:]
            },
            TEST_DF,
            None
        ),
        (
            {
                'h24_usd_volume': 225,
                'h24_trades_count': 34,
                'd7_usd_volume': 335.5,
                'd7_trades_count': 49,
                'trades': df_to_list(TEST_DF)[1:] + df_to_list(ADDITIONAL_DF)
            },
            ADDITIONAL_DF,
            df_to_list(TEST_DF)
        )
    ]
)
def test_update_account_statistics(bot: Bot, mocker, mocked_dt, results, df, init_trades):
    bot.exchange_credentials.meta = {'markets': ['BTC/USDT']}
    if init_trades is not None:
        bot.exchange_credentials.statistics = {'trades': init_trades}
    bot.exchange_credentials.save()

    mocker.patch('core.services.get_trades_since', return_value=df)

    update_account_statistics(None, bot.exchange_credentials)

    assert bot.exchange_credentials.statistics['updated']
    assert bot.exchange_credentials.statistics['h24_usd_volume'] == results['h24_usd_volume']
    assert bot.exchange_credentials.statistics['h24_trades_count'] == results['h24_trades_count']
    assert bot.exchange_credentials.statistics['d7_usd_volume'] == results['d7_usd_volume']
    assert bot.exchange_credentials.statistics['d7_trades_count'] == results['d7_trades_count']

    assert bot.exchange_credentials.owner.h24_usd_volume == results['h24_usd_volume']
    assert bot.exchange_credentials.owner.h24_trades_count == results['h24_trades_count']
    assert bot.exchange_credentials.owner.d7_usd_volume == results['d7_usd_volume']
    assert bot.exchange_credentials.owner.d7_trades_count == results['d7_trades_count']

    assert tuple(results['trades']) == tuple(bot.exchange_credentials.statistics['trades'])
