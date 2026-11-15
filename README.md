# Field Shift

Crop-rotation planner for the NASA Space Apps 2026 challenge *Field Shift: Adapting Farms with NASA Data*.
This repo currently contains the **data layer**: one module per dataset, each with
`fetch(config, force=False)` (download + clean + cache) and `load(config)` (cache only, never the network).

MVP crops: **corn, soybeans, oats, winter wheat, alfalfa** plus **cereal rye** as the only cover crop.

## Quickstart (mock mode, about 2 minutes)

During development we **don't fetch real data**. Every client talks to a local mock service that imitates the
real API's request and response format and serves **synthetic data** (labeled `is_synthetic=True` everywhere).

```bash
uv python install 3.11 && uv venv -p 3.11 && source .venv/bin/activate
uv pip install -e ".[dev]"          # or: pip install -e ".[dev]"
cp .env.example .env                 # mock-mode values work as-is

python -m field_shift.mock serve     # terminal 1: mock APIs on http://127.0.0.1:8765
python -m field_shift.data fetch --all   # terminal 2: fetch + cache all 5 datasets
python -m field_shift.data status
pytest                               # offline; starts its own mock in-process
```

Then in code:

```python
from field_shift.config import load_config
from field_shift.data import power, nass, cdl, soils, terrain, reference

cfg = load_config()
weather = power.load(cfg)          # daily: tmax_c, precip_mm, rs_mj_m2, et0_mm, gdd10, gwetroot_frac, ...
frost = power.frost_dates(cfg)     # last spring / first fall frost per year
crops = reference.load_crops(cfg)  # hand-filled table (warns about blank cells)
```

## Data

### Online sources (5)

