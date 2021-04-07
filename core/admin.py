from django.contrib import admin
from django.db.models import JSONField
from django_json_widget.widgets import JSONEditorWidget
from rcdb_commons.schemas import bot as bot_schemas

from core import models


class CustomJSONEditorWidget(JSONEditorWidget):
    template_name = 'json_widget.html'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['config_templates'] = [
            bot_schemas.AdminConfigInput(
                **{'config_type': bot_schemas.OwnLongBotConfig().config_type}
            ).dict(),
            bot_schemas.AdminConfigInput(
                **{'config_type': bot_schemas.OwnShortBotConfig().config_type}
            ).dict()
        ]
        return context


class CustomJsonWidgetMixin:
    formfield_overrides = {
        JSONField: {
            'widget': CustomJSONEditorWidget(
                mode='form',
                options={
                    'maxVisibleChilds': 100000
                }
            )
        }
    }


class JsonWidgetMixin:
    formfield_overrides = {
        JSONField: {
            'widget': JSONEditorWidget(
                mode='form',
                options={
                    'maxVisibleChilds': 100000
                }
            )
        }
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
class ExchangeCredentialsAdmin(admin.ModelAdmin):
    exclude = ('balance_snapshot', 'balance_snapshot_created')


@admin.register(models.Owner)
class OwnerAdmin(admin.ModelAdmin):
    pass


@admin.register(models.BotStatistic)
class BotStatisticAdmin(admin.ModelAdmin):
    pass


@admin.register(models.Bot)
class BotAdmin(CustomJsonWidgetMixin, admin.ModelAdmin):
    list_display = ('name', 'is_active')

    def name(self, obj):
        return str(obj)
