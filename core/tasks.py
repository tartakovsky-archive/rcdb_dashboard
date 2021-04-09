import logging

import ccxt
import requests
from celery import shared_task
from django.conf import settings
from rcdb_commons.data_store import DataStore

from .models import Bot, ExchangeCredentials
from .services import BotStatisticUpdater, snapshot_account_balances


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


@shared_task
def t_schedule_snapshot_balances():
    logging.info('started task: <t_schedule_snapshot_balances>')
    for exchange_credentials in ExchangeCredentials.objects.all():
        if exchange_credentials.parameters:
            t_snapshot_exchange_credentials_balances.delay(exchange_credentials.id)
    logging.info('ended task: <t_schedule_snapshot_balances>')


@shared_task
def t_snapshot_exchange_credentials_balances(exchange_credentials_id: int):
    logging.info(f'started task: <t_snapshot_exchange_credentials_balances> for {exchange_credentials_id}')
    try:
        snapshot_account_balances(
            ExchangeCredentials.objects.get(pk=exchange_credentials_id)
        )
    except ExchangeCredentials.DoesNotExist:
        logging.warning(
            f'<t_snapshot_exchange_credentials_balances>: instance with id: {exchange_credentials_id} does not exist'
        )
    except ccxt.errors.NetworkError as e:
        logging.warning(
            f'<t_snapshot_exchange_credentials_balances>: instance with id: {exchange_credentials_id} NetworkError {e}'
        )
    except Exception:
        logging.exception(f'<t_snapshot_exchange_credentials_balances>: unexpected error for {exchange_credentials_id}')

    logging.info(f'ended task: <t_snapshot_exchange_credentials_balances> for {exchange_credentials_id}')
