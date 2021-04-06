from typing import Optional

import pydantic
from django.db import models
from django.core.validators import RegexValidator, ValidationError
from rcdb_commons.schemas import bot as bot_schemas


class Owner(models.Model):
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

    price_precision = models.IntegerField(null=True, blank=True)
    amount_precision = models.IntegerField(null=True, blank=True)

    @property
    def pair(self):
        return f"{self.base.slug.upper()}/{self.quote.slug.upper()}"

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
    order_amount_max = models.FloatField(default=100_000)
    order_amount_min = models.FloatField(default=10)

    def __str__(self):
        return f"{self.symbol} - {self.type} on {self.exchange}"


class ExchangeCredentials(models.Model):
    class Meta:
        verbose_name_plural = 'ExchangeCredentials'

    name = models.CharField(max_length=200)
    owner = models.ForeignKey(Owner, on_delete=models.PROTECT)
    exchange = models.ForeignKey(Exchange, on_delete=models.PROTECT)
    parameters = models.JSONField(default=dict)

    def __str__(self):
        return f"{self.name} for {self.exchange}"


class Bot(models.Model):
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=False)
    exchange_credentials = models.ForeignKey(ExchangeCredentials, on_delete=models.PROTECT)
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)

    config = models.JSONField(default=dict)

    def clean(self, *args, **kwargs):
        try:
            bot_schemas.AdminConfigInput(**self.config)
        except pydantic.error_wrappers.ValidationError as ex:
            raise ValidationError(f'Config: {ex}')

        if self.exchange_credentials.exchange != self.instrument.exchange:
            raise ValidationError('Exchange of the instrument and credentials should be the same')
        super().clean(*args, **kwargs)

    def save(self, *args, **kwargs):
        self.full_clean()
        self.config = bot_schemas.AdminConfigInput(**self.config).dict()
        super().save(*args, **kwargs)

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

    @property
    def price_deviation(self) -> Optional[float]:
        try:
            upside_dev = max(self.price_crypto / max(self.price_fair, self.price_forex) - 1, 0)
            downside_dev = min(self.price_crypto / min(self.price_fair, self.price_forex - 1), 0)
            return upside_dev if upside_dev > 0 else downside_dev
        except ZeroDivisionError:
            return None
