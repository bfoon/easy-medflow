/* Realistic, animated anatomy for the lab insights pop-out.
   Adds the organs that previously fell back to a plain circle (stomach & gut, bladder, reproductive, bones)
   and replaces the simple brain, thyroid, pancreas and immune drawings with shaded, textured versions.
   Load after organs.js (and organs-real.js). Teaching illustrations only: the patient's results decide what is shown. */
(() => {
  'use strict';
  const ART = window.__MF_ART, H = (window.MedFlowOrgans || {}).helpers;
  if (!ART || !H) return;
  const {part, rnd, scale} = H;
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const DEFS = `<filter id="ox-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="8" result="n"/>
    <feColorMatrix in="n" type="saturate" values="0" result="g"/><feComposite in="g" in2="SourceGraphic" operator="in" result="gi"/><feBlend in="SourceGraphic" in2="gi" mode="multiply"/></filter>
    <filter id="ox-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <filter id="ox-shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="3" stdDeviation="3" flood-color="#3A1E1A" flood-opacity=".22"/></filter>`;

  // particles riding a path (SMIL so they follow curves); nothing moves when reduced motion is requested
  const ride = (path, cls, n, dur, r = 2.6, rotate = false) => still ? '' : Array.from({length: n}, (_, i) =>
    `<circle r="${r}" class="${cls}"><animateMotion dur="${dur}s" repeatCount="indefinite" begin="-${(i * dur / Math.max(1, n)).toFixed(2)}s" path="${path}"${rotate ? ' rotate="auto"' : ''}/></circle>`).join('');
  const rideShape = (path, shape, n, dur) => still ? '' : Array.from({length: n}, (_, i) =>
    `<g>${shape}<animateMotion dur="${dur}s" repeatCount="indefinite" begin="-${(i * dur / Math.max(1, n)).toFixed(2)}s" path="${path}" rotate="auto"/></g>`).join('');
  const low = (r, c) => ['L', 'LL'].includes(r.flag(c)), high = (r, c) => ['H', 'HH'].includes(r.flag(c));
  const grade = (r, c) => (r.txt(c) || '').trim();
  const patientSex = () => { try { return (JSON.parse(document.getElementById('lab-data').textContent).patient || {}).sex || ''; } catch (e) { return ''; } };
  const shorten = (s, n) => s && s.length > n ? s.slice(0, n - 1) + '…' : s;

  /* ================================================================ STOMACH & GUT */
  ART.stomach = r => {
    const blood = r.abn('FOB'), worms = r.abn('OVA'), hp = r.abn('HPYL'), note = r.txt('NOTE');
    const ROUTE = 'M150,0 L160,40 C186,52 214,76 202,100 C190,116 158,110 140,106 C118,106 106,120 110,140 C112,152 128,154 150,152 C190,148 222,154 226,166 C230,180 122,172 118,186 C114,200 228,192 232,206 C234,220 132,216 128,226';
    const SMALL = 'M150,152 C190,148 222,154 226,166 C230,180 122,172 118,186 C114,200 228,192 232,206 C234,220 132,216 128,226';
    const COLON = 'M96,234 L86,160 C84,146 94,140 108,141 L254,144 C270,145 276,154 274,168 L268,234';
    const DUO = 'M140,106 C118,106 106,120 110,140 C112,152 128,154 150,152';
    const tube = (d, outer, inner, w) => `<path d="${d}" stroke="${outer}" stroke-width="${w}" fill="none" stroke-linecap="round" filter="url(#ox-grain)"/><path d="${d}" stroke="${inner}" stroke-width="${w * .55}" fill="none" stroke-linecap="round" opacity=".85"/>`;
    const worm = `<path d="M-9,0 q2.2,-3 4.5,0 t4.5,0 t4.5,0 t4.5,0" class="ox-worm">${still ? '' : '<animate attributeName="d" dur=".9s" repeatCount="indefinite" values="M-9,0 q2.2,-3 4.5,0 t4.5,0 t4.5,0 t4.5,0;M-9,0 q2.2,3 4.5,0 t4.5,0 t4.5,0 t4.5,0;M-9,0 q2.2,-3 4.5,0 t4.5,0 t4.5,0 t4.5,0"/>'}</path>`;
    const villi = Array.from({length: 6}, (_, i) => { const x = 24 + i * 11.5;
      return `<g class="ox-villus" style="animation-delay:-${(i * .4).toFixed(1)}s"><path d="M${x - 4.5},100 C${x - 5.5},78 ${x - 4},64 ${x},62 C${x + 4},64 ${x + 5.5},78 ${x + 4.5},100Z" fill="url(#ox-villus)" stroke="#C47A62" stroke-width=".8"/>
        <path d="M${x - 1.6},98 C${x - 2},80 ${x - 1},70 ${x},68 C${x + 1},70 ${x + 2},80 ${x + 1.6},98" stroke="#C81E2C" stroke-width="1" fill="none" opacity=".7"/></g>`; }).join('');
    const notes = [hp && 'H. pylori positive: inflamed stomach lining with spiral bacteria',
      blood && 'Occult blood positive: a bleeding point is shown in the bowel. The test cannot tell where bleeding starts',
      worms && 'Ova or parasites seen: worms shown in the small intestine',
      note && `Microscopy: ${shorten(note, 80)}`,
      !hp && !blood && !worms && 'Stool tests within range: food moving normally through the gut'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 240" class="oa ox ox-gut ${hp ? 'gastritis' : ''} ${blood ? 'bleed' : ''}"><defs>${DEFS}
      <radialGradient id="ox-st" cx="55%" cy="35%" r="70%"><stop offset="0" stop-color="#F7C2A8"/><stop offset=".6" stop-color="#E39577"/><stop offset="1" stop-color="#B86249"/></radialGradient>
      <linearGradient id="ox-villus" x1="0" x2="1"><stop offset="0" stop-color="#E9A189"/><stop offset=".5" stop-color="#F8CDBB"/><stop offset="1" stop-color="#E9A189"/></linearGradient>
      <clipPath id="ox-villi-clip"><circle cx="54" cy="60" r="38"/></clipPath></defs>
      ${part('small', 'Small intestine: about 6 metres long; absorbs nutrients', `<g>${tube(SMALL, '#C9806C', '#F4BFAB', 15)}<path d="${SMALL}" class="ox-peri" stroke-width="9"/></g>`)}
      ${part('duodenum', 'Duodenum: first part of the small intestine; bile and pancreatic juice enter here', tube(DUO, '#C9806C', '#F1B39C', 13))}
      ${part('colon', 'Large intestine (colon): absorbs water and forms stool', `<g>${tube(COLON, '#B97456', '#E8AE8C', 22)}<path d="${COLON}" stroke="#9C5A40" stroke-width="19" fill="none" stroke-dasharray="1.6 12" opacity=".3"/><path d="${COLON}" class="ox-peri slow" stroke-width="12"/></g>`)}
      ${ride(COLON, 'ox-stool', 4, 15, 4.2)}
      ${blood ? `<circle cx="271" cy="196" r="7" class="ox-bleed"/>${ride('M271,196 L269,234', 'ox-blooddrop', 3, 2.6, 2.2)}` : ''}
      ${part('oesophagus', 'Oesophagus: carries swallowed food to the stomach', tube('M150,0 C152,14 156,28 160,42', '#C9806C', '#EEB09A', 12))}
      <g class="ox-churn">${part('stomach', 'Stomach: churns food with acid and enzymes', `<path d="M158,40 C164,22 196,14 216,26 C244,44 256,80 242,106 C228,130 190,136 164,126 C154,122 148,114 140,113 L140,100 C150,99 158,100 166,98 C180,94 184,80 178,66 C172,56 162,50 158,40Z" fill="url(#ox-st)" filter="url(#ox-grain)"/>
        <path d="M176,40 C196,48 214,64 222,88 M184,56 C200,66 210,82 212,102 M172,112 C190,118 210,116 228,104 M198,30 C216,38 232,58 238,82" class="ox-rugae"/>
        <ellipse cx="206" cy="46" rx="18" ry="7" fill="#fff" opacity=".18" transform="rotate(28 206 46)"/>
        ${hp ? '<ellipse cx="214" cy="98" rx="11" ry="7" class="ox-gast"/><ellipse cx="190" cy="116" rx="9" ry="5" class="ox-gast"/><ellipse cx="226" cy="66" rx="8" ry="5" class="ox-gast"/>' : ''}`)}</g>
      ${hp ? [[208, 92], [220, 104], [186, 112], [228, 70], [196, 120]].map(([x, y], i) => `<path d="M${x - 4},${y} q2,-3 4,0 t4,0" class="ox-hp" style="animation-delay:-${(i * .3).toFixed(1)}s"/>`).join('') : ''}
      ${part('pylorus', 'Pylorus: a muscle ring that lets food out of the stomach a little at a time', '<ellipse cx="141" cy="106.5" rx="4.5" ry="8" class="ox-pylorus"/>')}
      ${ride(ROUTE, 'ox-bolus', 6, 10, 3.2)}
      ${worms ? rideShape(SMALL, worm, 3, 18) : ''}
      ${part('villi', 'Villi (magnified): finger-like folds that absorb food into the blood', `<g><circle cx="54" cy="60" r="38" fill="#FFF4EE" stroke="#C98466" stroke-width="2"/><g clip-path="url(#ox-villi-clip)"><rect x="10" y="98" width="90" height="10" fill="#E9A189"/>${villi}${ride('M30,96 L30,64', 'ox-nutrient', 2, 2.2, 1.6)}${ride('M65,96 L65,64', 'ox-nutrient', 2, 2.6, 1.6)}</g></g>`)}
      <path d="M86,82 L114,176" stroke="#C98466" stroke-dasharray="3 3"/>
    </svg>`, notes, parts: {
      oesophagus: 'The oesophagus pushes swallowed food down in waves (peristalsis).',
      stomach: 'The stomach churns food with acid and enzymes for 2 to 4 hours. H. pylori bacteria can inflame its lining and cause ulcers.',
      pylorus: 'The pylorus is a valve that releases small amounts of food into the duodenum.',
      duodenum: 'In the duodenum, bile from the liver and enzymes from the pancreas start breaking food down.',
      small: 'The small intestine absorbs most nutrients. Worms and parasites usually live here.',
      colon: 'The colon absorbs water and forms stool. Hidden (occult) blood in stool can come from anywhere along the gut, so a positive test needs follow-up.',
      villi: 'Millions of villi give the gut a surface area the size of a tennis court. Each has tiny blood vessels that carry nutrients away.'}};
  };

  /* ================================================================ BLADDER & URINE */
  ART.bladder = r => {
    const nit = r.abn('NIT'), leu = r.abn('LEU'), infection = nit || leu, app = grade(r, 'APP');
    const bloody = r.abn('UBLD') || app === 'Bloody', glu = r.abn('UGLU'), pro = r.abn('PRO');
    const sg = r.num('SG'), cloudy = ['Cloudy', 'Slightly cloudy'].includes(app);
    const urine = bloody ? '#DE8A72' : sg != null && sg >= 1.025 ? '#E3A63A' : sg != null && sg <= 1.008 ? '#F6EDB4' : '#F2D46A';
    const PADS = [
      ['LEU', 'LEU', {Negative: '#F3EDD2', Trace: '#EADDEA', '1+': '#DCC5E0', '2+': '#C3A0D0', '3+': '#9A6BB3'}],
      ['NIT', 'NIT', {Negative: '#FAF3E4', Positive: '#E79AB2'}],
      ['PRO', 'PRO', {Negative: '#E6EE98', Trace: '#D2E48C', '1+': '#B7D688', '2+': '#90C189', '3+': '#68AA8C'}],
      ['pH', 'PH', null],
      ['BLD', 'UBLD', {Negative: '#F2DA8C', Trace: '#CFC86E', '1+': '#A4B255', '2+': '#6F8E3A', '3+': '#3D6A2A'}],
      ['SG', 'SG', null],
      ['GLU', 'UGLU', {Negative: '#A0D5D5', Trace: '#A2CD9C', '1+': '#BBC46C', '2+': '#C99B4B', '3+': '#A0633A'}]];
    const padColour = (code, map) => {
      if (!r.has(code)) return '#E6EBEB';
      if (code === 'PH') { const v = r.num('PH'); return v == null ? '#E6EBEB' : v < 5.5 ? '#F3A23B' : v < 6.5 ? '#E9C43B' : v < 7.5 ? '#9DC23D' : v < 8.5 ? '#3E9C7A' : '#2E6E8E'; }
      if (code === 'SG') { const v = r.num('SG'); return v == null ? '#E6EBEB' : v < 1.010 ? '#2F6F6F' : v < 1.020 ? '#7E9A4A' : '#C9A83A'; }
      return map[grade(r, code)] || '#E6EBEB';
    };
    const pads = PADS.map(([lbl, code, map], i) => `<rect x="286" y="${34 + i * 25}" width="18" height="16" rx="2" fill="${padColour(code, map)}" stroke="#C7CFCF" stroke-width=".8"/><text x="281" y="${45 + i * 25}" text-anchor="end" class="oa-lbl">${lbl}</text>`).join('');
    let inside = '';
    if (infection) for (let i = 0; i < 9; i++) inside += `<rect x="-4" y="-1.4" width="8" height="2.8" rx="1.4" class="ox-rod" style="--x:${(130 + rnd() * 80).toFixed(0)}px;--y:${(120 + rnd() * 36).toFixed(0)}px;animation-delay:-${(rnd() * 2).toFixed(1)}s"/>`;
    if (leu) for (let i = 0; i < 3; i++) inside += `<circle r="5" class="ox-uwbc" cx="${(140 + rnd() * 60).toFixed(0)}" cy="${(128 + rnd() * 24).toFixed(0)}"/>`;
    if (bloody) for (let i = 0; i < 6; i++) inside += `<ellipse rx="3.4" ry="2.4" class="ox-urbc" cx="${(132 + rnd() * 76).toFixed(0)}" cy="${(124 + rnd() * 32).toFixed(0)}"/>`;
    if (glu) for (let i = 0; i < 5; i++) inside += `<rect width="5" height="5" rx="1" class="sugar" x="${(134 + rnd() * 70).toFixed(0)}" y="${(124 + rnd() * 30).toFixed(0)}"/>`;
    if (pro) for (let i = 0; i < 10; i++) inside += `<circle r="${(1.6 + rnd() * 2.6).toFixed(1)}" class="ox-foam" cx="${(124 + rnd() * 92).toFixed(0)}" cy="${(108 + rnd() * 6).toFixed(0)}"/>`;
    const notes = [sg != null && `Specific gravity ${sg}${sg >= 1.025 ? ': concentrated urine (drink more water?)' : sg <= 1.008 ? ': dilute urine' : ''}`,
      infection && `Signs of infection (${[nit && 'nitrite', leu && 'leukocytes'].filter(Boolean).join(' and ')}): bacteria and white cells in the urine`,
      bloody && 'Blood in the urine: red cells shown', glu && 'Glucose in the urine: often means blood sugar is high', pro && 'Protein in the urine: shown as foam; can mean kidney damage',
      cloudy && !infection && `Appearance: ${app.toLowerCase()}`,
      !infection && !bloody && !glu && !pro && 'Urine tests within range'].filter(Boolean);
    const UL = 'M86,0 C92,40 104,70 124,96', UR = 'M254,0 C248,40 236,70 216,96';
    return {svg: `<svg viewBox="0 0 340 230" class="oa ox ox-bladder ${cloudy || infection ? 'cloudy' : ''}" style="--urine:${urine}"><defs>${DEFS}
      <radialGradient id="ox-bw" cx="45%" cy="35%" r="70%"><stop offset="0" stop-color="#F6CFC3"/><stop offset=".65" stop-color="#E2A094"/><stop offset="1" stop-color="#B9706A"/></radialGradient>
      <clipPath id="ox-bl-in"><path d="M122,100 C118,74 146,66 170,68 C194,66 222,74 218,100 C214,136 196,158 170,160 C144,158 126,136 122,100Z"/></clipPath></defs>
      ${part('ureters', 'Ureters: carry urine from each kidney to the bladder', `<g><path d="${UL}" stroke="#D9B48E" stroke-width="9" fill="none" stroke-linecap="round"/><path d="${UR}" stroke="#D9B48E" stroke-width="9" fill="none" stroke-linecap="round"/><path d="${UL}" stroke="#F3DDB9" stroke-width="4" fill="none"/><path d="${UR}" stroke="#F3DDB9" stroke-width="4" fill="none"/></g>`)}
      ${ride(UL, 'ox-udrop', 3, 2.8, 2.4)}${ride(UR, 'ox-udrop', 3, 3.1, 2.4)}
      ${part('bladder', 'Bladder: a stretchy muscle bag that stores urine', `<g filter="url(#ox-shadow)"><path d="M112,98 C106,66 140,54 170,56 C200,54 234,66 228,98 C224,142 200,170 180,174 L180,184 L160,184 L160,174 C140,170 116,142 112,98Z" fill="url(#ox-bw)" filter="url(#ox-grain)"/>
        <path d="M120,84 C150,72 190,72 220,84 M116,108 C150,98 190,98 224,108 M124,134 C150,126 190,126 216,134" stroke="#B9706A" stroke-width="1" fill="none" opacity=".45"/>
        <path d="M122,100 C118,74 146,66 170,68 C194,66 222,74 218,100 C214,136 196,158 170,160 C144,158 126,136 122,100Z" fill="#FFF6EF"/>
        <g clip-path="url(#ox-bl-in)"><g class="ox-fill"><path class="ox-urine" d="M60,110 q15,-5 30,0 t30,0 t30,0 t30,0 t30,0 t30,0 t30,0 V220 H60Z"/>${inside}</g>
        <path d="M150,150 L190,150 L170,162Z" fill="#E2A094" opacity=".35"/></g></g>`)}
      ${part('urethra', 'Urethra: carries urine out of the body; a sphincter muscle keeps it closed', `<g><path d="M170,184 L170,228" stroke="#E2A094" stroke-width="9" stroke-linecap="round"/><path d="M170,184 L170,228" stroke="#F6D8CC" stroke-width="3.5"/><ellipse cx="170" cy="184" rx="9" ry="3.4" class="ox-sphincter"/></g>`)}
      ${ride('M170,186 L170,232', 'ox-udrop', 2, 3.4, 2.2)}
      ${part('dipstick', 'Urine dipstick: each pad changes colour for one test', `<g><rect x="283" y="14" width="24" height="210" rx="4" fill="#FFFFFF" stroke="#C7CFCF"/><rect x="283" y="14" width="24" height="14" rx="4" fill="#DCE5E5"/>${pads}</g>`)}
    </svg>`, notes, parts: {
      ureters: 'Each ureter squeezes urine down from a kidney in small spurts.',
      bladder: 'The bladder holds about 400 to 600 mL. Its colour on screen follows the urine results: darker when concentrated, red with blood, cloudy with infection.',
      urethra: 'The urethra drains the bladder. Bacteria travelling up it cause most urinary tract infections.',
      dipstick: 'The dipstick pads shown use the patient\'s own results: leukocytes, nitrite, protein, pH, blood, specific gravity and glucose. Grey pads were not tested.'}};
  };

  /* ================================================================ REPRODUCTIVE */
  ART.reproductive = r => {
    const sex = patientSex(), male = sex === 'M' || (sex !== 'F' && r.has('PSA') && !r.has('HCG'));
    return male ? prostate(r) : uterus(r);
  };

  function uterus(r) {
    const preg = (grade(r, 'HCG') || '').startsWith('Positive');
    const fimb = (x, y, dir) => Array.from({length: 6}, (_, i) => { const a = (dir < 0 ? Math.PI : 0) + (-1 + i * .4) * dir;
      return `<path d="M${x},${y} l${(Math.cos(a) * 10).toFixed(1)},${(Math.sin(a) * 10).toFixed(1)}" stroke="#E39CB0" stroke-width="2.4" stroke-linecap="round"/>`; }).join('');
    const follicles = (cx, cy) => Array.from({length: 6}, () => `<circle cx="${(cx - 12 + rnd() * 24).toFixed(1)}" cy="${(cy - 7 + rnd() * 14).toFixed(1)}" r="${(1.6 + rnd() * 2.2).toFixed(1)}" fill="#FBE8D0" stroke="#D9A88E" stroke-width=".5"/>`).join('');
    const EGG = 'M86,92 C80,82 76,76 78,70 C96,52 120,50 142,64 C152,70 162,80 170,96';
    const notes = [preg && 'β-hCG positive: early pregnancy shown implanted in the uterus', !preg && r.has('HCG') && 'β-hCG negative: monthly cycle shown with an egg travelling down the tube',
      !r.has('HCG') && 'No pregnancy test resulted: monthly cycle shown'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 220" class="oa ox ox-uterus ${preg ? 'preg' : ''}"><defs>${DEFS}
      <radialGradient id="ox-ut" cx="45%" cy="30%" r="75%"><stop offset="0" stop-color="#F3B9C8"/><stop offset=".6" stop-color="#D88199"/><stop offset="1" stop-color="#A5506A"/></radialGradient>
      <radialGradient id="ox-ov" cx="40%" cy="35%" r="70%"><stop offset="0" stop-color="#F8E2D2"/><stop offset="1" stop-color="#D9A88E"/></radialGradient></defs>
      ${part('tubes', 'Fallopian tubes: carry the egg from the ovary to the uterus; fertilisation happens here', `<g><path d="M142,64 C120,50 96,52 80,68" stroke="#D98AA0" stroke-width="7" fill="none" stroke-linecap="round"/><path d="M198,64 C220,50 244,52 260,68" stroke="#D98AA0" stroke-width="7" fill="none" stroke-linecap="round"/>${fimb(78, 70, -1)}${fimb(262, 70, 1)}</g>`)}
      ${part('ovaries', 'Ovaries: hold the eggs and make oestrogen and progesterone', `<g><path d="M100,92 C118,96 130,92 142,80 M240,92 C222,96 210,92 198,80" stroke="#E3B7A6" stroke-width="2.4" fill="none"/>
        <ellipse cx="84" cy="96" rx="20" ry="13" fill="url(#ox-ov)" filter="url(#ox-grain)"/>${follicles(84, 96)}<circle cx="92" cy="92" r="5" class="ox-follicle"/>
        <ellipse cx="256" cy="96" rx="20" ry="13" fill="url(#ox-ov)" filter="url(#ox-grain)"/>${follicles(256, 96)}</g>`)}
      ${part('uterus', 'Uterus (womb): a thick muscle wall with a lining that grows each month', `<g filter="url(#ox-shadow)"><path d="M140,60 C140,46 200,46 200,60 C204,96 190,130 180,150 L180,176 L160,176 L160,150 C150,130 136,96 140,60Z" fill="url(#ox-ut)" filter="url(#ox-grain)"/>
        <path d="M150,66 C160,62 180,62 190,66 C186,96 176,122 170,138 C164,122 154,96 150,66Z" class="ox-endo"/>
        <ellipse cx="156" cy="62" rx="12" ry="4" fill="#fff" opacity=".2"/></g>`)}
      ${part('cervix', 'Cervix and vagina: the neck of the womb and the birth canal', '<path d="M160,176 L180,176 L186,216 L154,216Z" fill="#E7A9B9" opacity=".9"/><ellipse cx="170" cy="177" rx="6" ry="2" fill="#A5506A"/>')}
      ${preg ? `<g class="ox-sac"><circle cx="170" cy="98" r="13" fill="#FDE7EC" stroke="#E39CB0" stroke-width="1.5"/><path d="M164,100 C162,92 170,88 175,93 C179,98 175,106 169,105" fill="#F2B5A0"/><circle cx="170" cy="97" r="1.8" class="ox-fetal-heart"/></g>` :
        `${still ? '' : `<g><circle r="4.6" fill="#FFF3D6" stroke="#E9C46A" stroke-width="2"/><circle r="1.6" fill="#E9A23B"/><animateMotion dur="11s" repeatCount="indefinite" path="${EGG}"/></g>`}`}
    </svg>`, notes, parts: {
      ovaries: 'Each month one follicle matures (shown glowing) and releases an egg.',
      tubes: 'The fimbriae sweep the released egg into the tube. Sperm usually meets the egg in the outer part of the tube.',
      uterus: 'If an embryo implants, it releases β-hCG, the hormone that pregnancy tests detect.',
      cervix: 'The cervix stays closed during pregnancy and opens in labour.'}};
  }

  function prostate(r) {
    const psa = r.num('PSA'), big = r.abn('PSA');
    const nPsa = psa != null ? scale(psa, 0, 20, 2, 12) : 3;
    const URE = 'M170,74 L170,226';
    const notes = [psa != null && `PSA ${psa} ng/mL`, big && 'PSA above range: prostate shown enlarged and narrowing the urethra. Causes include benign enlargement, infection or cancer',
      !big && 'Prostate markers within range'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 230" class="oa ox ox-prostate ${big ? 'big' : ''}"><defs>${DEFS}
      <radialGradient id="ox-pr" cx="40%" cy="35%" r="70%"><stop offset="0" stop-color="#E9B39D"/><stop offset=".65" stop-color="#C97F66"/><stop offset="1" stop-color="#97523F"/></radialGradient>
      <radialGradient id="ox-bw2" cx="45%" cy="35%" r="70%"><stop offset="0" stop-color="#F6CFC3"/><stop offset="1" stop-color="#C98478"/></radialGradient></defs>
      ${part('bladder', 'Bladder: sits just above the prostate', '<path d="M106,60 C100,20 140,8 170,10 C200,8 240,20 234,60 C230,80 206,90 170,90 C134,90 110,80 106,60Z" fill="url(#ox-bw2)" filter="url(#ox-grain)"/><path d="M130,40 C150,32 190,32 210,40" stroke="#B9706A" fill="none" opacity=".4"/>')}
      ${part('vesicles', 'Seminal vesicles and vas deferens: make and carry the fluid that sperm travel in', `<g><path d="M146,98 C128,88 114,80 100,84 C92,88 96,98 106,98 C116,98 126,100 140,106" fill="#E3C08C" stroke="#B9935E" stroke-width="1.2"/><path d="M194,98 C212,88 226,80 240,84 C248,88 244,98 234,98 C224,98 214,100 200,106" fill="#E3C08C" stroke="#B9935E" stroke-width="1.2"/>
        <path d="M40,40 C70,60 100,90 150,112 M300,40 C270,60 240,90 190,112" stroke="#D9B48E" stroke-width="3" fill="none"/></g>`)}
      <g class="ox-pr-box">${part('prostate', 'Prostate: a walnut-sized gland around the urethra that makes PSA', `<g filter="url(#ox-shadow)"><path d="M136,112 C136,92 204,92 204,112 C206,140 188,156 170,156 C152,156 134,140 136,112Z" fill="url(#ox-pr)" filter="url(#ox-grain)"/>
        <path d="M150,104 C148,120 152,140 160,150 M190,104 C192,120 188,140 180,150 M146,124 C156,128 184,128 194,124" stroke="#97523F" stroke-width="1" fill="none" opacity=".5"/></g>`)}</g>
      ${part('urethra', 'Urethra: passes straight through the prostate', `<path d="${URE}" class="ox-ure"/>`)}
      ${ride(URE, 'ox-udrop', big ? 2 : 5, big ? 6 : 2.6, 2.2)}
      <path d="M204,126 C236,126 268,118 320,106" stroke="#3E5BA8" stroke-width="6" fill="none" stroke-linecap="round" opacity=".7"/>
      ${ride('M204,126 C236,126 268,118 320,106', 'ox-psa', nPsa, 3.2, 2)}
      <text x="232" y="142" class="oa-lbl">PSA into the blood</text>
    </svg>`, notes, parts: {
      prostate: 'The prostate makes part of the seminal fluid, including PSA. An enlarged prostate can squeeze the urethra and slow the urine stream.',
      urethra: 'Urine and semen leave through the urethra. The drops on screen slow down when the prostate is enlarged.',
      vesicles: 'The seminal vesicles add sugar-rich fluid; the vas deferens carries sperm up from the testes.',
      bladder: 'The bladder neck rests on top of the prostate.'}};
  }

  /* ================================================================ BONES & JOINTS */
  ART.bone = r => {
    const ca = r.num('CA'), lowCa = low(r, 'CA'), lowD = low(r, 'VITD'), alp = high(r, 'ALP'), uric = high(r, 'URIC'), rf = r.abn('RF');
    const weak = lowCa || lowD;
    const nCa = ca != null ? scale(ca, 1.6, 3.0, 2, 10) : 6;
    const F = 'M30,84 C30,62 56,54 70,66 C78,72 80,80 86,84 C92,74 104,72 110,80 C116,88 112,100 120,104 L242,104 C254,104 262,90 278,90 C298,90 312,104 310,120 C312,138 298,152 280,150 C264,150 256,138 242,136 L122,136 C104,136 90,128 80,116 C72,108 64,112 54,110 C38,108 30,98 30,84Z';
    const marrow = weak ? 'M126,108 L240,108 C245,112 245,128 240,132 L126,132 C121,128 121,112 126,108Z' : 'M130,112 L236,112 C240,114 240,126 236,128 L130,128 C126,126 126,114 130,112Z';
    const holes = (n, rmax) => Array.from({length: n}, () => `<ellipse cx="${(rnd() * 14).toFixed(1)}" cy="${(rnd() * 14).toFixed(1)}" rx="${(1 + rnd() * rmax).toFixed(1)}" ry="${(1 + rnd() * rmax * .7).toFixed(1)}" fill="#FBF0D4"/>`).join('');
    const lamellae = Array.from({length: 5}, (_, k) => `<circle cx="58" cy="184" r="${(k + 1) * 5.6}" class="ox-lamella" style="animation-delay:${(k * .25).toFixed(2)}s"/>`).join('');
    const lacunae = Array.from({length: 12}, () => { const a = rnd() * 6.28, d = 8 + rnd() * 20; return `<ellipse cx="${(58 + Math.cos(a) * d).toFixed(1)}" cy="${(184 + Math.sin(a) * d).toFixed(1)}" rx="2" ry="1" fill="#8A6A44" transform="rotate(${(a * 57.3 + 90).toFixed(0)} ${(58 + Math.cos(a) * d).toFixed(1)} ${(184 + Math.sin(a) * d).toFixed(1)})"/>`; }).join('');
    const blasts = Array.from({length: 8}, (_, i) => `<rect x="${140 + i * 12}" y="${weak ? 132 : 128}" width="7" height="5" rx="1.2" class="ox-blast" style="animation-delay:-${(i * .3).toFixed(1)}s"/>`).join('');
    const crystals = uric ? Array.from({length: 9}, (_, i) => { const x = 292 + rnd() * 16, y = 104 + rnd() * 34, a = rnd() * 180; return `<path d="M${x.toFixed(1)},${y.toFixed(1)} l6,0" transform="rotate(${a.toFixed(0)} ${x.toFixed(1)} ${y.toFixed(1)})" class="ox-urate" style="animation-delay:-${(i * .2).toFixed(1)}s"/>`; }).join('') : '';
    const notes = [ca != null && `Calcium ${ca} mmol/L${lowCa ? ': fewer calcium particles reaching the bone' : ''}`,
      lowD && `Vitamin D ${r.txt('VITD')}: less calcium absorbed, so the bone is shown thinner and less dense`,
      alp && `Alkaline phosphatase ${r.txt('ALP')}: bone-building cells shown working harder`,
      uric && `Uric acid ${r.txt('URIC')}: urate crystals shown in the joint (risk of gout)`, rf && 'Rheumatoid factor positive: inflamed joint lining shown',
      !weak && !alp && !uric && !rf && 'Bone tests within range: bone being renewed normally'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 230" class="oa ox ox-bone ${weak ? 'weak' : ''} ${alp ? 'active' : ''}"><defs>${DEFS}
      <linearGradient id="ox-cort" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#FBF6E8"/><stop offset=".45" stop-color="#EDE2C6"/><stop offset="1" stop-color="#C9B68E"/></linearGradient>
      <pattern id="ox-spongy" width="14" height="14" patternUnits="userSpaceOnUse"><rect width="14" height="14" fill="#D7C08E"/>${holes(weak ? 7 : 5, weak ? 3.4 : 2.3)}</pattern>
      <linearGradient id="ox-marrow" x1="0" x2="1"><stop offset="0" stop-color="#D9533F"/><stop offset=".3" stop-color="#E9A04A"/><stop offset=".7" stop-color="#EDBB5A"/><stop offset="1" stop-color="#D9533F"/></linearGradient>
      <clipPath id="ox-osteon"><circle cx="58" cy="184" r="34"/></clipPath></defs>
      ${part('femur', 'Femur (thigh bone): the longest, strongest bone in the body', `<g filter="url(#ox-shadow)"><path d="${F}" fill="url(#ox-cort)" stroke="#C9A98A" stroke-width="1.4" filter="url(#ox-grain)"/>
        <path d="M120,106 L242,106" stroke="#fff" stroke-width="2" opacity=".55"/></g>`)}
      ${part('spongy', 'Spongy bone: a light honeycomb at the ends of the bone, filled with red marrow', '<g><ellipse cx="52" cy="84" rx="17" ry="17" fill="url(#ox-spongy)"/><ellipse cx="100" cy="92" rx="10" ry="8" fill="url(#ox-spongy)"/><ellipse cx="284" cy="120" rx="20" ry="24" fill="url(#ox-spongy)"/></g>')}
      ${part('marrow', 'Bone marrow: makes red cells, white cells and platelets', `<path d="${marrow}" fill="url(#ox-marrow)"/>`)}
      ${part('cartilage', 'Joint cartilage: a smooth, slippery cap where bones meet', '<path d="M34,74 C40,60 60,56 70,66 M300,100 C313,112 313,132 300,146" stroke="#A9DCE6" stroke-width="4.5" fill="none" stroke-linecap="round"/>')}
      ${rf ? '<ellipse cx="300" cy="122" rx="20" ry="32" class="ox-synov"/>' : ''}${crystals}
      ${part('vessel', 'Nutrient artery: brings calcium, oxygen and food into the bone', '<path d="M186,200 C184,176 182,156 182,136" stroke="#C81E2C" stroke-width="4" fill="none" stroke-linecap="round"/><path d="M196,136 C198,156 204,176 210,200" stroke="#3E5BA8" stroke-width="3.4" fill="none" stroke-linecap="round"/>')}
      ${ride('M186,204 C184,176 182,156 182,122', 'ox-ca', nCa, lowD ? 5.5 : 3, 2.2)}
      ${ride('M200,124 C200,150 204,176 210,204', 'ox-marrow-out', 4, 3.6, 2)}
      <g class="ox-blasts">${blasts}</g>
      ${part('clast', 'Osteoclast: dissolves old bone so it can be rebuilt', `<g class="ox-clast"><ellipse rx="10" ry="5" fill="#9A6FB8"/><circle cx="-4" cy="-.5" r="1.5" fill="#5E3C7A"/><circle cx="0" cy=".5" r="1.5" fill="#5E3C7A"/><circle cx="4" cy="-.5" r="1.5" fill="#5E3C7A"/></g>`)}
      ${part('osteon', 'Osteon (magnified): rings of hard bone around a central blood vessel', `<g><circle cx="58" cy="184" r="34" fill="#F8EFDA" stroke="#C9A98A" stroke-width="2"/><g clip-path="url(#ox-osteon)">${lamellae}${lacunae}</g><circle cx="58" cy="184" r="4" fill="#C81E2C"/></g>`)}
      <path d="M86,164 L132,136" stroke="#C9A98A" stroke-dasharray="3 3"/>
    </svg>`, notes, parts: {
      femur: 'Bone is living tissue, rebuilt every 10 years or so. Calcium, phosphate and vitamin D keep it hard.',
      spongy: 'Spongy bone is strong but light. In osteoporosis and vitamin D deficiency the holes get bigger.',
      marrow: 'Red marrow is a blood factory; the red dots leaving the bone are new blood cells.',
      cartilage: 'Cartilage lets joints move smoothly. Gout crystals and rheumatoid arthritis both damage the joint here.',
      vessel: 'The nutrient artery feeds the bone. Each gold particle is calcium being delivered.',
      clast: 'Osteoclasts break down old bone while osteoblasts (the small blocks below) lay down new bone. ALP rises when osteoblasts are busy.',
      osteon: 'Compact bone is built from osteons: tight rings of mineral with living bone cells (osteocytes) between them.'}};
  };

  /* ================================================================ BRAIN */
  ART.brain = r => {
    const inflamed = r.abn('CWBC') || r.abn('CPRO') || r.abn('CGLU');
    const CER = 'M64,128 C46,92 72,46 130,36 C180,26 248,34 280,72 C300,96 298,128 280,144 C266,156 246,150 232,146 C214,152 196,150 182,156 C166,164 150,160 138,150 C120,156 96,156 82,148 C72,142 66,136 64,128Z';
    // gyri: short meandering folds that turn as they go, the way sulci look on a real cortex
    let gyri = '';
    for (let i = 0; i < 92; i++) {
      let x = 66 + rnd() * 222, y = 38 + rnd() * 120, a = rnd() * 6.28, d = `M${x.toFixed(1)},${y.toFixed(1)}`;
      for (let k = 0; k < 3; k++) {
        const len = 9 + rnd() * 9, a2 = a + (rnd() - .5) * 2.2, cx = x + Math.cos(a) * len * .6, cy = y + Math.sin(a) * len * .6;
        x += Math.cos(a2) * len; y += Math.sin(a2) * len; a = a2;
        d += ` Q${cx.toFixed(1)},${cy.toFixed(1)} ${x.toFixed(1)},${y.toFixed(1)}`;
      }
      gyri += `<path d="${d}" class="ox-gyrus-hi" transform="translate(1,1.6)"/><path d="${d}" class="ox-gyrus"/>`;
    }
    const IMP = ['M86,112 C104,72 146,50 190,50', 'M196,58 C228,60 258,78 274,112', 'M116,132 C150,120 190,120 226,134', 'M150,64 C160,84 166,100 160,118'];
    const impulses = IMP.map((d, i) => ride(d, 'ox-impulse', 2, 2.6 + i * .7, 2.2)).join('');
    const folia = Array.from({length: 8}, (_, k) => `<path d="M216,${148 + k * 5} C240,${144 + k * 5} 266,${148 + k * 5} 290,${154 + k * 4}" class="ox-folia"/>`).join('');
    const tint = (key, label, d, fill) => part(key, label, `<path d="${d}" fill="${fill}" class="ox-lobe" clip-path="url(#ox-br-clip)"/>`);
    const notes = [r.has('CWBC') && `CSF white cells ${r.txt('CWBC')}`, r.has('CPRO') && `CSF protein ${r.txt('CPRO')}`, r.has('CGLU') && `CSF glucose ${r.txt('CGLU')}`,
      inflamed && 'Spinal fluid abnormal: the membranes around the brain are shown inflamed (meningitis pattern)', !inflamed && 'Spinal fluid within range: signals firing normally'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 220" class="oa ox ox-brain ${inflamed ? 'inflamed' : ''}"><defs>${DEFS}
      <radialGradient id="ox-br" cx="40%" cy="30%" r="75%"><stop offset="0" stop-color="#F8D2DA"/><stop offset=".6" stop-color="#E5A3B3"/><stop offset="1" stop-color="#B66C82"/></radialGradient>
      <radialGradient id="ox-cb" cx="40%" cy="30%" r="70%"><stop offset="0" stop-color="#E9AFBD"/><stop offset="1" stop-color="#A55C72"/></radialGradient>
      <clipPath id="ox-br-clip"><path d="${CER}"/></clipPath>
      <clipPath id="ox-cb-clip"><path d="M228,146 C250,140 282,148 284,166 C284,184 252,190 232,182 C218,176 216,154 228,146Z"/></clipPath></defs>
      ${part('stem', 'Brainstem: controls breathing, heart rate and consciousness', '<path d="M196,150 C200,170 204,190 208,214 L224,214 C220,190 218,168 216,150Z" fill="#D2909F" filter="url(#ox-grain)"/>')}
      ${part('cerebellum', 'Cerebellum: balance and coordination', `<g><path d="M228,146 C250,140 282,148 284,166 C284,184 252,190 232,182 C218,176 216,154 228,146Z" fill="url(#ox-cb)" filter="url(#ox-grain)"/><g clip-path="url(#ox-cb-clip)">${folia}</g></g>`)}
      <g class="ox-swell"><path d="${CER}" fill="url(#ox-br)" filter="url(#ox-grain)"/>
        ${tint('frontal', 'Frontal lobe: planning, personality, movement', 'M30,10 L176,10 C170,60 182,80 172,108 L200,112 C170,104 140,106 110,118 L30,152Z', '#F4AFBE')}
        ${tint('parietal', 'Parietal lobe: touch, position and reading', 'M176,10 L276,10 L250,100 L200,112 L172,108 C182,80 170,60 176,10Z', '#E4ABD6')}
        ${tint('occipital', 'Occipital lobe: vision', 'M276,10 L330,10 L330,170 L234,170 L250,100Z', '#D5A2C8')}
        ${tint('temporal', 'Temporal lobe: hearing, memory and language', 'M30,152 L110,118 C140,106 170,104 200,112 L250,100 L234,170 L30,178Z', '#F1B39E')}
        <g clip-path="url(#ox-br-clip)" pointer-events="none">${gyri}<path d="M176,30 C170,60 182,80 172,108" class="ox-sulcus"/><path d="M108,120 C140,106 170,104 202,112" class="ox-sulcus"/>${impulses}</g>
        <ellipse cx="120" cy="58" rx="34" ry="10" fill="#fff" opacity=".16" transform="rotate(-14 120 58)" pointer-events="none"/></g>
      ${part('meninges', 'Meninges: three membranes around the brain, bathed in spinal fluid (CSF)', `<path d="${CER}" class="ox-mening" transform="translate(172,100) scale(1.045) translate(-172,-100)"/>`)}
      <g transform="translate(172,100) scale(1.045) translate(-172,-100)">${ride(CER, 'ox-csf', 8, inflamed ? 26 : 16, 1.8)}</g>
    </svg>`, notes, parts: {
      frontal: 'The frontal lobe plans, decides and starts movement.', parietal: 'The parietal lobe handles touch, body position and reading.',
      occipital: 'The occipital lobe at the back processes vision.', temporal: 'The temporal lobe holds hearing, memory and much of language.',
      cerebellum: 'The cerebellum fine-tunes balance and coordination.', stem: 'The brainstem runs breathing and heart rate automatically.',
      meninges: 'Spinal fluid (blue dots) circulates inside the meninges. Raised white cells or protein in a lumbar puncture suggest meningitis; low CSF glucose suggests bacteria.'}};
  };

  /* ================================================================ THYROID */
  ART.thyroid = r => {
    const tsh = r.num('TSH'), hi = high(r, 'TSH'), lo = low(r, 'TSH'), ft4 = r.num('FT4');
    const nT4 = lo ? 9 : hi ? 2 : 5, dT4 = lo ? 1.8 : hi ? 5 : 3, nTSH = hi ? 8 : lo ? 1 : 3;
    const rings = Array.from({length: 13}, (_, i) => `<rect x="148" y="${80 + i * 11}" width="44" height="5" rx="2.5" fill="#E9DDCB"/>`).join('');
    const foll = Array.from({length: 7}, (_, i) => { const a = i / 7 * 6.28; const cx = 288 + Math.cos(a) * 18, cy = 168 + Math.sin(a) * 18;
      return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="9" fill="#F4DDB6" stroke="#C97A62" stroke-width="2.6"/>`; }).join('');
    const notes = [tsh != null && `TSH ${tsh} mIU/L`, ft4 != null && `Free T4 ${ft4} pmol/L`,
      hi && 'High TSH: under-active thyroid. The pituitary sends more TSH signals, but little hormone comes out; the gland may swell (goitre)',
      lo && 'Low TSH: over-active thyroid. Lots of hormone released, so the pituitary sends almost no TSH', !hi && !lo && 'Thyroid within range: balanced hormone release'].filter(Boolean);
    const VL = 'M128,166 C118,186 110,204 98,222', VR = 'M212,166 C222,186 230,204 242,222';
    return {svg: `<svg viewBox="0 0 340 222" class="oa ox ox-thy ${hi ? 'goitre' : ''} ${lo ? 'fast' : ''}"><defs>${DEFS}
      <radialGradient id="ox-th" cx="40%" cy="35%" r="70%"><stop offset="0" stop-color="#D9787A"/><stop offset=".6" stop-color="#B04A4F"/><stop offset="1" stop-color="#7C2A32"/></radialGradient>
      <pattern id="ox-foll" width="13" height="13" patternUnits="userSpaceOnUse">${Array.from({length: 4}, () => `<circle cx="${(rnd() * 13).toFixed(1)}" cy="${(rnd() * 13).toFixed(1)}" r="${(1.2 + rnd() * 1.4).toFixed(1)}" fill="#F0B08A" opacity=".32"/>`).join('')}</pattern></defs>
      ${part('larynx', 'Larynx (voice box): the thyroid cartilage forms the Adam\'s apple', '<path d="M140,14 L200,14 L196,38 C190,52 178,58 170,60 C162,58 150,52 144,38Z" fill="#EADFCD" stroke="#C9B89E" stroke-width="1.4" filter="url(#ox-grain)"/><path d="M146,64 L194,64 L192,76 L148,76Z" fill="#E3D6C0" stroke="#C9B89E"/>')}
      ${part('trachea', 'Trachea: the windpipe the thyroid wraps around', `<g><rect x="150" y="76" width="40" height="146" fill="#D9CBB4"/>${rings}</g>`)}
      <path d="M96,40 C118,58 132,74 146,92 M244,40 C222,58 208,74 194,92" stroke="#C81E2C" stroke-width="3.4" fill="none" stroke-linecap="round"/>
      <path d="${VL}" stroke="#3E5BA8" stroke-width="5" fill="none" stroke-linecap="round" opacity=".75"/><path d="${VR}" stroke="#3E5BA8" stroke-width="5" fill="none" stroke-linecap="round" opacity=".75"/>
      <g class="ox-gland">${part('lobes', 'Thyroid lobes: make T4 and T3, the hormones that set the body\'s pace', '<g filter="url(#ox-shadow)"><path d="M150,86 C128,80 112,104 114,138 C116,166 130,178 146,172 C156,168 160,150 158,130 C158,112 156,96 150,86Z M190,86 C212,80 228,104 226,138 C224,166 210,178 194,172 C184,168 180,150 182,130 C182,112 184,96 190,86Z" fill="url(#ox-th)" filter="url(#ox-grain)"/><path d="M150,86 C128,80 112,104 114,138 C116,166 130,178 146,172 C156,168 160,150 158,130 C158,112 156,96 150,86Z M190,86 C212,80 228,104 226,138 C224,166 210,178 194,172 C184,168 180,150 182,130 C182,112 184,96 190,86Z" fill="url(#ox-foll)"/><ellipse cx="128" cy="110" rx="5" ry="14" fill="#fff" opacity=".18"/></g>')}
      ${part('isthmus', 'Isthmus: the bridge joining the two lobes in front of the windpipe', '<path d="M154,124 C162,120 178,120 186,124 L186,142 C178,138 162,138 154,142Z" fill="url(#ox-th)"/>')}</g>
      ${ride(VL, 'ox-t4', nT4, dT4, 2.4)}${ride(VR, 'ox-t4', nT4, dT4 + .3, 2.4)}
      <path d="M14,8 C52,16 84,28 112,56" stroke="#8A4A8F" stroke-width="1.4" stroke-dasharray="3 4" fill="none" opacity=".6"/>${ride('M14,8 C52,16 84,28 120,64', 'ox-tsh', nTSH, 3, 2.2)}
      <text x="14" y="26" class="oa-lbl">TSH from the pituitary</text><text x="60" y="214" class="oa-lbl">T4 into the blood</text>
      ${part('follicle', 'Follicles (magnified): hollow balls of cells storing hormone in colloid', `<g><circle cx="288" cy="168" r="36" fill="#FFF7EE" stroke="#B04A4F" stroke-width="2"/>${foll}<circle cx="288" cy="168" r="7" fill="#F4DDB6" stroke="#C97A62" stroke-width="2.6"/></g>`)}
      <path d="M254,160 L226,146" stroke="#B04A4F" stroke-dasharray="3 3"/>
    </svg>`, notes, parts: {
      lobes: 'The lobes store and release thyroid hormone. Purple dots arriving are TSH from the pituitary; gold dots leaving are T4.',
      isthmus: 'A thin bridge of thyroid tissue in front of the windpipe.', larynx: 'The thyroid sits just below the Adam\'s apple.',
      trachea: 'A large goitre can press on the windpipe.', follicle: 'Each follicle is a ring of cells around a store of colloid, where hormone is made.'}};
  };

  /* ================================================================ PANCREAS */
  ART.pancreas = r => {
    const glu = r.num('FBG'), a1c = r.num('A1C'), sugarHigh = r.abn('FBG') || r.abn('A1C'), inflamed = r.abn('LIPA') || r.abn('AMY');
    const nSugar = glu != null ? scale(glu, 3, 25, 3, 22) : (a1c != null ? scale(a1c, 4, 13, 3, 20) : 6);
    const PAN = 'M76,96 C74,72 104,66 118,82 C150,80 200,70 250,58 C276,52 300,52 304,66 C308,80 290,86 270,90 C220,100 170,112 132,126 C120,140 112,154 96,152 C80,150 72,130 76,96Z';
    const DUCT = 'M298,68 C250,78 200,90 150,104 C126,112 104,118 66,120';
    const VEIN = 'M300,96 C250,108 190,124 140,140 C120,148 104,158 96,174';
    let sugar = '';
    for (let i = 0; i < nSugar; i++) sugar += `<g class="oa-flow" style="--y:${(178 + rnd() * 22).toFixed(0)}px;--d:${(5 + rnd() * 4).toFixed(1)}s;animation-delay:${(-rnd() * 8).toFixed(1)}s"><rect x="-4" y="-4" width="8" height="8" rx="2" class="sugar"/></g>`;
    const lob = Array.from({length: 6}, () => `<circle cx="${(rnd() * 22).toFixed(1)}" cy="${(rnd() * 22).toFixed(1)}" r="${(2 + rnd() * 2.6).toFixed(1)}" fill="#FFF2D2" stroke="#C99A55" stroke-width=".5" opacity=".38"/>`).join('');
    const islets = [[116, 104], [170, 98], [226, 82], [272, 70], [96, 128]].map(([x, y], i) => `<circle cx="${x}" cy="${y}" r="5" class="ox-islet" style="animation-delay:-${(i * .45).toFixed(1)}s"/>`).join('');
    const notes = [glu != null && `Glucose ${glu} mmol/L → ${nSugar} sugar particles in the bloodstream`, a1c != null && `HbA1c ${a1c}%`, sugarHigh && 'Blood sugar above range: islets shown straining to release insulin',
      inflamed && `Pancreatic enzymes raised (${[r.has('LIPA') && 'lipase ' + r.txt('LIPA'), r.has('AMY') && 'amylase ' + r.txt('AMY')].filter(Boolean).join(', ')}): inflamed pancreas leaking enzymes`,
      !sugarHigh && !inflamed && 'Pancreas tests within range'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 210" class="oa ox ox-panc ${inflamed ? 'inflamed' : ''} ${sugarHigh ? 'sugar' : ''}"><defs>${DEFS}
      <linearGradient id="ox-pa" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="#F6DA9C"/><stop offset=".6" stop-color="#E3B165"/><stop offset="1" stop-color="#B9823A"/></linearGradient>
      <pattern id="ox-lob" width="22" height="22" patternUnits="userSpaceOnUse">${lob}</pattern></defs>
      ${part('duodenum', 'Duodenum: the pancreas head sits in its C-shaped curve', '<path d="M98,36 C60,40 46,90 52,130 C58,170 96,182 122,170" stroke="#D99079" stroke-width="20" fill="none" stroke-linecap="round" filter="url(#ox-grain)"/><path d="M98,36 C60,40 46,90 52,130 C58,170 96,182 122,170" stroke="#F1B39C" stroke-width="10" fill="none" stroke-linecap="round" opacity=".8"/>')}
      ${part('spleen', 'Spleen: sits at the tail of the pancreas', '<path d="M300,34 C328,30 338,60 328,82 C318,98 298,92 296,78 C292,62 290,44 300,34Z" fill="#8E4A6A" filter="url(#ox-grain)"/>')}
      <path d="${VEIN}" stroke="#3E5BA8" stroke-width="7" fill="none" stroke-linecap="round" opacity=".75"/>
      <g class="ox-pan-box">${part('pancreas', 'Pancreas: makes digestive enzymes and the hormones insulin and glucagon', `<g filter="url(#ox-shadow)"><path d="${PAN}" fill="url(#ox-pa)" filter="url(#ox-grain)"/><path d="${PAN}" fill="url(#ox-lob)"/><path d="M110,80 C160,74 220,64 290,56" stroke="#fff" stroke-width="3" opacity=".3" fill="none"/></g>`)}
        ${part('duct', 'Pancreatic duct: carries enzymes into the duodenum', `<path d="${DUCT}" stroke="#FBF0CF" stroke-width="3" fill="none"/>`)}
        ${part('islets', 'Islets of Langerhans: clusters of cells that release insulin into the blood', `<g>${islets}</g>`)}</g>
      ${ride(DUCT, 'ox-enz', 6, 4, 2)}${ride(VEIN, 'ox-ins', sugarHigh ? 8 : 5, sugarHigh ? 2 : 3.2, 2)}
      ${inflamed ? ride('M200,92 C210,70 230,60 250,40', 'ox-leak', 4, 2.6, 2) + ride('M150,118 C150,140 160,150 176,160', 'ox-leak', 3, 2.8, 2) : ''}
      <rect x="0" y="166" width="340" height="42" rx="20" class="vessel-wall"/>${part('blood', 'Bloodstream: glucose particles shown here', `<g>${sugar}</g>`)}
    </svg>`, notes, parts: {
      pancreas: 'The pancreas lies behind the stomach, its head in the curve of the duodenum and its tail touching the spleen.',
      duct: 'Green dots are digestive enzymes flowing into the duodenum. In pancreatitis they leak and damage the gland itself, raising lipase and amylase.',
      islets: 'Islets release insulin (white dots in the vein), which moves sugar from the blood into cells. In diabetes, sugar builds up despite the effort.',
      duodenum: 'Enzymes enter the duodenum through a small opening shared with the bile duct.', spleen: 'The spleen filters blood; it is not part of the pancreas but sits beside its tail.',
      blood: 'Each square is sugar in the bloodstream. More squares means higher glucose.'}};
  };

  /* ================================================================ IMMUNE (lymph node) */
  ART.immune = r => {
    const active = r.abn('WBC') || r.abn('CRP') || r.abn('ESR'), hiv = r.abn('HIV');
    const NODE = 'M110,40 C170,20 250,34 262,90 C270,130 250,176 196,182 C176,184 168,166 168,150 C168,132 150,124 132,128 C100,134 74,114 76,86 C78,62 92,46 110,40Z';
    const FOL = [[112, 62], [152, 46], [198, 46], [236, 70], [248, 112], [228, 152], [98, 102]];
    const follicles = FOL.map(([x, y], i) => `<circle cx="${x}" cy="${y}" r="13" fill="#E6EEF8" stroke="#A9BCD6" stroke-width="1"/><circle cx="${x}" cy="${y}" r="6" class="ox-gc" style="animation-delay:-${(i * .4).toFixed(1)}s"/>` +
      Array.from({length: hiv ? 2 : 5}, () => `<circle cx="${(x - 8 + rnd() * 16).toFixed(1)}" cy="${(y - 8 + rnd() * 16).toFixed(1)}" r="1.8" class="ox-lymph"/>`).join('')).join('');
    const AFF = ['M14,36 C50,36 76,44 102,50', 'M314,24 C294,40 276,54 254,68', 'M326,150 C302,150 282,148 256,140'];
    const EFF = 'M168,150 C152,170 142,190 124,214';
    const germ = '<g class="ox-germ"><circle r="4.4"/><path d="M-6.5,0 h-2.5 M6.5,0 h2.5 M0,-6.5 v-2.5 M0,6.5 v2.5"/></g>';
    const antibody = '<path d="M0,4 L0,-1 M0,-1 L-3.4,-4.4 M0,-1 L3.4,-4.4" class="ox-ab"/>';
    const notes = [r.has('WBC') && `White cells ${r.txt('WBC')}`, r.has('CRP') && `CRP ${r.txt('CRP')}`, r.has('ESR') && `ESR ${r.txt('ESR')}`,
      active && 'Infection or inflammation markers raised: lymph node shown fighting, follicles swollen and antibodies flowing out',
      hiv && 'HIV test reactive: fewer helper (CD4) cells shown in the follicles', !active && !hiv && 'Infection markers within range: lymph node at rest'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 214" class="oa ox ox-node ${active ? 'active' : ''} ${hiv ? 'depleted' : ''}"><defs>${DEFS}
      <radialGradient id="ox-ln" cx="40%" cy="35%" r="70%"><stop offset="0" stop-color="#D6E1EE"/><stop offset=".7" stop-color="#9DB2CC"/><stop offset="1" stop-color="#6F86A3"/></radialGradient>
      <clipPath id="ox-ln-clip"><path d="${NODE}"/></clipPath></defs>
      ${part('afferent', 'Lymph vessels: bring fluid and germs from the tissues to the node', `<g>${AFF.map(d => `<path d="${d}" stroke="#B5DCCB" stroke-width="6" fill="none" stroke-linecap="round"/>`).join('')}</g>`)}
      ${AFF.map((d, i) => rideShape(d, germ, active ? 3 : 1, 4 + i)).join('')}
      <g class="ox-node-box">${part('node', 'Lymph node: a filter packed with immune cells', `<g filter="url(#ox-shadow)"><path d="${NODE}" fill="url(#ox-ln)" stroke="#6F86A3" stroke-width="2" filter="url(#ox-grain)"/>
        <g clip-path="url(#ox-ln-clip)"><path d="M130,120 C150,100 180,96 200,110 M150,140 C170,120 200,118 222,130 M120,96 C150,80 190,80 220,92" stroke="#7F97B6" stroke-width="5" fill="none" opacity=".45" stroke-linecap="round"/></g></g>`)}
        ${part('follicles', 'Follicles: where B cells multiply and learn to make antibodies', `<g>${follicles}</g>`)}</g>
      ${part('efferent', 'Outgoing lymph vessel: carries antibodies and activated cells back to the blood', `<path d="${EFF}" stroke="#B5DCCB" stroke-width="7" fill="none" stroke-linecap="round"/>`)}
      ${active ? rideShape(EFF, antibody, 6, 3.4) : ride(EFF, 'ox-lymph-out', 2, 4, 2)}
      ${part('macrophage', 'Macrophage: swallows germs and shows them to other immune cells', `<g class="ox-mac"><path d="M0,-10 C8,-12 14,-4 12,4 C10,12 0,14 -6,10 C-14,6 -12,-8 0,-10Z" fill="#E9D7B9" stroke="#B99A6A" stroke-width="1.2"/><circle cx="2" cy="0" r="3" fill="#8A6A44"/>${active ? '<circle cx="-5" cy="3" r="2.2" fill="#7CB342"/>' : ''}</g>`)}
    </svg>`, notes, parts: {
      node: 'Lymph nodes sit along lymph vessels in the neck, armpits and groin. They swell when fighting an infection.',
      follicles: 'Germinal centres (the pulsing middles) are where B cells multiply. HIV destroys helper T cells, so the follicles look thinner.',
      afferent: 'Germs arrive through these vessels and get trapped in the node.', efferent: 'Antibodies (the Y shapes) leave the node and enter the blood.',
      macrophage: 'Macrophages eat germs and trigger the immune response. CRP and ESR rise when this response is active.'}};
  };
})();
