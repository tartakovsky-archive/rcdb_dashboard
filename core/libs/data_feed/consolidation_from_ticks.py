import time
import pandas as pd

from core.libs.helpers.hdf import hdf_append, hdf_read
from core.libs.helpers.tick_rest_stream import TickRequest

import logging
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)


class BackfillProxyApi:
    def __init__(self, api):
        self.api = api

    def backfill(self, tick_consolidator: "TickConsolidator", until_timestamp, one_batch_only=False):
        timestamp_start = tick_consolidator.get_dataset_end_date()
        timestamp_end = time.time() // tick_consolidator.time_frame_seconds * tick_consolidator.time_frame_seconds
        logging.info(f'Timestamp start: {timestamp_start}')

        fetch_req = TickRequest(
            exchange=tick_consolidator.exchange,
            instrument_class=tick_consolidator.instrument_class,
            base=tick_consolidator.base,
            quote=tick_consolidator.quote,
            timestamp_start=timestamp_start,
            timestamp_end=-1
        )

        try:
            ticks, err = self.api.fetch_trades(fetch_req)
        except Exception as ex:
            err = str(ex)

        if err:
            raise Exception(err)

        # "is live" means "first tick timestamp is less then 10 min delay from time.time()"
        is_live_data = time.time() - ticks[1].timestamp < 60 * 10
        if is_live_data:
            is_until_timestamp_reached = False
            for t in ticks:
                if until_timestamp < t.timestamp:
                    is_until_timestamp_reached = True
                    break

            if not is_until_timestamp_reached:
                return

        for tick in ticks:
            # TODO: we can add bid/ask or ticker info as a latest tick to
            #       force closing current bar when new timeframe started.
            #       This will improve lag between new timeframe start time and new bar arrival time.
            tick_consolidator.on_tick(**tick.__dict__, is_backfill_tick=True)

        tick_consolidator.dataset_flush()


##############################
# Tick consolidation
##############################


