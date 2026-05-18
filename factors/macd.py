"""
MACD因子
超短线常用：MACD金叉/死叉 + 柱状图方向
"""

import pandas as pd
from factors.base import FactorBase, FactorCategory, score_to_signal


class MACDFactor(FactorBase):
    name = "MACD金叉死叉"
    category = FactorCategory.TECHNICAL
    description = "MACD金叉(看多)/死叉(看空)，柱状图由负转正=金叉"
    default_weight = 1.0
    default_threshold = 0.3
    params = {
        "fast_period": {"default": 12, "min": 5, "max": 26, "step": 1, "label": "快线周期"},
        "slow_period": {"default": 26, "min": 10, "max": 60, "step": 1, "label": "慢线周期"},
        "signal_period": {"default": 9, "min": 3, "max": 20, "step": 1, "label": "信号线周期"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        fast = kwargs.get("fast_period", 12)
        slow = kwargs.get("slow_period", 26)
        sig = kwargs.get("signal_period", 9)

        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=sig, adjust=False).mean()
        hist = (dif - dea) * 2

        # 返回hist作为因子值（柱状图）
        return hist

    def evaluate(self, value, **kwargs):
        if pd.isna(value):
            return 0.0, score_to_signal(0.0), "数据不足"

        # MACD柱状图归一化：用tanh-like函数，避免原公式的阶梯效应
        # value范围通常在 -1~1 之间（已经过 *2），用softsign归一化
        score = value / (1.0 + abs(value))
        score = max(-1.0, min(1.0, score))

        if value > 0:
            detail = f"MACD柱状图正值，多头区域，值={value:.4f}"
        else:
            detail = f"MACD柱状图负值，空头区域，值={value:.4f}"

        return score, score_to_signal(score), detail
