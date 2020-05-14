import time
import json
import ccxt
import math
import requests

from core.libs.helpers.data_classes import *
import logging
logging.basicConfig()


class CcxtExecutor:
    def __init__(self, exchange_slug: str, exchange_credentials_dict: dict, symbol: SymbolData):
        self.exchange_api = None

        self.exchange_slug = exchange_slug
        self.exchange_credentials_dict = exchange_credentials_dict
        self.symbol = symbol

    def get_api(self):
        if self.exchange_api is None:
            exchange_api = getattr(ccxt, self.exchange_slug)({**self.exchange_credentials_dict, "verbose": 1})
            try:
                markets_cache = json.load(open(f"cache/{self.exchange_slug}.json", "r"))
                exchange_api.markets = markets_cache
            except FileNotFoundError:
                exchange_api.load_markets()
                json.dump(exchange_api.markets, open(f"cache/{self.exchange_slug}.json", "w"))

            self.exchange_api = exchange_api
        return self.exchange_api

    ##############################
    # Methods below should be implemented and tested for each exchange
    ##############################

    def get_ticker(self):
        per_exchange_methods = dict(
            bitfinex=self.__bitfinex__get_ticker,
            binance=self.__binance__get_ticker
        )

        return per_exchange_methods[self.exchange_slug](
            self.get_api(), self.symbol
        )

    def get_balance(self):
        per_exchange_methods = dict(
            bitfinex=self.__bitfinex__get_balance,
            binance=self.__binance__get_balance
        )

        return per_exchange_methods[self.exchange_slug](
            self.get_api(), self.symbol
        )

    def get_position(self):
        per_exchange_methods = dict(
            bitfinex=self.__bitfinex__get_position,
            binance=self.__binance__get_position
        )

        return per_exchange_methods[self.exchange_slug](
            self.get_api(), self.symbol
        )

    def create_order(self, size) -> OrderResultData:
        per_exchange_methods = dict(
            bitfinex=self.__bitfinex__create_order,
            binance=self.__binance__create_order
        )

        order_result = per_exchange_methods[self.exchange_slug](
            self.get_api(), self.symbol, size
        )
        return order_result

    ##############################
    # Bitfinex custom methods
    ##############################

    @staticmethod
    def __bitfinex__get_balance(api, symbol):
        balance = api.fetch_balance()['info']
        for item in balance:
            if item['type'] == 'trading':
                if item['currency'].upper() == symbol.quote:
                    return QuoteBalanceData(amount_all=float(item['amount']), amount_free=float(item['available']))

        return None

    @staticmethod
    def __bitfinex__get_ticker(api, symbol):
        ticker = api.fetch_ticker(
            f"{symbol.base}/{symbol.quote}"
        )

        return TickerData(
            timestamp=int(ticker['timestamp'] / 1000),
            ask=ticker['ask'],
            bid=ticker['bid'],
            price_avg=ticker['average'],
        )

    @staticmethod
    def __bitfinex__get_position(api, symbol: "SymbolData") -> PositionData:
        api_symbol = f"{symbol.base.lower()}{symbol.quote.lower()}"
        for p in api.private_post_positions():
            if p['symbol'] == api_symbol:
                price_avg = float(p['base'])
                size = float(p['amount'])
                return PositionData(
                    timestamp=int(float(p['timestamp'])),
                    price_avg=price_avg,
                    size=size,
                    pnl=float(p['pl']) / (price_avg * size),
                )

        return PositionData(
            timestamp=int(time.time()),
            price_avg=-1,
            size=0,
            pnl=0
        )

    @staticmethod
    def __bitfinex__create_order(api, symbol: SymbolData, size: float):
        api_symbol = symbol.to_ccxt()
        side = "buy" if size > 0 else "sell"
        amount = abs(size)
        order = api.create_order(
            symbol=api_symbol,
            type="market",
            side=side,
            amount=amount,
            params={
                'type': 'market',
                'aff_code': 'KZE9Xsts2'  # bitfinex aff code
            }
        )
        order_id = order['info']['id']
        for i in range(0, 5):
            try:
                order = api.private_post_order_status(params={"order_id": order_id})
            except (requests.exceptions.HTTPError, ccxt.OrderNotFound):
                print("Order not found Error")
                time.sleep(1)

        return OrderResultData(
            timestamp=int(float(order['timestamp'])),
            type="market",
            size=float(order['executed_amount']) * (1 if order['side'] == 'buy' else -1),
            price_avg=float(order['avg_execution_price'])
        )

    ##############################
    # Bitfinex custom methods
    ##############################

    @staticmethod
    def __binance__get_balance(api, symbol: SymbolData):
        balance = api.fetch_balance()
        if symbol.quote in balance:
            item = balance[symbol.quote]
            return QuoteBalanceData(amount_all=float(item['total']), amount_free=float(item['free']))

        return None

    @staticmethod
    def __binance__get_ticker(api, symbol: SymbolData):
        # ticker = api.fetch_ticker(
        #     f"{bot.instrument.symbol.base.slug}/{bot.instrument.symbol.quote.slug}"
        # )

        orderbook = api.fetch_order_book(
            f"{symbol.base}/{symbol.quote}"
        )
        timestamp = int(orderbook['timestamp'] / 1000) if orderbook['timestamp'] is not None else int(time.time())

        return TickerData(
            timestamp=timestamp,
            ask=orderbook['asks'][0][0],
            bid=orderbook['bids'][0][0],
            price_avg=(orderbook['asks'][0][0] + orderbook['bids'][0][0]) / 2,
        )

    @staticmethod
    def __binance__get_position(api, symbol: SymbolData) -> PositionData:
        api_symbol = f"{symbol.base}{symbol.quote}"
        positions = api.fapiPrivateGetPositionRisk()

        for p in positions:
            if p['symbol'] == api_symbol:
                price_avg = float(p['entryPrice'])
                size = float(p['positionAmt'])
                return PositionData(
                    timestamp=int(time.time()),
                    price_avg=price_avg,
                    size=size,
                    pnl=size if size == 0 else float(p['unRealizedProfit']) / (price_avg * size)
                )

        return PositionData(
            timestamp=int(time.time()),
            price_avg=-1,
            size=0,
            pnl=0
        )

    @staticmethod
    def __binance__create_order(api, symbol: SymbolData, size: float):
        api_symbol = symbol.to_binance()
        side = "BUY" if size > 0 else "SELL"
        amount = abs(size)
        order_resp = api.fapiPrivatePostOrder(params=dict(
            symbol=api_symbol,
            type="MARKET",
            side=side,
            quantity=amount
        ))

        for i in range(0, 5):
            order = api.fapiPrivateGetOrder(dict(symbol=order_resp['symbol'], orderId=order_resp['orderId']))
            time.sleep(1)

            if order['status'] == 'FILLED':
                break

        return OrderResultData(
            timestamp=int(float(order['time'] / 1000)),
            type="market",
            size=float(order['executedQty']) * (1 if order['side'] == 'BUY' else -1),
            price_avg=float(order['avgPrice'])
        )