# field-shift

`field-shift` is a Python 3.11 crop-rotation planner for the NASA Space Apps 2026 challenge **"Field Shift: Adapting Farms with NASA Data"**.

## Modes

The tool uses one shared scoring engine in two workflows:

1. **Evaluate**: score a user-provided 4-year rotation (crop by zone by year) and list each violated constraint with a human-readable reason.
2. **Optimize**: enumerate allowed per-zone sequences, score each sequence with the same evaluator, and use a small PuLP MILP to choose one sequence per zone under farm-wide limits.

## NASA and related datasets

The project includes loader stubs/caches for:

- NASA POWER daily weather API (point lat/lon)
- SMAP (soil moisture) CSV cache
- SSURGO soil attributes CSV cache
- SRTM slope CSV cache
- USDA CropScape history CSV cache
- NASS yields CSV cache
- Crop prices CSV cache

Cache files are expected under `data/cache/`.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Run

Evaluate/optimize logic is available as package modules under `src/field_shift`.

Run the Streamlit UI:

```bash
streamlit run app/streamlit_app.py
```

Run tests:

```bash
pytest
```

## Important note

This tool is intended to support planning and scenario analysis. It does **not** replace farmer, agronomist, or local extension judgment.

## TODOs

- Fill `data/crops.csv` and model defaults with validated agronomic values.
- Harden dataset loaders with schema validation and production-grade error handling.
- Calibrate scoring and constraints with local field data.
