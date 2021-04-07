import logging
import datetime
from typing import Optional, Dict, List

import pytz
import ccxt
from django.utils import timezone
from rcdb_commons.data_store import DataStore, DataType

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

        self.fill_bot_statistic(
            bot_statistic,
            self.calculate_bot_statistic_from_update(
                statistic_update,
                bot_statistic.bot.instrument.symbol.to_ccxt()
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
    def __init__(self, credentials: dict):
        self.api = ccxt.binance(credentials)
        self._usd_price_cache = {'USDT': 1}

    def update_amount_usd(self, data: dict) -> dict:
        return {**data, 'amount_usd': data['amount'] * self.usd_price(data['symbol'])}

    def usd_price(self, symbol: str) -> float:
        if symbol not in self._usd_price_cache:
            try:
                self._usd_price_cache[symbol] = self.api.fetch_ticker(f'{symbol}/USDT')['bid']
            except ccxt.errors.BadSymbol:
                self._usd_price_cache[symbol] = 1 / self.api.fetch_ticker(f'USDT/{symbol}')['ask']

        return self._usd_price_cache[symbol]

    @staticmethod
    def _sort_balances(balances: List[dict]) -> List[dict]:
        return sorted(balances, key=lambda x: x['amount_usd'], reverse=True)

    def get_balance_data(self) -> Dict[str, List[dict]]:
        result = {
            'spot': self._sort_balances(
                [
                    self.update_amount_usd(
                        {
                            'symbol': symbol,
                            'amount': amount,
                        }
                    )
                    for symbol, amount in self.api.fetch_balance()['total'].items()
                    if amount
                ]
            ),

            'margin': self._sort_balances(
                [
                    self.update_amount_usd(
                        {
                            'symbol': b['asset'],
                            'amount': float(b['netAsset']),
                        }
                    )
                    for b in self.api.sapi_get_margin_account()['userAssets']
                    if b['netAsset'] != '0'
                ]
            )
        }
        result['total_usd'] = sum(
            map(
                lambda x: x['amount_usd'],
                result['margin'] + result['spot']
            )
        )
        return result


EXCHANGE_ACCOUNT_CONNECTOR_MAP = {
    'binance': BinanceAccountConnector
}


def snapshot_account_balances(exchange_credentials: ExchangeCredentials):
    account_connector_class = EXCHANGE_ACCOUNT_CONNECTOR_MAP.get(exchange_credentials.exchange.slug)
    if not account_connector_class:
        logging.error(f'AccountConnector for {exchange_credentials.exchange.slug} is not implemented')
        return

    try:
        account_connector = account_connector_class(exchange_credentials.parameters)
        exchange_credentials.balance_snapshot = account_connector.get_balance_data()
        exchange_credentials.balance_snapshot_created = timezone.now()
        exchange_credentials.save()
    except ccxt.errors.AuthenticationError as e:
        logging.error(f"Can't auth to exchange {exchange_credentials}: {e}'")
