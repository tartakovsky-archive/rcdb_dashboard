from django.contrib import admin
from django.db.models import JSONField
from django_json_widget.widgets import JSONEditorWidget

from core import models


class JsonWidgetMixin:
    formfield_overrides = {
        JSONField: {'widget': JSONEditorWidget},
    }


@admin.register(models.Exchange)
class ExchangeAdmin(admin.ModelAdmin):
    pass


@admin.register(models.Currency)
class CurrencyAdmin(admin.ModelAdmin):
    pass


@admin.register(models.Symbol)
class SymbolAdmin(admin.ModelAdmin):
    pass


@admin.register(models.Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    pass


@admin.register(models.ExchangeCredentials)
class ExchangeCredentialsAdmin(JsonWidgetMixin, admin.ModelAdmin):
    pass


@admin.register(models.Account)
class AccountAdmin(admin.ModelAdmin):
    pass


@admin.register(models.BotStatistic)
class BotStatisticAdmin(admin.ModelAdmin):
    pass


@admin.register(models.Bot)
class BotAdmin(JsonWidgetMixin, admin.ModelAdmin):
    list_display = ('name', 'is_active')

    def name(self, obj):
        return str(obj)
