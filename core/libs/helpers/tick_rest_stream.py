import ccxt
import time
import datetime
import ujson as json
import requests

from dataclasses import dataclass


@dataclass
class Tick:
    timestamp: float
    price: float
    amount: float
    taker_side_sell: bool
    trade_id: str


@dataclass
class TickRequest:
    kaiko_exchange_mapping = dict(
        bitfinex="bfnx",
        bitmex="btmx",
        binance="bnce"
    )

    exchange: str
    timestamp_start: float
    timestamp_end: float
    instrument_class: str  # spot / futures
    base: str
    quote: str

    def to_kaiko(self):
        resp = self.__dict__
        resp['exchange'] = self.kaiko_exchange_mapping[self.exchange]
        resp['page_size'] = 100000
        resp['base'] = self.base.lower()
        resp['quote'] = self.quote.lower()

        return resp

    def to_ccxt(self):
        resp = self.__dict__
        resp['symbol'] = f"{self.base.upper()}/{self.quote.upper()}"
        resp['since'] = int(self.timestamp_start)
        return resp

    def to_bitfinex(self):
        resp = self.__dict__
        resp['symbol'] = f"t{self.base.upper()}{self.quote.upper()}"
        resp['start'] = int(self.timestamp_start) * 1000
        if self.timestamp_end > 0:
            resp['end'] = int(self.timestamp_end) * 1000
        resp['sort'] = 1
        resp['limit'] = 10000
        return resp


class BitfinexTickApi:
    def fetch_trades(self, req: TickRequest, **kwargs):
        bfnx_req = req.to_bitfinex()
        req_url = f"https://api-pub.bitfinex.com/v2/trades/tBTCUSD/hist?"\
                  f"limit={bfnx_req['limit']}&start={bfnx_req['start']}&sort={bfnx_req['sort']}"
        if "end" in bfnx_req:
            req_url += f"&end={bfnx_req['end']}"

        try:
            trades_resp = requests.get(req_url).json()
        except (json.decoder.JSONDecodeError):
            raise

        ticks = []

        for t in trades_resp:
            # t ~= [423318666, 1583917184478, -0.00267668, 7862.11271616]

            # TODO: REMOVE THIS SHIT AS SOON AS POSSIBLE
            #       added to support back compatibility with Kaiko timestamps (rounded mathematically)
            timestamp = round(t[1] / 1000, 0)

            amount = float(t[2])
            ticks.append(Tick(
                trade_id=str(t[0]),  # id
                timestamp=timestamp,  # timestamp milliseconds
                amount=abs(amount),  # amount
                price=float(t[3]),  # price,
                taker_side_sell=amount < 0  # no api equivalent
            ))

        return ticks, None


class KaikoTickApi:
    def __init__(self, api_key):
        self.api_key = api_key

    def fetch_trades(self, req: TickRequest, continuation_token=None, **kwargs):
        url, params = self.__get_url(**req.to_kaiko(), continuation_token=continuation_token)
        resp = self.__make_request(url, params=params)

        if resp['result'] == "error":
            return None, f"Kaiko API error: {resp['message']}"

        trades_resp = resp['data']
        ticks = []

        for t in trades_resp:
            ticks.append(Tick(
                timestamp=float(t['timestamp']) / 1000,
                trade_id=t['trade_id'],
                price=float(t['price']),
                amount=float(t['amount']),
                taker_side_sell=t['taker_side_sell']
            ))

        return ticks, None

    @staticmethod
    def __get_url(exchange, base, quote, instrument_class="spot",
                  timestamp_start=None, timestamp_end=None,
                  page_size=100000, continuation_token=None, **kwargs):
        url = f"https://eu.market-api.kaiko.io/v1/data/trades.v1/exchanges/{exchange}/" \
              f"{instrument_class}/{base}-{quote}/trades"

        params = dict()

        if continuation_token:
            params['continuation_token'] = continuation_token
        else:
            # since we can't request ticks with millisecond precision, it's ok to append ".000Z"
            # but anyway TODO: fix iso 8601 datetime with millisecond precision
            #                  (".000Z" part should be generated from timestamp_start mantissa)
            time_start = datetime.datetime.utcfromtimestamp(timestamp_start).isoformat()
            time_start += ".000Z"
            time_end = datetime.datetime.utcfromtimestamp(timestamp_end).isoformat()
            time_end += ".000Z"

            if time_start:
                params['start_time'] = time_start
            if timestamp_end > 0:
                params['end_time'] = time_end
            if page_size:
                params['page_size'] = page_size

        return url, params

    def __make_request(self, url, params):
        headers = {
            "X-Api-Key": self.api_key,
            "Accept": "application/json"
        }
        r = requests.get(url, headers=headers, params=params, timeout=30)
        return json.loads(r.text)


class TickApiProxy:
    def __init__(self, kaiko_api_params):
        self.bitfinex_api = BitfinexTickApi()
        self.kaiko_api = KaikoTickApi(**kaiko_api_params)

    def fetch_trades(self, req: TickRequest, continuation_token=None):
        if req.timestamp_start > time.time() - 60 * 10:
            # If requested ticks timestamp less the 10 min ago
            # Route request directly to exchange API

            if req.exchange == "bitfinex":
                return self.bitfinex_api.fetch_trades(req)
            else:
                raise Exception(f"Tick api for exchange {req.exchange} is not implemented.")
        else:
            return self.kaiko_api.fetch_trades(req, continuation_token=continuation_token)
