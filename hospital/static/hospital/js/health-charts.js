/* Shared chart pieces for the health pages: stylised map of The Gambia, calendar heatmap, donut. */
window.MFCharts = (() => {
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  // simplified outline of The Gambia (longitude, latitude); not to scale, for orientation only
  const OUTLINE = [[-16.82, 13.20], [-16.80, 13.45], [-16.80, 13.59], [-16.4, 13.59], [-16.0, 13.62], [-15.6, 13.68], [-15.2, 13.66], [-14.8, 13.63], [-14.4, 13.58],
    [-14.0, 13.55], [-13.80, 13.47], [-13.82, 13.35], [-14.2, 13.24], [-14.6, 13.30], [-15.0, 13.38], [-15.4, 13.36], [-15.8, 13.30], [-16.2, 13.20], [-16.6, 13.10], [-16.75, 13.06]];
  const RIVER = [[-16.62, 13.47], [-16.3, 13.43], [-15.95, 13.47], [-15.6, 13.50], [-15.3, 13.53], [-15.0, 13.55], [-14.7, 13.50], [-14.4, 13.42], [-14.1, 13.36], [-13.85, 13.40]];
  const W = 900, H = 300, P = 20;
  const prj = ([lon, lat]) => [P + (lon + 16.9) / 3.2 * (W - 2 * P), P + (13.75 - lat) / 0.75 * (H - 2 * P)];
  // magnified inset for the crowded Greater Banjul area
  const IN = {x: 20, y: 30, w: 300, h: 330, lon: [-16.80, -16.54], lat: [13.15, 13.51]};
  const inPrj = ([lon, lat]) => [IN.x + (lon - IN.lon[0]) / (IN.lon[1] - IN.lon[0]) * IN.w, IN.y + (IN.lat[1] - lat) / (IN.lat[1] - IN.lat[0]) * IN.h];
  const inInset = ([lon, lat]) => lon < -16.52 && lat > 13.14;
  function map(el, towns, {active = '', onPick} = {}) {
    const max = Math.max(1, ...towns.map(t => t.n));
    const dot = (t, [x, y], scale, label, side) => {
      const r = (6 + Math.sqrt(t.n / max) * 30) * scale, share = t.all ? t.n / t.all : 0;
      return `<g class="town-dot ${t.town === active ? 'on' : ''}" data-town="${esc(t.town)}" transform="translate(${x.toFixed(0)},${y.toFixed(0)})" tabindex="0" role="button" aria-label="${esc(t.town)}: ${t.n} patients">
        <circle r="${r.toFixed(1)}" class="halo" style="--o:${(.25 + share * .6).toFixed(2)}"/><circle r="${scale < 1 ? 2.5 : 4}" class="core"/>
        ${label ? (side ? `<text x="${(r + 5).toFixed(0)}" y="4">${esc(t.town)} <tspan class="n">${t.n}</tspan></text>` : `<text y="${(-r - 5).toFixed(0)}" text-anchor="middle">${esc(t.town)}</text><text y="${(r + 13).toFixed(0)}" text-anchor="middle" class="n">${t.n}</text>`) : ''}<title>${esc(t.town)}: ${t.n} patients in this group (of ${t.all})</title></g>`;
    };
    const placed = towns.filter(t => t.xy);
    const insetTowns = placed.filter(t => inInset(t.xy));
    const inset = insetTowns.length ? `<svg viewBox="0 0 400 380" class="gm-inset" role="img" aria-label="Greater Banjul area, magnified"><rect width="400" height="380" class="sea"/>
      <path d="M150,0 L400,0 L400,380 L120,380 C100,300 70,200 80,120 C90,60 120,20 150,0Z" class="land"/>
      <text x="14" y="20" class="inset-l">Greater Banjul area (magnified)</text>${insetTowns.map(t => dot(t, inPrj(t.xy), .6, true, true)).join('')}</svg>` : '';
    const dots = placed.map(t => dot(t, prj(t.xy), inInset(t.xy) ? .45 : 1, !inInset(t.xy))).join('');
    const unplaced = towns.filter(t => !t.xy);
    el.innerHTML = `<div class="gm-wrap ${inset ? 'has-inset' : ''}"><svg viewBox="0 0 ${W} ${H}" class="gm-map" role="img" aria-label="Map of patients by town">
      <rect width="${W}" height="${H}" class="sea"/><path d="M${OUTLINE.map(p => prj(p).map(v => v.toFixed(1)).join(',')).join(' L')} Z" class="land"/>
      <path d="M${RIVER.map(p => prj(p).map(v => v.toFixed(1)).join(',')).join(' L')}" class="river"/>
      <text x="14" y="${H - 14}" class="sea-l">Atlantic Ocean</text>${insetTowns.length ? `<rect x="${prj([-16.82, 13.52])[0]}" y="${prj([-16.82, 13.52])[1]}" width="${prj([-16.52, 13.14])[0] - prj([-16.82, 13.52])[0]}" height="${prj([-16.52, 13.14])[1] - prj([-16.82, 13.52])[1]}" class="inset-src"/>` : ''}${dots}</svg>${inset}</div>
      <div class="small muted mt-1">Stylised map of The Gambia, not to scale.${unplaced.length ? ` Not on map: ${unplaced.map(t => `${esc(t.town)} (${t.n})`).join(', ')}.` : ''} Bubble size = patients; darker = larger share of that town's patients.</div>`;
    if (onPick) el.querySelectorAll('.town-dot').forEach(g => { const go = () => onPick(g.dataset.town); g.addEventListener('click', go); g.addEventListener('keydown', e => { if (e.key === 'Enter') go(); }); });
  }
  function calendar(el, daily, start, days) {
    const d0 = new Date(start + 'T00:00:00'), cells = [], max = Math.max(1, ...Object.values(daily));
    const offset = (d0.getDay() + 6) % 7;            // Monday first
    for (let i = 0; i < days; i++) {
      const d = new Date(d0); d.setDate(d0.getDate() + i);
      const key = d.toISOString().slice(0, 10), n = daily[key] || 0, idx = i + offset;
      cells.push(`<rect x="${Math.floor(idx / 7) * 14}" y="${(idx % 7) * 14}" width="12" height="12" rx="2" class="cal-c" style="--a:${n ? (.15 + .85 * n / max).toFixed(2) : 0}"><title>${d.toDateString()}: ${n} visit${n === 1 ? '' : 's'}</title></rect>`);
    }
    const cols = Math.ceil((days + offset) / 7);
    el.innerHTML = `<svg viewBox="-28 0 ${cols * 14 + 30} 100" class="cal-map">${['Mon', '', 'Wed', '', 'Fri', '', ''].map((l, i) => l ? `<text x="-4" y="${i * 14 + 10}" text-anchor="end" class="c-ax">${l}</text>` : '').join('')}${cells.join('')}</svg>
      <div class="d-flex align-items-center gap-1 small muted mt-1 justify-content-end">Fewer <span class="cal-key" style="--a:.15"></span><span class="cal-key" style="--a:.5"></span><span class="cal-key" style="--a:1"></span> More</div>`;
  }
  function donut(el, parts, colors) {
    const total = parts.reduce((s, p) => s + p.n, 0) || 1; let a = -Math.PI / 2, segs = '';
    parts.forEach((p, i) => { const b = a + p.n / total * Math.PI * 2, large = b - a > Math.PI ? 1 : 0;
      const pt = (ang, r) => `${(60 + Math.cos(ang) * r).toFixed(2)},${(60 + Math.sin(ang) * r).toFixed(2)}`;
      segs += `<path d="M${pt(a, 52)} A52,52 0 ${large} 1 ${pt(b, 52)} L${pt(b, 32)} A32,32 0 ${large} 0 ${pt(a, 32)} Z" fill="${colors[i % colors.length]}" class="donut-s"><title>${esc(p.label)}: ${p.n} (${Math.round(p.n * 100 / total)}%)</title></path>`; a = b; });
    el.innerHTML = `<div class="d-flex gap-3 align-items-center"><svg viewBox="0 0 120 120" width="130" class="donut">${segs}<text x="60" y="58" text-anchor="middle" class="donut-n">${total}</text><text x="60" y="73" text-anchor="middle" class="c-ax">visits</text></svg>
      <ul class="plain small">${parts.map((p, i) => `<li><i class="sw" style="background:${colors[i % colors.length]}"></i>${esc(p.label)} <b>${Math.round(p.n * 100 / total)}%</b></li>`).join('')}</ul></div>`;
  }
  return {esc, map, calendar, donut};
})();
