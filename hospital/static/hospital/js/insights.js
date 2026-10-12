/* Lab insights: interactive body map + clean charts view, both rendered from one JSON payload. */
(() => {
  'use strict';
  const root = document.getElementById('insights');
  if (!root) return;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const csrf = () => ($('meta[name="csrf-token"]') || {}).content || '';
  const DATA = JSON.parse($('#lab-data').textContent);
  DATA.params.forEach(p => { p.latest = p.history[p.history.length - 1]; }); // JSON copies `latest`; re-link it to the history entry
  const SVGNS = 'http://www.w3.org/2000/svg';

  // Marker anchor points and camera boxes on the 400×800 body canvas
  const SPOTS = {
    brain: [200, 58], thyroid: [200, 150], lungs: [160, 250], heart: [214, 268], blood: [86, 336],
    liver: [168, 322], stomach: [244, 332], pancreas: [192, 364], kidneys: [240, 404], bladder: [200, 468],
    reproductive: (window.MF_ANATOMY && window.MF_ANATOMY.reproSpot) || [200, 497], bone: (window.MF_ANATOMY && window.MF_ANATOMY.boneSpot) || [150, 640], immune: [252, 212],
  };   // the bone marker sits where the problem is (spine level, hand, foot or long bone): see anatomy-layers.js
  const SEVERITY = {HH: 4, LL: 4, H: 2, L: 2, A: 2, N: 1, '': 0};
  const FLAG_TEXT = {HH: '▲▲ Critical high', LL: '▼▼ Critical low', H: '▲ High', L: '▼ Low', A: 'Abnormal', N: 'Normal'};
  const flagClass = f => (f === 'HH' || f === 'LL') ? 'crit' : (f === 'H' || f === 'L' || f === 'A') ? 'abn' : f === 'N' ? 'ok' : '';
  const isAbn = f => SEVERITY[f] >= 2;

  /* ------------------------------------------------------------ derived state */
  function systemsSummary() {
    const out = {};
    for (const p of DATA.params) {
      const s = out[p.system] ||= {key: p.system, label: DATA.systems[p.system] || p.system, params: [], worst: '', open: 0, crit: 0};
      s.params.push(p);
      const f = p.latest.flag;
      if (SEVERITY[f] > SEVERITY[s.worst]) s.worst = f;
      if (isAbn(f) && !p.latest.ack) s.open++;
      if (SEVERITY[f] === 4) s.crit++;
    }
    for (const im of (DATA.imaging || [])) {
      const s = out[im.system] ||= {key: im.system, label: DATA.systems[im.system] || im.system, params: [], worst: '', open: 0, crit: 0};
      (s.imaging ||= []).push(im);
      if (im.reported && im.abnormal && SEVERITY.A > SEVERITY[s.worst]) s.worst = 'A';
    }
    for (const s of Object.values(out)) s.params.sort((a, b) => SEVERITY[b.latest.flag] - SEVERITY[a.latest.flag] || a.name.localeCompare(b.name));
    return out;
  }
  let SYS = systemsSummary();

  /* ------------------------------------------------------------ small chart helpers */
  function rangeBar(p) {
    if (p.kind !== 'number' || p.latest.num == null) return '';
    const lo = p.lo ?? 0, hi = p.hi ?? (p.lo != null ? p.lo * 2 : Math.max(1, p.latest.num)), span = (hi - lo) || 1;
    const min = Math.min(lo - span * .6, p.latest.num), max = Math.max(hi + span * .6, p.latest.num);
    const pct = x => ((x - min) / (max - min) * 100).toFixed(1);
    return `<div class="rangebar"><i class="band" style="left:${pct(lo)}%;width:${pct(hi) - pct(lo)}%"></i><i class="pin ${flagClass(p.latest.flag)}" style="left:${pct(p.latest.num)}%"></i></div>`;
  }
  function lineChart(p, w = 300, h = 120, big = true) {
    const pts = p.history.filter(x => x.num != null);
    if (pts.length < 2) return '';
    const vals = pts.map(x => x.num), lo = p.lo, hi = p.hi;
    let min = Math.min(...vals, lo ?? Infinity), max = Math.max(...vals, hi ?? -Infinity);
    const pad = (max - min) * .15 || 1; min -= pad; max += pad;
    const L = big ? 34 : 4, R = 8, T = 8, B = big ? 22 : 4;
    const x = i => L + i * (w - L - R) / (pts.length - 1), y = v => T + (1 - (v - min) / (max - min)) * (h - T - B);
    const band = (lo != null || hi != null) ? `<rect x="${L}" width="${w - L - R}" y="${y(hi ?? max)}" height="${Math.max(0, y(lo ?? min) - y(hi ?? max))}" class="c-band"/>` : '';
    const d = pts.map((pt, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(pt.num).toFixed(1)}`).join(' ');
    const dots = pts.map((pt, i) => `<circle cx="${x(i)}" cy="${y(pt.num)}" r="${big ? 4.5 : 3}" class="c-dot ${flagClass(pt.flag)}"><title>${esc(pt.date)}: ${esc(pt.display)} ${esc(p.unit)}</title></circle>`).join('');
    const axis = big ? `<text x="${L - 6}" y="${y(max - pad) + 4}" class="c-ax" text-anchor="end">${+(max - pad).toFixed(1)}</text><text x="${L - 6}" y="${y(min + pad) + 4}" class="c-ax" text-anchor="end">${+(min + pad).toFixed(1)}</text>` +
      `<text x="${L}" y="${h - 4}" class="c-ax">${esc(pts[0].date.slice(5, 10))}</text><text x="${w - R}" y="${h - 4}" class="c-ax" text-anchor="end">${esc(pts.at(-1).date.slice(5, 10))}</text>` : '';
    const len = pts.length * 200;
    return `<svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="${esc(p.name)} trend">${band}${axis}<path d="${d}" class="c-line" style="stroke-dasharray:${len};stroke-dashoffset:${reduceMotion ? 0 : len}"/>${dots}</svg>`;
  }

  function drawLines(scope) {
    requestAnimationFrame(() => $$('.c-line', scope).forEach(l => { l.style.transition = 'stroke-dashoffset 1.1s cubic-bezier(.2,.8,.2,1)'; l.style.strokeDashoffset = 0; }));
  }

  /* ------------------------------------------------------------ review progress (the "game") */
  function reviewState() {
    const abn = DATA.params.filter(p => isAbn(p.latest.flag));
    return {total: abn.length, done: abn.filter(p => p.latest.ack).length};
  }
  function renderReview(celebrate = false) {
    const {total, done} = reviewState(), circ = 2 * Math.PI * 18, prog = $('#r-prog');
    prog.style.strokeDasharray = circ;
    prog.style.strokeDashoffset = total ? circ * (1 - done / total) : 0;
    $('#review').classList.toggle('complete', total > 0 && done === total);
    $('#review').classList.toggle('none', total === 0);
    $('#r-text').textContent = total ? `${done} of ${total}` : 'Nothing flagged';
    $('#r-sub').textContent = total ? (done === total ? 'All findings reviewed' : 'findings reviewed') : 'all results in range';
    if (celebrate && total && done === total) { window.mfToast?.('All out-of-range results reviewed. Nice work.'); burst($('#review')); }
  }
  function burst(el) { // tiny celebratory particle burst, once
    if (reduceMotion || !el) return;
    const r = el.getBoundingClientRect();
    for (let i = 0; i < 14; i++) {
      const s = document.createElement('i'); s.className = 'spark';
      s.style.left = (r.left + 22) + 'px'; s.style.top = (r.top + r.height / 2) + 'px';
      s.style.setProperty('--dx', (Math.cos(i / 14 * 6.28) * 60) + 'px'); s.style.setProperty('--dy', (Math.sin(i / 14 * 6.28) * 60) + 'px');
      document.body.appendChild(s); setTimeout(() => s.remove(), 900);
    }
  }
  async function acknowledge(valueId, btn) {  // returns a promise so the pop-up can close afterwards
    btn.disabled = true;
    try {
      const res = await fetch(root.dataset.ackUrl.replace('/0/', `/${valueId}/`), {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf()}});
      const j = await res.json(); if (!res.ok) throw new Error();
      DATA.params.forEach(p => p.history.forEach(h => { if (h.value_id === valueId) { h.ack = true; h.ack_by = j.by; } }));
      SYS = systemsSummary(); renderMarkers(); renderReview(true);
      if (current) renderDetail(current, false); else renderOverview();
      renderClean();
    } catch (err) { console.error('ack failed', err); btn.disabled = false; window.mfToast?.('Could not save the review. Try again.', 'error'); }
  }
  root.addEventListener('click', e => { const b = e.target.closest('[data-ack]'); if (b) acknowledge(+b.dataset.ack, b); });

  /* ------------------------------------------------------------ result pop-up: meaning, trend, history, suggested actions */
  function openParam(id) {
    const p = DATA.params.find(x => x.id === id); if (!p) return;
    const KB = window.MFKnowledge || {}, kb = KB[p.code] || {}, f = p.latest.flag;
    const steps = (kb[f] || (isAbn(f) ? (KB._default || {})[f[0]] : null) || []);
    const actions = isAbn(f) && steps.length ? `<div class="label-sm mt-3 mb-1">Suggested next steps</div><ol class="kb-steps">${steps.map(s => `<li>${esc(s)}</li>`).join('')}</ol>` : '';
    const repeat = DATA.open_encounter ? `<button class="btn btn-sm btn-primary" data-drawer="${esc(DATA.lab_new_url)}?encounter=${DATA.open_encounter}&test=${p.test_id}" data-title="Repeat ${esc(p.test)}"><i class="bi bi-arrow-repeat"></i>Repeat ${esc(p.test)}</button>` : '';
    const guide = p.latest.request_id && DATA.guidance_url ? `<a class="btn btn-sm btn-ghost" href="${esc(DATA.guidance_url.replace('/0/', `/${p.latest.request_id}/`))}#guidance-panel"><i class="bi bi-signpost-split"></i>WHO range, sources &amp; AI</a>` : '';
    const ack = isAbn(f) && !p.latest.ack ? `<button class="btn btn-sm btn-ink" data-ack="${p.latest.value_id}"><i class="bi bi-eye"></i>Mark reviewed</button>` : (p.latest.ack ? `<span class="acked"><i class="bi bi-check2-circle"></i> Reviewed by ${esc(p.latest.ack_by)}</span>` : '');
    window.mfModal(`${p.name} · ${p.test}`, `
      <div class="kb-top ${flagClass(f)}"><div><span class="kb-val">${esc(p.latest.display)}</span> <span class="muted">${esc(p.unit)}</span></div><span class="flag ${flagClass(f)}">${FLAG_TEXT[f] || ''}</span><span class="small muted">Reference ${esc(p.range || '—')} · ${esc(p.latest.date)}</span></div>
      ${kb.about ? `<p class="mt-2 mb-1">${esc(kb.about)}</p>` : ''}
      ${rangeBar(p)}
      ${p.history.filter(h => h.num != null).length >= 2 ? `<div class="kb-chart">${lineChart(p, 620, 200, true)}</div>` : ''}
      ${actions}
      <div class="label-sm mt-3 mb-1">History</div>
      <table class="mini-table"><thead><tr><th>Date</th><th>Result</th><th>Flag</th></tr></thead><tbody>${p.history.slice().reverse().map(h => `<tr><td class="small">${esc(h.date)}</td><td><b>${esc(h.display)}</b> ${esc(p.unit)}${h.preliminary ? ' <span class="tag amber">Preliminary</span>' : ''}</td><td><span class="flag ${flagClass(h.flag)}">${FLAG_TEXT[h.flag] || ''}</span></td></tr>`).join('')}</tbody></table>
      <div class="d-flex gap-2 flex-wrap mt-3">${repeat}${guide}${ack}</div>
      <p class="form-text mt-3 mb-0">Suggested steps are general guidance, not a protocol. Follow local guidelines and your clinical judgement.</p>`);
    drawLines(document.getElementById('modal-body'));
  }
  root.addEventListener('click', e => {
    if (e.target.closest('button, a, input, summary')) return;
    const el = e.target.closest('[data-param]'); if (el) openParam(+el.dataset.param);
  });
  root.addEventListener('keydown', e => { const el = e.target.closest('[data-param]'); if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openParam(+el.dataset.param); } });
  document.getElementById('modal')?.addEventListener('click', e => { const b = e.target.closest('[data-ack]'); if (b) { acknowledge(+b.dataset.ack, b).then(() => { document.getElementById('modal').hidden = true; }); } });
  root.addEventListener('click', e => {
    const t = e.target.closest('[data-img]'); if (!t) return;
    const im = (DATA.imaging || []).find(x => x.id === +t.dataset.im);
    window.mfModal?.(`${im.modality} · ${im.region}`, `<div class="lightbox"><img src="${esc(t.dataset.img)}" alt="${esc(im.region)}"></div>${im.impression ? `<p class="mt-2 mb-1"><b>Impression:</b> ${esc(im.impression)}</p>` : ''}<a class="btn btn-sm btn-ink" href="${esc(im.url)}">Open study &amp; viewer</a>`);
  });

  /* ------------------------------------------------------------ body map: markers, organs, blood */
  const svg = $('#body'), markers = $('#markers'), tip = $('#map-tip');
  function renderMarkers() {
    markers.innerHTML = '';
    $$('.org', svg).forEach(o => { const s = SYS[o.dataset.sys]; o.setAttribute('class', `org ${o.classList.contains('beat') ? 'beat' : ''} ${o.classList.contains('breathe') ? 'breathe' : ''} ${s ? 'tested ' + flagClass(s.worst) : 'untested'}`); });
    const blood = SYS.blood;
    $('#vessels').setAttribute('class', `vessels ${blood ? flagClass(blood.worst) : 'idle'}`);
    for (const [key, s] of Object.entries(SYS)) {
      const [x, y] = SPOTS[key] || [200, 400];
      const cls = flagClass(s.worst), n = s.params.filter(p => isAbn(p.latest.flag)).length + (s.imaging || []).filter(i => i.reported && i.abnormal).length;
      const g = document.createElementNS(SVGNS, 'g');
      g.setAttribute('class', `mk ${cls}${s.open ? ' open' : ''}`); g.setAttribute('transform', `translate(${x},${y})`);
      g.setAttribute('tabindex', '0'); g.setAttribute('role', 'button'); g.dataset.sys = key;
      g.setAttribute('aria-label', `${s.label}: ${n ? n + ' out of range' : 'all within range'}`);
      g.innerHTML = `${cls !== 'ok' ? '<circle class="ring" r="13"/><circle class="ring r2" r="13"/>' : ''}<circle class="dot" r="12"/>` +
        (n ? `<text y="4.5" text-anchor="middle">${n}</text>` : `<path d="M-5,0 L-1.5,3.5 L5,-3.5" class="tick"/>`) +
        (s.open === 0 && n && s.params.length ? '<circle class="seen" r="5" cx="10" cy="-10"/><path class="seen-tick" d="M7.5,-10 L9.3,-8.2 L12.5,-11.5"/>' : '') +
        ((s.imaging || []).length ? '<g class="cam" transform="translate(-13,9)"><rect x="-6" y="-4" width="12" height="9" rx="2"/><circle r="2.4" cy=".5"/></g>' : '');
      markers.appendChild(g);
    }
  }
  markers.addEventListener('click', e => { const m = e.target.closest('.mk'); if (m) focusSystem(m.dataset.sys); });
  markers.addEventListener('keydown', e => { const m = e.target.closest('.mk'); if (m && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); focusSystem(m.dataset.sys); } });
  svg.addEventListener('click', e => { const o = e.target.closest('.org.tested'); if (o && !e.target.closest('.mk')) focusSystem(o.dataset.sys); });
  markers.addEventListener('mouseover', e => {
    const m = e.target.closest('.mk'); if (!m) return;
    const s = SYS[m.dataset.sys], top = s.params[0], im = (s.imaging || [])[0];
    tip.innerHTML = `<b>${esc(s.label)}</b>` + (top ? `<span>${esc(top.name)}: <strong class="${flagClass(top.latest.flag)}">${esc(top.latest.display)} ${esc(top.unit)}</strong></span>` : '') +
      (im ? `<span><i class="bi bi-camera"></i> ${esc(im.modality)} · ${esc(im.region)}</span>` : '') + `<small>${s.params.length} value${s.params.length === 1 ? '' : 's'}${im ? ` · ${s.imaging.length} scan${s.imaging.length > 1 ? 's' : ''}` : ''} · click to zoom</small>`;
    const r = m.getBoundingClientRect(), pr = svg.parentElement.getBoundingClientRect();
    tip.style.left = (r.left - pr.left + r.width / 2) + 'px'; tip.style.top = (r.top - pr.top) + 'px'; tip.hidden = false;
  });
  markers.addEventListener('mouseout', e => { if (!e.relatedTarget?.closest?.('.mk')) tip.hidden = true; });

  function seedDroplets() {
    const box = $('#droplets'); box.innerHTML = '';
    if (reduceMotion || !SYS.blood && !DATA.params.length) return;
    $$('#vessels path').forEach((path, vi) => {
      const cells = ((window.MF_ANATOMY || {}).blood || {}).cells || {};   // disease-specific cells (sickle, pale, target, blasts…): see anatomy-layers.js
      const len = path.getTotalLength(), count = Math.max(2, Math.round(len / 90 * (cells.density || 1))), dur = (len / 38).toFixed(1);
      for (let i = 0; i < count; i++) {
        const d = document.createElementNS(SVGNS, 'path');
        const blast = cells.blastEvery && i % cells.blastEvery === 0;
        d.setAttribute('d', blast ? 'M0,-5.5 A5.5,5.5 0 1,1 -0.01,-5.5 Z' : (cells.shape || 'M0,-5 C3,-1.5 3.6,1.4 0,4.2 C-3.6,1.4 -3,-1.5 0,-5 Z'));
        d.setAttribute('class', `drop ${blast ? 'blast' : cells.cls || ''}`);
        const durHr = (dur * ((window.MF_ANATOMY || {}).flowFactor || 1)).toFixed(2);   // faster pulse, faster flow
        d.innerHTML = `<animateMotion dur="${durHr}s" repeatCount="indefinite" rotate="auto" begin="-${(i * dur / count + vi * .37).toFixed(2)}s"><mpath href="#${path.id}"/></animateMotion>`;
        box.appendChild(d);
      }
    });
  }

  /* camera: animate the SVG viewBox toward an organ ("zoom") and back */
  const FULL = [0, 0, 400, 800];
  let vb = FULL.slice(), anim = null;
  function camera(target) {
    cancelAnimationFrame(anim);
    const from = vb.slice(), t0 = performance.now(), D = reduceMotion ? 1 : 650;
    const step = now => {
      const k = Math.min(1, (now - t0) / D), e = k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
      vb = from.map((f, i) => f + (target[i] - f) * e);
      svg.setAttribute('viewBox', vb.map(v => v.toFixed(2)).join(' '));
      if (k < 1) anim = requestAnimationFrame(step);
    };
    anim = requestAnimationFrame(step);
  }
  let current = null;
  function focusSystem(key) {
    if (!SYS[key]) return;
    current = key; tip.hidden = true;
    const [x, y] = SPOTS[key];
    camera([x - 85, y - 120, 170, 240]);
    $$('.mk', svg).forEach(m => m.classList.toggle('dim', m.dataset.sys !== key));
    $$('.org', svg).forEach(o => o.classList.toggle('focus', o.dataset.sys === key));
    $('#zoom-out').hidden = false;
    renderDetail(key, true);
  }
  function zoomOut() {
    current = null; camera(FULL);
    $$('.mk', svg).forEach(m => m.classList.remove('dim')); $$('.org', svg).forEach(o => o.classList.remove('focus'));
    $('#zoom-out').hidden = true; renderOverview();
  }
  $('#zoom-out').addEventListener('click', zoomOut);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && current) zoomOut(); });

  /* ------------------------------------------------------------ side panel */
  const detail = $('#detail');
  function paramRow(p, withChart) {
    const f = p.latest.flag, cls = flagClass(f);
    const ack = isAbn(f) ? (p.latest.ack ? `<span class="acked"><i class="bi bi-check2-circle"></i> Reviewed by ${esc(p.latest.ack_by)}</span>` : `<button class="btn btn-sm btn-ink" data-ack="${p.latest.value_id}"><i class="bi bi-eye"></i>Mark reviewed</button>`) : '';
    return `<div class="prow ${cls}" data-param="${p.id}" role="button" tabindex="0" title="Open details">
      <div class="prow-top"><span class="pname">${esc(p.name)}<small>${esc(p.test)}</small></span>
        <span class="pval"><b>${esc(p.latest.display)}</b> <small>${esc(p.unit)}</small></span></div>
      <div class="prow-mid"><span class="flag ${cls}">${FLAG_TEXT[f] || ''}</span><span class="small muted">Ref ${esc(p.range || '—')}</span>${p.latest.preliminary ? '<span class="tag amber">Preliminary</span>' : ''}<span class="small muted ms-auto">${esc(p.latest.date)}</span></div>
      ${rangeBar(p)}${withChart ? lineChart(p, 300, 90, false) : ''}
      ${ack ? `<div class="prow-ack">${ack}</div>` : ''}
    </div>`;
  }
  function imagingCard(im) {
    const thumbs = im.images.slice(0, 4).map((img, i) => `<button class="im-thumb" data-img="${esc(img.url)}" data-im="${im.id}" aria-label="View image ${i + 1}"><img src="${esc(img.url)}" alt="${esc(img.caption || im.region)}" loading="lazy"></button>`).join('');
    return `<div class="im-card ${im.reported && im.abnormal ? 'abn' : ''}"><div class="d-flex gap-2 align-items-baseline"><b>${esc(im.modality)} · ${esc(im.region)}</b>${im.reported ? (im.abnormal ? '<span class="flag abn">Abnormal</span>' : '<span class="flag ok">Normal</span>') : '<span class="tag amber">Awaiting report</span>'}<a class="small ms-auto" href="${esc(im.url)}">Open</a></div>
      ${thumbs ? `<div class="im-thumbs">${thumbs}</div>` : ''}${im.impression ? `<p class="small mb-1 mt-2">${esc(im.impression)}</p>` : ''}
      ${(im.measurements || []).map(m => `<span class="vchip ${m.abnormal ? 'abn' : 'ok'}">${esc(m.label)} <b>${esc(m.value)}</b> ${esc(m.unit)}</span>`).join('')}<div class="small muted mt-1">${esc(im.date)}</div></div>`;
  }
  function renderDetail(key, animate) {
    const s = SYS[key], art = window.MedFlowOrgans ? window.MedFlowOrgans.render(key, DATA.params, s.label) : null;  // all results: e.g. potassium (a kidney test) shapes the heart rhythm
    detail.innerHTML = `<div class="${animate && !reduceMotion ? 'zoom-in' : ''}">
      <div class="d-head ${flagClass(s.worst)}"><span class="d-icon"></span><div><h2>${esc(s.label)}</h2><span class="small muted">${s.params.length} value${s.params.length === 1 ? '' : 's'}${(s.imaging || []).length ? ` · ${s.imaging.length} scan${s.imaging.length > 1 ? 's' : ''}` : ''}${s.crit ? ` · <b class="text-danger">${s.crit} critical</b>` : ''}</span></div>
      <button class="btn btn-sm btn-ghost ms-auto" data-close aria-label="Back to all systems"><i class="bi bi-x-lg"></i></button></div>
      ${art ? `<figure class="organ-art">${art.svg}<figcaption><div class="oa-caption" aria-live="polite">Tap a part of the illustration to learn what it does.</div>${art.notes.map(n => `<span class="oa-note">${esc(n)}</span>`).join('')}</figcaption></figure>` : ''}
      ${(s.imaging || []).map(imagingCard).join('')}
      ${s.params.map(p => paramRow(p, true)).join('')}</div>`;
    detail.querySelector('[data-close]').addEventListener('click', zoomOut);
    if (art) {
      const cap = detail.querySelector('.oa-caption');
      const show = el => { const k = el.dataset.part; cap.textContent = art.parts[k] || el.getAttribute('aria-label'); detail.querySelectorAll('.oa-part').forEach(p => p.classList.toggle('picked', p.dataset.part === k)); };
      detail.querySelectorAll('.oa-part').forEach(el => { el.addEventListener('click', () => show(el)); el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); show(el); } }); });
      if (art.mount) art.mount(detail.querySelector('.organ-art'), text => { cap.textContent = text; });   // e.g. the 3D heart builds itself in the panel
    }
    drawLines(detail);
  }
  function renderOverview() {
    const list = Object.values(SYS).sort((a, b) => SEVERITY[b.worst] - SEVERITY[a.worst]);
    const untested = Object.keys(DATA.systems).filter(k => !SYS[k]);
    detail.innerHTML = !DATA.params.length && !(DATA.imaging || []).length ? `<div class="empty"><i class="bi bi-droplet"></i>No resulted lab tests for this patient yet. Results appear here once the lab submits them.</div>` :
      `<div class="panel-head"><h2>Body systems</h2><span class="hint">Click a marker or a row</span></div>
      <ul class="plain sys-list">${list.map(s => `<li><button class="sys ${flagClass(s.worst)}" data-sys="${s.key}"><span class="sdot"></span><span><b>${esc(s.label)}</b><small>${s.params.length} value${s.params.length === 1 ? '' : 's'}${(s.imaging || []).length ? ` · ${s.imaging.length} scan${s.imaging.length > 1 ? 's' : ''}` : ''}${s.open ? ` · ${s.open} to review` : ''}</small></span><span class="flag ${flagClass(s.worst)}">${isAbn(s.worst) ? (SEVERITY[s.worst] === 4 ? 'Critical' : 'Out of range') : 'In range'}</span></button></li>`).join('')}</ul>
      ${untested.length ? `<p class="small muted mt-3 mb-0">Not tested: ${untested.map(k => esc(DATA.systems[k])).join(', ')}</p>` : ''}`;
    $$('.sys', detail).forEach(b => b.addEventListener('click', () => focusSystem(b.dataset.sys)));
  }

  /* ------------------------------------------------------------ clean view */
  let catFilter = '';
  function renderClean() {
    const params = DATA.params.filter(p => !catFilter || p.category === catFilter);
    const abn = params.filter(p => isAbn(p.latest.flag)), crit = abn.filter(p => SEVERITY[p.latest.flag] === 4);
    $('#kpis').innerHTML = [
      ['Tests resulted', DATA.orders.length, ''], ['Values measured', params.length, ''], ['Out of range', abn.length, abn.length ? 'abn' : ''],
      ['Critical', crit.length, crit.length ? 'crit' : ''], ['Still to review', abn.filter(p => !p.latest.ack).length, ''],
    ].map(([l, v, c]) => `<div class="kpi ${c}"><b>${v}</b><span>${l}</span></div>`).join('');
    const cats = [...new Set(DATA.params.map(p => p.category))];
    $('#cat-chips').innerHTML = `<button class="chip ${catFilter ? '' : 'on'}" data-cat="">All categories</button>` + cats.map(c => {
      const col = DATA.params.find(p => p.category === c).color;
      return `<button class="chip ${catFilter === c ? 'on' : ''}" data-cat="${esc(c)}"><span class="cat-dot" style="background:${esc(col)}"></span>${esc(c)}</button>`;
    }).join('');
    const bySev = (a, b) => SEVERITY[b.latest.flag] - SEVERITY[a.latest.flag];
    const open = abn.filter(p => !p.latest.ack).sort(bySev), seen = abn.filter(p => p.latest.ack).sort(bySev);
    $('#flagged').innerHTML = !abn.length ? '<div class="empty"><i class="bi bi-check2-circle"></i>Everything is within its reference range.</div>' :
      (open.length ? open.map(p => paramRow(p, false)).join('') : '<div class="alert-mf info mb-3"><i class="bi bi-check2-all"></i><div>All out-of-range results have been reviewed.</div></div>') +
      (seen.length ? `<details class="seen-group"><summary>Reviewed (${seen.length})</summary>${seen.map(p => paramRow(p, false)).join('')}</details>` : '');
    const trend = params.filter(p => p.history.filter(h => h.num != null).length >= 2);
    $('#trends').innerHTML = trend.length ? trend.map(p => `<div class="trend ${flagClass(p.latest.flag)}" data-param="${p.id}" role="button" tabindex="0" title="Open details"><div class="d-flex align-items-baseline gap-2"><b>${esc(p.name)}</b><span class="small muted">${esc(p.test)}</span><span class="ms-auto tval">${esc(p.latest.display)} <small>${esc(p.unit)}</small></span></div>${lineChart(p)}</div>`).join('')
      : '<div class="empty">Trends appear once a test has been done at least twice.</div>';
    drawLines($('#trends'));
    const ims = DATA.imaging || [];
    $('#imaging-panel').hidden = !ims.length;
    $('#imaging-list').innerHTML = ims.map(imagingCard).join('');
    const orders = DATA.orders.filter(o => !catFilter || o.category === catFilter);
    $('#orders').innerHTML = orders.length ? orders.map(o => `<div class="order-row" data-text="${esc((o.test + ' ' + o.values.map(v => v.name).join(' ')).toLowerCase())}">
      <div class="o-head"><span class="cat-dot" style="background:${esc(o.color)}"></span><b>${esc(o.test)}</b><span class="small muted">${esc(o.category)}</span><span class="tag ${o.status === 'Verified' ? 'teal' : 'amber'} ms-auto">${esc(o.status)}</span><span class="small muted">${esc(o.date)}</span></div>
      <div class="o-vals">${o.values.map(v => `<span class="vchip ${flagClass(v.flag)}" title="Ref ${esc(v.range)}">${esc(v.name)} <b>${esc(v.display)}</b> ${esc(v.unit)}</span>`).join('')}</div>
      ${o.comment ? `<div class="small muted mt-1">${esc(o.comment)}</div>` : ''}</div>`).join('') : '<div class="empty">No results.</div>';
  }
  $('#cat-chips').addEventListener('click', e => { const c = e.target.closest('[data-cat]'); if (c) { catFilter = c.dataset.cat; renderClean(); } });
  $('#res-filter').addEventListener('input', e => { const q = e.target.value.trim().toLowerCase(); $$('.order-row').forEach(r => { r.hidden = q && !r.dataset.text.includes(q); }); });

  /* ------------------------------------------------------------ view switch (remembered per clinician) */
  function setView(v, save) {
    $$('.seg button').forEach(b => b.classList.toggle('on', b.dataset.view === v));
    $$('[data-pane-view]').forEach(p => p.classList.toggle('on', p.dataset.paneView === v));
    if (v === 'clean') renderClean();
    if (save) fetch(root.dataset.viewUrl, {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf()}, body: new URLSearchParams({view: v})}).catch(() => {});
  }
  $$('.seg button').forEach(b => b.addEventListener('click', () => setView(b.dataset.view, true)));

  renderMarkers(); seedDroplets(); renderOverview(); renderReview(false);
  setView(root.dataset.initialView === 'clean' ? 'clean' : 'body', false);
  const firstCrit = Object.values(SYS).find(s => SEVERITY[s.worst] === 4 && s.open);
  if (firstCrit && root.dataset.initialView !== 'clean') {   // fly to the most urgent finding, unless the doctor has already chosen something
    const auto = setTimeout(() => { if (!current) focusSystem(firstCrit.key); }, reduceMotion ? 0 : 900);
    ['pointerdown', 'keydown'].forEach(ev => root.addEventListener(ev, () => clearTimeout(auto), {once: true}));
  }
})();
