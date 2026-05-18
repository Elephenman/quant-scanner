"""
资金攻击组合因子
超短线最核心组合：主力流入 × 竞价异动 × 板块联动 三维交叉
主力资金进场 + 竞价高开确认 + 板块共振 = 最强短线信号
"""

import pandas as pd
from factors.base import FactorBase, FactorCategory, score_to_signal


class CapitalAttackFactor(FactorBase):
    name = "资金攻击组合"
    category = FactorCategory.CAPITAL_FLOW
    description = "主力流入×竞价异动×板块联动 三维交叉：资金进场+竞价确认+板块共振=最强短线信号"
    default_weight = 2.0  # 超短线最核心
    default_threshold = 0.15
    params = {
        "capital_threshold": {"default": 5000, "min": 1000, "max": 50000, "step": 1000, "label": "主力净流入阈值(万)"},
        "auction_high_pct": {"default": 1.5, "min": 0.5, "max": 5.0, "step": 0.5, "label": "竞价高开阈值(%)"},
        "sector_up_pct": {"default": 1.0, "min": 0.5, "max": 5.0, "step": 0.5, "label": "板块涨幅阈值(%)"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        """计算三维交叉分数"""
        capital_threshold = kwargs.get("capital_threshold", 5000)

        # 维度1：主力资金（单位是元，转为万元再归一化）
        if "capital_net_inflow" in df.columns:
            capital_wan = df["capital_net_inflow"] / 10000.0
            capital_score = (capital_wan / (capital_threshold * 5)).clip(-1, 1)
        else:
            capital_score = pd.Series(0.0, index=df.index)

        # 维度2：竞价异动 = (开盘-昨收)/昨收
        prev_close = df["close"].shift(1)
        open_change = (df["open"] - prev_close) / (prev_close + 1e-10) * 100
        auction_score = (open_change / 5.0).clip(-1, 1)

        # 维度3：板块联动
        if "sector_change_pct" in df.columns:
            sector_score = (df["sector_change_pct"] / 5.0).clip(-1, 1)
        else:
            sector_score = pd.Series(0.0, index=df.index)

        # 三维交叉：同向信号放大，反向信号抵消
        # 乘法逻辑：三者同正则大正，同负则大负，有矛盾则接近0
        sign_product = (
            capital_score.clip(-1, 1) *
            auction_score.clip(-1, 1) *
            (sector_score.clip(-1, 1) + 0.3)  # 板块分加0.3偏移，避免板块中性时乘为0
        )

        # 加权平均作为基础分
        weighted_avg = capital_score * 0.5 + auction_score * 0.3 + sector_score * 0.2

        # 取加权平均和交叉乘积的混合
        composite = weighted_avg * 0.6 + sign_product * 0.4

        return composite

    def evaluate(self, value, **kwargs):
        capital_threshold = kwargs.get("capital_threshold", 500)
        auction_high = kwargs.get("auction_high_pct", 1.5)
        sector_up = kwargs.get("sector_up_pct", 1.0)

        if pd.isna(value):
            return 0.0, score_to_signal(0.0), "数据不足"

        score = max(-1.0, min(1.0, value))

        if score > 0.3:
            detail = f"资金攻击信号强，三维共振得分={value:.2f}，主力+竞价+板块同向看多"
        elif score > 0.1:
            detail = f"资金攻击偏多，得分={value:.2f}，部分维度支持"
        elif score < -0.3:
            detail = f"资金出逃信号，得分={value:.2f}，主力流出+低开+板块弱势"
        else:
            detail = f"资金攻击中性，得分={value:.2f}，多空分歧"

        return score, score_to_signal(score, threshold=0.15), detail
