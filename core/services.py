import io
import json
import threading
import time
import hmac
import base64
import hashlib
import logging
import asyncio
import operator
import datetime
from typing import Optional, Dict, List, Tuple, Union, Iterable, Callable

import pytz
import ccxt.async_support as ccxt
import boto3
import pandas as pd
import requests
from ccxt import BadSymbol, AuthenticationError
from django.utils import timezone
from django.core import management
from rcdb_commons.lib.helpers.graceful_killer import GracefulKiller
from rcdb_commons.lib.schemas.exchange import AccountType, SymbolEmpty, TransferType
from rcdb_commons.lib.stores import CredentialsStore, DataStore, DataType

from .forms import ReportType, RebatesForm, RebateCurrency, TimeframeForm
from .models import Bot, BotStatistic, ExchangeCredentials


class Ascendex(ccxt.ascendex):
    def __init__(self, params):
        self._api_key = params['apiKey']
        self._secret = params['secret']
        super(Ascendex, self).__init__(params)

    async def fetch_balance(self, params={}):
        if params.get('account-category') == 'futures':
            return await self._fetch_future_balance()
        return await super().fetch_balance(params)

    async def _fetch_future_balance(self):
        account_id = (await self.fetch_accounts())[0]['id']
        api_path = 'v2/futures/position'
        url = f'https://ascendex.com/{account_id}/api/pro/{api_path}'
        ts, auth_headers = self.make_auth_headers(api_path)
        res = await self.fetch(url, headers=auth_headers)
        return {'info': {'data': res['data']['collaterals']}}

    def make_auth_headers(self, path):
        ts = int(time.time() * 1000)
        return ts, self._make_auth_headers(ts, path, self._api_key, self._secret)

    @classmethod
    def _make_auth_headers(cls, timestamp, path, apikey, secret):
        # convert timestamp to string
        if isinstance(timestamp, bytes):
            timestamp = timestamp.decode("utf-8")
        elif isinstance(timestamp, int):
            timestamp = str(timestamp)

        msg = f"{timestamp}+{path}"

        header = {
            "x-auth-key": apikey,
            "x-auth-signature": cls._sign(msg, secret),
            "x-auth-timestamp": timestamp,
        }
        return header

    @staticmethod
    def _sign(msg, secret):
        msg = bytearray(msg.encode("utf-8"))
        hmac_key = base64.b64decode(secret)
        signature = hmac.new(hmac_key, msg, hashlib.sha256)
        signature_b64 = base64.b64encode(signature.digest()).decode("utf-8")
        return signature_b64


class BotStatisticUpdater:
    def __init__(self, datastore: DataStore):
        self.datastore = datastore

    def update(self, bot_id: int):
        bot_statistic = self._get_bot_statistic(bot_id)
        statistic_update = self._fetch_bot_statistic_update(bot_id)
        if not statistic_update:
            logging.warning(f'statistic update not found for bot: {bot_id}')
            return

        if isinstance(bot_statistic.bot.read_config().data.symbol, SymbolEmpty):
            raise Exception(f'Config of Bot({bot_statistic.bot}, id:{bot_id}) has SymbolEmpty symbol')

        self.fill_bot_statistic(
            bot_statistic,
            self.calculate_bot_statistic_from_update(
                statistic_update,
                bot_statistic.bot.read_config().data.symbol.to_ccxt()
            )
        )
        bot_statistic.save()

    def _get_bot_statistic(self, bot_id: int) -> BotStatistic:
        bot = Bot.objects.get(pk=bot_id)
        bot_statistic: Optional[BotStatistic] = bot.botstatistic_set.first()
        if not bot_statistic:
            bot_statistic = BotStatistic(bot_id=bot_id)
        return bot_statistic

    def _fetch_bot_statistic_update(self, bot_id: int) -> Optional[dict]:
        data = self.datastore.read(DataType.bot_performance, {'bot_id': bot_id})
        if len(data) > 0:
            dt: datetime.datetime = data.index.to_pydatetime()[0].replace(tzinfo=pytz.UTC)
            return {"timestamp": dt, **data.to_dict(orient='records')[0]}
        return None

    @staticmethod
    def fill_bot_statistic(bot_statistic: BotStatistic, statistic_data: dict):
        if bot_statistic.updated != statistic_data['updated']:
            bot_statistic.updated = statistic_data['updated']
            bot_statistic.equity = statistic_data['equity']
            bot_statistic.exposure = statistic_data['exposure']
            bot_statistic.employed_capital = statistic_data['employed_capital']
            bot_statistic.price_crypto = statistic_data['price_crypto']
            bot_statistic.price_fair = statistic_data['price_fair']
            bot_statistic.price_forex = statistic_data['price_forex']
            bot_statistic.balance_base_borrowed = statistic_data['balance_base_borrowed']
            bot_statistic.balance_quote_borrowed = statistic_data['balance_quote_borrowed']
        else:
            logging.info(f'{bot_statistic} has not updates')

    @staticmethod
    def calculate_bot_statistic_from_update(update: dict, symbol: str) -> dict:
        price = round(update['price_crypto'], 4)
        price_forex = round(update['price_forex'], 4)
        price_fair = round(update['price_fair'], 4)

        # костыль для расчета value реверсной пары,
        # вместо этого хака нужно будет считать USD value,
        # можно оставить на след итерацию или решить сейчас если есть хорошее решение
        is_reversed_pair = symbol in {'USDT/TRY', 'BUSD/TRY'}
        if is_reversed_pair:
            base_value = update['balance_base'] - update['balance_base_borrowed']
            quote_value = update['balance_quote'] * (1 / price) - update['balance_quote_borrowed'] * (1 / price)
            quote_own = update['balance_base'] - update['balance_base_borrowed'] \
                + update['balance_quote'] * (1 / price) - update['balance_quote_borrowed'] * (1 / price)
        else:
            base_value = update['balance_base'] * price - update['balance_base_borrowed'] * price
            quote_value = update['balance_quote'] - update['balance_quote_borrowed']
            quote_own = update['balance_base'] * price + update['balance_quote'] - update[
                'balance_base_borrowed'] * price - update['balance_quote_borrowed']

        base_own = 0

        equity = base_value + quote_value
        exposure = 0
        if base_value != 0:
            exposure = 100 * round(base_value / (quote_value + base_value), 2)

        base_capital = base_own + update['balance_base_borrowed']
        base_employed = 0 if base_capital == 0 else max(0, 1 - update['balance_base'] / base_capital)
        quote_capital = quote_own + update['balance_quote_borrowed'] + 0.0000001
        quote_employed = 0 if quote_capital == 0 else max(0, 1 - update['balance_quote'] / quote_capital)
        capital_employed = 100 * (quote_employed - base_employed)

        return {
            'updated': update['timestamp'],
            'equity': equity,
            'exposure': exposure,
            'employed_capital': capital_employed,
            'price_crypto': price,
            'price_fair': price_fair,
            'price_forex': price_forex,
            'balance_base_borrowed': update['balance_base_borrowed'],
            'balance_quote_borrowed': update['balance_quote_borrowed']
        }


