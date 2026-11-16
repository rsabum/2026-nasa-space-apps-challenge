# Deploying Field Shift to Streamlit Community Cloud

For Robert (the repo owner). Streamlit Cloud needs admin rights on the GitHub repo, so
the deploy has to come from your account. It takes about five minutes.

## 1. Deploy

1. Go to https://share.streamlit.io and sign in with the GitHub account that owns
   `rsabum/2026-nasa-space-apps-challenge`.
2. **Create app → Deploy a public app from GitHub.**
3. Settings:

   | Field | Value |
   |---|---|
   | Repository | `rsabum/2026-nasa-space-apps-challenge` |
   | Branch | `robert` (the branch with this merge; or whichever branch you merge it into) |
   | Main file path | `app.py` |
   | App URL | anything short, e.g. `field-shift` |
   | Advanced settings → Python version | **3.11** |

4. Press **Deploy**. The first build takes 2–4 minutes (it installs `requirements.txt`).

**Before deploying**, on your Mac:

```bash
source .venv/bin/activate
python real_data.py check   # must say 5 of 5: the app then runs on the real data in data/real/
python test_app.py          # model contract + every page loads; exit code 0 = good to deploy
```

The real tables in `data/real/` must be **committed and pushed**: the cloud only sees what's
in the repo (otherwise it falls back to the sample data, and the top bar says "Sample data").
The cloud has no Gurobi licence, so the optimizer runs on CBC there (same answers, a bit
slower; `gurobipy` is deliberately not in `requirements.txt`).

## 2. Optional: turn on the AI assistant

Without a key the "Ask Field Shift" bubble still works, using built-in quick answers.
To get live Claude answers:

1. App menu (⋮) → **Settings → Secrets**.
2. Paste one line and save:

   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```

The app picks it up within a minute. Each question is a small paid API call.

## 3. Check it

- Open the app URL. The header should read "Field Shift" with the floating logo.
- The top bar says **Real data**.
- **Rotation evaluator:** click a tile, pick a crop; scroll to **02 · Tested on NASA weather** and
  press **▶ Replay**.
- **Rotation optimizer:** a recommended plan appears; **Use this rotation** takes you to the
  evaluator with it loaded.
- Open the assistant (bottom right): the header shows "✦ Claude AI" if the key is set,
  "Quick answers" if not.

## 4. Updating later

Every `git push` to the deployed branch redeploys automatically. If the look ever breaks
after a redeploy, the cause is almost always a Streamlit upgrade: `requirements.txt` pins
`streamlit==1.50.0` and `plotly==7.1.0` for that reason, so keep those pins unless the
CSS in `style.css` is updated with them.

## If the build fails

- **"No module named model / real_data / crop_sim"**: make sure `model.py`, `crop_sim.py`,
  `real_data.py` and `synthetic_data.py` are committed on the deployed branch.
- **"Sample data" in the top bar**: `data/real/` isn't in the repo, or a file there fails
  `python real_data.py check`.
- **Memory limit**: Community Cloud allows ~1 GB. If PuLP solves are heavy, cut the number
  of trade-off options `solve_pareto` returns.
- Logs are under **Manage app** (bottom right of the running app).
