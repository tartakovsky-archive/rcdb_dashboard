import os
import json
import time
import ccxt
import math
from joblib import Parallel, delayed
from django.core.management.base import BaseCommand

from core.libs.helpers.ccxt import CcxtBotExecutor
from core.models import Symbol, Consolidator, ExchangeCredentials, Instrument, Bot, BotTargetState, BotSignal, BotOrderLog


class Command(BaseCommand):
    help = 'Displays current time'

    def handle(self, *args, **kwargs):
        # if BotSignal.objects.all().count() == 0:
        #     BotSignal.push_signal(Bot.objects.get(id=1), 2)

        while True:
            try:
                for bot_target in BotTargetState.objects.filter(is_active=True):
                    ccxt_manager = CcxtBotExecutor(bot_target.bot)
                    order_result = ccxt_manager.execute_target_state(bot_target)
            except Exception as ex:
                print("Got exception: ", ex)

            time.sleep(5)