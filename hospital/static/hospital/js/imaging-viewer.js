/* Imaging viewer: zoom/pan, window/level, rotate/flip, invert, colour maps, magnifier, side-by-side compare,
   measurement tools (ruler, angle, Cobb angle, elliptical region with intensity stats, arrow, note) with mm
   calibration, saved per image, and a photo-processing dialog (straighten from 4 corners, enhance, denoise).
   Display adjustments never change the stored image; processing saves a new copy beside the original.
   Dr. Flow (imaging-ai.js) draws its AI labels on a separate layer through window.ImagingViewer, and the "Cover
   names" tool paints boxes that are blacked out on the server before an image is sent to the AI. */
(() => {
  'use strict';
  const root = document.getElementById('iv');
  if (!root) return;
  const DATA = JSON.parse(document.getElementById('viewer-data').textContent);
  const CAN_EDIT = root.dataset.canEdit === '1';
  const CSRF = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '';
  const urlFor = (tpl, id) => tpl.replace('/0/', `/${id}/`);
  const $ = (s, el = root) => el.querySelector(s), $$ = (s, el = root) => [...el.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const NS = 'http://www.w3.org/2000/svg';
  const toast = (m, k) => window.mfToast ? mfToast(m, k) : alert(m);

  /* ================================================================ a pane: one image you can zoom, pan, rotate */
  class Pane {
    constructor(el, onChange) {
      this.el = el; this.stage = el.querySelector('.iv-stage'); this.img = el.querySelector('img'); this.svg = el.querySelector('svg');
      this.z = 1; this.fit = 1; this.px = 0; this.py = 0; this.rot = 0; this.flip = false;
      this.f = {b: 100, c: 100, inv: false, lut: ''};
      this.onChange = onChange || (() => {});
      this.img.addEventListener('load', () => { this.w = this.img.naturalWidth; this.h = this.img.naturalHeight; this.reset(); this.onChange('load'); });
      new ResizeObserver(() => this.w && this.apply()).observe(el);
    }
    load(url) { this.img.src = url; }
    reset() { this.z = 1; this.px = this.py = 0; this.rot = 0; this.flip = false; this.computeFit(); this.apply(); }
    computeFit() {
      const r = this.el.getBoundingClientRect(), rotated = this.rot % 180 !== 0;
      const w = rotated ? this.h : this.w, h = rotated ? this.w : this.h;
      this.fit = Math.min(r.width / w, r.height / h) * .96 || 1;
    }
    scale() { return this.fit * this.z; }
    apply() {
      if (!this.w) return;
      const r = this.el.getBoundingClientRect(), s = this.scale();
      Object.assign(this.stage.style, {width: this.w + 'px', height: this.h + 'px',
        transform: `translate(${r.width / 2 + this.px}px,${r.height / 2 + this.py}px) rotate(${this.rot}deg) scale(${this.flip ? -s : s},${s}) translate(${-this.w / 2}px,${-this.h / 2}px)`});
      this.img.style.filter = `brightness(${this.f.b}%) contrast(${this.f.c}%)${this.f.inv ? ' invert(1)' : ''}${this.f.lut ? ` url(#lut-${this.f.lut})` : ''}`;
      this.onChange('view');
    }
    /* screen point (client coords) -> image pixel coords, undoing pan, rotation, flip and zoom */
    toImage(cx, cy) {
      const r = this.el.getBoundingClientRect(), s = this.scale();
      let x = cx - r.left - r.width / 2 - this.px, y = cy - r.top - r.height / 2 - this.py;
      const a = -this.rot * Math.PI / 180, rx = x * Math.cos(a) - y * Math.sin(a), ry = x * Math.sin(a) + y * Math.cos(a);
      return [(this.flip ? -rx : rx) / s + this.w / 2, ry / s + this.h / 2];
    }
    zoomAt(cx, cy, factor) {
      const r = this.el.getBoundingClientRect(), nz = Math.min(20, Math.max(.5, this.z * factor)), k = nz / this.z;
      const ox = cx - r.left - r.width / 2, oy = cy - r.top - r.height / 2;
      this.px = ox - (ox - this.px) * k; this.py = oy - (oy - this.py) * k; this.z = nz; this.apply();
    }
  }

  /* ================================================================ state */
  const main = new Pane($('.iv-pane.main'), what => { if (what === 'load') { loadPixels(); draw(); } else draw(); hud(); syncCompare(); });
  const cmp = new Pane($('.iv-pane.compare'));
  let cur = DATA.images.find(i => i.id === DATA.start) || DATA.images[0];
  let anns = [], mm = null, dirty = false, undo = [], selected = -1, tool = 'pan', pending = null, pixels = null;
  // Dr. Flow's labels for the current image ([{n, name, box:[x,y,w,h]|null, point:[x,y]|null, concern}], fractions 0-1),
  // and the boxes to black out before sending (per image id, fractions 0-1; kept in this page only, never saved)
  const ai = {labels: [], show: true, active: -1};
  const covers = {}; let coverDraft = null;
  const emit = (name, detail) => root.dispatchEvent(new CustomEvent(name, {detail}));

  function select(img) {
    if (dirty && !confirm('You have unsaved measurements on this image. Discard them?')) return false;
    cur = img; anns = JSON.parse(JSON.stringify(img.annotations || [])); mm = img.mm || null; dirty = false; undo = []; selected = -1;
    main.load(img.url);
    $$('.iv-thumb').forEach(t => t.classList.toggle('on', +t.dataset.id === img.id));
    $('.iv-processed').hidden = !img.processed;
    $('.iv-processed span').textContent = img.processed ? describeSteps(img.steps) : '';
    ai.labels = []; ai.active = -1; coverDraft = null;
    status(); list();
    history.replaceState(null, '', `?img=${img.id}`);
    emit('iv:image', {id: img.id});
    return true;
  }
  const describeSteps = st => Object.keys(st || {}).filter(k => k !== 'source_image' && k !== 'resized').map(k => ({corners: 'straightened', grayscale: 'greyscale', enhance: 'contrast enhanced', level: 'levelled', denoise: 'denoised', sharpen: 'sharpened'}[k] || k)).join(', ');

  /* pixel data of the current image, for intensity statistics inside a region */
  function loadPixels() {
    pixels = null;
    try {
      const c = document.createElement('canvas'), max = 1600, k = Math.min(1, max / Math.max(main.w, main.h));
      c.width = Math.round(main.w * k); c.height = Math.round(main.h * k);
      const g = c.getContext('2d', {willReadFrequently: true}); g.drawImage(main.img, 0, 0, c.width, c.height);
      pixels = {data: g.getImageData(0, 0, c.width, c.height).data, w: c.width, h: c.height, k};
    } catch (e) { pixels = null; }
  }

  /* ================================================================ measurements */
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const lenText = px => mm ? (px * mm >= 100 ? `${(px * mm / 10).toFixed(1)} cm` : `${(px * mm).toFixed(1)} mm`) : `${px.toFixed(0)} px`;
  const angleAt = (a, v, c) => { const a1 = Math.atan2(a[1] - v[1], a[0] - v[0]), a2 = Math.atan2(c[1] - v[1], c[0] - v[0]); let d = Math.abs(a1 - a2) * 180 / Math.PI; return d > 180 ? 360 - d : d; };
  const lineAngle = (a, b, c, d) => { let x = Math.abs(Math.atan2(b[1] - a[1], b[0] - a[0]) - Math.atan2(d[1] - c[1], d[0] - c[0])) * 180 / Math.PI; x %= 180; return x > 90 ? 180 - x : x; };
  function roiStats(p1, p2) {
    if (!pixels) return null;
    const cx = (p1[0] + p2[0]) / 2 * pixels.k, cy = (p1[1] + p2[1]) / 2 * pixels.k, rx = Math.abs(p2[0] - p1[0]) / 2 * pixels.k, ry = Math.abs(p2[1] - p1[1]) / 2 * pixels.k;
    if (rx < 1 || ry < 1) return null;
    let n = 0, sum = 0, sq = 0, mn = 255, mx = 0;
    const step = Math.max(1, Math.round(Math.sqrt(rx * ry) / 60));
    for (let y = Math.max(0, Math.floor(cy - ry)); y <= Math.min(pixels.h - 1, cy + ry); y += step)
      for (let x = Math.max(0, Math.floor(cx - rx)); x <= Math.min(pixels.w - 1, cx + rx); x += step) {
        if (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 > 1) continue;
        const i = (y * pixels.w + x) * 4, v = .299 * pixels.data[i] + .587 * pixels.data[i + 1] + .114 * pixels.data[i + 2];
        n++; sum += v; sq += v * v; if (v < mn) mn = v; if (v > mx) mx = v;
      }
    if (!n) return null;
    const mean = sum / n;
    return {mean, sd: Math.sqrt(Math.max(0, sq / n - mean * mean)), min: mn, max: mx};
  }
  function measure(a) {
    const p = a.points;
    if (a.type === 'ruler') return {value: lenText(dist(p[0], p[1])), raw: dist(p[0], p[1]) * (mm || 1), unit: mm ? 'mm' : 'px', label: a.label || 'Length'};
    if (a.type === 'angle') return {value: `${angleAt(p[0], p[1], p[2]).toFixed(1)}°`, raw: angleAt(p[0], p[1], p[2]), unit: '°', label: a.label || 'Angle'};
    if (a.type === 'cobb') return {value: `${lineAngle(p[0], p[1], p[2], p[3]).toFixed(1)}°`, raw: lineAngle(p[0], p[1], p[2], p[3]), unit: '°', label: a.label || 'Cobb angle'};
    if (a.type === 'ellipse') {
      const rx = Math.abs(p[1][0] - p[0][0]) / 2, ry = Math.abs(p[1][1] - p[0][1]) / 2, area = Math.PI * rx * ry, st = roiStats(p[0], p[1]);
      const areaTxt = mm ? (area * mm * mm >= 100 ? `${(area * mm * mm / 100).toFixed(2)} cm²` : `${(area * mm * mm).toFixed(1)} mm²`) : `${area.toFixed(0)} px²`;
      return {value: areaTxt + (st ? ` · mean ${st.mean.toFixed(0)} ± ${st.sd.toFixed(0)}` : ''), raw: mm ? area * mm * mm : area, unit: mm ? 'mm²' : 'px²', label: a.label || 'Region', stats: st};
    }
    return null;
  }

  /* ================================================================ drawing the overlay */
  function el(tag, attrs, parent) { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent && parent.appendChild(e); return e; }
  function draw() {
    const svg = main.svg; if (!main.w) return;
    svg.setAttribute('viewBox', `0 0 ${main.w} ${main.h}`); svg.setAttribute('width', main.w); svg.setAttribute('height', main.h);
    svg.innerHTML = '';
    const s = main.scale(), fs = 13 / s, hr = 5 / s;
    const label = (x, y, txt, g) => {   // labels stay upright and readable whatever the rotation or flip
      const t = el('g', {transform: `translate(${x},${y}) scale(${main.flip ? -1 : 1},1) rotate(${-main.rot})`}, g);
      const tx = el('text', {x: 8 / s, y: -8 / s, 'font-size': fs, class: 'iv-label'}, t); tx.textContent = txt;
      requestAnimationFrame(() => { try { const b = tx.getBBox(); el('rect', {x: b.x - 3 / s, y: b.y - 2 / s, width: b.width + 6 / s, height: b.height + 4 / s, rx: 3 / s, class: 'iv-label-bg'}, t).after(tx); t.appendChild(tx); } catch (e) {} });
    };
    [...anns, ...(pending ? [pending] : [])].forEach((a, i) => {
      const g = el('g', {class: `iv-a ${i === selected ? 'sel' : ''} ${a === pending ? 'pending' : ''}`, 'data-i': a === pending ? -1 : i}, svg);
      const P = a.points, m = a !== pending || P.length >= ({ruler: 2, angle: 3, cobb: 4, ellipse: 2}[a.type] || 9) ? measure(a) : null;
      const line = (p, q) => el('line', {x1: p[0], y1: p[1], x2: q[0], y2: q[1]}, g);
      if (a.type === 'ruler' || a.type === 'calibrate') { if (P[1]) { line(P[0], P[1]); [P[0], P[1]].forEach(p => { const d = [P[1][1] - P[0][1], P[0][0] - P[1][0]], L = Math.hypot(...d) || 1; line([p[0] + d[0] / L * 6 / s, p[1] + d[1] / L * 6 / s], [p[0] - d[0] / L * 6 / s, p[1] - d[1] / L * 6 / s]); }); } }
      if (a.type === 'angle') { if (P[1]) line(P[0], P[1]); if (P[2]) line(P[1], P[2]); }
      if (a.type === 'cobb') { if (P[1]) line(P[0], P[1]); if (P[3]) line(P[2], P[3]); }
      if (a.type === 'ellipse' && P[1]) el('ellipse', {cx: (P[0][0] + P[1][0]) / 2, cy: (P[0][1] + P[1][1]) / 2, rx: Math.abs(P[1][0] - P[0][0]) / 2, ry: Math.abs(P[1][1] - P[0][1]) / 2}, g);
      if (a.type === 'arrow' && P[1]) {
        line(P[0], P[1]);
        const ang = Math.atan2(P[1][1] - P[0][1], P[1][0] - P[0][0]), L = 14 / s;
        el('path', {d: `M${P[1][0]},${P[1][1]} L${P[1][0] - L * Math.cos(ang - .4)},${P[1][1] - L * Math.sin(ang - .4)} L${P[1][0] - L * Math.cos(ang + .4)},${P[1][1] - L * Math.sin(ang + .4)}Z`, class: 'iv-head'}, g);
      }
      if (a.type === 'text' || a.type === 'arrow') { if (a.text) label(P[0][0], P[0][1], a.text, g); if (a.type === 'text') el('circle', {cx: P[0][0], cy: P[0][1], r: 3 / s, class: 'iv-head'}, g); }
      if (m) { const at = a.type === 'angle' ? P[1] : a.type === 'ellipse' ? [Math.max(P[0][0], P[1][0]), Math.min(P[0][1], P[1][1])] : P[P.length - 1]; label(at[0], at[1], `${a.label ? a.label + ': ' : ''}${m.value}`, g); }
      if (a.type === 'calibrate' && P[1]) label(P[1][0], P[1][1], lenText(dist(P[0], P[1])), g);
      if (i === selected && CAN_EDIT) P.forEach((p, k) => el('circle', {cx: p[0], cy: p[1], r: hr, class: 'iv-handle', 'data-h': k}, g));
    });
    drawAi(svg, s, label);
    drawCovers(svg, s);
  }

  /* Dr. Flow's labels: numbered boxes or points, coloured by concern; the active one shows its name */
  function drawAi(svg, s, label) {
    if (!ai.show || !ai.labels.length) return;
    const layer = el('g', {class: 'iv-ai-layer'}, svg), W = main.w, H = main.h;
    ai.labels.forEach((lb, i) => {
      const on = i === ai.active, g = el('g', {class: `iv-ai c-${lb.concern || 'watch'}${on ? ' on' : ''}`, 'data-ai': i}, layer);
      let bx, by;
      if (lb.box) {
        const [x, y, w, h] = lb.box;
        el('rect', {x: x * W, y: y * H, width: w * W, height: h * H, rx: 4 / s, class: 'iv-ai-box'}, g);
        bx = x * W; by = y * H;
      } else if (lb.point) {
        const [x, y] = lb.point;
        el('circle', {cx: x * W, cy: y * H, r: 14 / s, class: 'iv-ai-ring'}, g);
        el('circle', {cx: x * W, cy: y * H, r: 2.5 / s, class: 'iv-ai-dot'}, g);
        bx = x * W - 14 / s; by = y * H - 14 / s;
      } else return;
      const t = el('g', {transform: `translate(${bx},${by}) scale(${main.flip ? -1 : 1},1) rotate(${-main.rot})`, class: 'iv-ai-badge'}, g);
      el('circle', {cx: 0, cy: 0, r: 10 / s}, t);
      const n = el('text', {x: 0, y: 0, 'font-size': 11 / s, 'text-anchor': 'middle', 'dominant-baseline': 'central'}, t); n.textContent = lb.n || i + 1;
      if (on) label(bx + 8 / s, by + 4 / s, lb.name, g);
    });
  }
  /* boxes that will be blacked out before sending to the AI */
  function drawCovers(svg, s) {
    const list = [...(covers[cur?.id] || []), ...(coverDraft ? [coverDraft] : [])];
    if (!list.length) return;
    const layer = el('g', {class: 'iv-cover-layer'}, svg), W = main.w, H = main.h;
    list.forEach((b, i) => {
      const g = el('g', {class: `iv-cover${b === coverDraft ? ' draft' : ''}`, 'data-cover': b === coverDraft ? -1 : i}, layer);
      el('rect', {x: b[0] * W, y: b[1] * H, width: b[2] * W, height: b[3] * H}, g);
      if (b !== coverDraft && b[2] * W * s > 60 && b[3] * H * s > 16) {
        const t = el('text', {x: (b[0] + b[2] / 2) * W, y: (b[1] + b[3] / 2) * H, 'font-size': 11 / s, 'text-anchor': 'middle', 'dominant-baseline': 'central',
          transform: `rotate(${-main.rot} ${(b[0] + b[2] / 2) * W} ${(b[1] + b[3] / 2) * H})`}, g);
        t.textContent = 'hidden from AI';
      }
    });
  }

  /* ================================================================ HUD, list, status */
  function hud() {
    $('.iv-hud').textContent = `${Math.round(main.scale() * 100)}%  ·  B ${main.f.b}  C ${main.f.c}${main.rot ? `  ·  ${main.rot}°` : ''}${main.flip ? '  ·  flipped' : ''}  ·  ${mm ? `${mm.toFixed(3)} mm/px` : 'not calibrated'}`;
  }
  function status() {
    const s = $('.iv-status');
    s.textContent = dirty ? 'Unsaved changes' : anns.length ? `${anns.length} saved` : '';
    s.classList.toggle('dirty', dirty);
    $('[data-act=save]').disabled = !dirty;
  }
  function list() {
    const box = $('.iv-list');
    const rows = anns.map((a, i) => ({a, i, m: measure(a)})).filter(r => r.m || r.a.type === 'text' || r.a.type === 'arrow');
    box.innerHTML = rows.length ? rows.map(({a, i, m}) => `<div class="iv-row ${i === selected ? 'sel' : ''}" data-i="${i}">
        <i class="bi ${{ruler: 'bi-rulers', angle: 'bi-triangle', cobb: 'bi-bezier2', ellipse: 'bi-circle', arrow: 'bi-arrow-up-right', text: 'bi-chat-left-text'}[a.type]}"></i>
        <span class="iv-row-name">${esc(m ? (a.label || m.label) : (a.text || 'Note'))}</span><b>${m ? esc(m.value) : ''}</b>
        ${m && window.addReportMeasurement ? `<button type="button" class="btn btn-sm btn-ghost" data-report="${i}" title="Add to the report"><i class="bi bi-file-earmark-plus"></i></button>` : ''}
        ${CAN_EDIT ? `<button type="button" class="btn btn-sm btn-ghost" data-rename="${i}" title="Name it"><i class="bi bi-pencil"></i></button><button type="button" class="btn btn-sm btn-ghost" data-del="${i}" title="Delete"><i class="bi bi-trash"></i></button>` : ''}</div>`).join('')
      : `<p class="muted small mb-0">${CAN_EDIT ? 'Pick a tool above to measure lengths, angles or regions, or to add arrows and notes. Calibrate first for millimetres.' : 'No measurements on this image.'}</p>`;
  }
  function change(fn) { undo.push(JSON.stringify({anns, mm})); if (undo.length > 60) undo.shift(); fn(); dirty = true; draw(); list(); status(); hud(); }

  /* ================================================================ pointer interaction */
  const NEED = {ruler: 2, angle: 3, cobb: 4, ellipse: 2, arrow: 2, text: 1, calibrate: 2};
  let drag = null;
  const pane = main.el;
  pane.addEventListener('wheel', e => { e.preventDefault(); main.zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.15 : 1 / 1.15); }, {passive: false});
  pane.addEventListener('dblclick', e => { if (tool === 'pan') { main.z > 1.01 ? (main.z = 1, main.px = main.py = 0, main.apply()) : main.zoomAt(e.clientX, e.clientY, 2.5); } });
  pane.addEventListener('contextmenu', e => e.preventDefault());
  pane.addEventListener('pointerdown', e => {
    pane.setPointerCapture(e.pointerId);
    const p = main.toImage(e.clientX, e.clientY), h = e.target.closest('.iv-handle'), a = e.target.closest('.iv-a');
    if (h && selected >= 0) { undo.push(JSON.stringify({anns, mm})); drag = {type: 'handle', k: +h.dataset.h}; return; }
    if (e.button === 2 || tool === 'wl') { drag = {type: 'wl', x: e.clientX, y: e.clientY, b: main.f.b, c: main.f.c}; return; }
    if (tool === 'cover') {
      const c = e.target.closest('.iv-cover');
      if (c && +c.dataset.cover >= 0) { covers[cur.id].splice(+c.dataset.cover, 1); draw(); emit('iv:cover', {count: covers[cur.id].length}); return; }
      drag = {type: 'cover', start: p}; coverDraft = null; return;
    }
    const aiHit = e.target.closest('.iv-ai');
    if (tool === 'pan' && aiHit) { ai.active = +aiHit.dataset.ai; draw(); emit('iv:ai-select', {index: ai.active}); drag = {type: 'pan', x: e.clientX - main.px, y: e.clientY - main.py}; return; }
    if (tool === 'pan') {
      if (a && +a.dataset.i >= 0) { selected = +a.dataset.i; draw(); list(); drag = {type: 'move', start: p, orig: JSON.parse(JSON.stringify(anns[selected].points)), pushed: false}; return; }
      selected = -1; draw(); list(); drag = {type: 'pan', x: e.clientX - main.px, y: e.clientY - main.py}; return;
    }
    if (!CAN_EDIT && tool !== 'lens') return;
    if (NEED[tool]) {
      // the last point always follows the pointer; a click fixes it and, if more are needed, starts the next one
      if (!pending) pending = {type: tool, points: [p, [...p]], text: '', label: ''};
      else { pending.points[pending.points.length - 1] = p; if (pending.points.length < NEED[tool]) pending.points.push([...p]); }
      drag = {type: 'draw'};
      finishIfComplete(); draw();
    }
  });
  pane.addEventListener('pointermove', e => {
    lens(e);
    if (!drag) return;
    const p = main.toImage(e.clientX, e.clientY);
    if (drag.type === 'pan') { main.px = e.clientX - drag.x; main.py = e.clientY - drag.y; main.apply(); }
    else if (drag.type === 'wl') { main.f.c = Math.round(Math.min(400, Math.max(20, drag.c + (e.clientX - drag.x) * .6))); main.f.b = Math.round(Math.min(300, Math.max(20, drag.b - (e.clientY - drag.y) * .5))); syncSliders(); main.apply(); }
    else if (drag.type === 'handle') { anns[selected].points[drag.k] = p; dirty = true; draw(); list(); status(); }
    else if (drag.type === 'move' && CAN_EDIT) {
      if (!drag.pushed) { undo.push(JSON.stringify({anns, mm})); drag.pushed = true; }
      const dx = p[0] - drag.start[0], dy = p[1] - drag.start[1];
      anns[selected].points = drag.orig.map(q => [q[0] + dx, q[1] + dy]); dirty = true; draw(); status();
    }
    else if (drag.type === 'draw' && pending) { pending.points[pending.points.length - 1] = p; draw(); }
    else if (drag.type === 'cover') { coverDraft = boxFrac(drag.start, p); draw(); }
  });
  const clamp01 = v => Math.min(1, Math.max(0, v));
  function boxFrac(a, b) {
    const x0 = clamp01(Math.min(a[0], b[0]) / main.w), y0 = clamp01(Math.min(a[1], b[1]) / main.h);
    const x1 = clamp01(Math.max(a[0], b[0]) / main.w), y1 = clamp01(Math.max(a[1], b[1]) / main.h);
    return [x0, y0, x1 - x0, y1 - y0];
  }
  pane.addEventListener('pointerup', e => {
    if (drag && drag.type === 'draw' && pending) {
      const pts = pending.points, last = pts[pts.length - 1], prev = pts[pts.length - 2];
      if (prev && dist(last, prev) * main.scale() > 6 && pts.length < NEED[pending.type]) pts.push([...last]);   // a drag sets the next point; keep one following the pointer
      finishIfComplete(); draw();
    }
    if (drag && drag.type === 'move') list();
    if (drag && drag.type === 'cover') {
      const b = coverDraft; coverDraft = null;
      if (b && b[2] * main.w * main.scale() > 6 && b[3] * main.h * main.scale() > 6) { (covers[cur.id] = covers[cur.id] || []).push(b); emit('iv:cover', {count: covers[cur.id].length}); }
      draw();
    }
    drag = null;
  });
  pane.addEventListener('pointerleave', () => { $('.iv-lens').hidden = true; });

  function finishIfComplete() {
    if (!pending) return;
    const need = NEED[pending.type];
    const pts = pending.points;
    // complete when we have all points and the last one is not just a placeholder sitting on the previous point
    if (pts.length < need || (need > 1 && dist(pts[need - 1], pts[need - 2]) * main.scale() < 4)) return;
    const a = {...pending, points: pts.slice(0, need)}; pending = null;
    if (a.type === 'calibrate') {
      const px = dist(a.points[0], a.points[1]);
      const v = prompt(`This line is ${px.toFixed(0)} pixels long. How long is it in real life, in millimetres?\n(Use something of known size: a calibration marker, a ruler on the film, or the image's stated scale.)`, mm ? (px * mm).toFixed(1) : '');
      const n = parseFloat((v || '').replace(',', '.'));
      if (n > 0) change(() => { mm = n / px; }); else draw();
      return;
    }
    if (a.type === 'text' || a.type === 'arrow') {
      const t = prompt(a.type === 'text' ? 'Note text' : 'Label for this arrow (optional)', '');
      if (a.type === 'text' && !t) { draw(); return; }
      a.text = (t || '').slice(0, 200);
    }
    change(() => { anns.push(a); selected = anns.length - 1; });
  }

  /* ================================================================ magnifier */
  function lens(e) {
    const L = $('.iv-lens');
    if (tool !== 'lens' || !main.w) { L.hidden = true; return; }
    const r = pane.getBoundingClientRect(), p = main.toImage(e.clientX, e.clientY), k = 3, size = 180;
    L.hidden = false;
    Object.assign(L.style, {left: e.clientX - r.left - size / 2 + 'px', top: e.clientY - r.top - size / 2 + 'px', width: size + 'px', height: size + 'px',
      backgroundImage: `url("${main.img.src}")`, backgroundSize: `${main.w * main.scale() * k}px ${main.h * main.scale() * k}px`,
      backgroundPosition: `${size / 2 - p[0] * main.scale() * k}px ${size / 2 - p[1] * main.scale() * k}px`,
      filter: main.img.style.filter, transform: `rotate(${main.rot}deg) scaleX(${main.flip ? -1 : 1})`});
  }

  /* ================================================================ toolbar */
  function setTool(t) {
    if (pending) { pending = null; draw(); }
    tool = t; $$('[data-tool]').forEach(b => b.classList.toggle('on', b.dataset.tool === t));
    pane.dataset.mode = t;      // for the cursor; not data-tool, which marks toolbar buttons
    $('.iv-tip').textContent = {pan: 'Drag to pan · scroll to zoom · double-click to zoom in · click a measurement to select, drag to move · right-drag for window/level',
      wl: 'Drag left/right for contrast, up/down for brightness', ruler: 'Drag from one end to the other', angle: 'Drag along the first arm to the corner, then click the end of the second arm',
      cobb: 'Drag along the first endplate, then drag along the second', ellipse: 'Drag across the region', arrow: 'Drag from the label position to the point of interest',
      text: 'Click where the note should go', calibrate: 'Drag along something of known length, then enter its size in mm', lens: 'Move over the image to magnify',
      cover: 'Drag a box over any name, record number or date on the film. It is blacked out before Dr. Flow sees the image. Click a box to remove it.'}[t] || '';
    if (t === 'lens') $('.iv-lens').hidden = false;
    emit('iv:tool', {tool: t});
  }
  const syncSliders = () => { $('[data-f=b]').value = main.f.b; $('[data-f=c]').value = main.f.c; };
  root.addEventListener('click', e => {
    const t = e.target.closest('[data-tool]'); if (t) return setTool(t.dataset.tool);
    const b = e.target.closest('[data-act]');
    const del = e.target.closest('[data-del]'), ren = e.target.closest('[data-rename]'), rep = e.target.closest('[data-report]'), row = e.target.closest('.iv-row'), th = e.target.closest('.iv-thumb');
    if (del) return change(() => { anns.splice(+del.dataset.del, 1); selected = -1; });
    if (ren) { const i = +ren.dataset.rename, v = prompt('Name this measurement, e.g. "Cardiothoracic ratio" or "Lesion 1"', anns[i].label || ''); if (v !== null) change(() => { anns[i].label = v.slice(0, 60); }); return; }
    if (rep) { const a = anns[+rep.dataset.report], m = measure(a); window.addReportMeasurement({label: a.label || m.label, value: m.value.split(' · ')[0].replace(/[^\d.,-]/g, ''), unit: m.value.split(' · ')[0].replace(/^[\d.,-]+\s*/, ''), abnormal: false}); toast('Added to the report measurements'); return; }
    if (th) { const img = DATA.images.find(i => i.id === +th.dataset.id); if (img && img !== cur) select(img); return; }
    if (row && !e.target.closest('button')) { selected = +row.dataset.i; draw(); list(); return; }
    if (!b) return;
    const act = b.dataset.act;
    if (act === 'fit') { main.reset(); }
    if (act === 'rotl' || act === 'rotr') { main.rot = (main.rot + (act === 'rotl' ? -90 : 90) + 360) % 360; main.computeFit(); main.apply(); }
    if (act === 'flip') { main.flip = !main.flip; main.apply(); }
    if (act === 'invert') { main.f.inv = !main.f.inv; b.classList.toggle('on', main.f.inv); main.apply(); }
    if (act === 'undo' && undo.length) { const s = JSON.parse(undo.pop()); anns = s.anns; mm = s.mm; selected = -1; dirty = true; draw(); list(); status(); hud(); }
    if (act === 'clear' && anns.length && confirm('Remove every measurement and note from this image?')) change(() => { anns = []; selected = -1; });
    if (act === 'save') save();
    if (act === 'full') { const box = $('.iv-panes'); document.fullscreenElement ? document.exitFullscreen() : box.requestFullscreen?.(); }
    if (act === 'export') exportPng();
    if (act === 'process') openProcess();
    if (act === 'reset-wl') { main.f.b = main.f.c = 100; main.f.lut = ''; main.f.inv = false; $('[data-lut]').value = ''; $('[data-act=invert]').classList.remove('on'); syncSliders(); main.apply(); }
  });
  $$('[data-f]').forEach(r => r.addEventListener('input', () => { main.f[r.dataset.f] = +r.value; main.apply(); }));
  $('[data-lut]').addEventListener('change', e => { main.f.lut = e.target.value; main.apply(); });
  document.addEventListener('fullscreenchange', () => setTimeout(() => { main.computeFit(); main.apply(); cmp.w && (cmp.computeFit(), cmp.apply()); }, 60));

  document.addEventListener('keydown', e => {
    if (e.target.closest('input,textarea,select,dialog')) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); $('[data-act=undo]').click(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && CAN_EDIT) { e.preventDefault(); save(); return; }
    if (e.key === 'Escape') { pending = null; selected = -1; if (tool === 'cover') setTool('pan'); draw(); list(); return; }
    if ((e.key === 'Delete' || e.key === 'Backspace') && selected >= 0 && CAN_EDIT) { e.preventDefault(); change(() => { anns.splice(selected, 1); selected = -1; }); return; }
    const keys = {v: 'pan', w: 'wl', r: 'ruler', a: 'angle', c: 'cobb', e: 'ellipse', t: 'text', l: 'lens', k: 'calibrate', o: 'arrow'};
    if (keys[e.key] && (CAN_EDIT || ['pan', 'wl', 'lens'].includes(keys[e.key]))) setTool(keys[e.key]);
    if (e.key === 'i') $('[data-act=invert]').click();
    if (e.key === '0') main.reset();
    if (e.key === 'f') $('[data-act=full]').click();
  });

  async function save() {
    if (!dirty || !CAN_EDIT) return;
    try {
      const res = await fetch(urlFor(root.dataset.annUrl, cur.id), {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': CSRF}, body: JSON.stringify({annotations: anns, mm_per_pixel: mm})});
      const d = await res.json();
      if (!d.ok) throw new Error(d.error);
      cur.annotations = JSON.parse(JSON.stringify(anns)); cur.mm = mm; dirty = false; status(); toast(`Saved ${d.count} measurement${d.count === 1 ? '' : 's'}`, 'success');
    } catch (err) { toast('Could not save: ' + (err.message || 'network error'), 'danger'); }
  }
  window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

  /* export the current view of the image with its measurements burned in */
  function exportPng() {
    const c = document.createElement('canvas'); c.width = main.w; c.height = main.h;
    const g = c.getContext('2d');
    g.filter = `brightness(${main.f.b}%) contrast(${main.f.c}%)${main.f.inv ? ' invert(1)' : ''}`;
    g.drawImage(main.img, 0, 0); g.filter = 'none';
    const s = Math.max(1, main.w / 900);
    g.lineWidth = 2 * s; g.strokeStyle = '#FFD54F'; g.fillStyle = '#FFD54F'; g.font = `bold ${14 * s}px system-ui, sans-serif`;
    anns.forEach(a => {
      const P = a.points, m = measure(a);
      g.beginPath();
      if (a.type === 'ellipse') g.ellipse((P[0][0] + P[1][0]) / 2, (P[0][1] + P[1][1]) / 2, Math.abs(P[1][0] - P[0][0]) / 2, Math.abs(P[1][1] - P[0][1]) / 2, 0, 0, Math.PI * 2);
      else if (a.type === 'cobb') { g.moveTo(...P[0]); g.lineTo(...P[1]); g.moveTo(...P[2]); g.lineTo(...P[3]); }
      else if (a.type !== 'text') { g.moveTo(...P[0]); P.slice(1).forEach(p => g.lineTo(...p)); }
      g.stroke();
      const txt = m ? `${a.label ? a.label + ': ' : ''}${m.value}` : a.text;
      if (txt) { const at = P[a.type === 'angle' ? 1 : P.length - 1]; g.lineWidth = 4 * s; g.strokeStyle = 'rgba(0,0,0,.75)'; g.strokeText(txt, at[0] + 8 * s, at[1] - 8 * s); g.fillText(txt, at[0] + 8 * s, at[1] - 8 * s); g.lineWidth = 2 * s; g.strokeStyle = '#FFD54F'; }
    });
    if (ai.show && ai.labels.length) {   // Dr. Flow's labels, marked as AI so nobody mistakes them for measurements
      const col = {urgent: '#FF4D5E', abnormal: '#FF9F43', watch: '#7FDBFF', normal: '#7CE38B'};
      g.setLineDash([8 * s, 5 * s]);
      ai.labels.forEach(lb => {
        g.strokeStyle = g.fillStyle = col[lb.concern] || col.watch; g.lineWidth = 2 * s;
        let x, y;
        if (lb.box) { x = lb.box[0] * main.w; y = lb.box[1] * main.h; g.strokeRect(x, y, lb.box[2] * main.w, lb.box[3] * main.h); }
        else if (lb.point) { x = lb.point[0] * main.w; y = lb.point[1] * main.h; g.beginPath(); g.arc(x, y, 14 * s, 0, Math.PI * 2); g.stroke(); }
        else return;
        const txt = `AI ${lb.n}: ${lb.name}`; g.lineWidth = 4 * s; g.strokeStyle = 'rgba(0,0,0,.75)'; g.setLineDash([]);
        g.strokeText(txt, x + 4 * s, y - 6 * s); g.fillText(txt, x + 4 * s, y - 6 * s); g.setLineDash([8 * s, 5 * s]);
      });
      g.setLineDash([]);
    }
    const a = document.createElement('a'); a.download = `${root.dataset.number}-${cur.id}-annotated.png`; a.href = c.toDataURL('image/png'); a.click();
  }

  /* ================================================================ compare */
  const cmpSel = $('[data-compare]');
  cmpSel.addEventListener('change', () => {
    const id = +cmpSel.value, img = [...DATA.images, ...DATA.priors].find(i => i.id === id);
    $('.iv-panes').classList.toggle('split', !!img);
    $('.iv-pane.compare').hidden = !img;
    if (img) cmp.load(img.url);
    setTimeout(() => { main.computeFit(); main.apply(); }, 30);
  });
  function syncCompare() {
    if (!$('[data-sync]').checked || $('.iv-pane.compare').hidden || !cmp.w) return;
    cmp.z = main.z; cmp.px = main.px; cmp.py = main.py; cmp.f = {...main.f}; cmp.rot = main.rot; cmp.flip = main.flip; cmp.apply();
  }
  const cp = cmp.el; let cdrag = null;
  cp.addEventListener('wheel', e => { e.preventDefault(); cmp.zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.15 : 1 / 1.15); }, {passive: false});
  cp.addEventListener('pointerdown', e => { cp.setPointerCapture(e.pointerId); cdrag = [e.clientX - cmp.px, e.clientY - cmp.py]; });
  cp.addEventListener('pointermove', e => { if (cdrag) { cmp.px = e.clientX - cdrag[0]; cmp.py = e.clientY - cdrag[1]; cmp.apply(); } });
  cp.addEventListener('pointerup', () => { cdrag = null; });

  /* ================================================================ processing dialog */
  const dlg = document.getElementById('iv-process');
  let corners, prot = 0, pflip = false, previewUrl = null;
  function openProcess() {
    if (!dlg || !CAN_EDIT) return;
    corners = [[.04, .04], [.96, .04], [.96, .96], [.04, .96]]; prot = 0; pflip = false;
    const src = $('.ivp-src img', dlg); src.src = cur.url;
    $('.ivp-out', dlg).innerHTML = '<p class="muted small">Press <b>Preview</b> to see the result.</p>';
    src.onload = drawCorners; if (src.complete) drawCorners();
    dlg.showModal();
  }
  function drawCorners() {
    const svg = $('.ivp-src svg', dlg);
    svg.innerHTML = `<polygon points="${corners.map(c => c.map(v => v * 1000).join(',')).join(' ')}" class="ivp-poly"/>` +
      corners.map((c, i) => `<circle cx="${c[0] * 1000}" cy="${c[1] * 1000}" r="22" class="ivp-h" data-k="${i}"/><text x="${c[0] * 1000}" y="${c[1] * 1000 + 8}" class="ivp-ht">${['1', '2', '3', '4'][i]}</text>`).join('');
  }
  if (dlg) {
    const svg = $('.ivp-src svg', dlg); let ck = null;
    svg.addEventListener('pointerdown', e => { const h = e.target.closest('.ivp-h'); if (h) { ck = +h.dataset.k; svg.setPointerCapture(e.pointerId); } });
    svg.addEventListener('pointermove', e => { if (ck === null) return; const r = svg.getBoundingClientRect(); corners[ck] = [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; drawCorners(); });
    svg.addEventListener('pointerup', () => { ck = null; });
    dlg.addEventListener('click', async e => {
      const b = e.target.closest('[data-p]'); if (!b) return;
      const p = b.dataset.p;
      if (p === 'whole') { corners = [[0, 0], [1, 0], [1, 1], [0, 1]]; drawCorners(); return; }
      if (p === 'auto') { autoDetect(); return; }
      if (p === 'rotl' || p === 'rotr') { prot = (prot + (p === 'rotl' ? 270 : 90)) % 360; $('.ivp-rot', dlg).textContent = prot ? `Rotate ${prot}°` : ''; return; }
      if (p === 'flip') { pflip = !pflip; b.classList.toggle('on', pflip); return; }
      if (p === 'close') { dlg.close(); return; }
      if (p === 'preview' || p === 'save') {
        const opts = {corners, rotate: prot, flip: pflip, grayscale: $('[name=ivp-gray]', dlg).checked, denoise: $('[name=ivp-denoise]', dlg).checked, level: $('[name=ivp-level]', dlg).checked,
          enhance: +$('[name=ivp-enhance]', dlg).value, sharpen: +$('[name=ivp-sharpen]', dlg).value, gamma: +$('[name=ivp-gamma]', dlg).value, invert: $('[name=ivp-invert]', dlg).checked, save: p === 'save'};
        b.disabled = true; const label = b.innerHTML; b.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Working…';
        try {
          const res = await fetch(urlFor(root.dataset.processUrl, cur.id), {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': CSRF}, body: JSON.stringify(opts)});
          if (p === 'preview') {
            if (!res.ok) throw new Error((await res.json()).error);
            if (previewUrl) URL.revokeObjectURL(previewUrl);
            previewUrl = URL.createObjectURL(await res.blob());
            $('.ivp-out', dlg).innerHTML = `<img src="${previewUrl}" alt="Processed preview">`;
          } else {
            const d = await res.json(); if (!d.ok) throw new Error(d.error);
            dirty = false; location.href = d.redirect;
          }
        } catch (err) { toast(err.message || 'Processing failed', 'danger'); }
        finally { b.disabled = false; b.innerHTML = label; }
      }
    });
    $$('input[type=range]', dlg).forEach(r => r.addEventListener('input', () => { const o = dlg.querySelector(`[data-out="${r.name}"]`); if (o) o.textContent = r.value; }));
  }
  /* find the film on the light box: split dark from bright with Otsu's threshold, take the side that does not
     touch the photo's edges as the film, keep its largest connected region, and use its extreme diagonal points */
  function autoDetect() {
    const img = $('.ivp-src img', dlg), c = document.createElement('canvas'), W = 260, H = Math.max(1, Math.round(260 * img.naturalHeight / img.naturalWidth));
    c.width = W; c.height = H; const g = c.getContext('2d'); g.drawImage(img, 0, 0, W, H);
    const d = g.getImageData(0, 0, W, H).data, L = new Uint8Array(W * H), hist = new Array(256).fill(0);
    for (let i = 0; i < W * H; i++) { L[i] = Math.round(.299 * d[i * 4] + .587 * d[i * 4 + 1] + .114 * d[i * 4 + 2]); hist[L[i]]++; }
    let sum = 0; for (let t = 0; t < 256; t++) sum += t * hist[t];
    let sB = 0, wB = 0, best = 0, thr = 128;
    for (let t = 0; t < 256; t++) { wB += hist[t]; if (!wB) continue; const wF = W * H - wB; if (!wF) break; sB += t * hist[t];
      const between = wB * wF * ((sB / wB) - (sum - sB) / wF) ** 2; if (between > best) { best = between; thr = t; } }
    let edgeDark = 0, edgeN = 0;
    for (let x = 0; x < W; x++) { edgeDark += (L[x] <= thr) + (L[(H - 1) * W + x] <= thr); edgeN += 2; }
    for (let y = 0; y < H; y++) { edgeDark += (L[y * W] <= thr) + (L[y * W + W - 1] <= thr); edgeN += 2; }
    const filmDark = edgeDark / edgeN < .5;                       // light box around the film: the film is the dark side
    const isFilm = i => filmDark ? L[i] <= thr : L[i] > thr;
    const seen = new Uint8Array(W * H); let bestComp = null;
    for (let i = 0; i < W * H; i++) {
      if (seen[i] || !isFilm(i)) continue;
      const comp = [], stack = [i]; seen[i] = 1;
      while (stack.length) { const j = stack.pop(); comp.push(j); const x = j % W, y = (j / W) | 0;
        for (const k of [x > 0 ? j - 1 : -1, x < W - 1 ? j + 1 : -1, y > 0 ? j - W : -1, y < H - 1 ? j + W : -1])
          if (k >= 0 && !seen[k] && isFilm(k)) { seen[k] = 1; stack.push(k); } }
      if (!bestComp || comp.length > bestComp.length) bestComp = comp;
    }
    if (!bestComp || bestComp.length < W * H * .05) { toast('Could not find the film edges. Drag the four corners yourself.', 'warning'); return; }
    const ext = [[Infinity, null], [-Infinity, null], [-Infinity, null], [Infinity, null]];
    for (const j of bestComp) { const x = j % W, y = (j / W) | 0, s1 = x + y, s2 = x - y;
      if (s1 < ext[0][0]) ext[0] = [s1, [x, y]]; if (s2 > ext[1][0]) ext[1] = [s2, [x, y]];
      if (s1 > ext[2][0]) ext[2] = [s1, [x, y]]; if (s2 < ext[3][0]) ext[3] = [s2, [x, y]]; }
    corners = ext.map(([, [x, y]]) => [(x + .5) / W, (y + .5) / H]); drawCorners();
    toast('Film edges found. Adjust any corner if needed.', 'success');
  }

  /* ================================================================ API for Dr. Flow (imaging-ai.js) */
  function centreOn(ix, iy, z) {
    main.z = Math.min(20, Math.max(1, z));
    const s = main.scale(), vx = (ix - main.w / 2) * (main.flip ? -s : s), vy = (iy - main.h / 2) * s, a = main.rot * Math.PI / 180;
    main.px = -(vx * Math.cos(a) - vy * Math.sin(a)); main.py = -(vx * Math.sin(a) + vy * Math.cos(a)); main.apply();
  }
  window.ImagingViewer = {
    root,
    get current() { return cur ? {id: cur.id, caption: cur.caption, processed: cur.processed} : null; },
    get canEdit() { return CAN_EDIT; },
    images: () => DATA.images.map(i => ({id: i.id, caption: i.caption})),
    selectImage(id) { const img = DATA.images.find(i => i.id === +id); return img ? (img === cur || select(img)) : false; },
    setLabels(labels, active = -1) { ai.labels = Array.isArray(labels) ? labels : []; ai.active = active; draw(); },
    showLabels(on) { ai.show = !!on; draw(); },
    get labelsShown() { return ai.show; },
    focusLabel(i, zoom = true) {
      const lb = ai.labels[i]; if (!lb) return;
      ai.active = i; ai.show = true;
      if (zoom && main.w) {
        const r = main.el.getBoundingClientRect();
        if (lb.box) { const [x, y, w, h] = lb.box; centreOn((x + w / 2) * main.w, (y + h / 2) * main.h, Math.min(r.width / (w * main.w * main.fit), r.height / (h * main.h * main.fit)) * .45); }
        else if (lb.point) centreOn(lb.point[0] * main.w, lb.point[1] * main.h, Math.max(main.z, 2.5));
      }
      draw();
    },
    /* turn an AI label into an ordinary annotation (region or arrow + note) the clinician owns and saves */
    keepLabel(i) {
      const lb = ai.labels[i]; if (!lb || !CAN_EDIT || !main.w) return false;
      const name = String(lb.name || 'AI finding').slice(0, 60);
      if (lb.box) {
        const [x, y, w, h] = lb.box;
        change(() => { anns.push({type: 'ellipse', points: [[x * main.w, y * main.h], [(x + w) * main.w, (y + h) * main.h]], text: '', label: name}); selected = anns.length - 1; });
      } else if (lb.point) {
        const px = lb.point[0] * main.w, py = lb.point[1] * main.h, off = Math.min(main.w, main.h) * .08;
        const sx = Math.max(0, px - off), sy = Math.max(0, py - off);
        change(() => { anns.push({type: 'arrow', points: [[sx, sy], [px, py]], text: name, label: ''}); selected = anns.length - 1; });
      } else return false;
      return true;
    },
    coverMode(on) { setTool(on ? 'cover' : 'pan'); },
    get covering() { return tool === 'cover'; },
    covers(id) { return (covers[id ?? cur?.id] || []).map(b => b.map(v => +v.toFixed(4))); },
    clearCovers() { if (cur) { covers[cur.id] = []; draw(); emit('iv:cover', {count: 0}); } },
  };

  /* ================================================================ go */
  setTool('pan'); syncSliders();
  const start = () => { if (cur) select(cur); };      // after the report editor below has registered its hook
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', start) : setTimeout(start, 0);
})();
