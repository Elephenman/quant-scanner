"""
数据缓存层 - SQLite本地存储
避免重复请求akshare，支持增量更新
"""

import os
import sqlite3
from datetime import datetime, timedelta

import pandas as pd


DB_PATH = os.path.join(os.path.dirname(__file__), "quant_scanner.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_kline (
            stock_code TEXT,
            trade_date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            turnover REAL,
            change_pct REAL,
            PRIMARY KEY (stock_code, trade_date)
        );

        CREATE TABLE IF NOT EXISTS capital_flow (
            stock_code TEXT,
            trade_date TEXT,
            net_inflow REAL,
            net_inflow_large REAL,
            net_inflow_medium REAL,
            net_inflow_small REAL,
            PRIMARY KEY (stock_code, trade_date)
        );

        CREATE TABLE IF NOT EXISTS stock_info (
            stock_code TEXT PRIMARY KEY,
            stock_name TEXT,
            industry TEXT,
            sector TEXT,
            update_time TEXT
        );

        CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_time TEXT,
            stock_code TEXT,
            stock_name TEXT,
            signal_type TEXT,
            total_score REAL,
            detail TEXT,
            price REAL,
            change_pct REAL
        );

        CREATE TABLE IF NOT EXISTS scan_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_name TEXT,
            factors_json TEXT,
            created_at TEXT,
            is_active INTEGER DEFAULT 1
        );
    """)
    conn.commit()
    conn.close()
    print("[DB] 数据库初始化完成")


def save_daily_kline(stock_code: str, df: pd.DataFrame):
    """保存日K线数据（批量写入）"""
    if df is None or df.empty:
        return
    rows = []
    for _, row in df.iterrows():
        rows.append((
            stock_code,
            str(row.get("日期", row.get("trade_date", ""))),
            float(row.get("开盘", row.get("open", 0))),
            float(row.get("最高", row.get("high", 0))),
            float(row.get("最低", row.get("low", 0))),
            float(row.get("收盘", row.get("close", 0))),
            float(row.get("成交量", row.get("volume", 0))),
            float(row.get("成交额", row.get("turnover", 0))),
            float(row.get("涨跌幅", row.get("change_pct", 0))),
        ))
    conn = get_connection()
    conn.executemany("""
        INSERT OR REPLACE INTO daily_kline
        (stock_code, trade_date, open, high, low, close, volume, turnover, change_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    conn.close()


def load_daily_kline(stock_code: str, days: int = 120) -> pd.DataFrame:
    """从本地加载日K线"""
    conn = get_connection()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    df = pd.read_sql_query(
        "SELECT * FROM daily_kline WHERE stock_code=? AND trade_date>=? ORDER BY trade_date",
        conn, params=(stock_code, cutoff)
    )
    conn.close()
    if df.empty:
        return df
    # 列名已经标准（trade_date, open, high, low, close, volume, turnover, change_pct）
    return df


def get_last_trade_date(stock_code: str) -> str:
    """获取本地最新交易日"""
    conn = get_connection()
    result = conn.execute(
        "SELECT MAX(trade_date) FROM daily_kline WHERE stock_code=?",
        (stock_code,)
    ).fetchone()
    conn.close()
    return result[0] if result and result[0] else ""


def save_signal(signal_data: dict):
    """保存信号到历史记录"""
    conn = get_connection()
    conn.execute("""
        INSERT INTO signal_history
        (scan_time, stock_code, stock_name, signal_type, total_score, detail, price, change_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        signal_data.get("scan_time", ""),
        signal_data.get("stock_code", ""),
        signal_data.get("stock_name", ""),
        signal_data.get("signal_type", ""),
        signal_data.get("total_score", 0.0),
        signal_data.get("detail", ""),
        signal_data.get("price", 0.0),
        signal_data.get("change_pct", 0.0),
    ))
    conn.commit()
    conn.close()


def load_signal_history(limit: int = 100) -> pd.DataFrame:
    """加载信号历史"""
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM signal_history ORDER BY id DESC LIMIT ?",
        conn, params=(limit,)
    )
    conn.close()
    return df


def save_scan_config(config_name: str, factors_json: str):
    """保存扫描配置"""
    conn = get_connection()
    conn.execute("""
        INSERT INTO scan_config (config_name, factors_json, created_at, is_active)
        VALUES (?, ?, ?, 1)
    """, (config_name, factors_json, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def load_scan_configs() -> pd.DataFrame:
    """加载所有扫描配置"""
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM scan_config WHERE is_active=1 ORDER BY id DESC",
        conn
    )
    conn.close()
    return df
