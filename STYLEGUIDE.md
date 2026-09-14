# Django Backend Style Guide

Coding standards for the `tracker` app and the `flighttracker` project. Follow these for new code and when editing existing files.

## 1. Module layout

Order every module top to bottom:

1. Module docstring (when the module is non-obvious).
2. `import` statements in three groups, blank line between each (see "Imports").
3. Module-level constants (e.g. `RADIUS_KM`, `_route_cache`).
4. `logger = logging.getLogger(__name__)`.
5. **Public functions and classes** — the API surface of the module.
6. **Private helpers last** — everything prefixed with `_` goes at the bottom of the file.

`tracker/atc.py` follows this: constants, public `haversine` / `feed_stream_url` / `find_atc_feed`, then private `_feed_applies` / `_to_feed_dict` at the bottom.

> Existing files that interleave private helpers with public functions (e.g. `tracker/services.py` currently defines `_plane_distance_bearing` and `_parse_ac` before `fetch_nearby_planes`) should be reordered to private-last as they are touched.

## 2. Naming

- **Snake-case everything** in Python: `altitude_baro_ft`, `fetch_nearby_planes`, not `altitudeBaroFt`, not `fetchNearbyPlanes`.
- **Private members** use a single leading underscore: `_parse_ac`, `_feed_applies`. Never use trailing underscores or dunder-style names except `__init__`/`__all__`.
- Classes are `PascalCase` (`PlaneSerializer`); module-level functions and variables are `snake_case`.
- Constants are `UPPER_SNAKE_CASE` (`ADSB_BASE_URL`, `ROUTE_CACHE_TTL_SECONDS`).
- The JSON **wire format stays snake_case too** (`distance_km`, `liveatc_stream_url`). Upstream short keys from adsb.lol (`hex`, `r`, `t`, `gs`) must be mapped to descriptive names where they cross the boundary (see `_parse_ac` in `services.py`) — never leak `ac.get("t")` directly into a payload.

## 3. Imports

- Three groups, in this order, separated by blank lines:
  1. standard library (`os`, `math`, `datetime`)
  2. third-party (`requests`, `django`, `rest_framework`)
  3. project-local modules
- **Verbose absolute paths, anchored at the project root.** Prefer `from tracker.atc import find_atc_feed` over `from .atc import find_atc_feed`. No relative imports, no `import *`, no aliasing just to shorten (`import tracker.services as s` is banned).
- This repo currently has one offender: `tracker/services.py` does `from .atc import ...  # noqa: E402` placed after `logger`. Change it to `from tracker.atc import feed_stream_url, find_atc_feed, haversine` in the third import group, and remove the `noqa` comment.
- **Zero unused imports.** Delete code you no longer import from. Use `ruff`/`pyflakes` locally to verify (see §6); `requirements.txt` must match what the code actually imports (currently all four — Django, DRF, corsheaders, requests — are used).

## 4. Module boundaries ("split out common functions")

- Put shared, reusable logic in its own module rather than inlining it into views or services.
- `tracker/atc.py` is the canonical example: radio/ATC concerns (feed catalog, radii, altitude ceilings, haversine, stream URLs) live there; `tracker/services.py` imports from it instead of re-implementing.
- Rules of thumb:
  - Anything reusable in ≥2 places moves to a dedicated module (`tracker/atc.py`, or a new `tracker/http.py` for a shared `requests`-based fetcher once more than one caller needs it).
  - Views stay thin: validate with serializers, delegate everything else to `services.py`.
  - One module = one concern. If a file covers ATC + photos + kangaroos, it needs splitting.

## 5. Public/private contract

- Every function and method has a docstring only when its purpose isn't obvious from the name (existing code keeps them short — follow that).
- Private functions are reachable only within their module. If something becomes a `_`-prefixed helper in one file, do not import it elsewhere: promote it to a shared module as a public function instead.
- No code comments for step-by-step explanation beyond what a docstring already covers; use them sparingly for non-obvious decisions (e.g. the tower-radius tuning in `atc.py`).

## 6. Verification

The WSL host can't install Django, so run checks in the container:

```sh
docker compose run --rm web python manage.py test
docker compose run --rm web pip install --quiet ruff && docker compose run --rm web ruff check tracker/
```

`ruff` flags unused imports, non-snake-case names, and undefined names; fix everything it reports before pushing.