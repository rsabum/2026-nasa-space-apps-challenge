# Synthetic data (format example)

Made by `python synthetic_data.py`. Every number is SYNTHETIC: plausible for central
Illinois, but made up. Real files should use the same file names and columns.

| File | One row per | Columns |
|---|---|---|
| weather_daily.csv | day, 1981-2024 | date, year, doy, PRECTOTCORR (rain, mm), T2M_MAX, T2M_MIN (C), ET0 (mm, Hargreaves) |
| crops.csv | crop | price_usd per unit, base_yield (unit/acre), cost_usd_per_acre (incl. full N), n_rate_lb, ky (FAO-33), kc_ini/kc_mid/kc_end and len_* days (FAO-56), plant_doy, root_depth_m, depletion_p, soil_points, family, c_factor |
| rotation_effects.csv | previous -> current crop | yield_mult, n_credit_lb (missing pairs = 1.0 and 0) |
| soils.csv | soil texture | awc_mm_per_m (plant-available water per metre of soil) |
| site.csv | the farm (1 row) | lat, lon, n_price_usd_per_lb, rye_*, irrigation_*, season window |
