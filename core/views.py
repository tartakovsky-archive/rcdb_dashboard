from django.views.generic import ListView
from django.db.models import Sum, Q

from .models import Account


class AccountBotStatisticListView(ListView):
    model = Account
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
