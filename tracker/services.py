import logging
import threading
import time
from datetime import datetime, timezone
from math import atan2, cos, degrees, radians, sin

import requests
from django.conf import settings

from tracker.atc import feed_stream_url, find_atc_feed, haversine

logger = logging.getLogger(__name__)

LIVEATC_GROUND = feed_stream_url("katl_gnd")
LIVEATC_TOWER = feed_stream_url("katl_twr")
LIVEATC_APPROACH = feed_stream_url("katl_app_fin_a")
LIVEATC_CENTER = feed_stream_url("katl_ztl22")

EHAM_LAT = 52.3086
EHAM_LON = 4.7639
KM_PER_NM = 1.852

AMS_ACC_NORTH_BAND_LAT = 52.85
AMS_GROUND_RADIUS_NM = 3.0
AMS_TOWER_RADIUS_NM = 6.0
AMS_TMA_RADIUS_NM = 35.0
AMS_ACC_RADIUS_NM = 150.0
AMS_MUAC_RADIUS_NM = 200.0
AMS_TOWER_MAX_ALT_FT = 2500
AMS_TMA_MAX_ALT_FT = 9500
AMS_ACC_MAX_ALT_FT = 24500
AMS_NIGHT_START_HOUR_UTC = 22
AMS_NIGHT_END_HOUR_UTC = 5

AMS_DELIVERY_STREAM = feed_stream_url("eham_del")
AMS_GROUND_STREAM = feed_stream_url("eham_gnd_0624")
AMS_TOWER_STREAM = feed_stream_url("eham_twr_0624")
AMS_DEPARTURE_STREAM = feed_stream_url("eham_app_121205")
AMS_APPROACH_STREAM = feed_stream_url("eham_app_119055")
AMS_ACC_STREAM = feed_stream_url("eham_rdr_sw")
AMS_MUAC_STREAM = feed_stream_url("eham_muac_135510")

AMS_DELIVERY_FREQ_MHZ = "121.980"
AMS_GROUND_FREQ_MHZ = "121.705"
AMS_TOWER_FREQ_MHZ = "135.110"
AMS_DEPARTURE_FREQ_MHZ = "121.205"
AMS_APPROACH_FREQ_MHZ = "119.055"
AMS_MUAC_FREQ_MHZ = "135.510"
AMS_NIGHT_FREQ_MHZ = "124.300"

AMS_SECTOR_FREQS = {
    "north": "119.175",
    "east": "124.875",
    "south": "123.850",
    "southwest": "125.750",
    "northwest": "123.700",
}

ROUTE_CACHE_TTL_SECONDS = 6 * 60 * 60
ROUTE_NEGATIVE_CACHE_TTL_SECONDS = 5 * 60

PHOTO_CACHE_TTL_SECONDS = 24 * 60 * 60
PHOTO_NEGATIVE_CACHE_TTL_SECONDS = 5 * 60

_route_cache = {}
_photo_cache = {}
_photo_http_lock = threading.Lock()
_last_photo_http_at = time.monotonic()


class UpstreamUnavailableError(Exception):
    pass


class UpstreamTimeoutError(Exception):
    pass


def fetch_atc_feed(lat, lon, altitude_ft):
    """Resolve the closest applicable LiveATC feed for a position, or None."""
    return find_atc_feed(lat, lon, altitude_ft)


def get_liveatc_url(lat, lon, altitude_ft):
    """Stream URL for the closest LiveATC feed for a position, or None."""
    feed = fetch_atc_feed(lat, lon, altitude_ft)
    return feed["stream_url"] if feed else None


