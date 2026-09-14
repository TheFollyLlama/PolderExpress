# FlightTracker

Nearby-aircraft tracker: a Django REST backend that proxies live ADS-B feeds and static data sources, plus two HTML pages that use the browser's geolocation to show planes around you.

## Pages

| URL        | What it does                                                            |
|------------|-------------------------------------------------------------------------|
| `/`        | Tile grid of nearby aircraft (callsign, tail, altitude, speed, photos, ATC audio per plane) |
| `/closest/`| Single "closest plane" view: photo, route, stats, and an ATC audio player for that plane |

Both pages ask for browser location via `getCurrentPosition` (HTTPS or `localhost` required), then POST the coords to the backend.

## API (all under `/api/v1/`)

- `POST nearby-planes/` — `{lat, lon, radius}` → nearby aircraft with route/photo/ATC enrichment.
- `POST closest/` — same input, returns the single nearest plane.
- `GET photo/<hex_id>/` — cached Planespotters photo for a 6-char ICAO hex.
- `GET atc/?lat=&lon=&altitude=` — pick a LiveATC feed for an arbitrary position (for testing/debugging; the pages get the feed via the plane endpoint).

See `adsb_contract.md` for the full payload contract.

## Upstream sources

- **Aircraft positions**: `api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{radius}` (global, no key).
- **Route info**: `api.adsbdb.com/v0/callsign/{callsign}` (global, no key).
- **Photos**: `api.planespotters.net/pub` (public, rate-limited; throttled internally by `PLANESPOTTERS_MIN_INTERVAL_SECONDS`).
- **ATC audio**: `d.liveatc.net/<slug>.mp3`, catalogued in `tracker/atc.py`.

## Quick start

```sh
docker compose up --build      # → http://localhost:8000  (or /closest/)
```

Manual run (needs Python >= 3.10 for Django 5):

```sh
pip install -r requirements.txt
python manage.py runserver
```

`tracker` uses no database models, so `migrate` is only needed if you want the Django admin at `/admin/`.

## Configuration

Environment variables (all optional; see `flighttracker/settings.py:6-12` and `:98-103`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `DJANGO_SECRET_KEY` | insecure dev key | set to something random in production |
| `DJANGO_DEBUG` | `True` | set `False` in production |
| `DJANGO_ALLOWED_HOSTS` | `*` | comma-separated hosts |
| `PLANESPOTTERS_USER_AGENT` | `FlightTracker/1.0 (+https://example.com/...)` | must identify you; update the contact URL |
| `PLANESPOTTERS_MIN_INTERVAL_SECONDS` | `1.5` | min gap between Planespotters photo requests |

Upstream base URLs and timeouts are hardcoded in `settings.py:90-97`. API throttling is `30/min` anonymous (`settings.py:85`).

---

## Moving away from the Amsterdam area

The app is currently wired for **Schiphol (EHAM)** plus an **Atlanta (KATL)** fallback cluster. ADS-B positions (`adsb.lol`), routes (`adsbdb`), and photos (`planespotters`) are global and need **no** changes. The ATC audio and a few tuning constants are area-specific:

### 1. Replace the ATC feed catalog — `tracker/atc.py` `ATC_FEEDS` (lines 10-74)

The Amsterdam feeds (`eham_app_*`, `eham_twr_0624`, `eham_gnd_0624`, `eham_muac_135510`) will only ever match positions within their coverage radii (tower 1 km / appdep 50 km / center 200 km). Outside the Netherlands every flight falls to whatever center feed is nearest (or the KATL cluster if you keep it).

To repoint to a new airport:

- Find the airport on `liveatc.net`. The stream slug is the part of the feed URL before `.mp3`.
- Add feed entries with the airport's lat/lon and the appropriate `kind`: `ground`, `tower`, `appdep` (departure or approach), or `center` (area control).
- Keep at least one `center` feed, or the "everything is a fallback" behavior described in `adsb_contract.md` breaks (a feed is always expected when lat/lon is present).
- If you don't want the Atlanta fallback either, delete those four KATL entries.

Kind priority (`ground` → `tower` → `appdep` → `center`, `atc.py:8`) means overlapping feeds resolve most-specific-first, ties by distance.

### 2. Tune radii and ceilings — `tracker/atc.py` `RADIUS_KM` / `MAX_ALTITUDE_FT` (lines 76-86)

Tower is deliberately narrow (`1 km`, `below 1,000 ft`, was 15 km / 10,000 ft) so airborne traffic near the field resolves to approach/departure — don't blindly widen it back, or "departure" loses to tower again. `appdep` = 50 km / below 24,000 ft. Airport geometry differs, so re-test after changes (see #4).

### 3. Front-end tuning — `tracker/templates/tracker/{index,closest}.html`

- `RADIUS_KM = 15` (`index.html:53`, `closest.html:56`) — search radius sent to the backend.
- `REFRESH_MS = 15000` — how often pages re-fetch.

### 4. Update the pinned tests — `tracker/tests.py`

`LiveAtcTests` and `FindAtcFeedTests` (lines ~85-190) assert that specific KATL/EHAM coordinates resolve to specific feeds (e.g. `find_atc_feed(33.64, -84.43, 5000)` → "Atlanta Approach"). After replacing feeds or changing radii/ceilings these will fail; rewrite the coordinate + expectation pairs for your new area. `PlaneAtcViewTests` also use Schiphol coordinates — update them too.

```sh
docker compose run --rm web python manage.py test
```

### 5. Refresh `adsb_contract.md`

The feed table (lines ~232-245) names the Schiphol/Atlanta feeds and their kind rules — update names and any radius/ceiling changes so the docs match `atc.py`.

### 6. Don't change these

- `LIVEATC_BASE_URL` (`atc.py:6`) — keep `d.liveatc.net` (the old `d.drivenad.net` host was dead/NXDOMAIN).
- Positions/routes/photos are location-independent.


## TODO:
- Create and abide by a style guide; mismatch of private methods; needs structure; sort out things like the 1000 line test file
- Model history of flights
- Maybe add map?
- Convert to mobile; add directionality