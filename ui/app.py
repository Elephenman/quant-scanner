"""
QuantScanner - A股量化信号扫描器
主页面：因子选配 + 信号扫描 + 结果展示
"""

import json
import sys
import os
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# 确保项目根目录在 sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from factors.loader import discover_factors, get_all_factors, get_factors_by_category
from factors.base import FactorRegistry, SignalType
from scanner.engine import SignalScanner
from data.cache import init_db, load_signal_history, save_scan_config, load_scan_configs
from data.fetcher import fetch_realtime_quotes

# ========== 页面配置 ==========
st.set_page_config(
    page_title="QuantScanner - A股信号扫描器",
    page_icon="📡",
    layout="wide",
)

# ========== 初始化 ==========
@st.cache_resource
def init_system():
    init_db()
    discover_factors()
    return SignalScanner()

scanner = init_system()

# ========== 侧边栏：因子选配 ==========
with st.sidebar:
    st.header("🎛️ 因子选配器")

    st.markdown("勾选因子、调整权重和参数，然后点击扫描")

    factors_by_cat = get_factors_by_category()
    factor_configs = {}

    for category, factors in factors_by_cat.items():
        with st.expander(f"{category.value} ({len(factors)})", expanded=True):
            for factor in factors:
                # 启用/禁用
                enabled = st.checkbox(
                    f"**{factor.name}**",
                    value=True,
                    key=f"enable_{factor.name}",
                    help=factor.description,
                )
                if enabled:
                    # 权重滑块
                    weight = st.slider(
                        "权重",
                        min_value=0.0,
                        max_value=3.0,
                        value=factor.default_weight,
                        step=0.1,
                        key=f"weight_{factor.name}",
                    )
                    # 因子参数
                    params = {}
                    if factor.params:
                        for param_name, param_config in factor.params.items():
                            param_val = st.slider(
                                param_config.get("label", param_name),
                                min_value=param_config["min"],
                                max_value=param_config["max"],
                                value=param_config["default"],
                                step=param_config["step"],
                                key=f"param_{factor.name}_{param_name}",
                            )
                            params[param_name] = param_val

                    factor_configs[factor.name] = {
                        "enabled": True,
                        "weight": weight,
                        "params": params,
                    }
                else:
                    factor_configs[factor.name] = {"enabled": False, "weight": 0, "params": {}}

    st.divider()

    # 过滤条件
    st.subheader("🔍 过滤条件")
    col1, col2 = st.columns(2)
    with col1:
        min_price = st.number_input("最低价", value=3.0, step=1.0)
        min_change = st.number_input("最小涨幅%", value=-9.0, step=1.0)
    with col2:
        max_price = st.number_input("最高价", value=50.0, step=5.0)
        max_change = st.number_input("最大涨幅%", value=9.0, step=1.0)

    scan_count = st.slider("扫描数量", min_value=10, max_value=200, value=50, step=10)

    st.divider()

    # 保存/加载配置
    st.subheader("💾 配置管理")
    config_name = st.text_input("配置名称", value="默认配置")
    if st.button("保存当前配置"):
        save_scan_config(config_name, json.dumps(factor_configs, ensure_ascii=False))
        st.success(f"已保存配置: {config_name}")

    saved_configs = load_scan_configs()
    if not saved_configs.empty:
        config_options = saved_configs["config_name"].tolist()
        selected_config = st.selectbox("加载配置", ["不加载"] + config_options)
        if selected_config != "不加载" and st.button("应用配置"):
            config_json = saved_configs[saved_configs["config_name"] == selected_config]["factors_json"].iloc[0]
            st.session_state["loaded_config"] = json.loads(config_json)
            st.rerun()

# ========== 主区域 ==========

# 标题栏
col_title, col_time, col_btn = st.columns([3, 2, 1])
with col_title:
    st.title("📡 QuantScanner")
    st.caption("A股超短线信号扫描器 | 因子自由组合 → 信号实时推送 → 手动下单")
with col_time:
    now = datetime.now()
    st.metric("当前时间", now.strftime("%Y-%m-%d %H:%M"))
    is_trading = 9 <= now.hour <= 15 and now.weekday() < 5
    st.metric("交易状态", "🟢 交易中" if is_trading else "⚪ 休市")
with col_btn:
    st.write("")  # spacer
    if st.button("🔄 刷新数据", type="primary", use_container_width=True):
        st.rerun()

st.divider()

