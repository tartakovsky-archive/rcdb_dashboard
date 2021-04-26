from django.views.generic import ListView, DetailView
from django.db.models import Count, Sum, Q
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import Owner, ExchangeCredentials


class OwnerUserPermissionFilterMixin:
    def filter_by_user(self, queryset):
        if not self.request.user.is_staff:
            filters_params = {
                Owner: {'user': self.request.user},
                ExchangeCredentials: {'owner__user': self.request.user},
            }
            queryset = queryset.filter(**(filters_params[self.model]))
        return queryset


class BotStatisticListView(OwnerUserPermissionFilterMixin, LoginRequiredMixin, ListView):
    model = Owner
    template_name = 'bot_statistic/list.html'
    context_object_name = 'owners'

    def get_queryset(self):
        is_active_condition = dict(
            filter=(Q(exchangecredentials__bot__is_active=True) if 'active_bots' in self.request.GET else {})
        )
        return self.filter_by_user(
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
            .filter(bots_count__gte=1)
        )


class ExchangeBalancesListView(OwnerUserPermissionFilterMixin, LoginRequiredMixin, ListView):
    model = Owner
    template_name = 'bot_balance/list.html'
    context_object_name = 'owners'

    def get_queryset(self):
        q = self.filter_by_user(
            Owner
            .objects
            .filter(exchangecredentials__visible=True)
            .distinct()
            .order_by('order_id', 'name')
        )
        return q.all()


class ExchangeBalancesDetailView(OwnerUserPermissionFilterMixin, LoginRequiredMixin, DetailView):
    model = ExchangeCredentials
    template_name = 'bot_balance/detail.html'
    context_object_name = 'creds'

    def get_queryset(self):
        return self.filter_by_user(super().get_queryset())
