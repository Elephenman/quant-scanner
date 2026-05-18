"""
趋势确认组合因子
多指标方向一致性确认：MACD方向 + SMA方向 + 价格位置 三重趋势验证
单独一个指标金叉不够，需要多个指标同向确认才算有效趋势
"""

import pandas as pd
from factors.base import FactorBase, FactorCategory, score_to_signal


class TrendConfirmFactor(FactorBase):
    name = "趋势确认组合"
    category = FactorCategory.TECHNICAL
    description = "MACD+SMA+价格位置 三重趋势确认：多指标同向才算有效趋势"
    default_weight = 1.2
    default_threshold = 0.2
    params = {
        "sma_short": {"default": 5, "min": 2, "max": 20, "step": 1, "label": "SMA短周期"},
        "sma_long": {"default": 20, "min": 10, "max": 60, "step": 5, "label": "SMA长周期"},
        "macd_fast": {"default": 12, "min": 5, "max": 26, "step": 1, "label": "MACD快线"},
        "macd_slow": {"default": 26, "min": 10, "max": 60, "step": 1, "label": "MACD慢线"},
        "macd_signal": {"default": 9, "min": 3, "max": 20, "step": 1, "label": "MACD信号线"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        sma_short = kwargs.get("sma_short", 5)
        sma_long = kwargs.get("sma_long", 20)
        fast = kwargs.get("macd_fast", 12)
        slow = kwargs.get("macd_slow", 26)
        sig = kwargs.get("macd_signal", 9)

        # SMA方向
        sma_s = df["close"].rolling(window=sma_short).mean()
        sma_l = df["close"].rolling(window=sma_long).mean()
        sma_diff = sma_s - sma_l
        sma_score = (sma_diff / (df["close"] + 1e-10) * 100).clip(-1, 1)  # 归一化

        # MACD方向
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=sig, adjust=False).mean()
        hist = (dif - dea) * 2
        macd_score = (hist / (df["close"] * 0.01 + 1e-10)).clip(-1, 1)

        # 价格位置（相对SMA长周期）
        price_pos = ((df["close"] - sma_l) / (sma_l + 1e-10) * 10).clip(-1, 1)

        # 趋势一致性：三者同向时放大
        # 用sign判断方向
        sma_dir = sma_score.apply(lambda x: 1 if x > 0.05 else (-1 if x < -0.05 else 0))
        macd_dir = macd_score.apply(lambda x: 1 if x > 0.05 else (-1 if x < -0.05 else 0))
        price_dir = price_pos.apply(lambda x: 1 if x > 0.05 else (-1 if x < -0.05 else 0))

        # 一致性加分：3个同向=1.5x，2个同向=1.2x，有矛盾=0.7x
        consistency = (sma_dir + macd_dir + price_dir).abs()
        multiplier = pd.Series(1.0, index=df.index)
        multiplier = multiplier.where(~(consistency >= 3), 1.5)
        multiplier = multiplier.where(~(consistency == 2), 1.2)
        multiplier = multiplier.where(~(consistency <= 1), 0.7)

        # 加权组合
        composite = (sma_score * 0.35 + macd_score * 0.35 + price_pos * 0.3) * multiplier
        return composite.clip(-1, 1)

    def evaluate(self, value, **kwargs):
        if pd.isna(value):
            return 0.0, score_to_signal(0.0), "数据不足"

        score = max(-1.0, min(1.0, value))

        if score > 0.3:
            detail = f"多头趋势确认，多指标同向看多，得分={value:.2f}"
        elif score < -0.3:
            detail = f"空头趋势确认，多指标同向看空，得分={value:.2f}"
        else:
            detail = f"趋势分歧，指标方向不一致，得分={value:.2f}"

        return score, score_to_signal(score, threshold=0.15), detail
