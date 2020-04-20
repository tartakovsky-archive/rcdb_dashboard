import io
import pandas as pd

from django.contrib import admin
from django.conf import settings
from core.models import *

from django.contrib.admin import AdminSite
from django.http import HttpResponse, StreamingHttpResponse


class MyAdminSite(AdminSite):
    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        urls += [
            path('get_cons_data/', self.admin_view(self.my_view))
        ]
        return urls

    def get_cons_data(self, request):
        date_start = request.GET.get("date_start", None)
        date_end = request.GET.get("date_end", None)
        cons_id = request.GET.get("cons_id")
        format = request.GET.get("format", "html")

        df = pd.read_hdf(f"{settings.BARS_DIRECTORY}/{cons_id}.h5", key='table')
        df.index = pd.to_datetime((df.index * 1e9).astype(int))

        if date_start is not None:
            df = df[df.index >= date_start]

        if date_end is not None:
            df = df[df.index >= date_end]

        if format == "html":
            response_content = df.to_html()
            return HttpResponse(response_content)
        elif format == "csv":
            response_content = df.to_csv()
            return HttpResponse(response_content)

admin_site = MyAdminSite()


@admin.register(Exchange, site=admin_site)
class ExchangeAdmin(admin.ModelAdmin):
    pass


class CurrencyAdmin(admin.ModelAdmin):
    pass


admin_site.register(Currency, CurrencyAdmin)


class SymbolAdmin(admin.ModelAdmin):
    pass


admin_site.register(Symbol, SymbolAdmin)


class InstrumentAdmin(admin.ModelAdmin):
    pass


admin_site.register(Instrument, InstrumentAdmin)


class ConsolidatorAdmin(admin.ModelAdmin):
    list_display = ('name', 'latest_update',)

    def name(self, obj: Consolidator):
        return str(obj)

    def latest_update(self, obj: Consolidator):
        return f"{pd.to_datetime(obj.update_timestamp * 1000000000)}"

    latest_update.allow_tags = True
    latest_update.short_description = 'Latest bar datetime'


admin_site.register(Consolidator, ConsolidatorAdmin)


class ExchangeCredentialsAdmin(admin.ModelAdmin):
    pass


admin_site.register(ExchangeCredentials, ExchangeCredentialsAdmin)


class BotSizingAdmin(admin.ModelAdmin):
    pass


admin_site.register(BotSizing, BotSizingAdmin)


class BotAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')

    def name(self, obj: BotSignal):
        return str(obj)


admin_site.register(Bot, BotAdmin)


class BotSignalAdmin(admin.ModelAdmin):
    list_display = ('name', 'latest_update', 'signal')

    def name(self, obj: BotSignal):
        return str(obj)

    def latest_update(self, obj: BotSignal):
        return f"{pd.to_datetime(obj.timestamp_consolidator * 1000000000)}"


admin_site.register(BotSignal, BotSignalAdmin)


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


admin_site.register(BotTargetState, BotTargetStateAdmin)


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


admin_site.register(BotPositionLog, BotPositionLogAdmin)


class BotOrderLogAdmin(admin.ModelAdmin):
    list_display = ('get_name',)

    def get_name(self, obj):
        return str(obj)


admin_site.register(BotOrderLog, BotOrderLogAdmin)


class BotMlConfigAdmin(admin.ModelAdmin):
    list_display = ('get_name',)

    def get_name(self, obj):
        return str(obj)


admin_site.register(BotMlConfig, BotMlConfigAdmin)