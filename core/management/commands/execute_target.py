import time

from django.conf import settings
from django.core.management.base import BaseCommand

from core.libs.helpers.ccxt import CcxtBotExecutor
from core.models import Bot, BotTargetState

import logging
logging.basicConfig()
logging.getLogger().setLevel(settings.LOG_LEVEL)


class Command(BaseCommand):
    help = 'Displays current time'

    def handle(self, *args, **kwargs):
        while True:
            try:
                for bot_target in BotTargetState.objects.filter(is_active=True):
                    ccxt_manager = CcxtBotExecutor(bot_target.bot)
                    order_result = ccxt_manager.execute_target_state(bot_target)
                    if order_result is not None:
                        logging.info(f"new target state executed: {order_result}")
            except Exception as ex:
                logging.exception("Target execution unhandled exception")

            time.sleep(1)

            from django.db import connection
            connection.close_all()


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