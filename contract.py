"""Shared interface contract for Field Shift.

Change this file only with the whole team (Tebit, Robert, Claude-Thomas).
Everyone imports names from here so a typo fails loudly.
"""

# Sample farm used until Tebit supplies real fields from Web Soil Survey.
# Each field may also carry "irrigated": True/False (missing = rain-fed).
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

# One fixed color per crop, used in every chart. Soft tones, checked so that
# all four stay distinguishable for colour-blind readers.
CROP_COLORS = {
    "corn": "#F8E68E",
    "soybeans": "#72BFB0",
    "winter_wheat": "#F0A972",
    "sorghum": "#C77882",
}

# Display only: how each crop is shown to the user. Code and data files keep
# using the plain keys above ("winter_wheat"), never these labels.
CROP_LABELS = {
    "corn": "Corn",
    "soybeans": "Soybeans",
    "winter_wheat": "Winter wheat",
    "sorghum": "Sorghum",
}
CROP_ICONS = {
    "corn": "\U0001F33D",          # ear of corn
    "soybeans": "\U0001F331",      # seedling
    "winter_wheat": "\U0001F33E",  # sheaf
    "sorghum": "\U0001F33F",       # herb
}

# DEPRECATED (kept so older code still runs): slider weights. The optimizer now takes one
# explicit goal plus explicit limits instead; see GOALS and DEFAULT_LIMITS below.
WEIGHTS = {"profit": 5, "water": 5, "soil": 5}

# The farmer picks ONE goal. Everything else becomes a limit (epsilon-constraint method).
GOALS = {
    "max_profit": "Most profit",
    "min_water": "Least water",
    "max_worst_profit": "Best bad-year profit",
    "max_soil": "Healthiest soil",
}
GOAL_HELP = {
    "max_profit": "Highest average net profit over the weather years you plan for.",
    "min_water": "Least water the crops need beyond rain: shortfall on rain-fed fields "
                 "plus irrigation on irrigated ones.",
    "max_worst_profit": "Best average profit across your worst seasons (the worst 10% of "
                        "1981-2024 by default), so a drought hurts less.",
    "max_soil": "Most soil-health points: legumes, small grains, residue and rye cover.",
}

# Limits are relative to the farmer's own rotation: 0.95 means "at least 95% of yours"
# for an "_min" limit and "at most 95% of yours" for a "_max" limit. None or missing = off.
LIMIT_LABELS = {
    "profit_min": "Profit at least",
    "worst_profit_min": "Bad-year profit at least",
    "shortfall_max": "Water shortfall at most",
    "irrigation_max": "Irrigation at most, every year",
    "soil_min": "Soil health at least",
    "production_min": "Harvest of each crop you grow at least",
}
DEFAULT_LIMITS = {
    "max_profit": {"shortfall_max": 1.0, "irrigation_max": 1.0},
    "min_water": {"profit_min": 0.95},
    "max_worst_profit": {"profit_min": 0.95},
    "max_soil": {"profit_min": 0.95, "shortfall_max": 1.0},
}
# Each goal's own measure: a limit on it would fight the goal, so it is not offered.
GOAL_OWN_LIMITS = {
    "max_profit": ["profit_min"],
    "min_water": ["shortfall_max", "irrigation_max"],
    "max_worst_profit": ["worst_profit_min"],
    "max_soil": ["soil_min"],
}
WORST_SHARE = 0.10   # "bad years" = the worst 10% of seasons, unless constraints say otherwise

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
