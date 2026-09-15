export const $ = (s) => document.querySelector(s);

export function setStatus(statusEl, statusText, state, text) {
  statusEl.className = 'status ' + state;
  statusText.textContent = text;
}

export function formatAltitude(alt) {
  if (alt === 'ground') return '<span class="ground">GND</span>';
  if (alt == null) return '--';
  return Number(alt).toLocaleString();
}

export function formatSpeed(s) {
  return s != null ? Math.round(s) : '--';
}

export function formatDistance(d) {
  if (d == null) return '--';
  return d.toFixed(1);
}

export function formatVertRate(v) {
  if (v == null) return '';
  if (v === 0) return '';
  const cls = v > 0 ? 'vr-up' : 'vr-down';
  const arrow = v > 0 ? '\u2191' : '\u2193';
  return '<span class="' + cls + '">' + arrow + ' ' + Math.abs(v).toLocaleString() + '</span>';
}

export function feedName(url) {
  if (!url) return 'No feed';
  const name = url.split('/').pop().replace('.mp3', '');
  return name;
}

export function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

export function routeHtml(p) {
  var r = p.route;
  if (!r) return '';
  var originCode = r.origin_iata || r.origin_icao;
  var destCode = r.destination_iata || r.destination_icao;
  if (!originCode && !destCode) return '';
  var originCity = [r.origin_city, r.origin_country].filter(Boolean).map(escapeHtml).join(', ');
  var destCity = [r.destination_city, r.destination_country].filter(Boolean).map(escapeHtml).join(', ');
  var airlineText = r.airline_name ? (r.airline_icao ? r.airline_name + ' (' + r.airline_icao + ')' : r.airline_name) : '';
  return '<div class="card-route">'
    + '<div class="route-line">'
    +   '<div class="route-airport">' + escapeHtml(originCode || '---') + '</div>'
    +   '<div class="route-arrow">\u2192</div>'
    +   '<div class="route-airport right">' + escapeHtml(destCode || '---') + '</div>'
    + '</div>'
    + '<div class="route-city">'
    +   '<span>' + (escapeHtml(originCity) || '\u00b7') + '</span>'
    +   '<span>' + (escapeHtml(destCity) || '\u00b7') + '</span>'
    + '</div>'
    + (airlineText ? '<div class="airline-tag">' + escapeHtml(airlineText) + '</div>' : '')
    + '</div>';
}

export function atcFreq(plane) {
  return (plane && plane.liveatc_frequency) ? String(plane.liveatc_frequency) : '';
}

export function requestLocation({ onSuccess, onError, onUnsupported }) {
  if (!navigator.geolocation) {
    if (onUnsupported) onUnsupported();
    return;
  }
  navigator.geolocation.getCurrentPosition(onSuccess, onError, {
    enableHighAccuracy: true,
    timeout: 10000,
    maximumAge: 0
  });
}

export function createPlayer() {
  const audio = $('#audio');
  const playerBar = $('#player-bar');
  const playerCallsign = $('#player-callsign');
  const playerFeed = $('#player-feed');
  const playerPlay = $('#player-play');
  const iconPlay = $('#icon-play');
  const iconPause = $('#icon-pause');
  const volumeSlider = $('#volume');
  const playerClose = $('#player-close');
  const listeningIndicator = $('#listening-indicator');

  let activeCallsign = null;
  let isPlaying = false;
  let dismissedUrl = null;
  let currentUrl = null;
  const changeListeners = [];

  function setIcon() {
    iconPlay.style.display = isPlaying ? 'none' : '';
    iconPause.style.display = isPlaying ? '' : 'none';
    listeningIndicator.style.display = isPlaying ? '' : 'none';
  }

  function emitChange() {
    changeListeners.forEach(function (fn) { fn(); });
  }

  function promptVolume() {
    var savedVol = localStorage.getItem('atc-volume');
    var initialVol = savedVol !== null ? Number(savedVol) : 80;
    volumeSlider.value = initialVol;
    audio.volume = initialVol / 100;
  }

  function open(plane) {
    if (!plane || !plane.liveatc_stream_url) return;
    activeCallsign = plane.callsign || plane.hex_id;
    currentUrl = plane.liveatc_stream_url;
    audio.src = currentUrl;
    audio.load();
    playerCallsign.textContent = activeCallsign;
    var parts = [feedName(currentUrl), plane.aircraft_type, atcFreq(plane)].filter(Boolean);
    playerFeed.textContent = parts.join(' \u00b7 ');
    playerBar.classList.add('visible');
    play();
    emitChange();
  }

  function play() {
    if (!currentUrl) return;
    audio.play().catch(function () {
      isPlaying = false;
      setIcon();
    });
  }

  function pause() {
    audio.pause();
  }

  function toggle() {
    if (isPlaying) {
      pause();
    } else {
      play();
    }
  }

  function stop() {
    audio.pause();
    audio.src = '';
    currentUrl = null;
    isPlaying = false;
    activeCallsign = null;
    playerBar.classList.remove('visible');
    setIcon();
    emitChange();
  }

  function markDismissed(url) {
    dismissedUrl = url;
  }

  function isDismissed(url) {
    return dismissedUrl === url;
  }

  function onChange(fn) {
    changeListeners.push(fn);
  }

  promptVolume();

  volumeSlider.addEventListener('input', function () {
    audio.volume = volumeSlider.value / 100;
    localStorage.setItem('atc-volume', volumeSlider.value);
  });

  playerPlay.addEventListener('click', toggle);

  audio.addEventListener('playing', function () {
    isPlaying = true;
    setIcon();
  });
  audio.addEventListener('pause', function () {
    isPlaying = false;
    setIcon();
  });
  audio.addEventListener('error', function () {
    isPlaying = false;
    setIcon();
    markDismissed(currentUrl);
    playerFeed.textContent = 'Stream unavailable';
  });

  playerClose.addEventListener('click', function () {
    markDismissed(currentUrl);
    stop();
  });

  return {
    get active() { return activeCallsign; },
    get playing() { return isPlaying; },
    get url() { return currentUrl; },
    open: open,
    play: play,
    pause: pause,
    toggle: toggle,
    stop: stop,
    markDismissed: markDismissed,
    isDismissed: isDismissed,
    onChange: onChange
  };
}