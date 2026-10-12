/* Injury & burns: an animated body figure drawn from the values the clinician enters.
   MFInjury.compute mirrors hospital/injury.py `compute` exactly (same rounding, same messages), so the figure and
   the numbers update while typing; the server recomputes on save and the page redraws from its answer.
   MFInjury.figure(el, state) draws front + back views and, for a spinal injury, a close-up of the spine with nerve
   signals that stop (or thin out) at the lesion according to the ASIA grade. Teaching/documentation visual only. */
(() => {
  'use strict';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const rnd = (x, d = 0) => { const m = 10 ** d; return Math.floor(x * m + 0.5) / m; };
  const fmt = x => String(x);
  const num = (v, lo, hi) => { const x = parseFloat(v); return Number.isFinite(x) ? Math.max(lo, Math.min(hi, x)) : null; };
  const SVGNS = 'http://www.w3.org/2000/svg';

  /* ------------------------------------------------------------------ the maths (mirror of injury.py) */
  const AGE_BANDS = [1, 5, 10, 15, 16];
  const ageBand = age => { if (age == null) return 5; for (let i = 0; i < AGE_BANDS.length; i++) if (age < AGE_BANDS[i]) return i; return 5; };
  const LEVELS = [...Array(7)].map((_, i) => `C${i + 1}`).concat([...Array(12)].map((_, i) => `T${i + 1}`), [...Array(5)].map((_, i) => `L${i + 1}`), ['S']);
  const LABEL = {head: 'Head', neck: 'Neck', chest: 'Chest', abdomen: 'Abdomen', upper_back: 'Upper back', lower_back: 'Lower back', buttock: 'Buttock',
    genitalia: 'Genitalia', upper_arm: 'Upper arm', forearm: 'Forearm', hand: 'Hand', thigh: 'Thigh', leg: 'Lower leg', foot: 'Foot'};
  const ASIA_PASS = {A: 0, B: .15, C: .4, D: .75, E: 1};

  function spinalEffects(level, asia) {
    const i = LEVELS.indexOf(level), L = x => LEVELS.indexOf(x);
    let affected;
    if (asia === 'E') affected = [];
    else if (i <= L('C4')) affected = ['upper_arm', 'forearm', 'hand', 'chest', 'abdomen', 'upper_back', 'lower_back', 'buttock', 'genitalia', 'thigh', 'leg', 'foot'];
    else if (i <= L('C7')) affected = ['forearm', 'hand', 'chest', 'abdomen', 'upper_back', 'lower_back', 'buttock', 'genitalia', 'thigh', 'leg', 'foot'];
    else if (i <= L('T6')) affected = ['abdomen', 'lower_back', 'buttock', 'genitalia', 'thigh', 'leg', 'foot'];
    else if (i <= L('T12')) affected = ['buttock', 'genitalia', 'thigh', 'leg', 'foot'];
    else if (i <= L('L3')) affected = ['leg', 'foot', 'genitalia'];
    else if (i <= L('L5')) affected = ['foot', 'genitalia'];
    else affected = ['genitalia'];
    const cervical = level[0] === 'C', high = i <= L('T6');
    const pattern = asia === 'E' ? 'No loss of function' : cervical ? (/[AB]/.test(asia) ? 'Tetraplegia (arms and legs)' : 'Incomplete tetraplegia')
      : i <= L('L1') ? (/[AB]/.test(asia) ? 'Paraplegia (legs and trunk)' : 'Incomplete paraplegia') : 'Cauda equina / nerve root injury';
    return {affected, pass: ASIA_PASS[asia], pattern, cervical, breathing_risk: 'ABC'.includes(asia) && i <= L('C5'),
      ventilation_likely: 'AB'.includes(asia) && i <= L('C3'), neurogenic_shock_risk: 'ABC'.includes(asia) && high,
      dysreflexia_risk: 'ABCD'.includes(asia) && high, below_cord: i > L('L1')};
  }

  function compute(data, cat, {age = null, weight_kg = null, vitals = {}, now = new Date()} = {}) {
    vitals = vitals || {};
    const weight = num(weight_kg, 1, 400);
    const areas = {}, byDepth = {superficial: 0, superficial_partial: 0, deep_partial: 0, full: 0};
    for (const e of data.burns || []) {
      const key = `${e.region}|${e.side}|${e.view}`, already = areas[key] || 0, pct = Math.min(e.pct, 100 - already);
      if (pct <= 0) continue;
      areas[key] = already + pct;
      byDepth[e.depth] += cat.lund_browder[e.region][ageBand(age)] / cat.views[e.region].length * pct / 100;
    }
    for (const k in byDepth) byDepth[k] = rnd(byDepth[k], 1);
    const tbsa = rnd(Math.min(100, byDepth.superficial_partial + byDepth.deep_partial + byDepth.full), 1);
    const child = age != null && age < 16, threshold = child ? 10 : 15;
    let fluids = null;
    if (tbsa > 0 && weight) {
      const total = rnd(4 * weight * tbsa), first = rnd(total / 2), second = total - first;
      fluids = {total_24h: total, first_8h: first, next_16h: second, rate_first_ml_h: rnd(first / 8), rate_next_ml_h: rnd(second / 16),
        urine_target_ml_h: rnd((child && weight < 30 ? 1 : .5) * weight), resuscitation_needed: tbsa >= threshold, threshold};
      const burn = data.burn || {};
      if (burn.time) {
        const started = new Date(burn.time);
        if (!isNaN(started)) {
          const elapsed = Math.max(0, (now - started) / 3600000), given = burn.given_ml || 0;
          fluids.hours_since_burn = rnd(elapsed, 1);
          if (elapsed < 8) { fluids.catch_up_ml_h = rnd(Math.max(0, first - given) / Math.max(.5, 8 - elapsed)); fluids.phase = 'first 8 hours'; }
          else if (elapsed < 24) { fluids.catch_up_ml_h = rnd(Math.max(0, total - given) / Math.max(.5, 24 - elapsed)); fluids.phase = 'next 16 hours'; }
          else fluids.phase = 'after 24 hours';
        }
      }
    }
    const alerts = [];
    if (tbsa >= threshold) alerts.push({level: 'high', text: `Major burn: ${fmt(tbsa)}% of body surface. Start formal fluid resuscitation and refer to a burns unit.`});
    else if (tbsa > 0) alerts.push({level: 'info', text: `Burns cover ${fmt(tbsa)}% of body surface (not counting simple redness).`});
    if (tbsa > 0 && !weight) alerts.push({level: 'warn', text: 'Enter the weight to calculate fluids.'});
    if ((data.burn || {}).inhalation) alerts.push({level: 'high', text: 'Possible inhalation injury: watch the airway closely; early senior anaesthetic review.'});
    for (const e of data.burns || []) if (e.circumferential && (e.depth === 'deep_partial' || e.depth === 'full'))
      alerts.push({level: 'high', text: `Deep circumferential burn of the ${LABEL[e.region].toLowerCase()}: check circulation and breathing; escharotomy may be needed.`});
    if ((data.burns || []).some(e => ['head', 'neck', 'hand', 'foot', 'genitalia'].includes(e.region) && e.depth !== 'superficial'))
      alerts.push({level: 'warn', text: 'Burns to the face, hands, feet or genitals need specialist burns care.'});
    let spine = null;
    if (data.spine) {
      const s = data.spine;
      spine = spinalEffects(s.level, s.asia);
      const sbp = num(vitals.systolic, 0, 400), hr = num(vitals.heart_rate, 0, 400);
      spine.neurogenic_shock = !!(spine.neurogenic_shock_risk && sbp != null && hr != null && sbp < 90 && hr < 60);
      if (spine.neurogenic_shock) alerts.push({level: 'high', text: `Low blood pressure (${fmt(sbp)}) with slow pulse (${fmt(hr)}) after a ${s.level} injury: likely neurogenic shock.`});
      if (spine.ventilation_likely) alerts.push({level: 'high', text: `${s.level} complete injury: breathing muscles are affected; prepare for ventilation.`});
      else if (spine.breathing_risk) alerts.push({level: 'warn', text: `${s.level} injury can weaken breathing: monitor breathing effort and vital capacity.`});
      if (spine.cervical && !s.immobilised) alerts.push({level: 'high', text: 'Cervical injury without immobilisation: apply a collar and log-roll.'});
      if (spine.dysreflexia_risk) alerts.push({level: 'info', text: 'Injury at or above T6: watch for autonomic dysreflexia (sudden high blood pressure, headache).'});
    }
    let head = null;
    if (data.head) {
      const h = data.head, gcs = h.eye + h.verbal + h.motor;
      head = {gcs, severity: gcs >= 13 ? 'mild' : gcs >= 9 ? 'moderate' : 'severe'};
      if (gcs <= 8) alerts.push({level: 'high', text: `GCS ${gcs}: severe head injury. Protect the airway.`});
      else if (gcs <= 12) alerts.push({level: 'warn', text: `GCS ${gcs}: moderate head injury. CT and frequent neuro checks.`});
      if (h.pupils === 'unequal' || h.pupils === 'fixed') alerts.push({level: 'high', text: `Pupils ${h.pupils}: possible raised pressure in the skull. Urgent senior review.`});
    }
    for (const e of data.injuries || []) {
      const name = `${e.side ? e.side + ' ' : ''}${LABEL[e.region].toLowerCase()}`;
      if (e.bleeding === 'active') alerts.push({level: 'high', text: `Active bleeding from the ${name}: apply pressure.`});
      if (e.type === 'fracture' && e.open) alerts.push({level: 'high', text: `Open fracture of the ${name}: antibiotics, tetanus and urgent orthopaedic review.`});
      if (e.type === 'amputation') alerts.push({level: 'high', text: `Amputation at the ${name}: control bleeding and preserve the part.`});
    }
    const spo2 = num(vitals.spo2, 0, 100) ?? 100;
    if (spo2 < 92) alerts.push({level: 'high', text: `Oxygen saturation ${fmt(spo2)}%: give oxygen.`});
    const order = {high: 0, warn: 1, info: 2};
    alerts.sort((a, b) => order[a.level] - order[b.level]);          // stable, like Python's sort
    return {tbsa, by_depth: byDepth, fluids, spine, head, alerts, counts: {burns: (data.burns || []).length, injuries: (data.injuries || []).length}};
  }

  /* ------------------------------------------------------------------ the figure */
  // Shapes for the viewer's LEFT half; the right half is the mirror image. Front view: viewer-left = patient's right.
  const SHAPE = {
    head: 'M110,9 C128,9 136,24 136,40 C136,58 125,72 110,72 C95,72 84,58 84,40 C84,24 92,9 110,9Z',
    neck: 'M99,66 L121,66 L123,92 L97,92Z',
    chest: 'M97,90 L123,90 L150,96 Q161,100 159,114 L153,170 L67,170 L61,114 Q59,100 70,96Z',
    abdomen: 'M67,170 L153,170 L151,214 Q151,230 146,240 L74,240 Q69,230 69,214Z',
    upper_back: 'M97,90 L123,90 L150,96 Q161,100 159,114 L153,170 L67,170 L61,114 Q59,100 70,96Z',
    lower_back: 'M67,170 L153,170 L151,214 Q151,230 146,240 L74,240 Q69,230 69,214Z',
    genitalia: 'M100,240 L120,240 L116,260 Q110,267 104,260Z',
    buttock: 'M74,240 L110,240 L110,270 Q92,279 76,268Z',
    upper_arm: 'M61,101 Q49,104 45,118 L37,182 L56,186 L64,128Z',
    forearm: 'M37,186 L56,190 L50,258 L34,256Z',
    hand: 'M34,260 L50,262 Q55,282 47,294 Q37,298 32,285 Q30,272 34,260Z',
    thigh: 'M74,240 L108,244 L104,344 L80,344 Q70,294 74,240Z',
    leg: 'M80,348 L104,348 L101,434 L86,434 Q80,392 80,348Z',
    foot: 'M85,438 L102,438 L104,454 Q100,464 90,464 L75,464 Q71,457 85,438Z',
  };
  const PAIRED = new Set(['buttock', 'upper_arm', 'forearm', 'hand', 'thigh', 'leg', 'foot']);
  const IN_VIEW = {front: ['head', 'neck', 'chest', 'abdomen', 'genitalia', 'upper_arm', 'forearm', 'hand', 'thigh', 'leg', 'foot'],
    back: ['head', 'neck', 'upper_back', 'lower_back', 'thigh', 'leg', 'foot', 'buttock', 'upper_arm', 'forearm', 'hand']};
  const DEPTH = {superficial: {fill: '#F4A9A1', name: 'Superficial'}, superficial_partial: {fill: '#E0574B', name: 'Superficial partial'},
    deep_partial: {fill: '#B7303D', name: 'Deep partial'}, full: {fill: '#4E3A2E', name: 'Full thickness'}};
  const DEPTH_RANK = {superficial: 0, superficial_partial: 1, deep_partial: 2, full: 3};
  const SEV = {minor: .7, moderate: 1, severe: 1.35};
  // Where each spine level sits on the BACK view (y), for the lesion marker and nerve signals.
  const LEVEL_Y = (() => { const y = {}; LEVELS.forEach((l, i) => { y[l] = i < 7 ? 70 + i * 3.2 : i < 19 ? 93 + (i - 7) * 9.4 : i < 24 ? 207 + (i - 19) * 7.2 : 250; }); return y; })();

  const sideOf = (view, half) => (view === 'front') === (half === 'L') ? 'right' : 'left';     // patient's side for a viewer half

  function svgEl(tag, attrs = {}, parent) {
    const n = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v != null) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }

  // Seeded random so the blisters/embers stay put between redraws of the same assessment.
  const seeded = seed => () => (seed = (seed * 9301 + 49297) % 233280) / 233280;

  function drawView(view, st, opts) {
    const {data, computed, cat, age} = st;
    const svg = svgEl('svg', {viewBox: '0 0 220 476', class: `inj-fig v-${view}`, role: 'img', 'aria-label': `${view === 'front' ? 'Front' : 'Back'} of body`});
    const defs = svgEl('defs', {}, svg);
    defs.innerHTML = `<radialGradient id="ig-bruise-${view}"><stop offset="0" stop-color="#5B2A7A" stop-opacity=".85"/><stop offset=".55" stop-color="#7D3C8C" stop-opacity=".45"/><stop offset="1" stop-color="#9C5BA3" stop-opacity="0"/></radialGradient>
      <radialGradient id="ig-glow-${view}"><stop offset="0" stop-color="#FF4F5E" stop-opacity=".9"/><stop offset="1" stop-color="#FF4F5E" stop-opacity="0"/></radialGradient>
      <pattern id="ig-scuff-${view}" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><path d="M0,0 L0,4" stroke="#C0564C" stroke-width="1.4" opacity=".7"/></pattern>
      <pattern id="ig-char-${view}" width="9" height="9" patternUnits="userSpaceOnUse"><rect width="9" height="9" fill="#4E3A2E"/><path d="M0,4 L4,6 L9,2 M2,9 L5,6" stroke="#2A1D16" stroke-width=".9" fill="none"/><circle cx="7" cy="7" r=".8" fill="#E9DCCB" opacity=".7"/></pattern>
      <pattern id="ig-mottle-${view}" width="10" height="10" patternUnits="userSpaceOnUse"><rect width="10" height="10" fill="#B7303D"/><circle cx="3" cy="3" r="2" fill="#F1D6D2" opacity=".75"/><circle cx="8" cy="7" r="1.5" fill="#F1D6D2" opacity=".6"/></pattern>`;
    const affected = new Set(computed.spine ? computed.spine.affected : []);
    const pass = computed.spine ? computed.spine.pass : 1;
    const body = svgEl('g', {class: 'inj-body'}, svg);
    const regions = {};                                       // "region|side" -> path element (for overlays)
    for (const half of ['L', 'R']) {
      const g = svgEl('g', {transform: half === 'R' ? 'matrix(-1 0 0 1 220 0)' : null}, body);
      for (const r of IN_VIEW[view]) {
        if (!PAIRED.has(r) && half === 'R') continue;
        const side = PAIRED.has(r) ? sideOf(view, half) : '';
        const p = svgEl('path', {d: SHAPE[r], class: 'inj-region', 'data-region': r, 'data-side': side, 'data-view': view, tabindex: opts.interactive ? 0 : null,
          role: opts.interactive ? 'button' : null}, g);
        const area = cat.lund_browder[r][ageBand(age)] / cat.views[r].length;
        svgEl('title', {}, p).textContent = `${side ? side[0].toUpperCase() + side.slice(1) + ' ' : ''}${LABEL[r].toLowerCase()} (${view}) · ${rnd(area, 2)}% of body`;
        regions[`${r}|${side}`] = p;
      }
    }

    // face details on the front, hair parting on the back
    if (view === 'front') {
      const h = data.head || {};
      const pupils = h.pupils || 'equal';
      const big = pupils === 'fixed' ? 3.2 : 1.5, bigR = pupils === 'unequal' ? 3.2 : big;
      svg.insertAdjacentHTML('beforeend', `<g class="inj-face${pupils === 'fixed' || !data.head ? '' : ' react'}" aria-hidden="true">
        <ellipse cx="100" cy="38" rx="5" ry="3.4" fill="#fff"/><ellipse cx="120" cy="38" rx="5" ry="3.4" fill="#fff"/>
        <circle cx="100" cy="38" r="${bigR}" class="pupil"/><circle cx="120" cy="38" r="${big}" class="pupil"/>
        <path d="M103,57 Q110,61 117,57" fill="none" stroke="#9A6B57" stroke-width="1.6" stroke-linecap="round"/></g>`);
    } else {
      svg.insertAdjacentHTML('beforeend', '<path d="M110,10 L110,30" stroke="#8E6E5C" stroke-width="1" opacity=".4" aria-hidden="true"/>');
    }

    // ----- spinal: limbs below the lesion lose signal (grey-blue wash), proportionally to the ASIA grade
    if (computed.spine) {
      for (const [key, p] of Object.entries(regions)) {
        if (!affected.has(key.split('|')[0])) continue;
        const o = svgEl('path', {d: p.getAttribute('d'), class: 'inj-numb', style: `--numb:${(.62 * (1 - pass)).toFixed(2)}`, transform: p.parentNode.getAttribute('transform')}, svg);
        if (pass > 0 && pass < 1) o.classList.add('tingle');
      }
    }

    // ----- burns: per region-side, deepest depth drawn with its texture; the burned share fills the region from its far end
    const groups = {};
    for (const b of data.burns || []) {
      if (b.view !== view) continue;
      const k = `${b.region}|${b.side}`;
      (groups[k] ||= []).push(b);
    }
    const rand = seeded(17 + (data.burns || []).length);
    const fx = svgEl('g', {class: 'inj-fx'}, svg);
    const pending = [];
    for (const [k, list] of Object.entries(groups)) {
      const p = regions[k];
      if (!p) continue;
      const deepest = list.reduce((a, b) => DEPTH_RANK[b.depth] > DEPTH_RANK[a.depth] ? b : a);
      const pct = Math.min(100, list.reduce((s, b) => s + b.pct, 0));
      pending.push({p, list, deepest, pct, circ: list.some(b => b.circumferential)});
    }
    // ----- other injuries and the head
    const marks = [];
    (data.injuries || []).forEach((inj, i) => { if (inj.view === view && regions[`${inj.region}|${inj.side}`]) marks.push({inj, p: regions[`${inj.region}|${inj.side}`], i}); });

    // bounding boxes need the SVG in the document; finish drawing once it is attached
    svg.__finish = () => {
      for (const {p, list, deepest, pct, circ} of pending) {
        const bb = p.getBBox(), tf = p.parentNode.getAttribute('transform');
        const cid = `ig-c-${view}-${p.dataset.region}-${p.dataset.side || 'm'}`;
        const clip = svgEl('clipPath', {id: cid}, defs);
        svgEl('path', {d: p.getAttribute('d'), transform: tf}, clip);
        const g = svgEl('g', {'clip-path': `url(#${cid})`, class: `inj-burn d-${deepest.depth}`}, fx);
        // limbs burn from the far (distal) end, trunk and head from the top
        const distal = ['forearm', 'hand', 'leg', 'foot', 'upper_arm', 'thigh'].includes(p.dataset.region);
        const h = bb.height * pct / 100, y = distal ? bb.y + bb.height - h : bb.y;
        const inner = svgEl('g', {transform: tf}, g);
        const fill = deepest.depth === 'full' ? `url(#ig-char-${view})` : deepest.depth === 'deep_partial' ? `url(#ig-mottle-${view})` : DEPTH[deepest.depth].fill;
        // ragged leading edge
        const edge = distal ? y : y + h, step = bb.width / 6;
        let d = distal ? `M${bb.x - 2},${bb.y + bb.height + 2} L${bb.x - 2},${edge}` : `M${bb.x - 2},${bb.y - 2} L${bb.x - 2},${edge}`;
        for (let i = 1; i <= 6; i++) d += ` Q${bb.x + step * (i - .5)},${edge + (distal ? -1 : 1) * (2 + rand() * 4)} ${bb.x + step * i},${edge}`;
        d += distal ? ` L${bb.x + bb.width + 2},${bb.y + bb.height + 2}Z` : ` L${bb.x + bb.width + 2},${bb.y - 2}Z`;
        svgEl('path', {d, fill, class: 'burn-area'}, inner);
        if (deepest.depth === 'superficial_partial' || list.some(b => b.depth === 'superficial_partial')) {
          const n = Math.max(2, Math.round(h * bb.width / 160));
          for (let i = 0; i < Math.min(n, 14); i++)
            svgEl('circle', {cx: bb.x + 3 + rand() * (bb.width - 6), cy: y + 2 + rand() * Math.max(2, h - 4), r: 1.4 + rand() * 2.2, class: 'blister', style: `animation-delay:${(-rand() * 5).toFixed(2)}s`}, inner);
        }
        if (deepest.depth === 'full') {
          for (let i = 0; i < Math.min(10, Math.round(h / 6) + 2); i++)
            svgEl('circle', {cx: bb.x + 2 + rand() * (bb.width - 4), cy: y + 2 + rand() * Math.max(2, h - 4), r: .9 + rand(), class: 'ember', style: `animation-delay:${(-rand() * 3).toFixed(2)}s`}, inner);
        }
        if (circ) {
          const band = svgEl('rect', {x: bb.x - 3, y: y + h / 2 - 3, width: bb.width + 6, height: 6, rx: 3, class: 'circ-band'}, svgEl('g', {transform: tf}, fx));   // around the middle of the burned part
          svgEl('title', {}, band).textContent = 'Circumferential burn';
        }
      }
      for (const {inj, p, i} of marks) drawInjury(fx, inj, p, i, view, rand);
      if (data.head && view === 'front') drawHead(fx, computed.head);
      if (computed.spine && view === 'back') drawCord(svg, data.spine, computed.spine);
    };
    if (opts.interactive) svg.classList.add('interactive');
    return svg;
  }

  function centre(p) {
    const bb = p.getBBox(), tf = p.parentNode.getAttribute('transform');
    let x = bb.x + bb.width / 2;
    if (tf) x = 220 - x;
    return {x, y: bb.y + bb.height / 2, w: bb.width, h: bb.height};
  }

  function drawInjury(fx, inj, p, i, view, rand) {
    const c = centre(p), s = SEV[inj.severity] || 1, ox = ((i % 3) - 1) * 4, oy = ((i % 2) ? 5 : -5);
    const x = c.x + ox, y = c.y + oy, g = svgEl('g', {class: `inj-mark t-${inj.type} b-${inj.bleeding} s-${inj.severity}`, transform: `translate(${x},${y}) scale(${s})`}, fx);
    svgEl('title', {}, g).textContent = `${(window.MF_INJURY_TYPES || {})[inj.type] || inj.type}: ${inj.side ? inj.side + ' ' : ''}${LABEL[inj.region].toLowerCase()} (${inj.severity}${inj.bleeding !== 'none' ? ', ' + inj.bleeding + ' bleeding' : ''})`;
    switch (inj.type) {
      case 'fracture':
        svgEl('circle', {r: 11, fill: `url(#ig-glow-${view})`, class: 'pulse'}, g);
        svgEl('path', {d: 'M-9,-6 L-3,-1 L-6,2 L1,5 L-1,8 L8,11', class: 'crack'}, g);
        if (inj.open) svgEl('path', {d: 'M-4,-2 l3,-4 l2,5', fill: '#F4EDE2', stroke: '#C8323F', 'stroke-width': .8}, g);
        break;
      case 'dislocation':
        svgEl('circle', {r: 7, class: 'joint'}, g); svgEl('circle', {r: 7, cx: 4, cy: 3, class: 'joint off'}, g);
        svgEl('path', {d: 'M-12,-10 l6,6 m0,-5 v5 h-5', class: 'arrow'}, g);
        break;
      case 'laceration': svgEl('path', {d: 'M-10,-4 Q0,-1 10,4', class: 'cut'}, g); break;
      case 'abrasion': svgEl('ellipse', {rx: 11, ry: 6, fill: `url(#ig-scuff-${view})`, class: 'scuff'}, g); break;
      case 'contusion': svgEl('circle', {r: 14, fill: `url(#ig-bruise-${view})`, class: 'bruise'}, g); break;
      case 'penetrating': svgEl('circle', {r: 7, class: 'ring'}, g); svgEl('circle', {r: 2.6, fill: '#3B0F14'}, g); break;
      case 'crush': svgEl('circle', {r: 14, fill: `url(#ig-bruise-${view})`, class: 'bruise'}, g); svgEl('path', {d: 'M-12,-9 h24 M-12,9 h24', class: 'press'}, g); break;
      case 'amputation': svgEl('path', {d: 'M-12,0 h24', class: 'amp'}, g); svgEl('path', {d: 'M-12,0 h24', class: 'amp-line'}, g); break;
      case 'sprain': svgEl('circle', {r: 12, class: 'swell'}, g); break;
    }
    // blood: drips fall from wounds at a rate set by the bleeding entered
    if (inj.bleeding !== 'none' && ['laceration', 'penetrating', 'amputation', 'fracture', 'crush', 'abrasion'].includes(inj.type)) {
      const n = inj.bleeding === 'active' ? 4 : 1, dur = inj.bleeding === 'active' ? 1.1 : 3.4;
      for (let k = 0; k < n; k++) svgEl('path', {d: 'M0,0 q2.4,3.4 0,5.4 q-2.4,-2 0,-5.4z', class: 'drip', transform: `translate(${(k - (n - 1) / 2) * 4},2)`, style: `--dur:${dur}s;animation-delay:${(-k * dur / n).toFixed(2)}s`}, g);
    }
  }

  function drawHead(fx, head) {
    const g = svgEl('g', {class: `inj-headwave sev-${head.severity}`, transform: 'translate(124,22)'}, fx);
    svgEl('title', {}, g).textContent = `Head injury · GCS ${head.gcs} (${head.severity})`;
    const dur = head.severity === 'severe' ? 1.2 : head.severity === 'moderate' ? 2 : 3.2;
    for (let k = 0; k < 3; k++) svgEl('circle', {r: 4, class: 'wave', style: `--dur:${dur}s;animation-delay:${(-k * dur / 3).toFixed(2)}s`}, g);
    svgEl('circle', {r: 3.4, class: 'impact'}, g);
  }

  // Back view: the spine down the middle, the cord, and the lesion.
  function drawCord(svg, s, sp) {
    const g = svgEl('g', {class: 'inj-spine', 'aria-hidden': 'true'});
    svg.insertBefore(g, svg.querySelector('.inj-fx'));
    LEVELS.forEach((l, i) => { if (l !== 'S') svgEl('rect', {x: 106 - (i > 18 ? 1 : 0), y: LEVEL_Y[l] - (i < 7 ? 1.2 : 3.4), width: 8 + (i > 18 ? 2 : 0), height: i < 7 ? 2.4 : i < 19 ? 7 : 6, rx: 1.5, class: l === s.level ? 'vert hit' : 'vert'}, g); });
    svgEl('path', {d: 'M104,246 L116,246 L112,266 L108,266Z', class: 'vert'}, g);
    const ly = LEVEL_Y[s.level];
    svgEl('circle', {cx: 110, cy: ly, r: 10, class: 'lesion-glow'}, g);
    svgEl('circle', {cx: 110, cy: ly, r: 4, class: 'lesion'}, g);
  }

  /* ------------------------------------------------------------------ spine close-up (side panel) */
  function drawSpinePanel(s, sp) {
    const svg = svgEl('svg', {viewBox: '0 0 170 476', class: 'inj-spinepanel', role: 'img', 'aria-label': `Spine with ${s.level} injury, ASIA ${s.asia}`});
    const Y = {}; let y = 30;
    LEVELS.forEach((l, i) => { const h = l === 'S' ? 40 : i < 7 ? 9 : i < 19 ? 12 : 15; Y[l] = {y, h}; y += h + 4; });
    const cordEnd = Y.L1.y + Y.L1.h;
    let html = `<text x="85" y="16" class="sp-title">Spinal cord · ASIA ${s.asia}</text>
      <path d="M85,20 L85,${cordEnd}" class="cord"/>
      <path d="M85,${cordEnd} C82,${cordEnd + 40} 78,${Y.S.y} 74,${Y.S.y + 30} M85,${cordEnd} C88,${cordEnd + 40} 92,${Y.S.y} 96,${Y.S.y + 30} M85,${cordEnd} L85,${Y.S.y + 34}" class="cauda"/>`;
    LEVELS.forEach((l, i) => {
      const {y, h} = Y[l], w = l === 'S' ? 40 : i < 7 ? 30 + i : i < 19 ? 36 + (i - 7) : 50 + (i - 19) * 3, hit = l === s.level;
      const dx = hit && s.type === 'dislocation' ? 8 : 0;
      if (l === 'S') html += `<path d="M${85 - w / 2},${y} L${85 + w / 2},${y} L${85 + 8},${y + h} L${85 - 8},${y + h}Z" class="sp-bone"/>`;
      else if (hit && s.type === 'fracture') html += `<path d="M${85 - w / 2},${y + h * .55} L${85 + w / 2},${y} L${85 + w / 2},${y + h} L${85 - w / 2},${y + h}Z" class="sp-bone hit"/><path d="M${85 - w / 2 + 3},${y + h * .5} l${w / 3},${-h * .2} l${w / 4},${h * .4}" class="sp-crack"/>`;
      else html += `<rect x="${85 - w / 2 + dx}" y="${y}" width="${w}" height="${h}" rx="3" class="sp-bone${hit ? ' hit' : ''}"/>`;
      if (l !== 'S' && i < 23) html += hit && s.type === 'disc' ? `<ellipse cx="${85 + w / 4}" cy="${y + h + 2}" rx="${w / 3}" ry="3.6" class="sp-disc bulge"/>` : `<rect x="${85 - w / 2 + 4}" y="${y + h + .6}" width="${w - 8}" height="2.6" rx="1.3" class="sp-disc"/>`;
      html += `<text x="${85 + w / 2 + 7}" y="${y + h / 2 + 3}" class="sp-lbl${hit ? ' hot' : ''}">${l}</text>`;
    });
    const ly = Y[s.level].y + Y[s.level].h / 2;
    const lesionCls = s.type === 'cord_contusion' ? 'swollen' : s.type === 'central_cord' ? 'central' : '';
    html += `<circle cx="85" cy="${ly}" r="14" class="lesion-glow"/><ellipse cx="85" cy="${ly}" rx="${lesionCls === 'swollen' ? 7 : 4.5}" ry="${lesionCls === 'swollen' ? 9 : 5}" class="lesion ${lesionCls}"/>
      <path d="M85,${ly} L85,${cordEnd}" class="cord below" style="opacity:${(.25 + .75 * sp.pass).toFixed(2)}"/>`;
    html += `<g class="signals"></g>`;
    svg.innerHTML = html;
    svg.__signals = {top: 20, lesion: ly, end: Y.S.y + 30, pass: sp.pass};
    return svg;
  }

  // Nerve signals: dots run down the cord; at the lesion each either continues (dimmer for B) or bursts and stops.
  function animateSignals(svg) {
    if (reduce || !svg.__signals) return () => {};
    const {top, lesion, end, pass} = svg.__signals, layer = svg.querySelector('.signals');
    const dots = [...Array(9)].map((_, i) => ({el: svgEl('circle', {cx: 85, r: 2.6, class: 'sig'}, layer), t: i / 9, i}));
    let raf, last = performance.now();
    const step = now => {
      const dt = Math.min(.05, (now - last) / 1000); last = now;
      for (const d of dots) {
        d.t += dt * .22;
        if (d.t > 1) { d.t -= 1; d.burst = false; }
        const y = top + (end - top) * d.t;
        const through = ((d.i * 37) % 100) / 100 < pass;            // deterministic share of signals that get past
        if (y > lesion && !through) {
          if (!d.burst) { d.burst = true; burst(layer, lesion); }
          d.el.setAttribute('opacity', 0); continue;
        }
        d.el.setAttribute('cy', y.toFixed(1));
        d.el.setAttribute('opacity', y > lesion ? (pass < .2 ? .35 : .85) : 1);
        d.el.classList.toggle('dim', y > lesion && pass < .2);
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }
  function burst(layer, y) {
    const g = svgEl('g', {class: 'burst', transform: `translate(85,${y})`}, layer);
    for (let k = 0; k < 6; k++) svgEl('line', {x1: 0, y1: 0, x2: Math.cos(k) * 9, y2: Math.sin(k) * 9}, g);
    setTimeout(() => g.remove(), 600);
  }

  // Back view cord signals (smaller), from the head down the back, stopping at the lesion.
  function animateBackCord(svg, s, sp) {
    if (reduce || !s) return () => {};
    const layer = svgEl('g', {class: 'signals'}, svg.querySelector('.inj-spine'));
    const top = 66, lesion = LEVEL_Y[s.level], end = 240;
    const dots = [...Array(6)].map((_, i) => ({el: svgEl('circle', {cx: 110, r: 1.6, class: 'sig'}, layer), t: i / 6, i}));
    let raf, last = performance.now();
    const step = now => {
      const dt = Math.min(.05, (now - last) / 1000); last = now;
      for (const d of dots) {
        d.t = (d.t + dt * .3) % 1;
        const y = top + (end - top) * d.t, through = ((d.i * 37) % 100) / 100 < sp.pass;
        d.el.setAttribute('cy', y.toFixed(1));
        d.el.setAttribute('opacity', y > lesion ? (through ? .7 : 0) : 1);
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }

  /* ------------------------------------------------------------------ public: draw everything into a container */
  function figure(host, st, opts = {}) {
    (host.__stop || []).forEach(f => f());
    host.__stop = [];
    host.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'inj-figs';
    host.appendChild(wrap);
    for (const view of ['front', 'back']) {
      const cell = document.createElement('figure');
      cell.className = 'inj-cell';
      const svg = drawView(view, st, opts);
      cell.appendChild(svg);
      cell.insertAdjacentHTML('beforeend', `<figcaption>${view === 'front' ? 'Front' : 'Back'}<span>patient's ${view === 'front' ? 'right is on your left' : 'left is on your left'}</span></figcaption>`);
      wrap.appendChild(cell);
      svg.__finish();
      if (view === 'back' && st.computed.spine) host.__stop.push(animateBackCord(svg, st.data.spine, st.computed.spine));
    }
    if (st.data.spine && st.computed.spine) {
      const cell = document.createElement('figure');
      cell.className = 'inj-cell spine';
      const sp = drawSpinePanel(st.data.spine, st.computed.spine);
      cell.appendChild(sp);
      cell.insertAdjacentHTML('beforeend', `<figcaption>${esc(st.computed.spine.pattern)}<span>${Math.round(st.computed.spine.pass * 100)}% of nerve signals pass the lesion</span></figcaption>`);
      wrap.appendChild(cell);
      host.__stop.push(animateSignals(sp));
    }
    if (opts.onRegion) {
      host.querySelectorAll('.inj-region[data-region]').forEach(p => {
        const go = ev => opts.onRegion({region: p.dataset.region, side: p.dataset.side, view: p.dataset.view}, ev);
        p.addEventListener('click', go);
        p.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); go(ev); } });
      });
    }
  }

  window.MFInjury = {compute, figure, LEVELS, LABEL, DEPTH, ageBand, rnd, SHAPE, IN_VIEW, PAIRED, sideOf};
})();
