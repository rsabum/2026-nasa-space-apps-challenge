"""Real data for Field Shift: where it goes, what it must contain, and how it's loaded.

The model needs five tables, the same ones synthetic_data.py makes (same file names and
columns). Put the real ones in data/real/ (or the folder in FIELD_SHIFT_DATA_DIR):

    weather_daily.csv     daily weather 1981-2024 at the farm (NASA POWER; see fetch-weather)
    crops.csv             one row per crop: price, yield, costs, water use, drought response
    rotation_effects.csv  previous crop -> crop: yield multiplier and nitrogen credit
    soils.csv             soil name -> water the soil holds (mm per m), with a "default" row
    site.csv              one row of farm-wide settings

All or nothing: the app switches to real data only when ALL FIVE are present and valid
(model.py decides; FIELD_SHIFT_DATA=synthetic forces the sample data, =real insists).
data/real/README.md lists each column, its units and a suggested source.

Commands (run inside the virtual environment):
    python real_data.py check                     what's ready, what's missing, and why
    python real_data.py fetch-weather [--lat --lon --out]   download NASA POWER 1981-2024
    python real_data.py templates [--out]         example files to fill in by hand
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

import synthetic_data
from contract import CROPS, FARM, FIRST_YEAR, LAST_YEAR
from synthetic_data import FILES, SITE, _extraterrestrial_radiation

HERE = Path(__file__).parent
REAL_DIR = HERE / "data" / "real"
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_PARAMS = ["PRECTOTCORR", "T2M_MAX", "T2M_MIN", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN"]
PM_INPUTS = ["T2M_MAX", "T2M_MIN", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN"]   # for Penman-Monteith
# Other names the data team uses for the same weather columns; accepted and renamed on load.
WEATHER_ALIASES = {"precip_mm": "PRECTOTCORR", "t2m_max_c": "T2M_MAX", "t2m_min_c": "T2M_MIN",
                   "rh2m": "RH2M", "ws2m": "WS2M", "rs_mj_m2": "ALLSKY_SFC_SW_DWN", "eto_mm": "ET0"}
FLAT_RUN_DAYS = 30            # this many identical days in a row = a placeholder, not a measurement
ET0_TOLERANCE = (0.85, 1.15)  # a supplied ET0 must average within this share of FAO-56 PM

# Columns the model reads, per table (weather is checked separately: see _check_weather).
REQUIRED = {
    "weather": ["PRECTOTCORR"],
    "crops": ["crop", "price_usd", "base_yield", "cost_usd_per_acre", "ky", "kc_ini", "kc_mid",
              "kc_end", "len_ini", "len_dev", "len_mid", "len_late", "plant_doy", "root_depth_m",
              "depletion_p", "soil_points"],
    "rotation_effects": ["prev_crop", "crop", "yield_mult", "n_credit_lb"],
    "soils": ["soil", "awc_mm_per_m"],
    "site": list(SITE),
}


class RealDataError(Exception):
    """The real data isn't complete or valid; .problems = {table: [plain sentences]}."""

    def __init__(self, problems):
        self.problems = problems
        lines = [f"{t}: {p}" for t, ps in problems.items() for p in ps]
        super().__init__("Real data isn't ready: " + "; ".join(lines))


def real_dir():
    """The real-data folder: FIELD_SHIFT_DATA_DIR if set, else data/real/."""
    return Path(os.environ.get("FIELD_SHIFT_DATA_DIR") or REAL_DIR)


def signature(folder=None):
    """Which files exist and when they last changed: a cheap key for caching."""
    folder = Path(folder or real_dir())
    sig = []
    for name in FILES.values():
        path = folder / name
        st = path.stat() if path.exists() else None
        sig.append((name, st.st_mtime_ns if st else None, st.st_size if st else None))
    return (str(folder), tuple(sig))


# ---------------------------------------------------------------- reference evapotranspiration

