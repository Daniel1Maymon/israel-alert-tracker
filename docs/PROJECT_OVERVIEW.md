# Project Overview

## Purpose

**Tzeva Adom Monitor** is a real-time dashboard for Israeli rocket alert data (צבע אדום — "Red Color"). It connects to the unofficial tzevaadom.co.il WebSocket API, persists all incoming alerts to a local SQLite database, and presents them in a live-updating web UI.

## Problem It Solves

The official Home Front Command (Pikud HaOref) app does not expose alert history or provide a way to monitor events programmatically. This system captures the raw event stream in real time, stores it durably, and displays it in a structured, searchable table.

## Key Capabilities

- **Live ingestion** via WebSocket — alerts appear within milliseconds of being issued.
- **Dual-source redundancy** — a fallback REST poller targets the official `oref.org.il` government endpoint when the WebSocket is down, ensuring no alert is missed.
- **Persistent history** — all alerts are stored in SQLite; the last 100 are loaded on page open.
- **Searchable UI** — filter by city name in real time.
- **Bilingual** — full English / Hebrew (RTL) toggle with no page reload.
- **Alert classification** — distinguishes live sirens (`ALERT`), early warnings (`SYSTEM_MESSAGE`), and all-clear messages (green highlight).

## Scope

Single-machine, single-user tool. Not designed for multi-user deployment or high availability. Production hardening (proper WSGI server, auth, etc.) is out of scope.

## How to Run

```bash
cd Desktop/my_projects/tzevaadom-ws
python3 -m venv .venv && .venv/bin/pip install flask websockets
.venv/bin/python app.py
# Open http://localhost:5000
```

Python 3.10+ required. No environment variables or config files needed.