# 扫描按钮
col_scan1, col_scan2, col_scan3 = st.columns([1, 1, 3])
with col_scan1:
    if st.button("🚀 全市场扫描", type="primary", use_container_width=True):
        with st.spinner("扫描中，请耐心等待..."):
            signals = scanner.scan_market(
                selected_factors=factor_configs,
                min_price=min_price,
                max_price=max_price,
                min_change=min_change,
                max_change=max_change,
                top_n=scan_count,
            )
            st.session_state["signals"] = signals

with col_scan2:
    watchlist_input = st.text_input("自选股（逗号分隔）", value="600519,000858,300750", label_visibility="collapsed")
    if st.button("👁️ 扫描自选股", use_container_width=True):
        codes = [c.strip() for c in watchlist_input.split(",") if c.strip()]
        with st.spinner("扫描自选股..."):
            signals = scanner.scan_watchlist(codes, selected_factors=factor_configs)
            st.session_state["signals"] = signals

# ========== 信号展示 ==========
signals = st.session_state.get("signals", [])

if signals:
    # 信号统计
    st.subheader("📊 信号统计")
    col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
    signal_counts = {t: 0 for t in SignalType}
    for s in signals:
        signal_counts[s.signal_type] = signal_counts.get(s.signal_type, 0) + 1

    col_s1.metric("强买 🔴", signal_counts.get(SignalType.STRONG_BUY, 0))
    col_s2.metric("买 🟠", signal_counts.get(SignalType.BUY, 0))
    col_s3.metric("观察 ⚪", signal_counts.get(SignalType.WATCH, 0))
    col_s4.metric("卖 🔵", signal_counts.get(SignalType.SELL, 0))
    col_s5.metric("强卖 🟣", signal_counts.get(SignalType.STRONG_SELL, 0))

    # 信号列表
    st.subheader("📡 信号列表")

    # 筛选信号类型
    filter_types = st.multiselect(
        "显示信号类型",
        options=[t.value for t in SignalType],
        default=["强买", "买"],
    )

    for signal in signals:
        if signal.signal_type.value not in filter_types:
            continue

        # 颜色映射
        color_map = {
            SignalType.STRONG_BUY: "🔴",
            SignalType.BUY: "🟠",
            SignalType.WATCH: "⚪",
            SignalType.SELL: "🔵",
            SignalType.STRONG_SELL: "🟣",
        }
        bg_map = {
            SignalType.STRONG_BUY: "#fff0f0",
            SignalType.BUY: "#fff5e6",
            SignalType.WATCH: "#f5f5f5",
            SignalType.SELL: "#e6f0ff",
            SignalType.STRONG_SELL: "#f0e6ff",
        }

        icon = color_map.get(signal.signal_type, "⚪")
        bg = bg_map.get(signal.signal_type, "#f5f5f5")

        with st.container():
            st.markdown(
                f'<div style="background:{bg}; padding:12px 16px; border-radius:8px; margin:4px 0;">'
                f'<span style="font-size:18px">{icon}</span> '
                f'<b>{signal.stock_code}</b> {signal.stock_name} '
                f'<span style="color:#666">现价:{signal.price:.2f} 涨跌:{signal.change_pct:+.2f}%</span> '
                f'<span style="float:right; font-weight:bold">{signal.signal_type.value} '
                f'评分:{signal.total_score:+.2f}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            # 展开因子详情
            with st.expander(f"因子详情: {signal.stock_name}"):
                for fr in signal.factor_results:
                    if abs(fr.score) > 0.05:
                        st.markdown(
                            f"- **{fr.factor_name}**: score={fr.score:+.2f}, "
                            f"signal={fr.signal.value} — {fr.detail}"
                        )

            # 弹窗提醒（仅强买/强卖）
            if signal.signal_type in (SignalType.STRONG_BUY, SignalType.STRONG_SELL):
                st.toast(
                    f"{icon} {signal.signal_type.value}: {signal.stock_name}({signal.stock_code}) "
                    f"评分:{signal.total_score:+.2f} | {signal.detail_text[:50]}",
                    icon="🚨" if signal.signal_type == SignalType.STRONG_BUY else "⚠️",
                )

else:
    # 无信号时的提示
    st.info("👈 左侧配置因子，点击「全市场扫描」或「扫描自选股」开始")

    # 显示历史信号
    st.subheader("📜 历史信号")
    history = load_signal_history(limit=20)
    if not history.empty:
        st.dataframe(
            history[["scan_time", "stock_code", "stock_name", "signal_type", "total_score", "price", "change_pct"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("暂无历史信号，开始你的第一次扫描吧！")

# ========== 底部 ==========
st.divider()
st.caption("QuantScanner v0.1 | 数据源: akshare | 仅供研究参考，不构成投资建议")
