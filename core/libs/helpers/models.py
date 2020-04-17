from joblib import Parallel, delayed
from rcdb_libs import features as ft
from rcdb_libs.job_manager import JobManager, km, t

import numpy as np
import numpy_ext as npext

import pandas as pd
from rcdb_libs import bars as consolidators

from typing import List


def add_basic_features(df):
    bars = df.copy()

    bars['timestamp'] = bars.index.values.astype("int64") / 1e9
    bars['timediff'] = ft.misc.diff(bars['timestamp'].values, fillna=1)
    bars['change'] = ft.misc.frac_change_open_to_close(o=bars['open'].values, c=bars['close'].values)

    return bars


def extract_subset(df, start=None, end=None):
    bars = df.copy()
    if start is not None:
        bars = bars[bars.index >= start]
    if end is not None:
        bars = bars[bars.index < end]

    return bars


def add_random_noise(bars, amplitude, seed=None):
    bars = bars.copy()

    if seed is not None:
        np.random.seed(seed)

    bars.close = bars.close + bars.close * (np.random.rand(bars.index.size) - 0.5) * amplitude
    return bars


def consolidate_datasets(datasets: List[dict], n_jobs=-1) -> List[dict]:
    def config_to_bars(config: dict) -> pd.DataFrame:
        name = config['name']
        date_range = config.get('date_range', None)

        bars = config['bars']
        for cns in config['consolidators']:
            bars = getattr(consolidators, cns['type'])(bars, **cns['kwargs'])

        bars = add_basic_features(bars)

        if date_range is not None:
            bars = extract_subset(bars, start=date_range.get('start'), end=date_range.get('end'))

        # assert len(RcdbData.missing_columns(bars)) == 0, \
        #     f'Dataset {name} has missing columns:\n {RcdbData.missing_columns(bars)}'

        return bars

    def eval_config(config):
        config['bars'] = config_to_bars(config)
        return config

    parallel = Parallel(n_jobs=n_jobs)
    results = parallel(delayed(eval_config)(dataset) for dataset in datasets)

    return results


