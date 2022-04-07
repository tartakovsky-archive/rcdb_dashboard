from django.core.management.base import BaseCommand
from core.models import ExchangeCredentials
from core.services import df_from_list


class Command(BaseCommand):

    def handle(self, *args, **options):
        for ex in ExchangeCredentials.objects.all():
            if ex.statistics and 'trades' in ex.statistics and ex.statistics['trades']:
                ex.set_trades(df_from_list(ex.statistics['trades']))
                ex.statistics = {k: v for k, v in ex.statistics.items() if k != 'trades'}
                ex.save()
