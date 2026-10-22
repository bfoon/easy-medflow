/* Crew screen: the job, one big next-step button, turn-by-turn directions from the phone's GPS (or a simulated drive),
   the preparation checklist, vital signs, treatment and the ATMIST handover. Talks only to the crew API. */
(() => {
  const E = window.EmsMap, C = window.CREW, $ = s => document.querySelector(s), esc = E.esc;
  const unitQ = C.unit ? `?unit=${C.unit}` : '';
  const post = (url, data) => E.api(url, Object.assign(C.unit ? {unit: C.unit} : {}, data || {}));
  const PCOL = E.PCOL;
  const TREAT = ['Oxygen started', 'IV access', 'Aspirin 300 mg chewed', 'GTN spray', 'Salbutamol nebuliser', 'Glucose given', 'Splint applied',
                 'Cervical collar', 'Bleeding controlled', 'CPR started', 'Defibrillation shock', 'Pain relief given', 'Baby delivered', 'Wound dressed'];
  let job = JSON.parse($('#crew-job').textContent);
  let tab = null, map = null, mk = {}, routeLine = null, rt = null, routeKey = '', pos = null, lastCallId = job.call ? job.call.id : null;
  let gpsWatch = null, lastSent = 0, sim = null, rerouteAt = 0;

  /* ------------------------------------------------------------ helpers */
  const toast = (m, l) => (window.mfToast ? mfToast(m, l) : alert(m));
  const fail = e => toast(e.message || 'Something went wrong.', 'error');
  const sinceMin = iso => iso ? Math.floor((Date.now() - new Date(iso)) / 60000) : null;
  function beep() {
    try { const a = new (window.AudioContext || window.webkitAudioContext)(); [0, .25, .5].forEach(t => { const o = a.createOscillator(), g = a.createGain();
      o.frequency.value = 880; o.connect(g); g.connect(a.destination); g.gain.setValueAtTime(.2, a.currentTime + t); o.start(a.currentTime + t); o.stop(a.currentTime + t + .15); }); } catch (e) { /* no audio */ }
    if (navigator.vibrate) navigator.vibrate([300, 120, 300, 120, 600]);
  }

  /* ------------------------------------------------------------ layout */
  function build() {
    const c = job.call;
    if (map) { map.remove(); map = null; mk = {}; routeLine = null; rt = null; routeKey = ''; }
    $('#job').innerHTML = `<div class="ck-grid"><div class="d-flex flex-column gap-3"><div class="ck-card ck-job" id="jobcard"></div><div class="ck-card" id="navcard"></div></div>
      <div class="ck-map" id="ckmap"></div></div><div class="ck-tabs" id="tabs" role="tablist"></div><div id="panel"></div>`;
    map = E.map('ckmap', JSON.parse($('#ems-tiles').textContent), {layers: false, zoomControl: false});
    pos = [job.unit.lat, job.unit.lon];
    mk.unit = L.marker(pos, {icon: E.unitIcon(job.unit, false), zIndexOffset: 1000}).addTo(map);
    if (c.lat != null) mk.scene = L.marker([c.lat, c.lon], {icon: E.callIcon(c)}).addTo(map);
    mk.dest = L.marker([c.destination.lat, c.destination.lon], {icon: E.hospIcon(c.destination.home)}).addTo(map).bindTooltip(esc(c.destination.name));
    map.setView(pos, 15);
    tab = tab || (c.status === 'at_hospital' ? 'handover' : ['on_scene', 'transporting'].includes(c.status) ? 'patient' : 'prep');
  }

  function render() {
    const c = job.call;
    $('#u-badge').style.setProperty('--uc', job.unit.color);
    $('#u-sub').textContent = `${job.unit.level_label} · ${job.unit.status_label}`;
    if (!c) {
      $('#job').innerHTML = ''; if (map) { map.remove(); map = null; }
      $('#idle').hidden = false;
      const st = job.unit.status;
      $('#idle-title').textContent = st === 'available' ? 'Ready' : st === 'returning' || st === 'at_hospital' ? 'Job finished' : job.unit.status_label;
      $('#idle-sub').textContent = st === 'available' ? 'Waiting for a job. This screen will alert you when dispatch sends one.' :
        st === 'returning' ? 'Restock and clean, then tell dispatch you are available.' : 'Ask dispatch to put this ambulance back in service.';
      $('#idle-actions').innerHTML = ['returning', 'at_hospital'].includes(st) ? '<button class="ck-next" id="avail" style="--pc:#0F7B78;max-width:420px"><i class="bi bi-check2-circle"></i>Back in service</button>' : '';
      $('#crewlist').innerHTML = job.unit.crew.map(p => `<div class="prep-i"><i class="bi bi-person-badge"></i><span>${esc(p.name)} <small>${esc(p.role)}</small></span></div>`).join('') || '<p style="color:#E0912A">No one is signed on.</p>';
      return;
    }
    $('#idle').hidden = true;
    if (!$('#jobcard')) build();
    document.documentElement.style.setProperty('--pc', PCOL[c.priority]);
    $('#jobcard').style.setProperty('--pc', PCOL[c.priority]);
    const p = c.patient, n = c.next;
    const trans = ['transporting', 'at_hospital'].includes(c.status);
    $('#jobcard').innerHTML = `<div class="d-flex align-items-center gap-2"><span class="ptag pri-${c.priority}">P${c.priority} ${esc(c.priority_label.split('· ')[1] || '')}</span>
        <span style="color:#9DB8C8;font-size:.85rem">${esc(c.reference)} · ${esc(c.status_label)}</span></div>
      <div class="what mt-1"><i class="bi ${c.icon}"></i> ${esc(c.complaint_label)}${c.patients > 1 ? ` · ${c.patients} patients` : ''}</div>
      <div class="where"><i class="bi ${trans ? 'bi-hospital' : 'bi-geo-alt-fill'}"></i> ${esc(trans ? c.destination.name : (c.landmark || c.town || 'See map'))}</div>
      <div class="meta">${esc(p.name || 'Name not known')}${p.age != null ? ` · ${p.age} y` : ''} · ${esc(p.sex)}${p.linked ? ' · <b style="color:#9FE7D0">known to the hospital</b>' : ''}</div>
      ${c.description ? `<div class="meta">“${esc(c.description)}”</div>` : ''}
      ${c.caller.phone && !trans ? `<a class="ck-btn d-inline-block mt-2 text-decoration-none" href="tel:${esc(c.caller.phone)}"><i class="bi bi-telephone"></i> Call ${esc(c.caller.name || 'the caller')}</a>` : ''}
      ${n ? `<button class="ck-next" data-next="${n[0]}" style="--pc:${PCOL[c.priority]}"><i class="bi ${n[2]}"></i>${esc(n[1])}</button>` : ''}
      ${c.status === 'on_scene' ? `<div class="d-flex gap-2 mt-2"><select class="form-select" id="outcome"><option value="">Not taking the patient because…</option>${c.outcomes.map(o => `<option value="${o[0]}">${esc(o[1])}</option>`).join('')}</select>
        <button class="ck-btn text-nowrap" id="closescene">Close</button></div>` : ''}
      ${c.status === 'at_hospital' ? `<button class="ck-next" data-tab-go="handover" style="--pc:#8A4A8F"><i class="bi bi-clipboard2-pulse"></i>Hand over the patient</button>` : ''}`;
    nav();
    tabs();
    panel();
    markers();
  }

  /* ------------------------------------------------------------ navigation */
  async function ensureRoute() {
    const t = job.call && job.call.target;
    if (!t || !map) return;
    const key = `${t.kind}:${t.lat.toFixed(5)},${t.lon.toFixed(5)}`;
    if (key === routeKey && rt) return;
    routeKey = key;
    rt = await E.route(C.router, pos, [t.lat, t.lon]);
    if (routeLine) map.removeLayer(routeLine);
    routeLine = L.polyline(rt.coords, {color: '#3FE0B0', weight: 6, opacity: .85, dashArray: rt.road ? null : '10 10'}).addTo(map);
    map.fitBounds(routeLine.getBounds().pad(.2), {maxZoom: 16});
    nav();
  }
  function nav() {
    const c = job.call, box = $('#navcard');
    if (!box || !c) return;
    const t = c.target;
    if (c.status === 'on_scene') {
      box.innerHTML = `<div class="ck-turn"><div class="ck-arrow" style="color:var(--pc)">${E.flagSvg()}</div><div><div class="ck-dist">${sinceMin(c.events.find(e => e.text.startsWith('Crew with'))?.at) ?? 0} min</div>
        <div class="ck-instr">With the patient</div><div class="ck-then">Aim to leave within 15 minutes for time-critical patients.</div></div></div>
        <div class="ck-eta"><div><b>${esc(c.destination.name)}</b><span>Taking the patient to</span></div></div>`;
      return;
    }
    if (c.status === 'at_hospital') {
      box.innerHTML = `<div class="ck-turn"><div class="ck-arrow">${E.flagSvg()}</div><div><div class="ck-instr">At ${esc(c.destination.name)}</div><div class="ck-then">Hand over with ATMIST, then restock.</div></div></div>`;
      return;
    }
    if (!t) { box.innerHTML = '<div class="ck-instr">No destination.</div>'; return; }
    if (!rt) { box.innerHTML = `<div class="ck-instr">Finding the route to ${esc(t.name)}…</div>`; ensureRoute(); return; }
    const pr = E.progress(rt, pos);
    const step = rt.steps[pr.next], then = rt.steps[pr.next + 1];
    const svg = step.arrive ? E.flagSvg() : step.round ? E.roundSvg() : E.arrowSvg();
    const turn = rt.road ? step.turn : ((E.bearing(pos, [t.lat, t.lon]) - (job.unit.heading || 0) + 540) % 360) - 180;
    const speed = Math.max(job.unit.speed || 0, 35);
    const eta = rt.road ? rt.min * (pr.left / Math.max(rt.km, .01)) : pr.left / speed * 60;
    box.innerHTML = `<div class="ck-turn"><div class="ck-arrow"><span style="display:inline-block;transform:rotate(${step.round ? 0 : turn}deg)">${svg}</span></div>
      <div class="min-w-0"><div class="ck-dist">${E.fmtKm(pr.toNext)}</div><div class="ck-instr">${esc(rt.road ? step.text : `Head ${E.compass(E.bearing(pos, [t.lat, t.lon]))} to ${t.name}`)}</div>
      ${then ? `<div class="ck-then">Then: ${esc(then.text)}</div>` : ''}</div></div>
      <div class="ck-eta"><div><b>${E.fmtMin(eta)}</b><span>to ${t.kind === 'scene' ? 'the patient' : esc(t.name)}</span></div><div><b>${E.fmtKm(pr.left)}</b><span>left</span></div>
        <div class="ms-auto"><a class="ck-btn d-inline-block text-decoration-none" target="_blank" rel="noopener" href="${E.googleNav(t.lat, t.lon)}"><i class="bi bi-google"></i> Maps</a></div></div>
      ${rt.road ? '' : '<div class="ck-then mt-2">No road router reachable: showing straight-line guidance. Use Maps for turn-by-turn.</div>'}`;
    if (pr.offRoute && rt.road && Date.now() > rerouteAt) { rerouteAt = Date.now() + 20000; routeKey = ''; rt = null; ensureRoute(); }
  }
  function markers() {
    if (!map || !mk.unit) return;
    mk.unit.setLatLng(pos);
    mk.unit.setIcon(E.unitIcon(Object.assign({}, job.unit, {lat: pos[0], lon: pos[1]}), false));
    ensureRoute();
  }

  /* ------------------------------------------------------------ tabs */
  function tabs() {
    const c = job.call, pr = c.prep;
    const T = [['prep', 'Prepare', `${pr.done}/${pr.total}`], ['patient', 'Patient', c.observations.length || ''],
               ...(['on_scene', 'transporting', 'at_hospital'].includes(c.status) ? [['handover', 'Handover', '']] : []), ['timeline', 'Timeline', '']];
    if (!T.find(t => t[0] === tab)) tab = 'prep';
    $('#tabs').innerHTML = T.map(([k, l, n]) => `<button type="button" role="tab" aria-selected="${k === tab}" class="${k === tab ? 'on' : ''}" data-tab="${k}">${l}${n !== '' ? `<span class="cnt">${n}</span>` : ''}</button>`).join('');
  }
  function panel(force = true) {
    const box = $('#panel'); if (!box) return;
    if (!force && (box.contains(document.activeElement) || tab === 'handover')) return;
    const c = job.call;
    if (tab === 'prep') {
      const k = c.prep.known;
      box.innerHTML = `<div class="ck-grid"><div class="ck-card">${c.prep.groups.map(g => `<div class="prep-g"><h3>${esc(g.title)}</h3>${g.items.map(i =>
        `<label class="prep-i ${i.done ? 'done' : ''}"><input type="checkbox" class="form-check-input" data-prep="${i.key}" ${i.done ? 'checked' : ''}><span>${esc(i.text)}${i.done ? `<small>${esc(i.done.by)}</small>` : ''}</span></label>`).join('')}</div>`).join('')}</div>
        <div class="d-flex flex-column gap-3"><div class="ck-warn"><i class="bi bi-megaphone"></i> ${esc(c.prep.alert)}</div>
        ${k ? `<div class="ck-card"><h2><i class="bi bi-person-vcard"></i> Known to the hospital</h2><div class="small">
          <div><b>${esc(k.name)}</b> · ${esc(k.mrn)} · ${k.age ?? '?'} y${k.blood_group ? ' · blood ' + esc(k.blood_group) : ''}</div>
          ${k.allergies.length ? `<div class="mt-1" style="color:#FF9AA2"><b>Allergies:</b> ${k.allergies.map(esc).join('; ')}</div>` : '<div class="mt-1">No known allergies recorded</div>'}
          ${k.conditions.length ? `<div class="mt-1"><b>Conditions:</b> ${k.conditions.map(esc).join(', ')}</div>` : ''}
          ${k.medicines.length ? `<div class="mt-1"><b>Medicines (last 90 days):</b> ${k.medicines.map(esc).join(', ')}</div>` : ''}
          ${k.alerts ? `<div class="mt-1">${esc(k.alerts)}</div>` : ''}${k.emergency_contact ? `<div class="mt-1">Next of kin: ${esc(k.emergency_contact)}</div>` : ''}</div></div>` : ''}
        ${c.answers.length ? `<div class="ck-card"><h2>What the caller said</h2>${c.answers.map(a => `<div class="small">${esc(a.q)} <b>${esc(a.a)}</b></div>`).join('')}
          ${c.reason ? `<div class="small mt-1" style="color:#9DB8C8">${esc(c.reason)}</div>` : ''}</div>` : ''}
        <div class="ck-card"><h2>Caller was told</h2><ol class="small mb-0 ps-3">${c.prep.first_aid.map(t => `<li>${esc(t)}</li>`).join('')}</ol></div></div></div>`;
    } else if (tab === 'patient') {
      const F = [['heart_rate', 'HR'], ['systolic', 'Sys BP'], ['diastolic', 'Dia BP'], ['resp_rate', 'Resp'], ['spo2', 'SpO₂'], ['temperature_c', 'Temp'], ['glucose_mmol', 'Glucose'], ['gcs', 'GCS']];
      box.innerHTML = `<div class="ck-grid"><div class="ck-card"><h2><i class="bi bi-activity"></i> Vital signs</h2><form id="obsform"><div class="vgrid">
        ${F.map(([k, l]) => `<div><label class="form-label small mb-1" for="o-${k}">${l}</label><input class="form-control" id="o-${k}" name="${k}" inputmode="decimal" autocomplete="off"></div>`).join('')}
        <div><label class="form-label small mb-1" for="o-avpu">AVPU</label><select class="form-select" id="o-avpu" name="avpu"><option value=""></option><option>A</option><option>V</option><option>P</option><option>U</option></select></div>
        <div><label class="form-label small mb-1" for="o-pain">Pain 0–10</label><input class="form-control" id="o-pain" name="pain" inputmode="numeric"></div></div>
        <button class="ck-next" style="--pc:#0F7B78;padding:14px;font-size:1.1rem"><i class="bi bi-plus-circle"></i>Save vital signs</button></form>
        <ul class="tl mt-3">${c.observations.slice().reverse().map(o => `<li><time>${new Date(o.at).toTimeString().slice(0, 5)}</time><span class="k k-status"></span>
          <span>${esc(o.line)} ${o.flags.map(f => `<span class="flag ${f[0]}">${esc(f[1])}</span>`).join('')}</span></li>`).join('') || '<li style="color:#8FB0C2">No vital signs yet.</li>'}</ul></div>
        <div class="ck-card"><h2><i class="bi bi-capsule"></i> Treatment given</h2><div class="quick">${TREAT.map(t => `<button type="button" data-treat="${esc(t)}">${esc(t)}</button>`).join('')}</div>
          <form id="treatform" class="d-flex gap-2"><input class="form-control" name="text" placeholder="Drug, dose, route — or anything done"><button class="ck-btn text-nowrap">Add</button></form>
          <ul class="tl mt-3">${c.events.filter(e => e.kind === 'treatment').reverse().map(e => `<li><time>${new Date(e.at).toTimeString().slice(0, 5)}</time><span class="k k-treatment"></span><span>${esc(e.text)}</span></li>`).join('')}</ul></div></div>`;
    } else if (tab === 'handover') {
      const h = c.handover;
      box.innerHTML = `<div class="ck-card"><h2><i class="bi bi-clipboard2-pulse"></i> ATMIST handover <span class="ms-auto small" style="color:#8FB0C2">Filled from what you recorded. Check and correct.</span></h2>
        <form id="hoform"><div class="atmist">${c.atmist_labels.map(([k, letter, label]) => `<b>${letter}</b><div><label class="form-label small mb-1" for="h-${k}">${esc(label)}</label>
          <textarea class="form-control" rows="1" name="${k}" id="h-${k}">${esc(h[k] || '')}</textarea></div>`).join('')}</div>
        <div class="row g-2 mt-2"><div class="col-md-6"><input class="form-control" name="received_by" placeholder="Received by (name and role)"></div>
        <div class="col-md-6 d-flex align-items-center">${c.destination.home ? `<label class="d-flex gap-2 align-items-center"><input class="form-check-input m-0" type="checkbox" name="register" checked> Register in the emergency queue</label>` : `<span style="color:#9DB8C8">Handing over at ${esc(c.destination.name)}</span>`}</div></div>
        ${c.status === 'at_hospital' ? '<button class="ck-next" style="--pc:#8A4A8F"><i class="bi bi-clipboard2-check"></i>Hand over and finish the job</button>' : '<p class="mt-2 mb-0" style="color:#9DB8C8">You can hand over once you arrive at hospital.</p>'}</form></div>`;
    } else {
      box.innerHTML = `<div class="ck-card"><ul class="tl">${c.events.slice().reverse().map(e => `<li><time>${new Date(e.at).toTimeString().slice(0, 5)}</time><span class="k k-${e.kind}"></span><span>${esc(e.text)}</span></li>`).join('')}</ul>
        <form id="noteform" class="d-flex gap-2 mt-2"><input class="form-control" name="text" placeholder="Note for dispatch and the hospital"><button class="ck-btn">Add</button></form></div>`;
    }
  }

  /* ------------------------------------------------------------ actions */
  document.addEventListener('click', async e => {
    const t = e.target.closest('[data-tab]'); if (t) { tab = t.dataset.tab; tabs(); panel(); return; }
    const tg = e.target.closest('[data-tab-go]'); if (tg) { tab = tg.dataset.tabGo; tabs(); panel(); $('#panel').scrollIntoView({behavior: 'smooth'}); return; }
    const nx = e.target.closest('[data-next]');
    if (nx) { nx.disabled = true; try { job = await post(C.status, {status: nx.dataset.next}); routeKey = ''; rt = null;
      if (job.call && ['on_scene', 'transporting'].includes(job.call.status)) tab = 'patient'; if (job.call && job.call.status === 'at_hospital') tab = 'handover'; render(); } catch (err) { fail(err); nx.disabled = false; } return; }
    if (e.target.id === 'closescene') { const o = $('#outcome').value; if (!o) return toast('Choose why the patient is not being taken.', 'warning');
      try { job = await post(C.status, {status: 'closed', outcome: o}); render(); toast('Job closed.'); } catch (err) { fail(err); } return; }
    if (e.target.closest('#avail')) { try { job = await post(C.available); render(); toast('You are available.'); } catch (err) { fail(err); } return; }
    const tr = e.target.closest('[data-treat]');
    if (tr) { const inp = $('#treatform [name=text]'); inp.value = `${tr.dataset.treat} ${new Date().toTimeString().slice(0, 5)}`; inp.focus(); }
  });
  document.addEventListener('change', async e => {
    const cb = e.target.closest('[data-prep]'); if (!cb) return;
    try { const r = await post(C.prep, {key: cb.dataset.prep, done: cb.checked}); job.call.prep = r.prep; tabs(); cb.closest('.prep-i').classList.toggle('done', cb.checked); }
    catch (err) { cb.checked = !cb.checked; fail(err); }
  });
  document.addEventListener('submit', async e => {
    const f = e.target; if (!['obsform', 'treatform', 'noteform', 'hoform'].includes(f.id)) return;
    e.preventDefault();
    const data = Object.fromEntries(new FormData(f).entries());
    try {
      if (f.id === 'obsform') { const r = await post(C.obs, data); job = r.job; toast(`Saved: ${r.line}`, r.flags.some(x => x[0] === 'red') ? 'warning' : 'success'); }
      if (f.id === 'treatform' || f.id === 'noteform') { if (!data.text) return; job = await post(C.note, {text: data.text, kind: f.id === 'treatform' ? 'treatment' : 'note'}); }
      if (f.id === 'hoform') { data.register = !!f.querySelector('[name=register]')?.checked; const r = await post(C.handover, data); job = r; tab = null; toast(r.registered ? 'Handed over. The patient is in the emergency queue.' : 'Handed over.'); }
      tabs(); panel(); render();
    } catch (err) { fail(err); }
  });

  /* ------------------------------------------------------------ position: GPS or simulated drive */
  async function onFix(lat, lon, speed, heading, acc) {
    pos = [lat, lon];
    job.unit.heading = heading ?? job.unit.heading; job.unit.speed = speed ?? job.unit.speed;
    markers(); nav();
    if (map && job.call) map.panTo(pos, {animate: true});
    if (Date.now() - lastSent > (sim ? 900 : 4000)) {
      lastSent = Date.now();
      try { const r = await post(C.position, {latitude: lat, longitude: lon, speed_kmh: speed, heading, accuracy_m: acc});
        if (job.call && r.call_status && r.call_status !== job.call.status) refresh(); } catch (err) { /* keep driving; retry next fix */ }
    }
  }
  const gpsBtn = $('#gps');
  gpsBtn.addEventListener('click', () => {
    if (gpsWatch !== null) { navigator.geolocation.clearWatch(gpsWatch); gpsWatch = null; gpsBtn.querySelector('span').textContent = 'GPS off'; gpsBtn.setAttribute('aria-pressed', 'false'); return; }
    if (!navigator.geolocation) return toast('This device has no GPS access in the browser.', 'error');
    gpsWatch = navigator.geolocation.watchPosition(p => onFix(p.coords.latitude, p.coords.longitude, p.coords.speed != null ? p.coords.speed * 3.6 : null, p.coords.heading, p.coords.accuracy),
      err => toast(`GPS: ${err.message}`, 'error'), {enableHighAccuracy: true, maximumAge: 2000, timeout: 15000});
    gpsBtn.querySelector('span').textContent = 'GPS on'; gpsBtn.setAttribute('aria-pressed', 'true');
  });
  const simBtn = $('#simdrive');
  if (simBtn) simBtn.addEventListener('click', async () => {
    if (sim) { clearInterval(sim); sim = null; simBtn.querySelector('span').textContent = 'Simulate'; return; }
    if (!job.call || !job.call.target) return toast('Simulated driving needs a job with somewhere to go.', 'warning');
    if (job.call.status === 'dispatched') { try { job = await post(C.status, {status: 'en_route'}); render(); } catch (err) { return fail(err); } }
    await ensureRoute(); if (!rt) return;
    let i = 0; const pts = rt.coords; const perTick = 60 / 3.6 * 8 / 1000;    // km per second at 60 km/h × 8
    simBtn.querySelector('span').textContent = 'Stop';
    sim = setInterval(() => {
      let budget = perTick, cur = pos;
      while (i < pts.length - 1 && budget > 0) { const d = E.km(cur, pts[i + 1]); if (d <= budget) { budget -= d; cur = pts[++i]; } else { const f = budget / d; cur = [cur[0] + (pts[i + 1][0] - cur[0]) * f, cur[1] + (pts[i + 1][1] - cur[1]) * f]; budget = 0; } }
      const hd = E.bearing(pos, cur);
      onFix(cur[0], cur[1], 60, isNaN(hd) ? 0 : hd, 5);
      if (i >= pts.length - 1) { clearInterval(sim); sim = null; simBtn.querySelector('span').textContent = 'Simulate'; toast('Arrived. Press the button to confirm.'); }
    }, 1000);
  });

  /* ------------------------------------------------------------ live job */
  async function refresh() {
    try {
      const r = await E.api(C.me + unitQ, null, 'GET');
      if (!r.unit) { location.reload(); return; }
      const before = job.call ? `${job.call.id}|${job.call.status}` : '';
      job = r;
      const id = job.call ? job.call.id : null;
      if (id && id !== lastCallId) {
        lastCallId = id; tab = null; build();
        $('#nj-what').innerHTML = `<span class="ptag pri-${job.call.priority}">P${job.call.priority}</span> ${esc(job.call.complaint_label)}`;
        $('#nj-where').textContent = job.call.landmark || job.call.town || '';
        $('#newjob').hidden = false; beep();
      } else if (!id) { lastCallId = null; }
      const after = job.call ? `${job.call.id}|${job.call.status}` : '';
      if (!sim && !gpsWatch) pos = [job.unit.lat, job.unit.lon];
      if (before !== after) { if (job.call && !$('#jobcard')) build(); render(); }
      else if (job.call) { $('#jobcard') && render(); }
      else render();
    } catch (err) { /* offline for a moment: try again next round */ }
  }
  $('#nj-go').addEventListener('click', async () => { $('#newjob').hidden = true; try { job = await post(C.status, {status: 'en_route'}); render(); } catch (err) { fail(err); } });
  $('#nj-later').addEventListener('click', () => { $('#newjob').hidden = true; });
  // re-render panels only when nobody is typing in them
  const _panel = panel; panel = (force) => _panel(force === undefined ? !document.querySelector('#panel')?.contains(document.activeElement) : force);

  pos = [job.unit.lat, job.unit.lon];
  if (job.call) build();
  render();
  setInterval(refresh, 5000);
})();
