"""
涨跌幅/振幅因子
超短线：涨停/跌停/大阳大阴线判断
"""

import pandas as pd
from factors.base import FactorBase, FactorCategory, score_to_signal


class ChangeAmplitudeFactor(FactorBase):
    name = "涨跌幅振幅"
    category = FactorCategory.VOLUME_PRICE
    description = "当日涨跌幅+振幅：大阳线看多，大阴线看空，高振幅=波动大"
    default_weight = 0.8
    default_threshold = 0.2
    params = {
        "big_up_pct": {"default": 5.0, "min": 2.0, "max": 10.0, "step": 0.5, "label": "大阳线阈值(%)"},
        "big_down_pct": {"default": -5.0, "min": -10.0, "max": -2.0, "step": 0.5, "label": "大阴线阈值(%)"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        change_pct = (df["close"] - df["close"].shift(1)) / (df["close"].shift(1) + 1e-10) * 100
        return change_pct

    def evaluate(self, value, **kwargs):
        big_up = kwargs.get("big_up_pct", 5.0)
        big_down = kwargs.get("big_down_pct", -5.0)

        if pd.isna(value):
            return 0.0, score_to_signal(0.0), "数据不足"

        # 涨停特殊处理
        if value >= 9.9:
            return 0.8, score_to_signal(0.8), f"涨停{value:.2f}%，强势但追高风险大"
        if value <= -9.9:
            return -0.8, score_to_signal(-0.8), f"跌停{value:.2f}%，极度弱势"

        if value >= big_up:
            score = min(0.7, value / 10.0)
            detail = f"大阳线{value:.2f}%，强势"
        elif value <= big_down:
            score = max(-0.7, value / 10.0)
            detail = f"大阴线{value:.2f}%，弱势"
        else:
            score = value / 10.0 * 0.5
            detail = f"涨跌{value:.2f}%，正常波动"

        return score, score_to_signal(score, threshold=0.15), detail
