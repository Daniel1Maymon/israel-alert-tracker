"""
City and zone data.

Loads a third-party JSON of Israeli city records once at startup and exposes
two lookup tables used throughout the application:

    city_lookup  — int city-ID → full city record dict
    name_to_zone — Hebrew city name → English zone name (zone_en)

resolve_zones() uses these tables to derive a pipe-separated zone_en string
from any incoming alert or system-message payload.  It is called at ingest
time so that zone information is stored durably alongside the raw event.
"""

import json
from typing import Any, Dict
from urllib.request import urlopen

from config import CITIES_URL

# ---------------------------------------------------------------------------
# In-memory lookup tables (populated by load_cities on startup)
# ---------------------------------------------------------------------------

# city_id (int) → full city record, e.g. {id, name, name_en, zone, zone_en, …}
city_lookup: Dict[int, Dict[str, Any]] = {}

# Hebrew city name → zone_en, used to resolve ALERT events which carry city
# names rather than numeric IDs
name_to_zone: Dict[str, str] = {}


def load_cities() -> None:
    """Fetch the cities JSON from GitHub and populate the two lookup tables.

    The JSON is a flat list of city records.  Each record contains at minimum:
        id       — numeric city identifier used in SYSTEM_MESSAGE events
        name     — Hebrew city name used in ALERT events
        zone_en  — English zone name shared by all cities in the same area

    On failure the lookup tables stay empty and zone resolution will silently
    produce empty strings; alerts are still saved and displayed without zone
    information.
    """
    global city_lookup, name_to_zone

    try:
        with urlopen(CITIES_URL, timeout=10) as response:
            cities = json.loads(response.read().decode())

        city_lookup = {
            c["id"]: c
            for c in cities
            if c.get("id")
        }

        name_to_zone = {
            c["name"]: c["zone_en"]
            for c in cities
            if c.get("name") and c.get("zone_en")
        }

        print(f"[cities] loaded {len(city_lookup)} entries", flush=True)

    except Exception as exc:
        print(f"[cities] failed to load: {exc}", flush=True)


def resolve_zones(msg_type: str, data: Dict[str, Any]) -> str:
    """Derive a sorted, pipe-separated string of English zone names from an event.

    ALERT events carry a list of Hebrew city names in data["cities"].  Each
    name is looked up in name_to_zone to find its zone_en.

    SYSTEM_MESSAGE events carry a list of numeric city IDs in data["citiesIds"].
    Each ID is looked up in city_lookup to find its zone_en.

    Zones are deduplicated and sorted for stable storage and comparison.
    Returns an empty string if no zones can be resolved (e.g. before cities
    data is loaded, or for drill alerts with no matching cities).
    """
    zones: set = set()

    if msg_type == "ALERT":
        for city_name in data.get("cities", []):
            zone = name_to_zone.get(city_name)
            if zone:
                zones.add(zone)

    elif msg_type == "SYSTEM_MESSAGE":
        city_ids = data.get("citiesIds", [])
        if isinstance(city_ids, str):
            try:
                city_ids = json.loads(city_ids)
            except Exception:
                city_ids = []

        for cid in city_ids:
            try:
                city = city_lookup.get(int(cid))
            except (TypeError, ValueError):
                continue
            if city and city.get("zone_en"):
                zones.add(city["zone_en"])

    return "|".join(sorted(zones))
