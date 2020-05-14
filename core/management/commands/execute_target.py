import time

from django.db import DatabaseError, transaction
from django.db.utils import InterfaceError
from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import BotTargetState

import logging
logging.basicConfig()
logging.getLogger().setLevel(settings.LOG_LEVEL)

@transaction.atomic
def execute_target_state():
    bot_targets = BotTargetState.objects.filter(is_active=True).select_for_update(skip_locked=True)[0:1]
    if not bot_targets:
        return
    bot_target = bot_targets[0]

    order_result = bot_target.execute()

    if order_result is not None:
        logging.info(f"new target state executed: {order_result}")

    return order_result


class Command(BaseCommand):
    help = 'Displays current time'

    def handle(self, *args, **kwargs):
        while True:
            try:
                execute_target_state()
            except DatabaseError:
                # When multiple execute_target process running concurrently race condition can be observed.
                # This scenario is handle by Django's `select_for_update(nowait=True, skip_locked=True)` query,
                # which will skip locked objects or raise `django.db.DatabaseError`
                # on access attempt to the locked target_state object.
                raise
            except InterfaceError:
                logging.exception("There is no space left on device (It's not 100% true, but the most common scenario)")
                return
            except Exception:
                logging.exception("BotTargetState execution unhandled exception")

            time.sleep(1)
