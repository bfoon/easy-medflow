/* Care programmes: weekly chart, measurement sparklines, patient picker, tracing form, one-tap reminders and the
   optional de-identified Dr. Flow panel. Server-rendered pages; this only adds the small interactions. */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  const toast = (m, l) => (window.mfToast ? mfToast(m, l) : alert(m));
  const post = (url, body) => fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf(), 'Accept': 'application/json'}, body: new URLSearchParams(body || {})});

  /* "New programme" panel */
  $$('[data-pg-open]').forEach(b => b.addEventListener('click', () => { const el = document.getElementById(b.dataset.pgOpen); el.hidden = !el.hidden; if (!el.hidden) el.scrollIntoView({behavior: 'smooth', block: 'start'}); }));

  /* visits by week: stacked bars (attended, missed, planned) */
  const chart = $('#pg-chart'), wk = $('#pg-weeks');
  if (chart && wk) {
    const weeks = JSON.parse(wk.textContent), max = Math.max(1, ...weeks.map(w => w.attended + w.missed + w.planned));
    const Wd = Math.max(300, chart.clientWidth || 600), H = 96, step = Wd / weeks.length, bw = Math.min(46, step * .62), gap = step - bw;   // drawn at real pixel width: no stretched text
    let svg = `<svg viewBox="0 0 ${Wd} 118" width="100%" height="118">`;
    weeks.forEach((w, i) => {
      const x = i * (bw + gap) + gap / 2;
      let y = H;
      [['att', w.attended], ['mis', w.missed], ['pla', w.planned]].forEach(([c, n]) => {
        if (!n) return;
        const h = Math.max(2, n / max * (H - 4));
        y -= h;
        svg += `<rect class="${c}" x="${x}" y="${y.toFixed(1)}" width="${bw}" height="${h.toFixed(1)}" rx="3"><title>Week of ${esc(w.label)}: ${w.attended} attended, ${w.missed} missed, ${w.planned} planned</title></rect>`;
      });
      if (i % 3 === 0) svg += `<text x="${x + bw / 2}" y="113" text-anchor="middle">${esc(w.label)}</text>`;
    });
    chart.innerHTML = svg + `<line x1="0" x2="${Wd}" y1="${H}" y2="${H}" stroke="#DCE4E0"/></svg>`;
  }

  /* measurement sparklines (BP shows systolic and diastolic with the 140/90 target) */
  $$('.pg-spark').forEach(fig => {
    let pts; try { pts = JSON.parse(fig.dataset.points); } catch (e) { return; }
    if (pts.length < 2) return;
    const bp = fig.dataset.kind === 'bp', W = 240, H = 70, pad = 6;
    const vals = pts.flatMap(p => bp ? [p[1], p[2], 140, 90] : [p[1]]);
    const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
    const X = i => pad + i * (W - 2 * pad) / (pts.length - 1), Y = v => H - pad - (v - lo) / span * (H - 2 * pad);
    const line = (k, cls) => `<polyline fill="none" stroke="${cls}" stroke-width="2" stroke-linejoin="round" points="${pts.map((p, i) => `${X(i).toFixed(1)},${Y(p[k]).toFixed(1)}`).join(' ')}"/>`
      + pts.map((p, i) => `<circle cx="${X(i).toFixed(1)}" cy="${Y(p[k]).toFixed(1)}" r="2.6" fill="${cls}"><title>${esc(p[0])}: ${p[k]}</title></circle>`).join('');
    let svg = `<svg viewBox="0 0 ${W} ${H}">`;
    if (bp) svg += `<line x1="0" x2="${W}" y1="${Y(140)}" y2="${Y(140)}" stroke="#C8323F" stroke-dasharray="3 3" opacity=".5"/><line x1="0" x2="${W}" y1="${Y(90)}" y2="${Y(90)}" stroke="#C8323F" stroke-dasharray="3 3" opacity=".5"/>`;
    svg += line(1, '#0F7B78') + (bp ? line(2, '#4A5FC1') : '');
    const last = pts[pts.length - 1];
    fig.insertAdjacentHTML('beforeend', svg + `</svg><div class="small muted">${esc(pts[0][0])} → ${esc(last[0])}: <b>${bp ? `${last[1]}/${last[2]}` : last[1]}</b></div>`);
  });

  /* tracing: a new date is only asked for when one was agreed */
  $$('[data-pg-outcome]').forEach(sel => sel.addEventListener('change', () => {
    const d = sel.form.querySelector('input[name=due]');
    if (d) { d.hidden = sel.value !== 'rescheduled'; d.required = sel.value === 'rescheduled'; if (!d.hidden) d.focus(); }
  }));

  /* one-tap reminders: open WhatsApp / SMS on the phone, then mark the message sent */
  $$('[data-pg-sent]').forEach(a => a.addEventListener('click', () => {
    setTimeout(async () => {
      if (!confirm('Was the message sent?')) return;
      const r = await post(a.dataset.pgSent, {act: 'sent'}).then(x => x.json()).catch(() => null);
      if (r && r.ok) { toast('Marked as sent.'); const li = a.closest('li'); if (li) { li.classList.add('st-sent'); li.querySelector('.act') && (li.querySelector('.act').innerHTML = '<span class="tag teal">Sent</span>'); } }
    }, 600);
  }));

  /* enrol: find a patient by name, record number or phone */
  const pick = $('.pg-pick');
  if (pick) {
    const q = $('#pg-q', pick), list = $('.pg-results', pick), hid = $('input[name=patient]', pick), shown = $('.pg-picked', pick);
    let timer = 0, items = [], on = -1;
    const choose = it => { hid.value = it.id; shown.querySelector('b').textContent = it.name; shown.querySelector('span').textContent = it.mrn; shown.hidden = false; q.hidden = true; list.hidden = true; };
    const render = () => {
      list.innerHTML = items.length ? items.map((it, i) => `<li data-i="${i}" class="${it.enrolled ? 'dis' : ''} ${i === on ? 'on' : ''}"><b>${esc(it.name)}</b><span class="small muted">${esc(it.mrn)} · ${esc(it.sex)}${it.age != null ? ', ' + it.age + ' y' : ''}${it.enrolled ? ' · already enrolled' : ''}</span></li>`).join('')
        : '<li class="dis small muted">No patient found.</li>';
      list.hidden = false;
    };
    q.addEventListener('input', () => {
      clearTimeout(timer);
      if (q.value.trim().length < 2) { list.hidden = true; return; }
      timer = setTimeout(async () => {
        const d = await fetch(`${pick.dataset.search}?q=${encodeURIComponent(q.value.trim())}`, {credentials: 'same-origin'}).then(r => r.json()).catch(() => ({results: []}));
        items = d.results; on = -1; render();
      }, 220);
    });
    q.addEventListener('keydown', e => {
      if (list.hidden || !items.length) return;
      if (e.key === 'ArrowDown') { on = Math.min(items.length - 1, on + 1); render(); e.preventDefault(); }
      if (e.key === 'ArrowUp') { on = Math.max(0, on - 1); render(); e.preventDefault(); }
      if (e.key === 'Enter') { e.preventDefault(); const it = items[Math.max(0, on)]; if (it && !it.enrolled) choose(it); }
    });
    list.addEventListener('click', e => { const li = e.target.closest('[data-i]'); if (!li) return; const it = items[+li.dataset.i]; if (!it.enrolled) choose(it); });
    $('[data-pg-clear]', pick)?.addEventListener('click', () => { hid.value = ''; shown.hidden = true; q.hidden = false; q.value = ''; q.focus(); });
  }

  /* select all (eligible patients) */
  $$('[data-pg-all]').forEach(b => b.addEventListener('change', () => $$('input[name=patient][type=checkbox]', b.closest('form')).forEach(c => { c.checked = b.checked; })));

  /* Dr. Flow panel: ask, poll, and show exactly what is sent */
  $$('.pg-ai').forEach(panel => {
    const out = $('.pg-ai-out', panel);
    let poll = 0;
    const show = run => {
      if (!run) return;
      clearTimeout(poll);
      if (run.status === 'running' || run.status === 'queued') {
        out.innerHTML = '<div class="small muted"><span class="spinner-border spinner-border-sm"></span> Dr. Flow is thinking… (de-identified data only)</div>';
        poll = setTimeout(async () => { const d = await fetch(panel.dataset.status.replace('/0/', `/${run.id}/`), {credentials: 'same-origin'}).then(r => r.json()).catch(() => null); if (d) show(d.run); }, 2500);
      } else if (run.status === 'done') {
        out.innerHTML = `<div class="small muted mb-1">${esc(run.at)}${run.by ? ' · asked by ' + esc(run.by) : ''} · advisory only, the clinician decides</div>${run.html}`;
      } else if (run.status === 'blocked') {
        out.innerHTML = `<div class="pg-verdict no"><i class="bi bi-shield-x"></i><div><b>Blocked by the privacy check.</b> ${esc(run.error)} Nothing was sent.</div></div>`;
      } else {
        out.innerHTML = `<div class="alert-mf warn"><i class="bi bi-exclamation-triangle"></i><div>${esc(run.error || 'The AI did not answer. Try again in a moment.')}</div></div>`;
      }
    };
    if (panel.dataset.last) fetch(panel.dataset.status.replace('/0/', `/${panel.dataset.last}/`), {credentials: 'same-origin'}).then(r => r.json()).then(d => show(d.run)).catch(() => {});
    $('[data-pg-ai-ask]', panel)?.addEventListener('click', async ev => {
      ev.currentTarget.disabled = true;
      const r = await post(panel.dataset.ask).then(x => x.json()).catch(() => null);
      ev.currentTarget.disabled = false;
      if (!r || !r.ok) { toast((r && r.error) || 'Could not ask Dr. Flow.', 'warning'); return; }
      show(r.run);
    });
    $('[data-pg-ai-see]', panel)?.addEventListener('click', async () => {
      const d = await fetch(panel.dataset.context, {credentials: 'same-origin'}).then(r => r.json()).catch(() => null);
      if (!d) return;
      const html = `<div class="pg-verdict ${d.ok ? 'ok' : 'no'}"><i class="bi bi-shield-${d.ok ? 'check' : 'x'}"></i><div><b>Privacy check:</b> ${esc(d.verdict)}</div></div>
        <p class="small muted">${d.ai_on ? 'This is exactly what Dr. Flow receives when you ask.' : 'AI is off for this programme: nothing is sent. This is what would be sent if it were switched on.'}</p>
        <pre class="pg-ai-ctx">${esc(JSON.stringify(d.context, null, 2))}</pre>`;
      if (window.mfModal) mfModal('What the AI receives', html); else out.innerHTML = html;
    });
  });
})();

