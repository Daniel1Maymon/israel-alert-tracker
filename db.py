"""
Database layer.

All SQLite access lives here.  The rest of the application treats this module
as an opaque persistence layer — no SQL appears anywhere else.

Schema
------
alerts
    Stores every incoming event exactly once (deduped on notification_id).
    The zone_en column is resolved at ingest time from the in-memory city
    lookup so that filtering never requires a join.

shelter_intervals
    One row per contiguous shelter period per zone.  An open interval
    (end_time IS NULL) means the zone is currently in shelter.
    UNIQUE(zone_en, start_time) prevents duplicate open intervals when
    the same alert is processed more than once.
"""

import json
import sqlite3
from typing import Any, Dict

from cities import resolve_zones
from config import DB_PATH


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create tables and add any columns introduced after the initial schema.

    Safe to call on an already-initialised database: CREATE TABLE IF NOT EXISTS
    and the ALTER TABLE guards make every operation idempotent.
    """
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
                received_at     TEXT    DEFAULT (datetime('now')),
                zone_en         TEXT    DEFAULT ''
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS shelter_intervals (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                zone_en    TEXT    NOT NULL,
                start_time INTEGER NOT NULL,
                end_time   INTEGER,
                UNIQUE(zone_en, start_time)
            )
        """)

        # Columns added after the initial release — safe no-ops on fresh DBs.
        for col, default in [("source", "'tzevaadom'"), ("zone_en", "''")]:
            try:
                conn.execute(
                    f"ALTER TABLE alerts ADD COLUMN {col} TEXT DEFAULT {default}"
                )
            except Exception:
                pass  # column already exists


# ---------------------------------------------------------------------------
# Alert persistence
# ---------------------------------------------------------------------------

def save_alert(
    msg_type: str,
    data: Dict[str, Any],
    raw: str,
    source: str = "tzevaadom",
) -> None:
    """Persist a single alert and keep shelter_intervals up to date.

    Uses INSERT OR IGNORE so duplicate notification_ids are silently dropped.
    Shelter intervals are only updated when the row is genuinely new
    (rowcount > 0), preventing double-counting on replayed or duplicate events.
    """
    nid     = data.get("notificationId")
    ts      = data.get("time")
    zone_en = resolve_zones(msg_type, data)

    with sqlite3.connect(DB_PATH) as conn:
        if msg_type == "ALERT":
            cursor = conn.execute(
                """INSERT OR IGNORE INTO alerts
                       (notification_id, type, time, threat, is_drill,
                        cities, raw_data, source, zone_en)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    nid, msg_type, ts,
                    data.get("threat"),
                    1 if data.get("isDrill") else 0,
                    json.dumps(data.get("cities", []), ensure_ascii=False),
                    raw, source, zone_en,
                ),
            )

        elif msg_type == "SYSTEM_MESSAGE":
            cursor = conn.execute(
                """INSERT OR IGNORE INTO alerts
                       (notification_id, type, time, title_en, body_en,
                        areas_ids, raw_data, source, zone_en)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    nid, msg_type, ts,
                    data.get("titleEn"),
                    data.get("bodyEn"),
                    json.dumps(data.get("areasIds", []), ensure_ascii=False),
                    raw, source, zone_en,
                ),
            )

        else:
            return

        if cursor.rowcount > 0 and ts:
            _update_shelter_intervals(conn, msg_type, data, zone_en, ts)


# ---------------------------------------------------------------------------
# Shelter interval management
# ---------------------------------------------------------------------------

def _is_exit_message(data: Dict[str, Any]) -> bool:
    """Return True if this SYSTEM_MESSAGE signals the end of a shelter period."""
    return (
        "יציאה מהמרחב המוגן" in (data.get("titleHe") or "")
        or "יציאה מהמרחב המוגן" in (data.get("bodyHe")  or "")
        or "סיום אירוע"        in (data.get("titleHe") or "")
        or "leaving the protected space" in (data.get("titleEn") or "").lower()
        or "leaving the protected space" in (data.get("bodyEn")  or "").lower()
        or "incident ended"              in (data.get("titleEn") or "").lower()
    )


