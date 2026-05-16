# ============================================================
# 字段配置 — 如果 Excel 列名有变化，只需修改这里
# ============================================================

COLUMN_MAP = {
    "order_id":          "主订单编号",
    "user_id":           "用户id",
    "sub_order_id":      "子订单编号",
    "product_name":      "选购商品",
    "product_id":        "商品ID",
    "spec":              "商品规格",
    "sku":               "货号",           # 品类筛选维度
    "merchant_code":     "商家编码",
    "quantity":          "商品数量",
    "item_amount":       "商品金额",
    "order_submit_time": "订单提交时间",
    "pay_month":         "支付月份",
    "pay_time":          "支付时间",       # 主要时间字段
    "pay_complete":      "支付完成时间",
    "order_status":      "订单状态",
    "after_sale_status": "售后状态",
    "payable_amount":    "订单应付金额",
    "influencer_id":     "达人ID",
    "influencer_name":   "达人昵称",       # 直播间/渠道维度
}

# ── 老客判定规则 ──────────────────────────────────────────────────────────────
# 历史有过 >= OLD_CUSTOMER_MIN_AMOUNT 元、订单状态=TRANSACTION_SUCCESS_STATUS
# 且时间早于当前订单至少 OLD_CUSTOMER_MIN_DAYS 天，则当前订单标记为老客
OLD_CUSTOMER_MIN_AMOUNT    = 550        # 元
OLD_CUSTOMER_MIN_DAYS      = 1          # 天
TRANSACTION_SUCCESS_STATUS = "已完成"   # 判定为"有效历史成交"的订单状态值

# ── 金额字段选择 ──────────────────────────────────────────────────────────────
# "payable_amount"（订单应付金额，实付）或 "item_amount"（商品金额，原价）
AMOUNT_FIELD = "payable_amount"

# ── 数据目录 ──────────────────────────────────────────────────────────────────
RAW_DATA_DIR       = "data/raw"
PROCESSED_DATA_DIR = "data/processed"

# ── Sankey / 流转图 ────────────────────────────────────────────────────────────
SANKEY_MIN_COUNT = 3   # 低于此次数的路径不显示
MAX_PURCHASE_RANK = 6  # 最多展示第几次购买
