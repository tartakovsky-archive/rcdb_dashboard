from dataclasses import dataclass


@dataclass
class PositionData:
    timestamp: int
    price_avg: float
    size: float
    pnl: float


@dataclass
class TickerData:
    timestamp: int
    bid: float
    ask: float
    price_avg: float


@dataclass
class OrderResultData:
    timestamp: int
    type: str
    size: float
    price_avg: float


@dataclass
class QuoteBalanceData:
    amount_all: float
    amount_free: float


#
# BotDataClasses
#

@dataclass
class SymbolData:
    base: str
    quote: str

    def __post_init__(self):
        assert self.base == self.base.upper()
        assert self.quote == self.quote.upper()

    def to_kaiko(self):
        return f"{self.base.lower()}-{self.quote.lower()}"

    def to_ccxt(self):
        return f"{self.base}/{self.quote}"

    def to_binance(self):
        return f"{self.base.upper()}{self.quote.upper()}"

