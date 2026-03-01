import os

# ── External data sources ────────────────────────────────────────────────────

WS_URL = "wss://ws.tzevaadom.co.il/socket?platform=ANDROID"

WS_HEADERS = {
    "Origin": "https://www.tzevaadom.co.il",
    "User-Agent": "okhttp/4.9.0",
}

CITIES_URL = (
    "https://raw.githubusercontent.com/eladnava/pikud-haoref-api/master/cities.json"
)

NOTIFICATIONS_URL = (
    "https://www.oref.org.il/WarningMessages/alert/alerts.json"
)

# ── Storage ──────────────────────────────────────────────────────────────────

# Override with a Railway volume path, e.g. /data/alerts.db
DB_PATH = os.environ.get("DB_PATH", "alerts.db")

# ── Tuning ───────────────────────────────────────────────────────────────────

# How often the REST fallback poller checks oref.org.il (seconds)
REST_POLL_INTERVAL = 5

# Grace period before the REST poller activates, giving the WebSocket time to
# connect first and avoiding a burst of duplicate alerts on startup (seconds)
REST_GRACE_PERIOD = 10
