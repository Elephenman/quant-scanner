"""
筹码异动组合因子
超短线核心关注：换手率 × 振幅 × 量比 三维交叉
高换手+高振幅+放量 = 筹码大幅换手，短线即将变盘
"""

import pandas as pd
from factors.base import FactorBase, FactorCategory, score_to_signal


class ChipActivityFactor(FactorBase):
    name = "筹码异动组合"
    category = FactorCategory.VOLUME_PRICE
    description = "换手率×振幅×量比 三维交叉：高换手+高振幅+放量=筹码大幅换手，变盘在即"
    default_weight = 1.3
    default_threshold = 0.2
    params = {
        "turnover_high": {"default": 8.0, "min": 3.0, "max": 25.0, "step": 1.0, "label": "高换手阈值(%)"},
        "amplitude_high": {"default": 5.0, "min": 2.0, "max": 15.0, "step": 0.5, "label": "高振幅阈值(%)"},
        "vol_ratio_high": {"default": 2.0, "min": 1.2, "max": 5.0, "step": 0.2, "label": "高量比阈值"},
        "vol_ma_period": {"default": 20, "min": 5, "max": 60, "step": 5, "label": "均量周期"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        vol_ma_period = kwargs.get("vol_ma_period", 20)

        # 换手率评分（如有）
        if "turnover_rate" in df.columns:
            turnover = pd.to_numeric(df["turnover_rate"], errors="coerce").fillna(0)
            turnover_score = (turnover / 15.0).clip(-1, 1)  # 15%换手=满分
        else:
            # 用 volume/close 近似
            vol_per_price = df["volume"] / (df["close"] + 1e-10)
            turnover_score = (vol_per_price / vol_per_price.rolling(20).mean()).clip(0, 2) - 1.0

        # 振幅评分
        if "amplitude" in df.columns:
            amplitude = pd.to_numeric(df["amplitude"], errors="coerce").fillna(0)
            amp_score = (amplitude / 10.0).clip(-1, 1)
        else:
            amp = (df["high"] - df["low"]) / (df["close"].shift(1) + 1e-10) * 100
            amp_score = (amp / 10.0).clip(-1, 1)

        # 量比评分
        vol_ma = df["volume"].rolling(window=vol_ma_period).mean()
        vol_ratio = df["volume"] / (vol_ma + 1e-10)
        vol_score = ((vol_ratio - 1.0) / 2.0).clip(-1, 1)

        # 价格方向（决定筹码异动方向）
        price_dir = (df["close"] - df["close"].shift(1)) / (df["close"].shift(1) + 1e-10) * 100
        dir_score = (price_dir / 10.0).clip(-1, 1)

        # 筹码异动分数 = 活跃度 × 方向
        activity = (turnover_score + amp_score + vol_score) / 3.0
        composite = activity * (0.4 + 0.6 * dir_score.clip(-1, 1))

        return composite.clip(-1, 1)

    def evaluate(self, value, **kwargs):
        if pd.isna(value):
            return 0.0, score_to_signal(0.0), "数据不足"

        score = max(-1.0, min(1.0, value))

        if score > 0.3:
            detail = f"筹码向上异动，活跃+做多方向，得分={value:.2f}，短线关注"
        elif score < -0.3:
            detail = f"筹码向下异动，活跃+做空方向，得分={value:.2f}，注意风险"
        elif abs(value) > 0.1:
            detail = f"筹码异动但方向不明，得分={value:.2f}，变盘信号"
        else:
            detail = f"筹码平稳，得分={value:.2f}，无异常"

        return score, score_to_signal(score, threshold=0.15), detail
