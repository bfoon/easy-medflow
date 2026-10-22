/* Dispatch board: live map + lists. Polls the board API; with "Demo motion" on it drives the simulator instead. */
(() => {
  const E = window.EmsMap, C = window.EMS, $ = s => document.querySelector(s), esc = E.esc;
  const url = (tpl, id) => tpl.replace('/0/', `/${id}/`);
  let data = JSON.parse($('#ems-data').textContent);
  const map = E.map('emsmap', JSON.parse($('#ems-tiles').textContent), {zoomControl: true});
  const layer = {units: {}, calls: {}, lines: {}, fixed: L.layerGroup().addTo(map), route: L.layerGroup().addTo(map)};
  let selected = null, sim = false, timer = null, firstFit = true;

  /* ------------------------------------------------------------ fixed places */
  function drawFixed() {
    layer.fixed.clearLayers();
    data.stations.forEach(s => L.marker([s.lat, s.lon], {icon: E.stationIcon(s), zIndexOffset: -500}).bindTooltip(esc(s.name)).addTo(layer.fixed));
    L.marker([data.home.lat, data.home.lon], {icon: E.hospIcon(true), zIndexOffset: -200}).bindTooltip(`<b>${esc(data.home.name)}</b><br>This hospital`).addTo(layer.fixed);
    data.facilities.forEach(f => L.marker([f.lat, f.lon], {icon: E.hospIcon(false), zIndexOffset: -300})
      .bindTooltip(`<b>${esc(f.name)}</b>${f.caps.length ? '<br>' + f.caps.map(esc).join(', ') : ''}`).addTo(layer.fixed));
  }

  /* ------------------------------------------------------------ live markers */
  function unitPopup(u) {
    const crew = u.crew.length ? u.crew.map(c => `${esc(c.name)} <span class="muted">(${esc(c.role)})</span>`).join('<br>') : '<span class="muted">No crew signed on</span>';
    return `<div style="min-width:200px;font:13px var(--body)"><b style="font-size:15px">${esc(u.call_sign)}</b> · ${esc(u.level_label)}<br>
      <span style="color:${u.color};font-weight:700">${esc(u.status_label)}</span>${u.speed ? ` · ${u.speed} km/h` : ''}
      ${u.call ? `<br>Job <a href="${url(C.call, u.call.id)}">${esc(u.call.reference)}</a>` : ''}${u.target ? `<br>Heading to ${esc(u.target.name)}` : ''}
      <hr style="margin:6px 0">${crew}<div class="muted" style="margin-top:4px">Fuel ${u.fuel}% · Oxygen ${u.oxygen}%${u.position_at ? ' · GPS ' + E.ago(u.position_at) : ''}</div></div>`;
  }
  function render() {
    const seenU = new Set(), seenC = new Set();
    data.units.forEach(u => {
      seenU.add(u.id);
      const ll = [u.lat, u.lon];
      let m = layer.units[u.id];
      if (!m) {
        m = layer.units[u.id] = L.marker(ll, {icon: E.unitIcon(u), zIndexOffset: 1000}).addTo(map);
        m.bindPopup('');
        m.on('popupopen', () => m.setPopupContent(unitPopup(m._u)));
      } else {
        m.setLatLng(ll);
        if (m._key !== `${u.status}|${u.heading}|${u.color}`) m.setIcon(E.unitIcon(u));
      }
      m._u = u; m._key = `${u.status}|${u.heading}|${u.color}`;
      const line = layer.lines[u.id];
      if (u.target && u.status !== 'on_scene' && u.status !== 'at_hospital') {
        const pts = [ll, [u.target.lat, u.target.lon]];
        if (line) line.setLatLngs(pts); else layer.lines[u.id] = L.polyline(pts, {color: u.color, weight: 2, dashArray: '6 7', opacity: .8}).addTo(map);
      } else if (line) { map.removeLayer(line); delete layer.lines[u.id]; }
    });
    Object.keys(layer.units).forEach(id => { if (!seenU.has(+id)) { map.removeLayer(layer.units[id]); delete layer.units[id]; } });
    data.calls.forEach(c => {
      if (c.lat == null) return;
      seenC.add(c.id);
      let m = layer.calls[c.id];
      if (!m) {
        m = layer.calls[c.id] = L.marker([c.lat, c.lon], {icon: E.callIcon(c), zIndexOffset: 800}).addTo(map);
        m.on('click', () => select(m._c.id, false));
      } else {
        m.setLatLng([c.lat, c.lon]);
        if (m._key !== `${c.priority}|${c.unit}`) m.setIcon(E.callIcon(c));
      }
      m._c = c; m._key = `${c.priority}|${c.unit}`;
      m.bindTooltip(`<b>P${c.priority} ${esc(c.complaint_label)}</b><br>${esc(c.landmark || c.town || '')}`);
    });
    Object.keys(layer.calls).forEach(id => { if (!seenC.has(+id)) { map.removeLayer(layer.calls[id]); delete layer.calls[id]; } });
    lists();
    if (firstFit) { firstFit = false; fitAll(true); }
  }

  function fitAll(focus) {
    let pts = data.calls.filter(c => c.lat != null).map(c => [c.lat, c.lon])
      .concat(data.units.filter(u => focus ? u.call || u.status === 'available' : true).map(u => [u.lat, u.lon]));
    if (focus) {   // the busiest area: calls and units within 40 km of this hospital, if there are any
      const near = pts.filter(p => E.km(p, [data.home.lat, data.home.lon]) < 40);
      if (near.length >= 3) pts = near;
    }
    if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.15), {maxZoom: 13});
  }

  /* ------------------------------------------------------------ side lists */
  const clockW = c => Math.min(100, (c.waiting_min / c.target_min) * 100);
  const srcIcon = s => ({app: 'bi-phone', phone: 'bi-telephone', transfer: 'bi-arrow-left-right', police: 'bi-shield', walk_in: 'bi-broadcast'}[s] || 'bi-telephone');
  function callCard(c) {
    return `<div class="callcard pri-${c.priority} ${c.late ? 'late' : ''} ${c.status === 'new' ? 'app-new' : ''} ${selected === c.id ? 'sel' : ''}" data-call="${c.id}" tabindex="0" role="button"
      aria-label="P${c.priority} ${esc(c.complaint_label)}, waiting ${c.waiting_min} minutes">
      <div class="top"><span class="ptag">P${c.priority}</span><span class="what"><i class="bi ${c.icon}"></i> ${esc(c.complaint_label)}${c.patients > 1 ? ` ×${c.patients}` : ''}</span>
        <span class="wait" data-recv="${c.received_at}">${c.waiting_min} min</span></div>
      <div class="where">${esc(c.landmark || c.town || 'Location not given')}</div>
      <div class="d-flex align-items-center gap-2 mt-1"><span class="src"><i class="bi ${srcIcon(c.source)}"></i>${c.status === 'new' ? 'App request · call back to confirm' : esc(c.status_label)}</span>
        <span class="src ms-auto">target ${c.target_min} min</span></div>
      <div class="rclock"><i style="--w:${clockW(c)}%"></i></div></div>`;
  }
  function activeRow(c) {
    const u = data.units.find(x => x.id === c.unit_id);
    const eta = c.status === 'transporting' ? E.untilMin(c.eta_hospital) : ['dispatched', 'en_route'].includes(c.status) ? E.untilMin(c.eta_scene) : null;
    return `<div class="unitrow" data-call="${c.id}" style="--uc:${u ? u.color : '#5A6F7D'}"><span class="dot"><i class="bi bi-truck-front"></i></span>
      <div class="min-w-0"><b>${esc(c.unit || '')}</b> <span class="ptag pri-${c.priority}" style="font-size:.66rem">P${c.priority}</span><div class="st">${esc(c.status_label)} · ${esc(c.complaint_label)}</div></div>
      <div class="meta">${eta != null ? `<b style="color:var(--ink)">${E.fmtMin(eta)}</b><br>to ${c.status === 'transporting' ? 'hospital' : 'patient'}` : `${c.waiting_min} min<br>since call`}</div></div>`;
  }
  function incomingCard(c) {
    const h = c.handover || {}, eta = E.untilMin(c.eta_hospital);
    return `<a class="incoming d-block text-decoration-none" href="${url(C.call, c.id)}" style="color:inherit"><div class="d-flex align-items-center gap-2">
      <span class="ptag pri-${c.priority}">P${c.priority}</span><b style="color:var(--ink)">${esc(c.unit)}</b><span class="muted small">${esc(c.complaint_label)}</span>
      <span class="ms-auto eta">${c.status === 'at_hospital' ? 'Here' : E.fmtMin(eta)}</span></div>
      <dl><dt>A</dt><dd>${esc(h.age || '–')}</dd><dt>M</dt><dd>${esc(h.mechanism || '–')}</dd><dt>S</dt><dd>${esc(h.signs || 'No observations yet')}</dd>${h.treatment ? `<dt>T</dt><dd>${esc(h.treatment)}</dd>` : ''}</dl></a>`;
  }
  function unitLine(u) {
    return `<div class="unitrow" data-unit="${u.id}" style="--uc:${u.color}"><span class="dot"><i class="bi ${u.level === 'moto' ? 'bi-bicycle' : u.level === 'boat' ? 'bi-water' : 'bi-truck-front'}"></i></span>
      <div class="min-w-0"><b>${esc(u.call_sign)}</b><div class="st">${esc(u.status_label)}${u.station ? ' · ' + esc(u.station) : ''}</div></div>
      <div class="meta">${u.crew.length ? u.crew.map(c => esc(c.first)).join(', ') : '<span style="color:#8A520B">no crew</span>'}<br>${esc(u.level_label)}</div></div>`;
  }
  function lists() {
    const wait = data.calls.filter(c => c.status === 'new' || c.status === 'waiting');
    const act = data.calls.filter(c => !(c.status === 'new' || c.status === 'waiting'));
    $('#list-wait').innerHTML = wait.map(callCard).join('') || '<div class="empty"><i class="bi bi-check2-circle"></i>No one is waiting.</div>';
    $('#list-active').innerHTML = act.map(activeRow).join('') || '<div class="empty small">No ambulance is on a job.</div>';
    $('#list-in').innerHTML = data.incoming.map(incomingCard).join('') || '<div class="empty small">No ambulance is bringing a patient here.</div>';
    $('#list-units').innerHTML = data.units.map(unitLine).join('');
    $('#n-wait').textContent = wait.length; $('#n-active').textContent = act.length; $('#n-in').textContent = data.incoming.length;
    const k = data.kpi;
    $('#k-wait b').textContent = k.waiting; $('#k-wait').classList.toggle('hot', wait.some(c => c.late || c.priority === 1));
    $('#k-free').textContent = `${k.free}/${k.units}`; $('#k-active').textContent = k.active; $('#k-today').textContent = k.today;
    $('#k-resp').textContent = k.median_response != null ? `${k.median_response} min` : '–';
  }

  /* ------------------------------------------------------------ select a call: route + best ambulances */
  async function select(id, pan = true) {
    selected = id;
    lists();
    const c = data.calls.find(x => x.id === id);
    const m = layer.calls[id];
    if (!c || !m) { location.href = url(C.call, id); return; }
    if (pan) map.setView([c.lat, c.lon], Math.max(map.getZoom(), 13));
    let html = `<div style="min-width:240px;font:13px var(--body)"><div style="display:flex;gap:6px;align-items:center"><span class="ptag pri-${c.priority}">P${c.priority}</span>
      <b style="font-size:14px">${esc(c.complaint_label)}</b></div><div class="muted" style="margin:3px 0 6px">${esc(c.landmark || c.town || '')}</div>
      ${c.reason ? `<div style="font-size:12px;margin-bottom:6px">${esc(c.reason)}</div>` : ''}<div id="pop-recs" class="muted">${C.canDispatch && !c.unit ? 'Finding the best ambulance…' : ''}</div>
      <a href="${url(C.call, id)}" style="display:inline-block;margin-top:6px;font-weight:700">Open the call</a></div>`;
    m.bindPopup(html, {maxWidth: 320}).openPopup();
    layer.route.clearLayers();
    if (C.canDispatch && !c.unit && (c.status === 'new' || c.status === 'waiting')) {
      try {
        const r = await E.api(url(C.recommend, id), null, 'GET');
        const box = document.getElementById('pop-recs');
        if (!box) return;
        if (!r.units.length) { box.innerHTML = '<span style="color:var(--red)">No ambulance is free.</span>'; return; }
        box.innerHTML = r.units.slice(0, 3).map(u => `<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-top:1px solid var(--line)">
          <b style="font-size:15px;min-width:44px">${Math.round(u.eta_min)}′</b><div style="flex:1;line-height:1.25"><b style="color:var(--ink)">${esc(u.call_sign)}</b>${u.best ? ' <span class="tag teal">Best</span>' : ''}<br>
          <span style="font-size:11px">${esc([...u.reasons, ...u.warnings].join(' · ') || u.level)}</span></div>
          <button class="btn btn-primary btn-sm" data-send="${u.id}" data-call="${id}">Send</button></div>`).join('');
        const best = data.units.find(x => x.id === r.units[0].id);
        if (best) {
          const rt = await E.route(C.router, [best.lat, best.lon], [c.lat, c.lon]);
          L.polyline(rt.coords, {color: '#0F2C3F', weight: 4, opacity: .55}).addTo(layer.route);
        }
      } catch (e) { const box = document.getElementById('pop-recs'); if (box) box.textContent = e.message; }
    }
  }

  document.addEventListener('click', async e => {
    const send = e.target.closest('[data-send]');
    if (send) {
      send.disabled = true;
      try {
        const r = await E.api(url(C.assign, send.dataset.call), {ambulance: send.dataset.send});
        window.mfToast && mfToast(`${r.call.unit} is on its way to ${r.call.reference}.`);
        map.closePopup(); layer.route.clearLayers(); selected = null; refresh();
      } catch (err) { window.mfToast ? mfToast(err.message, 'error') : alert(err.message); send.disabled = false; }
      return;
    }
    const card = e.target.closest('.callcard[data-call]');
    if (card) { select(+card.dataset.call); return; }
    const row = e.target.closest('.unitrow[data-call]');
    if (row) { location.href = url(C.call, row.dataset.call); return; }
    const ur = e.target.closest('.unitrow[data-unit]');
    if (ur) { const m = layer.units[ur.dataset.unit]; if (m) { map.setView(m.getLatLng(), Math.max(map.getZoom(), 13)); m.openPopup(); } }
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.target.matches('.callcard')) select(+e.target.dataset.call);
  });
  $('#fit').addEventListener('click', () => fitAll(false));

  /* ------------------------------------------------------------ live updates */
  async function refresh() {
    try {
      data = sim ? await E.api(C.simulate, {speedup: 12}) : await E.api(C.board, null, 'GET');
      render();
    } catch (e) { if (sim) { toggleSim(false); window.mfToast && mfToast(e.message, 'error'); } }
  }
  function schedule() { clearInterval(timer); timer = setInterval(refresh, sim ? 2500 : 6000); }
  function toggleSim(on) {
    sim = on; const b = $('#sim'); if (!b) return;
    b.classList.toggle('sim-on', on); b.setAttribute('aria-pressed', on); b.querySelector('span').textContent = on ? 'Demo motion ×12' : 'Demo motion';
    schedule(); if (on) refresh();
  }
  if ($('#sim')) $('#sim').addEventListener('click', () => toggleSim(!sim));
  // waiting clocks tick every few seconds between refreshes
  setInterval(() => document.querySelectorAll('.wait[data-recv]').forEach(w => {
    const m = Math.floor((Date.now() - new Date(w.dataset.recv)) / 60000); w.textContent = `${m} min`;
  }), 5000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

  drawFixed(); render(); schedule();
})();
