from django.views.generic import ListView
from django.db.models import Count, Sum, Q
from django.contrib.auth.mixins import LoginRequiredMixin
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