def et0_hargreaves(tmax, tmin, doy, lat):
    """FAO-56 Hargreaves ET0 (mm/day) from daily max/min temperature only."""
    ra = _extraterrestrial_radiation(lat, doy)               # mm/day equivalent
    tmean = (tmax + tmin) / 2
    return np.clip(0.0023 * ra * (tmean + 17.8) * np.sqrt(np.clip(tmax - tmin, 0, None)), 0, None)


def et0_penman_monteith(tmax, tmin, rh, u2, rs, doy, lat, elevation_m=0.0):
    """FAO-56 Penman-Monteith ET0 (mm/day), eq. 6, from NASA POWER daily values:
    temperature (C), mean relative humidity (%), wind at 2 m (m/s), solar radiation (MJ/m2/day)."""
    tmean = (tmax + tmin) / 2
    pressure = 101.3 * ((293 - 0.0065 * elevation_m) / 293) ** 5.26          # kPa
    gamma = 0.000665 * pressure

    def sat(t):
        return 0.6108 * np.exp(17.27 * t / (t + 237.3))
    es = (sat(tmax) + sat(tmin)) / 2
    ea = np.clip(rh, 0, 100) / 100 * es
    delta = 4098 * sat(tmean) / (tmean + 237.3) ** 2
    ra = _extraterrestrial_radiation(lat, doy) / 0.408                      # MJ/m2/day
    rso = (0.75 + 2e-5 * elevation_m) * ra
    rns = 0.77 * rs
    ratio = np.clip(rs / np.maximum(rso, 1e-6), 0.25, 1.0)
    rnl = 4.903e-9 * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 \
        * (0.34 - 0.14 * np.sqrt(np.clip(ea, 0, None))) * (1.35 * ratio - 0.35)
    rn = rns - rnl
    et0 = (0.408 * delta * rn + gamma * 900 / (tmean + 273) * u2 * (es - ea)) \
        / (delta + gamma * (1 + 0.34 * u2))
    return np.clip(et0, 0, None)


# ---------------------------------------------------------------- validation

def _numeric_problems(df, cols):
    out = []
    for c in cols:
        if c not in df:
            continue
        v = pd.to_numeric(df[c], errors="coerce")
        if v.isna().any():
            out.append(f"column '{c}' has {int(v.isna().sum())} empty or non-numeric value(s)")
        elif (v == -999).any():
            out.append(f"column '{c}' has {int((v == -999).sum())} fill value(s) of -999 (missing data)")
    return out


def _flagged(series):
    """rs_estimated-style flags (True/False, 1/0, "true") as a boolean array."""
    return series.astype(str).str.strip().str.lower().isin(["1", "true", "yes"]).to_numpy()


def _flat_run(df, col):
    """The longest run of identical consecutive values in `col`: (value, days, first year,
    last year), or None if it's shorter than FLAT_RUN_DAYS."""
    v = pd.to_numeric(df[col], errors="coerce")
    run_id = (v != v.shift()).cumsum()
    sizes = v.groupby(run_id).size()
    rid = sizes.idxmax()
    if sizes[rid] < FLAT_RUN_DAYS:
        return None
    rows = df[run_id == rid]
    years = (pd.to_datetime(rows["date"]).dt.year if "date" in rows else rows["year"]).astype(int)
    return float(v[run_id == rid].iloc[0]), int(sizes[rid]), int(years.min()), int(years.max())


def _check_et0(df, lat):
    """A supplied ET0 must agree with FAO-56 Penman-Monteith from the file's own columns
    (on days whose solar radiation was measured, not estimated)."""
    if "ET0" not in df or not set(PM_INPUTS) <= set(df):
        return []
    d = df.copy()
    doy = pd.to_datetime(d["date"]).dt.day_of_year if "date" in d else d["doy"]
    keep = ~_flagged(d["rs_estimated"]) if "rs_estimated" in d else np.ones(len(d), bool)
    num = {c: pd.to_numeric(d[c], errors="coerce").to_numpy()[keep] for c in PM_INPUTS + ["ET0"]}
    pm = et0_penman_monteith(num["T2M_MAX"], num["T2M_MIN"], num["RH2M"], num["WS2M"],
                             num["ALLSKY_SFC_SW_DWN"], np.asarray(doy)[keep], lat)
    ratio = np.nanmean(num["ET0"]) / max(np.nanmean(pm), 1e-9)
    lo, hi = ET0_TOLERANCE
    if lo <= ratio <= hi:
        return []
    return [f"ET0 averages {ratio:.0%} of FAO-56 Penman-Monteith computed from the file's own "
            f"temperature, humidity, wind and solar columns (expected {lo:.0%}-{hi:.0%}). Drop the "
            "ET0 column to have it computed, or fix the formula."]


