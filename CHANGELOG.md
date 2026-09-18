# Changelog

All notable changes to this project are documented in this file.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/), and this project aims to adhere to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Nothing yet.

## [0.1.0] - 2026-09-18

First release: FlightTracker is a nearby-aircraft tracker with a Django REST backend that proxies live ADS-B feeds and static data sources (routes, photos, LiveATC audio), plus two HTML pages that use the browser's geolocation to show planes around you.

### Added

- **Nearby-planes page (`/`)** — tile grid of aircraft within radius (callsign, tail, altitude, speed), with route, photo, and ATC audio per plane.
- **Closest-plane page (`/closest/`)** — single nearest airborne aircraft with photo, route, stats, and a LiveATC player.
- **Live map (adsb.lol embed)** on both pages, loaded once on geolocation and centered on the user (Schiphol default to speed up initial load); on `/closest/` the map highlights and centers on the closest aircraft and zooms out to keep it in view.
- **Backend API** under `/api/v1/`:
  - `POST nearby-planes/` — `{lat, lon, radius}` → aircraft with route/photo/ATC enrichment.
  - `POST closest/` — same input, returns the nearest plane.
  - `GET photo/<hex_id>/` — cached Planespotters photo for a 6-char ICAO hex.
  - `GET atc/?lat=&lon=&altitude=` — LiveATC feed lookup for arbitrary positions (test/debug).
- **Amsterdam ACC layer resolution** — altitudes/distance from EHAM map to delivery, ground, tower, TMA approach/departure, the five radar sectors (with the 124.300 night band-box), and MUAC, emitting `liveatc_frequency` alongside the nearest-live stream.
- **Payload contract** (`adsb_contract.md`) documenting every field and its upstream source.
- **Features from the backlog**: STYLEGUIDE for backend/frontend conventions; web map on both pages.

### Known limitations

- ATC audio and ACC-layer tuning are Amsterdam-specific (with an Atlanta fallback cluster); ADS-B positions, routes, and photos are global. See README "Moving away from the Amsterdam area".
- Pages require HTTPS or `localhost` for `getCurrentPosition` geolocation.
- No database models — `migrate` needed only for the Django admin.
- No flight history yet; map centering on `/closest/` recenters only when the closest aircraft changes (not every poll).