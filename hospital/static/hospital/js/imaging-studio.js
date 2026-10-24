/* Imaging studio: make the picture easier to read, with Dr. Flow's help.

   * Dr. Flow enhance: the server measures the picture (exposure, contrast, grain, glare, blur) and proposes a recipe for
     the controls, with the reason for each step (imaging_studio.py; nothing leaves the hospital's server).
   * Looks for common jobs (lungs, bone, soft tissue, ultrasound, film photo, night reading, photo-real) and fine controls.
   * Photo-real: illustrative colour from brightness plus relief lighting, so the picture reads like a photograph.
     Colours come from brightness only; they do not identify tissue and are labelled as illustrative wherever shown.
   * Before / after: wipe between the original and the studio rendering.
   * Navigator: a map of the whole image with the part on screen, zoom controls, box zoom, and a tour of Dr. Flow's labels.
   * Save as a new image: the server recomputes the result at full resolution from the original (imaging_tools.process).

   The rendering runs in a Web Worker on a working copy (long side WORK px) and is laid over the image through
   window.ImagingViewer.setOverlay, so it pans, zooms and rotates with it. The same steps, in the same order and with the
   same radii (relative to image size), run on the server when saving, so the copy matches what was seen. */
(() => {
  'use strict';
  const IV = window.ImagingViewer;
  const root = document.getElementById('iv');
  if (!IV || !root) return;
  const CAN_SAVE = root.dataset.canEdit === '1' && !!root.dataset.processUrl;
  const ASSIST = root.dataset.assistUrl || '';
  const CSRF = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '';
  const urlFor = (tpl, id) => tpl.replace('/0/', `/${id}/`);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const toast = (m, k) => window.mfToast ? mfToast(m, k) : alert(m);
  const WORK = 1400;

  /* ------------------------------------------------------------------ looks (same as imaging_studio.PRESETS) */
  const PRESETS = {
    original: ['Original', {}],
    lungs: ['Lungs', {smooth: .25, level: true, enhance: 2.5, gamma: .95, detail: .8, sharpen: .5}],
    bone: ['Bone', {smooth: .2, level: true, enhance: 2, gamma: .85, detail: 1.1, sharpen: 1.1, edges: .25}],
    soft: ['Soft tissue', {smooth: .45, level: true, enhance: 1.5, gamma: 1.2, detail: .5}],
    ultrasound: ['Ultrasound', {smooth: .8, level: true, enhance: 1, gamma: 1.1, detail: .4}],
    film: ['Film photo', {smooth: .35, level: true, glare: .8, enhance: 2, gamma: 1, detail: .7, sharpen: .6}],
    night: ['Night reading', {smooth: .25, level: true, enhance: 2, detail: .6, invert: true}],
    photo: ['Photo-real', {smooth: .45, level: true, enhance: 1.8, detail: .9, colour: 'anatomy', relief: .55, light: 315}],
  };
  const PALETTES = {
    anatomy: ['Anatomy', [[0, [6, 8, 14]], [.12, [22, 30, 52]], [.26, [92, 58, 40]], [.38, [176, 128, 72]], [.5, [178, 106, 92]], [.64, [206, 142, 124]],
                          [.78, [230, 198, 172]], [.9, [244, 236, 214]], [1, [255, 252, 244]]]],
    warm: ['Warm film', [[0, [8, 5, 2]], [.35, [88, 52, 26]], [.7, [214, 170, 118]], [1, [255, 246, 226]]]],
    cool: ['Cool blue', [[0, [2, 6, 14]], [.4, [24, 72, 120]], [.75, [140, 196, 226]], [1, [246, 252, 255]]]],
    heat: ['Heat', [[0, [0, 0, 0]], [.3, [120, 10, 10]], [.55, [230, 90, 10]], [.8, [255, 210, 60]], [1, [255, 255, 230]]]],
    spectrum: ['Spectrum', [[0, [20, 0, 90]], [.2, [0, 70, 220]], [.4, [0, 190, 170]], [.6, [120, 220, 40]], [.8, [250, 170, 0]], [1, [230, 20, 20]]]],
  };
  const BLANK = {smooth: 0, level: false, glare: 0, enhance: 0, gamma: 1, detail: 0, sharpen: 0, invert: false, colour: '', relief: 0, light: 315, edges: 0};
  const SLIDERS = [
    ['smooth', 'Clarity (remove grain & speckle)', 0, 1, .05, v => `${Math.round(v * 100)}%`],
    ['glare', 'Glare & light box', 0, 1, .05, v => `${Math.round(v * 100)}%`],
    ['enhance', 'Adaptive contrast', 0, 4, .1, v => v.toFixed(1)],
    ['gamma', 'Mid-tones', .4, 2.5, .05, v => v.toFixed(2)],
    ['detail', 'Anatomical detail', 0, 2, .05, v => v.toFixed(2)],
    ['sharpen', 'Fine edges', 0, 3, .1, v => v.toFixed(1)],
  ];

  /* ------------------------------------------------------------------ the worker: same maths as imaging_studio.py */
  function workerMain() {
    const radius = (w, h, f) => Math.max(1, Math.round(Math.min(w, h) * f));
    function box1(src, w, h, r, horizontal) {          // running mean, window shrunk at the ends
      const out = new Float32Array(w * h), n = horizontal ? w : h, m = horizontal ? h : w;
      const c = new Float64Array(n + 1);
      for (let j = 0; j < m; j++) {
        c[0] = 0;
        for (let i = 0; i < n; i++) c[i + 1] = c[i] + src[horizontal ? j * w + i : i * w + j];
        for (let i = 0; i < n; i++) {
          const lo = Math.max(0, i - r), hi = Math.min(n, i + r + 1);
          out[horizontal ? j * w + i : i * w + j] = (c[hi] - c[lo]) / (hi - lo);
        }
      }
      return out;
    }
    const box = (a, w, h, r) => r < 1 ? a : box1(box1(a, w, h, Math.min(r, h - 1), false), w, h, Math.min(r, w - 1), true);
    const blur = (a, w, h, r) => box(box(box(a, w, h, r), w, h, r), w, h, r);
    function pct(a, ps) {                             // percentiles from a fine histogram
      const B = 4096, hist = new Uint32Array(B);
      for (let i = 0; i < a.length; i++) hist[Math.min(B - 1, Math.max(0, (a[i] * (B - 1)) | 0))]++;
      return ps.map(p => { const t = p / 100 * (a.length - 1); let acc = 0;
        for (let b = 0; b < B; b++) { acc += hist[b]; if (acc > t) return b / (B - 1); } return 1; });
    }
    function guided(g, w, h, s) {
      if (s <= 0) return g;
      const r = radius(w, h, .004 + .012 * s), eps = (.02 + .10 * s) ** 2, n = g.length;
      const g2 = new Float32Array(n); for (let i = 0; i < n; i++) g2[i] = g[i] * g[i];
      const m = box(g, w, h, r), m2 = box(g2, w, h, r), A = new Float32Array(n), B = new Float32Array(n);
      for (let i = 0; i < n; i++) { const v = Math.max(m2[i] - m[i] * m[i], 0), a = v / (v + eps); A[i] = a; B[i] = m[i] - a * m[i]; }
      const ma = box(A, w, h, r), mb = box(B, w, h, r), out = new Float32Array(n);
      for (let i = 0; i < n; i++) out[i] = Math.min(1, Math.max(0, ma[i] * g[i] + mb[i]));
      return out;
    }
    function clahe(g, w, h, clip) {                   // port of imaging_tools.clahe on 8-bit values
      const tiles = 8, ty = Math.max(1, Math.min(tiles, (h / 16) | 0)), tx = Math.max(1, Math.min(tiles, (w / 16) | 0));
      const ys = Array.from({length: ty + 1}, (_, i) => Math.floor(i * h / ty)), xs = Array.from({length: tx + 1}, (_, i) => Math.floor(i * w / tx));
      const u8 = new Uint8Array(g.length); for (let i = 0; i < g.length; i++) u8[i] = Math.min(255, Math.max(0, Math.floor(g[i] * 255 + .5)));
      const luts = new Float32Array(ty * tx * 256);
      for (let i = 0; i < ty; i++) for (let j = 0; j < tx; j++) {
        const hist = new Float32Array(256); let size = 0;
        for (let y = ys[i]; y < ys[i + 1]; y++) for (let x = xs[j]; x < xs[j + 1]; x++) { hist[u8[y * w + x]]++; size++; }
        const limit = Math.max(1, clip * size / 256); let excess = 0;
        for (let k = 0; k < 256; k++) if (hist[k] > limit) { excess += hist[k] - limit; hist[k] = limit; }
        let acc = 0, mn = Infinity, mx = -Infinity; const cdf = new Float32Array(256);
        for (let k = 0; k < 256; k++) { acc += hist[k] + excess / 256; cdf[k] = acc; mn = Math.min(mn, acc); mx = Math.max(mx, acc); }
        const o = (i * tx + j) * 256, span = Math.max(1, mx - mn);
        for (let k = 0; k < 256; k++) luts[o + k] = (cdf[k] - mn) / span * 255;
      }
      const cy = Array.from({length: ty}, (_, i) => (ys[i] + ys[i + 1]) / 2), cx = Array.from({length: tx}, (_, j) => (xs[j] + xs[j + 1]) / 2);
      const interp = (v, c, n) => { if (n === 1 || v <= c[0]) return 0; if (v >= c[n - 1]) return n - 1;
        let k = 0; while (c[k + 1] < v) k++; return k + (v - c[k]) / (c[k + 1] - c[k]); };
      const fy = new Float32Array(h), fx = new Float32Array(w);
      for (let y = 0; y < h; y++) fy[y] = interp(y, cy, ty);
      for (let x = 0; x < w; x++) fx[x] = interp(x, cx, tx);
      const out = new Float32Array(g.length);
      for (let y = 0; y < h; y++) {
        const y0 = Math.floor(fy[y]), y1 = Math.min(y0 + 1, ty - 1), wy = fy[y] - y0;
        for (let x = 0; x < w; x++) {
          const x0 = Math.floor(fx[x]), x1 = Math.min(x0 + 1, tx - 1), wx = fx[x] - x0, v = u8[y * w + x];
          const a = luts[(y0 * tx + x0) * 256 + v], b = luts[(y0 * tx + x1) * 256 + v], c = luts[(y1 * tx + x0) * 256 + v], d = luts[(y1 * tx + x1) * 256 + v];
          out[y * w + x] = Math.min(255, Math.max(0, Math.floor((a * (1 - wx) + b * wx) * (1 - wy) + (c * (1 - wx) + d * wx) * wy))) / 255;
        }
      }
      return out;
    }
    function sobel(g, w, h) {
      const gx = new Float32Array(g.length), gy = new Float32Array(g.length);
      const at = (x, y) => g[Math.min(h - 1, Math.max(0, y)) * w + Math.min(w - 1, Math.max(0, x))];
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const i = y * w + x;
        gx[i] = ((at(x + 1, y - 1) + 2 * at(x + 1, y) + at(x + 1, y + 1)) - (at(x - 1, y - 1) + 2 * at(x - 1, y) + at(x - 1, y + 1))) / 8;
        gy[i] = ((at(x - 1, y + 1) + 2 * at(x, y + 1) + at(x + 1, y + 1)) - (at(x - 1, y - 1) + 2 * at(x, y - 1) + at(x + 1, y - 1))) / 8;
      }
      return [gx, gy];
    }
    function lut(stops) {
      const out = new Float32Array(256 * 3);
      for (let i = 0; i < 256; i++) {
        const t = i / 255; let k = 0; while (k < stops.length - 2 && stops[k + 1][0] < t) k++;
        const [p0, c0] = stops[k], [p1, c1] = stops[k + 1], f = Math.min(1, Math.max(0, (t - p0) / ((p1 - p0) || 1)));
        for (let c = 0; c < 3; c++) out[i * 3 + c] = (c0[c] + (c1[c] - c0[c]) * f) / 255;
      }
      return out;
    }
    function render(src, w, h, o, palettes) {
      let g = src.slice(), n = g.length;
      const clamp = v => v < 0 ? 0 : v > 1 ? 1 : v;
      if (o.smooth > 0) g = guided(g, w, h, o.smooth);
      if (o.level) { const [lo, hi] = pct(g, [.5, 99.5]); if (hi - lo > 1e-3) for (let i = 0; i < n; i++) g[i] = clamp((g[i] - lo) / (hi - lo)); }
      if (o.glare > 0) {
        let knee = Math.min(Math.max(pct(g, [85])[0], .55), .95); const span = 1 - knee, den = 1 - Math.exp(-2.2);
        for (let i = 0; i < n; i++) if (g[i] > knee) {
          const sq = knee + span * (1 - Math.exp(-(g[i] - knee) / Math.max(span, 1e-3) * 2.2)) / den;
          g[i] = clamp(knee + (sq - knee) * (1 - .6 * o.glare));
        }
      }
      if (o.enhance > 0) g = clahe(g, w, h, 1 + Math.min(o.enhance, 4));
      if (Math.abs(o.gamma - 1) > .02) { const e = 1 / Math.max(.3, Math.min(o.gamma, 3)); for (let i = 0; i < n; i++) g[i] = Math.pow(clamp(g[i]), e); }
      if (o.detail > 0) { const b = blur(g, w, h, radius(w, h, .03));
        for (let i = 0; i < n; i++) g[i] = clamp(g[i] + o.detail * .9 * 4 * g[i] * (1 - g[i]) * (g[i] - b[i])); }
      if (o.sharpen > 0) { const b = blur(g, w, h, radius(w, h, .0015)), a = o.sharpen * .8;
        for (let i = 0; i < n; i++) g[i] = clamp(g[i] + a * (g[i] - b[i])); }
      if (o.invert) for (let i = 0; i < n; i++) g[i] = 1 - g[i];
      const rgb = new Float32Array(n * 3);
      if (o.colour && palettes[o.colour]) { const L = lut(palettes[o.colour]);
        for (let i = 0; i < n; i++) { const k = Math.min(255, Math.max(0, Math.floor(g[i] * 255 + .5))) * 3; rgb[i * 3] = L[k]; rgb[i * 3 + 1] = L[k + 1]; rgb[i * 3 + 2] = L[k + 2]; } }
      else for (let i = 0; i < n; i++) rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = g[i];
      if (o.relief > 0) {
        const hgt = blur(g, w, h, radius(w, h, .002)), [gx, gy] = sobel(hgt, w, h), k = 6 * Math.min(w, h) / 512;
        const a = o.light * Math.PI / 180, lx = Math.sin(a) * .62, ly = -Math.cos(a) * .62, lz = .78, s = o.relief;
        for (let i = 0; i < n; i++) {
          const nx = -gx[i] * k, ny = -gy[i] * k, nn = Math.sqrt(nx * nx + ny * ny + 1);
          const lam = clamp((nx * lx + ny * ly + lz) / nn), spec = Math.pow(lam, 24) * .35, shade = .45 + .75 * lam;
          for (let c = 0; c < 3; c++) { const v = rgb[i * 3 + c]; rgb[i * 3 + c] = v * (1 - s) + clamp(v * shade + spec) * s; }
        }
      }
      if (o.edges > 0) {
        const [gx, gy] = sobel(guided(g, w, h, .4), w, h), mag = new Float32Array(n);
        let mx = 0; for (let i = 0; i < n; i++) { mag[i] = Math.sqrt(gx[i] * gx[i] + gy[i] * gy[i]); if (mag[i] > mx) mx = mag[i]; }
        const scaled = new Float32Array(n); for (let i = 0; i < n; i++) scaled[i] = mag[i] / (mx || 1);
        const hi = (pct(scaled, [97])[0] * (mx || 1)) || 1e-3, E = [63 / 255, 224 / 255, 208 / 255];
        for (let i = 0; i < n; i++) { const al = clamp((mag[i] - hi * .45) / (hi * .75)) * o.edges;
          for (let c = 0; c < 3; c++) rgb[i * 3 + c] = rgb[i * 3 + c] * (1 - al) + E[c] * al; }
      }
      const out = new Uint8ClampedArray(n * 4);
      for (let i = 0; i < n; i++) { out[i * 4] = rgb[i * 3] * 255 + .5; out[i * 4 + 1] = rgb[i * 3 + 1] * 255 + .5; out[i * 4 + 2] = rgb[i * 3 + 2] * 255 + .5; out[i * 4 + 3] = 255; }
      return out;
    }
    let src = null, W = 0, H = 0;
    self.onmessage = e => {
      const d = e.data;
      if (d.type === 'image') { src = d.gray; W = d.w; H = d.h; return; }
      if (d.type === 'render' && src) {
        const t = performance.now(), px = render(src, W, H, d.opts, d.palettes);
        self.postMessage({type: 'frame', id: d.id, px, w: W, h: H, ms: Math.round(performance.now() - t)}, [px.buffer]);
      }
    };
  }

  /* ------------------------------------------------------------------ state */
  let worker = null, workId = 0, busy = false, queued = false, imageReady = false;
  let opts = {...BLANK}, look = 'original', on = false, swipe = 100, assist = null, canvas = null, ctx2d = null, frameUrl = null;
  let imgId = null, navDrag = false, tourIndex = -1;
  const W = {};

  function startWorker() {
    if (worker) return worker;
    const blob = new Blob([`(${workerMain.toString()})()`], {type: 'text/javascript'});
    worker = new Worker(URL.createObjectURL(blob));
    worker.onmessage = e => {
      const d = e.data;
      if (d.type !== 'frame') return;
      busy = false;
      if (on && d.id === workId) paint(d);
      if (queued) { queued = false; render(); }
    };
    worker.onerror = () => { busy = false; toast('The studio could not run in this browser.', 'danger'); };
    return worker;
  }

  /* the current image as a grey working copy, sent to the worker */
  function loadWorkingCopy() {
    imageReady = false;
    const img = root.querySelector('.iv-pane.main img');
    if (!img || !img.naturalWidth) return;
    const k = Math.min(1, WORK / Math.max(img.naturalWidth, img.naturalHeight));
    const w = Math.max(1, Math.round(img.naturalWidth * k)), h = Math.max(1, Math.round(img.naturalHeight * k));
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const g = c.getContext('2d', {willReadFrequently: true}); g.drawImage(img, 0, 0, w, h);
    let data;
    try { data = g.getImageData(0, 0, w, h).data; } catch (e) { return; }
    const gray = new Float32Array(w * h);
    for (let i = 0; i < w * h; i++) gray[i] = (.299 * data[i * 4] + .587 * data[i * 4 + 1] + .114 * data[i * 4 + 2]) / 255;
    startWorker().postMessage({type: 'image', gray, w, h}, [gray.buffer]);
    canvas = document.createElement('canvas'); canvas.width = w; canvas.height = h; ctx2d = canvas.getContext('2d');
    imageReady = true;
    drawNavThumb(c);
  }

  function render() {
    if (!on || !imageReady) return;
    if (busy) { queued = true; return; }
    busy = true; workId++;
    const palettes = Object.fromEntries(Object.entries(PALETTES).map(([k, v]) => [k, v[1]]));
    worker.postMessage({type: 'render', id: workId, opts: {...opts}, palettes});
    status('Rendering…');
  }

  function paint(d) {
    ctx2d.putImageData(new ImageData(d.px, d.w, d.h), 0, 0);
    if (frameUrl) URL.revokeObjectURL(frameUrl);
    canvas.toBlob(b => { frameUrl = URL.createObjectURL(b); IV.setOverlay(canvas, frameUrl); applySwipe(); drawNavThumb(canvas); }, 'image/jpeg', .9);
    IV.setOverlay(canvas, frameUrl);
    applySwipe();
    status(`${describe()} · ${d.ms} ms`);
    badge();
  }

  function applySwipe() {
    if (!canvas) return;
    canvas.style.clipPath = swipe >= 100 ? '' : `inset(0 0 0 ${100 - swipe}%)`;
  }

  /* ------------------------------------------------------------------ panel */
  function build() {
    const panes = root.querySelector('.iv-panes');
    const el = document.createElement('aside');
    el.className = 'ivs'; el.hidden = true; el.setAttribute('aria-label', 'Imaging studio');
    el.innerHTML = `
      <header class="ivs-head"><i class="bi bi-palette2"></i><b>Studio</b><span class="ivs-status" aria-live="polite"></span>
        <button type="button" class="ivs-x" data-s="wide" title="Widen the viewer"><i class="bi bi-arrows-angle-expand"></i></button>
        <button type="button" class="ivs-x" data-s="close" aria-label="Close the studio"><i class="bi bi-x-lg"></i></button></header>
      <div class="ivs-body">
        ${ASSIST ? `<section class="ivs-drflow">
          <button type="button" class="btn btn-primary btn-sm w-100" data-s="assist"><i class="bi bi-stars"></i>Dr. Flow, make it clearer</button>
          <div class="ivs-assist" hidden></div>
          <div class="ivs-row2">
            <button type="button" class="btn btn-ghost btn-sm" data-s="anatomy" title="Dr. Flow labels the bones, organs and landmarks"><i class="bi bi-tags"></i>Label the parts</button>
            <button type="button" class="btn btn-ghost btn-sm" data-s="area" title="Select an area and ask Dr. Flow about it"><i class="bi bi-bounding-box-circles"></i>Ask about an area</button>
          </div>
        </section>` : ''}
        <section><div class="ivs-h">Looks</div>
          <div class="ivs-looks">${Object.entries(PRESETS).map(([k, [l]]) => `<button type="button" data-look="${k}" class="${k === 'photo' ? 'photo' : ''}">${esc(l)}</button>`).join('')}</div></section>
        <section><div class="ivs-h">Make it readable</div>
          ${SLIDERS.map(([k, l, mn, mx, st]) => `<label class="ivs-range"><span>${esc(l)}<b data-v="${k}"></b></span><input type="range" min="${mn}" max="${mx}" step="${st}" data-k="${k}"></label>`).join('')}
          <div class="ivs-checks"><label><input type="checkbox" class="form-check-input" data-k="level"> Level exposure</label>
            <label><input type="checkbox" class="form-check-input" data-k="invert"> Invert</label></div></section>
        <section><div class="ivs-h">Photo-real <span class="ivs-hint">illustrative</span></div>
          <div class="ivs-pal"><button type="button" data-pal="" title="No colour">Grey</button>${Object.entries(PALETTES).map(([k, [l, st]]) =>
            `<button type="button" data-pal="${k}" title="${esc(l)}" style="--sw:linear-gradient(90deg,${st.map(([p, c]) => `rgb(${c}) ${p * 100}%`).join(',')})"><i></i>${esc(l)}</button>`).join('')}</div>
          <label class="ivs-range"><span>Relief (3-D light)<b data-v="relief"></b></span><input type="range" min="0" max="1" step=".05" data-k="relief"></label>
          <div class="ivs-light"><span>Light from</span><input type="range" min="0" max="360" step="5" data-k="light" aria-label="Light direction"><i class="ivs-sun" aria-hidden="true"></i></div>
          <label class="ivs-range"><span>Outline edges<b data-v="edges"></b></span><input type="range" min="0" max="1" step=".05" data-k="edges"></label>
          <p class="ivs-note"><i class="bi bi-info-circle"></i> Colour is assigned from brightness only, to make the picture easier to read. It does not show tissue type, blood flow or disease. Report from the original.</p></section>
        <section><div class="ivs-h">Before / after</div>
          <label class="ivs-range"><span>Original ◂ ▸ Studio<b data-v="swipe"></b></span><input type="range" min="0" max="100" step="1" value="100" data-swipe></label>
          <div class="ivs-row2"><button type="button" class="btn btn-ghost btn-sm" data-s="hold" title="Hold to see the original"><i class="bi bi-eye"></i>Hold for original</button>
            <button type="button" class="btn btn-ghost btn-sm" data-s="reset"><i class="bi bi-arrow-counterclockwise"></i>Reset</button></div></section>
        ${CAN_SAVE ? `<section><button type="button" class="btn btn-ink btn-sm w-100" data-s="save"><i class="bi bi-floppy"></i>Save as a new image</button>
          <p class="ivs-note">Made at full resolution from the original, which stays unchanged.</p></section>` : ''}
      </div>`;
    panes.appendChild(el);
    W.panel = el;

    const badgeEl = document.createElement('div');
    badgeEl.className = 'ivs-badge'; badgeEl.hidden = true;
    root.querySelector('.iv-pane.main').appendChild(badgeEl);
    W.badge = badgeEl;

    const nav = document.createElement('div');
    nav.className = 'ivs-nav';
    nav.innerHTML = `<canvas width="180" height="140" aria-label="Navigator: click or drag to move around the image"></canvas>
      <div class="ivs-navbar">
        <button type="button" data-n="out" title="Zoom out (−)"><i class="bi bi-dash-lg"></i></button><span class="ivs-zoom">100%</span>
        <button type="button" data-n="in" title="Zoom in (+)"><i class="bi bi-plus-lg"></i></button>
        <button type="button" data-n="box" title="Box zoom: drag around what you want (Z)"><i class="bi bi-zoom-in"></i></button>
        <button type="button" data-n="one" title="Actual pixels (1:1)">1:1</button>
        <button type="button" data-n="fit" title="Fit (0)"><i class="bi bi-arrows-angle-contract"></i></button>
        <button type="button" data-n="hide" title="Hide the navigator"><i class="bi bi-chevron-down"></i></button>
      </div>
      <div class="ivs-tour" hidden><button type="button" data-n="prev" title="Previous label"><i class="bi bi-chevron-left"></i></button>
        <span class="ivs-tour-name"></span><button type="button" data-n="next" title="Next label"><i class="bi bi-chevron-right"></i></button></div>`;
    root.querySelector('.iv-pane.main').appendChild(nav);
    W.nav = nav; W.navCanvas = nav.querySelector('canvas');
    bind();
    syncControls();
  }

  function syncControls() {
    const p = W.panel; if (!p) return;
    p.querySelectorAll('[data-k]').forEach(i => { const k = i.dataset.k; i.type === 'checkbox' ? (i.checked = !!opts[k]) : (i.value = opts[k]); });
    SLIDERS.forEach(([k, , , , , f]) => { const b = p.querySelector(`[data-v="${k}"]`); if (b) b.textContent = f(+opts[k]); });
    p.querySelector('[data-v="relief"]').textContent = `${Math.round(opts.relief * 100)}%`;
    p.querySelector('[data-v="edges"]').textContent = `${Math.round(opts.edges * 100)}%`;
    p.querySelector('[data-v="swipe"]').textContent = swipe >= 100 ? 'studio' : swipe <= 0 ? 'original' : `${swipe}%`;
    p.querySelector('.ivs-sun').style.transform = `rotate(${opts.light}deg)`;
    p.querySelectorAll('[data-look]').forEach(b => b.classList.toggle('on', b.dataset.look === look));
    p.querySelectorAll('[data-pal]').forEach(b => b.classList.toggle('on', b.dataset.pal === (opts.colour || '')));
  }

  function setOpts(next, name) {
    opts = {...BLANK, ...next};
    look = name || 'custom';
    syncControls();
    if (look === 'original' && !Object.keys(next).length) { clearOverlay(); status('Original'); return; }
    render();
  }

  function clearOverlay() { IV.setOverlay(null); badge(); }

  function describe() {
    const bits = [];
    if (opts.smooth) bits.push('clarity'); if (opts.level) bits.push('levelled'); if (opts.glare) bits.push('glare'); if (opts.enhance) bits.push('contrast');
    if (Math.abs(opts.gamma - 1) > .02) bits.push('mid-tones'); if (opts.detail) bits.push('detail'); if (opts.sharpen) bits.push('edges');
    if (opts.invert) bits.push('inverted'); if (opts.colour) bits.push(PALETTES[opts.colour][0].toLowerCase() + ' colour');
    if (opts.relief) bits.push('relief'); if (opts.edges) bits.push('outlines');
    return bits.join(' · ') || 'no changes';
  }
  function status(t) { const s = W.panel?.querySelector('.ivs-status'); if (s) s.textContent = t || ''; }
  function badge() {
    const show = on && IV.overlay && (opts.colour || opts.relief || opts.edges);
    W.badge.hidden = !show;
    if (show) W.badge.innerHTML = opts.colour || opts.relief ? '<i class="bi bi-palette2"></i> Illustrative colour · not for diagnosis'
      : '<i class="bi bi-bezier"></i> Edges outlined by the studio · report from the original';
  }

  /* ------------------------------------------------------------------ Dr. Flow enhance */
  async function runAssist() {
    const btn = W.panel.querySelector('[data-s=assist]'), box = W.panel.querySelector('.ivs-assist');
    btn.disabled = true; const label = btn.innerHTML; btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Checking the picture…';
    const RD = window.RoboDoc;
    const thinking = RD ? RD.summon().then(() => RD.think(['Measuring exposure', 'Looking for grain and speckle', 'Checking for glare', 'Choosing the steps'])) : null;
    try {
      const res = await fetch(urlFor(ASSIST, IV.current.id), {credentials: 'same-origin'});
      const d = await res.json();
      if (!res.ok || !d.ok) throw new Error(d.error || 'Dr. Flow could not check this picture.');
      assist = d;
      const r = d.recipe, ring = d.score;
      box.hidden = false;
      box.innerHTML = `<div class="ivs-q"><div class="ivs-ring" style="--v:${ring}"><span>${ring}</span></div>
          <div><b>${esc(d.verdict)} readability</b><div class="small muted">${esc(d.modality)} · ${esc(d.region)}</div>
          <div class="ivs-issues">${(d.issues.length ? d.issues : ['No major problems']).map(i => `<span>${esc(i)}</span>`).join('')}</div></div></div>
        <ol class="ivs-why">${d.reasons.map(x => `<li>${esc(x.text)}</li>`).join('')}</ol>
        <p class="ivs-note mb-0">Steps chosen from measurements of this picture on the hospital's server. Adjust any control below.</p>`;
      setOpts({...r}, 'drflow');
      if (RD) thinking.then(() => RD.done(`Readability <b>${ring}</b>/100 (${esc(d.verdict.toLowerCase())}). I applied ${d.reasons.length} steps; the reasons are in the studio panel.`));
    } catch (err) {
      toast(err.message, 'danger');
      if (RD) thinking.then(() => RD.fail(esc(err.message)));
    } finally {
      btn.disabled = false; btn.innerHTML = label;
    }
  }

  /* ------------------------------------------------------------------ save */
  async function save() {
    const b = W.panel.querySelector('[data-s=save]');
    if (look === 'original' && JSON.stringify(opts) === JSON.stringify(BLANK)) { toast('Choose a look or move a control first.', 'warning'); return; }
    if ((opts.colour || opts.relief) && !confirm('Save an illustrative colour copy? It will be marked as illustrative and is not for diagnosis.')) return;
    b.disabled = true; const label = b.innerHTML; b.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Making the full-size copy…';
    try {
      const res = await fetch(urlFor(root.dataset.processUrl, IV.current.id), {method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': CSRF}, body: JSON.stringify({...opts, grayscale: true, save: true, studio: look})});
      const d = await res.json();
      if (!d.ok) throw new Error(d.error || 'Could not save.');
      location.href = d.redirect;
    } catch (err) { toast(err.message, 'danger'); b.disabled = false; b.innerHTML = label; }
  }

  /* ------------------------------------------------------------------ navigator */
  let thumbSrc = null;
  function drawNavThumb(src) { thumbSrc = src; drawNav(); }
  function navGeom() {
    const v = IV.view(); if (!v) return null;
    const c = W.navCanvas, k = Math.min(c.width / v.w, c.height / v.h);
    return {v, k, ox: (c.width - v.w * k) / 2, oy: (c.height - v.h * k) / 2};
  }
  function drawNav() {
    const G = navGeom(); if (!G || !W.navCanvas) return;
    const c = W.navCanvas, g = c.getContext('2d'), {v, k, ox, oy} = G;
    g.clearRect(0, 0, c.width, c.height);
    if (thumbSrc) g.drawImage(thumbSrc, ox, oy, v.w * k, v.h * k);
    else { const img = root.querySelector('.iv-pane.main img'); if (img?.complete) g.drawImage(img, ox, oy, v.w * k, v.h * k); }
    g.fillStyle = 'rgba(8,16,24,.45)'; g.fillRect(ox, oy, v.w * k, v.h * k);
    g.save(); g.beginPath();
    v.corners.forEach(([x, y], i) => { const px = ox + Math.min(v.w, Math.max(0, x)) * k, py = oy + Math.min(v.h, Math.max(0, y)) * k; i ? g.lineTo(px, py) : g.moveTo(px, py); });
    g.closePath(); g.clip();
    if (thumbSrc) g.drawImage(thumbSrc, ox, oy, v.w * k, v.h * k);
    g.restore();
    g.beginPath(); v.corners.forEach(([x, y], i) => { const px = ox + x * k, py = oy + y * k; i ? g.lineTo(px, py) : g.moveTo(px, py); }); g.closePath();
    g.strokeStyle = '#3FE0B0'; g.lineWidth = 1.5; g.stroke();
    (IV.labels || []).forEach((lb, i) => {
      const p = lb.box ? [lb.box[0] + lb.box[2] / 2, lb.box[1] + lb.box[3] / 2] : lb.point; if (!p) return;
      g.beginPath(); g.arc(ox + p[0] * v.w * k, oy + p[1] * v.h * k, i === tourIndex ? 4 : 2.5, 0, 7);
      g.fillStyle = {urgent: '#ff5d6c', abnormal: '#ff9f43', watch: '#ffd166', normal: '#3FE0B0'}[lb.concern] || '#ffd166'; g.fill();
    });
    W.nav.querySelector('.ivs-zoom').textContent = `${Math.round(v.scale * 100)}%`;
    tour();
  }
  function navTo(e) {
    const G = navGeom(); if (!G) return;
    const r = W.navCanvas.getBoundingClientRect(), sx = W.navCanvas.width / r.width, sy = W.navCanvas.height / r.height;
    const ix = ((e.clientX - r.left) * sx - G.ox) / G.k, iy = ((e.clientY - r.top) * sy - G.oy) / G.k;
    IV.centreOn(Math.min(G.v.w, Math.max(0, ix)), Math.min(G.v.h, Math.max(0, iy)), Math.max(G.v.z, 1));
  }
  function tour() {
    const labels = IV.labels || [], t = W.nav.querySelector('.ivs-tour');
    t.hidden = !labels.length;
    if (!labels.length) { tourIndex = -1; return; }
    if (tourIndex >= labels.length) tourIndex = -1;
    t.querySelector('.ivs-tour-name').textContent = tourIndex < 0 ? `Tour ${labels.length} label${labels.length === 1 ? '' : 's'}` : `${labels[tourIndex].n || tourIndex + 1}. ${labels[tourIndex].name}`;
  }
  function step(d) {
    const labels = IV.labels || []; if (!labels.length) return;
    tourIndex = (tourIndex + d + labels.length) % labels.length;
    IV.focusLabel(tourIndex, true);
    IV.root.dispatchEvent(new CustomEvent('iv:ai-select', {detail: {index: tourIndex}}));
    drawNav();
  }

  /* ------------------------------------------------------------------ events */
  function bind() {
    const p = W.panel;
    p.addEventListener('input', e => {
      const k = e.target.dataset.k;
      if (k) { opts[k] = e.target.type === 'checkbox' ? e.target.checked : +e.target.value; look = 'custom'; syncControls(); render(); }
      if (e.target.matches('[data-swipe]')) { swipe = +e.target.value; applySwipe(); syncControls(); }
    });
    p.addEventListener('click', e => {
      const lk = e.target.closest('[data-look]'); if (lk) { const [, r] = PRESETS[lk.dataset.look]; setOpts({...r}, lk.dataset.look); return; }
      const pl = e.target.closest('[data-pal]');
      if (pl) { opts.colour = pl.dataset.pal; if (opts.colour && !opts.relief) opts.relief = .35; look = 'custom'; syncControls(); render(); return; }
      const s = e.target.closest('[data-s]')?.dataset.s;
      if (s === 'close') toggle(false);
      if (s === 'wide') { const sec = root.closest('.viewer-panel'), wide = !sec.classList.contains('iv-wide'); sec.classList.toggle('iv-wide', wide);
        e.target.closest('[data-s]').innerHTML = `<i class="bi bi-arrows-angle-${wide ? 'contract' : 'expand'}"></i>`; sec.scrollIntoView({behavior: 'smooth', block: 'start'}); }
      if (s === 'assist') runAssist();
      if (s === 'reset') { swipe = 100; setOpts({}, 'original'); const sw = p.querySelector('[data-swipe]'); if (sw) sw.value = 100; }
      if (s === 'save') save();
      if (s === 'anatomy') IV.root.dispatchEvent(new CustomEvent('iva:run', {detail: {kind: 'anatomy'}}));
      if (s === 'area') { IV.areaMode(true); toast('Drag a box around the area, then ask your question in the Dr. Flow panel.', 'info'); }
    });
    const hold = p.querySelector('[data-s=hold]');
    const show = v => { if (canvas) canvas.style.visibility = v ? '' : 'hidden'; };
    hold.addEventListener('pointerdown', () => show(false));
    ['pointerup', 'pointerleave', 'pointercancel'].forEach(t => hold.addEventListener(t, () => show(true)));

    // the navigator sits inside the image pane: keep its pointer and wheel events away from the pane's pan/zoom/draw
    ['pointerdown', 'dblclick', 'wheel', 'contextmenu'].forEach(t => W.nav.addEventListener(t, e => e.stopPropagation()));
    W.navCanvas.addEventListener('pointerdown', e => { navDrag = true; W.navCanvas.setPointerCapture(e.pointerId); navTo(e); });
    W.navCanvas.addEventListener('pointermove', e => { if (navDrag) navTo(e); });
    W.navCanvas.addEventListener('pointerup', () => { navDrag = false; });
    W.navCanvas.addEventListener('wheel', e => { e.preventDefault(); IV.zoomBy(e.deltaY < 0 ? 1.2 : 1 / 1.2); }, {passive: false});
    W.nav.addEventListener('click', e => {
      const n = e.target.closest('[data-n]')?.dataset.n; if (!n) return;
      if (n === 'in') IV.zoomBy(1.4); if (n === 'out') IV.zoomBy(1 / 1.4);
      if (n === 'box') IV.zoomTool(); if (n === 'fit') IV.fit();
      if (n === 'one') { const v = IV.view(); if (v) { const c = [(v.corners[0][0] + v.corners[2][0]) / 2, (v.corners[0][1] + v.corners[2][1]) / 2]; IV.centreOn(c[0], c[1], v.z / v.scale); } }
      if (n === 'hide') W.nav.classList.toggle('min');
      if (n === 'prev') step(-1); if (n === 'next') step(1);
    });

    IV.root.addEventListener('iv:view', drawNav);
    IV.root.addEventListener('iv:image', () => { thumbSrc = null; tourIndex = -1; imgId = IV.current?.id; });
    const mainImg = root.querySelector('.iv-pane.main img');
    mainImg.addEventListener('load', () => { loadWorkingCopy(); if (on && look !== 'original') render(); else clearOverlay(); drawNav(); });
    if (mainImg.complete && mainImg.naturalWidth) loadWorkingCopy();
    // labels change when Dr. Flow answers or another answer is chosen
    new MutationObserver(() => drawNav()).observe(root.querySelector('.iv-pane.main svg'), {childList: true});
    document.addEventListener('keydown', e => {
      if (e.target.closest('input,textarea,select,dialog')) return;
      if (e.key === 's' && !e.ctrlKey && !e.metaKey) toggle();
      if (e.key === 'b' && on && canvas) { canvas.style.visibility = canvas.style.visibility === 'hidden' ? '' : 'hidden'; }
      if (e.key === 'n') step(1);
    });
  }

  function toggle(force) {
    on = force ?? !on;
    W.panel.hidden = !on;
    root.querySelector('[data-act=studio]')?.classList.toggle('on', on);
    root.querySelector('.iv-panes').classList.toggle('studio-open', on);
    if (on) { if (!imageReady) loadWorkingCopy(); if (look !== 'original') render(); }
    else clearOverlay();
    badge();
  }

  root.addEventListener('click', e => { if (e.target.closest('[data-act=studio]')) toggle(); });
  build();
  window.ImagingStudio = {toggle, apply: (r, name) => { toggle(true); setOpts(r, name || 'custom'); }, get options() { return {...opts}; }};
})();