def _check_weather(df, lat=FARM["lat"]):
    probs = []
    if "date" not in df and not {"year", "doy"} <= set(df):
        probs.append("needs a 'date' column (YYYY-MM-DD) or 'year' and 'doy' columns")
        return probs
    if "ET0" not in df and not {"T2M_MAX", "T2M_MIN"} <= set(df):
        probs.append("needs 'ET0', or 'T2M_MAX' and 'T2M_MIN' to compute it")
    probs += _numeric_problems(df, ["PRECTOTCORR", "ET0", "T2M_MAX", "T2M_MIN"] +
                               [c for c in ("RH2M", "WS2M", "ALLSKY_SFC_SW_DWN") if c in df])
    years = (pd.to_datetime(df["date"], errors="coerce").dt.year if "date" in df else df["year"])
    if years.isna().any():
        probs.append("some dates can't be read (use YYYY-MM-DD)")
        return probs
    counts = years.astype(int).value_counts()
    missing = [y for y in range(FIRST_YEAR, LAST_YEAR + 1) if y not in counts]
    if missing:
        probs.append(f"no data for {len(missing)} year(s): {', '.join(map(str, missing[:6]))}"
                     + ("…" if len(missing) > 6 else ""))
    short = [y for y in range(FIRST_YEAR, LAST_YEAR + 1) if y in counts and counts[y] < 365]
    if short:
        probs.append(f"{len(short)} year(s) have missing days: {', '.join(map(str, short[:6]))}")
    if "PRECTOTCORR" in df and (pd.to_numeric(df["PRECTOTCORR"], errors="coerce") < 0).any():
        probs.append("rain (PRECTOTCORR) has negative values")
    structural = bool(probs)               # missing columns, bad dates or numbers
    names = {"ALLSKY_SFC_SW_DWN": "solar radiation", "RH2M": "humidity", "WS2M": "wind speed"}
    for col, label in names.items():
        run = _flat_run(df, col) if col in df else None
        if run:
            value, days, y0, y1 = run
            fix = (" Estimate it from the daily temperature range (FAO-56 eq. 50), as "
                   "`python real_data.py fetch-weather` does." if col == "ALLSKY_SFC_SW_DWN" else "")
            probs.append(f"{label} ({col}) is a constant {value:g} for {days:,} days in a row "
                         f"({y0}-{y1}): looks like a placeholder, not a measurement.{fix}")
    if not structural:
        probs += _check_et0(df, lat)
    return probs


def _check_crops(df):
    probs = []
    missing = [c for c in CROPS if c not in set(df["crop"])]
    if missing:
        probs.append(f"missing crop row(s): {', '.join(missing)} (needs all of {', '.join(CROPS)})")
    probs += _numeric_problems(df, REQUIRED["crops"][1:])
    if probs:
        return probs
    rows = df.set_index("crop")
    for crop in [c for c in CROPS if c in rows.index]:
        r = rows.loc[crop]
        if r["price_usd"] <= 0 or r["base_yield"] <= 0:
            probs.append(f"{crop}: price and base_yield must be above 0")
        if not 0 < r["ky"] <= 2:
            probs.append(f"{crop}: ky (FAO-33 yield response) should be between 0 and 2")
        if not 0 < r["depletion_p"] < 1:
            probs.append(f"{crop}: depletion_p should be between 0 and 1")
        season = sum(int(r[k]) for k in ("len_ini", "len_dev", "len_mid", "len_late"))
        if not 1 <= int(r["plant_doy"]) <= 366 or int(r["plant_doy"]) + season - 1 > 366:
            probs.append(f"{crop}: the season (plant_doy {int(r['plant_doy'])} + {season} days) "
                         "must fit inside one calendar year")
    return probs


