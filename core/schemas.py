from typing import Optional

from ninja import Schema


class Exchange(Schema):
    slug: str


class Currency(Schema):
    slug: str


class Symbol(Schema):
    pair: str
    price_precision: Optional[int]
    amount_precision: Optional[int]


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


class CredentialData(Schema):
    access_token: str
    token_type: str = 'bearer'
