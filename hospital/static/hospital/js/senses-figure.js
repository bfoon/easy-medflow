/* Eyes & ears: animations drawn from the values the clinician enters.
   MFSenses.compute mirrors hospital/senses.py `compute` exactly (same rounding, same messages), so every picture
   follows the numbers while typing; the server recomputes on save and the page redraws from its answer.
   Drawings: the two eyes with a swinging-torch pupil test, a cross-section with aqueous flow and pressure, the fundus,
   a simulation of what the patient sees, the ear's sound path to the cochlea and nerve, the otoscope view, an
   audiogram and a "hear it as the patient does" sound demo. Teaching / documentation visual only. */
(() => {
  'use strict';
  const reduce = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const rnd = (x, d = 0) => { const m = 10 ** d; return Math.floor(x * m + 0.5) / m; };
  const fmt = x => String(x);
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
  const SIDES = ['right', 'left'];
  const ORDER = {high: 0, warn: 1, info: 2};

  /* ================================================================== the maths (mirror of senses.py) */
  const LENS = {clear: 0, early: 1, moderate: 2, dense: 3, mature: 4, iol: 0};
  const LENS_LABELS = {clear: 'Clear', early: 'Early cataract', moderate: 'Moderate cataract', dense: 'Dense cataract', mature: 'Mature (white) cataract', iol: 'Lens implant (after cataract surgery)'};
  const LOGMAR = {'6/5': -0.1, '6/6': 0.0, '6/9': 0.2, '6/12': 0.3, '6/18': 0.5, '6/24': 0.6, '6/36': 0.8, '6/60': 1.0, '3/60': 1.3, '1/60': 1.8, CF: 2.0, HM: 2.3, PL: 2.7, NPL: 3.0};
  const VI = [['none', 'No visual impairment', 0.3], ['mild', 'Mild visual impairment', 0.5], ['moderate', 'Moderate visual impairment', 1.0], ['severe', 'Severe visual impairment', 1.3], ['blind', 'Blindness', 99]];
  const FREQS = ['250', '500', '1000', '2000', '4000', '8000'], PTA_FREQS = ['500', '1000', '2000', '4000'];
  const HEARING = [['normal', 'Normal hearing', 20], ['mild', 'Mild hearing loss', 35], ['moderate', 'Moderate hearing loss', 50], ['mod_severe', 'Moderately severe hearing loss', 65],
    ['severe', 'Severe hearing loss', 80], ['profound', 'Profound hearing loss', 95], ['complete', 'Complete hearing loss', 999]];
  const TYPE_LABELS = {normal: 'Normal', conductive: 'Conductive', sensorineural: 'Sensorineural', mixed: 'Mixed', conductive_probable: 'Probably conductive', sensorineural_probable: 'Probably sensorineural'};
  const BLOCK = {clear: 0, wax: 0.35, impacted_wax: 0.92, otitis_externa: 0.6, foreign_body: 0.75};
  const MOB_TYMP = {A: 1, As: 0.5, Ad: 1.5, B: 0.08, C: 0.55};
  const MOB_TM = {normal: 1, retracted: 0.6, effusion: 0.25, bulging: 0.1, perforation: 0.7, cholesteatoma: 0.3, grommet: 0.9, scarred: 0.7};

  function viCategory(lm) { for (const [k, l, u] of VI) if (lm <= u) return [k, l]; return ['blind', 'Blindness']; }
  function hearingGrade(p) { for (const [k, l, u] of HEARING) if (p < u) return [k, l]; return ['complete', 'Complete hearing loss']; }
  const avg = v => v.length ? rnd(v.reduce((a, b) => a + b, 0) / v.length, 1) : null;

  function computeEye(e, side, sym, ctx, alerts, procs) {
    if (!e.examined) return null;
    const where = `${side} eye`;
    const lm = e.va ? LOGMAR[e.va] : null, ph = e.pinhole ? LOGMAR[e.pinhole] : null;
    const cat = lm !== null ? viCategory(lm) : [null, null];
    const grade = LENS[e.lens], iop = e.iop, cdr = e.cdr, r = e.retina;
    const refractive = lm !== null && ph !== null && rnd(lm - ph, 1) >= 0.2;
    const add = (level, text) => alerts.push({level, text});
    const proc = (code, reason) => { if (!procs.some(p => p.code === code && p.side === side)) procs.push({code, side, reason}); };

    if (e.va === 'NPL') add('high', `No perception of light in the ${where}: the eye is blind.`);
    let iopState = null;
    if (iop !== null) {
      iopState = iop < 6 ? 'low' : iop <= 21 ? 'normal' : iop < 30 ? 'raised' : iop < 40 ? 'high' : 'very_high';
      const closure = iop >= 40 && (e.chamber === 'shallow' || e.reaction !== 'brisk' || !!sym.eye_pain);
      if (closure) add('high', `Possible acute angle-closure glaucoma in the ${where} (pressure ${iop} mmHg): an emergency. Lower the pressure now and refer the same day.`);
      else if (iop >= 30) add('high', `Pressure ${iop} mmHg in the ${where} is very high: start treatment and refer this week.`);
      else if (iop > 21) add('warn', `Pressure ${iop} mmHg in the ${where} is raised (normal 10–21).`);
      else if (iop < 6) add('warn', `Pressure ${iop} mmHg in the ${where} is very low: look for a wound leak or perforation.`);
    }
    let glaucoma = null;
    if (cdr !== null) {
      if (cdr >= 0.7 && iop !== null && iop > 21) {
        glaucoma = 'likely';
        add('warn', `Glaucoma likely in the ${where}: cup-to-disc ${fmt(cdr)} with pressure ${iop} mmHg. Start pressure-lowering drops and check the visual field.`);
        proc('trabeculectomy', `Glaucoma (${where}) if the pressure stays uncontrolled on drops`);
      } else if (cdr >= 0.7 || (cdr >= 0.6 && iop !== null && iop > 21)) {
        glaucoma = 'suspect';
        add('warn', `Glaucoma suspect in the ${where} (cup-to-disc ${fmt(cdr)}): repeat the pressure and test the visual field.`);
      }
    }
    if (grade >= 3 || (grade >= 2 && lm !== null && lm >= 0.5)) {
      add('warn', `Cataract is reducing vision in the ${where}` + (e.va ? ` (${e.va})` : '') + ': cataract surgery should restore sight.');
      proc('cataract', `${LENS_LABELS[e.lens]} in the ${where}` + (e.va ? `, vision ${e.va}` : ''));
    } else if (grade >= 1) add('info', `Early cataract in the ${where}: review yearly; surgery when it limits daily life.`);
    if (refractive) add('info', `Vision in the ${where} improves with a pinhole (${e.va} → ${e.pinhole}): glasses should help.`);
    const dr = r.dr;
    if (dr === 'proliferative') add('high', `Proliferative diabetic retinopathy in the ${where}: urgent laser or anti-VEGF treatment; risk of bleeding and blindness.`);
    else if (dr === 'severe') add('high', `Severe non-proliferative diabetic retinopathy in the ${where}: refer to an eye specialist within 2–4 weeks.`);
    else if (dr === 'moderate') add('warn', `Moderate diabetic retinopathy in the ${where}: refer, and review every 3–6 months.`);
    else if (dr === 'mild') add('info', `Mild diabetic retinopathy in the ${where}: review in 12 months; control sugar and blood pressure.`);
    if (r.maculopathy) add('high', `Diabetic maculopathy in the ${where}: refer for laser or anti-VEGF to protect central vision.`);
    const sbp = ctx.systolic ?? null, dbp = ctx.diastolic ?? null;
    const crisis = (sbp !== null && sbp >= 180) || (dbp !== null && dbp >= 120);
    if (r.htn >= 3 && crisis) add('high', `Hypertensive retinopathy grade ${r.htn} with blood pressure ${sbp !== null ? fmt(sbp) : '?'}/${dbp !== null ? fmt(dbp) : '?'}: hypertensive emergency. Lower the pressure in a monitored bed.`);
    else if (r.htn === 4) add('high', `Hypertensive retinopathy grade 4 (disc swelling) in the ${where}: malignant hypertension until proven otherwise.`);
    else if (r.htn >= 1) add(r.htn >= 3 ? 'warn' : 'info', `Hypertensive retinopathy grade ${r.htn} in the ${where}: control the blood pressure.`);
    if (r.detachment) add('high', `Retinal detachment in the ${where}: emergency referral for surgery today; keep the patient still.`);
    if (r.amd === 'wet') add('high', `Wet macular degeneration in the ${where}: urgent anti-VEGF injections to save central vision.`);
    else if (r.amd === 'dry') add('info', `Dry macular degeneration in the ${where}: stop smoking; low-vision aids; watch for sudden distortion.`);
    if (e.chamber === 'hypopyon') add('high', `Pus in the front chamber of the ${where} (hypopyon): severe infection or ulcer; same-day eye surgeon.`);
    else if (e.chamber === 'hyphaema') add('high', `Blood in the front chamber of the ${where} (hyphaema): rest with the head up, check the pressure daily.`);
    if (e.cornea === 'ulcer') add('high', `Corneal ulcer in the ${where}: same-day eye review and intensive antibiotic drops; no steroid drops.`);
    else if (e.cornea === 'abrasion') add('warn', `Corneal abrasion in the ${where}: antibiotic ointment and review in 24–48 hours.`);
    else if (e.cornea === 'oedema') add('warn', `Hazy cornea in the ${where}: check the pressure.`);
    if (e.conjunctiva === 'injected' && e.discharge === 'purulent') add('info', `Bacterial conjunctivitis likely in the ${where}: antibiotic drops; wash hands and do not share towels.`);
    else if (e.conjunctiva === 'injected' && e.discharge === 'watery') add('info', `Viral or allergic conjunctivitis likely in the ${where}: cool compresses; very contagious if viral.`);
    else if (e.conjunctiva === 'pterygium') { add('info', `Pterygium in the ${where}: sun protection; remove it if it grows towards the pupil.`); proc('pterygium', `Pterygium in the ${where}`); }
    else if (e.conjunctiva === 'haemorrhage') add('info', `Subconjunctival haemorrhage in the ${where}: harmless and clears in 2 weeks` + (crisis || (sbp !== null && sbp >= 160) ? '; the blood pressure is high, treat it.' : '; check the blood pressure.'));
    if (e.rapd) add('warn', `Relative afferent pupil defect in the ${where}: optic nerve or severe retinal disease; urgent review.`);
    if (e.reaction === 'none' && e.pupil_mm >= 6 && !(iop !== null && iop >= 40)) add('high', `Fixed dilated pupil in the ${where} (${fmt(e.pupil_mm)} mm): urgent neurological review.`);

    const scotoma = Math.max(r.maculopathy ? 0.18 : 0, {none: 0, dry: 0.12, wet: 0.24}[r.amd], e.field === 'central_loss' ? 0.2 : 0);
    let field = cdr === null ? 1.0 : clamp(1 - Math.max(0, cdr - 0.5) * 1.8, 0.15, 1);
    if (e.field === 'peripheral_loss') field = Math.min(field, 0.55);
    const haze = Math.min(1, grade * 0.2 + (['oedema', 'scar'].includes(e.cornea) ? 0.35 : 0) + (['hypopyon', 'hyphaema'].includes(e.chamber) ? 0.3 : 0));
    const vision = {blur: rnd(clamp(lm !== null ? lm : 0, 0, 2.3) * 6, 1), haze: rnd(haze, 2), tint: rnd(grade * 0.12, 2), field: rnd(field, 2), scotoma: rnd(scotoma, 2),
      spots: {none: 0, mild: 2, moderate: 5, severe: 9, proliferative: 14}[dr], floaters: dr === 'proliferative', curtain: r.detachment ? 0.45 : 0,
      dark: {NPL: 1, PL: 0.9, HM: 0.6}[e.va] || 0};
    let outflow = iop === null || iop <= 21 ? 1.0 : rnd(21 / iop, 2);
    if (e.chamber === 'shallow' && iop !== null && iop >= 30) outflow = 0.15;
    return {logmar: lm, pinhole_logmar: ph, category: cat[0], category_label: cat[1], refractive, lens_grade: grade, iop_state: iopState, glaucoma, outflow, vision};
  }

  function computeEar(a, side, sym, ctx, alerts, procs) {
    if (!a.examined) return null;
    const where = `${side} ear`, ac = a.ac, bc = a.bc, has = (o, f) => Object.prototype.hasOwnProperty.call(o, f);
    const ptaVals = PTA_FREQS.filter(f => has(ac, f)).map(f => ac[f]);
    const pta = ptaVals.length >= 3 ? avg(ptaVals) : null;
    const bcVals = PTA_FREQS.filter(f => has(bc, f)).map(f => bc[f]);
    const bcPta = bcVals.length ? avg(bcVals) : null;
    const gap = avg(PTA_FREQS.filter(f => has(ac, f) && has(bc, f)).map(f => ac[f] - bc[f]));
    const grade = pta !== null ? hearingGrade(pta) : [null, null];
    const signs = ['impacted_wax', 'foreign_body', 'otitis_externa'].includes(a.canal) || ['effusion', 'bulging', 'perforation', 'cholesteatoma'].includes(a.tm)
      || ['B', 'C'].includes(a.tympanogram) || a.rinne === 'negative';
    let kind = null;
    if (pta !== null) {
      if (pta < 20 && (gap === null || gap < 15)) kind = 'normal';
      else if (gap !== null) kind = gap >= 15 ? (bcPta !== null && bcPta >= 20 ? 'mixed' : 'conductive') : 'sensorineural';
      else kind = signs ? 'conductive_probable' : 'sensorineural_probable';
    }
    const notch = has(ac, '4000') && has(ac, '2000') && ac['4000'] - ac['2000'] >= 15 && (!has(ac, '8000') || ac['4000'] - ac['8000'] >= 5);
    const lows = ['250', '500'].filter(f => has(ac, f)).map(f => ac[f]), highs = ['4000', '8000'].filter(f => has(ac, f)).map(f => ac[f]);
    const sloping = !!(lows.length && highs.length) && avg(highs) - avg(lows) >= 20;
    const lowTone = !!(lows.length && highs.length) && avg(lows) - avg(highs) >= 10;
    const add = (level, text) => alerts.push({level, text});
    const proc = (code, reason) => { if (!procs.some(p => p.code === code && p.side === side)) procs.push({code, side, reason}); };

    const neural = ['sensorineural', 'mixed', 'sensorineural_probable'].includes(kind);
    if (sym.sudden_loss && neural) add('high', `Sudden sensorineural hearing loss in the ${where}: an emergency. Start oral steroids within 72 hours and see ENT today.`);
    if (notch && neural) add('info', `Dip at 4 kHz in the ${where}: typical of noise damage; protect the ears from loud noise.`);
    if (sloping && neural && ctx.age != null && ctx.age >= 60) add('info', `High-frequency loss sloping down in the ${where}: age-related hearing loss (presbycusis).`);
    if (lowTone && neural && sym.vertigo && sym.tinnitus) add('warn', `Low-tone loss with vertigo and tinnitus in the ${where}: possible Ménière’s disease; refer to ENT.`);
    if (a.canal === 'impacted_wax') { add('warn', `Impacted wax in the ${where}: remove it (microsuction or syringing) and test the hearing again.`); proc('ear-microsuction', `Impacted wax in the ${where}`); }
    else if (a.canal === 'foreign_body') { add('warn', `Foreign body in the ${where}: remove it under direct vision; do not syringe batteries or seeds.`); proc('ear-microsuction', `Foreign body in the ${where}`); }
    else if (a.canal === 'otitis_externa') {
      if (ctx.diabetic && ctx.age != null && ctx.age >= 60) add('high', `Otitis externa in an older person with diabetes (${where}): rule out necrotising (malignant) otitis externa.`);
      else add('warn', `Otitis externa in the ${where}: clean the canal, antibiotic–steroid drops, keep it dry.`);
    }
    if (a.tm === 'bulging') add('warn', `Acute otitis media in the ${where}: pain relief; antibiotics if severe, under 2 years old, or discharging.`);
    else if (a.tm === 'effusion') {
      add('info', `Fluid behind the ${where} drum (glue ear): watch for 3 months; grommets if it persists with hearing loss.`);
      if (pta !== null && pta >= 25) proc('grommet', `Glue ear in the ${where} with hearing loss (${fmt(pta)} dB)`);
    } else if (a.tm === 'perforation') {
      if (['mucoid', 'purulent'].includes(a.discharge)) add('warn', `Chronic suppurative otitis media in the ${where} (${a.perforation_pct}% perforation, discharging): dry mopping and antibiotic drops; repair once dry.`);
      else add('info', `Dry perforation of the ${where} drum (${a.perforation_pct}%): a tympanoplasty can close it and improve hearing.`);
      proc('tympanoplasty', `${a.perforation_pct}% perforation of the ${where} drum`);
    } else if (a.tm === 'cholesteatoma') { add('high', `Cholesteatoma in the ${where}: it erodes bone and can reach the brain; refer for mastoid surgery.`); proc('mastoidectomy', `Cholesteatoma in the ${where}`); }
    else if (a.tm === 'retracted') add('info', `Retracted ${where} drum: Eustachian tube not opening well.`);
    if (a.discharge === 'bloody') add('warn', `Blood from the ${where}: after head injury, suspect a skull-base fracture.`);

    const block = BLOCK[a.canal];
    const mob = a.tympanogram ? MOB_TYMP[a.tympanogram] : MOB_TM[a.tm];
    const fluid = {effusion: 0.65, bulging: 1}[a.tm] || 0;
    const conduct = gap !== null ? clamp(1 - Math.max(0, gap) / 60, 0.05, 1) : clamp(1 - (block * 0.7 + (1 - Math.min(1, mob)) * 0.5), 0.05, 1);
    const conductiveOnly = ['conductive', 'conductive_probable'].includes(kind);
    const cochlea = {};
    for (const f of FREQS) {
      const th = has(bc, f) ? bc[f] : (conductiveOnly ? null : (has(ac, f) ? ac[f] : null));
      cochlea[f] = th === null ? 0 : rnd(clamp((th - 15) / 90, 0, 1), 2);
    }
    return {pta, grade: grade[0], grade_label: grade[1], bc_pta: bcPta, gap, type: kind, type_label: kind ? TYPE_LABELS[kind] : null, notch, sloping,
      block, mobility: mob, fluid, conduct: rnd(conduct, 2), cochlea, signal: pta !== null ? rnd(clamp(1 - pta / 100, 0, 1), 2) : 1};
  }

  function compute(data, ctx = {}) {
    ctx = ctx || {};
    const sym = data.symptoms || {}, alerts = [], procs = [];
    const eyes = {}, ears = {};
    for (const s of SIDES) eyes[s] = computeEye(data.eyes[s], s, sym, ctx, alerts, procs);
    for (const s of SIDES) ears[s] = computeEar(data.ears[s], s, sym, ctx, alerts, procs);
    const seen = SIDES.filter(s => eyes[s] && eyes[s].logmar !== null).map(s => eyes[s]);
    let vision = null;
    if (seen.length) {
      const best = Math.min(...seen.map(x => x.logmar)), cat = viCategory(best);
      vision = {better_logmar: best, category: cat[0], label: cat[1]};
      if (seen.length === 2 && cat[0] === 'blind') alerts.push({level: 'high', text: 'Blindness (the better eye sees less than 3/60): refer for rehabilitation and treat any cause that can be reversed.'});
      else if (seen.length === 2 && ['moderate', 'severe'].includes(cat[0])) alerts.push({level: 'warn', text: `${cat[1]} (better eye): affects reading, work and moving about safely.`});
    }
    const cdrs = SIDES.filter(s => eyes[s] && data.eyes[s].cdr !== null).map(s => data.eyes[s].cdr);
    if (cdrs.length === 2 && rnd(Math.abs(cdrs[0] - cdrs[1]), 2) >= 0.2) alerts.push({level: 'warn', text: `Cup-to-disc ratios differ by ${fmt(rnd(Math.abs(cdrs[0] - cdrs[1]), 2))} between the eyes: a sign of glaucoma.`});
    if (SIDES.some(s => eyes[s] && data.eyes[s].retina.papilloedema)) alerts.push({level: 'high', text: 'Papilloedema (swollen optic discs): raised pressure inside the skull until proven otherwise; urgent brain scan.'});
    const anyDr = SIDES.some(s => eyes[s] && data.eyes[s].retina.dr !== 'none');
    if (anyDr && ctx.hba1c != null && ctx.hba1c >= 8) alerts.push({level: 'warn', text: `HbA1c ${fmt(ctx.hba1c)}% with diabetic retinopathy: better sugar control slows the damage.`});
    if (ctx.diabetic && SIDES.some(s => eyes[s]) && !anyDr) alerts.push({level: 'info', text: 'Diabetes with no retinopathy seen: screen the eyes again in 12 months.'});
    const ptas = SIDES.filter(s => ears[s] && ears[s].pta !== null).map(s => ears[s].pta);
    let hearing = null;
    if (ptas.length) {
      const best = Math.min(...ptas), g = hearingGrade(best);
      hearing = {better_pta: best, grade: g[0], label: g[1], aid: ptas.length === 2 && best >= 35};
      if (hearing.aid) alerts.push({level: 'warn', text: `${g[1]} in the better ear (${fmt(best)} dB): offer hearing aids and check again in a year.`});
      if (ptas.length === 2 && best >= 80 && SIDES.every(s => ['sensorineural', 'sensorineural_probable'].includes(ears[s].type)))
        alerts.push({level: 'info', text: 'Severe-to-profound sensorineural loss in both ears: assess for a cochlear implant.'});
    }
    if (ptas.length === 2 && Math.abs(ptas[0] - ptas[1]) >= 15 && SIDES.every(s => ['sensorineural', 'sensorineural_probable', 'normal'].includes(ears[s].type)))
      alerts.push({level: 'warn', text: `Hearing differs by ${fmt(rnd(Math.abs(ptas[0] - ptas[1]), 1))} dB between the ears without a conductive cause: MRI to exclude a vestibular schwannoma.`});
    if (SIDES.includes(data.weber)) {
      const other = data.weber === 'right' ? 'left' : 'right';
      alerts.push({level: 'info', text: `Weber test heard in the ${data.weber} ear: conductive loss on the ${data.weber} or sensorineural loss on the ${other}.`});
    }
    const seenText = new Set();
    const uniq = alerts.filter(a => !seenText.has(a.text) && seenText.add(a.text));
    uniq.sort((a, b) => ORDER[a.level] - ORDER[b.level]);
    return {eyes, ears, vision, hearing, alerts: uniq, procedures: procs};
  }

  /* ================================================================== drawing helpers */
  const NS = 'http://www.w3.org/2000/svg';
  let uid = 0;
  const id = p => `${p}${++uid}`;
  function seeded(seed) { let s = seed >>> 0 || 1; return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296; }
  function stopAll(host) { (host.__stop || []).forEach(f => { try { f(); } catch (e) { /* ignore */ } }); host.__stop = []; }
  function loop(host, fn) {
    if (reduce) { fn(0, 0); return; }
    let raf, t0 = null, last = 0, alive = true;
    const step = ts => { if (!alive) return; if (t0 === null) t0 = ts; const t = (ts - t0) / 1000; fn(t, t - last); last = t; raf = requestAnimationFrame(step); };
    raf = requestAnimationFrame(step);
    (host.__stop ||= []).push(() => { alive = false; cancelAnimationFrame(raf); });
  }
  const svgEl = (w, h, cls, label) => `<svg viewBox="0 0 ${w} ${h}" class="${cls}" role="img" aria-label="${label}" xmlns="${NS}">`;

  /* ================================================================== the two eyes (front view, swinging torch) */
  const SKIN = '#8A5A3C', SKIN_D = '#6E432A';
  function eyesFront(host, data, computed, opts = {}) {
    stopAll(host);
    const W = 600, H = 230, boxes = {right: 150, left: 450};      // the patient's right eye is on the viewer's left
    const gid = id('ef');
    let s = svgEl(W, H, 'ss-eyes', 'Both eyes seen from the front, with a torch swinging between them');
    s += `<defs>
      <radialGradient id="${gid}-iris" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#5A3317"/><stop offset=".55" stop-color="#7A4A23"/><stop offset=".85" stop-color="#4A2A12"/><stop offset="1" stop-color="#26150A"/></radialGradient>
      <radialGradient id="${gid}-red" cx="50%" cy="50%" r="60%"><stop offset=".25" stop-color="#E25B5B" stop-opacity="0"/><stop offset="1" stop-color="#D23C3C" stop-opacity=".75"/></radialGradient>
      <radialGradient id="${gid}-flush" cx="50%" cy="50%" r="50%"><stop offset=".55" stop-color="#C8323F" stop-opacity="0"/><stop offset=".72" stop-color="#C8323F" stop-opacity=".55"/><stop offset="1" stop-color="#C8323F" stop-opacity="0"/></radialGradient>
      <radialGradient id="${gid}-beam" cx="50%" cy="0%" r="100%"><stop offset="0" stop-color="#FFF6C8" stop-opacity=".9"/><stop offset="1" stop-color="#FFF6C8" stop-opacity="0"/></radialGradient>
      <filter id="${gid}-soft"><feGaussianBlur stdDeviation="1.2"/></filter>
    </defs>`;
    s += `<rect x="0" y="0" width="${W}" height="${H}" rx="18" fill="${SKIN}"/><path d="M0,40 Q300,0 600,40 L600,0 L0,0Z" fill="${SKIN_D}" opacity=".35"/>`;
    for (const side of SIDES) {
      const cx = boxes[side], cy = 118, e = data.eyes[side], c = computed.eyes[side];
      const nasal = side === 'right' ? 1 : -1;
      const clip = `${gid}-${side}-clip`;
      const almond = `M${cx - 104},${cy} Q${cx},${cy - 70} ${cx + 104},${cy} Q${cx},${cy + 64} ${cx - 104},${cy}Z`;
      s += `<g class="ss-eye" data-side="${side}" ${c ? '' : 'opacity=".45"'}>
        <path d="${almond}" fill="#3B2416" transform="translate(0,3)" opacity=".5"/>
        <clipPath id="${clip}"><path d="${almond}"/></clipPath>
        <g clip-path="url(#${clip})">
          <rect x="${cx - 110}" y="${cy - 70}" width="220" height="140" fill="#F6F1EA"/>`;
      if (c && e.conjunctiva === 'injected') {
        s += `<rect x="${cx - 110}" y="${cy - 70}" width="220" height="140" fill="url(#${gid}-red)"/>`;
        const rr = seeded(side === 'right' ? 11 : 23);
        for (let i = 0; i < 16; i++) {
          const a = rr() * Math.PI * 2, r0 = 46 + rr() * 6, r1 = 70 + rr() * 40;
          const x0 = cx + Math.cos(a) * r0, y0 = cy + Math.sin(a) * r0 * .7, x1 = cx + Math.cos(a) * r1, y1 = cy + Math.sin(a) * r1 * .7;
          s += `<path d="M${x1.toFixed(1)},${y1.toFixed(1)} Q${((x0 + x1) / 2 + (rr() - .5) * 16).toFixed(1)},${((y0 + y1) / 2 + (rr() - .5) * 16).toFixed(1)} ${x0.toFixed(1)},${y0.toFixed(1)}" stroke="#C2272F" stroke-width="${(.6 + rr() * 1.2).toFixed(1)}" fill="none" opacity=".8"/>`;
        }
        if (e.cornea === 'ulcer' || e.chamber === 'hypopyon') s += `<circle cx="${cx}" cy="${cy}" r="70" fill="url(#${gid}-flush)"/>`;
      }
      if (c && e.conjunctiva === 'haemorrhage') s += `<path d="M${cx - nasal * 52},${cy - 30} q${-nasal * 30},10 ${-nasal * 40},40 q${nasal * 12},18 ${nasal * 34},6 q${nasal * 10},-24 ${nasal * 6},-46Z" fill="#B3121E" opacity=".85" filter="url(#${gid}-soft)"/>`;
      if (c && e.conjunctiva === 'pterygium') s += `<path d="M${cx + nasal * 104},${cy - 20} L${cx + nasal * 26},${cy - 4} Q${cx + nasal * 20},${cy} ${cx + nasal * 26},${cy + 4} L${cx + nasal * 104},${cy + 22}Z" fill="#E8A79A" stroke="#C9665A" stroke-width="1" opacity=".9"/>`;
      // iris, chamber levels, pupil, lens, cornea
      s += `<circle cx="${cx}" cy="${cy}" r="40" fill="url(#${gid}-iris)"/>`;
      for (let i = 0; i < 28; i++) { const a = i / 28 * Math.PI * 2; s += `<line x1="${(cx + Math.cos(a) * 14).toFixed(1)}" y1="${(cy + Math.sin(a) * 14).toFixed(1)}" x2="${(cx + Math.cos(a) * 38).toFixed(1)}" y2="${(cy + Math.sin(a) * 38).toFixed(1)}" stroke="#2E1A0C" stroke-width=".7" opacity=".45"/>`; }
      const lensFill = !c ? '#0B0B0B' : e.lens === 'mature' ? '#F2EFE6' : e.lens === 'dense' ? '#9C8458' : '#0B0B0B';
      s += `<circle class="ss-pupil" cx="${cx}" cy="${cy}" r="${Math.min(36, e.pupil_mm * 4.2)}" fill="${lensFill}"/>`;
      if (c && ['early', 'moderate'].includes(e.lens)) s += `<circle class="ss-pupil ss-cat" cx="${cx}" cy="${cy}" r="${Math.min(36, e.pupil_mm * 4.2)}" fill="#D9D3C0" opacity="${e.lens === 'early' ? .28 : .5}"/>`;
      if (c && e.lens === 'iol') s += `<circle cx="${cx}" cy="${cy}" r="11" fill="none" stroke="#9FB7C8" stroke-width="1.2" opacity=".7"/>`;
      if (c && (e.chamber === 'hypopyon' || e.chamber === 'hyphaema')) {
        const cl = `${gid}-${side}-ac`;
        s += `<clipPath id="${cl}"><circle cx="${cx}" cy="${cy}" r="40"/></clipPath><rect clip-path="url(#${cl})" x="${cx - 42}" y="${cy + 22}" width="84" height="20" fill="${e.chamber === 'hypopyon' ? '#EFE3A8' : '#A3151F'}" opacity=".95"/>`;
      }
      if (c && e.cornea === 'oedema') s += `<circle cx="${cx}" cy="${cy}" r="44" fill="#E8EEF2" opacity=".55"/>`;
      if (c && e.cornea === 'scar') s += `<ellipse cx="${cx - 10}" cy="${cy - 8}" rx="14" ry="10" fill="#F4F2EC" opacity=".85" filter="url(#${gid}-soft)"/>`;
      if (c && e.cornea === 'ulcer') s += `<circle cx="${cx + 8}" cy="${cy - 12}" r="9" fill="#F3EED4" stroke="#C7BF92" stroke-width="2" opacity=".95"/>`;
      if (c && e.cornea === 'abrasion') s += `<path class="ss-fluor" d="M${cx - 20},${cy - 22} q14,-6 26,4 q-4,10 -18,10 q-10,-4 -8,-14Z" fill="#7CFF6B" opacity=".8" filter="url(#${gid}-soft)"/>`;
      s += `<ellipse cx="${cx - 12}" cy="${cy - 14}" rx="7" ry="5" fill="#fff" opacity=".85"/>`;
      s += `<rect class="ss-lid" x="${cx - 110}" y="${cy - 72}" width="220" height="0" fill="${SKIN}"/>
        </g>
        <path d="M${cx - 104},${cy} Q${cx},${cy - 70} ${cx + 104},${cy}" fill="none" stroke="#2A170C" stroke-width="3"/>
        <path d="M${cx - 104},${cy} Q${cx},${cy + 64} ${cx + 104},${cy}" fill="none" stroke="#3A2214" stroke-width="1.6"/>`;
      for (let i = 0; i < 13; i++) { const t = .12 + i * .065, x = (1 - t) ** 2 * (cx - 104) + 2 * (1 - t) * t * cx + t * t * (cx + 104), y = (1 - t) ** 2 * cy + 2 * (1 - t) * t * (cy - 70) + t * t * cy; s += `<path d="M${x.toFixed(1)},${(y - 1).toFixed(1)} q${(t - .5) * 8},-8 ${(t - .5) * 14},-12" stroke="#1E1009" stroke-width="1.4" fill="none"/>`; }
      if (c && e.discharge !== 'none') {
        const col = e.discharge === 'purulent' ? '#E9D27A' : '#CFE7F5';
        s += `<path d="M${cx - 40},${cy + 30} q40,14 80,0" stroke="${col}" stroke-width="4" fill="none" opacity=".9"/><circle class="ss-drip" cx="${cx - 16 * nasal}" cy="${cy + 40}" r="4" fill="${col}" opacity=".95"/>`;
      }
      const va = e.va ? `${e.va}` : '—';
      s += `<text x="${cx}" y="${H - 14}" text-anchor="middle" class="ss-cap ss-cap-light">${side === 'right' ? 'Right eye (R)' : 'Left eye (L)'} · ${c ? `vision ${va}${e.iop !== null ? ` · pressure ${e.iop}` : ''}${e.rapd ? ' · RAPD' : ''}` : 'not examined'}</text>
      </g>`;
    }
    s += `<g class="ss-torch"><path class="ss-beam" d="M-28,24 L28,24 L70,150 L-70,150Z" fill="url(#${gid}-beam)" opacity="0"/><rect x="-9" y="-30" width="18" height="44" rx="4" fill="#374151"/><rect x="-12" y="10" width="24" height="14" rx="3" fill="#9CA3AF"/><circle cx="0" cy="22" r="7" fill="#FFF4B0"/></g>`;
    s += '</svg>';
    host.innerHTML = `<div class="ss-fig">${s}<p class="ss-legend" aria-live="polite"></p></div>`;
    const svg = host.querySelector('svg'), torch = svg.querySelector('.ss-torch'), beam = svg.querySelector('.ss-beam'), legend = host.querySelector('.ss-legend');
    const eyesEl = {}, size = {}, lids = [];
    for (const side of SIDES) {
      const g = svg.querySelector(`.ss-eye[data-side=${side}]`);
      eyesEl[side] = [...g.querySelectorAll('.ss-pupil')];
      size[side] = data.eyes[side].pupil_mm;
      lids.push(g.querySelector('.ss-lid'));
    }
    const constrict = {brisk: .48, sluggish: .22, none: 0}, speed = {brisk: 6, sluggish: 1.6, none: 0};
    const afferent = side => { const e = data.eyes[side], c = computed.eyes[side]; if (!c) return 1; if (e.va === 'NPL') return 0; return e.rapd ? .25 : 1; };
    let shown = '';
    loop(host, (t, dt) => {
      const cyc = t % 6;
      const lit = cyc > .8 && cyc < 2.7 ? 'right' : cyc > 3.2 && cyc < 5.1 ? 'left' : null;
      const pos = cyc < 2.7 ? boxes.right : cyc < 3.2 ? boxes.right + (boxes.left - boxes.right) * (cyc - 2.7) / .5 : cyc < 5.6 ? boxes.left : boxes.left + (boxes.right - boxes.left) * (cyc - 5.6) / .4;
      torch.setAttribute('transform', `translate(${pos},${lit ? 2 : -6})`);
      beam.setAttribute('opacity', lit ? '.85' : '0');
      const msg = lit ? `Torch on the ${lit} eye: ${afferent(lit) === 1 ? 'both pupils constrict' : afferent(lit) === 0 ? 'no light gets through: both pupils widen' : 'weak signal from this eye: both pupils widen (RAPD)'}` : 'Torch moving…';
      if (msg !== shown) { legend.textContent = msg; shown = msg; }
      for (const side of SIDES) {
        const e = data.eyes[side];
        const goal = Math.max(1, lit ? e.pupil_mm * (1 - constrict[e.reaction] * afferent(lit)) : e.pupil_mm * (e.reaction === 'none' ? 1 : 1.12));
        size[side] += (goal - size[side]) * Math.min(1, dt * (speed[e.reaction] || 0));
        for (const p of eyesEl[side]) p.setAttribute('r', Math.min(36, size[side] * 4.2).toFixed(2));
      }
      const b = t % 4.3, h = b < .09 ? b / .09 : b < .18 ? 1 - (b - .09) / .09 : 0;
      for (const l of lids) l.setAttribute('height', (h * 150).toFixed(1));
    });
    svg.querySelectorAll('.ss-eye').forEach(g => {
      g.style.cursor = opts.onPick ? 'pointer' : '';
      if (opts.onPick) g.addEventListener('click', () => opts.onPick(g.dataset.side));
    });
  }

  /* ================================================================== cross-section: pressure, lens, optic nerve */
  function eyeSection(host, e, c, side) {
    stopAll(host);
    if (!c) { host.innerHTML = `<div class="ss-empty">The ${side} eye has not been examined.</div>`; return; }
    const W = 460, H = 280, cx = 240, cy = 140, R = 104, gid = id('es');
    const iop = e.iop, hi = iop !== null && iop > 21, shallow = e.chamber === 'shallow';
    const cdr = e.cdr ?? .3, grade = c.lens_grade;
    const press = iop === null ? 0 : clamp((iop - 15) / 30, 0, 1);
    const fibres = Math.max(3, Math.round(14 * (1 - Math.max(0, cdr - .3) * 1.25)));
    let s = svgEl(W, H, 'ss-section', `Cross-section of the ${side} eye showing fluid flow and pressure`);
    s += `<defs><radialGradient id="${gid}-vit" cx="40%" cy="45%" r="70%"><stop offset="0" stop-color="#F7FBFD"/><stop offset="1" stop-color="#E3EEF3"/></radialGradient>
      <marker id="${gid}-ar" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10Z" fill="${hi ? '#C8323F' : '#0F7B78'}"/></marker></defs>`;
    s += `<g class="ss-globe" style="transform-origin:${cx}px ${cy}px">
      <circle cx="${cx}" cy="${cy}" r="${R + 6}" fill="#FAF6F0" stroke="${hi ? '#C8323F' : '#B9A99A'}" stroke-width="${hi ? 3 + press * 4 : 3}"/>
      <circle cx="${cx}" cy="${cy}" r="${R}" fill="url(#${gid}-vit)"/>
      <path d="M${cx + 30},${cy - R + 6} A${R - 4},${R - 4} 0 0 1 ${cx + 30},${cy + R - 6}" fill="none" stroke="#E07A5F" stroke-width="5" opacity=".8"/>`;
    if (e.retina.detachment) s += `<path class="ss-detach" d="M${cx + 60},${cy - 80} Q${cx + 30},${cy - 40} ${cx + 66},${cy - 10}" fill="none" stroke="#E07A5F" stroke-width="5"/>`;
    // optic nerve and cup
    const cupW = 6 + cdr * 26;
    s += `<path d="M${cx + R - 2},${cy - 18} L${W - 6},${cy - 22} L${W - 6},${cy + 22} L${cx + R - 2},${cy + 18}Z" fill="#F2D7A6" stroke="#C9A66B"/>
      <path d="M${cx + R - 4},${cy - cupW / 2} Q${cx + R + 8 + cdr * 18},${cy} ${cx + R - 4},${cy + cupW / 2}" fill="#FFF7E6" stroke="#C9A66B" stroke-width="1.2"/>`;
    for (let i = 0; i < fibres; i++) { const y = cy - 16 + i * (32 / Math.max(1, fibres - 1)); s += `<path class="ss-fibre" d="M${cx + R + 4},${y.toFixed(1)} L${W - 8},${(cy + (y - cy) * 1.2).toFixed(1)}" stroke="#E2B76A" stroke-width="1.4"/>`; }
    // cornea, iris, lens, ciliary body
    const ax = cx - R + 4;
    s += `<path d="M${ax + 6},${cy - 66} Q${ax - 46},${cy} ${ax + 6},${cy + 66}" fill="#E9F6FB" stroke="#7FB3CC" stroke-width="3" ${e.cornea === 'oedema' ? 'opacity=".75"' : ''}/>`;
    const irisBow = shallow ? -18 : 0;
    for (const sg of [-1, 1]) {
      s += `<path d="M${ax + 12},${cy + sg * 64} Q${ax + 14 + irisBow},${cy + sg * 40} ${ax + 16 + irisBow / 2},${cy + sg * 14}" stroke="#6B3E1E" stroke-width="7" stroke-linecap="round" fill="none"/>
        <ellipse cx="${ax + 30}" cy="${cy + sg * 62}" rx="10" ry="14" fill="#B05A44" opacity=".8"/>`;
    }
    const lensOp = [0.15, .3, .5, .75, .95][grade] ?? .15, lensCol = e.lens === 'mature' ? '#F4F1E8' : e.lens === 'dense' ? '#B89B62' : '#D9E7EE';
    s += `<ellipse cx="${ax + 34}" cy="${cy}" rx="16" ry="44" fill="${lensCol}" opacity="${e.lens === 'clear' || e.lens === 'iol' ? .55 : lensOp}" stroke="#9BB8C8"/>`;
    if (e.lens === 'iol') s += `<rect x="${ax + 30}" y="${cy - 26}" width="8" height="52" rx="4" fill="#DDEBF2" stroke="#7FA2B8"/>`;
    if (e.chamber === 'hypopyon' || e.chamber === 'hyphaema') s += `<path d="M${ax - 8},${cy + 42} Q${ax + 4},${cy + 58} ${ax + 12},${cy + 62} L${ax + 14},${cy + 42}Z" fill="${e.chamber === 'hypopyon' ? '#EFE3A8' : '#A3151F'}"/>`;
    // drain at the angle, pressure arrows, gauge
    s += `<circle cx="${ax + 8}" cy="${cy - 64}" r="3.5" fill="${c.outflow < .5 ? '#C8323F' : '#0F7B78'}"/><circle cx="${ax + 8}" cy="${cy + 64}" r="3.5" fill="${c.outflow < .5 ? '#C8323F' : '#0F7B78'}"/>`;
    if (hi) for (let i = 0; i < 8; i++) { const a = -1.1 + i * .32, x0 = cx + Math.cos(a) * (R - 18), y0 = cy + Math.sin(a) * (R - 18); s += `<line class="ss-press" x1="${x0.toFixed(1)}" y1="${y0.toFixed(1)}" x2="${(cx + Math.cos(a) * (R + 2)).toFixed(1)}" y2="${(cy + Math.sin(a) * (R + 2)).toFixed(1)}" stroke="#C8323F" stroke-width="2" marker-end="url(#${gid}-ar)" opacity=".7"/>`; }
    s += `</g><g class="ss-aq"></g>`;
    const g = iop === null ? 0 : clamp(iop / 50, 0, 1);
    s += `<g transform="translate(16,18)"><text class="ss-cap" x="0" y="0" text-anchor="start">Eye pressure</text>
      <rect x="0" y="8" width="120" height="10" rx="5" fill="#E6ECEA"/><rect x="${10 / 50 * 120}" y="8" width="${11 / 50 * 120}" height="10" fill="#BFE3D6"/>
      ${iop !== null ? `<circle cx="${g * 120}" cy="13" r="7" fill="${hi ? '#C8323F' : '#0F7B78'}"/><text x="0" y="36" class="ss-val">${iop} mmHg${hi ? ' · drain struggling' : ' · normal flow'}</text>` : '<text x="0" y="36" class="ss-val">not measured</text>'}</g>
      <text class="ss-cap" x="${W - 8}" y="${cy + 42}" text-anchor="end">optic nerve · cup ${fmt(cdr)}</text>
      <text class="ss-cap" x="${ax - 30}" y="${H - 12}" text-anchor="start">cornea · iris · lens</text></svg>`;
    host.innerHTML = `<div class="ss-fig">${s}</div>`;
    const svg = host.querySelector('svg'), aq = svg.querySelector('.ss-aq'), globe = svg.querySelector('.ss-globe');
    const parts = [];
    const spawn = () => ({x: ax + 30, y: cy + (Math.random() < .5 ? -1 : 1) * 54, p: 0, v: .12 + Math.random() * .08, el: null});
    const max = Math.round(14 + (1 - c.outflow) * 40);
    loop(host, (t, dt) => {
      if (parts.length < max && Math.random() < .25) { const p = spawn(); p.el = document.createElementNS(NS, 'circle'); p.el.setAttribute('r', '2.2'); p.el.setAttribute('fill', '#3AA6D0'); aq.appendChild(p.el); parts.push(p); }
      for (let i = parts.length - 1; i >= 0; i--) {
        const p = parts[i], up = p.y < cy;
        p.p += dt * p.v * (p.p > .62 ? c.outflow * 1.6 : 1);
        let x, y;
        if (p.p < .35) { const k = p.p / .35; x = ax + 30 - k * 10; y = cy + (up ? -1 : 1) * (54 - k * 44); }
        else if (p.p < .7) { const k = (p.p - .35) / .35; x = ax + 20 - k * 24; y = cy + (up ? -1 : 1) * (10 + k * (shallow ? 10 : 30)); }
        else { const k = (p.p - .7) / .3; x = ax - 4 + k * 12; y = cy + (up ? -1 : 1) * ((shallow ? 20 : 40) + k * 24); }
        p.el.setAttribute('cx', x.toFixed(1)); p.el.setAttribute('cy', y.toFixed(1));
        if (p.p >= 1) { p.el.remove(); parts.splice(i, 1); }
      }
      if (hi) globe.style.transform = `scale(${1 + Math.sin(t * 2.4) * .006 * (1 + press * 2)})`;
    });
  }

  /* ================================================================== fundus (back of the eye) */
  function fundus(host, e, c, side) {
    stopAll(host);
    if (!c) { host.innerHTML = `<div class="ss-empty">The ${side} eye has not been examined.</div>`; return; }
    const S = 300, m = S / 2, gid = id('fu'), r = e.retina, cdr = e.cdr ?? .3;
    const dx = side === 'right' ? 62 : -62, disc = {x: m + dx, y: m - 4}, mac = {x: m - dx * .15, y: m + 4};
    const swollen = r.papilloedema || r.htn === 4;
    const rand = seeded((side === 'right' ? 7 : 13) + (r.dr.length * 31));
    const away = (x, y) => Math.hypot(x - disc.x, y - disc.y) > 30 && Math.hypot(x - m, y - m) < 128;
    const pts = (n, near = 0) => { const out = []; let k = 0; while (out.length < n && k++ < 500) { const a = rand() * Math.PI * 2, d = near ? rand() * near : 20 + rand() * 105; const x = (near ? mac.x : m) + Math.cos(a) * d, y = (near ? mac.y : m) + Math.sin(a) * d; if (away(x, y)) out.push([x, y]); } return out; };
    let s = svgEl(S, S, 'ss-fundus', `Back of the ${side} eye`);
    s += `<defs><radialGradient id="${gid}-bg" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#E8763F"/><stop offset=".7" stop-color="#C4522B"/><stop offset="1" stop-color="#7A2A16"/></radialGradient>
      <radialGradient id="${gid}-disc"><stop offset="0" stop-color="#FFF1CF"/><stop offset=".6" stop-color="#F7CF8F"/><stop offset="1" stop-color="#E9A46A"/></radialGradient>
      <filter id="${gid}-blur"><feGaussianBlur stdDeviation="${swollen ? 3.2 : .4}"/></filter><filter id="${gid}-s"><feGaussianBlur stdDeviation="1.4"/></filter>
      <clipPath id="${gid}-c"><circle cx="${m}" cy="${m}" r="${m - 4}"/></clipPath></defs>
      <g clip-path="url(#${gid}-c)"><rect width="${S}" height="${S}" fill="url(#${gid}-bg)"/>
      <circle cx="${mac.x}" cy="${mac.y}" r="22" fill="#9B3415" opacity=".55" filter="url(#${gid}-s)"/><circle cx="${mac.x}" cy="${mac.y}" r="3" fill="#F7C08A" opacity=".8"/>`;
    // vessels: four arcades from the disc
    const tx = -Math.sign(dx);
    const arcade = (up, temporal, vein) => {
      const sy = up ? -1 : 1, off = vein ? 4 : -4;
      if (temporal)        // the big arcades sweep around the macula towards the temporal side
        return `M${disc.x},${disc.y + sy * 5} C${disc.x + tx * 30},${disc.y + sy * (52 + off)} ${mac.x + tx * 40},${mac.y + sy * (74 + off)} ${mac.x + tx * 140},${mac.y + sy * (46 + off)}`;
      return `M${disc.x},${disc.y + sy * 5} C${disc.x - tx * 8},${disc.y + sy * (30 + off)} ${disc.x - tx * 34},${disc.y + sy * (64 + off)} ${disc.x - tx * 70},${disc.y + sy * (96 + off)}`;
    };
    const art = r.htn >= 1 ? 1.4 : 2.2;
    for (const up of [true, false]) for (const temp of [true, false]) {
      s += `<path d="${arcade(up, temp, true)}" stroke="#7E1414" stroke-width="3.6" fill="none"/>`;
      s += `<path class="ss-art" d="${arcade(up, temp, false)}" stroke="#D2342C" stroke-width="${art}" fill="none" ${r.htn >= 2 ? 'stroke-dasharray="26 3"' : ''}/>`;
    }
    for (let i = 0; i < 6; i++) { const a = rand() * Math.PI * 2; s += `<path d="M${(mac.x + Math.cos(a) * 60).toFixed(1)},${(mac.y + Math.sin(a) * 60).toFixed(1)} q${(rand() - .5) * 30},${(rand() - .5) * 30} ${(Math.cos(a) * 30).toFixed(1)},${(Math.sin(a) * 30).toFixed(1)}" stroke="#B02A22" stroke-width="1" fill="none" opacity=".7"/>`; }
    // disc and cup
    s += `<g filter="url(#${gid}-blur)"><circle cx="${disc.x}" cy="${disc.y}" r="${swollen ? 28 : 22}" fill="url(#${gid}-disc)"/>${swollen ? '' : `<circle cx="${disc.x}" cy="${disc.y}" r="${(22 * cdr).toFixed(1)}" fill="#FFFBEF" stroke="#E7C89A" stroke-width="1"/>`}</g>`;
    // diabetic changes
    const order = ['none', 'mild', 'moderate', 'severe', 'proliferative'], lvl = order.indexOf(r.dr);
    if (lvl >= 1) for (const [x, y] of pts([0, 6, 10, 14, 16][lvl])) s += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="1.6" fill="#7A0B0B"/>`;
    if (lvl >= 2) for (const [x, y] of pts([0, 0, 6, 14, 16][lvl])) s += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(3 + rand() * 3).toFixed(1)}" fill="#8E0F12" opacity=".9" filter="url(#${gid}-s)"/>`;
    if (lvl >= 2) for (const [x, y] of pts([0, 0, 5, 8, 8][lvl])) s += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(1.6 + rand() * 1.8).toFixed(1)}" fill="#F6E27A"/>`;
    if (lvl >= 3 || r.htn >= 3) for (const [x, y] of pts(lvl >= 3 ? 4 : 3)) s += `<ellipse cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" rx="7" ry="5" fill="#F4F0E3" opacity=".85" filter="url(#${gid}-s)"/>`;
    if (r.htn >= 3) for (const [x, y] of pts(5)) { const a = Math.atan2(y - disc.y, x - disc.x) * 180 / Math.PI; s += `<ellipse cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" rx="8" ry="2.6" transform="rotate(${a.toFixed(0)} ${x.toFixed(1)} ${y.toFixed(1)})" fill="#9A1010" opacity=".85"/>`; }
    if (lvl === 4) {
      s += `<g class="ss-nv">`;
      for (let i = 0; i < 12; i++) { const a = rand() * Math.PI * 2; s += `<path d="M${disc.x},${disc.y} q${(Math.cos(a) * 18).toFixed(1)},${(Math.sin(a) * 6).toFixed(1)} ${(Math.cos(a + .6) * 26).toFixed(1)},${(Math.sin(a + .6) * 26).toFixed(1)}" stroke="#E0453A" stroke-width=".8" fill="none"/>`; }
      s += `</g><path d="M${mac.x - 40},${mac.y + 50} q40,22 80,0 q-40,-12 -80,0Z" fill="#7A0000" opacity=".9"/>`;
    }
    if (r.maculopathy) for (let i = 0; i < 14; i++) { const a = i / 14 * Math.PI * 2; s += `<circle cx="${(mac.x + Math.cos(a) * 26).toFixed(1)}" cy="${(mac.y + Math.sin(a) * 22).toFixed(1)}" r="2.4" fill="#F6E27A"/>`; }
    if (r.amd === 'dry') for (const [x, y] of pts(14, 24)) s += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.2" fill="#F2DE8C" opacity=".9"/>`;
    if (r.amd === 'wet') s += `<ellipse cx="${mac.x}" cy="${mac.y}" rx="20" ry="16" fill="#6C7A55" opacity=".85" filter="url(#${gid}-s)"/><path d="M${mac.x - 22},${mac.y + 6} q22,22 44,0" stroke="#7A0000" stroke-width="6" fill="none" opacity=".8"/>`;
    if (r.detachment) s += `<path class="ss-rd" d="M${m - 140},${m - 150} L${m + 150},${m - 150} L${m + 150},${m - 40} Q${m + 40},${m - 10} ${m - 20},${m - 60} Q${m - 80},${m - 30} ${m - 140},${m - 50}Z" fill="#B9B4AC" opacity=".8"/><path d="M${m - 60},${m - 120} q30,30 0,60 M${m + 40},${m - 120} q30,30 0,50" stroke="#8F8A82" stroke-width="2" fill="none"/>`;
    if (e.lens === 'mature') s += `<rect width="${S}" height="${S}" fill="#F3EFE4" opacity=".92"/><text x="${m}" y="${m}" text-anchor="middle" class="ss-val">No view: mature cataract</text>`;
    else if (c.lens_grade >= 2) s += `<rect width="${S}" height="${S}" fill="#EDE7D6" opacity="${c.lens_grade * .14}"/>`;
    s += `<circle class="ss-glint" cx="${m}" cy="${m}" r="40" fill="#fff" opacity=".07"/></g><circle cx="${m}" cy="${m}" r="${m - 4}" fill="none" stroke="#1C1C1C" stroke-width="8"/></svg>`;
    const chips = [`Cup-to-disc ${fmt(cdr)}${e.cdr === null ? ' (not measured)' : ''}`, r.dr !== 'none' ? `${r.dr} diabetic retinopathy` : '', r.htn ? `Hypertensive grade ${r.htn}` : '', swollen ? 'Swollen disc' : '', r.detachment ? 'Detachment' : '', r.amd !== 'none' ? `${r.amd} AMD` : '', r.maculopathy ? 'Maculopathy' : ''].filter(Boolean);
    host.innerHTML = `<div class="ss-fig ss-fundus-wrap">${s}<div class="ss-chips">${chips.map(x => `<span>${x}</span>`).join('')}</div></div>`;
    const svg = host.querySelector('svg'), artEls = [...svg.querySelectorAll('.ss-art')], glint = svg.querySelector('.ss-glint'), nv = svg.querySelector('.ss-nv');
    loop(host, t => {
      const beat = Math.max(0, Math.sin(t * 7.3)) ** 6;
      artEls.forEach(a => a.setAttribute('stroke-width', (art + beat * .8).toFixed(2)));
      glint.setAttribute('cx', (m + Math.sin(t * .4) * 60).toFixed(1)); glint.setAttribute('cy', (m + Math.cos(t * .33) * 50).toFixed(1));
      if (nv) nv.setAttribute('opacity', (.7 + Math.sin(t * 3) * .3).toFixed(2));
    });
  }

  /* ================================================================== what the patient sees */
  function combine(a, b) {
    if (!a) return b; if (!b) return a;
    return {blur: Math.min(a.blur, b.blur), haze: Math.min(a.haze, b.haze), tint: Math.min(a.tint, b.tint), field: Math.max(a.field, b.field),
      scotoma: Math.min(a.scotoma, b.scotoma), spots: Math.min(a.spots, b.spots), floaters: a.floaters && b.floaters, curtain: Math.min(a.curtain, b.curtain), dark: Math.min(a.dark, b.dark)};
  }
  function vision(host, v, opts = {}) {
    stopAll(host);
    const W = 480, H = 270, gid = id('vs');
    const n = opts.normal || !v ? {blur: 0, haze: 0, tint: 0, field: 1, scotoma: 0, spots: 0, floaters: false, curtain: 0, dark: 0} : v;
    const t = n.tint, R = Math.hypot(W, H) / 2;
    let s = svgEl(W, H, 'ss-vision', opts.label || 'What the patient sees');
    s += `<defs>
      <filter id="${gid}-f" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="${(n.blur * .7).toFixed(2)}"/>
        <feColorMatrix type="matrix" values="${(1 - .1 * t).toFixed(3)} ${(.25 * t).toFixed(3)} 0 0 ${(.08 * t).toFixed(3)}  0 ${(1 - .05 * t).toFixed(3)} ${(.1 * t).toFixed(3)} 0 ${(.04 * t).toFixed(3)}  0 0 ${(1 - .55 * t).toFixed(3)} 0 0  0 0 0 1 0"/></filter>
      <radialGradient id="${gid}-tun" cx="50%" cy="50%" r="${(R).toFixed(0)}" gradientUnits="userSpaceOnUse" fx="${W / 2}" fy="${H / 2}">
        <stop offset="${(n.field * .62).toFixed(3)}" stop-color="#000" stop-opacity="0"/><stop offset="${Math.min(1, n.field * .62 + .16).toFixed(3)}" stop-color="#05070A" stop-opacity=".97"/></radialGradient>
      <radialGradient id="${gid}-sc"><stop offset="0" stop-color="#1E1A16" stop-opacity=".96"/><stop offset=".65" stop-color="#2A241D" stop-opacity=".7"/><stop offset="1" stop-color="#2A241D" stop-opacity="0"/></radialGradient>
      <radialGradient id="${gid}-gl"><stop offset="0" stop-color="#FFFDF0" stop-opacity=".95"/><stop offset="1" stop-color="#FFFDF0" stop-opacity="0"/></radialGradient>
      <linearGradient id="${gid}-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7EC3E8"/><stop offset="1" stop-color="#CDE9F5"/></linearGradient>
    </defs>
    <g filter="url(#${gid}-f)">
      <rect width="${W}" height="${H}" fill="url(#${gid}-sky)"/>
      <circle cx="400" cy="48" r="20" fill="#FFD95A"/>
      <path d="M0,170 Q90,120 190,160 T380,150 T480,160 L480,${H} L0,${H}Z" fill="#9CC36B"/>
      <path d="M0,200 L480,200 L480,${H} L0,${H}Z" fill="#C7A574"/>
      <path d="M180,${H} L240,200 L260,200 L330,${H}Z" fill="#6F6F6F"/><path d="M247,206 L246,214 M252,226 L251,238 M258,248 L257,262" stroke="#F4F4F4" stroke-width="3"/>
      <g transform="translate(60,108)"><rect x="0" y="30" width="78" height="62" fill="#E9D8B8"/><path d="M-8,32 L39,0 L86,32Z" fill="#A4552E"/><rect x="30" y="58" width="18" height="34" fill="#6B4226"/><rect x="8" y="44" width="16" height="14" fill="#7EC3E8"/></g>
      <g transform="translate(330,92)"><rect x="18" y="50" width="16" height="64" fill="#7A5A3C"/><ellipse cx="26" cy="40" rx="44" ry="30" fill="#4F8A3A"/><ellipse cx="8" cy="52" rx="20" ry="14" fill="#5E9C45"/></g>
      <g class="ss-car"><rect x="0" y="0" width="34" height="14" rx="4" fill="#C8323F"/><rect x="6" y="-8" width="20" height="10" rx="3" fill="#C8323F"/><circle cx="8" cy="15" r="4" fill="#222"/><circle cx="27" cy="15" r="4" fill="#222"/></g>
      <g transform="translate(200,60)"><rect x="0" y="0" width="84" height="94" rx="4" fill="#FFFFFF" stroke="#333"/><rect x="38" y="94" width="8" height="40" fill="#555"/>
        <text x="42" y="40" text-anchor="middle" font-size="34" font-weight="700" fill="#111" font-family="Arial">E</text>
        <text x="42" y="62" text-anchor="middle" font-size="16" font-weight="700" fill="#111" font-family="Arial">F P</text>
        <text x="42" y="78" text-anchor="middle" font-size="10" font-weight="700" fill="#111" font-family="Arial">T O Z</text>
        <text x="42" y="88" text-anchor="middle" font-size="6" font-weight="700" fill="#111" font-family="Arial">L P E D</text></g>
      <g transform="translate(150,150)"><circle cx="0" cy="0" r="7" fill="#5B3A26"/><path d="M0,7 L0,34 M0,34 L-7,52 M0,34 L7,52" stroke="#2F3E8C" stroke-width="5"/><path class="ss-wave" d="M0,14 L-12,24 M0,14 L12,2" stroke="#5B3A26" stroke-width="4"/></g>
    </g>
    ${n.haze || t ? `<circle cx="400" cy="48" r="${(30 + n.haze * 90).toFixed(0)}" fill="url(#${gid}-gl)" opacity="${Math.min(.95, .3 + n.haze).toFixed(2)}"/>` : ''}
    <rect width="${W}" height="${H}" fill="#F4F1E6" opacity="${(n.haze * .62).toFixed(2)}"/>
    <g class="ss-gaze">${n.scotoma ? `<circle cx="0" cy="0" r="${(n.scotoma * H).toFixed(0)}" fill="url(#${gid}-sc)"/>` : ''}<g class="ss-spots"></g></g>
    ${n.curtain ? `<path class="ss-curtain" d="" fill="#3A3F45" opacity=".93"/>` : ''}
    ${n.field < 1 ? `<rect width="${W}" height="${H}" fill="url(#${gid}-tun)"/>` : ''}
    <rect width="${W}" height="${H}" fill="#000" opacity="${n.dark}"/>
    </svg>`;
    host.innerHTML = `<div class="ss-fig ss-vision-wrap">${s}</div>`;
    const svg = host.querySelector('svg'), car = svg.querySelector('.ss-car'), gaze = svg.querySelector('.ss-gaze'), spots = svg.querySelector('.ss-spots'), curtain = svg.querySelector('.ss-curtain'), wave = svg.querySelector('.ss-wave');
    const rand = seeded(41);
    for (let i = 0; i < n.spots; i++) { const a = rand() * Math.PI * 2, d = 20 + rand() * 120; spots.insertAdjacentHTML('beforeend', `<ellipse cx="${(Math.cos(a) * d).toFixed(1)}" cy="${(Math.sin(a) * d * .6).toFixed(1)}" rx="${(4 + rand() * 9).toFixed(1)}" ry="${(3 + rand() * 7).toFixed(1)}" fill="#5A0E0E" opacity="${(.55 + rand() * .35).toFixed(2)}"/>`); }
    const floaters = n.floaters ? [...Array(5)].map(() => { const el = document.createElementNS(NS, 'path'); el.setAttribute('d', `M0,0 q${8 + rand() * 10},${-6 + rand() * 12} ${18 + rand() * 18},${rand() * 6}`); el.setAttribute('stroke', '#3A1010'); el.setAttribute('stroke-width', '2.5'); el.setAttribute('fill', 'none'); el.setAttribute('opacity', '.6'); spots.appendChild(el); return {el, x: (rand() - .5) * 200, y: (rand() - .5) * 120, s: .3 + rand() * .6}; }) : [];
    loop(host, tt => {
      car.setAttribute('transform', `translate(${(((tt * 40) % (W + 80)) - 60).toFixed(1)},214)`);
      if (wave) wave.setAttribute('transform', `rotate(${(Math.sin(tt * 5) * 18).toFixed(1)} 0 14)`);
      const gx = W / 2 + Math.sin(tt * .35) * 120, gy = H / 2 + Math.sin(tt * .53) * 50;
      gaze.setAttribute('transform', `translate(${gx.toFixed(1)},${gy.toFixed(1)})`);
      floaters.forEach((f, i) => f.el.setAttribute('transform', `translate(${(f.x + Math.sin(tt * f.s + i) * 30).toFixed(1)},${(f.y + Math.cos(tt * f.s * .8 + i) * 20 + tt * 2 % 30).toFixed(1)})`));
      if (curtain) {
        const h = n.curtain * H * 1.3, w = Math.sin(tt * 1.6) * 6;
        curtain.setAttribute('d', `M0,0 L${W * .75},0 Q${W * .55},${(h * .5 + w).toFixed(1)} ${W * .3},${(h * .8 - w).toFixed(1)} Q${W * .12},${(h + w).toFixed(1)} 0,${(h * .9).toFixed(1)}Z`);
      }
    });
  }

  /* ================================================================== the ear: sound path to the brain */
  function earSection(host, a, c, side) {
    stopAll(host);
    if (!c) { host.innerHTML = `<div class="ss-empty">The ${side} ear has not been examined.</div>`; return; }
    const W = 640, H = 300, gid = id('ea'), tmX = 236, cy = 128;
    const swollen = a.canal === 'otitis_externa', canalH = swollen ? 18 : 30;
    let s = svgEl(W, H, 'ss-ear', `Cross-section of the ${side} ear with sound travelling to the brain`);
    s += `<defs><linearGradient id="${gid}-bm" x1="0" x2="1"><stop offset="0" stop-color="#F4C6C0"/><stop offset="1" stop-color="#F9E0D8"/></linearGradient>
      <clipPath id="${gid}-me"><rect x="${tmX}" y="70" width="88" height="128" rx="26"/></clipPath></defs>`;
    s += `<rect x="0" y="0" width="${W}" height="${H}" fill="#F8EFE6" rx="16"/>
      <path d="M10,30 C80,10 120,80 96,${cy - 36} C82,${cy - 20} 92,${cy + 50} 60,${cy + 110} C30,${cy + 140} 10,${cy + 90} 18,${cy + 50}" fill="#C98B67" stroke="#A86A49" stroke-width="2"/>
      <path d="M92,${cy - canalH / 2} L${tmX},${cy - canalH / 2 + 4} L${tmX},${cy + canalH / 2 - 4} L92,${cy + canalH / 2}Z" fill="#FFF6EE" stroke="${swollen ? '#C8323F' : '#B98563'}" stroke-width="${swollen ? 6 : 2}"/>`;
    if (a.canal === 'wax' || a.canal === 'impacted_wax') s += `<ellipse cx="${tmX - 30}" cy="${cy}" rx="${a.canal === 'wax' ? 9 : 24}" ry="${a.canal === 'wax' ? 7 : canalH / 2 - 2}" fill="#8A5A1F"/>`;
    if (a.canal === 'foreign_body') s += `<circle cx="${tmX - 36}" cy="${cy}" r="11" fill="#2B78C2" stroke="#1B4E80" stroke-width="2"/>`;
    // middle ear, fluid, ossicles, Eustachian tube
    s += `<path d="M${tmX + 40},198 Q${tmX + 30},250 ${tmX - 20},${H - 10}" stroke="#D9B79E" stroke-width="16" fill="none" stroke-linecap="round"/>
      <rect x="${tmX}" y="70" width="88" height="128" rx="26" fill="#EAF4F7" stroke="#B9CDD6" stroke-width="2"/>`;
    if (c.fluid) s += `<g clip-path="url(#${gid}-me)"><rect class="ss-fluid" x="${tmX}" y="${198 - 128 * c.fluid}" width="88" height="${128 * c.fluid}" fill="${a.tm === 'bulging' ? '#E7C34E' : '#E8C27A'}" opacity=".8"/></g>`;
    if (a.tm === 'cholesteatoma') s += `<ellipse cx="${tmX + 34}" cy="92" rx="30" ry="18" fill="#F6F3EA" stroke="#D8D2BF" stroke-width="2"/>`;
    const bow = a.tm === 'bulging' ? -14 : a.tm === 'retracted' ? 12 : 0;
    const hole = a.tm === 'perforation' ? clamp(a.perforation_pct, 5, 90) / 100 * 50 : 0;
    s += `<g class="ss-tm"><path d="M${tmX},${cy - 34} Q${tmX + bow},${cy} ${tmX},${cy + 34}" stroke="${a.tm === 'bulging' ? '#C8323F' : a.tm === 'scarred' ? '#B7B2A5' : '#8C9AA6'}" stroke-width="4" fill="none" ${hole ? `stroke-dasharray="${(34 - hole / 2).toFixed(1)} ${hole.toFixed(1)} 80"` : ''}/></g>`;
    if (a.tm === 'grommet') s += `<rect x="${tmX - 6}" y="${cy + 12}" width="12" height="6" rx="2" fill="#2B78C2"/>`;
    s += `<g class="ss-oss"><path d="M${tmX + 2},${cy + 10} L${tmX + 16},${cy - 28} L${tmX + 30},${cy - 34}" stroke="#E9E2D0" stroke-width="7" stroke-linecap="round" fill="none"/>
      ${a.tm === 'cholesteatoma' ? '' : `<path d="M${tmX + 30},${cy - 34} L${tmX + 48},${cy - 30} L${tmX + 54},${cy - 4}" stroke="#E9E2D0" stroke-width="7" stroke-linecap="round" fill="none"/>`}
      <path d="M${tmX + 54},${cy - 4} L${tmX + 70},${cy - 4} M${tmX + 70},${cy - 14} L${tmX + 70},${cy + 6}" stroke="#E9E2D0" stroke-width="5" stroke-linecap="round" fill="none"/></g>`;
    // inner ear
    const cx = 412, ccy = 150;
    let spiral = `M${cx},${ccy}`;
    for (let i = 0; i <= 60; i++) { const th = i / 60 * Math.PI * 5, r = 4 + i * .62; spiral += ` L${(cx + Math.cos(th) * r).toFixed(1)},${(ccy + Math.sin(th) * r).toFixed(1)}`; }
    s += `<path d="${spiral}" stroke="#E7B3A8" stroke-width="10" fill="none" stroke-linecap="round"/><path d="${spiral}" stroke="#C97A6B" stroke-width="1.5" fill="none"/>
      <ellipse cx="384" cy="70" rx="22" ry="16" fill="none" stroke="#E7B3A8" stroke-width="7"/><ellipse cx="408" cy="58" rx="14" ry="24" fill="none" stroke="#E7B3A8" stroke-width="7"/><ellipse cx="420" cy="82" rx="26" ry="12" fill="none" stroke="#E7B3A8" stroke-width="7"/>
      <path d="M${tmX + 70},${cy - 4} Q360,${cy} ${cx - 30},${ccy}" stroke="#E7B3A8" stroke-width="10" fill="none"/>
      <path class="ss-nerve" d="M${cx + 30},${ccy - 6} C480,120 520,110 ${W - 70},104" stroke="#F2D7A6" stroke-width="10" fill="none" stroke-linecap="round"/>
      <g transform="translate(${W - 66},64)"><path d="M10,40 C-6,10 30,-10 52,8 C70,-4 72,30 56,44 C60,70 20,76 10,40Z" fill="#F1C3CF" stroke="#C78B9A" stroke-width="2"/><circle class="ss-brain" cx="34" cy="34" r="10" fill="#0F7B78" opacity=".15"/></g>`;
    // the uncoiled basilar membrane with its hair cells
    const bx = 330, bw = 280, by = 252;
    s += `<rect x="${bx}" y="${by - 12}" width="${bw}" height="24" rx="10" fill="url(#${gid}-bm)" stroke="#E2A79A"/><path class="ss-bmwave" d="" stroke="#B5473B" stroke-width="2.4" fill="none"/>`;
    for (let i = 0; i < 36; i++) {
      const pos = i / 35, f = 8000 * Math.pow(250 / 8000, pos);
      const near = FREQS.reduce((b, x) => Math.abs(Math.log(+x / f)) < Math.abs(Math.log(+b / f)) ? x : b, FREQS[0]);
      const loss = c.cochlea[near] || 0, gone = seeded(i + 3)() < loss;
      s += `<rect x="${(bx + 6 + pos * (bw - 12)).toFixed(1)}" y="${by - 26}" width="4" height="${gone ? 4 : 12}" rx="2" fill="${gone ? '#B9B2A8' : '#2FA36B'}"/>`;
    }
    s += `<text class="ss-cap" x="${bx}" y="${by + 30}" text-anchor="start">base · high pitch (8 kHz)</text><text class="ss-cap" x="${bx + bw}" y="${by + 30}" text-anchor="end">apex · low pitch (250 Hz)</text>
      <text class="ss-cap" x="${bx + bw / 2}" y="${by - 34}" text-anchor="middle">hair cells${Object.values(c.cochlea).some(x => x > .05) ? ' · grey = damaged' : ''}</text>
      <g class="ss-waves"></g><g class="ss-imp"></g>
      <text class="ss-val ss-freq" x="20" y="${H - 18}" text-anchor="start"></text></svg>`;
    host.innerHTML = `<div class="ss-fig">${s}</div>`;
    const svg = host.querySelector('svg'), wavesG = svg.querySelector('.ss-waves'), tm = svg.querySelector('.ss-tm'), oss = svg.querySelector('.ss-oss'),
      bm = svg.querySelector('.ss-bmwave'), imp = svg.querySelector('.ss-imp'), freqT = svg.querySelector('.ss-freq'), brain = svg.querySelector('.ss-brain'), fluid = svg.querySelector('.ss-fluid');
    const waves = [...Array(4)].map(() => { const el = document.createElementNS(NS, 'path'); el.setAttribute('fill', 'none'); el.setAttribute('stroke', '#0F7B78'); el.setAttribute('stroke-width', '2.5'); wavesG.appendChild(el); return el; });
    const pulses = [];
    const nerve = svg.querySelector('.ss-nerve'), nl = nerve.getTotalLength ? nerve.getTotalLength() : 200;
    let lastFire = 0, shown = '';
    loop(host, (t, dt) => {
      const fi = Math.floor(t / 1.8) % FREQS.length, f = FREQS[fi], lossF = c.cochlea[f] || 0;
      const strength = c.conduct * (1 - lossF);
      const lab = `Playing ${+f >= 1000 ? +f / 1000 + ' kHz' : f + ' Hz'} · ${strength > .7 ? 'heard clearly' : strength > .35 ? 'heard faintly' : strength > .1 ? 'barely heard' : 'not heard'}`;
      if (lab !== shown) { freqT.textContent = lab; shown = lab; }
      waves.forEach((w, i) => {
        const p = ((t * .9 + i / waves.length) % 1), x = 30 + p * (tmX - 40);
        const past = x > tmX - 60 ? 1 - c.block : 1, op = (1 - p * .4) * past;
        w.setAttribute('d', `M${x.toFixed(1)},${cy - 16} Q${(x + 10).toFixed(1)},${cy} ${x.toFixed(1)},${cy + 16}`);
        w.setAttribute('opacity', op.toFixed(2));
      });
      const amp = Math.sin(t * 22) * 3 * Math.min(1.5, c.mobility) * (1 - c.block * .8);
      tm.setAttribute('transform', `translate(${amp.toFixed(2)},0)`);
      oss.setAttribute('transform', `rotate(${(amp * .8).toFixed(2)} ${tmX + 30} ${cy - 34})`);
      if (fluid) fluid.setAttribute('transform', `translate(0,${(Math.sin(t * 1.4) * 1.5).toFixed(2)})`);
      const pos = FREQS.length - 1 - fi, peak = bx + 6 + (pos / (FREQS.length - 1)) * (bw - 12);
      let d = '';
      for (let x = bx + 4; x <= bx + bw - 4; x += 4) {
        const env = Math.exp(-((x - peak) ** 2) / (2 * 26 ** 2)) * (x < peak ? 1 : 1);
        d += `${d ? 'L' : 'M'}${x},${(by - Math.sin(x * .16 - t * 14) * 8 * env * c.conduct).toFixed(1)}`;
      }
      bm.setAttribute('d', d);
      if (strength > .05 && t - lastFire > .45 / strength) {
        lastFire = t;
        const el = document.createElementNS(NS, 'circle'); el.setAttribute('r', '4'); el.setAttribute('fill', '#0F7B78'); imp.appendChild(el); pulses.push({el, p: 0});
      }
      for (let i = pulses.length - 1; i >= 0; i--) {
        const q = pulses[i]; q.p += dt * .9;
        if (nerve.getPointAtLength) { const pt = nerve.getPointAtLength(q.p * nl); q.el.setAttribute('cx', pt.x.toFixed(1)); q.el.setAttribute('cy', pt.y.toFixed(1)); }
        if (q.p >= 1) { q.el.remove(); pulses.splice(i, 1); brain.setAttribute('opacity', '.75'); }
      }
      brain.setAttribute('opacity', Math.max(.12, (+brain.getAttribute('opacity') || .15) - dt * .8).toFixed(2));
    });
  }

  /* ================================================================== otoscope view */
  function otoscope(host, a, c, side) {
    if (!c) { host.innerHTML = `<div class="ss-empty">Not examined.</div>`; return; }
    const S = 240, m = S / 2, gid = id('ot'), right = side === 'right';
    const lr = right ? 1 : -1;                                    // cone of light: 5 o'clock right ear, 7 o'clock left ear
    const tmCol = {normal: '#C9C3BA', retracted: '#BDB7AE', effusion: '#D9A85E', bulging: '#D4483C', perforation: '#C9C3BA', cholesteatoma: '#C9C3BA', grommet: '#C9C3BA', scarred: '#CFCAC0'}[a.tm];
    const narrow = a.canal === 'otitis_externa' ? 34 : 0;
    let s = svgEl(S, S, 'ss-oto', `Otoscope view of the ${side} ear drum`);
    s += `<defs><radialGradient id="${gid}-tm" cx="45%" cy="45%" r="60%"><stop offset="0" stop-color="#F2EEE8"/><stop offset="1" stop-color="${tmCol}"/></radialGradient><clipPath id="${gid}-c"><circle cx="${m}" cy="${m}" r="${m - 10 - narrow}"/></clipPath></defs>
      <circle cx="${m}" cy="${m}" r="${m - 2}" fill="#1A1A1A"/><circle cx="${m}" cy="${m}" r="${m - 10}" fill="${narrow ? '#D15A4E' : '#E6B9A0'}"/>
      <g clip-path="url(#${gid}-c)"><ellipse cx="${m}" cy="${m}" rx="78" ry="74" fill="url(#${gid}-tm)" stroke="#B0A89C" stroke-width="2"/>`;
    if (a.tm !== 'bulging') s += `<path d="M${m - 4 * lr},${m - 50} L${m + 6 * lr},${m + 4}" stroke="${a.tm === 'retracted' ? '#F7F3EC' : '#EDE6DA'}" stroke-width="${a.tm === 'retracted' ? 7 : 5}" stroke-linecap="round"/>`;
    if (['normal', 'scarred', 'grommet'].includes(a.tm)) s += `<path class="ss-cone" d="M${m + 8 * lr},${m + 8} L${m + 48 * lr},${m + 50} L${m + 30 * lr},${m + 60}Z" fill="#FFFFFF" opacity=".9"/>`;
    if (a.tm === 'effusion') s += `<path d="M${m - 70},${m + 4} Q${m},${m - 8} ${m + 70},${m + 4}" stroke="#7A5420" stroke-width="2" fill="none"/><circle cx="${m - 20}" cy="${m - 20}" r="6" fill="none" stroke="#F3E2C0" stroke-width="1.5"/><circle cx="${m + 26}" cy="${m - 34}" r="4" fill="none" stroke="#F3E2C0" stroke-width="1.5"/>`;
    if (a.tm === 'bulging') s += `<ellipse cx="${m}" cy="${m}" rx="60" ry="56" fill="#E06A52" opacity=".55"/><ellipse cx="${m - 10}" cy="${m - 10}" rx="26" ry="20" fill="#F3D27A" opacity=".55"/>`;
    if (a.tm === 'perforation') { const r = 10 + a.perforation_pct * .55; s += `<ellipse cx="${m - 14 * lr}" cy="${m + 18}" rx="${r.toFixed(1)}" ry="${(r * .85).toFixed(1)}" fill="#3B1C14"/>`; }
    if (a.tm === 'cholesteatoma') s += `<path d="M${m - 40},${m - 64} Q${m},${m - 30} ${m + 36},${m - 66}" fill="#F7F5EE" stroke="#D9D3C2" stroke-width="2"/><circle cx="${m - 6}" cy="${m - 56}" r="4" fill="#E9E2CF"/>`;
    if (a.tm === 'grommet') s += `<circle cx="${m + 26 * lr}" cy="${m - 16}" r="9" fill="#2B78C2"/><circle cx="${m + 26 * lr}" cy="${m - 16}" r="4" fill="#0E2C47"/>`;
    if (a.tm === 'scarred') s += `<path d="M${m - 50},${m + 20} q14,-16 26,0 q-10,14 -26,0Z M${m + 30},${m - 30} q12,-10 22,2 q-10,12 -22,-2Z" fill="#FAF8F2"/>`;
    s += `</g>`;
    if (a.canal === 'wax') s += `<path d="M${m + 40},${m + 70} q30,-20 50,-60 q10,30 -20,70Z" fill="#8A5A1F"/>`;
    if (a.canal === 'impacted_wax') s += `<circle cx="${m}" cy="${m}" r="${m - 16}" fill="#7A4E1A"/><path d="M${m - 40},${m - 30} q30,-20 70,6" stroke="#9C6A2A" stroke-width="6" fill="none"/>`;
    if (a.canal === 'foreign_body') s += `<circle cx="${m - 8}" cy="${m + 6}" r="26" fill="#2B78C2" stroke="#1B4E80" stroke-width="3"/><ellipse cx="${m - 16}" cy="${m - 4}" rx="8" ry="5" fill="#A9CFF0"/>`;
    if (a.discharge === 'purulent' || a.discharge === 'mucoid') s += `<path class="ss-pus" d="M${m - 60},${m + 70} q20,-14 40,4 q-14,22 -40,-4Z" fill="${a.discharge === 'purulent' ? '#E5CF5E' : '#EDEAD0'}" opacity=".95"/>`;
    if (a.discharge === 'bloody') s += `<path d="M${m - 60},${m + 70} q20,-14 40,4 q-14,22 -40,-4Z" fill="#8E0F12"/>`;
    s += `</svg>`;
    host.innerHTML = `<div class="ss-fig ss-oto-wrap">${s}<span class="ss-cap">${right ? 'Right' : 'Left'} ear · ${({normal: 'normal drum, cone of light', retracted: 'retracted, landmarks prominent', effusion: 'amber fluid and bubbles behind the drum', bulging: 'red bulging drum, landmarks lost', perforation: `${a.perforation_pct}% perforation`, cholesteatoma: 'white debris in the attic', grommet: 'grommet in the drum', scarred: 'white scars (tympanosclerosis)'})[a.tm]}</span></div>`;
  }

  /* ================================================================== audiogram */
  const AUD = {W: 470, H: 330, x0: 52, y0: 30, w: 360, h: 270};
  const fx = f => AUD.x0 + FREQS.indexOf(String(f)) / (FREQS.length - 1) * AUD.w;
  const dy = db => AUD.y0 + (db + 10) / 130 * AUD.h;
  function audiogram(host, data, computed, opts = {}) {
    const {W, H, x0, y0, w, h} = AUD;
    const bands = [[-10, 20, '#FFFFFF'], [20, 35, '#F3F8F1'], [35, 50, '#FFF7E5'], [50, 65, '#FDEEDC'], [65, 80, '#FBE3D8'], [80, 95, '#F7D6D6'], [95, 120, '#EFC9CF']];
    let s = svgEl(W, H, 'ss-aud', 'Audiogram: hearing thresholds for both ears');
    s += bands.map(([a, b, col], i) => `<rect x="${x0}" y="${dy(a)}" width="${w}" height="${dy(b) - dy(a)}" fill="${col}"/><text x="${x0 + w + 6}" y="${((dy(a) + dy(b)) / 2 + 4).toFixed(1)}" class="ss-cap" text-anchor="start">${['Normal', 'Mild', 'Moderate', 'Mod. severe', 'Severe', 'Profound', 'Complete'][i]}</text>`).join('');
    for (let db = -10; db <= 120; db += 10) s += `<line x1="${x0}" x2="${x0 + w}" y1="${dy(db)}" y2="${dy(db)}" stroke="#DCE4E0"/><text x="${x0 - 8}" y="${dy(db) + 4}" class="ss-cap" text-anchor="end">${db}</text>`;
    for (const f of FREQS) s += `<line x1="${fx(f)}" x2="${fx(f)}" y1="${y0}" y2="${y0 + h}" stroke="#DCE4E0"/><text x="${fx(f)}" y="${y0 - 10}" class="ss-cap" text-anchor="middle">${+f >= 1000 ? +f / 1000 + 'k' : f}</text>`;
    s += `<text x="12" y="${y0 + h / 2}" class="ss-cap" transform="rotate(-90 12 ${y0 + h / 2})" text-anchor="middle">Hearing level (dB HL) · louder needed ↓</text>`;
    const col = {right: '#C8323F', left: '#2B59C3'};
    for (const side of SIDES) {
      const a = data.ears[side];
      if (!a.examined) continue;
      const pts = FREQS.filter(f => a.ac[f] !== undefined).map(f => [fx(f), dy(a.ac[f])]);
      if (pts.length > 1) s += `<path class="ss-line" d="M${pts.map(p => p.join(',')).join(' L')}" stroke="${col[side]}" stroke-width="2.4" fill="none" ${side === 'left' ? 'stroke-dasharray="6 4"' : ''}/>`;
      for (const f of FREQS) if (a.ac[f] !== undefined) {
        const X = fx(f), Y = dy(a.ac[f]);
        s += side === 'right' ? `<circle cx="${X}" cy="${Y}" r="7" fill="#fff" stroke="${col.right}" stroke-width="2.4"/>` : `<path d="M${X - 6},${Y - 6} L${X + 6},${Y + 6} M${X + 6},${Y - 6} L${X - 6},${Y + 6}" stroke="${col.left}" stroke-width="2.6"/>`;
      }
      for (const f of PTA_FREQS) if (a.bc[f] !== undefined) {
        const X = fx(f) + (side === 'right' ? -12 : 12), Y = dy(a.bc[f]);
        s += `<path d="${side === 'right' ? `M${X + 5},${Y - 7} L${X - 4},${Y} L${X + 5},${Y + 7}` : `M${X - 5},${Y - 7} L${X + 4},${Y} L${X - 5},${Y + 7}`}" stroke="${col[side]}" stroke-width="2.4" fill="none"/>`;
      }
    }
    s += `<line class="ss-hair" x1="0" x2="0" y1="${y0}" y2="${y0 + h}" stroke="#0F2C3F" stroke-dasharray="3 3" opacity="0"/><rect class="ss-hit" x="${x0 - 20}" y="${y0}" width="${w + 40}" height="${h}" fill="transparent"/>
      <text class="ss-val ss-hint" x="${x0}" y="${H - 8}" text-anchor="start">${opts.onSet ? 'Click the chart to enter a threshold for the chosen ear.' : ''}</text></svg>`;
    host.innerHTML = `<div class="ss-fig">${s}<div class="ss-aud-key"><span><i style="border-color:#C8323F" class="o"></i>Right air</span><span><b style="color:#2B59C3">✕</b>Left air</span><span><b style="color:#C8323F">&lt;</b>Right bone</span><span><b style="color:#2B59C3">&gt;</b>Left bone</span></div></div>`;
    const svg = host.querySelector('svg');
    if (!reduce) svg.querySelectorAll('.ss-line').forEach(p => { const L = p.getTotalLength ? p.getTotalLength() : 0; if (!L) return; p.style.strokeDasharray = p.getAttribute('stroke-dasharray') ? '' : L; p.style.strokeDashoffset = L; p.getBoundingClientRect(); p.style.transition = 'stroke-dashoffset .9s ease'; p.style.strokeDashoffset = 0; });
    if (opts.onSet) {
      const hit = svg.querySelector('.ss-hit'), hair = svg.querySelector('.ss-hair'), hint = svg.querySelector('.ss-hint');
      const at = ev => {
        const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
        const p = pt.matrixTransform(svg.getScreenCTM().inverse());
        const i = clamp(Math.round((p.x - x0) / w * (FREQS.length - 1)), 0, FREQS.length - 1);
        const db = clamp(Math.round(((p.y - y0) / h * 130 - 10) / 5) * 5, -10, 120);
        return {freq: FREQS[i], db};
      };
      hit.addEventListener('mousemove', ev => { const r = at(ev); hair.setAttribute('x1', fx(r.freq)); hair.setAttribute('x2', fx(r.freq)); hair.setAttribute('opacity', '.6'); hint.textContent = `${+r.freq >= 1000 ? +r.freq / 1000 + ' kHz' : r.freq + ' Hz'} · ${r.db} dB — click to set`; });
      hit.addEventListener('mouseleave', () => hair.setAttribute('opacity', '0'));
      hit.addEventListener('click', ev => opts.onSet(at(ev)));
    }
  }

  /* ================================================================== hear it as the patient does */
  let audio = null;
  function playHearing(thresholds, {tinnitus = false} = {}) {
    stopSound();
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    const ctx = new AC(), master = ctx.createGain();
    master.gain.value = .9; master.connect(ctx.destination);
    const th = f => {                                                   // threshold at any pitch, interpolated on the audiogram
      if (!thresholds) return 0;
      const known = FREQS.filter(k => thresholds[k] !== undefined).map(k => [+k, thresholds[k]]);
      if (!known.length) return 0;
      if (f <= known[0][0]) return known[0][1];
      for (let i = 1; i < known.length; i++) if (f <= known[i][0]) { const [f0, a] = known[i - 1], [f1, b] = known[i]; return a + (b - a) * Math.log(f / f0) / Math.log(f1 / f0); }
      return known[known.length - 1][1];
    };
    const gainFor = f => Math.pow(10, -Math.max(0, th(f) - 10) / 20);
    const notes = [262, 392, 523, 784, 1047, 1568, 2093, 3136, 4186, 6272, 4186, 2093, 1047, 523];
    let t = ctx.currentTime + .05;
    for (const f of notes) {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'sine'; o.frequency.value = f; o.connect(g); g.connect(master);
      const peak = .16 * gainFor(f);
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(Math.max(.0002, peak), t + .03); g.gain.exponentialRampToValueAtTime(.0001, t + .3);
      o.start(t); o.stop(t + .32); t += .26;
    }
    // a few "syllables" of speech-like noise in three pitch bands
    const len = 1.6, buf = ctx.createBuffer(1, ctx.sampleRate * len, ctx.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    for (const [fc, q] of [[500, 3], [1500, 4], [3200, 4]]) {
      const src = ctx.createBufferSource(), bp = ctx.createBiquadFilter(), g = ctx.createGain();
      src.buffer = buf; bp.type = 'bandpass'; bp.frequency.value = fc; bp.Q.value = q;
      src.connect(bp); bp.connect(g); g.connect(master);
      const peak = .5 * gainFor(fc);
      g.gain.setValueAtTime(0, t + .2);
      for (let k = 0; k < 6; k++) { const s0 = t + .2 + k * .25; g.gain.linearRampToValueAtTime(peak, s0 + .06); g.gain.linearRampToValueAtTime(peak * .05, s0 + .2); }
      src.start(t + .2); src.stop(t + .2 + len);
    }
    if (tinnitus) { const o = ctx.createOscillator(), g = ctx.createGain(); o.frequency.value = 6000; g.gain.value = .012; o.connect(g); g.connect(master); o.start(); o.stop(t + 1.9); }
    audio = ctx;
    setTimeout(() => { if (audio === ctx) stopSound(); }, (t - ctx.currentTime + 2.2) * 1000);
    return ctx;
  }
  function stopSound() { if (audio) { try { audio.close(); } catch (e) { /* ignore */ } audio = null; } }

  window.MFSenses = {compute, eyesFront, eyeSection, fundus, vision, combine, earSection, otoscope, audiogram, playHearing, stopSound, stopAll,
    FREQS, PTA_FREQS, LOGMAR, rnd};
  if (typeof module !== 'undefined') module.exports = window.MFSenses;
})();
