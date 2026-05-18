"""
QuantScanner 启动入口
"""

import sys
import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

if __name__ == "__main__":
    from data.cache import init_db
    init_db()
    from factors.loader import discover_factors
    loaded = discover_factors()
    print(f"QuantScanner 启动 | 已加载 {len(loaded)} 个因子: {loaded}")
    print("启动命令: streamlit run ui/app.py")
