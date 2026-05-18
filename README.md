# QuantScanner - A股超短线信号扫描器

> 因子自由组合 → 信号实时扫描 → 手动下单

## 核心理念

- **信号扫描器**，不是自动交易平台
- 超短线因子驱动：主力资金、集合竞价、放量突破、板块联动
- 因子插件化：随时新增/调整因子，无需改主程序

## 快速开始

```bash
# 1. 激活虚拟环境
cd A:/Dev/github/quant-scanner
venv\Scripts\activate

# 2. 启动
streamlit run ui/app.py
```

## 因子列表（持续扩展中）

| 因子 | 分类 | 说明 |
|------|------|------|
| SMA金叉死叉 | 技术面 | 短期均线上穿/下穿长期均线 |
| MACD金叉死叉 | 技术面 | DIF上穿/下穿DEA |
| RSI超买超卖 | 技术面 | RSI<30超卖看反弹，>70超买看回调 |
| 放量突破 | 量价面 | 成交量放大+价格突破 |
| 涨跌幅振幅 | 量价面 | 大阳线/大阴线判断 |
| 主力资金流入流出 | 资金面 | 大单净流入/流出 |
| 集合竞价异动 | 竞价面 | 高开/低开幅度 |
| 板块预期涨幅 | 板块面 | 所属板块当日涨跌 |

## 新增因子

在 `factors/` 目录下新建 .py 文件：

```python
from factors.base import FactorBase, FactorCategory, score_to_signal
import pandas as pd

class MyFactor(FactorBase):
    name = "我的因子"
    category = FactorCategory.TECHNICAL
    description = "因子描述"
    default_weight = 1.0
    default_threshold = 0.3
    params = {
        "period": {"default": 10, "min": 2, "max": 60, "step": 1, "label": "周期"},
    }

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.Series:
        # 计算因子值
        return df["close"].rolling(window=kwargs.get("period", 10)).mean()

    def evaluate(self, value, **kwargs):
        # 返回 (score, signal, detail)
        score = 0.5  # -1.0 ~ 1.0
        return score, score_to_signal(score), "看多信号"
```

重启 Streamlit 即可自动加载。

## 技术栈

- Python 3.12 + Streamlit
- akshare（A股数据源）
- SQLite（本地缓存）
- APScheduler（定时扫描，v0.2）
- Plotly（图表，v0.2）

## 免责声明

本工具仅供学习研究，不构成任何投资建议。投资有风险，决策需谨慎。
