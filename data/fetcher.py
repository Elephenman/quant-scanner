"""
数据获取层 - 双数据源自动降级
主源：东方财富（akshare）  备源：腾讯财经（HTTP直连）
Clash TUN模式会拦截东方财富，自动降级到腾讯接口
"""

import json
import os
import time
from datetime import datetime

import pandas as pd
import requests

from data.cache import save_daily_kline, load_daily_kline, get_last_trade_date, get_connection, init_db

# ========== 代理处理 ==========
_ORIG_PROXY = {}

# 模块加载时清除代理（akshare请求东方财富需直连）
for _key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    _val = os.environ.get(_key)
    if _val:
        _ORIG_PROXY[_key] = _val
        del os.environ[_key]


def _clear_proxy():
    """清除所有代理环境变量"""
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(key, None)


def _restore_proxy():
    """恢复代理"""
    for key, val in _ORIG_PROXY.items():
        os.environ[key] = val


# ========== 数据源健康检测 ==========
_datasource_status = {"em": None, "qq": None}  # None=未检测, True=可用, False=不可用


def _check_datasource(source: str = "em") -> bool:
    """检测数据源是否可用"""
    if source == "em":
        try:
            _clear_proxy()
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            _restore_proxy()
            available = df is not None and not df.empty
            _datasource_status["em"] = available
            if available:
                print("[数据源] 东方财富 ✓")
            else:
                print("[数据源] 东方财富返回空 ✗")
            return available
        except Exception as e:
            _restore_proxy()
            _datasource_status["em"] = False
            print(f"[数据源] 东方财富不可用: {e}")
            return False
    elif source == "qq":
        try:
            r = requests.get("http://qt.gtimg.cn/q=sh600519", timeout=5)
            available = r.status_code == 200 and "贵州茅台" in r.text
            _datasource_status["qq"] = available
            if available:
                print("[数据源] 腾讯财经 ✓")
            else:
                print("[数据源] 腾讯财经返回异常 ✗")
            return available
        except Exception as e:
            _datasource_status["qq"] = False
            print(f"[数据源] 腾讯财经不可用: {e}")
            return False
    return False


def _ensure_datasource():
    """确保至少有一个可用数据源，优先东方财富"""
    if _datasource_status["em"] is None:
        _check_datasource("em")
    if not _datasource_status["em"] and _datasource_status["qq"] is None:
        _check_datasource("qq")


# ========== 腾讯接口解析 ==========

def _qq_code_prefix(stock_code: str) -> str:
    """股票代码转腾讯前缀：6开头=sh，其余=sz"""
    code = str(stock_code).strip()
    if code.startswith("6"):
        return f"sh{code}"
    return f"sz{code}"


def _qq_parse_realtime(raw_text: str) -> pd.DataFrame:
    """解析腾讯实时行情字符串为DataFrame"""
    rows = []
    for line in raw_text.strip().split(";"):
        line = line.strip()
        if not line or '="' not in line:
            continue
        try:
            _, val = line.split('="', 1)
            val = val.rstrip('"')
            parts = val.split("~")
            if len(parts) < 50:
                continue
            # 腾讯字段映射（关键字段）
            # [1]名称 [2]代码 [3]最新价 [4]昨收 [5]今开
            # [6]成交量(手) [31]涨跌额 [32]涨跌幅 [33]最高 [34]最低
            # [37]成交额(万) [38]换手率 [43]振幅
            stock_name = parts[1]
            stock_code = parts[2]
            price = float(parts[3]) if parts[3] else 0
            prev_close = float(parts[4]) if parts[4] else 0
            open_price = float(parts[5]) if parts[5] else 0
            volume = float(parts[6]) if parts[6] else 0
            change_amount = float(parts[31]) if parts[31] else 0
            change_pct = float(parts[32]) if parts[32] else 0
            high = float(parts[33]) if parts[33] else 0
            low = float(parts[34]) if parts[34] else 0
            turnover = float(parts[37]) if parts[37] else 0  # 万元
            turnover_rate = float(parts[38]) if parts[38] else 0
            amplitude = float(parts[43]) if parts[43] else 0
            vol_ratio = 0  # 腾讯不直接提供量比

            if price <= 0:
                continue

            rows.append({
                "stock_code": stock_code,
                "stock_name": stock_name,
                "price": price,
                "prev_close": prev_close,
                "open": open_price,
                "high": high,
                "low": low,
                "volume": volume * 100,  # 手→股
                "turnover": turnover * 10000,  # 万元→元
                "change_pct": change_pct,
                "change_amount": change_amount,
                "amplitude": amplitude,
                "turnover_rate": turnover_rate,
                "vol_ratio": vol_ratio,
            })
        except (ValueError, IndexError):
            continue

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _qq_fetch_kline(stock_code: str, period: int = 120) -> pd.DataFrame:
    """通过腾讯接口获取日K线"""
    prefix = _qq_code_prefix(stock_code)
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix},day,,,{period},qfq"
    try:
        r = requests.get(url, timeout=10)
        data = json.loads(r.text)
        if data.get("code") != 0:
            return pd.DataFrame()

        stock_data = data.get("data", {})
        inner = None
        for key in stock_data:
            inner = stock_data[key]
            break
        if inner is None:
            return pd.DataFrame()

        kline_data = inner.get("qfqday") or inner.get("day") or []
        if not kline_data:
            return pd.DataFrame()

        rows = []
        for item in kline_data:
            # 格式: [date, open, close, high, low, volume(手)]
            if len(item) < 6:
                continue
            try:
                open_p = float(item[1])
                close_p = float(item[2])
                high_p = float(item[3])
                low_p = float(item[4])
                vol_shou = float(item[5])   # 手
                vol_gu = vol_shou * 100     # 转为股
                # 成交额近似 = 均价 × 成交量(股)
                turnover = (open_p + close_p) / 2 * vol_gu if vol_gu > 0 else 0
                rows.append({
                    "日期": item[0],
                    "开盘": open_p,
                    "收盘": close_p,
                    "最高": high_p,
                    "最低": low_p,
                    "成交量": vol_gu,
                    "成交额": turnover,
                    "涨跌幅": 0,
                })
            except (ValueError, IndexError):
                continue

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        # 计算涨跌幅
        if len(df) > 1:
            df["涨跌幅"] = (df["收盘"] / df["收盘"].shift(1) - 1) * 100
            df["涨跌幅"] = df["涨跌幅"].fillna(0)

        # 去掉最后一行（可能是盘中不完整数据，导致技术指标异常）
        if len(df) > 5:
            today = datetime.now().strftime("%Y-%m-%d")
            last_date = str(df["日期"].iloc[-1])
            now = datetime.now()
            # 如果最后一行是今天且未收盘，去掉
            if last_date == today and now.hour < 15:
                df = df.iloc[:-1].copy()

        return df

    except Exception as e:
        print(f"[WARN] 腾讯K线获取 {stock_code} 失败: {e}")
        return pd.DataFrame()


