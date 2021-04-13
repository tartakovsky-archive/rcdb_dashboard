from datetime import timedelta

import pytest
from django.utils import timezone

from core import models
from core.services import BinanceAccountConnector, snapshot_account_balances, EXCHANGE_ACCOUNT_CONNECTOR_MAP

use_db = pytest.mark.django_db


def test_binnace_account_connector():
    assert EXCHANGE_ACCOUNT_CONNECTOR_MAP['binance'] == BinanceAccountConnector


@use_db
def test_snapshot_account_balances_unsupported_exchange(bot: models.Bot):
    exchange_credentials = bot.exchange_credentials
    exchange_credentials.exchange.slug = 'some'
    exchange_credentials.save()
    snapshot_account_balances(exchange_credentials)

    assert exchange_credentials.balance_snapshot is None
    assert exchange_credentials.balance_snapshot_created is None


@use_db
@pytest.mark.parametrize('ignore_spot_balance', [True, False])
def test_snapshot_account_balances(bot: models.Bot, mocker, ignore_spot_balance):
    class MockBinance:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_balance(self):
            return {
                'total': {
                    'USDT': 20,
                    'BTC': 0.5,
                    'BUSD': 0
                }
            }

        def fetch_ticker(self, sym):
            v = 20. if 'BTC' in sym else 1.
            return {'bid': v, 'ask': v}

        def sapi_get_margin_account(self):
            return {
                'userAssets': [
                    {
                        'asset': 'USDC',
                        'netAsset': '20.5'
                    },
                    {
                        'asset': 'BUSD',
                        'netAsset': '0'
                    },
                    {
                        'asset': 'USDT',
                        'netAsset': '11'
                    },
                    {
                        'asset': 'BTC',
                        'netAsset': '0.5'
                    },
                ]
            }

    mocker.patch('core.services.ccxt.binance', MockBinance)

    bot.exchange_credentials.ignore_spot_balance = ignore_spot_balance
    bot.exchange_credentials.save()
    print(bot.exchange_credentials.ignore_spot_balance)

    snapshot_account_balances(bot.exchange_credentials)

    snapshot = bot.exchange_credentials.balance_snapshot
    snapshot['spot'] = tuple(snapshot['spot'])
    snapshot['margin'] = tuple(snapshot['margin'])

    assert timezone.now() - bot.exchange_credentials.balance_snapshot_created <= timedelta(minutes=1)

    print(bot.exchange_credentials.balance_snapshot)
    assert bot.exchange_credentials.balance_snapshot == {
        'spot': tuple() if ignore_spot_balance else (
            {'symbol': 'USDT', 'amount': 20, 'amount_usd': 20},
            {'symbol': 'BTC', 'amount': 0.5, 'amount_usd': 10.}
        ),
        'margin': (
            {'symbol': 'USDC', 'amount': 20.5, 'amount_usd': 20.5},
            {'symbol': 'USDT', 'amount': 11., 'amount_usd': 11.},
            {'symbol': 'BTC', 'amount': 0.5, 'amount_usd': 10.}
        ),
        'total_usd': 41.5 if ignore_spot_balance else 71.5,
        'margin_usd': 41.5,
        'spot_usd': 0 if ignore_spot_balance else 30.
    }
