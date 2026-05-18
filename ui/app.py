"""
QuantScanner - A股量化信号扫描器
主页面：因子选配 + 信号扫描 + 结果展示
v0.2.2: 双数据源自动降级 + 美化UI + 扫描修复
"""

import json
import sys
import os
from datetime import datetime

# 在任何网络请求之前清除代理（Clash TUN会拦截东方财富API）
for _key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_key, None)

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# 确保项目根目录在 sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from factors.loader import discover_factors, get_all_factors, get_factors_by_category
from factors.base import FactorRegistry, SignalType, FactorCategory
from scanner.engine import SignalScanner
from data.cache import init_db, load_signal_history, save_scan_config, load_scan_configs
from data.fetcher import fetch_realtime_quotes

# ========== 自定义CSS ==========
CUSTOM_CSS = """
<style>
    /* 主色调 */
    :root {
        --qs-primary: #1a73e8;
        --qs-success: #34a853;
        --qs-danger: #ea4335;
        --qs-warning: #fbbc04;
        --qs-bg: #0f1117;
        --qs-card: #1a1d29;
        --qs-border: #2a2d3a;
        --qs-text: #e8eaed;
        --qs-text-dim: #9aa0a6;
    }

    /* 全局深色主题 */
    .stApp {
        background: var(--qs-bg) !important;
    }

    /* 信号卡片 */
    .signal-card {
        border: 1px solid var(--qs-border);
        border-radius: 12px;
        padding: 16px 20px;
        margin: 8px 0;
        background: var(--qs-card);
        transition: all 0.2s ease;
    }
    .signal-card:hover {
        border-color: var(--qs-primary);
        box-shadow: 0 2px 12px rgba(26,115,232,0.15);
    }
    .signal-strong-buy {
        border-left: 4px solid #34a853;
    }
    .signal-buy {
        border-left: 4px solid #8bc34a;
    }
    .signal-watch {
        border-left: 4px solid #9aa0a6;
    }
    .signal-sell {
        border-left: 4px solid #ff9800;
    }
    .signal-strong-sell {
        border-left: 4px solid #ea4335;
    }
    .signal-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 13px;
        font-weight: 600;
    }
    .badge-strong-buy { background: rgba(52,168,83,0.2); color: #34a853; }
    .badge-buy { background: rgba(139,195,74,0.2); color: #8bc34a; }
    .badge-watch { background: rgba(154,160,166,0.2); color: #9aa0a6; }
    .badge-sell { background: rgba(255,152,0,0.2); color: #ff9800; }
    .badge-strong-sell { background: rgba(234,67,53,0.2); color: #ea4335; }

    /* 统计卡片 */
    .stat-card {
        text-align: center;
        padding: 12px 8px;
        border-radius: 10px;
        background: var(--qs-card);
        border: 1px solid var(--qs-border);
    }
    .stat-number {
        font-size: 28px;
        font-weight: 700;
        line-height: 1.2;
    }
    .stat-label {
        font-size: 12px;
        color: var(--qs-text-dim);
        margin-top: 4px;
    }

    /* 因子分数条 */
    .factor-bar {
        height: 6px;
        border-radius: 3px;
        background: var(--qs-border);
        margin: 4px 0;
    }
    .factor-bar-fill {
        height: 6px;
        border-radius: 3px;
        transition: width 0.3s ease;
    }

    /* 侧边栏样式 */
    [data-testid="stSidebar"] {
        background: #13151f !important;
    }

    /* 扫描按钮 */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #1a73e8, #4285f4) !important;
        border: none !important;
        font-weight: 600 !important;
    }

    /* 进度条 */
    .scan-progress {
        background: var(--qs-card);
        border-radius: 8px;
        padding: 12px 16px;
        margin: 8px 0;
        border: 1px solid var(--qs-border);
    }
</style>
"""

