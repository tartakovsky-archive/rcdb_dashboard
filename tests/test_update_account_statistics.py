import datetime
import pandas as pd
import pytest

from core.models import Bot
from core.services import update_account_statistics


use_db = pytest.mark.django_db


@use_db
def test_update_account_statistics_no_markets(bot: Bot):
    bot.exchange_credentials.meta = {}
    bot.exchange_credentials.save()

    update_account_statistics(None, bot.exchange_credentials)
    assert bot.exchange_credentials.statistics['updated']
    assert bot.exchange_credentials.statistics['h24_usd_volume'] is None
    assert bot.exchange_credentials.statistics['h24_trades_count'] is None


@use_db
def test_update_account_statistics(bot: Bot, mocker):
    class MockBinance:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_ticker(self, sym):
            v = 1.2 if 'BUSD' in sym else 1.
            return {'bid': v, 'ask': v}

    class DataStore:
        @staticmethod
        def read(type, query_params):
            return pd.DataFrame(
                [
                    {
                        'timestamp': datetime.datetime.utcnow(),
                        'symbol': query_params['symbol'],
                        'volume_buy': 3.5,
                        'volume_sell': 4.5,
                        'trades_count_buy': 1,
                        'trades_count_sell': 3,
                        'price_avg_buy': 60_000,
                        'price_avg_sell': 60_000
                    },
                    {
                        'timestamp': datetime.datetime.utcnow(),
                        'symbol': query_params['symbol'],
                        'volume_buy': 4.5,
                        'volume_sell': 3.5,
                        'trades_count_buy': 3,
                        'trades_count_sell': 1,
                        'price_avg_buy': 60_000,
                        'price_avg_sell': 60_000
                    }
                ]
            )

    bot.exchange_credentials.meta = {'markets': ['BTC/USDT', 'BTC/BUSD']}
    bot.exchange_credentials.save()

    mocker.patch('core.services.ccxt.binance', MockBinance)

    update_account_statistics(DataStore(), bot.exchange_credentials)

    assert bot.exchange_credentials.statistics['h24_trades_count'] == 16
    assert bot.exchange_credentials.statistics['h24_usd_volume'] == 2112000.0
    assert bot.exchange_credentials.statistics['updated']
