from django.core.management.base import BaseCommand
from core.models import ExchangeCredentials


class Command(BaseCommand):

    def handle(self, *args, **options):
        for ex in ExchangeCredentials.objects.all():
            if ex.balance_snapshot and 'balances' in ex.balance_snapshot:
                ex.balance_snapshot_clean = {k: v for k, v in ex.balance_snapshot.items() if k != 'balances'}

            if ex.statistics and 'trades' in ex.statistics:
                ex.statistics_clean = {k: v for k, v in ex.statistics.items() if k != 'trades'}

            ex.save()
