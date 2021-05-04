import datetime

import pytz
import pytest
import pandas as pd
from dateutil.parser import parse as dt_parse
from rcdb_commons.lib.stores import DataStore, DataType

from core import models
from core.services import BotStatisticUpdater

use_db = pytest.mark.django_db

TEST_DATA = {
    "timestamp": "2021-03-10T12:15:58.387397",
    "bot_id": 1,
    "balance_base": 25.5,
    "balance_quote": 25.3,
    "bid": 1245.5,
    "ask": 1245.3,
    "price_crypto": 12245.45,
    "price_fair": 12245.45,
    "price_forex": 1245.35,
    "balance_base_borrowed": 100000.5,
    "balance_quote_borrowed": 14555.5
}


@pytest.fixture
def mocked_datastore_run_updater(mocker):
    datastore = DataStore(None, None)

    def _mock_fabric(data: list, bot_id: int):
        df = pd.DataFrame(data)

        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index("timestamp")

        mocked_method = mocker.patch.object(datastore, 'read', autospect=True)
        mocked_method.return_value = df
        BotStatisticUpdater(datastore).update(bot_id)
        mocked_method.assert_called_once_with(DataType.bot_performance, {'bot_id': bot_id})

    return _mock_fabric


@use_db
def test_create_bot_statistic(bot: models.Bot, mocked_datastore_run_updater):
    assert bot.botstatistic_set.first() is None

    mocked_datastore_run_updater([TEST_DATA], bot.id)

    bot_statistic = bot.botstatistic_set.first()
    assert bot_statistic.updated == dt_parse(TEST_DATA['timestamp']).replace(tzinfo=pytz.UTC)
    assert bot_statistic.price_crypto == TEST_DATA['price_crypto']
    assert bot_statistic.price_fair == TEST_DATA['price_fair']
    assert bot_statistic.price_forex == TEST_DATA['price_forex']
    assert bot_statistic.balance_base_borrowed == TEST_DATA['balance_base_borrowed']
    assert bot_statistic.balance_quote_borrowed == TEST_DATA['balance_quote_borrowed']
    assert bot_statistic.employed_capital is not None
    assert bot_statistic.exposure is not None
    assert bot_statistic.equity is not None


@use_db
def test_update_bot_statistic_same(bot: models.Bot, mocked_datastore_run_updater):
    test_create_bot_statistic(bot, mocked_datastore_run_updater)
    old_datastore_updated = bot.botstatistic_set.first().updated

    mocked_datastore_run_updater([TEST_DATA], bot.id)

    assert bot.botstatistic_set.first().updated == old_datastore_updated


@use_db
def test_update_bot_statistic(bot: models.Bot, mocked_datastore_run_updater):
    test_create_bot_statistic(bot, mocked_datastore_run_updater)
    old_datastore_updated = bot.botstatistic_set.first().updated

    mocked_datastore_run_updater(
        [{**TEST_DATA, 'timestamp': datetime.datetime.utcnow().isoformat()}],
        bot.id
    )

    assert bot.botstatistic_set.first().updated > old_datastore_updated


@use_db
def test_create_bot_statistic_empty(bot: models.Bot, mocked_datastore_run_updater):
    mocked_datastore_run_updater([], bot.id)
    assert bot.botstatistic_set.first() is None
