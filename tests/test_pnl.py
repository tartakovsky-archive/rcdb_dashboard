import datetime

import pytest
import pandas as pd
from rcdb_commons.lib.stores import DataType
from rcdb_commons.lib.schemas.exchange import AccountType, TransferType

from core.models import Bot, ExchangeCredentials
from core.services import update_accounts_pnl

use_db = pytest.mark.django_db
NOW = datetime.datetime(2021, 4, 23, 13)


@pytest.fixture
def mocked_dt(mocker):
    mocked_utc = mocker.patch('core.services.datetime')

    class FakeDatetime(datetime.datetime):
        @classmethod
        def utcnow(cls):
            return NOW

    mocked_utc.datetime = FakeDatetime
    mocked_utc.timedelta = datetime.timedelta
    yield


class DummyDataStore:

    @classmethod
    def read(cls, data_type, query_params):
        if data_type == DataType.balance:
            date_end = query_params['date_end']
            if (NOW - datetime.timedelta(hours=1)).isoformat() == date_end:
                return pd.DataFrame(
                    [{
                        'timestamp': NOW - datetime.timedelta(hours=1, minutes=5),
                        'name': 'Creds',
                        'account_type': AccountType.CROSS_MARGIN.value,
                        'symbol': 'USDT',
                        'amount': 80,
                        'amount_usd': 80
                    }]
                ).set_index('timestamp')
            elif (NOW - datetime.timedelta(hours=24)).isoformat() == date_end:
                return pd.DataFrame(
                    [{
                        'timestamp': NOW - datetime.timedelta(hours=24),
                        'name': 'Creds',
                        'account_type': AccountType.CROSS_MARGIN.value,
                        'symbol': 'USDT',
                        'amount': 60,
                        'amount_usd': 60
                    }]
                ).set_index('timestamp')
            else:
                raise Exception(f'Wrong date {date_end}')

        if data_type == DataType.transfers:
            return pd.DataFrame(
                [
                    {
                        'timestamp': NOW - datetime.timedelta(hours=23),
                        'symbol': 'USDT',
                        'name': 'Creds',
                        'transfer_type': TransferType.C2C_MARGIN.value,
                        'amount': 5,
                        'amount_usd': 5
                    },
                    # irrelevant transfer for CROSS_MARGIN
                    {
                        'timestamp': NOW - datetime.timedelta(hours=23),
                        'symbol': 'USDT',
                        'name': 'Creds',
                        'transfer_type': TransferType.MAIN_CMFUTURE.value,
                        'amount': 5,
                        'amount_usd': 5
                    },
                    {
                        'timestamp': NOW - datetime.timedelta(minutes=45),
                        'symbol': 'USDT',
                        'name': 'Creds',
                        'transfer_type': TransferType.MINING_MARGIN.value,
                        'amount': 5,
                        'amount_usd': 5
                    },

                    # mutual destroy transfers
                    {
                        'timestamp': NOW - datetime.timedelta(minutes=30),
                        'symbol': 'USDT',
                        'name': 'Creds',
                        'transfer_type': TransferType.C2C_MARGIN.value,
                        'amount': 2.5,
                        'amount_usd': 2.5
                    },
                    {
                        'timestamp': NOW - datetime.timedelta(minutes=15),
                        'symbol': 'USDT',
                        'name': 'Creds',
                        'transfer_type': TransferType.MARGIN_MINING.value,
                        'amount': 2.5,
                        'amount_usd': 2.5
                    },

                ]
            ).set_index('timestamp')


@use_db
def test_pnl(bot: Bot, mocked_dt):
    account: ExchangeCredentials = ExchangeCredentials.objects.first()
    account.balance_snapshot = {'total_usd': 110}
    account.save()

    update_accounts_pnl(DummyDataStore())

    account.refresh_from_db()
    print(account.statistics)
    total_usd = account.balance_snapshot['total_usd']
    data = account.statistics

    for h in [1, 24]:
        # (current_amount - old_amount - transfers_volume) / old_amount * 100
        key = f'h{h}'
        transfers_volume = data[f'{key}_transfers_in_volume'] + data[f'{key}_transfers_out_volume']
        assert account.statistics[f'{key}_pnl'] == \
               (total_usd - data[f'{key}_total_usd'] - transfers_volume) / data[f'{key}_total_usd'] * 100