def _update_shelter_intervals(
    conn: sqlite3.Connection,
    msg_type: str,
    data: Dict[str, Any],
    zone_en_str: str,
    event_time_s: int,
) -> None:
    """Open or close shelter intervals in response to a newly saved event.

    Called within the same connection that saved the alert row, so both
    writes are committed atomically.

    Opening rule  — ALERT (non-drill): for each zone, open a new interval only
                    when no interval is already open (prevents double-opens when
                    several alerts arrive for the same zone in quick succession).

    Closing rule  — exit SYSTEM_MESSAGE: close the open interval (if any) for
                    each zone mentioned in the message.  Zero-duration intervals
                    (exit timestamp == start timestamp) are left in the DB but
                    contribute 0 ms to any total — the frontend guards against
                    this with max(0, end − start).
    """
    zone_ens = [z for z in (zone_en_str or "").split("|") if z]
    if not zone_ens:
        return

    if msg_type == "ALERT" and not data.get("isDrill"):
        for zone in zone_ens:
            already_open = conn.execute(
                "SELECT id FROM shelter_intervals "
                "WHERE zone_en = ? AND end_time IS NULL",
                (zone,),
            ).fetchone()

            if not already_open:
                try:
                    conn.execute(
                        "INSERT INTO shelter_intervals (zone_en, start_time) "
                        "VALUES (?, ?)",
                        (zone, event_time_s),
                    )
                except sqlite3.IntegrityError:
                    pass  # UNIQUE constraint race — already inserted

    elif msg_type == "SYSTEM_MESSAGE" and _is_exit_message(data):
        for zone in zone_ens:
            conn.execute(
                "UPDATE shelter_intervals "
                "SET end_time = ? "
                "WHERE zone_en = ? AND end_time IS NULL",
                (event_time_s, zone),
            )


# ---------------------------------------------------------------------------
# One-time startup migrations
# ---------------------------------------------------------------------------

def backfill_zone_en() -> None:
    """Resolve zone_en for rows saved before that column was introduced.

    Reads every row with a NULL or empty zone_en, re-parses its raw_data,
    and runs resolve_zones() to fill in the zone string.  Rows whose cities
    cannot be resolved (e.g. unknown city names) are left with an empty
    zone_en rather than being skipped, so they still appear in the table.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, type, raw_data "
            "FROM alerts "
            "WHERE zone_en IS NULL OR zone_en = ''"
        ).fetchall()

        updated = 0
        for row in rows:
            try:
                raw     = json.loads(row["raw_data"])
                zone_en = resolve_zones(row["type"], raw.get("data", {}))
                conn.execute(
                    "UPDATE alerts SET zone_en = ? WHERE id = ?",
                    (zone_en, row["id"]),
                )
                updated += 1
            except Exception:
                pass

    print(f"[migration] backfilled zone_en for {updated} rows", flush=True)


def rebuild_shelter_intervals() -> None:
    """Rebuild shelter_intervals from scratch by replaying all stored alerts.

    This runs on every startup to guarantee consistency after schema changes,
    code fixes, or manual DB edits.  The full replay takes under a second for
    thousands of rows — it is not incremental by design, to keep the logic
    simple and the result deterministic.

    Events are processed oldest-first so the open/close state machine mirrors
    the original chronological order.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM shelter_intervals")
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            "SELECT type, raw_data, zone_en, time "
            "FROM alerts "
            "WHERE zone_en IS NOT NULL AND zone_en != '' "
            "ORDER BY time ASC"
        ).fetchall()

        for row in rows:
            try:
                raw  = json.loads(row["raw_data"])
                data = raw.get("data", {})
                _update_shelter_intervals(
                    conn, row["type"], data, row["zone_en"], row["time"]
                )
            except Exception:
                pass

    print("[migration] rebuilt shelter_intervals", flush=True)
