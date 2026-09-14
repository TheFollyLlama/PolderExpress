# ADS-B API Payload Contract

Mapping from `api.adsb.lol/v2` (aircraft) and `api.adsbdb.com/v0` (route) to the Django backend at `POST /api/v1/nearby-planes/`.

## Upstream Sources

### Aircraft positions

```
GET https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{radius}
```

Response wraps aircraft in the `"ac"` array. Each object contains raw ADS-B fields.

### Route data (per callsign)

```
GET https://api.adsbdb.com/v0/callsign/{callsign}
```

Response shape (on success):

```json
{
  "response": {
    "flightroute": {
      "callsign": "TRA75U",
      "callsign_iata": "HV75U",
      "airline": {
        "name": "Transavia Holland",
        "icao": "TRA",
        "iata": "HV",
        "country": "Netherlands",
        "country_iso": "NL"
      },
      "origin": {
        "iata_code": "IBZ",
        "icao_code": "LEIB",
        "name": "Ibiza Airport",
        "municipality": "Ibiza",
        "country_name": "Spain"
      },
      "destination": {
        "iata_code": "AMS",
        "icao_code": "EHAM",
        "name": "Amsterdam Airport Schiphol",
        "municipality": "Amsterdam",
        "country_name": "Netherlands"
      }
    }
  }
}
```

When no route is available adsbdb returns `{"response": "No flightroute found"}` (no `flightroute` key). These are cached as `null` for 5 minutes. Successful lookups are cached in-process for 6 hours.

---

## Request — `POST /api/v1/nearby-planes/`

| Field   | Type    | Description                          | Example       |
|---------|---------|--------------------------------------|---------------|
| `lat`   | float   | User latitude (decimal degrees, WGS84) | `33.7490`  |
| `lon`   | float   | User longitude (decimal degrees, WGS84) | `-84.3880` |
| `radius`| integer | Search radius in km (max 250)        | `15`          |

```json
{
  "lat": 33.749,
  "lon": -84.388,
  "radius": 15
}
```

---

## Response — 200 OK

| Field                | Type          | Source (adsb.lol `ac.*`) | Description                                  |
|----------------------|---------------|---------------------------|----------------------------------------------|
| `callsign`           | string        | `flight`                  | Trimmed flight callsign                      |
| `tail_number`        | string \| null| `r`                       | Aircraft registration (tail number)          |
| `hex_id`             | string        | `hex`                     | ICAO 24-bit transponder address              |
| `distance_km`        | float         | `dst`                     | Distance from user in km                     |
| `bearing`            | float \| null | `dir`                     | Bearing from user in degrees                 |
| `altitude_ft`        | int \| "ground" | `alt_baro`              | Barometric altitude in feet, or `"ground"`   |
| `altitude_geom_ft`   | int \| null   | `alt_geom`                | Geometric altitude in feet (if available)    |
| `speed_knots`        | float         | `gs`                      | Ground speed in knots                        |
| `track_deg`          | float \| null | `track`                   | True track in degrees                        |
| `vertical_rate_fpm`  | int \| null   | `baro_rate`               | Barometric vertical rate in ft/min           |
| `aircraft_type`      | string \| null| `t`                       | ICAO aircraft type code                      |
| `squawk`             | string \| null| `squawk`                  | Transponder squawk code                      |
| `emergency`          | string        | `emergency`               | Emergency status (`"none"` if normal)        |
| `liveatc_stream_url` | string \| null| *(computed)*              | LiveATC MP3 stream URL for nearest feed      |
| `liveatc_frequency`  | string \| null| *(not emitted)*           | Reserved. The backend does **not** currently emit this field. The frontend player renders `plane.liveatc_frequency` whenever a response includes it and drops the freq text otherwise. |
| `route`             | object \| null| *(adsbdb)*                | Flattened flight route (see below)           |
| `fetched_at`         | datetime      | *(server-side)*           | ISO 8601 timestamp of the fetch              |

### Example Response

