# Technology Stack

## Backend

| Component | Technology | Version | Notes |
|---|---|---|---|
| Language | Python | 3.10+ | Uses `match`-free async; compatible with 3.10–3.13 |
| Web framework | Flask | 3.1.3 | Werkzeug dev server with debug/auto-reload |
| WebSocket client | websockets | 16.0 | Async; runs inside its own event loop in a daemon thread |
| Database | SQLite | (stdlib) | Single-file, zero-config; accessed via `sqlite3` stdlib module |
| HTTP client | `urllib.request` | (stdlib) | Used for REST backup poll and city list fetch |
| Concurrency | `threading` + `asyncio` | (stdlib) | WebSocket uses asyncio; REST poller uses blocking sleep loop |

## Frontend

| Component | Technology | Notes |
|---|---|---|
| UI | Vanilla HTML/CSS/JS | No framework; no build step |
| Data updates | HTTP polling (`fetch`) | 2-second interval against `/history?since=<ts>` |
| Elapsed timer | `setInterval` (1 s) | Updates all visible rows simultaneously |
| i18n | In-memory JS object | English + Hebrew; RTL via `<html dir="rtl">` |
| City search | Client-side string match | Filters on cached `data-cities-text` attribute |

## External Services

| Service | URL | Purpose |
|---|---|---|
| Tzevaadom WebSocket | `wss://ws.tzevaadom.co.il/socket?platform=ANDROID` | Primary real-time alert stream |
| Oref REST API | `https://www.oref.org.il/WarningMessages/alert/alerts.json` | Backup alert source (Israeli government) |
| City data | `https://raw.githubusercontent.com/eladnava/pikud-haoref-api/master/cities.json` | Static city ID → name mapping (1,449 entries) |

## Runtime Requirements

- Python 3.10+
- `flask` and `websockets` packages (no other third-party dependencies)
- Network access to the three external services listed above
- Write access to the working directory (for `alerts.db`)

## Not Used

- No task queue (Celery, RQ, etc.)
- No ORM (raw SQL only)
- No frontend build toolchain
- No container/Docker setup
- No authentication layer