class TickToTimeframeConsolidator:
    bar: dict = None  # dict(timestamp, open, high, low, close, volume, ticks)
    time_frame_prev: int = 0  # last_tick_timestamp // self.timeframe_seconds
    tick_timestamp_latest: int = None
    dataset: pd.DataFrame = None
    is_first_bar = True  # always drop first consolidated bar (to ensure dataset consistency)

    is_backfilled = False  # Consolidator should be backfilled before starts to receive messages

    def __init__(self, exchange, instrument_class, base, quote, time_frame_seconds,
                 file_path,
                 backfill_api: BackfillProxyApi,
                 dataset_flush_auto=False):
        """
        :param base:
        :param quote:
        :param time_frame_seconds:
        :param data_directory:
        :param dataset_flush_auto: append h5 file on each new file
        """
        self.exchange = exchange
        self.instrument_class = instrument_class
        self.base = base
        self.quote = quote
        self.time_frame_seconds = time_frame_seconds
        # self.data_directory = data_directory
        self.file_path = file_path
        self.dataset_flush_auto = dataset_flush_auto
        self.backfill_api = backfill_api

    ##############################
    # Dataset
    ##############################

    def get_dataset(self):
        return pd.read_hdf(self.file_path, key='table')

    def get_latest_bar_from_file(self) -> pd.DataFrame:
        try:
            return hdf_read(self.file_path, tail=1)
        except OSError:
            return pd.DataFrame()

    def get_dataset_end_date(self):
        df = self.get_latest_bar_from_file()
        if df.shape[0] == 0:
            return 0  # epoch start timestamp

        return df.index.values[-1]

    def dataset_append_bar(self, df_bar):
        if self.is_first_bar:
            # always drop first consolidated bar (to ensure dataset consistency)
            self.is_first_bar = False
            return

        if self.dataset is None:
            self.dataset = df_bar
        else:
            self.dataset = self.dataset.append(df_bar)

        if self.dataset_flush_auto:
            self.dataset_flush()

    def dataset_flush(self):
        if self.dataset is None:
            return

        # print("======> FILE <========")
        # df_tmp_file = self.get_dataset().tail(3)
        # df_tmp_file.index = pd.to_datetime(df_tmp_file.index * 1000000000)
        # print(df_tmp_file)
        # print("======> TICKS <========")
        # df_tmp = self.dataset.copy()
        # df_tmp.index = pd.to_datetime(df_tmp.index * 1000000000)
        # print(df_tmp)
        # print("======> /// <========")

        hdf_append(self.file_path, self.dataset)
        self.dataset = None

    ##############################
    # Consolidate
    ##############################

    def backfill(self, until_timestamp, taker_side_sell=None, trade_id=None, one_batch_only=False):
        if self.tick_timestamp_latest is None:
            # recording first tick timestamp
            self.tick_timestamp_latest = self.get_dataset_end_date()

        has_new_bars = False

        if self.tick_timestamp_latest < until_timestamp:
            self.backfill_api.backfill(
                tick_consolidator=self,
                until_timestamp=until_timestamp,
                one_batch_only=one_batch_only)

            self.dataset_flush_auto = True
            self.is_backfilled = True
            has_new_bars = True
        else:
            self.tick_timestamp_latest = until_timestamp

        df_last_bar = self.get_latest_bar_from_file()
        df_last_bar['timestamp'] = df_last_bar.index.values
        df_last_bar = df_last_bar.to_dict("records")

        return (
            has_new_bars,
            df_last_bar[-1]
        )

    def on_tick(self, timestamp, price, amount, taker_side_sell=None, trade_id=None, is_backfill_tick=False):
        if not self.is_backfilled and not is_backfill_tick:
            is_backfill_done = self.backfill(since_timestamp=timestamp, taker_side_sell=None, trade_id=None)
            if not is_backfill_done:
                return

        self.tick_timestamp_latest = int(timestamp)
        price = float(price)
        amount = float(amount)

        if self.bar is None:
            prev_bar_close = None
        else:
            prev_bar_close = self.bar['close']

        if self.is_bar_consolidated():
            self.on_bar_close()

        if self.bar is None:
            self.bar = dict(
                timestamp=self.tick_timestamp_latest,
                open=prev_bar_close if prev_bar_close is not None else price,  # price,
                high=price,
                low=price,
                close=price,
                volume=amount,
                ticks=1
            )
            self.on_bar_open()
            return

        else:
            self.bar['volume'] += amount
            if self.bar['high'] < price:
                self.bar['high'] = price
            elif self.bar['low'] > price:
                self.bar['low'] = price

        self.bar['close'] = price
        self.bar['ticks'] += 1

    def get_last_tick_time_frame(self):
        return self.tick_timestamp_latest // self.time_frame_seconds

    def is_bar_consolidated(self):
        time_frame_now = self.get_last_tick_time_frame()

        if self.time_frame_prev < time_frame_now:
            self.time_frame_prev = time_frame_now
            return True

        return False

    def on_bar_open(self):
        pass

    def on_bar_close(self):
        if self.bar is None:
            return False

        bar_data = dict(
            timestamp_open=self.get_last_tick_time_frame() * self.time_frame_seconds - self.time_frame_seconds,
            open=self.bar['open'],
            high=self.bar['high'],
            low=self.bar['low'],
            close=self.bar['close'],
            volume=self.bar['volume'],
        )

        df_bar = pd.DataFrame([[
            bar_data['timestamp_open'],
            bar_data['open'],
            bar_data['high'],
            bar_data['low'],
            bar_data['close'],
            bar_data['volume'],
        ]], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        if hasattr(self, 'bar_logger'):
            self.bar_logger.log(**bar_data)

        df_bar = df_bar.set_index("timestamp")
        self.dataset_append_bar(df_bar)

        self.bar = None