/* Near-realistic organ illustrations: shaded anatomy, texture, depth and flow.
   Replaces the simple versions in organs.js for the heart, blood, lungs, kidneys and liver.
   Teaching illustrations only; the patient's results decide what is shown. */
(() => {
  'use strict';
  const ART = window.__MF_ART, H = (window.MedFlowOrgans || {}).helpers;
  if (!ART || !H) return;
  const {part, rnd, scale} = H;
  const GRAIN = `<filter id="oa-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="3" result="n"/>
    <feColorMatrix in="n" type="saturate" values="0" result="g"/><feComposite in="g" in2="SourceGraphic" operator="in" result="gi"/><feBlend in="SourceGraphic" in2="gi" mode="multiply"/></filter>
    <filter id="oa-soft"><feGaussianBlur stdDeviation="1.6"/></filter><filter id="oa-glow"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>`;

  /* ------------------------------------------------------------ HEART */
  ART.heart = r => {
    const injury = r.abn('TNI') || r.abn('CKMB'), strain = r.abn('BNP'), arr = r.crit('K') || r.abn('K');
    const flow = (path, cls, n, dur) => Array.from({length: n}, (_, i) => `<circle r="2.6" class="${cls}"><animateMotion dur="${dur}s" repeatCount="indefinite" begin="-${(i * dur / n).toFixed(2)}s" path="${path}"/></circle>`).join('');
    const notes = [injury && `Troponin ${r.txt('TNI') || r.txt('CKMB')}: injured muscle shown on the front wall of the left ventricle`,
      strain && `BNP ${r.txt('BNP')}: chambers enlarged by strain`, arr && `Potassium ${r.txt('K')}: irregular rhythm`, !injury && !strain && !arr && 'Heart markers within range: regular rhythm'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 230" class="oa oa-heart real ${injury ? 'injury' : ''} ${strain ? 'strain' : ''} ${arr ? 'arrhythmia' : ''}">
      <defs>${GRAIN}
        <radialGradient id="hm" cx="42%" cy="38%" r="70%"><stop offset="0" stop-color="#D2474F"/><stop offset=".55" stop-color="#A8202C"/><stop offset="1" stop-color="#5E0C14"/></radialGradient>
        <linearGradient id="ha" x1="0" x2="1"><stop offset="0" stop-color="#E05A5F"/><stop offset=".5" stop-color="#C2343E"/><stop offset="1" stop-color="#8E1A24"/></linearGradient>
        <linearGradient id="hv" x1="0" x2="1"><stop offset="0" stop-color="#7C8FD0"/><stop offset="1" stop-color="#3E4F98"/></linearGradient>
        <radialGradient id="hi" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#3B0A2E" stop-opacity=".95"/><stop offset=".7" stop-color="#5A1438" stop-opacity=".7"/><stop offset="1" stop-color="#5A1438" stop-opacity="0"/></radialGradient>
      </defs>
      ${part('svc', 'Superior vena cava: returns blood from the upper body', '<path d="M118,20 C116,40 116,60 122,78" stroke="url(#hv)" stroke-width="18" fill="none" stroke-linecap="round"/>')}
      ${part('pa', 'Pulmonary trunk: carries blood to the lungs', '<path d="M150,82 C140,50 112,40 82,50" stroke="url(#hv)" stroke-width="20" fill="none" stroke-linecap="round"/>')}
      ${part('aorta', 'Aorta: carries oxygen-rich blood to the body', '<path d="M170,86 C164,36 196,10 236,20 C262,26 270,46 262,66" stroke="url(#ha)" stroke-width="22" fill="none" stroke-linecap="round"/><path d="M208,16 L208,2 M226,18 L230,4 M244,24 L252,10" stroke="#B02A35" stroke-width="7" stroke-linecap="round"/>')}
      <g class="beat-box">
        ${part('heart', 'Heart muscle (myocardium): pumps about 70 times a minute', '<path d="M112,86 C92,92 82,122 92,150 C104,184 140,212 176,222 C214,206 252,172 258,132 C264,98 244,74 214,78 C196,80 184,90 176,98 C162,84 136,78 112,86Z" fill="url(#hm)" filter="url(#oa-grain)"/>')}
        <path d="M176,98 C172,140 170,180 176,222" class="groove"/>
        ${part('lca', 'Left coronary artery: supplies the front of the heart (the artery blocked in many heart attacks)', '<path d="M180,100 C188,130 196,160 206,196 M188,128 C206,132 226,140 240,156 M196,160 C214,166 228,174 236,186" class="coronary"/>')}
        ${part('rca', 'Right coronary artery: supplies the right side and back', '<path d="M166,100 C140,110 118,128 108,156 C104,170 110,184 122,196" class="coronary"/>')}
        <ellipse cx="214" cy="160" rx="28" ry="22" fill="url(#hi)" class="injury-zone" filter="url(#oa-grain)"/>
        <ellipse cx="128" cy="112" rx="26" ry="12" fill="#fff" opacity=".18" transform="rotate(-25 128 112)"/>
      </g>
      ${flow('M118,20 C116,40 116,60 122,78', 'p-blue', 4, 1.6)}${flow('M170,86 C164,36 196,10 236,20 C262,26 270,46 262,66', 'p-red', 6, 1.4)}${flow('M150,82 C140,50 112,40 82,50', 'p-blue', 4, 1.5)}
      <polyline class="ecg-line" points="0,226 40,226 50,226 56,216 62,229 68,192 74,231 80,226 120,226 130,221 140,226 340,226"/>
    </svg>`, notes, parts: {heart: 'The heart muscle pumps blood through two circuits: lungs and body.', lca: 'The left coronary artery feeds the front wall of the heart. Raised troponin often means part of this territory has lost blood supply.',
      rca: 'The right coronary artery feeds the right side and back of the heart.', aorta: 'The aorta carries oxygen-rich blood from the left ventricle to the body.',
      pa: 'The pulmonary trunk takes used blood from the right ventricle to the lungs.', svc: 'The vena cava returns used blood to the right atrium.'}};
  };

  /* ------------------------------------------------------------ BLOOD */
  ART.blood = r => {
    const hb = r.num('HB'), wbc = r.num('WBC'), plt = r.num('PLT');
    const nR = scale(hb, 4, 18, 6, 26) ?? 16, nW = scale(wbc, 1, 30, 1, 8) ?? 2, nP = scale(plt, 20, 700, 4, 22) ?? 10;
    const malaria = r.abn('RDT') || (r.num('DENS') || 0) > 0;
    const rbc = (depth, i) => `<g class="tumble" style="animation-duration:${(3 + rnd() * 4).toFixed(1)}s;animation-delay:-${(rnd() * 4).toFixed(1)}s">
      <ellipse rx="15" ry="${(7 + rnd() * 6).toFixed(1)}" fill="url(#rbc)"/><ellipse rx="7" ry="${(3 + rnd() * 2).toFixed(1)}" fill="#8E0F1C" opacity=".45"/>
      ${malaria && i % 4 === 0 ? '<circle r="3" cx="5" cy="-1" fill="#3A1255"/><circle r="1.3" cx="-4" cy="2" fill="#3A1255"/>' : ''}</g>`;
    let back = '', front = '';
    const layer = (n, make, depthFront) => { let out = ''; for (let i = 0; i < n; i++) {
      const far = !depthFront && rnd() < .5, y = 34 + rnd() * 116, d = far ? 9 + rnd() * 5 : 5 + rnd() * 3, sc = far ? .55 + rnd() * .2 : .9 + rnd() * .25;
      out += `<g class="oa-flow ${far ? 'far' : ''}" style="--y:${y.toFixed(0)}px;--d:${d.toFixed(1)}s;animation-delay:-${(rnd() * 10).toFixed(1)}s"><g transform="scale(${sc.toFixed(2)})">${make(i)}</g></g>`; }
      return out; };
    back += layer(Math.round(nR * .5), i => rbc(true, i));
    front += layer(Math.round(nR * .5), i => part('rbc', 'Red blood cell: a concave disc full of haemoglobin, carrying oxygen', rbc(false, i)), true);
    front += layer(nW, () => part('wbc', 'White blood cell (neutrophil): fights infection', `<circle r="17" fill="url(#wbc)"/>${Array.from({length: 14}, () => `<circle r="1" cx="${(rnd() * 22 - 11).toFixed(1)}" cy="${(rnd() * 22 - 11).toFixed(1)}" fill="#B6A6DA"/>`).join('')}<path d="M-8,-4 C-6,-10 2,-10 1,-3 C0,2 7,0 8,5 C9,10 0,11 -2,6 C-4,2 -10,2 -8,-4Z" fill="#6E58B5"/>`), true);
    front += layer(nP, () => part('plt', 'Platelet: a cell fragment that plugs leaks and starts clotting', `<path d="M-5,-2 C-3,-5 3,-4 5,-1 C6,2 2,4 -2,3 C-5,2 -6,0 -5,-2Z" fill="#E6A93A"/>`), true);
    const notes = [hb != null && `Haemoglobin ${hb} → ${nR} red cells`, wbc != null && `White cells ${wbc} → ${nW}`, plt != null && `Platelets ${plt} → ${nP}`, malaria && 'Malaria parasites inside red cells'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 190" class="oa oa-blood real"><defs>${GRAIN}
      <radialGradient id="rbc" cx="45%" cy="40%" r="60%"><stop offset="0" stop-color="#F06B72"/><stop offset=".55" stop-color="#C81E2C"/><stop offset="1" stop-color="#7E0C16"/></radialGradient>
      <radialGradient id="wbc" cx="40%" cy="35%" r="65%"><stop offset="0" stop-color="#FBFAFF"/><stop offset="1" stop-color="#D9D1EF"/></radialGradient>
      <linearGradient id="lumen" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#8E1D27"/><stop offset=".12" stop-color="#F3C0C2"/><stop offset=".5" stop-color="#FBE0E0"/><stop offset=".88" stop-color="#F3C0C2"/><stop offset="1" stop-color="#8E1D27"/></linearGradient></defs>
      <rect x="0" y="16" width="340" height="158" rx="70" fill="url(#lumen)" filter="url(#oa-grain)"/>
      <g filter="url(#oa-soft)" opacity=".7">${back}</g>${front}</svg>`, notes,
      parts: {rbc: 'Red cells are flexible concave discs, so they can squeeze through tiny capillaries. Fewer cells on screen means lower haemoglobin.', wbc: 'Neutrophils have a lobed nucleus and granules full of enzymes that destroy bacteria.', plt: 'Platelets clump at a leak to start a clot. Very low counts mean a bleeding risk.'}};
  };

  /* ------------------------------------------------------------ LUNGS */
  ART.lungs = r => {
    const sat = r.num('SAO2'), lowO2 = r.abn('SAO2') || r.abn('PO2'), tb = r.abn('AFB') || r.abn('MTB');
    const tree = (x, y, ang, len, depth) => { if (depth === 0) return '';
      const x2 = x + Math.cos(ang) * len, y2 = y + Math.sin(ang) * len;
      return `<path d="M${x.toFixed(1)},${y.toFixed(1)} L${x2.toFixed(1)},${y2.toFixed(1)}" stroke-width="${depth * 1.4}"/>` + tree(x2, y2, ang - .45, len * .72, depth - 1) + tree(x2, y2, ang + .4, len * .72, depth - 1); };
    const nO2 = sat != null ? scale(sat, 75, 100, 2, 12) : 9;
    const o2 = Array.from({length: nO2}, (_, i) => `<circle r="2.4" class="o2r"><animateMotion dur="2.4s" repeatCount="indefinite" begin="-${(i * 2.4 / nO2).toFixed(2)}s" path="M262,${150 + (i % 3) * 6} C272,${160 + (i % 3) * 4} 286,${170 + (i % 3) * 3} 300,178"/></circle>`).join('');
    const notes = [sat != null && `Oxygen saturation ${sat}%`, lowO2 && 'Low oxygen: fewer oxygen particles crossing into the blood', tb && 'TB test positive: cavity marked in the upper lobe', !lowO2 && !tb && 'Lung tests within range'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 210" class="oa oa-lungs real ${lowO2 ? 'lowo2' : ''}"><defs>${GRAIN}
      <radialGradient id="lg" cx="45%" cy="35%" r="70%"><stop offset="0" stop-color="#F8C9C6"/><stop offset=".6" stop-color="#E79A9A"/><stop offset="1" stop-color="#B9606A"/></radialGradient></defs>
      <g class="breath">
        ${part('lung-r', 'Right lung: three lobes', '<path d="M148,34 C108,30 54,74 50,136 C46,182 84,198 124,188 C142,184 146,160 146,128Z" fill="url(#lg)" filter="url(#oa-grain)"/><path d="M60,110 C90,104 120,112 146,104 M58,150 C88,142 118,148 146,140" class="fissure"/>')}
        ${part('lung-l', 'Left lung: two lobes and a notch for the heart', '<path d="M172,34 C212,30 266,74 270,136 C274,182 236,198 196,188 C182,184 184,168 194,156 C182,146 174,132 174,116Z" fill="url(#lg)" filter="url(#oa-grain)"/><path d="M178,92 C210,100 240,110 264,128" class="fissure"/>')}
        <g class="bronchi">${tree(150, 70, Math.PI * .72, 26, 5)}${tree(170, 70, Math.PI * .28, 26, 5)}</g>
        ${tb ? '<circle cx="96" cy="70" r="11" class="tb-spot"/>' : ''}
      </g>
      ${part('trachea', 'Trachea: the windpipe, held open by rings of cartilage', '<rect x="153" y="0" width="14" height="70" rx="6" fill="#E5C6C0"/>' + Array.from({length: 8}, (_, i) => `<rect x="152" y="${4 + i * 8}" width="16" height="3" rx="1.5" fill="#CDA59F"/>`).join(''))}
      ${part('alveoli', 'Alveoli (magnified): oxygen crosses a wall one cell thick into the capillary', `<g class="zoom-inset"><circle cx="282" cy="160" r="40" fill="#FFF5F4" stroke="#C98383" stroke-width="2"/><circle cx="270" cy="150" r="13" class="alv-s"/><circle cx="292" cy="146" r="11" class="alv-s"/><circle cx="282" cy="168" r="12" class="alv-s"/><path d="M246,182 C266,170 290,176 318,166" stroke="#C81E2C" stroke-width="6" fill="none" stroke-linecap="round" opacity=".7"/>${o2}</g>`)}
      <path d="M248,140 L230,150" stroke="#C98383" stroke-dasharray="3 3"/>
    </svg>`, notes, parts: {'lung-r': 'The right lung has three lobes separated by fissures.', 'lung-l': 'The left lung has two lobes and a notch where the heart sits.',
      trachea: 'The trachea divides into two main bronchi, then branches about 23 times down to the air sacs.', alveoli: 'Each air sac is wrapped in capillaries. Low oxygen saturation means less oxygen is crossing here.'}};
  };

  /* ------------------------------------------------------------ KIDNEYS */
  ART.kidneys = r => {
    const slow = r.abn('CREA') || r.abn('UREA'), k = r.abn('K'), prot = r.abn('PRO');
    const pyramids = Array.from({length: 7}, (_, i) => { const a = -1.15 + i * .38, cx = 112, cy = 104;
      const x1 = cx + Math.cos(a) * 58, y1 = cy + Math.sin(a) * 66, x2 = cx + Math.cos(a + .26) * 58, y2 = cy + Math.sin(a + .26) * 66, xt = cx + Math.cos(a + .13) * 22, yt = cy + Math.sin(a + .13) * 26;
      return `<path d="M${x1.toFixed(0)},${y1.toFixed(0)} L${x2.toFixed(0)},${y2.toFixed(0)} L${xt.toFixed(0)},${yt.toFixed(0)}Z" fill="url(#kp)"/>`; }).join('');
    const drops = Array.from({length: 7}, (_, i) => `<circle r="3" class="k-drop2"><animateMotion dur="${slow ? 5.5 : 2.4}s" repeatCount="indefinite" begin="-${(i * (slow ? 5.5 : 2.4) / 7).toFixed(2)}s" path="M118,112 C140,130 160,150 166,196"/></circle>`).join('');
    const notes = [slow && `Creatinine ${r.txt('CREA') || '—'} / urea ${r.txt('UREA') || '—'}: filtering slowed`, k && `Potassium ${r.txt('K')} out of range`, prot && 'Protein leaking into the urine', !slow && !k && 'Kidney tests within range'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 210" class="oa oa-kidney real ${slow ? 'slow' : ''}"><defs>${GRAIN}
      <radialGradient id="kc" cx="40%" cy="35%" r="75%"><stop offset="0" stop-color="#C9585F"/><stop offset=".7" stop-color="#9C2F3A"/><stop offset="1" stop-color="#6A1A23"/></radialGradient>
      <linearGradient id="kp" x1="0" x2="1"><stop offset="0" stop-color="#7A1E29"/><stop offset=".5" stop-color="#A3434C"/><stop offset="1" stop-color="#7A1E29"/></linearGradient></defs>
      ${part('cortex', 'Cortex: outer layer holding about a million filters (nephrons) per kidney', '<path d="M112,24 C52,24 34,92 46,140 C58,190 118,206 150,170 C162,156 150,136 150,112 C150,86 166,66 154,46 C146,32 130,24 112,24Z" fill="url(#kc)" filter="url(#oa-grain)"/>')}
      ${part('medulla', 'Medulla: cone-shaped pyramids that concentrate the urine', `<g>${pyramids}</g>`)}
      ${part('pelvis', 'Renal pelvis: collects urine from the calyces', '<path d="M126,82 C110,92 108,120 124,132 C134,138 144,128 146,112 C147,96 138,80 126,82Z" fill="#F0D38A"/>')}
      <path d="M160,90 C190,84 220,84 250,86" stroke="#C81E2C" stroke-width="9" fill="none" stroke-linecap="round"/>
      <path d="M160,106 C190,104 220,104 250,104" stroke="#3E5BA8" stroke-width="9" fill="none" stroke-linecap="round"/>
      <path d="M140,124 C156,146 164,170 166,206" class="ureter2"/>${drops}
      <text x="256" y="90" class="oa-lbl">renal artery</text><text x="256" y="108" class="oa-lbl">renal vein</text><text x="174" y="200" class="oa-lbl">ureter</text>
    </svg>`, notes, parts: {cortex: 'The cortex holds the glomeruli, tiny filters that clean the blood. Raised creatinine means they are filtering more slowly.',
      medulla: 'The pyramids of the medulla concentrate urine and balance salt and water.', pelvis: 'The renal pelvis funnels urine into the ureter and down to the bladder.'}};
  };

  /* ------------------------------------------------------------ LIVER */
  ART.liver = r => {
    const alt = r.num('ALT'), ast = r.num('AST'), inflamed = r.abn('ALT') || r.abn('AST'), bili = r.abn('TBIL');
    const n = inflamed ? scale(Math.max(alt || 0, ast || 0), 40, 400, 4, 16) : 0;
    const hex = (cx, cy, rr) => [0, 1, 2, 3, 4, 5].map(k => `${(cx + rr * Math.cos(k * Math.PI / 3)).toFixed(1)},${(cy + rr * Math.sin(k * Math.PI / 3)).toFixed(1)}`).join(' ');
    const sparks = Array.from({length: n}, () => `<circle r="2.6" cx="${(60 + rnd() * 170).toFixed(0)}" cy="${(52 + rnd() * 80).toFixed(0)}" class="spark-l"/>`).join('');
    const notes = [inflamed && `ALT ${alt ?? '—'} / AST ${ast ?? '—'}: injured liver cells shown as red flashes`, bili && `Bilirubin ${r.txt('TBIL')}: yellow (jaundiced) tint`, !inflamed && !bili && 'Liver tests within range'].filter(Boolean);
    return {svg: `<svg viewBox="0 0 340 200" class="oa oa-liver real ${bili ? 'jaundice' : ''}"><defs>${GRAIN}
      <linearGradient id="lv" x1="0" x2=".3" y1="0" y2="1"><stop offset="0" stop-color="#B85C46"/><stop offset=".6" stop-color="#8E3B2C"/><stop offset="1" stop-color="#5E2219"/></linearGradient></defs>
      ${part('liver', 'Liver: the largest internal organ; cleans blood, makes proteins, stores energy', '<path d="M24,70 C24,34 110,24 214,32 C262,36 270,58 246,80 C206,118 140,152 84,152 C42,152 22,112 24,70Z" fill="url(#lv)" filter="url(#oa-grain)" class="liver-shape"/><path d="M150,34 C146,70 140,110 130,148" stroke="#5E2219" stroke-width="2" fill="none" opacity=".6"/>')}
      ${part('gb', 'Gallbladder: stores bile made by the liver', '<path d="M120,140 C114,154 120,170 134,170 C146,170 148,154 140,142Z" fill="#5E8A3A"/>')}
      <path d="M90,60 C110,80 128,96 140,118 M170,56 C160,82 150,100 142,118" stroke="#3E5BA8" stroke-width="4" fill="none" opacity=".75"/>
      ${sparks}
      ${part('lobule', 'Lobule (magnified): liver cells arranged around a central vein', `<g><circle cx="286" cy="120" r="44" fill="#FBEFEA" stroke="#8E3B2C" stroke-width="2"/><polygon points="${hex(286, 120, 32)}" fill="#C97B60" stroke="#8E3B2C" stroke-width="1.5"/>${[0, 1, 2, 3, 4, 5].map(k => `<line x1="286" y1="120" x2="${(286 + 32 * Math.cos(k * Math.PI / 3)).toFixed(1)}" y2="${(120 + 32 * Math.sin(k * Math.PI / 3)).toFixed(1)}" stroke="#A5583F" stroke-width="2"/>`).join('')}<circle cx="286" cy="120" r="5" fill="#3E5BA8"/></g>`)}
      <path d="M244,104 L222,96" stroke="#8E3B2C" stroke-dasharray="3 3"/>
    </svg>`, notes, parts: {liver: 'The liver filters everything absorbed from the gut and makes clotting proteins.', gb: 'The gallbladder stores bile; stones here can block the bile duct and cause jaundice.',
      lobule: 'Each lobule is a hexagon of liver cells around a central vein. Raised ALT and AST mean some of these cells are damaged.'}};
  };
})();