def _check_rotation(df):
    probs = _numeric_problems(df, ["yield_mult", "n_credit_lb"])
    unknown = sorted((set(df["prev_crop"]) | set(df["crop"])) - set(CROPS))
    if unknown:
        probs.append(f"unknown crop name(s): {', '.join(map(str, unknown))} (use {', '.join(CROPS)})")
    if not probs and (pd.to_numeric(df["yield_mult"]) <= 0).any():
        probs.append("yield_mult must be above 0 (1.0 = no effect)")
    return probs


def _check_soils(df):
    probs = _numeric_problems(df, ["awc_mm_per_m"])
    if "default" not in set(df["soil"].astype(str).str.strip().str.lower()):
        probs.append("needs a 'default' row (used for any soil name not in the table)")
    if not probs and (pd.to_numeric(df["awc_mm_per_m"]) <= 0).any():
        probs.append("awc_mm_per_m must be above 0")
    return probs


def _check_site(df):
    if len(df) != 1:
        return [f"needs exactly one row (has {len(df)})"]
    probs = _numeric_problems(df, REQUIRED["site"])
    if probs:
        return probs
    r = df.iloc[0]
    if not -90 <= r["lat"] <= 90:
        probs.append("lat must be between -90 and 90")
    if not 1 <= r["season_start_doy"] < r["season_end_doy"] <= 366:
        probs.append("season_start_doy must come before season_end_doy (days 1-366)")
    return probs


CHECKS = {"weather": _check_weather, "crops": _check_crops, "rotation_effects": _check_rotation,
          "soils": _check_soils, "site": _check_site}


def validate(folder=None):
    """({table: [problems]}, {table: DataFrame}) for the files in `folder`. No problems = ready."""
    folder = Path(folder or real_dir())
    problems, tables = {}, {}
    try:                                   # the farm's latitude, for the ET0 check
        lat = float(pd.read_csv(folder / FILES["site"])["lat"].iloc[0])
    except Exception:                      # noqa: BLE001 - fall back to the demo farm
        lat = FARM["lat"]
    for table, name in FILES.items():
        path = folder / name
        if not path.exists():
            problems[table] = [f"{name} is missing"]
            continue
        try:
            df = pd.read_csv(path)
        except Exception as e:                       # noqa: BLE001 - report any read problem
            problems[table] = [f"{name} can't be read: {e}"]
            continue
        if table == "weather":
            df = df.rename(columns={a: b for a, b in WEATHER_ALIASES.items() if b not in df})
        missing = [c for c in REQUIRED[table] if c not in df]
        if df.empty:
            problems[table] = [f"{name} has no rows"]
        elif missing:
            problems[table] = [f"{name} is missing column(s): {', '.join(missing)}"]
        else:
            problems[table] = CHECKS[table](df, lat) if table == "weather" else CHECKS[table](df)
            tables[table] = df
    return problems, tables


_STATUS = {}


def status(folder=None):
    """What's ready: {"folder", "ready": [tables], "problems": {table: [..]}, "complete"}.
    Cached until a file in the folder changes."""
    folder = Path(folder or real_dir())
    sig = signature(folder)
    if sig not in _STATUS:
        problems, _ = validate(folder)
        _STATUS.clear()
        _STATUS[sig] = {"folder": str(folder),
                        "ready": [t for t in FILES if not problems.get(t)],
                        "problems": {t: p for t, p in problems.items() if p},
                        "complete": not any(problems.values())}
    return _STATUS[sig]


# ---------------------------------------------------------------- loading

