import logging
import operator
import datetime
from typing import Generator, Optional, Dict, List, Tuple, Union, Iterable

import pytz
import ccxt
import numpy as np
import pandas as pd
from django.utils import timezone
from rcdb_commons.lib.schemas.exchange import AccountType, SymbolEmpty
from rcdb_commons.lib.stores import CredentialsStore, DataStore, DataType

from .forms import ReportType, RebatesForm, RebateCurrency
from .models import Bot, BotStatistic, ExchangeCredentials


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


class BinanceAccountConnector:
    class Exceptions:
        class UnsupportedMarketType(Exception):
            pass

    def __init__(self, credentials: dict, data_store: DataStore):
        self.api = ccxt.binance(credentials)
        self.data_store = data_store
        self._usd_price_cache = {'USDT': 1, 'ETF': 1, 'BUSD': 1}

    def update_amount_usd(self, data: dict) -> dict:
        result = data.copy()

        for field in ['borrowed', 'interest', 'amount']:
            field_btc = f'{field}_btc'
            field_usd = f'{field}_usd'

            if field_btc in data:
                result[field_usd] = data[field_btc] * self.usd_price('BTC')
            elif field in data:
                if data[field] == 0:
                    result[field_usd] = 0.
                else:
                    result[field_usd] = data[field] * self.usd_price(data['symbol'])

        return result

    def fetch_price(self, symbol: str) -> Optional[float]:
        df = self.data_store.read(
            DataType.ohlcv,
            query_params=dict(
                exchange='BINANCE',
                instrument='SPOT',
                symbol=symbol
            )
        )
        if len(df):
            return df.close.values[-1]
        return None

    def usd_price(self, symbol: str) -> float:
        if symbol not in self._usd_price_cache:
            for pair, is_reversed in [
                (f'{symbol}/USDT', False),
                (f'USDT/{symbol}', True),
                (f'{symbol}/BUSD', False),
                (f'BUSD/{symbol}', True)
            ]:
                price = self.fetch_price(pair)
                if price is not None:
                    self._usd_price_cache[symbol] = (1 / price) if is_reversed else price
                    break
            else:
                logging.warning(f"Can't find price for {symbol}. Set to 0")
                self._usd_price_cache[symbol] = 0

        return self._usd_price_cache[symbol]

    @staticmethod
    def _sort_balances(balances: Iterable[dict]) -> List[dict]:
        return sorted(balances, key=lambda x: x['amount_usd'], reverse=True)

    def _get_spot_balances(self):
        return (
            {'symbol': symbol, 'amount': amount}
            for symbol, amount in self.api.fetch_balance()['total'].items()
        )

    def _get_cross_margin_balances(self) -> Generator[dict, None, None]:
        return (
            {
                'symbol': b['asset'],
                'amount': float(b['netAsset']),
                'interest': float(b['interest']),
                'borrowed': float(b['borrowed'])
            }
            for b in self.api.sapi_get_margin_account()['userAssets']
        )

    def _get_isolated_margin_balances(self) -> Generator[dict, None, None]:
        asset_getter = operator.itemgetter('baseAsset', 'quoteAsset')
        return (
            {
                'pair_symbol': pair_asset['symbol'],
                'symbol': asset['asset'],
                'amount': float(asset['netAsset']),
                'interest': float(asset['interest']),
                'borrowed': float(asset['borrowed']),
                **({} if asset['asset'] in {'USDT', 'BUSD'} else {'amount_btc': float(asset['netAssetOfBtc'])})
            }
            for pair_asset in self.api.sapi_get_margin_isolated_account()['assets']
            for asset in asset_getter(pair_asset)
        )

    def get_balance_data(self, type: str) -> Dict[str, Union[List[dict], float]]:
        market_type_method = {
            AccountType.SPOT.value: self._get_spot_balances,
            AccountType.CROSS_MARGIN.value: self._get_cross_margin_balances,
            AccountType.ISOLATED_MARGIN.value: self._get_isolated_margin_balances,
        }
        if type not in market_type_method:
            raise self.Exceptions.UnsupportedMarketType(type)

        result = {
            'balances': list(
                filter(
                    lambda x: x.get('amount_usd', 0.) == 0. and x.get('amount', 0.) != 0 or sum(
                        abs(x.get(k, 0.)) for k in ('amount_usd', 'borrowed_usd', 'interest_usd')
                    ) >= 1.,
                    self._sort_balances(
                        self.update_amount_usd(data)
                        for data in market_type_method[type]()
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


EXCHANGE_ACCOUNT_CONNECTOR_MAP = {
    'binance': BinanceAccountConnector
}


def snapshot_account_balances(
    exchange_credentials: ExchangeCredentials,
    data_store: DataStore,
    credentials_store: CredentialsStore
):
    account_connector_class = EXCHANGE_ACCOUNT_CONNECTOR_MAP.get(exchange_credentials.exchange.slug)
    if not account_connector_class:
        logging.error(f'AccountConnector for {exchange_credentials.exchange.slug} is not implemented')
        return

    if exchange_credentials.ignore_balance or not exchange_credentials.visible:
        logging.debug(f'Ignore balance for {exchange_credentials}')
        exchange_credentials.set_balance_snapshot({})
        return

    try:
        credentials = credentials_store.get_secret(exchange_credentials.name)
        account_connector = account_connector_class(credentials, data_store)
        exchange_credentials.set_balance_snapshot(
            account_connector.get_balance_data(exchange_credentials.account_type)
        )
    except BinanceAccountConnector.Exceptions.UnsupportedMarketType as e:
        logging.error(f"Unsupported market type: {e}")
    except ccxt.errors.AuthenticationError as e:
        logging.error(f"Can't auth to exchange {exchange_credentials}: {e}'")


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
        df_local = self.get_df_statistics(exchange_credentials, 'trades')
        markets_data = [
            self.fetch_from_datastore(
                data_type=DataType.account_trades,
                since=(
                    df_local[df_local.symbol == market].timestamp.max().to_pydatetime()
                    if len(df_local) and (df_local.symbol == market).any() else
                    (datetime.datetime.utcnow() - datetime.timedelta(days=30))
                ),
                name=exchange_credentials.name,
                symbol=market,
                account_type=exchange_credentials.account_type
            )
            for market in exchange_credentials.meta.get('markets', [])
        ]
        return self.concat_dfs_safe_with_cut_history([df_local, *markets_data])

    def get_updated_rebates(self, exchange_credentials: ExchangeCredentials) -> pd.DataFrame:
        df_local = self.get_df_statistics(exchange_credentials, 'raw_rebates')
        df_updates = self.fetch_from_datastore(
            data_type=DataType.rebates,
            since=(
                df_local.timestamp.max().to_pydatetime()
                if len(df_local) else
                (datetime.datetime.utcnow() - datetime.timedelta(days=30))
            ),
            name=exchange_credentials.name,
            account_type=exchange_credentials.account_type
        )
        return self.concat_dfs_safe_with_cut_history([df_local, df_updates])

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
    def concat_dfs_safe_with_cut_history(dfs: List[pd.DataFrame], td=datetime.timedelta(days=30)) -> pd.DataFrame:
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
        statistics['expected_rebates'] = cls.expected_rebates(trades)
        statistics['trades'] = df_to_list(trades)
        return statistics

    @classmethod
    def rebates_statistics(cls, rebates: pd.DataFrame, expected_rebates: pd.DataFrame) -> dict:
        if len(rebates):
            rebates = rebates.set_index('timestamp')
            rebates_symbol_map = df_dict_group(rebates, 'symbol')
        else:
            rebates_symbol_map = {}

        expected_rebates_symbol_map = df_dict_group(expected_rebates, 'symbol')

        res = {}
        df: pd.DataFrame
        for symbol, df in expected_rebates_symbol_map.items():
            rebate = rebates_symbol_map.get(symbol)
            if rebate is None:
                rebate = pd.DataFrame(index=df.index)
                rebate['rebate'] = 0.
                rebate['rebate_usd'] = 0.
            rebate.index = rebate.index.map(lambda x: x.replace(second=0))
            res[symbol] = df.merge(rebate, how='outer', left_index=True, right_index=True)

        res_df = concat_dfs_safe([df.assign(symbol=symbol) for symbol, df in res.items()]).fillna(0.)
        if len(res_df):
            res_df = res_df[
                ['symbol', 'volume', 'expected_rebate', 'rebate', 'volume_usd', 'expected_rebate_usd', 'rebate_usd']
            ]
        return {
            'raw_rebates': df_to_list(rebates),
            'rebates': df_to_list(res_df)
        }

    @staticmethod
    def expected_rebates(
        trades: pd.DataFrame,
        fiat_symbols: tuple = ('EUR', 'GBP', 'AUD', 'BRL', 'TRY', 'RUB', 'UAH'),
        rebate_percent: float = 0.00005
    ) -> pd.DataFrame:
        df = trades.copy()

        def symbol_replacer(symbol: str) -> str:
            for fiat_symbol in fiat_symbols:
                if symbol.startswith(f'{fiat_symbol}/') or symbol.endswith(f'/{fiat_symbol}'):
                    return fiat_symbol

        is_startswith_fiat = df.symbol.str.startswith(tuple(map(lambda s: f'{s}/', fiat_symbols)))
        is_endswith_fiat = df.symbol.str.endswith(tuple(map(lambda s: f'/{s}', fiat_symbols)))
        df.symbol = df.symbol.apply(symbol_replacer)
        df['volume'] = 0.
        df['volume_usd'] = df.volume_buy_usd + df.volume_sell_usd
        df.loc[is_endswith_fiat, 'volume'] = (
            df.loc[is_endswith_fiat, 'volume_buy'] + df.loc[is_endswith_fiat, 'volume_sell']
        )
        df.loc[is_startswith_fiat, 'volume'] = (
            (
                df.loc[is_startswith_fiat, 'volume_buy'] / df.loc[is_startswith_fiat, 'price_avg_buy']
            ).fillna(0.) + (
                df.loc[is_startswith_fiat, 'volume_sell'] / df.loc[is_startswith_fiat, 'price_avg_sell']
            ).fillna(0.)
        )
        df['expected_rebate'] = df.volume * rebate_percent
        df['expected_rebate_usd'] = df.volume_usd * rebate_percent
        df = df[['timestamp', 'expected_rebate', 'expected_rebate_usd', 'symbol', 'volume', 'volume_usd']].reset_index()
        is_before_half_hour = df.timestamp.dt.minute <= 30
        is_after_half_hour = ~is_before_half_hour
        df['rebate_time'] = pd.NaT
        df.loc[is_before_half_hour, 'rebate_time'] = (
            df.loc[is_before_half_hour, 'timestamp'].apply(lambda x: x.replace(minute=30))
        )
        df.loc[is_after_half_hour, 'rebate_time'] = (
            df.loc[is_after_half_hour, 'timestamp'].apply(lambda x: x.replace(minute=30) + datetime.timedelta(hours=1))
        )
        df.drop('timestamp', axis=1, inplace=True)
        df.rename(columns={'rebate_time': 'timestamp'}, inplace=True)
        df = df.groupby(['symbol', 'timestamp']).agg(
            {
                'expected_rebate': 'sum',
                'volume': 'sum',
                'expected_rebate_usd': 'sum',
                'volume_usd': 'sum'
            }
        )

        return concat_dfs_safe([df.loc[symbol].assign(symbol=symbol) for symbol in df.index.unique(level=0)])


class RebateReport:
    def __init__(self, report_form: RebatesForm):
        form_data = report_form.cleaned_data
        self.exchange_credentials_list = (
            [form_data['exchange_credentials']]
            if form_data['exchange_credentials'] and form_data['type'] == ReportType.BY_ACCOUNT.value else
            ExchangeCredentials.objects.exclude(
                id__in=list(
                    map(operator.attrgetter('id'), form_data['excluded_exchange_credentials'])
                )
            )
        )
        self.report_form = report_form
        self.exchange_credentials_account_map = {
            (ex.name, ex.account_type): ex for ex in self.exchange_credentials_list
        }

    def generate_report(self) -> dict:
        rebates = self.filter_df_by_rebate_currencies(
            self.filter_df_by_get_dt(
                concat_dfs_safe([
                    DataStoreDataSynchronizer.get_df_statistics(exchange_credentials, 'rebates').assign(
                        account_type=exchange_credentials.account_type,
                        name=exchange_credentials.name
                    )
                    for exchange_credentials in self.exchange_credentials_list
                ])
            )
        )

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

    def filter_df_by_rebate_currencies(self, df: pd.DataFrame) -> pd.DataFrame:
        if not len(df) or RebateCurrency.ALL.value in self.report_form.cleaned_data['currencies']:
            return df
        return df[df.symbol.isin(self.report_form.cleaned_data['currencies'])]

    def filter_df_by_get_dt(self, df: pd.DataFrame) -> pd.DataFrame:
        if not len(df):
            return df

        start = self.report_form.start
        end = self.report_form.end

        if start and end:
            return df[(df.timestamp >= np.datetime64(start)) & (df.timestamp <= np.datetime64(end))]

        if start:
            return df[df.timestamp >= np.datetime64(start)]

        if end:
            return df[df.timestamp <= np.datetime64(end)]

        return df

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

        rebates['difference'] = rebates.rebate - rebates.expected_rebate
        rebates = rebates[rebates.difference != 0.]

        summary.update(self._calculate_overall_totals(rebates))

        for account, account_rebates in df_dict_group(rebates, ['name', 'account_type']).items():
            aggregated_account_rebates = self.aggregate_rebates(
                account_rebates, self.report_form.cleaned_data['timeframe']
            )
            account_data = self._calculate_overall_totals(aggregated_account_rebates)
            account_data['data'] = aggregated_account_rebates.to_dict(orient='records')
            account_data['exchange_credentials'] = self.exchange_credentials_account_map[account]
            summary['accounts_data'].append(account_data)

        return summary

    def _calculate_overall_totals(self, rebates: pd.DataFrame) -> dict:
        return {
            'total_volume': rebates.volume.sum(),
            'total_rebate': rebates.rebate.sum(),
            'total_expected_rebate': rebates.expected_rebate.sum(),
            'total_difference': rebates.difference.sum()
        }

    def calculate_by_account_summary(self, rebates: pd.DataFrame) -> dict:
        aggregated_rebates = self.aggregate_rebates(rebates, self.report_form.cleaned_data['timeframe'])
        summary = (
            {
                'total_volume': aggregated_rebates.volume.sum(),
                'total_rebate': aggregated_rebates.rebate.sum(),
                'total_expected_rebate': aggregated_rebates.expected_rebate.sum(),
                'total_volume_usd': aggregated_rebates.volume_usd.sum(),
                'total_rebate_usd': aggregated_rebates.rebate_usd.sum(),
                'total_expected_rebate_usd': aggregated_rebates.expected_rebate_usd.sum()
            } if len(aggregated_rebates) else {
                'total_volume': 0,
                'total_rebate': 0,
                'total_expected_rebate': 0,
                'total_volume_usd': 0,
                'total_rebate_usd': 0,
                'total_expected_rebate_usd': 0
            }
        )
        summary['data'] = aggregated_rebates.to_dict(orient='records')
        return summary

    @classmethod
    def aggregate_rebates(cls, rebates: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        rebates = rebates.copy().sort_values('timestamp')
        rebates['ts'] = rebates.timestamp
        dt_format = {
            '1H': '%d/%m/%Y %H:%M:%S',
            '1D': '%d/%m/%Y',
            '1M': '%Y/%m',
        }

        if timeframe == '1W':
            rebates.timestamp = rebates.timestamp.apply(cls.week_string)
        else:
            rebates.timestamp = rebates.timestamp.dt.strftime(dt_format[timeframe])

            if timeframe == '1H':
                return rebates.sort_values('ts', ascending=False)

        rebates = (
            rebates
            .groupby('timestamp')
            .agg(
                {
                    'volume': 'sum',
                    'rebate': 'sum',
                    'expected_rebate': 'sum',
                    'volume_usd': 'sum',
                    'rebate_usd': 'sum',
                    'expected_rebate_usd': 'sum',
                    'ts': 'first',
                    **({'difference': 'sum'} if 'difference' in rebates.columns else {}),
                }
            )
            .reset_index()
            .sort_values('ts', ascending=False)
        )
        return rebates

    @staticmethod
    def week_string(dt: pd.Timestamp) -> str:
        dt = dt.to_pydatetime().date()
        start_of_week = dt - datetime.timedelta(days=dt.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)
        dt_format = '%d/%m/%Y'
        return f'{start_of_week.strftime(dt_format)} - {end_of_week.strftime(dt_format)}'


def update_account_statistics(datastore: DataStore, exchange_credentials: ExchangeCredentials):
    datastore_manager = DataStoreDataSynchronizer(datastore)
    trades = datastore_manager.get_updated_trades(exchange_credentials)
    rebates = datastore_manager.get_updated_rebates(exchange_credentials)

    exchange_credentials.statistics = {
        'h1_usd_volume': None,
        'h1_trades_count': None,
        'h24_usd_volume': None,
        'h24_trades_count': None,
        'd7_usd_volume': None,
        'd7_trades_count': None,
        'updated': timezone.now().strftime('%d/%m/%Y %H:%M:%S'),
        'trades': [],
        'rebates': [],
        'raw_rebates': []
    }

    statistics = {
        **exchange_credentials.statistics,
        **(StatisticsCalculator.trades_statistics(trades) if len(trades) else {}),
    }
    exchange_credentials.statistics = {
        **statistics,
        **StatisticsCalculator.rebates_statistics(
            rebates,
            statistics.pop('expected_rebates', pd.DataFrame([]))
        )
    }
    exchange_credentials.save()


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
        return {group_name: df[df[column_name] == group_name] for group_name in df[column_name].unique()}

    df = df.copy()
    df['x'] = df[column_names].apply(tuple, axis=1)
    return {group: df[df.x == group].drop('x', axis=1) for group in df.x.unique()}
