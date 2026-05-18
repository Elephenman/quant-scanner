"""
QuantScanner - A股量化信号扫描器
因子插件系统核心模块
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd


class SignalType(Enum):
    STRONG_BUY = "强买"
    BUY = "买"
    WATCH = "观察"
    SELL = "卖"
    STRONG_SELL = "强卖"


class FactorCategory(Enum):
    TECHNICAL = "技术面"
    VOLUME_PRICE = "量价面"
    CAPITAL_FLOW = "资金面"
    FUNDAMENTAL = "基本面"
    SENTIMENT = "情绪面"
    AUCTION = "竞价面"
    SECTOR = "板块面"


@dataclass
class FactorResult:
    """单个因子的计算结果"""
    factor_name: str
    stock_code: str
    stock_name: str
    value: Any               # 因子原始值
    score: float             # -1.0 ~ 1.0, 负=看空, 正=看多
    signal: SignalType       # 信号类型
    detail: str = ""         # 人类可读的解释


@dataclass
class SignalResult:
    """一只股票的综合信号"""
    stock_code: str
    stock_name: str
    total_score: float       # 加权总分
    signal_type: SignalType  # 综合信号
    factor_results: list[FactorResult] = field(default_factory=list)
    price: float = 0.0
    change_pct: float = 0.0
    timestamp: str = ""

    @property
    def detail_text(self) -> str:
        parts = [f"{r.factor_name}:{r.signal.value}" for r in self.factor_results if abs(r.score) > 0.1]
        return " | ".join(parts)


class FactorBase(ABC):
    """因子基类 - 所有因子必须继承此类"""

    # 子类必须设置的类属性
    name: str = ""                    # 因子名称
    category: FactorCategory = None   # 因子分类
    description: str = ""             # 因子描述
    default_weight: float = 1.0       # 默认权重
    default_threshold: float = 0.3    # 默认阈值（绝对值超过此才触发信号）
    params: dict = None               # 可调参数定义 {name: {default, min, max, step, label}}

    def __init__(self):
        if self.params is None:
            self.params = {}

    @abstractmethod
    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        """
        计算因子值
        df: 包含历史行情的DataFrame (至少有 open/high/low/close/volume 列)
        返回: 与df等长的Series，最后一个是最新值
        """
        pass

    @abstractmethod
    def evaluate(self, value: Any, **kwargs) -> tuple[float, SignalType, str]:
        """
        评估因子值，返回 (score, signal, detail)
        score: -1.0 ~ 1.0
        signal: 信号类型
        detail: 解释文字
        """
        pass

    def run(self, df: pd.DataFrame, stock_code: str, stock_name: str, **kwargs) -> FactorResult | None:
        """执行因子计算 + 评估，返回FactorResult"""
        try:
            series = self.calculate(df, **kwargs)
            if series is None or len(series) == 0:
                return None
            latest_value = series.iloc[-1]
            score, signal, detail = self.evaluate(latest_value, **kwargs)
            return FactorResult(
                factor_name=self.name,
                stock_code=stock_code,
                stock_name=stock_name,
                value=latest_value,
                score=score,
                signal=signal,
                detail=detail,
            )
        except Exception as e:
            return FactorResult(
                factor_name=self.name,
                stock_code=stock_code,
                stock_name=stock_name,
                value=None,
                score=0.0,
                signal=SignalType.WATCH,
                detail=f"计算异常: {str(e)}",
            )

    def get_param_config(self) -> dict:
        """返回参数配置（给UI用）"""
        return self.params.copy() if self.params else {}


class FactorRegistry:
    """因子注册器 - 自动发现和管理所有因子"""

    _factors: dict[str, FactorBase] = {}

    @classmethod
    def register(cls, factor: FactorBase):
        """注册一个因子实例"""
        cls._factors[factor.name] = factor

    @classmethod
    def get(cls, name: str) -> FactorBase | None:
        return cls._factors.get(name)

    @classmethod
    def all_factors(cls) -> dict[str, FactorBase]:
        return cls._factors.copy()

    @classmethod
    def by_category(cls) -> dict[FactorCategory, list[FactorBase]]:
        result = {}
        for f in cls._factors.values():
            result.setdefault(f.category, []).append(f)
        return result

    @classmethod
    def list_names(cls) -> list[str]:
        return list(cls._factors.keys())


def score_to_signal(score: float, threshold: float = 0.3) -> SignalType:
    """分数转信号类型"""
    if score >= 0.7:
        return SignalType.STRONG_BUY
    elif score >= threshold:
        return SignalType.BUY
    elif score > -threshold:
        return SignalType.WATCH
    elif score > -0.7:
        return SignalType.SELL
    else:
        return SignalType.STRONG_SELL
