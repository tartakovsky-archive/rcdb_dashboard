from django.contrib import admin
from django.db.models import JSONField
from django_json_widget.widgets import JSONEditorWidget
# from rcdb_commons.lib.schemas import strategy_configs

from core import models


class CustomJSONEditorWidget(JSONEditorWidget):
    template_name = 'json_widget.html'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['config_templates'] = [
            # strategy_configs.AdminConfigInput(config_type=cls().config_type).dict()
            # for cls in strategy_configs.STRATEGY_CONFIG_CLASS_MAP.values()
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
    list_display = ('name', 'label', 'account_type', 'visible', 'ignore_balance', 'ignore_datapipes', 'order_id')
    list_editable = ('label', 'account_type', 'visible', 'ignore_balance', 'ignore_datapipes', 'order_id')
    exclude = ('balance_snapshot', 'balance_snapshot_created', 'statistics')


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
