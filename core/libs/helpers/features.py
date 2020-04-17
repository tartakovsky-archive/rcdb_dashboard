import numpy as np

from rcdb_libs.job_manager import JobManager


def get_calc_features_fn(features_config=None, fn_tasks=None):
    if features_config is None and fn_tasks is None:
        raise Exception("Both features_config and fn_tasks can't be None")

    if features_config is not None and fn_tasks is not None:
        raise Exception("Both features_config and fn_tasks can't be declared")

    def calc_features(bars):
        if bars.index.dtype.name == 'datetime64[ns]':
            bars.index = bars.index.tz_localize(None)
            bars['timestamp'] = bars.index.values.astype("int64") / 1e9 / 1000
        else:
            bars['timestamp'] = bars.index / 1000

        bars['direction'] = np.where(bars.open < bars.close, 1, np.where(bars.open > bars.close, -1, 0))

        if fn_tasks is not None:
            jm = JobManager(
                bars, fn_tasks=fn_tasks, batch_size=100, n_jobs=1,
            )
        else:
            jm = JobManager(
                bars, config=features_config, batch_size=100, n_jobs=1,
            )

        job_results = jm.run_job()
        results = job_results.get_pandas()

        results['target'] = np.where(bars['direction'].shift(-1).fillna(0) == 1, 1, 0)

        results = results.replace([np.inf, -np.inf], 0)
        X_to_predict = results.tail(1).drop('target', axis=1)
        results = results.dropna()

        X = results.drop('target', axis=1)
        y = results['target']

        return X, y, X_to_predict
    return calc_features