def load_data(folder=None):
    """The five real tables in the model's shape (same as synthetic_data.load_data()).
    Fills in what can be derived: year/doy from date, ET0 if it's missing. Raises
    RealDataError when anything is missing or invalid (all or nothing)."""
    folder = Path(folder or real_dir())
    problems, t = validate(folder)
    if any(problems.values()):
        raise RealDataError({k: v for k, v in problems.items() if v})
    site = t["site"].copy()

    w = t["weather"].copy()
    if "date" in w:
        dates = pd.to_datetime(w["date"])
        w["year"], w["doy"] = dates.dt.year, dates.dt.day_of_year
    w["year"], w["doy"] = w["year"].astype(int), w["doy"].astype(int)
    w = w[(w["year"] >= FIRST_YEAR) & (w["year"] <= LAST_YEAR)].sort_values(["year", "doy"])
    if "ET0" not in w:
        lat = float(site["lat"].iloc[0])
        if set(PM_INPUTS) <= set(w):
            elev = float(site["elevation_m"].iloc[0]) if "elevation_m" in site else 0.0
            w["ET0"] = et0_penman_monteith(w["T2M_MAX"], w["T2M_MIN"], w["RH2M"], w["WS2M"],
                                           w["ALLSKY_SFC_SW_DWN"], w["doy"], lat, elev)
        else:
            w["ET0"] = et0_hargreaves(w["T2M_MAX"], w["T2M_MIN"], w["doy"], lat)

    crops = t["crops"].set_index("crop").loc[CROPS].reset_index()     # contract order
    soils = t["soils"].assign(soil=t["soils"]["soil"].astype(str).str.strip().str.lower())
    return {"weather": w.reset_index(drop=True), "crops": crops,
            "rotation_effects": t["rotation_effects"], "soils": soils, "site": site,
            "source": "real"}


# ---------------------------------------------------------------- NASA POWER

def fetch_weather(lat=FARM["lat"], lon=FARM["lon"], out=None, first=FIRST_YEAR, last=LAST_YEAR):
    """Download NASA POWER daily weather for one point, fill short gaps, compute FAO-56
    Penman-Monteith ET0, and save weather_daily.csv. Returns the table."""
    out = Path(out or real_dir())
    url = (f"{POWER_URL}?parameters={','.join(POWER_PARAMS)}&community=AG&longitude={lon}"
           f"&latitude={lat}&start={first}0101&end={last}1231&format=JSON")
    req = urllib.request.Request(url, headers={"User-Agent": "FieldShift/1.0 (NASA Space Apps)"})
    print(f"Downloading NASA POWER daily {first}-{last} at lat {lat}, lon {lon} …")
    with urllib.request.urlopen(req, timeout=300) as r:
        payload = json.load(r)
    params = payload["properties"]["parameter"]
    elevation = float(payload.get("geometry", {}).get("coordinates", [0, 0, 0])[2] or 0)
    w = pd.DataFrame({p: pd.Series(params[p]) for p in POWER_PARAMS})
    w.index = pd.to_datetime(w.index, format="%Y%m%d")
    w = w.replace(-999.0, np.nan).sort_index()
    gaps = {p: int(w[p].isna().sum()) for p in POWER_PARAMS if w[p].isna().any()}
    w = w.interpolate(limit=7, limit_area="inside")              # short gaps only (up to a week)
    doy = w.index.day_of_year.to_numpy()
    # POWER's daily solar radiation starts in 1984. Where it's missing, estimate it from the
    # day's temperature range, FAO-56 eq. 50 (kRs = 0.16 for inland sites), and mark those days.
    rs_missing = w["ALLSKY_SFC_SW_DWN"].isna().to_numpy()
    if rs_missing.any():
        ra_mj = _extraterrestrial_radiation(lat, doy) / 0.408
        est = 0.16 * np.sqrt(np.clip(w["T2M_MAX"] - w["T2M_MIN"], 0, None)) * ra_mj
        w.loc[rs_missing, "ALLSKY_SFC_SW_DWN"] = est[rs_missing].round(2)
    still = {p: int(w[p].isna().sum()) for p in POWER_PARAMS if w[p].isna().any()}
    if still:
        raise RuntimeError(f"NASA POWER returned long gaps that can't be filled: {still}")
    w["date"] = w.index.strftime("%Y-%m-%d")
    w["year"], w["doy"] = w.index.year, doy
    w["rs_estimated"] = rs_missing.astype(int)
    w["ET0"] = et0_penman_monteith(w["T2M_MAX"], w["T2M_MIN"], w["RH2M"], w["WS2M"],
                                   w["ALLSKY_SFC_SW_DWN"], w["doy"], lat, elevation).round(3)
    w = w[["date", "year", "doy"] + POWER_PARAMS + ["ET0", "rs_estimated"]].reset_index(drop=True)
    out.mkdir(parents=True, exist_ok=True)
    w.to_csv(out / FILES["weather"], index=False)

    season = w[(w["doy"] >= SITE["season_start_doy"]) & (w["doy"] <= SITE["season_end_doy"])]
    by_year = season.groupby("year")["PRECTOTCORR"].sum()
    july = w[(w["doy"] >= 182) & (w["doy"] <= 212)]["ET0"].mean()
    print(f"Saved {len(w):,} days to {out / FILES['weather']} (elevation {elevation:.0f} m)")
    print(f"Missing in the download: {gaps or 'none'}")
    if rs_missing.any():
        yrs = sorted(set(w.loc[w["rs_estimated"] == 1, "year"]))
        print(f"  solar radiation estimated from temperature (FAO-56 eq. 50) on {int(rs_missing.sum())} "
              f"days ({yrs[0]}-{yrs[-1]}); marked in column rs_estimated")
    print(f"Growing-season rain (May-Sep): mean {by_year.mean():.0f} mm; driest {by_year.idxmin()} "
          f"({by_year.min():.0f} mm); 2012: {by_year.get(2012, float('nan')):.0f} mm")
    print(f"July ET0 (Penman-Monteith): mean {july:.1f} mm/day")
    print("Tip: add elevation_m to site.csv if you compute ET0 again from these columns.")
    return w


