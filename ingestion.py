"""
Data ingestion layer.

Responsible for receiving alert events from two external sources and
delivering them to both the database and any connected SSE clients:

    WebSocket listener  — primary source, connects to tzevaadom.co.il and
                          stays connected with automatic reconnection.

    REST poller         — fallback source, polls oref.org.il every few seconds
                          but only activates when the WebSocket is disconnected.
                          This prevents duplicate rows under normal operation
                          because both sources publish the same real-world events
                          with different notification IDs.

Both paths call save_alert() for persistence and broadcast() for live delivery.
"""

import asyncio
import json
import queue
import sqlite3
import threading
import time
from typing import Any, Dict, List

import websockets

from cities import resolve_zones
from config import (
    DB_PATH,
    NOTIFICATIONS_URL,
    REST_GRACE_PERIOD,
    REST_POLL_INTERVAL,
    WS_HEADERS,
    WS_URL,
)
from db import save_alert

# ---------------------------------------------------------------------------
# SSE subscriber registry
# ---------------------------------------------------------------------------

# Each connected SSE client gets its own Queue.  broadcast() pushes a message
# string into every queue; the /stream generator reads from its own queue.
subscribers: List[queue.Queue] = []

# Shared flag: True while the WebSocket connection is healthy.  The REST poller
# checks this before each poll cycle to avoid running in parallel with the WS.
ws_connected: bool = False


def broadcast(payload: str) -> None:
    """Push a serialised JSON string to every active SSE subscriber.

    Iterates over a snapshot of the list so that subscribers that disconnect
    mid-loop (and trigger a GeneratorExit inside /stream) do not cause
    index errors.
    """
    for q in subscribers[:]:
        q.put(payload)


# ---------------------------------------------------------------------------
# WebSocket listener (primary source)
# ---------------------------------------------------------------------------

async def ws_listener() -> None:
    """Async loop that maintains a persistent WebSocket connection.

    On each received message:
      1. Parse the JSON payload.
      2. Resolve the zone_en string server-side (city lookup is in memory).
      3. Persist via save_alert() — INSERT OR IGNORE deduplicates.
      4. Attach zone_en and source to the payload, then broadcast to SSE
         clients so the browser receives the event without waiting for the
         next poll cycle.

    On any connection error the loop waits 5 seconds and reconnects.
    The ws_connected flag is kept in sync so the REST poller knows whether
    to activate.
    """
    global ws_connected

    while True:
        try:
            async with websockets.connect(
                WS_URL,
                ping_interval=30,
                additional_headers=WS_HEADERS,
            ) as ws:
                ws_connected = True
                print("[WS] connected", flush=True)
                broadcast(
                    json.dumps({"type": "STATUS", "data": {"status": "connected"}})
                )

                while True:
                    raw_message = await ws.recv()
                    _handle_ws_message(raw_message)

        except Exception as exc:
            ws_connected = False
            print(f"[WS] error: {exc} — reconnecting in 5 s", flush=True)
            broadcast(
                json.dumps({"type": "STATUS", "data": {"status": "disconnected"}})
            )
            await asyncio.sleep(5)


def _handle_ws_message(raw_message: str) -> None:
    """Parse a single WebSocket message, persist it, and broadcast it."""
    try:
        payload: Dict[str, Any] = json.loads(raw_message)
    except json.JSONDecodeError:
        return

    msg_type = payload.get("type", "")
    data     = payload.get("data", {})

    save_alert(msg_type, data, raw_message, source="tzevaadom")

    payload["source"]  = "tzevaadom"
    payload["zone_en"] = resolve_zones(msg_type, data)
    broadcast(json.dumps(payload, ensure_ascii=False))


def run_ws() -> None:
    """Entry point for the WebSocket background thread.

    Wraps the async ws_listener() coroutine in a dedicated event loop.
    Using asyncio.run() rather than get_event_loop() avoids deprecation
    warnings in Python 3.10+ and ensures the loop is properly closed if
    the thread ever exits.
    """
    try:
        asyncio.run(ws_listener())
    except Exception as exc:
        print(f"[WS thread fatal] {exc}", flush=True)


# ---------------------------------------------------------------------------
# REST poller (fallback source)
# ---------------------------------------------------------------------------

def rest_poller() -> None:
    """Poll oref.org.il as a backup when the WebSocket is disconnected.

    The poller maintains a local set of already-seen notification IDs so that
    alerts fetched before a restart are not re-processed.  This set is seeded
    from the database at startup to survive server restarts cleanly.

    The oref.org.il response format differs from tzevaadom:
        {"id": "...", "title": [...], "data": [city_name, ...], "cat": "1"}
    The poller normalises this into the same structure save_alert() expects.
    """
    seen: set = _seed_seen_ids()
    time.sleep(REST_GRACE_PERIOD)

    while True:
        if ws_connected:
            time.sleep(REST_POLL_INTERVAL)
            continue

        try:
            alert = _fetch_oref_alert()
            if alert is None:
                time.sleep(REST_POLL_INTERVAL)
                continue

            nid = str(alert.get("notificationId", ""))
            if nid and nid not in seen:
                seen.add(nid)
                raw     = json.dumps({"type": "ALERT", "data": alert}, ensure_ascii=False)
                zone_en = resolve_zones("ALERT", alert)
                save_alert("ALERT", alert, raw, source="oref")
                broadcast(json.dumps({
                    "type":    "ALERT",
                    "data":    alert,
                    "source":  "oref",
                    "zone_en": zone_en,
                }, ensure_ascii=False))
                print(
                    f"[REST] caught missed alert: {nid} — "
                    f"{alert.get('cities', [])[:3]}",
                    flush=True,
                )

        except Exception as exc:
            print(f"[REST] poll error: {exc}", flush=True)

        time.sleep(REST_POLL_INTERVAL)


def _seed_seen_ids() -> set:
    """Load all known notification IDs from the DB to avoid reprocessing them."""
    seen: set = set()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            for (nid,) in conn.execute(
                "SELECT notification_id FROM alerts WHERE notification_id IS NOT NULL"
            ):
                seen.add(str(nid))
    except Exception:
        pass
    return seen


def _fetch_oref_alert() -> Dict[str, Any] | None:
    """Fetch the current active alert from oref.org.il and normalise it.

    Returns a dict in the same shape as a tzevaadom ALERT data payload,
    or None if there is no active alert or the response is empty/malformed.
    """
    from urllib.request import Request, urlopen

    req = Request(
        NOTIFICATIONS_URL,
        headers={
            "Referer":          "https://www.oref.org.il/",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent":       "Mozilla/5.0",
        },
    )

    with urlopen(req, timeout=5) as response:
        body = response.read().decode("utf-8-sig").strip()

    if not body:
        return None

    raw = json.loads(body)

    # oref format: {"id": "...", "data": ["city", ...], "cat": "1", ...}
    return {
        "notificationId": str(raw.get("id", "")),
        "time":           int(time.time()),
        "threat":         int(raw.get("cat", 0)),
        "isDrill":        False,
        "cities":         raw.get("data", []),
    }
