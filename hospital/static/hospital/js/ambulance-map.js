/* Ambulance maps: tiles, markers, road routes with turn-by-turn steps (OSRM), and a straight-line fallback when no
   router is reachable (the server may be on an intranet). Used by the board, call page, crew screen and tracking page. */
(() => {
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const PCOL = {1: '#C8323F', 2: '#D2593A', 3: '#E0912A', 4: '#0F7B78'};
  const LICON = {als: 'bi-truck-front-fill', bls: 'bi-truck-front', neonatal: 'bi-heart-fill', rural: 'bi-truck', moto: 'bi-bicycle', boat: 'bi-water'};

  function map(el, tiles, opts = {}) {
    const m = L.map(el, Object.assign({zoomControl: true, scrollWheelZoom: true, attributionControl: true}, opts));
    const o = attr => ({maxZoom: 19, attribution: attr, referrerPolicy: 'strict-origin-when-cross-origin'});
    const layers = {};
    (tiles || []).forEach((t, i) => { layers[t.name] = L.tileLayer(t.url, o(t.attr)); if (i === 0) layers[t.name].addTo(m); });
    if (opts.layers !== false && Object.keys(layers).length > 1) L.control.layers(layers, null, {collapsed: true, position: 'topright'}).addTo(m);
    m.fitBounds([[13.05, -16.85], [13.83, -13.79]]);
    return m;
  }

  const unitIcon = (u, label = true) => L.divIcon({className: '', iconSize: [34, 34], iconAnchor: [17, 17],
    html: `<div class="mk-unit ${['en_route', 'transporting', 'returning', 'dispatched'].includes(u.status) ? 'moving' : ''}" style="--uc:${u.color};--hd:${u.heading || 0}deg">
      <div class="nose"></div><div class="body"><i class="bi ${LICON[u.level] || 'bi-truck-front'}"></i></div>${label ? `<span class="mk-label">${esc(u.call_sign)}</span>` : ''}</div>`});
  const callIcon = c => L.divIcon({className: '', iconSize: [26, 26], iconAnchor: [13, 13],
    html: `<div class="mk-call pri-${c.priority} ${c.unit ? 'active' : ''}" style="--pc:${PCOL[c.priority]}"><div class="halo"></div><div class="core" data-p="P${c.priority}"></div></div>`});
  const stationIcon = s => L.divIcon({className: '', iconSize: [18, 18], iconAnchor: [9, 9], html: `<div class="mk-station" title="${esc(s.name)}">${s.kind === 'jetty' ? '⚓' : 'S'}</div>`});
  const hospIcon = home => L.divIcon({className: '', iconSize: home ? [30, 30] : [26, 26], iconAnchor: home ? [15, 15] : [13, 13], html: `<div class="mk-hosp ${home ? 'home' : ''}">H</div>`});
  const youIcon = () => L.divIcon({className: '', iconSize: [22, 22], iconAnchor: [11, 11], html: '<div class="mk-you"></div>'});

  /* ------------------------------------------------------------ geometry */
  const rad = d => d * Math.PI / 180;
  function km(a, b) {
    const R = 6371, dLat = rad(b[0] - a[0]), dLon = rad(b[1] - a[1]);
    const x = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(x)));
  }
  function bearing(a, b) {
    const y = Math.sin(rad(b[1] - a[1])) * Math.cos(rad(b[0]));
    const x = Math.cos(rad(a[0])) * Math.sin(rad(b[0])) - Math.sin(rad(a[0])) * Math.cos(rad(b[0])) * Math.cos(rad(b[1] - a[1]));
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  }
  const COMPASS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'];
  const compass = d => COMPASS[Math.floor(((d + 22.5) % 360) / 45)];
  const fmtKm = k => k < 1 ? `${Math.round(k * 1000 / 10) * 10} m` : `${k < 10 ? k.toFixed(1) : Math.round(k)} km`;
  const fmtMin = m => m == null ? '–' : m < 1 ? '<1 min' : m < 60 ? `${Math.round(m)} min` : `${Math.floor(m / 60)} h ${Math.round(m % 60)} min`;

  /* ------------------------------------------------------------ turn-by-turn text from OSRM steps */
  const TURN = {uturn: 180, 'sharp right': 135, right: 90, 'slight right': 40, straight: 0, 'slight left': -40, left: -90, 'sharp left': -135};
  function instruction(st) {
    const m = st.maneuver || {}, mod = m.modifier || 'straight', road = st.name ? ` onto ${st.name}` : '';
    const on = st.name ? ` on ${st.name}` : '';
    switch (m.type) {
      case 'depart': return {text: `Head ${compass(m.bearing_after || 0)}${on}`, turn: 0};
      case 'arrive': return {text: 'You have arrived', turn: 0, arrive: true};
      case 'roundabout': case 'rotary': case 'roundabout turn': case 'exit roundabout': case 'exit rotary':
        return {text: `At the roundabout, take exit ${m.exit || 1}${road}`, turn: TURN[mod] ?? 0, round: true};
      case 'merge': return {text: `Merge ${mod.replace('slight ', '')}${road}`, turn: TURN[mod] ?? 0};
      case 'fork': return {text: `Keep ${mod.includes('left') ? 'left' : 'right'} at the fork${road}`, turn: TURN[mod] ?? 0};
      case 'end of road': return {text: `At the end of the road, turn ${mod.replace('slight ', '')}${road}`, turn: TURN[mod] ?? 0};
      case 'continue': case 'new name': return {text: mod === 'straight' ? `Continue straight${on}` : `Continue ${mod}${road}`, turn: TURN[mod] ?? 0};
      default: return {text: mod === 'straight' ? `Go straight${on}` : mod === 'uturn' ? 'Make a U-turn' : `Turn ${mod}${road}`, turn: TURN[mod] ?? 0};
    }
  }

  /* ------------------------------------------------------------ routes */
  const cache = new Map();
  async function route(router, from, to) {
    const key = `${from.map(n => n.toFixed(4))}|${to.map(n => n.toFixed(4))}`;
    if (cache.has(key)) return cache.get(key);
    let out = null;
    if (router) {
      try {
        const url = `${router.replace(/\/$/, '')}/route/v1/driving/${from[1]},${from[0]};${to[1]},${to[0]}?overview=full&geometries=geojson&steps=true`;
        const ctl = new AbortController(); const timer = setTimeout(() => ctl.abort(), 6000);
        const r = await fetch(url, {signal: ctl.signal, referrerPolicy: 'strict-origin-when-cross-origin'}); clearTimeout(timer);
        const j = await r.json();
        if (j.code === 'Ok' && j.routes && j.routes[0]) {
          const rt = j.routes[0];
          const steps = rt.legs[0].steps.map(s => Object.assign(instruction(s), {km: s.distance / 1000, at: [s.maneuver.location[1], s.maneuver.location[0]], name: s.name}));
          out = {road: true, coords: rt.geometry.coordinates.map(c => [c[1], c[0]]), km: rt.distance / 1000, min: rt.duration / 60, steps};
        }
      } catch (e) { out = null; }
    }
    if (!out) {
      const d = km(from, to) * 1.35;
      out = {road: false, coords: [from, to], km: d, min: d / 45 * 60,
             steps: [{text: `Head ${compass(bearing(from, to))} toward the destination`, turn: 0, km: d, at: from}, {text: 'You have arrived', turn: 0, km: 0, at: to, arrive: true}]};
    }
    cache.set(key, out);
    return out;
  }

  /* Where am I on the route: index of the next step and distance to it. */
  function progress(rt, pos) {
    if (!rt) return null;
    let best = 0, bestD = Infinity;
    rt.coords.forEach((c, i) => { const d = km(pos, c); if (d < bestD) { bestD = d; best = i; } });
    let left = 0;
    if (!rt.road) left = km(pos, rt.coords[rt.coords.length - 1]);       // straight line: simply what is left to the end
    else { for (let i = best; i < rt.coords.length - 1; i++) left += km(rt.coords[i], rt.coords[i + 1]); left += bestD; }
    // next manoeuvre: the first step whose point lies ahead of us along the line
    let next = rt.steps.length - 1;
    for (let i = 1; i < rt.steps.length; i++) {
      const s = rt.steps[i];
      let idx = 0, dd = Infinity;
      rt.coords.forEach((c, j) => { const d = km(s.at, c); if (d < dd) { dd = d; idx = j; } });
      if (idx > best) { next = i; break; }
    }
    const toNext = km(pos, rt.steps[next].at) * (rt.road ? 1.1 : 1.35);
    return {left: rt.road ? left : left * 1.35, next, toNext, offRoute: bestD > 0.25};
  }

  const arrowSvg = () => '<svg viewBox="0 0 48 48" aria-hidden="true"><path d="M24 4 L38 22 H29 V44 H19 V22 H10 Z" fill="currentColor"/></svg>';
  const flagSvg = () => '<svg viewBox="0 0 48 48" aria-hidden="true"><path d="M12 44V6h4v2h20l-5 8 5 8H16v20z" fill="currentColor"/></svg>';
  const roundSvg = () => '<svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="28" r="9" fill="none" stroke="currentColor" stroke-width="5"/><path d="M24 2 L34 14 H28 V19 H20 V14 H14 Z" fill="currentColor"/></svg>';

  async function api(url, data, method = 'POST') {
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const opt = {method, credentials: 'same-origin', headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/json'}};
    if (method !== 'GET') opt.body = JSON.stringify(data || {});
    const r = await fetch(url, opt);
    let j = {};
    try { j = await r.json(); } catch (e) { j = {ok: false, error: 'The server did not answer properly.'}; }
    if (!r.ok || j.ok === false) throw new Error(j.error || `Error ${r.status}`);
    return j;
  }

  const googleNav = (lat, lon) => `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}&travelmode=driving`;
  const ago = iso => { if (!iso) return ''; const s = (Date.now() - new Date(iso)) / 1000; return s < 60 ? 'now' : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`; };
  const untilMin = iso => iso ? Math.max(0, (new Date(iso) - Date.now()) / 60000) : null;

  window.EmsMap = {map, unitIcon, callIcon, stationIcon, hospIcon, youIcon, km, bearing, compass, fmtKm, fmtMin, route, progress, instruction,
                   arrowSvg, flagSvg, roundSvg, api, esc, googleNav, ago, untilMin, PCOL};
})();
