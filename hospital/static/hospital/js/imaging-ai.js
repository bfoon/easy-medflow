/* Dr. Flow on the imaging page: analyse the image on screen (numbered labels drawn on it, with explanations), then ask
   questions about it. Talks to imaging_ai_views.py; draws through window.ImagingViewer (imaging-viewer.js) and
   animates the robot through window.RoboDoc (robodoc.js).
   Before anything is sent the clinician covers any name or number on the film ("Cover names") and confirms; the
   server blacks those boxes out, strips metadata and sends only de-identified context. Answers are suggestions. */
(() => {
  'use strict';
  const box = document.getElementById('iva');
  const IV = window.ImagingViewer;
  if (!box || !IV) return;
  const RD = window.RoboDoc;
  const CSRF = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '';
  const urlFor = (tpl, id) => tpl.replace('/0/', `/${id}/`);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const toast = (m, k) => window.mfToast ? mfToast(m, k) : alert(m);
  const $ = (s, el = box) => el.querySelector(s);
  const CONCERN = {urgent: 'Urgent', abnormal: 'Abnormal', watch: 'Check', normal: 'Normal'};
  const THINK = {
    analyse: ['Removing names and metadata', 'Checking the image quality', 'Finding the anatomy', 'Marking what I see', 'Weighing TB, pneumonia and the usual suspects', 'Writing the explanation'],
    question: ['Reading your question', 'Looking at the image again', 'Checking the labels', 'Writing the answer'],
  };
  const ASK_IDEAS = ['What is the most important finding?', 'Is the image quality good enough to report?', 'Could this be TB?',
                     'Explain this in plain words for the patient', 'What should I compare it with?', 'What would change your impression?'];

  let state = {enabled: false, canKeep: false, cancelled: false, runs: [], image: null};
  let activeRun = null, poll = null, engaged = false;
  const confirmed = new Set();

  /* ---------------------------------------------------------------- Markdown (same subset as the report editor) */
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/(^|[^\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])/g, '$1<i>$2</i>')
    .replace(/\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\[(\d{1,2})\](?!\()/g, '<button type="button" class="iva-ref" data-ref="$1" title="Show label $1 on the image">$1</button>');
  function md(text) {
    const out = []; let open = null;
    for (const raw of String(text || '').split('\n')) {
      const line = raw.trim(), h = line.match(/^#{1,4}\s+(.*)/), ol = line.match(/^(\d+)[.)]\s+(.*)/), ul = line.match(/^[-*•]\s+(.*)/);
      const kind = ol ? 'ol' : ul ? 'ul' : null;
      if (open && kind !== open && line) { out.push(`</${open}>`); open = null; }
      if (h) out.push(`<h4>${inline(h[1])}</h4>`);
      else if (kind) { if (!open) { out.push(`<${kind}>`); open = kind; } out.push(`<li>${inline(ol ? ol[2] : ul[1])}</li>`); }
      else if (line) out.push(`<p>${inline(line)}</p>`);
    }
    if (open) out.push(`</${open}>`);
    return out.join('');
  }
  const plain = t => String(t || '').replace(/\[(\d{1,2})\]/g, 'label $1').replace(/[#*_`>]/g, '').replace(/\s+/g, ' ').trim();

  /* ---------------------------------------------------------------- server */
  async function api(url, body) {
    const opt = body === undefined ? {credentials: 'same-origin'} :
      {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': CSRF}, body: JSON.stringify(body)};
    const res = await fetch(url, opt);
    let d = {};
    try { d = await res.json(); } catch (e) { /* not JSON */ }
    if (!res.ok || d.ok === false) throw new Error(d.error || (res.status === 403 ? 'Your account cannot use Dr. Flow here.' : 'Network error'));
    return d;
  }

  async function load(imageId) {
    clearTimeout(poll);
    state.image = imageId; activeRun = null;
    IV.setLabels([]);
    renderShell();
    $('.iva-thread').innerHTML = '<div class="iva-loading"><span class="spinner-border spinner-border-sm"></span> Loading…</div>';
    try {
      const d = await api(urlFor(box.dataset.threadUrl, imageId));
      if (state.image !== imageId) return;
      Object.assign(state, {enabled: d.enabled, canKeep: d.can_keep, cancelled: d.cancelled, runs: d.runs});
      const last = [...d.runs].reverse().find(r => r.status === 'done' && r.labels.length);
      if (last) activate(last.id, -1, false);
      renderShell(); renderThread();
      const busy = d.runs.find(r => r.busy);
      if (busy) watch(busy.id);
    } catch (err) {
      $('.iva-thread').innerHTML = `<p class="small text-danger mb-0">${esc(err.message)}</p>`;
    }
  }

  /* ---------------------------------------------------------------- shell: privacy, actions, ask box */
  function renderShell() {
    const body = $('.iva-body');
    const draft = $('.iva-ask textarea')?.value || '';      // keep a half-typed question across re-renders
    if (!state.enabled && state.runs.length === 0 && body.dataset.ready) {
      body.innerHTML = `<div class="iva-off"><i class="bi bi-plug"></i><div><b>AI is not connected on this server yet.</b>
        <div class="small muted">An administrator can switch it on (CLINICAL_AI_ENABLED with a vision-capable model).</div></div></div><div class="iva-thread"></div>`;
      return;
    }
    body.dataset.ready = '1';
    const can = state.enabled && !state.cancelled, covered = IV.covers(state.image).length, ok = confirmed.has(state.image);
    body.innerHTML = `
      ${can ? `<div class="iva-privacy">
        <div class="d-flex flex-wrap gap-1 align-items-center">
          <button type="button" class="btn btn-sm btn-ghost ${IV.covering ? 'on' : ''}" data-iva="cover" title="Drag boxes over names, numbers or dates on the film"><i class="bi bi-eraser-fill"></i>Cover names${covered ? ` <span class="iva-count">${covered}</span>` : ''}</button>
          ${covered ? '<button type="button" class="btn btn-sm btn-ghost" data-iva="uncover" title="Remove all boxes"><i class="bi bi-x-circle"></i></button>' : ''}
          <button type="button" class="btn btn-sm btn-ghost" data-iva="preview"><i class="bi bi-eye"></i>See what is sent</button>
        </div>
        <label class="iva-confirm"><input type="checkbox" class="form-check-input" data-iva-confirm ${ok ? 'checked' : ''}> No patient name, record number or date of birth is visible on this image, or I have covered it.</label>
      </div>
      <div class="iva-actions">
        <button type="button" class="btn btn-primary btn-sm" data-iva="analyse" ${ok ? '' : 'disabled'}><i class="bi bi-stars"></i>Analyse this image</button>
        <label class="iva-switch"><input type="checkbox" class="form-check-input" data-iva-show ${IV.labelsShown ? 'checked' : ''}> Show AI labels</label>
      </div>` : state.cancelled ? '<p class="small muted">This study was cancelled.</p>' : ''}
      <div class="iva-thread" aria-live="polite"></div>
      ${can ? `<div class="iva-ask">
        <div class="iva-ideas">${ASK_IDEAS.map(q => `<button type="button" data-idea="${esc(q)}">${esc(q)}</button>`).join('')}</div>
        <div class="iva-ask-row"><textarea class="form-control form-control-sm" rows="2" maxlength="1000" placeholder="Ask Dr. Flow about this image… (Enter to send)" aria-label="Question for Dr. Flow" ${ok ? '' : 'disabled'}></textarea>
        <button type="button" class="btn btn-ink btn-sm" data-iva="ask" ${ok ? '' : 'disabled'} aria-label="Ask"><i class="bi bi-send"></i></button></div>
      </div>` : ''}
      <p class="iva-disclaimer"><i class="bi bi-shield-check"></i> AI suggestions, not a report. Labels are approximate. The clinician decides.</p>`;
    const ta = $('.iva-ask textarea'); if (ta && draft) ta.value = draft;
  }

  /* ---------------------------------------------------------------- thread */
  function labelList(r) {
    if (!r.labels.length) return '';
    const on = activeRun === r.id;
    return `<ol class="iva-labels">${r.labels.map((lb, i) => `<li class="iva-label c-${esc(lb.concern)}${on ? ' live' : ''}" data-run="${r.id}" data-i="${i}">
      <button type="button" class="iva-label-head" data-locate title="Show on the image"><span class="n">${lb.n}</span><b>${esc(lb.name)}</b>
        <span class="iva-tag">${CONCERN[lb.concern] || 'Check'}</span><small>${esc(lb.confidence)} confidence</small>${lb.box || lb.point ? '' : ' <small class="muted">(no position)</small>'}</button>
      ${lb.explanation ? `<div class="iva-ex">${inline(lb.explanation)}</div>` : ''}
      ${state.canKeep && IV.canEdit && (lb.box || lb.point) ? `<button type="button" class="btn btn-sm btn-ghost iva-keep" data-keep title="Add to the measurements and notes on this image, then Save"><i class="bi bi-pin-angle"></i>Keep as annotation</button>` : ''}
    </li>`).join('')}</ol>`;
  }
  function card(r) {
    const head = `<div class="iva-meta">${r.kind === 'analyse' ? '<i class="bi bi-stars"></i> Analysis' : '<i class="bi bi-chat-dots"></i> Question'} · ${esc(r.by || 'staff')} · ${esc(r.at)}${r.covered ? ` · <span title="Boxes blacked out before sending"><i class="bi bi-eraser-fill"></i> ${r.covered} covered</span>` : ''}</div>`;
    const q = r.kind === 'question' ? `<div class="iva-q">${esc(r.question)}</div>` : '';
    if (r.busy || r.status === 'queued' || r.status === 'running') {
      return `<article class="iva-run busy" data-run="${r.id}">${head}${q}<div class="iva-a"><span class="spinner-border spinner-border-sm"></span> Dr. Flow is ${r.kind === 'analyse' ? 'looking at the image' : 'thinking'}…</div></article>`;
    }
    if (r.status === 'failed') {
      return `<article class="iva-run failed" data-run="${r.id}">${head}${q}<div class="iva-a"><i class="bi bi-exclamation-triangle"></i> ${esc(r.error || 'No answer.')}
        <button type="button" class="btn btn-sm btn-ghost" data-retry="${r.id}"><i class="bi bi-arrow-repeat"></i>Try again</button></div></article>`;
    }
    const live = activeRun === r.id;
    return `<article class="iva-run${live ? ' live' : ''}" data-run="${r.id}">${head}${q}
      <div class="iva-a">
        ${r.summary ? `<p class="iva-summary">${inline(r.summary)}</p>` : ''}
        ${r.quality ? `<p class="iva-quality"><i class="bi bi-camera"></i> ${inline(r.quality)}</p>` : ''}
        ${labelList(r)}
        ${r.text ? `<details class="iva-more" ${r.kind === 'question' || !r.labels.length ? 'open' : ''}><summary>${r.kind === 'question' ? 'Answer' : 'Full explanation'}</summary><div class="iva-md">${md(r.text)}</div></details>` : ''}
        ${r.limitations ? `<p class="iva-limits"><b>Limits:</b> ${inline(r.limitations)}</p>` : ''}
        <div class="iva-tools">
          ${r.labels.length ? `<button type="button" class="btn btn-sm btn-ghost${live ? ' on' : ''}" data-activate="${r.id}"><i class="bi bi-bounding-box-circles"></i>${live ? 'Labels on image' : 'Show these labels'}</button>` : ''}
          ${RD ? `<button type="button" class="btn btn-sm btn-ghost" data-speak="${r.id}" title="Read aloud"><i class="bi bi-volume-up"></i></button>` : ''}
          ${document.getElementById('findings') ? `<button type="button" class="btn btn-sm btn-ghost" data-findings="${r.id}" title="Insert into the report findings, marked as an AI suggestion"><i class="bi bi-box-arrow-in-down-left"></i>To findings</button>` : ''}
          <span class="ms-auto iva-rate">${r.model ? `<small class="muted me-1">${esc(r.model)}</small>` : ''}
            <button type="button" class="btn btn-sm btn-ghost${r.helpful === true ? ' on' : ''}" data-rate="${r.id}" data-v="1" title="Helpful" aria-label="Helpful"><i class="bi bi-hand-thumbs-up"></i></button>
            <button type="button" class="btn btn-sm btn-ghost${r.helpful === false ? ' on' : ''}" data-rate="${r.id}" data-v="0" title="Not helpful" aria-label="Not helpful"><i class="bi bi-hand-thumbs-down"></i></button></span>
        </div>
      </div></article>`;
  }
  function renderThread() {
    const t = $('.iva-thread'); if (!t) return;
    t.innerHTML = state.runs.length ? state.runs.map(card).join('') :
      `<div class="iva-empty"><i class="bi bi-robot"></i><div>${state.enabled ? 'Cover any name on the film, tick the box, then press <b>Analyse this image</b>. Dr. Flow will label what it sees and explain it. Then ask it anything about the picture.' : 'Nothing yet.'}</div></div>`;
  }
  const runById = id => state.runs.find(r => r.id === +id);
  function upsert(r) {
    const i = state.runs.findIndex(x => x.id === r.id);
    if (i >= 0) state.runs[i] = r; else state.runs.push(r);
  }

  /* which run's labels are drawn on the image */
  function activate(id, index = -1, zoom = true) {
    const r = runById(id); if (!r || !r.labels.length) return;
    activeRun = r.id;
    IV.setLabels(r.labels, index);
    if (index >= 0) IV.focusLabel(index, zoom);
    box.querySelectorAll('.iva-run').forEach(a => a.classList.toggle('live', +a.dataset.run === r.id));
    box.querySelectorAll('.iva-label').forEach(li => { li.classList.toggle('live', +li.dataset.run === r.id); li.classList.toggle('on', +li.dataset.run === r.id && +li.dataset.i === index); });
    box.querySelectorAll('[data-activate]').forEach(b => { const on = +b.dataset.activate === r.id; b.classList.toggle('on', on); b.innerHTML = `<i class="bi bi-bounding-box-circles"></i>${on ? 'Labels on image' : 'Show these labels'}`; });
  }

  /* ---------------------------------------------------------------- asking */
  async function ask(kind, question = '') {
    if (!confirmed.has(state.image)) { toast('Cover any name or number on the image and tick the confirmation first.', 'warning'); return; }
    if (IV.covering) IV.coverMode(false);
    const btn = box.querySelector(kind === 'analyse' ? '[data-iva=analyse]' : '[data-iva=ask]');
    if (btn) btn.disabled = true;
    engaged = true;
    if (RD) RD.summon().then(() => RD.think(THINK[kind]));
    try {
      const d = await api(urlFor(box.dataset.askUrl, state.image), {kind, question, redactions: IV.covers(state.image), confirm_no_identifiers: true});
      upsert(d.run); renderThread();
      if (kind === 'question') { const ta = $('.iva-ask textarea'); if (ta) ta.value = ''; }
      box.querySelector(`.iva-run[data-run="${d.run.id}"]`)?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
      d.run.busy || d.run.status === 'queued' || d.run.status === 'running' ? watch(d.run.id) : finished(d.run);
    } catch (err) {
      toast(err.message, 'danger');
      if (RD) RD.fail(esc(err.message));
    } finally { if (btn) btn.disabled = !confirmed.has(state.image); }
  }
  function watch(id) {
    clearTimeout(poll);
    if (RD && engaged && RD.state !== 'thinking') RD.summon().then(() => RD.think(THINK[runById(id)?.kind || 'analyse']));
    const tick = async () => {
      try {
        const d = await api(urlFor(box.dataset.runUrl, id));
        if (d.run.image !== state.image) return;
        upsert(d.run);
        if (d.run.status === 'queued' || d.run.status === 'running') { if (d.run.busy) { poll = setTimeout(tick, 2500); return; } }
        renderThread(); finished(d.run);
      } catch (e) { poll = setTimeout(tick, 5000); }
    };
    poll = setTimeout(tick, 2000);
  }
  function finished(r) {
    if (r.status === 'done') {
      if (r.labels.length) activate(r.id, -1, false);
      renderThread();
      if (RD && engaged) {
        const n = r.labels.length;
        const lead = r.kind === 'analyse' ? (n ? `I put <b>${n}</b> label${n === 1 ? '' : 's'} on the image.` : 'I could not place labels on this one.') : 'Here is my answer.';
        RD.focus(() => box.querySelector(`.iva-run[data-run="${r.id}"]`));
        RD.done(`${lead} ${inline(r.summary || '')}`, [
          ...(n ? [{label: 'Show me', icon: 'eye', primary: true, onClick: () => { activate(r.id, 0); sayLabel(r, 0); }}] : []),
          {label: 'Read it to me', icon: 'volume-up', onClick: () => RD.speak(plain([r.summary, r.text].join('. ')))},
        ]);
      }
    } else if (r.status === 'failed') {
      renderThread();
      if (RD && engaged) RD.fail('The AI did not answer this time. Press <b>Try again</b> in a moment.');
    }
  }
  function sayLabel(r, i) {
    const lb = r?.labels[i]; if (!RD || !lb) return;
    if (RD.state === 'hidden') return;
    RD.say(`<b>${lb.n}. ${esc(lb.name)}</b> <span class="iva-tag c-${esc(lb.concern)}">${CONCERN[lb.concern] || ''}</span><br>${inline(lb.explanation || '')}`, [
      {label: 'Read it', icon: 'volume-up', onClick: () => RD.speak(`${lb.name}. ${plain(lb.explanation)}`)},
      ...(i + 1 < r.labels.length ? [{label: 'Next', icon: 'arrow-right', primary: true, onClick: () => { activate(r.id, i + 1); sayLabel(r, i + 1); }}] : []),
    ]);
  }

  /* ---------------------------------------------------------------- what is sent */
  async function preview() {
    let dlg = document.getElementById('iva-preview');
    if (!dlg) {
      dlg = document.createElement('dialog'); dlg.id = 'iva-preview'; dlg.className = 'ivp iva-dlg';
      dlg.innerHTML = `<header><h2><i class="bi bi-eye"></i> What Dr. Flow receives</h2><button type="button" class="btn btn-ghost btn-sm ms-auto" data-close aria-label="Close"><i class="bi bi-x-lg"></i></button></header>
        <p class="small muted mb-2">Exactly these pixels (metadata removed, covered boxes painted black) and this de-identified context. Nothing has been sent yet.</p>
        <div class="iva-dlg-body"><div class="iva-dlg-img"></div><pre class="iva-dlg-ctx"></pre></div>`;
      document.body.appendChild(dlg);
      dlg.addEventListener('click', e => { if (e.target.closest('[data-close]') || e.target === dlg) dlg.close(); });
    }
    dlg.querySelector('.iva-dlg-img').innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    dlg.querySelector('.iva-dlg-ctx').textContent = '';
    dlg.showModal();
    try {
      const d = await api(urlFor(box.dataset.previewUrl, state.image), {redactions: IV.covers(state.image)});
      dlg.querySelector('.iva-dlg-img').innerHTML = `<img src="${d.image}" alt="Image as sent"><div class="small muted mt-1">${d.width} × ${d.height} px · ${Math.round(d.bytes / 1024)} KB · SHA-256 ${esc(d.digest.slice(0, 12))}…</div>`;
      dlg.querySelector('.iva-dlg-ctx').textContent = d.context;
    } catch (err) { dlg.querySelector('.iva-dlg-img').innerHTML = `<p class="text-danger small">${esc(err.message)}</p>`; }
  }

  /* findings: appended as a clearly marked AI suggestion for the radiologist to edit or delete */
  function toFindings(r) {
    const ta = document.getElementById('findings'); if (!ta) return;
    const lines = [`[Dr. Flow AI suggestion, ${r.at}, unverified: edit or delete]`];
    if (r.summary) lines.push(r.summary);
    r.labels.filter(l => l.concern !== 'normal').forEach(l => lines.push(`- ${l.name}${l.explanation ? `: ${l.explanation}` : ''}`));
    ta.value = (ta.value.trim() ? ta.value.trim() + '\n\n' : '') + lines.join('\n');
    ta.dispatchEvent(new Event('input', {bubbles: true}));
    ta.scrollIntoView({behavior: 'smooth', block: 'center'}); ta.focus();
    toast('Added to the findings. Edit it before you save.', 'success');
  }

  /* ---------------------------------------------------------------- events */
  box.addEventListener('change', e => {
    if (e.target.matches('[data-iva-confirm]')) {
      e.target.checked ? confirmed.add(state.image) : confirmed.delete(state.image);
      const ok = e.target.checked;
      box.querySelectorAll('[data-iva=analyse], [data-iva=ask], .iva-ask textarea').forEach(x => { x.disabled = !ok; });
    }
    if (e.target.matches('[data-iva-show]')) IV.showLabels(e.target.checked);
  });
  box.addEventListener('click', async e => {
    const t = e.target;
    const act = t.closest('[data-iva]')?.dataset.iva;
    if (act === 'cover') { IV.coverMode(!IV.covering); renderShell(); renderThread(); if (IV.covering) IV.root.scrollIntoView({behavior: 'smooth', block: 'nearest'}); return; }
    if (act === 'uncover') { IV.clearCovers(); return; }
    if (act === 'preview') return preview();
    if (act === 'analyse') return ask('analyse');
    if (act === 'ask') { const q = $('.iva-ask textarea')?.value.trim(); if (q) ask('question', q); else toast('Type a question first.', 'warning'); return; }
    const idea = t.closest('[data-idea]'); if (idea) { const ta = $('.iva-ask textarea'); if (ta && !ta.disabled) { ta.value = idea.dataset.idea; ta.focus(); } else toast('Tick the confirmation above first.', 'warning'); return; }
    const li = t.closest('.iva-label');
    if (li && t.closest('[data-keep]')) {
      const r = runById(li.dataset.run), i = +li.dataset.i;
      activate(r.id, i, false);
      if (IV.keepLabel(i)) toast('Added to the measurements and notes. Press Save on the viewer to keep it.', 'success');
      return;
    }
    if (li && (t.closest('[data-locate]') || !t.closest('a,button'))) { const r = runById(li.dataset.run); activate(r.id, +li.dataset.i); sayLabel(r, +li.dataset.i); return; }
    const ref = t.closest('.iva-ref');
    if (ref) { const r = runById(ref.closest('.iva-run').dataset.run), i = +ref.dataset.ref - 1; if (r && r.labels[i]) { activate(r.id, i); sayLabel(r, i); } return; }
    const a = t.closest('[data-activate]'); if (a) return activate(+a.dataset.activate, -1, false);
    const sp = t.closest('[data-speak]'); if (sp && RD) { const r = runById(sp.dataset.speak); RD.summon().then(() => RD.speak(plain([r.summary, r.text].join('. ')))); return; }
    const f = t.closest('[data-findings]'); if (f) return toFindings(runById(f.dataset.findings));
    const re = t.closest('[data-retry]'); if (re) { const r = runById(re.dataset.retry); return ask(r.kind, r.question); }
    const rt = t.closest('[data-rate]');
    if (rt) {
      try { const d = await api(urlFor(box.dataset.rateUrl, rt.dataset.rate), {helpful: rt.dataset.v}); const r = runById(rt.dataset.rate); r.helpful = rt.dataset.v === '1'; renderThread(); toast(d.message, 'success'); }
      catch (err) { toast(err.message, 'danger'); }
    }
  });
  box.addEventListener('keydown', e => {
    if (e.target.matches('.iva-ask textarea') && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); box.querySelector('[data-iva=ask]')?.click(); }
  });
  box.querySelector('[data-robodoc-call]')?.addEventListener('click', () => {
    if (!RD) return;
    engaged = true;
    RD.focus(() => box);
    RD.summon().then(() => {
      const last = [...state.runs].reverse().find(r => r.status === 'done');
      if (!state.enabled) RD.say('AI is not connected on this server yet. An administrator can switch it on.');
      else if (last) RD.say(`Last time I said: ${inline(last.summary || 'see the panel')}`, [
        ...(last.labels.length ? [{label: 'Walk me through the labels', icon: 'signpost', primary: true, onClick: () => { activate(last.id, 0); sayLabel(last, 0); }}] : []),
        {label: 'Ask a question', icon: 'chat-dots', onClick: () => box.querySelector('.iva-ask textarea')?.focus()}]);
      else RD.say('Hello, I am Dr. Flow. Cover any name on the film with <b>Cover names</b>, tick the box, then press <b>Analyse this image</b>. I will label what I see, explain it, and answer your questions about the picture.');
    });
  });

  /* the viewer tells us when the image changes, a label is clicked on the image, or covers change */
  IV.root.addEventListener('iv:image', e => load(e.detail.id));
  IV.root.addEventListener('iv:ai-select', e => {
    const r = runById(activeRun); if (!r) return;
    activate(r.id, e.detail.index, false);
    box.querySelector(`.iva-label[data-run="${r.id}"][data-i="${e.detail.index}"]`)?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    if (RD) RD.summon().then(() => sayLabel(r, e.detail.index));
  });
  IV.root.addEventListener('iv:cover', () => { renderShell(); renderThread(); });
  IV.root.addEventListener('iv:tool', () => { const b = box.querySelector('[data-iva=cover]'); if (b) b.classList.toggle('on', IV.covering); });
  document.addEventListener('robodoc:dismissed', () => { engaged = false; });

  // the viewer announces its first image as soon as it starts; this is only a fallback
  setTimeout(() => { if (state.image == null && IV.current) load(IV.current.id); }, 400);
})();