# ---------------------------------------------------------------- templates and command line

def write_templates(out=None):
    """Example files in <folder>/templates/: the synthetic tables as a filled-in example
    (weather: first 5 days only, since fetch-weather makes the real one)."""
    out = Path(out or real_dir()) / "templates"
    out.mkdir(parents=True, exist_ok=True)
    d = synthetic_data.load_data()
    for table, name in FILES.items():
        df = d[table].head(5) if table == "weather" else d[table]
        df.to_csv(out / name, index=False)
    print(f"Wrote {len(FILES)} example files to {out} (synthetic values: replace them with real ones,")
    print("then save the files one folder up, in", out.parent, ")")


def print_check(folder=None):
    s = status(folder)
    print(f"Real data folder: {s['folder']}")
    for table, name in FILES.items():
        if table in s["ready"]:
            print(f"  ✓ {name}")
        else:
            for i, p in enumerate(s["problems"][table]):
                print(f"  {'✗' if i == 0 else ' '} {name if i == 0 else ' ' * len(name)}  {p}")
    n = len(s["ready"])
    print(f"{n} of {len(FILES)} tables ready. " + (
        "The app uses the real data." if s["complete"] else
        "The app uses the synthetic sample data until all of them are ready."))
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description="Field Shift real data: check, fetch, templates.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="report which real tables are ready")
    c.add_argument("--folder")
    f = sub.add_parser("fetch-weather", help="download NASA POWER daily weather 1981-2024")
    f.add_argument("--lat", type=float, default=FARM["lat"])
    f.add_argument("--lon", type=float, default=FARM["lon"])
    f.add_argument("--out", help="folder to save weather_daily.csv in (default data/real/)")
    t = sub.add_parser("templates", help="write example files to fill in by hand")
    t.add_argument("--out")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        return 0 if print_check(args.folder)["complete"] else 1
    if args.cmd == "fetch-weather":
        fetch_weather(args.lat, args.lon, args.out)
        return 0
    write_templates(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