class AccountConnector:
    _usd_price_cache: Dict[str, float]
    _account_name: str

    class Exceptions:
        class UnsupportedMarketType(Exception):
            pass

    def __init__(self, account_name: str):
        self._account_name = account_name

    @staticmethod
    def _sort_balances(balances: Iterable[dict]) -> List[dict]:
        return sorted(balances, key=lambda x: x['amount_usd'], reverse=True)

    def set_usd_price_cache(self):
        raise NotImplementedError('method is not implemented')

    async def _get_main_balances(self) -> List[dict]:
        raise NotImplementedError('method is not implemented')

    async def _get_spot_balances(self) -> List[dict]:
        raise NotImplementedError('method is not implemented')

    async def _get_cross_margin_balances(self) -> List[dict]:
        raise NotImplementedError('method is not implemented')

    async def _get_isolated_margin_balances(self) -> List[dict]:
        raise NotImplementedError('method is not implemented')

    async def _get_future_usd_m_balances(self) -> List[dict]:
        raise NotImplementedError('method is not implemented')

    async def _get_future_coin_m_balances(self) -> List[dict]:
        raise NotImplementedError('method is not implemented')

    async def fetch_price(self, symbol: str) -> Optional[float]:
        raise NotImplementedError('method is not implemented')

    async def usd_price(self, symbol: str) -> float:
        if symbol not in self._usd_price_cache:
            for pair, is_reversed in [
                (f'{symbol}/USDT', False),
                (f'USDT/{symbol}', True),
                (f'{symbol}/BUSD', False),
                (f'BUSD/{symbol}', True)
            ]:
                price = await self.fetch_price(pair)
                if price is not None:
                    self._usd_price_cache[symbol] = (1 / price) if is_reversed else price
                    break
            else:
                logging.warning(f"Can't find price for {symbol}. Set to 0")
                self._usd_price_cache[symbol] = 0

        return self._usd_price_cache[symbol]

    async def update_amount_usd(self, data: dict) -> dict:
        result = data.copy()
        if 'amount_usd' in result:
            return result

        for field in ['borrowed', 'interest', 'amount']:
            field_btc = f'{field}_btc'
            field_usd = f'{field}_usd'

            if field_btc in data:
                result[field_usd] = data[field_btc] * await self.usd_price('BTC')
            elif field in data:
                if data[field] == 0:
                    result[field_usd] = 0.
                else:
                    result[field_usd] = data[field] * await self.usd_price(data['symbol'])

        return result

    async def get_balance_data(self, type: str) -> Dict[str, Union[List[dict], float]]:
        market_type_method = {
            AccountType.MAIN.value: self._get_main_balances,
            AccountType.SPOT.value: self._get_spot_balances,
            AccountType.CROSS_MARGIN.value: self._get_cross_margin_balances,
            AccountType.ISOLATED_MARGIN.value: self._get_isolated_margin_balances,
            AccountType.USDT_M_FUTURES.value: self._get_future_usd_m_balances,
            AccountType.COIN_M_FUTURES.value: self._get_future_coin_m_balances
        }
        if type not in market_type_method:
            raise self.Exceptions.UnsupportedMarketType(type)

        raw_res = await market_type_method[type]()
        logging.info(f'Raw balance for {self._account_name} {type}: {raw_res}')
        result = {
            'balances': list(
                filter(
                    lambda x: x.get('amount_usd', 0.) == 0. and x.get('amount', 0.) != 0 or sum(
                        abs(x.get(k, 0.)) for k in ('amount_usd', 'borrowed_usd', 'interest_usd')
                    ) >= 1.,
                    self._sort_balances(
                        [
                            await self.update_amount_usd(data)
                            for data in raw_res
                        ]
                    )
                )
            )
        }
        if type in {
            AccountType.CROSS_MARGIN.value,
            AccountType.ISOLATED_MARGIN.value
        }:
            result['borrowed_usd'] = sum(map(operator.itemgetter('borrowed_usd'), result['balances']))
            result['interest_usd'] = sum(map(operator.itemgetter('interest_usd'), result['balances']))

        result['total_usd'] = sum(map(operator.itemgetter('amount_usd'), result['balances']))
        return result

    async def close(self):
        raise NotImplementedError('method is not implemented')


class AscendexAccountConnector(AccountConnector):
    def __init__(self, credentials: dict, account_name: str, *args, **kwargs):
        super().__init__(account_name)
        self.api = Ascendex(credentials)
        self.set_usd_price_cache()

    def set_usd_price_cache(self):
        self._usd_price_cache = {'USDT': 1, 'BUSD': 1}

    async def fetch_price(self, symbol: str) -> Optional[float]:
        try:
            res = await self.api.fetch_ticker(symbol)
            price = float(res['bid'] if res['bid'] else res['close'])

            assert price > 0, f'Low price ascendex {res}'

            return price
        except BadSymbol:
            return None

    async def _get_spot_balances(self) -> List[dict]:
        return [
            {'symbol': symbol, 'amount': amount}
            for symbol, amount in (await self.api.fetch_balance())['total'].items()
            if amount
        ]

    async def _get_cross_margin_balances(self) -> List[dict]:
        return [
            {
                'symbol': b['asset'],
                'amount': float(b['totalBalance']),
                'interest': float(b['interest']),
                'borrowed': float(b['borrowed'])
            }
            for b in (await self.api.fetch_balance(params={'account-category': 'margin'}))['info']['data']
        ]

    async def _get_future_usd_m_balances(self) -> List[dict]:
        return [
            {'symbol': b['asset'], 'amount': float(b['balance'])}
            for b in (await self.api.fetch_balance(params={'account-category': 'futures'}))['info']['data']
        ]

    async def close(self):
        await self.api.close()


