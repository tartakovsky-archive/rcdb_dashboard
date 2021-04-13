from django.views.generic import ListView, DetailView
from django.db.models import Count, Sum, Q, FloatField, IntegerField
from django.db.models.functions import Cast
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.urls import reverse_lazy

from .models import Owner


class BotStatisticListView(LoginRequiredMixin, ListView):
    model = Owner
    login_url = reverse_lazy('admin:index')
    template_name = 'bot_statistic/list.html'
    context_object_name = 'owners'

    def get_queryset(self):
        is_active_condition = dict(
            filter=(Q(exchangecredentials__bot__is_active=True) if 'active_bots' in self.request.GET else {})
        )
        return (
            Owner
            .objects
            .annotate(
                total_equity=Sum(
                    'exchangecredentials__bot__botstatistic__equity',
                    **is_active_condition
                ),
                bots_count=Count(
                    'exchangecredentials__bot',
                    **is_active_condition
                )
            )
        )


class TotalUsdAnnotateMixin:
    def annotate(self, queryset):
        return queryset.annotate(
            total_usd=Sum(
                Cast(
                    KeyTextTransform('total_usd', 'exchangecredentials__balance_snapshot'),
                    FloatField()
                )
            ),
            h24_usd_volume=Sum(
                Cast(
                    KeyTextTransform('h24_usd_volume', 'exchangecredentials__statistics'),
                    FloatField()
                )
            ),
            h24_trades_count=Sum(
                Cast(
                    KeyTextTransform('h24_trades_count', 'exchangecredentials__statistics'),
                    IntegerField()
                )
            ),
        )


class ExchangeBalancesListView(TotalUsdAnnotateMixin, LoginRequiredMixin, ListView):
    model = Owner
    login_url = reverse_lazy('admin:index')
    template_name = 'bot_balance/list.html'
    context_object_name = 'owners'

    def get_queryset(self):
        return self.annotate(
            Owner
            .objects
            .filter(
                exchangecredentials__balance_snapshot_created__isnull=False
            )

        )


class ExchangeBalancesDetailView(TotalUsdAnnotateMixin, LoginRequiredMixin, DetailView):
    model = Owner
    login_url = reverse_lazy('admin:index')
    template_name = 'bot_balance/detail.html'
    context_object_name = 'owner'

    def get_queryset(self):
        return self.annotate(super().get_queryset())
