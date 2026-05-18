# QuantScanner - A股超短线信号扫描器

> 因子自由组合 → 信号实时扫描 → 手动下单

## 核心理念

- **信号扫描器**，不是自动交易平台
- 超短线因子驱动：主力资金、集合竞价、放量突破、板块联动
- 因子插件化：随时新增/调整因子，无需改主程序

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/Elephenman/quant-scanner.git
cd quant-scanner

# 2. 创建虚拟环境并安装依赖
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt

# 3. 启动
streamlit run ui/app.py --server.headless true
```

## 项目结构

```
quant-scanner/
├── factors/              # 因子插件目录（新增因子放这里）
│   ├── base.py           # FactorBase 抽象基类 + FactorRegistry
│   ├── loader.py         # 自动发现并注册因子
│   ├── sma_cross.py      # SMA金叉死叉
│   ├── macd.py           # MACD金叉死叉
│   ├── rsi.py            # RSI超买超卖
│   ├── volume_break.py   # 放量突破
│   ├── change_amplitude.py # 涨跌幅振幅
│   ├── capital_flow.py   # 主力资金流入流出
│   ├── auction.py        # 集合竞价异动
│   └── sector.py         # 板块预期涨幅
├── data/                 # 数据层
│   ├── fetcher.py        # akshare 数据获取
│   └── cache.py          # SQLite 本地缓存
├── scanner/              # 扫描引擎
│   ├── engine.py         # 信号扫描 + 评分
│   └── scheduler.py      # APScheduler 定时扫描
├── ui/                   # Streamlit 界面
│   └── app.py            # 主页面
├── main.py               # CLI 入口
└── requirements.txt
```

## 因子列表（12个，含4个组合策略）

### 组合策略因子 🔥（多维度交叉验证，比单一指标更可靠）

| 因子 | 分类 | 默认权重 | 说明 |
|------|------|---------|------|
| **资金攻击组合** | 资金面 | **2.0** | 主力流入×竞价异动×板块联动 三维交叉 |
| **动量突破组合** | 量价面 | **1.5** | 量比×涨幅×RSI 三重共振 |
| **趋势确认组合** | 技术面 | **1.2** | MACD+SMA+价格位置 三重趋势验证 |
| **筹码异动组合** | 量价面 | **1.3** | 换手率×振幅×量比 三维交叉 |

### 单一指标因子

| 因子 | 分类 | 默认权重 | 说明 |
|------|------|---------|------|
| 主力资金流入流出 | 资金面 | 1.5 | 大单净流入/流出 |
| 集合竞价异动 | 竞价面 | 1.3 | 高开/低开幅度 |
| SMA金叉死叉 | 技术面 | 1.0 | 短期均线上穿/下穿长期均线 |
| MACD金叉死叉 | 技术面 | 1.0 | DIF上穿/下穿DEA |
| 放量突破 | 量价面 | 1.2 | 成交量放大+价格突破 |
| 板块预期涨幅 | 板块面 | 1.0 | 所属板块当日涨跌 |
| RSI超买超卖 | 技术面 | 0.8 | RSI<30超卖看反弹，>70超买看回调 |
| 涨跌幅振幅 | 量价面 | 0.8 | 大阳线/大阴线判断 |

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

## 信号评分机制

1. 每个因子计算原始值 → 映射为 [-1.0, 1.0] 评分
2. 加权汇总：`total_score = Σ(weight_i × score_i) / Σ(weight_i)`
3. 映射为信号：
   - `score ≥ 0.6` → 🟢 强买
   - `0.3 ≤ score < 0.6` → 🟡 买
   - `-0.3 < score < 0.3` → ⚪ 观察
   - `-0.6 < score ≤ -0.3` → 🟠 卖
   - `score ≤ -0.6` → 🔴 强卖

## 资金约束适配

- 1万本金 → 单仓位 ≤50%，止损5%
- 聚焦 10-30 元股价区间
- T+1 限制下做超短线（今买明卖）

## 技术栈

- Python 3.12 + Streamlit
- akshare（A股免费数据源）
- SQLite（本地缓存）
- APScheduler（定时扫描）
- Plotly（图表可视化）

## 免责声明

本工具仅供学习研究，不构成任何投资建议。投资有风险，决策需谨慎。
