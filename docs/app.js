/* Williamsburg Citi Bike - live availability dashboard.
 *
 * Runs entirely in the browser. Both upstream feeds send
 * `access-control-allow-origin: *`, so GitHub Pages can call them directly with
 * no backend, no key, and no proxy.
 *
 * Two sources of truth are combined:
 *   live  - GBFS, polled every 30s, plus a short rolling history this page keeps
 *           itself so it can show which way a station is currently moving.
 *   past  - stats.json, the day x time grid built from collected snapshots.
 * Live tells you what's there now; past tells you whether that's normal.
 */

const GBFS = 'https://gbfs.lyft.com/gbfs/2.3/bkn/en/station_status.json';
const WX   = 'https://api.open-meteo.com/v1/forecast?latitude=40.716&longitude=-73.952'
           + '&current=temperature_2m,apparent_temperature,precipitation,wind_speed_10m,weather_code'
           + '&temperature_unit=fahrenheit&timezone=America%2FNew_York';

const POLL_MS   = 30_000;
const HIST_MS   = 45 * 60 * 1000;   // rolling window kept for the trend
const WALK_MPS  = 1.35;
const LS_KEY    = 'wburg.hist.v1';
const LS_ORIGIN = 'wburg.origin.v1';

let STATIONS = {}, STATS = null, LIVE = {}, HIST = {}, ORIGIN = null;
let mode = 'get', kind = 'any', selected = null;
let map, layer, markers = {};

/* ---------- storage helpers (may throw in private windows) ---------- */
const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; }
                         catch { return d; } };
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };

