"""
RSI超买超卖因子
超短线：RSI低于30=超卖(看多反弹)，高于70=超买(看空回调)
"""

import pandas as pd
from factors.base import FactorBase, FactorCategory, score_to_signal


class RSIFactor(FactorBase):
    name = "RSI超买超卖"
    category = FactorCategory.TECHNICAL
    description = "RSI<30超卖看反弹，RSI>70超买看回调"
    default_weight = 0.8
    default_threshold = 0.2
    params = {
        "period": {"default": 6, "min": 2, "max": 30, "step": 1, "label": "RSI周期"},
        "oversold": {"default": 30, "min": 10, "max": 40, "step": 5, "label": "超卖线"},
        "overbought": {"default": 70, "min": 60, "max": 90, "step": 5, "label": "超买线"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        period = kwargs.get("period", 6)
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def evaluate(self, value, **kwargs):
        oversold = kwargs.get("oversold", 30)
        overbought = kwargs.get("overbought", 70)

        if pd.isna(value):
            return 0.0, score_to_signal(0.0), "数据不足"

        # RSI超卖区 → 看多（反弹逻辑），超买区 → 看空
        if value <= oversold:
            score = (oversold - value) / oversold  # 越低越看多
            score = min(score, 1.0)
            detail = f"RSI={value:.1f}，超卖区，反弹概率大"
        elif value >= overbought:
            score = -(value - overbought) / (100 - overbought)  # 越高越看空
            score = max(score, -1.0)
            detail = f"RSI={value:.1f}，超买区，回调风险高"
        else:
            score = (value - 50) / 100 * 0.3  # 中性区微偏
            detail = f"RSI={value:.1f}，中性区域"

        return score, score_to_signal(score, threshold=0.15), detail
