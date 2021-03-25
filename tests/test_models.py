import pytest
from django.core.validators import ValidationError

from core import models

use_db = pytest.mark.django_db


@use_db
def test_create_bot_with_different_exchange():
    exchange = models.Exchange(name='test', slug='test')
    exchange.save()

    exchange2 = models.Exchange(name='test2', slug='test2')
    exchange2.save()

    account = models.Account(name='Test account')
    account.save()

    exchange_credentials = models.ExchangeCredentials(
        name='Creds',
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
        account=account,
        exchange_credentials=exchange_credentials,
        instrument=instrument,
        config={'b': 1}
    )

    with pytest.raises(ValidationError) as exc:
        b.save()

    assert exc.match('Exchange of the instrument and credentials should be the same')