| Dataset | Source | Used for | Auth | Coverage | Cached at (`data/processed/`) |
|---|---|---|---|---|---|
| NASA POWER daily point (AG) | [power.larc.nasa.gov API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) | weather, frost dates, crop water use (FAO-56 ET0), past years as scenarios | none | 1981 to present (we use 2001–2025) | `power.parquet` |
| SSURGO via Soil Data Access | [sdmdataaccess.sc.egov.usda.gov](https://sdmdataaccess.sc.egov.usda.gov) | soil water (AWC), erosion risk (surface K factor), soil zones (polygons) | none | current SSURGO snapshot | `soils.parquet`, `soils/mupolygons.geojson` |
| SRTM 1 arc-second (SRTMGL1 v003) | [LP DAAC](https://lpdaac.usgs.gov/products/srtmgl1v003/) via [CMR](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html) | slope and slope zones | Earthdata login | Feb 2000 (static) | `terrain/{dem,slope_pct,slope_zones}.tif`, `terrain_summary.parquet` |
| ↳ backup: USGS 3DEP 1/3″ | [TNM Access API](https://tnmaccess.nationalmap.gov/api/v1/docs) | same, used when there is no Earthdata login | none | static | same files (`source` column says which) |
| NASS QuickStats | [quickstats.nass.usda.gov/api](https://quickstats.nass.usda.gov/api) | county yields; Iowa prices received | free API key | annual (we use 2001–2025) | `nass.parquet` |
| Cropland Data Layer | [CropScape](https://nassgeodata.gmu.edu/CropScape/) (point) + [USDA PDI ImageServer](https://pdi.scinet.usda.gov/image/rest/services/CDL_WM/ImageServer) (box) | the farm's current rotation | none | 2008–2025 used | `cdl.parquet`, `cdl_box_fractions.parquet`, `cdl/box_<year>.tif` |

Raw downloads go to `data/raw/<dataset>/`, and `data/manifest.json` records when, from where (mock or real) and how
many rows. Everything under `data/` except `data/reference/` is gitignored. Re-running a fetch reuses the cache;
`--force` re-downloads.

### Hand-filled tables (3), in `data/reference/` (committed)

| Table | One row per | Fill from |
|---|---|---|
| `crops.csv` | crop: family, legume, water use, drought sensitivity, season length, frost tolerance, planting window (end = USDA final planting date), cost/acre, erosion protection, soil-health points | Iowa State Ag Decision Maker (costs; USDA ERS for oats and wheat), USDA RMA |
| `rotation_effects.csv` | previous → next crop: yield change, fertilizer N credit (corn after soy, corn after corn, corn after alfalfa) | Iowa State Extension |
| `site.csv` | site: rainfall erosivity (RUSLE R), cereal-rye planting dates | RUSLE2 county data; Midwest Cover Crops Council Cover Crop Decision Tool |

They ship as **templates with blank values** (only the CDL codes and NASS names are pre-filled). The loaders
validate types, levels (`low|medium|high`) and `MM-DD` dates, and warn about every blank cell, so code works while
they're being filled in. Put the source of each row in its `source` column. The soil score is **our own
heuristic** (soil-health points, erosion protection, K factor), not an external index.

### Setup for real mode

1. **NASS API key** (free): request one at <https://quickstats.nass.usda.gov/api> and put `NASS_API_KEY=...`
   in `.env`. Without it, NASS is skipped with a message.
2. **NASA Earthdata login** (free): create an account at <https://urs.earthdata.nasa.gov>, then either
   - add to `~/.netrc` (and `chmod 600 ~/.netrc`):
     `machine urs.earthdata.nasa.gov login YOUR_USER password YOUR_PASSWORD`, or
   - run `python -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"` once, or
   - put `EARTHDATA_TOKEN=...` in `.env` (generate one in your Earthdata profile).

   Without it, terrain uses the USGS 3DEP backup.
3. Set `endpoints.mode: real` in `config.yaml`.

Secrets are never printed, logged or written to the cache; request URLs are redacted in errors and in the mock's log.

## Mock services

`python -m field_shift.mock serve` runs one Flask app. Each service sits under a prefix, and the rest of the path is the
real one, e.g. `/power/api/temporal/daily/point`, `/nass/api/api_get/`, `/cdl_point/axis2/services/CDLService/GetCDLValue`,
`/cdl_image/image/rest/services/CDL_WM/ImageServer/exportImage`, `/sda/tabular/post.rest`,
`/cmr/search/granules.json`, `/tnm/api/v1/products`.

The synthetic world is **coherent and seeded** (`mock.seed` in `config.yaml`): yields respond to synthetic rain and
heat, POWER soil wetness follows synthetic rain, soils follow synthetic terrain, and the site sits in a field
with a corn–soy-dominated rotation. Parameters are in `src/field_shift/mock/params/`, each with a provenance line:
- **Weather is fitted** to one real POWER response for the site (`scripts/fit_weather_params.py` → `*.weather.yaml`):
  annual rain, ET0, temperatures and wet-day frequency match the real record. Year-to-year rain variance is
  somewhat low, a known weakness of this kind of generator.
- **Everything else is a PLACEHOLDER** (yields, prices, rotations, soil properties, terrain shape): plausible-looking
  numbers for development only. Don't draw agronomic conclusions from mock data.

Mock limitations: it serves only the configured site; the SDA mock understands only the queries `soils.py` sends;
the mock 3DEP tile covers ~10 km around the site instead of a full 1°×1° tile.

`tests/test_contracts.py` runs each parser on a small **real** response (`tests/fixtures/real/`, captured with
`scripts/capture_fixtures.py`) and on the mock's response, so the mock can't drift from the real formats.

## Commands

```bash
python -m field_shift.data fetch --all [--force]
python -m field_shift.data fetch --dataset power|nass|cdl|soils|terrain [--force]
python -m field_shift.data status
pytest                 # offline
pytest -m network      # optional live smoke tests against the real APIs
```

## Later

- **Phase 2 (if time allows, in order):** SMAP soil moisture (AppEEARS point sample of SPL3SMP_E; POWER's
  `GWETROOT` stands in until then), PRISM, GPM IMERG, NDVI.
- **Dropped for the MVP:** AMS Market News (NASS prices replace it), NASS Crop Progress, external soil-health index.
- **Cloud/real phase:** run each client in real mode; replace PLACEHOLDER mock parameters with fits to real data.
