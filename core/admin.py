from django.contrib import admin
from django.contrib.admin import AdminSite
from django.http import HttpResponse

from core import models


class MyAdminSite(AdminSite):
    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        urls += [
            path('get_cons_data/', self.admin_view(self.get_cons_data))
        ]
        return urls

    def get_cons_data(self, request):
        return HttpResponse()


admin_site = MyAdminSite()


@admin.register(models.Exchange, site=admin_site)
class ExchangeAdmin(admin.ModelAdmin):
    pass


@admin.register(models.Currency, site=admin_site)
class CurrencyAdmin(admin.ModelAdmin):
    pass


@admin.register(models.Symbol, site=admin_site)
class SymbolAdmin(admin.ModelAdmin):
    pass


@admin.register(models.Instrument, site=admin_site)
class InstrumentAdmin(admin.ModelAdmin):
    pass


@admin.register(models.ExchangeCredentials, site=admin_site)
class ExchangeCredentialsAdmin(admin.ModelAdmin):
    pass


@admin.register(models.Bot, site=admin_site)
class BotAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')

    def name(self, obj):
        return str(obj)
