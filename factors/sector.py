"""
板块预期涨幅因子
超短线：所在板块当日涨幅，板块联动效应
"""

import pandas as pd
from factors.base import FactorBase, FactorCategory, score_to_signal


class SectorFactor(FactorBase):
    name = "板块预期涨幅"
    category = FactorCategory.SECTOR
    description = "所在板块当日涨幅：板块涨=个股有板块支撑，板块跌=个股承压"
    default_weight = 1.0
    default_threshold = 0.2
    params = {
        "sector_up_pct": {"default": 2.0, "min": 0.5, "max": 5.0, "step": 0.5, "label": "板块强势阈值(%)"},
        "sector_down_pct": {"default": -2.0, "min": -5.0, "max": -0.5, "step": 0.5, "label": "板块弱势阈值(%)"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        """
        外部传入 sector_change_pct 列
        """
        if "sector_change_pct" in df.columns:
            return df["sector_change_pct"]
        return pd.Series([0.0] * len(df), index=df.index)

    def evaluate(self, value, **kwargs):
        up_threshold = kwargs.get("sector_up_pct", 2.0)
        down_threshold = kwargs.get("sector_down_pct", -2.0)

        if pd.isna(value) or value == 0:
            return 0.0, score_to_signal(0.0), "无板块数据"

        if value >= up_threshold:
            score = min(1.0, value / 5.0)
            detail = f"板块涨{value:.2f}%，板块强势支撑"
        elif value <= down_threshold:
            score = max(-1.0, value / 5.0)
            detail = f"板块跌{abs(value):.2f}%，板块弱势拖累"
        else:
            score = value / 10.0 * 0.3
            detail = f"板块涨跌{value:.2f}%，中性"

        return score, score_to_signal(score, threshold=0.15), detail
