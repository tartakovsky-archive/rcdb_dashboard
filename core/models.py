import os
import logging
from typing import Optional

import numpy as np
import pandas as pd
import pydantic
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models.functions import Cast
from django.db.models.fields.json import KeyTextTransform
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import RegexValidator, ValidationError
from django.contrib.auth.models import User
from rcdb_commons.lib.schemas import strategy_configs
from rcdb_commons.lib.schemas.exchange import AccountType


class CustomDjangoJSONEncoder(DjangoJSONEncoder):
    def default(self, o):
        if isinstance(o, np.int64):
            return int(o)
        return super().default(o)


class Owner(models.Model):
    class Meta:
        ordering = ['order_id', 'name']

    name = models.CharField(max_length=100, unique=True)
    user = models.ForeignKey(User, verbose_name='Associated user', null=True, blank=True, on_delete=models.SET_NULL)
    order_id = models.IntegerField(default=0)

    _totals = None

    def get_exchange_credentials_balances(self):
        return (
            self
            .exchangecredentials_set
            .filter(visible=True)
            .order_by('order_id', 'name')
            .defer('balance_snapshot', 'statistics', 'meta')
        )

    def has_visible_exchange_credentials(self) -> bool:
        return self.exchangecredentials_set.filter(visible=True).exists()

    def _owner_totals(self):
        aggs = {
            'balance_snapshot': ['total_usd', 'borrowed_usd', 'interest_usd'],
            'statistics': ['h1_usd_volume', 'h24_usd_volume', 'd7_usd_volume']
        }
        return (
            self
            .exchangecredentials_set
            .filter(
                visible=True,
                ignore_balance=False,
            )
            .annotate(
                **{
                    field: Cast(
                        KeyTextTransform(field, table_field),
                        models.FloatField()
                    )
                    for table_field, fields in aggs.items()
                    for field in fields
                }
            )
            .aggregate(
                **{
                    f'agg__{field}': models.Sum(field)
                    for fields in aggs.values()
                    for field in fields
                }
            )
        )

    @property
    def totals(self):
        if not self._totals:
            self._totals = {k[len('agg__'):]: v for k, v in self._owner_totals().items()}
            self._totals['borrowed_interest_sum'] = \
                (self._totals.get('interest_usd') or 0) + (self._totals.get('borrowed_usd') or 0)
        return self._totals

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
        ordering = ['order_id', 'name']

    name = models.CharField(max_length=200)
    account_id = models.CharField(max_length=64, blank=True, null=True)
    label = models.CharField(max_length=200, blank=True, default='')
    owner = models.ForeignKey(Owner, on_delete=models.PROTECT)
    account_type = models.CharField(
        max_length=15, choices=AccountType.choices(), default=AccountType.CROSS_MARGIN.value
    )
    exchange = models.ForeignKey(Exchange, on_delete=models.PROTECT)
    meta = models.JSONField(default=dict, null=True, blank=True)

    balance_snapshot = models.JSONField(null=True, blank=True)
    balance_snapshot_clean = models.JSONField(null=True, blank=True)
    balance_snapshot_created = models.DateTimeField(null=True, blank=True)

    statistics = models.JSONField(null=True, blank=True, encoder=CustomDjangoJSONEncoder)
    statistics_clean = models.JSONField(null=True, blank=True, encoder=CustomDjangoJSONEncoder)

    visible = models.BooleanField(default=True)
    ignore_balance = models.BooleanField(default=False)
    ignore_datapipes = models.BooleanField(
        default=False,
        db_index=True,
        help_text='Disables a collecting data for the account'
    )
    order_id = models.IntegerField(default=0)

    def set_trades(self, df: pd.DataFrame):
        try:
            path = self._get_trades_path()
            if not len(df):
                if os.path.exists(path):
                    os.remove(path)
            else:
                df.to_feather(path)
        except Exception:
            logging.exception(f"Can't write trades {self._get_trades_path()}")

    def get_trades(self) -> pd.DataFrame:
        try:
            path = self._get_trades_path()
            if os.path.exists(path):
                return pd.read_feather(path)
        except Exception:
            logging.exception(f"Can't read trades {self._get_trades_path()}")

        return pd.DataFrame([])

    def _get_trades_path(self):
        return os.path.join(settings.TRADES_ROOT, f'{self.id}_{self.name}_{self.account_type}.feather')

    def set_balance_snapshot(self, snapshot: dict, save: bool = True):
        self.balance_snapshot = snapshot
        self.balance_snapshot_clean = {k: v for k, v in snapshot.items() if k != 'balances'}
        self.balance_snapshot_created = timezone.now()
        if save:
            self.save(update_fields=['balance_snapshot', 'balance_snapshot_created', 'balance_snapshot_clean'])

    def set_statistics(self, statistics: dict, save: bool = True):
        self.statistics = statistics
        self.statistics_clean = {k: v for k, v in statistics.items() if k != 'trades'}
        if save:
            self.save(update_fields=['statistics', 'statistics_clean'])

    @property
    def account_type_label(self) -> Optional[str]:
        if not self.account_type:
            return
        return AccountType[self.account_type].label

    @property
    def borrowed_interest_sum(self):
        if self.is_margin and self.balance_snapshot_clean \
                and 'borrowed_usd' in self.balance_snapshot_clean and 'interest_usd' in self.balance_snapshot_clean:
            return self.balance_snapshot_clean['borrowed_usd'] + self.balance_snapshot_clean['interest_usd']

    @property
    def is_margin(self) -> bool:
        if self.account_type:
            return AccountType[self.account_type] in {AccountType.CROSS_MARGIN, AccountType.ISOLATED_MARGIN}

    def __str__(self):
        return f"{self.name} for {self.exchange} {self.account_type}"


class Bot(models.Model):
    name = models.CharField(max_length=200)
    owner = models.ForeignKey(Owner, on_delete=models.SET_NULL, blank=True, null=True)
    is_active = models.BooleanField(default=False)

    config = models.JSONField(default=dict, encoder=CustomDjangoJSONEncoder)

    def clean(self, *args, **kwargs):
        try:
            strategy_configs.AdminConfigInput(**self.config)
        except pydantic.error_wrappers.ValidationError as ex:
            raise ValidationError(f'Config: {ex}')

        super().clean(*args, **kwargs)

    def read_config(self) -> strategy_configs.AdminConfigInput:
        return strategy_configs.AdminConfigInput(**self.config)

    def save(self, *args, **kwargs):
        self.full_clean()
        self.config = strategy_configs.AdminConfigInput(**self.config).dict()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

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
