/* Interactive organ illustrations for the lab insights pop-out.
   Each illustration is an SVG whose animation is shaped by the patient's latest results for that organ.
   They are teaching visuals, not diagnostic images. */
(() => {
  'use strict';
  const rnd = (seed => () => (seed = (seed * 9301 + 49297) % 233280) / 233280)(7);   // stable pseudo-random layout
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const scale = (v, inLo, inHi, outLo, outHi) => v == null ? null : Math.round(outLo + (clamp(v, inLo, inHi) - inLo) / (inHi - inLo) * (outHi - outLo));

  // helpers over the system's parameters
  function reader(params) {
    const by = c => params.find(p => p.code === c && p.kind === 'number') || params.find(p => p.code === c);
    return {
      num: c => { const p = by(c); return p && p.latest.num != null ? p.latest.num : null; },
      flag: c => { const p = by(c); return p ? p.latest.flag : ''; },
      txt: c => { const p = by(c); return p ? p.latest.display : ''; },
      abn: c => ['H', 'L', 'HH', 'LL', 'A'].includes((by(c) || {latest: {}}).latest.flag),
      crit: c => ['HH', 'LL'].includes((by(c) || {latest: {}}).latest.flag),
      has: c => !!by(c),
    };
  }
  const part = (key, label, svg) => `<g class="oa-part" data-part="${key}" tabindex="0" role="button" aria-label="${label}"><title>${label}</title>${svg}</g>`;

  /* ------------------------------------------------------------------ BLOOD */
  function blood(r) {
    const hb = r.num('HB'), wbc = r.num('WBC'), plt = r.num('PLT');
    const nR = scale(hb, 4, 18, 5, 22) ?? 14, nW = scale(wbc, 1, 30, 1, 10) ?? 3, nP = scale(plt, 20, 700, 3, 18) ?? 9;
    const malaria = r.abn('RDT') || (r.num('DENS') || 0) > 0;
    let cells = '';
    for (let i = 0; i < nR; i++) {
      const y = 40 + rnd() * 100, d = (5 + rnd() * 4).toFixed(1), delay = (-rnd() * 8).toFixed(1), s = (.85 + rnd() * .3).toFixed(2);
      cells += `<g class="oa-flow" style="--y:${y}px;--d:${d}s;animation-delay:${delay}s"><g transform="scale(${s})">${part('rbc', 'Red blood cell: carries oxygen using haemoglobin',
        `<ellipse rx="13" ry="10" class="rbc"/><ellipse rx="6" ry="4" class="rbc-dip"/>${malaria && i % 3 === 0 ? '<circle r="2.6" cx="4" cy="-2" class="parasite"/>' : ''}`)}</g></g>`;
    }
    for (let i = 0; i < nW; i++) {
      const y = 45 + rnd() * 90, d = (8 + rnd() * 5).toFixed(1), delay = (-rnd() * 10).toFixed(1);
      cells += `<g class="oa-flow" style="--y:${y}px;--d:${d}s;animation-delay:${delay}s">${part('wbc', 'White blood cell: fights infection', '<circle r="15" class="wbc"/><path d="M-6,-3 q4,-6 8,0 q4,6 -2,8 q-7,2 -6,-8" class="wbc-n"/>')}</g>`;
    }
    for (let i = 0; i < nP; i++) {
      const y = 40 + rnd() * 100, d = (4 + rnd() * 3).toFixed(1), delay = (-rnd() * 6).toFixed(1);
      cells += `<g class="oa-flow" style="--y:${y}px;--d:${d}s;animation-delay:${delay}s">${part('plt', 'Platelet: helps blood clot', '<ellipse rx="4" ry="2.4" class="plt"/>')}</g>`;
    }
    const notes = [hb != null && `Haemoglobin ${hb} → ${nR} red cells shown`, wbc != null && `White cells ${wbc} → ${nW} shown`, plt != null && `Platelets ${plt} → ${nP} shown`, malaria && 'Malaria parasites shown inside red cells'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 180" class="oa oa-blood"><defs><linearGradient id="vein" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#FBE3E5"/><stop offset=".5" stop-color="#F7CFD3"/><stop offset="1" stop-color="#FBE3E5"/></linearGradient></defs>
      <rect x="0" y="22" width="340" height="136" rx="60" fill="url(#vein)" class="vessel-wall"/>${cells}</svg>`, notes,
      parts: {rbc: 'Red blood cells carry oxygen. Fewer cells on screen means lower haemoglobin.', wbc: 'White blood cells fight infection. More appear when the white count is high.', plt: 'Platelets plug leaks and help blood clot.'}};
  }

  /* ------------------------------------------------------------------ HEART */
  function heart(r) {
    const injury = r.abn('TNI') || r.abn('CKMB'), strain = r.abn('BNP'), arr = r.crit('K') || r.abn('K');
    const cls = ['oa-heart', injury && 'injury', strain && 'strain', arr && 'arrhythmia'].filter(Boolean).join(' ');
    const notes = [injury && `Troponin ${r.txt('TNI') || r.txt('CKMB')}: heart-muscle injury highlighted on the left ventricle`, strain && `BNP ${r.txt('BNP')}: heart under strain (chambers shown enlarged)`,
      arr && `Potassium ${r.txt('K')}: irregular rhythm shown`, !injury && !strain && !arr && 'Heart markers within range: steady rhythm'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 200" class="oa ${cls}">
      <g class="beat-box">
        ${part('ra', 'Right atrium: receives blood from the body', '<path d="M118,62 C100,60 92,78 98,96 C104,110 126,110 134,96 C140,82 136,64 118,62Z" class="ch-r"/>')}
        ${part('la', 'Left atrium: receives oxygen-rich blood from the lungs', '<path d="M196,58 C214,54 228,70 224,90 C220,106 198,108 190,94 C182,80 182,62 196,58Z" class="ch-l"/>')}
        ${part('rv', 'Right ventricle: pumps blood to the lungs', '<path d="M100,104 C96,132 120,170 160,186 C150,150 148,124 150,102 C136,112 112,114 100,104Z" class="ch-r"/>')}
        ${part('lv', 'Left ventricle: pumps blood to the whole body', '<path d="M152,100 C150,128 154,156 162,186 C200,170 232,130 226,96 C212,110 172,112 152,100Z" class="ch-l lv"/>')}
        <path class="injury-zone" d="M196,128 C206,124 218,132 214,146 C208,158 192,156 190,144 C188,136 190,130 196,128Z"/>
        ${part('aorta', 'Aorta: carries blood out to the body', '<path d="M170,62 C168,30 196,14 226,24 C246,30 250,48 246,58" class="vessel-l" />')}
        ${part('pa', 'Pulmonary artery: carries blood to the lungs', '<path d="M150,70 C140,40 108,34 90,44" class="vessel-r"/>')}
      </g>
      <path d="M40,90 C70,90 80,80 98,84" class="flow flow-in"/><path d="M226,26 C260,20 290,30 310,40" class="flow flow-out"/>
      <polyline class="ecg-line" points="0,195 40,195 50,195 56,185 62,198 68,160 74,200 80,195 120,195 130,190 140,195 340,195"/>
    </svg>`, notes, parts: {ra: 'Right atrium: collects used blood from the body.', la: 'Left atrium: collects fresh, oxygen-rich blood from the lungs.',
      rv: 'Right ventricle: pumps blood to the lungs.', lv: 'Left ventricle: the strongest chamber, pumping blood to the whole body. A raised troponin means this muscle may be injured.',
      aorta: 'Aorta: the main artery leaving the heart.', pa: 'Pulmonary artery: takes blood to the lungs for oxygen.'}};
  }

  /* ------------------------------------------------------------------ KIDNEYS */
  function kidneys(r) {
    const slow = r.abn('CREA') || r.abn('UREA'), k = r.abn('K'), prot = r.abn('PRO');
    let drops = '';
    for (let i = 0; i < 6; i++) drops += `<circle r="3.2" class="k-drop" style="animation-delay:${(i * .5).toFixed(1)}s"/>`;
    const notes = [slow && `Creatinine ${r.txt('CREA') || '—'} / urea ${r.txt('UREA') || '—'}: filtering shown slowed`, k && `Potassium ${r.txt('K')} out of range`, prot && 'Protein leaking into urine',
      !slow && !k && 'Kidney markers within range: filtering normally'].filter(Boolean);
    const bean = (x, flip) => `<g transform="translate(${x},20)${flip ? ' scale(-1,1)' : ''}">${part('cortex', 'Cortex: millions of filters (nephrons) clean the blood',
      '<path d="M0,10 C-40,10 -50,60 -40,100 C-30,140 10,145 20,110 C26,90 12,80 14,60 C16,38 30,10 0,10Z" class="k-body"/>')}
      ${part('pelvis', 'Renal pelvis: collects urine', '<path d="M8,55 C-6,60 -6,80 8,86 C14,80 14,62 8,55Z" class="k-pelvis"/>')}</g>`;
    return {svg: `<svg viewBox="0 0 340 190" class="oa oa-kidney ${slow ? 'slow' : ''} ${k ? 'kalert' : ''}">
      ${bean(110, false)}${bean(230, true)}
      <path id="ureter-l" d="M118,100 C122,130 150,150 170,172" class="ureter"/><path id="ureter-r" d="M222,100 C218,130 190,150 170,172" class="ureter"/>
      ${part('bladder', 'Bladder: stores urine', '<ellipse cx="170" cy="176" rx="22" ry="10" class="k-bladder"/>')}
      <g class="k-drops-l">${drops}</g></svg>`, notes,
      parts: {cortex: 'The cortex holds about a million tiny filters per kidney. Raised creatinine means they are clearing blood more slowly.', pelvis: 'The pelvis funnels urine into the ureter.', bladder: 'The bladder stores urine.'}};
  }

  /* ------------------------------------------------------------------ LUNGS */
  function lungs(r) {
    const sat = r.num('SAO2'), lowO2 = r.abn('SAO2') || r.abn('PO2'), tb = r.abn('AFB') || r.abn('MTB'), acid = r.abn('PH');
    const nO2 = sat != null ? scale(sat, 75, 100, 3, 16) : 12;
    let o2 = '';
    for (let i = 0; i < nO2; i++) o2 += `<circle r="3" class="o2" style="--x:${(40 + rnd() * 260).toFixed(0)}px;animation-delay:${(-rnd() * 3).toFixed(1)}s"/>`;
    const notes = [sat != null && `Oxygen saturation ${sat}% → ${nO2} oxygen particles shown`, lowO2 && 'Low oxygen: particles dimmed', tb && 'TB test positive: affected areas marked', acid && `Blood pH ${r.txt('PH')} out of range`,
      !lowO2 && !tb && !acid && 'Lung tests within range'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 200" class="oa oa-lungs ${lowO2 ? 'lowo2' : ''}">
      ${part('trachea', 'Trachea (windpipe): carries air to the lungs', '<path d="M170,8 L170,62" class="airway"/><path d="M170,62 C160,72 140,78 126,92 M170,62 C180,72 200,78 214,92" class="airway"/>')}
      <g class="breath">${part('lung-r', 'Right lung: three lobes', '<path d="M160,40 C120,34 70,70 66,130 C62,176 100,190 140,180 C158,176 160,150 160,120Z" class="lung"/>')}
      ${part('lung-l', 'Left lung: two lobes, with a notch for the heart', '<path d="M180,40 C220,34 270,70 274,130 C278,176 240,190 200,180 C186,176 186,160 196,150 C186,140 180,126 180,110Z" class="lung"/>')}
      ${tb ? '<circle cx="104" cy="74" r="10" class="tb-spot"/><circle cx="240" cy="80" r="8" class="tb-spot"/>' : ''}</g>
      ${part('alveoli', 'Alveoli: tiny air sacs where oxygen passes into the blood', '<g class="alv"><circle cx="110" cy="140" r="9"/><circle cx="124" cy="150" r="8"/><circle cx="104" cy="156" r="7"/><circle cx="226" cy="142" r="9"/><circle cx="238" cy="154" r="7"/></g>')}
      <g class="o2-field">${o2}</g></svg>`, notes,
      parts: {trachea: 'The windpipe divides into two bronchi, one for each lung.', 'lung-r': 'The right lung has three lobes.', 'lung-l': 'The left lung has two lobes and a notch where the heart sits.',
        alveoli: 'About 300 million air sacs. Oxygen crosses here into the blood; low oxygen saturation means less is getting through.'}};
  }

  /* ------------------------------------------------------------------ LIVER */
  function liver(r) {
    const alt = r.num('ALT'), ast = r.num('AST'), bili = r.abn('TBIL'), hbs = r.abn('HBS');
    const inflamed = r.abn('ALT') || r.abn('AST');
    const nSpark = inflamed ? scale(Math.max(alt || 0, ast || 0), 40, 400, 4, 18) : 0;
    let hex = '';
    for (let row = 0; row < 3; row++) for (let col = 0; col < 6; col++) {
      const x = 70 + col * 36 + (row % 2) * 18, y = 60 + row * 30;
      hex += `<polygon points="${[0, 1, 2, 3, 4, 5].map(k => `${(x + 15 * Math.cos(k * Math.PI / 3)).toFixed(1)},${(y + 15 * Math.sin(k * Math.PI / 3)).toFixed(1)}`).join(' ')}" class="lobule" style="animation-delay:${((row + col) * .15).toFixed(2)}s"/>`;
    }
    let sparks = '';
    for (let i = 0; i < nSpark; i++) sparks += `<circle r="3" cx="${(70 + rnd() * 210).toFixed(0)}" cy="${(48 + rnd() * 80).toFixed(0)}" class="spark-l" style="animation-delay:${(rnd() * 2).toFixed(1)}s"/>`;
    const notes = [inflamed && `ALT ${alt ?? '—'} / AST ${ast ?? '—'}: inflamed liver cells shown as red sparks (${nSpark})`, bili && `Bilirubin ${r.txt('TBIL')}: yellow tint`, hbs && 'Hepatitis B surface antigen reactive',
      !inflamed && !bili && !hbs && 'Liver tests within range'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 180" class="oa oa-liver ${bili ? 'jaundice' : ''}">
      ${part('liver', 'Liver: filters blood, makes proteins, stores energy', '<path d="M40,60 C40,30 120,20 230,30 C300,36 310,60 280,80 C230,116 150,150 90,146 C50,144 36,110 40,60Z" class="liver-body"/>')}
      ${part('lobules', 'Lobules: the liver\'s working units', `<g>${hex}</g>`)}${sparks}</svg>`, notes,
      parts: {liver: 'The liver cleans the blood and makes clotting proteins and bile.', lobules: 'Each lobule is a cluster of liver cells around a small vein. Raised ALT and AST mean some of these cells are damaged.'}};
  }

  /* ------------------------------------------------------------------ PANCREAS */
  function pancreas(r) {
    const glu = r.num('FBG'), a1c = r.num('A1C'), high = r.abn('FBG') || r.abn('A1C'), enz = r.abn('LIPA') || r.abn('AMY');
    const nSugar = glu != null ? scale(glu, 3, 25, 3, 22) : (a1c != null ? scale(a1c, 4, 13, 3, 20) : 6);
    let sugar = '';
    for (let i = 0; i < nSugar; i++) sugar += `<g class="oa-flow" style="--y:${(130 + rnd() * 34).toFixed(0)}px;--d:${(5 + rnd() * 4).toFixed(1)}s;animation-delay:${(-rnd() * 8).toFixed(1)}s"><rect x="-4" y="-4" width="8" height="8" rx="2" class="sugar"/></g>`;
    const notes = [glu != null && `Glucose ${glu} → ${nSugar} sugar particles in the bloodstream`, a1c != null && `HbA1c ${a1c}%`, high && 'Blood sugar above range', enz && 'Pancreatic enzymes raised: inflamed pancreas shown',
      !high && !enz && 'Pancreas tests within range'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 180" class="oa oa-pancreas ${enz ? 'inflamed' : ''}">
      ${part('pancreas', 'Pancreas: makes insulin and digestive enzymes', '<path d="M40,80 C70,50 150,58 220,54 C280,50 310,62 300,80 C290,96 220,94 160,104 C100,114 50,112 40,80Z" class="pan-body"/>')}
      ${part('islets', 'Islets: clusters of cells that release insulin', '<g class="islets"><circle cx="110" cy="84" r="8"/><circle cx="170" cy="80" r="7"/><circle cx="236" cy="72" r="8"/></g>')}
      <rect x="0" y="118" width="340" height="56" rx="26" class="vessel-wall"/>${part('blood', 'Bloodstream: glucose particles shown here', `<g>${sugar}</g>`)}</svg>`, notes,
      parts: {pancreas: 'The pancreas sits behind the stomach.', islets: 'Islets release insulin, which moves sugar out of the blood into cells. In diabetes sugar builds up in the blood.', blood: 'Each small square is sugar in the bloodstream. More squares means higher glucose.'}};
  }

  /* ------------------------------------------------------------------ BRAIN */
  function brain(r) {
    const inflamed = r.abn('CWBC') || r.abn('CPRO') || r.abn('CGLU');
    let net = '', firing = '';
    const nodes = Array.from({length: 11}, () => [70 + rnd() * 200, 40 + rnd() * 100]);
    nodes.forEach(([x, y], i) => {
      const [x2, y2] = nodes[(i + 3) % nodes.length];
      net += `<line x1="${x.toFixed(0)}" y1="${y.toFixed(0)}" x2="${x2.toFixed(0)}" y2="${y2.toFixed(0)}" class="axon"/>`;
      firing += `<circle cx="${x.toFixed(0)}" cy="${y.toFixed(0)}" r="5" class="neuron" style="animation-delay:${(rnd() * 2).toFixed(1)}s"/>`;
    });
    const notes = [inflamed && 'Spinal fluid abnormal: inflammation shown around the brain', !inflamed && 'Spinal fluid tests within range'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 180" class="oa oa-brain ${inflamed ? 'inflamed' : ''}">
      ${part('cortex', 'Cerebrum: thinking, movement, senses', '<path d="M60,100 C40,50 100,14 170,18 C250,14 300,50 286,100 C276,140 230,160 170,158 C110,160 70,140 60,100Z" class="brain-body"/>')}
      ${part('meninges', 'Meninges: membranes around the brain, bathed in spinal fluid', '<path d="M54,100 C34,46 98,8 170,12 C254,8 308,46 292,100 C282,146 232,166 170,164 C108,166 64,146 54,100Z" class="meninges"/>')}
      <g>${net}${firing}</g></svg>`, notes,
      parts: {cortex: 'Billions of neurons pass signals; each flash is a neuron firing.', meninges: 'The meninges hold the spinal fluid tested in a lumbar puncture. Raised white cells or protein suggest infection or inflammation (meningitis).'}};
  }

  /* ------------------------------------------------------------------ THYROID */
  function thyroid(r) {
    const tsh = r.num('TSH'), hi = r.flag('TSH') === 'H' || r.flag('TSH') === 'HH', lo = r.flag('TSH') === 'L' || r.flag('TSH') === 'LL';
    const n = lo ? 16 : hi ? 3 : 8;
    let dots = '';
    for (let i = 0; i < n; i++) dots += `<circle r="3" class="hormone" style="--x:${(110 + rnd() * 120).toFixed(0)}px;animation-delay:${(-rnd() * 3).toFixed(1)}s"/>`;
    const notes = [tsh != null && `TSH ${tsh}`, hi && 'High TSH: under-active thyroid (fewer hormone particles)', lo && 'Low TSH: over-active thyroid (more hormone particles)', !hi && !lo && 'Thyroid within range'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 180" class="oa oa-thyroid ${lo ? 'fast' : hi ? 'slow' : ''}">
      ${part('lobes', 'Thyroid lobes: make hormones that set the body\'s energy use', '<path d="M120,60 C90,60 86,140 120,146 C146,150 156,120 158,96 C160,72 146,60 120,60Z M220,60 C250,60 254,140 220,146 C194,150 184,120 182,96 C180,72 194,60 220,60Z" class="thy"/>')}
      ${part('isthmus', 'Isthmus: bridge joining the two lobes', '<rect x="150" y="94" width="40" height="18" rx="8" class="thy"/>')}
      <g>${dots}</g></svg>`, notes, parts: {lobes: 'The thyroid releases T4 and T3, which control metabolism.', isthmus: 'A thin bridge of tissue in front of the windpipe.'}};
  }

  /* ------------------------------------------------------------------ IMMUNE */
  function immune(r) {
    const active = r.abn('WBC') || r.abn('CRP') || r.abn('ESR') || r.abn('HIV');
    const nB = active ? 9 : 2;
    let germs = '';
    for (let i = 0; i < nB; i++) germs += `<g class="germ" style="--x:${(60 + rnd() * 220).toFixed(0)}px;--y:${(40 + rnd() * 100).toFixed(0)}px;animation-delay:${(-rnd() * 4).toFixed(1)}s"><circle r="5"/><path d="M-7,0 h-3 M7,0 h3 M0,-7 v-3 M0,7 v3"/></g>`;
    const notes = [active && 'Infection or inflammation markers raised: immune cells shown hunting', !active && 'Infection markers within range'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 180" class="oa oa-immune ${active ? 'active' : ''}">${germs}
      ${part('wbc', 'White blood cells chasing germs', '<g class="hunter" style="--x:120px;--y:80px"><circle r="18" class="wbc"/></g><g class="hunter h2" style="--x:220px;--y:110px"><circle r="15" class="wbc"/></g>')}</svg>`, notes,
      parts: {wbc: 'White blood cells find and destroy germs. CRP and ESR rise when the body is fighting infection or inflammation.'}};
  }

  /* ------------------------------------------------------------------ generic fallback */
  function generic(r, label) {
    return {svg: `<svg viewBox="0 0 340 140" class="oa oa-generic"><circle cx="170" cy="70" r="40" class="g-core"/><circle cx="170" cy="70" r="40" class="g-ring"/><circle cx="170" cy="70" r="40" class="g-ring r2"/></svg>`, notes: [label], parts: {}};
  }

  const ART = {blood, heart, kidneys, lungs, liver, pancreas, brain, thyroid, immune};
  window.MedFlowOrgans = {
    render(system, params, label) {
      const r = reader(params || []);
      const art = (ART[system] || (() => generic(r, label)))(r);
      return art;
    },
  };
})();
