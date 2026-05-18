"""
数据获取层 - akshare 数据拉取
全A股行情、资金流向、板块数据
"""

import os
import time
from datetime import datetime

import akshare as ak
import pandas as pd

from data.cache import save_daily_kline, load_daily_kline, get_last_trade_date, get_connection, init_db

# ========== 代理处理 ==========
# akshare请求东方财富API需直连，Clash代理会拦截
# 在模块加载时就清除代理，因为akshare内部requests会读取环境变量
_ORIG_PROXY = {}

# 启动时自动清除代理
for _key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    _val = os.environ.get(_key)
    if _val:
        _ORIG_PROXY[_key] = _val
        del os.environ[_key]


def _disable_proxy():
    """确保代理已禁用"""
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        val = os.environ.get(key)
        if val:
            _ORIG_PROXY[key] = val
            os.environ.pop(key, None)
    """临时禁用代理（akshare需要直连东方财富）"""
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        val = os.environ.get(key)
        if val:
            _ORIG_PROXY[key] = val
            os.environ.pop(key, None)


def _restore_proxy():
    """恢复代理"""
    for key, val in _ORIG_PROXY.items():
        os.environ[key] = val
    _ORIG_PROXY.clear()


def fetch_realtime_quotes() -> pd.DataFrame:
    """获取A股全市场实时行情"""
    try:
        _disable_proxy()
        df = ak.stock_zh_a_spot_em()
        _restore_proxy()
        if df is None or df.empty:
            return pd.DataFrame()
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
            "60日涨跌幅": "change_pct_60d",
            "年初至今涨跌幅": "change_pct_ytd",
        }
        # 只重命名存在的列
        existing = {k: v for k, v in rename_map.items() if k in df.columns}
        df = df.rename(columns=existing)

        # 确保stock_code是字符串
        if "stock_code" in df.columns:
            df["stock_code"] = df["stock_code"].astype(str)

        return df
    except Exception as e:
        _restore_proxy()
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
        _disable_proxy()
        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=(datetime.now() - pd.Timedelta(days=period * 2)).strftime("%Y%m%d"),
            end_date=datetime.now().strftime("%Y%m%d"),
            adjust="qfq"
        )
        _restore_proxy()
        if not df.empty:
            save_daily_kline(stock_code, df)
        return df.tail(period) if not df.empty else df
    except Exception as e:
        _restore_proxy()
        print(f"[ERROR] 获取 {stock_code} 日K线失败: {e}")
        if use_cache:
            return load_daily_kline(stock_code, days=period)
        return pd.DataFrame()


def fetch_capital_flow(stock_code: str) -> dict:
    """获取个股资金流向"""
    try:
        _disable_proxy()
        market = "sh" if stock_code.startswith("6") else "sz"
        df = ak.stock_individual_fund_flow(stock=stock_code, market=market)
        _restore_proxy()
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            return {
                "net_inflow": float(latest.get("主力净流入-净额", latest.get("主力净流入", 0))),
                "net_inflow_large": float(latest.get("超大单净流入-净额", latest.get("超大单净流入", 0))),
                "net_inflow_medium": float(latest.get("大单净流入-净额", latest.get("大单净流入", 0))),
            }
    except Exception as e:
        _restore_proxy()
        print(f"[WARN] 获取 {stock_code} 资金流向失败: {e}")
    return {}


def fetch_sector_changes() -> pd.DataFrame:
    """获取板块涨跌幅"""
    try:
        _disable_proxy()
        df = ak.stock_board_industry_name_em()
        _restore_proxy()
        if df is not None and not df.empty:
            rename_map = {
                "板块名称": "sector_name",
                "涨跌幅": "change_pct",
                "总市值": "total_market_cap",
                "换手率": "turnover_rate",
                "上涨家数": "up_count",
                "下跌家数": "down_count",
            }
            existing = {k: v for k, v in rename_map.items() if k in df.columns}
            df = df.rename(columns=existing)
            return df
    except Exception as e:
        _restore_proxy()
        print(f"[WARN] 获取板块数据失败: {e}")
    return pd.DataFrame()


def fetch_stock_sector_map() -> pd.DataFrame:
    """获取个股-板块映射关系"""
    try:
        _disable_proxy()
        # 获取东方财富行业板块成分股
        boards = ak.stock_board_industry_name_em()
        if boards is None or boards.empty:
            return pd.DataFrame()

        mapping = []
        board_col = "板块名称" if "板块名称" in boards.columns else None
        if board_col is None:
            return pd.DataFrame()

        # 只取前20个板块（避免请求太多）
        for _, board_row in boards.head(20).iterrows():
            board_name = board_row[board_col]
            try:
                members = ak.stock_board_industry_cons_em(symbol=board_name)
                if members is not None and not members.empty:
                    code_col = "代码" if "代码" in members.columns else None
                    if code_col:
                        for _, m in members.iterrows():
                            mapping.append({
                                "stock_code": str(m[code_col]),
                                "sector_name": board_name,
                            })
                time.sleep(0.2)
            except Exception:
                continue

        _restore_proxy()
        return pd.DataFrame(mapping)
    except Exception as e:
        _restore_proxy()
        print(f"[WARN] 获取板块映射失败: {e}")
        return pd.DataFrame()


def fetch_stock_list() -> pd.DataFrame:
    """获取A股股票列表"""
    try:
        _disable_proxy()
        df = ak.stock_zh_a_spot_em()
        _restore_proxy()
        if df is not None and not df.empty:
            code_col = "代码" if "代码" in df.columns else "stock_code"
            name_col = "名称" if "名称" in df.columns else "stock_name"
            result = df[[code_col, name_col]].rename(columns={code_col: "stock_code", name_col: "stock_name"})
            return result
    except Exception as e:
        _restore_proxy()
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
