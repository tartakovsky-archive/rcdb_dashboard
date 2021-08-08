import asyncio
import logging

import requests
from redis import StrictRedis
from celery import shared_task
from django.conf import settings
from rcdb_commons.lib.helpers.graceful_killer import GracefulKiller
from rcdb_commons.lib.stores import CredentialsStore, DataStore

from .models import Bot, ExchangeCredentials
from .services import S3DBDumper, BotStatisticUpdater, update_account_statistics, \
    update_accounts_pnl, balance_updater, RedisSimpleLock


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
def t_schedule_update_account_statistics():
    logging.info('started task: <t_schedule_update_account_statistics>')
    for exchange_credentials in ExchangeCredentials.objects.filter(exchange__name='binance'):
        if exchange_credentials.meta:
            t_update_account_statistics.delay(exchange_credentials.id)
    logging.info('ended task: <t_schedule_update_account_statistics>')


@shared_task
def t_update_account_statistics(exchange_credentials_id: int):
    logging.info(f'started task: <t_update_account_statistics> for {exchange_credentials_id}')
    try:
        update_account_statistics(
            DataStore(settings.DATASTORE_URL, settings.DATASTORE_TOKEN),
            ExchangeCredentials.objects.get(pk=exchange_credentials_id)
        )
    except ExchangeCredentials.DoesNotExist:
        logging.warning(
            f'<t_update_account_statistics>: instance with id: {exchange_credentials_id} does not exist'
        )
    except requests.exceptions.RequestException as e:
        logging.warning(f'<t_update_account_statistics>: request error {e}')
    except Exception:
        logging.exception(f'<t_update_account_statistics>: unexpected error for {exchange_credentials_id}')

    logging.info(f'ended task: <t_update_account_statistics> for {exchange_credentials_id}')


@shared_task
def t_balance_updater():
    logging.info('started task: <t_balance_updater>')

    lock = RedisSimpleLock(
        StrictRedis(settings.REDIS_HOST, settings.REDIS_PORT, password=settings.REDIS_PASSWORD),
        't_balance_updater_lock'
    )

    if lock.is_locked():
        logging.info('<t_balance_updater> already running')
        return

    lock.lock()

    try:
        data_store = DataStore(settings.DATASTORE_URL, settings.DATASTORE_TOKEN)
        credentials_store = CredentialsStore(
            settings.CREDENTIALSTORE_URL,
            settings.CREDENTIALSTORE_TOKEN,
            settings.CREDENTIALSTORE_VAULT,
        )

        asyncio.run(
            balance_updater(
                credentials_store,
                data_store,
                healthcheck=lock.lock,
                binance_proxies=settings.BINANCE_PROXIES,
                graceful_killer=GracefulKiller()
            )
        )
    except Exception as e:
        logging.exception(f'<t_balance_updater>: unexpected error {e}')

    finally:
        lock.release()
        logging.info('<t_balance_updater>: released')

    logging.info('ended task: <t_balance_updater>')


@shared_task
def t_update_accounts_pnl():
    logging.info('started task: <t_update_accounts_pnl>')
    try:
        update_accounts_pnl(DataStore(settings.DATASTORE_URL, settings.DATASTORE_TOKEN))
    except requests.exceptions.RequestException as e:
        logging.warning(f'<t_update_accounts_pnl>: request error {e}')
    except Exception:
        logging.exception('<t_update_accounts_pnl>: unexpected error')

    logging.info('ended task: <t_update_accounts_pnl>')


@shared_task
def t_backup_db():
    logging.info('started task: <t_backup_db>')
    try:
        S3DBDumper(bucket_name=settings.BUCKET_NAME).dump()
    except Exception:
        logging.exception('<t_backup_db>: unexpected error')

    logging.info('ended task: <t_backup_db>')