# ========== 页面配置 ==========
st.set_page_config(
    page_title="QuantScanner - A股信号扫描器",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ========== 初始化 ==========
# 版本号：修改代码后递增此值，强制 Streamlit 重建缓存
_CACHE_VERSION = "v0.3.0"

def _create_scanner():
    """创建新的扫描器实例（确保每次代码更新都拿到最新类）"""
    init_db()
    loaded = discover_factors()
    return SignalScanner(), loaded

@st.cache_resource
def init_system(_version: str = ""):
    return _create_scanner()

scanner, loaded_factors = init_system(_version=_CACHE_VERSION)

# ========== 侧边栏：因子选配 ==========
with st.sidebar:
    st.markdown("### 🎛️ 因子策略选配")
    st.caption("勾选因子策略 → 调整权重 → 扫描")

    factors_by_cat = get_factors_by_category()
    factor_configs = {}

    # 分类顺序
    cat_order = [
        FactorCategory.CAPITAL_FLOW,
        FactorCategory.VOLUME_PRICE,
        FactorCategory.TECHNICAL,
        FactorCategory.AUCTION,
        FactorCategory.SECTOR,
    ]
    # 补上不在顺序中的分类
    for cat in factors_by_cat:
        if cat not in cat_order:
            cat_order.append(cat)

    for category in cat_order:
        factors = factors_by_cat.get(category, [])
        if not factors:
            continue

        cat_icon = {
            FactorCategory.CAPITAL_FLOW: "💰",
            FactorCategory.VOLUME_PRICE: "📊",
            FactorCategory.TECHNICAL: "📈",
            FactorCategory.AUCTION: "🔔",
            FactorCategory.SECTOR: "🏭",
            FactorCategory.FUNDAMENTAL: "📋",
            FactorCategory.SENTIMENT: "🗣️",
        }.get(category, "📌")

        with st.expander(f"{cat_icon} {category.value} ({len(factors)})", expanded=True):
            for factor in factors:
                # 判断是否为组合因子
                is_combo = "组合" in factor.name
                label = f"**{factor.name}** {'🔥' if is_combo else ''}"
                if is_combo:
                    label += "  `组合`"

                enabled = st.checkbox(
                    label,
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
    st.markdown("### 🔍 过滤条件")
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
    st.markdown("### 💾 配置管理")
    config_name = st.text_input("配置名称", value="默认配置")
    if st.button("💾 保存当前配置"):
        save_scan_config(config_name, json.dumps(factor_configs, ensure_ascii=False))
        st.success(f"已保存配置: {config_name}")

    saved_configs = load_scan_configs()
    if not saved_configs.empty:
        config_options = saved_configs["config_name"].tolist()
        selected_config = st.selectbox("加载配置", ["不加载"] + config_options)
        if selected_config != "不加载" and st.button("📥 应用配置"):
            config_json = saved_configs[saved_configs["config_name"] == selected_config]["factors_json"].iloc[0]
            st.session_state["loaded_config"] = json.loads(config_json)
            st.rerun()

# ========== 主区域 ==========

# 顶部标题栏
col_title, col_info = st.columns([3, 2])
with col_title:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;">
        <span style="font-size:36px">📡</span>
        <div>
            <div style="font-size:24px;font-weight:700;color:var(--qs-text);">QuantScanner</div>
            <div style="font-size:13px;color:var(--qs-text-dim);">A股超短线信号扫描器 | 因子策略组合 → 信号实时推送 → 手动下单</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
with col_info:
    now = datetime.now()
    is_trading = 9 <= now.hour <= 15 and now.weekday() < 5
    status_text = "🟢 交易中" if is_trading else "⚪ 休市"
    status_color = "#34a853" if is_trading else "#9aa0a6"
    st.markdown(f"""
    <div style="text-align:right;">
        <div style="font-size:18px;font-weight:600;color:var(--qs-text);">{now.strftime('%Y-%m-%d %H:%M')}</div>
        <div style="font-size:14px;color:{status_color};">{status_text}</div>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# 扫描区域
col_scan1, col_scan2, col_scan3 = st.columns([1, 1, 2])
with col_scan1:
    if st.button("🚀 全市场扫描", type="primary", use_container_width=True):
        progress_text = st.empty()
        progress_bar = st.progress(0)

        def on_progress(current, total, name):
            if total > 0:
                progress_bar.progress(current / total)
                progress_text.text(f"扫描中 {current}/{total} {name}")

        with st.spinner("扫描中..."):
            try:
                signals = scanner.scan_market(
                    selected_factors=factor_configs,
                    min_price=min_price,
                    max_price=max_price,
                    min_change=min_change,
                    max_change=max_change,
                    top_n=scan_count,
                    progress_callback=on_progress,
                )
                st.session_state["signals"] = signals
            except TypeError as e:
                st.error(f"⚠️ 扫描器版本不匹配，请刷新页面（Ctrl+F5）后重试：{e}")
                signals = []
            except Exception as e:
                st.error(f"⚠️ 扫描失败：{e}")
                signals = []
        progress_bar.empty()
        progress_text.empty()
        if signals:
            st.success(f"✅ 扫描完成，发现 {len(signals)} 只信号股")
        elif "signals" not in st.session_state or not st.session_state.get("signals"):
            st.warning("⚠️ 未发现信号，请检查因子配置或网络连接")

with col_scan2:
    watchlist_input = st.text_input(
        "自选股代码（逗号分隔）",
        value="600519,000858,300750",
        label_visibility="visible",
    )
    if st.button("👁️ 扫描自选股", use_container_width=True):
        codes = [c.strip() for c in watchlist_input.split(",") if c.strip()]
        if not codes:
            st.error("请输入至少一个股票代码")
        else:
            progress_text = st.empty()
            progress_bar = st.progress(0)

            def on_progress2(current, total, name):
                if total > 0:
                    progress_bar.progress(current / total)
                    progress_text.text(f"扫描中 {current}/{total} {name}")

            with st.spinner("扫描自选股..."):
                try:
                    signals = scanner.scan_watchlist(
                        codes,
                        selected_factors=factor_configs,
                        progress_callback=on_progress2,
                    )
                    st.session_state["signals"] = signals
                except TypeError as e:
                    st.error(f"⚠️ 扫描器版本不匹配，请刷新页面（Ctrl+F5）后重试：{e}")
                    signals = []
                except Exception as e:
                    st.error(f"⚠️ 扫描失败：{e}")
                    signals = []
            progress_bar.empty()
            progress_text.empty()
            if signals:
                st.success(f"✅ 扫描完成，{len(signals)}/{len(codes)} 只产生信号")
            else:
                st.warning("⚠️ 未产生信号，请检查代码和网络")

with col_scan3:
    # 快速说明
    active_count = sum(1 for v in factor_configs.values() if v.get("enabled", True))
    combo_count = sum(1 for k, v in factor_configs.items() if v.get("enabled", True) and "组合" in k)
    st.markdown(f"""
    <div style="background:var(--qs-card);border:1px solid var(--qs-border);border-radius:10px;padding:12px 16px;">
        <div style="font-size:13px;color:var(--qs-text-dim);">
        📌 当前策略：<b style="color:var(--qs-text)">{active_count}</b> 个因子启用
        （其中 <b style="color:#fbbc04">{combo_count}</b> 个组合策略）
        ｜ 价格区间 {min_price}-{max_price} ｜ 涨跌幅 {min_change}%~{max_change}%
        </div>
    </div>
    """, unsafe_allow_html=True)

# ========== 信号展示 ==========
signals = st.session_state.get("signals", [])

if signals:
    # 信号统计卡片
    signal_counts = {}
    for t in SignalType:
        signal_counts[t] = sum(1 for s in signals if s.signal_type == t)

    cols = st.columns(5)
    stat_config = [
        (SignalType.STRONG_BUY, "强买", "#34a853", "🟢"),
        (SignalType.BUY, "买", "#8bc34a", "🟡"),
        (SignalType.WATCH, "观察", "#9aa0a6", "⚪"),
        (SignalType.SELL, "卖", "#ff9800", "🟠"),
        (SignalType.STRONG_SELL, "强卖", "#ea4335", "🔴"),
    ]

    for i, (stype, label, color, icon) in enumerate(stat_config):
        with cols[i]:
            st.markdown(f"""
            <div class="stat-card">
                <div class="stat-number" style="color:{color}">{signal_counts.get(stype, 0)}</div>
                <div class="stat-label">{icon} {label}</div>
            </div>
            """, unsafe_allow_html=True)

    # 筛选信号类型
    st.markdown("---")
    col_filter, col_sort = st.columns([2, 1])
    with col_filter:
        filter_types = st.multiselect(
            "显示信号类型",
            options=[t.value for t in SignalType],
            default=["强买", "买", "观察"],
        )
    with col_sort:
        sort_order = st.selectbox("排序", ["按评分降序", "按涨跌幅", "按价格升序"])

    # 排序
    filtered_signals = [s for s in signals if s.signal_type.value in filter_types]
    if sort_order == "按涨跌幅":
        filtered_signals.sort(key=lambda s: s.change_pct, reverse=True)
    elif sort_order == "按价格升序":
        filtered_signals.sort(key=lambda s: s.price)

    # 信号列表
    st.markdown(f"### 📡 信号列表（{len(filtered_signals)} 只）")

    for signal in filtered_signals:
        # CSS class
        css_class = {
            SignalType.STRONG_BUY: "signal-strong-buy",
            SignalType.BUY: "signal-buy",
            SignalType.WATCH: "signal-watch",
            SignalType.SELL: "signal-sell",
            SignalType.STRONG_SELL: "signal-strong-sell",
        }.get(signal.signal_type, "signal-watch")

        badge_class = {
            SignalType.STRONG_BUY: "badge-strong-buy",
            SignalType.BUY: "badge-buy",
            SignalType.WATCH: "badge-watch",
            SignalType.SELL: "badge-sell",
            SignalType.STRONG_SELL: "badge-strong-sell",
        }.get(signal.signal_type, "badge-watch")

        badge_color = {
            SignalType.STRONG_BUY: "#34a853",
            SignalType.BUY: "#8bc34a",
            SignalType.WATCH: "#9aa0a6",
            SignalType.SELL: "#ff9800",
            SignalType.STRONG_SELL: "#ea4335",
        }.get(signal.signal_type, "#9aa0a6")

        # 评分进度条颜色
        score_pct = (signal.total_score + 1) / 2 * 100  # -1~1 → 0~100
        bar_color = "#34a853" if signal.total_score > 0.3 else "#ff9800" if signal.total_score < -0.3 else "#9aa0a6"

        # 因子分数条
        factor_bars = ""
        for fr in signal.factor_results:
            if abs(fr.score) > 0.05:
                fw = (fr.score + 1) / 2 * 100
                fc = "#34a853" if fr.score > 0.2 else "#ea4335" if fr.score < -0.2 else "#9aa0a6"
                factor_bars += f"""
                <div style="display:flex;align-items:center;gap:8px;margin:3px 0;">
                    <span style="font-size:12px;color:var(--qs-text-dim);width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{fr.factor_name}</span>
                    <div style="flex:1;height:4px;background:var(--qs-border);border-radius:2px;">
                        <div style="width:{fw}%;height:4px;background:{fc};border-radius:2px;"></div>
                    </div>
                    <span style="font-size:11px;color:{fc};width:40px;text-align:right;">{fr.score:+.2f}</span>
                </div>
                """

        st.markdown(f"""
        <div class="signal-card {css_class}">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                    <span style="font-size:18px;font-weight:700;color:var(--qs-text);">{signal.stock_name}</span>
                    <span style="font-size:14px;color:var(--qs-text-dim);margin-left:8px;">{signal.stock_code}</span>
                    <span style="margin-left:12px;font-size:15px;color:var(--qs-text);">
                        ¥{signal.price:.2f}
                    </span>
                    <span style="font-size:14px;color:{'#34a853' if signal.change_pct >= 0 else '#ea4335'};margin-left:6px;">
                        {signal.change_pct:+.2f}%
                    </span>
                </div>
                <div style="display:flex;align-items:center;gap:12px;">
                    <span class="signal-badge {badge_class}">{signal.signal_type.value}</span>
                    <span style="font-size:20px;font-weight:700;color:{badge_color};">
                        {signal.total_score:+.2f}
                    </span>
                </div>
            </div>
            <div style="margin-top:8px;">
                {factor_bars}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 强买/强卖弹窗提醒
        if signal.signal_type in (SignalType.STRONG_BUY, SignalType.STRONG_SELL):
            st.toast(
                f"{'🟢' if signal.signal_type == SignalType.STRONG_BUY else '🔴'} "
                f"{signal.signal_type.value}: {signal.stock_name}({signal.stock_code}) "
                f"评分:{signal.total_score:+.2f}",
                icon="🚨" if signal.signal_type == SignalType.STRONG_BUY else "⚠️",
            )

else:
    # 无信号时的引导
    st.markdown("""
    <div style="text-align:center;padding:60px 20px;">
        <div style="font-size:64px;margin-bottom:16px;">📡</div>
        <div style="font-size:22px;font-weight:600;color:var(--qs-text);margin-bottom:8px;">开始你的第一次扫描</div>
        <div style="font-size:15px;color:var(--qs-text-dim);max-width:500px;margin:0 auto;">
            在左侧选择因子策略组合，调整权重和参数，<br>
            然后点击「全市场扫描」或输入自选股代码扫描<br>
            <br>
            💡 <b>组合因子</b>比单一指标更可靠：多维度交叉验证减少假信号
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 显示历史信号
    history = load_signal_history(limit=20)
    if not history.empty:
        st.markdown("### 📜 历史信号")
        st.dataframe(
            history[["scan_time", "stock_code", "stock_name", "signal_type", "total_score", "price", "change_pct"]],
            use_container_width=True,
            hide_index=True,
        )

# ========== 底部 ==========
st.divider()
st.caption("QuantScanner v0.3 | 数据源: akshare + 腾讯财经 | 仅供研究参考，不构成投资建议")
