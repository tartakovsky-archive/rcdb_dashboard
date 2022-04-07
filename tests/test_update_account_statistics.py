import datetime
import pandas as pd
import pytest
from rcdb_commons.lib.stores import DataType

from core.models import Bot, ExchangeCredentials
from core.services import update_account_statistics, df_from_list, df_to_list


use_db = pytest.mark.django_db


TEST_DF = pd.DataFrame([
    dict(
        timestamp=datetime.datetime(2021, 2, 18, 12, 0),
        symbol='BTC/USDT',
        volume_buy_usd=100,
        volume_sell_usd=10.5,
        volume_buy=200,
        volume_sell=21,
        price_avg_buy=2,
        price_avg_sell=2,
        trades_count_buy=10,
        trades_count_sell=5
    ),
    dict(
        timestamp=datetime.datetime(2021, 4, 18, 12, 0),
        symbol='BTC/USDT',
        volume_buy_usd=100,
        volume_sell_usd=10.5,
        volume_buy=200,
        volume_sell=21,
        price_avg_buy=2.,
        price_avg_sell=2.,
        trades_count_buy=10,
        trades_count_sell=5
    ),
    dict(
        timestamp=datetime.datetime(2021, 4, 19, 12, 0),
        symbol='BTC/USDT',
        volume_buy_usd=100,
        volume_sell_usd=10.5,
        volume_buy=200,
        volume_sell=21,
        price_avg_buy=2,
        price_avg_sell=2,
        trades_count_buy=10,
        trades_count_sell=5
    ),
    dict(
        timestamp=datetime.datetime(2021, 4, 23, 12, 0),
        symbol='BTC/USDT',
        volume_buy_usd=101,
        volume_sell_usd=10.5,
        volume_buy=200,
        volume_sell=21,
        price_avg_buy=2,
        price_avg_sell=2,
        trades_count_buy=12,
        trades_count_sell=5
    ),
    dict(
        timestamp=datetime.datetime(2021, 4, 23, 12, 50),
        symbol='BTC/USDT',
        volume_buy_usd=102,
        volume_sell_usd=10.5,
        volume_buy=200,
        volume_sell=21,
        price_avg_buy=2,
        price_avg_sell=2,
        trades_count_buy=11,
        trades_count_sell=5
    )
])
ADDITIONAL_DF = pd.DataFrame([
    dict(
        timestamp=datetime.datetime(2021, 4, 23, 12, 59),
        symbol='BTC/USDT',
        volume_buy_usd=1,
        volume_sell_usd=0,
        volume_buy=2,
        volume_sell=0,
        price_avg_buy=2,
        price_avg_sell=2,
        trades_count_buy=1,
        trades_count_sell=0
    )
])


def test_df_from_to_list():
    data = df_to_list(TEST_DF)
    df = df_from_list(data)
    assert TEST_DF.equals(df)


@use_db
def test_update_account_statistics_no_markets(bot: Bot, mocker):
    exchange_credentials = ExchangeCredentials.objects.first()
    exchange_credentials.meta = {}
    exchange_credentials.save()

    mocker.patch('core.services.DataStoreDataSynchronizer.get_updated_trades', return_value=pd.DataFrame([]))

    update_account_statistics(None, exchange_credentials)
    assert exchange_credentials.statistics['updated']
    assert exchange_credentials.statistics['h1_usd_volume'] is None
    assert exchange_credentials.statistics['h1_trades_count'] is None
    assert exchange_credentials.statistics['h24_usd_volume'] is None
    assert exchange_credentials.statistics['h24_trades_count'] is None
    assert exchange_credentials.statistics['d7_usd_volume'] is None
    assert exchange_credentials.statistics['d7_trades_count'] is None


@pytest.fixture
def mocked_dt(mocker):
    mocked_utc = mocker.patch('core.services.datetime')

    class FakeDatetime(datetime.datetime):
        @classmethod
        def utcnow(cls):
            return datetime.datetime(2021, 4, 23, 13)

    mocked_utc.datetime = FakeDatetime
    mocked_utc.timedelta = datetime.timedelta
    yield


@use_db
@pytest.mark.parametrize(
    ('results, df, init_trades'),
    [
        (
            {
                'h1_usd_volume': 112.5,
                'h1_trades_count': 16,
                'h24_usd_volume': 224,
                'h24_trades_count': 33,
                'd7_usd_volume': 334.5,
                'd7_trades_count': 48,
                'trades': df_to_list(TEST_DF)[1:]
            },
            TEST_DF.copy(),
            None
        ),
        (
            {
                'h1_usd_volume': 113.5,
                'h1_trades_count': 17,
                'h24_usd_volume': 225,
                'h24_trades_count': 34,
                'd7_usd_volume': 335.5,
                'd7_trades_count': 49,
                'trades': df_to_list(TEST_DF)[1:] + df_to_list(ADDITIONAL_DF)
            },
            ADDITIONAL_DF.copy(),
            df_to_list(TEST_DF)
        )
    ]
)
def test_update_account_statistics(bot: Bot, mocker, mocked_dt, results, df, init_trades):
    exchange_credentials = ExchangeCredentials.objects.first()
    exchange_credentials.meta = {'markets': ['BTC/USDT']}
    if init_trades is not None:
        exchange_credentials.get_trades = lambda *args: df_from_list(init_trades)
    else:
        exchange_credentials.get_trades = lambda *args: pd.DataFrame([])
    exchange_credentials.save()

    class DummyDatastore:
        ret = True

        @classmethod
        def read(cls, datatype, *args, **kwargs):
            if cls.ret and datatype is DataType.account_trades:
                cls.ret = not cls.ret
                return df
            return pd.DataFrame([])

    update_account_statistics(DummyDatastore(), exchange_credentials)

    assert exchange_credentials.statistics['updated']
    assert exchange_credentials.statistics['h1_usd_volume'] == results['h1_usd_volume']
    assert exchange_credentials.statistics['h1_trades_count'] == results['h1_trades_count']
    assert exchange_credentials.statistics['h24_usd_volume'] == results['h24_usd_volume']
    assert exchange_credentials.statistics['h24_trades_count'] == results['h24_trades_count']
    assert exchange_credentials.statistics['d7_usd_volume'] == results['d7_usd_volume']
    assert exchange_credentials.statistics['d7_trades_count'] == results['d7_trades_count']

    assert exchange_credentials.owner.totals['h1_usd_volume'] == results['h1_usd_volume']
    assert exchange_credentials.owner.totals['h24_usd_volume'] == results['h24_usd_volume']
    assert exchange_credentials.owner.totals['d7_usd_volume'] == results['d7_usd_volume']
