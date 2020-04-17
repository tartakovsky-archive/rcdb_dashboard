import os
import uuid
import logging

import numpy as np
import pandas as pd


DEFAULT_AGGREGATE_MAPPING = {
    'open': 'first',
    'high': 'max',
    'low': 'min',
    'close': 'last',
    'volume_buy': 'sum',
    'volume_sell': 'sum',
    'volume': 'sum',
    'volume_quote_buy': 'sum',
    'volume_quote_sell': 'sum',
    'volume_quote': 'sum',
    'ticks_buy': 'sum',
    'ticks_sell': 'sum',
    'ticks': 'sum'
}


def consolidate(
    df: pd.DataFrame,
    column_name: str,
    aggregate: dict = None,
    aggregate_default='first',
    verbose=False
):
    if aggregate is None:
        aggregate = DEFAULT_AGGREGATE_MAPPING.copy()

    df = df.copy()

    if verbose:
        unexpected_columns = list(set(df.columns) - set(aggregate.keys()))
        logging.warning(
            f'WARNING: mapping rule has not been found for columns {unexpected_columns}. '
            f'Using the default rule: "{aggregate_default}".'
        )

    # save index
    index_tmp_name = str(uuid.uuid4())
    index_prev_name = df.index.name

    columns = list(df.columns) + [index_tmp_name]
    df[index_tmp_name] = df.index

    # tmp column for aggregation
    agg_id_name = str(uuid.uuid4())
    df[agg_id_name] = df[column_name].cumsum()  # np.where(df[column_name] != df[column_name].shift(1), 1, 0).cumsum()
    tmp = df[agg_id_name].values
    tmp[0] = tmp[1]
    df[agg_id_name] = tmp

    # apply default aggregation
    cols_exists = []
    for col in df.columns:
        cols_exists.append(col)
        if col not in aggregate:
            aggregate[col] = aggregate_default

    for col in list(aggregate.keys()):
        if col not in cols_exists:
            del aggregate[col]

    # aggregate
    df_new = df.groupby([agg_id_name]).agg(aggregate)[columns]
    df.drop([agg_id_name, index_tmp_name], axis=1, inplace=True)

    # return original index
    df_new = df_new.set_index(index_tmp_name)
    df_new.index.rename(index_prev_name, inplace=True)

    # if drop_first_bar:
    #     df_new = df_new[1:]

    return df_new


def price_pct_threshold_default(open: np.array, close: np.array,
                        threshold_up: float, threshold_down: float = None) -> np.array:
    """Fixed Range

    Price move (range) accumulation feature. Fixed % range.

    :param open: Series of open prices
    :param close: Series of close prices
    :param threshold_up: Event UP is generated after price moves by more percent than this threshold
    :param threshold_down: (if None than equal to threshold_up) Event DOWN is generated after price
                            moves by more percent than this threshold
    :return: Binary series. 1 signals firing of accumulation event.
    """
    if threshold_down is None:
        threshold_down = threshold_up

    bars = []
    upper_limit, lower_limit = None, None
    for v_close, v_open in np.c_[close, open]:
        if upper_limit is None:
            upper_limit, lower_limit = (v_open * (1 + threshold_up), v_open * (1 - threshold_down))

            # if abs(upper_limit / v_open - 1) < threshold_up:
            #     upper_limit += 0.5
            #
            # if abs(lower_limit / v_open - 1) < threshold_down:
            #     lower_limit -= 0.5

        if v_close >= upper_limit or v_close <= lower_limit:
            upper_limit, lower_limit = None, None
            bars.append(1)
        else:
            bars.append(0)
    feature = np.array([0] + bars[:-1])
    assert feature.shape == close.shape
    return feature


def consolidate_timebars_to_percent_bars(bar_size):
    def construct_bars(ohlcv):
        bars_1m = ohlcv
        bars_1m['f'] = price_pct_threshold_default(
            bars_1m.open.values, bars_1m.close.values, bar_size
        )
        bars = consolidate(bars_1m, column_name="f")

        last_bar = bars.tail(1)
        last_bar_open = last_bar.open.values[0]
        last_bar_close = last_bar.close.values[0]

        if abs(last_bar_close / last_bar_open - 1) < bar_size:
            bars = bars.head(bars.shape[0] - 1)

        return bars
    return construct_bars


consolidation_functions_name = dict(
    percent=consolidate_timebars_to_percent_bars
)


# def get_bot_feed_dataframe(bot: "Bot", rows_count=None) -> pd.DataFrame:
#     data_directory = os.environ.get('DATA_DIRECTORY', 'data')
#     feed_id = bot.data_feed.id
#     file_path = f"{data_directory}/{feed_id}.h5"
#
#     with pd.HDFStore(file_path, mode='r') as store:
#         store_rows_count = store.get_storer('table').nrows
#         if rows_count is None:
#             df = store.select('table')
#         else:
#             if store_rows_count < rows_count:
#                 raise Exception(f"Bars feed_id={feed_id} has {store_rows_count} bars in store "
#                                 f"(less then requested amount {rows_count}).")
#             df = store.select('table', start=store_rows_count - rows_count, stop=store_rows_count)
#
#         return df
