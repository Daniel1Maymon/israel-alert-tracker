# Israel Alert Tracker 🚨

Real-time dashboard for Israeli rocket alerts (צבע אדום — "Tzeva Adom"). Connects to the tzevaadom.co.il WebSocket stream, persists every alert to a local SQLite database, and displays them in a live-updating web UI.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Flask](https://img.shields.io/badge/Flask-latest-lightgrey) ![License](https://img.shields.io/badge/license-MIT-green)

---

## Features

- **Live ingestion** — alerts appear within milliseconds via WebSocket
- **Dual-source redundancy** — automatic fallback to the official oref.org.il REST API when the WebSocket is down
- **Persistent history** — all alerts stored in SQLite; last 100 loaded on page open
- **Area filter bar** — one-click chip filter by geographic zone (Tavor, Dan, Sharon, etc.)
- **City search** — real-time text filter with area name shown next to each city
- **Bilingual** — full Hebrew (RTL) / English toggle with no page reload
- **Alert classification** — distinguishes live sirens, early warnings, drills, and all-clear messages
- **Persistent UI state** — language, active area filter, and search query survive page refresh

---

## Screenshots

| English | Hebrew (RTL) |
|---|---|
| *(live alerts table with area chips)* | *(same view in Hebrew)* |

---

## How It Works

```
tzevaadom.co.il WebSocket
        │
        ▼
  ws_listener (thread)  ──►  save_alert()  ──►  alerts.db
        │                                            │
        ▼                                            ▼
   broadcast() ──► SSE /stream         GET /history (polled every 2s)
                                                     │
  oref.org.il REST (fallback)                        ▼
        │                                      index.html
        ▼                                   (vanilla JS SPA)
  rest_poller (thread)
```

Two message types arrive from the WebSocket:
- **`ALERT`** — live siren with a list of affected cities
- **`SYSTEM_MESSAGE`** — early warning (~2 min before sirens) or all-clear

Geographic zones are resolved at render time by joining city data from the [pikud-haoref-api](https://github.com/eladnava/pikud-haoref-api) city list.

---

## Getting Started

**Requirements:** Python 3.10+

```bash
git clone https://github.com/Daniel1Maymon/israel-alert-tracker
cd israel-alert-tracker

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

python3 app.py
# Open http://localhost:5000
```

No environment variables or config files required for local development.

---

## Deployment (Railway)

1. Create a new Railway project and connect this repo
2. Attach a **Volume** and set the `DB_PATH` environment variable to the mount path (e.g. `/data/alerts.db`) so the database persists across deploys
3. Railway auto-detects the `Procfile` and starts gunicorn

```
web: gunicorn app:app --worker-class gthread --workers 1 --threads 4 --bind 0.0.0.0:$PORT
```

`PORT` is injected automatically by Railway.

---

## Project Structure

```
israel-alert-tracker/
├── app.py               # Backend — Flask, WebSocket listener, REST poller, SQLite
├── templates/
│   └── index.html       # Frontend — single-page app (vanilla JS)
├── requirements.txt
├── Procfile
└── docs/                # Architecture & data-flow documentation
```

---

## Data Sources

| Source | URL | Used when |
|---|---|---|
| tzevaadom WebSocket | `wss://ws.tzevaadom.co.il/socket` | Always (primary) |
| oref.org.il REST | `oref.org.il/WarningMessages/alert/alerts.json` | WebSocket disconnected |
| City data | pikud-haoref-api (GitHub) | Loaded once at startup |
