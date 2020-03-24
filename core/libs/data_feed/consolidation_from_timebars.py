import os
import time
import logging
from core.libs.helpers.event_logger import EventDataLogger
import pandas as pd


class HdfDataFeed:
    class Exception:
        class BarIsMissing(Exception):
            pass

    def __init__(self, instrument, file_path):
        """
        instruments = [
            dict(
                exchange='bnce',  # Binance exchange
                instrument_class='spot',  # Spot market
                instrument='btc-usdt',  # all instrument traded against BTC
            ),
            dict(
                exchange='bfnx',  # Binance exchange
                instrument_class='spot',  # Spot market
                instrument='btc-usd',  # all instrument traded against BTC
            ),
            dict(
                exchange='btmx',  # Binance exchange
                instrument_class='spot',  # Spot market
                instrument='btc-usd',  # all instrument traded against BTC
            )
        ]
        :param instruments:
        """

        self.instrument = instrument
        self.file_path = file_path

    def get_dataset_file_name(self):
        return self.file_path  # os.path.join(self.data_directory, self.get_dataset_name(instrument) + ".h5")

    def get_dataset(self):
        return self.get_since(0, None, False)

    def get_since(self, timestamp_seconds, rows_count=None, raise_if_bar_missing=True):
        """

        :param timestamp_seconds:
        :param rows_count: optimize file read performance with this argument,
                            if None all dataset is loaded, else only `rows_count` from the end of file
        :param raise_if_bar_missing:
        :return:
        """
        resp = dict()

        # for inst in self.instruments:
        while True:
            try:
                with pd.HDFStore(self.get_dataset_file_name(), mode='r') as store:
                    store_rows_count = store.get_storer('table').nrows
                    if rows_count is None:
                        df = store.select('table')
                    else:
                        df = store.select('table', start=store_rows_count - rows_count, stop=store_rows_count)
                    df = df[df.index >= timestamp_seconds]

                    if raise_if_bar_missing and df.shape[0] == 0:
                        raise self.Exception.BarIsMissing(f"No bars since {timestamp_seconds} for "
                                                          + self.get_dataset_file_name() + " dataset")

                    resp = df
                    break
            except (OSError, AttributeError):
                time.sleep(0.1)
                logging.debug("File race condition occurred, waiting for 0.1 sec to retry")
                continue

        return resp


