import logging
from enum import Enum
from typing import Optional

import requests
import pandas as pd


logger = logging.getLogger("rcdb_datastore")


class DataException(Exception):
    pass


class DataType(Enum):
    ohlcv = 'ohlcv'
    kalman = 'kalman'
    bot_performance = 'bot_performance'
    price_index = 'price_index'


class DataStore:
    data_type = DataType

    def __init__(self, api_url, token):
        self.api_url = api_url
        self.session = requests.Session()
        self.session.headers.update({'Authorization': f'Bearer {token}'})

    @staticmethod
    def __get_data_type(df: pd.DataFrame) -> Optional[DataType]:
        cols = set(df.columns)
        if "high" in cols:
            return DataType.ohlcv
        if "s1_x" in cols:
            return DataType.kalman
        if "balance_base" in cols:
            return DataType.bot_performance

        return None

    def __send_data(self, data_type: DataType, rows):
        logger.debug(f"sending {len(rows)} rows to `{data_type}`")
        r = self.session.post(
            f"{self.api_url}/log/",
            json=rows,
            params={"type": data_type.value},
            timeout=100
        )
        if r.status_code != 200:
            raise requests.exceptions.RequestException(f'Send data error {r.status_code} {r.text}')

    def __get_data(self, data_type, query) -> Optional[pd.DataFrame]:
        logger.debug(f"loading `{data_type}` with query={query}")
        query = {
            k: (v.upper() if k in {'exchange', 'symbol', 'instrument'} else v)
            for k, v in query.items()
        }
        r = self.session.get(
            f"{self.api_url}/latest/",
            params={**query, "type": data_type.value},
            timeout=100
        )
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 404:
            return None
        else:
            raise DataException(r.text)

    def append(self, df: pd.DataFrame):
        data_type = self.__get_data_type(df)

        if not data_type:
            raise ValueError(f'Unsupported data_type of {df}')

        rows = df.to_dict(orient="records")
        self.__send_data(data_type, rows)

    def read(self, data_type: DataType, query_params):
        rows = self.__get_data(data_type, query_params)
        if rows is not None:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame()

        if df.shape[0] > 0:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index("timestamp")
        return df
