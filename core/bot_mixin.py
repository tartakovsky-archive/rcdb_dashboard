from abc import ABC
import pandas as pd

from core.libs.helpers.data_classes import *
from core.libs.helpers.ccxt import CcxtExecutor


class BotException(Exception):
    pass


class NothingToExecuteException(BotException):
    """
    Desired position is already reached and there is no trade can be made according to `min_trade_amount`
    """
    pass


class BotMixin:
    # def __init__(self, *args, **kwargs):
    #    raise NotImplementedError

    def get_performance(self) -> pd.DataFrame:
        """
        :return: pd.DataFrame(columns=[signal, balance, unrealized_pnl, exposure, timestamp])
        """
        raise NotImplementedError

    def get_exposure(self) -> float:
        """
        Real exposure from the exchange.
        :return:
        """
        raise NotImplementedError

    def get_target_exposure(self) -> float:
        """
        Exposure that is planned but not executed yet.
        :return:
        """
        raise NotImplementedError

    def get_balance(self) -> QuoteBalanceData:
        """
        Exposure that is planned but not executed yet.
        :return:
        """
        raise NotImplementedError

    def get_ticker(self) -> TickerData:
        """
        Exposure that is planned but not executed yet.
        :return:
        """
        raise NotImplementedError

    def create_order(self, size: float) -> OrderResultData:
        raise NotImplementedError

    def execute_desired_position(
            self,
            desired_base_size: float,
            desired_quote_price: float,
            slippage_pct_position_increase: float,
            slippage_pct_position_decrease: float,
            min_trade_amount: float,
            max_trade_amount: float,
            size_round_precision: int = 9
    ):
        """
        Execute BotTargetState
        :return:
        """
        raise NotImplementedError


class BotCcxtMixin(BotMixin):
    exchange_slug: str
    exchange_credentials_dict: dict
    symbol: SymbolData

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__ccxt_manager = None

    @property
    def ccxt_manager(self):
        if self.__ccxt_manager is None:
            self.__ccxt_manager = CcxtExecutor(
                exchange_slug=self.exchange_slug,
                exchange_credentials_dict=self.exchange_credentials_dict,
                symbol=self.symbol
            )
        return self.__ccxt_manager

    def get_exposure(self, on_price: float = None) -> float:
        bot_balance = self.ccxt_manager.get_balance()
        bot_position = self.ccxt_manager.get_position()
        position_price = on_price

        if position_price is None:
            position_price = bot_position.price_avg

        return bot_position.size * position_price / bot_balance.amount_all

    def get_balance(self):
        return self.ccxt_manager.get_balance()

    def get_ticker(self):
        return self.ccxt_manager.get_ticker()

    def get_position(self):
        return self.ccxt_manager.get_position()

    def create_order(self, size: float) -> OrderResultData:
        return self.ccxt_manager.create_order(size)

    def execute_desired_position(
            self,
            desired_base_size: float,
            desired_quote_price: float,
            slippage_pct_position_increase: float,
            slippage_pct_position_decrease: float,
            min_trade_amount: float,
            max_trade_amount: float,
            size_round_precision: int = 9
    ):
        """
        Execute BotTargetState
        :return:
        """
        raise NotImplementedError
