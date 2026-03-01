# Architecture

## Current Architecture

```
External Sources
  wss://ws.tzevaadom.co.il      ──► ws_listener thread ──►┐
  https://oref.org.il (fallback) ──► rest_poller thread  ──►┤
                                                            ▼
                                                    resolve_zones()        ← server-side at ingest
                                                    save_alert()
                                                    update_shelter_intervals()
                                                    SQLite (alerts.db)
                                                         │
                                    ┌────────────────────┤
                                    ▼                    ▼
                            SSE /stream            GET /history
                         (push, real-time)       (initial load + fallback poll)
                                    │                    │
                                    └─────────┬──────────┘
                                              ▼
                                          Browser
                            ┌─────────────────────────────────────┐
                            │  fetchShelterState() ─► GET /shelter │
                            │  area filter (multi-select Set)       │
                            │  shelter meter (one card per area)    │
                            │  pagination (10 rows/page)            │
                            │  search, sort, render, i18n          │
                            └─────────────────────────────────────┘
```

---

### Backend responsibilities

| Responsibility | Where |
|---|---|
| Connect to external WebSocket | `app.py` — `ws_listener()` |
| Fallback REST polling (gated on `ws_connected`) | `app.py` — `rest_poller()` |
| Resolve city → zone_en at ingest | `app.py` — `resolve_zones()` |
| Persist enriched rows + dedup | `app.py` — `save_alert()` |
| Maintain shelter intervals in DB | `app.py` — `update_shelter_intervals()` |
| Push live events to all SSE clients | `app.py` — `broadcast()` |
| Serve enriched history rows | `GET /history` |
| Serve pre-computed shelter intervals | `GET /shelter` |
| Serve city name lookup (for display only) | `GET /cities` |

### Frontend responsibilities

| Responsibility | Where |
|---|---|
| Receive live events via SSE | `index.html` — EventSource `/stream` |
| Poll `/history` as SSE fallback | `index.html` — `poll()` every 2s |
| Fetch shelter intervals from server | `index.html` — `fetchShelterState()` |
| Accumulate live shelter events into state | `index.html` — `processEventForShelter()` |
| Render shelter meter cards | `index.html` — `shelterCardHTML()` |
| Multi-area filter (chips + mobile dropdown) | `index.html` — `toggleArea()` |
| Row rendering, sorting, search, pagination | `index.html` — `addRow()`, `filterAndPage()` |
| Language switching (EN/HE, RTL) | `index.html` — `applyLang()` |
| All UI state (localStorage, in-memory Maps) | `index.html` |

The backend is a **WebSocket-to-SQLite relay with server-side enrichment**. Zone resolution and shelter state are computed once at ingest and stored durably. The browser is a thin view layer.

---

## Database Schema

### `alerts`

| Column | Notes |
|---|---|
| `notification_id` | UNIQUE dedup key |
| `type` | `ALERT` or `SYSTEM_MESSAGE` |
| `time` | Unix timestamp |
| `zone_en` | Pipe-separated zone names (e.g. `Dan|Sharon`), resolved at ingest |
| `cities` | JSON array of Hebrew city name strings (ALERT only) |
| `areas_ids` | JSON array of area IDs (SYSTEM_MESSAGE only) |
| `title_en`, `body_en` | English text (SYSTEM_MESSAGE only) |
| `raw_data` | Full original JSON payload |
| `source` | `tzevaadom` or `oref` |

### `shelter_intervals`

| Column | Notes |
|---|---|
| `zone_en` | Area name (matches `zone_en` in `alerts`) |
| `start_time` | Unix timestamp of first alert for this open interval |
| `end_time` | Unix timestamp of exit message; `NULL` while still in shelter |

`UNIQUE(zone_en, start_time)` prevents duplicate open intervals.

---

## Startup sequence

On every process start `app.py` runs four steps before accepting traffic:

1. `init_db()` — create tables / add missing columns to existing DBs.
2. `load_cities()` — fetch the GitHub cities JSON into memory (`city_lookup`, `name_to_zone`).
3. `backfill_zone_en()` — resolve `zone_en` for any rows saved before this column existed.
4. `rebuild_shelter_intervals()` — delete and replay all alerts to rebuild the `shelter_intervals` table from scratch (ensures consistency after restarts or schema changes).
