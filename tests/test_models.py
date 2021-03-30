import pytest
from django.core.validators import ValidationError
from rcdb_commons.schemas import bot as bot_schemas

from core import models

use_db = pytest.mark.django_db


@use_db
def test_create_bot_with_different_exchange():
    exchange = models.Exchange(name='test', slug='test')
    exchange.save()

    exchange2 = models.Exchange(name='test2', slug='test2')
    exchange2.save()

    owner = models.Owner(name='Test account')
    owner.save()

    exchange_credentials = models.ExchangeCredentials(
        name='Creds',
        owner=owner,
        exchange=exchange2,
        parameters={'some': 1}
    )
    exchange_credentials.save()

    base = models.Currency(name='EUR', slug='EUR')
    base.save()

    quote = models.Currency(name='USDT', slug='USDT')
    quote.save()

    symbol = models.Symbol(base=base, quote=quote)
    symbol.save()

    instrument = models.Instrument(exchange=exchange, symbol=symbol)
    instrument.save()

    b = models.Bot(
        name='test bot',
        is_active=True,
        exchange_credentials=exchange_credentials,
        instrument=instrument,
        config={'config_type': 'OwnLongBotConfig'}
    )

    with pytest.raises(ValidationError) as exc:
        b.save()

    assert exc.match('Exchange of the instrument and credentials should be the same')


@pytest.mark.parametrize(
    'config_data',
    [
        ('OwnLongBotConfig', bot_schemas.OwnLongBotConfig),
        ('OwnShortBotConfig', bot_schemas.OwnShortBotConfig)
    ]
)
@use_db
def test_empty_config(bot: models.Bot, config_data):
    config_type, config_class = config_data
    bot.config = {'config_type': config_type}
    bot.save()

    _bot = models.Bot.objects.get(id=bot.id)
    assert _bot.config['data'] == config_class().dict()
    _bot.save()
