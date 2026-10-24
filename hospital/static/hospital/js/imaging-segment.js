/* Outlines on medical images: organs, abnormal areas and other structures as vector objects.

   * Smart select (M): move over the image and the structure under the pointer lights up as a live outline (region
     growing from the pointer on a smoothed copy, stopped by strong edges); click to keep it. Scroll with Alt held, or use
     the slider, to make it grow more or less.
   * Draw outline (D): trace around something freehand; "Snap to edges" pulls the line onto the nearest strong edge.
   * Show me…: type "heart" or "left lung" in the find box. Matching outlines (yours or Dr. Flow's) are spotlit and
     zoomed to. If there is none and Dr. Flow is connected, it is asked to outline it.
   * Click an outline to inspect it: name, kind, area, perimeter, mean brightness; spotlight, zoom, ask Dr. Flow about
     it (the outline itself is sent, drawn on the picture), snap to edges, rename, recolour, delete.
   Outlines are saved with the image's other annotations (type "polygon"). Smart select and snapping are image
   processing on this computer, not AI; they follow brightness and edges and are only as good as the picture. */
(() => {
  'use strict';
  const IV = window.ImagingViewer;
  const root = document.getElementById('iv');
  if (!IV || !root) return;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const toast = (m, k) => window.mfToast ? mfToast(m, k) : alert(m);
  const CAN_EDIT = IV.canEdit;
  const HAS_AI = !!document.getElementById('iva');
  const REGION = (root.dataset.region || '').toLowerCase(), MODALITY = root.dataset.modality || '';
  const WORK = 768;

  /* ------------------------------------------------------------------ structures to suggest, by study */
  const STRUCTURES = [
    [/chest|lung|thorax|rib/, ['Heart', 'Right lung', 'Left lung', 'Trachea', 'Aortic knuckle', 'Mediastinum', 'Right hemidiaphragm', 'Left hemidiaphragm',
                               'Right hilum', 'Left hilum', 'Clavicle', 'Costophrenic angle']],
    [/abdomen|liver|kidney|renal|pelvis|gall|spleen|bladder/, ['Liver', 'Gallbladder', 'Right kidney', 'Left kidney', 'Spleen', 'Pancreas', 'Aorta', 'Bladder', 'Bowel loops', 'Free fluid']],
    [/head|brain|skull/, ['Brain', 'Lateral ventricle', 'Third ventricle', 'Skull vault', 'Midline', 'Sinus', 'Orbit']],
    [/knee/, ['Femur', 'Tibia', 'Fibula', 'Patella', 'Joint space', 'Fracture line']],
    [/hip|femur|pelvis/, ['Femoral head', 'Acetabulum', 'Femoral neck', 'Pelvis', 'Fracture line']],
    [/spine|lumbar|cervical|thoracic/, ['Vertebral body', 'Disc space', 'Spinal canal', 'Pedicle']],
    [/hand|wrist|ankle|foot|elbow|shoulder|humerus|radius|tibia/, ['Bone', 'Joint', 'Fracture line', 'Soft tissue swelling']],
    [/heart|echo/, ['Left ventricle', 'Right ventricle', 'Left atrium', 'Right atrium', 'Mitral valve', 'Pericardial effusion']],
  ];
  const ABNORMAL = ['Opacity', 'Consolidation', 'Effusion', 'Cavity', 'Mass', 'Nodule', 'Fracture', 'Collection', 'Pneumothorax', 'Free air'];
  const suggestions = () => {
    const m = STRUCTURES.find(([re]) => re.test(REGION) || re.test(MODALITY));
    return [...(m ? m[1] : ['Organ', 'Bone', 'Soft tissue']), ...ABNORMAL];
  };
  const SYN = {cardiac: 'heart', lungs: 'lung', pulmonary: 'lung', hepatic: 'liver', renal: 'kidney', kidneys: 'kidney', bones: 'bone', ribs: 'rib',
               airway: 'trachea', windpipe: 'trachea', diaphragm: 'hemidiaphragm', fluid: 'effusion', ventricles: 'ventricle'};
  const norm = t => String(t || '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ').split(/\s+/).filter(Boolean).map(w => SYN[w] || w.replace(/s$/, ''));
  const PALETTE = ['#4FC3F7', '#81C784', '#BA68C8', '#4DD0E1', '#AED581', '#7986CB', '#F06292', '#FFB74D', '#90A4AE', '#9575CD'];
  const colourFor = (name, kind) => kind === 'finding' ? '#FF6B6B' : kind === 'other' ? '#FFD166'
    : PALETTE[[...String(name || '')].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % PALETTE.length];

  /* ------------------------------------------------------------------ the worker: region growing, contours, snapping */
  function workerMain() {
    let G = null, E = null, W = 0, H = 0, edgeT = 1;
    function prepare(gray, w, h) {
      W = w; H = h;
      const tmp = new Float32Array(w * h); G = new Float32Array(w * h);     // 5x5 box smoothing (two 3x3 passes)
      const pass = (src, dst) => { for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        let s = 0, n = 0;
        for (let dy = -1; dy <= 1; dy++) { const yy = y + dy; if (yy < 0 || yy >= h) continue;
          for (let dx = -1; dx <= 1; dx++) { const xx = x + dx; if (xx < 0 || xx >= w) continue; s += src[yy * w + xx]; n++; } }
        dst[y * w + x] = s / n; } };
      pass(gray, tmp); pass(tmp, G);
      E = new Float32Array(w * h);
      const at = (x, y) => G[Math.min(h - 1, Math.max(0, y)) * w + Math.min(w - 1, Math.max(0, x))];
      const mags = [];
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const gx = (at(x + 1, y - 1) + 2 * at(x + 1, y) + at(x + 1, y + 1)) - (at(x - 1, y - 1) + 2 * at(x - 1, y) + at(x - 1, y + 1));
        const gy = (at(x - 1, y + 1) + 2 * at(x, y + 1) + at(x + 1, y + 1)) - (at(x - 1, y - 1) + 2 * at(x, y - 1) + at(x + 1, y - 1));
        const m = Math.sqrt(gx * gx + gy * gy) / 8; E[y * w + x] = m; if ((x + y) % 7 === 0) mags.push(m);
      }
      mags.sort((a, b) => a - b);
      edgeT = mags[Math.floor(mags.length * .92)] || .05;      // the strongest 8 % of edges stop the growth
    }
    function grow(sx, sy, tol, edgeK) {
      sx = Math.max(0, Math.min(W - 1, Math.round(sx))); sy = Math.max(0, Math.min(H - 1, Math.round(sy)));
      let seed = 0, n = 0;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) { const x = sx + dx, y = sy + dy; if (x >= 0 && y >= 0 && x < W && y < H) { seed += G[y * W + x]; n++; } }
      seed /= n;
      const lim = edgeT * edgeK, mask = new Uint8Array(W * H), stack = new Int32Array(W * H);
      let top = 0, count = 0, sum = 0; const max = W * H * .6;
      stack[top++] = sy * W + sx; mask[sy * W + sx] = 1;
      while (top) {
        const i = stack[--top], x = i % W, y = (i / W) | 0; count++; sum += G[i];
        if (count > max) return {tooBig: true};
        const mean = sum / count;                                   // the reference drifts slowly with the region
        const ref = .7 * seed + .3 * mean;
        for (let k = 0; k < 4; k++) {
          const nx = x + (k === 0) - (k === 1), ny = y + (k === 2) - (k === 3);
          if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
          const j = ny * W + nx;
          if (mask[j]) continue;
          if (Math.abs(G[j] - ref) <= tol && E[j] < lim) { mask[j] = 1; stack[top++] = j; }
        }
      }
      if (count < 12) return {tooSmall: true};
      fillHoles(mask);
      close(mask);
      return {poly: contour(mask), count, seed};
    }
    function fillHoles(mask) {                     // background reachable from the border stays outside
      const out = new Uint8Array(W * H), st = []; const push = i => { if (!mask[i] && !out[i]) { out[i] = 1; st.push(i); } };
      for (let x = 0; x < W; x++) { push(x); push((H - 1) * W + x); } for (let y = 0; y < H; y++) { push(y * W); push(y * W + W - 1); }
      while (st.length) { const i = st.pop(), x = i % W, y = (i / W) | 0;
        if (x > 0) push(i - 1); if (x < W - 1) push(i + 1); if (y > 0) push(i - W); if (y < H - 1) push(i + W); }
      for (let i = 0; i < W * H; i++) if (!out[i]) mask[i] = 1;
    }
    function close(mask) {                          // dilate then erode once: smooths ragged borders and tiny gaps
      const d = new Uint8Array(W * H);
      for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) { const i = y * W + x;
        d[i] = mask[i] | mask[i - 1] | mask[i + 1] | mask[i - W] | mask[i + W]; }
      for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) { const i = y * W + x;
        mask[i] = d[i] & d[i - 1] & d[i + 1] & d[i - W] & d[i + W]; }
    }
    function contour(mask) {                        // Moore-neighbour tracing of the outer border
      let start = -1;
      for (let i = 0; i < W * H; i++) if (mask[i]) { start = i; break; }
      if (start < 0) return [];
      const dirs = [[1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]];
      const on = (x, y) => x >= 0 && y >= 0 && x < W && y < H && mask[y * W + x];
      let x = start % W, y = (start / W) | 0, d = 7; const pts = [[x, y]]; const sx = x, sy = y;
      for (let guard = 0; guard < W * H * 2; guard++) {
        let found = false;
        for (let k = 0; k < 8; k++) {
          const nd = (d + 6 + k) % 8, nx = x + dirs[nd][0], ny = y + dirs[nd][1];
          if (on(nx, ny)) { x = nx; y = ny; d = nd; found = true; break; }
        }
        if (!found || (x === sx && y === sy)) break;
        pts.push([x, y]);
      }
      return smooth(simplify(pts, .9), 2);
    }
    function simplify(P, eps) {                     // Douglas-Peucker on a closed chain
      if (P.length < 8) return P;
      const dp = (a, b) => {
        let best = -1, bi = -1; const [x1, y1] = P[a], [x2, y2] = P[b], L = Math.hypot(x2 - x1, y2 - y1) || 1;
        for (let i = a + 1; i < b; i++) { const dd = Math.abs((y2 - y1) * P[i][0] - (x2 - x1) * P[i][1] + x2 * y1 - y2 * x1) / L; if (dd > best) { best = dd; bi = i; } }
        return best > eps ? [...dp(a, bi).slice(0, -1), ...dp(bi, b)] : [P[a], P[b]];
      };
      const mid = Math.floor(P.length / 2);
      return [...dp(0, mid).slice(0, -1), ...dp(mid, P.length - 1)];
    }
    function smooth(P, it) {                        // Chaikin corner cutting
      for (let k = 0; k < it && P.length > 3; k++) {
        const Q = [];
        for (let i = 0; i < P.length; i++) { const a = P[i], b = P[(i + 1) % P.length];
          Q.push([.75 * a[0] + .25 * b[0], .75 * a[1] + .25 * b[1]], [.25 * a[0] + .75 * b[0], .25 * a[1] + .75 * b[1]]); }
        P = Q;
      }
      return P.length > 400 ? P.filter((_, i) => i % Math.ceil(P.length / 400) === 0) : P;
    }
    function snap(P, r) {                           // move each point along its normal to the strongest nearby edge
      const n = P.length, out = [];
      for (let i = 0; i < n; i++) {
        const a = P[(i - 1 + n) % n], b = P[(i + 1) % n], tx = b[0] - a[0], ty = b[1] - a[1], L = Math.hypot(tx, ty) || 1;
        const nx = -ty / L, ny = tx / L; let best = P[i], bv = -1;
        for (let t = -r; t <= r; t += .5) {
          const x = Math.round(P[i][0] + nx * t), y = Math.round(P[i][1] + ny * t);
          if (x < 0 || y < 0 || x >= W || y >= H) continue;
          const v = E[y * W + x] - Math.abs(t) / r * edgeT * .35;   // prefer edges close to where the hand drew
          if (v > bv) { bv = v; best = [P[i][0] + nx * t, P[i][1] + ny * t]; }
        }
        out.push(best);
      }
      const sm = out.map((p, i) => { const a = out[(i - 1 + n) % n], b = out[(i + 1) % n]; return [(a[0] + 2 * p[0] + b[0]) / 4, (a[1] + 2 * p[1] + b[1]) / 4]; });
      return smooth(simplify(sm, .6), 1);
    }
    self.onmessage = e => {
      const d = e.data;
      if (d.type === 'image') { prepare(d.gray, d.w, d.h); self.postMessage({type: 'ready'}); return; }
      if (!G) return;
      if (d.type === 'grow') self.postMessage({type: 'grown', id: d.id, final: d.final, ...grow(d.x, d.y, d.tol, d.edge)});
      if (d.type === 'snap') self.postMessage({type: 'snapped', id: d.id, poly: snap(d.points, d.r)});
      if (d.type === 'simplify') self.postMessage({type: 'simplified', id: d.id, poly: smooth(simplify(d.points, d.eps), 2)});
    };
  }

  /* ------------------------------------------------------------------ state */
  let worker = null, ready = false, k = 1, reqId = 0, lastHover = 0;
  let preview = null, previewInfo = null, drawing = null, pendingSnap = null, waiters = {};
  const opts = {tol: .08, edge: 1, kind: 'organ', snap: true};
  const W = {};

  function startWorker() {
    if (worker) return;
    worker = new Worker(URL.createObjectURL(new Blob([`(${workerMain.toString()})()`], {type: 'text/javascript'})));
    worker.onmessage = e => {
      const d = e.data;
      if (d.type === 'ready') { ready = true; return; }
      if (d.type === 'grown') {
        if (d.final) { const w = waiters[d.id]; delete waiters[d.id]; w && w(d); return; }
        if (d.id !== reqId) return;
        preview = d.poly ? d.poly.map(([x, y]) => [x / k, y / k]) : null;
        previewInfo = d.tooBig ? 'Too large: lower “Grow” or click inside a smaller structure' : d.tooSmall ? 'Too small: raise “Grow”' : null;
        IV.redraw(); barHint();
      }
      if (d.type === 'snapped' || d.type === 'simplified') { const w = waiters[d.id]; delete waiters[d.id]; w && w(d.poly); }
    };
  }
  const ask = msg => new Promise(res => { const id = ++reqId; waiters[id] = res; worker.postMessage({...msg, id}); });

  function loadWorking() {
    ready = false;
    const img = root.querySelector('.iv-pane.main img');
    if (!img || !img.naturalWidth) return;
    k = Math.min(1, WORK / Math.max(img.naturalWidth, img.naturalHeight));
    const w = Math.max(1, Math.round(img.naturalWidth * k)), h = Math.max(1, Math.round(img.naturalHeight * k));
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const g = c.getContext('2d', {willReadFrequently: true}); g.drawImage(img, 0, 0, w, h);
    let px; try { px = g.getImageData(0, 0, w, h).data; } catch (e) { return; }
    const gray = new Float32Array(w * h);
    for (let i = 0; i < w * h; i++) gray[i] = (.299 * px[i * 4] + .587 * px[i * 4 + 1] + .114 * px[i * 4 + 2]) / 255;
    startWorker();
    worker.postMessage({type: 'image', gray, w, h}, [gray.buffer]);
  }

  /* ------------------------------------------------------------------ preview layer */
  IV.addLayer((svg, s, el) => {
    const path = P => 'M' + P.map(q => q.join(',')).join('L') + 'Z';
    if (IV.tool === 'wand' && preview && preview.length > 2) {
      const g = el('g', {class: 'iv-wand'}, svg);
      el('path', {d: path(preview), class: 'iv-wand-fill', style: `--pc:${colourFor('', opts.kind)}`}, g);
      el('path', {d: path(preview), class: 'iv-wand-ants'}, g);
    }
    if (drawing && drawing.length > 1) {
      el('path', {d: 'M' + drawing.map(q => q.join(',')).join('L'), class: 'iv-lasso'}, svg);
    }
  });

  /* ------------------------------------------------------------------ tools */
  IV.registerTool('wand', {
    hoverObjects: false,
    move(p, e, dragging) {
      if (!ready || dragging) return;
      const now = performance.now(); if (now - lastHover < 35) return; lastHover = now;
      reqId++; worker.postMessage({type: 'grow', id: reqId, x: p[0] * k, y: p[1] * k, tol: opts.tol, edge: opts.edge, final: false});
    },
    leave() { preview = null; IV.redraw(); },
    async up(p) {
      if (!ready) { toast('Still preparing the image. Try again in a moment.', 'warning'); return; }
      const d = await ask({type: 'grow', x: p[0] * k, y: p[1] * k, tol: opts.tol, edge: opts.edge, final: true});
      if (!d.poly || d.poly.length < 3) { toast(d.tooBig ? 'That would select most of the image. Lower “Grow”, or click inside a smaller structure.' : 'Nothing to select there. Raise “Grow”.', 'warning'); return; }
      const poly = d.poly.map(([x, y]) => [x / k, y / k]);
      preview = null; IV.redraw();
      nameIt(poly, 'smart');
    },
  });
  IV.registerTool('outline', {
    down(p) { drawing = [p]; IV.redraw(); },
    move(p, e, dragging) {
      if (!dragging || !drawing) return;
      const last = drawing[drawing.length - 1], s = IV.size?.scale || 1;
      if (Math.hypot(p[0] - last[0], p[1] - last[1]) * s > 3) { drawing.push(p); IV.redraw(); }
    },
    async up() {
      const pts = drawing; drawing = null; IV.redraw();
      if (!pts || pts.length < 6) { toast('Trace all the way round the structure.', 'warning'); return; }
      const sz = IV.size, scaled = pts.map(([x, y]) => [x * k, y * k]);
      let poly = await ask({type: 'simplify', points: scaled, eps: .8});
      if (opts.snap && ready) poly = await ask({type: 'snap', points: poly, r: Math.max(3, Math.min(sz.w, sz.h) * k * .02)});
      nameIt(poly.map(([x, y]) => [x / k, y / k]), 'drawn');
    },
  });

  /* ------------------------------------------------------------------ segment bar (while a tool is on) */
  function buildBar() {
    const bar = document.createElement('div');
    bar.className = 'ivg-bar'; bar.hidden = true;
    bar.innerHTML = `<div class="ivg-kind" role="radiogroup" aria-label="What you are outlining">
        ${[['organ', 'Organ'], ['finding', 'Abnormal'], ['other', 'Other']].map(([v, l]) => `<button type="button" data-kind="${v}" class="k-${v}">${l}</button>`).join('')}</div>
      <label class="ivg-grow" data-only="wand">Grow <input type="range" min=".02" max=".3" step=".01" value="${opts.tol}" data-g="tol"></label>
      <label class="ivg-grow" data-only="wand" title="How strongly edges stop the selection">Edges <input type="range" min=".4" max="3" step=".1" value="${opts.edge}" data-g="edge"></label>
      <label class="ivg-snap" data-only="outline"><input type="checkbox" class="form-check-input" data-g="snap" ${opts.snap ? 'checked' : ''}> Snap to edges</label>
      <span class="ivg-hint"></span>`;
    root.querySelector('.iv-pane.main').appendChild(bar);
    ['pointerdown', 'wheel', 'dblclick'].forEach(t => bar.addEventListener(t, e => e.stopPropagation()));
    bar.addEventListener('input', e => { const g = e.target.dataset.g; if (!g) return; opts[g] = e.target.type === 'checkbox' ? e.target.checked : +e.target.value; preview = null; IV.redraw(); });
    bar.addEventListener('click', e => { const b = e.target.closest('[data-kind]'); if (b) { opts.kind = b.dataset.kind; syncBar(); } });
    W.bar = bar;
    syncBar();
  }
  function syncBar() {
    const t = IV.tool, on = t === 'wand' || t === 'outline';
    W.bar.hidden = !on;
    W.bar.querySelectorAll('[data-only]').forEach(x => { x.hidden = x.dataset.only !== t; });
    W.bar.querySelectorAll('[data-kind]').forEach(b => b.classList.toggle('on', b.dataset.kind === opts.kind));
    barHint();
  }
  function barHint() {
    const h = W.bar?.querySelector('.ivg-hint'); if (!h) return;
    h.textContent = IV.tool === 'wand' ? (previewInfo || (ready ? 'Move over a structure · click to keep it · Alt+scroll to grow' : 'Preparing the image…'))
      : IV.tool === 'outline' ? 'Trace around it with the mouse or a finger' : '';
  }
  root.querySelector('.iv-pane.main').addEventListener('wheel', e => {
    if (IV.tool !== 'wand' || !e.altKey) return;
    e.preventDefault(); e.stopPropagation();
    opts.tol = Math.min(.3, Math.max(.02, opts.tol + (e.deltaY < 0 ? .01 : -.01)));
    const r = W.bar.querySelector('[data-g=tol]'); if (r) r.value = opts.tol;
    preview = null; lastHover = 0;
  }, {capture: true, passive: false});

  /* ------------------------------------------------------------------ naming a new outline */
  function card(html, cls = '') {
    closeCard();
    const c = document.createElement('div');
    c.className = `ivg-card ${cls}`; c.innerHTML = html;
    root.querySelector('.iv-pane.main').appendChild(c);
    ['pointerdown', 'wheel', 'dblclick', 'keydown'].forEach(t => c.addEventListener(t, e => e.stopPropagation()));
    W.card = c;
    return c;
  }
  function closeCard() { W.card?.remove(); W.card = null; }

  function nameIt(poly, source) {
    if (!CAN_EDIT) { toast('Only imaging staff can save outlines.', 'warning'); return; }
    let kind = opts.kind;
    const sugg = suggestions();
    const c = card(`<div class="ivg-card-h"><i class="bi bi-vector-pen"></i><b>Name this outline</b><button type="button" class="ivg-x" data-c="cancel" aria-label="Cancel"><i class="bi bi-x-lg"></i></button></div>
      <input class="form-control form-control-sm" data-c="name" list="ivg-names" placeholder="e.g. Heart, Left lung, Effusion" maxlength="60" aria-label="Name">
      <datalist id="ivg-names">${sugg.map(n => `<option value="${esc(n)}">`).join('')}</datalist>
      <div class="ivg-chips">${sugg.slice(0, 10).map(n => `<button type="button" data-name="${esc(n)}">${esc(n)}</button>`).join('')}</div>
      <div class="ivg-kind">${[['organ', 'Organ'], ['finding', 'Abnormal'], ['other', 'Other']].map(([v, l]) => `<button type="button" data-k="${v}" class="k-${v}${v === kind ? ' on' : ''}">${l}</button>`).join('')}</div>
      <textarea class="form-control form-control-sm" data-c="note" rows="2" maxlength="300" placeholder="Note (optional)"></textarea>
      <div class="ivg-card-go"><button type="button" class="btn btn-primary btn-sm" data-c="save"><i class="bi bi-check2"></i>Keep outline</button>
        <button type="button" class="btn btn-ghost btn-sm" data-c="cancel">Discard</button></div>`, 'name');
    const input = c.querySelector('[data-c=name]');
    setTimeout(() => input.focus(), 30);
    // show what is being named
    const ghost = {poly};
    const layer = (svg, s, el) => { if (W.card === c) el('path', {d: 'M' + ghost.poly.map(q => q.join(',')).join('L') + 'Z', class: 'iv-ghost', style: `--pc:${colourFor(input.value, kind)}`}, svg); };
    IV.addLayer(layer); IV.redraw();
    const finish = save => {
      if (save) {
        const name = input.value.trim() || (kind === 'finding' ? 'Abnormal area' : kind === 'organ' ? 'Organ' : 'Outline');
        const i = IV.addPolygon(poly, {label: name, kind, source, color: colourFor(name, kind), text: c.querySelector('[data-c=note]').value.trim()});
        toast(`${name} outlined. Press Save on the viewer to keep it with the image.`, 'success');
        closeCard(); if (i >= 0) inspect(i);
      } else { closeCard(); IV.redraw(); }
    };
    c.addEventListener('click', e => {
      const n = e.target.closest('[data-name]'); if (n) { input.value = n.dataset.name; if (ABNORMAL.includes(n.dataset.name)) setKind('finding'); IV.redraw(); return; }
      const kk = e.target.closest('[data-k]'); if (kk) { setKind(kk.dataset.k); return; }
      const a = e.target.closest('[data-c]')?.dataset.c;
      if (a === 'save') finish(true); if (a === 'cancel') finish(false);
    });
    c.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target === input) finish(true); if (e.key === 'Escape') finish(false); });
    function setKind(v) { kind = v; c.querySelectorAll('[data-k]').forEach(b => b.classList.toggle('on', b.dataset.k === v)); IV.redraw(); }
  }

  /* ------------------------------------------------------------------ inspector */
  function inspect(i) {
    const a = IV.annotations[i]; if (!a || a.type !== 'polygon') { closeCard(); return; }
    const m = IV.measure(i), col = IV.colourFor(a), lit = IV.spot.some(t => t.type === 'ann' && t.i === i);
    const src = {smart: 'Smart select', drawn: 'Drawn by hand', ai: 'From Dr. Flow'}[a.source] || 'Drawn';
    const c = card(`<div class="ivg-card-h"><span class="ivg-dot" style="background:${col}"></span><b>${esc(a.label || m.label)}</b>
        <span class="ivg-tag k-${esc(a.kind)}">${{organ: 'Organ', finding: 'Abnormal', other: 'Other'}[a.kind] || 'Other'}</span>
        <button type="button" class="ivg-x" data-c="close" aria-label="Close"><i class="bi bi-x-lg"></i></button></div>
      <dl class="ivg-meas"><dt>Area</dt><dd>${esc(m.area)}</dd><dt>Around</dt><dd>${esc(m.perimeter)}</dd>
        ${m.stats ? `<dt>Brightness</dt><dd>${m.stats.mean.toFixed(0)} ± ${m.stats.sd.toFixed(0)}</dd>` : ''}<dt>Made by</dt><dd>${esc(src)}</dd></dl>
      ${IV.size?.mm ? '' : '<p class="ivg-small">Calibrate the image (ruler tool → K) to get millimetres.</p>'}
      ${a.text ? `<p class="ivg-note">${esc(a.text)}</p>` : ''}
      <div class="ivg-actions">
        <button type="button" data-c="spot" class="${lit ? 'on' : ''}"><i class="bi bi-brightness-high"></i>${lit ? 'Spotlight on' : 'Spotlight'}</button>
        <button type="button" data-c="zoom"><i class="bi bi-zoom-in"></i>Zoom to</button>
        ${HAS_AI ? '<button type="button" data-c="ask"><i class="bi bi-stars"></i>Ask Dr. Flow</button>' : ''}
        ${CAN_EDIT ? `<button type="button" data-c="snap" title="Pull the outline onto the nearest strong edges"><i class="bi bi-magnet"></i>Snap to edges</button>
          <button type="button" data-c="rename"><i class="bi bi-pencil"></i>Rename</button>
          <span class="ivg-swatches">${['#4FC3F7', '#81C784', '#BA68C8', '#FFB74D', '#FF6B6B', '#FFD166'].map(x => `<button type="button" data-col="${x}" style="background:${x}" aria-label="Colour"></button>`).join('')}</span>
          <button type="button" data-c="delete" class="danger"><i class="bi bi-trash"></i></button>` : ''}
      </div>`, 'inspect');
    c.addEventListener('click', async e => {
      const col2 = e.target.closest('[data-col]'); if (col2) { IV.updateAnnotation(i, {color: col2.dataset.col}); inspect(i); return; }
      const act = e.target.closest('[data-c]')?.dataset.c;
      if (act === 'close') { closeCard(); IV.select(-1); }
      if (act === 'spot') { IV.spotlight(lit ? [] : [{type: 'ann', i}]); inspect(i); }
      if (act === 'zoom') IV.zoomToBox(boxOf(a.points));
      if (act === 'ask') askAbout(a.points, a.label);
      if (act === 'rename') { const v = prompt('Name', a.label || ''); if (v !== null) { IV.updateAnnotation(i, {label: v.trim().slice(0, 60)}); inspect(i); } }
      if (act === 'delete' && confirm(`Delete the outline “${a.label || 'Outline'}”?`)) { IV.removeAnnotation(i); closeCard(); }
      if (act === 'snap') {
        if (!ready) return toast('Still preparing the image.', 'warning');
        const sz = IV.size, P = await ask({type: 'snap', points: a.points.map(([x, y]) => [x * k, y * k]), r: Math.max(3, Math.min(sz.w, sz.h) * k * .015)});
        IV.updateAnnotation(i, {points: P.map(([x, y]) => [+(x / k).toFixed(2), +(y / k).toFixed(2)])}); inspect(i);
        toast('Outline snapped to the nearest edges. Undo with Ctrl+Z if it got worse.', 'info');
      }
    });
  }
  const boxOf = P => { const sz = IV.size, xs = P.map(p => p[0] / sz.w), ys = P.map(p => p[1] / sz.h);
    const x0 = Math.min(...xs), y0 = Math.min(...ys); return [x0, y0, Math.max(...xs) - x0, Math.max(...ys) - y0]; };
  function askAbout(points, name) {
    const sz = IV.size; if (!sz) return;
    const shape = points.map(([x, y]) => [+(x / sz.w).toFixed(4), +(y / sz.h).toFixed(4)]);
    IV.root.dispatchEvent(new CustomEvent('iva:area', {detail: {box: boxOf(points), shape, question: name ? `About the outlined ${name}: ` : ''}}));
    document.getElementById('iva')?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  /* ------------------------------------------------------------------ find: "show me the heart" */
  let pendingFind = null;
  function findTargets(text) {
    const want = norm(text); if (!want.length) return [];
    const score = name => { const have = norm(name); return want.filter(w => have.includes(w)).length / want.length; };
    const out = [];
    IV.annotations.forEach(a => { if (a.type === 'polygon' && score(a.label) >= .99) out.push({type: 'ann', i: a.index}); });
    IV.labels.forEach((lb, i) => { if ((lb.outline || lb.box) && score(lb.name) >= .99) out.push({type: 'ai', i}); });
    if (!out.length) {      // partial matches ("lung" also finds "Right lung" and "Left lung")
      IV.annotations.forEach(a => { if (a.type === 'polygon' && score(a.label) > 0) out.push({type: 'ann', i: a.index}); });
      IV.labels.forEach((lb, i) => { if ((lb.outline || lb.box) && score(lb.name) > 0) out.push({type: 'ai', i}); });
    }
    return out;
  }
  function showAll(targets) {
    closeCard();
    IV.spotlight(targets);
    const sz = IV.size, pts = targets.flatMap(t => IV.outline(t) || []);
    if (pts.length && sz) { const b = boxOf(pts); IV.zoomToBox([Math.max(0, b[0] - .03), Math.max(0, b[1] - .03), Math.min(1, b[2] + .06), Math.min(1, b[3] + .06)]); }
  }
  function find(text) {
    text = String(text || '').trim(); if (!text) { IV.spotlight([]); return; }
    const t = findTargets(text);
    if (t.length) { showAll(t); status(`Showing ${t.length === 1 ? (IV.describe(t[0])?.name || text) : `${t.length} matches`} · Esc to clear`); return; }
    if (HAS_AI) {
      pendingFind = text;
      status(`Asking Dr. Flow to outline “${text}”…`);
      IV.root.dispatchEvent(new CustomEvent('iva:run', {detail: {kind: 'outline', question: text}}));
    } else status(`Nothing called “${text}” is outlined on this image yet.`);
  }
  function status(t) { if (W.findStatus) W.findStatus.textContent = t || ''; }
  IV.root.addEventListener('iva:done', e => {
    if (!pendingFind) return;
    const text = pendingFind; pendingFind = null;
    setTimeout(() => { const t = findTargets(text); if (t.length) { showAll(t); status(`Dr. Flow outlined ${t.length === 1 ? `“${IV.describe(t[0])?.name}”` : `${t.length} matches`}`); }
                       else status(`Dr. Flow could not find “${text}” on this image.`); }, 120);
  });
  IV.root.addEventListener('iva:failed', () => { if (pendingFind) { status('Dr. Flow did not answer. Try again.'); pendingFind = null; } });

  function buildFind() {
    const f = root.querySelector('[data-find]'); if (!f) return;
    W.findStatus = root.querySelector('.ivg-find-status');
    const names = () => [...new Set([...IV.annotations.filter(a => a.type === 'polygon').map(a => a.label), ...IV.labels.map(l => l.name), ...suggestions()])];
    f.addEventListener('focus', () => { const dl = document.getElementById('ivg-find-list'); if (dl) dl.innerHTML = names().map(n => `<option value="${esc(n)}">`).join(''); });
    f.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); find(f.value); } if (e.key === 'Escape') { f.value = ''; IV.spotlight([]); status(''); f.blur(); } });
    f.addEventListener('change', () => find(f.value));
  }

  /* ------------------------------------------------------------------ wiring */
  IV.root.addEventListener('iv:tool', () => { preview = null; drawing = null; syncBar(); IV.redraw(); });
  IV.root.addEventListener('iv:select', e => { if (e.detail.index >= 0 && e.detail.type === 'polygon') inspect(e.detail.index); else if (W.card?.classList.contains('inspect')) closeCard(); });
  IV.root.addEventListener('iv:image', () => { closeCard(); preview = null; pendingFind = null; status(''); });
  const mainImg = root.querySelector('.iv-pane.main img');
  mainImg.addEventListener('load', loadWorking);
  if (mainImg.complete && mainImg.naturalWidth) loadWorking();
  document.addEventListener('keydown', e => {
    if (e.target.closest('input,textarea,select,dialog')) return;
    if (e.key === 'm' && CAN_EDIT) IV.setTool('wand');
    if (e.key === 'd' && CAN_EDIT) IV.setTool('outline');
    if (e.key === '/' ) { const f = root.querySelector('[data-find]'); if (f) { e.preventDefault(); f.focus(); } }
    if (e.key === 'h') IV.showNames(!IV.namesShown);
  });
  buildBar(); buildFind();
  window.ImagingSegment = {find, askAbout, inspect};
})();
