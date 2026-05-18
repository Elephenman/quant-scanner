"""
信号扫描引擎
核心逻辑：选因子 → 跑全市场 → 打分排序 → 输出信号
支持实时行情扫描 + 历史K线回退扫描
v0.3.0: 修复progress_callback兼容性 + 评分归一化改进
"""

from datetime import datetime
from typing import Any, Callable

import pandas as pd

from factors.base import FactorBase, FactorRegistry, SignalResult, SignalType, score_to_signal
from factors.loader import discover_factors
from data.fetcher import (
    fetch_realtime_quotes, fetch_daily_kline, fetch_capital_flow,
    fetch_sector_changes, fetch_stock_sector_map
)
from data.cache import save_signal, init_db


class SignalScanner:
    """信号扫描器"""

    def __init__(self):
        init_db()
        self._factors_loaded = False
        self._sector_data = pd.DataFrame()
        self._sector_map = pd.DataFrame()  # 个股-板块映射

    def _ensure_factors(self):
        if not self._factors_loaded:
            discover_factors()
            self._factors_loaded = True

    def _get_sector_for_stock(self, stock_code: str) -> float:
        """获取个股所属板块涨跌幅"""
        if self._sector_map.empty or self._sector_data.empty:
            return 0.0

        # 查找该股票所属板块
        match = self._sector_map[self._sector_map["stock_code"] == stock_code]
        if match.empty:
            return 0.0

        sector_name = match.iloc[0]["sector_name"]
        sector_match = self._sector_data[self._sector_data["sector_name"] == sector_name]
        if sector_match.empty:
            return 0.0

        return float(sector_match.iloc[0].get("change_pct", 0.0))

    def scan_market(
        self,
        selected_factors: dict[str, dict] | None = None,
        min_price: float = 3.0,
        max_price: float = 50.0,
        min_change: float = -9.0,
        max_change: float = 9.0,
        top_n: int = 50,
        progress_callback: Callable | None = None,
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
            print("[扫描] 实时行情为空，尝试从缓存构建扫描列表...")
            realtime = self._build_fallback_list()

        if realtime.empty:
            print("[扫描] 无可用数据，扫描终止")
            return []

        # 2. 过滤股票
        filtered = realtime.copy()

        # 确保 price 和 change_pct 列存在且为数值
        if "price" in filtered.columns:
            filtered["price"] = pd.to_numeric(filtered["price"], errors="coerce")
            filtered = filtered[
                (filtered["price"] >= min_price) &
                (filtered["price"] <= max_price)
            ]

        if "change_pct" in filtered.columns:
            filtered["change_pct"] = pd.to_numeric(filtered["change_pct"], errors="coerce")
            filtered = filtered[
                (filtered["change_pct"] >= min_change) &
                (filtered["change_pct"] <= max_change)
            ]

        # 过滤非正常股票代码
        if "stock_code" in filtered.columns:
            filtered = filtered[filtered["stock_code"].str.match(r"^\d{6}$", na=False)]

        print(f"[扫描] 过滤后 {len(filtered)} 只股票 (价格{min_price}-{max_price}, 涨跌{min_change}%-{max_change}%)")

        if filtered.empty:
            return []

        # 3. 获取板块数据
        self._sector_data = fetch_sector_changes()
        if not self._sector_data.empty:
            self._sector_map = fetch_stock_sector_map()

        # 4. 确定要用的因子
        all_factors = FactorRegistry.all_factors()
        if selected_factors is None:
            selected_factors = {name: {"weight": f.default_weight, "enabled": True, "params": {}}
                               for name, f in all_factors.items()}

        # 过滤掉禁用的因子
        active_factors = {k: v for k, v in selected_factors.items() if v.get("enabled", True)}
        if not active_factors:
            print("[扫描] 没有启用的因子")
            return []

        # 5. 逐股票计算
        results: list[SignalResult] = []

        # 按成交额/换手率排序，优先扫活跃股
        sort_col = None
        for col_candidate in ["turnover", "turnover_rate", "volume"]:
            if col_candidate in filtered.columns:
                sort_col = col_candidate
                break
        if sort_col:
            filtered[sort_col] = pd.to_numeric(filtered[sort_col], errors="coerce").fillna(0)
            filtered = filtered.sort_values(sort_col, ascending=False)

        scan_list = filtered.head(top_n)
        total = len(scan_list)

        for idx, (_, row) in enumerate(scan_list.iterrows()):
            code = str(row.get("stock_code", ""))
            name = str(row.get("stock_name", code))
            print(f"\r[扫描] {idx+1}/{total} {code} {name}        ", end="", flush=True)

            if progress_callback:
                progress_callback(idx + 1, total, f"{code} {name}")

            signal = self._scan_single(code, name, row, all_factors, active_factors)
            if signal is not None:
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

    def _build_fallback_list(self) -> pd.DataFrame:
        """实时行情获取失败时，从缓存构建扫描列表"""
        from data.cache import get_connection
        try:
            conn = get_connection()
            # 取最近有数据的股票
            df = pd.read_sql_query("""
                SELECT stock_code, MAX(trade_date) as last_date,
                       AVG(close) as price,
                       COALESCE(AVG(change_pct), 0) as change_pct
                FROM daily_kline
                WHERE trade_date >= date('now', '-7 days')
                GROUP BY stock_code
                LIMIT 200
            """, conn)
            conn.close()
            if not df.empty:
                df["stock_name"] = df["stock_code"]
                df["price"] = pd.to_numeric(df["price"], errors="coerce")
                df["change_pct"] = pd.to_numeric(df["change_pct"], errors="coerce")
                print(f"[扫描] 从缓存构建 {len(df)} 只股票")
            return df
        except Exception as e:
            print(f"[扫描] 缓存回退也失败: {e}")
            return pd.DataFrame()

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
        if df.empty or len(df) < 5:
            return None

        # 标准化列名（akshare返回中文列名）
        col_map = {
            "日期": "date", "股票代码": "stock_code",
            "开盘": "open", "最高": "high", "最低": "low", "收盘": "close",
            "成交量": "volume", "成交额": "turnover", "振幅": "amplitude",
            "涨跌幅": "change_pct", "涨跌额": "change_amount", "换手率": "turnover_rate",
        }
        existing_map = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=existing_map)

        # 如果缺少必要列，跳过
        required = ["open", "high", "low", "close", "volume"]
        if not all(c in df.columns for c in required):
            return None

        # 确保数值类型
        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=required)

        if len(df) < 5:
            return None

        # 补充资金流数据
        capital = fetch_capital_flow(stock_code)
        if capital:
            df["capital_net_inflow"] = capital.get("net_inflow", 0)
        else:
            df["capital_net_inflow"] = 0.0

        # 补充板块数据
        sector_change = self._get_sector_for_stock(stock_code)
        df["sector_change_pct"] = sector_change

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

            # 传入最新收盘价供因子归一化使用
            params_with_price = dict(params)
            params_with_price["close_price"] = float(df["close"].iloc[-1]) if not df.empty else 0

            result = factor.run(df, stock_code, stock_name, **params_with_price)
            if result is not None:
                factor_results.append(result)
                total_weighted_score += result.score * weight
                total_weight += weight

        if total_weight == 0 or not factor_results:
            return None

        avg_score = total_weighted_score / total_weight

        # 不再过滤 score==0 的信号，让用户看到完整信息
        signal_type = score_to_signal(avg_score, threshold=0.2)

        # 从 realtime_row 取价格，如果没有就用K线最后收盘价
        price = 0.0
        change_pct = 0.0
        if "price" in realtime_row.index:
            try:
                price = float(realtime_row.get("price", 0))
            except (ValueError, TypeError):
                price = float(df["close"].iloc[-1]) if not df.empty else 0.0
        if "change_pct" in realtime_row.index:
            try:
                change_pct = float(realtime_row.get("change_pct", 0))
            except (ValueError, TypeError):
                change_pct = 0.0

        if price == 0 and not df.empty:
            price = float(df["close"].iloc[-1])

        return SignalResult(
            stock_code=stock_code,
            stock_name=stock_name,
            total_score=round(avg_score, 4),
            signal_type=signal_type,
            factor_results=factor_results,
            price=price,
            change_pct=change_pct,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def scan_watchlist(
        self,
        stock_codes: list[str],
        selected_factors: dict[str, dict] | None = None,
        progress_callback: Callable | None = None,
    ) -> list[SignalResult]:
        """扫描自选股列表"""
        self._ensure_factors()

        all_factors = FactorRegistry.all_factors()
        if selected_factors is None:
            selected_factors = {name: {"weight": f.default_weight, "enabled": True, "params": {}}
                               for name, f in all_factors.items()}

        # 获取板块数据
        self._sector_data = fetch_sector_changes()
        if not self._sector_data.empty:
            self._sector_map = fetch_stock_sector_map()

        # 获取实时行情用于补充价格信息
        realtime = fetch_realtime_quotes()

        results = []
        for idx, code in enumerate(stock_codes):
            code = str(code).strip()
            if not code:
                continue

            if progress_callback:
                progress_callback(idx + 1, len(stock_codes), code)

            # 在实时行情中找该股票
            rt_row = pd.Series({"price": 0, "change_pct": 0})
            stock_name = code

            if not realtime.empty and "stock_code" in realtime.columns:
                rt_match = realtime[realtime["stock_code"] == code]
                if not rt_match.empty:
                    rt_row = rt_match.iloc[0]
                    stock_name = str(rt_row.get("stock_name", code))

            signal = self._scan_single(code, stock_name, rt_row, all_factors, selected_factors)
            if signal:
                results.append(signal)

        results.sort(key=lambda s: s.total_score, reverse=True)
        return results
