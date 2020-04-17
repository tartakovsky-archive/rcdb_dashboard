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
        # return debug()
        # if BotSignal.objects.all().count() == 0:
        #     BotSignal.push_signal(Bot.objects.get(id=1), 2)

        while True:
            try:
                for bot_target in BotTargetState.objects.filter(is_active=True):
                    ccxt_manager = CcxtBotExecutor(bot_target.bot)
                    order_result = ccxt_manager.execute_target_state(bot_target)
            except Exception as ex:
                print("Got exception: ", ex)


            time.sleep(1)


def debug():
    # bot_parent = Bot.objects.get(id=3)
    # signal = BotSignal.push_signal(bot_parent, 0.4)
    #
    bot_child = Bot.objects.get(id=3)
    # target_child = BotTargetState.objects.get(bot=bot_child, is_active=True)
    ccxt_manager = CcxtBotExecutor(bot_child)
    print(ccxt_manager.create_order(0.001))
    # print(ccxt_manager.get_balance())
    # print(ccxt_manager.get_ticker())
    # print(ccxt_manager.get_position())

    # order_result = ccxt_manager.execute_target_state(target_child)