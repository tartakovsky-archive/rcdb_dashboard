import time
import logging
import tables
import pandas as pd


def hdf_append(file_path: str, df: pd.DataFrame):
    """
    Append DataFrame to hdf file
    :param file_path:
    :param df: pd.DataFrame
    :return:
    """
    while True:
        try:
            logging.debug(f"\n> Saving: {file_path} // {str(df.shape)} // {df.index.values[0]} // "
                          f"DateTime: {pd.to_datetime(time.time() * 1000000000)}")

            with pd.HDFStore(file_path, mode='a') as f:
                f.append('table', df, format='t', data_columns=True)
            break
        except tables.exceptions.HDF5ExtError as ex:
            logging.error("hdf_append", str(ex))
            time.sleep(0.1)
            continue


def hdf_read(file_path: str, tail: int = None) -> pd.DataFrame:
    """
    Read tail rows from the end of hdf file.
    If tail is None, whole file would be returned.
    :param file_path:
    :param tail: number of rows from the end to return
    :return: pd.DataFrame
    """
    while True:
        try:
            if tail is None:
                return pd.HDFStore(file_path, mode='r', key="table")
            else:
                with pd.HDFStore(file_path, mode='r') as store:
                    store_rows_count = store.get_storer('table').nrows
                    df = store.select('table', start=store_rows_count - tail, stop=store_rows_count)
                    return df
        except tables.exceptions.HDF5ExtError as ex:
            time.sleep(0.1)
            continue