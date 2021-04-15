from datetime import timedelta

import pytest
from django.utils import timezone

from core import models
from core.services import BinanceAccountConnector, snapshot_account_balances, EXCHANGE_ACCOUNT_CONNECTOR_MAP

use_db = pytest.mark.django_db


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

    def sapi_get_margin_isolated_account(self):
        return {
            "assets": [
                {
                    "baseAsset": {
                        "asset": "BTC",
                        "netAsset": "0.5",
                        "netAssetOfBtc": "0.5",
                    },
                    "quoteAsset": {
                        "asset": "USDT",
                        "netAsset": "2",
                        "netAssetOfBtc": "0.000032",
                    },
                    "symbol": "BTCUSDT",
                },
                {
                    "baseAsset": {
                        "asset": "ETH",
                        "netAsset": "1000",
                        "netAssetOfBtc": "0.1",
                    },
                    "quoteAsset": {
                        "asset": "USDT",
                        "netAsset": "2",
                        "netAssetOfBtc": "0.000032",
                    },
                    "symbol": "ETHUSDT",
                }
            ],
        }


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
@pytest.mark.parametrize(
    'market_type',
    [
        models.ExchangeCredentials.AccountChoices.SPOT,
        models.ExchangeCredentials.AccountChoices.ISOLATED_MARGIN,
        models.ExchangeCredentials.AccountChoices.CROSS_MARGIN,
    ]
)
def test_snapshot_account_balances(bot: models.Bot, mocker, market_type):
    mocker.patch('core.services.ccxt.binance', MockBinance)

    bot.exchange_credentials.account_type = market_type

    snapshot_account_balances(bot.exchange_credentials)

    snapshot = bot.exchange_credentials.balance_snapshot
    snapshot['balances'] = tuple(snapshot['balances'])
    assert timezone.now() - bot.exchange_credentials.balance_snapshot_created <= timedelta(minutes=1)

    test_result = {
        models.ExchangeCredentials.AccountChoices.SPOT: (
            {'symbol': 'USDT', 'amount': 20, 'amount_usd': 20},
            {'symbol': 'BTC', 'amount': 0.5, 'amount_usd': 10.}
        ),
        models.ExchangeCredentials.AccountChoices.CROSS_MARGIN: (
            {'symbol': 'USDC', 'amount': 20.5, 'amount_usd': 20.5},
            {'symbol': 'USDT', 'amount': 11., 'amount_usd': 11.},
            {'symbol': 'BTC', 'amount': 0.5, 'amount_usd': 10.}
        ),
        models.ExchangeCredentials.AccountChoices.ISOLATED_MARGIN: (
            {'pair_symbol': 'BTCUSDT', 'symbol': 'BTC',
             'amount': 0.5, 'amount_btc': 0.5, 'amount_usd': 10.},
            {'pair_symbol': 'BTCUSDT', 'symbol': 'USDT', 'amount': 2., 'amount_usd': 2.},
            {'pair_symbol': 'ETHUSDT', 'symbol': 'ETH', 'amount': 1000, 'amount_btc': 0.1, 'amount_usd': 2.},
            {'pair_symbol': 'ETHUSDT', 'symbol': 'USDT', 'amount': 2., 'amount_usd': 2.},
        ),
        'total_usd': {
            models.ExchangeCredentials.AccountChoices.SPOT: 30.,
            models.ExchangeCredentials.AccountChoices.CROSS_MARGIN: 41.5,
            models.ExchangeCredentials.AccountChoices.ISOLATED_MARGIN: 16.
        }
    }
    assert snapshot == {'balances': test_result[market_type], 'total_usd': test_result['total_usd'][market_type]}


@pytest.mark.parametrize(
    'market_type',
    [
        models.ExchangeCredentials.AccountChoices.USDT_M_FUTURES,
        models.ExchangeCredentials.AccountChoices.COIN_M_FUTURES
    ]
)
def test_snapshot_account_balances_unsupported_market_type(mocker, market_type):
    mocker.patch('core.services.ccxt.binance', MockBinance)
    with pytest.raises(BinanceAccountConnector.Exceptions.UnsupportedMarketType):
        BinanceAccountConnector({}).get_balance_data(market_type.value)
