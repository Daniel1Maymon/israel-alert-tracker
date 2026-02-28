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
        BC["broadcast()\n─────────────────\nPushes to all SSE queues"]
        DB_FN["save_alert()\nINSERT OR IGNORE\non notification_id"]
        FLASK["Flask / Werkzeug\nmain thread\n─────────────────\nGET /\nGET /history?since=\nGET /cities\nGET /stream  (SSE)"]
        MEM["city_lookup dict\nloaded at startup\n1,449 entries"]
    end

    subgraph Storage["Storage"]
        DB[("alerts.db\nSQLite")]
    end

    subgraph Browser["Browser — index.html"]
        POLL["setInterval poll\nevery 2 seconds\nGET /history?since=latestTime"]
        RENDER["Table renderer\nsorted by data.time DESC"]
        ELAPSED["Elapsed timer\nsetInterval 1s"]
        SEARCH["City search\nclient-side filter"]
        I18N["i18n toggle\nen / he + RTL"]
    end

    CITIES -->|"HTTP GET at startup"| MEM
    TZW -->|"push messages"| WS
    WS -->|"on message"| DB_FN
    WS -->|"on message"| BC
    WS -->|"connected/error"| FLAG
    FLAG -->|"gates activation"| REST
    OREF -->|"HTTP GET every 5s\n(only when WS down)"| REST
    REST -->|"new alert"| DB_FN
    REST -->|"new alert"| BC
    DB_FN -->|"write"| DB
    MEM -->|"served via /cities"| FLASK
    DB -->|"SELECT"| FLASK
    FLASK -->|"JSON rows"| POLL
    POLL -->|"new rows"| RENDER
    RENDER --> ELAPSED
    RENDER --> SEARCH
    RENDER --> I18N
```

## Thread Interaction

```mermaid
sequenceDiagram
    participant WS as ws_listener thread
    participant FLAG as ws_connected (global)
    participant REST as rest_poller thread
    participant DB as SQLite
    participant SSE as SSE subscribers

    WS->>FLAG: ws_connected = True
    WS->>DB: save_alert(source="tzevaadom")
    WS->>SSE: broadcast(payload + source)

    Note over REST: polls every 5s<br/>ws_connected=True → skip

    WS->>FLAG: ws_connected = False (on error)
    WS-->>WS: sleep 5s, reconnect

    REST->>REST: ws_connected=False → activate
    REST->>DB: save_alert(source="oref")
    REST->>SSE: broadcast(payload)

    WS->>FLAG: ws_connected = True (reconnected)
    Note over REST: next tick: ws_connected=True → skip again
```

## Deduplication Logic

```
Inbound alert
      │
      ▼
notification_id already in DB?
      │ YES → discard (INSERT OR IGNORE)
      │ NO  → insert + broadcast
      ▼
Is source=oref AND ws_connected=True?
      → This path is unreachable by design (REST is gated)
```
