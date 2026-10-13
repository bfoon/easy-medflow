/* Dr. Flow on the Lab insights page.
   Heads-up: worked out on the server with no AI, shown in the panel and, when something needs attention, said by the
   robot when the page opens (once per patient per browser session). Each item that names a result opens it, because
   insights.js opens any [data-param] clicked inside #insights.
   AI: "Explain the big picture" (all results together) and questions about the results, from de-identified data only.
   Talks to lab_insights_views.py; animates the robot through window.RoboDoc (robodoc.js). */
(() => {
  'use strict';
  const box = document.getElementById('lidf');
  if (!box) return;
  const RD = window.RoboDoc;
  const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  const urlFor = (tpl, id) => tpl.replace('/0/', `/${id}/`);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const toast = (m, k) => window.mfToast ? mfToast(m, k) : alert(m);
  const plain = html => { const d = document.createElement('div'); d.innerHTML = html; return d.textContent.replace(/\s+/g, ' ').trim(); };
  const THINK = {
    headsup: ['Reading every result', 'Comparing with earlier values', 'Looking for patterns across body systems', 'Checking what is still in the lab', 'Writing the heads-up'],
    question: ['Reading your question', 'Looking at the results again', 'Checking the trends', 'Writing the answer'],
  };
  const IDEAS = ['What do these results mean together?', 'What is getting worse?', 'Which tests should I repeat?',
                 'Could this be malaria, sickle cell or anaemia?', 'Is the kidney function getting worse?', 'Explain these results for the patient'];
  let state = {enabled: false, headsup: [], thread: []}, poll = null, engaged = false;

  async function api(url, body) {
    const opt = body === undefined ? {credentials: 'same-origin'} :
      {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': CSRF}, body: new URLSearchParams(body)};
    const res = await fetch(url, opt);
    let d = {};
    try { d = await res.json(); } catch (e) { /* not JSON */ }
    if (!res.ok || d.ok === false) throw new Error(d.error || (res.status === 403 ? 'Your account cannot use Dr. Flow here.' : 'Network error'));
    return d;
  }

  /* ---------------------------------------------------------------- drawing */
  const line = h => `<li class="lv-${esc(h.level)}${h.param ? ' has-param' : ''}"${h.param ? ` data-param="${h.param}" role="button" tabindex="0" title="Open this result"` : ''}>
      <i class="bi bi-${esc(h.icon)}"></i><span>${esc(h.text)}</span>${h.param ? '<i class="bi bi-chevron-right ms-auto go"></i>' : ''}</li>`;
  function card(a) {
    const q = a.kind === 'question' ? `<div class="lidf-q">${esc(a.question)}</div>` : '<div class="lidf-kind"><i class="bi bi-stars"></i> Big picture</div>';
    let body;
    if (a.status === 'running') body = '<div class="lidf-busy"><span class="spinner-border spinner-border-sm"></span> Dr. Flow is thinking…</div>';
    else if (a.status === 'failed') body = `<div class="lidf-failed"><i class="bi bi-exclamation-triangle"></i> ${esc(a.error)} <button type="button" class="btn btn-sm btn-ghost" data-retry="${a.id}"><i class="bi bi-arrow-repeat"></i>Try again</button></div>`;
    else body = `<div class="lidf-md">${a.html}</div>
      <div class="lidf-meta">${esc(a.by || 'staff')} · ${a.minutes_ago < 1 ? 'just now' : a.minutes_ago < 60 ? `${a.minutes_ago} min ago` : esc(a.at)}${a.model ? ` · ${esc(a.model)}` : ''}
        <span class="ms-auto d-inline-flex gap-1">
          ${RD ? `<button type="button" class="btn btn-sm btn-ghost" data-speak="${a.id}" title="Read aloud" aria-label="Read aloud"><i class="bi bi-volume-up"></i></button>` : ''}
          <button type="button" class="btn btn-sm btn-ghost${a.helpful === true ? ' on' : ''}" data-rate="${a.id}" data-v="1" title="Helpful" aria-label="Helpful"><i class="bi bi-hand-thumbs-up"></i></button>
          <button type="button" class="btn btn-sm btn-ghost${a.helpful === false ? ' on' : ''}" data-rate="${a.id}" data-v="0" title="Not helpful" aria-label="Not helpful"><i class="bi bi-hand-thumbs-down"></i></button>
        </span></div>`;
    return `<article class="lidf-card" data-ask="${a.id}">${q}${body}</article>`;
  }
  function render() {
    const draft = box.querySelector('.lidf-ask textarea')?.value || '';
    const busy = state.thread.some(a => a.status === 'running');
    box.querySelector('.lidf-body').innerHTML = `
      <ul class="lidf-heads">${state.headsup.map(line).join('')}</ul>
      <div class="lidf-actions">
        ${state.enabled ? `<button type="button" class="btn btn-primary btn-sm" data-b="headsup" ${busy ? 'disabled' : ''}><i class="bi bi-stars"></i>Explain the big picture</button>` :
          '<span class="small muted"><i class="bi bi-plug"></i> AI is not connected on this server yet; the heads-up above works without it.</span>'}
        <button type="button" class="btn btn-sm btn-ghost" data-b="context"><i class="bi bi-eye"></i>What Dr. Flow receives</button>
      </div>
      ${state.thread.length ? `<div class="lidf-thread" aria-live="polite">${state.thread.map(card).join('')}</div>` : ''}
      ${state.enabled ? `<div class="lidf-ask">
        <div class="lidf-ideas">${IDEAS.map(q => `<button type="button" data-idea="${esc(q)}">${esc(q)}</button>`).join('')}</div>
        <div class="lidf-ask-row"><textarea class="form-control form-control-sm" rows="2" maxlength="500" placeholder="Ask Dr. Flow anything about these results… (Enter to send)" aria-label="Question for Dr. Flow"></textarea>
          <button type="button" class="btn btn-ink btn-sm" data-b="ask" ${busy ? 'disabled' : ''} aria-label="Ask"><i class="bi bi-send"></i></button></div></div>` : ''}
      <p class="lidf-privacy"><i class="bi bi-shield-lock"></i> No name, record number, phone, date of birth, dates, reviewer or staff names are sent. AI suggestions: the clinician decides.</p>`;
    const ta = box.querySelector('.lidf-ask textarea'); if (ta && draft) ta.value = draft;
    const t = box.querySelector('.lidf-thread'); if (t) t.scrollTop = t.scrollHeight;
  }

  /* ---------------------------------------------------------------- the robot's heads-up when the page opens */
  function greet() {
    if (!RD) return;
    const urgent = state.headsup.filter(h => h.level === 'danger' || h.level === 'warn');
    if (!urgent.length) return;
    const key = `mf-lidf-${box.dataset.patient}`;
    try { if (sessionStorage.getItem(key)) return; sessionStorage.setItem(key, '1'); } catch (e) { /* private mode: greet every time */ }
    setTimeout(() => {
      RD.focus(() => box);
      RD.summon().then(() => RD.say(`<b>Heads-up</b><ul class="lidf-bubble">${urgent.slice(0, 3).map(h => `<li>${esc(h.text)}</li>`).join('')}</ul>`, [
        ...(urgent[0].param ? [{label: 'Show me', icon: 'eye', primary: true, onClick: () => openParam(urgent[0].param)}] : []),
        ...(state.enabled ? [{label: 'Explain the big picture', icon: 'stars', onClick: () => ask('headsup')}] : []),
      ]));
    }, 1600);      // after insights.js has flown to the most urgent organ
  }
  const openParam = id => box.querySelector(`.lidf-heads [data-param="${id}"]`)?.click();

  /* ---------------------------------------------------------------- server */
  async function load() {
    try {
      const d = await api(box.dataset.panel);
      state = {enabled: d.enabled, headsup: d.headsup, thread: d.thread};
      render(); greet();
      const busy = d.thread.find(a => a.status === 'running');
      if (busy) watch(busy.id);
    } catch (err) { box.querySelector('.lidf-body').innerHTML = `<p class="small text-danger mb-0">${esc(err.message)}</p>`; }
  }
  async function ask(kind, question = '') {
    engaged = true;
    if (RD) RD.summon().then(() => RD.think(THINK[kind]));
    try {
      const d = await api(box.dataset.ask, {kind, question});
      upsert(d.ask); render();
      if (kind === 'question') { const ta = box.querySelector('.lidf-ask textarea'); if (ta) ta.value = ''; }
      d.ask.status === 'running' ? watch(d.ask.id) : finished(d.ask);
    } catch (err) { toast(err.message, 'danger'); if (RD) RD.fail(esc(err.message)); }
  }
  const upsert = a => { const i = state.thread.findIndex(x => x.id === a.id); i >= 0 ? (state.thread[i] = a) : state.thread.push(a); };
  function watch(id) {
    clearTimeout(poll);
    const tick = async () => {
      try {
        const d = await api(urlFor(box.dataset.status, id));
        upsert(d.ask);
        if (d.ask.status === 'running') { poll = setTimeout(tick, 2500); return; }
        render(); finished(d.ask);
      } catch (e) { poll = setTimeout(tick, 5000); }
    };
    poll = setTimeout(tick, 2000);
  }
  function finished(a) {
    if (!RD || !engaged) return;
    if (a.status === 'done') {
      RD.focus(() => box.querySelector(`.lidf-card[data-ask="${a.id}"]`));
      const first = plain(a.html).split(/(?<=\.)\s/)[0] || 'Here is my answer.';
      RD.done(esc(first), [{label: 'Read it to me', icon: 'volume-up', primary: true, onClick: () => RD.speak(plain(a.html))}]);
    } else if (a.status === 'failed') RD.fail('The AI did not answer this time. Press <b>Try again</b> in a moment.');
  }
  async function showContext() {
    let dlg = document.getElementById('lidf-ctx');
    if (!dlg) {
      dlg = document.createElement('dialog'); dlg.id = 'lidf-ctx'; dlg.className = 'lidf-dlg';
      dlg.innerHTML = `<header><h2><i class="bi bi-eye"></i> What Dr. Flow receives</h2><button type="button" class="btn btn-ghost btn-sm ms-auto" data-close aria-label="Close"><i class="bi bi-x-lg"></i></button></header>
        <p class="small muted mb-2">This de-identified data is all the AI sees about these results. Nothing has been sent by opening this.</p><pre></pre><p class="small muted mb-0 lidf-digest"></p>`;
      document.body.appendChild(dlg);
      dlg.addEventListener('click', e => { if (e.target.closest('[data-close]') || e.target === dlg) dlg.close(); });
    }
    dlg.querySelector('pre').textContent = 'Loading…'; dlg.showModal();
    try { const d = await api(box.dataset.context); dlg.querySelector('pre').textContent = d.context; dlg.querySelector('.lidf-digest').textContent = `SHA-256 ${d.digest.slice(0, 16)}…`; }
    catch (err) { dlg.querySelector('pre').textContent = err.message; }
  }

  /* ---------------------------------------------------------------- events */
  box.addEventListener('click', async e => {
    const t = e.target, b = t.closest('[data-b]')?.dataset.b;
    if (b === 'headsup') return ask('headsup');
    if (b === 'context') return showContext();
    if (b === 'ask') { const q = box.querySelector('.lidf-ask textarea')?.value.trim(); return q && q.length >= 3 ? ask('question', q) : toast('Type a question first.', 'warning'); }
    const idea = t.closest('[data-idea]'); if (idea) { const ta = box.querySelector('.lidf-ask textarea'); ta.value = idea.dataset.idea; ta.focus(); return; }
    const re = t.closest('[data-retry]'); if (re) { const a = state.thread.find(x => x.id === +re.dataset.retry); return ask(a.kind, a.question); }
    const sp = t.closest('[data-speak]'); if (sp && RD) { const a = state.thread.find(x => x.id === +sp.dataset.speak); return RD.summon().then(() => RD.speak(plain(a.html))); }
    const rt = t.closest('button[data-rate]');
    if (rt) {
      try { const d = await api(urlFor(box.dataset.rate, rt.dataset.rate), {helpful: rt.dataset.v}); const a = state.thread.find(x => x.id === +rt.dataset.rate); a.helpful = rt.dataset.v === '1'; render(); toast(d.message, 'success'); }
      catch (err) { toast(err.message, 'danger'); }
    }
  });
  box.addEventListener('keydown', e => {
    if (e.target.matches('.lidf-ask textarea') && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); box.querySelector('[data-b=ask]')?.click(); }
  });
  box.querySelector('[data-robodoc-call]')?.addEventListener('click', () => {
    if (!RD) return;
    engaged = true; RD.focus(() => box);
    const top = state.headsup.slice(0, 3);
    RD.summon().then(() => RD.say(top.length ? `<b>Heads-up</b><ul class="lidf-bubble">${top.map(h => `<li>${esc(h.text)}</li>`).join('')}</ul>` : 'Nothing needs attention right now.', [
      ...(state.enabled ? [{label: 'Explain the big picture', icon: 'stars', primary: true, onClick: () => ask('headsup')},
                          {label: 'Ask a question', icon: 'chat-dots', onClick: () => box.querySelector('.lidf-ask textarea')?.focus()}] : []),
    ]));
  });
  load();
})();