```json
{
  "planes": [
    {
      "callsign": "DAL441",
      "tail_number": "N919AT",
      "hex_id": "acb82c",
      "distance_km": 48.337,
      "bearing": 242.0,
      "altitude_ft": 14425,
      "altitude_geom_ft": 15400,
      "speed_knots": 372.8,
      "track_deg": 76.19,
      "vertical_rate_fpm": -2368,
      "aircraft_type": "B712",
      "squawk": "3473",
      "emergency": "none",
      "liveatc_stream_url": "http://d.liveatc.net/katl_ztl22.mp3",
      "route": {
        "callsign_iata": "DL441",
        "airline_name": "Delta Air Lines",
        "airline_icao": "DAL",
        "airline_iata": "DL",
        "origin_iata": "TPA",
        "origin_icao": "KTPA",
        "origin_name": "Tampa International Airport",
        "origin_city": "Tampa",
        "origin_country": "United States",
        "destination_iata": "ATL",
        "destination_icao": "KATL",
        "destination_name": "Hartsfield-Jackson Atlanta International Airport",
        "destination_city": "Atlanta",
        "destination_country": "United States"
      },
      "fetched_at": "2025-01-15T03:41:52Z"
    }
  ],
  "user_lat": 33.749,
  "user_lon": -84.388,
  "radius_km": 50,
  "count": 1,
  "fetched_at": "2025-01-15T03:41:52Z"
}
```

---

## Closest Plane — `POST /api/v1/closest/`

Finds the **closest airborne aircraft that also has route data** within the search radius. Shares the same request shape as `nearby-planes/`:

```json
{
  "lat": 33.749,
  "lon": -84.388,
  "radius": 15
}
```

### Response — 200 OK

| Field      | Type        | Description                                          |
|------------|-------------|------------------------------------------------------|
| `plane`    | object \| null | Closest qualifying `Plane` object, or `null` if none found |
| `user_lat` | float       | Echo of request `lat`                                |
| `user_lon` | float       | Echo of request `lon`                                |
| `radius_km`| integer     | Echo of request `radius`                             |
| `fetched_at` | datetime   | ISO 8601 timestamp of the fetch                      |

### Selection rules

Candidates must satisfy all of:
- `distance_km` is not `null` (position is known)
- `altitude_ft` is a positive number — airborne, i.e. **not** the string `"ground"`
- `route` is not `null` — adsbdb returned a flight route

The candidate with the smallest `distance_km` wins. Returns `plane: null` (200) when no aircraft qualifies.

```json
{
  "plane": {
    "callsign": "TRA75U",
    "tail_number": "PH-TFN",
    "hex_id": "484e32",
    "distance_km": 12.04,
    "route": { "...": "..." }
  },
  "user_lat": 33.749,
  "user_lon": -84.388,
  "radius_km": 15,
  "fetched_at": "2025-01-15T03:41:52Z"
}
```

---

## Field Mapping Details

### `callsign`

```python
callsign = ac["flight"].strip()  # adsb.lol pads with trailing spaces
```

### `altitude_ft`

`alt_baro` may be the string `"ground"` for aircraft on the surface. Map to the string literal `"ground"` in JSON or `0` / `None` in the database — do not cast to `int` directly.

```python
altitude = ac.get("alt_baro")  # int or "ground"
```

### `distance_km` and `bearing`

These are computed server-side using the Haversine formula against the user's `lat`/`lon` and each aircraft's `lat`/`lon`. They are **not** re-read from the upstream `dst`/`dir` fields — those are relative to the query point in the URL and are identical, but computing locally gives us flexibility if the user's stored location differs.

```python
from math import radians, sin, cos, sqrt, atan2

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))
```

### `liveatc_stream_url`

Determined by matching the aircraft's position against the LiveATC feed catalog in `tracker/atc.py` via `find_atc_feed`. Feeds are scoped by **kind**, each with its own coverage radius and altitude ceiling:

