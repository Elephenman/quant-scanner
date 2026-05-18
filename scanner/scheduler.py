"""
定时扫描调度器
交易日盘前/盘中/盘后自动扫描
"""

import os
import sys
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from factors.loader import discover_factors
from scanner.engine import SignalScanner
from data.cache import init_db


scheduler = BackgroundScheduler()
scanner = None


def init_scanner():
    global scanner
    if scanner is None:
        init_db()
        discover_factors()
        scanner = SignalScanner()
    return scanner


def pre_market_scan():
    """盘前扫描：9:15 集合竞价分析"""
    print(f"[定时] 盘前扫描 {datetime.now()}")
    s = init_scanner()
    s._ensure_factors()
    from factors.base import FactorRegistry
    # 全部因子启用，竞价权重加倍
    factors = {
        name: {"weight": f.default_weight * 2 if f.category.value == "竞价面" else f.default_weight,
               "enabled": True, "params": {}}
        for name, f in FactorRegistry.all_factors().items()
    }
    results = s.scan_market(selected_factors=factors, top_n=30)
    print(f"[定时] 盘前扫描完成，发现 {len(results)} 个信号")
    return results


def intraday_scan():
    """盘中扫描：每5分钟"""
    now = datetime.now()
    if now.weekday() >= 5:  # 周末不扫
        return
    print(f"[定时] 盘中扫描 {now}")
    s = init_scanner()
    results = s.scan_market(top_n=50)
    print(f"[定时] 盘中扫描完成，发现 {len(results)} 个信号")
    return results


def post_market_scan():
    """盘后扫描：15:30 总结"""
    print(f"[定时] 盘后总结 {datetime.now()}")
    s = init_scanner()
    results = s.scan_market(top_n=100)
    print(f"[定时] 盘后总结完成，发现 {len(results)} 个信号")
    return results


def setup_schedule():
    """设置定时任务"""
    # 盘前 9:15
    scheduler.add_job(
        pre_market_scan,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=15),
        id="pre_market",
        name="盘前竞价扫描",
    )

    # 盘中 每5分钟 9:35-11:25, 13:05-14:55
    scheduler.add_job(
        intraday_scan,
        CronTrigger(day_of_week="mon-fri", hour="9-14", minute="*/5"),
        id="intraday_1",
        name="盘中扫描(上午)",
    )

    # 盘后 15:30
    scheduler.add_job(
        post_market_scan,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30),
        id="post_market",
        name="盘后总结",
    )

    print("[定时] 已设置定时任务:")
    print("  09:15 盘前竞价扫描")
    print("  09:35-14:55 每5分钟盘中扫描")
    print("  15:30 盘后总结")


def start_scheduler():
    """启动定时器"""
    setup_schedule()
    scheduler.start()
    print("[定时] 调度器已启动")


if __name__ == "__main__":
    start_scheduler()
    try:
        while True:
            pass
    except KeyboardInterrupt:
        scheduler.shutdown()
        print("[定时] 调度器已停止")
