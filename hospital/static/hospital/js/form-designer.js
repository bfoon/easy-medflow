/* Form designer: palette → pages of fields → inspector (settings, logic, formula) with live preview, undo/redo,
   keyboard shortcuts and a running list of problems. Saves the same schema the server checks (formkit.clean_schema). */
(() => {
  'use strict';
  const boot = JSON.parse(document.getElementById('designer-boot').textContent);
  const K = window.MFForm, cat = boot.catalogue;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const $ = s => document.querySelector(s);
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;

  const GROUPS = [
    ['Basic', 'text textarea number date time email phone'],
    ['Choices', 'select radio checkboxes checkbox yesno rating range'],
    ['Clinical', 'vitals gcs bodymap signature patient'],
    ['Smart', 'calc table'],
    ['Layout', 'heading paragraph divider'],
  ];
  const ICON = {text: 'bi-input-cursor', textarea: 'bi-text-paragraph', number: 'bi-123', date: 'bi-calendar-event', time: 'bi-clock', email: 'bi-envelope',
    phone: 'bi-telephone', select: 'bi-menu-button-wide', radio: 'bi-ui-radios', checkboxes: 'bi-ui-checks', checkbox: 'bi-check2-square', yesno: 'bi-toggle-on',
    rating: 'bi-emoji-neutral', range: 'bi-sliders', calc: 'bi-calculator', table: 'bi-table', signature: 'bi-pen', bodymap: 'bi-person-bounding-box',
    vitals: 'bi-heart-pulse', gcs: 'bi-person-exclamation', heading: 'bi-type-h2', paragraph: 'bi-paragraph', divider: 'bi-hr', patient: 'bi-person-vcard'};

  // ---------------------------------------------------------------- state + history
  let S = normalise(structuredClone(boot.schema || {fields: []}));
  let meta = {name: boot.name || '', slug: boot.slug || '', description: boot.description || '', published: boot.published !== false};
  let sel = null, page = 0, tab = 'field', past = [], future = [], dirty = false, previewVals = {};
  function normalise(s) {
    s.pages = s.pages && s.pages.length ? s.pages : [{id: 'p1', title: 'Form'}];
    s.settings = s.settings || {submit_label: 'Submit'};
    s.fields = (s.fields || []).map((f, i) => ({...f, key: f.key || `_${f.type}${i}`, page: f.page || s.pages[0].id}));
    return s;
  }
  const snapshot = () => JSON.stringify({S, meta});
  function commit(fn) { past.push(snapshot()); if (past.length > 80) past.shift(); future = []; fn(); dirty = true; draw(); }
  function undo() { if (!past.length) return; future.push(snapshot()); ({S, meta} = JSON.parse(past.pop())); dirty = true; draw(); }
  function redo() { if (!future.length) return; past.push(snapshot()); ({S, meta} = JSON.parse(future.pop())); dirty = true; draw(); }
  const isInput = t => cat.input_types.includes(t);
  const F = () => S.fields.find(f => f.key === sel);
  const pageId = () => S.pages[page].id;

  function newKey(label, type) {
    let base = String(label || type).toLowerCase().normalize('NFKD').replace(/[^\w\s]/g, '').trim().replace(/\s+/g, '_').replace(/^[^a-z]+/, '').slice(0, 30) || type;
    let k = base, n = 2;
    while (S.fields.some(f => f.key === k)) k = `${base}_${n++}`;
    return k;
  }
  function blank(type) {
    const label = {heading: 'Section', paragraph: '', divider: '', patient: 'Patient', vitals: 'Vital signs', gcs: 'Glasgow Coma Scale', bodymap: 'Affected areas',
      signature: 'Signature', calc: 'Result', table: 'Items', rating: 'Pain score', yesno: 'Question', checkbox: 'I confirm'}[type] ?? cat.types[type];
    const f = {_new: true, type, label, page: pageId(), width: 'full', key: isInput(type) ? newKey(label, type) : `_${type}${Date.now().toString(36)}`};
    if (['select', 'radio', 'checkboxes'].includes(type)) f.options = ['Option 1', 'Option 2'];
    if (type === 'paragraph') f.text = 'Write instructions or information here.';
    if (type === 'calc') { f.formula = ''; f.decimals = 2; }
    if (type === 'table') { f.columns = [{key: 'item', label: 'Item', type: 'text'}, {key: 'qty', label: 'Quantity', type: 'number'}]; f.max_rows = 20; }
    if (type === 'range') { f.min = 0; f.max = 100; }
    return f;
  }
  function add(type, at) {
    commit(() => {
      const f = blank(type);
      const idx = at ?? (sel ? S.fields.findIndex(x => x.key === sel) + 1 : S.fields.length);
      S.fields.splice(idx, 0, f);
      sel = f.key; tab = 'field';
    });
    setTimeout(() => $('#fd-insp [data-p="label"]')?.select(), 0);
  }

  // ---------------------------------------------------------------- problems (mirrors the server's checks)
  function problems() {
    const out = [], keys = new Set(S.fields.filter(f => isInput(f.type)).map(f => f.key)), seen = new Set();
    if (!meta.name.trim()) out.push({msg: 'Give the form a name.'});
    if (!S.fields.length) out.push({msg: 'Add at least one field.'});
    const treeKeys = t => !t ? [] : 'op' in t ? [t.field.split('.')[0], ...(t.ref ? [t.ref.split('.')[0]] : [])] : (t.all || t.any || []).flatMap(treeKeys);
    for (const f of S.fields) {
      const name = f.label || cat.types[f.type];
      if (isInput(f.type)) {
        if (!/^[a-z][a-z0-9_]{0,39}$/.test(f.key)) out.push({key: f.key, msg: `“${name}”: the key must start with a letter and use lowercase letters, digits and _.`});
        if (seen.has(f.key)) out.push({key: f.key, msg: `“${name}”: another field already uses the key ${f.key}.`});
        seen.add(f.key);
        if (!f.label) out.push({key: f.key, msg: `A ${cat.types[f.type].toLowerCase()} field has no label.`});
      }
      if (['select', 'radio', 'checkboxes'].includes(f.type)) {
        const o = (f.options || []).map(x => x.trim()).filter(Boolean);
        if (!o.length || new Set(o).size !== o.length) out.push({key: f.key, msg: `“${name}” needs options without repeats.`});
      }
      if (f.type === 'calc') { const t = K.tryFormula(f.formula || '', {}); if (!t.ok) out.push({key: f.key, msg: `“${name}”: ${t.error}`}); else t.vars.filter(v => !keys.has(v)).forEach(v => out.push({key: f.key, msg: `“${name}” uses ${v}, which is not a field.`})); }
      for (const k of ['show_if', 'require_if']) treeKeys(f[k]).filter(v => !keys.has(v)).forEach(v => out.push({key: f.key, msg: `“${name}”: a rule refers to ${v || 'nothing'}, which is not a field.`}));
      if (f.type === 'table' && new Set((f.columns || []).map(c => c.key)).size !== (f.columns || []).length) out.push({key: f.key, msg: `Table “${name}” has two columns with the same key.`});
      if (f.min != null && f.max != null && +f.min > +f.max) out.push({key: f.key, msg: `“${name}”: minimum is above maximum.`});
    }
    // loops between calculated fields
    const calc = Object.fromEntries(S.fields.filter(f => f.type === 'calc').map(f => { const t = K.tryFormula(f.formula || '', {}); return [f.key, t.ok ? t.vars : []]; }));
    const stack = new Set(), done = new Set();
    const visit = k => { if (stack.has(k)) { out.push({key: k, msg: `“${k}” depends on itself through other calculations.`}); return; } if (done.has(k) || !calc[k]) return; stack.add(k); calc[k].forEach(visit); stack.delete(k); done.add(k); };
    Object.keys(calc).forEach(visit);
    return out;
  }

  // ---------------------------------------------------------------- drawing
  function draw() {
    $('#fd-name').value = meta.name; $('#fd-slug').value = meta.slug; $('#fd-desc').value = meta.description; $('#fd-pub').checked = meta.published;
    page = Math.min(page, S.pages.length - 1);
    drawPages(); drawCanvas(); drawInspector(); drawProblems();
    $('#fd-undo').disabled = !past.length; $('#fd-redo').disabled = !future.length;
    $('#fd-dirty').hidden = !dirty;
    if (!$('#fd-preview').hidden) drawPreview();
  }
  function drawPages() {
    $('#fd-pages').innerHTML = S.pages.map((p, i) => `<button type="button" class="fd-page ${i === page ? 'on' : ''}" data-pg="${i}" draggable="true">${esc(p.title)} <small>${S.fields.filter(f => f.page === p.id).length}</small></button>`).join('')
      + `<button type="button" class="fd-page add" id="fd-addpage" title="Add a page"><i class="bi bi-plus-lg"></i>Page</button>`;
  }
  function badge(f) {
    const b = [];
    if (f.required) b.push('<span class="fb req">Required</span>');
    if (f.show_if) b.push('<span class="fb logic"><i class="bi bi-eye"></i>Shown when…</span>');
    if (f.require_if) b.push('<span class="fb logic"><i class="bi bi-asterisk"></i>Required when…</span>');
    if (f.filled_by) b.push(`<span class="fb step"><i class="bi bi-diagram-3"></i>Step ${esc(f.filled_by)}</span>`);
    if (f.prefill) b.push(`<span class="fb"><i class="bi bi-magic"></i>${esc(cat.prefill[f.prefill])}</span>`);
    if (f.type === 'calc') b.push(`<code class="fb code">${esc(f.formula || 'no formula')}</code>`);
    return b.join('');
  }
  function sample(f) {
    switch (f.type) {
      case 'heading': return `<h3>${esc(f.label)}</h3>`;
      case 'paragraph': return `<p class="muted mb-0">${esc(f.text)}</p>`;
      case 'divider': return '<hr class="m-0">';
      case 'select': return `<div class="fd-mock sel">${esc((f.options || [])[0] || 'Choose…')}<i class="bi bi-chevron-down"></i></div>`;
      case 'radio': case 'checkboxes': case 'yesno': return `<div class="fd-chips">${(f.type === 'yesno' ? ['Yes', 'No'] : f.options || []).slice(0, 6).map(o => `<span>${esc(o)}</span>`).join('')}</div>`;
      case 'checkbox': return `<div class="fd-mock chk"><i class="bi bi-square"></i>${esc(f.label)}</div>`;
      case 'rating': return `<div class="fd-chips rating">${[...Array(11)].map((_, i) => `<span style="--h:${120 - i * 12}">${i}</span>`).join('')}</div>`;
      case 'table': return `<div class="fd-mock tbl">${(f.columns || []).map(c => `<span>${esc(c.label)}</span>`).join('')}</div>`;
      case 'signature': return '<div class="fd-mock sig"><i class="bi bi-pen"></i>Sign here</div>';
      case 'vitals': return '<div class="fd-chips">' + ['HR', 'BP', 'RR', 'SpO₂', 'Temp', 'ACVPU', 'NEWS2'].map(x => `<span>${x}</span>`).join('') + '</div>';
      case 'gcs': return '<div class="fd-chips"><span>E 1–4</span><span>V 1–5</span><span>M 1–6</span><span>= GCS</span></div>';
      case 'bodymap': return '<div class="fd-mock"><i class="bi bi-person-bounding-box"></i>Tap areas on a front and back figure</div>';
      case 'patient': return '<div class="fd-mock"><i class="bi bi-person-vcard"></i>Name, number, age and allergies of the patient</div>';
      case 'calc': return `<div class="fd-mock calc"><i class="bi bi-calculator"></i>${esc(f.unit || '')} calculated</div>`;
      case 'range': return `<div class="fd-mock"><input type="range" disabled style="width:100%"></div>`;
      default: return `<div class="fd-mock">${esc(f.placeholder || '')}</div>`;
    }
  }
  function drawCanvas() {
    const list = S.fields.filter(f => f.page === pageId());
    const probs = new Set(problems().map(p => p.key));
    $('#fd-canvas').innerHTML = (list.length ? '' : `<div class="fd-empty"><i class="bi bi-ui-checks-grid"></i><b>This page is empty</b><span>Pick a field type on the left, or drag one here.</span></div>`) +
      list.map(f => `<div class="fd-card w-${f.width || 'full'} ${f.key === sel ? 'on' : ''} ${probs.has(f.key) ? 'bad' : ''}" data-key="${esc(f.key)}" tabindex="0" draggable="true" role="button" aria-label="${esc(f.label || cat.types[f.type])}, ${esc(cat.types[f.type])}">
        <div class="fd-card-h"><i class="bi ${ICON[f.type]}"></i><b>${esc(f.label || (f.type === 'paragraph' ? 'Text' : cat.types[f.type]))}</b>${f.required ? '<i class="req">*</i>' : ''}<span class="fd-type">${esc(cat.types[f.type])}${isInput(f.type) ? ` · <code>${esc(f.key)}</code>` : ''}</span>
          <span class="fd-tools"><button type="button" data-act="up" aria-label="Move up"><i class="bi bi-arrow-up"></i></button><button type="button" data-act="down" aria-label="Move down"><i class="bi bi-arrow-down"></i></button><button type="button" data-act="dup" aria-label="Duplicate"><i class="bi bi-copy"></i></button><button type="button" data-act="del" aria-label="Delete"><i class="bi bi-trash"></i></button></span></div>
        ${sample(f)}<div class="fd-badges">${badge(f)}</div></div>`).join('');
  }

  // ----- inspector
  const inp = (p, label, v, extra = '') => `<label>${label}<input class="form-control form-control-sm" data-p="${p}" value="${esc(v ?? '')}" ${extra}></label>`;
  const chk = (p, label, v) => `<label class="fd-chk"><input type="checkbox" data-p="${p}" ${v ? 'checked' : ''}>${label}</label>`;
  const selBox = (p, label, opts, v) => `<label>${label}<select class="form-select form-select-sm" data-p="${p}">${opts.map(([k, l]) => `<option value="${esc(k)}" ${String(k) === String(v ?? '') ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></label>`;
  function drawInspector() {
    const f = F(), box = $('#fd-insp');
    if (!f) {
      box.innerHTML = `<h3>Form settings</h3>${inp('s.submit_label', 'Submit button text', S.settings.submit_label)}
        <label>Introduction (shown at the top)<textarea class="form-control form-control-sm" rows="3" data-p="s.intro">${esc(S.settings.intro || '')}</textarea></label>
        <h3 class="mt-3">Page</h3>${inp('pg.title', 'Page title', S.pages[page].title)}
        <div class="d-flex gap-2"><button type="button" class="btn btn-sm btn-ghost" data-pg-move="-1" ${page ? '' : 'disabled'}><i class="bi bi-arrow-left"></i>Move</button><button type="button" class="btn btn-sm btn-ghost" data-pg-move="1" ${page < S.pages.length - 1 ? '' : 'disabled'}>Move<i class="bi bi-arrow-right ms-1"></i></button>
        <button type="button" class="btn btn-sm btn-ghost ms-auto" id="fd-delpage" ${S.pages.length > 1 ? '' : 'disabled'}><i class="bi bi-trash"></i>Delete page</button></div>
        <p class="small muted mt-3">Select a field to change it. Shortcuts: Ctrl+Z undo, Ctrl+Shift+Z redo, Ctrl+D duplicate, Delete remove, Ctrl+S save.</p>`;
      return;
    }
    const tabs = ['field', 'logic'].concat(f.type === 'calc' ? ['formula'] : []);
    if (!tabs.includes(tab)) tab = 'field';
    let body = '';
    if (tab === 'field') {
      body += f.type === 'paragraph' ? `<label>Text<textarea class="form-control form-control-sm" rows="5" data-p="text">${esc(f.text)}</textarea></label>` : f.type === 'divider' ? '' : inp('label', f.type === 'heading' ? 'Heading' : 'Question / label', f.label);
      if (isInput(f.type)) body += inp('key', 'Key (used in rules and formulas)', f.key, 'spellcheck="false" pattern="[a-z][a-z0-9_]*"');
      if (!['divider'].includes(f.type)) body += selBox('width', 'Width', [['full', 'Full width'], ['half', 'Half'], ['third', 'One third']], f.width || 'full');
      if (S.pages.length > 1) body += selBox('page', 'Page', S.pages.map(p => [p.id, p.title]), f.page);
      if (isInput(f.type) && f.type !== 'calc') body += chk('required', 'Required', f.required) + inp('help', 'Help text', f.help);
      if (['text', 'textarea', 'email', 'phone', 'number'].includes(f.type)) body += inp('placeholder', 'Placeholder', f.placeholder);
      if (['number', 'range', 'calc'].includes(f.type)) body += inp('unit', 'Unit', f.unit, 'placeholder="kg, mL, mmHg…"');
      if (['number', 'range'].includes(f.type)) body += `<div class="fd-row3">${inp('min', 'Min', f.min, 'type="number"')}${inp('max', 'Max', f.max, 'type="number"')}${inp('step', 'Step', f.step, 'type="number"')}</div>`;
      if (f.type === 'date') body += `<div class="fd-row3">${inp('min', 'Earliest', f.min, 'placeholder="today or YYYY-MM-DD"')}${inp('max', 'Latest', f.max, 'placeholder="today or YYYY-MM-DD"')}</div>`;
      if (['text', 'textarea'].includes(f.type)) body += selBox('pattern', 'Format', [['', 'Any text'], ...Object.entries(cat.patterns).map(([k, v]) => [k, {digits: 'Digits only', letters: 'Letters only', gm_phone: 'Gambian phone', mrn: 'Patient number'}[k] || k])], f.pattern) + inp('maxlength', 'Maximum length', f.maxlength, 'type="number" min="1"');
      if (['select', 'radio', 'checkboxes'].includes(f.type)) body += `<label>Options, one per line<textarea class="form-control form-control-sm" rows="5" data-p="options">${esc((f.options || []).join('\n'))}</textarea></label>`;
      if (f.type === 'table') body += `<h4>Columns</h4>${(f.columns || []).map((c, i) => `<div class="fd-col"><input class="form-control form-control-sm" data-col="${i}" data-cp="label" value="${esc(c.label)}" aria-label="Column label"><select class="form-select form-select-sm" data-col="${i}" data-cp="type">${cat.table_column_types.map(t => `<option ${t === c.type ? 'selected' : ''}>${t}</option>`).join('')}</select><button type="button" class="btn btn-sm btn-ghost" data-col-del="${i}" aria-label="Remove column"><i class="bi bi-x-lg"></i></button>
          ${c.type === 'select' ? `<input class="form-control form-control-sm fd-colopts" data-col="${i}" data-cp="options" value="${esc((c.options || []).join(', '))}" placeholder="Options, separated by commas">` : ''}</div>`).join('')}
          <button type="button" class="btn btn-sm btn-ghost" id="fd-addcol"><i class="bi bi-plus-lg"></i>Column</button><div class="fd-row3">${inp('min_rows', 'Min rows', f.min_rows, 'type="number" min="0"')}${inp('max_rows', 'Max rows', f.max_rows, 'type="number" min="1"')}</div>`;
      if (isInput(f.type) && !['calc', 'signature', 'table', 'vitals', 'gcs', 'bodymap'].includes(f.type)) body += selBox('prefill', 'Fill in automatically from', [['', 'Nothing'], ...Object.entries(cat.prefill)], f.prefill) + (f.prefill ? chk('readonly', 'Cannot be changed', f.readonly) : '');
      if (isInput(f.type) && f.type !== 'calc') body += `<label>Filled in at<select class="form-select form-select-sm" data-p="filled_by"><option value="">When the form is started</option>${(boot.flow_steps || []).map(([id, l]) => `<option value="${esc(id)}" ${f.filled_by === id ? 'selected' : ''}>Flow step: ${esc(l)}</option>`).join('')}${f.filled_by && !(boot.flow_steps || []).some(([id]) => id === f.filled_by) ? `<option selected value="${esc(f.filled_by)}">Step ${esc(f.filled_by)}</option>` : ''}</select></label>${inp('filled_by', 'or step id', f.filled_by, 'placeholder="e.g. pharmacy"')}`;
      if (f.type === 'calc') body += `<div class="fd-row3">${inp('decimals', 'Decimals', f.decimals ?? 2, 'type="number" min="0" max="6"')}</div><button type="button" class="btn btn-sm btn-primary" data-tab="formula"><i class="bi bi-calculator"></i>Edit formula</button>`;
    } else if (tab === 'logic') {
      body += ruleBlock(f, 'show_if', 'Show this field only when', 'Always shown') + (isInput(f.type) && f.type !== 'calc' ? ruleBlock(f, 'require_if', 'Make it required when', f.required ? 'Always required (see Field)' : 'Never required') : '');
    } else {
      const fieldsList = S.fields.filter(x => isInput(x.type) && x.key !== f.key);
      const res = K.tryFormula(f.formula || '', resolvedPreview(), f.decimals ?? 2);
      body += `<label>Formula<textarea class="form-control fd-formula" rows="4" data-p="formula" spellcheck="false" placeholder="e.g. round(weight / (height/100)^2, 1)">${esc(f.formula)}</textarea></label>
        <div class="fd-result ${res.ok ? '' : 'bad'}">${res.ok ? `With the preview answers: <b>${esc(res.value === null ? 'empty' : K.text(res.value))}</b>` : esc(res.error)}</div>
        <h4>Fields</h4><div class="fd-insert">${fieldsList.map(x => `<button type="button" data-ins="${esc(x.key)}" title="${esc(x.label)}">${esc(x.key)}</button>`).join('') || '<span class="muted small">Add other fields first.</span>'}</div>
        <h4>Functions</h4><div class="fd-insert fn">${['round(x, 1)', 'if(test, a, b)', 'sum(a, b)', 'avg(a, b)', 'min(a, b)', 'max(a, b)', 'bmi(kg, cm)', 'age(date)', 'days_between(a, b)', 'today()', 'coalesce(a, b)', 'count(a, b)', 'sum(col(table, "column"))', 'concat(a, " ", b)']
          .map(x => `<button type="button" data-ins="${esc(x)}">${esc(x)}</button>`).join('')}</div>
        <p class="small muted">Operators: + − * / % ^ and comparisons == != &lt; &lt;= &gt; &gt;= with and / or / not. Text goes in "quotes". Inside vital signs: <code>obs.heart_rate</code>.</p>`;
    }
    box.innerHTML = `<div class="fd-insp-tabs">${tabs.map(t => `<button type="button" data-tab="${t}" class="${t === tab ? 'on' : ''}">${{field: 'Field', logic: 'Logic', formula: 'Formula'}[t]}${t === 'logic' && (f.show_if || f.require_if) ? ' •' : ''}</button>`).join('')}</div>${body}`;
  }
  function ruleBlock(f, prop, title, none) {
    const t = f[prop];
    const mode = t ? ('any' in t ? 'any' : 'all') : 'all', rules = t ? (t[mode] || []) : [];
    const fieldOpts = S.fields.filter(x => isInput(x.type) && x.key !== f.key);
    const subs = x => x.type === 'vitals' ? ['heart_rate', 'systolic', 'resp_rate', 'spo2', 'temperature_c', 'news2'].map(s => [`${x.key}.${s}`, `${x.label} › ${s.replace('_', ' ')}`]) : x.type === 'gcs' ? [[`${x.key}.total`, `${x.label} › total`]] : [];
    return `<div class="fd-rules" data-prop="${prop}"><h4>${title}</h4>${rules.length ? `<div class="fd-mode">Match <select class="form-select form-select-sm" data-rmode><option value="all" ${mode === 'all' ? 'selected' : ''}>all rules</option><option value="any" ${mode === 'any' ? 'selected' : ''}>any rule</option></select></div>` : `<p class="small muted">${none}.</p>`}
      ${rules.map((r, i) => { const src = fieldOpts.find(x => x.key === (r.field || '').split('.')[0]); return `<div class="fd-rule" data-i="${i}">
        <select class="form-select form-select-sm" data-r="field">${fieldOpts.map(x => `<option value="${esc(x.key)}" ${x.key === r.field ? 'selected' : ''}>${esc(x.label || x.key)}</option>${subs(x).map(([k, l]) => `<option value="${esc(k)}" ${k === r.field ? 'selected' : ''}>${esc(l)}</option>`).join('')}`).join('')}</select>
        <select class="form-select form-select-sm" data-r="op">${Object.entries(cat.ops).map(([k, l]) => `<option value="${k}" ${k === r.op ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>
        ${cat.unary.includes(r.op) ? '' : r.ref !== undefined ? `<select class="form-select form-select-sm" data-r="ref">${fieldOpts.map(x => `<option value="${esc(x.key)}" ${x.key === r.ref ? 'selected' : ''}>${esc(x.label || x.key)}</option>`).join('')}</select>`
          : src && src.options && ['eq', 'neq'].includes(r.op) ? `<select class="form-select form-select-sm" data-r="value">${src.options.map(o => `<option ${o === r.value ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`
          : src && src.type === 'yesno' && ['eq', 'neq'].includes(r.op) ? `<select class="form-select form-select-sm" data-r="value"><option value="yes" ${r.value === 'yes' ? 'selected' : ''}>Yes</option><option value="no" ${r.value === 'no' ? 'selected' : ''}>No</option></select>`
          : `<input class="form-control form-control-sm" data-r="value" value="${esc(r.value)}" placeholder="${cat.listy.includes(r.op) ? 'a, b, c' : r.op === 'within_days' ? 'days' : 'value'}">`}
        ${cat.range.includes(r.op) ? `<input class="form-control form-control-sm" data-r="value2" value="${esc(r.value2)}" placeholder="and">` : ''}
        <span class="fd-rule-tools">${!cat.unary.includes(r.op) && !cat.listy.includes(r.op) ? `<button type="button" data-rref title="${r.ref !== undefined ? 'Compare with a value' : 'Compare with another field'}"><i class="bi ${r.ref !== undefined ? 'bi-123' : 'bi-arrow-left-right'}"></i></button>` : ''}<button type="button" data-rdel aria-label="Remove rule"><i class="bi bi-x-lg"></i></button></span></div>`; }).join('')}
      <button type="button" class="btn btn-sm btn-ghost" data-radd ${fieldOpts.length ? '' : 'disabled'}><i class="bi bi-plus-lg"></i>Add a rule</button></div>`;
  }
  function drawProblems() {
    const p = problems(), box = $('#fd-problems');
    box.innerHTML = p.length ? `<b><i class="bi bi-exclamation-triangle-fill"></i>${p.length} thing${p.length > 1 ? 's' : ''} to fix before saving</b><ul>${p.slice(0, 8).map(x => `<li ${x.key ? `data-goto="${esc(x.key)}"` : ''}>${esc(x.msg)}</li>`).join('')}</ul>` : '<span><i class="bi bi-check-circle-fill"></i>Ready to save</span>';
    box.className = `fd-problems ${p.length ? 'bad' : 'ok'}`;
    $('#fd-save').disabled = !!p.length;
  }

  // ----- preview (the real fill-in runtime)
  function resolvedPreview() { try { return K.resolve(cleanForPreview(), previewVals).values; } catch (e) { return previewVals; } }
  function cleanForPreview() { return {...S, fields: S.fields.map(f => ({...f, options: f.options ? f.options.map(o => o.trim()).filter(Boolean) : f.options}))}; }
  let rt = null;
  function drawPreview() {
    const host = $('#fd-preview-body');
    rt = MFFormRuntime.mount(host, {schema: cleanForPreview(), values: previewVals, patient: {name: 'Awa Jallow', mrn: 'MF-PREVIEW01', age: 36, sex: 'Female', allergies: ['Penicillin']}, patterns: boot.patterns},
      {preview: v => { $('#fd-preview-out').textContent = JSON.stringify(v, null, 1); $('#fd-preview-out').hidden = false; }, onChange: v => { previewVals = v; }});
  }

  // ---------------------------------------------------------------- events
  const setProp = (f, p, v) => {
    if (['min', 'max', 'step', 'decimals', 'min_rows', 'max_rows', 'maxlength'].includes(p) && f.type !== 'date') v = v === '' ? undefined : +v;
    if (p === 'options') v = v.split('\n');
    if (v === '' || v === undefined || v === false) delete f[p]; else f[p] = v;
    // only fields added in this session get a new key; saved keys keep earlier answers linked
    if (p === 'label' && f._new && !f._keyTouched && isInput(f.type)) { const old = f.key; delete f.key; f.key = newKey(v, f.type); renameRefs(old, f.key); sel = f.key; }
    if (p === 'key') { f._keyTouched = true; }
  };
  function renameRefs(old, nu) {
    if (old === nu) return;
    const walk = t => { if (!t) return; if ('op' in t) { if (t.field && t.field.split('.')[0] === old) t.field = nu + t.field.slice(old.length); if (t.ref === old) t.ref = nu; } else (t.all || t.any || []).forEach(walk); };
    for (const f of S.fields) { walk(f.show_if); walk(f.require_if); if (f.type === 'calc' && f.formula) f.formula = f.formula.replace(new RegExp(`\\b${old}\\b`, 'g'), nu); }
  }
  let typingTimer = null;
  $('#fd-insp').addEventListener('input', ev => {
    const el = ev.target, f = F();
    if (el.dataset.p && el.dataset.p.startsWith('s.')) { S.settings[el.dataset.p.slice(2)] = el.value; dirty = true; drawProblems(); return; }
    if (el.dataset.p === 'pg.title') { S.pages[page].title = el.value || 'Page'; dirty = true; drawPages(); return; }
    if (!f) return;
    if (el.dataset.p) {
      if (!typingTimer) past.push(snapshot());
      clearTimeout(typingTimer); typingTimer = setTimeout(() => typingTimer = null, 600);
      const old = f.key;
      setProp(f, el.dataset.p, el.type === 'checkbox' ? el.checked : el.value);
      if (el.dataset.p === 'key') { renameRefs(old, el.value); sel = f.key; }
      dirty = true; future = [];
      if (el.tagName === 'SELECT' || el.type === 'checkbox') draw();
      else { drawCanvas(); drawProblems(); if (el.dataset.p === 'formula') { const r = K.tryFormula(f.formula || '', resolvedPreview(), f.decimals ?? 2), box = $('.fd-result'); box.className = `fd-result ${r.ok ? '' : 'bad'}`; box.innerHTML = r.ok ? `With the preview answers: <b>${esc(r.value === null ? 'empty' : K.text(r.value))}</b>` : esc(r.error); } }
      return;
    }
    if (el.dataset.col !== undefined) {
      commitSoft(() => { const c = f.columns[+el.dataset.col]; if (el.dataset.cp === 'label') { c.label = el.value; c.key = slugCol(el.value, f, +el.dataset.col); } else if (el.dataset.cp === 'options') c.options = el.value.split(',').map(x => x.trim()).filter(Boolean); else c.type = el.value; });
      if (el.tagName === 'SELECT') drawInspector();
      return;
    }
    const rb = el.closest('.fd-rules');
    if (rb) {
      const prop = rb.dataset.prop, t = f[prop], mode = 'any' in t ? 'any' : 'all';
      commitSoft(() => {
        if (el.dataset.rmode !== undefined) { f[prop] = {[el.value]: t[mode]}; }
        else { const r = t[mode][+el.closest('.fd-rule').dataset.i]; r[el.dataset.r] = el.value; if (el.dataset.r === 'op') { if (cat.unary.includes(r.op)) { delete r.value; delete r.ref; } if (cat.listy.includes(r.op)) delete r.ref; } if (el.dataset.r === 'field') r.value = ''; }
      });
      if (el.tagName === 'SELECT') drawInspector();
    }
  });
  const slugCol = (l, f, i) => { let b = (l.toLowerCase().replace(/[^\w\s]/g, '').trim().replace(/\s+/g, '_').replace(/^[^a-z]+/, '') || 'col').slice(0, 30), k = b, n = 2; while (f.columns.some((c, j) => j !== i && c.key === k)) k = `${b}_${n++}`; return k; };
  function commitSoft(fn) { past.push(snapshot()); future = []; fn(); dirty = true; drawCanvas(); drawProblems(); $('#fd-undo').disabled = false; }

  $('#fd-insp').addEventListener('click', ev => {
    const t = ev.target.closest('button'); if (!t) return;
    const f = F();
    if (t.dataset.tab) { tab = t.dataset.tab; drawInspector(); return; }
    if (t.id === 'fd-delpage') { const id = pageId(); if (S.fields.some(x => x.page === id) && !confirm('Delete this page and move its fields to the first page?')) return; commit(() => { S.pages.splice(page, 1); S.fields.forEach(x => { if (x.page === id) x.page = S.pages[0].id; }); page = 0; }); return; }
    if (t.dataset.pgMove) { const d = +t.dataset.pgMove; commit(() => { const [p] = S.pages.splice(page, 1); S.pages.splice(page + d, 0, p); page += d; }); return; }
    if (!f) return;
    if (t.id === 'fd-addcol') return commit(() => f.columns.push({key: slugCol('column', f, -1), label: 'Column', type: 'text'}));
    if (t.dataset.colDel !== undefined) return commit(() => f.columns.splice(+t.dataset.colDel, 1));
    if (t.dataset.ins !== undefined) { const ta = $('.fd-formula'), s = ta.selectionStart ?? ta.value.length; ta.value = ta.value.slice(0, s) + t.dataset.ins + ta.value.slice(ta.selectionEnd ?? s); ta.focus(); ta.selectionStart = ta.selectionEnd = s + t.dataset.ins.length; ta.dispatchEvent(new Event('input', {bubbles: true})); return; }
    const rb = t.closest('.fd-rules'); if (!rb) return;
    const prop = rb.dataset.prop;
    if (t.hasAttribute('data-radd')) return commit(() => { const first = S.fields.find(x => isInput(x.type) && x.key !== f.key); const rule = {field: first.key, op: 'not_empty'}; if (!f[prop]) f[prop] = {all: [rule]}; else f[prop][('any' in f[prop]) ? 'any' : 'all'].push(rule); tab = 'logic'; });
    const i = +t.closest('.fd-rule').dataset.i, mode = 'any' in f[prop] ? 'any' : 'all';
    if (t.hasAttribute('data-rdel')) return commit(() => { f[prop][mode].splice(i, 1); if (!f[prop][mode].length) delete f[prop]; });
    if (t.hasAttribute('data-rref')) return commit(() => { const r = f[prop][mode][i]; if (r.ref !== undefined) { delete r.ref; r.value = ''; } else { delete r.value; r.ref = S.fields.find(x => isInput(x.type) && x.key !== f.key && x.key !== r.field)?.key || r.field; } });
  });

  // canvas: select, tools, drag to reorder, drop from palette
  const canvas = $('#fd-canvas');
  canvas.addEventListener('click', ev => {
    const card = ev.target.closest('.fd-card'); if (!card) { sel = null; draw(); return; }
    const act = ev.target.closest('[data-act]')?.dataset.act, k = card.dataset.key;
    if (!act) { sel = k; draw(); return; }
    const i = S.fields.findIndex(f => f.key === k);
    if (act === 'del') commit(() => { S.fields.splice(i, 1); if (sel === k) sel = null; });
    if (act === 'dup') duplicate(k);
    if (act === 'up' || act === 'down') move(k, act === 'up' ? -1 : 1);
  });
  function duplicate(k) { commit(() => { const i = S.fields.findIndex(f => f.key === k), c = structuredClone(S.fields[i]); c.key = isInput(c.type) ? newKey(c.label + ' copy', c.type) : `_${c.type}${Date.now().toString(36)}`; c.label = c.label ? c.label + ' (copy)' : c.label; S.fields.splice(i + 1, 0, c); sel = c.key; }); }
  function move(k, d) {
    const onp = S.fields.filter(f => f.page === pageId()), j = onp.findIndex(f => f.key === k), other = onp[j + d];
    if (!other) return;
    commit(() => { const a = S.fields.findIndex(f => f.key === k), b = S.fields.findIndex(f => f.key === other.key); [S.fields[a], S.fields[b]] = [S.fields[b], S.fields[a]]; });
    canvas.querySelector(`[data-key="${CSS.escape(k)}"]`)?.focus();
  }
  let dragKey = null, dragType = null;
  canvas.addEventListener('dragstart', ev => { const c = ev.target.closest('.fd-card'); if (c) { dragKey = c.dataset.key; ev.dataTransfer.effectAllowed = 'move'; ev.dataTransfer.setData('text/plain', dragKey); c.classList.add('dragging'); } });
  canvas.addEventListener('dragend', () => { dragKey = null; canvas.querySelectorAll('.dragging,.drop-before,.drop-after').forEach(x => x.classList.remove('dragging', 'drop-before', 'drop-after')); });
  canvas.addEventListener('dragover', ev => {
    if (!dragKey && !dragType) return; ev.preventDefault();
    canvas.querySelectorAll('.drop-before,.drop-after').forEach(x => x.classList.remove('drop-before', 'drop-after'));
    const c = ev.target.closest('.fd-card'); if (!c) return;
    const r = c.getBoundingClientRect(); c.classList.add(ev.clientY < r.top + r.height / 2 ? 'drop-before' : 'drop-after');
  });
  canvas.addEventListener('drop', ev => {
    ev.preventDefault();
    const c = ev.target.closest('.fd-card'), after = c && c.classList.contains('drop-after');
    let idx = c ? S.fields.findIndex(f => f.key === c.dataset.key) + (after ? 1 : 0) : S.fields.length;
    if (dragType) { add(dragType, idx); dragType = null; return; }
    if (!dragKey || (c && c.dataset.key === dragKey)) return;
    commit(() => { const from = S.fields.findIndex(f => f.key === dragKey), [f] = S.fields.splice(from, 1); if (from < idx) idx--; f.page = pageId(); S.fields.splice(idx, 0, f); });
  });
  canvas.addEventListener('keydown', ev => {
    const c = ev.target.closest('.fd-card'); if (!c) return;
    if (ev.key === 'Enter') { sel = c.dataset.key; draw(); $('#fd-insp input, #fd-insp textarea')?.focus(); }
    if (ev.altKey && (ev.key === 'ArrowUp' || ev.key === 'ArrowDown')) { ev.preventDefault(); move(c.dataset.key, ev.key === 'ArrowUp' ? -1 : 1); }
    if (ev.key === 'Delete') { const k = c.dataset.key; commit(() => { S.fields.splice(S.fields.findIndex(f => f.key === k), 1); sel = null; }); }
  });

  // palette
  $('#fd-palette').innerHTML = GROUPS.map(([g, types]) => `<div class="fd-group"><span>${g}</span>${types.split(' ').map(t => `<button type="button" draggable="true" data-type="${t}" title="${esc(cat.types[t])}"><i class="bi ${ICON[t]}"></i>${esc(cat.types[t])}</button>`).join('')}</div>`).join('');
  $('#fd-palette').addEventListener('click', ev => { const b = ev.target.closest('[data-type]'); if (b) add(b.dataset.type); });
  $('#fd-palette').addEventListener('dragstart', ev => { const b = ev.target.closest('[data-type]'); if (b) { dragType = b.dataset.type; ev.dataTransfer.setData('text/plain', dragType); } });
  $('#fd-palette').addEventListener('dragend', () => { dragType = null; });

  // pages
  $('#fd-pages').addEventListener('click', ev => {
    const b = ev.target.closest('button'); if (!b) return;
    if (b.id === 'fd-addpage') return commit(() => { let n = S.pages.length + 1, id = `p${n}`; while (S.pages.some(p => p.id === id)) id = `p${++n}`; S.pages.push({id, title: `Page ${S.pages.length + 1}`}); page = S.pages.length - 1; sel = null; });
    page = +b.dataset.pg; sel = null; draw();
  });
  $('#fd-pages').addEventListener('dragover', ev => { if (dragKey && ev.target.closest('[data-pg]')) { ev.preventDefault(); ev.target.closest('[data-pg]').classList.add('drop'); } });
  $('#fd-pages').addEventListener('dragleave', ev => ev.target.closest('[data-pg]')?.classList.remove('drop'));
  $('#fd-pages').addEventListener('drop', ev => { const b = ev.target.closest('[data-pg]'); if (!b || !dragKey) return; ev.preventDefault(); const k = dragKey; commit(() => { S.fields.find(f => f.key === k).page = S.pages[+b.dataset.pg].id; }); });

  // meta + toolbar
  ['name', 'slug', 'desc'].forEach(k => $(`#fd-${k}`).addEventListener('input', ev => { meta[{desc: 'description'}[k] || k] = ev.target.value; if (k === 'name' && !boot.slug && !$('#fd-slug').dataset.touched) { meta.slug = ev.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50); $('#fd-slug').value = meta.slug; } if (k === 'slug') ev.target.dataset.touched = 1; dirty = true; drawProblems(); $('#fd-dirty').hidden = false; }));
  $('#fd-pub').addEventListener('change', ev => { meta.published = ev.target.checked; dirty = true; $('#fd-dirty').hidden = false; });
  $('#fd-undo').onclick = undo; $('#fd-redo').onclick = redo;
  $('#fd-preview-btn').onclick = () => { const p = $('#fd-preview'); p.hidden = !p.hidden; $('#fd-preview-btn').setAttribute('aria-pressed', !p.hidden); document.body.classList.toggle('fd-previewing', !p.hidden); if (!p.hidden) drawPreview(); };
  $('#fd-preview-close').onclick = () => $('#fd-preview-btn').click();
  $('#fd-problems').addEventListener('click', ev => { const li = ev.target.closest('[data-goto]'); if (!li) return; const f = S.fields.find(x => x.key === li.dataset.goto); if (f) { sel = f.key; page = S.pages.findIndex(p => p.id === f.page); draw(); } });
  document.addEventListener('keydown', ev => {
    const mod = ev.ctrlKey || ev.metaKey, typing = ev.target.matches('input, textarea, select');
    if (mod && ev.key.toLowerCase() === 's') { ev.preventDefault(); save(); }
    else if (mod && ev.key.toLowerCase() === 'z' && !typing) { ev.preventDefault(); ev.shiftKey ? redo() : undo(); }
    else if (mod && ev.key.toLowerCase() === 'y' && !typing) { ev.preventDefault(); redo(); }
    else if (mod && ev.key.toLowerCase() === 'd' && sel && !typing) { ev.preventDefault(); duplicate(sel); }
  });
  $('#fd-template').addEventListener('change', ev => { if (!ev.target.value) return; if (dirty && !confirm('Replace what you have with this template?')) { ev.target.value = ''; return; } location.href = `${location.pathname}?template=${ev.target.value}`; });

  async function save() {
    if (problems().length) { drawProblems(); $('#fd-problems').scrollIntoView({block: 'nearest'}); return; }
    const clean = {...S, fields: S.fields.map(({_keyTouched, _new, ...f}) => ({...f, options: f.options ? f.options.map(o => o.trim()).filter(Boolean) : undefined}))};
    const body = new URLSearchParams({name: meta.name, slug: meta.slug, description: meta.description, schema: JSON.stringify(clean), csrfmiddlewaretoken: csrf});
    if (meta.published) body.set('published', 'on');
    const btn = $('#fd-save'); btn.disabled = true; btn.classList.add('busy');
    try {
      const r = await fetch(boot.save_url, {method: 'POST', body, headers: {Accept: 'application/json'}, credentials: 'same-origin'});
      const d = await r.json();
      if (!d.ok) { $('#fd-problems').className = 'fd-problems bad'; $('#fd-problems').innerHTML = `<b><i class="bi bi-exclamation-triangle-fill"></i>The server found problems</b><ul>${d.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>`; }
      else { dirty = false; $('#fd-dirty').hidden = true; flash(`Saved · version ${d.version}${meta.published ? ' · published' : ' · draft'}`); if (location.pathname !== d.url) history.replaceState(null, '', d.url); boot.save_url = d.url; }
    } catch (e) { flash('Could not reach the server. Nothing was lost; try again.', true); }
    btn.disabled = false; btn.classList.remove('busy');
  }
  $('#fd-save').onclick = save;
  function flash(m, bad) { const t = $('#fd-toast'); t.textContent = m; t.className = `fd-toast show${bad ? ' bad' : ''}`; clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 3500); }
  window.addEventListener('beforeunload', ev => { if (dirty) { ev.preventDefault(); ev.returnValue = ''; } });
  if (boot.errors && boot.errors.length) setTimeout(() => { $('#fd-problems').className = 'fd-problems bad'; $('#fd-problems').innerHTML = `<b>The server found problems</b><ul>${boot.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>`; });
  draw();
})();
