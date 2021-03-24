from ninja import Schema


class Exchange(Schema):
    slug: str


class Currency(Schema):
    slug: str


class Symbol(Schema):
    base: Currency
    quote: Currency


class Instrument(Schema):
    exchange: Exchange
    symbol: Symbol
    type: str
    size_round_precision: int


class ExchangeCredentials(Schema):
    name: str
    parameters: dict


class Bot(Schema):
    id: int
    name: str
    is_active: bool
    exchange_credentials: ExchangeCredentials
    instrument: Instrument
    config: dict
