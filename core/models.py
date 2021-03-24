import json

from django.db import models
from django.core.validators import RegexValidator, ValidationError


def validate_json(value: str):
    try:
        json.loads(value)
    except json.JSONDecodeError:
        raise ValidationError('Invalid json')


class Account(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Exchange(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.CharField(max_length=30, default="binance", unique=True)

    def __str__(self):
        return f"{self.name}"


class Currency(models.Model):
    class Meta:
        verbose_name_plural = 'Currencies'

    name = models.CharField(unique=True, max_length=16)
    slug = models.CharField(max_length=16, validators=[
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
        ("SPOT", "SPOT"),
        ("MARGIN", "MARGIN"),
        ("FUTURE", "FUTURE"),
    )

    exchange = models.ForeignKey(Exchange, null=False, blank=False, on_delete=models.PROTECT)
    symbol = models.ForeignKey(Symbol, on_delete=models.PROTECT)
    type = models.CharField(max_length=6, choices=TYPE_CHOICES, default="SPOT")

    size_round_precision = models.IntegerField(default=9)

    def __str__(self):
        return f"{self.symbol} - {self.type} on {self.exchange}"


class ExchangeCredentials(models.Model):
    class Meta:
        verbose_name_plural = 'ExchangeCredentials'

    name = models.CharField(max_length=200)
    exchange = models.ForeignKey(Exchange, on_delete=models.PROTECT)
    parameters = models.JSONField(default=dict)

    def __str__(self):
        return f"{self.name} for {self.exchange}"


class Bot(models.Model):
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    exchange_credentials = models.ForeignKey(ExchangeCredentials, on_delete=models.PROTECT)
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)

    config = models.JSONField(default=dict)

    def clean(self):
        if self.exchange_credentials.exchange != self.instrument.exchange:
            raise ValidationError('Exchange of the instrument and credentials should be the same')

    def __str__(self):
        return f"{self.name} // {self.instrument}"

    @property
    def bot_name(self):
        return str(self)


class BotStatistic(models.Model):
    updated = models.DateTimeField()
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE)
    equity = models.FloatField()
    exposure = models.FloatField()
    employed_capital = models.FloatField()
    price_crypto = models.FloatField()
    price_fair = models.FloatField()
    price_forex = models.FloatField()
    balance_base_borrowed = models.FloatField()
    balance_quote_borrowed = models.FloatField()

    @property
    def price_change(self) -> float:
        return round(100 * (self.price_forex / self.price_fair - 1), 2)
