"""Synthetic stand-in for the team's data (owner: Robert, until Tebit's CSVs arrive).

Builds the same tables the real data will provide, always the same for a given seed:

    weather           daily 1981-2024 at the demo farm, NASA POWER column names
    crops             one row per crop: price, yield, cost, water use (FAO-56), drought response (FAO-33)
    rotation_effects  previous crop -> current crop: yield multiplier and nitrogen credit
    soils             soil texture -> how much water the soil holds
    site              one row of farm-wide settings: N price, rye cover, irrigation

Every number here is SYNTHETIC: plausible for central Illinois, but made up. The weather
is generated, not downloaded. Run `python synthetic_data.py` to also save the tables as
CSVs in data/synthetic/, which shows the format the real files should follow.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from contract import CROPS, FARM, FIRST_YEAR, LAST_YEAR

# Real Midwest drought years, made dry and hot on purpose so the demo looks like history.
DROUGHTS = {2012: 0.62, 1988: 0.72}      # year -> scale on growing-season rain
HEAT = {2012: 2.5, 1988: 2.0}            # year -> extra degrees C on every day

CROPS_TABLE = [
    # Prices and yields: rough recent central-Illinois values. Kc and stage lengths:
    # FAO-56 Tables 11-12 (mid-latitude). Ky: FAO-33. All synthetic until Tebit's crop table.
    dict(crop="corn", unit="bu", price_usd=4.40, base_yield=200, cost_usd_per_acre=620,
         n_rate_lb=170, ky=1.25, kc_ini=0.30, kc_mid=1.20, kc_end=0.35,
         len_ini=30, len_dev=40, len_mid=50, len_late=30, plant_doy=121,
         root_depth_m=1.2, depletion_p=0.55, soil_points=0.5, family="grass", c_factor=0.20),
    dict(crop="soybeans", unit="bu", price_usd=11.50, base_yield=62, cost_usd_per_acre=390,
         n_rate_lb=0, ky=0.85, kc_ini=0.40, kc_mid=1.15, kc_end=0.50,
         len_ini=20, len_dev=30, len_mid=60, len_late=25, plant_doy=135,
         root_depth_m=1.0, depletion_p=0.50, soil_points=1.0, family="legume", c_factor=0.30),
    # Winter wheat is sown in the fall; we simulate its spring regrowth to harvest (late March - July).
    dict(crop="winter_wheat", unit="bu", price_usd=6.20, base_yield=82, cost_usd_per_acre=360,
         n_rate_lb=110, ky=1.00, kc_ini=0.70, kc_mid=1.15, kc_end=0.25,
         len_ini=20, len_dev=30, len_mid=40, len_late=25, plant_doy=79,
         root_depth_m=1.4, depletion_p=0.55, soil_points=1.5, family="small_grain", c_factor=0.10),
    dict(crop="sorghum", unit="bu", price_usd=4.10, base_yield=135, cost_usd_per_acre=400,
         n_rate_lb=120, ky=0.90, kc_ini=0.30, kc_mid=1.00, kc_end=0.55,
         len_ini=20, len_dev=35, len_mid=40, len_late=30, plant_doy=140,
         root_depth_m=1.3, depletion_p=0.55, soil_points=0.8, family="grass", c_factor=0.22),
]

ROTATION_EFFECTS = [
    # prev, cur, yield multiplier rho, nitrogen credit nu (lb N/acre). Pairs not listed: 1.0 and 0.
    ("soybeans", "corn", 1.10, 40), ("soybeans", "sorghum", 1.08, 30),
    ("soybeans", "winter_wheat", 1.05, 20), ("winter_wheat", "corn", 1.06, 10),
    ("winter_wheat", "soybeans", 1.04, 0), ("winter_wheat", "sorghum", 1.04, 10),
    ("corn", "corn", 0.88, 0), ("sorghum", "sorghum", 0.90, 0),
    ("soybeans", "soybeans", 0.92, 0), ("winter_wheat", "winter_wheat", 0.85, 0),
    ("corn", "sorghum", 0.95, 0), ("sorghum", "corn", 0.95, 0),
    ("corn", "winter_wheat", 0.97, 0),     # late harvest, head-scab risk after corn
]

SOILS = [
    # texture, available water capacity (mm of water per m of soil). "default" covers unknown names.
    ("silt loam", 200), ("silty clay loam", 190), ("loam", 170), ("clay loam", 160),
    ("sandy loam", 120), ("loamy sand", 90), ("sand", 70), ("default", 160),
]

SITE = dict(
    lat=FARM["lat"], lon=FARM["lon"],
    n_price_usd_per_lb=0.60,                # what a lb of nitrogen credit saves
    rye_cost_usd_per_acre=40.0,             # seed + drilling + termination
    rye_soil_points=1.0,                    # soil-health points per rye cover
    rye_spring_draw_mm=35.0,                # spring soil water the rye uses before the next crop
    irrigation_capacity_mm_per_day=6.0,     # what a centre pivot can apply in a day
    irrigation_cost_usd_per_acre_in=9.0,    # pumping energy and wear
    season_start_doy=121, season_end_doy=273,   # growing-season rain window: May 1 - Sep 30
)


def _extraterrestrial_radiation(lat_deg, doy):
    """FAO-56 eq. 21: radiation at the top of the atmosphere, in mm/day of evaporation."""
    phi = np.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    delta = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1, 1))
    ra_mj = (24 * 60 / np.pi) * 0.0820 * dr * (
        ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))
    return 0.408 * ra_mj


def make_weather(seed=2026, lat=FARM["lat"], first=FIRST_YEAR, last=LAST_YEAR):
    """Daily synthetic weather: rain from a wet/dry Markov chain with gamma amounts,
    temperature from a seasonal curve plus day-to-day noise, ET0 by Hargreaves."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(f"{first}-01-01", f"{last}-12-31", freq="D")
    year, doy = dates.year.to_numpy(), dates.day_of_year.to_numpy()

    # Year-level wetness and heat, so some seasons are wet and some dry.
    years = np.arange(first, last + 1)
    wet = dict(zip(years, rng.lognormal(0, 0.22, len(years))))
    warm = dict(zip(years, rng.normal(0, 0.6, len(years))))
    wet.update(DROUGHTS)
    for y, extra in HEAT.items():
        warm[y] = warm.get(y, 0) + extra
    wet_y = np.array([wet[y] for y in year])
    warm_y = np.array([warm[y] for y in year])

    # Rain: average mm/day peaks in June (about 3.3 mm/day May-Sep, about 1,000 mm a year).
    mean_mm = 2.7 + 0.9 * np.sin(2 * np.pi * (doy - 100) / 365)
    p_wet, p_stay = 0.32, 0.45                              # share of wet days; P(wet | wet yesterday)
    p_start = p_wet * (1 - p_stay) / (1 - p_wet)            # P(wet | dry yesterday)
    in_season = (doy >= SITE["season_start_doy"]) & (doy <= SITE["season_end_doy"])
    is_drought = np.isin(year, list(DROUGHTS)) & in_season
    rain = np.zeros(len(dates))
    wet_day = False
    for i in range(len(dates)):
        p = p_stay if wet_day else p_start * (0.7 if is_drought[i] else 1.0)
        wet_day = rng.random() < p
        if wet_day:
            rain[i] = rng.gamma(0.8, mean_mm[i] * wet_y[i] / p_wet / 0.8)

    # Make sure the drought years really are the driest growing seasons on record.
    season_rain = pd.Series(rain[in_season]).groupby(year[in_season]).sum()
    others = season_rain.drop(list(DROUGHTS))
    for y, rank in ((2012, 0.85), (1988, 0.95)):
        target = others.min() * rank
        if season_rain[y] > target:
            rain[(year == y) & in_season] *= target / season_rain[y]

    # Temperature: mean 10.5 C, coldest in mid-January, warmest in late July, AR(1) noise.
    noise = np.zeros(len(dates))
    for i in range(1, len(dates)):
        noise[i] = 0.7 * noise[i - 1] + rng.normal(0, 2.1)
    t_mean = 10.5 + 13.5 * np.sin(2 * np.pi * (doy - 109) / 365) + noise + warm_y
    spread = 11 + np.where(rain > 1, -3.0, 1.0) + rng.normal(0, 1.2, len(dates))
    t_max, t_min = t_mean + spread / 2, t_mean - spread / 2

    ra = _extraterrestrial_radiation(lat, doy)
    et0 = np.clip(0.0023 * ra * (t_mean + 17.8) * np.sqrt(np.clip(t_max - t_min, 0, None)), 0, None)

    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "year": year, "doy": doy,
        "PRECTOTCORR": rain.round(2), "T2M_MAX": t_max.round(2), "T2M_MIN": t_min.round(2),
        "ET0": et0.round(3),
    })


