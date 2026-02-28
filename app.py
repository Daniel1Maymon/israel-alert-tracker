import asyncio
import json
import os
import queue
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict
from urllib.request import urlopen, Request

import websockets
from flask import Flask, Response, render_template, request, stream_with_context

WS_URL = "wss://ws.tzevaadom.co.il/socket?platform=ANDROID"
HEADERS = {
    "Origin": "https://www.tzevaadom.co.il",
    "User-Agent": "okhttp/4.9.0",
}
DB_PATH = os.environ.get("DB_PATH", "alerts.db")
CITIES_URL        = "https://raw.githubusercontent.com/eladnava/pikud-haoref-api/master/cities.json"
NOTIFICATIONS_URL = "https://www.oref.org.il/WarningMessages/alert/alerts.json"
REST_POLL_INTERVAL = 5   # seconds

app = Flask(__name__)
subscribers: list[queue.Queue] = []
ws_connected: bool = False

# city_id (int) -> {"name": "...", "name_en": "..."}
city_lookup: Dict[int, Dict[str, str]] = {}


def load_cities() -> None:
    global city_lookup
    try:
        with urlopen(CITIES_URL, timeout=10) as r:
            cities = json.loads(r.read().decode())
        city_lookup = {c["id"]: c for c in cities if c.get("id")}
        print(f"[cities] loaded {len(city_lookup)} entries", flush=True)
    except Exception as e:
        print(f"[cities] failed to load: {e}", flush=True)


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_id TEXT    UNIQUE,
                type            TEXT    NOT NULL,
                time            INTEGER,
                threat          INTEGER,
                is_drill        INTEGER,
                cities          TEXT,
                title_en        TEXT,
                body_en         TEXT,
                areas_ids       TEXT,
                raw_data        TEXT    NOT NULL,
                source          TEXT    DEFAULT 'tzevaadom',
                received_at     TEXT    DEFAULT (datetime('now'))
            )
        """)
        # add column to existing DBs that predate this change
        try:
            conn.execute("ALTER TABLE alerts ADD COLUMN source TEXT DEFAULT 'tzevaadom'")
        except Exception:
            pass


def save_alert(msg_type: str, data: Dict[str, Any], raw: str, source: str = "tzevaadom") -> None:
    nid = data.get("notificationId")
    ts = data.get("time")
    with sqlite3.connect(DB_PATH) as conn:
        if msg_type == "ALERT":
            conn.execute(
                """INSERT OR IGNORE INTO alerts
                       (notification_id, type, time, threat, is_drill, cities, raw_data, source)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    nid, msg_type, ts,
                    data.get("threat"),
                    1 if data.get("isDrill") else 0,
                    json.dumps(data.get("cities", []), ensure_ascii=False),
                    raw, source,
                ),
            )
        elif msg_type == "SYSTEM_MESSAGE":
            conn.execute(
                """INSERT OR IGNORE INTO alerts
                       (notification_id, type, time, title_en, body_en, areas_ids, raw_data, source)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    nid, msg_type, ts,
                    data.get("titleEn"),
                    data.get("bodyEn"),
                    json.dumps(data.get("areasIds", []), ensure_ascii=False),
                    raw, source,
                ),
            )


# ---------------------------------------------------------------------------
# WebSocket background listener
# ---------------------------------------------------------------------------

def broadcast(payload: str) -> None:
    for q in subscribers[:]:
        q.put(payload)


async def ws_listener() -> None:
    while True:
        try:
            async with websockets.connect(
                WS_URL, ping_interval=30, additional_headers=HEADERS
            ) as ws:
                global ws_connected
                ws_connected = True
                print(f"[WS] connected", flush=True)
                broadcast(json.dumps({"type": "STATUS", "data": {"status": "connected"}}))
                while True:
                    message = await ws.recv()
                    try:
                        payload: Dict[str, Any] = json.loads(message)
                        save_alert(payload.get("type", ""), payload.get("data", {}), message)
                        payload["source"] = "tzevaadom"
                        broadcast(json.dumps(payload, ensure_ascii=False))
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            ws_connected = False
            print(f"[WS] error: {e} — reconnecting in 5s", flush=True)
            broadcast(json.dumps({"type": "STATUS", "data": {"status": "disconnected"}}))
            await asyncio.sleep(5)


def run_ws() -> None:
    try:
        asyncio.run(ws_listener())
    except Exception as e:
        print(f"[WS thread fatal] {e}", flush=True)


def rest_poller() -> None:
    """Polls the REST API every REST_POLL_INTERVAL seconds as a backup.
    Catches any alerts missed during WebSocket reconnects."""
    import time
    # Pre-populate seen from DB so restarts don't reprocess recent oref alerts
    seen: set = set()
    try:
        with sqlite3.connect(DB_PATH) as _c:
            for (nid,) in _c.execute("SELECT notification_id FROM alerts WHERE notification_id IS NOT NULL"):
                seen.add(str(nid))
    except Exception:
        pass
    # Grace period: give the WS time to connect before REST activates
    time.sleep(10)
    while True:
        if ws_connected:
            time.sleep(REST_POLL_INTERVAL)
            continue
        try:
            req = Request(
                NOTIFICATIONS_URL,
                headers={
                    "Referer":    "https://www.oref.org.il/",
                    "X-Requested-With": "XMLHttpRequest",
                    "User-Agent": "Mozilla/5.0",
                },
            )
            with urlopen(req, timeout=5) as r:
                body = r.read().decode("utf-8-sig").strip()
            if not body:
                continue   # no active alerts right now
            payload = json.loads(body)
            # oref format: {"id":"...", "title":[...], "data":[...], "cat":"1"}
            nid = str(payload.get("id", ""))
            if not nid or nid in seen:
                continue
            seen.add(nid)
            cities = payload.get("data", [])
            item = {
                "notificationId": nid,
                "time": int(time.time()),
                "threat": int(payload.get("cat", 0)),
                "isDrill": False,
                "cities": cities,
            }
            raw = json.dumps({"type": "ALERT", "data": item}, ensure_ascii=False)
            save_alert("ALERT", item, raw, source="oref")
            broadcast(raw)
            print(f"[REST] caught missed alert: {nid} — {cities[:3]}", flush=True)
        except Exception as e:
            print(f"[REST] poll error: {e}", flush=True)
        time.sleep(REST_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/stream")
def stream():
    q: queue.Queue = queue.Queue()
    subscribers.append(q)

    def generate():
        try:
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield f"data: {msg}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"   # SSE comment, no-op in browser
        except GeneratorExit:
            if q in subscribers:
                subscribers.remove(q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/cities")
def cities():
    return json.dumps(city_lookup, ensure_ascii=False)


@app.route("/history")
def history():
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
                "SELECT * FROM alerts ORDER BY time DESC LIMIT 100"
            ).fetchall()
    return json.dumps([dict(r) for r in rows], ensure_ascii=False)


# ---------------------------------------------------------------------------
# Startup — runs when imported by gunicorn or executed directly.
# ---------------------------------------------------------------------------

init_db()
load_cities()
threading.Thread(target=run_ws,      daemon=True).start()
threading.Thread(target=rest_poller, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
