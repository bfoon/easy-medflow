/* Bone pop-out with tabs: Spine, Hands, Feet and Bone tissue (the bone-tissue view from organs-anatomy.js).
   The tab that matters for this patient opens first; findings come from window.MF_ANATOMY (anatomy-layers.js),
   which reads results, scans and diagnoses. Teaching illustration only. */
(() => {
  'use strict';
  const ART = window.__MF_ART, H = (window.MedFlowOrgans || {}).helpers;
  if (!ART || !H) return;
  const {part} = H;
  const tissue = ART.bone;                                   // keep the bone-tissue drawing as the fourth tab
  const DEFS = `<linearGradient id="sk-bone" x1="0" x2="1"><stop offset="0" stop-color="#E8DCC6"/><stop offset=".5" stop-color="#FBF5EA"/><stop offset="1" stop-color="#DCCDB2"/></linearGradient>
    <radialGradient id="sk-hot" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#ff3b4e" stop-opacity=".95"/><stop offset=".6" stop-color="#ff3b4e" stop-opacity=".35"/><stop offset="1" stop-color="#ff3b4e" stop-opacity="0"/></radialGradient>
    <filter id="sk-sh" filterUnits="userSpaceOnUse" x="0" y="0" width="320" height="520"><feDropShadow dx="0" dy="1.5" stdDeviation="1.4" flood-color="#4a3a28" flood-opacity=".35"/></filter>`;

  /* ------------------------------------------------------------------ spine (front view, C1 to sacrum, with the cord) */
  function spine(A) {
    const hit = Object.fromEntries((A.realSpine || []).map(s => [s.level, s.kind]));
    let s = '', y = 14;
    const names = [...Array(7)].map((_, i) => `C${i + 1}`).concat([...Array(12)].map((_, i) => `T${i + 1}`), [...Array(5)].map((_, i) => `L${i + 1}`));
    const pos = {};
    names.forEach(n => {
      const r = n[0], i = +n.slice(1), h = r === 'C' ? 7 : r === 'T' ? 9.2 : 12, w = r === 'C' ? 26 + i : r === 'T' ? 32 + i * 1.2 : 50 + i * 2;
      pos[n] = y + h / 2;
      const k = hit[n];
      const body = k === 'fracture' ? `M${170 - w / 2},${y + h * .45} L${170 + w / 2},${y} L${170 + w / 2},${y + h} L${170 - w / 2},${y + h}Z`
        : `M${170 - w / 2 + 3},${y} H${170 + w / 2 - 3} Q${170 + w / 2},${y} ${170 + w / 2},${y + 3} V${y + h - 3} Q${170 + w / 2},${y + h} ${170 + w / 2 - 3},${y + h} H${170 - w / 2 + 3} Q${170 - w / 2},${y + h} ${170 - w / 2},${y + h - 3} V${y + 3} Q${170 - w / 2},${y} ${170 - w / 2 + 3},${y}Z`;
      s += `<path d="${body}" fill="url(#sk-bone)" stroke="${k ? '#C8323F' : '#B9A27E'}" stroke-width="${k ? 2 : 1}" class="${k ? 'sk-hit k-' + k : ''}" filter="url(#sk-sh)"><title>${n}</title></path>`;
      s += `<path d="M${170 - w / 2 - 6},${y + h / 2} L${170 - w / 2},${y + h / 2} M${170 + w / 2},${y + h / 2} L${170 + w / 2 + 6},${y + h / 2}" stroke="#CDB892" stroke-width="2.4" stroke-linecap="round"/>`;
      if (k === 'disc') s += `<ellipse cx="${170 + w / 4}" cy="${y + h + 2.5}" rx="${w / 3}" ry="3.4" class="sk-disc-bulge"><title>Herniated disc below ${n}</title></ellipse>`;
      else s += `<rect x="${170 - w / 2 + 3}" y="${y + h + .6}" width="${w - 6}" height="2.2" rx="1" fill="#9FC4D8" opacity=".8"/>`;
      if (k === 'wear') s += `<path d="M${170 - w / 2},${y + h} l-4,3 M${170 + w / 2},${y + h} l4,3" stroke="#B9A27E" stroke-width="2"/>`;
      y += h + 3.4;
    });
    const sac = `<path d="M146,${y} L194,${y} L180,${y + 36} L160,${y + 36} Z" fill="url(#sk-bone)" stroke="#B9A27E" filter="url(#sk-sh)"/>`;
    const cordKind = (A.realSpine || []).find(x => x.kind === 'cord');
    const lesion = cordKind ? pos[cordKind.level] : null;
    const cord = `<path d="M170,8 L170,${pos.L1}" stroke="#F2C76B" stroke-width="4" stroke-linecap="round" opacity=".75"/>` +
      (lesion ? `<path d="M170,${lesion} L170,${pos.L1}" stroke="#7a6f66" stroke-width="4" opacity=".85" stroke-dasharray="3 2"/><circle cx="170" cy="${lesion}" r="6" class="sk-lesion"/>` : '') +
      `<path d="M170,${pos.L1} C168,${pos.L3} 164,${pos.L5} 160,${y + 20} M170,${pos.L1} C172,${pos.L3} 176,${pos.L5} 180,${y + 20}" stroke="${lesion ? '#7a6f66' : '#F2C76B'}" stroke-width="1.4" fill="none" opacity=".75"/>`;
    const labels = [['Cervical', pos.C4], ['Thoracic', pos.T6], ['Lumbar', pos.L3]].map(([t, yy]) => `<text x="236" y="${yy + 3}" class="sk-lbl">${t}</text>`).join('') +
      (A.realSpine || []).map(f => pos[f.level] ? `<text x="100" y="${pos[f.level] + 3}" class="sk-lbl hot" text-anchor="end">${f.level} ${f.kind === 'cord' ? 'cord injury' : f.kind}</text><line x1="104" y1="${pos[f.level]}" x2="${170 - 22}" y2="${pos[f.level]}" class="sk-lead"/>` : '').join('');
    return `<svg viewBox="0 0 300 ${y + 46}" class="oa sk sk-spine"><defs>${DEFS}</defs>
      ${part('column', 'Vertebral column: 7 cervical, 12 thoracic and 5 lumbar vertebrae, cushioned by discs (blue).', `<g>${s}</g>`)}
      ${part('cord', 'Spinal cord (seen through the bone): carries every message between the brain and the body. Below an injury, movement and feeling are lost.', cord)}
      ${part('sacrum', 'Sacrum: five fused vertebrae joining the spine to the pelvis.', sac)}${labels}</svg>`;
  }

  /* ------------------------------------------------------------------ hand (back of the right hand) */
  function hand(A) {
    const hot = A.hands && A.hands.inflamed, broken = A.hands && A.hands.fracture;
    let s = '';
    const carpals = [[120, 214, 14, 11], [138, 210, 13, 11], [154, 212, 12, 11], [170, 216, 13, 12], [124, 196, 12, 10], [140, 193, 13, 10], [156, 194, 12, 10], [172, 198, 13, 11]];
    carpals.forEach(([x, y, w, h]) => { s += `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="5" fill="url(#sk-bone)" stroke="#B9A27E" filter="url(#sk-sh)"/>`; });
    const rays = [{x: 116, a: -.32, m: 46, p: [30, 22]}, {x: 134, a: -.1, m: 62, p: [38, 24, 18]}, {x: 150, a: 0, m: 64, p: [42, 27, 19]},
                  {x: 166, a: .08, m: 60, p: [39, 25, 18]}, {x: 181, a: .18, m: 54, p: [31, 20, 16]}];
    const joints = [];
    rays.forEach((r, i) => {
      let x = r.x, y = 190, dx = Math.sin(r.a), dy = -Math.cos(r.a);
      const seg = (len, w, cls, brokenHere) => {
        const x2 = x + dx * len, y2 = y + dy * len;
        s += `<line x1="${x.toFixed(1)}" y1="${y.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="#EADCC3" stroke-width="${w}" stroke-linecap="round" filter="url(#sk-sh)" class="${cls}"/>`;
        if (brokenHere) { const mx = (x + x2) / 2, my = (y + y2) / 2; s += `<path d="M${mx - 6},${my - 2} l4,2 l-3,2 l5,1.5" stroke="#C8323F" stroke-width="1.8" fill="none" class="sk-crack"/>`; }
        x = x2; y = y2; joints.push([x, y, i]);
      };
      seg(r.m, 9, 'meta', broken && i === 4);
      r.p.forEach((len, k) => seg(len, 7 - k, 'phal'));
    });
    const jhtml = joints.map(([x, y, i], k) => `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${hot ? 4.6 : 3.2}" class="${hot ? 'sk-joint hot' : 'sk-joint'}" style="animation-delay:${(k * .09).toFixed(2)}s"/>`).join('');
    return `<svg viewBox="0 0 300 250" class="oa sk sk-hand"><defs>${DEFS}</defs>
      <path d="M110,240 C108,214 114,198 120,186 L186,186 C194,204 196,222 192,240Z" fill="#F4E3D7" opacity=".35"/>
      ${part('carpals', 'Carpals: eight small wrist bones that let the wrist bend and turn.', `<g>${s.split('<line')[0]}</g>`)}
      ${part('rays', 'Metacarpals and phalanges: the palm bones and the 14 finger bones (thumb has two).', `<g>${'<line' + s.split('<line').slice(1).join('<line')}</g>`)}
      ${part('joints', hot ? 'Finger and knuckle joints: swollen and inflamed, as in rheumatoid arthritis, which attacks the joint lining on both hands.' : 'Joints between the finger bones.', `<g>${jhtml}</g>`)}
      ${broken ? '<text x="200" y="120" class="sk-lbl hot">Fracture: 5th metacarpal</text>' : ''}${hot ? '<text x="16" y="36" class="sk-lbl hot">Inflamed joints</text>' : ''}</svg>`;
  }

  /* ------------------------------------------------------------------ foot (top view, right foot) */
  function foot(A) {
    const F = A.feet || {};
    const bone = (d, title, cls = '') => `<path d="${d}" fill="url(#sk-bone)" stroke="#B9A27E" filter="url(#sk-sh)" class="${cls}"><title>${title}</title></path>`;
    let tarsals = bone('M132,214 C126,196 150,186 168,192 C182,198 180,222 164,230 C148,236 136,228 132,214Z', 'Calcaneus (heel bone)') +
      bone('M140,186 C138,168 168,164 174,178 C178,190 160,194 148,192Z', 'Talus', F.fracture ? 'sk-hit' : '') +
      bone('M128,168 C126,158 140,152 148,158 C152,166 144,172 134,172Z', 'Navicular') + bone('M170,166 C176,156 190,160 188,172 C186,180 174,182 170,176Z', 'Cuboid') +
      bone('M124,150 l12,-2 l2,12 l-12,2Z', 'Medial cuneiform') + bone('M140,148 l10,-1 l1,11 l-10,1Z', 'Middle cuneiform') + bone('M154,148 l11,0 l0,11 l-11,0Z', 'Lateral cuneiform');
    if (F.fracture) tarsals += '<path d="M150,170 l6,4 l-4,3 l6,4" stroke="#C8323F" stroke-width="2" fill="none" class="sk-crack"/>';
    let rays = '';
    const R = [{x: 128, a: -.08, m: 50, p: [26, 20]}, {x: 144, a: -.02, m: 56, p: [18, 12, 10]}, {x: 156, a: .05, m: 54, p: [16, 11, 9]}, {x: 168, a: .12, m: 50, p: [14, 10, 8]}, {x: 180, a: .2, m: 44, p: [12, 9, 7]}];
    let mtp1 = null;
    R.forEach((r, i) => {
      let x = r.x, y = 146; const dx = Math.sin(r.a), dy = -Math.cos(r.a);
      const seg = (len, w, extra = '') => { const x2 = x + dx * len, y2 = y + dy * len; rays += `<line x1="${x.toFixed(1)}" y1="${y.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="#EADCC3" stroke-width="${w}" stroke-linecap="round" filter="url(#sk-sh)" ${extra}/>`; x = x2; y = y2; };
      seg(r.m, i === 0 ? 12 : 8, F.infection && i === 0 ? 'class="sk-infected"' : '');
      if (i === 0) mtp1 = [x, y];
      r.p.forEach((len, k) => seg(len, (i === 0 ? 10 : 6) - k));
    });
    const gout = F.gout ? `<circle cx="${mtp1[0]}" cy="${mtp1[1]}" r="20" fill="url(#sk-hot)" class="sk-gout"/>${[...Array(7)].map((_, k) => `<path d="M${(mtp1[0] - 8 + (k * 7) % 16).toFixed(0)},${(mtp1[1] - 6 + (k * 5) % 12).toFixed(0)} l3,-5 l1,6" stroke="#fff" stroke-width="1.2" class="sk-crystal" style="animation-delay:${k * .2}s"/>`).join('')}` : '';
    return `<svg viewBox="0 0 300 250" class="oa sk sk-foot"><defs>${DEFS}</defs>
      <path d="M118,236 C100,170 108,70 130,40 C150,22 196,30 206,70 C214,120 196,190 178,236Z" fill="#F4E3D7" opacity=".3"/>
      ${part('tarsals', 'Tarsals: seven bones of the back of the foot, including the heel (calcaneus) and the talus that forms the ankle.', `<g>${tarsals}</g>`)}
      ${part('rays', 'Metatarsals and toe bones: carry the body weight when you walk and push off.', `<g>${rays}</g>`)}
      ${F.gout ? part('mtp1', 'Big-toe joint (1st MTP): urate crystals deposit here in gout, making it red, hot and very painful.', `<g>${gout}</g>`) : ''}
      ${F.gout ? '<text x="200" y="40" class="sk-lbl hot">Gout: big-toe joint</text>' : ''}${F.infection ? '<text x="200" y="90" class="sk-lbl hot">Bone infection</text>' : ''}${F.fracture ? '<text x="200" y="190" class="sk-lbl hot">Fracture</text>' : ''}</svg>`;
  }

  ART.bone = r => {
    const A = window.MF_ANATOMY || {};
    const base = tissue ? tissue(r) : {svg: '', notes: [], parts: {}};
    const tabs = [['spine', 'Spine', spine(A)], ['hands', 'Hands', hand(A)], ['feet', 'Feet', foot(A)], ['tissue', 'Bone tissue', base.svg]];
    const first = (A.realSpine || []).length ? 'spine' : (A.feet && (A.feet.gout || A.feet.fracture || A.feet.infection)) ? 'feet'
      : (A.hands && (A.hands.inflamed || A.hands.fracture)) ? 'hands' : 'tissue';
    const notes = [...(base.notes || [])];
    (A.realSpine || []).forEach(s => notes.unshift(`Spine ${s.level}: ${s.text}`));
    if (A.hands && A.hands.inflamed) notes.unshift('Hands: inflamed finger and knuckle joints (rheumatoid pattern)');
    if (A.feet && A.feet.gout) notes.unshift('Foot: gout in the big-toe joint');
    return {
      svg: `<div class="sk-tabs" role="tablist">${tabs.map(([k, l]) => `<button type="button" role="tab" data-sk="${k}" class="${k === first ? 'on' : ''}">${l}</button>`).join('')}</div>` +
        tabs.map(([k, , html]) => `<div class="sk-pane" data-pane="${k}" ${k === first ? '' : 'hidden'}>${k === 'tissue' ? html : html.replace(/sk-(bone|hot|sh)\b/g, `sk-$1-${k}`)}</div>`).join(''),
      notes: notes.slice(0, 8),
      parts: {...(base.parts || {}), cord: 'Spinal cord: carries every message between the brain and the body. Below an injury, movement and feeling are lost.',
              column: 'Vertebral column: 24 vertebrae separated by shock-absorbing discs.', sacrum: 'Sacrum: fused vertebrae joining the spine to the pelvis.',
              carpals: 'Carpals: eight wrist bones.', rays: 'Long bones of the hand or foot and the finger or toe bones.', joints: 'Joints between the finger bones.',
              tarsals: 'Tarsals: the seven bones at the back of the foot.', mtp1: 'Big-toe joint: where gout usually strikes first.'},
      mount: fig => {
        fig.querySelectorAll('[data-sk]').forEach(b => b.addEventListener('click', () => {
          fig.querySelectorAll('[data-sk]').forEach(x => x.classList.toggle('on', x === b));
          fig.querySelectorAll('.sk-pane').forEach(p => { p.hidden = p.dataset.pane !== b.dataset.sk; });
        }));
      },
    };
  };
})();
