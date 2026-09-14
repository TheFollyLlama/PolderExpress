import logging
from math import atan2, cos, radians, sin, sqrt

logger = logging.getLogger(__name__)

LIVEATC_BASE_URL = "http://d.liveatc.net"

KIND_PRIORITY = {"ground": 0, "tower": 1, "appdep": 2, "center": 3}

ATC_FEEDS = [
    {
        "name": "Schiphol Departure",
        "kind": "appdep",
        "slug": "eham_app_121205",
        "lat": 52.3086,
        "lon": 4.7639,
    },
    {
        "name": "Schiphol Approach",
        "kind": "appdep",
        "slug": "eham_app_119055",
        "lat": 52.3086,
        "lon": 4.7639,
    },
    {
        "name": "Schiphol Tower",
        "kind": "tower",
        "slug": "eham_twr_0624",
        "lat": 52.3086,
        "lon": 4.7639,
    },
    {
        "name": "Schiphol Ground",
        "kind": "ground",
        "slug": "eham_gnd_0624",
        "lat": 52.3086,
        "lon": 4.7639,
    },
    {
        "name": "Maastricht Upper Area Control (MUAC)",
        "kind": "center",
        "slug": "eham_muac_135510",
        "lat": 50.8442,
        "lon": 5.7082,
    },
    {
        "name": "Atlanta Ground",
        "kind": "ground",
        "slug": "katl_gnd",
        "lat": 33.6367,
        "lon": -84.4281,
    },
    {
        "name": "Atlanta Tower",
        "kind": "tower",
        "slug": "katl_twr",
        "lat": 33.6367,
        "lon": -84.4281,
    },
    {
        "name": "Atlanta Approach",
        "kind": "appdep",
        "slug": "katl_app_fin_a",
        "lat": 33.6367,
        "lon": -84.4281,
    },
    {
        "name": "Atlanta Center (ZTL)",
        "kind": "center",
        "slug": "katl_ztl22",
        "lat": 33.6367,
        "lon": -84.4281,
    },
]

RADIUS_KM = {
    "ground": 15.0,
    "tower": 1.0,
    "appdep": 50.0,
    "center": 200.0,
}

MAX_ALTITUDE_FT = {
    "tower": 1000,
    "appdep": 24000,
}


def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points in kilometers."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def feed_stream_url(slug):
    """Build the LiveATC MP3 stream URL for a feed slug."""
    return f"{LIVEATC_BASE_URL}/{slug}.mp3"


def _feed_applies(feed, distance, altitude_ft):
    """Return True if a feed covers a position at the given distance."""
    if distance > RADIUS_KM[feed["kind"]]:
        return False

    if feed["kind"] == "ground":
        return altitude_ft == "ground"

    if altitude_ft == "ground" or altitude_ft is None:
        return False

    if not isinstance(altitude_ft, (int, float)):
        return False

    if not 0 < altitude_ft:
        return False

    max_alt = MAX_ALTITUDE_FT.get(feed["kind"])
    return max_alt is None or altitude_ft < max_alt


def _to_feed_dict(feed, kind, distance):
    result = {
        "name": feed["name"],
        "kind": kind,
        "stream_url": feed_stream_url(feed["slug"]),
        "distance_km": round(distance, 1),
    }
    if kind == "center":
        result["altitude_ceiling_ft"] = None
    else:
        result["altitude_ceiling_ft"] = MAX_ALTITUDE_FT.get(kind)
    return result


def find_atc_feed(lat, lon, altitude_ft):
    """Find the closest applicable LiveATC feed for an aircraft position.

    Mirrors the on-demand resolver pattern used by the photo endpoint.
    Feeds are scoped by kind (appdep/tower/ground/center), each with its own
    coverage radius and altitude ceiling. Tower is intentionally narrow
    (1 km, below 1,000 ft) so airborne traffic near the field resolves to
    approach/departure, not tower. Falls back to the nearest center
    feed when nothing else applies. Returned as a plain dict, or None.
    """
    if lat is None or lon is None:
        return None

    scoring = []
    for feed in ATC_FEEDS:
        distance = haversine(lat, lon, feed["lat"], feed["lon"])
        if _feed_applies(feed, distance, altitude_ft):
            scoring.append((feed["kind"], distance, feed))

    if scoring:
        scoring.sort(key=lambda item: (KIND_PRIORITY[item[0]], item[1]))
        kind, distance, feed = scoring[0]
        return _to_feed_dict(feed, kind, distance)

    centers = [f for f in ATC_FEEDS if f["kind"] == "center"]
    if not centers:
        return None
    fallback = min(
        centers,
        key=lambda f: haversine(lat, lon, f["lat"], f["lon"]),
    )
    distance = haversine(lat, lon, fallback["lat"], fallback["lon"])
    return _to_feed_dict(fallback, "center", distance)