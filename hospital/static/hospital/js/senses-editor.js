/* Eye & ear examination editor. Every value entered recomputes the findings (MFSenses.compute, a mirror of the
   server's senses.py) and redraws the animations: what the patient sees, the eye's pressure and fundus, the swinging
   torch, the audiogram, the sound path through the ear and the otoscope view. Save sends the values; the server
   cleans them, recomputes and answers, and the page redraws from its copy. */
(() => {
  'use strict';
  const boot = JSON.parse(document.getElementById('senses-boot').textContent);
  const M = window.MFSenses, cat = boot.catalogue;
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  const SIDES = ['right', 'left'];
  let X = structuredClone(boot.exam), dirty = false, C = null;
  const ui = Object.assign({mode: 'eyes', eye: 'right', view: 'vision', ear: 'right', entry: 'right.ac', normal: false},
    JSON.parse(sessionStorage.getItem('mf-senses-ui') || '{}'));
  if (location.hash === '#ears') ui.mode = 'ears';

  /* ------------------------------------------------------------- inputs */
  const opt = (obj, sel) => Object.entries(obj).map(([k, v]) => `<option value="${esc(k)}" ${k === sel ? 'selected' : ''}>${esc(v)}</option>`).join('');
  const acuityOpts = sel => `<option value="">—</option>` + cat.acuity.map(a => `<option value="${a}" ${a === sel ? 'selected' : ''}>${a}${cat.acuity_labels[a] ? ` · ${cat.acuity_labels[a]}` : ''}</option>`).join('');
  const row = (label, cell, hint = '') => `<tr><th scope="row">${label}${hint ? `<small>${hint}</small>` : ''}</th>${SIDES.map(s => `<td class="side-${s}">${cell(s)}</td>`).join('')}</tr>`;
  const sel = (k, obj) => s => `<select class="form-select form-select-sm" data-k="${k.replace('$', s)}">${opt(obj, get(k.replace('$', s)))}</select>`;
  const num = (k, attrs) => s => `<input type="number" class="form-control form-control-sm" data-k="${k.replace('$', s)}" data-num value="${get(k.replace('$', s)) ?? ''}" ${attrs}>`;
  const chk = k => s => `<input type="checkbox" class="form-check-input" data-k="${k.replace('$', s)}" ${get(k.replace('$', s)) ? 'checked' : ''}>`;
  function get(path) { return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), X); }
  function set(path, v) {
    const k = path.split('.'); let o = X;
    while (k.length > 1) { const p = k.shift(); o[p] ??= {}; o = o[p]; }
    if (v === undefined) delete o[k[0]]; else o[k[0]] = v;
  }

  function renderInputs() {
    const box = $('#ss-inputs');
    if (ui.mode === 'eyes') {
      box.innerHTML = `<div class="panel-head"><h2>Eye findings</h2><span class="hint">R = patient's right</span></div>
      <div class="ss-table-wrap"><table class="ss-table"><thead><tr><th></th><th>Right eye</th><th>Left eye</th></tr></thead><tbody>
        ${row('Examined', chk('eyes.$.examined'))}
        ${row('Vision', s => `<select class="form-select form-select-sm" data-k="eyes.${s}.va">${acuityOpts(get(`eyes.${s}.va`))}</select>`, 'with usual glasses')}
        ${row('Pinhole', s => `<select class="form-select form-select-sm" data-k="eyes.${s}.pinhole">${acuityOpts(get(`eyes.${s}.pinhole`))}</select>`)}
        ${row('Pressure', num('eyes.$.iop', 'min="0" max="80" step="1" placeholder="mmHg"'), 'mmHg · normal 10–21')}
        ${row('Cup-to-disc', num('eyes.$.cdr', 'min="0" max="1" step="0.05" placeholder="0.3"'), '0–1')}
        ${row('Pupil size', num('eyes.$.pupil_mm', 'min="1" max="9" step="0.5"'), 'mm')}
        ${row('Pupil reaction', sel('eyes.$.reaction', cat.reaction))}
        ${row('RAPD', chk('eyes.$.rapd'), 'swinging torch')}
        ${row('Lens', sel('eyes.$.lens', cat.lens))}
        ${row('Conjunctiva', sel('eyes.$.conjunctiva', cat.conjunctiva))}
        ${row('Discharge', sel('eyes.$.discharge', cat.discharge_eye))}
        ${row('Cornea', sel('eyes.$.cornea', cat.cornea))}
        ${row('Front chamber', sel('eyes.$.chamber', cat.chamber))}
        ${row('Visual field', sel('eyes.$.field', cat.field))}
        <tr class="grp"><th colspan="3">Back of the eye</th></tr>
        ${row('Diabetic retinopathy', sel('eyes.$.retina.dr', cat.dr))}
        ${row('Maculopathy', chk('eyes.$.retina.maculopathy'))}
        ${row('Hypertensive grade', s => `<select class="form-select form-select-sm" data-k="eyes.${s}.retina.htn" data-num>${[0, 1, 2, 3, 4].map(g => `<option value="${g}" ${get(`eyes.${s}.retina.htn`) === g ? 'selected' : ''}>${g === 0 ? 'None' : `Grade ${g}`}</option>`).join('')}</select>`)}
        ${row('Swollen disc (papilloedema)', chk('eyes.$.retina.papilloedema'))}
        ${row('Retinal detachment', chk('eyes.$.retina.detachment'))}
        ${row('Macular degeneration', sel('eyes.$.retina.amd', cat.amd))}
      </tbody></table></div>
      <div class="ss-sym">${[['eye_pain', 'Eye pain'], ['photophobia', 'Light hurts']].map(([k, l]) => `<label class="chk"><input type="checkbox" class="form-check-input" data-k="symptoms.${k}" ${X.symptoms[k] ? 'checked' : ''}> ${l}</label>`).join('')}</div>
      <label class="w-100 mt-2 small fw-semibold">Notes<textarea class="form-control" rows="3" maxlength="2000" data-k="notes">${esc(X.notes)}</textarea></label>`;
    } else {
      const thr = (side, kind, freqs) => `<tr><th scope="row">${side === 'right' ? 'Right' : 'Left'} ${kind === 'ac' ? 'air' : 'bone'}</th>${cat.freqs.map(f => `<td>${freqs.includes(f) ? `<input type="number" class="form-control form-control-sm" min="-10" max="120" step="5" data-k="ears.${side}.${kind}.${f}" data-thr value="${X.ears[side][kind][f] ?? ''}" aria-label="${side} ${kind} ${f} Hz">` : ''}</td>`).join('')}</tr>`;
      box.innerHTML = `<div class="panel-head"><h2>Ear findings</h2><span class="hint">Thresholds in dB HL; click the audiogram or type</span></div>
      <div class="ss-table-wrap"><table class="ss-table ss-thr"><thead><tr><th></th>${cat.freqs.map(f => `<th>${+f >= 1000 ? +f / 1000 + 'k' : f}</th>`).join('')}</tr></thead><tbody>
        ${SIDES.map(s => thr(s, 'ac', cat.freqs) + thr(s, 'bc', cat.pta_freqs)).join('')}</tbody></table></div>
      <div class="ss-table-wrap"><table class="ss-table"><thead><tr><th></th><th>Right ear</th><th>Left ear</th></tr></thead><tbody>
        ${row('Examined', chk('ears.$.examined'))}
        ${row('Ear canal', sel('ears.$.canal', cat.canal))}
        ${row('Ear drum', sel('ears.$.tm', cat.tm))}
        ${row('Perforation size', num('ears.$.perforation_pct', 'min="0" max="100" step="5"'), '% of the drum')}
        ${row('Discharge', sel('ears.$.discharge', cat.discharge_ear))}
        ${row('Tympanogram', sel('ears.$.tympanogram', cat.tympanogram))}
        ${row('Rinne test', sel('ears.$.rinne', {'': 'Not done', positive: 'Positive (air > bone)', negative: 'Negative (bone > air)'}))}
      </tbody></table></div>
      <div class="mt-2"><label class="small fw-semibold ss-weber">Weber test<select class="form-select form-select-sm" data-k="weber">${opt({'': 'Not done', central: 'Central', right: 'Heard in the right ear', left: 'Heard in the left ear'}, X.weber)}</select></label></div>
      <div class="ss-sym">${[['tinnitus', 'Ringing (tinnitus)'], ['vertigo', 'Vertigo'], ['sudden_loss', 'Sudden loss (within 72 h)'], ['ear_pain', 'Ear pain']].map(([k, l]) => `<label class="chk"><input type="checkbox" class="form-check-input" data-k="symptoms.${k}" ${X.symptoms[k] ? 'checked' : ''}> ${l}</label>`).join('')}</div>
      <label class="w-100 mt-2 small fw-semibold">Notes<textarea class="form-control" rows="3" maxlength="2000" data-k="notes">${esc(X.notes)}</textarea></label>`;
    }
    markExamined();
  }
  function markExamined() {
    for (const s of SIDES) {
      const on = ui.mode === 'eyes' ? X.eyes[s].examined : X.ears[s].examined;
      $$(`#ss-inputs td.side-${s}`).forEach((td, i) => { if (i) td.classList.toggle('off', !on); });
    }
  }

  $('#ss-inputs').addEventListener('input', ev => {
    const el = ev.target, k = el.dataset.k;
    if (!k) return;
    let v;
    if (el.type === 'checkbox') v = el.checked;
    else if (el.dataset.thr !== undefined) v = el.value === '' ? undefined : +el.value;
    else if (el.dataset.num !== undefined || el.type === 'number') v = el.value === '' ? null : +el.value;
    else v = el.value;
    set(k, v);
    // filling in a value means the side was examined
    const m = k.match(/^(eyes|ears)\.(right|left)\.(?!examined)/);
    if (m && v !== '' && v != null && v !== false && !X[m[1]][m[2]].examined) {
      X[m[1]][m[2]].examined = true;
      const box = $(`[data-k="${m[1]}.${m[2]}.examined"]`); if (box) box.checked = true;
    }
    if (k.endsWith('.examined')) markExamined();
    changed();
  });

  /* ------------------------------------------------------------- Dr. Flow follows the findings */
  const QUESTIONS = [
    ['angle-closure', 'How is acute angle-closure glaucoma managed in the first hour?'], ['Glaucoma', 'How is open-angle glaucoma treated and followed up?'],
    ['Cataract is reducing', 'What should I tell a patient before cataract surgery?'], ['diabetic retinopathy', 'How should diabetic retinopathy be followed up?'],
    ['hypertensive emergency', 'How is a hypertensive emergency treated?'], ['Retinal detachment', 'What are the warning signs of retinal detachment?'],
    ['Corneal ulcer', 'How is a corneal ulcer treated?'], ['conjunctivitis', 'How do I tell bacterial from viral conjunctivitis?'],
    ['Papilloedema', 'What are the causes of papilloedema?'], ['Acute otitis media', 'When does acute otitis media need antibiotics?'],
    ['Chronic suppurative', 'How is chronic suppurative otitis media treated?'], ['Cholesteatoma', 'What are the complications of cholesteatoma?'],
    ['Sudden sensorineural', 'How is sudden sensorineural hearing loss treated?'], ['hearing aids', 'Which patients benefit from hearing aids?'],
    ['vestibular schwannoma', 'When should asymmetric hearing loss be scanned?'], ['wax', 'How is impacted ear wax removed safely?'],
    ['glue ear', 'When does glue ear need grommets?'], ['Otitis externa', 'How is otitis externa treated?']];
  function tellDrFlow() {
    const lines = C.alerts.map(a => ({level: a.level === 'high' ? 'danger' : a.level, text: a.text}));
    const suggest = [];
    for (const [k, q] of QUESTIONS) if (C.alerts.some(a => a.text.includes(k)) && !suggest.includes(q)) suggest.push(q);
    const msg = {lines, suggest: suggest.length ? suggest : undefined};
    if (window.DrFlowPage) window.DrFlowPage.update(msg); else window.__drflowPending = msg;   // Dr. Flow picks it up when he arrives
  }

  /* ------------------------------------------------------------- rendering */
  let drawT = null;
  function changed() { dirty = true; refresh(true); }
  function refresh(soon) {
    C = M.compute(X, boot.ctx);
    renderSummary();
    $('#ss-save').disabled = !dirty; $('#ss-dirty').hidden = !dirty;
    clearTimeout(drawT);
    drawT = setTimeout(() => { draw(); tellDrFlow(); }, soon ? 160 : 0);
  }

  function draw() {
    $$('[data-show]').forEach(el => { el.hidden = el.dataset.show !== ui.mode; });
    $$('[data-mode]').forEach(b => b.setAttribute('aria-selected', b.dataset.mode === ui.mode));
    $$('[data-eye]').forEach(b => b.classList.toggle('on', b.dataset.eye === ui.eye));
    $$('[data-view]').forEach(b => { b.classList.toggle('on', b.dataset.view === ui.view); b.disabled = ui.eye === 'both' && b.dataset.view !== 'vision'; });
    $$('[data-ear]').forEach(b => b.classList.toggle('on', b.dataset.ear === ui.ear));
    $$('[data-entry]').forEach(b => b.classList.toggle('on', b.dataset.entry === ui.entry));
    $('#ss-normal').checked = ui.normal;
    sessionStorage.setItem('mf-senses-ui', JSON.stringify(ui));
    if (ui.mode === 'eyes') {
      for (const id of ['#ss-ear', '#ss-oto', '#ss-aud']) M.stopAll($(id));
      M.eyesFront($('#ss-eyes'), X, C, {onPick: side => { ui.eye = side; if (ui.view === 'vision' && ui.eye === 'both') ui.view = 'vision'; draw(); }});
      const host = $('#ss-view'), s = ui.eye;
      if (s === 'both') M.vision(host, M.combine(C.eyes.right?.vision, C.eyes.left?.vision), {normal: ui.normal, label: 'What the patient sees with both eyes open'});
      else if (ui.view === 'vision') {
        if (!C.eyes[s]) { M.stopAll(host); host.innerHTML = `<div class="ss-empty">The ${s} eye has not been examined.</div>`; }
        else M.vision(host, C.eyes[s].vision, {normal: ui.normal, label: `What the ${s} eye sees`});
      } else if (ui.view === 'section') M.eyeSection(host, X.eyes[s], C.eyes[s], s);
      else M.fundus(host, X.eyes[s], C.eyes[s], s);
      $('.ss-compare').hidden = ui.view !== 'vision' && ui.eye !== 'both';
    } else {
      for (const id of ['#ss-eyes', '#ss-view']) M.stopAll($(id));
      M.audiogram($('#ss-aud'), X, C, {onSet: ({freq, db}) => {
        const [side, kind] = ui.entry.split('.');
        if (kind === 'bc' && !cat.pta_freqs.includes(freq)) { toast('Bone conduction is tested at 500 Hz – 4 kHz.', true); return; }
        X.ears[side][kind][freq] = db; X.ears[side].examined = true;
        const inp = $(`[data-k="ears.${side}.${kind}.${freq}"]`); if (inp) inp.value = db;
        const box = $(`[data-k="ears.${side}.examined"]`); if (box) box.checked = true;
        markExamined(); changed();
      }});
      M.earSection($('#ss-ear'), X.ears[ui.ear], C.ears[ui.ear], ui.ear);
      M.otoscope($('#ss-oto'), X.ears[ui.ear], C.ears[ui.ear], ui.ear);
    }
  }

  function renderSummary() {
    const v = C.vision, h = C.hearing;
    const eyeRow = s => { const c = C.eyes[s], e = X.eyes[s]; if (!c) return `<li class="muted">${s === 'right' ? 'Right' : 'Left'} eye not examined</li>`;
      return `<li><b>${s === 'right' ? 'R' : 'L'}</b><span>${e.va || '—'}${e.iop !== null ? ` · ${e.iop} mmHg` : ''}${e.cdr !== null ? ` · C/D ${e.cdr}` : ''}${c.glaucoma ? ` · <em class="t-warn">glaucoma ${c.glaucoma}</em>` : ''}${c.lens_grade >= 2 ? ' · cataract' : ''}</span></li>`; };
    const earRow = s => { const c = C.ears[s]; if (!c) return `<li class="muted">${s === 'right' ? 'Right' : 'Left'} ear not examined</li>`;
      return `<li><b>${s === 'right' ? 'R' : 'L'}</b><span>${c.pta !== null ? `${c.pta} dB · ${esc(c.grade_label)}` : 'no audiogram'}${c.type_label ? ` · ${esc(c.type_label)}` : ''}${c.gap !== null ? ` · gap ${c.gap} dB` : ''}</span></li>`; };
    // the same operation suggested for both sides becomes one booking for both sides
    const procs = [];
    for (const p of (C.procedures || []).filter(x => boot.procedure_types[x.code])) {
      const twin = procs.find(q => q.code === p.code && q.side !== p.side);
      if (twin) { twin.side = 'bilateral'; twin.reason = `${twin.reason}; ${p.reason}`; } else procs.push({...p});
    }
    const link = p => { const t = boot.procedure_types[p.code];
      const q = new URLSearchParams({encounter: boot.encounter, procedure_type: t.id, side: p.side, indication: p.reason, specialty: t.specialty, est_minutes: t.minutes, anaesthesia: t.anaesthesia});
      return `/theatre/new/?${q}`; };
    $('#ss-summary').innerHTML = `
      <div class="ss-kpis">
        <div class="ss-kpi ${v && ['moderate', 'severe', 'blind'].includes(v.category) ? 'bad' : v && v.category === 'mild' ? 'meh' : ''}"><i class="bi bi-eye"></i><div><b>${v ? esc(v.label) : 'Vision not tested'}</b><span>better eye${v ? ` · logMAR ${v.better_logmar}` : ''}</span></div></div>
        <div class="ss-kpi ${h && h.better_pta >= 35 ? 'bad' : h && h.better_pta >= 20 ? 'meh' : ''}"><i class="bi bi-ear"></i><div><b>${h ? esc(h.label) : 'Hearing not tested'}</b><span>better ear${h ? ` · ${h.better_pta} dB${h.aid ? ' · hearing aid advised' : ''}` : ''}</span></div></div>
      </div>
      <ul class="ss-sides">${ui.mode === 'eyes' ? SIDES.map(eyeRow).join('') : SIDES.map(earRow).join('')}</ul>
      <ul class="inj-alerts">${C.alerts.map(a => `<li class="lv-${a.level}"><i class="bi ${a.level === 'high' ? 'bi-exclamation-octagon-fill' : a.level === 'warn' ? 'bi-exclamation-triangle-fill' : 'bi-info-circle-fill'}"></i>${esc(a.text)}</li>`).join('') || '<li class="lv-ok"><i class="bi bi-check-circle"></i>Nothing abnormal from what is entered.</li>'}</ul>
      ${procs.length ? `<div class="ss-procs"><h3><i class="bi bi-scissors"></i> Operations these findings may need</h3>${procs.map(p => `<div class="ss-proc"><div><b>${esc(boot.procedure_types[p.code].name)} · ${p.side === 'bilateral' ? 'both sides' : p.side}</b><span>${esc(p.reason)}</span></div>
        <button type="button" class="btn btn-sm btn-ghost" ${dirty ? 'disabled title="Save the examination first"' : ''} data-drawer="${esc(link(p))}" data-title="Book ${esc(boot.procedure_types[p.code].name)}"><i class="bi bi-calendar-plus"></i>Book</button></div>`).join('')}
        ${dirty ? '<p class="small muted mb-0">Save the examination first, then book.</p>' : ''}</div>` : ''}`;
  }

  /* ------------------------------------------------------------- navigation inside the stage */
  document.addEventListener('click', ev => {
    const b = ev.target.closest('[data-mode],[data-eye],[data-view],[data-ear],[data-entry],[data-play]');
    if (!b || b.disabled) return;
    if (b.dataset.mode) { ui.mode = b.dataset.mode; M.stopSound(); renderInputs(); refresh(); return; }
    if (b.dataset.eye) { ui.eye = b.dataset.eye; if (ui.eye === 'both') ui.view = 'vision'; }
    if (b.dataset.view) ui.view = b.dataset.view;
    if (b.dataset.ear) ui.ear = b.dataset.ear;
    if (b.dataset.entry) { ui.entry = b.dataset.entry; ui.ear = ui.entry.split('.')[0]; }
    if (b.dataset.play) {
      if (b.dataset.play === 'stop') M.stopSound();
      else if (b.dataset.play === 'normal') M.playHearing(null);
      else {
        const a = X.ears[ui.ear];
        if (!a.examined || !Object.keys(a.ac).length) { toast(`Enter the ${ui.ear} ear's air-conduction thresholds first.`, true); return; }
        M.playHearing(a.ac, {tinnitus: X.symptoms.tinnitus});
        toast(`Playing tones and speech sounds, made quieter wherever the ${ui.ear} ear needs them louder.`);
      }
      return;
    }
    draw();
  });
  $('#ss-normal').addEventListener('change', ev => { ui.normal = ev.target.checked; draw(); });

  /* ------------------------------------------------------------- save */
  async function post(url, body) {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(body), credentials: 'same-origin'});
    const data = await r.json().catch(() => ({ok: false, error: `The server answered ${r.status}.`}));
    if (!r.ok || !data.ok) throw new Error(data.error || 'Saving failed.');
    return data;
  }
  $('#ss-save').addEventListener('click', async () => {
    const btn = $('#ss-save'); btn.disabled = true;
    try {
      const d = await post(boot.save_url, {exam: X});
      X = d.exam; dirty = false;
      renderInputs(); refresh();
      toast(`Saved · ${d.summary}`);
      const h = $('#ss-history'); if (h) { h.querySelector('.muted.small')?.remove(); h.insertAdjacentHTML('afterbegin', `<li><b>Just now</b><span>${esc(d.summary)}</span></li>`); }
    } catch (e) { toast(e.message, true); btn.disabled = false; }
  });
  function toast(msg, bad) {
    const t = $('#ss-toast'); t.textContent = msg; t.className = `inj-toast show${bad ? ' bad' : ''}`;
    clearTimeout(t.__h); t.__h = setTimeout(() => t.classList.remove('show'), 4200);
  }
  window.addEventListener('beforeunload', ev => { if (dirty) { ev.preventDefault(); ev.returnValue = ''; } });

  renderInputs();
  refresh();
})();