class BinanceAccountConnector(AccountConnector):
    def __init__(self, credentials: dict, price_api: ccxt.binance, account_name: str):
        super().__init__(account_name)
        self.api = ccxt.binance(self._set_adjust_for_time_difference(credentials))
        self._price_api = price_api
        self.set_usd_price_cache()

        self._spot_lock = asyncio.Lock()

    @staticmethod
    def _set_adjust_for_time_difference(credentials: dict) -> dict:
        credentials = credentials.copy()
        credentials['enableRateLimit'] = True
        if 'options' not in credentials:
            credentials['options'] = {}

        # credentials['options']['adjustForTimeDifference'] = True
        credentials['options']['recvWindow'] = 60000
        return credentials

    def set_usd_price_cache(self):
        self._usd_price_cache = {'USDT': 1, 'ETF': 1, 'BUSD': 1}

    async def fetch_price(self, symbol: str) -> Optional[float]:
        try:
            res = await self._price_api.fetch_ticker(symbol)
            if float(res['bid']) > 0:
                price = float(res['bid'])
            elif float(res['close']) > 0:
                price = float(res['close'])
            else:
                price = float(res['previousClose'])

            assert price > 0, f'Low price binance {res}'

            return price
        except BadSymbol:
            return None

    async def _get_spot_balances(self) -> List[dict]:
        async with self._spot_lock:
            return await self._get_spot_like_balances()

    async def _get_spot_like_balances(self) -> List[dict]:
        return [
            {'symbol': symbol, 'amount': amount}
            for symbol, amount in (await self.api.fetch_balance())['total'].items()
            if amount
        ]

    async def _get_cross_margin_balances(self) -> List[dict]:
        return [
            {
                'symbol': b['asset'],
                'amount': float(b['netAsset']),
                'interest': float(b['interest']),
                'borrowed': float(b['borrowed'])
            }
            for b in (await self.api.sapi_get_margin_account())['userAssets']
        ]

    async def _get_isolated_margin_balances(self) -> List[dict]:
        asset_getter = operator.itemgetter('baseAsset', 'quoteAsset')
        return [
            {
                'pair_symbol': pair_asset['symbol'],
                'symbol': asset['asset'],
                'amount': float(asset['netAsset']),
                'interest': float(asset['interest']),
                'borrowed': float(asset['borrowed']),
                **({} if asset['asset'] in {'USDT', 'BUSD'} else {'amount_btc': float(asset['netAssetOfBtc'])})
            }
            for pair_asset in (await self.api.sapi_get_margin_isolated_account())['assets']
            for asset in asset_getter(pair_asset)
        ]

    async def _get_future_balances(self, market_type) -> List[dict]:
        options = self.api.options.copy()
        try:
            self.api.options = {**options, 'defaultType': market_type}
            positions = []
            for pos in (await self.api.fetch_positions()):
                notional = pos['notional']
                if notional > 0:
                    positions.append(
                        {'symbol': f"Position {pos['symbol']}", 'amount': notional, 'amount_usd': notional}
                    )
            return positions + (await self._get_spot_like_balances())
        except Exception as e:
            raise e
        finally:
            self.api.options = options

    async def _get_future_usd_m_balances(self) -> List[dict]:
        async with self._spot_lock:
            return await self._get_future_balances('future')

    async def _get_future_coin_m_balances(self) -> List[dict]:
        async with self._spot_lock:
            return await self._get_future_balances('delivery')

    async def close(self):
        await asyncio.gather(self.api.close(), self._price_api.close())


class KucoinAccountConnector(AccountConnector):
    def __init__(self, credentials: dict, account_name: str, *args, **kwargs):
        super().__init__(account_name)
        self.api = ccxt.kucoin(credentials)
        self.set_usd_price_cache()

    def set_usd_price_cache(self):
        self._usd_price_cache = {'USDT': 1, 'USDC': 1, 'BUSD': 1}

    async def fetch_price(self, symbol: str) -> Optional[float]:
        try:
            res = await self.api.fetch_ticker(symbol)
            price = float(res['bid'] if res['bid'] else res['close'])

            assert price > 0, f'Low price kucoin {res}'

            return price
        except BadSymbol:
            return None

    async def _fetch_balance(self, params):
        return [
            {'symbol': symbol, 'amount': amount}
            for symbol, amount in (await self.api.fetch_balance(params))['total'].items()
            if amount
        ]

    async def _get_main_balances(self) -> List[dict]:
        return await self._fetch_balance({'type': 'main'})

    async def _get_spot_balances(self) -> List[dict]:
        return await self._fetch_balance({'type': 'trade'})

    async def _get_cross_margin_balances(self) -> List[dict]:
        return [{**data, 'interest': 0, 'borrowed': 0} for data in (await self._fetch_balance({'type': 'margin'}))]

    async def _get_future_usd_m_balances(self) -> List[dict]:
        return await self._fetch_balance({'type': 'contract', 'currency': 'USDT'})

    async def _get_future_coin_m_balances(self) -> List[dict]:
        res = []
        for currency in ['BTC', 'ETH', 'DOT', 'XRP']:
            res += await self._fetch_balance({'type': 'contract', 'currency': currency})
        return res


class RedisSimpleLock:
    def __init__(self, redis, key):
        self.redis = redis
        self.key = key

    def lock(self, expires=60*5):
        self.redis.set(self.key, '1', ex=expires)

    def release(self):
        self.redis.delete(self.key)

    def is_locked(self):
        return self.redis.exists(self.key) != 0


EXCHANGE_ACCOUNT_CONNECTOR_MAP = {
    'binance': BinanceAccountConnector,
    'ascendex': AscendexAccountConnector,
    'kucoin': KucoinAccountConnector
}


