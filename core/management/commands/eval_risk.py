import time
import ccxt

from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import Bot

import logging
logging.basicConfig()
logging.getLogger().setLevel(settings.LOG_LEVEL)


class Command(BaseCommand):
    help = 'Displays current time'

    def handle(self, *args, **kwargs):
        while True:
            bots = Bot.objects.filter(is_active=True)

            for bot in bots:
                try:
                    bot_signal = bot.predict_and_push_signal()
                    if bot_signal is not None:
                        logging.info(f"new bot_signal: {bot_signal}")
                except (ccxt.base.errors.RequestTimeout,):
                    pass

            time.sleep(2)
