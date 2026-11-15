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
| Optimization | Robert (GitHub `rsabum`) | `model.py` (in, Nov 15): the real optimizer, same functions as `fake_model.py`; PuLP, solved by Gurobi or CBC. Works on branch **`robert`** |
| Software | Claude-Thomas (me) | This Streamlit app |

Planning docs (claude.ai, shared with the team):
- Team Reference Sheet **v2.01** (the source of truth): https://claude.ai/artifact/SksLDwoMDu1ExcaYW5MmZq
- Weekend Roadmap (older; predates the backtest objective): https://claude.ai/artifact/RRX38L5NLMYbCWMD3CLNXa

## Repo and setup

- GitHub: `rsabum/2026-nasa-space-apps-challenge` (private, on Robert's personal account). I work on branch **`claude`**.
- Local: `~/2026-nasa-space-apps-challenge`, virtual environment `.venv`: on my Mac **Python 3.9.6**; on Robert's Mac Python 3.11 plus `pip install -r requirements-gurobi.txt` (his academic Gurobi license, `~/gurobi.lic`, expires 2027-02-01). Keep code Python 3.9-compatible (no `match`, no `X | Y` type hints).
- Run: `source .venv/bin/activate` then `streamlit run app.py` (opens http://localhost:8501).
- Save work: `git add .` then `git commit -m "message"` then `git push`.
- **Deploy is parked.** Streamlit Community Cloud needs GitHub admin rights on the repo and I only have push access. Robert must deploy from his own Streamlit account (main file: `app.py` on branch `claude`, Python 3.11), or the repo moves to a GitHub organization.

## Files

| File | What it is |
|---|---|
| `app.py` | Entry point (my file). Runs first on every click: page setup, styles, `ui.keep_state()`, the page menu (`st.navigation`), the shared left panel (Your fields + Ground rules), then the open page, then the assistant |
| `pages/home.py` | **Home**: hero, the two tools (cards with `st.page_link` buttons), how it works, farm at a glance, data sources |
| `pages/evaluate.py` | **Rotation evaluator**: drought switch, "01 · Your rotation" (editor, tiles, rule check, Reset), key numbers, "02 · Tested on NASA weather" for the farmer's rotation alone |
| `pages/optimize.py` | **Rotation optimizer**: "01 · Your goal" (goal + limits), drought switch, "02 · Optimized rotation" (chips, why, crop mix, Apply), key numbers vs yours, "03 · Tested on NASA weather" head-to-head |
| `ui.py` | Everything the pages share: crop colours/icons, tiles, field map, charts (`backtest_chart` for one or two lines, with replay), chips, why-this-plan, page header + logo directory, metric row, the goal controls, cross-page state, and `analysis()` (the one place that calls the model) |
| `style.css` | All custom styling; loaded by app.py. Any `st.container(key="card_...")` gets the panel look |
| `contract.py` | Shared names: FARM, CROPS, CROP_COLORS/LABELS/ICONS, CONSTRAINTS, column lists, `baseline_plan()`, and (Nov 15) GOALS, GOAL_HELP, LIMIT_LABELS, DEFAULT_LIMITS, GOAL_OWN_LIMITS, WORST_SHARE. WEIGHTS is deprecated. **Change only with the whole team.** |
| `model.py` | Robert's optimizer, "Enumerate, Simulate, Assign": every 4-year rotation per field (4 crops × yes/no rye cover after each year = 4,096), filtered by `rules.py`, scored by table lookups into `crop_sim.py`, then a PuLP integer program picks one per field. Gurobi when licensed, else CBC (`FIELD_SHIFT_SOLVER=gurobi\|cbc` forces one) |
| `crop_sim.py` | Stage 1 crop model: daily soil-water bucket (FAO-56) + FAO-33 yield, with irrigation and rye's spring water draw, precomputed per (soil, crop, rye before, irrigated, year) |
| `synthetic_data.py` | Synthetic stand-in for Tebit's data (weather 1981–2024 with POWER column names, crops, rotation effects, soils, site). `python synthetic_data.py` writes `data/synthetic/*.csv` + README as the format spec |
| `check_model.py` | `python check_model.py`: 43 checks, incl. MILP = brute force on a 2-field farm for every goal, on both solvers. Keep it passing |
| `fake_model.py` | The old stand-in with fake numbers (accepts a goal name). Fallback only |
| `requirements-gurobi.txt` | `gurobipy` for Robert's Mac only; kept out of requirements.txt (unlicensed pip gurobipy is capped at 2,000 variables, so the cloud uses CBC) |
| `assets/logo.svg`, `assets/icon.png` | Our original logo (classical column with three flutes and a sprout). Nov 15: recoloured to the theme: NASA-blue gradient tile, mint / blue / NASA-red gradient flutes, mint-to-blue sprout, sharper corners. icon.png is rendered from the SVG (`qlmanage -t -s 256`, corners masked with Pillow). |
| `.streamlit/config.toml` | Dark theme colours, font name, corner radius (restart Streamlit after editing) |
| `assistant.py` | The "Ask Field Shift" chat bubble (bottom right). Claude mode (Opus 5.5, streamed, low effort, server-side refusal fallback) when `ANTHROPIC_API_KEY` is in `.streamlit/secrets.toml` (git-ignored) or the environment; otherwise keyword-matched quick answers. Both use only the live numbers app.py passes in (`ui.faq_context`). It knows the three pages. |
| `rules.py` | Plain-English check of a rotation against the ground rules (used by the pages, model.py's filter and fake_model.py) |
| `requirements.txt` | streamlit, pandas, plotly, pulp, requests, anthropic (0.125 is the newest that runs on Python 3.9) |

The app uses the real `model.py` (`import model` at the top of ui.py). To fall back to fake numbers: `import fake_model as model`.

### The interface contract (Reference Sheet v2.01, updated Nov 15 for goals + limits)

- `evaluate(plan, farm, data, scenario, covers=None)`: score a given plan; returns `PLAN_COLUMNS` plus `cover` (rye after that year?) and `irrigation_mm`. `covers=None` = no rye.
- `solve(farm, data, goal, scenario, constraints)`: best plan for **one goal** (a key of `GOALS`: max_profit, min_water, max_worst_profit, max_soil). No weights: Robert chose explicit goals + limits (epsilon-constraint) because weighted scores aren't interpretable. `constraints` = ground rules plus `limits` ({name: fraction of the farmer's rotation}, e.g. `{"profit_min": 0.95}`), `reference_plan` (the farmer's rotation) and `worst_share`. Returns evaluate()'s table with `attrs["unmet"]` (plain sentences for limits that couldn't be met; it never crashes), `attrs["status"]` and `attrs["solver"]`.
- `solve_pareto(farm, data, scenario, constraints, n=9)`: profit-vs-water trade-off plans (min water at stepped profit floors). Not shown in the app yet.
- `backtest(plan, farm, data, covers=None)`: one row per year 1981–2024, `BACKTEST_COLUMNS` plus `total_irrigation_acre_in`; values per season, as if every season of the rotation had that year's weather.
- `table_to_plan(table)`, `table_to_covers(table)`.
- A plan is `{field_name: [crop for year 1, year 2, year 3, year 4]}`. Crops: corn, soybeans, winter_wheat, sorghum. Fields may carry `irrigated: True`.
- Water: **shortfall** (crop need minus what rain and soil supplied) on every field, plus **irrigation** on irrigated fields, in acre-inches. Scenarios: "average" (all years) and "dry" (driest 25% of seasons).
- Soil health shown in the app = points per acre over the four years, area-weighted (`totals()` in ui.py), the same measure the optimizer uses.

## Design decisions (my choices)

- **User:** a semi-experienced farmer in his 30s. Use real farming terms but keep it simple; add `help=` tooltips for anything technical.
- **Look (changed again Nov 15, "mission control"):** comfortable futuristic dashboard. Deep-space navy page `#0A0E1F` with a faint star field + blueprint grid, glassy indigo panels with a glowing top edge, NASA blue `#0B3D91` (brightened `#4F8BFF` for text/lines) and NASA red `#FC3D21` (driest seasons, warnings), mint `#5DD6B0` kept for the recommendation. Top bar with breadcrumb + location pill, 4-step "mission timeline", ring gauge for the N/44 backtest stat, mint area fill under the recommendation's profit line. **Inter** for text, **JetBrains Mono** for small uppercase labels and eyebrows (the "instrument" feel). Soft off-white text `#E6E9F5`, never pure white. Then sharpened: corners 18px panels / 12px boxes / 6px tags; gradient borders (blue → mint) on panels, steps and metric cards; gradient text on section titles and big numbers; glassy sheen on crop tiles; gradient primary button and ring arc; glow under the recommendation's chart line. Gradients live as `--grad-*` variables in style.css. Palette lives as CSS variables at the top of `style.css`, plus `.streamlit/config.toml` for Streamlit's own widgets. Text on crop-coloured tiles stays dark (`--on-crop`).
- **Crop colours:** contract.py keeps the team's original pastels (corn `#F8E68E`, soybeans `#72BFB0`, winter wheat `#F0A972`, sorghum `#C77882`), but since Nov 15 the app (now ui.py) overrides them with its own blue-white `CROP_COLORS`: corn `#EEF4FF` ice white, soybeans `#B5D3F7` pale sky, winter wheat `#93A9EE` periwinkle, sorghum `#6F8FD8` steel blue (all ≥5.5:1 contrast with the dark tile text). Similar hues, so **always** pair colour with the icon and label.
- **Colour experiment (Nov 15, latest):** crops are colourful again, each with meaning: corn `#F5C94C` golden, soybeans `#6FD49B` green, winter wheat `#E9A866` tan, sorghum `#E0879A` burgundy-rose (all ≥6.7:1 contrast). Used on tiles, field map, crop tags, a crop key under 01, coloured crop names in "Why this plan", the 1–4 step badges, metric bars (profit gold, soil green), and a new "Acres by crop, year by year" stacked-bar chart in 02. To go back to blue-white, revert the commit "Colour experiment" (the old values are in a comment by `CROP_COLORS`).
- **No mint any more (Nov 15):** the accent is ice blue-white `#BFD7FF` (recommendation, ring, buttons, sliders, "good" chips). The logo keeps its own mint/blue/red flutes. The logo floats idly (CSS `fs-float`, leaves `fs-sway`; off under prefers-reduced-motion).
- **Icons (Nov 15):** our own line-art SVGs in ui.py `CROP_SVG` (corn cob in husk, soybean pod, wheat head, sorghum seed head), drawn in `currentColor` with a light duotone fill; used on the rotation tiles and field map. Dropdowns/tables show the plain label (they can't draw SVG). contract.py's emoji `CROP_ICONS` are untouched but no longer used by the app.
- **Animated backtest chart (Nov 15):** on load the lines draw in, the fill fades in and the rain bars grow in a wave (CSS in style.css). `ui.backtest_chart(mine, rec=None)` builds it with Plotly frames: "▶ Replay 1981–2024" plays the seasons with a marker and a running tally ("profitable in N of K" for one rotation, "recommendation ahead in N of K" for two); a slider scrubs to any year. It tracks trace indices itself, so adding a trace means adding it to its `animated` list.
- **Weather icons + rocket (Nov 15):** typical/dry buttons get line-art icons via CSS masks (`.st-key-scenario button::before`, data-URI SVGs in style.css); the explanation box shows animated `WEATHER_SVG` (rain falling / sun blazing with heat shimmer). A pencil-sketch satellite (750×438 px; was a rocket, then swapped) is a data-URI SVG on `[data-testid="stApp"]::before` (z-index -1 in an isolated app) and flies behind everything every 25 s; panels are 88% opaque so it shows faintly. Both switch off under prefers-reduced-motion.
- **Motion pass (Nov 15, bottom of style.css):** header fades in; title gradient drifts; a light sweeps the 1–4 step edges in order; cards/metrics slide up on scroll (`animation-timeline: view()`, skipped where unsupported); rotation tiles pop in staggered (replay when the plan changes); recommended-plan border orbits (`@property --angle`); chips slide in; ring fills from 0 (`@property --pct`); Apply button shimmers; field-map furrows drift. All off under prefers-reduced-motion.
- **Nov 15 (later):** acreage cap in 1% steps (the old priority sliders are gone); a faint two-line data trace with travelling pulses runs along the background grid (`stApp::after`, SMIL animation inside the SVG); "Crops you'd grow" (`key="allowed_crops"`) tags get crop colours + icons from `crop_tag_css()` and pop/lift/wiggle effects.
- **Layout today (Nov 15, multi-page):** three pages from the menu at the top of the left panel: Home, Rotation evaluator, Rotation optimizer (see the Files table). The left panel (page menu, field map with "Edit fields", Ground rules) and the assistant bubble are on every page. Home has the full hero; the tool pages a compact one (`page_header(..., compact=True)`). The 1–4 steps on Home are static tiles now, not links. The "What matters most" sliders are gone: the goal and limits live in the optimizer's "01 · Your goal" card.
- **Shared state across pages:** the farmer's rotation is `st.session_state["my_plan"]` (written by the evaluator, compared against by the optimizer; `ui.apply_plan` / `ui.reset_plan` change it). Page-only widgets (weather switch, goal, limits) keep a saved copy under `"_" + key` via `ui.remember(key, default)` before drawing and `on_change=ui.save, args=(key,)`; everything else reads `ui.saved(key)`. The left-panel widgets need none of this because app.py draws them on every page.
- **Logo = page directory (Nov 15):** clicking the logo opens a "Jump to" panel of the **open page's** sections (each page passes its groups to `ui.page_header`, plus `ui.SETUP_GROUP` for the left panel). It's a `<details>`/`<summary>`, so no JavaScript. Add a section? Add an `ui.anchor("name")` (or `st.subheader(..., anchor="name")`) and a row in that page's groups.
- **Honesty rule (my call):** never show numbers the model doesn't produce (no invented scores or "conditions" bars); label sample data as sample until the real data lands.

## Gotchas

- To turn on AI answers: create `.streamlit/secrets.toml` with `ANTHROPIC_API_KEY = "..."` (never commit it). On Streamlit Cloud, paste the same line into the app's Secrets settings.
- AppTest can't rerun after clicking the assistant's buttons either (same segmented-control limitation); test it by setting `faq_history` + `faq_pending` before a fresh run.

- Streamlit gives sidebar headings **no** anchor id, so the sidebar uses our own `anchor()` markers. In-page `#` links stay in the page (Streamlit only adds target=_blank to other links).

- Streamlit's test tool (AppTest) can't rerun after clicking `st.segmented_control` (on my older Streamlit; it works on 1.67); test each state as a fresh load with `at.session_state[...]` set first. For pages: `at.run()` once, then `at.switch_page("pages/optimize.py")` and `at.run()`.
- **Switching pages wipes widget values** of the page you left, *before* the next page runs, so the old "re-save the key at the top" trick doesn't work. Use `ui.remember` / `ui.save` (see Shared state above).
- **Never link to another page with a plain `<a href>`**: it reloads the app and the farmer loses their fields and rotation. Use the page menu or `st.page_link`. In-page `#anchor` links are fine.
- **PuLP + Gurobi bug (PuLP 3.3.2):** once a model comes back Infeasible, that `pulp.GUROBI` solver object reports Infeasible for every later model. model.py makes a fresh solver object per solve; keep it that way.

- My Mac runs an **older Streamlit** (Python 3.9 caps it around 1.50). Don't use brand-new arguments such as `width="stretch"` on `st.plotly_chart`; it shows deprecation warning boxes. Call `st.plotly_chart(fig)` plainly.
- Keep files at the top level of the repo, never inside `.venv/`.
- `style.css` targets some Streamlit internals (`data-testid` names and `st-key-<key>` classes from `st.container(key=...)`). If a Streamlit upgrade breaks the look, check those selectors first.

## What's next

Done Nov 15: the farmer enters their own rotation; the dry-year switch changes the plan; "why this plan"; Robert's real `model.py` is in; the app is three pages.

1. Swap in Tebit's CSVs: a loader returning the same dict as `synthetic_data.load_data()` (format in `data/synthetic/README.md`), passed as `data`.
2. Trade-off chart from `solve_pareto` on the optimizer page.
3. Show rye cover on the rotation tiles, and carry it over on "Apply recommendation" (today Apply copies crops only).
4. More goals if wanted (MOTAD, least nitrogen, fewest changes): one entry in model.py's goal map + contract.GOALS / DEFAULT_LIMITS / GOAL_OWN_LIMITS.
5. Demo polish; deployment via Robert (main file `app.py`; the cloud uses CBC).
