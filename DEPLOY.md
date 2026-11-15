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
   | Branch | `claude` |
   | Main file path | `app.py` |
   | App URL | anything short, e.g. `field-shift` |
   | Advanced settings → Python version | **3.11** |

4. Press **Deploy**. The first build takes 2–4 minutes (it installs `requirements.txt`).

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
- Click **Dry year**, then scroll to **03 · Tested on NASA weather** and press **▶ Replay**.
- Open the assistant (bottom right): the header shows "✦ Claude AI" if the key is set,
  "Quick answers" if not.

## 4. Updating later

Every `git push` to the `claude` branch redeploys automatically. If the look ever breaks
after a redeploy, the cause is almost always a Streamlit upgrade: `requirements.txt` pins
`streamlit==1.50.0` and `plotly==7.1.0` for that reason, so keep those pins unless the
CSS in `style.css` is updated with them.

## If the build fails

- **"No module named model"**: `app.py` still imports `fake_model`; that's fine for a
  demo. If it imports `model`, make sure `model.py` is committed on the `claude` branch.
- **Memory limit**: Community Cloud allows ~1 GB. If PuLP solves are heavy, cut the number
  of trade-off options `solve_pareto` returns.
- Logs are under **Manage app** (bottom right of the running app).