| Kind      | Radius (km) | Altitude ceiling | Feeds                                                        |
|-----------|-------------|------------------|--------------------------------------------------------------|
| `ground`  | 15          | on surface only  | Schiphol Ground, Atlanta Ground                              |
| `tower`   | 1           | below 1,000 ft   | Schiphol Tower, Atlanta Tower                                |
| `appdep`  | 50          | below 24,000 ft  | Schiphol Departure, Schiphol Approach, Atlanta Approach      |
| `center`  | 200         | none             | Maastricht Upper Area Control (MUAC), Atlanta Center (ZTL)   |

Selection rules:

- Only feeds within their radius are candidates.
- `ground` applies only when the aircraft is on the surface (`altitude_ft == "ground"`).
- `tower` is intentionally narrow (1 km, below **1,000** ft) so airborne traffic near the field resolves to approach/departure; `appdep` covers **below** 24,000 ft — the ceiling is exclusive (`>=`): exactly 1,000 ft falls in `appdep`, exactly 24,000 ft falls in `center`.
- Kind priority resolves candidates that overlap: `ground` → `tower` → `appdep` → `center` (ties broken by closest distance).
- If nothing matches, fall back to the nearest `center` feed regardless of distance, so a feed is returned whenever a valid lat/lon is present — `null` is returned only when lat or lon is absent.

### `route`

Enriched per aircraft after the adsb.lol fetch, keyed by the trimmed uppercase callsign. Server-side lazy fetch against adsbdb with an in-process LRU-style cache:

```python
def fetch_route(callsign):
    ...
```

Caching:
- Hits (route found): 6 hours.
- Misses (`"No flightroute found"`, network/HTTP error, parse failure): 5 minutes, cached as `null`.

Network/HTTP/JSON failures are swallowed — `route` is `null` rather than failing the whole response. Unknown/general-aviation callsigns (e.g. `N123AB`, `HELI1`) will usually return `null`.

### `photo` (on-demand, isolated)

Planespotters is **isolated**: it is never called as part of the `nearby-planes/` or `closest/` flows. The frontend calls a dedicated endpoint when the user enters the closest/detailed aircraft view:

```
GET /api/v1/photo/{hex_id}/
```

The closest page lives at its own URL and refreshes flight data and photos on different cadences:

| URL                | Page                                   | Refresh policy |
|--------------------|----------------------------------------|----------------|
| `/`                | Tracker grid (SPA)                     | flight list every 15s |
| `/closest/`        | Closest airborne detail page           | flight data every 15s; photo on load, when `hex_id` changes, or every 5 min (whichever first); manual Refresh forces a photo refetch |

This keeps photo requests far below the flight-data cadence and preserves the isolation rule (the grid page never calls Planespotters).

| Status | Body                                            |
|--------|-------------------------------------------------|
| `200`  | `{"hex_id": "a34aa0", "photo": {...} \| null}`  |
| `400`  | `{"error": "hex_id must be a 6-character ICAO hex code"}` |

Server-side lookup against Planespotters.net `/pub/photos/hex/{hex}`, keyed by the lowercase ICAO 24-bit hex, with an in-process LRU-style cache:

```python
def fetch_plane_photo(hex_id):
    ...
```

Planespotters requires a descriptive `User-Agent` header (the default library User-Agent is rejected with HTTP 403). The header is configurable via the `PLANESPOTTERS_USER_AGENT` environment variable.

```json
{
  "photos": [
    {
      "id": "1486276",
      "thumbnail": {"src": "https://t.plnspttrs.net/..._t.jpg", "size": {"width":200, "height":125}},
      "thumbnail_large": {"src": "https://t.plnspttrs.net/..._280.jpg", "size": {"width":448, "height":280}},
      "link": "https://www.planespotters.net/photo/1486276/...?utm_source=api",
      "photographer": "Donald e Moore"
    }
  ]
}
```

Only the first photo is mapped. If `photos` is empty or missing the result is `null`.

Rate limiting: Planespotters aggressively rate-limits burst traffic from one IP (returns HTTP 403 even with a valid `User-Agent`). `fetch_plane_photo` therefore enforces a process-wide minimum interval between HTTP calls (`PLANESPOTTERS_MIN_INTERVAL_SECONDS`, default `1.5`). When a request arrives too soon after the previous one, the hex is skipped (uncached) and returns `null` — it can be retried on a later request without hammering the API.

