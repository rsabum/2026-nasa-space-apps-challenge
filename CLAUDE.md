# Field Shift (Team Athens, NASA Space Apps Challenge 2026)

This file brings Claude up to speed on a project that started in a claude.ai chat on Nov 14, 2026.
Claude Code reads it automatically at the start of every session in this folder.

## Who I am and how to help me

- I'm Claude-Thomas, on Team Athens. I own the **Software** track: this Streamlit app.
- I'm a beginner. Walk me through things **step by step**, and when a step changes a file, give me the full file or the exact edit.
- I like **detailed** explanations: what we're doing and why.
- I'm on a Mac, in US Central time.

## The hackathon

- NASA Space Apps Challenge 2026, Nov 14–15. Challenge: "Field Shift: Adapting Farms with NASA Data".
  Page: https://www.spaceappschallenge.org/2026/challenges/adapting-farms-with-nasa-data/ (blocks automated fetching; ask me to paste text).
- **Team objective (our own words):** "Given a planting rotation, objectives and restraints, see how the rotation would perform on historical data."
  So: the farmer enters their rotation and ground rules, the app backtests it on every year of NASA POWER weather (1981–2024), and the optimizer suggests a better rotation that is backtested the same way.
- Demo farm: central Illinois, lat 40.1, lon −88.2, four fields (North 80 ac, South 60, East 40, West 20).

## The team

| Track | Owner | Delivers |
|---|---|---|
| Data | Tebit | CSVs: NASA POWER weather 1981–2024, crop table (yields, prices, costs, water need), fields.csv from Web Soil Survey |
| Optimization | Robert (GitHub `rsabum`) | `model.py` with the same functions as `fake_model.py`, using PuLP |
| Software | Claude-Thomas (me) | This Streamlit app |

Planning docs (claude.ai, shared with the team):
- Team Reference Sheet **v2.01** (the source of truth): https://claude.ai/artifact/SksLDwoMDu1ExcaYW5MmZq
- Weekend Roadmap (older; predates the backtest objective): https://claude.ai/artifact/RRX38L5NLMYbCWMD3CLNXa

## Repo and setup

- GitHub: `rsabum/2026-nasa-space-apps-challenge` (private, on Robert's personal account). I work on branch **`claude`**.
- Local: `~/2026-nasa-space-apps-challenge`, virtual environment `.venv` on **Python 3.9.6**.
- Run: `source .venv/bin/activate` then `streamlit run app.py` (opens http://localhost:8501).
- Save work: `git add .` then `git commit -m "message"` then `git push`.
- **Deploy is parked.** Streamlit Community Cloud needs GitHub admin rights on the repo and I only have push access. Robert must deploy from his own Streamlit account (main file: `app.py` on branch `claude`, Python 3.11), or the repo moves to a GitHub organization.

## Files

| File | What it is |
|---|---|
| `app.py` | The Streamlit app (my file) |
| `style.css` | All custom styling; loaded by app.py |
| `contract.py` | Shared names: FARM, CROPS, CROP_COLORS/LABELS/ICONS, WEIGHTS, CONSTRAINTS, column lists, `baseline_plan()`. **Change only with the whole team.** |
| `fake_model.py` | Stand-in for Robert's model, same function signatures, deterministic fake numbers |
| `assets/logo.svg`, `assets/icon.png` | Our original logo (classical column with three crop-coloured flutes and a sprout) |
| `.streamlit/config.toml` | Dark theme colours, font name, corner radius (restart Streamlit after editing) |
| `rules.py` | Plain-English check of a rotation against the ground rules (used by app.py and fake_model.py) |
| `requirements.txt` | streamlit, pandas, plotly, pulp, requests |

Swapping in the real model is one line in app.py: `import fake_model as model` becomes `import model`.

### The interface contract (from Reference Sheet v2.01)

- `evaluate(plan, farm, data, scenario)`: score a given plan; returns a table with columns in `PLAN_COLUMNS`.
- `solve(farm, data, weights, scenario, constraints)`: best plan for the farmer's weights and ground rules.
- `solve_pareto(farm, data, scenario, constraints)`: a set of trade-off plans (for a later chart).
- `backtest(plan, farm, data)`: one row per year 1981–2024 with columns in `BACKTEST_COLUMNS`.
- A plan is `{field_name: [crop for year 1, year 2, year 3, year 4]}`. Crops: corn, soybeans, winter_wheat, sorghum.
- Water is measured as **shortfall** (crop need minus growing-season rain), shown in acre-inches. Scenarios: "average" and "dry".

## Design decisions (my choices)

- **User:** a semi-experienced farmer in his 30s. Use real farming terms but keep it simple; add `help=` tooltips for anything technical.
- **Look (changed Nov 15):** dark theme, modern-app feel (think X / Instagram dark mode): near-black page `#0F1115`, cards one shade lighter, mint accent `#5DD6B0`, "bubble" corners (28px cards, pill buttons and badges). **Inter** everywhere (professional sans), heavy weights for headings. Palette lives as CSS variables at the top of `style.css`, plus `.streamlit/config.toml` for Streamlit's own widgets. Text on crop-coloured tiles stays dark (`--on-crop`).
- **Crop colours** (pastel, checked for colour-blind separation): corn `#F8E68E`, soybeans `#72BFB0`, winter wheat `#F0A972`, sorghum `#C77882`. Always pair colour with a label or icon.
- **Icons:** corn 🌽, soybeans 🌱, winter wheat 🌾, sorghum 🌿.
- **Layout today:** hero header with logo and "Team Athens" badge; sidebar with a farm map of "Your fields" (plots sized by acres, tinted by last crop, furrow stripes, table inside an "Edit fields" popover), "What matters most" sliders, "Ground rules"; main area with bordered cards "01 · The plan" (rotation as a tile grid) and "02 · The test" (big "N / 44" stat plus a backtest line chart), three metric cards with crop-coloured top borders, an expander with the raw numbers, and a footer.

## Gotchas

- My Mac runs an **older Streamlit** (Python 3.9 caps it around 1.50). Don't use brand-new arguments such as `width="stretch"` on `st.plotly_chart`; it shows deprecation warning boxes. Call `st.plotly_chart(fig)` plainly.
- Keep files at the top level of the repo, never inside `.venv/`.
- `style.css` targets some Streamlit internals (`data-testid` names and `st-key-<key>` classes from `st.container(key=...)`). If a Streamlit upgrade breaks the look, check those selectors first.

## What's next

1. **Part 3: let the farmer enter their own rotation.** A grid (fields × years) where they pick a crop per cell, then the app backtests *their* rotation alongside the suggestion. This is the core of the team objective.
2. Make the "typical year / dry year" switch visibly change things; add a short "why this plan" sentence.
3. Swap in Robert's `model.py` and Tebit's CSVs when ready.
4. Sunday: trade-off chart from `solve_pareto`, demo polish, deployment via Robert.
