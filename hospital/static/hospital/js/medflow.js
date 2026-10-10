/* MedFlow front-end. Vanilla JS, no build step. Every feature activates only if its markup exists. */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const csrf = () => ($('meta[name="csrf-token"]') || {}).content || '';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const URLS = window.MEDFLOW || {};

  async function post(url, data = {}) {
    const body = new URLSearchParams(data);
    const res = await fetch(url, {method: 'POST', body, credentials: 'same-origin',
      headers: {'X-CSRFToken': csrf(), 'x-requested-with': 'fetch'}});
    let json = {};
    try { json = await res.json(); } catch (_) { /* non-JSON error page */ }
    if (!res.ok || json.ok === false) throw new Error(json.error || `Request failed (${res.status})`);
    return json;
  }

  /* ---------------------------------------------------------------- toasts */
  const toastBox = $('.toasts') || document.body.appendChild(Object.assign(document.createElement('div'), {className: 'toasts'}));
  const ICON = {success: 'bi-check-circle-fill', error: 'bi-exclamation-octagon-fill', warning: 'bi-exclamation-triangle-fill', info: 'bi-info-circle-fill'};
  function dismiss(t) { t.classList.add('leaving'); setTimeout(() => t.remove(), 300); }
  function arm(t) {
    t.querySelector('button')?.addEventListener('click', () => dismiss(t));
    if (!t.classList.contains('error')) setTimeout(() => t.isConnected && dismiss(t), 6500);
  }
  window.mfToast = (msg, level = 'success') => {
    const t = document.createElement('div');
    t.className = `toast-mf ${level}`; t.setAttribute('role', 'status');
    t.innerHTML = `<i class="bi ${ICON[level] || ICON.info}"></i><div>${esc(msg)}</div><button aria-label="Dismiss"><i class="bi bi-x-lg"></i></button>`;
    toastBox.appendChild(t); arm(t);
  };
  $$('.toast-mf').forEach(arm);

  /* ---------------------------------------------------------------- small behaviours */
  $('.menu-btn')?.addEventListener('click', () => $('.rail').classList.toggle('open'));
  document.addEventListener('click', e => {
    const rail = $('.rail');
    if (rail?.classList.contains('open') && !rail.contains(e.target) && !e.target.closest('.menu-btn')) rail.classList.remove('open');
  });
  document.addEventListener('submit', e => {
    const msg = e.target.dataset.confirm;
    if (msg && !confirm(msg)) e.preventDefault();
  });
  $$('[data-clock]').forEach(el => {
    const tick = () => { el.textContent = new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: el.dataset.clock === 'short' ? undefined : '2-digit'}); };
    tick(); setInterval(tick, 1000);
  });
  $$('[data-tabs]').forEach(box => {
    const btns = $$('[data-tab]', box);
    const show = name => {
      btns.forEach(b => { const on = b.dataset.tab === name; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); });
      $$('[data-pane]', box).forEach(p => p.classList.toggle('on', p.dataset.pane === name));
    };
    btns.forEach(b => b.addEventListener('click', () => { show(b.dataset.tab); history.replaceState(null, '', '#' + b.dataset.tab); }));
    const fromHash = location.hash.slice(1);
    show(btns.some(b => b.dataset.tab === fromHash) ? fromHash : btns[0]?.dataset.tab);
  });

  function countUp(el, to, ms = 900) {
    const from = parseInt(el.textContent, 10) || 0;
    if (reduceMotion || from === to) { el.textContent = to; return; }
    const t0 = performance.now();
    const step = now => {
      const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      el.textContent = Math.round(from + (to - from) * e);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  $$('[data-count]').forEach((el, i) => { const to = +el.dataset.count; el.textContent = '0'; setTimeout(() => countUp(el, to), 250 + i * 70); });

  /* ---------------------------------------------------------------- ECG monitor
     A sweep-style trace like a bedside monitor: the cursor writes the waveform left to right,
     erasing a small gap ahead of itself. Heart rate is set from data-bpm and can change live. */
  function pqrst(p) {
    const g = (c, w, a) => a * Math.exp(-Math.pow((p - c) / w, 2));
    return g(.10, .028, .12) + g(.205, .009, -.12) + g(.23, .011, 1) + g(.258, .011, -.28) + g(.46, .045, .26);
  }
  class ECG {
    constructor(canvas) {
      this.c = canvas; this.ctx = canvas.getContext('2d');
      this.bpm = +canvas.dataset.bpm || 72; this.sweep = +canvas.dataset.sweep || 5.5;
      this.x = 0; this.t = 0; this.last = null; this.buf = null;
      this.resize(); addEventListener('resize', () => this.resize());
      if (reduceMotion) { this.prefill(); this.draw(); } else requestAnimationFrame(ts => this.frame(ts));
    }
    resize() {
      const r = this.c.getBoundingClientRect(), d = devicePixelRatio || 1;
      this.w = Math.max(50, Math.floor(r.width)); this.h = Math.floor(r.height);
      this.c.width = this.w * d; this.c.height = this.h * d; this.ctx.setTransform(d, 0, 0, d, 0, 0);
      const old = this.buf; this.buf = new Float32Array(this.w).fill(NaN);
      if (old) this.buf.set(old.subarray(0, Math.min(old.length, this.w)));
      this.x = Math.min(this.x, this.w - 1);
    }
    color() { return getComputedStyle(this.c).getPropertyValue('--trace').trim() || '#3FE0B0'; }
    sample() {
      const period = 60 / this.bpm, p = (this.t % period) / period;
      return pqrst(p) + (Math.random() - .5) * .018;
    }
    prefill() { const dt = this.sweep / this.w; for (let i = 0; i < this.w; i++) { this.buf[i] = this.sample(); this.t += dt; } }
    frame(ts) {
      if (this.last == null) this.last = ts;
      const dt = Math.min(.05, (ts - this.last) / 1000); this.last = ts;
      const px = this.w / this.sweep * dt, steps = Math.max(1, Math.round(px));
      for (let i = 0; i < steps; i++) {
        this.t += dt / steps; this.x = (this.x + px / steps) % this.w;
        const xi = Math.floor(this.x); this.buf[xi] = this.sample();
        for (let g = 1; g <= 18; g++) this.buf[(xi + g) % this.w] = NaN; // erase gap ahead of the cursor
      }
      this.draw(); requestAnimationFrame(t => this.frame(t));
    }
    y(v) { const mid = this.h * .62, amp = this.h * .5; return mid - v * amp; }
    draw() {
      const {ctx, w, buf} = this, col = this.color(), cx = Math.floor(this.x);
      ctx.clearRect(0, 0, w, this.h); ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.strokeStyle = col;
      ctx.shadowColor = col; ctx.shadowBlur = 8;
      // draw in chunks; alpha fades with distance behind the cursor (phosphor afterglow)
      const CH = 6;
      for (let s = 0; s < w; s += CH) {
        const age = ((cx - s) + w) % w, alpha = reduceMotion ? 1 : Math.max(.12, 1 - age / w * .9);
        ctx.globalAlpha = alpha; ctx.beginPath(); let pen = false;
        for (let i = s; i <= Math.min(w - 1, s + CH); i++) {
          const v = buf[i]; if (Number.isNaN(v)) { pen = false; continue; }
          pen ? ctx.lineTo(i, this.y(v)) : ctx.moveTo(i, this.y(v)); pen = true;
        }
        ctx.stroke();
      }
      if (!reduceMotion && !Number.isNaN(buf[cx])) {
        ctx.globalAlpha = 1; ctx.shadowBlur = 16; ctx.fillStyle = '#fff';
        ctx.beginPath(); ctx.arc(cx, this.y(buf[cx]), 3, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1; ctx.shadowBlur = 0;
    }
  }
  const monitors = $$('canvas[data-ecg]').map(c => new ECG(c));
  const setBeat = bpm => document.documentElement.style.setProperty('--beat', (60 / bpm).toFixed(2) + 's');

  /* ---------------------------------------------------------------- live hospital pulse */
  function applyPulse(d) {
    setBeat(d.bpm);
    monitors.forEach(m => { m.bpm = d.bpm; });
    $$('[data-pulse-bpm]').forEach(el => countUp(el, d.bpm, 600));
    $$('[data-pulse-mood]').forEach(el => { el.textContent = d.mood; });
    const mon = $('.monitor');
    if (mon) { mon.classList.toggle('busy', d.mood === 'Busy'); mon.classList.toggle('surging', d.mood === 'Surging'); }
    (d.flow || []).forEach(f => {
      const el = $(`[data-flow="${f.key}"]`);
      if (el && +el.textContent !== f.value) { countUp(el, f.value, 500); el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump'); }
    });
    $$('[data-live]').forEach(el => { const v = d[el.dataset.live]; if (v !== undefined && String(v) !== el.textContent) countUp(el, +v, 500); });
    const qb = $('[data-queue-baseline]');
    if (qb && +qb.dataset.queueBaseline !== d.waiting) $('#queue-changed')?.removeAttribute('hidden');
  }
  if (URLS.pulse) {
    const poll = () => fetch(URLS.pulse, {credentials: 'same-origin'}).then(r => r.ok ? r.json() : null).then(d => d && applyPulse(d)).catch(() => {});
    const initial = $('[data-initial-bpm]');
    if (initial) setBeat(+initial.dataset.initialBpm);
    poll();
    setInterval(poll, +(document.body.dataset.pollMs || 15000));
  }

  /* ---------------------------------------------------------------- command palette */
  const pal = $('.palette-backdrop');
  if (pal) {
    const input = $('input', pal), list = $('.results', pal);
    const NAV = $$('.rail a.nav-link').map(a => ({name: a.textContent.trim().replace(/\d+$/, '').trim(), url: a.href, kind: 'Go to'}));
    const ACTIONS = [
      {name: 'Register a patient', url: URLS.patientNew, kind: 'Action'},
      {name: 'Issue a queue ticket', url: URLS.ticketNew, kind: 'Action'},
      {name: 'Start an encounter', url: URLS.encounterNew, kind: 'Action'},
      {name: 'Write a prescription', url: URLS.rxNew, kind: 'Action'},
      {name: 'Open waiting-room display', url: URLS.display, kind: 'Action'},
    ].filter(a => a.url);
    let items = [], sel = 0, timer;
    const render = (patients = []) => {
      const q = input.value.trim().toLowerCase();
      const match = x => !q || x.name.toLowerCase().includes(q);
      const groups = [['Patients', patients], ['Actions', ACTIONS.filter(match)], ['Navigate', NAV.filter(match)]];
      items = []; let html = '';
      groups.forEach(([label, arr]) => {
        if (!arr.length) return;
        html += `<div class="group">${label}</div>`;
        arr.forEach(x => {
          const i = items.push(x) - 1;
          html += x.mrn
            ? `<a class="res" href="${esc(x.url)}" data-i="${i}"><span class="avatar">${esc(x.initials)}</span><span><b>${esc(x.name)}</b><small>${esc(x.mrn)}${x.age != null ? ' · ' + esc(x.age) + ' yrs' : ''}</small></span><span class="kind">Chart</span></a>`
            : `<a class="res" href="${esc(x.url)}" data-i="${i}"><span>${esc(x.name)}</span><span class="kind">${esc(x.kind)}</span></a>`;
        });
      });
      list.innerHTML = html || `<div class="empty">No matches. Try a name, MRN, or phone number.</div>`;
      sel = 0; highlight();
    };
    const highlight = () => $$('.res', list).forEach(r => r.classList.toggle('sel', +r.dataset.i === sel));
    const open = () => { pal.classList.add('open'); input.value = ''; render(); setTimeout(() => input.focus(), 10); };
    const close = () => pal.classList.remove('open');
    $$('[data-palette]').forEach(b => b.addEventListener('click', open));
    pal.addEventListener('click', e => { if (e.target === pal) close(); });
    document.addEventListener('keydown', e => {
      const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
      if ((e.key === 'k' && (e.metaKey || e.ctrlKey)) || (e.key === '/' && !typing)) { e.preventDefault(); open(); }
      if (!pal.classList.contains('open')) return;
      if (e.key === 'Escape') close();
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(items.length - 1, sel + 1); highlight(); }
      if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(0, sel - 1); highlight(); }
      if (e.key === 'Enter' && items[sel]) { e.preventDefault(); location.href = items[sel].url; }
    });
    input.addEventListener('input', () => {
      clearTimeout(timer); render();
      const q = input.value.trim();
      if (q.length < 2 || !URLS.search) return;
      timer = setTimeout(() => fetch(`${URLS.search}?q=${encodeURIComponent(q)}`, {credentials: 'same-origin'})
        .then(r => r.json()).then(d => input.value.trim() === q && render(d.results)).catch(() => {}), 180);
    });
  }

  /* ---------------------------------------------------------------- queue board: drag, drop, act */
  const board = $('[data-board]');
  if (board) {
    const FLOW = {waiting: ['called', 'cancelled'], called: ['in_service', 'skipped', 'waiting'], in_service: ['completed'], skipped: ['waiting', 'cancelled']};
    const LABEL = {called: ['Call', 'btn-primary', 'bi-megaphone'], in_service: ['Start', 'btn-ink', 'bi-play-fill'], completed: ['Complete', 'btn-primary', 'bi-check2'],
      skipped: ['Skip', 'btn-ghost', 'bi-skip-forward'], waiting: ['Requeue', 'btn-ghost', 'bi-arrow-counterclockwise'], cancelled: ['Cancel', 'btn-danger-soft', 'bi-x']};
    const room = $('#call-room');
    if (room) { room.value = localStorage.getItem('mf-room') || ''; room.addEventListener('change', () => localStorage.setItem('mf-room', room.value)); }
    const urlFor = (id, s) => board.dataset.transition.replace('/0/', `/${id}/`).replace('__state__', s);
    const renderActs = card => {
      const acts = $('.acts', card); if (!acts) return;
      acts.innerHTML = (FLOW[card.dataset.status] || []).map(s => {
        const [l, cls, ic] = LABEL[s];
        return `<button type="button" class="btn btn-sm ${cls}" data-to="${s}"><i class="bi ${ic}"></i>${l}</button>`;
      }).join('');
    };
    const recount = () => $$('.lane', board).forEach(l => {
      const n = $$('.ticket', l).length;
      $('.count', l).textContent = n;
      $('.empty', l)?.toggleAttribute('hidden', n > 0);
    });
    async function move(card, to) {
      if (to === 'cancelled' && !confirm(`Cancel ticket ${card.dataset.code}?`)) return;
      const data = {}; if (to === 'called' && room?.value) data.counter = room.value;
      try {
        await post(urlFor(card.dataset.id, to), data);
      } catch (err) { mfToast(err.message, 'error'); return; }
      const qb = $('[data-queue-baseline]');
      if (qb) { let n = +qb.dataset.queueBaseline; if (card.dataset.status === 'waiting') n--; if (to === 'waiting') n++; qb.dataset.queueBaseline = n; }
      const first = card.getBoundingClientRect();
      if (to === 'completed' || to === 'cancelled') {
        card.style.transition = 'opacity .3s, transform .3s'; card.style.opacity = '0'; card.style.transform = 'scale(.92)';
        setTimeout(() => { card.remove(); recount(); }, 300);
        mfToast(`${card.dataset.code} ${to === 'completed' ? 'completed' : 'cancelled'}.`);
        const done = $('[data-done-count]'); if (done && to === 'completed') countUp(done, +done.textContent + 1, 300);
        return;
      }
      card.dataset.status = to;
      const lane = $(`.lane[data-status="${to}"] .lane-body`, board);
      lane.appendChild(card); renderActs(card); recount();
      if (!reduceMotion) { // FLIP: animate from old position to new
        const last = card.getBoundingClientRect();
        card.animate([{transform: `translate(${first.left - last.left}px, ${first.top - last.top}px)`}, {transform: 'none'}], {duration: 380, easing: 'cubic-bezier(.2,.8,.2,1)'});
      }
      if (to === 'called') mfToast(`${card.dataset.code} called${data.counter ? ' to ' + data.counter : ''}. It is now on the waiting-room display.`);
    }
    $$('.ticket', board).forEach(card => {
      renderActs(card);
      card.addEventListener('dragstart', e => {
        e.dataTransfer.setData('text/plain', card.dataset.id); card.classList.add('dragging');
        const ok = FLOW[card.dataset.status] || [];
        $$('.lane', board).forEach(l => l.classList.add(ok.includes(l.dataset.status) ? 'drop-ok' : 'drop-no'));
      });
      card.addEventListener('dragend', () => { card.classList.remove('dragging'); $$('.lane', board).forEach(l => l.classList.remove('drop-ok', 'drop-no')); });
    });
    board.addEventListener('click', e => { const b = e.target.closest('[data-to]'); if (b) move(b.closest('.ticket'), b.dataset.to); });
    $$('.lane', board).forEach(l => {
      l.addEventListener('dragover', e => { if (l.classList.contains('drop-ok')) e.preventDefault(); });
      l.addEventListener('drop', e => {
        e.preventDefault();
        const card = $(`.ticket[data-id="${e.dataTransfer.getData('text/plain')}"]`, board);
        if (card && card.dataset.status !== l.dataset.status) move(card, l.dataset.status);
      });
    });
    recount();
  }

  /* ---------------------------------------------------------------- live prescription safety panel */
  const rxPanel = $('[data-rx-check]');
  if (rxPanel && URLS.rxCheck) {
    const f = rxPanel.closest('form') || document;
    const get = n => $(`[name="${n}"]`, f);
    let timer;
    const run = () => {
      const enc = get('encounter')?.value, med = get('medication')?.value, qty = get('quantity')?.value || 1;
      if (!enc || !med) { rxPanel.innerHTML = `<div class="empty"><i class="bi bi-shield-plus"></i>Choose a visit and a medication to see allergy and stock checks.</div>`; return; }
      fetch(`${URLS.rxCheck}?encounter=${enc}&medication=${med}&quantity=${qty}`, {credentials: 'same-origin'}).then(r => r.json()).then(d => {
        if (!d.ready) return;
        const matches = d.possible_allergy_matches, docd = d.documented_allergies;
        rxPanel.innerHTML = `
          <div class="label-sm">Checking ${esc(d.medication)} for ${esc(d.patient)}</div>
          ${matches.length ? `<div class="alert-mf danger mt-2"><i class="bi bi-exclamation-octagon-fill"></i><div><b>Possible allergy match:</b> ${matches.map(a => esc(a.substance) + ' (' + esc(a.severity) + ')').join(', ')}. Choose another medication or document an override reason.</div></div>` : ''}
          <div class="mt-3"><div class="label-sm mb-1">Documented allergies</div>${docd.length ? docd.map(a => `<span class="tag red me-1">${esc(a.substance)} · ${esc(a.severity)}</span>`).join('') : '<span class="tag amber">None documented — confirm with the patient</span>'}</div>
          <div class="mt-3"><div class="label-sm mb-1">Unexpired stock</div><b class="display" style="font-size:1.6rem">${d.inventory_available}</b> <span class="muted">units</span> ${d.insufficient_stock ? '<span class="tag amber ms-1">Not enough for this quantity</span>' : '<span class="tag teal ms-1">Sufficient</span>'}</div>
          <p class="form-text mt-3 mb-0">${esc(d.disclaimer)}</p>`;
        const ov = get('override_reason')?.closest('.field'); if (ov) ov.hidden = !matches.length && !get('override_reason').value;
      }).catch(() => {});
    };
    ['encounter', 'medication', 'quantity'].forEach(n => get(n)?.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 200); }));
    run();
  }

  /* ---------------------------------------------------------------- attendance shift ring */
  const ring = $('[data-shift-since]');
  if (ring) {
    const since = new Date(ring.dataset.shiftSince), circ = 2 * Math.PI * 64, prog = $('.prog', ring), label = $('[data-shift-label]', ring);
    prog.style.strokeDasharray = circ;
    const tick = () => {
      const s = Math.max(0, (Date.now() - since) / 1000), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
      prog.style.strokeDashoffset = circ * (1 - Math.min(1, s / (8 * 3600)));
      label.textContent = `${h}h ${String(m).padStart(2, '0')}m`;
    };
    tick(); setInterval(tick, 15000);
  }


  /* ---------------------------------------------------------------- slide-out panel (stay on the page) */
  const drawer = $('#drawer'), frame = $('#drawer-frame'), backdrop = $('#drawer-backdrop');
  function openDrawer(url, title) {
    if (!drawer) { location.href = url; return; }
    $('#drawer-title').textContent = title || '';
    $('#drawer-loading').hidden = false; frame.style.visibility = 'hidden';
    frame.src = url + (url.includes('?') ? '&' : '?') + 'embed=1';
    drawer.classList.add('open'); drawer.setAttribute('aria-hidden', 'false'); backdrop.hidden = false;
    document.body.classList.add('drawer-open');
  }
  function closeDrawer() {
    if (!drawer) return;
    drawer.classList.remove('open'); drawer.setAttribute('aria-hidden', 'true'); backdrop.hidden = true;
    document.body.classList.remove('drawer-open'); setTimeout(() => { frame.src = 'about:blank'; }, 300);
  }
  if (drawer) {
    frame.addEventListener('load', () => { $('#drawer-loading').hidden = true; frame.style.visibility = 'visible'; });
    document.addEventListener('click', e => {
      const b = e.target.closest('[data-drawer]'); if (b) { e.preventDefault(); $$('.dropdown-menu.show').forEach(m => m.classList.remove('show')); openDrawer(b.dataset.drawer, b.dataset.title || b.textContent.trim()); }
      if (e.target.closest('[data-drawer-close]') || e.target === backdrop) closeDrawer();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && drawer.classList.contains('open')) closeDrawer(); });
    window.addEventListener('message', e => {
      if (e.origin !== location.origin || !e.data) return;
      if (e.data.type === 'medflow:done') {
        closeDrawer(); sessionStorage.setItem('mf-flash', e.data.message || 'Saved.');
        setTimeout(() => location.reload(), 250);   // refresh in place; the open tab is kept in the URL hash
      }
      if (e.data.type === 'medflow:close') closeDrawer();
    });
    const flash = sessionStorage.getItem('mf-flash'); if (flash) { sessionStorage.removeItem('mf-flash'); mfToast(flash); }
  }
  // Inside the panel, "Cancel" closes the panel instead of navigating away.
  if (document.body.classList.contains('embed')) {
    $$('a[href="javascript:history.back()"]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); window.parent.postMessage({type: 'medflow:close'}, location.origin); }));
  }

  /* ---------------------------------------------------------------- pop-up: anonymous case histories and image previews */
  const modal = $('#modal');
  window.mfModal = (title, html) => { if (!modal) return; $('#modal-title').textContent = title; $('#modal-body').innerHTML = html; modal.hidden = false; modal.querySelector('[data-modal-close]').focus(); };
  if (modal) {
    modal.addEventListener('click', e => { if (e.target === modal || e.target.closest('[data-modal-close]')) modal.hidden = true; });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') modal.hidden = true; });
  }
  const sim = $('.similar');
  if (sim) sim.addEventListener('click', async e => {
    const b = e.target.closest('.case'); if (!b) return;
    const res = await fetch(sim.dataset.caseUrl.replace('TOKEN', b.dataset.token) + '?patient=' + sim.dataset.patient, {credentials: 'same-origin'});
    const d = await res.json();
    if (!d.ok) { mfToast(d.error || 'Case not available', 'warning'); return; }
    const FL = {HH: 'crit', LL: 'crit', H: 'abn', L: 'abn', A: 'abn', N: 'ok'};
    mfModal(d.title, `
      <div class="case-head ${d.success ? 'ok' : 'no'}"><span class="case-badge">${d.success ? '<i class="bi bi-check2-circle"></i>' : '<i class="bi bi-dash-circle"></i>'} ${esc(d.outcome)}</span>
        <span>${esc(d.sex)} · ${esc(d.age)}</span>${d.length ? `<span class="muted">Course: ${esc(d.length)}</span>` : ''}</div>
      <p class="mb-2"><b>Diagnosis:</b> ${esc(d.diagnosis)}</p>
      <div class="label-sm mb-1">Treatment</div>
      <ol class="rx-items">${d.medicines.map(m => `<li><span class="med">${esc(m.medicine)}</span><span class="dir">${esc(m.directions)}</span><span class="qty">× ${m.quantity}</span></li>`).join('') || '<li class="muted">No medicines recorded</li>'}</ol>
      ${d.labs.length ? `<div class="label-sm mb-1 mt-3">Lab results</div>${d.labs.map(l => `<div class="small mb-1"><b>${esc(l.test)}</b> <span class="muted">${esc(l.when)}</span><div>${l.values.map(v => `<span class="vchip ${FL[v.flag] || ''}">${esc(v.name)} <b>${esc(v.value)}</b> ${esc(v.unit)}</span>`).join('')}</div></div>`).join('')}` : ''}
      ${d.own ? `<a class="btn btn-sm btn-ink mt-3" href="${esc(d.url)}">Open this visit</a>` : '<p class="form-text mt-3 mb-0">Identity and real dates are withheld. Days are counted from the start of the visit.</p>'}`);
  });
  /* ---------------------------------------------------------------- client-side list filter */
  $$('[data-filter]').forEach(input => {
    const rows = $$(input.dataset.filter);
    input.addEventListener('input', () => {
      const q = input.value.trim().toLowerCase();
      rows.forEach(r => { r.hidden = q && !r.textContent.toLowerCase().includes(q); });
    });
  });
})();