class CredentialsRotator:
    def __init__(
        self,
        credentials_store: CredentialsStore,
        graceful_killer: GracefulKiller,
        recheck_interval: int = 30
    ):
        self._credentials_store = credentials_store
        self._credentials: Dict[str, str] = {}
        self._recheck_interval = recheck_interval
        self._graceful_killer = graceful_killer
        self._rotated_names = []
        self._lock = threading.Lock()
        self._thread = None

    def get_secret(self, name: str) -> Optional[dict]:
        if name not in self._credentials:
            with self._lock:
                try:
                    self._credentials[name] = self._credentials_store.get_secret(name, raw=True)
                except Exception as e:
                    logging.exception(f'Creds {name} error:{e}')
                    return None
        return json.loads(self._credentials[name])

    def enable_rotation(self):
        if not self._thread:
            self._thread = threading.Thread(target=self._rotate, daemon=True)
            self._thread.start()
        else:
            logging.warning('Rotation already enabled')

    def get_rotated_names(self) -> List[str]:
        with self._lock:
            names = self._rotated_names
            self._rotated_names = []
        return names

    def _rotate(self):
        while not self._graceful_killer.kill_now:
            logging.info('Start credentials rotations')
            for name in list(self._credentials.keys()):
                try:
                    logging.info(f'Start credentials rotation for {name}')
                    raw_credentials = self._credentials_store.get_secret(name, raw=True)
                    if raw_credentials != self._credentials[name]:
                        logging.info(f'credentials changed for {name}')
                        with self._lock:
                            self._credentials[name] = raw_credentials
                            self._rotated_names.append(name)
                except Exception as e:
                    logging.exception(f'credentials rotator: unexpected error: {e}')

            self._sleep(self._recheck_interval)

    def _sleep(self, seconds: int, sleep_interval: float = 0.1):
        end_ts = time.time() + seconds
        for _ in range(int(seconds / sleep_interval)):
            if self._graceful_killer.kill_now or time.time() >= end_ts:
                return
            time.sleep(sleep_interval)


async def balance_updater(
    credentials_store: CredentialsStore,
    graceful_killer: GracefulKiller,
    proxies: Optional[list] = None,
    sleep_between_rounds: int = 10,
    price_cache_clear_interval: int = 60,
    healthcheck: Optional[Callable] = None
):
    credentials_rotator = CredentialsRotator(credentials_store, graceful_killer, recheck_interval=10)
    binance_price_api = ccxt.binance(
        BinanceAccountConnector._set_adjust_for_time_difference(
            {'aiohttp_proxy': proxies[-1]} if proxies else {}
        )
    )
    credentials_rotator.enable_rotation()
    connector_by_name: Dict[str, AccountConnector] = {}

    last_cache_clear = time.time()

    skip_asc = False
    while not graceful_killer.kill_now:
        logging.info('Start snapshot balances')
        exchange_credentials_list: List[ExchangeCredentials] = (
            ExchangeCredentials
            .objects
            .select_related('exchange')
            .order_by('exchange')
            .all()
            .defer('statistics', 'statistics_clean', 'meta')
        )

        async def dummy():
            return None

        ex: ExchangeCredentials
        rotated_names = set(credentials_rotator.get_rotated_names())
        for i, ex in enumerate(exchange_credentials_list):
            if ex.name not in connector_by_name or ex.name in rotated_names:
                rotated_names.discard(ex.name)
                logging.info(f'Getting credentials for {ex.name}')
                secret = credentials_rotator.get_secret(ex.name)
                if not secret:
                    continue
                account_connector_class = EXCHANGE_ACCOUNT_CONNECTOR_MAP.get(ex.exchange.slug)
                if proxies and account_connector_class in {BinanceAccountConnector, AscendexAccountConnector}:
                    secret['aiohttp_proxy'] = proxies[i % len(proxies)]

                connector_by_name[ex.name] = account_connector_class(
                    secret, price_api=binance_price_api, account_name=ex.name
                )

        tasks = []
        for ex in exchange_credentials_list:
            account_connector = connector_by_name.get(ex.name)
            if not account_connector:
                logging.error(f'No connector for {ex}')
                tasks.append(dummy())
            elif isinstance(account_connector, AscendexAccountConnector) and skip_asc:
                tasks.append(dummy())
            else:
                tasks.append(
                    snapshot_account_balances(
                        exchange_credentials=ex,
                        price_api=binance_price_api,
                        credentials_store=None,
                        account_connector=account_connector
                    )
                )
        logging.info('Waiting snapshots')
        results = await asyncio.gather(*tasks)
        for ex, snapshot in zip(exchange_credentials_list, results):
            if snapshot is not None:
                logging.info(f'Set snapshot for {ex} {snapshot}')
                ex.set_balance_snapshot(snapshot)

        logging.info('End snapshots round')
        if healthcheck:
            healthcheck()

        if graceful_killer.kill_now:
            break

        await asyncio.sleep(sleep_between_rounds)

        skip_asc = True
        if time.time() - last_cache_clear > price_cache_clear_interval:
            skip_asc = False
            logging.info('balance_updater price cache clear')
            for connector in connector_by_name.values():
                connector.set_usd_price_cache()
            last_cache_clear = time.time()

    await asyncio.gather(*[connector.close() for connector in connector_by_name.values()])


async def snapshot_account_balances(
    exchange_credentials: ExchangeCredentials,
    price_api: ccxt.Exchange,
    credentials_store: Optional[CredentialsStore] = None,
    credentials: Optional[dict] = None,
    account_connector: Optional[AccountConnector] = None,
) -> Optional[dict]:
    if exchange_credentials.ignore_balance or not exchange_credentials.visible:
        logging.debug(f'Ignore balance for {exchange_credentials}')
        return {}

    try:
        if not account_connector:
            account_connector_class = EXCHANGE_ACCOUNT_CONNECTOR_MAP.get(exchange_credentials.exchange.slug)
            if not account_connector_class:
                logging.error(f'AccountConnector for {exchange_credentials.exchange.slug} is not implemented')
                return

            if not credentials:
                credentials = credentials_store.get_secret(exchange_credentials.name)

            account_connector = account_connector_class(
                credentials, price_api=price_api, account_name=exchange_credentials.name)

        res = await account_connector.get_balance_data(exchange_credentials.account_type)
        if hasattr(account_connector, 'api') and isinstance(account_connector, BinanceAccountConnector):
            logging.info(f'{exchange_credentials.account_type} {get_weight_str(account_connector.api)}')
        return res
    except BinanceAccountConnector.Exceptions.UnsupportedMarketType as e:
        logging.error(f"Unsupported market type: {e}")
    except AuthenticationError as e:
        logging.error(f"Can't auth to exchange {exchange_credentials}: {e}'")
    except Exception as e:
        logging.exception(f'snapshot_account_balances: unexpected error for {exchange_credentials}: {e}')

    return None


