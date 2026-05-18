"""
数据获取层 - akshare 数据拉取
全A股行情、资金流向、板块数据
"""

import time
from datetime import datetime

import akshare as ak
import pandas as pd

from data.cache import save_daily_kline, load_daily_kline, get_last_trade_date, get_connection, init_db


def fetch_realtime_quotes() -> pd.DataFrame:
    """获取A股全市场实时行情"""
    try:
        df = ak.stock_zh_a_spot_em()
        # 标准化列名
        rename_map = {
            "代码": "stock_code",
            "名称": "stock_name",
            "最新价": "price",
            "涨跌幅": "change_pct",
            "涨跌额": "change_amount",
            "成交量": "volume",
            "成交额": "turnover",
            "振幅": "amplitude",
            "最高": "high",
            "最低": "low",
            "今开": "open",
            "昨收": "prev_close",
            "量比": "vol_ratio",
            "换手率": "turnover_rate",
            "市盈率-动态": "pe_ttm",
            "市净率": "pb",
        }
        df = df.rename(columns=rename_map)
        return df
    except Exception as e:
        print(f"[ERROR] 获取实时行情失败: {e}")
        return pd.DataFrame()


def fetch_daily_kline(stock_code: str, period: int = 120, use_cache: bool = True) -> pd.DataFrame:
    """
    获取个股日K线
    优先从本地缓存加载，缺失部分从akshare补
    """
    if use_cache:
        cached = load_daily_kline(stock_code, days=period + 30)
        last_date = get_last_trade_date(stock_code)
        today = datetime.now().strftime("%Y%m%d")
        if not cached.empty and last_date == today:
            return cached.tail(period)

    try:
        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=(datetime.now() - pd.Timedelta(days=period * 2)).strftime("%Y%m%d"),
            end_date=datetime.now().strftime("%Y%m%d"),
            adjust="qfq"
        )
        if not df.empty:
            save_daily_kline(stock_code, df)
        return df.tail(period) if not df.empty else df
    except Exception as e:
        print(f"[ERROR] 获取 {stock_code} 日K线失败: {e}")
        if use_cache:
            return load_daily_kline(stock_code, days=period)
        return pd.DataFrame()


def fetch_capital_flow(stock_code: str) -> dict:
    """获取个股资金流向"""
    try:
        df = ak.stock_individual_fund_flow(stock=stock_code, market="sh" if stock_code.startswith("6") else "sz")
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            return {
                "net_inflow": float(latest.get("主力净流入-净额", latest.get("主力净流入", 0))),
                "net_inflow_large": float(latest.get("超大单净流入-净额", latest.get("超大单净流入", 0))),
                "net_inflow_medium": float(latest.get("大单净流入-净额", latest.get("大单净流入", 0))),
            }
    except Exception as e:
        print(f"[WARN] 获取 {stock_code} 资金流向失败: {e}")
    return {}


def fetch_sector_changes() -> pd.DataFrame:
    """获取板块涨跌幅"""
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            rename_map = {
                "板块名称": "sector_name",
                "涨跌幅": "change_pct",
                "总市值": "total_market_cap",
                "换手率": "turnover_rate",
                "上涨家数": "up_count",
                "下跌家数": "down_count",
            }
            df = df.rename(columns=rename_map)
            return df
    except Exception as e:
        print(f"[WARN] 获取板块数据失败: {e}")
    return pd.DataFrame()


def fetch_stock_list() -> pd.DataFrame:
    """获取A股股票列表"""
    try:
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            result = df[["代码", "名称"]].rename(columns={"代码": "stock_code", "名称": "stock_name"})
            return result
    except Exception as e:
        print(f"[ERROR] 获取股票列表失败: {e}")
    return pd.DataFrame()


def batch_fetch_daily_kline(stock_codes: list[str], period: int = 60, delay: float = 0.3) -> dict[str, pd.DataFrame]:
    """
    批量获取日K线
    delay: 请求间隔（秒），避免被ban
    """
    results = {}
    total = len(stock_codes)
    for i, code in enumerate(stock_codes):
        print(f"\r[数据] 拉取中 {i+1}/{total} {code}", end="", flush=True)
        df = fetch_daily_kline(code, period=period)
        if not df.empty:
            results[code] = df
        time.sleep(delay)
    print(f"\n[数据] 完成，成功 {len(results)}/{total}")
    return results


if __name__ == "__main__":
    init_db()
    print("=== 测试数据获取 ===")

    # 测试实时行情
    print("\n1. 实时行情（前5只）:")
    rt = fetch_realtime_quotes()
    if not rt.empty:
        print(rt[["stock_code", "stock_name", "price", "change_pct"]].head())

    # 测试日K线
    print("\n2. 茅台日K线:")
    kline = fetch_daily_kline("600519", period=10)
    if not kline.empty:
        print(kline.tail(3))

    # 测试板块
    print("\n3. 板块涨跌（前5）:")
    sectors = fetch_sector_changes()
    if not sectors.empty:
        print(sectors.head())