class ConsolidationDataFeed:
    is_full_fetched = False
    timestamp_latest: int = -1
    df_data: pd.DataFrame = None
    df_bars: pd.DataFrame = None

    def __init__(self, feed_base: HdfDataFeed, consolidate_fn, bars_tail=None,
                 bars_base_logger: EventDataLogger = None, bars_consolidated_logger: EventDataLogger = None):
        self.feed_base = feed_base
        self.consolidate_fn = consolidate_fn
        self.bars_tail = bars_tail
        self.bars_base_logger = bars_base_logger
        self.bars_consolidated_logger = bars_consolidated_logger

    def __get_all_bars(self):
        """
        Return full consolidated dataset
        :return:
        """
        data = self.__get_feed_updates(self.feed_base, timestamp_latest=0)
        bars = self.consolidate_fn(data)
        return bars

    ####################################
    # Updates
    ####################################

    def get_base_quote(self):
        instruments = self.feed_base.instruments
        if len(instruments) != 1:
            raise Exception("Multiple instruments in base data feed is prohibited")
        [base, quote] = instruments[0]['instrument'].split("-")
        return base, quote

    @staticmethod
    def __get_feed_updates(feed, timestamp_latest):
        update = feed.get_since(timestamp_latest)
        datasets = list(update.keys())

        if len(datasets) != 1:
            raise Exception("Expected only one dataset from feed_base, looks like you have multiple instruments")

        # TODO: remove `drop_duplicates` after fixing bug with duplicate rows
        return update[datasets[0]].drop_duplicates(keep='first')

    def __refresh_data(self):
        data = self.__get_feed_updates(self.feed_base, self.timestamp_latest)

        if self.df_data is None:
            self.df_data = data
        else:
            self.df_data = self.df_data.append(data)

            # log arrived time bar
            if self.bars_base_logger is not None:
                for i in range(data.shape[0]):
                    bar_data = dict(
                        timestamp_open=data.index.values[i],
                        open=data.open.values[i],
                        high=data.high.values[i],
                        low=data.low.values[i],
                        close=data.close.values[i],
                        volume=data.volume.values[i],
                    )
                    self.bars_base_logger.log(**bar_data)

        self.timestamp_latest = self.df_data.index.values[-1]

    def get_full(self):
        """
        Initial consolidation from all available data
        Need to be called after consolidation feed init
        :return:
        """
        self.timestamp_latest = 0
        self.is_full_fetched = True

        self.__refresh_data()
        self.df_bars = self.consolidate_fn(self.df_data)
        return self.df_bars

    def get_updates(self):
        if not self.is_full_fetched:
            raise Exception("You should call `get_full()` first, "
                            "to initialize bars from all available data.")
        try:
            self.__refresh_data()
        except self.feed_base.Exception.BarIsMissing:
            # No new data bars, therefore no new consolidated bars
            return None

        if self.bars_tail is not None:
            timestamp_start = self.df_bars.tail(self.bars_tail + 1).index.values[0]
            self.df_data = self.df_data[self.df_data.index >= timestamp_start]

        index_before = self.df_bars.index.values[-1]
        self.df_bars = self.consolidate_fn(self.df_data)
        index_after = self.df_bars.index.values[-1]

        if index_before < index_after:
            df_bars_new = self.df_bars[self.df_bars.index > index_before]

            # log new consolidated bar
            if self.bars_consolidated_logger is not None:
                for i in range(df_bars_new.shape[0]):
                    bar_data = dict(
                        timestamp_open=df_bars_new.index.values[i],
                        open=df_bars_new.open.values[i],
                        high=df_bars_new.high.values[i],
                        low=df_bars_new.low.values[i],
                        close=df_bars_new.close.values[i],
                        volume=df_bars_new.volume.values[i],
                    )
                    self.bars_consolidated_logger.log(**bar_data)

            return df_bars_new

        return None


if __name__ == "__main__":
    kaiko_instruments = [
        dict(
            exchange='bnce',  # Binance exchange
            instrument_class='spot',  # Spot market
            instrument='btc-usdt',  # all instrument traded against BTC
            time_frame_seconds=60,
        ),
        dict(
            exchange='bnce',  # Binance exchange
            instrument_class='spot',  # Spot market
            instrument='eth-usdt',  # all instrument traded against BTC
            time_frame_seconds=60,
        ),
        # dict(
        #     exchange='bfnx',  # Binance exchange
        #     instrument_class='spot',  # Spot market
        #     instrument='btc-usd',  # all instrument traded against BTC
        #     time_frame_seconds=60,
        # ),
        dict(
            exchange='btmx',  # Binance exchange
            instrument_class='spot',  # Spot market
            instrument='btc-usd',  # all instrument traded against BTC
            time_frame_seconds=60,
        )
    ]
    feed = HdfDataFeed(instruments=kaiko_instruments, data_directory="data/kaiko")
    missing_seconds = 0
    timeframe = 60
    timestamp = int(time.time()) // timeframe * timeframe - timeframe
    while True:
        try:
            data = feed.get_since(timestamp)
            print("\n\n\n\n\n\n\n", pd.to_datetime(time.time() * 1000000000))
            for key in data.keys():
                print("====")
                print(key)
                print(data[key])
            missing_seconds = 0
            timestamp = int(time.time()) // timeframe * timeframe - timeframe
        except HdfDataFeed.Exception.BarIsMissing as ex:
            missing_seconds += 1
            # print('\n\n\n', ex)
            # print("Misssing seconds:", missing_seconds)

        time.sleep(1)