def get_weight_str(api):
    headers = {k: v for k, v in api.last_response_headers.items() if 'weight' in k.lower()}
    proxy = api.aiohttp_proxy
    return f'{proxy} {headers}'


def print_api_weight(api):
    print(get_weight_str(api))


def concat_dfs_safe(dfs: List[pd.DataFrame]) -> pd.DataFrame:
    try:
        df = pd.concat(dfs)
    except ValueError:
        df = pd.DataFrame([])
    return df


class DataStoreDataSynchronizer:
    def __init__(self, datastore: DataStore):
        self.datastore = datastore

    def get_updated_trades(self, exchange_credentials: ExchangeCredentials) -> pd.DataFrame:
        df_local = exchange_credentials.get_trades()
        markets_data = [
            self.fetch_from_datastore(
                data_type=DataType.account_trades,
                since=(
                    max(
                        df_local[df_local.symbol == market].timestamp.max().to_pydatetime(),
                        datetime.datetime.utcnow() - datetime.timedelta(days=8)
                    )
                    if len(df_local) and (df_local.symbol == market).any() else
                    (datetime.datetime.utcnow() - datetime.timedelta(days=8))
                ),
                name=exchange_credentials.name,
                symbol=market,
                account_type=exchange_credentials.account_type
            )
            for market in exchange_credentials.meta.get('markets', [])
        ]
        return self.concat_dfs_safe_with_cut_history([df_local, *markets_data])

    def fetch_from_datastore(self, data_type: DataType, since: datetime.datetime, **params) -> pd.DataFrame:
        df = pd.DataFrame([])
        while True:
            df_batch = self.datastore.read(
                data_type,
                query_params=dict(
                    **params,
                    tail=1500,
                    **({'date_end': df.timestamp.min().isoformat()} if len(df) else {})
                )
            )
            df_batch.reset_index(inplace=True)
            if len(df_batch):
                df = pd.concat([df, df_batch])

            if not len(df_batch) or (df_batch.timestamp <= since).any():
                break

        if len(df):
            df = df[df.timestamp > since]

        return df

    @staticmethod
    def concat_dfs_safe_with_cut_history(dfs: List[pd.DataFrame], td=datetime.timedelta(days=7)) -> pd.DataFrame:
        df = concat_dfs_safe(dfs)
        if len(df):
            df = df[df.timestamp >= (datetime.datetime.utcnow() - td)]
        return df

    @staticmethod
    def get_df_statistics(exchange_credentials: ExchangeCredentials, field: str):
        statistics = exchange_credentials.statistics or {}
        return df_from_list(statistics.get(field, []))


class StatisticsCalculator:
    @classmethod
    def trades_statistics(cls, trades: pd.DataFrame) -> dict:
        statistics = {}
        now = datetime.datetime.utcnow()

        for key, since in [
            ('h1', ((now - datetime.timedelta(hours=1)) if now.minute < 30 else now).replace(minute=30)),
            ('h24', now - datetime.timedelta(days=1)),
            (
                'd7',
                (now - datetime.timedelta(days=now.weekday() % 7)).replace(hour=0, minute=0, second=0, microsecond=0)
            ),
        ]:
            data = trades[trades.timestamp >= since]
            statistics[f'{key}_usd_volume'] = (data.volume_buy_usd + data.volume_sell_usd).sum()
            statistics[f'{key}_trades_count'] = int(
                (data.trades_count_buy + data.trades_count_sell).sum()
            )
        return statistics


