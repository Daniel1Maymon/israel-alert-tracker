# Architecture

## Process Model

A single Python process runs three concurrent execution paths:

| Thread | Role |
|---|---|
| Main (Flask/Werkzeug) | HTTP server — serves the UI and API endpoints |
| `run_ws` (daemon thread) | Async WebSocket listener — primary alert source |
| `rest_poller` (daemon thread) | HTTP polling loop — backup alert source (oref.org.il) |

Both background threads are started only inside the Werkzeug child process (`WERKZEUG_RUN_MAIN == 'true'`) to avoid double-start when debug mode is active.

## Components

### `app.py`

The entire backend in one file. Responsibilities:

- **`init_db()`** — creates the SQLite schema on startup; runs `ALTER TABLE` to add new columns to pre-existing databases.
- **`load_cities()`** — fetches 1,449 city records from a GitHub-hosted JSON file at startup; builds an in-memory `dict[int, dict]` keyed by city ID.
- **`save_alert()`** — writes an alert to SQLite using `INSERT OR IGNORE` on `notification_id` to prevent duplicates within a source.
- **`ws_listener()`** — async loop; connects to `wss://ws.tzevaadom.co.il/socket?platform=ANDROID` with Android-mimicking headers, auto-reconnects after 5 s on failure, sets the `ws_connected` flag.
- **`rest_poller()`** — polls `https://www.oref.org.il/WarningMessages/alert/alerts.json` every 5 s **only when `ws_connected == False`**; pre-seeds its `seen` set from the DB to avoid reprocessing after restarts.
- **`broadcast()`** — pushes a message string into every active SSE subscriber queue.
- **Flask routes** — `/` (UI), `/stream` (SSE), `/history` (DB query), `/cities` (city lookup JSON).

### `templates/index.html`

Self-contained single-page app (vanilla JS, no frameworks). Responsibilities:

- Polls `/history?since=<timestamp>` every **2 seconds** to pick up new rows.
- Tracks `latestTime` to request only new records on subsequent polls.
- Maintains an in-memory city lookup (`cityLookup`) fetched once from `/cities`.
- Renders rows sorted by `data.time` (descending) after every insert.
- Updates the elapsed timer (`HH:MM:SS`) every second via `setInterval`.
- Language toggle (`en`/`he`) re-renders all row content cells and flips `<html dir>`.

### `alerts.db`

SQLite file created in the working directory on first run. Single table: `alerts`. See [DATA_FLOW.md](DATA_FLOW.md) for schema.

## Key Design Decisions

| Decision | Rationale |
|---|---|
| REST poller only activates when WS is disconnected | Prevents duplicate rows — the two sources assign different IDs to the same real-world event |
| `INSERT OR IGNORE` on `notification_id` | Deduplicates within a single source across restarts |
| City lookup loaded at startup, served via `/cities` | ~1,449 records; cheap to hold in memory; avoids per-request DB joins |
| Frontend polls `/history` rather than consuming SSE directly | Simpler, stateless; survives server restarts without losing history |
| `ws_connected` global flag shared between threads | Both threads run in the same process; Python GIL makes bool reads/writes atomic |
| Flask debug mode with `WERKZEUG_RUN_MAIN` guard | Enables hot-reload during development without starting background threads twice |
