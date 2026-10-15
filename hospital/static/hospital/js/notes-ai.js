/* Clinical and nursing notes on the visit page: edit in place, let Dr. Flow polish the wording (a suggestion you
   accept or discard; nothing is saved until you press Save), and ask Dr. Flow for tests, next steps or answers about
   the notes. The server removes the patient's name and other identifiers before anything is sent (notes_ai.py). */
(() => {
  'use strict';
  const root = document.querySelector('.notes-root');
  if (!root) return;
  const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || root.querySelector('[name=csrfmiddlewaretoken]')?.value
    || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const url = (tpl, id) => tpl.replace(/\/0\/(rate\/)?$/, `/${id}/$1`);
  const LABELS = {symptoms: 'Symptoms', assessment: 'Assessment', diagnosis: 'Diagnosis', plan: 'Plan', nursing_notes: 'Nursing notes'};
  const PLACEHOLDER = /\[(patient|name|phone|record|number)( \d+)?\]/;

  async function post(u, data) {
    const fd = data instanceof FormData ? data : new FormData();
    if (!(data instanceof FormData)) Object.entries(data || {}).forEach(([k, v]) => fd.append(k, v));
    const r = await fetch(u, {method: 'POST', body: fd, credentials: 'same-origin', headers: {'X-CSRFToken': CSRF}});
    let j = {}; try { j = await r.json(); } catch (e) { j = {ok: false, error: r.status === 403 ? 'You do not have access to this.' : 'Something went wrong. Try again.'}; }
    return j;
  }
  /* poll until the answer is ready */
  async function wait(ask, onTick) {
    let a = ask, n = 0;
    while (a.status === 'running' || a.status === 'queued') {
      await new Promise(r => setTimeout(r, Math.min(1200 + n * 300, 4000))); n++;
      const r = await fetch(url(root.dataset.statusUrl, a.id), {credentials: 'same-origin'});
      a = (await r.json()).ask || {status: 'failed', error: 'Lost contact with the server.'};
      if (onTick) onTick(a);
    }
    return a;
  }

  /* ------------------------------------------------------------ editing in place */
  const forms = [...root.querySelectorAll('.notes-form')];
  const dirty = new Set();
  forms.forEach(f => {
    const section = f.dataset.section, panel = f.closest('.notes-panel'), view = panel.querySelector('.notes-view');
    const btn = panel.querySelector(`[data-notes-edit="${section}"]`);
    const open = on => { f.hidden = !on; view.hidden = on; if (btn) btn.hidden = on; if (on) f.querySelector('textarea')?.focus(); };
    btn?.addEventListener('click', () => open(true));
    f.querySelector('[data-notes-cancel]').addEventListener('click', () => {
      if (dirty.has(f) && !confirm('Discard your changes to these notes?')) return;
      f.reset(); f.querySelector('[name=ai_assisted]').value = '0'; dirty.delete(f);
      const sg = f.querySelector('.notes-suggestion'); if (sg) { sg.hidden = true; sg.innerHTML = ''; }
      open(false);
    });
    f.addEventListener('input', () => dirty.add(f));
    f.addEventListener('submit', () => dirty.delete(f));
    if (location.hash === `#notes-${section}-edit`) open(true);
  });
  addEventListener('beforeunload', ev => { if (dirty.size) { ev.preventDefault(); ev.returnValue = ''; } });

  /* ------------------------------------------------------------ Dr. Flow rewrites the draft */
  // a small word diff so the clinician sees exactly what would change
  function diff(a, b) {
    const A = a.split(/(\s+)/), B = b.split(/(\s+)/);
    if (A.length * B.length > 250000) return `<ins>${esc(b)}</ins>`;          // very long: just show the new text
    const L = Array.from({length: A.length + 1}, () => new Uint16Array(B.length + 1));
    for (let i = A.length - 1; i >= 0; i--) for (let j = B.length - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    let i = 0, j = 0, out = '';
    while (i < A.length && j < B.length) {
      if (A[i] === B[j]) { out += esc(A[i]); i++; j++; }
      else if (L[i + 1][j] >= L[i][j + 1]) { out += /^\s+$/.test(A[i]) ? '' : `<del>${esc(A[i])}</del>`; i++; }
      else { out += /^\s+$/.test(B[j]) ? esc(B[j]) : `<ins>${esc(B[j])}</ins>`; j++; }
    }
    while (i < A.length) { if (!/^\s+$/.test(A[i])) out += `<del>${esc(A[i])}</del>`; i++; }
    while (j < B.length) { out += /^\s+$/.test(B[j]) ? esc(B[j]) : `<ins>${esc(B[j])}</ins>`; j++; }
    return out.replace(/\n/g, '<br>');
  }
  function showRewrite(f, a, sent) {
    const box = f.querySelector('.notes-suggestion');
    const fields = Object.entries(a.fields || {}).filter(([k, v]) => (v || '') !== (sent[k] || ''));
    if (!fields.length) {
      box.hidden = false;
      box.innerHTML = `<div class="ns-head"><b><i class="bi bi-check2-circle"></i> Nothing to change</b><button type="button" class="ns-x" aria-label="Close">×</button></div><p class="small mb-0">Dr. Flow found nothing to correct.</p>`;
      return;
    }
    const names = fields.some(([, v]) => PLACEHOLDER.test(v));
    box.hidden = false;
    box.innerHTML = `<div class="ns-head"><b><i class="bi bi-robot"></i> ${esc(a.kind_label)}: suggestion</b><span class="small muted">Review before using. Nothing is saved until you press Save.</span><button type="button" class="ns-x" aria-label="Discard">×</button></div>
      ${a.changes.length ? `<ul class="ns-changes">${a.changes.map(c => `<li>${esc(c)}</li>`).join('')}</ul>` : ''}
      ${names ? '<div class="ns-warn"><i class="bi bi-exclamation-triangle"></i> Some names or numbers could not be put back automatically, so the suggestion still shows a placeholder such as [name 2]. Replace it with the real detail before saving.</div>' : ''}
      ${fields.map(([k, v]) => `<div class="ns-field" data-k="${k}"><div class="ns-fh"><b>${esc(LABELS[k] || k)}</b><button type="button" class="btn btn-sm btn-ghost" data-use="${k}"><i class="bi bi-check2"></i>Use this</button></div>
        <div class="ns-diff">${diff(sent[k] || '', v)}</div></div>`).join('')}
      <div class="ns-acts">${fields.length > 1 ? '<button type="button" class="btn btn-sm btn-primary" data-use="*"><i class="bi bi-check2-all"></i>Use all</button>' : ''}
        <button type="button" class="btn btn-sm btn-ghost" data-discard>Discard</button>
        <span class="ns-rate">Helpful? <button type="button" data-rate="1" aria-label="Helpful"><i class="bi bi-hand-thumbs-up"></i></button><button type="button" data-rate="0" aria-label="Not helpful"><i class="bi bi-hand-thumbs-down"></i></button></span></div>`;
    box.dataset.ask = a.id;
    box._fields = Object.fromEntries(fields);
  }
  root.addEventListener('click', async ev => {
    const rw = ev.target.closest('[data-rewrite]');
    if (rw) {
      const f = rw.closest('.notes-form'), state = f.querySelector('.notes-aistate');
      const sent = {};
      f.querySelectorAll('.notes-field[data-field] textarea').forEach(t => { sent[t.name] = t.value; });
      if (!Object.values(sent).some(v => v.trim())) { state.textContent = 'Write something first.'; return; }
      f.querySelectorAll('[data-rewrite]').forEach(b => { b.disabled = true; });
      state.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Dr. Flow is working…';
      const j = await post(root.dataset.askUrl, {kind: rw.dataset.rewrite, section: f.dataset.section, ...sent});
      let a = j.ask;
      if (j.ok && a) a = await wait(a);
      f.querySelectorAll('[data-rewrite]').forEach(b => { b.disabled = false; });
      if (!j.ok || !a) { state.textContent = j.error || 'Something went wrong.'; return; }
      if (a.status !== 'done') { state.textContent = a.error || 'The AI did not answer. Try again.'; return; }
      state.textContent = '';
      showRewrite(f, a, sent);
      return;
    }
    const use = ev.target.closest('[data-use]');
    if (use) {
      const box = use.closest('.notes-suggestion'), f = box.closest('.notes-form');
      const keys = use.dataset.use === '*' ? Object.keys(box._fields) : [use.dataset.use];
      keys.forEach(k => { const t = f.querySelector(`textarea[name="${k}"]`); if (t) { t.value = box._fields[k]; t.classList.add('ns-used'); setTimeout(() => t.classList.remove('ns-used'), 1600); } box.querySelector(`.ns-field[data-k="${k}"]`)?.remove(); delete box._fields[k]; });
      f.querySelector('[name=ai_assisted]').value = '1'; dirty.add(f);
      if (!Object.keys(box._fields).length) { box.hidden = true; box.innerHTML = ''; }
      else if (Object.keys(box._fields).length < 2) box.querySelector('[data-use="*"]')?.remove();
      return;
    }
    if (ev.target.closest('[data-discard], .ns-x')) { const box = ev.target.closest('.notes-suggestion'); box.hidden = true; box.innerHTML = ''; return; }
    const rate = ev.target.closest('[data-rate]');
    if (rate) {
      const holder = rate.closest('[data-ask]');
      const j = await post(url(root.dataset.rateUrl, holder.dataset.ask), {helpful: rate.dataset.rate});
      rate.closest('.ns-rate').textContent = j.message || 'Thank you.';
      return;
    }
    const k = ev.target.closest('[data-ask-kind]');
    if (k) startAsk('suggest', '');
  });

  /* ------------------------------------------------------------ suggestions and questions */
  const answers = root.querySelector('[data-answers]');
  const qform = root.querySelector('[data-ask-form]');
  function card(a) {
    const el = document.createElement('article');
    el.className = 'notes-answer'; el.dataset.ask = a.id;
    fill(el, a);
    return el;
  }
  function fill(el, a) {
    const head = a.kind === 'question' ? `<i class="bi bi-chat-left-dots"></i> ${esc(a.question)}` : '<i class="bi bi-clipboard2-pulse"></i> Suggested tests &amp; next steps';
    const body = a.status === 'running' || a.status === 'queued' ? '<p class="muted small"><span class="spinner-border spinner-border-sm"></span> Dr. Flow is reading the notes…</p>'
      : a.status === 'failed' ? `<p class="text-danger small mb-0">${esc(a.error)}</p>` : `<div class="notes-md">${a.html}</div>`;
    el.innerHTML = `<header><b>${head}</b><span class="small muted">${esc(a.by)} · ${esc(a.at)}</span></header>${body}
      ${a.status === 'done' ? `<footer><span class="small muted">Advisory only. Check against the patient and guidelines.</span>${a.helpful === null || a.helpful === undefined ? '<span class="ns-rate">Helpful? <button type="button" data-rate="1" aria-label="Helpful"><i class="bi bi-hand-thumbs-up"></i></button><button type="button" data-rate="0" aria-label="Not helpful"><i class="bi bi-hand-thumbs-down"></i></button></span>' : ''}</footer>` : ''}`;
  }
  async function startAsk(kind, question) {
    const data = {kind, section: 'clinical', question};
    forms.filter(f => !f.hidden).forEach(f => f.querySelectorAll('.notes-field[data-field] textarea').forEach(t => { data[t.name] = t.value; }));   // the draft on screen
    const btns = root.querySelectorAll('[data-ask-kind], [data-ask-form] button');
    btns.forEach(b => { b.disabled = true; });
    const j = await post(root.dataset.askUrl, data);
    btns.forEach(b => { b.disabled = false; });
    if (!j.ok || !j.ask) { alert(j.error || 'Something went wrong.'); return; }
    let el = answers.querySelector(`[data-ask="${j.ask.id}"]`);
    if (!el) { el = card(j.ask); answers.prepend(el); }
    if (qform && kind === 'question') qform.reset();
    const a = await wait(j.ask, x => fill(el, x));
    fill(el, a);
  }
  qform?.addEventListener('submit', ev => {
    ev.preventDefault();
    const q = qform.question.value.trim();
    if (q.length < 3) { qform.question.focus(); return; }
    startAsk('question', q);
  });
  try {
    JSON.parse(root.querySelector('.notes-asks-data')?.textContent || '[]').forEach(a => {
      const el = card(a); answers.append(el);
      if (a.status === 'running') wait(a, x => fill(el, x)).then(x => fill(el, x));
    });
  } catch (e) { /* no earlier answers */ }
})();
