"""
预处理脚本
----------
把 data/raw/ 下所有 .xlsx 文件处理成 data/processed/ 下的 Parquet 文件。

每次替换源表后重新运行：
    python preprocess.py
"""

import json
import sys
from pathlib import Path

import pandas as pd

from config import (
    AMOUNT_FIELD,
    COLUMN_MAP,
    MAX_PURCHASE_RANK,
    OLD_CUSTOMER_MIN_AMOUNT,
    OLD_CUSTOMER_MIN_DAYS,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
    SANKEY_MIN_COUNT,
    TRANSACTION_SUCCESS_STATUS,
)


# ── 1. 加载 ───────────────────────────────────────────────────────────────────

def load_all_excel(data_dir: str) -> pd.DataFrame:
    files = list(Path(data_dir).glob("*.xlsx"))
    if not files:
        print(f"[ERROR] 在 {data_dir} 目录下没有找到 .xlsx 文件")
        sys.exit(1)

    dfs = []
    for f in sorted(files):
        print(f"  读取 {f.name} ...")
        df = pd.read_excel(f, dtype=str)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)
    print(f"  合并后共 {len(combined):,} 行")
    return combined


# ── 2. 清洗 ───────────────────────────────────────────────────────────────────

def clean(df: pd.DataFrame) -> pd.DataFrame:
    # 重命名为标准英文字段
    reverse_map = {v: k for k, v in COLUMN_MAP.items()}
    df = df.rename(columns=reverse_map)

    # 保留需要的列（忽略不存在的列，兼容不同格式的源表）
    needed = [
        "user_id", "sku", "product_name", "influencer_name",
        "order_status", "after_sale_status",
        "quantity", "item_amount", "payable_amount",
        "pay_time", "order_submit_time",
    ]
    df = df[[c for c in needed if c in df.columns]].copy()

    # ── 时间字段：优先 pay_time，其次 order_submit_time ──
    for col in ("pay_time", "order_submit_time"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    if "pay_time" not in df.columns or df["pay_time"].isna().all():
        df["pay_time"] = df.get("order_submit_time", pd.NaT)

    # 去掉关键字段为空的行
    df = df.dropna(subset=["pay_time", "user_id"])
    df["user_id"] = df["user_id"].astype(str).str.strip()

    # ── 数值字段 ──
    for col in ("item_amount", "payable_amount", "quantity"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 统一 gmv 字段（优先用 AMOUNT_FIELD 配置的字段）
    if AMOUNT_FIELD in df.columns:
        df["gmv"] = df[AMOUNT_FIELD]
    elif "item_amount" in df.columns:
        df["gmv"] = df["item_amount"]
    else:
        df["gmv"] = 0.0

    # ── 文本字段归一化 ──
    for col in ("sku", "product_name", "order_status", "after_sale_status"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().replace({"nan": "未知", "": "未知"})
        else:
            df[col] = "未知"
    # 达人昵称单独处理：空值标记为"货架"
    if "influencer_name" in df.columns:
        df["influencer_name"] = (
            df["influencer_name"].astype(str).str.strip()
            .replace({"nan": "货架", "": "货架"})
        )
    else:
        df["influencer_name"] = "货架"

    # ── 时间衍生字段 ──
    df["order_date"] = df["pay_time"].dt.date
    df["order_ym"]   = df["pay_time"].dt.strftime("%Y-%m")

    # 去重（同一订单可能多行）— 以 user_id + pay_time + sku 为粒度去重
    before = len(df)
    df = df.drop_duplicates(subset=["user_id", "pay_time", "sku", "influencer_name"])
    after = len(df)
    if before != after:
        print(f"  去重移除 {before - after:,} 行重复记录")

    print(f"  清洗后剩余 {len(df):,} 行")
    return df


# ── 3. 计算新老客 ──────────────────────────────────────────────────────────────
#
# 老客定义：该用户在当前订单之前（至少 OLD_CUSTOMER_MIN_DAYS 天），
#           有过 ≥ OLD_CUSTOMER_MIN_AMOUNT 元 且 订单状态=TRANSACTION_SUCCESS_STATUS 的历史订单。
#
# 实现思路：
#   1. 找出所有"有效历史成交"订单（状态=交易成功 且 金额≥550）
#   2. 对每个用户，取有效成交中最早那笔的时间 → first_qualifying_time
#   3. 当前订单时间 ≥ first_qualifying_time + 1天 → 老客，否则新客
#
# 同时记录老客的"首次有效成交"信息，用于客户数据库视图。

def label_customer_type(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["user_id", "pay_time"]).reset_index(drop=True)

    # 找有效历史成交记录
    qualifying = df[
        (df["order_status"] == TRANSACTION_SUCCESS_STATUS) &
        (df["gmv"] >= OLD_CUSTOMER_MIN_AMOUNT)
    ].copy()

    if qualifying.empty:
        print("  [警告] 没有找到任何\"交易成功且金额>=550\"的订单，所有用户均标记为新客")
        df["customer_type"] = "新客"
        df["first_qualify_time"] = pd.NaT
        df["first_qualify_influencer"] = ""
        df["first_qualify_sku"] = ""
        df["first_qualify_gmv"] = 0.0
        return df

    # 每个用户最早有效成交
    first_q = (
        qualifying.sort_values("pay_time")
        .groupby("user_id")
        .first()[["pay_time", "influencer_name", "sku", "gmv"]]
        .rename(columns={
            "pay_time":        "first_qualify_time",
            "influencer_name": "first_qualify_influencer",
            "sku":             "first_qualify_sku",
            "gmv":             "first_qualify_gmv",
        })
        .reset_index()
    )

    df = df.merge(first_q, on="user_id", how="left")

    # 成为老客的门槛时间 = first_qualify_time + 1天
    threshold = df["first_qualify_time"] + pd.Timedelta(days=OLD_CUSTOMER_MIN_DAYS)
    is_old = df["first_qualify_time"].notna() & (df["pay_time"] >= threshold)

    df["customer_type"] = "新客"
    df.loc[is_old, "customer_type"] = "老客"

    n_new = (df["customer_type"] == "新客").sum()
    n_old = (df["customer_type"] == "老客").sum()
    print(f"  新客订单: {n_new:,}  |  老客订单: {n_old:,}")
    return df


# ── 4. 购买序号 ───────────────────────────────────────────────────────────────

def add_purchase_rank(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["user_id", "pay_time"])
    df["purchase_rank"] = df.groupby("user_id").cumcount() + 1
    return df


# ── 5. 购买对（用于复购周期/复购率/流转图） ────────────────────────────────────

def build_purchase_pairs(df: pd.DataFrame) -> pd.DataFrame:
    """
    为每个用户生成相邻两次购买的"对"，包含时间间隔。
    用于：复购周期热力图、复购率分析、渠道流转 Sankey。
    """
    df_s = df.sort_values(["user_id", "pay_time"]).copy()

    shift_cols = ["pay_time", "influencer_name", "sku", "product_name", "order_ym",
                  "purchase_rank", "order_date", "gmv", "order_status"]

    for col in shift_cols:
        if col in df_s.columns:
            df_s[f"next_{col}"] = df_s.groupby("user_id")[col].shift(-1)

    pairs = df_s.dropna(subset=["next_pay_time"]).copy()
    pairs["days_between"] = (
        pd.to_datetime(pairs["next_pay_time"]) - pd.to_datetime(pairs["pay_time"])
    ).dt.days

    # 只保留 days_between >= 0 的（极少数时间倒序情况）
    pairs = pairs[pairs["days_between"] >= 0]

    pairs = pairs.rename(columns={
        "order_ym":             "from_ym",
        "influencer_name":      "from_influencer",
        "sku":                  "from_sku",
        "product_name":         "from_product",
        "purchase_rank":        "from_rank",
        "order_date":           "from_date",
        "gmv":                  "from_gmv",
        "order_status":         "from_status",
        "next_order_ym":        "to_ym",
        "next_influencer_name": "to_influencer",
        "next_sku":             "to_sku",
        "next_product_name":    "to_product",
        "next_purchase_rank":   "to_rank",
        "next_order_date":      "to_date",
        "next_gmv":             "to_gmv",
        "next_order_status":    "to_status",
    })

    keep = [
        "user_id", "customer_type",
        "from_ym", "from_date", "from_influencer", "from_sku", "from_product",
        "from_rank", "from_gmv", "from_status",
        "to_ym",   "to_date",   "to_influencer",   "to_sku",   "to_product",
        "to_rank",  "to_gmv",   "to_status",
        "days_between",
    ]
    pairs = pairs[[c for c in keep if c in pairs.columns]]

    print(f"  购买对数量: {len(pairs):,}")
    return pairs


# ── 6. 保存 ───────────────────────────────────────────────────────────────────

def save_all(df: pd.DataFrame, pairs: pd.DataFrame, out_dir: str):
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    df.to_parquet(f"{out_dir}/orders.parquet", index=False)
    pairs.to_parquet(f"{out_dir}/purchase_pairs.parquet", index=False)

    after_sale = sorted(df["after_sale_status"].dropna().unique().tolist()) if "after_sale_status" in df.columns else []
    meta = {
        "skus":                sorted(df["sku"].dropna().unique().tolist()),
        "influencers":         sorted(df["influencer_name"].dropna().unique().tolist()),
        "order_statuses":      sorted(df["order_status"].dropna().unique().tolist()),
        "after_sale_statuses": after_sale,
        "date_min":            str(df["order_date"].min()),
        "date_max":            str(df["order_date"].max()),
        "gmv_max":             float(df["gmv"].max()),
        "total_rows":          len(df),
        "total_users":         df["user_id"].nunique(),
    }
    with open(f"{out_dir}/meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 处理完成！")
    print(f"   订单行数  : {meta['total_rows']:,}")
    print(f"   独立买家  : {meta['total_users']:,}")
    print(f"   时间范围  : {meta['date_min']} ~ {meta['date_max']}")
    print(f"   货号数量  : {len(meta['skus'])}")
    print(f"   达人数量  : {len(meta['influencers'])}")
    print(f"   输出目录  : {out_dir}/")


# ── 主流程 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("Step 1/5  加载 Excel ...")
    raw = load_all_excel(RAW_DATA_DIR)

    print("Step 2/5  清洗数据 ...")
    df = clean(raw)

    print("Step 3/5  标记新老客 ...")
    df = label_customer_type(df)

    print("Step 4/5  计算购买序号与购买对 ...")
    df = add_purchase_rank(df)
    pairs = build_purchase_pairs(df)

    print("Step 5/5  保存文件 ...")
    save_all(df, pairs, PROCESSED_DATA_DIR)
