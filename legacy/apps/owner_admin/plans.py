CARE_FROW_PLAN_CHOICES = [
    ("standard", "スタンダード"),
    ("pro", "プロ"),
    ("campaign_standard", "先行導入キャンペーン"),
]


CARE_FROW_PLAN_DEFINITIONS = {
    "standard": {
        "key": "standard",
        "display_name": "スタンダード",
        "monthly_base_fee": 29800,
        "initial_fee": 30000,
        "included_minutes": 3000,
        "overage_unit_minutes": 1000,
        "overage_unit_price": 5000,
        "hard_limit_minutes": 3000,
        "description": "月3000分まで利用できます。1日5名程度のAI録音に対応します。",
        "campaign": False,
    },
    "pro": {
        "key": "pro",
        "display_name": "プロ",
        "monthly_base_fee": 49800,
        "initial_fee": 50000,
        "included_minutes": 7000,
        "overage_unit_minutes": 1000,
        "overage_unit_price": 5000,
        "hard_limit_minutes": 7000,
        "description": "月7000分まで利用できます。複数スタッフ・高頻度運用に対応します。",
        "campaign": False,
    },
    "campaign_standard": {
        "key": "campaign_standard",
        "display_name": "先行導入キャンペーン",
        "monthly_base_fee": 19800,
        "initial_fee": 30000,
        "included_minutes": 3000,
        "overage_unit_minutes": 1000,
        "overage_unit_price": 5000,
        "hard_limit_minutes": 3000,
        "description": "3か月間19,800円、4か月目以降29,800円の先行導入価格です。",
        "campaign": True,
    },
}


def normalize_plan_key(plan_name):
    value = str(plan_name or "").strip().lower()
    if value in CARE_FROW_PLAN_DEFINITIONS:
        return value
    if "campaign" in value or "先行" in value or "キャンペーン" in value:
        return "campaign_standard"
    if "pro" in value or "プロ" in value:
        return "pro"
    if "standard" in value or "スタンダード" in value:
        return "standard"
    return ""


def plan_definition(plan_name, fallback=None):
    key = normalize_plan_key(plan_name)
    if key:
        return CARE_FROW_PLAN_DEFINITIONS[key]
    return fallback


def apply_plan_definition(ai_plan, plan_key):
    definition = CARE_FROW_PLAN_DEFINITIONS[plan_key]
    ai_plan.plan_name = plan_key
    ai_plan.monthly_base_fee = definition["monthly_base_fee"]
    ai_plan.included_minutes = definition["included_minutes"]
    ai_plan.overage_unit_minutes = definition["overage_unit_minutes"]
    ai_plan.overage_unit_price = definition["overage_unit_price"]
    ai_plan.hard_limit_minutes = definition["hard_limit_minutes"]
    ai_plan.warning_threshold_percent = 70
    ai_plan.danger_threshold_percent = 90
    ai_plan.allow_overage = True
    ai_plan.is_ai_enabled = True
    ai_plan.notes = definition["description"]
    return ai_plan
