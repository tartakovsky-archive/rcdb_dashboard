from typing import Optional

from ninja import Schema


class CredentialData(Schema):
    access_token: str
    token_type: str = 'bearer'


class Exchange(Schema):
    name: str
    slug: str


class ExchangeCredentials(Schema):
    exchange: Exchange
    name: str
    label: str
    parameters: dict
    meta: Optional[dict]
