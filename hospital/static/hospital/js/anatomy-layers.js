/* Body systems on the body map: skeleton, circulation, nerves and lymphatics, drawn over the figure and driven by
   the patient's results, scans and diagnoses. Also works out *where* in the skeleton a problem is (spine level, which
   hand, which foot, which long bone) for the markers and the bone pop-out. Teaching illustration only. */
(() => {
  'use strict';
  const el = document.getElementById('lab-data'), svg = document.getElementById('body');
  if (!el || !svg) return;
  const D = JSON.parse(el.textContent);
  const NS = 'http://www.w3.org/2000/svg';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const latest = code => { const p = (D.params || []).find(x => x.code === code); return p ? p.latest : null; };
  const flag = code => (latest(code) || {}).flag || '';
  const num = code => (latest(code) || {}).num;
  const bad = code => ['H', 'L', 'HH', 'LL', 'A'].includes(flag(code));
  const crit = code => ['HH', 'LL'].includes(flag(code));
  const texts = [...(D.dx || []), ...(D.imaging || []).map(i => `${i.region} ${i.impression || ''} ${i.findings || ''}`)].map(t => (t || '').toLowerCase());
  const any = (...words) => texts.some(t => words.some(w => t.includes(w)));
  // true when the word is only mentioned as absent: "no cervical spine fracture", "negative for fracture"
  const negated = (t, word) => new RegExp(`\\b(no|not|without|negative for|nil)\\b[^.;]{0,40}\\b${word}`).test(t) && !new RegExp(`(?:^|[.;]\\s*)(?![^.;]*\\b(no|not|without|negative for|nil)\\b)[^.;]*\\b${word}`).test(t);
  const positive = (t, word) => new RegExp(`\\b${word}`).test(t) && !negated(t, word);
  const side = (t) => /\bleft\b/.test(t) ? 'left' : /\bright\b/.test(t) ? 'right' : null;

  /* ------------------------------------------------------------------ where in the body is the problem? */
  // spine levels: y position of each vertebra on the 400×800 figure
  const LEVELS = [];
  for (let i = 1; i <= 7; i++) LEVELS.push({name: `C${i}`, y: 128 + i * 5.2, w: 9});
  for (let i = 1; i <= 12; i++) LEVELS.push({name: `T${i}`, y: 172 + (i - 1) * 13.2, w: 11 + i * .45});
  for (let i = 1; i <= 5; i++) LEVELS.push({name: `L${i}`, y: 326 + (i - 1) * 17.5, w: 17 + i * .6});
  const levelY = name => (LEVELS.find(l => l.name === name) || {}).y;

  const spine = [];
  (D.imaging || []).concat((D.dx || []).map(t => ({region: '', impression: t, findings: ''}))).forEach(i => {
    const t = `${i.region || ''} ${i.impression || ''} ${i.findings || ''}`;
    const tl = t.toLowerCase();
    if (!/spine|spinal|vertebr|disc|cord|lumbar|cervical|thoracic|sciatica|whiplash|spondyl|back pain/.test(tl)) return;
    const lv = [...t.matchAll(/\b([CTL])(\d{1,2})\b/g)].map(m => m[1] + m[2]).filter(levelY);
    const kind = /cord/.test(tl) ? 'cord' : /disc|herniat|prolapse|sciatica/.test(tl) ? 'disc' : /fracture|compression|burst|wedge/.test(tl) ? 'fracture'
      : /spondyl|arthritis|degenerat/.test(tl) ? 'wear' : /whiplash|strain|sprain|back pain/.test(tl) ? 'strain' : 'finding';
    const normal = kind !== 'cord' && (/normal alignment|normal (mri|ct|x-ray)/.test(tl) || (/fracture/.test(tl) && negated(tl, 'fracture') && !/disc|cord|strain|whiplash|spondyl/.test(tl)));
    const fallback = /cervical|neck|whiplash/.test(tl) ? 'C5' : /thoracolumbar/.test(tl) ? 'T12' : /lumbar|sciatica|back pain/.test(tl) ? 'L4' : /thoracic/.test(tl) ? 'T8' : 'L3';
    // the first level named is the finding ("T10 burst fracture… swelling from T9 to T11" is a T10 injury); a disc sits between two levels
    const levels = lv.length ? lv.slice(0, kind === 'disc' ? 2 : 1) : [fallback];
    levels.forEach(l => { if (!spine.some(s => s.level === l && s.kind === kind)) spine.push({level: l, kind, normal, text: (i.impression || t).slice(0, 140)}); });
  });
  const realSpine = spine.filter(s => !s.normal);

  const handText = texts.filter(t => /hand|finger|metacarp|phalan|wrist|rheumatoid/.test(t));
  const footText = texts.filter(t => /foot|toe|ankle|metatars|gout|hallux|malleol|calcane|diabetic foot/.test(t));
  const hands = {
    inflamed: any('rheumatoid') || (bad('RF') && bad('ESR')) || (bad('RF') && bad('CRP')),
    fracture: handText.some(t => positive(t, 'fracture')),
    side: handText.map(side).find(Boolean) || null,
  };
  const feet = {
    gout: any('gout') || (bad('URIC') && num('URIC') > 480),
    fracture: footText.some(t => positive(t, 'fracture')),
    infection: any('osteomyelitis', 'diabetic foot'),
    side: footText.map(side).find(Boolean) || null,
  };
  const longBones = [];
  [['femur', /femur|femoral/], ['tibia', /tibia/], ['humerus', /humerus|supracondylar/], ['radius', /radius|radial|forearm/], ['clavicle', /clavicle/]].forEach(([bone, re]) => {
    texts.forEach(t => { if (re.test(t) && positive(t, 'fracture') && !longBones.some(b => b.bone === bone)) longBones.push({bone, side: side(t) || 'left', healing: /healing|follow-up/.test(t)}); });
  });
  const cordInjury = realSpine.find(s => s.kind === 'cord');
  const weakBone = bad('VITD') || flag('CA') === 'L' || flag('CA') === 'LL' || any('osteoporo');

  // marker for the bone system: put it where the most important problem is
  let boneSpot = [150, 640];
  if (realSpine.length) boneSpot = [200, levelY(realSpine[0].level)];
  else if (feet.gout || feet.fracture || feet.infection) boneSpot = [feet.side === 'left' ? 254 : 146, 786];
  else if (hands.inflamed || hands.fracture) boneSpot = [hands.side === 'left' ? 346 : 54, 520];
  else if (longBones.length) {
    const b = longBones[0], L = b.side === 'left';
    boneSpot = {femur: [L ? 244 : 156, 560], tibia: [L ? 252 : 148, 700], humerus: [L ? 308 : 92, 300], radius: [L ? 326 : 74, 420], clavicle: [L ? 226 : 174, 176]}[b.bone] || boneSpot;
  }

  const hr = parseFloat((D.vitals || {}).heart_rate) || 76;
  const nerveIrregular = ['K', 'NA', 'CA'].filter(bad);
  const lymphActive = ['WBC', 'CRP', 'ESR'].filter(bad);
  const anaemia = flag('HB') === 'L' || flag('HB') === 'LL';
  const lowO2 = bad('SAO2') || bad('PO2');

  /* ------------------------------------------------------------------ reproductive: pregnancy and organ findings */
  const sex = (D.patient || {}).sex;
  const hcgPos = ((latest('HCG') || {}).display || '').toLowerCase().startsWith('positive');
  const dxl = (D.dx || []).map(t => t.toLowerCase());
  const ended = dxl.some(t => /postpartum|postnatal|miscarriage|delivered|termination/.test(t));
  const ectopic = dxl.find(t => /ectopic/.test(t));
  const pregText = dxl.find(t => /pregnan|antenatal|gestation|weeks/.test(t) && !/not pregnant/.test(t));
  const wk = (() => { for (const t of [...dxl, ...texts]) { const m = t.match(/(\d{1,2})\s*(?:weeks|wks|w\b)/); if (m && +m[1] >= 4 && +m[1] <= 42) return +m[1]; } return null; })();
  const fhrImg = (D.imaging || []).flatMap(i => i.measurements || []).find(m => /fetal heart/i.test(m.label || ''));
  const pregnancy = sex === 'F' && !ended && (hcgPos || pregText) ? {weeks: wk || (hcgPos ? 8 : 20), ectopic: ectopic ? {side: side(ectopic) || 'right'} : null,
    fhr: fhrImg ? +fhrImg.value : 140, anaemia: flag('HB') === 'L' || flag('HB') === 'LL', bp: (D.vitals || {}).bp || ''} : null;
  const repro = {sex, pregnancy, fibroids: any('fibroid'), pid: any('pelvic inflammatory'), cyst: any('ovarian cyst'),
    prostate: sex === 'M' && (bad('PSA') || any('prostat', 'bph')), psa: num('PSA')};
  // the womb's top (fundus) rises with gestation: pubic bone at 12 weeks, navel at 20, near the ribs at 36
  const fundusY = pregnancy && !pregnancy.ectopic ? Math.max(300, Math.min(470, 470 - (pregnancy.weeks - 12) * (170 / 24))) : null;

  /* ------------------------------------------------------------------ blood disorders */
  const disp = code => ((latest(code) || {}).display || '').toLowerCase();
  const geno = disp('HBGENO'), film = disp('PBFM');
  const blood = {
    sickle: /^(ss|sc|s-beta)/.test(geno) || film.includes('sickle') || any('sickle cell disease', 'sickle cell anaemia', 'hbss', 'sickle cell crisis'),
    trait: geno === 'as' || any('sickle cell trait'),
    iron: any('iron deficiency', 'iron-deficiency') || film.includes('microcytic') || (flag('MCV') === 'L' && flag('FERR') === 'L'),
    thal: any('thalass') || geno.includes('thalass') || film.includes('target'),
    macro: any('megaloblastic', 'b12 deficiency', 'folate deficiency', 'pernicious') || film.includes('macrocyt') || num('MCV') > 105,
    leuk: any('leukaem', 'leukem') || num('BLAST') >= 20 || num('WBC') > 50,
    lowPlt: num('PLT') != null && num('PLT') < 50, itp: any('thrombocytopenic purpura', ' itp'),
    haemolysis: any('haemoly', 'hemoly') || /schisto|spherocyt|bite/.test(film) || disp('G6PD') === 'deficient',
    g6pd: disp('G6PD') === 'deficient' || any('g6pd'),
    poly: any('polycyth') || flag('HB') === 'H' || flag('HCT') === 'H',
    bleeding: flag('INR') === 'H' || flag('INR') === 'HH' || flag('APTT') === 'H' || flag('APTT') === 'HH',
    malaria: ((latest('RDT') || {}).display || '').toLowerCase().startsWith('positive'),
  };
  blood.crisis = blood.sickle && any('crisis', 'vaso-occlusive', 'acute chest');
  blood.bigSpleen = blood.leuk || blood.thal || (blood.sickle && ((D.patient || {}).age ?? 99) < 6) || any('splenomegaly');
  blood.jaundice = blood.haemolysis || (blood.sickle && bad('TBIL'));
  blood.primary = blood.leuk ? 'leuk' : blood.sickle ? 'sickle' : blood.itp || blood.lowPlt ? 'lowplt' : blood.g6pd || blood.haemolysis ? 'haemolysis' : blood.thal ? 'thal'
    : blood.iron ? 'iron' : blood.macro ? 'macro' : blood.poly ? 'poly' : blood.malaria ? 'malaria' : null;
  // how the body map's flowing blood cells look for this patient
  blood.cells = {sickle: {shape: 'M-5,2 C-3,-4.5 3,-4.5 5,2 C2,-1 -2,-1 -5,2 Z', cls: 'sickle'}, iron: {cls: 'pale small'}, thal: {cls: 'target'},
                 macro: {cls: 'big'}, leuk: {cls: '', blastEvery: 2}, poly: {cls: 'dense', density: 1.8}, haemolysis: {cls: 'frag'}}[blood.primary] || null;

  window.MF_ANATOMY = {blood, repro, fundusY, reproSpot: fundusY ? [200, fundusY + 30] : null,spine, realSpine, hands, feet, longBones, cordInjury, weakBone, boneSpot, hr, levels: LEVELS,
    flowFactor: Math.max(.55, Math.min(1.8, 76 / hr)), nerveIrregular, lymphActive, anaemia, lowO2};

  /* ------------------------------------------------------------------ drawing helpers */
  const g = (cls, html) => `<g class="${cls}">${html}</g>`;
  const M = x => 400 - x;                                   // mirror to the other side of the body
  const both = (fn) => fn(x => x) + fn(M);
  const bonePath = (d, cls = '') => `<path d="${d}" class="bn ${cls}"/>`;

  /* ------------------------------------------------------------------ skeleton */
  function skeleton() {
    let s = '';
    s += `<ellipse cx="200" cy="62" rx="38" ry="46" class="bn skull"/><path d="M174,92 C178,116 222,116 226,92" class="bn"/><ellipse cx="186" cy="64" rx="8" ry="7" class="socket"/><ellipse cx="214" cy="64" rx="8" ry="7" class="socket"/>`;
    // spine, one vertebra per level, with data for highlighting
    LEVELS.forEach(l => { s += `<rect x="${(200 - l.w / 2).toFixed(1)}" y="${(l.y - 2.4).toFixed(1)}" width="${l.w.toFixed(1)}" height="${l.name[0] === 'C' ? 4.2 : l.name[0] === 'T' ? 10.4 : 14}" rx="2" class="bn vert" data-level="${l.name}"><title>${l.name} vertebra</title></rect>`; });
    s += `<path d="M186,410 L214,410 L206,446 L194,446 Z" class="bn sacrum"><title>Sacrum</title></path>`;
    // ribs (12 pairs) and sternum
    for (let i = 0; i < 12; i++) {
      const y = 176 + i * 13.2, out = i < 7 ? 58 + i * 3 : 76 - (i - 7) * 6, drop = 14 + i * 1.6;
      s += both(f => `<path d="M${f(206)},${y} C${f(206 + out * .55)},${y - 6} ${f(200 + out)},${y + drop * .3} ${f(200 + out - 4)},${y + drop}" class="bn rib"/>`);
    }
    s += `<rect x="196" y="180" width="8" height="78" rx="3" class="bn"/>`;
    s += both(f => `<path d="M${f(198)},173 C${f(186)},170 ${f(166)},172 ${f(150)},178" class="bn long"/>`);                      // clavicles
    s += `<path d="M156,446 C148,424 172,418 186,436 C192,448 208,448 214,436 C228,418 252,424 244,446 C240,470 222,484 200,486 C178,484 160,470 156,446Z" class="bn pelvis"/>`;
    // arms: humerus, radius & ulna, hand (carpals, metacarpals, phalanges)
    s += both(f => bonePath(`M${f(300)},206 C${f(306)},250 ${f(310)},292 ${f(314)},332`, 'long') +
      bonePath(`M${f(314)},344 C${f(320)},390 ${f(328)},440 ${f(334)},484`, 'long thin') + bonePath(`M${f(308)},344 C${f(314)},392 ${f(322)},440 ${f(330)},486`, 'long thin') + hand(f));
    // legs: femur, patella, tibia & fibula, foot (tarsals, metatarsals, phalanges)
    s += both(f => bonePath(`M${f(236)},486 C${f(242)},530 ${f(248)},590 ${f(250)},626`, 'long femur') + `<circle cx="${f(250)}" cy="640" r="7" class="bn"/>` +
      bonePath(`M${f(250)},654 C${f(251)},690 ${f(252)},730 ${f(253)},768`, 'long') + bonePath(`M${f(262)},656 C${f(264)},694 ${f(266)},730 ${f(266)},766`, 'long thin') + foot(f));
    return s;
  }
  function hand(f) {
    let s = '';
    const isPatLeft = f(10) === 10;                         // figure's right side = patient's left
    for (let i = 0; i < 6; i++) s += `<circle cx="${f(337 + (i % 3) * 5)}" cy="${494 + Math.floor(i / 3) * 5}" r="2.3" class="bn carpal"/>`;
    const rays = [[333, 336, 335], [338, 341, 341], [343, 347, 348], [348, 353, 355]];   // little → index (thumb separate)
    rays.forEach(([a, b, c], i) => {
      s += `<line x1="${f(a)}" y1="504" x2="${f(b)}" y2="${523 - i}" class="bn meta"/>`;
      s += `<line x1="${f(b)}" y1="${526 - i}" x2="${f(c)}" y2="${552 - (i === 0 ? 6 : 0)}" class="bn phal" data-joint="${isPatLeft ? 'L' : 'R'}-mcp${i}"/>`;
      s += `<circle cx="${f(b)}" cy="${524.5 - i}" r="1.9" class="joint-dot" data-joint="${isPatLeft ? 'L' : 'R'}-mcp${i}"/><circle cx="${f((b + c) / 2)}" cy="${(539 - i / 2).toFixed(1)}" r="1.6" class="joint-dot pip"/>`;
    });
    s += `<line x1="${f(354)}" y1="500" x2="${f(361)}" y2="516" class="bn meta"/><line x1="${f(361)}" y1="518" x2="${f(363)}" y2="533" class="bn phal"/>`;   // thumb
    return `<g class="hand" data-side="${isPatLeft ? 'left' : 'right'}">${s}</g>`;
  }
  function foot(f) {
    let s = '';
    const isPatLeft = f(10) === 10;
    s += `<ellipse cx="${f(256)}" cy="776" rx="9" ry="5" class="bn tarsal"/><ellipse cx="${f(262)}" cy="782" rx="7" ry="3.5" class="bn tarsal"/>`;
    const toes = [[244, 240], [252, 249], [259, 258], [266, 267], [273, 276]];   // big toe (towards the midline) first
    toes.forEach(([a, b], i) => {
      s += `<line x1="${f(a + 6)}" y1="784" x2="${f(a)}" y2="${793 - i * .4}" class="bn meta"/><line x1="${f(a)}" y1="${794 - i * .4}" x2="${f(b)}" y2="${800 - i}" class="bn phal"/>`;
      if (i === 0) s += `<circle cx="${f(a)}" cy="793.5" r="2.4" class="joint-dot mtp1" data-joint="${isPatLeft ? 'L' : 'R'}-mtp1"/>`;
    });
    return `<g class="foot" data-side="${isPatLeft ? 'left' : 'right'}">${s}</g>`;
  }

  /* ------------------------------------------------------------------ nerves */
  const NERVES = {
    cord: 'M200,104 L200,330',
    caudaL: 'M200,330 C198,370 192,410 186,450', caudaR: 'M200,330 C202,370 208,410 214,450',
    armR: 'M204,168 C240,178 288,196 300,214 C306,256 310,296 314,338 C320,390 328,440 336,488 L348,540',
    armL: 'M196,168 C160,178 112,196 100,214 C94,256 90,296 86,338 C80,390 72,440 64,488 L52,540',
    legR: 'M206,440 C222,470 238,500 244,530 C248,580 250,620 251,650 C252,700 253,740 256,790',
    legL: 'M194,440 C178,470 162,500 156,530 C152,580 150,620 149,650 C148,700 147,740 144,790',
  };
  function nerves() {
    const lesionY = cordInjury ? levelY(cordInjury.level) : null;
    const cervical = cordInjury && cordInjury.level[0] === 'C';
    const dead = k => lesionY && (k.startsWith('leg') || k.startsWith('cauda') || (cervical && k.startsWith('arm')));
    let s = '';
    Object.entries(NERVES).forEach(([k, d]) => {
      s += `<path id="nv-${k}" d="${d}" class="nerve ${dead(k) ? 'dead' : ''}"/>`;
      if (dead(k)) return;
      const n = k === 'cord' ? 3 : 2, dur = nerveIrregular.length ? 2.6 : 1.7;
      for (let i = 0; i < n; i++) {
        const stutter = nerveIrregular.length ? `keyPoints="0;0.35;0.35;1" keyTimes="0;0.4;0.7;1" calcMode="linear"` : '';
        s += `<circle r="2.2" class="impulse ${nerveIrregular.length ? 'irr' : ''}"><animateMotion dur="${dur}s" begin="-${(i * dur / n).toFixed(2)}s" repeatCount="indefinite" ${stutter}><mpath href="#nv-${k}"/></animateMotion></circle>`;
      }
    });
    if (lesionY) s += `<g class="lesion"><circle cx="200" cy="${lesionY}" r="9"/><circle cx="200" cy="${lesionY}" r="9" class="pulse"/></g>
      <rect x="196" y="${lesionY + 6}" width="8" height="${330 - lesionY}" class="cord-dead"/>`;
    return s;
  }

  /* ------------------------------------------------------------------ lymphatics */
  function lymph() {
    const nodes = [[186, 150], [214, 150], [150, 230], [250, 230], [200, 236], [192, 384], [210, 392], [170, 484], [230, 484], [178, 160], [222, 160]];
    const r = lymphActive.length ? 5.6 : 3.4;
    let s = `<path d="M186,150 C180,190 170,215 150,230 M214,150 C220,190 230,215 250,230 M200,236 L200,384 M150,230 C170,300 186,360 192,384 M250,230 C230,300 214,360 210,392 M192,384 C184,430 176,460 170,484 M210,392 C218,430 224,460 230,484" class="lymph-v"/>`;
    s += `<path d="M232,312 C250,304 262,320 256,338 C250,352 236,350 232,340 Z" class="spleen ${lymphActive.length ? 'active' : ''}"><title>Spleen</title></path>`;
    nodes.forEach(([x, y], i) => { s += `<circle cx="${x}" cy="${y}" r="${r}" class="node ${lymphActive.length ? 'active' : ''}" style="animation-delay:${(i * .17).toFixed(2)}s"><title>Lymph node</title></circle>`; });
    return s;
  }

  /* ------------------------------------------------------------------ mount */
  const layers = document.createElementNS(NS, 'g');
  layers.setAttribute('id', 'layers');
  layers.innerHTML = `<g class="layer layer-skeleton ${weakBone ? 'weak' : ''}">${skeleton()}</g><g class="layer layer-nerves">${nerves()}</g><g class="layer layer-lymph">${lymph()}</g>`;
  const organs = svg.querySelector('.organs');
  svg.insertBefore(layers, organs);
  // highlight what the findings point to
  realSpine.forEach(sf => { const v = layers.querySelector(`[data-level="${sf.level}"]`); if (v) { v.classList.add('hit', `k-${sf.kind}`); v.querySelector('title').textContent = `${sf.level}: ${sf.text}`; } });
  if (realSpine.some(s => s.kind === 'disc')) realSpine.filter(s => s.kind === 'disc').forEach(sf => { const y = levelY(sf.level); if (y) layers.querySelector('.layer-skeleton').insertAdjacentHTML('beforeend', `<ellipse cx="205" cy="${y + 15}" rx="9" ry="3.6" class="disc-bulge"><title>Disc herniation at ${sf.level}</title></ellipse>`); });
  if (hands.inflamed) layers.querySelectorAll('.hand .joint-dot').forEach(j => j.classList.add('inflamed'));
  if (hands.fracture) layers.querySelectorAll(`.hand${hands.side ? `[data-side="${hands.side}"]` : ''} .meta`).forEach((m, i) => { if (i === 0) m.classList.add('broken'); });
  if (feet.gout) layers.querySelectorAll(`.foot${feet.side ? `[data-side="${feet.side}"]` : '[data-side="right"]'} .mtp1`).forEach(j => j.classList.add('inflamed', 'gout'));
  if (feet.fracture || feet.infection) layers.querySelectorAll(`.foot${feet.side ? `[data-side="${feet.side}"]` : ''} .tarsal`).forEach(t => t.classList.add(feet.infection ? 'infected' : 'broken'));
  longBones.forEach(b => {
    const sel = {femur: '.femur', tibia: '.long:not(.thin):not(.femur)', humerus: '.long', radius: '.thin', clavicle: '.long'}[b.bone];
    const paths = [...layers.querySelectorAll(`.layer-skeleton ${sel}`)];
    const pick = paths.filter(p => (b.side === 'left') === (parseFloat(p.getAttribute('d').slice(1)) > 200));
    if (pick[0]) pick[0].classList.add(b.healing ? 'healing' : 'broken');
  });

  if (fundusY) {
    const top = fundusY, h = 486 - top, w = Math.min(96, 30 + h * .55), cy = top + h / 2, sc = Math.min(1, .25 + (pregnancy.weeks - 8) / 32);
    const womb = document.createElementNS(NS, 'g');
    womb.setAttribute('class', 'bm-preg');
    womb.innerHTML = `<title>Pregnancy, ${pregnancy.weeks} weeks</title>
      <ellipse cx="200" cy="${cy}" rx="${w / 2}" ry="${h / 2}" class="womb"/><ellipse cx="200" cy="${cy}" rx="${w / 2 - 5}" ry="${h / 2 - 5}" class="fluid"/>
      <path d="M${200 + w / 2 - 6},${top + h * .22} q8,${h * .2} 0,${h * .4}" class="placenta"/>
      <g class="fetus" transform="translate(200,${cy + 4}) scale(${(sc * h / 120).toFixed(3)})">
        <circle cx="-6" cy="-26" r="15" class="skin"/><path d="M-14,-12 C-30,6 -22,34 0,40 C22,42 30,22 22,4 C16,-8 4,-14 -14,-12Z" class="skin"/>
        <path d="M8,30 C20,34 24,22 16,14" class="limb"/><path d="M-12,-4 C-20,6 -14,14 -6,10" class="limb"/>
        <circle cx="2" cy="4" r="3.2" class="fhr" style="animation-duration:${(60 / (pregnancy.fhr || 140)).toFixed(2)}s"/>
        <path d="M2,14 C14,10 22,-4 ${(w / 2 - 6) / (sc * h / 120)},-${h * .12}" class="cord"/></g>`;
    svg.querySelector('.organs').appendChild(womb);
    svg.querySelectorAll('.organs [data-sys="reproductive"] > *').forEach(n => { n.style.opacity = '.0'; });   // the enlarged womb replaces the small drawing
  }

  // blood disorders on the body: vaso-occlusion and pain in sickle crisis, bleeding spots with low platelets, jaundice, big spleen
  {
    let fx = '';
    if (blood.crisis) [[150, 560, 'Thigh bone'], [250, 560, 'Thigh bone'], [92, 300, 'Arm'], [200, 300, 'Spine'], [170, 250, 'Chest (acute chest syndrome)'], [230, 250, 'Chest']].forEach(([x, y, t], i) => {
      fx += `<g class="voc" style="animation-delay:${(i * .3).toFixed(1)}s"><circle cx="${x}" cy="${y}" r="10" class="voc-ring"/><path d="M${x - 4},${y - 2} C${x - 2},${y - 5} ${x + 2},${y - 5} ${x + 4},${y - 2} C${x + 1},${y - 3.5} ${x - 1},${y - 3.5} ${x - 4},${y - 2} M${x - 4},${y + 3} C${x - 2},${y} ${x + 2},${y} ${x + 4},${y + 3}" class="voc-cells"/><title>Vaso-occlusion: sickled cells blocking small vessels (${t})</title></g>`;
    });
    if (blood.lowPlt || blood.bleeding) {
      const pts = [[160, 600], [168, 640], [240, 610], [234, 660], [150, 700], [252, 720], [92, 380], [308, 400], [182, 300], [220, 330], [160, 520], [244, 540], [86, 430], [316, 450]];
      pts.forEach(([x, y], i) => { fx += `<circle cx="${x + (i % 3) * 3}" cy="${y}" r="${i % 4 ? 1.6 : 4.2}" class="${i % 4 ? 'petechia' : 'bruise'}"><title>${i % 4 ? 'Petechiae: pinpoint bleeding under the skin' : 'Bruise'}</title></circle>`; });
    }
    if (fx) { const gx = document.createElementNS(NS, 'g'); gx.setAttribute('class', 'blood-fx'); gx.innerHTML = fx; svg.querySelector('#markers').before(gx); }
    svg.classList.toggle('jaundice', !!blood.jaundice);
    if (blood.bigSpleen) layers.querySelector('.spleen')?.classList.add('big');
  }

  /* ------------------------------------------------------------------ layer switches */
  const want = {skeleton: !!(realSpine.length || hands.inflamed || hands.fracture || feet.gout || feet.fracture || feet.infection || longBones.length),
                nerves: !!(cordInjury || nerveIrregular.length), lymph: !!(lymphActive.length || blood.bigSpleen)};
  const LAYERS = [['organs', 'Organs', 'bi-heart-pulse'], ['skeleton', 'Skeleton', 'bi-person-standing'], ['circulation', 'Circulation', 'bi-droplet-half'],
                  ['nerves', 'Nerves', 'bi-lightning'], ['lymph', 'Lymphatic', 'bi-diagram-3']];
  const on = {organs: true, circulation: true, skeleton: want.skeleton, nerves: want.nerves, lymph: want.lymph};
  const notes = [];
  if (realSpine.length) notes.push(`Spine: ${realSpine.map(s => `${s.level} ${s.kind === 'cord' ? 'cord injury' : s.kind}`).join(', ')}`);
  if (hands.inflamed) notes.push('Hand joints inflamed (rheumatoid pattern)');
  if (hands.fracture) notes.push(`Hand fracture${hands.side ? ` (${hands.side})` : ''}`);
  if (feet.gout) notes.push('Big-toe joint: gout');
  if (feet.fracture) notes.push(`Foot/ankle fracture${feet.side ? ` (${feet.side})` : ''}`);
  if (feet.infection) notes.push('Foot bone infection');
  longBones.forEach(b => notes.push(`${b.side} ${b.bone}: ${b.healing ? 'healing' : 'fracture'}`));
  if (weakBone) notes.push('Bones shown thinner (low vitamin D / calcium)');
  if (cordInjury) notes.push(`Nerve signals stop below ${cordInjury.level}`);
  if (pregnancy) notes.push(pregnancy.ectopic ? `Ectopic pregnancy (${pregnancy.ectopic.side} tube)` : `Pregnancy, ${pregnancy.weeks} weeks · fetal heart ${pregnancy.fhr}/min`);
  if (repro.prostate) notes.push(`Prostate enlarged${repro.psa ? ` (PSA ${repro.psa})` : ''}`);
  if (nerveIrregular.length) notes.push(`Nerve impulses irregular: ${nerveIrregular.join(', ')} out of range`);
  if (lymphActive.length) notes.push(`Lymph nodes active: ${lymphActive.join(', ')} raised`);
  if (anaemia) notes.push('Blood paler: low haemoglobin');
  const BLOOD_NOTE = {sickle: blood.crisis ? 'Sickle cell crisis: sickled cells blocking vessels in bones and chest' : 'Sickle cell disease: sickle-shaped red cells',
    iron: 'Iron deficiency: small, pale red cells', thal: 'Thalassaemia: small target cells', macro: 'Large red cells (B12/folate)', leuk: 'Leukaemia: immature white cells (blasts) in the blood',
    lowplt: 'Low platelets: pinpoint bleeding (petechiae) and bruises', haemolysis: blood.g6pd ? 'G6PD deficiency: red cells breaking down (jaundice)' : 'Red cells breaking down (haemolysis)',
    poly: 'Too many red cells: thick blood', malaria: 'Malaria parasites in red cells'};
  if (blood.primary) notes.push(BLOOD_NOTE[blood.primary]);
  if (blood.trait && !blood.sickle) notes.push('Sickle cell trait (carrier): cells normal in everyday life');
  if (blood.bigSpleen) notes.push('Spleen enlarged');
  if (hr && Math.abs(hr - 76) > 20) notes.push(`Blood flow ${hr > 76 ? 'faster' : 'slower'}: pulse ${hr}/min`);
  const bar = document.createElement('div');
  bar.className = 'layer-bar';
  bar.innerHTML = `<div class="layer-btns" role="group" aria-label="Body systems">${LAYERS.map(([k, l, i]) => `<button type="button" class="lb ${on[k] ? 'on' : ''}" data-layer="${k}" aria-pressed="${on[k]}"><i class="bi ${i}"></i>${l}</button>`).join('')}</div>
    ${notes.length ? `<div class="layer-notes">${notes.map(n => `<span>${esc(n)}</span>`).join('')}</div>` : ''}`;
  const stage = svg.closest('.body-stage');
  stage.insertBefore(bar, stage.querySelector('.stage-tools').nextSibling);
  const apply = () => {
    svg.classList.toggle('hide-organs', !on.organs); svg.classList.toggle('see-through', on.organs && (on.skeleton || on.nerves || on.lymph));
    svg.classList.toggle('hide-circ', !on.circulation);
    layers.querySelector('.layer-skeleton').style.display = on.skeleton ? '' : 'none';
    layers.querySelector('.layer-nerves').style.display = on.nerves ? '' : 'none';
    layers.querySelector('.layer-lymph').style.display = on.lymph ? '' : 'none';
    svg.classList.toggle('pale-blood', anaemia); svg.classList.toggle('low-o2', lowO2);
    bar.querySelectorAll('.lb').forEach(b => { b.classList.toggle('on', on[b.dataset.layer]); b.setAttribute('aria-pressed', on[b.dataset.layer]); });
  };
  bar.addEventListener('click', e => { const b = e.target.closest('.lb'); if (!b) return; on[b.dataset.layer] = !on[b.dataset.layer]; apply(); });
  // clicking a bone opens the bone detail
  layers.querySelector('.layer-skeleton').addEventListener('click', () => { const m = svg.querySelector('.mk[data-sys="bone"]'); if (m) m.dispatchEvent(new MouseEvent('click', {bubbles: true})); });
  apply();
})();
