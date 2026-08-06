# Kaggle GPU Quota Dashboard

A zero-server, GitHub-Pages-hosted dashboard that shows your remaining Kaggle weekly GPU hours.
GitHub Actions fetches the data on a schedule; your friend can request an on-demand refresh from any browser.

```
┌─────────────────────────────────┐
│      Kaggle GPU Quota           │
│                                 │
│          ██████░░░░             │
│            62%                  │
│  Remaining: 18.6 h  Total: 30 h │
│  Last updated: 6 Aug 2026 09:00 │
│                                 │
│    [ ↻  Request refresh ]       │
└─────────────────────────────────┘
```

---

## How it works

| Component | Role |
|-----------|------|
| **GitHub Actions** | Runs `fetch_quota.py` every 6 hours (and on demand) |
| **`fetch_quota.py`** | Authenticates to Kaggle's API, parses GPU quota, writes `status.json` |
| **`status.json`** | Plain JSON file committed to the repo; served by GitHub Pages |
| **`index.html` + JS** | Reads `status.json`, renders the gauge; calls GitHub API to trigger a refresh |
| **GitHub Secrets** | Store `KAGGLE_USERNAME` and `KAGGLE_KEY` — never exposed in the repo |

The Refresh button calls the GitHub Actions API (`workflow_dispatch`) using a
**Personal Access Token you paste into the browser once** — it is stored only in
`localStorage`, never in the repository.

---

## Setup (step by step)

### 1 · Get your Kaggle API credentials

1. Log in at [kaggle.com](https://www.kaggle.com).
2. Click your profile picture → **Settings**.
3. Scroll to **API** → click **Create New Token**.
4. A file called `kaggle.json` downloads. Open it — it looks like:
   ```json
   { "username": "yourname", "key": "abc123..." }
   ```
5. Note the two values (`username` and `key`). **Do not commit this file.**

---

### 2 · Create a GitHub repository

1. Go to [github.com/new](https://github.com/new).
2. Name it (e.g. `kaggle-gpu-dashboard`). Choose **Public** (required for free GitHub Pages).
3. Do **not** initialize with a README — you'll push this repo's files instead.

---

### 3 · Push this project to GitHub

```bash
cd kaggle_gpu_check          # this folder
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

---

### 4 · Edit `config.json`

Open `config.json` and replace the placeholder values:

```json
{
  "repo_owner": "YOUR_GITHUB_USERNAME",
  "repo_name":  "YOUR_REPO_NAME",
  "workflow_id": "update-kaggle-quota.yml",
  "branch": "main"
}
```

Commit and push:

```bash
git add config.json
git commit -m "set repo owner and name"
git push
```

---

### 5 · Add GitHub Secrets

1. Open your repo on GitHub → **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret** and add:

   | Secret name | Value |
   |-------------|-------|
   | `KAGGLE_USERNAME` | The `username` from your `kaggle.json` |
   | `KAGGLE_KEY` | The `key` from your `kaggle.json` |

---

### 6 · Enable GitHub Pages

1. In your repo → **Settings** → **Pages**.
2. Under **Source**, select **Deploy from a branch**.
3. Branch: `main`, folder: `/ (root)`.
4. Click **Save**.

GitHub will show a URL like:
```
https://YOUR_USERNAME.github.io/YOUR_REPO/
```

It may take 1–2 minutes to go live.

---

### 7 · Trigger the first data fetch

1. Go to your repo → **Actions** → **Update Kaggle GPU Quota**.
2. Click **Run workflow** → **Run workflow**.
3. Wait ~30 seconds for it to complete.
4. Reload your GitHub Pages URL — you should see your GPU hours.

After this, the workflow runs automatically every 6 hours.

---

### 8 · Set up the Refresh button (optional)

This lets your friend request fresh data from the dashboard without logging in to GitHub.

**Create a fine-grained Personal Access Token:**

1. Go to [github.com/settings/tokens?type=beta](https://github.com/settings/tokens?type=beta).
2. Click **Generate new token**.
3. **Token name**: `kaggle-dashboard-refresh`
4. **Expiration**: 1 year (or no expiration)
5. **Repository access**: select **Only select repositories** → choose your dashboard repo.
6. **Permissions** → **Actions** → set to **Read and write**.
7. Click **Generate token** and copy it.

**Share the token with your friend (or use it yourself):**

1. Open the dashboard in a browser.
2. Click **Request refresh**.
3. Paste the token and click **Save & refresh**.
4. The token is saved in the browser's `localStorage`. You won't need to paste it again on that device.

> **Security note:** This token can only trigger GitHub Actions on this specific repository.
> The worst a bad actor can do with it is spam-trigger your workflow (consuming free Actions minutes).
> It cannot read secrets, access your Kaggle credentials, or do anything else.

---

## File reference

| File | Purpose |
|------|---------|
| `index.html` | Dashboard UI |
| `style.css` | Dark-theme styling |
| `script.js` | Data rendering, gauge animation, GitHub API trigger |
| `status.json` | Machine-readable quota data (updated by the workflow) |
| `config.json` | Non-secret repo config (owner, name, workflow ID) |
| `fetch_quota.py` | Python script run by GitHub Actions |
| `.github/workflows/update-kaggle-quota.yml` | GitHub Actions workflow |

---

## Troubleshooting

### Dashboard shows "Data not yet fetched"
Run the workflow manually (Step 7 above).

### Workflow fails with HTTP 401
Your `KAGGLE_USERNAME` or `KAGGLE_KEY` secret is wrong. Re-add them.

### Workflow fails with "All endpoints failed"
Kaggle may have changed their internal API path. Open the workflow run log, copy
the raw error, and [open an issue](../../issues) with it.

### `status.json` shows `null` for `remaining_hours`
The endpoint responded but the field names didn't match any known format.
Check the `raw_response` field in `status.json` and open an issue with its contents.

### Refresh button says "Token rejected"
Your fine-grained PAT may have expired or been revoked. Create a new one (Step 8).

---

## Local development

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install requests

# Set creds in your shell (never commit these)
export KAGGLE_USERNAME=yourname
export KAGGLE_KEY=yourkey

python fetch_quota.py
cat status.json
```

Then open `index.html` in a browser (or use `python -m http.server`).