# ========== 公共接口（自动降级） ==========

def fetch_realtime_quotes() -> pd.DataFrame:
    """获取A股全市场实时行情，三级降级：东方财富 → 新浪 → 腾讯"""
    # 1. 尝试东方财富
    try:
        _clear_proxy()
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        _restore_proxy()
        if df is not None and not df.empty:
            _datasource_status["em"] = True
            rename_map = {
                "代码": "stock_code", "名称": "stock_name", "最新价": "price",
                "涨跌幅": "change_pct", "涨跌额": "change_amount",
                "成交量": "volume", "成交额": "turnover", "振幅": "amplitude",
                "最高": "high", "最低": "low", "今开": "open", "昨收": "prev_close",
                "量比": "vol_ratio", "换手率": "turnover_rate",
                "市盈率-动态": "pe_ttm", "市净率": "pb",
            }
            existing = {k: v for k, v in rename_map.items() if k in df.columns}
            df = df.rename(columns=existing)
            if "stock_code" in df.columns:
                df["stock_code"] = df["stock_code"].astype(str)
            return df
    except Exception as e:
        _restore_proxy()
        _datasource_status["em"] = False
        print(f"[WARN] 东方财富实时行情失败: {e}")

    # 2. 降级到新浪接口
    print("[数据源] 降级到新浪财经获取实时行情...")
    try:
        _clear_proxy()
        import akshare as ak
        df = ak.stock_zh_a_spot()
        _restore_proxy()
        if df is not None and not df.empty:
            _datasource_status["sina"] = True
            rename_map = {
                "代码": "stock_code", "名称": "stock_name", "最新价": "price",
                "涨跌幅": "change_pct", "涨跌额": "change_amount",
                "成交量": "volume", "成交额": "turnover",
                "最高": "high", "最低": "low", "今开": "open", "昨收": "prev_close",
            }
            existing = {k: v for k, v in rename_map.items() if k in df.columns}
            df = df.rename(columns=existing)
            if "stock_code" in df.columns:
                df["stock_code"] = df["stock_code"].astype(str)
            # 新浪接口缺少的字段补默认值
            for col, default in [("amplitude", 0), ("turnover_rate", 0), ("vol_ratio", 0)]:
                if col not in df.columns:
                    df[col] = default
            print(f"[数据源] 新浪财经获取 {len(df)} 只股票行情")
            return df
    except Exception as e:
        _restore_proxy()
        print(f"[WARN] 新浪实时行情失败: {e}")

    # 3. 最终降级到腾讯接口（逐批查询）
    print("[数据源] 降级到腾讯财经获取实时行情...")
    try:
        return _qq_fetch_all_realtime()
    except Exception as e:
        print(f"[ERROR] 腾讯实时行情也失败: {e}")
        return pd.DataFrame()


