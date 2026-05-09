# Streamlit Cloud Deployment

A 10-minute walkthrough to get the platform live at a public URL.

## 1. Create a GitHub repo

```bash
cd /Users/jenelle/Documents/BAAI/Spring2/Genai/project/talent-scout
git init
git add .
# Verify .env and secrets.toml are NOT in the staged list:
git status | grep -E "\.env|secrets\.toml"
# (should print nothing — they are .gitignored)
git commit -m "Initial commit: Talent Scout MVP"
```

Then create an empty repo at https://github.com/new (private OR public —
Streamlit Cloud supports both):
- Repo name: `talent-scout` (or whatever)
- Do NOT initialize with README (we already have one)

```bash
git remote add origin https://github.com/<your-user>/talent-scout.git
git branch -M main
git push -u origin main
```

## 2. Sign up for Streamlit Cloud

1. https://share.streamlit.io/ → Sign in with GitHub
2. Authorize Streamlit to read your repos

## 3. Deploy

1. Click **New app** (top right)
2. Pick the `talent-scout` repo, branch `main`, main file path `app.py`
3. Click **Advanced settings** → **Python version** = `3.13`
4. Click **Secrets** and paste:

```toml
ANTHROPIC_API_KEY = "sk-ant-xxx"
GITHUB_TOKEN = "ghp_xxx"
LANGSMITH_API_KEY = "lsv2_pt_xxx"
LANGSMITH_TRACING = "true"
LANGSMITH_PROJECT = "talent-scout"
```

(Use the keys from your local `.env`, NOT the placeholders.)

5. Click **Deploy**

First deploy takes ~3-5 minutes (installs deps from requirements.txt).
You'll get a URL like `https://talent-scout-xxxxx.streamlit.app/`.

## 4. Smoke test the deployed URL

1. Open the URL in a private/incognito window
2. Verify all 5 tabs render (Run / Architecture / Evaluation / FinOps / Scoring)
3. In **Run Agent**, submit:
   - Repo owner: `tokio-rs`
   - Repo name: `axum`
   - Criteria: `Find good Rust contributors`
   - Top N: `5`
4. Verify clarify_node interrupt fires, you can submit follow-up,
   and the agent completes (~45s)

## 5. Optional: restrict access

Streamlit Cloud free tier exposes a public URL by default. To gate access:

- **Option A** (cheapest): Settings → Sharing → "Only specific viewers"
  → enter instructor's email
- **Option B**: add a password gate at the top of `app.py` using
  `st.text_input("Password", type="password")` checked against a secret

## 6. For the demo / video

Record a 5-minute screen capture (Loom / QuickTime) walking through:
- Inputs form + Run Agent
- The 5 status blocks streaming live (slow it down — this is the
  "agent reasoning is visible, not a chatbot" beat)
- Clarify interrupt + resume
- Final candidates table + per-candidate predicate trace
- Architecture tab (mermaid diagram + ADRs)
- Evaluation tab (Spearman ρ vs ground truth)
- FinOps tab (cost-per-success)
- Scoring Rationale tab (ablation table — point out the
  "merged_pr_count is mildly counter-productive" finding)

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Build fails on `pip install` | Python version mismatch | Set Python 3.13 in Advanced Settings |
| Live mode says "API key missing" | Secrets not saved | Settings → Secrets, verify TOML syntax (quoted strings) |
| Agent times out at 30s on first run | GitHub Search rate limit | Wait 1 minute, retry — limit is 30/min not 30/hr |
| `streamlit_mermaid` import error | Cloud cached old deps | Settings → Reboot app |
