from dataclasses import dataclass

@dataclass
class BotPosition:
    timestamp: int
    price_avg: float
    size: float
    pnl: float


@dataclass
class BotTicker:
    timestamp: int
    bid: float
    ask: float
    price_avg: float


@dataclass
class BotOrderResult:
    timestamp: int
    type: str
    size: float
    price_avg: float


@dataclass
class BotQuoteBalance:
    amount_all: float
    amount_free: float
