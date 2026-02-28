# Deployment Guide

This guide covers publishing the project to GitHub and deploying it to Railway.

---

## 1. Push to GitHub

If you haven't already pushed the project:

```bash
# Initialize git and commit everything
git init
git add .
git commit -m "Initial commit"

# Create a new GitHub repo and push
gh repo create israel-alert-tracker --public --source=. --remote=origin --push
```

Or create the repo manually at [github.com/new](https://github.com/new), then:

```bash
git remote add origin https://github.com/YOUR_USERNAME/israel-alert-tracker.git
git push -u origin main
```

---

## 2. Deploy to Railway

### Step 1 — Create a Railway account

Go to [railway.app](https://railway.app) and sign up (you can use your GitHub account).

---

### Step 2 — Create a new project

1. From the Railway dashboard click **New Project**
2. Choose **Deploy from GitHub repo**
3. Authorize Railway to access your GitHub account if prompted
4. Select **israel-alert-tracker**

Railway will detect the `Procfile` automatically and start a build.

---

### Step 3 — Attach a Volume (persistent database)

Without a Volume, the SQLite database resets every time Railway redeploys. To persist your alert history:

1. In your Railway project, click **New** → **Volume**
2. Set the mount path to `/data`
3. Click **Add**

---

### Step 4 — Set environment variables

In your Railway service, go to **Variables** and add:

| Variable | Value |
|---|---|
| `DB_PATH` | `/data/alerts.db` |

`PORT` is injected by Railway automatically — do not set it manually.

---

### Step 5 — Deploy

Railway triggers a deploy automatically after you set the variables. You can also click **Deploy** manually.

Once the build finishes, Railway assigns a public URL like:

```
https://israel-alert-tracker-production.up.railway.app
```

Click it to open your live dashboard.

---

## 3. Automatic Deploys (optional)

By default Railway re-deploys every time you push to the `main` branch on GitHub. To disable this, go to **Settings → Source** and turn off **Auto Deploy**.

To trigger a manual deploy at any time:

```bash
git push origin main   # Railway picks it up automatically
```

---

## 4. Updating the App

```bash
# Make your changes locally, then:
git add .
git commit -m "describe your change"
git push origin main
```

Railway will rebuild and redeploy within ~1 minute. Alert history is preserved because it lives on the Volume.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `PORT` | Auto (Railway) | `5000` | HTTP port gunicorn listens on |
| `DB_PATH` | Yes (Railway) | `alerts.db` | Path to the SQLite database file |

---

## Troubleshooting

**Build fails — module not found**
Make sure `requirements.txt` is committed and lists `flask`, `websockets`, and `gunicorn`.

**Database resets on every deploy**
You haven't attached a Volume, or `DB_PATH` doesn't point to the Volume mount path.

**WebSocket not connecting**
The tzevaadom.co.il WebSocket requires outbound internet access. Railway allows this by default. Check the Railway logs (`railway logs`) for `[WS] connected`.

**App crashes immediately**
Check logs in the Railway dashboard under **Deployments → View Logs**. Common cause: `DB_PATH` directory doesn't exist yet — make sure the Volume is attached before the first deploy.