class Report:
    def __init__(self, report_form, data_store: DataStore):
        self.report_form = report_form
        self.data_store = data_store

    def generate_report(self) -> dict:
        raise NotImplementedError()

    @classmethod
    def group_field(cls, timeframe: str, timestamp: pd.Series) -> pd.Series:
        return {
            'H': cls._1H_group_field,
            'D': cls._1D_group_field,
            'W': cls._1W_group_field,
            'M': cls._1M_group_field,
        }[timeframe](timestamp)

    @staticmethod
    def _1H_group_field(timestamp: pd.Series) -> pd.Series:
        return (
            timestamp
            .dt.strftime('%d/%m/%Y %H:%M')
            .str.cat((timestamp + datetime.timedelta(hours=1)).dt.strftime(' - %H:%M'))
        )

    @staticmethod
    def _1D_group_field(timestamp: pd.Series) -> pd.Series:
        return (
            timestamp
            .dt.strftime('%d/%m/%Y')
            .str.cat((timestamp + datetime.timedelta(days=1)).dt.strftime(' - %d/%m/%Y'))
        )

    @classmethod
    def _1W_group_field(cls, timestamp: pd.Series) -> pd.Series:
        return timestamp.apply(cls.week_string)

    @staticmethod
    def _1M_group_field(timestamp: pd.Series) -> pd.Series:
        return timestamp.dt.strftime('%Y/%m')

    @classmethod
    def prettify_timestamp_by_timeframe(cls, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        return (
            df
            .copy()
            .sort_values('timestamp')
            .assign(
                timestamp=cls.group_field(timeframe, df.timestamp),
                ts=df.timestamp
            )
            .sort_values('ts', ascending=False)
        )

    @staticmethod
    def week_string(dt: pd.Timestamp) -> str:
        dt = dt.to_pydatetime().date()
        start_of_week = dt - datetime.timedelta(days=dt.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)
        dt_format = '%d/%m/%Y'
        return f'{start_of_week.strftime(dt_format)} - {end_of_week.strftime(dt_format)}'


class PairVolumesReport(Report):
    def generate_report(self) -> dict:
        volumes = self.fetch_report_volumes(unfilled=False).reset_index()
        return {
            'report_data': {
                symbol: self._calculate_summary(df)
                for symbol, df in df_dict_group(volumes, 'symbol').items()
            }
        }

    def _calculate_summary(self, df: pd.DataFrame):
        df = self.prettify_timestamp_by_timeframe(df, self.report_form.cleaned_data['timeframe'])
        df.pct *= 100
        total_volume = df.self_volume.sum()
        total_market_volume = df.market_volume.sum()
        summary = (
            {
                'total_volume': total_volume,
                'total_market_volume': total_market_volume,
                'total_pct': ((total_volume / total_market_volume) if total_market_volume else 0) * 100
            } if len(df) else {
                'total_volume': 0,
                'total_market_volume': 0,
                'total_pct': 0
            }
        )
        summary['data'] = df.to_dict(orient='records')
        return summary

    def fetch_report_volumes(self, unfilled: bool = True) -> pd.DataFrame:
        data = self.report_form.cleaned_data
        return self.data_store.read(
            DataType.report,
            query_params={
                "report_name": "pair_volumes",
                "start_datetime": self.report_form.start.isoformat(),
                "end_datetime": self.report_form.end.isoformat(),
                "timeframe": data['timeframe'],
                "unfilled": unfilled
            }
        )


class FiatVolumesReport(PairVolumesReport):
    def generate_report(self) -> dict:
        volumes = self._fiat_volumes(self.fetch_report_volumes(unfilled=True).reset_index())
        return {
            'report_data': {
                fiat_symbol: self._calculate_summary(df)
                for fiat_symbol, df in df_dict_group(volumes, 'fiat').items()
            }
        }

    def _fiat_volumes(self, df: pd.DataFrame) -> pd.DataFrame:
        fiats = set(RebateCurrency.currencies())
        df['fiat'] = df.symbol.apply(lambda symbol: self._fiat_currency(symbol, fiats))
        df = df[~df.fiat.isna()]
        df['is_base_fiat'] = df.apply(lambda row: row['symbol'].startswith(row['fiat']), axis=1)
        return df

    @staticmethod
    def _fiat_currency(symbol: str, fiats: set) -> Optional[str]:
        base, quote = symbol.split('/')
        if base in fiats:
            return base

        if quote in fiats:
            return quote

        return None

    def _calculate_summary(self, df: pd.DataFrame) -> dict:
        df.loc[df.is_base_fiat, 'self_volume'] = df.loc[df.is_base_fiat, 'self_volume']
        df.loc[~df.is_base_fiat, 'self_volume'] = df.loc[~df.is_base_fiat, 'self_volume_quote']

        df.loc[df.is_base_fiat, 'market_volume'] = df.loc[df.is_base_fiat, 'market_volume']
        df.loc[~df.is_base_fiat, 'market_volume'] = df.loc[~df.is_base_fiat, 'market_volume_quote']
        summary = super(FiatVolumesReport, self)._calculate_summary(df)
        summary.pop('data')
        summary['symbols_data'] = {
            symbol: super(FiatVolumesReport, self)._calculate_summary(symbol_df)
            for symbol, symbol_df in df_dict_group(df, 'symbol').items()
        }
        return summary


class RebateReport(Report):
    def __init__(self, report_form: RebatesForm, data_store: DataStore):
        super().__init__(report_form, data_store)
        form_data = report_form.cleaned_data
        self.exchange_credentials_list = (
            [form_data['exchange_credentials']]
            if form_data['exchange_credentials'] and form_data['type'] == ReportType.BY_ACCOUNT.value else
            ExchangeCredentials.objects.exclude(
                id__in=list(
                    map(operator.attrgetter('id'), form_data['excluded_exchange_credentials'])
                )
            ).defer('statistics', 'balance_snapshot', 'statistics_clean', 'balance_snapshot_clean', 'meta')
        )
        self.exchange_credentials_account_map = {
            (ex.name, ex.account_type): ex for ex in self.exchange_credentials_list
        }

    def generate_report(self) -> dict:
        rebates = self.fetch_report_rebates().reset_index()
        summary_method = {
            ReportType.BY_ACCOUNT: self.calculate_by_account_summary,
            ReportType.OVERALL: self.calculate_overall_summary
        }[self.report_form.cleaned_data['type']]

        return {
            'type': self.report_form.cleaned_data['type'],
            'report_data': {
                symbol: summary_method(df)
                for symbol, df in df_dict_group(rebates, 'symbol').items()
            }
        }

    def fetch_report_rebates(self) -> pd.DataFrame:
        data = self.report_form.cleaned_data
        return self.data_store.read(
            DataType.report,
            query_params={
                "report_name": "rebate",
                "start_datetime": self.report_form.start.isoformat(),
                "end_datetime": self.report_form.end.isoformat(),
                "timeframe": data['timeframe'],
                "currencies": data['currencies'],
                "account": {
                    'name': data['exchange_credentials'].name,
                    'account_type': data['exchange_credentials'].account_type
                } if data['exchange_credentials'] else None,
                "excluded_accounts": [
                    {'name': ex.name, 'account_type': ex.account_type} for ex in data['excluded_exchange_credentials']
                ]
            }
        )

    def calculate_overall_summary(self, rebates: pd.DataFrame) -> dict:
        summary = {
            'total_volume': 0,
            'total_rebate': 0,
            'total_expected_rebate': 0,
            'total_difference': 0,
            'accounts_data': []
        }
        if not len(rebates):
            return summary

        for account, account_rebates in df_dict_group(rebates, ['name', 'account_type']).items():
            account_rebates_pretty_ts = self.prettify_timestamp_by_timeframe(
                account_rebates, self.report_form.cleaned_data['timeframe']
            )
            account_data = self._calculate_overall_totals(account_rebates_pretty_ts)
            account_data['data'] = account_rebates_pretty_ts.to_dict(
                orient='records'
            )
            try:
                account_data['exchange_credentials'] = self.exchange_credentials_account_map[account]
                summary['accounts_data'].append(account_data)
            except KeyError:
                logging.warning(f'No {account} in db')
                name, account_type = account
                rebates = rebates[~((rebates.account_type == account_type) & (rebates.name == name))]

        summary.update(self._calculate_overall_totals(rebates))
        return summary

    def _calculate_overall_totals(self, rebates: pd.DataFrame) -> dict:
        return {
            'total_volume': rebates.volume.sum(),
            'total_rebate': rebates.rebate.sum(),
            'total_expected_rebate': rebates.expected_rebate.sum(),
            'total_difference': rebates.difference.sum()
        }

    def calculate_by_account_summary(self, rebates: pd.DataFrame) -> dict:
        rebates = self.prettify_timestamp_by_timeframe(rebates, self.report_form.cleaned_data['timeframe'])
        summary = (
            {
                'total_volume': rebates.volume.sum(),
                'total_rebate': rebates.rebate.sum(),
                'total_expected_rebate': rebates.expected_rebate.sum(),
                'total_volume_usd': rebates.volume_usd.sum(),
                'total_rebate_usd': rebates.rebate_usd.sum(),
                'total_expected_rebate_usd': rebates.expected_rebate_usd.sum()
            } if len(rebates) else {
                'total_volume': 0,
                'total_rebate': 0,
                'total_expected_rebate': 0,
                'total_volume_usd': 0,
                'total_rebate_usd': 0,
                'total_expected_rebate_usd': 0
            }
        )
        summary['data'] = rebates.to_dict(orient='records')
        return summary


class S3DBDumper:
    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name

    def get_db_data(self) -> io.BytesIO:
        buffer = io.StringIO()
        management.call_command('dumpdata', 'core', 'auth', stdout=buffer)
        buffer.seek(0)
        return io.BytesIO(buffer.read().encode('utf-8'))

    def dump(self):
        buffer = self.get_db_data()
        s3 = boto3.client('s3')
        path = f'dashboard-dump/{datetime.datetime.utcnow().isoformat()}.json'
        s3.upload_fileobj(buffer, self.bucket_name, path)


def update_account_statistics(datastore: DataStore, exchange_credentials: ExchangeCredentials):
    datastore_manager = DataStoreDataSynchronizer(datastore)
    trades = datastore_manager.get_updated_trades(exchange_credentials)

    statistics = {
        **(
            {
                k: exchange_credentials.statistics.get(k)
                for k in [
                    'h1_pnl', 'h1_total_usd', 'h24_pnl', 'h24_total_usd', 'pnl_updated',
                    'h24_transfers_in_volume', 'h1_transfers_in_volume',
                    'h24_transfers_out_volume', 'h1_transfers_out_volume',
                ]
            }
            if exchange_credentials.statistics else
            {}
        ),
        'h1_usd_volume': None,
        'h1_trades_count': None,
        'h24_usd_volume': None,
        'h24_trades_count': None,
        'd7_usd_volume': None,
        'd7_trades_count': None,
        'updated': timezone.now().strftime('%d/%m/%Y %H:%M:%S'),
    }

    statistics = {
        **statistics,
        **(StatisticsCalculator.trades_statistics(trades) if len(trades) else {}),
    }
    exchange_credentials.set_statistics(statistics)
    exchange_credentials.set_trades(trades)


def update_accounts_pnl(datastore: DataStore):
    df_data = {}
    hours = [1, 24]
    date_ends = {}

    utc_now = datetime.datetime.utcnow()
    for hour in hours:
        offset = datetime.timedelta(hours=hour)
        date_end = utc_now - offset
        date_ends[hour] = date_end
        df = datastore.read(
            DataType.balance,
            query_params=dict(
                date_end=date_end.isoformat(),
                tail=1000
            )
        )
        if not len(df):
            logging.warning(f'df h{hour} is empty')
            continue

        deviation = abs(df.index.max() - date_end)
        deviation_threshold = datetime.timedelta(minutes={1: 10, 24: 30}[hour])
        if deviation > deviation_threshold:
            logging.error(
                f'old data deviation from expected too big. deviation: {deviation} max: {deviation_threshold}'
            )
            continue

        df_data[f'h{hour}'] = (
            df[df.index == df.index.max()]
            .groupby(['name', 'account_type'])
            .agg({'amount_usd': 'sum'})
        )

    if not df_data:
        logging.error('No data were received for pnl')

    grouped_transfers = get_transfers_grouped_by_account_name(datastore)
    pnl_updated_string = timezone.now().strftime('%d/%m/%Y %H:%M:%S')

    accounts = (
        ExchangeCredentials
        .objects
        .filter(
            visible=True,
            ignore_balance=False,
            exchange__name='binance',
        )
        .exclude(
            account_type=AccountType.ISOLATED_MARGIN.value
        )
    )
    for account in accounts:
        statistics = (account.statistics or {})
        for hour in hours:
            df_key = f'h{hour}'
            statistics[f'{df_key}_total_usd'] = None
            statistics[f'{df_key}_pnl'] = None
            statistics[f'{df_key}_transfers_in_volume'] = 0
            statistics[f'{df_key}_transfers_out_volume'] = 0
            if df_key not in df_data:
                continue

            df = df_data[df_key]
            old_balance = df[df.index == (account.name, account.account_type)]

            if len(old_balance) and account.balance_snapshot and 'total_usd' in account.balance_snapshot:
                old_total_usd = old_balance.amount_usd.values[-1]
                statistics[f'{df_key}_total_usd'] = old_total_usd
                if old_total_usd != 0:
                    pnl_subtrahend, transfers_in_volume, transfers_out_volume = transfers_volume(
                        grouped_transfers.get(account.name, pd.DataFrame([])),
                        account,
                        date_ends[hour]
                    )
                    statistics[f'{df_key}_transfers_in_volume'] = transfers_in_volume
                    statistics[f'{df_key}_transfers_out_volume'] = transfers_out_volume
                    statistics[f'{df_key}_pnl'] = \
                        (account.balance_snapshot['total_usd'] - old_total_usd - pnl_subtrahend) / old_total_usd * 100

        statistics['pnl_updated'] = pnl_updated_string
        account.set_statistics(statistics)


def transfer_types_prepare(filter_func):
    return list(
        map(
            lambda _type: _type.value,
            filter(filter_func, TransferType)
        )
    )


ACCOUNT_TYPE_TO_TRANSFER_OPERATIONS = {
    AccountType.SPOT: {
        'in': transfer_types_prepare(lambda _type: _type.value.endswith('_MAIN') or _type == TransferType.MAIN_DEPOSIT),
        'out': transfer_types_prepare(
            lambda _type: _type.value.startswith('MAIN_') and _type != TransferType.MAIN_DEPOSIT
        )
    },
    AccountType.CROSS_MARGIN: {
        'in': transfer_types_prepare(lambda _type: _type.value.endswith('_MARGIN')),
        'out': transfer_types_prepare(lambda _type: _type.value.startswith('MARGIN_'))
    },
    AccountType.COIN_M_FUTURES: {
        'in': transfer_types_prepare(
            lambda _type: _type.value.endswith('_CMFUTURE') or _type == TransferType.CMFUTURE_DEPOSIT
        ),
        'out': transfer_types_prepare(
            lambda _type: _type.value.startswith('CMFUTURE_') or _type == TransferType.CMFUTURE_WITHDRAWAL
        )
    },
    AccountType.USDT_M_FUTURES: {
        'in': transfer_types_prepare(
            lambda _type: _type.value.endswith('_UMFUTURE') or _type == TransferType.UMFUTURE_DEPOSIT
        ),
        'out': transfer_types_prepare(
            lambda _type: _type.value.startswith('UMFUTURE_') and _type != TransferType.UMFUTURE_DEPOSIT
        )
    }
}


def get_transfers_grouped_by_account_name(datastore: DataStore):
    df = datastore.read(
        DataType.transfers,
        query_params=dict(
            start_date=datetime.datetime.utcnow() - datetime.timedelta(hours=24),
            tail=35_000
        )
    )
    if not len(df):
        return {}

    return df_dict_group(df, 'name')


def transfers_volume(
    account_transfers: pd.DataFrame,
    exchange_credentials: ExchangeCredentials,
    date_end: datetime.datetime
) -> Tuple[float, float, float]:
    """
    returns transfers_volume, transfers_in_volume, transfers_out_volume
    :param account_transfers:
    :param exchange_credentials:
    :param date_end:
    :return:
    """
    if not len(account_transfers):
        return 0., 0., 0.

    account_transfers = account_transfers[account_transfers.index >= date_end].copy()
    if not len(account_transfers):
        return 0., 0., 0.

    transfers = ACCOUNT_TYPE_TO_TRANSFER_OPERATIONS[AccountType[exchange_credentials.account_type]]
    account_transfers['direction'] = account_transfers.transfer_type.apply(
        lambda ttype: ('in' if ttype in transfers['in'] else ('out' if ttype in transfers['out'] else None))
    )
    account_transfers = account_transfers[~account_transfers.direction.isna()]
    account_transfers.loc[account_transfers.direction == 'out', 'amount_usd'] *= -1
    return (
        account_transfers.amount_usd.sum(),
        account_transfers[account_transfers.direction == 'in'].amount_usd.sum(),
        account_transfers[account_transfers.direction == 'out'].amount_usd.sum()
    )


def df_to_list(df: pd.DataFrame) -> List[dict]:
    df = df.copy()
    if df.index.name == 'timestamp':
        df = df.reset_index()

    if 'index' in df.columns:
        df = df.drop('index', axis=1)

    if 'timestamp' in df.columns:
        df.timestamp = df.timestamp.astype(int) / 1e9
    return df.to_dict(orient='records')


def df_from_list(data: List[dict]) -> pd.DataFrame:
    df = pd.DataFrame(data)
    if 'timestamp' in df.columns:
        df.timestamp = pd.to_datetime(df.timestamp, unit='s')
    return df


def df_dict_group(
    df: pd.DataFrame,
    column_names: Union[List[str], str]
) -> Dict[Union[str, Tuple[str]], pd.DataFrame]:
    if not len(df) or not column_names:
        return {}

    if isinstance(column_names, str):
        column_name = column_names
        return {group_name: df[df[column_name] == group_name] for group_name in sorted(df[column_name].unique())}

    df = df.copy()
    df['x'] = df[column_names].apply(tuple, axis=1)
    return {group: df[df.x == group].drop('x', axis=1) for group in sorted(df.x.unique())}


class VolumeNotificator:
    def __init__(self, token, channel, datastore):
        self.token = token
        self.channel = channel
        self.datastore = datastore

    def post_message_to_slack(self, blocks):
        return requests.post('https://slack.com/api/chat.postMessage', {
            'token': self.token,
            'channel': self.channel,
            'blocks': json.dumps(blocks) if blocks else None
        }).json()

    def update_slack_message(self, blocks, ts):
        return requests.post('https://slack.com/api/chat.update', {
            'token': self.token,
            'channel': self.channel,
            'ts': ts,
            'blocks': json.dumps(blocks) if blocks else None
        }).json()

    @staticmethod
    def start_of_week(dt: datetime.datetime):
        start = dt - datetime.timedelta(days=dt.weekday())
        return start.replace(hour=0, minute=0, second=0)

    @staticmethod
    def end_of_week(dt: datetime.datetime):
        end = dt + datetime.timedelta(days=6 - dt.weekday())
        return end.replace(hour=23, minute=59, second=59)

    def report(self, ts=None):
        mm_symbols = [
            'ENJ/EUR',
            'XLM/EUR',
            'CHZ/TRY',
            'LAZIO/TRY',
            'LINK/GBP',
            'MATIC/GBP',
            'GMT/AUD',
            'MATIC/AUD',
            'DOT/BRL',
            'FTM/BRL',
            'BNB/RUB',
            'LTC/RUB',
            'BNB/UAH',
            'LTC/UAH',
        ]

        now = datetime.datetime.utcnow()
        start = self.start_of_week(now)
        end = self.end_of_week(now)
        form = TimeframeForm({
            'start_date': start.date(),
            'start_time': start.time(),
            'end_date': end.date(),
            'end_time': end.time(),
            'timeframe': 'W',
        })
        assert form.is_valid()

        pair_volumes_report = PairVolumesReport(form, self.datastore)
        report = pair_volumes_report.generate_report()

        blocks = [
            {
                'type': 'section',
                'text': {
                    'text': (
                        f'{start.strftime("%d/%m/%Y")} - {end.strftime("%d/%m/%Y")},'
                        f' updated: {now.strftime("%d/%m/%Y %H:%M")}'
                    ),
                    'type': 'mrkdwn',
                }
            },
            {
                'type': 'section',
                'text': {
                    'text': '',
                    'type': 'mrkdwn',
                },
            },
        ]

        for symbol in mm_symbols:
            data = report['report_data'].get(symbol)
            if data is None:
                data = {
                    'total_volume': 0,
                    'total_market_volume': 0,
                    'total_pct': 0,
                }
            pct = f'{data["total_pct"]:.3f}%'
            blocks[1]['text']['text'] += (
                f'\n{":exclamation:" if data["total_pct"] < 1 else ":grey_exclamation:"}{symbol:<15}'
                f'{pct:<10} '
                f'{data["total_volume"]:<15,.2f}'
            )
        res = {}
        if ts is not None:
            res = self.update_slack_message(blocks, ts)
        if not res.get('ok', True) or ts is None:
            res = self.post_message_to_slack(blocks)
        return res['ts']
