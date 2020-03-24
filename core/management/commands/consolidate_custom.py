import os
import json
import time
import pandas as pd

from joblib import Parallel, delayed
from django.core.management.base import BaseCommand

from core.models import Consolidator
from core.libs.helpers.hdf import hdf_append
from core.libs.data_feed.consolidation_from_timebars import HdfDataFeed
from core.libs.data_feed.functions import consolidation_functions_name


exchange_names_to_slug = {
    "bitfinex": "bfnx"
}


class ConsolidationCustomFeed:
    def __init__(self, feed_base: HdfDataFeed, consolidate_fn_name, consolidate_fn_kwargs, file_path):
        self.feed_base = feed_base
        self.consolidate_fn = consolidation_functions_name[consolidate_fn_name](**consolidate_fn_kwargs)
        self.file_path = file_path

    def get_tail_from_file(self, tail=1):
        try:
            with pd.HDFStore(self.file_path, mode='r') as store:
                store_rows_count = store.get_storer('table').nrows
                df = store.select('table', start=store_rows_count - tail, stop=store_rows_count)
                return df
        except OSError:
            return pd.DataFrame()

    def get_latest_ts_from_file(self):
        df = self.get_tail_from_file()
        if df.shape[0] == 0:
            return 0
        return df.index.values[0]

    def get_timestamp_to_start(self):
        df = self.get_tail_from_file(2)
        if df.shape[0] == 0:
            return 0
        return df.index.values[0]

    def run(self, verbose=False):
        ts_start = self.get_timestamp_to_start()
        # print(ts_start, pd.to_datetime(ts_start * 1e9))
        df = self.feed_base.get_since(ts_start)

        if verbose:
            print("==============")
            print("Input bars")
            print(df.tail(3))
            print("==============")

        bars = self.consolidate_fn(df)

        if verbose:
            df_bars = bars.copy()
            df_bars.index = pd.to_datetime((df_bars.index * 1e9).astype("int"))
            print("==============")
            print("Consolidated bars")
            print(df_bars)
            print("==============")

        has_new_bars = False
        if bars.shape[0] > 1:
            # we consolidate bars from the TIMESTAMP_START of the previous consolidated bar
            # So we have to skip it
            hdf_append(self.file_path, bars.tail(bars.shape[0] - 1))
            has_new_bars = True

        df_last_bar = self.get_tail_from_file()
        last_bar = None
        if df_last_bar.shape[0] != 0:
            df_last_bar['timestamp'] = df_last_bar.index.values
            df_last_bar = df_last_bar.to_dict("records")
            last_bar = df_last_bar[-1]

        return has_new_bars, last_bar


def consolidate(
        feed_id,
        feed_from_id,
        kaiko_instrument,
        consolidate_fn_name,
        consolidate_fn_kwargs
):
    DATA_DIRECTORY = os.environ.get('DATA_DIRECTORY', 'data')

    feed_base = HdfDataFeed(
        instrument=kaiko_instrument, file_path=f"{DATA_DIRECTORY}/{feed_from_id}.h5")

    feed_custom = ConsolidationCustomFeed(
        feed_base=feed_base,
        consolidate_fn_name=consolidate_fn_name,
        consolidate_fn_kwargs=consolidate_fn_kwargs,
        file_path=f"{DATA_DIRECTORY}/{feed_id}.h5",
    )

    has_new_bars, latest_bar_data = feed_custom.run(verbose=False)

    return {
        "feed_id": feed_id,
        "has_new_bars": has_new_bars,
        "latest_bar_data": latest_bar_data
    }


class Command(BaseCommand):
    help = 'Consolidate Custom consolidators'

    def handle(self, *args, **kwargs):
        # return debug()

        while True:
            # fetch consolidators with parents (typically parents are TickToTimeFrameConsolidators)
            consolidators = Consolidator.objects.all().filter(
                parent__isnull=False,
                is_active=True,
            )
            jobs = []
            for cons in consolidators:
                # create consolidation task if parent has fresh updates
                if cons.parent_update_timestamp == cons.parent.update_timestamp:
                    continue

                jobs.append(dict(
                    feed_id=cons.id,
                    feed_from_id=cons.parent.id,
                    consolidate_fn_name=cons.type.lower(),
                    consolidate_fn_kwargs=cons.get_kwargs(),
                    kaiko_instrument=dict(
                        exchange=exchange_names_to_slug[cons.instrument.exchange.slug],
                        instrument_class=cons.instrument.type.lower(),
                        instrument=cons.instrument.symbol.to_kaiko(),
                    )
                ))

            if jobs:
                # TODO: dedicated process per instrument, to prevent blocking on new instrument history fetch
                # run consolidation jobs in parallel
                resps = Parallel(n_jobs=1, verbose=0)(
                    delayed(consolidate)(**job) for job in jobs
                )

                for feed_resp in resps:
                    if feed_resp['has_new_bars']:
                        # for each job response handle new bar only
                        c = Consolidator.objects.get(id=feed_resp['feed_id'])
                        c.new_bars_event(feed_resp['latest_bar_data'])

            time.sleep(1)

##############################
# DEBUG
##############################


def print_job_results(job):
    df_res = pd.read_hdf(f"data/{job['feed_id']}.h5", key='table')
    df_res.index = pd.to_datetime((df_res.index * 1e9).astype("int"))
    print(df_res)


def debug():
    import os

    df = pd.read_hdf("data/1.h5", key="table")
    # df.index = pd.to_datetime((df.index * 1e9).astype("int"))

    test_feed_from_id = 444
    test_feed_id = 555

    try:
        os.remove(f"data/{test_feed_from_id}.h5")
        os.remove(f"data/{test_feed_id}.h5")
        os.remove(f"data/666.h5")
    except:
        pass

    ts_start, ts_end = ("2020-03-20 20:01:00", "2020-03-20 20:59:00")
    ts_start, ts_end = pd.to_datetime(ts_start).value / 1e9, pd.to_datetime(ts_end).value / 1e9

    timestamps = list(df[(df.index >= ts_start) & (df.index <= ts_end)].index.values)
    print(timestamps)

    job = {
        'feed_id': test_feed_id,
        'feed_from_id': test_feed_from_id,
        'consolidate_fn_name': 'percent',
        'consolidate_fn_kwargs': {
            'bar_size': 0.015
        },
        'kaiko_instrument': {
            'exchange': 'bfnx',
            'instrument_class': 'spot',
            'instrument': 'btc-usd'
        }
    }

    for ts in timestamps[1:]:
        df_test: pd.DataFrame = df[(df.index >= ts_start) & (df.index <= ts)]
        df_test.to_hdf(f"data/{test_feed_from_id}.h5", key="table")
        consolidate(**job)

    print_job_results(job)
    job['feed_id'] = 666

    df[(df.index >= ts_start) & (df.index <= ts_end)].to_hdf(f"data/{test_feed_from_id}.h5", key="table")
    consolidate(**job)

    print_job_results(job)

    df = consolidation_functions_name['percent'](0.015)(df[(df.index >= ts_start) & (df.index <= ts_end)])
    df.index = pd.to_datetime((df.index * 1e9).astype("int"))
    print(df)


