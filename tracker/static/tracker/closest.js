import {
  $, setStatus, escapeHtml, formatAltitude, formatSpeed, formatDistance,
  formatVertRate, routeHtml, atcFreq, requestLocation, createPlayer
} from './shared.js';
import { callsignName } from './callsigns.js';

const API_URL = '/api/v1/closest/';
const PHOTO_URL = '/api/v1/photo/';
const REFRESH_MS = 15000;
const PHOTO_REFRESH_MS = 5 * 60 * 1000;
const RADIUS_KM = 15;
const GREEN_START_KM = 8;
const GREEN_FULL_KM = 1.5;

const bodyEl = $('#closest-body');
const photoEl = $('#closest-photo');
const statusEl = $('#status');
const statusText = $('#status-text');
const refreshBtn = $('#refresh-btn');

const player = createPlayer();

let userLat = null;
let userLon = null;
let refreshTimer = null;
let lastPhotoHex = null;
let lastPhotoAt = 0;

function applyProximityBackground(distanceKm) {
  var t = 0;
  if (distanceKm != null) {
    t = (GREEN_START_KM - distanceKm) / (GREEN_START_KM - GREEN_FULL_KM);
    if (t < 0) t = 0;
    if (t > 1) t = 1;
  }
  document.body.style.setProperty('--proximity-glow', t.toFixed(4));
}

function photoHtml(photo) {
  if (!photo || !photo.url) return '';
  var link = photo.link ? '<a href="' + escapeHtml(photo.link) + '" target="_blank" rel="noopener">' : '';
  var linkClose = link ? '</a>' : '';
  return link
    + '<img class="closest-img" src="' + escapeHtml(photo.url) + '" alt="Aircraft photo" loading="lazy" onerror="this.remove()">'
    + linkClose
    + '<div class="closest-photo-credit">Photos by ' + escapeHtml(photo.photographer || 'unknown') + '</div>';
}

function closestStatsHtml(p) {
  var vert = formatVertRate(p.vertical_rate_fpm);
  return '<div class="closest-stats">'
    + '<div class="closest-stat"><div class="v">' + (p.aircraft_type ? escapeHtml(p.aircraft_type) : '\u2013') + '</div><div class="l">Aircraft</div></div>'
    + '<div class="closest-stat"><div class="v">' + formatAltitude(p.altitude_ft) + '</div><div class="l">Altitude ft</div></div>'
    + '<div class="closest-stat"><div class="v">' + formatSpeed(p.speed_knots) + '</div><div class="l">Speed kts</div></div>'
    + '<div class="closest-stat"><div class="v">' + formatDistance(p.distance_km) + '</div><div class="l">Distance km</div></div>'
    + '<div class="closest-stat"><div class="v">' + (p.bearing != null ? Math.round(p.bearing) + '\u00b0' : '\u2013') + '</div><div class="l">Bearing</div></div>'
    + (vert ? '<div class="closest-stat"><div class="v">' + vert + '</div><div class="l">Vert rate fpm</div></div>' : '')
    + '</div>';
}

function renderClosest(data, forcePhoto) {
  var p = data.plane;
  if (!p) {
    bodyEl.innerHTML = '<div class="empty">No qualifying aircraft.<br>No airborne plane with route data within ' + RADIUS_KM + ' km.</div>';
    photoEl.innerHTML = '';
    player.stop();
    applyProximityBackground(null);
    return;
  }
  applyProximityBackground(p.distance_km);
  var meta = [p.tail_number].filter(Boolean).map(escapeHtml).join(' \u00b7 ');
  if (p.squawk) meta += ' \u00b7 Sqwk ' + escapeHtml(p.squawk);
  var freq = atcFreq(p);
  if (freq) meta += ' \u00b7 Freq ' + escapeHtml(freq);
  var html = '<div class="closest-hero">' + escapeHtml(p.callsign || p.hex_id) + '</div>';
  var callsignNameText = callsignName(p.callsign, p.route);
  if (callsignNameText) html += '<div class="closest-callsign-name">' + escapeHtml(callsignNameText) + '</div>';
  html += '<div class="closest-meta">' + meta + '</div>';
  html += '<div class="closest-route">' + routeHtml(p) + '</div>';
  html += closestStatsHtml(p);
  html += '<button class="closest-atc" id="closest-atc"' + (p.liveatc_stream_url ? '' : ' disabled') + '>' + (p.liveatc_stream_url ? 'Play ATC feed' : 'No ATC feed') + '</button>';
  bodyEl.innerHTML = html;
  var atc = document.getElementById('closest-atc');
  if (atc) atc.addEventListener('click', function () { startStream(p, true); });
  autoTune(p);
  maybeRefreshPhoto(p.hex_id, forcePhoto);
}

function maybeRefreshPhoto(hex, force) {
  if (!hex) { photoEl.innerHTML = ''; return; }
  var now = Date.now();
  if (!force && hex === lastPhotoHex && now - lastPhotoAt < PHOTO_REFRESH_MS) return;
  lastPhotoHex = hex;
  lastPhotoAt = now;
  fetch(PHOTO_URL + encodeURIComponent(hex) + '/', { headers: { 'Accept': 'application/json' } })
    .then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    })
    .then(function (d) {
      photoEl.innerHTML = photoHtml(d.photo);
    })
    .catch(function () {
      photoEl.innerHTML = '';
    });
}

function fetchClosest(forcePhoto) {
  if (userLat == null || userLon == null) return;
  setStatus(statusEl, statusText, 'loading', 'Finding closest...');
  fetch(API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lat: userLat, lon: userLon, radius: RADIUS_KM })
  })
  .then(function (r) {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  })
  .then(function (data) {
    renderClosest(data, !!forcePhoto);
    var label = data.plane ? (data.plane.callsign || data.plane.hex_id) : 'none';
    setStatus(statusEl, statusText, '', label + ' closest');
  })
  .catch(function (err) {
    bodyEl.innerHTML = '<div class="error-msg">Unable to reach closest endpoint.<br><small>' + escapeHtml(err.message) + '</small></div>';
    setStatus(statusEl, statusText, 'error', 'Fetch failed');
  });
}

function startStream(plane, manual) {
  if (!plane.liveatc_stream_url) return;
  if (manual && player.isDismissed(plane.liveatc_stream_url)) {
    player.markDismissed(null);
  }
  player.open(plane);
}

function autoTune(plane) {
  if (!plane || !plane.liveatc_stream_url) {
    player.stop();
    return;
  }
  if (player.url === plane.liveatc_stream_url) return;
  if (player.isDismissed(plane.liveatc_stream_url)) return;
  startStream(plane, false);
}

refreshBtn.addEventListener('click', function () {
  fetchClosest(true);
});

requestLocation({
  onSuccess: function (pos) {
    userLat = pos.coords.latitude;
    userLon = pos.coords.longitude;
    setStatus(statusEl, statusText, '', 'Located');
    fetchClosest();
    if (!refreshTimer) {
      refreshTimer = setInterval(function () {
        fetchClosest(false);
      }, REFRESH_MS);
    }
  },
  onError: function () {
    setStatus(statusEl, statusText, 'error', 'Location denied');
    bodyEl.innerHTML = '<div class="error-msg">Location access is required to find nearby aircraft.<br>Please allow location access and reload.</div>';
  },
  onUnsupported: function () {
    setStatus(statusEl, statusText, 'error', 'Geolocation not supported');
    bodyEl.innerHTML = '<div class="error-msg">Your browser does not support geolocation.</div>';
  }
});