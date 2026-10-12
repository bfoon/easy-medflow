/* Bed page: the controls beside the animated bed. Changing a value previews it on the scene at once; "Save
   equipment" and "Record observations" send it to the server, and the scene is redrawn from the server's answer. */
(() => {
  'use strict';
  const node = document.getElementById('bedside-boot');
  if (!node) return;
  const boot = JSON.parse(node.textContent), cat = boot.catalogue;
  const $ = s => document.querySelector(s), esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  const canEdit = !!boot.can_edit;
  let saved = structuredClone(boot.devices), dev = structuredClone(boot.devices), dirty = false;
  const scene = MFBedside.mount($('#bs-host'), {devices: dev, vitals: boot.vitals, patient: boot.patient, injury: boot.injury});

  const opts = (obj, sel) => Object.entries(obj).map(([k, v]) => `<option value="${k}" ${String(k) === String(sel) ? 'selected' : ''}>${esc(v)}</option>`).join('');
  const sw = (path, on, label) => `<label class="bs-switch"><input type="checkbox" data-p="${path}" ${on ? 'checked' : ''} ${canEdit ? '' : 'disabled'}><span></span>${label}</label>`;
  const numIn = (path, val, label, attrs) => `<label>${label}<input type="number" class="form-control form-control-sm" data-p="${path}" value="${val ?? ''}" ${attrs} ${canEdit ? '' : 'disabled'}></label>`;
  const sel = (path, obj, val, label) => `<label>${label}<select class="form-select form-select-sm" data-p="${path}" ${canEdit ? '' : 'disabled'}>${opts(obj, val)}</select></label>`;

  function sections() {
    const iv = dev.iv, o2 = dev.oxygen, c = dev.catheter, ng = dev.ng_tube, tr = dev.traction, cd = dev.chest_drain, [lo, hi] = cat.o2_limits[o2.device];
    return [
      ['iv', 'bi-droplet', 'IV infusion', iv.on, `${sw('iv.on', iv.on, 'IV running')}
        <div class="bs-grid">${sel('iv.fluid', cat.fluids, iv.fluid, 'Fluid')}${sel('iv.site', cat.sites, iv.site, 'Cannula site')}
        ${numIn('iv.bag_ml', iv.bag_ml, 'Bag size (mL)', 'min="50" max="3000" step="50"')}${numIn('iv.remaining_ml', iv.remaining_ml, 'Left in bag (mL)', `min="0" max="${iv.bag_ml}" step="10"`)}
        ${numIn('iv.rate_ml_h', iv.rate_ml_h, 'Rate (mL/hour)', 'min="0" max="999" step="1"')}${sel('iv.drop_factor', Object.fromEntries(cat.drop_factors.map(f => [f, `${f} drops/mL${f === 60 ? ' (micro)' : ''}`])), iv.drop_factor, 'Giving set')}</div>
        ${sw('iv.pump', iv.pump, 'On an infusion pump')}`],
      ['oxygen', 'bi-wind', 'Oxygen', o2.on, `${sw('oxygen.on', o2.on, 'Oxygen on')}
        <div class="bs-grid">${sel('oxygen.device', cat.o2_devices, o2.device, 'Device')}${numIn('oxygen.flow_l_min', o2.flow_l_min, `Flow (L/min, ${lo}–${hi})`, `min="${lo}" max="${hi}" step="0.5"`)}
        ${['venturi', 'hfnc'].includes(o2.device) ? numIn('oxygen.fio2', o2.fio2, 'Set oxygen %', 'min="21" max="100"') : ''}</div>`],
      ['monitor', 'bi-activity', 'Monitor & probes', dev.monitor.on, `${sw('monitor.on', dev.monitor.on, 'Cardiac monitor')}${sw('pulse_ox.on', dev.pulse_ox.on, 'Finger pulse oximeter')}${sw('bp_cuff.on', dev.bp_cuff.on, 'Automatic BP cuff')}
        <div class="bs-grid">${numIn('bp_cuff.interval_min', dev.bp_cuff.interval_min, 'BP every (minutes)', 'min="5" max="240" step="5"')}</div>${sw('monitor.sound', dev.monitor.sound, 'Beep with each heartbeat (this screen only)')}`],
      ['catheter', 'bi-cup-straw', 'Urinary catheter', c.on, `${sw('catheter.on', c.on, 'Catheter in place')}
        <div class="bs-grid">${numIn('catheter.output_ml_h', c.output_ml_h, 'Output last hour (mL)', 'min="0" max="1000"')}${numIn('catheter.bag_ml', c.bag_ml, 'In the bag now (mL)', 'min="0" max="2000" step="10"')}</div>`],
      ['ng_tube', 'bi-bezier2', 'Nasogastric tube', ng.on, `${sw('ng_tube.on', ng.on, 'NG tube in place')}<div class="bs-grid">${sel('ng_tube.purpose', cat.ng_purposes, ng.purpose, 'Used for')}${ng.purpose === 'feeding' ? numIn('ng_tube.feed_ml_h', ng.feed_ml_h, 'Feed rate (mL/h)', 'min="0" max="300"') : ''}</div>`],
      ['collar', 'bi-shield-plus', 'Neck collar', dev.collar.on, sw('collar.on', dev.collar.on, 'Cervical collar on (log-roll only)')],
      ['traction', 'bi-arrows-expand', 'Traction', tr.on, `${sw('traction.on', tr.on, 'Leg traction')}<div class="bs-grid">${sel('traction.limb', {left: 'Left leg', right: 'Right leg'}, tr.limb, 'Leg')}${numIn('traction.weight_kg', tr.weight_kg, 'Weight (kg)', 'min="1" max="15" step="0.5"')}</div>`],
      ['chest_drain', 'bi-lungs', 'Chest drain', cd.on, `${sw('chest_drain.on', cd.on, 'Chest drain')}<div class="bs-grid">${sel('chest_drain.side', {left: 'Left', right: 'Right'}, cd.side, 'Side')}${numIn('chest_drain.drainage_ml', cd.drainage_ml, 'Drained so far (mL)', 'min="0" max="3000" step="10"')}</div>${sw('chest_drain.bubbling', cd.bubbling, 'Bubbling (air leak)')}`],
      ['bed', 'bi-hospital', 'Bed', true, `<label class="bs-range">Head of bed <b>${dev.bed.head_deg}°</b><input type="range" min="0" max="80" step="5" data-p="bed.head_deg" value="${dev.bed.head_deg}" ${canEdit ? '' : 'disabled'}></label>${sw('bed.rails', dev.bed.rails, 'Side rails up')}`],
    ];
  }

  let open = 'iv';
  function renderControls() {
    const d = MFBedside.derive(dev, boot.patient.weight_kg);
    $('#bs-controls').innerHTML = sections().map(([k, icon, title, on, body]) => `<details class="bs-sec ${on ? 'on' : ''}" data-sec="${k}" ${open === k ? 'open' : ''}>
      <summary><i class="bi ${icon}"></i>${title}<span class="bs-state">${k === 'iv' && on ? `${dev.iv.rate_ml_h} mL/h · ${d.drops_per_min} drops/min` : k === 'oxygen' && on ? `${dev.oxygen.flow_l_min} L/min` : k === 'bed' ? `${dev.bed.head_deg}°` : on ? 'On' : 'Off'}</span></summary><div class="bs-body">${body}</div></details>`).join('');
    renderDerived(d);
    $('#bs-save').hidden = !dirty;
    $('#bs-reset').hidden = !dirty;
  }
  function renderDerived(d) {
    const iv = dev.iv;
    let html = '';
    if (iv.on) {
      const ends = d.hours_left != null ? new Date(Date.now() + d.hours_left * 3600000) : null;
      html += `<div class="bs-fact"><b>${iv.pump ? `${iv.rate_ml_h} mL/h` : `${d.drops_per_min} drops/min`}</b><span>${iv.pump ? 'pump rate' : `${iv.rate_ml_h} mL/h with a ${iv.drop_factor} drops/mL set (rate × ${iv.drop_factor} ÷ 60)`}</span></div>`;
      if (ends) html += `<div class="bs-fact"><b>${Math.floor(d.hours_left)} h ${Math.round((d.hours_left % 1) * 60)} min</b><span>until the bag is empty, about ${ends.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}</span></div>`;
    }
    if (dev.oxygen.on) html += `<div class="bs-fact"><b>~${d.fio2}%</b><span>estimated oxygen breathed in</span></div>`;
    if (d.urine_ml_kg_h != null) html += `<div class="bs-fact"><b>${d.urine_ml_kg_h} mL/kg/h</b><span>urine output (target 0.5 or more)</span></div>`;
    html += d.warnings.map(w => `<div class="bs-warn"><i class="bi bi-exclamation-triangle-fill"></i>${esc(w)}</div>`).join('');
    $('#bs-derived').innerHTML = html;
  }

  const setP = (path, val) => { const k = path.split('.'); dev[k[0]][k[1]] = val; };
  $('#bs-controls').addEventListener('toggle', ev => { if (ev.target.open) open = ev.target.dataset.sec; }, true);
  $('#bs-controls').addEventListener('input', ev => {
    const el = ev.target; if (!el.dataset.p) return;
    let v = el.type === 'checkbox' ? el.checked : el.type === 'number' || el.type === 'range' || el.dataset.p === 'iv.drop_factor' ? (el.value === '' ? 0 : +el.value) : el.value;
    setP(el.dataset.p, v);
    // keep the preview inside the limits the server will apply
    if (el.dataset.p === 'oxygen.device') { const [lo, hi] = cat.o2_limits[dev.oxygen.device]; dev.oxygen.flow_l_min = Math.min(hi, Math.max(lo, dev.oxygen.flow_l_min)); }
    if (el.dataset.p === 'iv.bag_ml' || el.dataset.p === 'iv.remaining_ml') dev.iv.remaining_ml = Math.min(dev.iv.remaining_ml, dev.iv.bag_ml);
    dirty = true;
    scene.update({devices: dev});
    if (el.tagName === 'SELECT' || el.type === 'checkbox') renderControls();
    else { renderDerived(MFBedside.derive(dev, boot.patient.weight_kg)); $('#bs-save').hidden = false; $('#bs-reset').hidden = false;
      const s = el.closest('details').querySelector('.bs-state'), d = MFBedside.derive(dev, boot.patient.weight_kg);
      if (el.dataset.p.startsWith('iv.')) s.textContent = `${dev.iv.rate_ml_h} mL/h · ${d.drops_per_min} drops/min`;
      if (el.dataset.p === 'bed.head_deg') { s.textContent = `${dev.bed.head_deg}°`; el.previousElementSibling.textContent = `${dev.bed.head_deg}°`; } }
  });

  async function post(url, body) {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(body), credentials: 'same-origin'});
    const data = await r.json().catch(() => ({ok: false, error: `The server answered ${r.status}.`}));
    if (!r.ok || !data.ok) throw new Error(data.error || 'Saving failed.');
    return data;
  }
  function fromServer(d) {
    saved = structuredClone(d.devices); dev = structuredClone(d.devices); dirty = false;
    boot.vitals = d.vitals; boot.patient = d.patient;
    scene.update({devices: dev, vitals: d.vitals, patient: d.patient, injury: d.injury});
    renderControls(); renderObs(d);
  }
  $('#bs-save').addEventListener('click', async ev => {
    ev.target.disabled = true;
    try { fromServer(await post(boot.urls.devices, {devices: dev})); flash('Equipment saved.'); } catch (e) { flash(e.message, true); }
    ev.target.disabled = false;
  });
  $('#bs-reset').addEventListener('click', () => { dev = structuredClone(saved); dirty = false; scene.update({devices: dev}); renderControls(); });

  // ---------------------------------------------------------------- observations
  const obsForm = $('#bs-obs');
  function renderObs(d) {
    const n = d ? d.news2 : boot.news2, hist = d ? d.history : boot.history;
    $('#bs-news-card').innerHTML = n ? `<div class="news-score news-${n.risk}"><b>${n.total}</b><span>NEWS2</span></div><div><b>${({high: 'High risk', medium: 'Medium risk', 'low-medium': 'Low–medium risk', low: 'Low risk'})[n.risk]}</b>
      <div class="small">${esc(n.response || '')}</div>${n.missing && n.missing.length ? `<div class="small muted">Not measured: ${n.missing.map(m => m.replace('_', ' ')).join(', ')}</div>` : ''}</div>` : '<p class="muted small mb-0">No observations recorded for this stay.</p>';
    $('#bs-obs-history').innerHTML = (hist || []).map(o => `<tr><td>${new Date(o.at).toLocaleString([], {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'})}</td><td>${o.heart_rate ?? '–'}</td><td>${o.systolic ? `${o.systolic}/${o.diastolic ?? '–'}` : '–'}</td><td>${o.resp_rate ?? '–'}</td><td>${o.spo2 ?? '–'}${o.on_oxygen ? '<small> O₂</small>' : ''}</td><td>${o.temperature_c ?? '–'}</td><td>${o.consciousness}</td><td><span class="news-pill">${o.news2 ?? '–'}</span></td></tr>`).join('') || '<tr><td colspan="8" class="empty">No observations yet.</td></tr>';
  }
  if (obsForm) {
    const v = boot.vitals || {};
    for (const k of ['heart_rate', 'systolic', 'diastolic', 'resp_rate', 'spo2', 'temperature_c']) if (v[k] != null) obsForm.elements[k].value = v[k];
    obsForm.elements.on_oxygen.checked = dev.oxygen.on;
    const preview = () => {
      const f = obsForm.elements, o = {};
      for (const k of ['heart_rate', 'systolic', 'diastolic', 'resp_rate', 'spo2', 'temperature_c']) o[k] = f[k].value === '' ? null : +f[k].value;
      o.consciousness = f.consciousness.value; o.on_oxygen = f.on_oxygen.checked;
      const n = MFBedside.news2(o);
      $('#bs-obs-preview').innerHTML = n ? `NEWS2 would be <b class="news-${n.risk}">${n.total}</b>` : '';
      scene.update({vitals: o});
      return o;
    };
    obsForm.addEventListener('input', preview);
    obsForm.addEventListener('submit', async ev => {
      ev.preventDefault();
      const o = preview(), btn = obsForm.querySelector('button[type=submit]'); btn.disabled = true;
      try { fromServer(await post(boot.urls.observations, o)); flash('Observations recorded.'); } catch (e) { flash(e.message, true); }
      btn.disabled = false;
    });
  }

  // clicking equipment on the picture opens its controls
  $('#bs-host').addEventListener('click', ev => {
    const hit = ev.target.closest('[data-open]'); if (!hit) return;
    if (hit.dataset.open === 'obs') { obsForm?.scrollIntoView({behavior: 'smooth', block: 'center'}); obsForm?.elements.heart_rate.focus(); return; }
    open = hit.dataset.open; renderControls(); document.querySelector(`[data-sec="${open}"]`)?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  });
  $('#bs-host').addEventListener('keydown', ev => { if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.closest('[data-open]')) { ev.preventDefault(); ev.target.closest('[data-open]').dispatchEvent(new MouseEvent('click', {bubbles: true})); } });

  function flash(msg, bad) { const t = $('#bs-toast'); t.textContent = msg; t.className = `bs-toast show${bad ? ' bad' : ''}`; clearTimeout(t.__h); t.__h = setTimeout(() => t.classList.remove('show'), 3800); }
  window.addEventListener('beforeunload', ev => { if (dirty) { ev.preventDefault(); ev.returnValue = ''; } });

  renderControls(); renderObs();
})();
