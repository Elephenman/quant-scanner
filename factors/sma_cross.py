"""
SMA均线金叉/死叉因子
超短线核心：5日/10日均线交叉
"""

import pandas as pd
from factors.base import FactorBase, FactorCategory, score_to_signal


class SMAFactor(FactorBase):
    name = "SMA金叉死叉"
    category = FactorCategory.TECHNICAL
    description = "短期均线上穿长期均线=金叉(看多)，下穿=死叉(看空)"
    default_weight = 1.0
    default_threshold = 0.3
    params = {
        "short_period": {"default": 5, "min": 2, "max": 20, "step": 1, "label": "短周期"},
        "long_period": {"default": 10, "min": 5, "max": 60, "step": 1, "label": "长周期"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        short_p = kwargs.get("short_period", 5)
        long_p = kwargs.get("long_period", 10)
        sma_short = df["close"].rolling(window=short_p).mean()
        sma_long = df["close"].rolling(window=long_p).mean()
        diff = sma_short - sma_long
        return diff

    def evaluate(self, value, **kwargs):
        short_p = kwargs.get("short_period", 5)
        long_p = kwargs.get("long_period", 10)
        if pd.isna(value):
            return 0.0, score_to_signal(0.0), "数据不足"

        # 用股价的2%作为归一化基准，避免原公式小值几乎为0大值直跳满
        # value = SMA_short - SMA_long，相对于股价做归一化
        norm = max(abs(value), 1e-6)
        score = (value / (norm + 1.0)) * 2.0  # 值越大分数越高，但压制极端值
        score = max(-1.0, min(1.0, score))

        if value > 0:
            detail = f"SMA{short_p}在SMA{long_p}上方，金叉状态，价差={value:.2f}"
        else:
            detail = f"SMA{short_p}在SMA{long_p}下方，死叉状态，价差={value:.2f}"

        return score, score_to_signal(score), detail
