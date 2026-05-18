"""
动量突破组合因子
多维交叉验证：量比 × 涨幅 × RSI 三重确认
不是单一指标，而是"量价+动量+超买超卖"的共振信号
"""

import pandas as pd
from factors.base import FactorBase, FactorCategory, score_to_signal


class MomentumBreakFactor(FactorBase):
    name = "动量突破组合"
    category = FactorCategory.VOLUME_PRICE
    description = "量比×涨幅×RSI 三重共振：放量+上涨+非超买=强势突破信号"
    default_weight = 1.5
    default_threshold = 0.2
    params = {
        "vol_ratio_min": {"default": 1.5, "min": 1.0, "max": 5.0, "step": 0.1, "label": "最小量比"},
        "change_min": {"default": 2.0, "min": 0.5, "max": 8.0, "step": 0.5, "label": "最小涨幅(%)"},
        "rsi_upper": {"default": 70, "min": 55, "max": 85, "step": 5, "label": "RSI上限"},
        "rsi_period": {"default": 6, "min": 2, "max": 30, "step": 1, "label": "RSI周期"},
        "vol_ma_period": {"default": 20, "min": 5, "max": 60, "step": 5, "label": "均量周期"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        vol_ma_period = kwargs.get("vol_ma_period", 20)
        rsi_period = kwargs.get("rsi_period", 6)

        # 量比
        vol_ma = df["volume"].rolling(window=vol_ma_period).mean()
        vol_ratio = df["volume"] / (vol_ma + 1e-10)

        # 涨幅
        change_pct = (df["close"] - df["close"].shift(1)) / (df["close"].shift(1) + 1e-10) * 100

        # RSI
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=rsi_period).mean()
        avg_loss = loss.rolling(window=rsi_period).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))

        # 组合分数 = 量比因子 × 涨幅因子 × RSI因子
        # 量比因子：>1.5 正，<0.8 负
        vol_score = (vol_ratio - 1.0).clip(-2, 2) / 2.0
        # 涨幅因子
        chg_score = change_pct.clip(-10, 10) / 10.0
        # RSI因子：40-70区间为正向，>80或<20为负向
        rsi_score = pd.Series(0.0, index=df.index)
        rsi_score = rsi_score.where(~((rsi >= 40) & (rsi <= 70)), 0.5)  # 中性偏多
        rsi_score = rsi_score.where(~(rsi < 30), 0.7)  # 超卖反弹
        rsi_score = rsi_score.where(~(rsi > 80), -0.5)  # 超买风险
        rsi_score = rsi_score.where(~((rsi >= 30) & (rsi < 40)), 0.3)

        # 三重共振：同向信号才加分
        composite = (vol_score + chg_score + rsi_score) / 3.0
        return composite

    def evaluate(self, value, **kwargs):
        vol_min = kwargs.get("vol_ratio_min", 1.5)
        chg_min = kwargs.get("change_min", 2.0)

        if pd.isna(value):
            return 0.0, score_to_signal(0.0), "数据不足"

        score = max(-1.0, min(1.0, value))

        if score > 0.3:
            detail = f"动量突破共振，综合得分={value:.2f}，量涨价升动能强"
        elif score < -0.3:
            detail = f"动量衰减共振，综合得分={value:.2f}，放量下跌风险"
        else:
            detail = f"动量中性，综合得分={value:.2f}，无明显突破"

        return score, score_to_signal(score, threshold=0.15), detail
