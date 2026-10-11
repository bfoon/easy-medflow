/* Health intelligence dashboard: interactive SVG charts from one JSON payload. */
(() => {
  'use strict';
  const D = JSON.parse(document.getElementById('health-data').textContent), root = document.getElementById('hd');
  const EX = (q) => '/health/explore/?days=' + D.days + q;

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const COLORS = ['#0F7B78', '#C8323F', '#4A5FC1', '#E0912A', '#8A4A8F', '#0E7490', '#5E7D2B', '#B85C46'];
  const last = a => a.filter(x => x != null).slice(-1)[0];
  const avg = a => { const v = a.filter(x => x != null); return v.length ? Math.round(v.reduce((s, x) => s + x, 0) / v.length) : null; };
  const kpi = (v, l, cls = '') => `<div class="kpi ${cls}"><b>${v ?? '—'}</b><span>${esc(l)}</span></div>`;
  const occ = D.beds.total ? Math.round(D.beds.occupied * 100 / D.beds.total) : 0;
  root.innerHTML = `
    <div class="advice">${D.advice.map(a => `<div class="adv ${a.level}"><i class="bi ${a.level === 'danger' ? 'bi-megaphone-fill' : a.level === 'warn' ? 'bi-exclamation-triangle-fill' : a.level === 'ok' ? 'bi-check-circle-fill' : 'bi-lightbulb-fill'}"></i><div><b>${esc(a.title)}</b><p>${esc(a.text)}</p></div></div>`).join('')}</div>
    <div class="kpis hd-kpis">${kpi(D.visits, `visits in ${D.days} days`)}${kpi(D.patients, 'different patients')}${kpi(last(D.positivity) != null ? last(D.positivity) + '%' : '—', 'malaria tests positive (this week)', last(D.positivity) >= 40 ? 'abn' : '')}
      ${kpi(occ + '%', `beds occupied (${D.beds.occupied}/${D.beds.total})`, occ >= 85 ? 'abn' : '')}${kpi(D.abx_rate + '%', 'visits with an antibiotic')}${kpi(avg(D.waits.slice(-7)) != null ? avg(D.waits.slice(-7)) + ' min' : '—', 'average wait (7 days)')}</div>
    <div class="grid g-main">
      <div class="stack">
        <section class="panel"><div class="panel-head"><h2>Disease trends</h2><span class="hint">Visits per week by diagnosis · click to show or hide</span><a class="more" href="${EX('')}">Explore all data →</a></div><div class="legend-chips" id="legend"></div><div class="chart-wrap" id="trend"></div></section>
        <div class="grid g-2">
          <section class="panel"><div class="panel-head"><h2>Malaria positivity</h2><span class="hint">${D.rdt_total} tests</span></div><div id="pos"></div></section>
          <section class="panel"><div class="panel-head"><h2>Admissions</h2><span class="hint">per week</span></div><div id="adm"></div></section>
        </div>
        <section class="panel"><div class="panel-head"><h2>Where patients come from</h2><span class="hint">Click a town to explore</span></div><div id="hmap"></div><div id="towns" class="mt-3"></div></section>
      </div>
      <div class="stack">
        ${D.signals.length ? `<section class="panel signals"><div class="panel-head"><h2><i class="bi bi-broadcast"></i> Outbreak signals</h2></div>${D.signals.map(s => `<div class="sig"><a href="${EX('&dx=' + encodeURIComponent(D.diagnoses.find(d => d.label === s.label)?.key || ''))}"><b>${esc(s.label)}</b></a><span>${s.recent} this week vs ${s.baseline}/week</span><em>+${s.change}%</em></div>`).join('')}</section>` : ''}
        <section class="panel"><div class="panel-head"><h2>Who we see</h2><span class="hint">Age and sex</span></div><div id="pyr"></div></section>
        <section class="panel"><div class="panel-head"><h2>How patients did</h2><span class="hint">Resolved or improved</span></div><div id="out"></div></section>
        <section class="panel"><div class="panel-head"><h2>Waiting time</h2><span class="hint">minutes to be called, 14 days</span></div><div id="wait"></div></section>
        <section class="panel"><div class="panel-head"><h2>Chronic disease</h2></div><div class="chronic">
          <div><b>${D.chronic.hypertension}</b><span>hypertension</span></div><div><b>${D.chronic.diabetes}</b><span>diabetes</span></div>
          <div><b>${D.chronic.a1c_tested ? Math.round(D.chronic.a1c_controlled * 100 / D.chronic.a1c_tested) + '%' : '—'}</b><span>diabetes controlled (HbA1c &lt; 7%)</span></div></div>
          ${D.resp_abx != null ? `<p class="small mt-3 mb-0"><b>${D.resp_abx}%</b> of respiratory infection visits got an antibiotic.</p>` : ''}</section>
      </div>
    </div>`;

  /* ---------- interactive multi-line trend */
  const hidden = new Set();
  function trend() {
    const W = 760, H = 260, L = 34, R = 12, T = 12, B = 28, n = D.weeks.length;
    const series = D.diagnoses.filter(d => !hidden.has(d.key));
    const max = Math.max(1, ...series.flatMap(d => d.series));
    const x = i => L + i * (W - L - R) / Math.max(1, n - 1), y = v => T + (1 - v / max) * (H - T - B);
    let g = '';
    for (let k = 0; k <= 4; k++) { const v = Math.round(max * k / 4); g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="grid-l"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end" class="c-ax">${v}</text>`; }
    D.weeks.forEach((w, i) => { if (i % Math.ceil(n / 8) === 0) g += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" class="c-ax">${esc(w)}</text>`; });
    const lines = D.diagnoses.map((d, di) => hidden.has(d.key) ? '' : `<path d="${d.series.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')}" class="t-line" stroke="${COLORS[di % 8]}"/>`).join('');
    document.getElementById('trend').innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="chart t-chart">${g}${lines}<line id="hover-l" y1="${T}" y2="${H - B}" class="hover-l" hidden/><rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent" id="hover-r"/></svg><div class="t-tip" id="t-tip" hidden></div>`;
    document.querySelectorAll('.t-line').forEach(p => { const len = p.getTotalLength(); p.style.strokeDasharray = len; p.style.strokeDashoffset = len; requestAnimationFrame(() => { p.style.transition = 'stroke-dashoffset 1.2s ease'; p.style.strokeDashoffset = 0; }); });
    const svg = document.querySelector('.t-chart'), tip = document.getElementById('t-tip'), hl = document.getElementById('hover-l');
    document.getElementById('hover-r').addEventListener('mousemove', e => {
      const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY; const sp = pt.matrixTransform(svg.getScreenCTM().inverse());
      const i = Math.max(0, Math.min(n - 1, Math.round((sp.x - L) / ((W - L - R) / Math.max(1, n - 1)))));
      hl.setAttribute('x1', x(i)); hl.setAttribute('x2', x(i)); hl.hidden = false;
      tip.innerHTML = `<b>Week of ${esc(D.weeks[i])}</b>` + series.map(d => `<div><i style="background:${COLORS[D.diagnoses.indexOf(d) % 8]}"></i>${esc(d.label)} <b>${d.series[i]}</b></div>`).join('');
      tip.hidden = false; tip.style.left = Math.min(e.offsetX + 16, svg.clientWidth - 180) + 'px'; tip.style.top = (e.offsetY + 10) + 'px';
    });
    document.getElementById('hover-r').addEventListener('mouseleave', () => { tip.hidden = true; hl.hidden = true; });
  }
  document.getElementById('legend').innerHTML = D.diagnoses.map((d, i) => `<span class="lchip-wrap"><button class="lchip" data-k="${esc(d.key)}" style="--c:${COLORS[i % 8]}"><i></i>${esc(d.label)} <span>${d.n}</span></button><a class="lchip-go" href="${EX('&dx=' + encodeURIComponent(d.key))}" title="Explore ${esc(d.label)}" aria-label="Explore ${esc(d.label)}"><i class="bi bi-box-arrow-in-right"></i></a></span>`).join('') || '<span class="muted small">No diagnoses recorded in this period.</span>';
  document.getElementById('legend').addEventListener('click', e => { const b = e.target.closest('.lchip'); if (!b) return; hidden.has(b.dataset.k) ? hidden.delete(b.dataset.k) : hidden.add(b.dataset.k); b.classList.toggle('off'); trend(); });
  trend();

  /* ---------- bars helper */
  const bars = (el, vals, labels, opt = {}) => {
    const W = 360, H = 150, B = 22, n = vals.length, max = Math.max(1, opt.max || 0, ...vals.map(v => v ?? 0)), bw = (W - 10) / n;
    document.getElementById(el).innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="chart">${opt.line != null ? `<line x1="0" x2="${W}" y1="${(1 - opt.line / max) * (H - B)}" y2="${(1 - opt.line / max) * (H - B)}" class="warn-l"/><text x="${W - 2}" y="${(1 - opt.line / max) * (H - B) - 4}" text-anchor="end" class="c-ax">${opt.line}${opt.unit || ''}</text>` : ''}
      ${vals.map((v, i) => v == null ? '' : `<rect x="${5 + i * bw + bw * .15}" width="${bw * .7}" y="${(1 - v / max) * (H - B)}" height="${v / max * (H - B)}" rx="3" class="hb ${opt.bad && v >= opt.bad ? 'bad' : ''}" style="animation-delay:${i * 30}ms"><title>${esc(labels[i])}: ${v}${opt.unit || ''}</title></rect>`).join('')}
      ${labels.map((l, i) => i % Math.ceil(n / 6) === 0 ? `<text x="${5 + i * bw + bw / 2}" y="${H - 6}" text-anchor="middle" class="c-ax">${esc(l)}</text>` : '').join('')}</svg>`;
  };
  bars('pos', D.positivity, D.weeks, {max: 100, line: 40, unit: '%', bad: 40});
  bars('adm', D.admissions, D.weeks);
  bars('wait', D.waits, D.wait_days, {unit: ' min', line: 45, bad: 45});

  /* ---------- age / sex pyramid */
  const bands = ['0–9', '10–19', '20–29', '30–39', '40–49', '50–59', '60–69', '70–79', '80+'];
  const pmax = Math.max(1, ...D.pyramid.M, ...D.pyramid.F);
  document.getElementById('pyr').innerHTML = `<div class="pyr"><div class="pyr-h"><span>Male</span><span></span><span>Female</span></div>${bands.map((b, i) => i).reverse().map(i => `<div class="pyr-row"><div class="pym"><i style="--w:${D.pyramid.M[i] * 100 / pmax}%" title="${D.pyramid.M[i]} male, ${bands[i]}"></i><em>${D.pyramid.M[i] || ''}</em></div><span>${bands[i]}</span><div class="pyf"><i style="--w:${D.pyramid.F[i] * 100 / pmax}%" title="${D.pyramid.F[i]} female, ${bands[i]}"></i><em>${D.pyramid.F[i] || ''}</em></div></div>`).join('')}</div>`;

  /* ---------- towns heat list */
  const tmax = Math.max(1, ...D.towns.map(t => t.patients));
  document.getElementById('towns').innerHTML = D.towns.map(t => `<div class="town"><a href="${EX('&town=' + encodeURIComponent(t.town))}">${esc(t.town)}</a><div class="tbar"><i style="--w:${t.patients * 100 / tmax}%"></i><b style="--w:${t.malaria * 100 / tmax}%" title="${t.malaria} malaria"></b></div><em>${t.patients}${t.malaria ? ` · <span class="text-danger">${t.malaria} malaria</span>` : ''}</em></div>`).join('') || '<p class="muted small">No addresses recorded.</p>';

  /* ---------- outcomes */
  document.getElementById('out').innerHTML = D.outcomes.map(o => `<div class="mb-2"><div class="d-flex small"><span>${esc(o.label)}</span><span class="ms-auto"><b>${o.rate}%</b> of ${o.n}</span></div><div class="meter ${o.rate < 60 ? 'red' : o.rate < 80 ? 'amber' : ''}"><i style="--w:${o.rate}%"></i></div></div>`).join('') || '<p class="muted small mb-0">Not enough completed visits with outcomes.</p>';
})();

/* real map on the dashboard */
(() => { const D = JSON.parse(document.getElementById('health-data').textContent), el = document.getElementById('hmap');
  if (el) el.innerHTML = `<iframe class="real-map" src="/health/map/?days=${D.days}" title="Map of patients by location" loading="lazy"></iframe><div class="small muted mt-1">Street map © OpenStreetMap contributors. <a href="/health/locations/">Manage locations</a></div>`; })();
