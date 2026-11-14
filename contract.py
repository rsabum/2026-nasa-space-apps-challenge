"""Shared interface contract for Field Shift.

Change this file only with the whole team (Tebit, Robert, Claude-Thomas).
Everyone imports names from here so a typo fails loudly.
"""

# Sample farm used until Tebit supplies real fields from Web Soil Survey.
FARM = {
    "name": "Demo farm, central Illinois",
    "lat": 40.1,
    "lon": -88.2,
    "years": 4,
    "fields": [
        {"name": "North", "acres": 80, "soil": "silt loam", "last_crop": "corn"},
        {"name": "South", "acres": 60, "soil": "silty clay loam", "last_crop": "soybeans"},
        {"name": "East", "acres": 40, "soil": "loam", "last_crop": "corn"},
        {"name": "West", "acres": 20, "soil": "sandy loam", "last_crop": "soybeans"},
    ],
}

CROPS = ["corn", "soybeans", "winter_wheat", "sorghum"]

# One fixed color per crop, used in every chart.
CROP_COLORS = {
    "corn": "#E3B505",
    "soybeans": "#4E8E2F",
    "winter_wheat": "#C77D3A",
    "sorghum": "#9B2D20",
}

# Default priorities, each 0-10. Normalize in code with normalize_weights().
WEIGHTS = {"profit": 5, "water": 5, "soil": 5}

# Default constraints the farmer can change in the sidebar.
CONSTRAINTS = {
    "allowed_crops": list(CROPS),
    "no_repeat": True,           # no same crop two years running
    "min_legume_years": 1,       # soybean years per field over the plan
    "max_crop_share": 0.75,      # max share of acres in one crop in any year
}

SCENARIOS = ["average", "dry"]

FIRST_YEAR = 1981
LAST_YEAR = 2024

# Columns returned by evaluate() and solve(): one row per field per year.
PLAN_COLUMNS = [
    "field", "year", "crop", "acres",
    "water_need_mm", "water_shortfall_mm", "soil_score_change", "profit_usd",
]

# Keys of each option returned by solve_pareto().
PARETO_KEYS = ["total_profit_usd", "total_shortfall_acre_in", "soil_score_change", "plan"]

# Columns returned by backtest(): one row per historical year.
BACKTEST_COLUMNS = [
    "year", "growing_season_rain_mm",
    "total_profit_usd", "total_shortfall_acre_in", "soil_score_change",
]


def normalize_weights(weights):
    """Turn 0-10 slider values into weights that sum to 1."""
    total = sum(weights.values())
    if total == 0:
        return {k: 1 / len(weights) for k in weights}
    return {k: v / total for k, v in weights.items()}


def baseline_plan(farm):
    """The farmer's current corn-soybean rotation, as a plan dict {field: [crop per year]}."""
    plan = {}
    for f in farm["fields"]:
        crop = "soybeans" if f["last_crop"] == "corn" else "corn"
        seq = []
        for _ in range(farm["years"]):
            seq.append(crop)
            crop = "soybeans" if crop == "corn" else "corn"
        plan[f["name"]] = seq
    return plan
