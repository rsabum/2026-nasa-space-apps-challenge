"""Field Shift: Streamlit app (owner: Claude-Thomas)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import fake_model as model  # switch to `import model` when Robert's model.py is ready
from contract import (CONSTRAINTS, CROP_COLORS, CROPS, FARM, WEIGHTS,
                      baseline_plan, normalize_weights)

st.set_page_config(page_title="Field Shift", layout="wide")
st.title("Field Shift")
st.caption("Test a crop rotation against 40+ years of NASA climate data, then find a better one.")

# ---------- Sidebar: inputs ----------
with st.sidebar:
    st.header("Your farm")
    fields = st.data_editor(
        pd.DataFrame(FARM["fields"]),
        column_config={"last_crop": st.column_config.SelectboxColumn(options=CROPS)},
        num_rows="dynamic", hide_index=True, key="fields",
    )

    st.header("Priorities")
    weights = {
        "profit": st.slider("Profit", 0, 10, WEIGHTS["profit"]),
        "water": st.slider("Water", 0, 10, WEIGHTS["water"]),
        "soil": st.slider("Soil health", 0, 10, WEIGHTS["soil"]),
    }

    st.header("Constraints")
    allowed = st.multiselect("Crops allowed", CROPS, CONSTRAINTS["allowed_crops"])
    no_repeat = st.checkbox("No same crop two years running", CONSTRAINTS["no_repeat"])

    scenario = st.radio("Optimize for", ["average", "dry"], horizontal=True)

farm = {**FARM, "fields": fields.to_dict("records")}
constraints = {**CONSTRAINTS, "allowed_crops": allowed, "no_repeat": no_repeat}

# ---------- Run the model ----------
try:
    plan_table = model.solve(farm, None, normalize_weights(weights), scenario, constraints)
    base_table = model.evaluate(baseline_plan(farm), farm, None, scenario)
except Exception as e:  # never show a traceback to a judge
    st.error(f"The model could not run: {e}")
    st.stop()

# ---------- Rotation grid ----------
st.subheader("Recommended rotation")
grid = plan_table.pivot(index="field", columns="year", values="crop").reindex(plan_table["field"].unique())
color_index = {c: i for i, c in enumerate(CROP_COLORS)}
n = len(CROP_COLORS)
colorscale = []
for c, i in color_index.items():
    colorscale += [[i / n, CROP_COLORS[c]], [(i + 1) / n, CROP_COLORS[c]]]
fig = go.Figure(go.Heatmap(
    z=grid.apply(lambda col: col.map(color_index)).values,
    x=[f"Year {y}" for y in grid.columns], y=grid.index,
    text=grid.values, texttemplate="%{text}", textfont={"size": 14},
    colorscale=colorscale, zmin=0, zmax=n, showscale=False, xgap=3, ygap=3,
))
fig.update_layout(height=60 * len(grid) + 60, margin=dict(l=0, r=0, t=10, b=0), yaxis=dict(autorange="reversed"))
st.plotly_chart(fig, width="stretch")

# ---------- Metrics vs baseline ----------
def totals(t):
    return (t["profit_usd"].sum(),
            (t["water_shortfall_mm"] * t["acres"]).sum() / 25.4,
            t["soil_score_change"].sum())

p, w, s = totals(plan_table)
bp, bw, bs = totals(base_table)
c1, c2, c3 = st.columns(3)
c1.metric("Profit, 4 years", f"${p:,.0f}", f"{p - bp:+,.0f} vs corn–soybean")
c2.metric("Water shortfall", f"{w:,.0f} acre-in", f"{w - bw:+,.0f}", delta_color="inverse")
c3.metric("Soil score change", f"{s:+.1f}", f"{s - bs:+.1f}")

# ---------- Backtest ----------
st.subheader("How each rotation would have done, 1981–2024")
bt_plan = model.backtest(model.table_to_plan(plan_table), farm)
bt_base = model.backtest(baseline_plan(farm), farm)
wins = int((bt_plan["total_profit_usd"] > bt_base["total_profit_usd"]).sum())
st.write(f"The recommended rotation beat your current rotation in **{wins} of {len(bt_plan)}** years.")
bt = go.Figure()
bt.add_trace(go.Scatter(x=bt_base["year"], y=bt_base["total_profit_usd"], name="Current rotation",
                        line=dict(color="#888")))
bt.add_trace(go.Scatter(x=bt_plan["year"], y=bt_plan["total_profit_usd"], name="Recommended",
                        line=dict(color=CROP_COLORS["soybeans"], width=3)))
bt.update_layout(height=320, yaxis_title="Profit (USD)", margin=dict(l=0, r=0, t=10, b=0),
                 legend=dict(orientation="h"))
st.plotly_chart(bt, width="stretch")
st.caption("Data: fake values until the real model and NASA POWER data are connected.")

with st.expander("Plan details"):
    st.dataframe(plan_table, hide_index=True)
