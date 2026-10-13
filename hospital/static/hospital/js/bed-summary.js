/* Dr. Flow on the bed page: quick facts worked out on the server (no AI), and a handover summary written by the AI
   from de-identified data only. "What Dr. Flow receives" shows the exact context before anything is sent.
   Talks to bed_summary_views.py; animates the robot through window.RoboDoc (robodoc.js) when it is on the page. */
(() => {
  'use strict';
  const box = document.getElementById('bsum');
  if (!box) return;
  const RD = window.RoboDoc;
  const CSRF = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '';
  const urlFor = (tpl, id) => tpl.replace('/0/', `/${id}/`);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const toast = (m, k) => window.mfToast ? mfToast(m, k) : alert(m);
  const $ = s => box.querySelector(s);
  const THINK = ['Reading the de-identified chart', 'Checking observations and NEWS2', 'Checking the bedside devices',
                 'Checking medicines and doses given', 'Checking what is still in the lab', 'Writing the handover'];
  const plain = html => { const d = document.createElement('div'); d.innerHTML = html; return d.textContent.replace(/\s+/g, ' ').trim(); };
  let state = {enabled: false, discharged: false, quick: [], summary: null}, poll = null, engaged = false;

  async function api(url, body) {
    const opt = body === undefined ? {credentials: 'same-origin'} :
      {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': CSRF}, body: new URLSearchParams(body)};
    const res = await fetch(url, opt);
    let d = {};
    try { d = await res.json(); } catch (e) { /* not JSON */ }
    if (!res.ok || d.ok === false) throw new Error(d.error || (res.status === 403 ? 'Your account cannot use Dr. Flow here.' : 'Network error'));
    return d;
  }

  function render() {
    const s = state.summary, busy = s && s.status === 'running';
    const quick = state.quick.length ? `<ul class="bsum-quick">${state.quick.map(q =>
      `<li class="lv-${esc(q.level)}"><i class="bi bi-${esc(q.icon)}"></i><span>${esc(q.text)}</span></li>`).join('')}</ul>` : '';
    let sum = '';
    if (busy) sum = `<div class="bsum-busy"><span class="spinner-border spinner-border-sm"></span> Dr. Flow is writing the handover…</div>`;
    else if (s && s.status === 'failed') sum = `<div class="bsum-failed"><i class="bi bi-exclamation-triangle"></i> ${esc(s.error)}</div>`;
    else if (s && s.status === 'done') sum = `<article class="bsum-text">${s.html}</article>
      <div class="bsum-meta">${esc(s.by || 'staff')} · ${s.minutes_ago < 1 ? 'just now' : s.minutes_ago < 60 ? `${s.minutes_ago} min ago` : esc(s.at)}${s.model ? ` · ${esc(s.model)}` : ''}
        ${s.minutes_ago >= 240 ? '<span class="tag amber ms-1">May be out of date</span>' : ''}
        <span class="ms-auto d-inline-flex gap-1">
          ${RD ? '<button type="button" class="btn btn-sm btn-ghost" data-b="speak" title="Read aloud" aria-label="Read aloud"><i class="bi bi-volume-up"></i></button>' : ''}
          <button type="button" class="btn btn-sm btn-ghost" data-b="copy" title="Copy the handover"><i class="bi bi-clipboard"></i></button>
          <button type="button" class="btn btn-sm btn-ghost${s.helpful === true ? ' on' : ''}" data-rate="1" title="Helpful" aria-label="Helpful"><i class="bi bi-hand-thumbs-up"></i></button>
          <button type="button" class="btn btn-sm btn-ghost${s.helpful === false ? ' on' : ''}" data-rate="0" title="Not helpful" aria-label="Not helpful"><i class="bi bi-hand-thumbs-down"></i></button>
        </span></div>`;
    const can = state.enabled && !state.discharged;
    box.querySelector('.bsum-body').innerHTML = `
      ${quick}
      ${can || s ? `<div class="bsum-summary">${sum}</div>` : ''}
      <div class="bsum-actions">
        ${can ? `<button type="button" class="btn btn-primary btn-sm" data-b="ask" ${busy ? 'disabled' : ''}><i class="bi bi-stars"></i>${s && s.status === 'done' ? 'Update handover summary' : s && s.status === 'failed' ? 'Try again' : 'Write handover summary'}</button>` :
          !state.enabled ? '<span class="small muted"><i class="bi bi-plug"></i> AI is not connected on this server yet; the quick facts above work without it.</span>' : ''}
        <button type="button" class="btn btn-sm btn-ghost" data-b="context"><i class="bi bi-eye"></i>What Dr. Flow receives</button>
      </div>
      <p class="bsum-privacy"><i class="bi bi-shield-lock"></i> No name, record number, phone, address, date of birth, dates, ward, bed code, staff names or notes are sent. AI suggestions: the clinician decides.</p>`;
  }

  async function load() {
    try {
      const d = await api(box.dataset.panel);
      state = {enabled: d.enabled, discharged: d.discharged, quick: d.quick, summary: d.summary};
      render();
      if (d.summary && d.summary.status === 'running') watch(d.summary.id);
    } catch (err) { box.querySelector('.bsum-body').innerHTML = `<p class="small text-danger mb-0">${esc(err.message)}</p>`; }
  }

  async function ask() {
    engaged = true;
    if (RD) RD.summon().then(() => RD.think(THINK));
    try {
      const d = await api(box.dataset.ask, {});
      state.summary = d.summary; render();
      d.summary.status === 'running' ? watch(d.summary.id) : finished();
    } catch (err) { toast(err.message, 'danger'); if (RD) RD.fail(esc(err.message)); }
  }
  function watch(id) {
    clearTimeout(poll);
    const tick = async () => {
      try {
        const d = await api(urlFor(box.dataset.status, id));
        state.summary = d.summary;
        if (d.summary.status === 'running') { poll = setTimeout(tick, 2500); return; }
        render(); finished();
      } catch (e) { poll = setTimeout(tick, 5000); }
    };
    poll = setTimeout(tick, 2000);
  }
  function finished() {
    const s = state.summary;
    if (!RD || !engaged || !s) return;
    if (s.status === 'done') {
      RD.focus(() => box.querySelector('.bsum-text'));
      const first = plain(s.html).split(/(?<=\.)\s/)[0] || 'The handover is ready.';
      RD.done(`${esc(first)}`, [{label: 'Read it to me', icon: 'volume-up', primary: true, onClick: () => RD.speak(plain(s.html))}]);
    } else if (s.status === 'failed') RD.fail('The AI did not answer this time. Press <b>Try again</b> in a moment.');
  }

  async function showContext() {
    let dlg = document.getElementById('bsum-ctx');
    if (!dlg) {
      dlg = document.createElement('dialog'); dlg.id = 'bsum-ctx'; dlg.className = 'bsum-dlg';
      dlg.innerHTML = `<header><h2><i class="bi bi-eye"></i> What Dr. Flow receives</h2><button type="button" class="btn btn-ghost btn-sm ms-auto" data-close aria-label="Close"><i class="bi bi-x-lg"></i></button></header>
        <p class="small muted mb-2">This de-identified context is all the AI sees for the handover. Nothing has been sent by opening this.</p><pre></pre><p class="small muted mb-0 bsum-digest"></p>`;
      document.body.appendChild(dlg);
      dlg.addEventListener('click', e => { if (e.target.closest('[data-close]') || e.target === dlg) dlg.close(); });
    }
    dlg.querySelector('pre').textContent = 'Loading…'; dlg.showModal();
    try { const d = await api(box.dataset.context); dlg.querySelector('pre').textContent = d.context; dlg.querySelector('.bsum-digest').textContent = `SHA-256 ${d.digest.slice(0, 16)}…`; }
    catch (err) { dlg.querySelector('pre').textContent = err.message; }
  }

  box.addEventListener('click', async e => {
    const b = e.target.closest('[data-b]')?.dataset.b, s = state.summary;
    if (b === 'ask') return ask();
    if (b === 'context') return showContext();
    if (b === 'speak' && RD && s) return RD.summon().then(() => RD.speak(plain(s.html)));
    if (b === 'copy' && s) { try { await navigator.clipboard.writeText(s.text); toast('Handover copied.', 'success'); } catch (err) { toast('Could not copy. Select the text instead.', 'warning'); } return; }
    const r = e.target.closest('button[data-rate]');
    if (r && s) {
      try { const d = await api(urlFor(box.dataset.rate, s.id), {helpful: r.dataset.rate}); s.helpful = r.dataset.rate === '1'; render(); toast(d.message, 'success'); }
      catch (err) { toast(err.message, 'danger'); }
    }
  });
  box.querySelector('[data-robodoc-call]')?.addEventListener('click', () => {
    if (!RD) return;
    engaged = true; RD.focus(() => box);
    RD.summon().then(() => {
      const top = state.quick.slice(0, 3).map(q => esc(q.text)).join('<br>');
      const s = state.summary;
      RD.say(top || 'Hello, I am Dr. Flow.', [
        ...(s && s.status === 'done' ? [{label: 'Read the handover', icon: 'volume-up', primary: true, onClick: () => RD.speak(plain(s.html))}] : []),
        ...(state.enabled && !state.discharged ? [{label: s && s.status === 'done' ? 'Update it' : 'Write a handover', icon: 'stars', onClick: ask}] : []),
      ]);
    });
  });
  load();
})();