Caching:
- Hits (at least one photo found): 24 hours.
- Misses (empty list, network/HTTP error, parse failure): 5 minutes, cached as `null`.

Network/HTTP/JSON failures are swallowed — `photo` is `null` rather than failing the whole response. Unknown/removed aircraft will usually return `null`.

### `atc` (on-demand, isolated)

The ATC feed lookup described above is also exposed standalone for diagnostics and direct frontend use — isolated from the `nearby-planes/` and `closest/` flows:

```
GET /api/v1/atc/?lat={lat}&lon={lon}&altitude={feet|ground}
```

| Param      | Required | Type            | Description                                    |
|------------|----------|-----------------|------------------------------------------------|
| `lat`      | yes      | float           | Position latitude, -90 to 90                   |
| `lon`      | yes      | float           | Position longitude, -180 to 180                |
| `altitude` | no       | int \| `"ground"` | Altitude in feet, or the string `"ground"`   |

| Status | Body                                                             |
|--------|------------------------------------------------------------------|
| `200`  | `{"feed": {"name": "...", "kind": "...", "stream_url": "...", "distance_km": 0.0, "altitude_ceiling_ft": null}}` |
| `400`  | DRF serializer errors for missing/invalid `lat`/`lon`; `{"error": "lat must be between -90 and 90"}` / `{"error": "lon must be between -180 and 180"}` for out-of-range coordinates; `{"error": "altitude must be a number in feet or 'ground'"}` for invalid altitude |
| `405`  | Non-GET methods are not allowed                                 |

The `feed` object mirrors the `liveatc_stream_url` selection output: `name`, `kind`, `stream_url`, `distance_km`, and `altitude_ceiling_ft` (`null` for `center` feeds). Because the resolver falls back to the nearest `center`, `feed` is `null` only when lat/lon are absent (which is itself a `400` at this endpoint).

---

## Upstream → Internal Field Map (Quick Reference)

| adsb.lol `ac` field | Internal field       | Transform                     |
|----------------------|----------------------|-------------------------------|
| `hex`                | `hex_id`             | passthrough                   |
| `flight`             | `callsign`           | `.strip()`                    |
| `r`                  | `tail_number`        | passthrough, nullable         |
| `t`                  | `aircraft_type`      | passthrough, nullable         |
| `alt_baro`           | `altitude_ft`        | passthrough (int or `"ground"`) |
| `alt_geom`           | `altitude_geom_ft`   | passthrough, nullable         |
| `gs`                 | `speed_knots`        | passthrough                   |
| `track`              | `track_deg`          | passthrough, nullable         |
| `baro_rate`          | `vertical_rate_fpm`  | passthrough, nullable         |
| `squawk`             | `squawk`             | passthrough, nullable         |
| `emergency`          | `emergency`          | passthrough                   |
| `lat`, `lon`         | *(not exposed)*      | used for Haversine only       |
| `dst`                | *(not used)*         | recomputed server-side        |
| `dir`                | `bearing`            | recomputed server-side        |

### adsbdb route → internal (`route.*`)

| adsbdb field         | Internal field        | Transform                     |
|----------------------|-----------------------|-------------------------------|
| `callsign_iata`      | `route.callsign_iata` | passthrough, nullable         |
| `airline.name`       | `route.airline_name`  | passthrough, nullable         |
| `airline.icao`       | `route.airline_icao`  | passthrough, nullable         |
| `airline.iata`       | `route.airline_iata`  | passthrough, nullable         |
| `origin.iata_code`   | `route.origin_iata`   | passthrough, nullable         |
| `origin.icao_code`   | `route.origin_icao`   | passthrough, nullable         |
| `origin.name`        | `route.origin_name`   | passthrough, nullable         |
| `origin.municipality`| `route.origin_city`   | passthrough, nullable         |
| `origin.country_name`| `route.origin_country`| passthrough, nullable         |
| `destination.iata_code` | `route.destination_iata` | passthrough, nullable    |
| `destination.icao_code` | `route.destination_icao` | passthrough, nullable    |
| `destination.name`      | `route.destination_name` | passthrough, nullable    |
| `destination.municipality` | `route.destination_city` | passthrough, nullable |
| `destination.country_name` | `route.destination_country` | passthrough, nullable |

