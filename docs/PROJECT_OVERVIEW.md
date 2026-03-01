# Project Overview

## Purpose

**Tzeva Adom Monitor** is a real-time dashboard for Israeli rocket alert data (צבע אדום — "Red Color"). It connects to the unofficial tzevaadom.co.il WebSocket API, persists all incoming alerts to a local SQLite database, and presents them in a live-updating web UI.

## Problem It Solves

The official Home Front Command (Pikud HaOref) app does not expose alert history or provide a way to monitor events programmatically. This system captures the raw event stream in real time, stores it durably, and displays it in a structured, searchable, filterable table.

## Key Capabilities

- **Live ingestion** via WebSocket — alerts appear within milliseconds via SSE push.
- **Dual-source redundancy** — a fallback REST poller targets the official `oref.org.il` government endpoint when the WebSocket is down, ensuring no alert is missed.
- **Persistent history** — all alerts stored in SQLite; full history loaded and paginated on page open.
- **Zone enrichment at ingest** — geographic zone resolved server-side and stored in the DB; no client-side lookup required.
- **Shelter Stay Duration Meter** — per-area shelter state machine maintained server-side in a `shelter_intervals` table; live timer shown when area is in shelter.
- **Multi-area filter** — chip bar (desktop) and dropdown (mobile) for filtering by one or more geographic zones; multi-select supported.
- **City search** — real-time text filter by city name.
- **Pagination** — table pages 10 rows at a time.
- **Bilingual** — full English / Hebrew (RTL) toggle with no page reload.
- **Alert classification** — distinguishes live sirens (`ALERT`), early warnings, drills, and all-clear messages (green highlight).

## Scope

Single-machine, single-user tool. Not designed for multi-user deployment or high availability. Production hardening (auth, rate limiting, etc.) is out of scope.

## How to Run

```bash
cd Desktop/my_projects/tzevaadom-ws
python3 -m venv .venv && .venv/bin/pip install flask websockets gunicorn
.venv/bin/python app.py
# Open http://localhost:5000
```

Python 3.10+ required. No environment variables needed for local development.

## Deployment

Railway. Set `DB_PATH=/data/alerts.db` and attach a Volume for persistence. See `DEPLOY.md`.