/* ---------- geometry ---------- */
function haversine(a, b, c, d) {
  const R = 6371000, r = Math.PI / 180;
  const dp = (c - a) * r, dl = (d - b) * r;
  const s = Math.sin(dp / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

/* ---------- historical slot lookup ---------- */
const DOW_JS_TO_PY = d => (d + 6) % 7;          // JS Sun=0 -> Python Mon=0

function slotFor(now) {
  if (!STATS || !STATS.slots) return null;
  const py = DOW_JS_TO_PY(now.getDay());
  const mins = now.getHours() * 60 + now.getMinutes();
  // Tue/Thu aren't tracked; fall back to the other weekdays as a proxy.
  const dows = STATS.dows.includes(py) ? [py]
             : (py < 5 ? STATS.dows.filter(d => d < 5) : STATS.dows);
  let best = null, bestD = 1e9;
  STATS.slots.forEach(([d, t], i) => {
    if (!dows.includes(d)) return;
    let diff = Math.abs(t - mins);
    diff = Math.min(diff, 1440 - diff);          // wrap around midnight
    if (diff < bestD) { bestD = diff; best = i; }
  });
  return best === null ? null
       : { i: best, exact: STATS.dows.includes(py), offBy: bestD };
}

function hist(sid, slot, key) {
  if (!slot || !STATS.stations[sid]) return null;
  const s = STATS.stations[sid];
  const n = s.n[slot.i];
  if (!n || n < STATS.min_n) return { thin: true, n: n || 0 };
  return { thin: false, n, p: s[key][slot.i] };
}

/* ---------- rolling live history -> trend ---------- */
function pushHistory(ts) {
  const cutoff = Date.now() - HIST_MS;
  for (const sid in LIVE) {
    const a = (HIST[sid] ||= []);
    if (!a.length || a[a.length - 1][0] !== ts) {
      a.push([ts, LIVE[sid].classic, LIVE[sid].ebikes, LIVE[sid].docks]);
    }
    while (a.length && a[0][0] < cutoff) a.shift();
  }
  save(LS_KEY, HIST);
}

/** Change per minute over the rolling window. null until there's enough span
 *  to mean anything - a slope off two samples 40 seconds apart is noise. */
function trend(sid, idx) {
  const a = HIST[sid];
  if (!a || a.length < 3) return null;
  const [t0, ...f0] = a[0], [t1, ...f1] = a[a.length - 1];
  const mins = (t1 - t0) / 60000;
  if (mins < 8) return null;
  return (f1[idx] - f0[idx]) / mins;
}

/* ---------- scoring ---------- */
function countFor(l) {
  if (mode === 'dock') return l.docks;
  return kind === 'ebike' ? l.ebikes : kind === 'classic' ? l.classic : l.bikes;
}
function trendIdx() {
  if (mode === 'dock') return 2;
  return kind === 'ebike' ? 1 : kind === 'classic' ? 0 : -1;   // -1 = classic+ebike
}
function trendFor(sid) {
  const i = trendIdx();
  if (i >= 0) return trend(sid, i);
  const a = trend(sid, 0), b = trend(sid, 1);
  return (a === null || b === null) ? null : a + b;
}
function histKey() {
  if (mode === 'dock') return 'pd';
  return kind === 'ebike' ? 'pe' : kind === 'classic' ? 'pc' : 'pc';
}

function rank(slot) {
  const out = [];
  for (const sid in STATIONS) {
    const st = STATIONS[sid], l = LIVE[sid];
    if (!l) continue;
    if (mode === 'get'  && !l.is_renting)   continue;
    if (mode === 'dock' && !l.is_returning) continue;

    const dist  = ORIGIN ? haversine(ORIGIN.lat, ORIGIN.lon, st.lat, st.lon) : null;
    const walk  = dist === null ? null : dist / WALK_MPS / 60;
    const now   = countFor(l);
    const slope = trendFor(sid);
    const proj  = (slope !== null && walk !== null)
                ? Math.max(0, now + slope * walk) : now;

    // Three-or-more is treated as effectively certain: the marginal value of the
    // 4th bike to someone walking over is nil.
    const pLive = Math.min(proj / 3, 1);
    const h = hist(sid, slot, histKey());
    const pPast = (h && !h.thin) ? h.p : null;
    let score = pPast === null ? pLive : 0.6 * pLive + 0.4 * pPast;
    if (walk !== null) score *= Math.exp(-walk / 12);   // decay with walking time

    out.push({ sid, st, l, dist, walk, now, slope, proj, h, score });
  }
  out.sort((a, b) => b.score - a.score || (a.dist ?? 0) - (b.dist ?? 0));
  return out;
}

/* ---------- render ---------- */
const fmtWalk = m => m === null ? '' : m < 1 ? '<1 min walk' : `${Math.round(m)} min walk`;

function render() {
  const slot = slotFor(new Date());
  const ranked = rank(slot);
  const list = document.getElementById('list');
  list.innerHTML = '';

  ranked.slice(0, 40).forEach(r => {
    const li = document.createElement('li');
    li.className = 'card' + (r.sid === selected ? ' sel' : '');
    li.onclick = () => { selected = r.sid; map.panTo([r.st.lat, r.st.lon]); render(); };

    const cls = v => v === 0 ? 'pill lo' : v >= 3 ? 'pill hi' : 'pill';
    const pills = mode === 'dock'
      ? `<span class="${cls(r.l.docks)}"><b>${r.l.docks}</b> docks</span>
         <span class="pill"><b>${r.l.bikes}</b> bike${r.l.bikes === 1 ? '' : 's'} in</span>`
      : `<span class="${cls(r.l.ebikes)}"><b>${r.l.ebikes}</b> e-bike</span>
         <span class="${cls(r.l.classic)}"><b>${r.l.classic}</b> classic</span>
         <span class="pill"><b>${r.l.docks}</b> docks</span>`;

    let why = [];
    if (r.slope !== null && Math.abs(r.slope) >= 0.05) {
      const dir = r.slope < 0 ? 'dn' : 'up';
      const verb = r.slope < 0 ? 'losing' : 'gaining';
      why.push(`<span class="${dir}">${verb} ${Math.abs(r.slope).toFixed(1)}/min</span>`
             + (r.walk !== null ? ` &rarr; <span class="em">~${Math.round(r.proj)}</span> on arrival` : ''));
    }
    if (r.h && !r.h.thin) {
      const what = mode === 'dock' ? 'a free dock'
                 : kind === 'ebike' ? 'an e-bike' : 'a bike';
      const when = slot.exact ? '' : ' (weekday avg)';
      why.push(`has ${what} <span class="em">${Math.round(r.h.p * 100)}%</span> of the time at this hour${when}`);
    } else if (r.h) {
      why.push(`<span class="thin">not enough history yet (n=${r.h.n})</span>`);
    }

    li.innerHTML =
      `<div class="row1"><span class="nm">${r.st.name}</span>
        <span class="walk">${fmtWalk(r.walk)}</span></div>
       <div class="counts">${pills}</div>
       <div class="why">${why.join(' &middot; ')}</div>`;
    list.appendChild(li);
  });

  drawMarkers(ranked);

  const n = Object.keys(LIVE).length;
  document.getElementById('subtitle').textContent =
    `${n} stations tracked · live, refreshing every 30s`;

  const anyTrend = ranked.some(r => r.slope !== null);
  document.getElementById('foot').innerHTML =
    (STATS && STATS.n_days
      ? `History: ${STATS.n_days} day(s), ${STATS.n_observations.toLocaleString()} observations`
      : 'History: none yet')
    + ` · ${anyTrend ? 'live trend active' : 'trend needs ~10 min of this page being open'}`
    + ` · updated ${new Date().toLocaleTimeString()}`;
}

function colorFor(r) {
  const v = r.now;
  if (v === 0) return '#c0392b';
  if (v <= 2)  return '#e0a33a';
  return '#1a7f4b';
}

function drawMarkers(ranked) {
  if (!layer) return;
  layer.clearLayers(); markers = {};
  ranked.forEach((r, i) => {
    const m = L.circleMarker([r.st.lat, r.st.lon], {
      radius: r.sid === selected ? 11 : (i < 5 ? 9 : 6),
      color: r.sid === selected ? '#0b6bcb' : colorFor(r),
      weight: r.sid === selected ? 3 : (i < 5 ? 2.5 : 1.5),
      fillColor: colorFor(r), fillOpacity: .78,
    }).bindTooltip(
      `<b>${r.st.name}</b><br>${r.l.ebikes} e · ${r.l.classic} classic · ${r.l.docks} docks`,
      { direction: 'top' });
    m.on('click', () => { selected = r.sid; render(); });
    m.addTo(layer);
    markers[r.sid] = m;
  });
}

/* ---------- data ---------- */
async function poll() {
  try {
    const j = await (await fetch(GBFS, { cache: 'no-store' })).json();
    const next = {};
    for (const s of j.data.stations) {
      const sid = String(s.station_id);
      if (!STATIONS[sid]) continue;
      const bikes = s.num_bikes_available || 0, e = s.num_ebikes_available || 0;
      next[sid] = { bikes, ebikes: e, classic: Math.max(bikes - e, 0),
                    docks: s.num_docks_available || 0,
                    is_renting: !!s.is_renting, is_returning: !!s.is_returning };
    }
    LIVE = next;
    pushHistory(Date.now());
    render();
  } catch (e) { console.error('poll failed', e); }
}

async function weather() {
  try {
    const c = (await (await fetch(WX)).json()).current;
    document.getElementById('wx').innerHTML =
      `<b>${Math.round(c.temperature_2m)}°F</b>
       feels ${Math.round(c.apparent_temperature)}° ·
       ${c.precipitation > 0 ? `${c.precipitation}mm rain` : 'dry'} ·
       ${Math.round(c.wind_speed_10m)} km/h wind`;
  } catch { document.getElementById('wx').textContent = ''; }
}

function setOrigin(lat, lon, label) {
  ORIGIN = { lat, lon, label };
  save(LS_ORIGIN, ORIGIN);
  document.getElementById('originline').innerHTML =
    `<span class="dot" style="background:var(--accent)"></span>Ranking from <b>${label}</b>
     &mdash; click the map to move it.`;
  render();
}

/* ---------- init ---------- */
async function init() {
  const si = await (await fetch('data/stations.json')).json();
  si.stations.forEach(s => STATIONS[s.station_id] = s);
  try { STATS = await (await fetch('data/stats.json')).json(); } catch { STATS = null; }
  HIST = load(LS_KEY, {});

  map = L.map('map', { zoomControl: true }).setView([40.716, -73.952], 14);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; OpenStreetMap'
  }).addTo(map);
  layer = L.layerGroup().addTo(map);
  map.on('click', e => setOrigin(e.latlng.lat, e.latlng.lng, 'pinned spot'));

  const saved = load(LS_ORIGIN, null);
  if (saved) {
    setOrigin(saved.lat, saved.lon, saved.label);
    map.setView([saved.lat, saved.lon], 15);
  } else {
    // No origin yet: frame the whole tracked area so it's clear what's covered.
    const pts = si.stations.map(s => [s.lat, s.lon]);
    if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.04));
  }

  document.querySelectorAll('#mode button').forEach(b => b.onclick = () => {
    mode = b.dataset.mode;
    document.querySelectorAll('#mode button').forEach(x => x.classList.toggle('on', x === b));
    document.getElementById('kind').style.visibility = mode === 'dock' ? 'hidden' : 'visible';
    render();
  });
  document.querySelectorAll('#kind button').forEach(b => b.onclick = () => {
    kind = b.dataset.kind;
    document.querySelectorAll('#kind button').forEach(x => x.classList.toggle('on', x === b));
    render();
  });
  document.getElementById('locate').onclick = () => {
    navigator.geolocation?.getCurrentPosition(
      p => { setOrigin(p.coords.latitude, p.coords.longitude, 'your location');
             map.setView([p.coords.latitude, p.coords.longitude], 15); },
      () => alert('Location unavailable. Click the map to set an origin instead.'),
      { enableHighAccuracy: true, timeout: 8000 });
  };

  await Promise.all([poll(), weather()]);
  setInterval(poll, POLL_MS);
  setInterval(weather, 10 * 60 * 1000);
}

init();