def _qq_fetch_all_realtime() -> pd.DataFrame:
    """通过腾讯接口获取全市场A股实时行情（分页拉取）"""
    all_rows = []

    # 获取股票列表：优先新浪，再缓存，最后代码段遍历
    codes = []
    try:
        _clear_proxy()
        import akshare as ak
        stock_list = ak.stock_zh_a_spot()
        _restore_proxy()
        if stock_list is not None and not stock_list.empty:
            code_col = "代码" if "代码" in stock_list.columns else "stock_code"
            codes = stock_list[code_col].astype(str).tolist()
    except Exception:
        _restore_proxy()

    if not codes:
        try:
            conn = get_connection()
            codes_df = pd.read_sql_query(
                "SELECT DISTINCT stock_code FROM daily_kline LIMIT 2000",
                conn
            )
            conn.close()
            codes = codes_df["stock_code"].tolist()
        except Exception:
            pass

    if not codes:
        # 最终方案：用代码段范围生成（沪市60xxxx + 深市00xxxx + 创业板30xxxx）
        codes = []
        for prefix in ("60", "00", "30"):
            for i in range(0, 3000):
                codes.append(f"{prefix}{i:04d}")

    if not codes:
        print("[ERROR] 无法获取股票列表")
        return pd.DataFrame()

    # 腾讯接口批量查（每批最多50个）
    batch_size = 50
    for i in range(0, min(len(codes), 500), batch_size):  # 限制最多500只
        batch = codes[i:i + batch_size]
        qq_codes = ",".join(_qq_code_prefix(c) for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={qq_codes}", timeout=10)
            df = _qq_parse_realtime(r.text)
            if not df.empty:
                all_rows.append(df)
        except Exception:
            continue
        time.sleep(0.1)

    if not all_rows:
        return pd.DataFrame()

    _datasource_status["qq"] = True
    result = pd.concat(all_rows, ignore_index=True)
    print(f"[数据源] 腾讯财经获取 {len(result)} 只股票行情")
    return result


def fetch_daily_kline(stock_code: str, period: int = 120, use_cache: bool = True) -> pd.DataFrame:
    """获取个股日K线，优先缓存 → 东方财富 → 腾讯降级"""
    # 1. 先查缓存
    if use_cache:
        cached = load_daily_kline(stock_code, days=period + 30)
        last_date = get_last_trade_date(stock_code)
        today = datetime.now().strftime("%Y%m%d")
        if not cached.empty and last_date == today:
            return cached.tail(period)

    # 2. 尝试东方财富
    if _datasource_status["em"] is not False:  # None或True都试
        try:
            _clear_proxy()
            import akshare as ak
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=(datetime.now() - pd.Timedelta(days=period * 2)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
                adjust="qfq"
            )
            _restore_proxy()
            if not df.empty:
                _datasource_status["em"] = True
                save_daily_kline(stock_code, df)
                return df.tail(period)
        except Exception as e:
            _restore_proxy()
            _datasource_status["em"] = False
            print(f"[WARN] 东方财富K线 {stock_code} 失败: {e}")

    # 3. 降级到腾讯
    if _datasource_status["qq"] is not False:
        try:
            df = _qq_fetch_kline(stock_code, period=period)
            if not df.empty:
                _datasource_status["qq"] = True
                save_daily_kline(stock_code, df)
                return df.tail(period)
        except Exception as e:
            _datasource_status["qq"] = False
            print(f"[WARN] 腾讯K线 {stock_code} 也失败: {e}")

    # 4. 最终降级到缓存
    if use_cache:
        cached = load_daily_kline(stock_code, days=period)
        if not cached.empty:
            print(f"[数据源] {stock_code} 使用缓存数据")
            return cached

    return pd.DataFrame()


def fetch_capital_flow(stock_code: str) -> dict:
    """获取个股资金流向（东方财富独有，失败返回空）"""
    try:
        _clear_proxy()
        import akshare as ak
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
        print(f"[WARN] 资金流向 {stock_code} 失败: {e}")
    return {}


def fetch_sector_changes() -> pd.DataFrame:
    """获取板块涨跌幅（东方财富独有，失败返回空）"""
    try:
        _clear_proxy()
        import akshare as ak
        df = ak.stock_board_industry_name_em()
        _restore_proxy()
        if df is not None and not df.empty:
            rename_map = {
                "板块名称": "sector_name", "涨跌幅": "change_pct",
                "总市值": "total_market_cap", "换手率": "turnover_rate",
                "上涨家数": "up_count", "下跌家数": "down_count",
            }
            existing = {k: v for k, v in rename_map.items() if k in df.columns}
            df = df.rename(columns=existing)
            return df
    except Exception as e:
        _restore_proxy()
        print(f"[WARN] 板块数据失败: {e}")
    return pd.DataFrame()


def fetch_stock_sector_map() -> pd.DataFrame:
    """获取个股-板块映射（东方财富独有，失败返回空）"""
    try:
        _clear_proxy()
        import akshare as ak
        boards = ak.stock_board_industry_name_em()
        if boards is None or boards.empty:
            return pd.DataFrame()

        mapping = []
        board_col = "板块名称" if "板块名称" in boards.columns else None
        if board_col is None:
            return pd.DataFrame()

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
        print(f"[WARN] 板块映射失败: {e}")
        return pd.DataFrame()


def fetch_stock_list() -> pd.DataFrame:
    """获取A股股票列表"""
    try:
        _clear_proxy()
        import akshare as ak
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
    """批量获取日K线"""
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
