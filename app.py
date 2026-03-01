"""
Flask application — routes and startup only.

All business logic lives in the modules below:

    config.py    — constants and environment variables
    cities.py    — city/zone data loading and resolution
    db.py        — SQLite schema, persistence, shelter intervals
    ingestion.py — WebSocket listener, REST poller, SSE broadcast
"""

import json
import os
import queue
import sqlite3
import threading

from flask import Flask, Response, render_template, request, stream_with_context

import cities
from db import backfill_zone_en, init_db, rebuild_shelter_intervals
from ingestion import rest_poller, run_ws, subscribers
from config import DB_PATH

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/stream")
def stream():
    """Server-Sent Events endpoint.

    Each connected client gets its own Queue registered in the shared
    subscribers list.  broadcast() pushes messages into every queue;
    this generator yields them as SSE frames.  A 15-second keepalive
    comment prevents proxies from closing idle connections.
    """
    q: queue.Queue = queue.Queue()
    subscribers.append(q)

    def generate():
        try:
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield f"data: {msg}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            if q in subscribers:
                subscribers.remove(q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/cities")
def cities_route():
    """Return the full city lookup map (city_id → city record) as JSON.

    The browser uses this to resolve city IDs in SYSTEM_MESSAGE events and
    to build the zone→Hebrew name translation map for language switching.
    The data is loaded once at startup and served from memory on every request.
    """
    return json.dumps(cities.city_lookup, ensure_ascii=False)


@app.route("/history")
def history():
    """Return persisted alerts, optionally filtered to those after `since`.

    ?since=<unix_seconds>  — omit to fetch all rows (initial page load)

    Rows are returned oldest-first so the frontend can append them in order.
    All fields are included; the browser decides which columns to display.
    """
    since = request.args.get("since", type=int, default=0)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if since:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE time > ? ORDER BY time ASC",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM (SELECT * FROM alerts ORDER BY time DESC LIMIT 100) ORDER BY time ASC"
            ).fetchall()
    return json.dumps([dict(r) for r in rows], ensure_ascii=False)


@app.route("/shelter")
def shelter():
    """Return pre-computed shelter intervals for one or more zones.

    Query parameters:
        zones=<zone_en>|<zone_en>  — pipe-separated list of zones to query
        since=<unix_seconds>       — only return intervals starting at or after
                                     this timestamp (default: 0 = all time)

    Response shape:
        {
          "<zone_en>": {
            "inShelter":      bool,
            "shelterStartMs": int | null,   // ms timestamp if currently in shelter
            "intervals":      [{"start": ms, "end": ms}, ...]  // closed intervals
          },
          ...
        }

    All timestamps are in milliseconds for direct JavaScript Date consumption.
    Open intervals (end_time IS NULL) set inShelter=true and shelterStartMs;
    closed intervals accumulate in the intervals array for total-time math.
    """
    zones_param = request.args.get("zones", "")
    zone_ens    = [z.strip() for z in zones_param.split("|") if z.strip()]
    since_s     = request.args.get("since", type=int, default=0)

    if not zone_ens:
        return json.dumps({}, ensure_ascii=False)

    result = {}
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        for zone in zone_ens:
            rows = conn.execute(
                "SELECT start_time, end_time FROM shelter_intervals "
                "WHERE zone_en = ? AND start_time >= ? ORDER BY start_time ASC",
                (zone, since_s),
            ).fetchall()

            intervals        = []
            in_shelter       = False
            shelter_start_ms = None

            for row in rows:
                if row["end_time"] is None:
                    in_shelter       = True
                    shelter_start_ms = row["start_time"] * 1000
                else:
                    intervals.append({
                        "start": row["start_time"] * 1000,
                        "end":   row["end_time"]   * 1000,
                    })

            result[zone] = {
                "inShelter":      in_shelter,
                "shelterStartMs": shelter_start_ms,
                "intervals":      intervals,
            }

    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

init_db()
cities.load_cities()
backfill_zone_en()
rebuild_shelter_intervals()

threading.Thread(target=run_ws,      daemon=True).start()
threading.Thread(target=rest_poller, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
