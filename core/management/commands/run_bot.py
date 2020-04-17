import time
import ccxt

from django.core.management.base import BaseCommand
from core.models import Bot


class Command(BaseCommand):
    help = 'Displays current time'

    def handle(self, *args, **kwargs):
        while True:
            bots = Bot.objects.filter(is_active=True)

            for bot in bots:
                try:
                    bot_signal = bot.predict_and_push_signal()
                except (ccxt.base.errors.RequestTimeout):
                    pass

            time.sleep(2)