/* Insights: the shared daily summary (refresh, history, live update) and private questions to Dr. Flow. */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  const toast = (m, l) => (window.mfToast ? mfToast(m, l) : alert(m));
  const getJSON = url => fetch(url, {credentials: 'same-origin'}).then(r => r.json());
  const post = (url, body) => fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf(), 'Accept': 'application/json'}, body: new URLSearchParams(body || {})})
    .then(r => r.json().catch(() => ({ok: false, error: 'No answer from the server.'})));
  const statusUrl = (panel, id) => panel.dataset.status.replace('/0/', `/${id}/`);
  // ask again every few seconds until the AI has answered
  const waitFor = (panel, id, done) => {
    const tick = async () => {
      const d = await getJSON(statusUrl(panel, id)).catch(() => null);
      if (!d || !d.run) return setTimeout(tick, 5000);
      if (d.run.status === 'running' || d.run.status === 'queued') return setTimeout(tick, 3000);
      done(d.run);
    };
    setTimeout(tick, 2000);
  };

  /* shared daily summary */
  const sum = $('.pg-sum');
  if (sum) {
    const body = $('.pg-sum-body', sum), meta = $('[data-sum-meta]', sum), pend = $('.pg-sum-pending', sum);
    const show = run => {
      body.innerHTML = run.status === 'done' ? run.html : `<div class="alert-mf warn"><i class="bi bi-exclamation-triangle"></i><div>${esc(run.error || 'The AI did not answer. The previous summary is still shown in Earlier.')}</div></div>`;
      body.scrollTop = 0;
      if (meta && run.status === 'done') meta.innerHTML = `${run.covers ? `After the visits of <b>${esc(run.covers)}</b>` : 'Made ' + esc(run.at)} · ${run.auto ? 'made automatically' : 'refreshed by ' + esc(run.by)} · ${esc(run.at)}`;
    };
    const watch = id => { pend.hidden = false; waitFor(sum, id, run => { pend.hidden = true; show(run); if (run.status === 'done') toast('Daily summary updated.'); }); };
    if (sum.dataset.pending) watch(sum.dataset.pending);
    $('[data-sum-refresh]', sum)?.addEventListener('click', async ev => {
      ev.currentTarget.disabled = true;
      const d = await post(sum.dataset.ask);
      ev.currentTarget.disabled = false;
      if (!d.ok) return toast(d.error || 'Could not refresh.', 'warning');
      if (d.run.status === 'done') show(d.run); else watch(d.run.id);
    });
    $('[data-sum-history]', sum)?.addEventListener('change', async ev => {
      const d = await getJSON(statusUrl(sum, ev.target.value)).catch(() => null);
      if (d && d.run) show(d.run);
    });
    $('[data-sum-see]', sum)?.addEventListener('click', async () => {
      const d = await getJSON(sum.dataset.context).catch(() => null);
      if (!d) return;
      const html = `<div class="pg-verdict ${d.ok ? 'ok' : 'no'}"><i class="bi bi-shield-${d.ok ? 'check' : 'x'}"></i><div><b>Privacy check:</b> ${esc(d.verdict)}</div></div>
        <p class="small muted">${d.ai_on ? 'This is exactly what Dr. Flow receives for the daily summary.' : 'AI is not active for this programme: nothing is sent. This is what would be sent.'}</p>
        <pre class="pg-ai-ctx">${esc(JSON.stringify(d.context, null, 2))}</pre>`;
      if (window.mfModal) mfModal('What the AI receives', html);
    });
    // a summary made by someone else (or automatically) while this page is open appears by itself
    setInterval(async () => {
      if (document.hidden || !pend.hidden) return;
      const d = await getJSON(sum.dataset.feed).catch(() => null);
      if (d && d.pending) watch(d.pending.id);
    }, 60000);
  }

  /* private questions */
  const qa = $('.pg-qa');
  if (qa) {
    const list = $('[data-qa-list]', qa), form = $('[data-qa-form]', qa);
    const fill = (item, run) => {
      const a = $('.pg-qa-a', item);
      item.dataset.statusNow = run.status;
      a.innerHTML = run.status === 'done' ? run.html : (run.status === 'running' || run.status === 'queued')
        ? '<span class="small muted"><span class="spinner-border spinner-border-sm"></span> Thinking…</span>'
        : `<span class="small text-danger">${esc(run.error || 'No answer. Try again.')}</span>`;
    };
    const add = run => {
      $('[data-qa-empty]', qa)?.remove();
      list.insertAdjacentHTML('afterbegin', `<article class="pg-qa-item" data-run="${run.id}"><div class="pg-qa-q"><i class="bi bi-person"></i>${esc(run.question)}</div><div class="pg-qa-a"></div>
        <div class="pg-qa-meta small muted">${esc(run.at)} · <button type="button" class="link-btn" data-qa-forget>Delete</button></div></article>`);
      const item = list.firstElementChild;
      fill(item, run);
      list.scrollTop = 0;
      if (run.status === 'running' || run.status === 'queued') waitFor(qa, run.id, r => fill(item, r));
    };
    $$('.pg-qa-item', list).forEach(item => { if (['running', 'queued'].includes(item.dataset.statusNow)) waitFor(qa, item.dataset.run, r => fill(item, r)); });
    $$('[data-qa-suggest]', qa).forEach(b => b.addEventListener('click', () => { const t = form.q; t.value = b.textContent.trim(); t.focus(); }));
    form?.addEventListener('submit', async ev => {
      ev.preventDefault();
      const q = form.q.value.trim(); if (q.length < 3) return;
      const btn = form.querySelector('button.btn-primary'); btn.disabled = true;
      $('.pg-qa-blocked', qa)?.remove();
      const d = await post(qa.dataset.ask, {q});
      btn.disabled = false;
      if (!d.ok) {
        if (d.privacy) form.insertAdjacentHTML('afterend', `<div class="pg-qa-blocked mb-2"><i class="bi bi-shield-x"></i> ${esc(d.error)}</div>`);
        else toast(d.error || 'Could not ask.', 'warning');
        return;
      }
      form.q.value = '';
      add(d.run);
    });
    form?.q.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) form.requestSubmit(); });
    list.addEventListener('click', async e => {
      const b = e.target.closest('[data-qa-forget]'); if (!b) return;
      const item = b.closest('[data-run]');
      if (!confirm('Delete this question and its answer?')) return;
      const d = await post(qa.dataset.forget.replace('/0/', `/${item.dataset.run}/`));
      if (d.ok) item.remove();
    });
  }
})();
