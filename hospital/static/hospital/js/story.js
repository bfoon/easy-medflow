/* Health story player: replays the record in time order. */
(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const EV = JSON.parse($('#story-data').textContent), SYS = JSON.parse($('#story-systems').textContent);
  if (!EV.length) { $('#s-card').innerHTML = '<div class="empty">No records yet.</div>'; return; }
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const SPOTS = {brain: [200, 58], thyroid: [200, 150], lungs: [160, 250], heart: [214, 268], blood: [118, 322], liver: [168, 322], stomach: [244, 332],
    pancreas: [192, 364], kidneys: [240, 404], bladder: [200, 468], reproductive: [200, 497], bone: [168, 640], immune: [252, 212]};
  const KIND = {visit: ['bi-clipboard2-pulse', 'Visit', '#0F7B78'], lab: ['bi-droplet-half', 'Lab results', '#4A5FC1'], rx: ['bi-capsule', 'Prescription', '#E0912A'],
    imaging: ['bi-radioactive', 'Imaging', '#0E7490'], admission: ['bi-hospital', 'Admission', '#C8323F'], referral: ['bi-signpost-split', 'Referral', '#8A4A8F'], allergy: ['bi-exclamation-triangle', 'Allergy', '#C8323F']};
  const t0 = new Date(EV[0].t).getTime(), t1 = Date.now(), span = Math.max(1, t1 - t0);
  const pos = t => (new Date(t).getTime() - t0) / span * 100;                 // real time: used by the trend charts
  const slot = i => EV.length === 1 ? 100 : 1 + i / (EV.length - 1) * 98;     // one equal slot per event: used by the scrubber
  // spots on the body
  const spots = $('#s-spots');
  spots.innerHTML = Object.entries(SPOTS).map(([k, [x, y]]) => `<g class="sp" data-sys="${k}" transform="translate(${x},${y})"><circle class="halo" r="14"/><circle class="core" r="7"/><title>${esc(SYS[k] || k)}</title></g>`).join('');
  // ticks on the scrubber
  $('#s-ticks').innerHTML = EV.map((e, i) => `<i class="tick" data-i="${i}" style="left:${slot(i)}%;background:${KIND[e.kind][2]}" title="${esc(KIND[e.kind][1])}: ${esc(e.title)}"></i>`).join('');
  $('#s-first').textContent = new Date(EV[0].t).toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'});
  // which lab values to chart: the 3 measured most often
  const counts = {};
  EV.filter(e => e.kind === 'lab').forEach(e => e.values.forEach(v => { if (v.num != null) counts[v.code] = (counts[v.code] || 0) + 1; }));
  const chartCodes = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 3).map(x => x[0]);
  const series = Object.fromEntries(chartCodes.map(c => [c, []]));
  const meta = {};
  let idx = -1, playing = false, speed = 1, timer = null;
  const heat = {};
  function drawCharts() {
    $('#s-charts').innerHTML = chartCodes.map(c => {
      const pts = series[c], m = meta[c] || {name: c, unit: ''};
      const W = 300, H = 110, L = 6, R = 6, T = 10, B = 16;
      const all = pts.map(p => p.v).concat([m.lo, m.hi].filter(x => x != null));
      let lo = Math.min(...all, 0), hi = Math.max(...all, 1); const pad = (hi - lo) * .15 || 1; lo -= pad; hi += pad;
      const x = t => L + pos(t) / 100 * (W - L - R), y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
      const band = m.lo != null || m.hi != null ? `<rect x="${L}" width="${W - L - R}" y="${y(m.hi ?? hi)}" height="${Math.max(0, y(m.lo ?? lo) - y(m.hi ?? hi))}" class="c-band"/>` : '';
      const path = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ');
      const last = pts[pts.length - 1];
      return `<div class="panel story-chart"><div class="d-flex"><b>${esc(m.name)}</b><span class="ms-auto ${last && last.bad ? 'text-danger fw-bold' : ''}">${last ? esc(last.label) : '—'} <small class="muted">${esc(m.unit)}</small></span></div>
        <svg viewBox="0 0 ${W} ${H}" class="chart">${band}<path d="${path}" class="c-line"/>${pts.map(p => `<circle cx="${x(p.t)}" cy="${y(p.v)}" r="3.5" class="c-dot ${p.bad ? 'crit' : ''}"/>`).join('')}</svg></div>`;
    }).join('');
  }
  function light(sys, bad) {
    if (!sys) return;
    heat[sys] = bad ? 'bad' : (heat[sys] === 'bad' ? 'bad' : 'ok');
    const g = spots.querySelector(`[data-sys="${sys}"]`); if (!g) return;
    g.setAttribute('class', `sp on ${heat[sys]}`); g.classList.remove('pulse'); void g.getBoundingClientRect(); g.classList.add('pulse');
  }
  function card(e) {
    const [icon, label, color] = KIND[e.kind];
    let body = '';
    if (e.kind === 'visit') body = `${e.detail ? `<p class="mb-1"><b>${esc(e.detail)}</b></p>` : ''}${e.dept ? `<div class="small muted">${esc(e.dept)}</div>` : ''}${Object.keys(e.vitals).length ? `<div class="vitals mt-2">${Object.entries(e.vitals).map(([k, v]) => `<div class="vital"><span>${esc({bp: 'BP', heart_rate: 'Pulse', temperature_c: 'Temp', spo2: 'SpO₂'}[k])}</span><b>${esc(v)}</b></div>`).join('')}</div>` : ''}${e.outcome ? `<span class="tag teal mt-2">Outcome: ${esc(e.outcome)}</span>` : ''}`;
    if (e.kind === 'lab') body = `<div>${e.values.map(v => `<span class="vchip ${['HH', 'LL'].includes(v.flag) ? 'crit' : ['H', 'L', 'A'].includes(v.flag) ? 'abn' : 'ok'}">${esc(v.name)} <b>${esc(v.value)}</b> ${esc(v.unit)}</span>`).join('')}</div>`;
    if (e.kind === 'rx') body = `<ol class="rx-items">${e.lines.map(l => `<li>${esc(l)}</li>`).join('')}</ol>`;
    if (e.kind === 'imaging') body = `${e.image ? `<img class="story-img" src="${esc(e.image)}" alt="${esc(e.title)}">` : ''}${e.detail ? `<p class="mt-2 mb-0 ${e.abnormal ? 'text-danger fw-semibold' : ''}">${esc(e.detail)}</p>` : ''}`;
    if (['admission', 'referral', 'allergy'].includes(e.kind)) body = `<p class="mb-0">${esc(e.detail || '')}</p>`;
    $('#s-card').innerHTML = `<div class="story-ev ${reduce ? '' : 'enter'}" style="--k:${color}"><div class="d-flex align-items-center gap-2"><span class="ev-ic"><i class="bi ${icon}"></i></span><span class="small fw-bold" style="color:${color}">${label}</span>${e.url ? `<a class="small ms-auto" href="${esc(e.url)}">Open</a>` : ''}</div><h2>${esc(e.title)}</h2>${body}</div>`;
  }
  function apply(i) {
    const e = EV[i];
    if (e.kind === 'lab') e.values.forEach(v => {
      light(v.system, ['H', 'L', 'HH', 'LL', 'A'].includes(v.flag));
      if (series[v.code] && v.num != null) { series[v.code].push({t: e.t, v: v.num, label: v.value, bad: ['H', 'L', 'HH', 'LL', 'A'].includes(v.flag)}); meta[v.code] = {name: v.name, unit: v.unit, lo: v.lo, hi: v.hi}; }
    });
    if (e.kind === 'imaging') light(e.system, e.abnormal);
    if (e.kind === 'admission') light('blood', false);
  }
  function goto(target) {   // rebuild state up to the target event so scrubbing backwards works
    target = Math.max(0, Math.min(EV.length - 1, target));
    Object.values(series).forEach(a => a.length = 0); Object.keys(heat).forEach(k => delete heat[k]);
    spots.querySelectorAll('.sp').forEach(g => g.setAttribute('class', 'sp'));
    for (let i = 0; i <= target; i++) apply(i);
    idx = target; card(EV[idx]); drawCharts();
    const d = new Date(EV[idx].t);
    $('#s-date').textContent = d.toLocaleDateString(undefined, {weekday: 'short', day: 'numeric', month: 'long', year: 'numeric'});
    $('#s-fill').style.width = slot(idx) + '%'; $('#s-idx').textContent = idx + 1;
    document.querySelectorAll('.tick').forEach(t => t.classList.toggle('past', +t.dataset.i <= idx));
  }
  function step() { if (idx >= EV.length - 1) { pause(); return; } goto(idx + 1); timer = setTimeout(step, 1700 / speed); }
  function play() { if (idx >= EV.length - 1) idx = -1; playing = true; $('#s-play').innerHTML = '<i class="bi bi-pause-fill"></i>'; step(); }
  function pause() { playing = false; clearTimeout(timer); $('#s-play').innerHTML = '<i class="bi bi-play-fill"></i>'; }
  $('#s-play').addEventListener('click', () => playing ? pause() : play());
  $('#s-next').addEventListener('click', () => { pause(); goto(idx + 1); });
  $('#s-prev').addEventListener('click', () => { pause(); goto(idx - 1); });
  document.querySelectorAll('[data-speed]').forEach(b => b.addEventListener('click', () => { speed = +b.dataset.speed; document.querySelectorAll('[data-speed]').forEach(x => x.classList.toggle('on', x === b)); }));
  $('#s-scrub').addEventListener('click', e => {
    const r = e.currentTarget.getBoundingClientRect(), pct = (e.clientX - r.left) / r.width * 100;
    pause(); goto(Math.round((pct - 1) / 98 * (EV.length - 1)));
  });
  document.addEventListener('keydown', e => { if (e.target.closest('input,textarea,select')) return; if (e.key === ' ') { e.preventDefault(); playing ? pause() : play(); } if (e.key === 'ArrowRight') { pause(); goto(idx + 1); } if (e.key === 'ArrowLeft') { pause(); goto(idx - 1); } });
  drawCharts();
})();
