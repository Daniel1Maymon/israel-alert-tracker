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

**All-clear detection**: classified as "leaving the protected space" when `titleHe` or `bodyHe` contains `יציאה מהמרחב המוגן`, or the English fields contain `leaving the protected space`.

### Oref REST format
When the backup poller activates, it normalises the government API response into the same `ALERT` structure before saving/broadcasting.

---

## Ingest pipeline (server-side, per event)

```
Inbound event (WebSocket or REST)
        │
        ▼
resolve_zones(type, data)
  ALERT:          city name → name_to_zone dict → zone_en
  SYSTEM_MESSAGE: citiesId  → city_lookup dict  → zone_en
        │
        ▼
save_alert() — INSERT OR IGNORE on notification_id
  stores: type, time, zone_en, cities/title_en/body_en, raw_data, source
        │
        ▼ (only if INSERT succeeded, i.e. new row)
update_shelter_intervals()
  ALERT (non-drill): open new interval for each zone (if none open)
  "יציאה" message:   close open interval for each zone
        │
        ▼
broadcast() — push enriched JSON to all SSE subscribers
  payload includes zone_en field
```

---

## Frontend Data Flow

### Initial page load

```
Page open
  │
  ├─► EventSource /stream  (SSE — persistent connection for live push)
  │
  ├─► GET /history         (all rows, ASC by time; each row includes zone_en)
  │       │
  │       └─► addRow() for each row → renderRowContent() → sortTable()
  │           latestTime = max(data.time)
  │           historyLoaded = true
  │           fetchShelterState()   ← hits /shelter for selected areas
  │
  └─► GET /cities           (city lookup for display names; one-time)
          │
          └─► cityLookup, nameToZone, zoneEnToZoneHe populated
              All rows re-rendered (Hebrew zone names now available)
              updateKnownAreas() refreshes chip labels
```

### Live events (SSE)

```
SSE message arrives
  │  (ignored until historyLoaded = true)
  │
  ▼
addRow(type, data, isLive=true, source, zone_en)
  dedup via receivedIds Set
  processEventForShelter() — update local shelter state
  fetchShelterState()      — re-sync with server if area affected
  filterAndPage()          — re-apply current filter + pagination
  flashBanner()
```

### Polling fallback

```
Every 2 seconds:
  GET /history?since=latestTime
    empty → no-op
    new rows → same addRow() path as SSE
```

Polling ensures no events are missed if the SSE connection drops.

### Area selection change

```
toggleArea(zoneEn)
  │
  ├─► activeAreasEn Set updated (add/remove/clear)
  ├─► localStorage saved
  ├─► renderAreaChips() + renderAreaDropdown()
  ├─► fetchShelterState()
  │       GET /shelter?zones=zone1|zone2
  │       Response: { zone_en: { inShelter, shelterStartMs, intervals } }
  │       → shelterState Map updated → updateShelterMeter()
  └─► filterAndPage()
```

---

## Zone Resolution

`zone_en` is resolved **once at ingest** and stored in the `alerts.zone_en` column. The browser reads it directly from the history response — no client-side lookup required for filtering or shelter logic.

City names are still resolved client-side from `/cities` for **display** only (showing Hebrew/English city names and zone labels in the table). City IDs from `SYSTEM_MESSAGE.citiesIds` that don't exist in the open cities dataset are silently skipped.

---

## Shelter Interval Logic

```
Server (shelter_intervals table):
  ALERT (non-drill, new) → INSERT (zone_en, start_time) if no open row
  "יציאה" SYSTEM_MESSAGE → UPDATE end_time WHERE end_time IS NULL

GET /shelter?zones=Dan|Sharon:
  Returns per zone:
    inShelter:      true/false
    shelterStartMs: start of open interval (ms) or null
    intervals:      [ {start, end} ]  — completed intervals (ms)

Frontend totalShelterMs(zEn):
  sum of all completed interval durations
  + (Date.now() − shelterStartMs) if currently in shelter
```

---

## Observed Event Patterns

- Alerts arrive in **waves** of ~90 seconds, separated by ~10–15 minute quiet periods.
- Each wave covers hundreds of cities across multiple geographic areas.
- `SYSTEM_MESSAGE` early warnings precede `ALERT` events by ~2 minutes.
- All-clear `SYSTEM_MESSAGE` events follow ~5–10 minutes after the last siren in an area.
