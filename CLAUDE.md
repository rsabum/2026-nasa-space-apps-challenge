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
| `assets/logo.svg`, `assets/icon.png` | Our original logo (classical column with three flutes and a sprout). Nov 15: recoloured to the theme: NASA-blue gradient tile, mint / blue / NASA-red gradient flutes, mint-to-blue sprout, sharper corners. icon.png is rendered from the SVG (`qlmanage -t -s 256`, corners masked with Pillow). |
| `.streamlit/config.toml` | Dark theme colours, font name, corner radius (restart Streamlit after editing) |
| `assistant.py` | The "Ask Field Shift" chat bubble (bottom right). Claude mode (Opus 5.5, streamed, low effort, server-side refusal fallback) when `ANTHROPIC_API_KEY` is in `.streamlit/secrets.toml` (git-ignored) or the environment; otherwise keyword-matched quick answers. Both use only the live numbers app.py passes in (`faq_context`). |
| `rules.py` | Plain-English check of a rotation against the ground rules (used by app.py and fake_model.py) |
| `requirements.txt` | streamlit, pandas, plotly, pulp, requests, anthropic (0.125 is the newest that runs on Python 3.9) |

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
- **Look (changed again Nov 15, "mission control"):** comfortable futuristic dashboard. Deep-space navy page `#0A0E1F` with a faint star field + blueprint grid, glassy indigo panels with a glowing top edge, NASA blue `#0B3D91` (brightened `#4F8BFF` for text/lines) and NASA red `#FC3D21` (driest seasons, warnings), mint `#5DD6B0` kept for the recommendation. Top bar with breadcrumb + location pill, 4-step "mission timeline", ring gauge for the N/44 backtest stat, mint area fill under the recommendation's profit line. **Inter** for text, **JetBrains Mono** for small uppercase labels and eyebrows (the "instrument" feel). Soft off-white text `#E6E9F5`, never pure white. Then sharpened: corners 18px panels / 12px boxes / 6px tags; gradient borders (blue → mint) on panels, steps and metric cards; gradient text on section titles and big numbers; glassy sheen on crop tiles; gradient primary button and ring arc; glow under the recommendation's chart line. Gradients live as `--grad-*` variables in style.css. Palette lives as CSS variables at the top of `style.css`, plus `.streamlit/config.toml` for Streamlit's own widgets. Text on crop-coloured tiles stays dark (`--on-crop`).
- **Crop colours:** contract.py keeps the team's original pastels (corn `#F8E68E`, soybeans `#72BFB0`, winter wheat `#F0A972`, sorghum `#C77882`), but since Nov 15 app.py overrides them with its own blue-white `CROP_COLORS`: corn `#EEF4FF` ice white, soybeans `#B5D3F7` pale sky, winter wheat `#93A9EE` periwinkle, sorghum `#6F8FD8` steel blue (all ≥5.5:1 contrast with the dark tile text). Similar hues, so **always** pair colour with the icon and label.
- **No mint any more (Nov 15):** the accent is ice blue-white `#BFD7FF` (recommendation, ring, buttons, sliders, "good" chips). The logo keeps its own mint/blue/red flutes. The logo floats idly (CSS `fs-float`, leaves `fs-sway`; off under prefers-reduced-motion).
- **Icons (Nov 15):** our own line-art SVGs in app.py `CROP_SVG` (corn cob in husk, soybean pod, wheat head, sorghum seed head), drawn in `currentColor` with a light duotone fill; used on the rotation tiles and field map. Dropdowns/tables show the plain label (they can't draw SVG). contract.py's emoji `CROP_ICONS` are untouched but no longer used by app.py.
- **Animated backtest chart (Nov 15):** on load the lines draw in, the fill fades in and the rain bars grow in a wave (CSS in style.css). `add_replay()` adds Plotly frames: "▶ Replay 1981–2024" plays the seasons with a marker and a running "ahead in N of K seasons" tally; a slider scrubs to any year. Trace order matters to the frames (0 mine, 1 floor, 2 rec, 3 glow, 4 rain, 5 marker).
- **Weather icons + rocket (Nov 15):** typical/dry buttons get line-art icons via CSS masks (`.st-key-scenario button::before`, data-URI SVGs in style.css); the explanation box shows animated `WEATHER_SVG` (rain falling / sun blazing with heat shimmer). A pencil-sketch satellite (750×438 px; was a rocket, then swapped) is a data-URI SVG on `[data-testid="stApp"]::before` (z-index -1 in an isolated app) and flies behind everything every 25 s; panels are 88% opaque so it shows faintly. Both switch off under prefers-reduced-motion.
- **Motion pass (Nov 15, bottom of style.css):** header fades in; title gradient drifts; a light sweeps the 1–4 step edges in order; cards/metrics slide up on scroll (`animation-timeline: view()`, skipped where unsupported); rotation tiles pop in staggered (replay when the plan changes); recommended-plan border orbits (`@property --angle`); chips slide in; ring fills from 0 (`@property --pct`); Apply button shimmers; field-map furrows drift. All off under prefers-reduced-motion.
- **Nov 15 (later):** priority sliders are 0.0–10.0 in 0.1 steps (acreage cap in 1% steps); a faint two-line data trace with travelling pulses runs along the background grid (`stApp::after`, SMIL animation inside the SVG); "Crops you'd grow" (`key="allowed_crops"`) tags get crop colours + icons from `crop_tag_css()` and pop/lift/wiggle effects.
- **Clickable 1–4 steps:** links to #rotation, #weather, #recommendation, #backtest.
- **Layout today (Nov 15):** hero with logo, "NASA climate-powered crop rotation planner" subtitle, NASA POWER + Team Athens badges, and a 4-step story strip (Your rotation → NASA weather → Optimizer → A better plan, tested). Sidebar: field map with "Edit fields" popover, "What matters most" sliders, "Ground rules" (crops, no back-to-back, soybean year, acreage cap). Main: drought switch card (segmented control: typical/dry) → "01 · Your rotation" (tiles + "Edit rotation" popover, rule check, Reset after apply) → "02 · Optimized rotation" (the star: glowing card, result chips incl. water stress, why-this-plan, "Apply recommendation") → three metric cards → "03 · Tested on NASA weather" (N/44 stat, profit lines over rain bars, driest season marked) → raw-numbers expander → "Data sources" card (NASA POWER, Web Soil Survey, CropScape, NASS).
- **Logo = page directory (Nov 15):** clicking the logo opens a "Jump to" panel (`DIRECTORY` + `directory_html()` in app.py), grouped Set up / Plan / Proof. It's a `<details>`/`<summary>`, so no JavaScript. Links go to anchor ids: fields, priorities, rules (sidebar), weather, rotation, recommendation, numbers, backtest, details, sources. Add a section? Add an `anchor("name")` (or `st.subheader(..., anchor="name")`) and a row in `DIRECTORY`.
- **Honesty rule (my call):** never show numbers the model doesn't produce (no invented scores or "conditions" bars); label sample data as sample until the real data lands.

## Gotchas

- To turn on AI answers: create `.streamlit/secrets.toml` with `ANTHROPIC_API_KEY = "..."` (never commit it). On Streamlit Cloud, paste the same line into the app's Secrets settings.
- AppTest can't rerun after clicking the assistant's buttons either (same segmented-control limitation); test it by setting `faq_history` + `faq_pending` before a fresh run.

- Streamlit gives sidebar headings **no** anchor id, so the sidebar uses our own `anchor()` markers. In-page `#` links stay in the page (Streamlit only adds target=_blank to other links).

- Streamlit's test tool (AppTest) can't rerun after clicking `st.segmented_control`; test each state as a fresh load with `at.session_state[...]` set first.

- My Mac runs an **older Streamlit** (Python 3.9 caps it around 1.50). Don't use brand-new arguments such as `width="stretch"` on `st.plotly_chart`; it shows deprecation warning boxes. Call `st.plotly_chart(fig)` plainly.
- Keep files at the top level of the repo, never inside `.venv/`.
- `style.css` targets some Streamlit internals (`data-testid` names and `st-key-<key>` classes from `st.container(key=...)`). If a Streamlit upgrade breaks the look, check those selectors first.

## What's next

1. **Part 3: let the farmer enter their own rotation.** A grid (fields × years) where they pick a crop per cell, then the app backtests *their* rotation alongside the suggestion. This is the core of the team objective.
2. Make the "typical year / dry year" switch visibly change things; add a short "why this plan" sentence.
3. Swap in Robert's `model.py` and Tebit's CSVs when ready.
4. Sunday: trade-off chart from `solve_pareto`, demo polish, deployment via Robert.
