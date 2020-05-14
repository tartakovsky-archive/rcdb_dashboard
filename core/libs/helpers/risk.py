import numpy as np
from dataclasses import dataclass

from core.bot_mixin import BotMixin


class RiskManager:
    def __init__(self, bot: BotMixin, *args, **kwargs):
        self.bot = bot

    def get_risk_adjusted_exposure(self, *args, **kwargs):
        raise NotImplementedError


class MaxDrawdownRiskManager(RiskManager):
    def __init__(self, bot: BotMixin, max_drawdown: float, *args, **kwargs):
        super().__init__(bot)
        self.max_drawdown = max_drawdown

    def get_risk_adjusted_exposure(self, target_exposure, **kwargs):
        df = self.bot.get_performance()

        equity_high = df.equity.max()
        equity_close = df.equity.values[-1]

        is_trade_allowed = equity_close / equity_high - 1 > -abs(self.max_drawdown)

        if is_trade_allowed:
            return target_exposure
        else:
            return 0
