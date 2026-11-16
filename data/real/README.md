# Real data for Field Shift

Put the five real tables in this folder. They use the **same file names and columns** as
`data/synthetic/`. The app switches from the synthetic sample data to these files **only
when all five are present and valid** (all or nothing). It picks up new files on the next
click; no restart is needed.

```bash
source .venv/bin/activate
python real_data.py check            # what's ready, what's missing, and why
python real_data.py fetch-weather    # download NASA POWER 1981-2024 into this folder
python real_data.py templates        # (re)create example files in data/real/templates/
```

**Switch override:** set `FIELD_SHIFT_DATA=synthetic` to force the sample data (e.g. for a demo),
or `FIELD_SHIFT_DATA=real` to insist on real data (the app then shows an error listing what's
missing instead of falling back). `FIELD_SHIFT_DATA_DIR=/some/folder` reads a different folder.

---

## 1. `weather_daily.csv`: daily weather at the farm, 1981-01-01 to 2024-12-31

One row per day, every day of every year. `fetch-weather` makes this file for you.

| Column | Units | Notes |
|---|---|---|
| `date` | YYYY-MM-DD | or give `year` and `doy` (day of year, 1–366) instead |
| `PRECTOTCORR` | mm/day | rain (bias-corrected) |
| `T2M_MAX`, `T2M_MIN` | °C | daily max / min air temperature at 2 m |
| `RH2M` | % | mean relative humidity at 2 m (optional, for Penman–Monteith ET0) |
| `WS2M` | m/s | mean wind speed at 2 m (optional, for Penman–Monteith ET0) |
| `ALLSKY_SFC_SW_DWN` | MJ/m²/day | solar radiation (optional, for Penman–Monteith ET0) |
| `ET0` | mm/day | reference evapotranspiration. If missing, it's computed: FAO-56 Penman–Monteith when RH2M, WS2M and ALLSKY_SFC_SW_DWN are there, else Hargreaves from temperature |

**Source:** [NASA POWER](https://power.larc.nasa.gov/) daily point API, community AG (no key).
`-999` is POWER's "missing" value: `fetch-weather` fills gaps of up to a week; the validator
rejects any left.

**Also accepted:** the data team's names `precip_mm`, `t2m_max_c`, `t2m_min_c`, `rh2m`, `ws2m`,
`rs_mj_m2`, `eto_mm` (renamed on load).

**Two checks that catch common pipeline mistakes:**
- **Placeholders:** 30+ identical days in a row in solar radiation, humidity or wind are
  rejected. POWER has **no daily solar radiation before 1984** at this point; `fetch-weather`
  estimates 1981–1983 from the daily temperature range (FAO-56 eq. 50) and flags those days
  `rs_estimated`. Don't fill them with a constant.
- **ET0 plausibility:** if you supply `ET0`, its average must be within 85–115% of FAO-56
  Penman–Monteith computed from the file's own columns (central Illinois July ≈ 4.5 mm/day).
  Simplest: leave `ET0` out and let the app compute it.

## 2. `crops.csv`: one row per crop (corn, soybeans, winter_wheat, sorghum)

| Column | Units | Suggested source |
|---|---|---|
| `crop` | name | exactly: corn, soybeans, winter_wheat, sorghum |
| `unit` | text | e.g. bu (informational) |
| `price_usd` | $ per unit | USDA NASS QuickStats, *price received*, Illinois, recent 3–5 year average |
| `base_yield` | units/acre | NASS QuickStats county yield (Champaign Co., IL). **Use a recent average (e.g. 2019–2024), not the 1981–2024 mean**: yields have trended up ~2 bu/acre/yr for corn, and the model replays old weather with today's crops |
| `cost_usd_per_acre` | $/acre | farmdoc (Univ. of Illinois) crop budgets: all direct + power costs, **including full nitrogen** (the rotation credit is subtracted separately) |
| `n_rate_lb` | lb N/acre | farmdoc / Illinois MRTN (informational) |
| `ky` | – | FAO-33 yield response factor (maize 1.25, soybean 0.85, sorghum 0.9, winter wheat 1.0) |
| `kc_ini`, `kc_mid`, `kc_end` | – | FAO-56 Table 12 crop coefficients |
| `len_ini`, `len_dev`, `len_mid`, `len_late` | days | FAO-56 Table 11 stage lengths (mid-latitude) |
| `plant_doy` | day of year | Illinois planting dates (NASS Crop Progress). Winter wheat: spring regrowth date. The season must fit in one calendar year |
| `root_depth_m` | m | FAO-56 Table 22 |
| `depletion_p` | 0–1 | FAO-56 Table 22 (fraction of available water before stress) |
| `soil_points` | points/yr | the team's own soil-health score (labelled heuristic) |
| `family`, `c_factor` | – | informational (crop family; RUSLE cover factor for a later erosion feature) |

## 3. `rotation_effects.csv`: previous crop → crop

| Column | Units | Notes |
|---|---|---|
| `prev_crop`, `crop` | names | from the four crops above |
| `yield_mult` | × | yield multiplier, 1.0 = no effect (e.g. corn after soybean ≈ 1.05–1.15 in Midwest rotation studies) |
| `n_credit_lb` | lb N/acre | nitrogen credit (e.g. soybean → corn ≈ 30–50) |

Pairs not listed count as no effect. **Source:** published rotation experiments (e.g. Illinois
Morrow Plots, Iowa/Minnesota long-term rotation trials); cite each row.

## 4. `soils.csv`: soil name → water the soil holds

| Column | Units | Notes |
|---|---|---|
| `soil` | name | must match the soil names in the app's **Your fields** table (case doesn't matter) |
| `awc_mm_per_m` | mm per m of soil | plant-available water capacity |

Include a row named **`default`** (used for any soil name not listed). **Source:** USDA
[Web Soil Survey](https://websoilsurvey.nrcs.usda.gov/) / SSURGO: the map units under each
field, `awc_r` (cm/cm × 1000 = mm/m), weighted over the root zone.

## 5. `site.csv`: one row of farm-wide settings

| Column | Units | Suggested source |
|---|---|---|
| `lat`, `lon` | degrees | the farm (used for ET0) |
| `elevation_m` | m | optional; improves Penman–Monteith ET0 (NASA POWER reports it) |
| `n_price_usd_per_lb` | $/lb N | USDA ERS fertilizer prices (anhydrous ammonia ÷ 0.82) |
| `rye_cost_usd_per_acre` | $/acre | cereal-rye seed + drilling + termination (farmdoc / cover-crop budgets) |
| `rye_soil_points` | points | the team's soil-health score for one rye cover |
| `rye_spring_draw_mm` | mm | spring soil water a rye cover uses before the next crop (cover-crop studies) |
| `irrigation_capacity_mm_per_day` | mm/day | the farm's pivot capacity |
| `irrigation_cost_usd_per_acre_in` | $/acre-inch | pumping energy + wear |
| `season_start_doy`, `season_end_doy` | day of year | the growing-season rain window (May 1 = 121, Sep 30 = 273) |