### planespotters photo → internal (`photo.*`)

| photo field              | Internal field      | Transform                                              |
|--------------------------|---------------------|--------------------------------------------------------|
| `photos[0].thumbnail_large.src` | `photo.url`        | passthrough, nullable |
| `photos[0].thumbnail.src`       | `photo.thumbnail_url` | passthrough, nullable |
| `photos[0].photographer`        | `photo.photographer` | passthrough, nullable |
| `photos[0].link`                | `photo.link`        | passthrough, nullable |

Only `photos[0]` is used. `photos: []` → `null`. Uses first photo; lookups keyed by lowercase hex.

---

## Error Responses

| Status | Body                                        | Cause                          |
|--------|---------------------------------------------|--------------------------------|
| `400`  | `{"error": "lat, lon, and radius required"}`| Missing or invalid parameters  |
| `400`  | `{"error": "radius must be 1-250"}`         | Radius out of range            |
| `502`  | `{"error": "upstream adsb.lol unavailable"}` | adsb.lol timeout or error      |
| `504`  | `{"error": "upstream request timed out"}`   | adsb.lol did not respond in time |

---

## Rate Limiting

- adsb.lol public API: no documented rate limit, but be respectful (≤ 1 req/sec recommended).
- adsbdb public API: free tier has documented per-minute/hour/month limits — the in-process route cache (6h hits / 5m misses) keeps lookups to 1 per unique callsign per window.
- planespotters.net photos API: free, requires a descriptive `User-Agent`; the in-process photo cache (24h hits / 5m misses) plus the per-process min-interval throttle (`PLANESPOTTERS_MIN_INTERVAL_SECONDS`, default 1.5s) keep lookups well under the burst limits.
- Django endpoints: DRF throttling via `rest_framework.throttling.AnonRateThrottle` / `UserRateThrottle` — **30 req/min** for anonymous and **60 req/min** for authenticated users (configured under `REST_FRAMEWORK` in `flighttracker/settings.py`).

---

## Frontend Behavior

Two Django-rendered pages consume the API. The app is branded **PolderExpress**; both tabs carry a plane-emoji SVG data-URI favicon, and both are plain-vanilla-JS single-page pages.

| Page          | URL         | Tab title                | Behavior                                                                         |
|---------------|-------------|--------------------------|----------------------------------------------------------------------------------|
| Tracker grid  | `/`         | `PolderExpress`          | Polls `nearby-planes/` every 15 s; renders cards sorted by distance              |
| Closest plane | `/closest/` | `Closest - PolderExpress`| Polls `closest/` every 15 s; auto-tunes the LiveATC player to the closest plane  |

### LiveATC audio player

Both pages share a bottom player bar:

- Play/pause toggle with a pulsing "listening" indicator while streaming.
- Volume slider (0-100) persisted to `localStorage` under `atc-volume` (default 80).
- Tracker grid: clicking a card with a `liveatc_stream_url` starts that stream; clicking the active card stops it.
- Closest page: starting a feed is automatic (`autoTune`) whenever the current plane changes; closing the player records `dismissedUrl` so the same feed is not re-tuned until it errors or the page reloads.
- Stream failures set the player label to `Stream unavailable`; on the grid page the active card is also un-highlighted.

### Airline callsign-name display (closest page)

The closest page resolves a human-readable airline name to show beside the callsign using the `CALLSIGNS` map in `tracker/templates/tracker/closest.html` (each line maps an IATA/ICAO pair to the same name, e.g. `BA: 'Speedbird', BAW: 'Speedbird'`). Resolution order:

1. `route.airline_iata` / `route.airline_icao` from the route payload.
2. The leading 2-3 letters of the callsign against the map (e.g. `DAL441` → `Delta`).
3. A 3-letter prefix that maps to a 2-letter IATA entry, else blank.

The map is kept alphabetized by key.
