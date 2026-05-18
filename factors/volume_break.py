"""
放量突破因子
超短线核心：成交量异动 + 价格突破
"""

import pandas as pd
from factors.base import FactorBase, FactorCategory, score_to_signal


class VolumeBreakFactor(FactorBase):
    name = "放量突破"
    category = FactorCategory.VOLUME_PRICE
    description = "成交量放大2倍以上+价格上涨=放量突破看多，放量下跌看空"
    default_weight = 1.2
    default_threshold = 0.3
    params = {
        "vol_ratio_threshold": {"default": 2.0, "min": 1.2, "max": 5.0, "step": 0.2, "label": "量比阈值"},
        "ma_period": {"default": 20, "min": 5, "max": 60, "step": 5, "label": "均量周期"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        ma_period = kwargs.get("ma_period", 20)
        vol_ma = df["volume"].rolling(window=ma_period).mean()
        vol_ratio = df["volume"] / (vol_ma + 1e-10)
        # 正=放量上涨，负=放量下跌
        direction = (df["close"] - df["close"].shift(1)) / (df["close"].shift(1) + 1e-10)
        result = vol_ratio * direction * 100  # 量比 × 涨跌幅
        return result

    def evaluate(self, value, **kwargs):
        vol_threshold = kwargs.get("vol_ratio_threshold", 2.0)

        if pd.isna(value):
            return 0.0, score_to_signal(0.0), "数据不足"

        if value > 0:
            # 放量上涨
            score = min(1.0, value / 5.0)
            detail = f"放量上涨，信号强度={value:.2f}"
        elif value < 0:
            # 放量下跌
            score = max(-1.0, value / 5.0)
            detail = f"放量下跌，风险信号={value:.2f}"
        else:
            score = 0.0
            detail = "量价正常"

        return score, score_to_signal(score), detail
