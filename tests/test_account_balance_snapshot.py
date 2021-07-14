from datetime import timedelta

import asyncio
import pandas as pd
import pytest
from django.utils import timezone

from core import models
from core.services import BinanceAccountConnector, snapshot_account_balances, EXCHANGE_ACCOUNT_CONNECTOR_MAP
from rcdb_commons.lib.schemas.exchange import AccountType

use_db = pytest.mark.django_db


class DummyDataStore:

    @classmethod
    def read(cls, data_type, query_params):
        return pd.DataFrame([{'close': 20. if 'BTC' in query_params['symbol'] else 1.}])


class DummyCredentialsStore:
    @classmethod
    def get_secret(cls, name):
        return {'secret': '0000'}


class MockBinance:
    options = {}

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
                    "interest": "0.03",
                    "borrowed": "10",
                    'netAsset': '20.5'
                },
                {
                    'asset': 'BUSD',
                    "interest": "0",
                    "borrowed": "0",
                    'netAsset': '0'
                },
                {
                    'asset': 'USDT',
                    "interest": "0.1",
                    "borrowed": "5.5",
                    'netAsset': '11'
                },
                {
                    'asset': 'BTC',
                    "interest": "0.03",
                    "borrowed": "0.1",
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
                        "interest": "0.05",
                        "borrowed": "0.1",
                        "netAsset": "0.5",
                        "netAssetOfBtc": "0.5",
                    },
                    "quoteAsset": {
                        "asset": "USDT",
                        "interest": "0",
                        "borrowed": "0",
                        "netAsset": "2",
                        "netAssetOfBtc": "0.000032",
                    },
                    "symbol": "BTCUSDT",
                },
                {
                    "baseAsset": {
                        "asset": "ETH",
                        "interest": "0.03",
                        "borrowed": "0",
                        "netAsset": "1000",
                        "netAssetOfBtc": "0.1",
                    },
                    "quoteAsset": {
                        "asset": "USDT",
                        "interest": "0.3",
                        "borrowed": "0.5",
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
    exchange_credentials = models.ExchangeCredentials.objects.first()
    exchange_credentials.exchange.slug = 'some'
    exchange_credentials.save()
    asyncio.run(snapshot_account_balances(exchange_credentials, DummyDataStore(), DummyCredentialsStore()))

    assert exchange_credentials.balance_snapshot is None
    assert exchange_credentials.balance_snapshot_created is None


@use_db
@pytest.mark.parametrize(
    'market_type',
    [
        AccountType.SPOT,
        AccountType.ISOLATED_MARGIN,
        AccountType.CROSS_MARGIN,
        AccountType.USDT_M_FUTURES,
        AccountType.COIN_M_FUTURES
    ]
)
def test_snapshot_account_balances(bot: models.Bot, mocker, market_type):
    mocker.patch('core.services.ccxt.binance', MockBinance)
    exchange_credentials = models.ExchangeCredentials.objects.first()
    exchange_credentials.account_type = market_type.value
    assert exchange_credentials.exchange.slug
    asyncio.run(snapshot_account_balances(exchange_credentials, DummyDataStore(), DummyCredentialsStore()))
    exchange_credentials.save()
    snapshot = exchange_credentials.balance_snapshot
    snapshot['balances'] = tuple(snapshot['balances'])
    assert timezone.now() - exchange_credentials.balance_snapshot_created <= timedelta(minutes=1)

    test_result = {
        AccountType.COIN_M_FUTURES: (
            {'symbol': 'USDT', 'amount': 20, 'amount_usd': 20},
            {'symbol': 'BTC', 'amount': 0.5, 'amount_usd': 10.}
        ),
        AccountType.USDT_M_FUTURES: (
            {'symbol': 'USDT', 'amount': 20, 'amount_usd': 20},
            {'symbol': 'BTC', 'amount': 0.5, 'amount_usd': 10.}
        ),
        AccountType.SPOT: (
            {'symbol': 'USDT', 'amount': 20, 'amount_usd': 20},
            {'symbol': 'BTC', 'amount': 0.5, 'amount_usd': 10.}
        ),
        AccountType.CROSS_MARGIN: (
            {
                'symbol': 'USDC', 'amount': 20.5, 'amount_usd': 20.5,
                'interest': 0.03, 'interest_usd': 0.03, 'borrowed': 10., 'borrowed_usd': 10.
            },
            {
                'symbol': 'USDT', 'amount': 11., 'amount_usd': 11.,
                'interest': 0.1, 'interest_usd': 0.1, 'borrowed': 5.5, 'borrowed_usd': 5.5
            },
            {
                'symbol': 'BTC', 'amount': 0.5, 'amount_usd': 10.,
                'interest': 0.03, 'interest_usd': 0.6, 'borrowed': 0.1, 'borrowed_usd': 2.
            }
        ),
        AccountType.ISOLATED_MARGIN: (
            {
                'pair_symbol': 'BTCUSDT', 'symbol': 'BTC', 'amount': 0.5, 'amount_btc': 0.5, 'amount_usd': 10.,
                'interest': 0.05, 'interest_usd': 1., 'borrowed': 0.1, 'borrowed_usd': 2.
            },
            {
                'pair_symbol': 'BTCUSDT', 'symbol': 'USDT', 'amount': 2., 'amount_usd': 2.,
                'interest': 0, 'interest_usd': 0, 'borrowed': 0, 'borrowed_usd': 0
            },
            {
                'pair_symbol': 'ETHUSDT', 'symbol': 'ETH', 'amount': 1000, 'amount_btc': 0.1, 'amount_usd': 2.,
                'interest': 0.03, 'interest_usd': 0.03, 'borrowed': 0, 'borrowed_usd': 0
            },
            {
                'pair_symbol': 'ETHUSDT', 'symbol': 'USDT', 'amount': 2., 'amount_usd': 2.,
                'interest': 0.3, 'interest_usd': 0.3, 'borrowed': 0.5, 'borrowed_usd': 0.5
            },
        ),
        'total_usd': {
            AccountType.COIN_M_FUTURES: 30.,
            AccountType.USDT_M_FUTURES: 30.,
            AccountType.SPOT: 30.,
            AccountType.CROSS_MARGIN: 41.5,
            AccountType.ISOLATED_MARGIN: 16.
        },
        'borrowed_usd': {
            AccountType.USDT_M_FUTURES: None,
            AccountType.COIN_M_FUTURES: None,
            AccountType.SPOT: None,
            AccountType.CROSS_MARGIN: 17.5,
            AccountType.ISOLATED_MARGIN: 2.5
        },
        'interest_usd': {
            AccountType.USDT_M_FUTURES: None,
            AccountType.COIN_M_FUTURES: None,
            AccountType.SPOT: None,
            AccountType.CROSS_MARGIN: 0.73,
            AccountType.ISOLATED_MARGIN: 1.33
        }
    }

    test_snapshot = {
        'balances': test_result[market_type],
        'total_usd': test_result['total_usd'][market_type],
        'borrowed_usd': test_result['borrowed_usd'][market_type],
        'interest_usd': test_result['interest_usd'][market_type]
    }
    if market_type in {AccountType.SPOT, AccountType.USDT_M_FUTURES, AccountType.COIN_M_FUTURES}:
        del test_snapshot['borrowed_usd']
        del test_snapshot['interest_usd']
        assert exchange_credentials.owner.total_interest is None
        assert exchange_credentials.owner.total_borrowed is None
    else:
        assert exchange_credentials.owner.total_interest == test_snapshot['interest_usd']
        assert exchange_credentials.owner.total_borrowed == test_snapshot['borrowed_usd']

    assert exchange_credentials.owner.total_balance == test_snapshot['total_usd']
    assert snapshot == test_snapshot


class CustomType:
    value = 'SOME VALUE'


@pytest.mark.parametrize(
    'market_type',
    [
        CustomType
    ]
)
def test_snapshot_account_balances_unsupported_market_type(mocker, market_type):
    mocker.patch('core.services.ccxt.binance', MockBinance)
    with pytest.raises(BinanceAccountConnector.Exceptions.UnsupportedMarketType):
        asyncio.run(BinanceAccountConnector({}, DummyDataStore()).get_balance_data(market_type.value))
