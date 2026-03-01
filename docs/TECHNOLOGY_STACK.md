# Technology Stack

## Backend

| Component | Technology | Notes |
|---|---|---|
| Language | Python 3.10+ | |
| Web framework | Flask | Served by gunicorn in production |
| Production server | gunicorn | `gthread` worker, 1 worker × 4 threads |
| WebSocket client | websockets | Async; runs in its own event loop inside a daemon thread |
| Database | SQLite (stdlib) | Two tables: `alerts`, `shelter_intervals` |
| HTTP client | `urllib.request` (stdlib) | Used for REST backup poll and city list fetch |
| Concurrency | `threading` + `asyncio` (stdlib) | WebSocket on asyncio; REST poller on blocking thread |

## Frontend

| Component | Technology | Notes |
|---|---|---|
| UI | Vanilla HTML/CSS/JS | No framework; no build step |
| Live events | SSE (`EventSource /stream`) | Primary real-time channel; near-zero latency |
| Polling fallback | `fetch /history?since=` every 2s | Catches events if SSE connection drops |
| Shelter data | `fetch /shelter?zones=` | Fetched on area selection change and after initial history load |
| Elapsed + shelter timers | `setInterval` (1s) | Single interval ticks all visible row clocks and shelter cards |
| Area filter | Multi-select Set (`activeAreasEn`) | Chip bar (desktop) + dropdown checklist (mobile) |
| Shelter meter | Per-area cards above table | Live timer when in shelter; total duration when exited |
| Pagination | Client-side, 10 rows/page | `filterAndPage()` |
| i18n | In-memory JS object | English + Hebrew; RTL via `<html dir="rtl">` |
| City search | Client-side string match | Filters on cached `data-cities-text` attribute |
| State persistence | `localStorage` | `lang`, `activeAreasEn`, `search` survive page refresh |

## External Services

| Service | URL | Purpose |
|---|---|---|
| Tzevaadom WebSocket | `wss://ws.tzevaadom.co.il/socket?platform=ANDROID` | Primary real-time alert stream |
| Oref REST API | `https://www.oref.org.il/WarningMessages/alert/alerts.json` | Backup alert source (Israeli government) |
| City data | `https://raw.githubusercontent.com/eladnava/pikud-haoref-api/master/cities.json` | City ID → name + zone mapping; loaded once at startup |

## Routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Serve `index.html` (Jinja template) |
| `/stream` | GET | SSE stream — push new events + status messages |
| `/history` | GET | All alerts ordered ASC; optional `?since=<unix_ts>` |
| `/cities` | GET | City lookup dict (`{id: {name, name_en, zone, zone_en}}`) |
| `/shelter` | GET | Shelter intervals per zone; `?zones=A\|B[&since=<ts>]` |

## Runtime Requirements

- Python 3.10+
- `flask`, `websockets`, `gunicorn` packages
- Network access to the three external services above
- Write access to the DB directory (`DB_PATH`, defaults to `./alerts.db`)

## Not Used

- No task queue (Celery, RQ, etc.)
- No ORM (raw SQL only)
- No frontend build toolchain
- No container/Docker setup
- No authentication layer