def fetch_route(callsign):
    """Fetch the route for a callsign from adsbdb, cached in-memory per process."""
    if not callsign:
        return None

    key = callsign.strip().upper()
    now = time.time()

    cached = _route_cache.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]

    try:
        response = requests.get(
            f"{settings.ADSBDB_BASE_URL}/callsign/{key}",
            timeout=settings.ADSBDB_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        _route_cache[key] = (now + ROUTE_NEGATIVE_CACHE_TTL_SECONDS, None)
        return None

    flightroute = None
    if isinstance(payload, dict):
        response_obj = payload.get("response")
        if isinstance(response_obj, dict):
            flightroute = response_obj.get("flightroute")

    route = _parse_route(flightroute) if isinstance(flightroute, dict) else None
    _route_cache[key] = (now + ROUTE_CACHE_TTL_SECONDS, route)
    return route


def fetch_plane_photo(hex_id):
    """Fetch the most recent spotter photo for a hex from planespotters, cached per process."""
    if not hex_id:
        return None

    key = hex_id.strip().lower()
    now = time.time()

    cached = _photo_cache.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]

    global _last_photo_http_at
    with _photo_http_lock:
        elapsed = time.monotonic() - _last_photo_http_at
        if 0 < elapsed < settings.PLANESPOTTERS_MIN_INTERVAL_SECONDS:
            return None
        _last_photo_http_at = time.monotonic()

    try:
        response = requests.get(
            f"{settings.PLANESPOTTERS_BASE_URL}/photos/hex/{key}",
            timeout=settings.PLANESPOTTERS_TIMEOUT_SECONDS,
            headers={"User-Agent": settings.PLANESPOTTERS_USER_AGENT},
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        _photo_cache[key] = (now + PHOTO_NEGATIVE_CACHE_TTL_SECONDS, None)
        return None

    photo = None
    if isinstance(payload, dict):
        photos = payload.get("photos")
        if isinstance(photos, list) and photos:
            photo = _parse_photo(photos[0])

    _photo_cache[key] = (now + PHOTO_CACHE_TTL_SECONDS, photo)
    return photo


def fetch_nearby_planes(lat, lon, radius):
    """Fetch aircraft from adsb.lol and map to the internal contract."""
    url = f"{settings.ADSB_BASE_URL}/lat/{lat}/lon/{lon}/dist/{radius}"
    try:
        response = requests.get(url, timeout=settings.ADSB_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.exceptions.Timeout as exc:
        raise UpstreamTimeoutError() from exc
    except requests.RequestException as exc:
        raise UpstreamUnavailableError() from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise UpstreamUnavailableError() from exc

    if not isinstance(payload, dict) or payload.get("msg") != "No error":
        raise UpstreamUnavailableError()

    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    ac_list = payload.get("ac") or []
    planes = [
        plane
        for plane in (_parse_ac(ac, lat, lon) for ac in ac_list)
        if plane["hex_id"] is not None
    ]
    for plane in planes:
        plane["route"] = fetch_route(plane["callsign"])

    return {
        "planes": planes,
        "user_lat": lat,
        "user_lon": lon,
        "radius_km": radius,
        "count": len(planes),
        "fetched_at": fetched_at,
    }


def fetch_closest_plane(lat, lon, radius=15):
    """Return the closest airborne aircraft that has route data, or None."""
    result = fetch_nearby_planes(lat, lon, radius)
    candidates = [
        p
        for p in result["planes"]
        if p["distance_km"] is not None
        and isinstance(p["altitude_ft"], (int, float))
        and p["altitude_ft"] > 0
        and p["route"] is not None
    ]
    closest = min(candidates, key=lambda p: p["distance_km"], default=None)
    return {
        "plane": closest,
        "user_lat": result["user_lat"],
        "user_lon": result["user_lon"],
        "radius_km": result["radius_km"],
        "fetched_at": result["fetched_at"],
    }


def _plane_distance_bearing(lat, lon, plane_lat, plane_lon):
    """Distance (km) and bearing (degrees) from origin to aircraft."""
    distance = haversine(lat, lon, plane_lat, plane_lon)
    dlon = radians(plane_lon - lon)
    y = sin(dlon) * cos(radians(plane_lat))
    x = cos(radians(lat)) * sin(radians(plane_lat)) - sin(radians(lat)) * cos(radians(plane_lat)) * cos(dlon)
    bearing = (degrees(atan2(y, x)) + 360) % 360
    return distance, bearing


def _parse_route(flightroute):
    """Map an adsbdb flightroute object to the internal flattened route shape."""
    origin = flightroute.get("origin") or {}
    destination = flightroute.get("destination") or {}
    airline = flightroute.get("airline") or {}
    return {
        "callsign_iata": flightroute.get("callsign_iata"),
        "airline_name": airline.get("name"),
        "airline_icao": airline.get("icao"),
        "airline_iata": airline.get("iata"),
        "origin_iata": origin.get("iata_code"),
        "origin_icao": origin.get("icao_code"),
        "origin_name": origin.get("name"),
        "origin_city": origin.get("municipality"),
        "origin_country": origin.get("country_name"),
        "destination_iata": destination.get("iata_code"),
        "destination_icao": destination.get("icao_code"),
        "destination_name": destination.get("name"),
        "destination_city": destination.get("municipality"),
        "destination_country": destination.get("country_name"),
    }


def _parse_photo(photo):
    """Map a planespotters photo object to the internal photo shape."""
    thumbnail = photo.get("thumbnail") or {}
    thumbnail_large = photo.get("thumbnail_large") or {}
    return {
        "url": thumbnail_large.get("src"),
        "thumbnail_url": thumbnail.get("src"),
        "photographer": photo.get("photographer"),
        "link": photo.get("link"),
    }


def _parse_ac(ac, user_lat, user_lon, now=None):
    plane_lat = ac.get("lat")
    plane_lon = ac.get("lon")

    distance_km, bearing = (
        _plane_distance_bearing(user_lat, user_lon, plane_lat, plane_lon)
        if plane_lat is not None and plane_lon is not None
        else (None, None)
    )

    altitude_ft = ac.get("alt_baro")
    if isinstance(altitude_ft, str) and altitude_ft != "ground":
        try:
            altitude_ft = int(altitude_ft)
        except (TypeError, ValueError):
            altitude_ft = None

    atc_layer = _ams_atc_layer(
        plane_lat,
        plane_lon,
        altitude_ft,
        ground_speed_knots=ac.get("gs"),
        vertical_rate_fpm=ac.get("baro_rate"),
        now=now,
    )

    return {
        "callsign": (ac.get("flight") or "").strip(),
        "tail_number": ac.get("r"),
        "hex_id": ac.get("hex"),
        "distance_km": round(distance_km, 3) if distance_km is not None else None,
        "bearing": round(bearing, 1) if bearing is not None else None,
        "altitude_ft": altitude_ft,
        "altitude_geom_ft": ac.get("alt_geom"),
        "speed_knots": ac.get("gs"),
        "track_deg": ac.get("track"),
        "vertical_rate_fpm": ac.get("baro_rate"),
        "aircraft_type": ac.get("t"),
        "squawk": ac.get("squawk"),
        "emergency": ac.get("emergency", "none"),
        "liveatc_stream_url": (
            atc_layer["stream_url"]
            if atc_layer is not None
            else get_liveatc_url(plane_lat, plane_lon, altitude_ft)
        ),
        "liveatc_frequency": atc_layer["frequency"] if atc_layer is not None else None,
    }


def _ams_atc_layer(
    lat,
    lon,
    altitude_ft,
    ground_speed_knots=None,
    vertical_rate_fpm=None,
    now=None,
):
    """Stream and frequency for the Amsterdam ACC layer covering a position.

    Layered by altitude and distance from EHAM: ground ops (delivery when
    slow, else ground) on the airfield, tower within 6 nm, TMA app/dep within
    35 nm, ACC radar sectors within 150 nm (night band-box merged), then MUAC.
    ACC sectors without a live feed fall back to the nearest live Amsterdam
    radar stream (eham_rdr_sw). Returns None outside AMS coverage.
    """
    dist_nm = _ams_distance_nm(lat, lon)

    if altitude_ft == "ground":
        if dist_nm is None or dist_nm >= AMS_GROUND_RADIUS_NM:
            return None
        if ground_speed_knots is not None and ground_speed_knots < 5:
            return {"stream_url": AMS_DELIVERY_STREAM, "frequency": AMS_DELIVERY_FREQ_MHZ}
        return {"stream_url": AMS_GROUND_STREAM, "frequency": AMS_GROUND_FREQ_MHZ}

    if not isinstance(altitude_ft, (int, float)) or altitude_ft <= 0:
        return None

    if dist_nm is not None and dist_nm <= AMS_TOWER_RADIUS_NM and altitude_ft <= AMS_TOWER_MAX_ALT_FT:
        return {"stream_url": AMS_TOWER_STREAM, "frequency": AMS_TOWER_FREQ_MHZ}

    if (
        dist_nm is not None
        and dist_nm <= AMS_TMA_RADIUS_NM
        and AMS_TOWER_MAX_ALT_FT < altitude_ft <= AMS_TMA_MAX_ALT_FT
    ):
        if vertical_rate_fpm is not None and vertical_rate_fpm > 300:
            return {
                "stream_url": AMS_DEPARTURE_STREAM,
                "frequency": AMS_DEPARTURE_FREQ_MHZ,
            }
        return {"stream_url": AMS_APPROACH_STREAM, "frequency": AMS_APPROACH_FREQ_MHZ}

    if (
        dist_nm is not None
        and dist_nm <= AMS_ACC_RADIUS_NM
        and AMS_TMA_MAX_ALT_FT < altitude_ft <= AMS_ACC_MAX_ALT_FT
    ):
        if is_night_bandbox_active(now):
            return {"stream_url": AMS_ACC_STREAM, "frequency": AMS_NIGHT_FREQ_MHZ}
        freq = AMS_SECTOR_FREQS[_ams_acc_sector_key(lat, lon)]
        return {"stream_url": AMS_ACC_STREAM, "frequency": freq}

    if (
        dist_nm is not None
        and dist_nm <= AMS_MUAC_RADIUS_NM
        and altitude_ft > AMS_ACC_MAX_ALT_FT
    ):
        return {"stream_url": AMS_MUAC_STREAM, "frequency": AMS_MUAC_FREQ_MHZ}

    return None


def is_night_bandbox_active(now=None):
    """True when Amsterdam ACC sectors are merged into the 124.300 band-box."""
    if now is None:
        now = datetime.now(timezone.utc)
    return now.hour >= AMS_NIGHT_START_HOUR_UTC or now.hour < AMS_NIGHT_END_HOUR_UTC


def _ams_distance_nm(lat, lon):
    """Distance from Schiphol (EHAM) in nautical miles, or None."""
    if lat is None or lon is None:
        return None
    return haversine(EHAM_LAT, EHAM_LON, lat, lon) / KM_PER_NM


def _ams_acc_sector_key(lat, lon):
    """Amsterdam ACC sector name by position when the North band does not apply."""
    if lat > AMS_ACC_NORTH_BAND_LAT:
        return "north"
    if lon < EHAM_LON:
        return "northwest" if lat > EHAM_LAT else "southwest"
    return "east" if lat > EHAM_LAT else "south"