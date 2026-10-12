/* Fill-in runtime: renders a form schema with pages, live conditions, calculations, checks and drafts.
   MFFormRuntime.mount(host, boot, {post(values) -> Promise<{ok, errors?, url?, error?}>, preview, onChange})
   boot: {schema, values, errors, scope, page, patient, draft_url, submit_label?, patterns}
   Used by the fill page, flow "fill in" steps, resubmitting after changes, and the designer preview. */
(() => {
  'use strict';
  const K = window.MFForm;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const W = {full: 6, half: 3, third: 2};
  const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  let uid = 0;

  function mount(host, boot, opts = {}) {
    window.MF_PATTERNS = boot.patterns || window.MF_PATTERNS;
    const schema = boot.schema || {fields: []}, fields = schema.fields || [];
    const pages = (schema.pages && schema.pages.length ? schema.pages : [{id: 'p1', title: 'Form'}]);
    const scope = boot.scope || '';
    const id = `fr${++uid}`;
    let values = {...(boot.values || {})}, errors = {...(boot.errors || {})}, touched = new Set(Object.keys(errors)), page = Math.min(boot.page || 0, pages.length - 1);
    let state = K.resolve(schema, values), busy = false, draftTimer = null;
    const editable = f => !K.DISPLAY.has(f.type) && f.type !== 'calc' && (f.filled_by || '') === scope && !f.readonly && !opts.readonly;
    const onPage = (f, i) => (f.page || pages[0].id) === pages[i].id;

    host.classList.add('fr');
    host.innerHTML = `<div class="fr-steps" role="tablist"></div><div class="fr-progress"><i></i><span></span></div>
      ${schema.settings && schema.settings.intro ? `<p class="fr-intro">${esc(schema.settings.intro)}</p>` : ''}
      <div class="fr-errors" role="alert" hidden></div><div class="fr-page"></div>
      <div class="fr-nav"><button type="button" class="btn btn-ghost fr-prev"><i class="bi bi-arrow-left"></i>Back</button>
        <span class="fr-draft small muted"></span>
        <button type="button" class="btn btn-ghost fr-next">Next<i class="bi bi-arrow-right ms-1"></i></button>
        <button type="button" class="btn btn-primary fr-submit">${esc(boot.submit_label || (schema.settings && schema.settings.submit_label) || 'Submit')}</button></div>`;
    const $ = s => host.querySelector(s);

    /* ---------------------------------------------------------------- field html */
    function control(f) {
      const v = values[f.key], dis = editable(f) ? '' : 'disabled', name = `${id}-${f.key}`;
      const attrs = `data-key="${f.key}" id="${name}" ${dis} ${f.required ? 'aria-required="true"' : ''} aria-describedby="${name}-msg"`;
      switch (f.type) {
        case 'text': case 'email': case 'phone':
          return `<input class="form-control" type="${f.type === 'phone' ? 'tel' : f.type === 'email' ? 'email' : 'text'}" ${attrs} value="${esc(v)}" placeholder="${esc(f.placeholder)}" ${f.maxlength ? `maxlength="${f.maxlength}"` : ''}>`;
        case 'textarea': return `<textarea class="form-control" rows="3" ${attrs} placeholder="${esc(f.placeholder)}">${esc(v)}</textarea>`;
        case 'number': return `<div class="fr-unit"><input class="form-control" type="number" inputmode="decimal" ${attrs} value="${v ?? ''}" ${f.min != null ? `min="${f.min}"` : ''} ${f.max != null ? `max="${f.max}"` : ''} step="${f.step || 'any'}">${f.unit ? `<span>${esc(f.unit)}</span>` : ''}</div>`;
        case 'date': return `<input class="form-control" type="date" ${attrs} value="${esc(v)}">`;
        case 'time': return `<input class="form-control" type="time" ${attrs} value="${esc(v)}">`;
        case 'select': return `<select class="form-select" ${attrs}><option value="">Choose…</option>${f.options.map(o => `<option ${o === v ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
        case 'radio': return `<div class="fr-pills" role="radiogroup" aria-labelledby="${name}-l">${f.options.map(o => `<label class="${o === v ? 'on' : ''}"><input type="radio" name="${name}" value="${esc(o)}" data-key="${f.key}" ${o === v ? 'checked' : ''} ${dis}>${esc(o)}</label>`).join('')}</div>`;
        case 'checkboxes': return `<div class="fr-pills multi">${f.options.map(o => { const on = (v || []).includes(o); return `<label class="${on ? 'on' : ''}"><input type="checkbox" value="${esc(o)}" data-key="${f.key}" data-multi ${on ? 'checked' : ''} ${dis}>${esc(o)}</label>`; }).join('')}</div>`;
        case 'checkbox': return `<label class="fr-check"><input type="checkbox" ${attrs} ${v ? 'checked' : ''}><span>${esc(f.label)}</span></label>`;
        case 'yesno': return `<div class="fr-pills yesno" role="radiogroup">${['yes', 'no'].map(o => `<label class="${o === v ? 'on' : ''}"><input type="radio" name="${name}" value="${o}" data-key="${f.key}" ${o === v ? 'checked' : ''} ${dis}>${o === 'yes' ? 'Yes' : 'No'}</label>`).join('')}</div>`;
        case 'rating': return `<div class="fr-rating" role="radiogroup">${[...Array(11)].map((_, i) => `<label style="--h:${120 - i * 12}" class="${v != null && +v === i ? 'on' : ''}"><input type="radio" name="${name}" value="${i}" data-key="${f.key}" data-num ${v != null && +v === i ? 'checked' : ''} ${dis}>${i}</label>`).join('')}<span class="lo">No pain</span><span class="hi">Worst</span></div>`;
        case 'range': return `<div class="fr-range"><input type="range" ${attrs} min="${f.min ?? 0}" max="${f.max ?? 100}" step="${f.step || 1}" value="${v ?? f.min ?? 0}"><output>${v ?? '–'}${f.unit ? ' ' + esc(f.unit) : ''}</output></div>`;
        case 'calc': return `<output class="fr-calc" id="${name}">${v == null || v === '' ? '<span class="muted">Fills in by itself</span>' : esc(typeof v === 'boolean' ? (v ? 'Yes' : 'No') : K.text(v))}${f.unit && v != null && v !== '' ? ` <small>${esc(f.unit)}</small>` : ''}</output>`;
        case 'signature': return `<div class="fr-sig ${v ? 'signed' : ''}">${v ? `<img src="${esc(v)}" alt="Signature">` : `<canvas data-sig="${f.key}" ${dis ? 'aria-disabled="true"' : ''} aria-label="Sign here with a finger, pen or mouse"></canvas>`}
          ${editable(f) ? `<button type="button" class="btn btn-sm btn-ghost" data-sig-clear="${f.key}"><i class="bi bi-eraser"></i>${v ? 'Sign again' : 'Clear'}</button>` : ''}<span class="fr-sig-line">Sign above the line</span></div>`;
        case 'table': {
          const rows = v || [];
          return `<div class="fr-table"><table><thead><tr>${f.columns.map(c => `<th>${esc(c.label)}</th>`).join('')}<th></th></tr></thead><tbody>${rows.map((r, i) => `<tr>${f.columns.map(c => `<td>${cell(f, c, r[c.key], i, dis)}</td>`).join('')}
            <td>${editable(f) ? `<button type="button" class="btn btn-sm btn-ghost" data-row-del="${f.key}:${i}" aria-label="Remove row"><i class="bi bi-x-lg"></i></button>` : ''}</td></tr>`).join('') || `<tr><td colspan="${f.columns.length + 1}" class="muted small">No rows yet.</td></tr>`}</tbody></table>
            ${editable(f) && rows.length < (f.max_rows || 20) ? `<button type="button" class="btn btn-sm btn-ghost" data-row-add="${f.key}"><i class="bi bi-plus-lg"></i>Add a row</button>` : ''}</div>`;
        }
        case 'bodymap': return `<div class="fr-body" data-body="${f.key}">${bodySvg(f, 'front', v || [], dis)}${bodySvg(f, 'back', v || [], dis)}<div class="fr-body-list">${(v || []).map(x => `<span class="tag">${esc(regionName(x))}</span>`).join('') || '<span class="muted small">Tap the body to mark areas.</span>'}</div></div>`;
        case 'vitals': {
          const o = v || {}, n = window.MFBedside ? MFBedside.news2(o) : null;
          const inp = (k, l, u, a) => `<label>${l}<span class="fr-unit"><input class="form-control form-control-sm" type="number" inputmode="decimal" data-key="${f.key}" data-sub="${k}" value="${o[k] ?? ''}" ${a} ${dis}><span>${u}</span></span></label>`;
          return `<div class="fr-vitals">${inp('heart_rate', 'Heart rate', '/min', 'min="20" max="250"')}${inp('systolic', 'BP upper', 'mmHg', 'min="40" max="280"')}${inp('diastolic', 'BP lower', 'mmHg', 'min="20" max="180"')}
            ${inp('resp_rate', 'Breathing', '/min', 'min="3" max="70"')}${inp('spo2', 'SpO₂', '%', 'min="50" max="100"')}${inp('temperature_c', 'Temp', '°C', 'min="30" max="43" step="0.1"')}
            <label>Alertness<select class="form-select form-select-sm" data-key="${f.key}" data-sub="consciousness" ${dis}>${[['A', 'Alert'], ['C', 'New confusion'], ['V', 'Voice'], ['P', 'Pain'], ['U', 'Unresponsive']].map(([k, l]) => `<option value="${k}" ${(o.consciousness || 'A') === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
            <label class="fr-check sm"><input type="checkbox" data-key="${f.key}" data-sub="on_oxygen" ${o.on_oxygen ? 'checked' : ''} ${dis}><span>On oxygen</span></label>
            <div class="fr-news ${n ? 'news-' + n.risk : ''}">${n ? `<b>${n.total}</b>NEWS2` : 'NEWS2 —'}</div></div>`;
        }
        case 'gcs': {
          const o = v || {}, tot = o.eye && o.verbal && o.motor ? +o.eye + +o.verbal + +o.motor : null;
          const sel = (k, l, arr) => `<label>${l}<select class="form-select form-select-sm" data-key="${f.key}" data-sub="${k}" data-num ${dis}><option value="">–</option>${arr.map((t, i) => `<option value="${i + 1}" ${+o[k] === i + 1 ? 'selected' : ''}>${i + 1} · ${t}</option>`).join('')}</select></label>`;
          return `<div class="fr-gcs">${sel('eye', 'Eyes', ['None', 'To pain', 'To voice', 'Spontaneous'])}${sel('verbal', 'Speech', ['None', 'Sounds', 'Words', 'Confused', 'Orientated'])}${sel('motor', 'Movement', ['None', 'Extends', 'Abnormal flexion', 'Withdraws', 'Localises', 'Obeys'])}
            <div class="fr-news ${tot == null ? '' : tot <= 8 ? 'news-high' : tot <= 12 ? 'news-medium' : 'news-low'}">${tot == null ? 'GCS —' : `<b>${tot}</b>GCS`}</div></div>`;
        }
      }
      return '';
    }
    function cell(f, c, v, i, dis) {
      const a = `data-key="${f.key}" data-row="${i}" data-col="${c.key}" ${dis} aria-label="${esc(c.label)} row ${i + 1}"`;
      if (c.type === 'number') return `<input class="form-control form-control-sm" type="number" ${a} value="${v ?? ''}">`;
      if (c.type === 'date') return `<input class="form-control form-control-sm" type="date" ${a} value="${esc(v)}">`;
      if (c.type === 'checkbox') return `<input type="checkbox" ${a} ${v ? 'checked' : ''}>`;
      if (c.type === 'select') return `<select class="form-select form-select-sm" ${a}><option value=""></option>${c.options.map(o => `<option ${o === v ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
      return `<input class="form-control form-control-sm" ${a} value="${esc(v)}">`;
    }
    const regionName = x => { const [r, s, vw] = x.split('|'); return `${s ? s[0].toUpperCase() + s.slice(1) + ' ' : ''}${(window.MFInjury ? MFInjury.LABEL[r] : r).toLowerCase()}${vw ? ` (${vw})` : ''}`; };
    function bodySvg(f, view, sel, dis) {
      if (!window.MFInjury) return '';
      const {SHAPE, IN_VIEW, PAIRED, sideOf} = MFInjury;
      let s = '';
      for (const half of ['L', 'R']) {
        s += `<g ${half === 'R' ? 'transform="matrix(-1 0 0 1 220 0)"' : ''}>`;
        for (const r of IN_VIEW[view]) {
          if (!PAIRED.has(r) && half === 'R') continue;
          const side = PAIRED.has(r) ? sideOf(view, half) : '', key = `${r}|${side}|${view}`;
          s += `<path d="${SHAPE[r]}" data-region="${key}" class="${sel.includes(key) ? 'on' : ''}" ${dis ? '' : 'tabindex="0" role="button"'} aria-pressed="${sel.includes(key)}"><title>${esc(regionName(key))}</title></path>`;
        }
        s += '</g>';
      }
      return `<svg viewBox="0 0 220 476" class="fr-fig" aria-label="${view} of body">${s}</svg>`;
    }

    function fieldHtml(f) {
      const hidden = state.hidden.has(f.key), req = state.required.has(f.key), err = touched.has(f.key) || touched.has('*') ? errors[f.key] : '';
      const w = `style="--span:${W[f.width] || 6}"`;
      if (f.type === 'heading') return `<h3 class="fr-h" ${w} ${hidden ? 'hidden' : ''}>${esc(f.label)}</h3>`;
      if (f.type === 'paragraph') return `<p class="fr-p" ${w} ${hidden ? 'hidden' : ''}>${esc(f.text || f.label).replace(/\n/g, '<br>')}</p>`;
      if (f.type === 'divider') return `<hr class="fr-hr" ${w}>`;
      if (f.type === 'patient') { const p = boot.patient || {}; return `<div class="fr-patient" ${w}><span class="avatar">${esc((p.name || '?').split(' ').map(x => x[0]).join('').slice(0, 2))}</span><div><b>${esc(p.name || 'Patient')}</b><div class="small muted">${esc(p.mrn || '')}${p.age != null ? ` · ${p.age} yrs` : ''}${p.sex ? ` · ${esc(p.sex)}` : ''}</div>${p.allergies && p.allergies.length ? `<div class="fr-allergy"><i class="bi bi-exclamation-triangle-fill"></i>Allergies: ${p.allergies.map(esc).join(', ')}</div>` : ''}</div></div>`; }
      const later = (f.filled_by || '') !== scope;
      const name = `${id}-${f.key}`;
      return `<div class="fr-field t-${f.type}${err ? ' has-err' : ''}${later ? ' later' : ''}" data-field="${f.key}" ${w} ${hidden ? 'hidden' : ''}>
        ${f.type === 'checkbox' ? '' : `<label class="fr-label" id="${name}-l" for="${name}">${esc(f.label)}${req ? '<i class="req" aria-label="required">*</i>' : ''}${later ? `<span class="fr-later">${scope ? 'filled in earlier' : 'filled in at a later step'}</span>` : ''}</label>`}
        ${control(f)}
        ${f.help ? `<div class="fr-help">${esc(f.help)}</div>` : ''}<div class="fr-msg" id="${name}-msg">${err ? esc(err) : ''}</div></div>`;
    }

    /* ---------------------------------------------------------------- render */
    function render(focusKey) {
      state = K.resolve(schema, values);
      values = state.values;
      errors = {...K.validate(schema, values, state.hidden, state.required, scope), ...serverOnly()};
      const visible = i => fields.some(f => onPage(f, i) && !state.hidden.has(f.key));
      $('.fr-steps').innerHTML = pages.length > 1 ? pages.map((p, i) => `<button type="button" role="tab" aria-selected="${i === page}" data-page="${i}" class="${pageErrors(i) ? 'err' : pageDone(i) ? 'done' : ''}" ${visible(i) ? '' : 'hidden'}><span>${i + 1}</span>${esc(p.title)}</button>`).join('') : '';
      $('.fr-page').innerHTML = `<div class="fr-grid">${fields.filter(f => onPage(f, page)).map(fieldHtml).join('')}</div>`;
      const need = fields.filter(f => state.required.has(f.key) && editable(f)), done = need.filter(f => K.filled(values[f.key]) && values[f.key] !== false && !errors[f.key]);
      const pct = need.length ? Math.round(done.length * 100 / need.length) : 100;
      $('.fr-progress i').style.width = pct + '%';
      $('.fr-progress span').textContent = need.length ? `${done.length} of ${need.length} required answers` : 'No required answers';
      const last = nextPage(1) == null;
      $('.fr-prev').hidden = nextPage(-1) == null;
      $('.fr-next').hidden = last;
      $('.fr-submit').hidden = !last || opts.readonly;
      wire();
      if (focusKey) { const el = host.querySelector(`[data-key="${focusKey}"]`); el?.focus(); }
      opts.onChange && opts.onChange(values, errors);
    }
    let server = {...(boot.errors || {})};
    const serverOnly = () => Object.fromEntries(Object.entries(server).filter(([k]) => k === '__all__'));
    const pageErrors = i => fields.some(f => onPage(f, i) && errors[f.key] && (touched.has(f.key) || touched.has('*')));
    const pageDone = i => fields.filter(f => onPage(f, i) && state.required.has(f.key) && editable(f)).every(f => K.filled(values[f.key]) && !errors[f.key]);
    const nextPage = d => { for (let i = page + d; i >= 0 && i < pages.length; i += d) if (fields.some(f => onPage(f, i) && !state.hidden.has(f.key))) return i; return null; };

    function wire() {
      host.querySelectorAll('[data-sig]').forEach(c => pad(c, editable(fields.find(f => f.key === c.dataset.sig))));
    }
    // Live updates without a full redraw while typing (keeps the cursor), full redraw for choices.
    function soft() {
      const before = state.hidden;
      state = K.resolve(schema, values); values = state.values;
      if (before.size !== state.hidden.size || [...before].some(k => !state.hidden.has(k))) { render(); return; }
      errors = {...K.validate(schema, values, state.hidden, state.required, scope), ...serverOnly()};
      for (const f of fields) {
        const box = host.querySelector(`[data-field="${f.key}"]`);
        if (!box) continue;
        if (f.type === 'calc') { box.querySelector('.fr-calc').outerHTML = control(f); }
        if (f.type === 'vitals' || f.type === 'gcs') { const nb = box.querySelector('.fr-news'), tmp = document.createElement('div'); tmp.innerHTML = control(f); nb.replaceWith(tmp.querySelector('.fr-news')); }
        const req = box.querySelector('.req'); if (!!req !== state.required.has(f.key)) { render(); return; }
        const m = box.querySelector('.fr-msg'), e = touched.has(f.key) || touched.has('*') ? errors[f.key] || '' : '';
        if (m && m.textContent !== e) { m.textContent = e; box.classList.toggle('has-err', !!e); }
      }
      const need = fields.filter(f => state.required.has(f.key) && editable(f)), done = need.filter(f => K.filled(values[f.key]) && values[f.key] !== false && !errors[f.key]);
      $('.fr-progress i').style.width = (need.length ? Math.round(done.length * 100 / need.length) : 100) + '%';
      $('.fr-progress span').textContent = need.length ? `${done.length} of ${need.length} required answers` : 'No required answers';
      opts.onChange && opts.onChange(values, errors);
    }

    host.addEventListener('input', ev => {
      const el = ev.target, key = el.dataset.key; if (!key) return;
      const f = fields.find(x => x.key === key); if (!f || !editable(f)) return;
      if (el.dataset.row !== undefined) { const rows = values[key] = [...(values[key] || [])]; rows[+el.dataset.row] = {...rows[+el.dataset.row], [el.dataset.col]: el.type === 'checkbox' ? el.checked : el.type === 'number' ? (el.value === '' ? null : +el.value) : el.value}; }
      else if (el.dataset.sub) { const o = {...(values[key] || {})}; o[el.dataset.sub] = el.type === 'checkbox' ? el.checked : el.dataset.num !== undefined || el.type === 'number' ? (el.value === '' ? null : +el.value) : el.value; values[key] = o; }
      else if (el.dataset.multi !== undefined) { const set = new Set(values[key] || []); el.checked ? set.add(el.value) : set.delete(el.value); values[key] = f.options.filter(o => set.has(o)); }
      else if (el.type === 'checkbox') values[key] = el.checked;
      else if (el.type === 'number' || el.type === 'range' || el.dataset.num !== undefined) values[key] = el.value === '' ? null : +el.value;
      else values[key] = el.value;
      if (el.type === 'range') el.nextElementSibling.textContent = `${el.value}${f.unit ? ' ' + f.unit : ''}`;
      touched.add(key); delete server[key];
      if (el.type === 'radio' || el.type === 'checkbox' || el.tagName === 'SELECT') { render(); } else soft();
      scheduleDraft();
    });
    host.addEventListener('focusout', ev => { const k = ev.target.dataset && ev.target.dataset.key; if (k && !touched.has(k)) { touched.add(k); soft(); } });
    host.addEventListener('click', ev => {
      const t = ev.target.closest('[data-page],[data-row-add],[data-row-del],[data-sig-clear],[data-region]');
      if (!t) return;
      if (t.dataset.page) { page = +t.dataset.page; render(); host.scrollIntoView({block: 'start', behavior: 'smooth'}); return; }
      if (t.dataset.rowAdd) { const k = t.dataset.rowAdd; values[k] = [...(values[k] || []), {}]; render(); }
      if (t.dataset.rowDel) { const [k, i] = t.dataset.rowDel.split(':'); values[k] = (values[k] || []).filter((_, j) => j !== +i); render(); }
      if (t.dataset.sigClear) { values[t.dataset.sigClear] = ''; render(); }
      if (t.dataset.region) {
        const box = t.closest('[data-body]'), k = box.dataset.body, f = fields.find(x => x.key === k);
        if (!editable(f)) return;
        const set = new Set(values[k] || []); set.has(t.dataset.region) ? set.delete(t.dataset.region) : set.add(t.dataset.region);
        values[k] = f.multiple === false ? (set.has(t.dataset.region) ? [t.dataset.region] : []) : [...set];
        touched.add(k); render();
      }
      scheduleDraft();
    });
    host.addEventListener('keydown', ev => { if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.dataset && ev.target.dataset.region) { ev.preventDefault(); ev.target.dispatchEvent(new MouseEvent('click', {bubbles: true})); } });
    $('.fr-prev').onclick = () => { const p = nextPage(-1); if (p != null) { page = p; render(); host.scrollIntoView({block: 'start'}); } };
    $('.fr-next').onclick = () => {
      fields.filter(f => onPage(f, page)).forEach(f => touched.add(f.key));
      render();
      const bad = fields.find(f => onPage(f, page) && errors[f.key]);
      if (bad) { host.querySelector(`[data-field="${bad.key}"] [data-key], [data-field="${bad.key}"] canvas`)?.focus(); return; }
      const p = nextPage(1); if (p != null) { page = p; render(); host.scrollIntoView({block: 'start'}); }
    };
    $('.fr-submit').onclick = async () => {
      if (busy) return;
      touched.add('*'); render();
      const bad = fields.find(f => errors[f.key]);
      if (bad) {
        const i = pages.findIndex((p, j) => onPage(bad, j)); if (i !== page) { page = i; render(); }
        showErrors(['Some answers need attention before you can submit.']);
        host.querySelector(`[data-field="${bad.key}"]`)?.scrollIntoView({block: 'center', behavior: 'smooth'});
        return;
      }
      if (opts.preview) { showErrors([]); opts.preview(values); return; }
      busy = true; $('.fr-submit').disabled = true; $('.fr-submit').classList.add('busy');
      try {
        const r = await opts.post(values);
        if (r.ok) { clearTimeout(draftTimer); window.removeEventListener('beforeunload', guard); if (r.url) location.href = r.url; return; }
        server = r.errors || {}; errors = {...errors, ...server}; touched.add('*');
        render(); showErrors([r.error || server.__all__ || 'Some answers need attention.'].filter(Boolean));
        Object.entries(server).forEach(([k, m]) => { const box = host.querySelector(`[data-field="${k}"] .fr-msg`); if (box) { box.textContent = m; box.parentNode.classList.add('has-err'); } });
      } catch (e) { showErrors([e.message || 'Could not reach the server. Your answers are still here; try again.']); }
      busy = false; $('.fr-submit').disabled = false; $('.fr-submit').classList.remove('busy');
    };
    function showErrors(list) { const b = $('.fr-errors'); b.hidden = !list.length; b.innerHTML = list.map(esc).join('<br>'); }

    /* ---------------------------------------------------------------- drafts */
    const guard = ev => { if (dirty) { ev.preventDefault(); ev.returnValue = ''; } };
    let dirty = false;
    window.addEventListener('beforeunload', guard);
    function scheduleDraft() {
      dirty = true;
      if (!boot.draft_url) return;
      clearTimeout(draftTimer);
      $('.fr-draft').textContent = 'Saving draft…';
      draftTimer = setTimeout(async () => {
        try {
          const r = await fetch(boot.draft_url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()}, credentials: 'same-origin', body: JSON.stringify({values, page})});
          $('.fr-draft').textContent = r.ok ? `Draft saved ${new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}` : 'Draft not saved';
          if (r.ok) dirty = false;
        } catch (e) { $('.fr-draft').textContent = 'Offline: draft not saved'; }
      }, 1200);
    }
    if (boot.draft_saved) $('.fr-draft').innerHTML = `Draft from ${new Date(boot.draft_saved).toLocaleString([], {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'})} restored · <button type="button" class="linkish fr-discard">Start again</button>`;
    host.addEventListener('click', async ev => {
      if (!ev.target.classList.contains('fr-discard')) return;
      await fetch(boot.draft_url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()}, credentials: 'same-origin', body: JSON.stringify({discard: true})});
      values = {}; touched = new Set(); page = 0; $('.fr-draft').textContent = ''; render();
    });

    /* ---------------------------------------------------------------- signature pad */
    function pad(c, on) {
      const ratio = window.devicePixelRatio || 1, r = c.getBoundingClientRect();
      c.width = r.width * ratio; c.height = r.height * ratio;
      const g = c.getContext('2d'); g.scale(ratio, ratio); g.lineCap = g.lineJoin = 'round'; g.strokeStyle = '#0F2C3F';
      if (!on) return;
      let down = false, last = null, lw = 2.4, inked = false;
      const pt = e => { const b = c.getBoundingClientRect(); return {x: e.clientX - b.left, y: e.clientY - b.top, t: performance.now()}; };
      c.addEventListener('pointerdown', e => { down = true; last = pt(e); c.setPointerCapture(e.pointerId); e.preventDefault(); });
      c.addEventListener('pointermove', e => {
        if (!down) return; const p = pt(e), d = Math.hypot(p.x - last.x, p.y - last.y), v = d / Math.max(1, p.t - last.t);
        lw = lw * .7 + Math.max(1.2, Math.min(3.6, 3.6 - v * 1.6)) * .3;          // faster strokes are thinner, like ink
        g.lineWidth = lw; g.beginPath(); g.moveTo(last.x, last.y); g.quadraticCurveTo(last.x, last.y, (last.x + p.x) / 2, (last.y + p.y) / 2); g.lineTo(p.x, p.y); g.stroke();
        last = p; inked = true;
      });
      const up = () => { if (!down) return; down = false; if (inked) { values[c.dataset.sig] = c.toDataURL('image/png'); touched.add(c.dataset.sig); soft(); scheduleDraft(); } };
      c.addEventListener('pointerup', up); c.addEventListener('pointercancel', up);
    }

    render();
    return {get values() { return values; }, render, setSchema(s) { Object.assign(schema, s); render(); }};
  }

  // Default poster for the fill page: JSON to submit_url.
  async function postJSON(url, body) {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf(), Accept: 'application/json'}, credentials: 'same-origin', body: JSON.stringify(body)});
    const d = await r.json().catch(() => ({ok: false, error: `The server answered ${r.status}.`}));
    return d;
  }
  window.MFFormRuntime = {mount, postJSON};
})();
