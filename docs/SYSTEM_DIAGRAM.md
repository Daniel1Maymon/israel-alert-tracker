# System Diagram

## Component Architecture

```mermaid
graph TD
    subgraph External["External Services"]
        TZW["tzevaadom.co.il\nWebSocket\nwss://ws.tzevaadom.co.il/socket"]
        OREF["oref.org.il\nREST API\n/WarningMessages/alert/alerts.json"]
        CITIES["GitHub\nCities JSON\npikud-haoref-api/cities.json"]
    end

    subgraph Process["Python Process — app.py"]
        direction TB
        WS["ws_listener()\nasync / daemon thread\n─────────────────\nConnects with Android headers\nAuto-reconnects every 5s\nSets ws_connected flag"]
        REST["rest_poller()\nblocking loop / daemon thread\n─────────────────\nPolls every 5s\nActive ONLY when ws_connected=False\nPre-seeds seen set from DB"]
        FLAG["ws_connected: bool\n(shared global)"]
        RZ["resolve_zones()\n─────────────────\nALERT: city name → name_to_zone\nSYSTEM_MESSAGE: citiesId → city_lookup"]
        SH["update_shelter_intervals()\n─────────────────\nALERT: open interval\nיציאה: close interval"]
        BC["broadcast()\n─────────────────\nPushes enriched payload\n(+ zone_en) to all SSE queues"]
        DB_FN["save_alert()\nINSERT OR IGNORE\non notification_id"]
        FLASK["Flask / gunicorn\n─────────────────\nGET /\nGET /stream  (SSE)\nGET /history[?since=]\nGET /cities\nGET /shelter?zones="]
        MEM["city_lookup dict\nname_to_zone dict\nloaded at startup"]
    end

    subgraph Storage["Storage"]
        DB[("alerts.db\nSQLite\n─────────────────\nTable: alerts\nTable: shelter_intervals")]
    end

    subgraph Browser["Browser — index.html"]
        SSE_C["EventSource /stream\n(primary real-time channel)"]
        POLL["poll() fallback\nevery 2s\nGET /history?since=latestTime"]
        SHELTER_F["fetchShelterState()\nGET /shelter?zones=...\non area change + initial load"]
        FILTER["Area filter\nactiveAreasEn Set\nmulti-select chips + dropdown"]
        SHELTER_UI["Shelter meter\none card per selected area\nlive timer + total duration"]
        RENDER["Table renderer\nsorted DESC by time\npaginated (10 rows/page)"]
        ELAPSED["Elapsed timer\nsetInterval 1s"]
        SEARCH["City search + pagination\nclient-side"]
        I18N["i18n toggle\nen / he + RTL"]
    end

    CITIES -->|"HTTP GET at startup"| MEM
    TZW -->|"push messages"| WS
    WS -->|"on message"| RZ
    RZ -->|"zone_en"| DB_FN
    RZ -->|"zone_en"| SH
    RZ -->|"zone_en enriched payload"| BC
    WS -->|"connected/error"| FLAG
    FLAG -->|"gates activation"| REST
    OREF -->|"HTTP GET every 5s\n(only when WS down)"| REST
    REST -->|"new alert"| RZ
    DB_FN -->|"INSERT OR IGNORE"| DB
    SH -->|"open/close intervals"| DB
    MEM -->|"served via /cities"| FLASK
    DB -->|"SELECT"| FLASK
    BC -->|"SSE queue"| FLASK
    FLASK -->|"text/event-stream"| SSE_C
    FLASK -->|"JSON rows + zone_en"| POLL
    FLASK -->|"shelter intervals"| SHELTER_F
    SSE_C -->|"live events"| RENDER
    SSE_C -->|"live events"| SHELTER_UI
    POLL -->|"missed events"| RENDER
    SHELTER_F -->|"intervals per zone"| SHELTER_UI
    FILTER -->|"area selection"| SHELTER_F
    FILTER -->|"area filter"| RENDER
    RENDER --> ELAPSED
    RENDER --> SEARCH
    RENDER --> I18N
```

---

## Thread Interaction

```mermaid
sequenceDiagram
    participant WS as ws_listener thread
    participant FLAG as ws_connected (global)
    participant REST as rest_poller thread
    participant RZ as resolve_zones()
    participant DB as SQLite
    participant SSE as SSE subscribers

    WS->>FLAG: ws_connected = True
    WS->>RZ: resolve_zones(type, data)
    RZ-->>WS: zone_en string
    WS->>DB: save_alert() + update_shelter_intervals()
    WS->>SSE: broadcast(payload + zone_en)

    Note over REST: polls every 5s; ws_connected=True → skip

    WS->>FLAG: ws_connected = False (on error)
    WS-->>WS: sleep 5s, reconnect

    REST->>REST: ws_connected=False → activate
    REST->>RZ: resolve_zones("ALERT", item)
    REST->>DB: save_alert() + update_shelter_intervals()
    REST->>SSE: broadcast(payload + zone_en)

    WS->>FLAG: ws_connected = True (reconnected)
    Note over REST: next tick: ws_connected=True → skip again
```

---

## Startup Sequence

```
Process start
  │
  ├─► init_db()                  — create tables; ALTER TABLE for missing columns
  ├─► load_cities()              — fetch GitHub JSON → city_lookup, name_to_zone
  ├─► backfill_zone_en()         — resolve zone_en for pre-existing rows (migration)
  ├─► rebuild_shelter_intervals() — DELETE + replay all alerts → consistent shelter state
  ├─► Thread: run_ws()            — start WebSocket listener
  └─► Thread: rest_poller()       — start REST backup poller
```

---

## Deduplication

```
Inbound alert
      │
      ▼
  notification_id in DB?
      YES → INSERT OR IGNORE (no-op)
      NO  → save + update shelter + broadcast

Browser:
  receivedIds Set (in-memory)
  Each addRow() call checks and skips duplicate notificationIds
  (guards against SSE + poll delivering same event twice)
```
