import asyncio
import logging

import ccxt
import requests
from celery import shared_task
from django.conf import settings
from rcdb_commons.lib.stores import CredentialsStore, DataStore

from .models import Bot, ExchangeCredentials
from .services import S3DBDumper, BotStatisticUpdater, snapshot_account_balances, \
    update_account_statistics, update_accounts_pnl, snapshot_ascendex_balances


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
    for exchange_credentials in ExchangeCredentials.objects.filter(exchange__name='binance'):
        t_snapshot_exchange_credentials_balances.delay(exchange_credentials.id)
    logging.info('ended task: <t_schedule_snapshot_balances>')


@shared_task(time_limit=59)
def t_snapshot_ascendex_balances():
    logging.info('started task: <t_snapshot_ascendex_balances>')
    exchange_credentials_list = \
        list(ExchangeCredentials.objects.select_related('exchange').filter(exchange__name='ascendex'))

    snapshots = asyncio.run(
        snapshot_ascendex_balances(
            CredentialsStore(
                settings.CREDENTIALSTORE_URL,
                settings.CREDENTIALSTORE_TOKEN,
                settings.CREDENTIALSTORE_VAULT
            ),
            exchange_credentials_list
        )
    )

    exchange_credential: ExchangeCredentials
    for exchange_credential, snapshot in snapshots:
        if snapshot is not None:
            exchange_credential.refresh_from_db()
            exchange_credential.set_balance_snapshot(snapshot)
    logging.info('ended task: <t_snapshot_ascendex_balances>')


@shared_task
def t_snapshot_exchange_credentials_balances(exchange_credentials_id: int):
    logging.info(f'started task: <t_snapshot_exchange_credentials_balances> for {exchange_credentials_id}')
    try:
        exchange_credentials: ExchangeCredentials = (
            ExchangeCredentials
            .objects
            .select_related('exchange')
            .get(pk=exchange_credentials_id)
        )
        snapshot = asyncio.run(
            snapshot_account_balances(
                exchange_credentials,
                DataStore(settings.DATASTORE_URL, settings.DATASTORE_TOKEN),
                CredentialsStore(
                    settings.CREDENTIALSTORE_URL,
                    settings.CREDENTIALSTORE_TOKEN,
                    settings.CREDENTIALSTORE_VAULT
                )
            )
        )
        if snapshot is not None:
            exchange_credentials.refresh_from_db()
            exchange_credentials.set_balance_snapshot(snapshot)

    except ExchangeCredentials.DoesNotExist:
        logging.warning(
            f'<t_snapshot_exchange_credentials_balances>: instance with id: {exchange_credentials_id} does not exist'
        )
    except ccxt.errors.NetworkError as e:
        logging.error(
            f'<t_snapshot_exchange_credentials_balances>: instance with id: {exchange_credentials_id} NetworkError {e}'
        )
    except Exception:
        logging.exception(f'<t_snapshot_exchange_credentials_balances>: unexpected error for {exchange_credentials_id}')

    logging.info(f'ended task: <t_snapshot_exchange_credentials_balances> for {exchange_credentials_id}')


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
