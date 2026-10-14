/* Realistic layered anatomy for Lab insights.
   Five layers you can peel away — skin, muscles, blood vessels, organs, skeleton — drawn with lighting so they look
   solid, and changed by the patient's real values: pale or yellow skin, a fever glow, swollen ankles, inflamed
   muscles, pressure in the arteries, cholesterol plaques, malaria parasites in the blood, a damaged heart wall,
   congested lungs, an inflamed liver, failing kidneys, fractures found on imaging…
   MFAnatomy.findings(data) is pure (tested in Node); MFAnatomy.mount(el, data) draws the interactive figure.
   Teaching and explanation aid: it does not replace the results, the images or clinical examination. */
(() => {
  'use strict';
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
  const round = (x, d = 2) => Math.round(x * 10 ** d) / 10 ** d;

  /* ================================================================== 1 · findings from the real values */
  const LEVEL = {HH: 3, LL: 3, H: 2, L: 2, A: 2};
  function findings(D) {
    D = D || {};
    const params = D.params || [];
    const P = code => params.find(p => p.code === code);
    const last = code => (P(code) || {}).latest || null;
    const n = code => { const l = last(code); return l && typeof l.num === 'number' ? l.num : null; };
    const fl = code => (last(code) || {}).flag || '';
    const hi = code => ['H', 'HH'].includes(fl(code)), lo = code => ['L', 'LL'].includes(fl(code));
    const crit = code => ['HH', 'LL'].includes(fl(code));
    const show = code => { const p = P(code), l = last(code); return p && l ? `${p.name} ${l.display}${p.unit ? ' ' + p.unit : ''}` : ''; };
    // whole history for long-term conditions; only the last 90 days of diagnoses and 6 months of imaging for acute ones
    const today = D.today ? new Date(D.today) : new Date();
    const recentImg = (D.imaging || []).filter(i => !i.date || (today - new Date(String(i.date).slice(0, 10))) / 864e5 <= 183);
    const lower = arr => arr.map(t => String(t || '').toLowerCase());
    const texts = lower([...(D.dx || []), ...(D.imaging || []).map(i => `${i.region || ''} ${i.impression || ''} ${i.findings || ''}`)]);
    const recent = lower([...(D.dx_recent || D.dx || []), ...recentImg.map(i => `${i.region || ''} ${i.impression || ''} ${i.findings || ''}`)]);
    const negated = (t, w) => new RegExp(`\\b(no|not|without|negative for|nil)\\b[^.;]{0,40}\\b${w}`).test(t)
      && !new RegExp(`(?:^|[.;]\\s*)(?![^.;]*\\b(no|not|without|negative for|nil)\\b)[^.;]*\\b${w}`).test(t);
    const found = (pool, words) => pool.some(t => words.some(w => new RegExp(`\\b${w}`).test(t) && !negated(t, w)));
    const says = (...words) => found(texts, words);        // ever (chronic conditions)
    const now = (...words) => found(recent, words);        // recently (acute problems)
    const V = D.vitals || {};
    const vit = k => { const x = parseFloat(String(V[k] ?? '').replace(',', '.')); return Number.isFinite(x) ? x : null; };
    const [sys, dia] = String(V.bp || '').split('/').map(x => parseFloat(x));
    const sbp = Number.isFinite(sys) ? sys : null, dbp = Number.isFinite(dia) ? dia : null;
    const spo2 = vit('spo2') ?? n('SAO2'), hr = vit('heart_rate'), rr = vit('resp_rate'), temp = vit('temperature_c');
    const sex = (D.patient || {}).sex || '', age = (D.patient || {}).age ?? null;
    const out = [];
    const add = (layer, target, level, title, text, codes = []) => out.push({id: `${layer}:${target}:${out.length}`, layer, target, level, title, text, codes});

    /* ---------------- skin */
    const hb = n('HB');
    const pallor = hb === null ? 0 : clamp((sex === 'F' ? 12 : 13) - hb, 0, 7) / 7;
    if (pallor > 0.05) add('skin', 'face', crit('HB') ? 3 : 2, 'Pale skin', `${show('HB')}: anaemia makes the skin, lips and nail beds pale.`, ['HB']);
    const bili = n('TBIL');
    const jaundice = bili === null ? (now('jaundice', 'icterus') ? 0.6 : 0) : clamp((bili - 21) / 120, 0, 1);
    if (jaundice > 0) add('skin', 'face', bili !== null && bili > 85 ? 3 : 2, 'Jaundice', bili !== null ? `${show('TBIL')}: bilirubin is staining the skin and the whites of the eyes yellow.` : 'Jaundice recorded in the notes.', ['TBIL']);
    const cyanosis = spo2 === null ? 0 : clamp((94 - spo2) / 14, 0, 1);
    if (cyanosis > 0) add('skin', 'lips', spo2 < 88 ? 3 : 2, 'Blue lips and fingertips', `Oxygen saturation ${spo2}%: not enough oxygen in the blood (cyanosis).`, ['SAO2']);
    const fever = temp === null ? 0 : clamp((temp - 37.5) / 2.5, 0, 1);
    if (fever > 0) add('skin', 'face', temp >= 39.5 ? 3 : 2, 'Fever', `Temperature ${temp} °C: the body is hot and flushed.`, []);
    const edema = Math.max(lo('ALB') ? clamp((35 - (n('ALB') ?? 35)) / 15, 0.3, 1) : 0, hi('BNP') ? 0.6 : 0, says('heart failure', 'nephrotic') || now('oedema', 'edema') ? 0.6 : 0);
    if (edema > 0) add('skin', 'ankles', 2, 'Swollen ankles', lo('ALB') ? `${show('ALB')}: low protein lets fluid leak into the legs.` : hi('BNP') ? `${show('BNP')}: the heart is struggling and fluid gathers in the legs.` : 'Fluid in the legs (oedema).', ['ALB', 'BNP']);
    const petechiae = (n('PLT') !== null && n('PLT') < 30) || hi('INR');
    if (petechiae) add('skin', 'legs', 3, 'Bleeding spots and bruises', n('PLT') !== null && n('PLT') < 30 ? `${show('PLT')}: too few platelets; tiny bleeds appear under the skin.` : `${show('INR')}: blood clots slowly; bruises appear easily.`, ['PLT', 'INR']);

    /* ---------------- muscles */
    const k = n('K');
    const twitch = k === null ? 0 : k > 5.5 ? clamp((k - 5.5) / 1.5, 0.3, 1) : k < 3.3 ? clamp((3.3 - k) / 1, 0.3, 1) : 0;
    if (twitch) add('muscle', 'thigh', crit('K') ? 3 : 2, k > 5.5 ? 'Muscle weakness (high potassium)' : 'Muscle weakness and cramps (low potassium)', `${show('K')}: muscles and the heart do not fire normally.`, ['K']);
    const ca = n('CA');
    const tetany = ca !== null && ca < 2.0;
    if (tetany) add('muscle', 'forearm', crit('CA') ? 3 : 2, 'Muscle spasms (low calcium)', `${show('CA')}: nerves over-fire; cramps of the hands and feet.`, ['CA']);
    const wasting = n('ALB') !== null && n('ALB') < 25 ? 0.5 : 0;
    if (wasting) add('muscle', 'thigh', 2, 'Muscle wasting', `${show('ALB')}: poor nutrition or long illness thins the muscles.`, ['ALB']);
    const inflamMuscle = now('myositis', 'rhabdomyolysis', 'pyomyositis') ? 0.8 : 0;
    if (inflamMuscle) add('muscle', 'thigh', 3, 'Inflamed muscle', 'Muscle inflammation in the diagnoses.', []);

    /* ---------------- blood vessels */
    const pressure = sbp === null ? 'normal' : sbp >= 180 || (dbp !== null && dbp >= 120) ? 'crisis' : sbp >= 140 || (dbp !== null && dbp >= 90) ? 'high' : sbp < 90 ? 'low' : 'normal';
    if (pressure !== 'normal') add('vessel', 'aorta', pressure === 'crisis' || pressure === 'low' ? 3 : 2,
      {crisis: 'Very high blood pressure', high: 'High blood pressure', low: 'Low blood pressure'}[pressure],
      `Blood pressure ${V.bp}: ${pressure === 'low' ? 'too little pressure to fill the organs (shock?).' : 'the arteries are under strain.'}`, []);
    const ldl = n('LDL'), tc = n('TC');
    const plaque = Math.max(ldl === null ? 0 : clamp((ldl - 3) / 3, 0, 1), tc === null ? 0 : clamp((tc - 5.2) / 3.5, 0, 1), says('atheroscler', 'coronary artery disease', 'stroke', 'peripheral arterial', 'dyslipid') ? 0.5 : 0);
    if (plaque > 0.05) add('vessel', 'carotid', plaque > 0.6 ? 3 : 2, 'Cholesterol plaques', `${[show('LDL'), show('TC')].filter(Boolean).join(', ') || 'Vascular disease'}: fatty plaques narrow the arteries.`, ['LDL', 'TC']);
    const anaemia = pallor;
    const rdt = last('RDT'), dens = n('DENS');
    const malaria = (rdt && (rdt.flag === 'A' || /pos|detected|falciparum/i.test(rdt.display || ''))) || (dens !== null && dens > 0) || now('malaria');
    if (malaria) add('vessel', 'blood', now('severe malaria', 'cerebral malaria') || (dens !== null && dens > 100000) ? 3 : 2, 'Malaria parasites in the blood',
      dens !== null ? `${show('DENS')}: parasites are living inside the red cells.` : 'Malaria test positive: parasites are living inside the red cells.', ['RDT', 'DENS']);
    const wbc = n('WBC'), plt = n('PLT');
    const white = wbc === null ? '' : wbc > 11 ? 'high' : wbc < 4 ? 'low' : '';
    if (white) add('vessel', 'blood', crit('WBC') ? 3 : 2, white === 'high' ? 'Many white cells' : 'Few white cells', `${show('WBC')}: ${white === 'high' ? 'the body is fighting an infection or inflammation.' : 'less protection against infection.'}`, ['WBC']);
    const glucose = n('FBG');
    const sugar = glucose === null ? (hi('A1C') ? 0.5 : 0) : clamp((glucose - 6) / 14, 0, 1);
    if (sugar > 0.05) add('vessel', 'blood', glucose !== null && glucose > 20 ? 3 : 2, 'High blood sugar', `${[show('FBG'), show('A1C')].filter(Boolean).join(', ')}: sugar damages small vessels in the eyes, kidneys and feet.`, ['FBG', 'A1C']);
    const clot = now('deep vein thrombosis', 'dvt\\b', 'venous thrombosis');
    if (clot) add('vessel', 'calf-vein', 3, 'Blood clot in a leg vein', 'Deep vein thrombosis recorded: a clot can travel to the lungs.', []);
    const sickle = (n('HBS') !== null && n('HBS') > 40) || says('sickle');
    if (sickle) add('vessel', 'blood', 2, 'Sickled red cells', `${show('HBS') || 'Sickle cell disease'}: stiff, curved red cells block small vessels.`, ['HBS']);

    /* ---------------- organs */
    const tni = n('TNI');
    const infarct = Math.max(hi('TNI') ? clamp((tni - 34) / 300, 0.35, 1) : 0, hi('CKMB') ? 0.4 : 0, now('myocardial infarction', 'st elevation', 'acute coronary') ? 0.5 : 0);
    if (infarct > 0) add('organ', 'heart', crit('TNI') || now('st elevation') ? 3 : 2, 'Heart muscle damage', `${show('TNI') || show('CKMB') || 'Acute coronary syndrome'}: part of the heart wall is not getting blood.`, ['TNI', 'CKMB']);
    const big = Math.max(hi('BNP') ? 0.5 : 0, says('cardiomegaly', 'dilated', 'heart failure', 'cardiomyopathy') ? 0.6 : 0);
    if (big > 0) add('organ', 'heart', 2, 'Enlarged, struggling heart', `${show('BNP') || 'Imaging'}: the heart is stretched and pumps weakly.`, ['BNP']);
    const hypox = Math.max(cyanosis, lo('PO2') ? 0.4 : 0);
    const consolid = now('consolidation', 'pneumonia', 'lobar pneumonia');
    const congest = now('congestion', 'pulmonary oedema', 'pulmonary edema', 'venous diversion');
    const effusion = now('pleural effusion', 'effusion');
    if (consolid) add('organ', 'lungs', 2, 'Pneumonia', 'Infection fills part of the lung with fluid and pus.', ['CRP', 'WBC']);
    if (congest) add('organ', 'lungs', 2, 'Fluid in the lungs', 'Congestion: fluid backs up into the lungs from a weak heart.', ['BNP']);
    if (hypox > 0.2 && !consolid && !congest) add('organ', 'lungs', 2, 'Low oxygen', `${spo2 !== null ? `Saturation ${spo2}%` : show('PO2')}: the lungs are not loading enough oxygen.`, ['SAO2', 'PO2']);
    if (now('tuberculosis', 'tb\\b', 'ptb\\b')) add('organ', 'lungs', 3, 'Tuberculosis', 'TB scars and cavities in the upper lungs.', []);
    const liverHit = Math.max(hi('ALT') ? clamp((n('ALT') - 56) / 400, 0.3, 1) : 0, hi('AST') ? clamp((n('AST') - 40) / 400, 0.3, 1) : 0, says('cirrhosis') || now('hepatitis', 'liver injury') ? 0.5 : 0);
    if (liverHit > 0) add('organ', 'liver', crit('ALT') || crit('AST') ? 3 : 2, 'Inflamed liver', `${[show('ALT'), show('AST')].filter(Boolean).join(', ') || 'Liver disease'}: liver cells are injured.`, ['ALT', 'AST', 'TBIL', 'ALB']);
    const kidneyHit = Math.max(hi('CREA') ? clamp((n('CREA') - 110) / 400, 0.3, 1) : 0, hi('UREA') ? 0.3 : 0, says('chronic kidney', 'ckd\\b', 'renal failure') || now('kidney injury', 'nephritis') ? 0.5 : 0);
    if (kidneyHit > 0) add('organ', 'kidneys', crit('CREA') || crit('K') ? 3 : 2, 'Kidneys filtering poorly', `${[show('CREA'), show('UREA')].filter(Boolean).join(', ') || 'Kidney disease'}: waste is building up in the blood.`, ['CREA', 'UREA', 'K']);
    const panc = Math.max(hi('LIPA') ? 0.8 : 0, hi('AMY') ? 0.5 : 0);
    if (panc > 0) add('organ', 'pancreas', crit('LIPA') ? 3 : 2, 'Inflamed pancreas', `${show('LIPA') || show('AMY')}: pancreatitis.`, ['LIPA', 'AMY']);
    if (sugar > 0.05) add('organ', 'pancreas', 2, 'Pancreas not controlling sugar', `${[show('FBG'), show('A1C')].filter(Boolean).join(', ')}: not enough insulin effect.`, ['FBG', 'A1C']);
    const spleen = malaria || now('splenomegaly', 'enlarged spleen') ? (now('splenomegaly') ? 0.8 : 0.5) : 0;
    if (spleen) add('organ', 'spleen', 2, 'Enlarged spleen', malaria ? 'The spleen swells while it clears malaria-infected red cells.' : 'Enlarged spleen on examination or imaging.', ['RDT']);
    const tsh = n('TSH');
    const thyroid = tsh === null ? '' : hi('TSH') ? 'under' : lo('TSH') ? 'over' : '';
    if (thyroid) add('organ', 'thyroid', crit('TSH') ? 3 : 2, thyroid === 'under' ? 'Underactive thyroid' : 'Overactive thyroid', `${show('TSH')}${show('FT4') ? ', ' + show('FT4') : ''}.`, ['TSH', 'FT4']);
    const na = n('NA');
    const brain = na === null ? '' : na < 125 || na > 155 ? 'swelling' : '';
    if (brain) add('organ', 'brain', 3, na < 125 ? 'Brain swelling risk (low sodium)' : 'Brain shrinking risk (high sodium)', `${show('NA')}: water moves in or out of the brain cells; confusion and fits.`, ['NA']);
    if (glucose !== null && glucose < 3.5) add('organ', 'brain', 3, 'Low blood sugar', `${show('FBG')}: the brain is short of fuel.`, ['FBG']);
    if (now('cerebral malaria', 'meningitis', 'stroke')) add('organ', 'brain', 3, now('stroke') ? 'Stroke' : 'Brain infection', 'Recorded in the diagnoses.', []);
    if (now('urinary tract infection', 'uti\\b', 'cystitis')) add('organ', 'bladder', 2, 'Bladder infection', 'Urinary tract infection.', []);
    if (sex === 'M' && hi('PSA')) add('organ', 'prostate', 2, 'Prostate', `${show('PSA')}: the prostate needs a closer look.`, ['PSA']);
    if (now('pregnan') && sex === 'F') add('organ', 'uterus', 1, 'Pregnancy', 'Pregnancy recorded.', []);

    /* ---------------- skeleton */
    const BONES = [['femur', ['femur', 'femoral neck', 'hip fracture', 'neck of femur']], ['tibia', ['tibia', 'tibial', 'shin']], ['fibula', ['fibula']], ['radius', ['radius', 'distal radius', 'colles', 'wrist fracture']],
      ['ulna', ['ulna']], ['humerus', ['humerus', 'humeral']], ['clavicle', ['clavicle', 'collarbone']], ['rib', ['rib']], ['pelvis', ['pelvis', 'pelvic', 'acetabul', 'pubic ramus']],
      ['skull', ['skull', 'cranial']], ['spine', ['vertebra', 'spine fracture', 'compression fracture', 'burst fracture']], ['ankle', ['ankle', 'malleol']], ['hand', ['metacarp', 'scaphoid', 'finger fracture']], ['foot', ['metatars', 'calcane', 'toe fracture']]];
    const fractures = [];
    recent.forEach(t => {
      if (!/fracture|broken/.test(t) || negated(t, 'fracture')) return;
      BONES.forEach(([bone, keys]) => {
        if (keys.some(k2 => t.includes(k2))) {
          const side = /\bleft\b/.test(t) ? 'left' : /\bright\b/.test(t) ? 'right' : 'right';
          if (!fractures.some(f => f.bone === bone && f.side === side)) fractures.push({bone, side, text: t.slice(0, 120)});
        }
      });
    });
    fractures.forEach(f => { add('bone', f.bone, 3, `Fracture: ${f.side} ${f.bone}`, f.text.charAt(0).toUpperCase() + f.text.slice(1), []); out[out.length - 1].side = f.side; });
    const osteo = says('osteopor', 'osteopenia') || (n('VITD') !== null && n('VITD') < 25) ? (says('osteopor') ? 0.8 : 0.4) : 0;
    if (osteo) add('bone', 'spine', 2, says('osteopor') ? 'Thin, fragile bones' : 'Low vitamin D', says('osteopor') ? 'Osteoporosis: bones break easily.' : `${show('VITD')}: bones lose strength.`, ['VITD', 'CA']);
    const gout = hi('URIC') || says('gout');
    if (gout) add('bone', 'toe', 2, 'Gout crystals', `${show('URIC') || 'Gout'}: uric acid crystals collect in joints, often the big toe.`, ['URIC']);
    const arthritis = says('rheumatoid', 'arthritis', 'osteoarthritis');
    if (arthritis) add('bone', 'knee', 2, 'Joint inflammation', 'Arthritis recorded: swollen, painful joints.', ['CRP', 'ESR']);
    const marrow = (wbc !== null && (wbc > 30 || wbc < 2)) || (plt !== null && plt < 50) || hi('BLAST') ? 1 : 0;
    if (marrow) add('bone', 'marrow', 3, 'Bone marrow under stress', `${[show('WBC'), show('PLT'), show('BLAST')].filter(Boolean).join(', ')}: the marrow is making too many or too few blood cells.`, ['WBC', 'PLT', 'BLAST']);
    const boneActivity = hi('ALP') && !liverHit ? 0.5 : 0;

    out.sort((a, b) => b.level - a.level);
    return {
      sex, age, hr: hr ?? 72, rr: rr ?? 14, findings: out,
      skin: {pallor: round(pallor), jaundice: round(jaundice), cyanosis: round(cyanosis), fever: round(fever), edema: round(edema), petechiae: !!petechiae},
      muscle: {twitch: round(twitch), tetany, wasting, inflam: inflamMuscle},
      vessel: {pressure, sbp, dbp, plaque: round(plaque), anaemia: round(anaemia), malaria: !!malaria, white, sugar: round(sugar), clot, sickle: !!sickle,
               plt: plt === null ? 'normal' : plt < 50 ? 'low' : plt > 450 ? 'high' : 'normal'},
      organ: {infarct: round(infarct), big: round(big), hypox: round(hypox), consolid, congest, effusion, liver: round(liverHit), yellow: round(jaundice),
              kidneys: round(kidneyHit), pancreas: round(Math.max(panc, sugar * 0.6)), spleen: round(spleen), thyroid, brain},
      bone: {fractures, osteo: round(osteo), gout: !!gout, arthritis: !!arthritis, marrow, activity: boneActivity},
    };
  }

  const API = {findings};
  if (typeof window !== 'undefined') window.MFAnatomy = API;
  if (typeof module !== 'undefined') module.exports = API;
  /* the drawing code below only runs in a browser */
  if (typeof document === 'undefined') return;

  /* ================================================================== 2 · geometry: one rig, five layers */
  const NS = 'http://www.w3.org/2000/svg';
  const W = 900, H = 1300, CX = 450;
  const RASTER = typeof devicePixelRatio === 'number' && devicePixelRatio > 1.5 ? 2 : 1.6;   // bitmap scale for the cached layers (sharp when zoomed in)
  const X = (dx, s) => CX + s * dx;                      // s = -1: patient's right (viewer's left); s = +1: patient's left
  const f1 = v => Math.round(v * 10) / 10;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  /* smooth curve through points (Catmull-Rom → cubic Bézier) */
  function smooth(pts, closed = true, t = 0.5) {
    const n = pts.length;
    if (n < 2) return '';
    const p = i => closed ? pts[(i + n) % n] : pts[clamp(i, 0, n - 1)];
    let d = `M${f1(pts[0][0])},${f1(pts[0][1])}`;
    const last = closed ? n : n - 1;
    for (let i = 0; i < last; i++) {
      const p0 = p(i - 1), p1 = p(i), p2 = p(i + 1), p3 = p(i + 2);
      const c1 = [p1[0] + (p2[0] - p0[0]) * t / 3, p1[1] + (p2[1] - p0[1]) * t / 3];
      const c2 = [p2[0] - (p3[0] - p1[0]) * t / 3, p2[1] - (p3[1] - p1[1]) * t / 3];
      d += ` C${f1(c1[0])},${f1(c1[1])} ${f1(c2[0])},${f1(c2[1])} ${f1(p2[0])},${f1(p2[1])}`;
    }
    return closed ? d + 'Z' : d;
  }
  /* a tapered tube along a centre line (limbs, muscles, bones, vessels) */
  function tubePts(line, widths) {
    const L = [], R = [];
    line.forEach((pt, i) => {
      const a = line[Math.max(0, i - 1)], b = line[Math.min(line.length - 1, i + 1)];
      let nx = -(b[1] - a[1]), ny = b[0] - a[0];
      const len = Math.hypot(nx, ny) || 1; nx /= len; ny /= len;
      const w = widths[i];
      L.push([pt[0] + nx * w, pt[1] + ny * w]); R.push([pt[0] - nx * w, pt[1] - ny * w]);
    });
    return L.concat(R.reverse());
  }
  const tube = (line, widths) => smooth(tubePts(line, widths), true, 0.45);
  const side = (pts, s) => pts.map(([dx, y]) => [X(dx, s), y]);
  /* a symmetric shape from its right half (dx ≥ 0, listed top to bottom) */
  const sym = half => smooth([...half.map(([dx, y]) => [X(dx, 1), y]), ...half.slice().reverse().map(([dx, y]) => [X(dx, -1), y])]);
  const ellipse = (cx, cy, rx, ry, rot = 0) => `<ellipse cx="${f1(cx)}" cy="${f1(cy)}" rx="${f1(rx)}" ry="${f1(ry)}" ${rot ? `transform="rotate(${rot} ${f1(cx)} ${f1(cy)})"` : ''}/>`;
  function rng(seed) { let s = seed >>> 0 || 7; return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296; }

  /* the rig: joints shared by every layer (dx from the midline, y) */
  const RIG = {
    arm: [[108, 292], [128, 330], [146, 420], [166, 515], [183, 605], [200, 700], [206, 714]],
    armW: [30, 33, 26, 22, 24, 17, 15],
    leg: [[62, 688], [60, 760], [56, 860], [52, 960], [52, 1010], [50, 1100], [46, 1205]],
    legW: [60, 55, 44, 33, 38, 30, 20],
  };

  const FINGERS = [[-18, 44, 5.2], [-6.5, 52, 5.5], [5.5, 50, 5.4], [16.5, 41, 4.7]];   // offset across the palm, length, half-width

  /* ---------------------------------------------------------------- the skin silhouette */
  function bodyParts(F) {
    const female = F.sex === 'F', ed = F.skin.edema * 9;
    const parts = [];
    parts.push(sym([[0, 36], [38, 42], [58, 70], [66, 112], [64, 150], [58, 178], [48, 200], [30, 218], [12, 228], [0, 230]]));    // head
    parts.push(sym([[0, 205], [32, 205], [36, 240], [46, 262], [0, 262]]));                                                          // neck
    const sh = female ? 0.92 : 1, hip = female ? 1.1 : 1;
    parts.push(sym([[0, 250], [40, 252], [74, 264], [102 * sh, 276], [122 * sh, 294], [132 * sh, 322], [106, 352], [110 * (female ? .97 : 1), 405], [102, 465],
      [84 * (female ? .92 : 1), 532], [92 * hip, 585], [106 * hip, 630], [114 * hip, 678], [108 * hip, 712], [62, 735], [12, 744], [0, 742]]));   // torso
    for (const s of [-1, 1]) {
      parts.push(tube(side(RIG.arm, s), RIG.armW));
      parts.push(tube(side([[205, 706], [211, 742], [215, 782]], s), [16, 24, 23]));                    // palm
      FINGERS.forEach(([o, len, w]) => parts.push(tube(side([[215 + o * .55, 776], [217 + o * .9, 778 + len * .55], [218 + o * 1.2, 778 + len]], s), [w, w * .9, w * .75])));
      parts.push(tube(side([[224, 724], [236, 750], [244, 776]], s), [8, 7, 5.5]));                       // thumb (palms forward: lateral)
      const lw = RIG.legW.map((w, i) => i >= 5 ? w + ed : i === 4 ? w + ed * .5 : w);
      parts.push(tube(side(RIG.leg, s), lw));
      parts.push(tube(side([[46, 1196], [49, 1238], [54, 1272]], s), [20 + ed * .6, 25, 27]));          // foot
      parts.push(smooth(side([[64, 128], [74, 132], [76, 150], [70, 166], [64, 162]], s)));   // ear
      if (female) parts.push(`<ellipse cx="${X(48, s)}" cy="392" rx="40" ry="34"/>`);
    }
    return parts.map(d => d.startsWith('<') ? d : `<path d="${d}"/>`).join('');
  }

  /* ---------------------------------------------------------------- muscles: [name, target, fibre angle, path] */
  function muscleList(F) {
    const M = [];
    const both = (name, target, ang, fn) => { for (const s of [-1, 1]) M.push([name, target, s * ang, fn(s)]); };
    M.push(['Frontalis', 'face', 90, sym([[0, 50], [34, 54], [54, 76], [56, 100], [30, 104], [0, 106]])]);
    both('Temporalis', 'face', 70, s => smooth(side([[54, 92], [64, 110], [62, 150], [52, 140], [48, 112]], s)));
    both('Orbicularis oculi', 'face', 0, s => smooth(side([[10, 120], [24, 110], [42, 116], [44, 134], [26, 144], [10, 138]], s)));
    both('Masseter', 'face', 80, s => smooth(side([[44, 160], [56, 164], [54, 198], [42, 204], [38, 180]], s)));
    M.push(['Orbicularis oris', 'lips', 0, sym([[0, 182], [14, 184], [22, 192], [14, 202], [0, 204]])]);
    both('Sternocleidomastoid', 'neck', 70, s => tube(side([[48, 178], [36, 215], [16, 262]], s), [7, 9, 6]));
    both('Trapezius', 'neck', 20, s => smooth(side([[30, 212], [40, 250], [80, 268], [112, 286], [70, 258], [36, 232]], s)));
    both('Deltoid', 'shoulder', 75, s => tube(side([[96, 284], [128, 304], [148, 360], [148, 402]], s), [16, 30, 22, 5]));
    both('Pectoralis major', 'chest', 15, s => smooth(side([[8, 276], [44, 272], [92, 286], [126, 322], [116, 342], [82, 390], [40, 404], [8, 392]], s)));
    both('Serratus anterior', 'chest', 40, s => [0, 1, 2, 3].map(i => smooth(side([[106 - i * 2, 382 + i * 22], [82 - i * 3, 392 + i * 22], [84 - i * 3, 402 + i * 22], [104 - i * 2, 398 + i * 22]], s))).join(' '));
    both('Rectus abdominis', 'abdomen', 90, s => [[408, 466], [472, 530], [536, 594], [600, 688]].map(([a, b], i) =>
      smooth(side([[5, a], [34 - i, a + 2], [37 - i * 2, (a + b) / 2], [33 - i * 3, b], [5, b]], s))).join(' '));
    both('External oblique', 'abdomen', 60, s => smooth(side([[44, 420], [96, 420], [104, 470], [92, 540], [100, 600], [72, 640], [44, 610], [42, 540]], s)));
    both('Biceps brachii', 'arm', 85, s => tube(side([[132, 350], [146, 420], [158, 490], [162, 512]], s), [8, 15, 12, 5]));
    both('Triceps (lateral head)', 'arm', 80, s => tube(side([[150, 352], [166, 430], [176, 500]], s), [6, 10, 5]));
    both('Brachioradialis', 'forearm', 80, s => tube(side([[170, 470], [186, 560], [198, 650], [203, 690]], s), [6, 12, 9, 4]));
    both('Forearm flexors', 'forearm', 80, s => tube(side([[160, 520], [172, 590], [188, 660], [198, 700]], s), [10, 13, 9, 4]));
    both('Thenar muscles', 'hand', 50, s => smooth(side([[214, 722], [226, 734], [226, 760], [214, 760]], s)));
    both('Tensor fasciae latae', 'thigh', 80, s => tube(side([[100, 610], [106, 660], [108, 705]], s), [8, 12, 6]));
    both('Vastus lateralis', 'thigh', 85, s => tube(side([[104, 690], [104, 780], [94, 880], [76, 940]], s), [10, 20, 18, 8]));
    both('Rectus femoris', 'thigh', 88, s => tube(side([[74, 650], [70, 740], [64, 840], [56, 925]], s), [8, 18, 16, 7]));
    both('Vastus medialis', 'thigh', 70, s => tube(side([[38, 830], [32, 880], [36, 935]], s), [6, 15, 9]));
    both('Adductors', 'thigh', 70, s => smooth(side([[14, 712], [42, 708], [46, 760], [32, 840], [14, 820]], s)));
    both('Sartorius', 'thigh', 60, s => tube(side([[94, 612], [80, 700], [56, 800], [36, 900], [38, 960]], s), [5, 7, 7, 6, 5]));
    both('Tibialis anterior', 'leg', 88, s => tube(side([[64, 992], [62, 1060], [56, 1140], [50, 1190]], s), [9, 11, 7, 3]));
    both('Gastrocnemius', 'leg', 88, s => tube(side([[30, 980], [24, 1040], [30, 1100], [38, 1140]], s), [8, 14, 9, 3]));
    both('Fibularis longus', 'leg', 88, s => tube(side([[80, 1000], [76, 1080], [66, 1170]], s), [6, 6, 3]));
    return M;
  }
  function tendons(F) {
    let t = `<path d="M${CX},404 L${CX},690" stroke-width="5"/>`;                                     // linea alba
    for (const s of [-1, 1]) {
      t += `<path d="${tube(side([[52, 925], [52, 990]], s), [12, 7])}" class="ar-fill"/>`;          // patellar tendon
      t += `<path d="${smooth(side([[150, 400], [160, 470], [166, 512]], s), false)}" stroke-width="3"/>`;
      FINGERS.forEach(([o]) => { t += `<path d="${smooth(side([[206 + o * .2, 712], [215 + o * .5, 776], [217 + o * .8, 800]], s), false)}" stroke-width="1.8" fill="none"/>`; });
      for (let i = 0; i < 4; i++) t += `<path d="${smooth(side([[46 + i * 3, 1205], [44 + i * 5, 1262]], s), false)}" stroke-width="1.8"/>`;
    }
    return t;
  }

  /* ---------------------------------------------------------------- vessels: [name, kind, target, points, widths] */
  function vesselList() {
    const V = [];
    const art = (name, target, pts, w) => V.push([name, 'a', target, pts, w]);
    const vein = (name, target, pts, w) => V.push([name, 'v', target, pts, w]);
    art('Aorta', 'aorta', [[462, 395], [458, 352], [446, 330], [430, 338], [432, 370], [440, 450], [444, 540], [448, 610]], [9, 9, 9, 8.5, 8, 7.5, 7, 6.5]);
    art('Brachiocephalic trunk', 'aorta', [[444, 333], [428, 304]], [6, 5.5]);
    for (const s of [-1, 1]) {
      const R = s < 0;
      art(`${R ? 'Right' : 'Left'} common carotid`, 'carotid', side([[R ? 24 : 10, R ? 300 : 332], [22, 270], [22, 228], [24, 200]], s), [4.5, 4.2, 4, 3.4]);
      art(`${R ? 'Right' : 'Left'} external carotid`, 'carotid', side([[24, 202], [36, 186], [50, 170], [60, 130], [58, 100]], s), [3, 2.6, 2.2, 1.8, 1.4]);
      art(`${R ? 'Right' : 'Left'} subclavian / axillary / brachial artery`, 'arm', side([[R ? 24 : 18, R ? 302 : 334], [60, 290], [104, 298], [136, 332], [146, 400], [158, 500], [168, 528]], s), [4.6, 4.4, 4.2, 3.8, 3.5, 3.2, 3]);
      art(`${R ? 'Right' : 'Left'} radial artery`, 'arm', side([[168, 528], [182, 590], [194, 660], [204, 712], [212, 750]], s), [2.6, 2.4, 2.2, 2, 1.6]);
      art(`${R ? 'Right' : 'Left'} ulnar artery`, 'arm', side([[166, 530], [170, 600], [186, 670], [200, 718], [208, 752]], s), [2.6, 2.4, 2.2, 2, 1.6]);
      art(`${R ? 'Right' : 'Left'} renal artery`, 'kidneys', [[X(R ? 8 : 6, s), 524], [X(74, s), 540]], [3, 2.6]);
      art(`${R ? 'Right' : 'Left'} iliac and femoral artery`, 'leg', side([[2, 610], [28, 640], [46, 690], [54, 730], [52, 800], [42, 900], [44, 960]], s), [5.5, 5.2, 5, 4.8, 4.4, 4, 3.6]);
      art(`${R ? 'Right' : 'Left'} anterior tibial artery`, 'leg', side([[48, 975], [58, 1010], [56, 1100], [50, 1200], [52, 1262]], s), [3, 2.8, 2.5, 2.2, 1.8]);
      vein(`${R ? 'Right' : 'Left'} internal jugular vein`, 'neck', side([[R ? 10 : 12, 318], [30, 270], [32, 232], [32, 200]], s), [5.5, 5, 4.6, 4]);
      vein(`${R ? 'Right' : 'Left'} external jugular vein`, 'neck', side([[42, 282], [44, 240], [52, 200], [56, 176]], s), [2.6, 2.4, 2.2, 1.8]);
      vein(`${R ? 'Right' : 'Left'} subclavian and axillary vein`, 'arm', side([[R ? 10 : 12, 320], [64, 302], [108, 306], [134, 342], [144, 408], [154, 500]], s), [5, 4.8, 4.6, 4.2, 3.6, 3.2]);
      vein(`${R ? 'Right' : 'Left'} cephalic vein`, 'arm', side([[118, 300], [150, 360], [164, 450], [176, 520], [194, 610], [206, 700]], s), [2.8, 2.7, 2.6, 2.5, 2.3, 2]);
      vein(`${R ? 'Right' : 'Left'} basilic vein`, 'arm', side([[150, 420], [158, 500], [168, 560], [180, 640], [196, 712]], s), [2.8, 2.7, 2.5, 2.3, 2]);
      vein(`${R ? 'Right' : 'Left'} median cubital vein (blood tests are taken here)`, 'arm', side([[176, 522], [168, 534], [161, 546]], s), [2.4, 2.4, 2.4]);
      vein(`${R ? 'Right' : 'Left'} iliac and femoral vein`, 'leg', side([[6, 612], [22, 646], [38, 694], [46, 734], [44, 800], [34, 900], [38, 962], [44, 1020]], s), [6, 5.6, 5.4, 5, 4.8, 4.4, 4, 3.6]);
      vein(`${R ? 'Right' : 'Left'} great saphenous vein`, 'leg', side([[44, 732], [32, 800], [24, 880], [28, 950], [34, 1040], [36, 1140], [34, 1210]], s), [3, 2.8, 2.7, 2.6, 2.4, 2.2, 2]);
    }
    vein('Superior vena cava', 'aorta', [[438, 400], [436, 360], [440, 322]], [7, 7, 6.5]);
    vein('Inferior vena cava', 'aorta', [[440, 430], [436, 520], [440, 612]], [8, 7.5, 7]);
    return V;
  }

  /* ---------------------------------------------------------------- organs: paths built on the same rig */
  function intestinePath(seed) {
    const r = rng(seed), pts = [];
    let y = 588, dir = 1;
    for (let row = 0; row < 6; row++) {
      for (let k = 0; k <= 6; k++) {
        const t = k / 6, x = dir > 0 ? -58 + t * 116 : 58 - t * 116;
        pts.push([CX + x + (r() - .5) * 8, y + Math.sin(t * Math.PI * 3) * 6 + (r() - .5) * 5]);
      }
      y += 17; dir = -dir;
    }
    return smooth(pts, false, .6);
  }
  function ribGeometry(i) {
    // i = 1..12: posterior end at the spine (higher), lateral bulge, anterior end (lower) towards the sternum
    const yp = 270 + i * 16.5, wide = [0, 56, 72, 84, 92, 98, 102, 104, 104, 100, 92, 70, 52][i];
    const yl = yp + 30 + i * 1.2, ya = yp + 56 + i * 3.4;
    const front = i <= 10 ? [[14, yp + 6], [wide * .55, yp - 4], [wide * .92, yp + 8], [wide, yl], [wide * .9, ya - 8], [wide * .62, ya]] : [[14, yp + 6], [wide * .7, yp + 2], [wide, yl + 6]];
    return {yp, ya, wide, front};
  }

  /* ================================================================== 3 · materials */
  const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const mix = (a, b, t) => '#' + hex(a).map((v, i) => Math.round(v + (hex(b)[i] - v) * clamp(t, 0, 1)).toString(16).padStart(2, '0')).join('');
  function lightFilter(id, blur, scale, spec, exp, k1 = 1.25, noise = 0) {
    return `<filter id="${id}" x="-4%" y="-4%" width="108%" height="108%" color-interpolation-filters="sRGB">
      <feGaussianBlur in="SourceAlpha" stdDeviation="${blur}" result="h"/>
      <feDiffuseLighting in="h" surfaceScale="${scale}" diffuseConstant="1" lighting-color="#fff" result="d"><feDistantLight azimuth="225" elevation="50"/></feDiffuseLighting>
      <feSpecularLighting in="h" surfaceScale="${scale}" specularConstant="${spec}" specularExponent="${exp}" lighting-color="#fff8f0" result="s"><feDistantLight azimuth="225" elevation="58"/></feSpecularLighting>
      <feComposite in="s" in2="SourceAlpha" operator="in" result="s2"/>
      <feComposite in="SourceGraphic" in2="d" operator="arithmetic" k1="${k1}" result="lit"/>
      <feComposite in="lit" in2="s2" operator="arithmetic" k2="1" k3="1" result="ls"/>
      ${noise ? `<feTurbulence type="fractalNoise" baseFrequency="${noise}" numOctaves="2" seed="4" result="n"/>
      <feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -.16 .09" result="n2"/>
      <feComposite in="n2" in2="SourceAlpha" operator="in" result="n3"/>
      <feMerge result="ls2"><feMergeNode in="ls"/><feMergeNode in="n3"/></feMerge>
      <feComposite in="ls2" in2="SourceAlpha" operator="in"/>` : '<feComposite in="ls" in2="SourceAlpha" operator="in"/>'}
    </filter>`;
  }
  function defs(F, skin) {
    const angles = [...new Set(muscleList(F).map(m => Math.round(m[2] / 10) * 10))];
    return `<defs>
      ${lightFilter('ar-f-skin', 9, 7, .32, 16, 1.2, 1.6)}
      ${lightFilter('ar-f-muscle', 2.4, 4, .75, 26, 1.3, 0)}
      ${lightFilter('ar-f-organ', 4, 5, .85, 30, 1.25, 0)}
      ${lightFilter('ar-f-bone', 2.2, 3.6, .5, 14, 1.18, 2.2)}
      <filter id="ar-blur6" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6"/></filter>
      <filter id="ar-blur14" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="14"/></filter>
      <filter id="ar-shadow" x="-20%" y="-10%" width="140%" height="130%"><feGaussianBlur in="SourceAlpha" stdDeviation="14"/><feOffset dx="10" dy="16"/><feComponentTransfer><feFuncA type="linear" slope=".45"/></feComponentTransfer></filter>
      ${angles.map(a => `<pattern id="ar-fib${a < 0 ? 'm' + -a : a}" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(${a})"><path d="M0,1.2 H5" stroke="#4a0d0d" stroke-width=".9" opacity=".45"/><path d="M0,3.6 H5" stroke="#e98a7a" stroke-width=".5" opacity=".25"/></pattern>`).join('')}
      <pattern id="ar-alv" width="7" height="7" patternUnits="userSpaceOnUse"><circle cx="3.5" cy="3.5" r="2.2" fill="none" stroke="#a24d58" stroke-width=".7" opacity=".55"/></pattern>
      <pattern id="ar-porous" width="6" height="6" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.1" fill="#8a7b62" opacity=".7"/><circle cx="5" cy="4.5" r=".8" fill="#8a7b62" opacity=".6"/></pattern>
      <linearGradient id="ar-g-muscle" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#c24a3f"/><stop offset=".55" stop-color="#a1302b"/><stop offset="1" stop-color="#7a1f1d"/></linearGradient>
      <linearGradient id="ar-g-bone" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f6efe0"/><stop offset=".6" stop-color="#e7dcc3"/><stop offset="1" stop-color="#cdbf9f"/></linearGradient>
      <radialGradient id="ar-g-lung" cx=".4" cy=".35" r=".8"><stop offset="0" stop-color="${mix('#e9a0a2', '#8f7fb6', F.organ.hypox)}"/><stop offset="1" stop-color="${mix('#b8606a', '#5d4f8a', F.organ.hypox)}"/></radialGradient>
      <radialGradient id="ar-g-heart" cx=".4" cy=".35" r=".8"><stop offset="0" stop-color="#c8463c"/><stop offset="1" stop-color="#7c1d1b"/></radialGradient>
      <radialGradient id="ar-g-liver" cx=".35" cy=".3" r=".9"><stop offset="0" stop-color="${mix(mix('#a2412c', '#d0402c', F.organ.liver), '#9a8a2a', F.organ.yellow)}"/><stop offset="1" stop-color="${mix(mix('#5e1f14', '#8a2016', F.organ.liver), '#5e5418', F.organ.yellow)}"/></radialGradient>
      <radialGradient id="ar-g-kidney" cx=".4" cy=".35" r=".8"><stop offset="0" stop-color="${mix('#a9483c', '#7d6a64', F.organ.kidneys)}"/><stop offset="1" stop-color="${mix('#5c1d18', '#3d322f', F.organ.kidneys)}"/></radialGradient>
      <radialGradient id="ar-g-hot"><stop offset="0" stop-color="#ff4d4d" stop-opacity=".75"/><stop offset=".55" stop-color="#ff4d4d" stop-opacity=".25"/><stop offset="1" stop-color="#ff4d4d" stop-opacity="0"/></radialGradient>
      <radialGradient id="ar-g-warn"><stop offset="0" stop-color="#ffb02e" stop-opacity=".7"/><stop offset=".55" stop-color="#ffb02e" stop-opacity=".22"/><stop offset="1" stop-color="#ffb02e" stop-opacity="0"/></radialGradient>
      <radialGradient id="ar-g-lens"><stop offset=".86" stop-color="#7fe7ff" stop-opacity="0"/><stop offset=".97" stop-color="#7fe7ff" stop-opacity=".5"/><stop offset="1" stop-color="#7fe7ff" stop-opacity="0"/></radialGradient>
      <clipPath id="ar-body-clip">${bodyParts(F)}</clipPath>
      ${LAYERS.map(l => `<clipPath id="ar-h-${l.key}" clipPathUnits="userSpaceOnUse"><path class="ar-holes" clip-rule="evenodd" d="M-200,-200H${W + 200}V${H + 200}H-200Z"/></clipPath><clipPath id="ar-l-${l.key}" clipPathUnits="userSpaceOnUse"><path class="ar-lens-hole" clip-rule="evenodd" d="M-200,-200H${W + 200}V${H + 200}H-200Z"/></clipPath>`).join('')}
    </defs>`;
  }

  const LAYERS = [
    {key: 'skin', label: 'Skin', icon: 'bi-person', flap: null},
    {key: 'muscle', label: 'Muscles', icon: 'bi-lightning-charge', flap: '#a1302b'},
    {key: 'vessel', label: 'Blood vessels', icon: 'bi-droplet-half', flap: '#c0392b'},
    {key: 'organ', label: 'Organs', icon: 'bi-heart-pulse', flap: '#b8606a'},
    {key: 'bone', label: 'Skeleton', icon: 'bi-universal-access', flap: '#e7dcc3'},
  ];

  /* ================================================================== 4 · the five layers */
  function skinColour(F) {
    let c = '#8a5a3c';
    c = mix(c, '#c9ab95', F.skin.pallor * .55);
    c = mix(c, '#b8923a', F.skin.jaundice * .5);
    return c;
  }
  function layerSkin(F, skin) {
    const lips = mix(mix('#6e2f2a', '#b08a7c', F.skin.pallor * .7), '#4c5c9c', F.skin.cyanosis * .85);
    const nail = mix(mix('#c99a86', '#e2d2c8', F.skin.pallor), '#7b86c0', F.skin.cyanosis);
    const sclera = mix('#f4f1ea', '#e8c84a', F.skin.jaundice * .85);
    const hair = `<path d="${sym([[0, 30], [40, 34], [62, 66], [67, 104], [60, 96], [54, 78], [30, 64], [0, 62]])}" fill="#1c1410"/>`;
    const shorts = `<path d="${sym([[0, 604], [94, 598], [110, 648], [117, 712], [114, 770], [70, 782], [24, 762], [6, 748], [0, 745]])}" fill="#4a5f74"/>`;
    let d = `<g filter="url(#ar-f-skin)" fill="${skin}" stroke="${skin}" stroke-width="2.2" stroke-linejoin="round" data-name="Skin" data-target="skin"><g>${bodyParts(F)}</g><g stroke="#1c1410">${hair}</g><g stroke="#4a5f74">${shorts}</g></g>`;
    // the face and details, drawn crisp on top of the lit skin
    d += '<g class="ar-face" pointer-events="none">';
    for (const s of [-1, 1]) {
      d += `<path d="${smooth(side([[12, 128], [24, 121], [38, 126], [26, 133]], s))}" fill="${sclera}"/>`;
      d += `<circle cx="${X(25, s)}" cy="127" r="5.6" fill="#2a1a10"/><circle cx="${X(25, s)}" cy="127" r="2.4" fill="#070403"/><circle cx="${X(23.4, s)}" cy="125.4" r="1.3" fill="#fff" opacity=".9"/>`;
      d += `<path d="${smooth(side([[10, 128], [24, 119], [40, 125]], s), false)}" stroke="#2a160d" stroke-width="1.8" fill="none"/>`;
      d += `<path d="${smooth(side([[10, 112], [26, 107], [42, 112]], s), false)}" stroke="#1c120c" stroke-width="3.2" stroke-linecap="round" fill="none"/>`;
      d += `<circle cx="${X(F.sex === 'F' ? 48 : 52, s)}" cy="${F.sex === 'F' ? 400 : 372}" r="4.5" fill="${mix(skin, '#3a2015', .55)}"/>`;
      // nail beds: blue when oxygen is low
      FINGERS.forEach(([o, len]) => { d += `<ellipse cx="${f1(X(218 + o * 1.2, s))}" cy="${778 + len - 5}" rx="3" ry="4.4" fill="${nail}"/>`; });
      for (let i = 0; i < 3; i++) { const a = FINGERS[i][0], b2 = FINGERS[i + 1][0], m = (a + b2) / 2; d += `<path d="${smooth(side([[215 + m * .55, 780], [218 + m * 1.05, 806]], s), false)}" stroke="${mix(skin, '#1a0d08', .55)}" stroke-width="1.4" fill="none" opacity=".8"/>`; }
    }
    d += `<path d="M${CX - 7},150 Q${CX},166 ${CX + 7},150" stroke="${mix(skin, '#2a160d', .5)}" stroke-width="2" fill="none"/>`;
    d += `<path d="${sym([[0, 186], [12, 184], [21, 191], [12, 199], [0, 201]])}" fill="${lips}"/><path d="M${CX - 20},191.5 Q${CX},194 ${CX + 20},191.5" stroke="#2a1410" stroke-width="1.2" fill="none"/>`;
    d += `<ellipse cx="${CX}" cy="560" rx="3.2" ry="5" fill="${mix(skin, '#2a160d', .5)}"/>`;
    d += '</g>';
    // values on the skin
    let fx = '';
    if (F.skin.fever) fx += `<g class="ar-fever" opacity="${f1(.25 + F.skin.fever * .55)}" filter="url(#ar-blur14)" fill="#ff5a2a">${bodyParts(F)}</g>`;
    if (F.skin.edema) for (const s of [-1, 1]) fx += `<ellipse cx="${X(46, s)}" cy="1180" rx="${f1(26 + F.skin.edema * 8)}" ry="34" fill="#fff" opacity=".12"/><ellipse cx="${X(40, s)}" cy="1170" rx="6" ry="14" fill="#fff" opacity=".25"/>`;
    if (F.skin.petechiae) { const r = rng(9); for (let i = 0; i < 60; i++) { const s = r() < .5 ? -1 : 1, leg = r() < .7; fx += `<circle cx="${f1(leg ? X(40 + r() * 26, s) : X(176 + r() * 20, s))}" cy="${f1(leg ? 1000 + r() * 180 : 540 + r() * 140)}" r="${f1(.8 + r() * 1.4)}" fill="#7a0b12" opacity=".85"/>`; } }
    const aura = (fx.match(/<g class="ar-fever"[\s\S]*?<\/g>/) || [''])[0];
    return {stat: `<g class="ar-shadowcast" filter="url(#ar-shadow)" fill="#000">${bodyParts(F)}</g>${aura}${d}${fx.replace(aura, '')}`, live: ''};
  }

  function layerMuscle(F) {
    const list = muscleList(F);
    let d = `<g fill="#5a1616" data-name="Fascia" data-target="fascia">${bodyParts(F)}</g>`;
    d += `<g filter="url(#ar-f-muscle)">`;
    d += list.map(([name, target, ang, path]) => `<path d="${path}" fill="url(#ar-g-muscle)" data-name="${esc(name)}" data-target="${target}"/>`).join('');
    d += `</g><g pointer-events="none">${list.map(([, , ang, path]) => { const a = Math.round(ang / 10) * 10; return `<path d="${path}" fill="url(#ar-fib${a < 0 ? 'm' + -a : a})"/>`; }).join('')}</g>`;
    d += `<g stroke="#e8dccb" fill="#e8dccb" opacity=".85" filter="url(#ar-f-bone)" data-name="Tendons and aponeuroses" data-target="tendon">${tendons(F)}</g>`;
    // the eyes stay visible under the muscles
    for (const s of [-1, 1]) d += `<ellipse cx="${X(25, s)}" cy="127" rx="13" ry="9" fill="${mix('#f2eee6', '#e8c84a', F.skin.jaundice * .8)}"/><circle cx="${X(25, s)}" cy="127" r="5.5" fill="#2a1a10"/>`;
    let fx = '';
    let live = '';
    if (F.muscle.twitch || F.muscle.inflam) live += `<g class="ar-twitch" fill="#ff3b2f" opacity="0">${list.filter(m => ['thigh', 'leg', 'arm', 'forearm'].includes(m[1])).map(m => `<path d="${m[3]}"/>`).join('')}</g>`;
    if (F.muscle.tetany) live += `<g class="ar-twitch" fill="#ffd23f" opacity="0">${list.filter(m => ['hand', 'forearm'].includes(m[1])).map(m => `<path d="${m[3]}"/>`).join('')}</g>`;
    if (F.muscle.wasting) fx += `<g fill="#1a0505" opacity=".25">${list.filter(m => ['thigh', 'arm'].includes(m[1])).map(m => `<path d="${m[3]}"/>`).join('')}</g>`;
    return {stat: d + fx, live};
  }

  function layerVessel(F) {
    const V = F.vessel, k = V.pressure === 'crisis' ? 1.3 : V.pressure === 'high' ? 1.15 : V.pressure === 'low' ? .72 : 1;
    const red = mix(mix('#c21f2a', '#d97a7a', V.anaemia * .6), '#e04040', V.pressure === 'crisis' ? .3 : 0);
    let d = `<g fill="#fff" opacity=".07" pointer-events="none">${bodyParts(F)}</g>`;
    const list = vesselList();
    let pulses = '';
    const draw = (kind) => list.filter(v => v[1] === kind).map(([name, , target, pts, w]) => {
      const ww = w.map(x => x * (kind === 'a' ? k : 1));
      const avg = ww.reduce((a, b) => a + b, 0) / ww.length;
      const c = smooth(pts, false);
      const [edge, mid, hl] = kind === 'a' ? [mix(red, '#3a0508', .5), red, mix(red, '#ffd0c8', .55)] : ['#1d2a63', '#3653b0', '#9fb3ff'];
      return `<g data-name="${esc(name)}" data-target="${target}" class="ar-v ar-v-${kind}"><path d="${tube(pts, ww)}" fill="${edge}"/>
        <path d="${c}" stroke="${mid}" stroke-width="${f1(avg * 1.25)}" fill="none" stroke-linecap="round"/>
        <path d="${c}" stroke="${hl}" stroke-width="${f1(Math.max(.6, avg * .35))}" fill="none" stroke-linecap="round" opacity=".8" transform="translate(-${f1(avg * .3)},-${f1(avg * .25)})"/>
        ${kind === 'a' ? ((pulses += `<path class="ar-pulse" d="${c}" stroke="#ffe3dc" stroke-width="${f1(avg * 1.6)}" fill="none" stroke-linecap="round" opacity=".7"/>`), '') : ''}</g>`;
    }).join('');
    d += `<g class="ar-veins">${draw('v')}</g><g class="ar-arteries">${draw('a')}</g>`;
    // plaques where cholesterol narrows the arteries
    if (V.plaque > .05) {
      const spots = [[X(22, -1), 226], [X(22, 1), 226], [438, 345], [X(50, -1), 760], [X(50, 1), 760], [446, 560]];
      d += `<g data-name="Cholesterol plaques" data-target="carotid">${spots.slice(0, 2 + Math.round(V.plaque * 4)).map(([x, y]) => `<ellipse cx="${x + 2.5}" cy="${y}" rx="${f1(2 + V.plaque * 3)}" ry="${f1(5 + V.plaque * 5)}" fill="#f4d35e" stroke="#b8901c" stroke-width=".8"/>`).join('')}</g>`;
    }
    if (V.clot) d += `<g data-name="Deep vein thrombosis (clot)" data-target="calf-vein"><ellipse cx="${X(41, -1)}" cy="1032" rx="5" ry="22" fill="#3a0306"/><ellipse cx="${X(44, -1)}" cy="1040" rx="30" ry="60" fill="#ff3b2f" opacity=".18"/></g>`;
    return {stat: d, live: `<g pointer-events="none">${pulses}</g><g class="ar-cells" pointer-events="none"></g>`};
  }

  function layerOrgan(F) {
    const O = F.organ, female = F.sex === 'F';
    let d = '';
    const g = (name, target, inner, extra = '') => `<g data-name="${esc(name)}" data-target="${target}" ${extra}>${inner}</g>`;
    // behind: kidneys, adrenals, ureters, great vessels
    let back = '';
    for (const s of [-1, 1]) {
      const kx = X(88, s), ky = s < 0 ? 556 : 544, sc = 1 - O.kidneys * .12;
      back += g(`${s < 0 ? 'Right' : 'Left'} kidney`, 'kidneys', `<path d="M${kx},${ky - 34 * sc} C${kx + s * 26 * sc},${ky - 34 * sc} ${kx + s * 26 * sc},${ky + 34 * sc} ${kx},${ky + 34 * sc} C${kx - s * 14},${ky + 30 * sc} ${kx - s * 6},${ky + 8} ${kx - s * 12},${ky} C${kx - s * 6},${ky - 8} ${kx - s * 14},${ky - 30 * sc} ${kx},${ky - 34 * sc}Z" fill="url(#ar-g-kidney)"/>
        <path d="M${kx - s * 4},${ky - 46} q${s * 14},-6 ${s * 20},8 q${-s * 10},4 ${-s * 20},-8z" fill="#d7a05a"/>`);
      back += `<path d="${smooth([[kx - s * 12, ky + 4], [X(52, s), 630], [X(20, s), 700]], false)}" stroke="#e6c7a4" stroke-width="2.4" fill="none"/>`;
    }
    d += `<g filter="url(#ar-f-organ)">${back}</g>`;
    // gut: small bowel coils, the colon frame, appendix
    const colon = smooth([[X(68, -1), 690], [X(72, -1), 612], [X(68, -1), 578], [X(40, -1), 572], [CX, 588], [X(40, 1), 572], [X(72, 1), 576], [X(74, 1), 622], [X(70, 1), 680], [X(40, 1), 704], [X(10, 1), 718]], false);
    let gut = g('Small intestine', 'gut', `<path d="${intestinePath(5)}" stroke="#e3a28b" stroke-width="15" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="${intestinePath(5)}" stroke="#f3c2ad" stroke-width="4" fill="none" opacity=".6"/>`);
    gut += g('Large intestine (colon)', 'gut', `<path d="${colon}" stroke="#c98a6c" stroke-width="22" fill="none" stroke-linecap="round" stroke-dasharray="16 2.2"/>`);
    gut += g('Appendix', 'gut', `<path d="${smooth([[X(76, -1), 690], [X(70, -1), 712], [X(60, -1), 718]], false)}" stroke="#c98a6c" stroke-width="5" fill="none" stroke-linecap="round"/>`);
    // pelvis organs
    gut += g('Bladder', 'bladder', `<ellipse cx="${CX}" cy="${female ? 716 : 708}" rx="26" ry="20" fill="${says(F, 'bladder') ? '#e46a5a' : '#e8b7a0'}"/>`);
    if (female) gut += g('Uterus', 'uterus', `<path d="M${CX - 18},676 Q${CX},660 ${CX + 18},676 Q${CX + 12},700 ${CX},704 Q${CX - 12},700 ${CX - 18},676Z" fill="#c9787a"/><ellipse cx="${CX - 34}" cy="682" rx="7" ry="5" fill="#e0b0a0"/><ellipse cx="${CX + 34}" cy="682" rx="7" ry="5" fill="#e0b0a0"/>`);
    else gut += g('Prostate', 'prostate', `<ellipse cx="${CX}" cy="732" rx="11" ry="9" fill="#b9806a"/>`);
    d += `<g filter="url(#ar-f-organ)">${gut}</g>`;
    // upper abdomen: liver, gallbladder, stomach, spleen, pancreas
    const sp = 1 + O.spleen * .5;
    let up = g('Pancreas', 'pancreas', `<path d="${tube([[X(16, -1), 548], [CX, 540], [X(40, 1), 528], [X(80, 1), 506]], [9, 10, 8, 6])}" fill="${mix('#e6c58f', '#ff8a3d', O.pancreas)}"/>`);
    up += g('Spleen', 'spleen', `<ellipse cx="${X(98, 1)}" cy="${478 + O.spleen * 14}" rx="${f1(17 * sp)}" ry="${f1(30 * sp)}" fill="#6e2a3c" transform="rotate(-22 ${X(98, 1)} 478)"/>`);
    up += g('Stomach', 'stomach', `<path d="${smooth([[X(18, 1), 470], [X(56, 1), 462], [X(88, 1), 486], [X(86, 1), 540], [X(58, 1), 574], [X(18, 1), 576], [X(8, -1), 560], [X(10, 1), 548], [X(44, 1), 546], [X(56, 1), 520], [X(36, 1), 496]])}" fill="#d9a09a"/>`);
    up += g('Liver', 'liver', `<path d="${smooth([[X(108, -1), 470], [X(64, -1), 450], [X(10, -1), 452], [X(30, 1), 462], [X(58, 1), 482], [X(30, 1), 506], [X(24, -1), 532], [X(72, -1), 568], [X(104, -1), 548]])}" fill="url(#ar-g-liver)"/>`);
    up += g('Gallbladder', 'liver', `<ellipse cx="${X(46, -1)}" cy="548" rx="9" ry="14" fill="#4f8a3c" transform="rotate(-25 ${X(46, -1)} 548)"/>`);
    d += `<g filter="url(#ar-f-organ)">${up}</g>`;
    // chest: trachea, lungs (breathing), heart (beating), thyroid, brain
    let neck = g('Thyroid', 'thyroid', `<path d="${sym([[0, 262], [10, 258], [22, 246], [24, 262], [18, 276], [0, 268]])}" fill="${O.thyroid ? '#d4523f' : '#b4604c'}"/>`);
    neck += g('Trachea', 'lungs', `<path d="${tube([[CX, 228], [CX, 300], [CX, 352]], [8, 8, 8])}" fill="#dccfc0"/>${Array.from({length: 13}, (_, i) => `<path d="M${CX - 8},${236 + i * 9} h16" stroke="#b7a690" stroke-width="2"/>`).join('')}`);
    neck += g('Brain', 'brain', `<ellipse cx="${CX}" cy="92" rx="58" ry="50" fill="${O.brain ? '#e6a3a0' : '#e2b7ae'}"/>${brainGyri()}`);
    d += `<g filter="url(#ar-f-organ)">${neck}</g>`;
    const lungs = [-1, 1].map(s => {
      const pts = s < 0 ? [[22, 300], [48, 296], [86, 352], [102, 420], [100, 478], [62, 462], [24, 470], [20, 410]] : [[22, 300], [46, 296], [84, 352], [100, 420], [98, 486], [58, 474], [32, 466], [38, 424], [24, 398]];
      return g(`${s < 0 ? 'Right' : 'Left'} lung`, 'lungs', `<path d="${smooth(side(pts, s))}" fill="url(#ar-g-lung)"/><path d="${smooth(side(pts, s))}" fill="url(#ar-alv)"/>
        <path d="${smooth(side(s < 0 ? [[86, 372], [52, 404], [26, 430]] : [[90, 366], [52, 414], [32, 450]], s), false)}" stroke="#7d3440" stroke-width="1.4" fill="none" opacity=".6"/>
        ${O.consolid && s < 0 ? `<path d="${smooth(side([[40, 424], [92, 420], [98, 470], [62, 458], [26, 464]], s))}" fill="#f2e9d8" opacity=".75"/>` : ''}
        ${O.congest ? `<path d="${smooth(side(pts, s))}" fill="#9fb6d8" opacity=".32"/>` : ''}
        ${O.effusion ? `<path d="${smooth(side([[22, 452], [100, 446], [100, 480], [22, 470]], s))}" fill="#a9c4dc" opacity=".8"/>` : ''}`);
    }).join('');
    const live = `<g class="ar-breathe" filter="url(#ar-f-organ)">${lungs}</g>`;
    const hs = 1 + O.big * .18;
    const heart = `<g transform="translate(470 418) scale(${hs}) rotate(-28)">
      <path d="M-34,-36 C-10,-52 26,-50 40,-26 C54,0 42,40 6,64 C-22,46 -50,10 -46,-12 C-44,-24 -40,-30 -34,-36Z" fill="url(#ar-g-heart)"/>
      <path d="M-18,-46 C-2,-30 6,0 4,58" stroke="#e8c96a" stroke-width="5" fill="none" opacity=".55"/>
      <path d="M-18,-46 C-2,-30 6,0 4,58" stroke="#b81d2a" stroke-width="2.4" fill="none"/>
      <path d="M-44,-14 C-30,6 -10,20 4,58" stroke="#b81d2a" stroke-width="1.8" fill="none" opacity=".8"/>
      ${O.infarct ? `<path class="ar-infarct" d="M6,-6 C22,-4 30,18 22,42 C10,52 -2,38 0,18 C2,6 2,-4 6,-6Z" fill="#3d1630" opacity="${f1(.45 + O.infarct * .45)}"/>` : ''}
      ${F.vessel.plaque > .2 ? '<ellipse cx="-12" cy="-30" rx="3" ry="5" fill="#f4d35e" stroke="#b8901c" stroke-width=".6"/>' : ''}
      </g>`;
    const great = `<path d="M452,386 C448,362 446,344 448,334 C452,318 474,318 478,334 C480,344 476,356 472,366" stroke="#9e1f24" stroke-width="13" fill="none" stroke-linecap="round"/>
      <path d="M452,386 C448,362 446,344 448,334 C452,318 474,318 478,334" stroke="#d9474a" stroke-width="5" fill="none" stroke-linecap="round" transform="translate(-2,-2)"/>
      <path d="M466,392 C470,376 476,364 488,356" stroke="#3f55a8" stroke-width="11" fill="none" stroke-linecap="round"/><path d="M466,392 C470,376 476,364 488,356" stroke="#7d92e0" stroke-width="3.5" fill="none" stroke-linecap="round" transform="translate(-2,-2)"/>`;
    return {stat: d, live: live + `<g class="ar-beat" filter="url(#ar-f-organ)">${g('Heart', 'heart', great + heart)}</g>`};
  }
  function says(F, target) { return F.findings.some(f => f.target === target); }
  function brainGyri() {
    const r = rng(21); let p = '';
    for (let i = 0; i < 26; i++) {
      const x = CX - 50 + r() * 100, y = 54 + r() * 76;
      if (((x - CX) / 56) ** 2 + ((y - 92) / 48) ** 2 > .8) continue;
      p += `<path d="M${f1(x)},${f1(y)} q${f1(6 + r() * 6)},${f1(-6 + r() * 12)} ${f1(12 + r() * 8)},${f1(-2 + r() * 4)} t${f1(10 + r() * 6)},${f1(-2 + r() * 4)}" stroke="#b07f78" stroke-width="1.6" fill="none"/>`;
    }
    return p + `<path d="M${CX},44 V140" stroke="#a46f68" stroke-width="2"/>`;
  }

  function layerBone(F) {
    const B = F.bone;
    let d = `<g fill="#fff" opacity=".05" pointer-events="none">${bodyParts(F)}</g>`;
    const bone = (name, target, inner) => `<g data-name="${esc(name)}" data-target="${target}">${inner}</g>`;
    const P = (path, fill = 'url(#ar-g-bone)') => `<path d="${path}" fill="${fill}"/>`;
    let b = '';
    // skull and face
    b += bone('Skull', 'skull', P(sym([[0, 34], [40, 40], [60, 70], [64, 112], [60, 148], [52, 170], [40, 182], [22, 188], [0, 190]]))
      + [-1, 1].map(s => `<path d="${smooth(side([[10, 116], [36, 112], [46, 128], [38, 146], [12, 144]], s))}" fill="#2a2420"/>`).join('')
      + `<path d="${sym([[0, 146], [8, 152], [10, 172], [0, 174]])}" fill="#2a2420"/>`
      + Array.from({length: 10}, (_, i) => `<rect x="${f1(CX - 24 + i * 4.8)}" y="186" width="4" height="8" rx="1.2" fill="#f7f3ea"/>`).join(''));
    b += bone('Mandible', 'skull', P(sym([[0, 196], [26, 196], [44, 186], [52, 162], [56, 176], [48, 206], [26, 224], [0, 230]])) + Array.from({length: 10}, (_, i) => `<rect x="${f1(CX - 24 + i * 4.8)}" y="196" width="4" height="7" rx="1.2" fill="#f7f3ea"/>`).join(''));
    // spine
    let spine = '';
    for (let i = 0; i < 7; i++) spine += `<rect x="${CX - 10}" y="${206 + i * 8}" width="20" height="6.4" rx="2" fill="url(#ar-g-bone)"/>`;
    for (let i = 0; i < 12; i++) { const y = 264 + i * 19.5, w = 13 + i * .55; spine += `<rect x="${f1(CX - w)}" y="${f1(y)}" width="${f1(w * 2)}" height="15.5" rx="4" fill="url(#ar-g-bone)"/><path d="M${f1(CX - w - 9)},${f1(y + 7)} h${f1(w * 2 + 18)}" stroke="#d9cdb2" stroke-width="5" stroke-linecap="round"/>`; }
    for (let i = 0; i < 5; i++) { const y = 498 + i * 21, w = 21 + i * .8; spine += `<rect x="${f1(CX - w)}" y="${f1(y)}" width="${f1(w * 2)}" height="17" rx="5" fill="url(#ar-g-bone)"/><path d="M${f1(CX - w - 12)},${f1(y + 8)} h${f1(w * 2 + 24)}" stroke="#d9cdb2" stroke-width="6" stroke-linecap="round"/>`; }
    b += bone('Spine (vertebrae)', 'spine', spine);
    // pelvis and sacrum
    b += bone('Pelvis', 'pelvis', [-1, 1].map(s => P(smooth(side([[18, 604], [60, 588], [104, 596], [108, 626], [84, 668], [70, 690], [46, 712], [22, 724], [10, 704], [26, 660]], s)))
      + `<ellipse cx="${X(42, s)}" cy="712" rx="11" ry="15" fill="#2a2420" transform="rotate(${s * 18} ${X(42, s)} 712)"/>`).join('')
      + P(sym([[0, 604], [24, 606], [20, 650], [8, 690], [0, 698]])));
    // ribs, sternum, clavicles, scapulae
    let ribs = '';
    for (let i = 1; i <= 12; i++) {
      const r = ribGeometry(i);
      for (const s of [-1, 1]) {
        ribs += `<path d="${smooth(side([[14, r.yp], [r.wide * .6, r.yp - 12], [r.wide * .97, r.yp + 14]], s), false)}" stroke="#bfb193" stroke-width="5" fill="none" opacity=".55"/>`;
        ribs += `<path d="${smooth(side(r.front, s), false)}" stroke="url(#ar-g-bone)" stroke-width="${i < 3 ? 6.5 : 8}" fill="none" stroke-linecap="round"/>`;
        if (i <= 10) { const end = r.front[r.front.length - 1]; const sy = i <= 7 ? 300 + i * 18 : 300 + 7 * 18 + (i - 7) * 6; ribs += `<path d="${smooth(side([end, [end[0] * .55, end[1] + 4], [i <= 7 ? 12 : end[0] * .3, i <= 7 ? sy : end[1] - 6]], s), false)}" stroke="#cfe0e4" stroke-width="5.5" fill="none" stroke-linecap="round"/>`; }
      }
    }
    b += bone('Ribs', 'rib', ribs);
    b += bone('Sternum', 'rib', P(sym([[0, 284], [14, 286], [12, 312], [9, 316], [10, 420], [4, 450], [0, 456]])));
    b += bone('Clavicles', 'clavicle', [-1, 1].map(s => P(tube(side([[12, 282], [44, 274], [80, 286], [112, 284]], s), [5.5, 4.5, 4.5, 6]))).join(''));
    b += bone('Scapulae', 'shoulder', [-1, 1].map(s => `<path d="${smooth(side([[84, 290], [118, 292], [108, 360], [92, 410], [80, 330]], s))}" fill="#d9cdb2" opacity=".6"/>`).join(''));
    // arms and hands
    for (const s of [-1, 1]) {
      const R = s < 0 ? 'Right' : 'Left';
      b += bone(`${R} humerus`, 'humerus', `<circle cx="${X(122, s)}" cy="304" r="15" fill="url(#ar-g-bone)"/>` + P(tube(side([[124, 312], [138, 380], [152, 450], [164, 500], [170, 520]], s), [10, 8, 7.5, 9, 15])));
      b += bone(`${R} radius`, 'radius', P(tube(side([[176, 528], [186, 600], [198, 670], [210, 708]], s), [5.5, 5, 5.5, 8])));
      b += bone(`${R} ulna`, 'ulna', P(tube(side([[160, 522], [170, 600], [186, 670], [198, 708]], s), [7, 5, 4.5, 5.5])));
      let hand = '';
      for (let i = 0; i < 8; i++) hand += `<circle cx="${f1(X(200 + (i % 4) * 5, s))}" cy="${f1(718 + Math.floor(i / 4) * 9)}" r="4.2" fill="url(#ar-g-bone)"/>`;
      FINGERS.forEach(([o, len]) => {
        hand += P(tube(side([[208 + o * .3, 734], [215 + o * .55, 776]], s), [3.2, 2.8]));
        [[.03, .42], [.47, .74], [.79, .97]].forEach(([a, z]) => { hand += P(tube(side([[215 + o * (.55 + a * .65), 780 + len * a], [216 + o * (.55 + z * .65), 778 + len * z]], s), [2.7, 2.2])); });
      });
      hand += P(tube(side([[220, 728], [232, 752], [240, 774]], s), [3.6, 3.2, 2.6]));
      b += bone(`${R} hand bones`, 'hand', hand);
      // legs and feet
      b += bone(`${R} femur`, 'femur', `<circle cx="${X(56, s)}" cy="694" r="15" fill="url(#ar-g-bone)"/>` + P(tube(side([[62, 698], [88, 706]], s), [8, 10])) + P(tube(side([[84, 712], [76, 800], [64, 880], [54, 940], [52, 952]], s), [11, 9.5, 9, 12, 20])));
      b += bone(`${R} patella`, 'knee', `<ellipse cx="${X(52, s)}" cy="944" rx="11" ry="13" fill="url(#ar-g-bone)"/><path d="${tube(side([[38, 962], [66, 962]], s), [4, 4])}" fill="#cfe0e4"/>`);
      b += bone(`${R} tibia`, 'tibia', P(tube(side([[50, 970], [52, 1040], [48, 1140], [42, 1198]], s), [20, 9, 8.5, 11])));
      b += bone(`${R} fibula`, 'fibula', P(tube(side([[74, 978], [72, 1060], [66, 1150], [64, 1204]], s), [5.5, 4, 3.8, 6])));
      let foot = `<ellipse cx="${X(52, s)}" cy="1214" rx="15" ry="10" fill="url(#ar-g-bone)"/>`;
      for (let i = 0; i < 5; i++) { const o = (i - 2) * 6.5; foot += P(tube(side([[48 + o * .4, 1222], [50 + o * 1.05, 1256]], s), [3.6, 3])); foot += P(tube(side([[50 + o * 1.05, 1259], [51 + o * 1.12, 1274]], s), [3, 2.4])); }
      b += bone(`${R} foot bones`, 'foot', foot);
    }
    d += `<g filter="url(#ar-f-bone)">${b}</g>`;
    // values on the bones
    let fx = '', stat = '';
    if (B.osteo) stat += `<g opacity="${f1(.3 + B.osteo * .5)}" pointer-events="none"><rect x="${CX - 26}" y="262" width="52" height="350" fill="url(#ar-porous)"/>${[-1, 1].map(s => `<path d="${tube(side([[56, 694], [84, 712], [76, 800]], s), [15, 10, 9])}" fill="url(#ar-porous)"/>`).join('')}</g>`;
    if (B.marrow) fx += [-1, 1].map(s => `<path class="ar-glow" d="${smooth(side([[80, 730], [74, 800], [64, 880]], s), false)}" stroke="#ff4d6d" stroke-width="6" fill="none" opacity=".6"/>`).join('') + `<path class="ar-glow" d="M${CX},300 V440" stroke="#ff4d6d" stroke-width="5" opacity=".55"/>`;
    if (B.gout) fx += [-1, 1].map(s => `<g class="ar-glow">${Array.from({length: 7}, (_, i) => `<path d="M${f1(X(37, s) + (i - 3) * 2.4)},${1258 + (i % 3) * 2} l1.5,-5 l1.5,5z" fill="#fffbe0" stroke="#e9c84a" stroke-width=".5"/>`).join('')}</g>`).join('');
    if (B.arthritis) fx += [-1, 1].map(s => `<circle class="ar-glow" cx="${X(52, s)}" cy="955" r="20" fill="url(#ar-g-warn)"/>${[-15, -5, 5, 14].map(o => `<circle class="ar-glow" cx="${f1(X(214 + o * .45, s))}" cy="${f1(780)}" r="6" fill="url(#ar-g-warn)"/>`).join('')}`).join('');
    B.fractures.forEach(fr => {
      const s = fr.side === 'left' ? 1 : -1, [x, y] = boneAnchor(fr.bone, s);
      fx += `<g class="ar-fracture"><circle cx="${f1(x)}" cy="${f1(y)}" r="22" fill="url(#ar-g-hot)" class="ar-glow"/><path d="M${f1(x - 13)},${f1(y - 3)} l6,4 l5,-6 l5,7 l5,-5 l5,4" stroke="#2a0a0a" stroke-width="2.4" fill="none"/><path d="M${f1(x - 13)},${f1(y - 3)} l6,4 l5,-6 l5,7 l5,-5 l5,4" stroke="#ff4d4d" stroke-width="1" fill="none"/></g>`;
    });
    return {stat: d + stat, live: fx};
  }
  function skinRegion(x, y) {
    const dx = Math.abs(x - CX), sideName = x < CX ? 'right' : 'left';      // the patient's right is on the viewer's left
    if (y < 205) return 'Skin of the face and scalp';
    if (y < 262 && dx < 50) return 'Skin of the neck';
    if (dx > 120 && y < 712) return `Skin of the ${sideName} arm`;
    if (dx > 150) return `Skin of the ${sideName} hand`;
    if (y < 470) return 'Skin of the chest';
    if (y < 600) return 'Skin of the abdomen';
    if (y < 760) return 'Skin of the hips and groin';
    if (y < 965) return `Skin of the ${sideName} thigh`;
    if (y < 1200) return `Skin of the ${sideName} lower leg`;
    return `Skin of the ${sideName} foot`;
  }
  function boneAnchor(bone, s) {
    const A = {femur: [72, 820], tibia: [50, 1090], fibula: [70, 1090], radius: [192, 620], ulna: [178, 620], humerus: [150, 420], clavicle: [60, 282], rib: [98, 440],
      pelvis: [72, 630], ankle: [46, 1205], hand: [214, 790], foot: [50, 1255], toe: [37, 1262], knee: [52, 955], marrow: [70, 820], shoulder: [122, 304]};
    if (bone === 'skull') return [CX, 70];
    if (bone === 'spine') return [CX, 470];
    const a = A[bone] || [CX - CX, 600];
    return [X(a[0], s), a[1]];
  }

  /* ================================================================== 5 · where each finding points */
  function anchor(f) {
    const T = {
      skin: {face: [CX, 150], lips: [CX, 193], ankles: [X(46, -1), 1185], legs: [X(52, -1), 1090]},
      muscle: {thigh: [X(84, -1), 810], forearm: [X(184, -1), 600]},
      vessel: {aorta: [442, 520], carotid: [X(22, -1), 226], blood: [X(53, 1), 790], 'calf-vein': [X(41, -1), 1032]},
      organ: {heart: [470, 420], lungs: [X(62, -1), 430], liver: [X(50, -1), 500], kidneys: [X(88, 1), 544], pancreas: [X(30, 1), 536], spleen: [X(98, 1), 480],
        thyroid: [CX, 262], brain: [CX, 92], bladder: [CX, 710], prostate: [CX, 732], uterus: [CX, 684], stomach: [X(56, 1), 520], gut: [CX, 630]},
    };
    if (f.layer === 'bone') return boneAnchor(f.target, f.side === 'left' ? 1 : -1);
    return (T[f.layer] || {})[f.target] || [CX, 600];
  }
  const SYSTEMS = {heart: ['heart'], lungs: ['lungs'], liver: ['liver'], kidneys: ['kidneys'], pancreas: ['pancreas'], spleen: ['immune', 'blood'], thyroid: ['thyroid'],
    brain: ['brain'], bladder: ['bladder'], prostate: ['reproductive'], uterus: ['reproductive'], blood: ['blood', 'immune'], aorta: ['blood'], carotid: ['blood'], 'calf-vein': ['blood']};
  const LV = {3: 'urgent', 2: 'abnormal', 1: 'note'};

  /* ================================================================== 6 · the interactive figure */
  function mount(root, D) {
    const F = findings(D);
    const skin = skinColour(F);
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const content = {skin: layerSkin(F, skin), muscle: layerMuscle(F), vessel: layerVessel(F), organ: layerOrgan(F), bone: layerBone(F)};
    const byLayer = k => F.findings.filter(f => f.layer === k);
    const hot = k => { const seen = new Set(); return byLayer(k).filter(f => !seen.has(f.target) && seen.add(f.target)).map(f => { const [x, y] = anchor(f); return `<circle class="ar-glow" cx="${f1(x)}" cy="${f1(y)}" r="${f.level >= 3 ? 34 : 26}" fill="url(#ar-g-${f.level >= 3 ? 'hot' : 'warn'})" pointer-events="none"/>`; }).join(''); };
    root.innerHTML = `<div class="ar-wrap" style="--ar-beat:${f1(60 / clamp(F.hr, 30, 200))}s;--ar-breath:${f1(60 / clamp(F.rr, 6, 50))}s">
      <div class="ar-stage">
        <div class="ar-tools">
          <div class="ar-toolset" role="group" aria-label="Tool">
            <button type="button" data-tool="peel" class="on" title="Click the body: the outer layer peels away from where you click"><i class="bi bi-scissors"></i>Peel</button>
            <button type="button" data-tool="window" title="Click to cut a small window through the outer layer"><i class="bi bi-circle"></i>Window</button>
            <button type="button" data-tool="lens" title="Move over the body to see through it"><i class="bi bi-binoculars"></i>X-ray lens</button>
            <button type="button" data-tool="inspect" title="Click a structure to see its name and the results that belong to it"><i class="bi bi-hand-index"></i>Inspect</button>
          </div>
          <select class="ar-lensdepth form-select form-select-sm" hidden aria-label="See through to">${LAYERS.slice(1).map(l => `<option value="${l.key}" ${l.key === 'bone' ? 'selected' : ''}>to ${l.label.toLowerCase()}</option>`).join('')}</select>
          <label class="ar-depth"><span>Depth</span><input type="range" min="0" max="4" step="1" value="0" aria-label="How deep to dissect"><b>Skin</b></label>
          <button type="button" class="ar-btn" data-act="dissect"><i class="bi bi-play-fill"></i>Dissect</button>
          <button type="button" class="ar-btn" data-act="reset"><i class="bi bi-arrow-counterclockwise"></i>Reset</button>
          <button type="button" class="ar-btn" data-act="whole" hidden><i class="bi bi-zoom-out"></i>Whole body</button>
        </div>
        <svg class="ar-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Layered anatomy of ${esc((D.patient || {}).name || 'the patient')}, coloured by the results" preserveAspectRatio="xMidYMid meet">
          ${defs(F, skin)}
          <ellipse cx="${CX}" cy="1282" rx="150" ry="16" fill="#000" opacity=".35" filter="url(#ar-blur14)"/>
          <g class="ar-layers">${LAYERS.slice().reverse().map(l => `<g class="ar-layer" data-layer="${l.key}" clip-path="url(#ar-l-${l.key})"><g clip-path="url(#ar-h-${l.key})"><g ${l.key === 'skin' ? '' : 'clip-path="url(#ar-body-clip)"'}>
            <image class="ar-raster" x="0" y="0" width="${W}" height="${H}" preserveAspectRatio="none"/><g class="ar-vec">${content[l.key].stat}</g>
            <g class="ar-live">${content[l.key].live}</g><g class="ar-hotspots">${hot(l.key)}</g></g></g></g>`).join('')}</g>
          <g class="ar-peelfx" clip-path="url(#ar-body-clip)" pointer-events="none"></g>
          <g class="ar-sel" pointer-events="none"></g>
          <g class="ar-lensfx" pointer-events="none"></g>
          <g class="ar-callouts"></g>
        </svg>
        <div class="ar-tip" hidden></div>
        <p class="ar-hint"><i class="bi bi-info-circle me-1"></i>Click the body to peel away a layer · drag the depth slider · hover to name a structure. Drawn from the results; an explanation aid, not a diagnosis.</p>
      </div>
      <aside class="ar-side">
        <div class="ar-stack"></div>
        <div class="ar-detail" aria-live="polite"></div>
        <div class="ar-list"></div>
      </aside></div>`;
    const svg = root.querySelector('.ar-svg'), tip = root.querySelector('.ar-tip');
    const defsText = defs(F, skin), urls = [];
    LAYERS.forEach((l, i) => {
      const doc = `<svg xmlns="${NS}" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${defsText}${content[l.key].stat}</svg>`;
      const url = URL.createObjectURL(new Blob([doc], {type: 'image/svg+xml'}));
      urls.push(url);
      const img = new Image();
      img.onload = () => {
        // paint the lit layer once into a plain bitmap (an SVG image would re-run its lighting filters on every repaint)
        const k = RASTER, c = document.createElement('canvas');
        c.width = W * k; c.height = H * k;
        const done = href => {
          const g = svg.querySelector(`.ar-layer[data-layer="${l.key}"]`);
          g.querySelector('.ar-raster').setAttribute('href', href);
          g.querySelector('.ar-vec').classList.add('ar-hit');          // shapes stay for hit-testing, painted by the image
        };
        try {
          c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
          c.toBlob(b => { if (!b) return done(url); const u2 = URL.createObjectURL(b); urls.push(u2); done(u2); }, 'image/png');
        } catch (e) { done(url); }
      };
      setTimeout(() => { img.src = url; }, i * 30);
    });
    const layerEl = k => svg.querySelector(`.ar-layer[data-layer="${k}"]`);
    const S = {tool: 'peel', peeled: new Set(), hidden: new Set(), holes: Object.fromEntries(LAYERS.map(l => [l.key, []])), lens: null, lensDepth: 'bone', sel: null, vb: [0, 0, W, H], busy: 0};
    const idx = k => LAYERS.findIndex(l => l.key === k);
    const FULL = 1700;

    /* ---- masks, holes and the peeled edge */
    function holePath(h) {
      const r = h.r, pts = [];
      for (let i = 0; i < 56; i++) {
        const a = i / 56 * Math.PI * 2;
        const rr = r * (1 + .07 * Math.sin(a * 5 + h.seed) + .04 * Math.sin(a * 11 + h.seed * 2) + (h.window ? 0 : .05 * Math.sin(a * 3 + h.seed * 3)));
        pts.push([h.x + Math.cos(a) * rr, h.y + Math.sin(a) * rr]);
      }
      return smooth(pts, true, .5);
    }
    const exposed = k => {
      const i = idx(k);
      if (S.peeled.has(k) || S.hidden.has(k)) return false;
      const above = LAYERS.slice(0, i);
      return above.every(l => S.peeled.has(l.key) || S.hidden.has(l.key)) || above.some(l => S.holes[l.key].length) || (!!S.lens && i <= idx(S.lensDepth));
    };
    function render(light) {
      const OUT = `M-200,-200H${W + 200}V${H + 200}H-200Z`;
      const put = (el, attr, v) => { if (el.__v !== v) { el.__v = v; if (attr === 'class') el.classList.toggle('ar-still', v); else if (attr === 'display') el.style.display = v; else el.setAttribute(attr, v); } };
      LAYERS.forEach((l, i) => {            // only touch what changed, so untouched layers are not repainted
        const g = layerEl(l.key);
        put(g, 'class', !exposed(l.key));
        put(g.firstElementChild, 'display', S.peeled.has(l.key) || S.hidden.has(l.key) ? 'none' : '');
        put(svg.querySelector(`#ar-h-${l.key} .ar-holes`), 'd', OUT + S.holes[l.key].filter(h => h.r > .5).map(holePath).join(''));
        const on = S.lens && i < idx(S.lensDepth);
        put(svg.querySelector(`#ar-l-${l.key} .ar-lens-hole`), 'd', OUT + (on ? holePath({x: S.lens.x, y: S.lens.y, r: S.lens.r, seed: 0, window: true}) : ''));
      });
      // the peeled edge: a rolled flap of the layer and a shadow on the layer beneath
      let fx = '';
      LAYERS.forEach(l => S.holes[l.key].forEach(h => {
        if (!h.r) return;
        const p = holePath(h), col = l.key === 'skin' ? skin : l.flap;
        const roll = h.window ? 5 : Math.max(3, 14 * (1 - h.t));
        fx += `<path d="${p}" fill="none" stroke="#000" stroke-width="${f1(roll * 3.2)}" opacity=".12"/><path d="${p}" fill="none" stroke="#000" stroke-width="${f1(roll * 2)}" opacity=".16"/>
          <path d="${p}" fill="none" stroke="${mix(col, '#000', .35)}" stroke-width="${f1(roll + 2)}"/>
          <path d="${p}" fill="none" stroke="${col}" stroke-width="${f1(roll)}"/>
          <path d="${p}" fill="none" stroke="${mix(col, '#fff', .45)}" stroke-width="${f1(Math.max(1, roll * .3))}" transform="translate(-1.2,-1.2)"/>`;
      }));
      const pf = svg.querySelector('.ar-peelfx');
      if (pf.__v !== fx) { pf.__v = fx; pf.innerHTML = fx; }
      if (light) return;
      svg.querySelector('.ar-lensfx').innerHTML = S.lens ? `<circle cx="${f1(S.lens.x)}" cy="${f1(S.lens.y)}" r="${S.lens.r}" fill="url(#ar-g-lens)" stroke="#7fe7ff" stroke-width="2"/>
        <path d="M${f1(S.lens.x - 8)},${f1(S.lens.y)} h16 M${f1(S.lens.x)},${f1(S.lens.y - 8)} v16" stroke="#7fe7ff" stroke-width="1.4"/>
        <text x="${f1(S.lens.x)}" y="${f1(S.lens.y + S.lens.r + 18)}" text-anchor="middle" class="ar-lenslabel">X-ray · ${LAYERS[idx(S.lensDepth)].label}</text>` : '';
      renderStack(); renderCallouts();
    }
    /* ---- peel animations */
    let raf = 0;
    const ease = t => t < .5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
    function tick(now) {
      let alive = false;
      LAYERS.forEach(l => {
        S.holes[l.key] = S.holes[l.key].filter(h => {
          if (!h.anim) return true;
          const t = clamp((now - h.t0) / h.dur, 0, 1); h.t = t;
          h.r = h.restore ? h.R * (1 - ease(t)) : (h.grow || 0) + (h.R - (h.grow || 0)) * ease(t);
          if (t < 1) { alive = true; return true; }
          h.anim = false;
          if (h.restore) return false;
          if (!h.window) { S.peeled.add(l.key); return false; }
          h.t = 1; h.grow = 0; return true;
        });
      });
      render(alive);
      raf = alive ? requestAnimationFrame(tick) : 0;
      if (!alive) S.busy = 0;
    }
    const run = () => { if (!raf) raf = requestAnimationFrame(tick); };
    function peel(k, x = CX, y = 420, delay = 0) {
      if (S.peeled.has(k)) return;
      S.busy = 1;
      S.holes[k] = [{x, y, r: 0, R: FULL, seed: Math.random() * 6, t0: performance.now() + delay, dur: reduce ? 1 : 1150, anim: true}];
      run();
    }
    function restore(k, delay = 0) {
      if (!S.peeled.has(k)) return;
      S.peeled.delete(k);
      S.holes[k] = [{x: CX, y: 420, r: FULL, R: FULL, seed: 1, t0: performance.now() + delay, dur: reduce ? 1 : 900, anim: true, restore: true}];
      run();
    }
    function cutWindow(k, x, y) {
      const near = S.holes[k].find(h => h.window && Math.hypot(h.x - x, h.y - y) < h.R + 74);
      if (near) {                                   // grow the existing window to cover both instead of overlapping
        const d = Math.hypot(near.x - x, near.y - y), R = (d + near.R + 74) / 2, t = d ? (R - near.R) / d : 0;
        Object.assign(near, {x: near.x + (x - near.x) * t, y: near.y + (y - near.y) * t, R, r: near.r, t0: performance.now(), dur: reduce ? 1 : 420, anim: true, grow: near.r});
        run(); return;
      }
      S.holes[k].push({x, y, r: 0, R: 74, seed: Math.random() * 6, t0: performance.now(), dur: reduce ? 1 : 520, anim: true, window: true});
      run();
    }
    function setDepth(n, from) {
      LAYERS.forEach((l, i) => {
        if (i < n && !S.peeled.has(l.key)) peel(l.key, from ? from[0] : CX, from ? from[1] : 420, (i - (n - 1)) < 0 ? i * 260 : 0);
        if (i >= n && S.peeled.has(l.key)) restore(l.key, (n - i) * 120 + 400);
        if (i >= n) S.holes[l.key] = S.holes[l.key].filter(h => h.restore);
      });
      S.hidden.clear();
      root.querySelector('.ar-depth input').value = n;
      root.querySelector('.ar-depth b').textContent = LAYERS[n].label;
      render();
    }
    const depthNow = () => { let n = 0; while (n < 4 && (S.peeled.has(LAYERS[n].key) || S.hidden.has(LAYERS[n].key))) n++; return n; };

    /* ---- what is under the pointer? */
    const pt = ev => { const p = svg.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); };
    function layerVisibleAt(k, x, y) {
      if (S.peeled.has(k) || S.hidden.has(k)) return false;
      if (S.holes[k].some(h => Math.hypot(x - h.x, y - h.y) < h.r * .93)) return false;
      if (S.lens && idx(k) < idx(S.lensDepth) && Math.hypot(x - S.lens.x, y - S.lens.y) < S.lens.r) return false;
      return true;
    }
    function hit(ev) {
      const p = pt(ev), els = document.elementsFromPoint(ev.clientX, ev.clientY);
      for (const l of LAYERS) {
        if (!layerVisibleAt(l.key, p.x, p.y)) continue;
        const el = els.find(e => e.closest && e.closest('[data-name]') && e.closest('.ar-layer') === layerEl(l.key));
        if (el) {
          const g = el.closest('[data-name]');
          const name = l.key === 'skin' ? skinRegion(p.x, p.y) : g.dataset.name;
          return {layer: l.key, name, target: g.dataset.target, x: p.x, y: p.y};
        }
      }
      return null;
    }
    /* ---- side panel */
    function renderStack() {
      const top = depthNow();
      root.querySelector('.ar-stack').innerHTML = `<h3>Layers <span>click a layer to dissect down to it</span></h3>` + LAYERS.map((l, i) => {
        const fs = byLayer(l.key), worst = Math.max(0, ...fs.map(f => f.level));
        const state = S.peeled.has(l.key) ? 'peeled' : S.hidden.has(l.key) ? 'hidden' : i === top ? 'top' : 'below';
        return `<div class="ar-row ${state}" data-depth="${i}">
          <button type="button" class="ar-row-main" data-depth="${i}"><i class="bi ${l.icon}"></i><span><b>${l.label}</b><small>${fs.length ? fs.slice(0, 2).map(f => esc(f.title)).join(' · ') + (fs.length > 2 ? ` · +${fs.length - 2}` : '') : 'Nothing abnormal recorded'}</small></span>
            ${fs.length ? `<em class="lv${worst}">${fs.length}</em>` : ''}</button>
          <button type="button" class="ar-eye" data-eye="${l.key}" aria-label="${S.hidden.has(l.key) ? 'Show' : 'Hide'} ${l.label}" title="${S.hidden.has(l.key) ? 'Show' : 'Hide'}"><i class="bi ${S.hidden.has(l.key) || S.peeled.has(l.key) ? 'bi-eye-slash' : 'bi-eye'}"></i></button></div>`;
      }).join('');
    }
    function related(f) {
      const codes = new Set(F.findings.filter(x => x.layer === f.layer && x.target === f.target).flatMap(x => x.codes));
      const sys = SYSTEMS[f.target] || [];
      return (D.params || []).filter(p => p.latest && (codes.has(p.code) || sys.includes(p.system)))
        .sort((a, b) => (LEVEL[b.latest.flag] || 0) - (LEVEL[a.latest.flag] || 0)).slice(0, 8);
    }
    function spark(p) {
      const h = (p.history || []).filter(x => typeof x.num === 'number').slice(-8);
      if (h.length < 2) return '';
      const ys = h.map(x => x.num), lo = Math.min(...ys, p.lo ?? Infinity), hi2 = Math.max(...ys, p.hi ?? -Infinity), span = hi2 - lo || 1;
      const pts = h.map((x, i) => `${f1(i / (h.length - 1) * 70)},${f1(18 - (x.num - lo) / span * 16)}`).join(' ');
      return `<svg viewBox="0 0 70 20" class="ar-spark"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>`;
    }
    function select(info, zoom) {
      S.sel = info;
      const fs = F.findings.filter(f => f.layer === info.layer && f.target === info.target);
      const rel = related({layer: info.layer, target: info.target});
      const lay = LAYERS[idx(info.layer)];
      root.querySelector('.ar-detail').innerHTML = `<div class="ar-card">
        <div class="ar-card-h"><i class="bi ${lay.icon}"></i><div><b>${esc(info.name)}</b><small>${lay.label}</small></div><button type="button" class="ar-x" aria-label="Close">×</button></div>
        ${fs.length ? fs.map(f => `<div class="ar-find lv${f.level}"><b>${esc(f.title)}</b><span>${esc(f.text)}</span></div>`).join('') : '<p class="ar-ok"><i class="bi bi-check-circle"></i>Nothing abnormal recorded here.</p>'}
        ${rel.length ? `<div class="ar-vals">${rel.map(p => `<div class="ar-val f-${esc(p.latest.flag || 'N')}"><span>${esc(p.name)}</span><b>${esc(p.latest.display)} <small>${esc(p.unit || '')}</small></b>${spark(p)}<small>ref ${esc(p.range || '—')}</small></div>`).join('')}</div>` : ''}
        <div class="ar-card-a">${zoom !== false ? '<button type="button" class="ar-btn" data-act="zoomsel"><i class="bi bi-zoom-in"></i>Look closer</button>' : ''}
          ${window.LabInsightsAsk || (window.DrFlow && window.DrFlow.ask) ? '<button type="button" class="ar-btn" data-act="askflow"><i class="bi bi-robot"></i>Ask Dr. Flow</button>' : ''}</div></div>`;
      // outline the structure
      const els = [...layerEl(info.layer).querySelectorAll(`[data-target="${CSS.escape(info.target)}"]`)].filter(e => !info.name || e.dataset.name === info.name || fs.length);
      let bb = null;
      els.forEach(e => { try { const b = e.getBBox(); if (b.width && b.height) bb = bb ? {x: Math.min(bb.x, b.x), y: Math.min(bb.y, b.y), x2: Math.max(bb.x2, b.x + b.width), y2: Math.max(bb.y2, b.y + b.height)} : {x: b.x, y: b.y, x2: b.x + b.width, y2: b.y + b.height}; } catch (e2) { /* hidden */ } });
      if (!bb) { const [ax, ay] = anchor({layer: info.layer, target: info.target, side: info.side}); bb = {x: ax - 30, y: ay - 30, x2: ax + 30, y2: ay + 30}; }
      S.selBox = bb;
      svg.querySelector('.ar-sel').innerHTML = `<rect x="${f1(bb.x - 8)}" y="${f1(bb.y - 8)}" width="${f1(bb.x2 - bb.x + 16)}" height="${f1(bb.y2 - bb.y + 16)}" rx="14" fill="none" stroke="#7fe7ff" stroke-width="2" stroke-dasharray="6 5"/>`;
      if (zoom) zoomTo(bb);
    }
    function renderList() {
      root.querySelector('.ar-list').innerHTML = F.findings.length ? `<h3>What the results show <span>${F.findings.length}</span></h3>` + F.findings.map((f, i) => `<button type="button" class="ar-li lv${f.level}" data-find="${i}"><i class="bi ${LAYERS[idx(f.layer)].icon}"></i><span><b>${esc(f.title)}</b><small>${esc(f.text)}</small></span></button>`).join('')
        : '<p class="ar-ok"><i class="bi bi-check-circle"></i>No abnormal findings to show. The body is drawn as healthy.</p>';
    }
    function openFinding(f) {
      setDepth(idx(f.layer));
      const name = (layerEl(f.layer).querySelector(`[data-target="${CSS.escape(f.target)}"]`) || {dataset: {}}).dataset.name || f.title;
      setTimeout(() => select({layer: f.layer, target: f.target, name, side: f.side}, true), reduce ? 0 : 700);
    }
    /* ---- callouts like an anatomy atlas */
    let calloutData = null;
    function renderCallouts() {
      if (!calloutData) {
        const seen = new Set();
        const pick = F.findings.filter(f => { const k = f.layer + f.target + (f.side || ''); if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 12);
        const L = [], R = [];
        pick.forEach(f => { const [x, y] = anchor(f); (x < CX ? L : R).push({f, x, y}); });
        const place = (arr) => { arr.sort((a, b) => a.y - b.y); let last = -1e9; arr.forEach(c => { c.ly = Math.max(c.y, last + 66); last = c.ly; }); const over = last - (H - 40); if (over > 0) arr.forEach(c => { c.ly -= over; }); };
        place(L); place(R);
        calloutData = [...L.map(c => ({...c, lx: 16, side: 'L'})), ...R.map(c => ({...c, lx: W - 16, side: 'R'}))];
      }
      svg.querySelector('.ar-callouts').innerHTML = calloutData.map((c, i) => {
        const covered = !layerVisibleAt(c.f.layer, c.x, c.y) || LAYERS.slice(0, idx(c.f.layer)).some(l => layerVisibleAt(l.key, c.x, c.y));
        const col = c.f.level >= 3 ? '#ff5a5f' : '#ffb02e', BW = 200, tx = c.side === 'L' ? c.lx : c.lx - BW, ex = c.side === 'L' ? c.lx + BW : c.lx - BW;
        const val = (c.f.text.split(':')[0] || '').slice(0, 26);
        return `<g class="ar-co ${covered ? 'covered' : ''}" data-co="${i}" tabindex="0" role="button" aria-label="${esc(c.f.title)}">
          <path d="M${f1(c.x)},${f1(c.y)} L${f1((c.x + ex) / 2)},${f1(c.ly)} L${f1(ex)},${f1(c.ly)}" stroke="${col}" stroke-width="1.6" fill="none" opacity=".9"/>
          <circle cx="${f1(c.x)}" cy="${f1(c.y)}" r="5" fill="${col}" stroke="#fff" stroke-width="1.6"/>
          <rect x="${f1(tx)}" y="${f1(c.ly - 27)}" width="${BW}" height="54" rx="11" fill="rgba(10,22,34,.84)" stroke="${col}" stroke-width="1.4"/>
          <text x="${f1(tx + 12)}" y="${f1(c.ly - 6)}" class="ar-co-t">${esc(c.f.title.length > 24 ? c.f.title.slice(0, 23) + '…' : c.f.title)}</text>
          <text x="${f1(tx + 12)}" y="${f1(c.ly + 15)}" class="ar-co-v">${covered ? '<tspan class="ar-co-r">⤵ </tspan>' : ''}${esc(val)}</text></g>`;
      }).join('');
    }
    /* ---- zoom */
    function zoomTo(bb) {
      let w = Math.max(220, (bb.x2 - bb.x) * 2.4), h = Math.max(260, (bb.y2 - bb.y) * 2.4);
      if (w / h > W / H) h = w * H / W; else w = h * W / H;
      const cx = (bb.x + bb.x2) / 2, cy = (bb.y + bb.y2) / 2;
      animateVB([clamp(cx - w / 2, -100, W - w + 100), clamp(cy - h / 2, -50, H - h + 50), w, h]);
      root.querySelector('[data-act="whole"]').hidden = false;
      svg.querySelector('.ar-callouts').style.display = 'none';
    }
    function animateVB(to) {
      const from = S.vb.slice(), t0 = performance.now(), dur = reduce ? 1 : 650;
      const step = now => { const t = ease(clamp((now - t0) / dur, 0, 1)); S.vb = from.map((v, i) => v + (to[i] - v) * t); svg.setAttribute('viewBox', S.vb.map(f1).join(' ')); if (t < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    }

    /* ---- events */
    root.querySelector('.ar-tools').addEventListener('click', ev => {
      const b = ev.target.closest('button'); if (!b) return;
      if (b.dataset.tool) {
        S.tool = b.dataset.tool;
        root.querySelectorAll('[data-tool]').forEach(x => x.classList.toggle('on', x === b));
        root.querySelector('.ar-lensdepth').hidden = S.tool !== 'lens';
        svg.dataset.tool = S.tool;
        if (S.tool !== 'lens') { S.lens = null; render(); }
      }
      if (b.dataset.act === 'reset') { LAYERS.forEach(l => { S.holes[l.key] = []; }); S.peeled.clear(); S.hidden.clear(); S.lens = null; svg.querySelector('.ar-sel').innerHTML = ''; animateVB([0, 0, W, H]); root.querySelector('[data-act="whole"]').hidden = true; svg.querySelector('.ar-callouts').style.display = ''; setDepth(0); }
      if (b.dataset.act === 'whole') { animateVB([0, 0, W, H]); b.hidden = true; svg.querySelector('.ar-callouts').style.display = ''; }
      if (b.dataset.act === 'dissect') {
        let n = 0; b.disabled = true;
        const next = () => { n++; if (n <= 4) { setDepth(n); setTimeout(next, reduce ? 300 : 1700); } else setTimeout(() => { setDepth(0); b.disabled = false; }, 2200); };
        setDepth(0); setTimeout(next, 500);
      }
    });
    root.querySelector('.ar-lensdepth').addEventListener('change', ev => { S.lensDepth = ev.target.value; render(); });
    root.querySelector('.ar-depth input').addEventListener('input', ev => setDepth(+ev.target.value));
    root.querySelector('.ar-side').addEventListener('click', ev => {
      const eye = ev.target.closest('[data-eye]');
      if (eye) { const k = eye.dataset.eye; if (S.peeled.has(k)) { restore(k); } else if (S.hidden.has(k)) S.hidden.delete(k); else S.hidden.add(k); render(); return; }
      const row = ev.target.closest('.ar-row-main'); if (row) { setDepth(+row.dataset.depth); return; }
      const li = ev.target.closest('[data-find]'); if (li) { openFinding(F.findings[+li.dataset.find]); return; }
      if (ev.target.closest('.ar-x')) { root.querySelector('.ar-detail').innerHTML = ''; svg.querySelector('.ar-sel').innerHTML = ''; S.sel = null; return; }
      const act = ev.target.closest('[data-act]');
      if (act && act.dataset.act === 'zoomsel' && S.selBox) zoomTo(S.selBox);
      if (act && act.dataset.act === 'askflow' && S.sel) {
        const fs = F.findings.filter(f => f.layer === S.sel.layer && f.target === S.sel.target);
        const q = `${S.sel.name}: ${fs.length ? fs.map(f => f.text).join(' ') : 'no abnormal result here'}. What does this mean for the patient and what should be checked next?`;
        if (window.LabInsightsAsk) window.LabInsightsAsk(q); else window.DrFlow.ask({kind: 'free', question: q});
      }
    });
    svg.addEventListener('click', ev => {
      const co = ev.target.closest('.ar-co'); if (co) { openFinding(calloutData[+co.dataset.co].f); return; }
      const h = hit(ev); if (!h) return;
      const p = pt(ev);
      if (S.tool === 'peel') {
        if (h.layer === 'bone') { select(h, false); return; }
        peel(h.layer, p.x, p.y);
        setTimeout(() => { const n = depthNow(); root.querySelector('.ar-depth input').value = n; root.querySelector('.ar-depth b').textContent = LAYERS[n].label; }, reduce ? 0 : 1200);
      } else if (S.tool === 'window') { if (h.layer !== 'bone') cutWindow(h.layer, p.x, p.y); }
      else select(h, false);
    });
    svg.addEventListener('keydown', ev => { const co = ev.target.closest && ev.target.closest('.ar-co'); if (co && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); openFinding(calloutData[+co.dataset.co].f); } });
    let hovRaf = 0;
    svg.addEventListener('pointermove', ev => {
      if (hovRaf) return;
      hovRaf = requestAnimationFrame(() => {
        hovRaf = 0;
        if (S.tool === 'lens') { const p = pt(ev); S.lens = {x: p.x, y: p.y, r: 95}; render(true); }
        const h = hit(ev);
        if (!h || ev.target.closest('.ar-co')) { tip.hidden = true; svg.style.cursor = ''; return; }
        const f = F.findings.find(x => x.layer === h.layer && x.target === h.target);
        tip.innerHTML = `<b>${esc(h.name)}</b><span>${LAYERS[idx(h.layer)].label}${f ? ` · <em class="lv${f.level}">${esc(f.title)}</em>` : ''}</span>`;
        const r = root.querySelector('.ar-stage').getBoundingClientRect();
        tip.style.left = `${ev.clientX - r.left + 16}px`; tip.style.top = `${ev.clientY - r.top + 12}px`; tip.hidden = false;
        svg.style.cursor = S.tool === 'peel' && h.layer !== 'bone' ? 'crosshair' : S.tool === 'window' ? 'cell' : 'pointer';
      });
    });
    svg.addEventListener('pointerleave', () => { tip.hidden = true; if (S.tool === 'lens') { S.lens = null; render(); } });

    /* ---- the living body: blood cells, twitching muscles */
    const cellsG = svg.querySelector('.ar-cells');
    const tracks = [...layerEl('vessel').querySelectorAll('.ar-pulse')].map(p => ({p, len: p.getTotalLength(), dir: 1}))
      .concat([...layerEl('vessel').querySelectorAll('.ar-v-v')].map(g => { const p = g.querySelectorAll('path')[1]; return {p, len: p.getTotalLength(), dir: -1}; }));
    const V = F.vessel, cells = [];
    const kinds = ['rbc', 'rbc', 'rbc', 'rbc', 'rbc'];
    if (V.white === 'high') kinds.push('wbc', 'wbc'); else if (V.white !== 'low') kinds.push('wbc');
    if (V.malaria) kinds.push('para', 'para', 'para');
    if (V.sickle) kinds.push('sick', 'sick');
    if (V.sugar > .05) kinds.push('sug', 'sug');
    const rbc = mix('#d8202c', '#e8a0a0', V.anaemia * .6);
    const shape = k => k === 'wbc' ? '<circle r="3.6" fill="#f4f1ff" stroke="#b9a6e8" stroke-width=".8"/><circle r="1.6" fill="#7a5bc8"/>'
      : k === 'para' ? `<ellipse rx="3.2" ry="2.2" fill="${rbc}"/><circle r="1.2" fill="none" stroke="#5b2a86" stroke-width=".8"/>`
      : k === 'sick' ? `<path d="M-3.5,1 Q0,-3 3.5,1 Q0,-1 -3.5,1Z" fill="${rbc}"/>`
      : k === 'sug' ? '<path d="M0,-2.2 L1.4,0 L0,2.2 L-1.4,0Z" fill="#fff" opacity=".9"/>'
      : `<ellipse rx="3" ry="2" fill="${rbc}"/><ellipse rx="1.3" ry=".8" fill="#000" opacity=".2"/>`;
    const r0 = rng(77);
    if (tracks.length) for (let i = 0; i < (reduce ? 0 : 70); i++) {
      const tr = tracks[i % tracks.length], k = kinds[Math.floor(r0() * kinds.length)];
      const el = document.createElementNS(NS, 'g'); el.innerHTML = shape(k); cellsG.appendChild(el);
      cells.push({el, tr, u: r0(), sp: (.06 + r0() * .05) * clamp(F.hr / 72, .5, 2.2) * (tr.dir < 0 ? .55 : 1)});
    }
    const twitch = [...svg.querySelectorAll('.ar-twitch')];
    let last = performance.now(), alive = true;
    const loop = now => {
      if (!alive) return;
      const dt = Math.min(.05, (now - last) / 1000); last = now;
      if (root.offsetParent !== null && !document.hidden) {
        root.classList.remove('ar-paused');
        if (exposed('vessel')) cells.forEach(c => {
          c.u = (c.u + c.sp * dt * 300 / c.tr.len) % 1;
          const at = c.tr.dir > 0 ? c.u : 1 - c.u, q = c.tr.p.getPointAtLength(at * c.tr.len), q2 = c.tr.p.getPointAtLength(Math.min(c.tr.len, at * c.tr.len + 2));
          c.el.setAttribute('transform', `translate(${f1(q.x)},${f1(q.y)}) rotate(${f1(Math.atan2(q2.y - q.y, q2.x - q.x) * 57.3)})`);
        });
        if (twitch.length && exposed('muscle')) twitch.forEach(g => g.setAttribute('opacity', Math.random() < .12 ? f1(.15 + Math.random() * .4 * Math.max(F.muscle.twitch, .5)) : 0));
      } else root.classList.add('ar-paused');
      requestAnimationFrame(loop);
    };
    if (!reduce) requestAnimationFrame(loop);

    renderList(); setDepth(0);
    return {findings: F, destroy() { alive = false; urls.forEach(u => URL.revokeObjectURL(u)); }};
  }

  API.mount = mount;
  API.LAYERS = LAYERS.map(l => l.key);
})();
