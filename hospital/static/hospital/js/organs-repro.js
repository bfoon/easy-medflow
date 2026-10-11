/* Reproductive pop-out with tabs.
   Women: Pregnancy (3D, when pregnant), Organs (womb, tubes, ovaries, cervix, vagina) and Cycle (organs-anatomy.js view).
   Men: Organs (bladder, prostate, seminal vesicles, vas deferens, urethra, penis, testis) and Prostate (organs-anatomy.js view).
   Findings come from window.MF_ANATOMY.repro (results, scans, diagnoses). Clinical teaching illustrations only. */
(() => {
  'use strict';
  const ART = window.__MF_ART, H = (window.MedFlowOrgans || {}).helpers;
  if (!ART || !H) return;
  const {part} = H;
  const original = ART.reproductive;
  const SH = id => `<filter id="${id}" filterUnits="userSpaceOnUse" x="0" y="0" width="340" height="300"><feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#5a2a32" flood-opacity=".3"/></filter>`;

  /* ------------------------------------------------------------------ female organs (front view) */
  function female(R) {
    const P = R.pregnancy, ect = P && P.ectopic, preg = P && !ect;
    const big = preg ? Math.min(1.5, 1 + P.weeks / 40) : 1;
    const ut = `M170,${150 - 52 * big} C${170 + 50 * big},${150 - 54 * big} ${170 + 52 * big},${150 + 6 * big} ${170 + 26},${150 + 34} L${170 + 14},178 L${170 - 14},178 L${170 - 26},${150 + 34} C${170 - 52 * big},${150 + 6 * big} ${170 - 50 * big},${150 - 54 * big} 170,${150 - 52 * big}Z`;
    const tube = (dir) => `M${170 + 34 * dir * big},${118 - 14 * big} C${170 + 64 * dir},${96} ${170 + 92 * dir},${100} ${170 + 104 * dir},${122}`;
    const fimb = dir => Array.from({length: 6}, (_, i) => { const a = (dir < 0 ? Math.PI : 0) + (-1 + i * .4) * dir; return `<path d="M${170 + 104 * dir},122 l${(Math.cos(a) * 9).toFixed(1)},${(Math.sin(a) * 9).toFixed(1)}" stroke="#E7A3B4" stroke-width="2.4" stroke-linecap="round"/>`; }).join('');
    const ovary = (dir) => `<ellipse cx="${170 + 96 * dir}" cy="140" rx="${R.cyst && dir > 0 ? 24 : 14}" ry="${R.cyst && dir > 0 ? 20 : 9}" fill="url(#rp-ov)" stroke="#C98E86" filter="url(#rp-sh)"/>` +
      (R.cyst && dir > 0 ? `<ellipse cx="${170 + 96 * dir}" cy="140" rx="16" ry="13" fill="#E8F2F6" opacity=".85" class="rp-cyst"/>` :
        Array.from({length: 4}, (_, i) => `<circle cx="${170 + 96 * dir - 7 + i * 5}" cy="${138 + (i % 2) * 4}" r="${1.6 + (i % 3)}" fill="#FBEAD8" class="rp-follicle" style="animation-delay:${i * .5}s"/>`).join(''));
    const fibroids = R.fibroids ? [[150, 110, 9], [196, 128, 12], [176, 92, 7]].map(([x, y, r]) => `<circle cx="${x}" cy="${y}" r="${r}" fill="#D9A3A0" stroke="#A86A68" class="rp-fibroid"/>`).join('') : '';
    const ectSac = ect ? (() => { const dir = ect.side === 'left' ? -1 : 1, x = 170 + 78 * dir, y = 104; return `<circle cx="${x}" cy="${y}" r="11" fill="#F7E3C8" stroke="#C8323F" stroke-width="2" class="rp-ectopic"/><circle cx="${x}" cy="${y}" r="3" fill="#C8323F" class="rp-embryo"/>`; })() : '';
    const baby = preg ? `<g transform="translate(170,${132 - 6 * big}) scale(${(.55 + P.weeks / 60).toFixed(2)})"><ellipse cx="0" cy="0" rx="30" ry="34" fill="#DDEFF6" opacity=".8"/>
      <circle cx="-6" cy="-16" r="11" fill="#F0B9A9"/><path d="M-12,-6 C-24,8 -16,28 0,30 C16,31 22,16 16,2 C12,-6 2,-10 -12,-6Z" fill="#F0B9A9"/><circle cx="2" cy="4" r="2.4" fill="#C8323F" class="rp-fhr" style="animation-duration:${(60 / (P.fhr || 140)).toFixed(2)}s"/></g>` : '';
    return `<svg viewBox="0 0 340 290" class="oa rp rp-f"><defs>${SH('rp-sh')}
      <radialGradient id="rp-ut" cx="45%" cy="35%" r="70%"><stop offset="0" stop-color="#F2B5BE"/><stop offset=".7" stop-color="#DC8592"/><stop offset="1" stop-color="#B85A6B"/></radialGradient>
      <radialGradient id="rp-ov" cx="40%" cy="35%" r="70%"><stop offset="0" stop-color="#FBE3D6"/><stop offset="1" stop-color="#E5B3A6"/></radialGradient>
      <linearGradient id="rp-vag" x1="0" x2="1"><stop offset="0" stop-color="#C96F80"/><stop offset=".5" stop-color="#E8A3B0"/><stop offset="1" stop-color="#C96F80"/></linearGradient></defs>
      ${part('tubes', 'Fallopian tubes: carry the egg from the ovary to the womb; fertilisation happens here.' + (R.pid ? ' Shown inflamed: pelvic inflammatory disease.' : ''),
        `<g class="${R.pid ? 'rp-inflamed' : ''}"><path d="${tube(-1)}" stroke="#E7A3B4" stroke-width="7" fill="none" stroke-linecap="round" filter="url(#rp-sh)"/><path d="${tube(1)}" stroke="#E7A3B4" stroke-width="7" fill="none" stroke-linecap="round" filter="url(#rp-sh)"/>${fimb(-1)}${fimb(1)}</g>`)}
      ${part('ovaries', R.cyst ? 'Ovaries: the right one has a fluid-filled cyst.' : 'Ovaries: hold the eggs and make oestrogen and progesterone; a follicle ripens each month.', `<g>${ovary(-1)}${ovary(1)}</g>`)}
      ${part('uterus', preg ? `Womb (uterus): enlarged by a ${P.weeks}-week pregnancy. Open the Pregnancy tab to see the baby in 3D.` : 'Womb (uterus): a muscular organ whose lining (endometrium) builds up each month and is shed as a period.',
        `<g><path d="${ut}" fill="url(#rp-ut)" stroke="#B85A6B" filter="url(#rp-sh)"/><path d="M170,${150 - 40 * big} C${170 + 30 * big},${150 - 40 * big} ${170 + 28 * big},${150 + 2 * big} 170,${150 + 22}" stroke="#F7CFD6" stroke-width="5" fill="none" opacity=".7"/>${fibroids}${baby}</g>`)}
      ${part('cervix', 'Cervix: the neck of the womb, opening into the vagina; screened for cancer with a smear test.', '<rect x="158" y="176" width="24" height="16" rx="7" fill="#D27685" stroke="#B85A6B"/>')}
      ${part('vagina', 'Vagina: the muscular canal from the cervix to the outside; the birth canal in childbirth.', '<path d="M160,192 L156,262 Q170,270 184,262 L180,192Z" fill="url(#rp-vag)" stroke="#B85A6B" filter="url(#rp-sh)"/>')}
      ${ectSac}
      ${ect ? `<text x="${ect.side === 'left' ? 30 : 230}" y="84" class="sk-lbl hot">Ectopic pregnancy</text>` : ''}${R.fibroids ? '<text x="16" y="40" class="sk-lbl hot">Fibroids</text>' : ''}${R.pid ? '<text x="16" y="56" class="sk-lbl hot">Tubes inflamed</text>' : ''}</svg>`;
  }

  /* ------------------------------------------------------------------ male organs (side view) */
  function male(R) {
    const enlarged = R.prostate, pr = enlarged ? 1.45 : 1;
    const flowDur = enlarged ? 3.6 : 1.8;
    const urethra = 'M150,118 C150,140 152,150 156,160 C166,186 196,196 222,194 C250,192 276,186 300,182';
    const drops = Array.from({length: enlarged ? 3 : 6}, (_, i) => `<circle r="2.2" fill="#F2D27A"><animateMotion dur="${flowDur}s" begin="-${(i * flowDur / (enlarged ? 3 : 6)).toFixed(2)}s" repeatCount="indefinite" path="${urethra}"/></circle>`).join('');
    return `<svg viewBox="0 0 340 260" class="oa rp rp-m"><defs>${SH('rp-shm')}
      <radialGradient id="rp-bl" cx="45%" cy="35%" r="70%"><stop offset="0" stop-color="#FBE6A6"/><stop offset="1" stop-color="#E2BF5C"/></radialGradient>
      <radialGradient id="rp-pr" cx="45%" cy="35%" r="70%"><stop offset="0" stop-color="#E8A898"/><stop offset="1" stop-color="#B86A5C"/></radialGradient>
      <radialGradient id="rp-te" cx="40%" cy="35%" r="70%"><stop offset="0" stop-color="#F6D3C6"/><stop offset="1" stop-color="#D99C8C"/></radialGradient>
      <linearGradient id="rp-pe" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#E7B39F"/><stop offset=".5" stop-color="#D69A86"/><stop offset="1" stop-color="#C08470"/></linearGradient></defs>
      ${part('bladder', 'Bladder: stores urine before it leaves through the urethra.', '<path d="M110,70 C110,36 190,36 190,70 C192,104 172,120 150,120 C128,120 108,104 110,70Z" fill="url(#rp-bl)" stroke="#C9A33F" filter="url(#rp-shm)"/>')}
      ${part('vesicles', 'Seminal vesicles: glands behind the bladder that make most of the fluid in semen.', '<path d="M178,92 C196,84 210,92 206,104 C200,112 186,108 180,102Z" fill="#E7C2A0" stroke="#BB9370"/>')}
      ${part('prostate', enlarged ? `Prostate: enlarged${R.psa ? ` (PSA ${R.psa} ng/mL)` : ''}. It squeezes the urethra, so urine flows weakly; a raised PSA needs follow-up.` : 'Prostate: a walnut-sized gland around the urethra below the bladder; adds fluid to semen.',
        `<ellipse cx="152" cy="${132 + 2 * pr}" rx="${18 * pr}" ry="${14 * pr}" fill="url(#rp-pr)" stroke="#9C5446" filter="url(#rp-shm)" class="${enlarged ? 'rp-hot' : ''}"/>`)}
      ${part('vas', 'Vas deferens: carries sperm from the testis up and over the bladder to the urethra.', '<path d="M236,230 C246,200 238,150 214,118 C200,98 186,96 176,104" stroke="#D9B48F" stroke-width="3" fill="none"/>')}
      ${part('penis', 'Penis: contains the urethra, which carries urine and semen out of the body.', '<path d="M196,184 C230,176 268,170 300,172 C316,173 318,196 300,198 C268,200 230,206 200,206Z" fill="url(#rp-pe)" stroke="#A86F5C" filter="url(#rp-shm)"/><path d="M296,172 C316,170 324,186 316,196 C310,202 298,200 296,198Z" fill="#D88E80" stroke="#A86F5C"/>')}
      ${part('testis', 'Testis and epididymis: make sperm and testosterone; sperm mature in the epididymis.', '<ellipse cx="236" cy="236" rx="22" ry="17" fill="url(#rp-te)" stroke="#B87F70" filter="url(#rp-shm)"/><path d="M252,224 C262,232 260,248 248,252" stroke="#C98E80" stroke-width="5" fill="none" stroke-linecap="round"/>')}
      ${part('urethra', enlarged ? 'Urethra: narrowed by the enlarged prostate, so the urine stream is slow and weak.' : 'Urethra: the tube that carries urine from the bladder to the outside.',
        `<g><path d="${urethra}" stroke="#F4D9A0" stroke-width="${enlarged ? 2 : 3.4}" fill="none"/>${drops}</g>`)}
      ${enlarged ? '<text x="16" y="40" class="sk-lbl hot">Prostate enlarged</text>' : ''}</svg>`;
  }

  /* ------------------------------------------------------------------ 3D pregnancy tab and its 2D fallback */
  const preg3d = P => `<div class="w3d-wrap"><div class="w3d"><canvas></canvas><div class="w3d-info"><b>${P.weeks} weeks</b><span>Fetal heart ${P.fhr}/min</span>${P.anaemia ? '<span class="warn">Mother: low haemoglobin</span>' : ''}${P.bp ? `<span>BP ${P.bp}</span>` : ''}</div>
    <div class="h3d-tools"><button type="button" data-w="reset" title="Reset view"><i class="bi bi-arrow-counterclockwise"></i></button></div>
    <div class="h3d-hint">Drag to rotate · scroll or pinch to zoom</div><div class="h3d-loading"><i class="bi bi-heart-pulse"></i> Building 3D view…</div></div>
    <p class="small muted mt-2 mb-0">${P.weeks < 10 ? 'Early pregnancy: the embryo in its gestational sac.' : `At ${P.weeks} weeks the baby is curled in the amniotic fluid; the cord links it to the placenta on the womb wall.`}</p></div>`;
  const preg2d = P => `<svg viewBox="0 0 340 260" class="oa rp"><ellipse cx="170" cy="130" rx="110" ry="118" fill="#E8A3AE" opacity=".55"/><ellipse cx="170" cy="130" rx="96" ry="104" fill="#DDEFF6"/>
    <path d="M250,80 q14,40 0,80" stroke="#8E2A35" stroke-width="16" fill="none" stroke-linecap="round"/>
    <g transform="translate(170,136) scale(${(.9 + P.weeks / 40).toFixed(2)})"><circle cx="-10" cy="-30" r="22" fill="#F0B9A9"/><path d="M-22,-10 C-44,14 -30,52 0,58 C30,60 42,30 30,4 C22,-12 4,-18 -22,-10Z" fill="#F0B9A9"/>
    <circle cx="2" cy="6" r="4" fill="#C8323F" class="rp-fhr" style="animation-duration:${(60 / (P.fhr || 140)).toFixed(2)}s"/><path d="M2,22 C30,18 50,-10 70,-30" stroke="#E6D3B3" stroke-width="5" fill="none"/></g></svg>`;

  ART.reproductive = r => {
    const A = window.MF_ANATOMY || {}, R = A.repro || {};
    const base = original ? original(r) : {svg: '', notes: [], parts: {}};
    const isMale = R.sex === 'M';
    const P = R.pregnancy;
    const tabs = isMale ? [['organs', 'Organs', male(R)], ['prostate', 'Prostate', base.svg]]
      : [...(P && !P.ectopic ? [['preg', 'Pregnancy 3D', preg3d(P)]] : []), ['organs', 'Organs', female(R)], ['cycle', 'Cycle', base.svg]];
    const notes = (base.notes || []).filter(n => !(P && (P.weeks >= 12 || P.ectopic) && /early pregnancy/i.test(n)));   // the cycle view's own note would contradict this
    if (P) notes.unshift(P.ectopic ? `Ectopic pregnancy in the ${P.ectopic.side} tube: an emergency, as the tube can rupture.` : `Pregnancy, ${P.weeks} weeks · fetal heart ${P.fhr}/min`);
    if (R.prostate) notes.unshift(`Prostate enlarged${R.psa ? ` · PSA ${R.psa} ng/mL` : ''}`);
    if (R.fibroids) notes.unshift('Fibroids: benign muscle growths in the womb wall');
    return {
      svg: `<div class="sk-tabs rp-tabs" role="tablist">${tabs.map(([k, l], i) => `<button type="button" role="tab" data-rp="${k}" class="${i === 0 ? 'on' : ''}">${l}</button>`).join('')}</div>` +
        tabs.map(([k, , html], i) => `<div class="rp-pane" data-pane="${k}" ${i === 0 ? '' : 'hidden'}>${html}</div>`).join(''),
      notes: notes.slice(0, 7),
      parts: {...(base.parts || {}), uterus: 'Womb (uterus).', tubes: 'Fallopian tubes.', ovaries: 'Ovaries.', cervix: 'Cervix.', vagina: 'Vagina.', bladder: 'Bladder.',
              prostate: 'Prostate.', vesicles: 'Seminal vesicles.', vas: 'Vas deferens.', penis: 'Penis.', testis: 'Testis.', urethra: 'Urethra.'},
      mount: fig => {
        let started = false;
        const start = () => {
          const box = fig.querySelector('.w3d'); if (!box || started) return; started = true;
          if (window.MFWomb3D) window.MFWomb3D.mount(box, P, () => { box.closest('.w3d-wrap').outerHTML = preg2d(P); });
          else box.closest('.w3d-wrap').outerHTML = preg2d(P);
        };
        fig.querySelectorAll('[data-rp]').forEach(b => b.addEventListener('click', () => {
          fig.querySelectorAll('[data-rp]').forEach(x => x.classList.toggle('on', x === b));
          fig.querySelectorAll('.rp-pane').forEach(p => { p.hidden = p.dataset.pane !== b.dataset.rp; });
          if (b.dataset.rp === 'preg') start();
        }));
        if (tabs[0][0] === 'preg') start();
      },
    };
  };
})();
