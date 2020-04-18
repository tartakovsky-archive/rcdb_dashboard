import time
import json
import ccxt
import math
import requests
from core.libs.helpers.data_classes import *


class CcxtBotExecutor:
    def __init__(self, bot: "Bot"):
        self.bot = bot
        self.exchange_api = None

    def get_api(self):
        if self.exchange_api is None:
            exchange_name = self.bot.exchange_credentials.exchange.slug
            exchange_creds = json.loads(self.bot.exchange_credentials.init_kwargs)
            exchange_api = getattr(ccxt, exchange_name)({**exchange_creds, "verbose": 1})
            try:
                markets_cache = json.load(open(f"cache/{exchange_name}.json", "r"))
                exchange_api.markets = markets_cache
            except FileNotFoundError:
                exchange_api.load_markets()
                json.dump(exchange_api.markets, open(f"cache/{exchange_name}.json", "w"))

            self.exchange_api = exchange_api
        return self.exchange_api



    def execute_target_state(self, bot_target: "BotTargetState"):
        try:
            # TODO lock in transaction

            bot_target.blocked = True
            bot_target.save()
            bot = bot_target.bot

            # return order_result or None
            order_results_response = None

            is_trade_allowed = False

            bot_position = self.get_position()
            # bot_target.log_position(bot_position)

            if abs(bot_position.size - bot_target.instrument_target_size) < bot.min_trade_amount:
                bot_target.is_active = False
                # bot_target.save()
            else:
                # is_position_side_changed is True if long changed to short or vice versa
                is_position_side_changed = bot_target.instrument_target_size * bot_position.size > 0
                if is_position_side_changed:
                    # only size is changed (position is the same)
                    is_position_increase = abs(bot_target.instrument_target_size) > abs(bot_position.size)
                else:
                    # if position side changes
                    # then position always decreasing, but there is a trick
                    # when position crosses 0 (e.g. -0.1 -> 0.1 -> 0.5) it starts increasing
                    is_position_increase = False

                # calculate order size
                order_size = round(bot_target.instrument_target_size - bot_position.size, bot.instrument.size_round_precision)
                if abs(order_size) > bot.max_trade_amount:
                    # limit order size to bot max allowed trade size
                    order_size = math.copysign(bot.max_trade_amount, order_size)

                bot_ticker = self.get_ticker()

                is_trade_allowed = False
                is_long = order_size > 0

                # allowed slippage_pct is different when increasing and decreasing positions
                slippage_pct__allowed = bot.slippage_pct_position_increase
                if not is_position_increase:
                    slippage_pct__allowed = bot.slippage_pct_position_decrease

                if is_long:
                    # calculate current slippage between live price and state's target price
                    price_pct_change_since_bar_open = bot_ticker.ask / bot_target.instrument_target_execution_price - 1
                    # negative slippage when price goes up
                    if price_pct_change_since_bar_open <= slippage_pct__allowed:
                        # trading is allowed if current slippage is lower then allowed
                        is_trade_allowed = True
                    else:
                        # current slippage if bigger then allowed, log information and do nothing
                        max_price = bot_target.instrument_target_execution_price + bot_target.instrument_target_execution_price * slippage_pct__allowed
                        print(f"[Long] Instrument price {bot_ticker.ask} is higher then "
                              f"target price {bot_target.instrument_target_execution_price} (with slippage {slippage_pct__allowed}% == {max_price})")
                else:
                    # calculate current slippage between live price and state's target price
                    price_pct_change_since_bar_open = bot_ticker.bid / bot_target.instrument_target_execution_price - 1
                    # multiply slippage by -1 for shorts (negative slippage when price goes down)
                    if -1 * price_pct_change_since_bar_open <= slippage_pct__allowed:
                        # trading is allowed if current slippage is lower then allowed
                        is_trade_allowed = True
                    else:
                        # current slippage if bigger then allowed, log information and do nothing
                        min_price = bot_target.instrument_target_execution_price - bot_target.instrument_target_execution_price * slippage_pct__allowed
                        print(f"[Short] Instrument price {bot_ticker.ask} is lower then "
                              f"target price {bot_target.instrument_target_execution_price} (with slippage {slippage_pct__allowed}% == {min_price})")

                if is_trade_allowed:
                    # create order if trade allowed and log results
                    order_result = self.create_order(order_size)
                    bot_target.log_order(order_result)
                    order_results_response = order_result

            if is_trade_allowed:
                # if trade occured we should refresh position info
                bot_position = self.get_position()

            # log position info in any case
            bot_target.log_position(bot_position)

            return order_results_response
        except Exception as ex:
            raise ex
        finally:
            bot_target.blocked = False
            bot_target.save()

    ##############################
    # Methods below should be implemented and tested for each exchange
    ##############################

    def get_ticker(self):
        per_exchange_methods = dict(
            bitfinex=self.__bitfinex__get_ticker,
            binance=self.__binance__get_ticker
        )

        return per_exchange_methods[self.bot.exchange_credentials.exchange.slug](
            self.get_api(), self.bot
        )

    def get_balance(self):
        per_exchange_methods = dict(
            bitfinex=self.__bitfinex__get_balance,
            binance=self.__binance__get_balance
        )

        return per_exchange_methods[self.bot.exchange_credentials.exchange.slug](
            self.get_api(), self.bot
        )

    def get_position(self, target=None):
        per_exchange_methods = dict(
            bitfinex=self.__bitfinex__get_position,
            binance=self.__binance__get_position
        )

        return per_exchange_methods[self.bot.exchange_credentials.exchange.slug](
            self.get_api(), self.bot.instrument.symbol
        )

    def create_order(self, size):
        per_exchange_methods = dict(
            bitfinex=self.__bitfinex__create_order,
            binance=self.__binance__create_order
        )

        order_result = per_exchange_methods[self.bot.exchange_credentials.exchange.slug](
            self.get_api(), self.bot.instrument, size
        )
        return order_result

    ##############################
    # Bitfinex custom methods
    ##############################

    @staticmethod
    def __bitfinex__get_balance(api, bot):
        balance = api.fetch_balance()['info']
        for item in balance:
            if item['type'] == 'trading':
                if item['currency'].upper() == bot.instrument.symbol.quote.slug:
                    return BotQuoteBalance(amount_all=float(item['amount']), amount_free=float(item['available']))

        return None

    @staticmethod
    def __bitfinex__get_ticker(api, bot):
        ticker = api.fetch_ticker(
            f"{bot.instrument.symbol.base.slug}/{bot.instrument.symbol.quote.slug}"
        )

        return BotTicker(
            timestamp=int(ticker['timestamp'] / 1000),
            ask=ticker['ask'],
            bid=ticker['bid'],
            price_avg=ticker['average'],
        )

    @staticmethod
    def __bitfinex__get_position(api, symbol: "Symbol") -> BotPosition:
        api_symbol = f"{symbol.base.slug.lower()}{symbol.quote.slug.lower()}"
        for p in api.private_post_positions():
            if p['symbol'] == api_symbol:
                price_avg = float(p['base'])
                size = float(p['amount'])
                return BotPosition(
                    timestamp=int(float(p['timestamp'])),
                    price_avg=price_avg,
                    size=size,
                    pnl=float(p['pl']) / (price_avg * size),
                )

        return BotPosition(
            timestamp=int(time.time()),
            price_avg=-1,
            size=0,
            pnl=0
        )

    @staticmethod
    def __bitfinex__create_order(api, instrument: "BotInstrument", size: float):
        api_symbol = instrument.symbol.to_ccxt()
        side = "buy" if size > 0 else "sell"
        amount = abs(size)
        order = api.create_order(
            symbol=api_symbol,
            type="market",
            side=side,
            amount=amount,
            params={
                'type': 'market',
                'aff_code': 'KZE9Xsts2'
            }
        )
        order_id = order['info']['id']
        for i in range(0, 5):
            try:
                order = api.private_post_order_status(params={"order_id": order_id})
            except (requests.exceptions.HTTPError, ccxt.OrderNotFound):
                print("Order not found Error")
                time.sleep(1)

        return BotOrderResult(
            timestamp=int(float(order['timestamp'])),
            type="market",
            size=float(order['executed_amount']) * (1 if order['side'] == 'buy' else -1),
            price_avg=float(order['avg_execution_price'])
        )

    ##############################
    # Bitfinex custom methods
    ##############################

    @staticmethod
    def __binance__get_balance(api, bot):
        balance = api.fetch_balance()
        if bot.instrument.symbol.quote.slug in balance:
            item = balance[bot.instrument.symbol.quote.slug]
            return BotQuoteBalance(amount_all=float(item['total']), amount_free=float(item['free']))

        return None

    @staticmethod
    def __binance__get_ticker(api, bot):
        # ticker = api.fetch_ticker(
        #     f"{bot.instrument.symbol.base.slug}/{bot.instrument.symbol.quote.slug}"
        # )

        orderbook = api.fetch_order_book(
            f"{bot.instrument.symbol.base.slug}/{bot.instrument.symbol.quote.slug}"
        )
        timestamp = int(orderbook['timestamp'] / 1000) if orderbook['timestamp'] is not None else int(time.time())

        return BotTicker(
            timestamp=timestamp,
            ask=orderbook['asks'][0][0],
            bid=orderbook['bids'][0][0],
            price_avg=(orderbook['asks'][0][0] + orderbook['bids'][0][0]) / 2,
        )

    @staticmethod
    def __binance__get_position(api, symbol: "Symbol") -> BotPosition:
        api_symbol = f"{symbol.base.slug.upper()}{symbol.quote.slug.upper()}"
        positions = api.fapiPrivateGetPositionRisk()

        for p in positions:
            if p['symbol'] == api_symbol:
                price_avg = float(p['entryPrice'])
                size = float(p['positionAmt'])
                return BotPosition(
                    timestamp=int(time.time()),
                    price_avg=price_avg,
                    size=size,
                    pnl=size if size == 0 else float(p['unRealizedProfit']) / (price_avg * size)
                )

        return BotPosition(
            timestamp=int(time.time()),
            price_avg=-1,
            size=0,
            pnl=0
        )

    @staticmethod
    def __binance__create_order(api, instrument: "BotInstrument", size: float):
        api_symbol = instrument.symbol.to_binance()
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

        return BotOrderResult(
            timestamp=int(float(order['time'] / 1000)),
            type="market",
            size=float(order['executedQty']) * (1 if order['side'] == 'BUY' else -1),
            price_avg=float(order['avgPrice'])
        )