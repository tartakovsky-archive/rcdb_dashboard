import pytest
from rcdb_commons.lib.schemas import strategy_configs

from core import models

use_db = pytest.mark.django_db


@pytest.mark.parametrize(
    'config_data',
    list(strategy_configs.STRATEGY_CONFIG_CLASS_MAP.items())
)
@use_db
def test_empty_config(bot: models.Bot, config_data):
    config_type, config_class = config_data
    bot.config = {'config_type': config_type}
    bot.save()

    _bot = models.Bot.objects.get(id=bot.id)
    assert _bot.read_config().data == config_class()
    _bot.save()
