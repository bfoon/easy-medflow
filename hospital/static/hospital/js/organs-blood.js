/* Blood pop-out with tabs: Blood film (microscope view for the patient's condition), In the vessel (the mechanism:
   sickle cells blocking a vessel, bleeding with low platelets, thick slow blood) and Blood cells (existing view).
   Findings come from window.MF_ANATOMY.blood (results, blood film, haemoglobin genotype, diagnoses). Teaching only. */
(() => {
  'use strict';
  const ART = window.__MF_ART, H = (window.MedFlowOrgans || {}).helpers;
  if (!ART || !H) return;
  const {part, rnd} = H;
  const original = ART.blood;
  const LABEL = {sickle: 'Sickle cell disease', iron: 'Iron-deficiency anaemia', thal: 'Thalassaemia', macro: 'Megaloblastic (B12 / folate) anaemia',
                 leuk: 'Acute leukaemia', lowplt: 'Low platelets (thrombocytopenia)', haemolysis: 'Haemolysis', poly: 'Polycythaemia', malaria: 'Malaria'};
  const EXPLAIN = {
    sickle: 'HbS makes red cells stiff and sickle-shaped when oxygen is low. They block small vessels (pain crises, acute chest syndrome, stroke) and break down early (anaemia, jaundice).',
    iron: 'Without enough iron, red cells are small and pale (microcytic, hypochromic) with a wide pale centre, and carry less oxygen.',
    thal: 'Faulty globin chains make small red cells, many shaped like targets (a dark spot in a pale ring).',
    macro: 'Without B12 or folate, DNA cannot be made properly: red cells grow large and oval, and neutrophils have too many lobes.',
    leuk: 'Immature white cells (blasts) fill the blood and bone marrow, crowding out red cells and platelets.',
    lowplt: 'Too few platelets to plug small leaks: pinpoint bleeding (petechiae), bruising and bleeding gums.',
    haemolysis: 'Red cells break down early: fragments, small round spherocytes, or "bite cells" in G6PD deficiency after certain drugs, foods or infection.',
    poly: 'Too many red cells make the blood thick and slow, raising the risk of clots.',
    malaria: 'Plasmodium parasites live inside red cells; ring forms are seen on the film.',
  };
  const reader = r => ({hb: r.num('HB'), wbc: r.num('WBC'), plt: r.num('PLT')});

  /* ------------------------------------------------------------------ microscope view */
  function cell(kind, x, y, s = 1) {
    const rot = (rnd() * 360).toFixed(0);
    switch (kind) {
      case 'normal': return `<g transform="translate(${x},${y}) scale(${s})"><circle r="9" class="bf-rbc"/><circle r="3.4" class="bf-pale"/></g>`;
      case 'small': return `<g transform="translate(${x},${y}) scale(${s * .72})"><circle r="9" class="bf-rbc hypo"/><circle r="6" class="bf-pale wide"/></g>`;
      case 'target': return `<g transform="translate(${x},${y}) scale(${s * .8})"><circle r="9" class="bf-rbc"/><circle r="6" class="bf-pale wide"/><circle r="2.6" class="bf-rbc"/></g>`;
      case 'macro': return `<g transform="translate(${x},${y}) rotate(${rot}) scale(${s})"><ellipse rx="13" ry="10" class="bf-rbc"/><ellipse rx="3" ry="2.4" class="bf-pale"/></g>`;
      case 'sickle': return `<g transform="translate(${x},${y}) rotate(${rot}) scale(${s})"><path d="M-13,4 C-8,-8 8,-8 13,4 C6,-1 -6,-1 -13,4Z" class="bf-rbc sick"/></g>`;
      case 'frag': return `<g transform="translate(${x},${y}) rotate(${rot}) scale(${s})"><path d="M-6,-5 L6,-3 L3,5 L-5,3Z" class="bf-rbc"/></g>`;
      case 'sphero': return `<g transform="translate(${x},${y}) scale(${s * .7})"><circle r="8" class="bf-rbc dense"/></g>`;
      case 'bite': return `<g transform="translate(${x},${y}) rotate(${rot}) scale(${s})"><path d="M-9,0 A9,9 0 1,1 4,8 A4,4 0 0,0 -1,4 A4,4 0 0,0 -9,0Z" class="bf-rbc"/></g>`;
      case 'ring': return `<g transform="translate(${x},${y}) scale(${s})"><circle r="9" class="bf-rbc"/><circle r="3.2" cx="2" cy="-1" class="bf-ring"/><circle r="1.1" cx="4.4" cy="-2" class="bf-chrom"/></g>`;
      case 'blast': return `<g transform="translate(${x},${y}) scale(${s})" class="bf-blast-g"><circle r="15" class="bf-blast"/><circle r="11.5" class="bf-blast-n"/><circle r="2" cx="3" cy="-3" class="bf-nucleolus"/></g>`;
      case 'neut': return `<g transform="translate(${x},${y}) scale(${s})"><circle r="12" class="bf-wbc"/><path d="M-6,-3 c2,-4 5,-4 6,0 c1,4 5,4 6,0 M-5,4 c2,3 5,3 6,0" class="bf-lobes"/></g>`;
      case 'hyperseg': return `<g transform="translate(${x},${y}) scale(${s})"><circle r="13" class="bf-wbc"/><path d="M-9,-2 c2,-4 4,-4 5,0 c1,4 4,4 5,0 c1,-4 4,-4 5,0 c1,4 4,4 5,0 M-7,5 c2,3 4,3 5,0 c1,3 4,3 5,0" class="bf-lobes"/></g>`;
      case 'plt': return `<g transform="translate(${x},${y}) rotate(${rot})"><ellipse rx="2.6" ry="1.6" class="bf-plt"/></g>`;
    }
    return '';
  }
  function film(B, n) {
    const P = B.primary;
    const hb = n.hb ?? 13, plt = n.plt ?? 250, wbc = n.wbc ?? 7;
    const nR = Math.round(Math.max(12, Math.min(46, hb * 2.8 * (P === 'poly' ? 1.5 : 1)))), nP = Math.round(Math.max(1, Math.min(18, plt / 22))), nW = Math.round(Math.max(1, Math.min(9, wbc / 4)));
    const pick = i => P === 'sickle' ? (i % 3 === 0 ? 'normal' : i % 5 === 0 ? 'target' : 'sickle') : P === 'iron' ? 'small' : P === 'thal' ? (i % 2 ? 'target' : 'small')
      : P === 'macro' ? 'macro' : P === 'haemolysis' ? (B.g6pd ? (i % 3 ? 'normal' : 'bite') : i % 3 === 0 ? 'frag' : i % 3 === 1 ? 'sphero' : 'normal')
      : P === 'malaria' ? (i % 4 ? 'normal' : 'ring') : 'normal';
    let cells = '';
    const place = () => { for (let k = 0; k < 20; k++) { const a = rnd() * Math.PI * 2, r = Math.sqrt(rnd()) * 102; return [150 + Math.cos(a) * r, 120 + Math.sin(a) * r]; } };
    for (let i = 0; i < nR; i++) { const [x, y] = place(); cells += cell(pick(i), x.toFixed(0), y.toFixed(0)); }
    for (let i = 0; i < nP; i++) { const [x, y] = place(); cells += cell('plt', x.toFixed(0), y.toFixed(0)); }
    const wKind = P === 'leuk' ? 'blast' : P === 'macro' ? 'hyperseg' : 'neut';
    const nWb = P === 'leuk' ? Math.max(6, nW) : nW;
    for (let i = 0; i < nWb; i++) { const [x, y] = place(); cells += cell(P === 'leuk' && i % 4 === 3 ? 'neut' : wKind, x.toFixed(0), y.toFixed(0)); }
    return `<svg viewBox="0 0 300 240" class="oa bf"><defs><clipPath id="bf-field"><circle cx="150" cy="120" r="112"/></clipPath>
      <radialGradient id="bf-vig" cx="50%" cy="50%" r="50%"><stop offset=".72" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#1b1220" stop-opacity=".55"/></radialGradient></defs>
      <rect width="300" height="240" fill="#141016"/><circle cx="150" cy="120" r="112" fill="#F7EEF1"/>
      ${part('film', P ? `${LABEL[P]}: ${EXPLAIN[P]}` : 'A normal blood film: red cells with a pale centre, a few white cells and many platelets.', `<g clip-path="url(#bf-field)" class="bf-drift">${cells}</g>`)}
      <circle cx="150" cy="120" r="112" fill="url(#bf-vig)" pointer-events="none"/><circle cx="150" cy="120" r="112" fill="none" stroke="#2a2030" stroke-width="3"/>
      <text x="8" y="232" class="bf-cap">×1000 · stained blood film</text></svg>`;
  }

  /* ------------------------------------------------------------------ inside a small vessel */
  function vessel(B) {
    const P = B.primary, occl = P === 'sickle' && B.crisis, leak = P === 'lowplt' || B.bleeding, thick = P === 'poly' || P === 'leuk';
    const path = 'M-10,110 C60,104 110,96 150,100 C190,104 240,116 310,110';
    const n = thick ? 26 : 16, dur = thick ? 7 : occl ? 0 : 3.6;
    let flow = '';
    for (let i = 0; i < n; i++) {
      const kind = P === 'sickle' ? (i % 3 ? 'sickle' : 'normal') : P === 'leuk' && i % 3 === 0 ? 'blast' : P === 'iron' ? 'small' : P === 'thal' ? 'target' : P === 'macro' ? 'macro' : 'normal';
      const dy = ((i % 5) - 2) * 6;
      if (occl) {                               // cells jammed at the narrowing
        const x = 120 + (i % 6) * 9 + (rnd() * 4), y = 100 + dy * .7;
        flow += `<g class="jam" style="animation-delay:${(i * .1).toFixed(1)}s">${cell(kind, x.toFixed(0), y.toFixed(0), .85)}</g>`;
      } else {
        flow += `<g>${cell(kind, 0, dy, .85)}<animateMotion dur="${dur}s" begin="-${(i * dur / n).toFixed(2)}s" repeatCount="indefinite" path="${path}"/></g>`;
      }
    }
    const leaks = leak ? Array.from({length: 7}, (_, i) => `<circle cx="${60 + i * 34}" cy="${150 + (i % 3) * 8}" r="${2 + (i % 3)}" class="leak" style="animation-delay:${(i * .35).toFixed(2)}s"/>`).join('') : '';
    return `<svg viewBox="0 0 300 220" class="oa bv ${occl ? 'occl' : ''}"><defs><linearGradient id="bv-wall" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#8E1D27"/><stop offset=".18" stop-color="#F3C0C2"/><stop offset=".82" stop-color="#F3C0C2"/><stop offset="1" stop-color="#8E1D27"/></linearGradient></defs>
      <rect width="300" height="220" fill="${occl ? '#F7E9F0' : '#FBF3F4'}"/>
      ${occl ? '<rect x="185" y="0" width="115" height="220" class="ischaemic"/><text x="244" y="30" text-anchor="middle" class="bf-cap dark">No oxygen downstream</text>' : ''}
      ${part('vessel', occl ? 'Vaso-occlusion: stiff sickled cells jam at a narrow point. Tissue beyond gets no oxygen, which causes severe pain and damage.'
        : leak ? 'With too few platelets, small leaks in the vessel wall are not plugged, so blood seeps into the skin (petechiae) and gums.'
        : thick ? 'Thick blood flows slowly, raising the risk of clots and poor circulation.' : 'Blood flowing through a small vessel.',
        `<path d="M-10,${occl ? 82 : 76} C60,70 110,${occl ? 88 : 62} 150,${occl ? 90 : 66} C190,${occl ? 88 : 70} 240,82 310,76 L310,144 C240,150 190,${occl ? 112 : 134} 150,${occl ? 110 : 136} C110,${occl ? 112 : 132} 60,140 -10,144Z" fill="url(#bv-wall)" opacity=".9"/>`)}
      ${flow}${leaks}
      <text x="8" y="212" class="bf-cap">${occl ? 'Sickle cell crisis' : leak ? 'Bleeding from small vessels' : thick ? 'Thick, slow blood' : 'Normal flow'}</text></svg>`;
  }

  ART.blood = r => {
    const A = window.MF_ANATOMY || {}, B = A.blood || {};
    const base = original ? original(r) : {svg: '', notes: [], parts: {}};
    const tabs = [['film', 'Blood film', film(B, reader(r))], ['vessel', 'In the vessel', vessel(B)], ['cells', 'Blood cells', base.svg]];
    const notes = [...(base.notes || [])];
    if (B.primary) notes.unshift(`${LABEL[B.primary]}: ${EXPLAIN[B.primary]}`);
    if (B.trait && !B.sickle) notes.unshift('Sickle cell trait (AS): a carrier; red cells are normal in everyday life.');
    return {
      svg: `<div class="sk-tabs bl-tabs" role="tablist">${tabs.map(([k, l], i) => `<button type="button" role="tab" data-bl="${k}" class="${i === 0 ? 'on' : ''}">${l}</button>`).join('')}</div>` +
        tabs.map(([k, , html], i) => `<div class="bl-pane" data-pane="${k}" ${i === 0 ? '' : 'hidden'}>${html}</div>`).join(''),
      notes: notes.slice(0, 7),
      parts: {...(base.parts || {}), film: B.primary ? `${LABEL[B.primary]}: ${EXPLAIN[B.primary]}` : 'A normal blood film.', vessel: 'A small blood vessel.'},
      mount: fig => fig.querySelectorAll('[data-bl]').forEach(b => b.addEventListener('click', () => {
        fig.querySelectorAll('[data-bl]').forEach(x => x.classList.toggle('on', x === b));
        fig.querySelectorAll('.bl-pane').forEach(p => { p.hidden = p.dataset.pane !== b.dataset.bl; });
      })),
    };
  };
})();
