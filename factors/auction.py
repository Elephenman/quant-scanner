"""
集合竞价异动因子
超短线：9:15-9:25竞价阶段量价异动
"""

import pandas as pd
from factors.base import FactorBase, FactorCategory, score_to_signal


class AuctionFactor(FactorBase):
    name = "集合竞价异动"
    category = FactorCategory.AUCTION
    description = "集合竞价量价异动：高开+放量=强势，低开+放量=弱势"
    default_weight = 1.3
    default_threshold = 0.2
    params = {
        "high_open_pct": {"default": 2.0, "min": 0.5, "max": 10.0, "step": 0.5, "label": "高开阈值(%)"},
        "low_open_pct": {"default": -2.0, "min": -10.0, "max": -0.5, "step": 0.5, "label": "低开阈值(%)"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        """
        计算 (开盘价 - 昨收) / 昨收
        外部可传入 auction_volume 列做量价结合
        """
        prev_close = df["close"].shift(1)
        open_change = (df["open"] - prev_close) / (prev_close + 1e-10) * 100
        return open_change

    def evaluate(self, value, **kwargs):
        high_threshold = kwargs.get("high_open_pct", 2.0)
        low_threshold = kwargs.get("low_open_pct", -2.0)

        if pd.isna(value):
            return 0.0, score_to_signal(0.0), "数据不足"

        # value是开盘涨跌幅(%)
        if value >= high_threshold:
            score = min(1.0, value / 5.0)
            detail = f"高开{value:.2f}%，竞价强势"
        elif value <= low_threshold:
            score = max(-1.0, value / 5.0)
            detail = f"低开{abs(value):.2f}%，竞价弱势"
        else:
            score = value / 10.0 * 0.3
            detail = f"平开{value:.2f}%，竞价中性"

        return score, score_to_signal(score, threshold=0.15), detail
