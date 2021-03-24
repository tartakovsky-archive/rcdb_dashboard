from django.views.generic import ListView
from django.db.models import Sum, Q
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy

from .models import Account


class AccountBotStatisticListView(LoginRequiredMixin, ListView):
    model = Account
    login_url = reverse_lazy('admin:index')
    template_name = 'acccount_bot_statistic/list.html'
    context_object_name = 'accounts'

    def get_queryset(self):
        return (
            Account
            .objects
            .annotate(
                total_equity=Sum(
                    'bot__botstatistic__equity',
                    **(dict(filter=Q(bot__is_active=True) if 'active_bots' in self.request.GET else {}))
                )
            )
        )
