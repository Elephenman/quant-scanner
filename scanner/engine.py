"""
信号扫描引擎
核心逻辑：选因子 → 跑全市场 → 打分排序 → 输出信号
"""

from datetime import datetime
from typing import Any

import pandas as pd

from factors.base import FactorBase, FactorRegistry, SignalResult, SignalType, score_to_signal
from factors.loader import discover_factors
from data.fetcher import fetch_realtime_quotes, fetch_daily_kline, fetch_capital_flow, fetch_sector_changes
from data.cache import save_signal, init_db


class SignalScanner:
    """信号扫描器"""

    def __init__(self):
        init_db()
        self._factors_loaded = False
        self._sector_data = pd.DataFrame()

    def _ensure_factors(self):
        if not self._factors_loaded:
            discover_factors()
            self._factors_loaded = True

    def scan_market(
        self,
        selected_factors: dict[str, dict] | None = None,
        min_price: float = 3.0,
        max_price: float = 50.0,
        min_change: float = -9.0,
        max_change: float = 9.0,
        top_n: int = 50,
    ) -> list[SignalResult]:
        """
        全市场扫描
        selected_factors: {"SMA金叉死叉": {"weight": 1.0, "enabled": True, "params": {}}, ...}
        """
        self._ensure_factors()

        # 1. 获取实时行情
        print("[扫描] 获取实时行情...")
        realtime = fetch_realtime_quotes()
        if realtime.empty:
            print("[扫描] 实时行情为空，可能非交易时间")
            return []

        # 2. 过滤股票
        filtered = realtime[
            (realtime["price"] >= min_price) &
            (realtime["price"] <= max_price) &
            (realtime["change_pct"] >= min_change) &
            (realtime["change_pct"] <= max_change) &
            (realtime["stock_code"].str.match(r"^\d{6}$"))
        ].copy()
        print(f"[扫描] 过滤后 {len(filtered)} 只股票 (价格{min_price}-{max_price}, 涨跌{min_change}%-{max_change}%)")

        # 3. 获取板块数据
        self._sector_data = fetch_sector_changes()

        # 4. 确定要用的因子
        all_factors = FactorRegistry.all_factors()
        if selected_factors is None:
            # 默认全部启用
            selected_factors = {name: {"weight": f.default_weight, "enabled": True, "params": {}}
                               for name, f in all_factors.items()}

        # 5. 逐股票计算
        results: list[SignalResult] = []
        total = min(len(filtered), top_n)  # 先只扫top_n只

        for idx, (_, row) in enumerate(filtered.head(top_n).iterrows()):
            code = row["stock_code"]
            name = row["stock_name"]
            print(f"\r[扫描] {idx+1}/{total} {code} {name}", end="", flush=True)

            signal = self._scan_single(code, name, row, all_factors, selected_factors)
            if signal and signal.total_score != 0:
                results.append(signal)

        print(f"\n[扫描] 完成，产生信号 {len(results)} 只")

        # 6. 按分数排序
        results.sort(key=lambda s: s.total_score, reverse=True)

        # 7. 保存信号
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for s in results:
            save_signal({
                "scan_time": now,
                "stock_code": s.stock_code,
                "stock_name": s.stock_name,
                "signal_type": s.signal_type.value,
                "total_score": s.total_score,
                "detail": s.detail_text,
                "price": s.price,
                "change_pct": s.change_pct,
            })

        return results

    def _scan_single(
        self,
        stock_code: str,
        stock_name: str,
        realtime_row: pd.Series,
        all_factors: dict[str, FactorBase],
        selected_factors: dict[str, dict],
    ) -> SignalResult | None:
        """扫描单只股票"""
        # 获取日K线
        df = fetch_daily_kline(stock_code, period=60)
        if df.empty or len(df) < 10:
            return None

        # 标准化列名（akshare返回中文列名）
        col_map = {
            "日期": "date", "股票代码": "stock_code",
            "开盘": "open", "最高": "high", "最低": "low", "收盘": "close",
            "成交量": "volume", "成交额": "turnover", "振幅": "amplitude",
            "涨跌幅": "change_pct", "涨跌额": "change_amount", "换手率": "turnover_rate",
        }
        df = df.rename(columns=col_map)

        # 如果缺少必要列，跳过
        required = ["open", "high", "low", "close", "volume"]
        if not all(c in df.columns for c in required):
            return None

        # 补充资金流数据
        capital = fetch_capital_flow(stock_code)
        if capital:
            df["capital_net_inflow"] = capital.get("net_inflow", 0)

        # 补充板块数据
        if not self._sector_data.empty:
            df["sector_change_pct"] = 0.0  # TODO: 匹配个股所属板块

        # 逐因子计算
        factor_results = []
        total_weighted_score = 0.0
        total_weight = 0.0

        for factor_name, config in selected_factors.items():
            if not config.get("enabled", True):
                continue

            factor = all_factors.get(factor_name)
            if factor is None:
                continue

            weight = config.get("weight", factor.default_weight)
            params = config.get("params", {})

            result = factor.run(df, stock_code, stock_name, **params)
            if result is not None:
                factor_results.append(result)
                total_weighted_score += result.score * weight
                total_weight += weight

        if total_weight == 0:
            return None

        avg_score = total_weighted_score / total_weight
        signal_type = score_to_signal(avg_score, threshold=0.2)

        return SignalResult(
            stock_code=stock_code,
            stock_name=stock_name,
            total_score=round(avg_score, 4),
            signal_type=signal_type,
            factor_results=factor_results,
            price=float(realtime_row.get("price", 0)),
            change_pct=float(realtime_row.get("change_pct", 0)),
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def scan_watchlist(
        self,
        stock_codes: list[str],
        selected_factors: dict[str, dict] | None = None,
    ) -> list[SignalResult]:
        """扫描自选股列表"""
        self._ensure_factors()

        all_factors = FactorRegistry.all_factors()
        if selected_factors is None:
            selected_factors = {name: {"weight": f.default_weight, "enabled": True, "params": {}}
                               for name, f in all_factors.items()}

        # 获取实时行情用于补充价格信息
        realtime = fetch_realtime_quotes()

        results = []
        for code in stock_codes:
            rt_row = realtime[realtime["stock_code"] == code]
            row = rt_row.iloc[0] if not rt_row.empty else pd.Series({"price": 0, "change_pct": 0})
            name = str(row.get("stock_name", code))

            signal = self._scan_single(code, name, row, all_factors, selected_factors)
            if signal:
                results.append(signal)

        results.sort(key=lambda s: s.total_score, reverse=True)
        return results
