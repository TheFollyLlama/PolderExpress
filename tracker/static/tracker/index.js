import {
  $, setStatus, escapeHtml, formatAltitude, formatSpeed, formatDistance,
  formatVertRate, routeHtml, atcFreq, requestLocation, createPlayer, centerMap
} from './shared.js';

const API_URL = '/api/v1/nearby-planes/';
const REFRESH_MS = 15000;
const RADIUS_KM = 15;
const MAP_ZOOM = 11;

const planesEl = $('#planes');
const countEl = $('#count');
const statusEl = $('#status');
const statusText = $('#status-text');
const refreshBtn = $('#refresh-btn');
const mapFrame = $('#map-frame');

const player = createPlayer();

let userLat = null;
let userLon = null;
let refreshTimer = null;
let planesData = [];
let mapCentered = false;

player.onChange(function () {
  renderPlanes();
});

function renderPlanes() {
  if (!planesData.length) {
    planesEl.innerHTML = '<div class="empty">No aircraft detected in range.<br>Make sure location access is enabled.</div>';
    return;
  }
  planesEl.innerHTML = '<div class="plane-grid">' + planesData.map(function (p, i) {
    var key = p.callsign || p.hex_id;
    var isActive = key === player.active;
    var emergencyHtml = p.emergency && p.emergency !== 'none'
      ? '<span class="emergency-badge">' + escapeHtml(p.emergency.toUpperCase()) + '</span>'
      : '';
    var vrHtml = formatVertRate(p.vertical_rate_fpm);
    var freqText = atcFreq(p) ? ' \u00b7 Freq ' + escapeHtml(atcFreq(p)) : '';
    return '<div class="plane-card' + (isActive ? ' active-stream' : '') + '" data-index="' + i + '">'
      + '<div class="card-top">'
      +   '<span class="callsign">' + escapeHtml(p.callsign || p.hex_id) + '</span>'
      +   emergencyHtml
      + '</div>'
      + '<div class="card-meta">'
      +   (p.tail_number || '') + (p.tail_number && p.aircraft_type ? ' \u00b7 ' : '')
      +   (p.aircraft_type || '')
      +   freqText
      + '</div>'
      + routeHtml(p)
      + '<div class="card-stats">'
      +   '<div class="stat"><div class="stat-value">' + formatAltitude(p.altitude_ft) + '</div><div class="stat-label">Alt ft</div></div>'
      +   '<div class="stat"><div class="stat-value">' + formatSpeed(p.speed_knots) + '</div><div class="stat-label">Spd kts</div></div>'
      +   '<div class="stat"><div class="stat-value">' + formatDistance(p.distance_km) + '</div><div class="stat-label">Dist km</div></div>'
      + '</div>'
      + (vrHtml ? '<div style="text-align:right;margin-top:6px;font-size:11px">' + vrHtml + '</div>' : '')
      + '</div>';
  }).join('') + '</div>';
}

function startStream(plane) {
  player.open(plane);
}

function fetchPlanes() {
  if (userLat == null || userLon == null) return;
  setStatus(statusEl, statusText, 'loading', 'Fetching...');
  refreshBtn.disabled = true;

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
    planesData = data.planes || [];
    planesData.sort(function (a, b) {
      return (a.distance_km ?? 9999) - (b.distance_km ?? 9999);
    });
    countEl.textContent = planesData.length;
    renderPlanes();
    setStatus(statusEl, statusText, '', planesData.length + ' aircraft');
    refreshBtn.disabled = false;
  })
  .catch(function (err) {
    setStatus(statusEl, statusText, 'error', 'Fetch failed');
    planesEl.innerHTML = '<div class="error-msg">Unable to reach flight data.<br><small>' + escapeHtml(err.message) + '</small></div>';
    refreshBtn.disabled = false;
  });
}

planesEl.addEventListener('click', function (e) {
  var card = e.target.closest('.plane-card');
  if (!card) return;
  var idx = parseInt(card.dataset.index, 10);
  var plane = planesData[idx];
  if (!plane) return;
  var key = plane.callsign || plane.hex_id;
  if (key === player.active) {
    player.stop();
  } else {
    startStream(plane);
  }
});

refreshBtn.addEventListener('click', function () {
  fetchPlanes();
});

requestLocation({
  onSuccess: function (pos) {
    userLat = pos.coords.latitude;
    userLon = pos.coords.longitude;
    setStatus(statusEl, statusText, '', 'Located');
    if (!mapCentered) {
      centerMap(mapFrame, userLat, userLon, MAP_ZOOM);
      mapCentered = true;
    }
    fetchPlanes();
    if (!refreshTimer) {
      refreshTimer = setInterval(function () {
        fetchPlanes();
      }, REFRESH_MS);
    }
  },
  onError: function () {
    setStatus(statusEl, statusText, 'error', 'Location denied');
    planesEl.innerHTML = '<div class="error-msg">Location access is required to find nearby aircraft.<br>Please allow location access and reload.</div>';
  },
  onUnsupported: function () {
    setStatus(statusEl, statusText, 'error', 'Geolocation not supported');
    planesEl.innerHTML = '<div class="error-msg">Your browser does not support geolocation.</div>';
  }
});