def load_data(seed=2026):
    """All tables, in the shape model.py expects (Tebit's loader should return the same)."""
    crops = pd.DataFrame(CROPS_TABLE)
    assert list(crops["crop"]) == CROPS, "crop table must list the contract's crops in order"
    return {
        "weather": make_weather(seed),
        "crops": crops,
        "rotation_effects": pd.DataFrame(ROTATION_EFFECTS,
                                         columns=["prev_crop", "crop", "yield_mult", "n_credit_lb"]),
        "soils": pd.DataFrame(SOILS, columns=["soil", "awc_mm_per_m"]),
        "site": pd.DataFrame([SITE]),
        "source": "synthetic",
    }


README = """# Synthetic data (format example)

Made by `python synthetic_data.py`. Every number is SYNTHETIC: plausible for central
Illinois, but made up. Real files should use the same file names and columns.

| File | One row per | Columns |
|---|---|---|
| weather_daily.csv | day, 1981-2024 | date, year, doy, PRECTOTCORR (rain, mm), T2M_MAX, T2M_MIN (C), ET0 (mm, Hargreaves) |
| crops.csv | crop | price_usd per unit, base_yield (unit/acre), cost_usd_per_acre (incl. full N), n_rate_lb, ky (FAO-33), kc_ini/kc_mid/kc_end and len_* days (FAO-56), plant_doy, root_depth_m, depletion_p, soil_points, family, c_factor |
| rotation_effects.csv | previous -> current crop | yield_mult, n_credit_lb (missing pairs = 1.0 and 0) |
| soils.csv | soil texture | awc_mm_per_m (plant-available water per metre of soil) |
| site.csv | the farm (1 row) | lat, lon, n_price_usd_per_lb, rye_*, irrigation_*, season window |
"""


if __name__ == "__main__":
    out = Path(__file__).parent / "data" / "synthetic"
    out.mkdir(parents=True, exist_ok=True)
    d = load_data()
    names = {"weather": "weather_daily.csv", "crops": "crops.csv",
             "rotation_effects": "rotation_effects.csv", "soils": "soils.csv", "site": "site.csv"}
    for key, name in names.items():
        d[key].to_csv(out / name, index=False)
    (out / "README.md").write_text(README)
    w = d["weather"]
    season = w[(w["doy"] >= SITE["season_start_doy"]) & (w["doy"] <= SITE["season_end_doy"])]
    by_year = season.groupby("year")["PRECTOTCORR"].sum()
    print(f"Wrote {len(names)} tables to {out}")
    print(f"Growing-season rain (May-Sep): mean {by_year.mean():.0f} mm, "
          f"driest {by_year.idxmin()} ({by_year.min():.0f} mm), wettest {by_year.idxmax()} ({by_year.max():.0f} mm)")
    print(f"Annual rain: mean {w.groupby('year')['PRECTOTCORR'].sum().mean():.0f} mm; "
          f"July ET0: mean {w[(w['doy'] >= 182) & (w['doy'] <= 212)]['ET0'].mean():.1f} mm/day")
