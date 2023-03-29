import datetime
from typing import Optional, Dict, List, Tuple

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
    account_type: str
    meta: Optional[dict]
    fallback_since: datetime.datetime


class AccountMarketsMeta(Schema):
    account_name: str
    symbol: str


class AccountsMarketsMeta(Schema):
    data: Dict[str, List[AccountMarketsMeta]]


class AccountsMarketsMetaResponse(Schema):
    success: bool
    errors: List[Tuple[str, str, str]]
