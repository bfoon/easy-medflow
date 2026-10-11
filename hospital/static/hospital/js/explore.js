/* Drill-down explorer: every element updates the URL filters and reloads the slice. */
(() => {
  'use strict';
  const D = JSON.parse(document.getElementById('explore-data').textContent), F = D.filters, S = D.summary;
  const {esc, calendar, donut} = window.MFCharts;
  const go = changes => { const q = new URLSearchParams(location.search); Object.entries(changes).forEach(([k, v]) => v === '' || v == null ? q.delete(k) : q.set(k, v)); location.search = q.toString(); };
  const chip = (label, key) => `<button class="fchip" data-clear="${key}">${esc(label)} <i class="bi bi-x"></i></button>`;
  const active = [F.dx && chip('Diagnosis: ' + F.dx_label, 'dx'), F.town && chip('Town: ' + F.town, 'town'), F.age_label && chip('Age ' + F.age_label, 'age'), F.sex && chip(F.sex === 'M' ? 'Male' : 'Female', 'sex')].filter(Boolean);
  const card = (v, l, cls = '') => `<div class="kpi ${cls}"><b>${v ?? '—'}</b><span>${esc(l)}</span></div>`;
  const per = [30, 90, 180, 365].map(d => `<button class="segl ${F.days === d ? 'on' : ''}" data-days="${d}">${d === 365 ? '1 year' : d === 180 ? '6 months' : d + ' days'}</button>`).join('');
  document.getElementById('ex').innerHTML = `
    <div class="ex-bar"><div class="seg">${per}</div><div class="fchips">${active.join('') || '<span class="muted small">Everyone. Click a chart to filter.</span>'}${active.length > 1 ? '<button class="fchip clear" data-clear="all">Clear all</button>' : ''}</div></div>
    <div class="kpis ex-kpis">${card(S.visits, `visits · ${S.share}% of all`)}${card(S.patients, 'patients')}${card(S.improved != null ? S.improved + '%' : null, 'resolved or improved', S.improved != null && S.improved < 70 ? 'abn' : '')}
      ${card(S.admitted, 'admissions')}${card(S.los != null ? S.los + ' d' : null, 'average stay')}${card(S.positivity != null ? S.positivity + '%' : null, 'malaria tests positive', S.positivity >= 40 ? 'abn' : '')}</div>
    <section class="panel mb-3"><div class="panel-head"><h2>Where</h2><span class="hint">Real map · click a bubble for details</span></div><div id="map"></div></section>
    <div class="grid g-main">
      <div class="stack">
        <section class="panel"><div class="panel-head"><h2>Visits per week</h2><span class="hint">This group against all visits</span></div><div id="wk"></div></section>
        <section class="panel"><div class="panel-head"><h2>Every day</h2><span class="hint">Calendar of visits</span></div><div id="cal"></div></section>
        <div class="grid g-2">
          <section class="panel"><div class="panel-head"><h2>Arrival time</h2><span class="hint">Visits by hour</span></div><div id="hr"></div></section>
          <section class="panel"><div class="panel-head"><h2>Outcomes</h2></div><div id="oc"></div></section>
        </div>
        <section class="panel"><div class="panel-head"><h2>Treatments used</h2><span class="hint">Share of visits · resolved or improved when used</span></div><div id="meds"></div></section>
      </div>
      <div class="stack">
        <section class="panel"><div class="panel-head"><h2>${F.dx ? 'Other diagnoses here' : 'Diagnoses'}</h2><span class="hint">Click to drill in</span></div><div id="dx"></div></section>
        <section class="panel"><div class="panel-head"><h2>Age and sex</h2><span class="hint">Click a bar to filter</span></div><div id="pyr"></div></section>
        <section class="panel"><div class="panel-head"><h2>Tests ordered</h2></div><div id="tests"></div>${D.positivity.some(x => x != null) ? '<div class="label-sm mt-3">Malaria positivity by week</div><div id="pos"></div>' : ''}</section>
      </div>
    </div>`;
  document.querySelectorAll('[data-days]').forEach(b => b.addEventListener('click', () => go({days: b.dataset.days})));
  document.querySelectorAll('[data-clear]').forEach(b => b.addEventListener('click', () => b.dataset.clear === 'all' ? go({dx: '', town: '', age: '', sex: ''}) : go({[b.dataset.clear]: ''})));
  document.getElementById('map').innerHTML = `<iframe class="real-map" src="/health/map/${location.search}" title="Map of patients by location" loading="lazy"></iframe>
    <div class="small muted mt-1">Street map © OpenStreetMap contributors. Click a bubble, then “Explore”, to filter by that town. Switch on the heat map from the layer box. <a href="/health/locations/" target="_top">Manage locations</a></div>`;
  calendar(document.getElementById('cal'), D.daily, D.start, F.days);
  donut(document.getElementById('oc'), D.outcomes, ['#0F7B78', '#5BBFA3', '#E0912A', '#C8323F', '#8A4A8F']);

  // weekly line: this group (solid) against all visits (faint)
  (() => {
    const W = 700, H = 210, L = 30, R = 10, T = 10, B = 24, n = D.weeks.length, max = Math.max(1, ...D.weekly_all);
    const x = i => L + i * (W - L - R) / Math.max(1, n - 1), y = v => T + (1 - v / max) * (H - T - B);
    const line = (s, cls) => `<path d="${s.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')}" class="${cls}"/>`;
    const area = `<path d="M${x(0)},${y(0)} ${D.weekly.map((v, i) => `L${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')} L${x(n - 1)},${y(0)} Z" class="ex-area"/>`;
    document.getElementById('wk').innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="chart">${[0, .5, 1].map(k => `<line x1="${L}" x2="${W - R}" y1="${y(max * k)}" y2="${y(max * k)}" class="grid-l"/><text x="${L - 4}" y="${y(max * k) + 4}" text-anchor="end" class="c-ax">${Math.round(max * k)}</text>`).join('')}
      ${line(D.weekly_all, 'ex-all')}${area}${line(D.weekly, 'ex-line')}${D.weekly.map((v, i) => `<circle cx="${x(i)}" cy="${y(v)}" r="3" class="ex-dot"><title>Week of ${esc(D.weeks[i])}: ${v} (all visits ${D.weekly_all[i]})</title></circle>`).join('')}
      ${D.weeks.map((w, i) => i % Math.ceil(n / 7) === 0 ? `<text x="${x(i)}" y="${H - 6}" text-anchor="middle" class="c-ax">${esc(w)}</text>` : '').join('')}</svg>`;
  })();
  // hours
  (() => { const max = Math.max(1, ...D.hours);
    document.getElementById('hr').innerHTML = `<svg viewBox="0 0 340 130" class="chart">${D.hours.map((v, h) => `<rect x="${h * 14 + 2}" y="${(1 - v / max) * 105}" width="11" height="${v / max * 105}" rx="2" class="hb" style="animation-delay:${h * 20}ms"><title>${h}:00 · ${v} visits</title></rect>`).join('')}
      ${[0, 6, 12, 18, 23].map(h => `<text x="${h * 14 + 7}" y="124" text-anchor="middle" class="c-ax">${h}h</text>`).join('')}</svg>`; })();
  // diagnoses (clickable)
  (() => { const max = Math.max(1, ...D.dx_mix.map(d => d.n));
    document.getElementById('dx').innerHTML = D.dx_mix.map(d => `<button class="dxrow ${d.key === F.dx ? 'on' : ''}" data-dx="${esc(d.key)}"><span>${esc(d.label)}</span><i style="--w:${d.n * 100 / max}%"></i><b>${d.n}</b></button>`).join('') || '<p class="muted small mb-0">No diagnoses in this group.</p>';
    document.querySelectorAll('[data-dx]').forEach(b => b.addEventListener('click', () => go({dx: b.dataset.dx === F.dx ? '' : b.dataset.dx}))); })();
  // pyramid (clickable by age band and sex)
  (() => { const max = Math.max(1, ...D.pyramid.M, ...D.pyramid.F);
    document.getElementById('pyr').innerHTML = `<div class="pyr"><div class="pyr-h"><span>Male</span><span></span><span>Female</span></div>${D.bands.map((b, i) => i).reverse().map(i => `
      <div class="pyr-row ${String(i) === String(F.age) ? 'on' : ''}"><button class="pym" data-age="${i}" data-sex="M" title="Male ${D.bands[i]}: ${D.pyramid.M[i]}"><i style="--w:${D.pyramid.M[i] * 100 / max}%"></i><em>${D.pyramid.M[i] || ''}</em></button>
      <button class="pyr-band" data-age="${i}">${D.bands[i]}</button><button class="pyf" data-age="${i}" data-sex="F" title="Female ${D.bands[i]}: ${D.pyramid.F[i]}"><i style="--w:${D.pyramid.F[i] * 100 / max}%"></i><em>${D.pyramid.F[i] || ''}</em></button></div>`).join('')}</div>
      <div class="d-flex gap-2 mt-2"><button class="chip ${F.sex === 'M' ? 'on' : ''}" data-sexonly="M">Male only</button><button class="chip ${F.sex === 'F' ? 'on' : ''}" data-sexonly="F">Female only</button></div>`;
    document.querySelectorAll('#pyr [data-age]').forEach(b => b.addEventListener('click', () => go({age: b.dataset.age, sex: b.dataset.sex || F.sex})));
    document.querySelectorAll('[data-sexonly]').forEach(b => b.addEventListener('click', () => go({sex: F.sex === b.dataset.sexonly ? '' : b.dataset.sexonly}))); })();
  // treatments & tests
  document.getElementById('meds').innerHTML = D.meds.length ? `<table class="mini-table"><thead><tr><th>Medicine</th><th class="text-end">Visits</th><th style="width:40%">Resolved or improved</th></tr></thead><tbody>${D.meds.map(m => `<tr><td>${esc(m.name)}</td><td class="text-end">${m.n}</td><td>${m.success != null ? `<div class="d-flex align-items-center gap-2"><div class="meter flex-fill ${m.success < 60 ? 'red' : m.success < 80 ? 'amber' : ''}"><i style="--w:${m.success}%"></i></div><b class="small">${m.success}%</b></div>` : '<span class="muted small">no outcomes</span>'}</td></tr>`).join('')}</tbody></table>` : '<p class="muted small mb-0">No prescriptions in this group.</p>';
  (() => { const max = Math.max(1, ...D.tests.map(t => t.n));
    document.getElementById('tests').innerHTML = D.tests.map(t => `<div class="mb-2"><div class="d-flex small"><span>${esc(t.name)}</span><b class="ms-auto">${t.n}</b></div><div class="meter"><i style="--w:${t.n * 100 / max}%"></i></div></div>`).join('') || '<p class="muted small mb-0">No tests in this group.</p>';
    const pos = document.getElementById('pos');
    if (pos) pos.innerHTML = `<svg viewBox="0 0 340 110" class="chart"><line x1="0" x2="340" y1="${(1 - .4) * 90}" y2="${(1 - .4) * 90}" class="warn-l"/>${D.positivity.map((v, i) => v == null ? '' : `<rect x="${i * 340 / D.positivity.length + 2}" width="${340 / D.positivity.length - 4}" y="${(1 - v / 100) * 90}" height="${v / 100 * 90}" rx="2" class="hb ${v >= 40 ? 'bad' : ''}"><title>Week of ${esc(D.weeks[i])}: ${v}% positive</title></rect>`).join('')}<text x="338" y="${(1 - .4) * 90 - 3}" text-anchor="end" class="c-ax">40%</text></svg>`; })();
})();
