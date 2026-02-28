# Data Flow

## Inbound Message Types

Two distinct message types arrive from the tzevaadom WebSocket:

### `ALERT` — live siren
Issued when sirens are actively sounding.

```json
{
  "type": "ALERT",
  "data": {
    "notificationId": "3bee632e-f2f3-419f-ae99-3598a1bff46a",
    "time": 1772282584,
    "threat": 0,
    "isDrill": false,
    "cities": ["תל אביב - מזרח", "בני ברק", "גבעתיים"]
  }
}
```

### `SYSTEM_MESSAGE` — early warning or all-clear
Issued ~2 minutes before sirens (missile detected) or after an event ends.

```json
{
  "type": "SYSTEM_MESSAGE",
  "data": {
    "notificationId": "0a34bf87-620f-4ae1-a371-1bafe1453c1f",
    "time": "1772282186",
    "titleHe": "מבזק פיקוד העורף - התרעה מקדימה",
    "titleEn": "Home Front Command - Early Warning",
    "bodyHe": "בעקבות זיהוי שיגורים...",
    "bodyEn": "Due to the detection of missile launches...",
    "areasIds": [21, 7],
    "citiesIds": [333, 1932, 320],
    "instructionType": 0,
    "pinUntil": 1772282607
  }
}
```

**All-clear detection**: a `SYSTEM_MESSAGE` is classified as "all clear" (green highlight in UI) when `titleHe` or `bodyHe` contains `יציאה מהמרחב המוגן`, or the English equivalents contain `leaving the protected space`.

### Oref REST format
When the backup poller activates, it normalises the government API response into the same `ALERT` structure before saving/broadcasting:

```json
{
  "id": "134167640540000000",
  "data": ["גאליה", "כפר הנגיד"],
  "cat": "1"
}
```

Becomes:
```json
{
  "type": "ALERT",
  "data": {
    "notificationId": "134167640540000000",
    "time": <unix_now>,
    "threat": 1,
    "isDrill": false,
    "cities": ["גאליה", "כפר הנגיד"]
  }
}
```

---

## Database Schema

**Table: `alerts`**

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `notification_id` | TEXT UNIQUE | Dedup key; UUID from tzevaadom, numeric string from oref |
| `type` | TEXT | `ALERT` or `SYSTEM_MESSAGE` |
| `time` | INTEGER | Unix timestamp from the alert payload |
| `threat` | INTEGER | Threat category (0 = rockets); ALERT only |
| `is_drill` | INTEGER | 0/1 boolean; ALERT only |
| `cities` | TEXT | JSON array of city name strings; ALERT only |
| `title_en` | TEXT | English title; SYSTEM_MESSAGE only |
| `body_en` | TEXT | English body; SYSTEM_MESSAGE only |
| `areas_ids` | TEXT | JSON array of area IDs; SYSTEM_MESSAGE only |
| `raw_data` | TEXT | Full original JSON payload |
| `source` | TEXT | `tzevaadom` or `oref` |
| `received_at` | TEXT | `datetime('now')` at insert time |

---

## Frontend Data Flow

```
Page load
  │
  ├─► GET /cities → cityLookup dict (one-time, held in memory)
  │
  └─► GET /history (no since) → last 100 rows, sorted DESC by time
            │
            └─► rows rendered; latestTime = max(data.time)

Every 2 seconds:
  GET /history?since=latestTime
    │  empty → no-op
    └─► new rows → addRow() → sortTable() → filterRows()
```

## City ID Resolution

`SYSTEM_MESSAGE` events carry `citiesIds` (integer array) rather than city name strings. The frontend resolves them at render time:

```
citiesIds: [333, 1932]
     │
     ▼
cityLookup["333"] → { name: "אשדוד", name_en: "Ashdod" }
cityLookup["1932"] → { name: "...", name_en: "..." }
     │
     ▼  (depending on active language)
"Ashdod · ..."   or   "אשדוד · ..."
```

City names are never stored in the DB — only IDs. Resolution is always done in the browser using the `/cities` endpoint.

---

## Observed Event Patterns

Based on captured data (177 alerts across ~1 hour session):

- Alerts arrive in **waves** of ~90 seconds duration, separated by ~10–15 minute quiet periods.
- Each wave typically covers hundreds of cities across multiple geographic areas.
- `SYSTEM_MESSAGE` events precede `ALERT` events for the same area by ~2 minutes.
- All-clear `SYSTEM_MESSAGE` events follow ~5–10 minutes after the last siren in an area.
