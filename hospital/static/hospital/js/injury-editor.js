/* Injury & burns editor: every input redraws the animated figure and recomputes TBSA, fluids, GCS and alerts.
   Click the body to add a burn or an injury at that spot. Save sends everything to the server, which cleans it,
   recomputes and answers; the page then redraws from the server's copy. */
(() => {
  'use strict';
  const boot = JSON.parse(document.getElementById('injury-boot').textContent);
  const cat = boot.catalogue, M = window.MFInjury;
  window.MF_INJURY_TYPES = cat.injury_types;
  const $ = s => document.querySelector(s), esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  let A = structuredClone(boot.assessment), weight = boot.weight_kg, dirty = false, tab = 'burns';
  A.burn ||= {cause: 'flame', time: '', inhalation: false, given_ml: 0};
  A.burns ||= []; A.injuries ||= [];

  const paired = new Set(cat.paired);
  const opt = (obj, sel) => Object.entries(obj).map(([k, v]) => `<option value="${k}" ${k === sel ? 'selected' : ''}>${esc(v)}</option>`).join('');
  const optList = (arr, sel, label = x => x[0].toUpperCase() + x.slice(1).replace(/_/g, ' ')) => arr.map(k => `<option value="${k}" ${k === sel ? 'selected' : ''}>${esc(label(k))}</option>`).join('');

  function fixPlace(e) {
    if (!paired.has(e.region)) e.side = ''; else if (!e.side) e.side = 'left';
    if (!cat.views[e.region].includes(e.view)) e.view = cat.views[e.region][0];
  }

  /* --------------------------------------------------------------- render */
  function render() {
    const computed = M.compute(A, cat, {age: boot.age, weight_kg: weight, vitals: boot.vitals});
    M.figure($('#inj-figure'), {data: A, computed, cat, age: boot.age}, {interactive: true, onRegion: addAt});
    renderSummary(computed);
    renderTab();
    $('#inj-save').disabled = !dirty;
    $('#inj-dirty').hidden = !dirty;
  }

  function renderSummary(c) {
    const f = c.fluids, bd = c.by_depth;
    const depthBar = Object.entries(M.DEPTH).map(([k, d]) => bd[k] ? `<span style="--w:${Math.min(100, bd[k] * 3)}%;--c:${d.fill}" title="${d.name}: ${bd[k]}%"><i></i>${d.name} <b>${bd[k]}%</b></span>` : '').join('');
    $('#inj-summary').innerHTML = `
      <div class="inj-stat ${c.tbsa >= (f ? f.threshold : 15) ? 'hot' : ''}"><b>${c.tbsa}<small>%</small></b><span>body surface burned<br><em>excludes simple redness</em></span></div>
      ${depthBar ? `<div class="inj-depths">${depthBar}</div>` : ''}
      ${f ? `<div class="inj-fluids"><h3>Parkland fluids (Ringer's lactate)</h3>
        <div class="fl-row"><span>First 24 hours</span><b>${f.total_24h.toLocaleString()} mL</b></div>
        <div class="fl-row"><span>First 8 hours from the burn</span><b>${f.first_8h.toLocaleString()} mL · ${f.rate_first_ml_h} mL/h</b></div>
        <div class="fl-row"><span>Next 16 hours</span><b>${f.next_16h.toLocaleString()} mL · ${f.rate_next_ml_h} mL/h</b></div>
        ${f.catch_up_ml_h != null ? `<div class="fl-row now"><span>Rate now (${f.hours_since_burn} h since burn, ${f.phase})</span><b>${f.catch_up_ml_h} mL/h</b></div>` : ''}
        <div class="fl-row"><span>Urine output target</span><b>≥ ${f.urine_target_ml_h} mL/h</b></div>
        ${!f.resuscitation_needed ? `<p class="small muted mb-0">Below ${f.threshold}%: formal resuscitation is usually not needed; give oral or maintenance fluids.</p>` : ''}
        ${boot.bedside_url && f.resuscitation_needed ? `<button type="button" class="btn btn-sm btn-primary mt-2" id="inj-apply-iv"><i class="bi bi-droplet"></i>Set the IV to ${f.catch_up_ml_h ?? f.rate_first_ml_h} mL/h</button>` : ''}
      </div>` : ''}
      ${c.spine ? `<div class="inj-chip"><i class="bi bi-diagram-2"></i><div><b>${esc(A.spine.level)} · ASIA ${A.spine.asia}</b><span>${esc(c.spine.pattern)}</span></div></div>` : ''}
      ${c.head ? `<div class="inj-chip sev-${c.head.severity}"><i class="bi bi-person-exclamation"></i><div><b>GCS ${c.head.gcs}</b><span>${c.head.severity} head injury · E${A.head.eye} V${A.head.verbal} M${A.head.motor}</span></div></div>` : ''}
      <ul class="inj-alerts">${c.alerts.map(a => `<li class="lv-${a.level}"><i class="bi ${a.level === 'high' ? 'bi-exclamation-octagon-fill' : a.level === 'warn' ? 'bi-exclamation-triangle-fill' : 'bi-info-circle-fill'}"></i>${esc(a.text)}</li>`).join('') || '<li class="lv-ok"><i class="bi bi-check-circle"></i>Nothing urgent from what is entered.</li>'}</ul>`;
    const btn = $('#inj-apply-iv');
    if (btn) btn.onclick = () => applyIv(f.catch_up_ml_h ?? f.rate_first_ml_h);
  }

  function renderTab() {
    document.querySelectorAll('.inj-tabs [data-tab]').forEach(b => b.setAttribute('aria-selected', b.dataset.tab === tab));
    const box = $('#inj-panel');
    if (box.dataset.tab === tab && box.contains(document.activeElement) && document.activeElement.matches('input[type=range],input[type=number],textarea,input[type=text]')) return; // keep focus while typing
    box.dataset.tab = tab;
    if (tab === 'burns') box.innerHTML = `
      <div class="grid-3">
        <label>Cause<select class="form-select form-select-sm" data-k="burn.cause">${optList(cat.causes, A.burn.cause)}</select></label>
        <label>Time of burn<input type="datetime-local" class="form-control form-control-sm" data-k="burn.time" value="${esc(A.burn.time)}"></label>
        <label>Fluids given since (mL)<input type="number" min="0" class="form-control form-control-sm" data-k="burn.given_ml" value="${A.burn.given_ml || 0}"></label>
      </div>
      <label class="chk"><input type="checkbox" data-k="burn.inhalation" ${A.burn.inhalation ? 'checked' : ''}> Possible inhalation injury (burnt in a closed space, soot, hoarse voice)</label>
      <div class="inj-rows">${A.burns.map((b, i) => burnRow(b, i)).join('') || '<p class="muted small">Click the body to add a burn there, or use the button below.</p>'}</div>
      <button type="button" class="btn btn-sm btn-ghost" data-add="burn"><i class="bi bi-plus-lg"></i>Add a burn</button>`;
    else if (tab === 'spine') box.innerHTML = A.spine ? `
      <div class="grid-3">
        <label>Level of injury<select class="form-select form-select-sm" data-k="spine.level">${optList(M.LEVELS, A.spine.level, x => x === 'S' ? 'Sacrum' : x)}</select></label>
        <label>Type<select class="form-select form-select-sm" data-k="spine.type">${optList(cat.spine_types, A.spine.type, x => ({cord_contusion: 'Cord contusion', central_cord: 'Central cord syndrome', disc: 'Disc injury'}[x] || x[0].toUpperCase() + x.slice(1)))}</select></label>
        <label class="chk mt-4"><input type="checkbox" data-k="spine.immobilised" ${A.spine.immobilised ? 'checked' : ''}> Immobilised (collar / log-roll)</label>
      </div>
      <div class="asia" role="radiogroup" aria-label="ASIA impairment grade">${Object.entries(cat.asia).map(([g, d]) => `<label class="${A.spine.asia === g ? 'on' : ''}"><input type="radio" name="asia" value="${g}" data-k="spine.asia" ${A.spine.asia === g ? 'checked' : ''}><b>${g}</b><span>${esc(d)}</span></label>`).join('')}</div>
      <button type="button" class="btn btn-sm btn-ghost" data-clear="spine"><i class="bi bi-x-lg"></i>Remove spinal injury</button>`
      : `<p class="muted">No spinal injury recorded.</p><button type="button" class="btn btn-sm btn-primary" data-add="spine"><i class="bi bi-plus-lg"></i>Record a spinal injury</button>`;
    else if (tab === 'head') {
      const E = ['No eye opening', 'To pain', 'To voice', 'Spontaneously'], V = ['No sounds', 'Sounds only', 'Words', 'Confused', 'Orientated'],
        Mo = ['No movement', 'Extends to pain', 'Abnormal flexion', 'Withdraws from pain', 'Localises pain', 'Obeys commands'];
      const sel = (k, arr) => `<select class="form-select form-select-sm" data-k="head.${k}" data-num>${arr.map((t, i) => `<option value="${i + 1}" ${A.head[k] === i + 1 ? 'selected' : ''}>${i + 1} · ${t}</option>`).join('')}</select>`;
      box.innerHTML = A.head ? `<div class="grid-3"><label>Eyes (E)${sel('eye', E)}</label><label>Speech (V)${sel('verbal', V)}</label><label>Movement (M)${sel('motor', Mo)}</label></div>
        <div class="grid-3"><label>Pupils<select class="form-select form-select-sm" data-k="head.pupils">${optList(cat.pupils, A.head.pupils, x => ({equal: 'Equal and reacting', unequal: 'Unequal', fixed: 'Fixed and dilated'}[x]))}</select></label>
        <label class="chk mt-4"><input type="checkbox" data-k="head.loc" ${A.head.loc ? 'checked' : ''}> Lost consciousness</label></div>
        <button type="button" class="btn btn-sm btn-ghost" data-clear="head"><i class="bi bi-x-lg"></i>Remove head injury</button>`
        : `<p class="muted">No head injury recorded.</p><button type="button" class="btn btn-sm btn-primary" data-add="head"><i class="bi bi-plus-lg"></i>Record a head injury (GCS)</button>`;
    } else if (tab === 'wounds') box.innerHTML = `<div class="inj-rows">${A.injuries.map((x, i) => injuryRow(x, i)).join('') || '<p class="muted small">Click the body to add a fracture, wound or bruise there.</p>'}</div>
      <button type="button" class="btn btn-sm btn-ghost" data-add="injury"><i class="bi bi-plus-lg"></i>Add an injury</button>`;
    else box.innerHTML = `<label class="w-100">Notes<textarea class="form-control" rows="6" data-k="notes" maxlength="2000">${esc(A.notes)}</textarea></label>`;
  }

  const placeSel = (e, i, list) => `<select class="form-select form-select-sm" data-row="${list}.${i}.region">${opt(cat.regions, e.region)}</select>
      ${paired.has(e.region) ? `<select class="form-select form-select-sm" data-row="${list}.${i}.side">${optList(['left', 'right'], e.side)}</select>` : ''}
      ${cat.views[e.region].length > 1 ? `<select class="form-select form-select-sm" data-row="${list}.${i}.view">${optList(cat.views[e.region], e.view)}</select>` : ''}`;
  const burnRow = (b, i) => `<div class="inj-row" style="--c:${M.DEPTH[b.depth].fill}"><i class="sw"></i>${placeSel(b, i, 'burns')}
      <select class="form-select form-select-sm" data-row="burns.${i}.depth">${opt(cat.depths, b.depth)}</select>
      <label class="pct">${b.pct}% of area<input type="range" min="1" max="100" value="${b.pct}" data-row="burns.${i}.pct" data-num aria-label="Percentage of this area burned"></label>
      <label class="chk"><input type="checkbox" data-row="burns.${i}.circumferential" ${b.circumferential ? 'checked' : ''}> All the way round</label>
      <button type="button" class="btn btn-sm btn-ghost" data-del="burns.${i}" aria-label="Remove burn"><i class="bi bi-trash"></i></button></div>`;
  const injuryRow = (x, i) => `<div class="inj-row"><select class="form-select form-select-sm" data-row="injuries.${i}.type">${opt(cat.injury_types, x.type)}</select>${placeSel(x, i, 'injuries')}
      <select class="form-select form-select-sm" data-row="injuries.${i}.severity">${optList(cat.severities, x.severity)}</select>
      <select class="form-select form-select-sm" data-row="injuries.${i}.bleeding">${optList(cat.bleeding, x.bleeding, k => ({none: 'No bleeding', oozing: 'Oozing', active: 'Active bleeding'}[k]))}</select>
      ${x.type === 'fracture' ? `<label class="chk"><input type="checkbox" data-row="injuries.${i}.open" ${x.open ? 'checked' : ''}> Open (bone through skin)</label>` : ''}
      <input class="form-control form-control-sm" placeholder="Note" maxlength="160" data-row="injuries.${i}.note" value="${esc(x.note)}">
      <button type="button" class="btn btn-sm btn-ghost" data-del="injuries.${i}" aria-label="Remove injury"><i class="bi bi-trash"></i></button></div>`;

  /* --------------------------------------------------------------- events */
  function changed() { dirty = true; render(); }
  function setPath(obj, path, v) { const k = path.split('.'); let o = obj; while (k.length > 1) o = o[k.shift()]; o[k[0]] = v; }
  const read = el => el.type === 'checkbox' ? el.checked : el.dataset.num !== undefined || el.type === 'number' ? (el.value === '' ? 0 : +el.value) : el.value;

  $('#inj-panel').addEventListener('input', ev => {
    const el = ev.target;
    if (el.dataset.k) setPath(A, el.dataset.k, read(el));
    else if (el.dataset.row) {
      const [list, i, key] = el.dataset.row.split('.');
      A[list][+i][key] = read(el);
      if (key === 'region') fixPlace(A[list][+i]);
      if (key === 'pct') el.parentNode.firstChild.textContent = `${el.value}% of area`;
    } else return;
    dirty = true;
    const rebuild = el.tagName === 'SELECT' || el.type === 'checkbox' || el.type === 'radio';
    if (rebuild) render(); else { const c = M.compute(A, cat, {age: boot.age, weight_kg: weight, vitals: boot.vitals}); M.figure($('#inj-figure'), {data: A, computed: c, cat, age: boot.age}, {interactive: true, onRegion: addAt}); renderSummary(c); $('#inj-save').disabled = false; $('#inj-dirty').hidden = false; }
  });
  $('#inj-panel').addEventListener('click', ev => {
    const add = ev.target.closest('[data-add]'), del = ev.target.closest('[data-del]'), clr = ev.target.closest('[data-clear]');
    if (add) {
      const k = add.dataset.add;
      if (k === 'burn') A.burns.push({region: 'forearm', side: 'left', view: 'front', depth: 'superficial_partial', pct: 50, circumferential: false});
      if (k === 'injury') A.injuries.push({type: 'fracture', region: 'leg', side: 'right', view: 'front', severity: 'moderate', bleeding: 'none', open: false, note: ''});
      if (k === 'spine') A.spine = {level: 'C5', asia: 'C', type: 'fracture', immobilised: true};
      if (k === 'head') A.head = {eye: 4, verbal: 5, motor: 6, pupils: 'equal', loc: false};
      changed();
    } else if (del) { const [list, i] = del.dataset.del.split('.'); A[list].splice(+i, 1); changed(); }
    else if (clr) { A[clr.dataset.clear] = null; changed(); }
  });
  document.querySelectorAll('.inj-tabs [data-tab]').forEach(b => b.addEventListener('click', () => { tab = b.dataset.tab; renderTab(); }));
  $('#inj-weight').addEventListener('input', ev => { weight = ev.target.value === '' ? null : +ev.target.value; changed(); });

  // Click on the body: add a burn (Burns tab) or an injury (otherwise) at that region.
  function addAt(place) {
    if (tab === 'burns') { A.burns.push({...place, depth: 'superficial_partial', pct: 50, circumferential: false}); }
    else { A.injuries.push({type: tab === 'spine' ? 'fracture' : 'contusion', ...place, severity: 'moderate', bleeding: 'none', open: false, note: ''}); if (tab !== 'wounds') tab = 'wounds'; }
    fixPlace(tab === 'burns' ? A.burns.at(-1) : A.injuries.at(-1));
    changed();
    const rows = document.querySelectorAll('#inj-panel .inj-row');
    rows[rows.length - 1]?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
    rows[rows.length - 1]?.classList.add('just-added');
  }

  /* --------------------------------------------------------------- save */
  async function post(url, body) {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(body), credentials: 'same-origin'});
    const data = await r.json().catch(() => ({ok: false, error: `The server answered ${r.status}.`}));
    if (!r.ok || !data.ok) throw new Error(data.error || 'Saving failed.');
    return data;
  }
  $('#inj-save').addEventListener('click', async () => {
    const btn = $('#inj-save'); btn.disabled = true; btn.classList.add('busy');
    try {
      const d = await post(boot.save_url, {assessment: A, weight_kg: weight});
      A = d.assessment; weight = d.weight_kg; dirty = false;
      A.burn ||= {cause: 'flame', time: '', inhalation: false, given_ml: 0};
      render();
      toast(`Saved · ${d.summary}`);
      const h = $('#inj-history'); if (h) h.insertAdjacentHTML('afterbegin', `<li><b>Just now</b><span>${esc(d.summary)}</span></li>`);
    } catch (e) { toast(e.message, true); btn.disabled = false; }
    btn.classList.remove('busy');
  });
  async function applyIv(rate) {
    if (!boot.bedside) return;
    const dev = structuredClone(boot.bedside.devices);
    Object.assign(dev.iv, {on: true, fluid: 'ringers', rate_ml_h: rate, pump: true});
    if (dev.iv.remaining_ml < 200) Object.assign(dev.iv, {bag_ml: 1000, remaining_ml: 1000});
    try { await post(boot.bedside_url, {devices: dev}); boot.bedside.devices = dev; toast(`IV set to Ringer's lactate at ${rate} mL/h on the bed page.`); }
    catch (e) { toast(e.message, true); }
  }
  function toast(msg, bad) {
    const t = $('#inj-toast'); t.textContent = msg; t.className = `inj-toast show${bad ? ' bad' : ''}`;
    clearTimeout(t.__h); t.__h = setTimeout(() => t.classList.remove('show'), 4200);
  }
  window.addEventListener('beforeunload', ev => { if (dirty) { ev.preventDefault(); ev.returnValue = ''; } });

  $('#inj-weight').value = weight ?? '';
  render();
})();
