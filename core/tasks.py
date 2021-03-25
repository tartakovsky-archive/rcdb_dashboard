import logging

import requests
from celery import shared_task
from django.conf import settings

from .models import Bot
from .helpers.data_store import DataStore
from .services import BotStatisticUpdater


@shared_task
def t_schedule_update_bot_statistic():
    logging.info('started task: <t_schedule_update_bot_statistic>')
    for bot in Bot.objects.filter(is_active=True):
        t_update_bot_statistic.delay(bot.id)
    logging.info('ended task: <t_schedule_update_bot_statistic>')


@shared_task
def t_update_bot_statistic(bot_id: int):
    logging.info(f'started task: <t_update_bot_statistic> for {bot_id}')
    try:
        datastore = DataStore(settings.DATASTORE_URL, settings.DATASTORE_TOKEN)
        BotStatisticUpdater(datastore).update(bot_id)

    except Bot.DoesNotExist:
        logging.warning(f'<t_update_bot_statistic>: instance with id: {bot_id} does not exist')

    except requests.exceptions.RequestException as e:
        logging.warning(f'<t_update_bot_statistic>: request error {e}')

    except Exception:
        logging.exception(f'<t_update_bot_statistic>: unexpected error for {bot_id}')

    logging.info(f'ended task: <t_update_bot_statistic> for {bot_id}')
