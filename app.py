"""
直播间销售数据分析仪表盘
运行：streamlit run app.py
"""

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="直播间销售分析", layout="wide", page_icon="📊")


# ═══════════════════════════════════════════════════════════════════════════════
# 数据加载（带缓存）
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data
def load_orders() -> pd.DataFrame:
    df = pd.read_parquet("data/processed/orders.parquet")
    df["order_date"] = pd.to_datetime(df["order_date"])
    df["pay_time"]   = pd.to_datetime(df["pay_time"])
    return df


@st.cache_data
def load_pairs() -> pd.DataFrame:
    p = pd.read_parquet("data/processed/purchase_pairs.parquet")
    p["from_date"] = pd.to_datetime(p["from_date"])
    p["to_date"]   = pd.to_datetime(p["to_date"])
    return p


@st.cache_data
def load_meta() -> dict:
    with open("data/processed/meta.json", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════════════════════
# 侧边栏筛选
# ═══════════════════════════════════════════════════════════════════════════════

def render_sidebar(meta: dict) -> dict:
    st.sidebar.header("🔍 全局筛选")

    d_min = pd.to_datetime(meta["date_min"]).date()
    d_max = pd.to_datetime(meta["date_max"]).date()
    date_range = st.sidebar.date_input("时间范围", value=(d_min, d_max),
                                        min_value=d_min, max_value=d_max)

    st.sidebar.subheader("渠道（达人）")
    sel_influencers = st.sidebar.multiselect(
        "选择渠道（不选 = 全选）", meta["influencers"], default=[])

    st.sidebar.subheader("货号")
    sku_kw = st.sidebar.text_input("货号关键词（如 tl）", "")
    all_skus = meta["skus"]
    filtered_skus = [s for s in all_skus if sku_kw.lower() in s.lower()] if sku_kw else all_skus
    if sku_kw:
        st.sidebar.caption(f"匹配 {len(filtered_skus)} 个货号")
    sel_skus = st.sidebar.multiselect(
        "选择货号（不选 = 全选）", filtered_skus, default=[])

    st.sidebar.subheader("订单状态")
    sel_statuses = st.sidebar.multiselect(
        "选择状态（不选 = 全选）", meta["order_statuses"], default=[])

    st.sidebar.subheader("成交金额（元）")
    amt_max_data = float(meta.get("gmv_max", 99999))
    amt_min = st.sidebar.number_input("最小金额", value=0.0, min_value=0.0, step=50.0)
    amt_max = st.sidebar.number_input("最大金额", value=amt_max_data, min_value=0.0, step=50.0)

    return {
        "date_range":      date_range,
        "sel_influencers": sel_influencers,
        "sel_skus":        sel_skus,
        "sel_statuses":    sel_statuses,
        "sku_kw":          sku_kw,
        "filtered_skus":   filtered_skus,
        "amt_min":         amt_min,
        "amt_max":         amt_max,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 过滤逻辑
# ═══════════════════════════════════════════════════════════════════════════════

def apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)

    dr = f["date_range"]
    if len(dr) == 2:
        mask &= (df["order_date"] >= pd.Timestamp(dr[0])) & \
                (df["order_date"] <= pd.Timestamp(dr[1]))

    if f["sel_influencers"]:
        mask &= df["influencer_name"].isin(f["sel_influencers"])

    if f["sel_skus"]:
        mask &= df["sku"].isin(f["sel_skus"])
    elif f["sku_kw"]:
        mask &= df["sku"].isin(f["filtered_skus"])

    if f["sel_statuses"]:
        mask &= df["order_status"].isin(f["sel_statuses"])

    mask &= (df["gmv"] >= f["amt_min"]) & (df["gmv"] <= f["amt_max"])

    return df[mask].copy()


def filter_pairs(pairs: pd.DataFrame, f: dict) -> pd.DataFrame:
    """筛选购买对：以 from_date 为时间锚点，from_influencer 为渠道锚点"""
    mask = pd.Series(True, index=pairs.index)

    dr = f["date_range"]
    if len(dr) == 2:
        mask &= (pairs["from_date"] >= pd.Timestamp(dr[0])) & \
                (pairs["from_date"] <= pd.Timestamp(dr[1]))

    if f["sel_influencers"]:
        mask &= pairs["from_influencer"].isin(f["sel_influencers"])

    if f["sel_skus"]:
        mask &= pairs["from_sku"].isin(f["sel_skus"])
    elif f["sku_kw"]:
        mask &= pairs["from_sku"].isin(f["filtered_skus"])

    if f["amt_min"] > 0:
        mask &= pairs["from_gmv"] >= f["amt_min"]

    return pairs[mask].copy()


# ═══════════════════════════════════════════════════════════════════════════════
# KPI 卡片
# ═══════════════════════════════════════════════════════════════════════════════

def render_kpi(df: pd.DataFrame):
    """
    客户维度新老客统计规则：
    若某用户在选定时间段内既有新客订单又有老客订单 → 该用户计为新客（首购在范围内）。
    """
    user_type = (
        df.groupby("user_id")["customer_type"]
        .apply(lambda s: "新客" if "新客" in s.values else "老客")
    )
    n_new   = int((user_type == "新客").sum())
    n_old   = int((user_type == "老客").sum())
    n_total = len(user_type)
    new_rate = n_new / n_total * 100 if n_total else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("总订单数",   f"{len(df):,}")
    c2.metric("总GMV",     f"¥{df['gmv'].sum():,.0f}")
    c3.metric("独立买家",   f"{n_total:,}")
    c4.metric("新客（人）", f"{n_new:,}")
    c5.metric("老客（人）", f"{n_old:,}")
    c6.metric("新客率",     f"{new_rate:.1f}%")


# ═══════════════════════════════════════════════════════════════════════════════
# Tab 1：新老客趋势
# ═══════════════════════════════════════════════════════════════════════════════

def tab_trend(df: pd.DataFrame):
    st.subheader("每日 / 汇总新老客趋势")

    col1, col2, col3 = st.columns(3)
    time_mode  = col1.radio("时间粒度", ["按天", "按月"], horizontal=True, key="t1_time")
    count_mode = col2.radio("计量指标", ["订单数", "GMV（元）"], horizontal=True, key="t1_count")
    show_pct   = col3.checkbox("显示占比 %", value=False, key="t1_pct")

    by_channel = st.checkbox("分渠道展示", value=False, key="t1_channel")

    date_col = "order_date" if time_mode == "按天" else "order_ym"
    val_col  = "gmv" if "GMV" in count_mode else None

    grp_cols = [date_col, "customer_type"]
    if by_channel:
        grp_cols = [date_col, "influencer_name", "customer_type"]

    if val_col:
        daily = df.groupby(grp_cols)["gmv"].sum().reset_index(name="value")
    else:
        daily = df.groupby(grp_cols).size().reset_index(name="value")

    # 折算占比
    if show_pct:
        total_by_date = daily.groupby(
            [date_col] + (["influencer_name"] if by_channel else [])
        )["value"].transform("sum")
        daily["value"] = (daily["value"] / total_by_date.replace(0, 1) * 100).round(2)
        y_label = "占比 (%)"
        y_range = [0, 100]
    else:
        y_label = count_mode
        y_range = None

    fig = px.bar(
        daily,
        x=date_col, y="value",
        color="customer_type",
        barmode="stack",
        facet_col="influencer_name" if by_channel else None,
        facet_col_wrap=3 if by_channel else None,
        color_discrete_map={"新客": "#FF6B6B", "老客": "#4ECDC4"},
        labels={"value": y_label, date_col: "日期", "customer_type": "客户类型",
                "influencer_name": "渠道"},
        height=450,
    )
    if y_range:
        fig.update_yaxes(range=y_range)
    fig.update_layout(hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    # 汇总表
    with st.expander("查看汇总数据表"):
        pivot_cols = ["influencer_name", "customer_type"] if by_channel else ["customer_type"]
        summary = df.groupby(pivot_cols).agg(
            订单数=("gmv", "count"),
            GMV=("gmv", "sum"),
            独立买家=("user_id", "nunique"),
        ).reset_index()
        summary["GMV"] = summary["GMV"].round(2)
        st.dataframe(summary, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Tab 2：货品分析
# ═══════════════════════════════════════════════════════════════════════════════

def tab_product(df: pd.DataFrame):
    st.subheader("货品新老客占比 & 销量排名")

    c1, c2 = st.columns([2, 1])
    sku_kw2 = c1.text_input("货号关键词过滤（仅此图表）", "", key="sku_kw2")
    metric  = c2.radio("指标", ["订单数", "GMV（元）"], horizontal=True, key="prod_metric")

    if sku_kw2:
        df = df[df["sku"].str.contains(sku_kw2, case=False, na=False)]

    if df.empty:
        st.info("没有匹配的货号")
        return

    use_gmv = "GMV" in metric
    if use_gmv:
        sku_grp   = df.groupby(["sku", "customer_type"])["gmv"].sum().reset_index(name="value")
        sku_total = df.groupby("sku")["gmv"].sum().reset_index(name="total")
    else:
        sku_grp   = df.groupby(["sku", "customer_type"]).size().reset_index(name="value")
        sku_total = df.groupby("sku").size().reset_index(name="total")

    sku_total = sku_total.sort_values("total", ascending=False)
    sku_order = sku_total["sku"].tolist()

    sku_pivot = sku_grp.pivot(index="sku", columns="customer_type", values="value").fillna(0)
    for ct in ("新客", "老客"):
        if ct not in sku_pivot.columns:
            sku_pivot[ct] = 0.0
    sku_pivot["total"]    = sku_pivot["新客"] + sku_pivot["老客"]
    sku_pivot["新客_pct"] = sku_pivot["新客"] / sku_pivot["total"].replace(0, 1) * 100
    sku_pivot["老客_pct"] = sku_pivot["老客"] / sku_pivot["total"].replace(0, 1) * 100
    sku_pivot = sku_pivot.reindex(sku_order)

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("**各货号新老客占比（%）**")
        fig1 = go.Figure()
        for ct, color in [("新客", "#FF6B6B"), ("老客", "#4ECDC4")]:
            fig1.add_trace(go.Bar(
                name=ct,
                y=sku_pivot.index,
                x=sku_pivot[f"{ct}_pct"],
                orientation="h",
                marker_color=color,
                text=sku_pivot[f"{ct}_pct"].round(1).astype(str) + "%",
                textposition="inside",
                hovertemplate=f"{ct}: %{{x:.1f}}%<extra></extra>",
            ))
        fig1.update_layout(
            barmode="stack",
            height=max(350, len(sku_pivot) * 28 + 120),
            xaxis=dict(title="占比 (%)", range=[0, 100]),
            yaxis=dict(title="货号", autorange="reversed"),
            legend_title="客户类型",
        )
        st.plotly_chart(fig1, use_container_width=True)

    with col_right:
        st.markdown(f"**{metric}总量排名（从高到低）**")
        display_total = sku_total.head(50)  # 最多显示50个
        fig2 = go.Figure(go.Bar(
            y=display_total["sku"],
            x=display_total["total"],
            orientation="h",
            marker_color="#6C8EBF",
            text=display_total["total"].round(0 if use_gmv else None),
            textposition="outside",
        ))
        fig2.update_layout(
            height=max(350, len(display_total) * 28 + 120),
            xaxis_title=metric,
            yaxis=dict(title="货号", autorange="reversed"),
        )
        st.plotly_chart(fig2, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Tab 3：老客复购周期
# ═══════════════════════════════════════════════════════════════════════════════

def tab_repurchase_cycle(df: pd.DataFrame, pairs: pd.DataFrame):
    st.subheader("老客平均复购周期")
    st.caption("仅统计老客的相邻两次购买之间的平均间隔天数。")

    user_ids = set(df[df["customer_type"] == "老客"]["user_id"].unique())
    p = pairs[pairs["user_id"].isin(user_ids)].copy()

    dim       = st.radio("分析维度", ["渠道 → 渠道", "货号 → 货号"], horizontal=True, key="cycle_dim")
    min_count = st.slider("最少转换次数（去除噪音）", 1, 100, 5, key="cycle_min")

    from_col = "from_influencer" if "渠道" in dim else "from_sku"
    to_col   = "to_influencer"   if "渠道" in dim else "to_sku"

    cycle = (
        p.groupby([from_col, to_col])
        .agg(avg_days=("days_between", "mean"), count=("days_between", "count"))
        .reset_index()
    )
    cycle = cycle[cycle["count"] >= min_count]

    if cycle.empty:
        st.info('没有足够的数据，请降低"最少转换次数"阈值')
        return

    pivot = cycle.pivot(index=from_col, columns=to_col, values="avg_days").round(1)

    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale="Blues",
        text=pivot.values,
        texttemplate="%{text:.0f}天",
        hovertemplate="从 %{y}<br>→ %{x}<br>平均 %{z:.0f} 天<extra></extra>",
        colorbar=dict(title="天数"),
    ))
    dim_label = "渠道" if "渠道" in dim else "货号"
    fig.update_layout(
        title=f"{dim_label}间平均复购间隔（天）",
        height=max(400, len(pivot) * 45 + 150),
        xaxis_title=f"下一次购买{dim_label}",
        yaxis_title=f"本次购买{dim_label}",
        xaxis=dict(tickangle=-30),
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("查看明细数据"):
        st.dataframe(
            cycle.rename(columns={
                from_col: "来源", to_col: "去向",
                "avg_days": "平均间隔（天）", "count": "转换次数"
            }).sort_values("平均间隔（天）"),
            use_container_width=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Tab 4：老客复购率
# ═══════════════════════════════════════════════════════════════════════════════

def tab_repurchase_rate(df: pd.DataFrame, pairs: pd.DataFrame):
    st.subheader("老客复购率分析")
    st.caption(
        "从某渠道/货号首次购买的用户中，有多少比例在后续去了哪个渠道/货号复购。"
        "「首次」= 该用户在整个数据集中的第1次购买。"
    )

    dim = st.radio("首次购买维度", ["渠道（达人）", "货号"], horizontal=True, key="rr_dim")

    if dim == "渠道（达人）":
        first_col = "influencer_name"
        from_col, to_col = "from_influencer", "to_influencer"
        options = sorted(df["influencer_name"].unique().tolist())
        label = "选择首次购买渠道"
    else:
        first_col = "sku"
        from_col, to_col = "from_sku", "to_sku"
        options = sorted(df["sku"].unique().tolist())
        label = "选择首次购买货号"

    sel_first = st.multiselect(label, options, default=[], key="rr_sel")

    # 首次购买用户（purchase_rank == 1）
    rank1 = df[df["purchase_rank"] == 1].copy()
    if sel_first:
        rank1 = rank1[rank1[first_col].isin(sel_first)]

    total_first = len(rank1)
    if total_first == 0:
        st.info("没有符合条件的首次购买记录")
        return

    # 找这些用户的 rank1→rank2 转换
    p = pairs[
        (pairs["user_id"].isin(rank1["user_id"])) &
        (pairs["from_rank"] == 1)
    ].copy()

    if sel_first:
        p = p[p[from_col].isin(sel_first)]

    repurchased = p["user_id"].nunique()
    overall_rate = repurchased / total_first * 100

    c1, c2, c3 = st.columns(3)
    c1.metric("首次购买用户数", f"{total_first:,}")
    c2.metric("有复购用户数",   f"{repurchased:,}")
    c3.metric("复购率",         f"{overall_rate:.1f}%")

    if p.empty:
        st.info("该条件下没有复购数据")
        return

    # 下一次去了哪里
    next_dist = (
        p.groupby(to_col)
        .agg(复购次数=("user_id", "count"), 复购人数=("user_id", "nunique"))
        .reset_index()
        .sort_values("复购次数", ascending=False)
    )
    next_dist["复购率(%)"] = (next_dist["复购人数"] / total_first * 100).round(2)

    fig = px.bar(
        next_dist,
        x=to_col, y="复购率(%)",
        color="复购次数",
        text="复购率(%)",
        color_continuous_scale="Blues",
        labels={to_col: "复购去向", "复购率(%)": "复购率 (%)"},
        height=400,
    )
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig.update_layout(coloraxis_showscale=True)
    st.plotly_chart(fig, use_container_width=True)

    # 平均复购间隔
    st.markdown("**复购间隔分布**")
    fig2 = px.histogram(
        p, x="days_between",
        nbins=30,
        labels={"days_between": "间隔天数", "count": "次数"},
        color_discrete_sequence=["#4ECDC4"],
        height=300,
    )
    fig2.update_layout(bargap=0.05)
    st.plotly_chart(fig2, use_container_width=True)

    with st.expander("查看明细数据"):
        st.dataframe(
            next_dist.rename(columns={to_col: "复购去向"}),
            use_container_width=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Tab 5：渠道流转 Sankey
# ═══════════════════════════════════════════════════════════════════════════════

def tab_channel_flow(df: pd.DataFrame, pairs: pd.DataFrame):
    st.subheader("渠道流转分析")
    st.caption("展示用户在不同直播间/渠道之间的购买顺序流转情况。")

    user_ids = set(df["user_id"].unique())
    p = pairs[pairs["user_id"].isin(user_ids)].copy()

    c1, c2 = st.columns(2)
    max_rank = c1.slider("展示到第几次购买", 2, 6, 4, key="flow_rank")
    min_count = c2.slider("最少流转次数（去除噪音）", 1, 100, 3, key="flow_min")

    p = p[p["from_rank"] <= max_rank - 1]

    p["source"] = "第" + p["from_rank"].astype(str) + "次\n" + p["from_influencer"]
    p["target"] = "第" + p["to_rank"].astype(str).str.replace(".0", "", regex=False) + "次\n" + p["to_influencer"]

    flow = p.groupby(["source", "target"]).size().reset_index(name="count")
    flow = flow[flow["count"] >= min_count]

    if flow.empty:
        st.info('没有足够的流转数据，请降低"最少流转次数"')
        return

    all_nodes = list(dict.fromkeys(flow["source"].tolist() + flow["target"].tolist()))
    node_idx  = {n: i for i, n in enumerate(all_nodes)}

    palette = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7", "#DDA0DD"]
    node_colors = []
    for n in all_nodes:
        try:
            rank = int(n.split("次")[0].replace("第", "")) - 1
        except Exception:
            rank = 0
        node_colors.append(palette[min(rank, len(palette) - 1)])

    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(
            pad=20, thickness=22,
            line=dict(color="black", width=0.5),
            label=all_nodes,
            color=node_colors,
        ),
        link=dict(
            source=[node_idx[s] for s in flow["source"]],
            target=[node_idx[t] for t in flow["target"]],
            value=flow["count"].tolist(),
            hovertemplate="%{source.label} → %{target.label}<br>流转 %{value} 次<extra></extra>",
        ),
    ))
    fig.update_layout(height=580, title_text="购买顺序 × 渠道流转图")
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("查看流转明细表"):
        st.dataframe(
            flow.rename(columns={"source": "来源", "target": "去向", "count": "次数"})
                .sort_values("次数", ascending=False),
            use_container_width=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    st.title("📊 直播间销售数据分析")

    # 加载数据
    try:
        orders = load_orders()
        pairs  = load_pairs()
        meta   = load_meta()
    except FileNotFoundError:
        st.error(
            "❌ 数据文件不存在！\n\n"
            "请先将 Excel 源表放入 `data/raw/` 目录，然后运行：\n"
            "```\npython preprocess.py\n```"
        )
        st.stop()

    # 侧边栏 & 筛选
    f = render_sidebar(meta)
    df = apply_filters(orders, f)

    if df.empty:
        st.warning("⚠️ 没有符合筛选条件的数据，请调整筛选条件")
        st.stop()

    # KPI
    render_kpi(df)
    st.divider()

    # 过滤购买对（基于 from_date 和 from_influencer 与全局筛选对齐）
    pairs_filtered = filter_pairs(pairs, f)

    # 五个功能 Tab
    t1, t2, t3, t4, t5 = st.tabs([
        "📈 新老客趋势",
        "📦 货品分析",
        "⏱ 复购周期",
        "🔁 复购率",
        "🔄 渠道流转",
    ])

    with t1:
        tab_trend(df)
    with t2:
        tab_product(df)
    with t3:
        tab_repurchase_cycle(df, pairs_filtered)
    with t4:
        tab_repurchase_rate(df, pairs_filtered)
    with t5:
        tab_channel_flow(df, pairs_filtered)


if __name__ == "__main__":
    main()
