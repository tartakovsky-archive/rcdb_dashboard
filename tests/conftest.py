import pytest

from core import models


@pytest.fixture
def bot():
    exchange = models.Exchange(name='binance', slug='binance')
    exchange.save()
    owner = models.Owner(name='Test account')
    owner.save()

    exchange_credentials = models.ExchangeCredentials(
        name='Creds',
        exchange=exchange,
        owner=owner,
        parameters={'some': 1}
    )
    exchange_credentials.save()

    base = models.Currency(name='EUR', slug='EUR')
    base.save()

    quote = models.Currency(name='USDT', slug='USDT')
    quote.save()

    symbol = models.Symbol(base=base, quote=quote, amount_precision=10, price_precision=10)
    symbol.save()

    instrument = models.Instrument(exchange=exchange, symbol=symbol)
    instrument.save()

    b = models.Bot(
        name='test bot',
        owner=owner,
        is_active=True,
        config={'config_type': 'OwnLongBotConfig', 'data': {'symbol': {'base': 'EUR', 'quote': 'USDT'}}}
    )
    b.save()
    return b
