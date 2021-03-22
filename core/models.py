from django.db import models
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator


class Exchange(models.Model):
    name = models.TextField(max_length=100)
    slug = models.TextField(max_length=30, default="bitfinex")
    exchange_email = models.EmailField()

    class Meta:
        unique_together = ('slug', 'exchange_email')

    def __str__(self):
        return f"{self.name} ({self.exchange_email})"


class Currency(models.Model):
    name = models.TextField(unique=True)
    slug = models.TextField(validators=[
        RegexValidator('^[A-Z]*$', 'Only uppercase letters are allowed.')])

    def __str__(self):
        return f"{self.slug} ({self.name})"


class Symbol(models.Model):
    base = models.ForeignKey(Currency, related_name="base", null=False, blank=False, on_delete=models.PROTECT)
    quote = models.ForeignKey(Currency, related_name="quote", null=False, blank=False, on_delete=models.PROTECT)

    def to_kaiko(self):
        return f"{self.base.slug.lower()}-{self.quote.slug.lower()}"

    def to_ccxt(self):
        return f"{self.base.slug}/{self.quote.slug}"

    def to_binance(self):
        return f"{self.base.slug.upper()}{self.quote.slug.upper()}"

    def __str__(self):
        return f"{self.base.slug}-{self.quote.slug}"


class Instrument(models.Model):
    TYPE_CHOICES = (
        ("SPOT", "spot"),
        ("MARGIN", "margin"),
        ("FUTURE", "future"),
    )

    exchange = models.ForeignKey(Exchange, null=False, blank=False, on_delete=models.PROTECT)
    symbol = models.ForeignKey(Symbol, on_delete=models.PROTECT)
    kaiko_type = models.TextField(choices=TYPE_CHOICES, default="SPOT")

    size_round_precision = models.IntegerField(default=9)

    def __str__(self):
        return f"{self.symbol} - {self.kaiko_type} on {self.exchange}"


class ExchangeCredentials(models.Model):
    """
    plain CCXT init object in json (would be translated to dict through json.loads)
    {
        "apiKey": "XXX",
        "secret": "YYY",
        "timeout": 5000,
        "enableRateLimit": true,
        "options": {
            "orderTypes": {
              "limit": "limit",
              "market": "market"
            }
        }
    }
    """
    name = models.TextField(max_length=200)
    exchange = models.ForeignKey(Exchange, on_delete=models.PROTECT)
    init_kwargs = models.TextField()

    def __str__(self):
        return f"{self.name} for {self.exchange}"


class Bot(models.Model):
    # if parent is not null, then this is DummyBot
    # that receiving signals on parent.push_signal
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)

    name = models.TextField(max_length=200)
    exchange_credentials = models.ForeignKey(ExchangeCredentials, on_delete=models.PROTECT)
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)

    predict_timestamp = models.IntegerField(default=0)

    is_active = models.BooleanField(default=False)

    min_trade_amount = models.FloatField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Min trade size for the instrument, e.g. bitfinex BTCUSD = 0.00082, bitmex XBTUSD - 1")

    max_trade_amount = models.FloatField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Max trade size for the instrument, e.g. bitfinex BTCUSD = 0.00082, bitmex XBTUSD - 1")

    slippage_pct_position_increase = models.FloatField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(0.1)],
        help_text="Max diff between current price and target instrument execution price on position increase.")

    slippage_pct_position_decrease = models.FloatField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(0.1)],
        help_text="Max diff between current price and target instrument execution price on position decrease.")

    def __str__(self):
        return f"{self.name} // {self.instrument}"
