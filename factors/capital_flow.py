"""
主力资金流入流出因子
超短线最重要的因子之一：大单净流入=看多，大单净流出=看空
"""

import pandas as pd
from factors.base import FactorBase, FactorCategory, score_to_signal


class CapitalFlowFactor(FactorBase):
    name = "主力资金流入流出"
    category = FactorCategory.CAPITAL_FLOW
    description = "大单净流入看多，大单净流出看空。超短线核心因子"
    default_weight = 1.5  # 你说的最重要的因子，权重最高
    default_threshold = 0.2
    params = {
        "flow_threshold": {"default": 5000, "min": 1000, "max": 50000, "step": 1000, "label": "最小关注金额(万)"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        """
        这个因子依赖akshare的资金流向数据，不在日K df中计算
        外部调用时会传入 capital_net_inflow 列
        """
        if "capital_net_inflow" in df.columns:
            return df["capital_net_inflow"]
        # 如果没有资金流数据，返回空
        return pd.Series([0.0] * len(df), index=df.index)

    def evaluate(self, value, **kwargs):
        threshold = kwargs.get("flow_threshold", 5000)

        # value单位是元，转换为万元
        value_wan = value / 10000.0

        if pd.isna(value) or value == 0:
            return 0.0, score_to_signal(0.0), "无资金流数据"

        # 用softsign归一化，以threshold为半饱和点
        # 当value_wan=threshold时score≈0.5，value_wan=5*threshold时score≈0.83
        score = value_wan / (threshold + abs(value_wan))
        score = max(-1.0, min(1.0, score))

        if value_wan > threshold:
            detail = f"主力净流入{value_wan:.0f}万，看多"
        elif value_wan < -threshold:
            detail = f"主力净流出{abs(value_wan):.0f}万，看空"
        else:
            detail = f"主力净流入{value_wan:.0f}万，中性"

        return score, score_to_signal(score, threshold=0.15), detail
