import pandas as pd

from django.contrib import admin
from core.models import *


class ExchangeAdmin(admin.ModelAdmin):
    pass
admin.site.register(Exchange, ExchangeAdmin)


class CurrencyAdmin(admin.ModelAdmin):
    pass
admin.site.register(Currency, CurrencyAdmin)


class SymbolAdmin(admin.ModelAdmin):
    pass
admin.site.register(Symbol, SymbolAdmin)


class InstrumentAdmin(admin.ModelAdmin):
    pass
admin.site.register(Instrument, InstrumentAdmin)


class ConsolidatorAdmin(admin.ModelAdmin):
    list_display = ('name', 'latest_update',)

    def name(self, obj: Consolidator):
        return str(obj)

    def latest_update(self, obj: Consolidator):
        return f"{pd.to_datetime(obj.update_timestamp * 1000000000)}"

    latest_update.allow_tags = True
    latest_update.short_description = 'Latest bar datetime'
admin.site.register(Consolidator, ConsolidatorAdmin)


class ExchangeCredentialsAdmin(admin.ModelAdmin):
    pass
admin.site.register(ExchangeCredentials, ExchangeCredentialsAdmin)


class BotSizingAdmin(admin.ModelAdmin):
    pass
admin.site.register(BotSizing, BotSizingAdmin)


class BotAdmin(admin.ModelAdmin):
    pass
admin.site.register(Bot, BotAdmin)


class BotSignalAdmin(admin.ModelAdmin):
    list_display = ('name', 'latest_update', 'signal')

    def name(self, obj: BotSignal):
        return str(obj)

    def latest_update(self, obj: BotSignal):
        return f"{pd.to_datetime(obj.timestamp_consolidator * 1000000000)}"
admin.site.register(BotSignal, BotSignalAdmin)


class BotTargetStateAdmin(admin.ModelAdmin):
    model = BotTargetState
    list_display = ('name', 'latest_update', 'get_performance_log', 'get_signal', 'get_instrument_target_size',
                    'get_instrument_target_execution_price', 'get_order_executed_size', 'get_latest_position')

    list_filter = ('bot',)

    def get_signal(self, obj):
        return round(obj.bot_signal.signal, 4)

    def get_performance_log(self, obj: BotTargetState):
        log = obj.bot_signal.botperformancelog_set.get()
        return f"""
        balance={round(log.balance, 2)}\r\n\r\n
        unrealized_pnl={round(log.unrealized_pnl, 2)}\r\n\r\n
        exposure={round(log.exposure, 2)}\r\n\r\n
        """

    def get_instrument_target_size(self, obj):
        return obj.instrument_target_size

    def get_instrument_target_execution_price(self, obj):
        return obj.instrument_target_execution_price

    def name(self, obj: BotTargetState):
        return str(obj)

    def latest_update(self, obj: BotTargetState):
        return f"{pd.to_datetime(obj.bot_signal.timestamp_consolidator * 1000000000)}"

    def get_order_executed_size(self, obj: BotTargetState):
        return " // ".join([f"{o.price_avg, o.size}" for o in obj.botorderlog_set.all()])

    def get_latest_position(self, obj: BotTargetState):
        positions = obj.botpositionlog_set.all().order_by('-id')

        if positions:
            p = positions[0]
            return f"{p.size} (price avg {p.price_avg})"

        return ""

admin.site.register(BotTargetState, BotTargetStateAdmin)


class BotPositionLogAdmin(admin.ModelAdmin):
    list_display = ('get_name', 'price_avg', 'size', 'get_bot_target')

    def get_name(self, obj):
        return str(obj)

    def get_price_avg(self, obj):
        return obj.price_avg

    def get_size(self, obj):
        return obj.size

    def get_bot_target(self, obj):
        return str(obj.bot_target_state)
admin.site.register(BotPositionLog, BotPositionLogAdmin)


class BotOrderLogAdmin(admin.ModelAdmin):
    list_display = ('get_name',)

    def get_name(self, obj):
        return str(obj)
admin.site.register(BotOrderLog, BotOrderLogAdmin)

