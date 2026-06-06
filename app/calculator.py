"""
原価計算ロジック

目標原価率:
  高粗利  (premium)  : 原価25% → 粗利75%
  標準粗利 (standard) : 原価35% → 粗利65%
  カスタム (custom)   : ユーザー指定粗利率

一頭買い前提:
  高級部位は原価率を下げて高値設定し、端肉で全体バランスを取る。
  このツールでは「部位1点ずつ」の計算を行い、全体収支は別途管理。
"""

COST_RATE = {
    "premium": 0.25,
    "standard": 0.35,
}

TIER_LABEL = {
    "premium": "高粗利 (粗利75%)",
    "standard": "標準粗利 (粗利65%)",
}

# 単位変換マップ (from_unit, to_unit) -> 倍率
_UNIT_FACTORS = {
    ("kg", "g"):  1000,
    ("g",  "kg"): 0.001,
    ("L",  "ml"): 1000,
    ("ml", "L"):  0.001,
}


def convert_to_price_unit(amount: float, from_unit: str, to_unit: str) -> float:
    """使用量の単位を単価の単位に変換して返す。
    例: convert_to_price_unit(10, 'g', 'kg') -> 0.01
    """
    if from_unit == to_unit:
        return amount
    factor = _UNIT_FACTORS.get((from_unit, to_unit))
    if factor is not None:
        return amount * factor
    return amount


def get_cost_rate(customer_tier: str, custom_gross_margin: float = None) -> float:
    """customer_tier から原価率を返す。custom の場合は custom_gross_margin (%) から算出。"""
    if customer_tier == "custom" and custom_gross_margin is not None:
        gm = max(1.0, min(99.0, float(custom_gross_margin)))  # 1〜99%に強制クランプ
        return 1.0 - (gm / 100.0)
    return COST_RATE.get(customer_tier, 0.35)


def get_tier_label(customer_tier: str, gross_margin: float = None) -> str:
    """表示用ラベルを返す。"""
    if customer_tier == "custom":
        gm = round(gross_margin, 1) if gross_margin is not None else "?"
        return f"カスタム粗利 ({gm}%)"
    return TIER_LABEL.get(customer_tier, customer_tier)


def calculate(
    raw_weight: float,
    raw_price: float,
    finished_weight: float,
    customer_tier: str,
    custom_gross_margin: float = None,
) -> dict:
    cost_rate = get_cost_rate(customer_tier, custom_gross_margin)

    yield_rate = (finished_weight / raw_weight) * 100
    cost_per_kg = raw_price / finished_weight
    recommended_price = cost_per_kg / cost_rate
    gross_margin = (1 - cost_rate) * 100

    return {
        "yield_rate": round(yield_rate, 1),
        "cost_per_kg": round(cost_per_kg),
        "recommended_price": round(recommended_price, -1),
        "gross_margin": round(gross_margin, 1),
    }
