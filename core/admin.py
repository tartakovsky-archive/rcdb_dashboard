from django.contrib import admin

from core import models


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
class ExchangeCredentialsAdmin(admin.ModelAdmin):
    pass


class BotStatisticInline(admin.TabularInline):
    model = models.BotStatistic


@admin.register(models.Account)
class AccountAdmin(admin.ModelAdmin):
    pass


@admin.register(models.BotStatistic)
class BotStatisticAdmin(admin.ModelAdmin):
    pass


@admin.register(models.Bot)
class BotAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')

    def name(self, obj):
        return str(obj)
