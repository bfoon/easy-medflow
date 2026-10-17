/* 3D Body: a rotatable, realistic full-body anatomy for Lab insights, built in code with three.js (vendored, no downloads).
   Like an anatomy atlas: a muscular figure with its skull, a glass body showing the skeleton, organs, blood vessels and
   nerves, and a deep figure with the organs inside the muscles; or one figure with Skin / Muscles / Glass / Organs /
   Skeleton presets and a switch per layer.
   Every number on the model is the value entered in E-MedFlow — the latest lab result or vital sign, exactly as typed
   (MFBody3D.values, tested in Node) — pinned to the organ it belongs to. The animation runs on the same values: the
   heart beats at the recorded heart rate, the lungs breathe at the respiratory rate, the pulse wave and blood cells run
   at that rate, the number of red cells follows the haemoglobin, white cells and platelets follow their counts, malaria
   parasites appear in the blood, and the colours and shapes come from the anatomy findings (MFAnatomy.findings):
   pale, yellow or blue skin, a fever glow, swollen ankles, a damaged heart wall, congested lungs, an inflamed liver,
   failing kidneys, an enlarged spleen, fractures from imaging…
   MFBody3D.mount(el, data) draws it. Teaching and explanation aid: it does not replace the results or the examination. */
(() => {
  'use strict';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  /* ================================================================== 1 · the values on the model (pure) */
  // where each body system's results are pinned (BODY_SYSTEMS in models.py)
  const ANCHOR_OF = {brain: 'brain', thyroid: 'thyroid', lungs: 'lungs', heart: 'heart', blood: 'blood', liver: 'liver', stomach: 'stomach',
    pancreas: 'pancreas', kidneys: 'kidneys', bladder: 'bladder', reproductive: 'reproductive', bone: 'bone', immune: 'spleen'};
  const ANCHOR_LABEL = {skin: 'Skin', brain: 'Brain', thyroid: 'Thyroid', lungs: 'Lungs', heart: 'Heart', arm: 'Arm artery', blood: 'Blood',
    liver: 'Liver', stomach: 'Stomach & gut', pancreas: 'Pancreas', spleen: 'Spleen & immunity', kidneys: 'Kidneys', bladder: 'Bladder & urine',
    reproductive: 'Reproductive organs', bone: 'Bones & joints', body: 'Body'};
  const ORDER = Object.keys(ANCHOR_LABEL);
  // vital signs as recorded on the visit or at the bedside (VITAL_FIELDS in forms.py)
  const VITALS = [['bp', 'Blood pressure', 'mmHg', 'arm'], ['heart_rate', 'Heart rate', 'bpm', 'heart'], ['spo2', 'SpO₂', '%', 'lungs'],
    ['resp_rate', 'Respiratory rate', '/min', 'lungs'], ['temperature_c', 'Temperature', '°C', 'skin'], ['weight_kg', 'Weight', 'kg', 'body']];
  const LEVEL = {HH: 3, LL: 3, H: 2, L: 2, A: 2};
  const num = v => { const x = parseFloat(String(v ?? '').replace(',', '.')); return Number.isFinite(x) ? x : null; };
  // vitals carry no laboratory flag: mark them with the same limits the anatomy findings use
  function vitalFlag(key, raw) {
    if (key === 'bp') {
      const [s, d] = String(raw).split('/').map(num);
      if (s === null) return '';
      return s >= 180 || (d !== null && d >= 120) ? 'HH' : s < 80 ? 'LL' : s >= 140 || (d !== null && d >= 90) ? 'H' : s < 90 ? 'L' : '';
    }
    const v = num(raw);
    if (v === null) return '';
    const lim = {heart_rate: [40, 50, 100, 130], spo2: [88, 94, null, null], resp_rate: [8, 10, 20, 30], temperature_c: [34, 35.5, 37.5, 39.5]}[key];
    if (!lim) return '';
    const [ll, l, h, hh] = lim;
    return ll !== null && v < ll ? 'LL' : l !== null && v < l ? 'L' : hh !== null && v >= hh ? 'HH' : h !== null && v >= h ? 'H' : '';
  }
  function values(D) {
    D = D || {};
    const groups = {};
    const group = a => groups[a] ||= {anchor: a, label: ANCHOR_LABEL[a] || a, items: [], level: 0};
    const V = D.vitals || {}, meta = D.vitals_meta || null;
    for (const [key, name, unit, anchor] of VITALS) {
      const raw = V[key];
      if (raw === undefined || raw === null || String(raw).trim() === '') continue;
      const flag = vitalFlag(key, raw);
      group(anchor).items.push({source: 'vital', code: key, name, display: String(raw).trim(), unit, flag, level: LEVEL[flag] || 0,
        date: meta && meta.source === 'bedside' ? `bedside, ${meta.hours_ago} h ago` : 'last visit'});
    }
    for (const p of D.params || []) {
      const latest = p.latest || (p.history || [])[(p.history || []).length - 1];
      if (!latest) continue;
      const anchor = ANCHOR_OF[p.system] || 'blood';
      group(anchor).items.push({source: 'lab', code: p.code, id: p.id, name: p.name, display: String(latest.display ?? ''), unit: p.unit || '',
        flag: latest.flag || '', level: LEVEL[latest.flag] || 0, range: p.range || '', date: latest.date || '', test: p.test || ''});
    }
    const out = Object.values(groups);
    out.forEach(g => {
      g.items.sort((a, b) => (a.source === 'vital' ? -1 : 0) - (b.source === 'vital' ? -1 : 0) || b.level - a.level);
      g.level = Math.max(0, ...g.items.map(i => i.level));
    });
    out.sort((a, b) => ORDER.indexOf(a.anchor) - ORDER.indexOf(b.anchor));
    return out;
  }
  const fmt = it => `${it.display}${it.unit ? ' ' + it.unit : ''}`;
  const arrow = f => ({HH: '▲▲', H: '▲', LL: '▼▼', L: '▼', A: '!'}[f] || '');

  const API = {values, vitalFlag, ANCHOR_OF};
  if (typeof window !== 'undefined') window.MFBody3D = API;
  if (typeof module !== 'undefined') module.exports = API;
  if (typeof document === 'undefined') return;

  /* ================================================================== 2 · signed distance shapes and a mesher */
  const smin = (a, b, k) => { const h = clamp(.5 + .5 * (b - a) / k, 0, 1); return b + (a - b) * h - k * h * (1 - h); };
  const smax = (a, b, k) => -smin(-a, -b, k);
  function rotM(rx = 0, ry = 0, rz = 0) {      // inverse rotation (world → local), row-major 3×3
    const cx = Math.cos(rx), sx = Math.sin(rx), cy = Math.cos(ry), sy = Math.sin(ry), cz = Math.cos(rz), sz = Math.sin(rz);
    // R = Rz·Ry·Rx ; inverse = transpose
    const R = [cy * cz, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx, cy * sz, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx, -sy, cy * sx, cy * cx];
    return [R[0], R[3], R[6], R[1], R[4], R[7], R[2], R[5], R[8]];
  }
  // shape constructors: o = {k: blend, sub: subtract, rot: [rx, ry, rz], name, fib: fibre axis}
  const El = (c, r, o = {}) => ({t: 'E', c, r, m: o.rot ? rotM(...o.rot) : null, br: Math.max(...r), ...o});
  const Sp = (c, r, o = {}) => ({t: 'S', c, r, br: r, ...o});
  function Cn(a, b, r1, r2 = r1, o = {}) {
    const ba = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], l2 = ba[0] ** 2 + ba[1] ** 2 + ba[2] ** 2, rr = r1 - r2;
    return {t: 'C', a, b, r1, r2, ba, l2, rr, a2: l2 - rr * rr, il2: 1 / l2, c: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2],
      br: Math.sqrt(l2) / 2 + Math.max(r1, r2), ...o};
  }
  const Cy = (c, r, hh, o = {}) => ({t: 'Y', c, r, hh, m: o.rot ? rotM(...o.rot) : null, br: Math.hypot(r, hh), ...o});   // capped cylinder along local y
  const Bx = (c, b, o = {}) => ({t: 'B', c, b, m: o.rot ? rotM(...o.rot) : null, br: Math.hypot(...b), ...o});            // rounded box
  function dPrim(p, x, y, z) {
    let px = x - p.c[0], py = y - p.c[1], pz = z - p.c[2];
    if (p.t === 'S') return Math.sqrt(px * px + py * py + pz * pz) - p.r;
    if (p.t === 'C') {
      const ax = x - p.a[0], ay = y - p.a[1], az = z - p.a[2];
      const yy = ax * p.ba[0] + ay * p.ba[1] + az * p.ba[2], zz = yy - p.l2;
      const xx = ax * p.l2 - p.ba[0] * yy, xy = ay * p.l2 - p.ba[1] * yy, xz = az * p.l2 - p.ba[2] * yy;
      const x2 = xx * xx + xy * xy + xz * xz, y2 = yy * yy * p.l2, z2 = zz * zz * p.l2;
      const k = Math.sign(p.rr) * p.rr * p.rr * x2;
      if (Math.sign(zz) * p.a2 * z2 > k) return Math.sqrt(x2 + z2) * p.il2 - p.r2;
      if (Math.sign(yy) * p.a2 * y2 < k) return Math.sqrt(x2 + y2) * p.il2 - p.r1;
      return (Math.sqrt(x2 * p.a2 * p.il2) + yy * p.rr) * p.il2 - p.r1;
    }
    if (p.m) { const m = p.m; const qx = m[0] * px + m[1] * py + m[2] * pz, qy = m[3] * px + m[4] * py + m[5] * pz, qz = m[6] * px + m[7] * py + m[8] * pz; px = qx; py = qy; pz = qz; }
    if (p.t === 'E') {
      const a = px / p.r[0], b = py / p.r[1], c = pz / p.r[2], k0 = Math.sqrt(a * a + b * b + c * c);
      const a1 = a / p.r[0], b1 = b / p.r[1], c1 = c / p.r[2], k1 = Math.sqrt(a1 * a1 + b1 * b1 + c1 * c1) || 1e-9;
      return k0 * (k0 - 1) / k1;
    }
    if (p.t === 'Y') { const dx = Math.hypot(px, pz) - p.r, dy = Math.abs(py) - p.hh; return Math.min(Math.max(dx, dy), 0) + Math.hypot(Math.max(dx, 0), Math.max(dy, 0)); }
    if (p.t === 'B') {
      const rr = p.round || 0, qx = Math.abs(px) - p.b[0] + rr, qy = Math.abs(py) - p.b[1] + rr, qz = Math.abs(pz) - p.b[2] + rr;
      return Math.hypot(Math.max(qx, 0), Math.max(qy, 0), Math.max(qz, 0)) + Math.min(Math.max(qx, qy, qz), 0) - rr;
    }
    return 1e9;
  }
  // a smooth union of shapes, minus the subtractive ones; optional displacement for wrinkles (brain folds, bumps)
  function field(prims, k0 = .01, disp = null) {
    const add = prims.filter(p => !p.sub), sub = prims.filter(p => p.sub);
    return (x, y, z) => {
      let d = 1e9;
      for (let i = 0; i < add.length; i++) {
        const p = add[i], k = p.k ?? k0;
        const dx = x - p.c[0], dy = y - p.c[1], dz = z - p.c[2];
        if (Math.sqrt(dx * dx + dy * dy + dz * dz) - p.br > d + k) continue;      // too far to change the blend
        d = smin(d, dPrim(p, x, y, z), k);
      }
      for (let i = 0; i < sub.length; i++) {
        const p = sub[i], k = p.k ?? k0;
        const dx = x - p.c[0], dy = y - p.c[1], dz = z - p.c[2];
        if (Math.sqrt(dx * dx + dy * dy + dz * dz) - p.br > k - d) continue;
        d = smax(d, -dPrim(p, x, y, z), k);
      }
      return disp ? d + disp(x, y, z, d) : d;
    };
  }
  // value noise for wrinkles and mottling (deterministic)
  const hash = (x, y, z) => { const s = Math.sin(x * 127.1 + y * 311.7 + z * 74.7) * 43758.5453; return s - Math.floor(s); };
  function noise(x, y, z) {
    const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z), xf = x - xi, yf = y - yi, zf = z - zi;
    const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf), w = zf * zf * (3 - 2 * zf), L = (a, b, t) => a + (b - a) * t, c = (a, b, d) => hash(xi + a, yi + b, zi + d);
    return L(L(L(c(0, 0, 0), c(1, 0, 0), u), L(c(0, 1, 0), c(1, 1, 0), u), v), L(L(c(0, 0, 1), c(1, 0, 1), u), L(c(0, 1, 1), c(1, 1, 1), u), v), w) * 2 - 1;
  }
  const fbm = (x, y, z, o = 3) => { let a = 0, f = 1, s = .5; for (let i = 0; i < o; i++) { a += s * noise(x * f, y * f, z * f); f *= 2.03; s *= .5; } return a; };

  /* surface nets: a smooth triangle mesh of a shape's zero surface. The volume is cut into blocks; each block only
     looks at the shapes that can reach it, and blocks far from the surface are skipped. */
  function surface(T, shape, lo, hi, h) {
    const prims = shape.prims, k0 = shape.k ?? .01, disp = null, margin = 0, vdisp = shape.disp || null;
    const kmax = Math.max(k0, ...prims.map(p => p.k ?? k0));
    const fAll = field(prims, k0, disp);
    const nx = Math.ceil((hi[0] - lo[0]) / h) + 3, ny = Math.ceil((hi[1] - lo[1]) / h) + 3, nz = Math.ceil((hi[2] - lo[2]) / h) + 3;
    const ox = lo[0] - h, oy = lo[1] - h, oz = lo[2] - h, NXY = nx * ny;
    const F = new Float32Array(nx * ny * nz).fill(1);
    const B = 6, nbx = Math.ceil(nx / B), nby = Math.ceil(ny / B), evals = new Array(nbx * nby * Math.ceil(nz / B)).fill(null), active = [];
    for (let bk = 0; bk < nz; bk += B) for (let bj = 0; bj < ny; bj += B) for (let bi = 0; bi < nx; bi += B) {
      const i1 = Math.min(nx - 1, bi + B), j1 = Math.min(ny - 1, bj + B), k1 = Math.min(nz - 1, bk + B);
      const rad = Math.hypot(i1 - bi, j1 - bj, k1 - bk) * h / 2;
      const cx = ox + (bi + i1) / 2 * h, cy = oy + (bj + j1) / 2 * h, cz = oz + (bk + k1) / 2 * h;
      const reach = rad + kmax + 3 * h + margin;
      const sel = prims.filter(p => Math.hypot(cx - p.c[0], cy - p.c[1], cz - p.c[2]) - p.br < reach);
      if (!sel.some(p => !p.sub)) continue;                                  // nothing reaches this block: outside
      const f = sel.length === prims.length ? fAll : field(sel, k0, disp);
      evals[bi / B + nbx * (bj / B + nby * (bk / B))] = f;
      const dc = f(cx, cy, cz);
      if (dc > rad * 1.25 + 2 * h) continue;
      const inside = dc < -(rad * 1.25 + 2 * h);
      for (let k = bk; k <= k1; k++) for (let j = bj; j <= j1; j++) for (let i = bi; i <= i1; i++)
        F[i + nx * j + NXY * k] = inside ? -1 : f(ox + i * h, oy + j * h, oz + k * h);
      if (!inside) active.push([bi, bj, bk, Math.min(nx - 1, bi + B), Math.min(ny - 1, bj + B), Math.min(nz - 1, bk + B)]);
    }
    const evalAt = (i, j, k) => evals[Math.floor(Math.min(i, nx - 2) / B) + nbx * (Math.floor(Math.min(j, ny - 2) / B) + nby * Math.floor(Math.min(k, nz - 2) / B))] || fAll;
    const cellOf = [];
    const vid = new Int32Array(nx * ny * nz).fill(-1), pos = [];
    const C = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]];
    const EDGES = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];
    const val = new Float32Array(8);
    for (const [bi, bj, bk, i1, j1, k1] of active) for (let k = bk; k < k1; k++) for (let j = bj; j < j1; j++) for (let i = bi; i < i1; i++) {
      let mask = 0;
      for (let c = 0; c < 8; c++) { const v = F[(i + C[c][0]) + nx * (j + C[c][1]) + NXY * (k + C[c][2])]; val[c] = v; if (v < 0) mask |= 1 << c; }
      if (mask === 0 || mask === 255) continue;
      let sx = 0, sy = 0, sz = 0, n = 0;
      for (const [a, b] of EDGES) {
        if ((val[a] < 0) === (val[b] < 0)) continue;
        const t = val[a] / (val[a] - val[b]);
        sx += C[a][0] + (C[b][0] - C[a][0]) * t; sy += C[a][1] + (C[b][1] - C[a][1]) * t; sz += C[a][2] + (C[b][2] - C[a][2]) * t; n++;
      }
      vid[i + nx * j + NXY * k] = pos.length / 3;
      cellOf.push(evalAt(i, j, k));
      pos.push(ox + (i + sx / n) * h, oy + (j + sy / n) * h, oz + (k + sz / n) * h);
    }
    const idx = [];
    const V = (i, j, k) => vid[i + nx * j + NXY * k];
    const quad = (a, b, c, d, flip) => { if (a < 0 || b < 0 || c < 0 || d < 0) return; if (flip) idx.push(a, c, b, a, d, c); else idx.push(a, b, c, a, c, d); };
    for (const [bi, bj, bk, i1, j1, k1] of active) for (let k = Math.max(1, bk); k < k1; k++) for (let j = Math.max(1, bj); j < j1; j++) for (let i = Math.max(1, bi); i < i1; i++) {
      const a = F[i + nx * j + NXY * k] < 0;
      if (a !== (F[i + 1 + nx * j + NXY * k] < 0)) quad(V(i, j - 1, k - 1), V(i, j, k - 1), V(i, j, k), V(i, j - 1, k), a);
      if (a !== (F[i + nx * (j + 1) + NXY * k] < 0)) quad(V(i - 1, j, k - 1), V(i - 1, j, k), V(i, j, k), V(i, j, k - 1), a);
      if (a !== (F[i + nx * j + NXY * (k + 1)] < 0)) quad(V(i - 1, j - 1, k), V(i, j - 1, k), V(i, j, k), V(i - 1, j, k), a);
    }
    // smooth normals from the field itself
    const nrm = new Float32Array(pos.length), e = h * .5;
    for (let v = 0; v < pos.length; v += 3) {
      const x = pos[v], y = pos[v + 1], z = pos[v + 2], f = cellOf[v / 3];
      let gx = f(x + e, y, z) - f(x - e, y, z), gy = f(x, y + e, z) - f(x, y - e, z), gz = f(x, y, z + e) - f(x, y, z - e);
      const l = Math.hypot(gx, gy, gz) || 1; nrm[v] = gx / l; nrm[v + 1] = gy / l; nrm[v + 2] = gz / l;
    }
    // wind every triangle to face outwards
    for (let t = 0; t < idx.length; t += 3) {
      const a = idx[t] * 3, b = idx[t + 1] * 3, c = idx[t + 2] * 3;
      const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2], vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
      const fx = uy * vz - uz * vy, fy = uz * vx - ux * vz, fz = ux * vy - uy * vx;
      if (fx * (nrm[a] + nrm[b] + nrm[c]) + fy * (nrm[a + 1] + nrm[b + 1] + nrm[c + 1]) + fz * (nrm[a + 2] + nrm[b + 2] + nrm[c + 2]) < 0) { const s = idx[t + 1]; idx[t + 1] = idx[t + 2]; idx[t + 2] = s; }
    }
    const g = new T.BufferGeometry();
    if (vdisp) for (let v = 0; v < pos.length; v += 3) { const d = vdisp(pos[v], pos[v + 1], pos[v + 2]); pos[v] -= nrm[v] * d; pos[v + 1] -= nrm[v + 1] * d; pos[v + 2] -= nrm[v + 2] * d; }
    g.setAttribute('position', new T.Float32BufferAttribute(pos, 3));
    g.setAttribute('normal', new T.BufferAttribute(nrm, 3));
    g.setIndex(pos.length / 3 > 65535 ? new T.Uint32BufferAttribute(idx, 1) : new T.Uint16BufferAttribute(idx, 1));
    if (vdisp) g.computeVertexNormals();
    g.computeBoundingSphere();
    return g;
  }
  // the other side of the body: mirror x and keep the triangles facing out
  function mirrorX(T, g) {
    const m = g.clone();
    const p = m.attributes.position.array, n = m.attributes.normal.array;
    for (let i = 0; i < p.length; i += 3) { p[i] = -p[i]; n[i] = -n[i]; }
    const ix = m.index.array;
    for (let t = 0; t < ix.length; t += 3) { const s = ix[t + 1]; ix[t + 1] = ix[t + 2]; ix[t + 2] = s; }
    m.computeBoundingSphere();
    return m;
  }
  function merge(T, list) {
    let nv = 0, ni = 0;
    list.forEach(g => { nv += g.attributes.position.count; ni += g.index ? g.index.count : g.attributes.position.count; });
    const names = Object.keys(list[0].attributes).filter(k => list.every(g => g.attributes[k]));
    const arrs = {}; names.forEach(k => { arrs[k] = new Float32Array(nv * list[0].attributes[k].itemSize); });
    const idx = new Uint32Array(ni);
    let ov = 0, oi = 0;
    list.forEach(g => {
      names.forEach(k => arrs[k].set(g.attributes[k].array, ov * g.attributes[k].itemSize));
      const cnt = g.attributes.position.count;
      if (g.index) { const a = g.index.array; for (let i = 0; i < a.length; i++) idx[oi + i] = a[i] + ov; oi += a.length; }
      else { for (let i = 0; i < cnt; i++) idx[oi + i] = ov + i; oi += cnt; }
      ov += cnt;
    });
    const m = new T.BufferGeometry();
    names.forEach(k => m.setAttribute(k, new T.BufferAttribute(arrs[k], list[0].attributes[k].itemSize)));
    m.setIndex(new T.BufferAttribute(idx, 1));
    m.computeBoundingSphere();
    return m;
  }
  // a tube with a changing radius along a smooth path; aU = distance along it (m) for the flowing pulse
  function tube(T, pts, r0, r1 = r0, opt = {}) {
    const curve = new T.CatmullRomCurve3(pts.map(p => new T.Vector3(...p)), false, 'catmullrom', .5);
    const len = curve.getLength(), seg = opt.seg || Math.max(8, Math.ceil(len / .012)), rad = opt.radial || 8;
    const fr = curve.computeFrenetFrames(seg, false);
    const pos = [], nrm = [], u = [], idx = [];
    for (let i = 0; i <= seg; i++) {
      const t = i / seg, c = curve.getPointAt(t), N = fr.normals[i], Bn = fr.binormals[i];
      let r = r0 + (r1 - r0) * t;
      if (opt.wave) r *= 1 + opt.wave(t, len);
      if (opt.cap && (i === 0 || i === seg)) r *= .55;
      for (let j = 0; j <= rad; j++) {
        const a = j / rad * Math.PI * 2, cs = Math.cos(a), sn = Math.sin(a);
        const nx = cs * N.x + sn * Bn.x, ny = cs * N.y + sn * Bn.y, nz = cs * N.z + sn * Bn.z;
        const sq = opt.flat || 1;
        pos.push(c.x + r * (cs * N.x + sn * Bn.x * sq), c.y + r * (cs * N.y + sn * Bn.y * sq), c.z + r * (cs * N.z + sn * Bn.z * sq));
        nrm.push(nx, ny, nz); u.push((opt.u0 || 0) + t * len);
      }
    }
    for (let i = 0; i < seg; i++) for (let j = 0; j < rad; j++) {
      const a = i * (rad + 1) + j, b = a + rad + 1;
      idx.push(a, b, a + 1, b, b + 1, a + 1);
    }
    const g = new T.BufferGeometry();
    g.setAttribute('position', new T.Float32BufferAttribute(pos, 3));
    g.setAttribute('normal', new T.Float32BufferAttribute(nrm, 3));
    g.setAttribute('aU', new T.Float32BufferAttribute(u, 1));
    g.setIndex(idx);
    g.userData = {curve, len};
    return g;
  }
  // a tight box around shapes (+ pad)
  function bounds(prims, pad = .008) {
    const lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
    const grow = (c, r) => { for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], c[a] - r - pad); hi[a] = Math.max(hi[a], c[a] + r + pad); } };
    prims.filter(p => !p.sub).forEach(p => { if (p.t === 'C') { grow(p.a, p.r1); grow(p.b, p.r2); } else grow(p.c, p.br); });
    return [lo, hi];
  }
  const mirP = pts => pts.map(([x, y, z]) => [-x, y, z]);
  const tick = () => new Promise(r => setTimeout(r, 0));

  /* ================================================================== 3 · the body (metres; patient's left is +x, front is +z) */
  function bodyShapes(female) {
    const P = [];
    const sh = female ? .93 : 1, hip = female ? 1.1 : 1, waist = female ? .9 : 1;
    // head and face
    P.push(El([0, 1.655, -.008], [.074, .094, .094]), El([0, 1.588, .028], [.058, .066, .066]), Sp([0, 1.537, .062], .024, {k: .02}),
      El([0, 1.656, .074], [.056, .016, .024], {k: .012}), Cn([0, 1.633, .087], [0, 1.597, .104], .007, .013, {k: .01}),
      El([0, 1.578, .085], [.022, .009, .012], {k: .008}));
    for (const s of [-1, 1]) {
      P.push(El([s * .044, 1.603, .06], [.028, .022, .03], {k: .02}), El([s * .074, 1.624, -.006], [.011, .028, .019], {k: .008}));
      P.push(Sp([s * .032, 1.628, .086], .012, {sub: true, k: .012}));      // soft eye hollows
    }
    // neck and trunk
    P.push(Cn([0, 1.462, -.012], [0, 1.565, -.008], .058, .05, {k: .03}));
    P.push(El([0, 1.33, 0], [.148 * sh, .14, .098], {k: .05}), El([0, 1.23, .005], [.14, .12, .1], {k: .05}),
      El([0, 1.1, .01], [.13 * waist, .13, .092], {k: .05}), El([0, .955, 0], [.158 * hip, .1, .102], {k: .05}));
    for (const s of [-1, 1]) {
      P.push(Cn([s * .02, 1.505, -.03], [s * .165 * sh, 1.425, -.012], .036, .03, {k: .04}));     // trapezius slope
      P.push(Sp([s * .186 * sh, 1.4, -.002], .05, {k: .04}));                                     // shoulder
      P.push(El([s * .074, 1.335, .062], [.08, .055, .04], {k: .03}));                             // pectoral
      if (female) P.push(Sp([s * .072, 1.3, .1], .055, {k: .035}));
      P.push(El([s * .075, .925, -.06], [.08 * hip, .085, .068], {k: .04}));                       // buttock
      // arm: shoulder → elbow → wrist → hand (palms forward)
      P.push(Cn([s * .19 * sh, 1.395, -.004], [s * .245, 1.11, -.02], .046, .036, {k: .025}),
        El([s * .215, 1.27, .018], [.032, .075, .032], {k: .02}),
        Cn([s * .245, 1.11, -.02], [s * .286, .866, 0], .04, .026, {k: .02}),
        El([s * .257, 1.04, .006], [.036, .07, .032], {k: .02}),
        El([s * .3, .8, .006], [.04, .05, .015], {k: .015}));
      [[.319, .755, .068], [.304, .757, .078], [.289, .755, .072], [.276, .76, .058]].forEach(([x, y, l]) =>
        P.push(Cn([s * x, y, .006], [s * (x + (x - .3) * .25), y - l, .012], .0095, .0075, {k: .008})));
      P.push(Cn([s * .325, .826, .014], [s * .348, .768, .032], .011, .008, {k: .01}));             // thumb
      // leg: hip → knee → ankle → foot
      P.push(Cn([s * .09, .91, 0], [s * .098, .5, .006], .088 * (female ? 1.04 : 1), .052, {k: .03}),
        El([s * .1, .7, .03], [.058, .17, .052], {k: .03}), El([s * .058, .8, 0], [.045, .1, .05], {k: .03}),
        Sp([s * .098, .5, .014], .047, {k: .02}),
        Cn([s * .098, .5, .004], [s * .1, .085, -.01], .05, .03, {k: .02}),
        El([s * .1, .36, -.028], [.047, .1, .043], {k: .025}),
        Cn([s * .1, .05, -.036], [s * .112, .027, .125], .032, .021, {k: .02}),
        El([s * .105, .035, .045], [.04, .026, .085], {k: .02}));
    }
    return P;
  }
  // named muscles: [name, zone, fibre axis, shape]
  function muscleShapes(female) {
    const M = [], hip = female ? 1.1 : 1, sh = female ? .93 : 1;
    const m = (name, zone, fib, p) => { p.name = name; p.zone = zone; p.fib = fib; M.push(p); };
    const both = fn => { fn(-1); fn(1); };
    // deep core: no grooves, keeps the surface closed
    const core = [El([0, 1.33, -.006], [.135 * sh, .13, .085]), El([0, 1.12, -.004], [.12, .14, .08]), El([0, .955, -.004], [.145 * hip, .09, .09]),
      Cn([0, 1.46, -.016], [0, 1.53, -.02], .048, .044)];
    for (const s of [-1, 1]) core.push(                                       // limb cores: no gaps at the elbows, wrists and knees
      Cn([s * .185 * sh, 1.39, -.004], [s * .243, 1.11, -.018], .034, .028), Cn([s * .243, 1.11, -.018], [s * .285, .87, 0], .028, .018),
      Cn([s * .285, .875, 0], [s * .298, .815, .005], .018, .015), Sp([s * .243, 1.11, -.018], .03),
      Cn([s * .09, .9, 0], [s * .098, .5, .004], .068, .04), Cn([s * .098, .52, 0], [s * .1, .09, -.012], .04, .023), Sp([s * .098, .5, .006], .041),
      Cn([s * .1, .1, -.012], [s * .102, .05, -.02], .023, .024));
    core.forEach(p => { p.name = ''; p.zone = 0; p.fib = [0, 1, 0]; p.k = .02; M.push(p); });
    m('Neck', 0, [0, 1, 0], Cn([0, 1.44, -.02], [0, 1.535, -.025], .046, .042, {k: .02}));
    both(s => {
      m('Sternocleidomastoid', 0, [0, 1, 0], Cn([s * .055, 1.565, -.025], [s * .018, 1.462, .045], .014, .012, {k: .009}));
      m('Trapezius', 0, [1, -.3, 0], Cn([s * .015, 1.51, -.04], [s * .17 * sh, 1.425, -.02], .03, .024, {k: .009}));
      m('Trapezius', 0, [0, 1, 0], El([s * .06, 1.33, -.075], [.065, .13, .025], {k: .009, rot: [0, 0, s * .2]}));
      m('Deltoid', 3, [0, 1, 0], El([s * .19 * sh, 1.375, .0], [.052, .072, .054], {k: .009, rot: [0, 0, s * .3]}));
      m('Pectoralis major', 0, [1, .25, 0], El([s * .072, 1.335, .058], [.082, .058, .04], {k: .009, rot: [0, 0, s * -.15]}));
      m('Serratus anterior', 0, [1, 1, 0], El([s * .126, 1.235, .03], [.03, .06, .04], {k: .009}));
      m('Latissimus dorsi', 0, [-.5, 1, 0], El([s * .1, 1.2, -.06], [.07, .13, .04], {k: .009, rot: [0, 0, s * -.25]}));
      [1.2, 1.135, 1.07].forEach((y, i) => m('Rectus abdominis', 0, [0, 1, 0], El([s * .03, y, .078 - i * .002], [.028, .034, .024], {k: .007})));
      m('Rectus abdominis', 0, [0, 1, 0], El([s * .028, .985, .072], [.026, .055, .024], {k: .007}));
      m('External oblique', 0, [-.4, 1, 0], El([s * .098, 1.095, .03], [.04, .09, .048], {k: .009}));
      m('Gluteus maximus', 1, [1, -1, 0], El([s * .078, .93, -.062], [.082 * hip, .088, .066], {k: .009}));
      m('Gluteus medius', 1, [0, 1, 0], El([s * .13 * hip, .98, -.01], [.04, .05, .05], {k: .009}));
      m('Biceps brachii', 3, [.15, 1, 0], Cn([s * .203, 1.33, .02], [s * .24, 1.13, .006], .028, .022, {k: .009}));
      m('Triceps brachii', 3, [.15, 1, 0], Cn([s * .198, 1.34, -.03], [s * .24, 1.13, -.04], .032, .022, {k: .009}));
      m('Brachialis', 3, [.15, 1, 0], El([s * .232, 1.17, .0], [.03, .05, .028], {k: .009}));
      m('Brachioradialis', 2, [.15, 1, 0], Cn([s * .262, 1.1, .006], [s * .283, .9, .012], .024, .012, {k: .009}));
      m('Forearm flexors', 2, [.15, 1, 0], Cn([s * .235, 1.08, .0], [s * .276, .88, .006], .026, .013, {k: .009}));
      m('Forearm extensors', 2, [.15, 1, 0], Cn([s * .258, 1.08, -.03], [s * .29, .88, -.008], .022, .012, {k: .009}));
      m('Hand', 2, [0, 1, 0], El([s * .3, .8, .006], [.039, .048, .014], {k: .01}));
      [[.319, .755, .068], [.304, .757, .078], [.289, .755, .072], [.276, .76, .058]].forEach(([x, y, l]) =>
        m('Hand', 2, [0, 1, 0], Cn([s * x, y, .006], [s * (x + (x - .3) * .25), y - l, .012], .009, .007, {k: .007})));
      m('Hand', 2, [0, 1, 0], Cn([s * .325, .826, .014], [s * .348, .768, .032], .0105, .0075, {k: .009}));
      m('Rectus femoris', 1, [0, 1, 0], El([s * .1, .7, .052], [.034, .165, .034], {k: .008}));
      m('Vastus lateralis', 1, [0, 1, 0], El([s * .133, .69, .01], [.04, .17, .05], {k: .008}));
      m('Vastus medialis', 1, [0, 1, 0], El([s * .072, .585, .032], [.034, .085, .038], {k: .008}));
      m('Sartorius', 1, [-.25, 1, 0], Cn([s * .135, .9, .055], [s * .062, .52, .002], .013, .011, {k: .007}));
      m('Adductors', 1, [.2, 1, 0], El([s * .058, .79, .0], [.044, .11, .05], {k: .009}));
      m('Hamstrings', 1, [0, 1, 0], El([s * .098, .7, -.05], [.05, .16, .04], {k: .009}));
      m('Patellar tendon', 1, [0, 1, 0], El([s * .098, .5, .03], [.026, .045, .02], {k: .008}));
      m('Tibialis anterior', 1, [0, 1, 0], El([s * .114, .33, .028], [.022, .14, .022], {k: .008}));
      m('Gastrocnemius', 1, [0, 1, 0], El([s * .084, .365, -.032], [.03, .1, .04], {k: .008}));
      m('Gastrocnemius', 1, [0, 1, 0], El([s * .116, .375, -.026], [.028, .09, .036], {k: .008}));
      m('Soleus', 1, [0, 1, 0], El([s * .1, .24, -.022], [.04, .1, .035], {k: .009}));
      m('Calf', 1, [0, 1, 0], Cn([s * .098, .46, .0], [s * .1, .09, -.012], .044, .026, {k: .01}));
      m('Foot', 1, [0, 0, 1], Cn([s * .1, .05, -.036], [s * .112, .027, .122], .029, .019, {k: .015}));
      m('Foot', 1, [0, 0, 1], El([s * .105, .034, .045], [.038, .024, .082], {k: .015}));
    });
    return M;
  }

  /* skeleton shapes (one side; the other is mirrored) */
  function skullShapes() {
    return [El([0, 1.662, -.012], [.07, .086, .09]), El([0, 1.598, .038], [.05, .045, .046], {k: .02}),
      El([0, 1.652, .066], [.052, .02, .022], {k: .015}),
      Cn([-.052, 1.612, .045], [-.07, 1.61, -.01], .007, .006, {k: .01}), Cn([.052, 1.612, .045], [.07, 1.61, -.01], .007, .006, {k: .01}),
      El([0, 1.6, -.04], [.048, .03, .04], {k: .03}),
      El([0, 1.575, .052], [.036, .016, .03], {k: .012}),
      Sp([-.031, 1.627, .074], .02, {sub: true, k: .008}), Sp([.031, 1.627, .074], .02, {sub: true, k: .008}),
      El([0, 1.597, .084], [.011, .018, .03], {sub: true, k: .006}),
      El([0, 1.553, .012], [.05, .02, .055], {sub: true, k: .01})];
  }
  function mandibleShapes() {
    const P = [Cn([0, 1.531, .066], [0, 1.528, .07], .012, .012, {k: .01})];
    for (const s of [-1, 1]) P.push(Cn([s * .047, 1.548, -.004], [s * .022, 1.528, .062], .0085, .0075, {k: .012}),
      Cn([s * .049, 1.548, -.006], [s * .053, 1.598, -.018], .007, .006, {k: .01}), Sp([s * .053, 1.6, -.02], .006, {k: .008}));
    return P;
  }
  function axialShapes(female) {
    const hip = female ? 1.08 : 1, P = [];
    // sternum
    P.push(Bx([0, 1.425, .09], [.022, .016, .006], {round: .005, rot: [-.18, 0, 0], k: .006}), Bx([0, 1.34, .098], [.014, .07, .005], {round: .004, rot: [-.12, 0, 0], k: .006}),
      Cn([0, 1.27, .105], [0, 1.245, .1], .005, .002, {k: .004}));
    // sacrum and coccyx
    P.push(El([0, .98, -.072], [.04 * hip, .05, .016], {rot: [-.5, 0, 0], k: .012}), Cn([0, .935, -.088], [0, .91, -.075], .008, .003, {k: .006}));
    for (const s of [-1, 1]) {
      // clavicle (an S-curve) and scapula
      P.push(Cn([s * .018, 1.448, .07], [s * .085, 1.458, .06], .007, .0065, {k: .006}), Cn([s * .085, 1.458, .06], [s * .165, 1.445, -.005], .0065, .006, {k: .006}));
      P.push(El([s * .1, 1.34, -.085], [.05, .072, .007], {rot: [.12, s * -.35, s * .12], k: .008}),
        Cn([s * .06, 1.38, -.09], [s * .16, 1.43, -.03], .006, .007, {k: .008}), Cn([s * .16, 1.43, -.03], [s * .18, 1.44, 0], .008, .006, {k: .008}),
        Cn([s * .14, 1.38, -.05], [s * .135, 1.36, .01], .004, .006, {k: .006}));
      // hip bone: iliac wing, ischium, pubis, socket; hole for the obturator
      P.push(El([s * .095 * hip, 1.0, -.012], [.068 * hip, .055, .011], {rot: [.35, s * .75, s * -.25], k: .012}),
        Cn([s * .13 * hip, 1.045, .01], [s * .14 * hip, 1.03, -.03], .007, .007, {k: .01}),
        Cn([s * .072 * hip, .93, .0], [s * .062 * hip, .875, -.02], .014, .011, {k: .012}),
        Cn([s * .07 * hip, .935, .024], [s * .012, .895, .052], .011, .009, {k: .01}),
        Cn([s * .055 * hip, .875, -.015], [s * .02, .88, .045], .008, .008, {k: .01}),
        Sp([s * .078 * hip, .935, .006], .022, {k: .01}),
        Sp([s * .075 * hip, .935, .01], .02, {sub: true, k: .004}),
        El([s * .043 * hip, .895, .025], [.015, .02, .03], {sub: true, k: .004, rot: [0, s * .6, 0]}));
    }
    return P;
  }
  function limbShapes(female) {            // the patient's left limbs (+x); mirrored for the right
    const hip = female ? 1.08 : 1, s = 1, P = {};
    P.humerus = [Sp([.172, 1.398, -.006], .023), Cn([.178, 1.385, -.006], [.236, 1.125, -.02], .012, .01, {k: .015}),
      El([.24, 1.11, -.02], [.028, .012, .016], {k: .012})];
    P.radius = [Sp([.258, 1.093, -.008], .009), Cn([.258, 1.09, -.006], [.288, .875, .004], .007, .011, {k: .01}), El([.288, .868, .004], [.016, .007, .011], {k: .008})];
    P.ulna = [El([.228, 1.105, -.033], [.01, .016, .011], {k: .01}), Cn([.23, 1.1, -.026], [.268, .872, -.008], .009, .006, {k: .012}), Sp([.268, .868, -.008], .007)];
    P.femur = [Sp([s * .076 * hip, .934, .008], .023), Cn([.076 * hip, .934, .008], [.112 * hip, .91, 0], .014, .013, {k: .01}),
      Sp([.122 * hip, .915, -.008], .018, {k: .012}), Cn([.11 * hip, .9, 0], [.097, .53, .002], .014, .013, {k: .02}),
      Sp([.08, .508, -.002], .024, {k: .02}), Sp([.116, .508, -.004], .023, {k: .02})];
    P.patella = [El([.098, .5, .044], [.018, .022, .009])];
    P.tibia = [El([.098, .478, .004], [.038, .016, .03], {k: .01}), Cn([.098, .47, .008], [.093, .09, .0], .016, .012, {k: .025}),
      El([.092, .08, .0], [.022, .012, .018], {k: .012}), Sp([.078, .072, .002], .012, {k: .01})];
    P.fibula = [Sp([.128, .468, -.016], .01), Cn([.128, .468, -.016], [.124, .085, -.014], .0065, .0065, {k: .01}), Sp([.123, .07, -.012], .011, {k: .01})];
    return P;
  }
  function vertebraShapes() {
    return [Cy([0, 0, 0], .016, .009, {k: .003}), Cn([-.012, .002, -.014], [.012, .002, -.014], .005, .005, {k: .006}),
      Cn([-.012, .003, -.014], [-.01, .003, -.032], .004, .004, {k: .006}), Cn([.012, .003, -.014], [.01, .003, -.032], .004, .004, {k: .006}),
      Cn([0, .003, -.03], [0, -.008, -.048], .0045, .003, {k: .006}),
      Cn([-.01, .003, -.02], [-.03, .005, -.022], .004, .003, {k: .005}), Cn([.01, .003, -.02], [.03, .005, -.022], .004, .003, {k: .005}),
      Cy([0, .003, -.022], .0085, .02, {sub: true, k: .002})];
  }
  // the spine's centre line (vertebral bodies), C1 at the top, L5 at the bottom
  const SPINE = [[0, 1.555, -.032], [0, 1.5, -.04], [0, 1.45, -.042], [0, 1.39, -.05], [0, 1.31, -.06], [0, 1.22, -.058], [0, 1.14, -.045], [0, 1.07, -.03], [0, 1.0, -.04]];

  /* organs */
  function organShapes(female) {
    const O = {};
    O.brain = {prims: [El([0, 1.68, -.014], [.064, .058, .08]), El([0, 1.665, .03], [.055, .04, .045], {k: .03}), Bx([0, 1.7, -.01], [.0018, .05, .09], {sub: true, k: .004})],
      disp: (x, y, z) => { const n = Math.abs(fbm(x * 70, y * 70, z * 70, 2)); return (n - .3) * .004; }, lo: [-.075, 1.6, -.1], hi: [.075, 1.75, .08], h: .0018};
    O.cerebellum = {prims: [El([-.022, 1.623, -.062], [.03, .02, .026]), El([.022, 1.623, -.062], [.03, .02, .026]), Cn([0, 1.645, -.035], [0, 1.57, -.04], .012, .009)],
      disp: (x, y) => Math.sin(y * 1400) * .0006, lo: [-.06, 1.55, -.095], hi: [.06, 1.66, -.02], h: .0017};
    O.heart = {prims: [El([.022, 1.245, .048], [.046, .062, .042], {rot: [.25, 0, -.6]}), El([-.008, 1.29, .03], [.032, .028, .03], {k: .02}),
      El([.04, 1.28, .03], [.028, .024, .028], {k: .02}), Cn([.03, 1.21, .07], [.04, 1.2, .073], .02, .015, {k: .025})],
      disp: (x, y, z) => fbm(x * 90, y * 90, z * 90, 2) * .0012, lo: [-.05, 1.17, -.01], hi: [.1, 1.33, .1], h: .002};
    const lung = s => ({prims: [El([s * .075, 1.29, .0], [.066, .125, .076], {rot: [0, 0, s * -.06]}),
      Sp([.03, 1.235, .06], .055, {sub: true, k: .02}), Sp([s * .06, 1.06, .02], .1, {sub: true, k: .03}),
      Bx([s * .1, 1.28, .03], [.06, .0015, .08], {rot: [0, 0, s * .55], sub: true, k: .003})],
      disp: (x, y, z) => fbm(x * 60, y * 60, z * 60, 2) * .0015, lo: [s < 0 ? -.15 : 0, 1.14, -.08], hi: [s < 0 ? 0 : .15, 1.43, .08], h: .0028});
    O.lungR = lung(-1); O.lungL = lung(1);
    O.liver = {prims: [El([-.045, 1.135, .02], [.11, .06, .072], {rot: [0, 0, -.25]}), El([.045, 1.155, .045], [.05, .03, .04], {k: .04}),
      Sp([-.03, 1.06, .04], .06, {sub: true, k: .03})], disp: (x, y, z) => fbm(x * 40, y * 40, z * 40, 2) * .0012, lo: [-.17, 1.06, -.06], hi: [.11, 1.21, .11], h: .0028};
    O.gallbladder = {prims: [Cn([-.05, 1.09, .07], [-.04, 1.115, .055], .011, .007)], lo: [-.07, 1.07, .04], hi: [-.025, 1.13, .085], h: .0015};
    O.stomach = {prims: [Cn([.03, 1.16, .03], [.075, 1.13, .045], .022, .036), Cn([.075, 1.13, .045], [.07, 1.07, .055], .036, .03),
      Cn([.07, 1.07, .055], [.02, 1.055, .06], .03, .016), Cn([.02, 1.055, .06], [-.01, 1.065, .05], .016, .011)],
      disp: (x, y, z) => fbm(x * 70, y * 70, z * 70, 2) * .0012, lo: [-.03, 1.02, 0], hi: [.12, 1.19, .1], h: .0022};
    O.spleen = {prims: [El([.112, 1.13, -.025], [.022, .048, .034], {rot: [0, .5, .3]})], lo: [.07, 1.07, -.07], hi: [.15, 1.19, .02], h: .002};
    O.pancreas = {prims: [Cn([-.025, 1.065, .02], [.04, 1.085, .0], .015, .011), Cn([.04, 1.085, .0], [.095, 1.1, -.02], .011, .007)],
      disp: (x, y, z) => fbm(x * 200, y * 200, z * 200, 1) * .0012, lo: [-.05, 1.04, -.04], hi: [.115, 1.12, .045], h: .0017};
    O.kidney = {prims: [El([.072, 1.055, -.055], [.025, .05, .02], {rot: [0, .5, .15]}), Sp([.05, 1.055, -.045], .016, {sub: true, k: .01})],
      lo: [.035, .99, -.09], hi: [.105, 1.12, -.02], h: .0017};
    O.adrenal = {prims: [El([.066, 1.107, -.052], [.014, .01, .008], {rot: [0, 0, -.4]})], lo: [.045, 1.09, -.065], hi: [.09, 1.125, -.04], h: .0012};
    O.bladder = {prims: [El([0, .905, .045], [.032, .027, .03])], lo: [-.04, .87, .01], hi: [.04, .94, .08], h: .0017};
    O.thyroid = {prims: [El([-.016, 1.476, .038], [.01, .02, .009]), El([.016, 1.476, .038], [.01, .02, .009]), Cn([-.01, 1.468, .045], [.01, 1.468, .045], .005, .005)],
      lo: [-.03, 1.45, .025], hi: [.03, 1.5, .055], h: .0011};
    O.larynx = {prims: [Cy([0, 1.505, .033], .013, .016, {k: .006}), El([0, 1.513, .045], [.015, .012, .008], {k: .006}), Cy([0, 1.505, .033], .008, .03, {sub: true})],
      lo: [-.02, 1.48, .015], hi: [.02, 1.53, .056], h: .0011};
    O.repro = female
      ? {prims: [El([0, .93, .02], [.025, .03, .018], {rot: [.5, 0, 0]}), Cn([-.02, .945, .02], [-.05, .95, .015], .004, .003), Cn([.02, .945, .02], [.05, .95, .015], .004, .003),
        Sp([-.055, .945, .012], .009), Sp([.055, .945, .012], .009)], lo: [-.07, .89, -.01], hi: [.07, .97, .05], h: .0015}
      : {prims: [El([0, .878, .03], [.016, .013, .014])], lo: [-.02, .86, .012], hi: [.02, .895, .048], h: .0012};
    return O;
  }
  // the small intestine: a long coiled tube packed into the belly; the large intestine framing it
  function intestinePath() {
    const pts = [], rows = 7;
    for (let r = 0; r < rows; r++) {
      const y = 1.03 - r * .017, dir = r % 2 ? -1 : 1;
      for (let i = 0; i <= 10; i++) {
        const t = i / 10, x = dir * (-.07 + .14 * t);
        pts.push([x + Math.sin(t * 9 + r) * .006, y + Math.sin(t * 13 + r * 2) * .007, .055 + Math.cos(t * 7 + r * 1.7) * .014]);
      }
    }
    return pts;
  }
  const COLON = [[-.085, .945, .04], [-.095, .975, .045], [-.1, 1.02, .045], [-.095, 1.06, .05], [-.06, 1.075, .07], [0, 1.07, .075], [.06, 1.075, .07],
    [.1, 1.065, .045], [.105, 1.02, .04], [.1, .975, .04], [.08, .94, .05], [.04, .925, .04], [.01, .925, .0], [0, .93, -.05], [0, .88, -.07]];

  /* blood vessels: [name, artery?, path, radius start, end] (one side when `side`) */
  function vesselPaths() {
    const A = [], Vn = [];
    const both = (list, name, pts, r0, r1) => { list.push({name, pts: mirP(pts), r0, r1, side: -1}); list.push({name, pts, r0, r1, side: 1}); };
    // arteries (from the heart outward; aU starts at the heart)
    A.push({name: 'Aorta', pts: [[.02, 1.25, .05], [.012, 1.3, .045], [.006, 1.35, .03], [.018, 1.37, -.0], [.022, 1.34, -.03], [.016, 1.26, -.035],
      [.012, 1.15, -.03], [.008, 1.05, -.012], [.004, 1.0, -.004]], r0: .0125, r1: .009, root: true});
    both(A, 'Common carotid artery', [[.012, 1.365, .02], [.024, 1.42, .03], [.028, 1.5, .03], [.032, 1.56, .02], [.04, 1.6, .02]], .0045, .0035);
    both(A, 'Subclavian & brachial artery', [[.02, 1.37, .015], [.07, 1.42, .02], [.14, 1.4, .0], [.19, 1.33, .01], [.225, 1.2, .012], [.248, 1.1, .01], [.272, .98, .016], [.29, .88, .018], [.3, .82, .02]], .0048, .0026);
    both(A, 'Iliac & femoral artery', [[.004, 1.0, -.004], [.04, .96, .01], [.07, .9, .035], [.08, .8, .035], [.09, .65, .02], [.1, .52, -.03], [.104, .4, -.03], [.106, .25, -.015], [.108, .1, -.005], [.112, .04, .05]], .0062, .0028);
    both(A, 'Renal artery', [[.008, 1.06, -.016], [.04, 1.058, -.03], [.06, 1.056, -.045]], .003, .0025);
    // veins (towards the heart)
    Vn.push({name: 'Vena cava', pts: [[-.015, .99, -.005], [-.02, 1.05, -.01], [-.024, 1.15, -.012], [-.02, 1.24, .02], [-.012, 1.3, .035], [-.012, 1.38, .03]], r0: .0105, r1: .011});
    both(Vn, 'Jugular vein', [[.04, 1.6, .012], [.038, 1.52, .028], [.03, 1.43, .034], [.014, 1.38, .03]], .0045, .0055);
    both(Vn, 'Arm vein', [[.302, .82, .028], [.292, .9, .03], [.262, 1.06, .036], [.232, 1.2, .03], [.2, 1.33, .02], [.14, 1.405, .02], [.06, 1.42, .03], [.014, 1.38, .03]], .0024, .0045);
    both(Vn, 'Femoral & saphenous vein', [[.1, .04, .06], [.085, .12, .01], [.078, .3, .0], [.075, .5, .01], [.068, .7, .045], [.062, .85, .05], [.035, .96, .015], [-.012, 1.0, -.004]], .003, .0065);
    both(Vn, 'Renal vein', [[.058, 1.056, -.04], [.03, 1.06, -.02], [-.015, 1.06, -.01]], .0032, .0034);
    return {A, Vn};
  }
  function nervePaths() {
    const N = [];
    const both = (name, pts, r) => { N.push({name, pts: mirP(pts), r, side: -1}); N.push({name, pts, r, side: 1}); };
    N.push({name: 'Spinal cord', pts: SPINE.slice(0, 8).map(([x, y, z]) => [x, y, z - .022]), r: .0045});
    both('Brachial plexus & median nerve', [[.0, 1.47, -.06], [.06, 1.43, -.02], [.15, 1.39, -.0], [.2, 1.3, .005], [.235, 1.17, .006], [.258, 1.04, .012], [.28, .92, .014], [.3, .79, .012]], .0022);
    both('Ulnar nerve', [[.2, 1.3, -.01], [.232, 1.12, -.032], [.258, .98, -.012], [.282, .86, -.005], [.28, .76, .006]], .0016);
    both('Sciatic nerve', [[.02, 1.0, -.07], [.06, .93, -.075], [.09, .85, -.06], [.096, .7, -.06], [.1, .52, -.045], [.104, .36, -.035], [.106, .15, -.02], [.108, .06, .0]], .0034);
    both('Femoral nerve', [[.03, 1.0, -.01], [.07, .92, .04], [.085, .8, .05], [.09, .65, .045]], .0022);
    for (let i = 0; i < 6; i++) { const y = 1.38 - i * .045; both('Intercostal nerve', [[.008, y, -.07], [.06, y - .01, -.08], [.12, y - .03, -.02], [.1, y - .06, .07]], .0011); }
    return N;
  }
  // anchors: where each group of values is pinned (figure coordinates)
  function anchorPos(key, female) {
    return ({skin: [0, 1.7, .088], brain: [.03, 1.71, .03], thyroid: [.02, 1.476, .045], lungs: [-.1, 1.31, .04], heart: [.03, 1.25, .08], arm: [-.225, 1.24, .03],
      blood: [.262, 1.06, .036], liver: [-.08, 1.13, .085], stomach: [.075, 1.1, .08], pancreas: [.05, 1.085, .02], spleen: [.12, 1.13, -.01], kidneys: [.075, 1.04, -.05],
      bladder: [0, .905, .07], reproductive: female ? [.05, .945, .02] : [0, .878, .045], bone: [-.11, .72, .012], body: [-.17, .96, .03]})[key] || [0, 1, 0];
  }
  // atlas names, as on an anatomy poster: [label, figure, position, side]
  const NAMES = [['Skeletal system', 0, [-.04, 1.69, .06], -1], ['Mandible', 0, [-.03, 1.535, .06], -1], ['Muscular system', 0, [-.12, 1.42, .03], -1],
    ['Pectoralis major', 0, [-.08, 1.34, .1], -1], ['Biceps', 0, [-.215, 1.25, .045], -1], ['Deltoid', 0, [-.2, 1.38, .04], -1], ['Rectus abdominis', 0, [-.03, 1.13, .1], -1],
    ['Quadriceps', 0, [-.12, .68, .06], -1], ['Patellar tendon', 0, [-.1, .5, .05], -1], ['Gastrocnemius', 0, [-.1, .37, .02], -1], ['Hand', 0, [-.3, .76, .03], -1],
    ['Skull', 1, [.05, 1.66, .07], 1], ['Clavicle', 1, [-.1, 1.455, .06], -1], ['Ribs', 1, [-.12, 1.3, .06], -1], ['Humerus', 1, [-.21, 1.26, -.01], -1], ['Pelvis', 1, [-.1, .99, .0], -1],
    ['Femur', 1, [-.105, .72, .0], -1], ['Tibia', 1, [-.095, .3, .01], -1], ['Fibula', 1, [-.126, .2, -.014], -1], ['Spine', 1, [0, 1.2, -.05], 1], ['Radius & ulna', 1, [.26, .98, -.01], 1],
    ['Brain', 2, [.04, 1.71, .0], 1], ['Cerebellum', 2, [.03, 1.62, -.07], 1], ['Spinal cord', 2, [0, 1.5, -.06], 1], ['Larynx', 2, [.012, 1.51, .05], 1], ['Thyroid', 2, [.022, 1.476, .045], 1],
    ['Lungs', 2, [.1, 1.3, .05], 1], ['Heart', 2, [.035, 1.24, .08], 1], ['Liver', 2, [-.07, 1.13, .08], 1], ['Stomach', 2, [.08, 1.1, .08], 1], ['Spleen', 2, [.12, 1.13, -.02], 1],
    ['Pancreas', 2, [.06, 1.088, .02], 1], ['Kidneys', 2, [.08, 1.05, -.05], 1], ['Intestines', 2, [.05, .98, .07], 1], ['Bladder', 2, [0, .905, .07], 1],
    ['Aorta', 2, [.015, 1.18, -.03], 1], ['Femoral artery', 2, [.09, .7, .03], 1], ['Sciatic nerve', 2, [.1, .6, -.05], 1]];

  /* ================================================================== 4 · materials */
  function skinColor(T, tone, F) {
    const c = new T.Color(tone);
    const hsl = {}; c.getHSL(hsl);
    const S = F.skin || {};
    if (S.pallor) { hsl.s *= 1 - .4 * S.pallor; hsl.l = hsl.l + (0.7 - hsl.l) * .22 * S.pallor; }
    c.setHSL(hsl.h, hsl.s, hsl.l);
    if (S.jaundice) c.lerp(new T.Color('#c9a227'), .3 * S.jaundice);
    if (S.cyanosis) c.lerp(new T.Color('#7d8fb5'), .25 * S.cyanosis);
    return c;
  }
  function wet(T, color, o = {}) {
    return new T.MeshPhysicalMaterial({color, roughness: .38, metalness: 0, clearcoat: .55, clearcoatRoughness: .3, vertexColors: !!o.vc, ...o.p});
  }
  // a pulse that travels along a vessel or nerve (aU = metres from the start), at the patient's heart rate
  function flowing(T, base, U, kind) {
    const m = new T.MeshStandardMaterial({color: base, roughness: kind === 'nerve' ? .45 : .32, metalness: .05, emissive: '#000'});
    m.onBeforeCompile = sh => {
      Object.assign(sh.uniforms, U);
      sh.vertexShader = 'attribute float aU;\nvarying float vU;\n' + sh.vertexShader.replace('#include <begin_vertex>', '#include <begin_vertex>\nvU = aU;');
      const glow = kind === 'artery'
        ? 'float ph = fract(uTime * uHz - vU * uHz / 0.9); float pulse = exp(-pow((ph - 0.12) * 9.0, 2.0)); totalEmissiveRadiance += uGlowA * pulse * uAmp;'
        : kind === 'vein'
          ? 'float ph = fract(vU * 22.0 - uTime * 0.35 * uHz); totalEmissiveRadiance += uGlowV * smoothstep(0.75, 1.0, ph) * 0.35;'
          : 'float ph = fract(vU * 3.0 - uTime * 1.6); totalEmissiveRadiance += uGlowN * (exp(-pow((ph - 0.5) * 24.0, 2.0)) * uSpark + 0.06);';
      sh.fragmentShader = `uniform float uTime; uniform float uHz; uniform float uAmp; uniform float uSpark; uniform vec3 uGlowA; uniform vec3 uGlowV; uniform vec3 uGlowN;\nvarying float vU;\n`
        + sh.fragmentShader.replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\n' + glow);
    };
    return m;
  }
  function muscleMaterial(T, U, opacity = 1) {
    const m = new T.MeshStandardMaterial({color: '#ffffff', vertexColors: true, roughness: .42, metalness: 0, envMapIntensity: .55, transparent: opacity < 1, opacity, depthWrite: opacity >= 1});
    m.onBeforeCompile = sh => {
      Object.assign(sh.uniforms, U);
      sh.vertexShader = 'attribute float aAcross;\nattribute float aTendon;\nattribute float aZone;\nvarying float vAcross;\nvarying float vTendon;\nvarying float vZone;\n'
        + sh.vertexShader.replace('#include <begin_vertex>', '#include <begin_vertex>\nvAcross = aAcross; vTendon = aTendon; vZone = aZone;');
      sh.fragmentShader = 'uniform float uTime; uniform float uTwitch; uniform float uTetany;\nvarying float vAcross;\nvarying float vTendon;\nvarying float vZone;\n'
        + sh.fragmentShader
          .replace('#include <color_fragment>', `#include <color_fragment>
            float w1 = clamp(1.0 - fwidth(vAcross * 1500.0) * 0.5, 0.0, 1.0), w2 = clamp(1.0 - fwidth(vAcross * 4200.0) * 0.5, 0.0, 1.0);
            float fib = mix(0.5, 0.5 + 0.5 * sin(vAcross * 1500.0 + sin(vAcross * 95.0) * 2.5), w1);
            float fine = mix(0.5, 0.5 + 0.5 * sin(vAcross * 4200.0), w2);
            diffuseColor.rgb *= mix(0.62, 1.18, fib) * mix(0.9, 1.05, fine);
            diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.82, 0.76, 0.68), clamp(vTendon, 0.0, 1.0));`)
          .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
            float flick = step(0.6, fract(sin(floor(uTime * 9.0) * 12.9898) * 43758.5453));
            totalEmissiveRadiance += vec3(0.6, 0.05, 0.02) * uTwitch * flick * step(0.5, vZone) * step(vZone, 1.5);
            totalEmissiveRadiance += vec3(0.6, 0.5, 0.05) * uTetany * flick * step(1.5, vZone) * step(vZone, 2.5);`);
    };
    return m;
  }
  function glassMaterial(T, color = '#7fd3ff') {
    return new T.ShaderMaterial({
      transparent: true, depthWrite: false, side: T.FrontSide,
      uniforms: {uColor: {value: new T.Color(color)}, uBase: {value: .05}, uRim: {value: .6}},
      vertexShader: 'varying vec3 vN; varying vec3 vV; void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.0); vN = normalize(normalMatrix * normal); vV = -mv.xyz; gl_Position = projectionMatrix * mv; }',
      fragmentShader: 'uniform vec3 uColor; uniform float uBase; uniform float uRim; varying vec3 vN; varying vec3 vV; void main(){ float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 2.6); gl_FragColor = vec4(uColor * (0.6 + f), uBase + f * uRim); }',
    });
  }
  // vertex colours with mottling, and a coloured patch where a finding is (heart damage, pneumonia, …)
  function paint(T, g, base, opt = {}) {
    const p = g.attributes.position.array, n = p.length / 3, col = new Float32Array(n * 3), c = new T.Color(base), tmp = new T.Color();
    for (let i = 0; i < n; i++) {
      const x = p[i * 3], y = p[i * 3 + 1], z = p[i * 3 + 2];
      const mot = fbm(x * (opt.f || 60), y * (opt.f || 60), z * (opt.f || 60), 3);
      tmp.copy(c).multiplyScalar(1 + mot * (opt.m ?? .22));
      if (opt.patch) opt.patch(tmp, x, y, z);
      col[i * 3] = tmp.r; col[i * 3 + 1] = tmp.g; col[i * 3 + 2] = tmp.b;
    }
    g.setAttribute('color', new T.BufferAttribute(col, 3));
    return g;
  }
  // per-vertex muscle names, fibre coordinates, tendons and grooves between muscles
  function muscleAttrs(T, g, M) {
    const p = g.attributes.position.array, nr = g.attributes.normal.array, n = p.length / 3;
    const across = new Float32Array(n), tendon = new Float32Array(n), zone = new Float32Array(n), mid = new Float32Array(n), col = new Float32Array(n * 3);
    const named = M.map((m, i) => ({m, i})).filter(o => o.m.name);
    const base = [.42, .055, .05];
    // a coarse grid of the muscles that can be nearest in each cell
    const C = .04, grid = new Map(), cell = (x, y, z) => `${Math.floor(x / C)},${Math.floor(y / C)},${Math.floor(z / C)}`;
    const near = (x, y, z) => {
      const key = cell(x, y, z);
      let list = grid.get(key);
      if (!list) {
        const cx = (Math.floor(x / C) + .5) * C, cy = (Math.floor(y / C) + .5) * C, cz = (Math.floor(z / C) + .5) * C;
        const ds = named.map(o => Math.max(0, Math.hypot(cx - o.m.c[0], cy - o.m.c[1], cz - o.m.c[2]) - o.m.br));
        const lim = Math.min(...ds) + C * 1.8 + .02;
        list = named.filter((o, i) => ds[i] <= lim);
        grid.set(key, list);
      }
      return list;
    };
    for (let v = 0; v < n; v++) {
      const x = p[v * 3], y = p[v * 3 + 1], z = p[v * 3 + 2];
      let d1 = 1e9, d2 = 1e9, best = null;
      for (const o of near(x, y, z)) {
        const pr = o.m, dx = x - pr.c[0], dy = y - pr.c[1], dz = z - pr.c[2];
        if (Math.sqrt(dx * dx + dy * dy + dz * dz) - pr.br > d2) continue;
        const d = dPrim(pr, x, y, z);
        if (d < d1) { d2 = d1; d1 = d; best = o; } else if (d < d2) d2 = d;
      }
      const pr = best ? best.m : M[0];
      mid[v] = best ? best.i : -1;
      zone[v] = pr.zone || 0;
      // fibres run along `fib`; stripes vary across them
      const f = pr.fib || [0, 1, 0], fl = Math.hypot(...f), fx = f[0] / fl, fy = f[1] / fl, fz = f[2] / fl;
      let ax = fy * nr[v * 3 + 2] - fz * nr[v * 3 + 1], ay = fz * nr[v * 3] - fx * nr[v * 3 + 2], az = fx * nr[v * 3 + 1] - fy * nr[v * 3];
      const al = Math.hypot(ax, ay, az) || 1;
      across[v] = (x * ax + y * ay + z * az) / al;
      // tendons at the ends of long muscles (along the fibre axis)
      const along = (x - pr.c[0]) * fx + (y - pr.c[1]) * fy + (z - pr.c[2]) * fz;
      const half = pr.t === 'C' ? Math.sqrt(pr.l2) / 2 + pr.r2 : pr.t === 'E' ? Math.max(...pr.r) : .05;
      const isTendon = /tendon/i.test(pr.name) ? 1 : 0;
      const distal = along * fy < 0 ? 1 : 0;   // the lower end of a limb muscle becomes tendon
      tendon[v] = Math.max(isTendon * .7, /Hand|Foot/.test(pr.name) ? .12 : clamp((Math.abs(along) / half - .8) / .18, 0, 1) * distal * (/biceps|brachioradialis|flexor|extensor|gastro|tibialis/i.test(pr.name) ? .8 : 0));
      // groove: where two muscles meet the surface is shadowed
      const groove = clamp(1 - (d2 - d1) / .007, 0, 1);
      const sh = 1 - .55 * groove * groove, wob = 1 + fbm(x * 50, y * 50, z * 50, 2) * .12;
      col[v * 3] = base[0] * sh * wob; col[v * 3 + 1] = base[1] * sh * wob; col[v * 3 + 2] = base[2] * sh * wob;
    }
    g.setAttribute('aAcross', new T.BufferAttribute(across, 1));
    g.setAttribute('aTendon', new T.BufferAttribute(tendon, 1));
    g.setAttribute('aZone', new T.BufferAttribute(zone, 1));
    g.setAttribute('color', new T.BufferAttribute(col, 3));
    g.userData.muscleIndex = mid;
    g.userData.names = M.map(m => m.name);
    return g;
  }

  /* ================================================================== 5 · geometry build (cached per body) */
  const CACHE = {};
  const GEO_VERSION = 'b3-geo-3';             // change when the shapes change, so browsers rebuild their stored copy
  // the built meshes are kept in the browser (IndexedDB), so the next visit opens at once
  const idb = () => new Promise((res, rej) => { const r = indexedDB.open('medflow-body3d', 1); r.onupgradeneeded = () => r.result.createObjectStore('geo'); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
  async function idbGet(k) { try { const db = await idb(); return await new Promise(res => { const q = db.transaction('geo').objectStore('geo').get(k); q.onsuccess = () => res(q.result || null); q.onerror = () => res(null); }); } catch (e) { return null; } }
  async function idbPut(k, v) { try { const db = await idb(); db.transaction('geo', 'readwrite').objectStore('geo').put(v, k); } catch (e) { /* private mode: rebuild next time */ } }
  function pack(v) {
    if (v && v.isBufferGeometry) {
      const a = {}; for (const [k, at] of Object.entries(v.attributes)) a[k] = [at.array, at.itemSize];
      const ud = {}; for (const [k, x] of Object.entries(v.userData || {})) if (k !== 'curve') ud[k] = x;
      return {__g: 1, a, i: v.index ? v.index.array : null, ud};
    }
    if (Array.isArray(v)) return v.map(pack);
    if (v && typeof v === 'object') { const o = {}; for (const [k, x] of Object.entries(v)) if (k !== 'flowPaths') o[k] = pack(x); return o; }
    return v;
  }
  function unpack(T, v) {
    if (v && v.__g) {
      const g = new T.BufferGeometry();
      for (const [k, [arr, n]] of Object.entries(v.a)) g.setAttribute(k, new T.BufferAttribute(arr, n));
      if (v.i) g.setIndex(new T.BufferAttribute(v.i, 1));
      g.userData = v.ud || {}; g.computeBoundingSphere();
      return g;
    }
    if (Array.isArray(v)) return v.map(x => unpack(T, x));
    if (v && typeof v === 'object') { const o = {}; for (const [k, x] of Object.entries(v)) o[k] = unpack(T, x); return o; }
    return v;
  }
  function flowPaths(T) {
    const {A, Vn} = vesselPaths();
    return A.map(v => ({curve: new T.CatmullRomCurve3(v.pts.map(p => new T.Vector3(...p))), r: v.r0, name: v.name}))
      .concat(Vn.map(v => ({curve: new T.CatmullRomCurve3(v.pts.map(p => new T.Vector3(...p))), r: v.r0, vein: true, name: v.name})));
  }
  async function buildGeometry(T, female, progress) {
    const key = female ? 'F' : 'M';
    if (CACHE[key]) return CACHE[key];
    const stored = typeof indexedDB !== 'undefined' && !window.MF_B3_NOCACHE ? await idbGet(`${GEO_VERSION}:${key}`) : null;
    if (stored) {
      try { const G = unpack(T, stored); G.flowPaths = flowPaths(T); CACHE[key] = G; return G; } catch (e) { /* rebuild */ }
    }
    const G = {};
    const step = async (label, fn) => { progress(label); await tick(); const t0 = performance.now(); fn(); if (window.MF_B3_DEBUG) console.log(label, Math.round(performance.now() - t0) + 'ms'); };
    await step('Shaping the body…', () => { G.skin = surface(T, {prims: bodyShapes(female), k: .02}, [-.4, -.01, -.16], [.4, 1.78, .17], .0058); });
    await step('Laying the muscles…', () => {
      const M = muscleShapes(female);
      G.muscle = muscleAttrs(T, surface(T, {prims: M, k: .009}, [-.39, 0, -.15], [.39, 1.6, .16], .0052), M);
    });
    await step('Building the skeleton…', () => {
      G.skull = paint(T, surface(T, {prims: skullShapes(), k: .02}, [-.09, 1.52, -.11], [.09, 1.77, .1], .0021), '#e9dfc6', {f: 90, m: .1});
      G.mandible = paint(T, surface(T, {prims: mandibleShapes(), k: .01}, [-.07, 1.51, -.03], [.07, 1.61, .085], .0016), '#e6dbc1', {f: 90, m: .1});
      G.axial = paint(T, surface(T, {prims: axialShapes(female), k: .008}, [-.2, .85, -.12], [.2, 1.48, .12], .0028), '#e6dac0', {f: 70, m: .12});
      const L = limbShapes(female), limbs = [];
      for (const [k, prims] of Object.entries(L)) {
        const [lo, hi] = bounds(prims, .012);
        const g = paint(T, surface(T, {prims, k: .012}, lo, hi, k === 'patella' ? .0015 : .0024), '#e8ddc3', {f: 80, m: .1});
        g.userData.bone = k; limbs.push(g);
      }
      G.limbL = limbs; G.limbR = limbs.map(g => { const m = mirrorX(T, g); m.userData.bone = g.userData.bone; return m; });
      G.vertebra = paint(T, surface(T, {prims: vertebraShapes(), k: .004}, [-.04, -.02, -.06], [.04, .02, .02], .0011), '#e8ddc3', {f: 140, m: .1});
      // ribs and costal cartilage
      const bony = [], cart = [];
      for (let i = 0; i < 12; i++) {
        const y = 1.43 - i * .0275, w = [.058, .085, .105, .12, .13, .138, .142, .143, .14, .135, .12, .1][i];
        for (const s of [-1, 1]) {
          const front = i < 10;
          const pts = [[s * .014, y, -.05], [s * .045, y - .004, -.07], [s * w * .9, y - .02, -.05], [s * w, y - .045, .0], [s * w * .85, y - .07, front ? .055 : .03]];
          if (front) pts.push([s * w * .55, y - .085, .085]);
          bony.push(tube(T, pts, .0058, .0048, {radial: 7, flat: .55}));
          if (i < 7) cart.push(tube(T, [pts[pts.length - 1], [s * (w * .3 + .01), y - .08 - i * .003, .095], [s * .016, 1.435 - i * .024 - (i ? .02 : 0), .1]], .0042, .0038, {radial: 6}));
          else if (i < 10) cart.push(tube(T, [pts[pts.length - 1], [s * (.06 - (i - 7) * .006), 1.235 + (9 - i) * .004, .1], [s * .03, 1.255, .105]], .0038, .0034, {radial: 6}));
        }
      }
      G.ribs = paint(T, merge(T, bony), '#e6dabf', {f: 80, m: .1});
      G.cartilage = paint(T, merge(T, cart), '#cfdcd8', {f: 80, m: .06});
      // hands and feet: metacarpals, phalanges, metatarsals as small capsules
      const small = [];
      const cap = (a, b, r) => {
        const A = new T.Vector3(...a), Bv = new T.Vector3(...b), len = A.distanceTo(Bv);
        const g = new T.CapsuleGeometry(r, Math.max(.0005, len - 2 * r), 3, 7);
        const q = new T.Quaternion().setFromUnitVectors(new T.Vector3(0, 1, 0), Bv.clone().sub(A).normalize());
        g.applyQuaternion(q); g.translate((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2);
        g.deleteAttribute('uv'); small.push(g);
      };
      for (const s of [-1, 1]) {
        [[.319, .068], [.304, .078], [.289, .072], [.276, .058]].forEach(([x, l]) => {
          const base = [s * (.296 + (x - .3) * .5), .842, .004], kn = [s * x, .756, .006], dir = (x - .3) * .25;
          cap(base, kn, .0042);
          let a = kn; [.42, .32, .26].forEach((fr, j) => { const b = [a[0] + s * dir * l * fr, a[1] - l * fr, a[2] + .002]; cap(a, b, .0036 - j * .0006); a = b; });
        });
        cap([s * .31, .845, .01], [s * .325, .815, .016], .0045); cap([s * .325, .815, .016], [s * .338, .79, .024], .004); cap([s * .338, .79, .024], [s * .348, .77, .032], .0034);
        for (let c = 0; c < 6; c++) cap([s * (.285 + (c % 3) * .011), .853 - Math.floor(c / 3) * .011, .004], [s * (.287 + (c % 3) * .011), .851 - Math.floor(c / 3) * .011, .006], .005);
        // foot
        cap([s * .1, .045, -.04], [s * .1, .04, -.012], .016); cap([s * .1, .06, -.01], [s * .102, .055, .012], .013);
        for (let t = 0; t < 5; t++) {
          const x = .082 + t * .011, b = [s * (.095 + t * .004), .04, .02], e = [s * x, .022, .085 + (t === 0 ? .008 : -t * .004)];
          cap(b, e, t === 0 ? .0055 : .0042); cap(e, [s * x, .016, e[2] + .028 - t * .002], t === 0 ? .005 : .0034);
        }
      }
      G.extremity = paint(T, merge(T, small), '#e8ddc3', {f: 90, m: .08});
      // teeth
      const teeth = [];
      for (const [y, rr] of [[1.567, .03], [1.552, .028]]) for (let i = 0; i < 14; i++) {
        const a = (i / 13 - .5) * Math.PI * .95, b = new T.BoxGeometry(.006, .009, .006);
        b.rotateY(a); b.translate(Math.sin(a) * rr, y, .045 + Math.cos(a) * rr); b.deleteAttribute('uv'); teeth.push(b);
      }
      G.teeth = merge(T, teeth);
    });
    await step('Placing the organs…', () => {
      const O = organShapes(female);
      G.organ = {};
      for (const [k, o] of Object.entries(O)) G.organ[k] = surface(T, {prims: o.prims, k: o.k || .012, disp: o.disp || null}, o.lo, o.hi, o.h);
      G.organ.kidneyR = mirrorX(T, G.organ.kidney); G.organ.kidneyR.translate(0, -.012, 0);
      G.organ.adrenalR = mirrorX(T, G.organ.adrenal); G.organ.adrenalR.translate(0, -.012, 0);
      G.organ.intestine = tube(T, intestinePath(), .0115, .0115, {radial: 10, seg: 420, wave: t => Math.sin(t * 900) * .06});
      G.organ.colon = tube(T, COLON, .016, .012, {radial: 12, seg: 200, wave: t => Math.max(0, Math.sin(t * 160)) * .18});
      G.organ.trachea = tube(T, [[0, 1.49, .033], [0, 1.4, .025], [0, 1.33, .012]], .0085, .0085, {radial: 10, wave: t => Math.max(0, Math.sin(t * 110)) * .1});
      const br = [];
      for (const s of [-1, 1]) {
        br.push(tube(T, [[0, 1.333, .012], [s * .03, 1.305, .01], [s * .055, 1.28, .01]], .0062, .0048, {radial: 8}));
        for (let j = 0; j < 5; j++) br.push(tube(T, [[s * .055, 1.28, .01], [s * (.07 + j * .006), 1.27 + (j - 2) * .03, .01 + (j % 2 ? .02 : -.015)], [s * (.08 + j * .008), 1.25 + (j - 2) * .05, .015]], .003, .0015, {radial: 6}));
      }
      G.organ.bronchi = merge(T, br);
      G.organ.esophagus = tube(T, [[0, 1.5, .018], [-.002, 1.4, .006], [.006, 1.28, .0], [.02, 1.19, .02], [.03, 1.16, .03]], .006, .007, {radial: 8});
      G.organ.ureters = merge(T, [tube(T, [[.06, 1.04, -.045], [.055, .99, -.03], [.04, .94, .0], [.015, .91, .04]], .0022, .0022, {radial: 6}),
        tube(T, [[-.06, 1.03, -.045], [-.055, .98, -.03], [-.04, .94, .0], [-.015, .91, .04]], .0022, .0022, {radial: 6})]);
    });
    await step('Running the vessels and nerves…', () => {
      const {A, Vn} = vesselPaths();
      const aortaLen = tube(T, A[0].pts, .01).userData.len;
      // arteries branching from the aorta start their pulse further out, so the wave runs from the heart
      const startU = n => n === 'Aorta' ? 0 : /carotid|Subclavian/.test(n) ? .12 : aortaLen * .95;
      G.arteries = merge(T, A.map(v => tube(T, v.pts, v.r0, v.r1, {radial: 9, u0: startU(v.name)})));
      G.veins = merge(T, Vn.map(v => tube(T, v.pts, v.r0, v.r1, {radial: 9})));
      G.nerves = merge(T, nervePaths().map(n => tube(T, n.pts, n.r, n.r * .7, {radial: 6})));
      G.flowPaths = flowPaths(T);
    });
    CACHE[key] = G;
    if (typeof indexedDB !== 'undefined') idbPut(`${GEO_VERSION}:${key}`, pack(G));
    return G;
  }

  /* ================================================================== 6 · the viewer */
  const TONES = [['Light', '#e8b896'], ['Medium', '#c68d63'], ['Tan', '#a46a43'], ['Brown', '#7a4a2b'], ['Dark', '#55311c']];
  const PRESETS = {
    atlas: {label: 'Atlas', icon: 'bi-people'},
    skin: {label: 'Skin', icon: 'bi-person', layers: ['skin']},
    muscle: {label: 'Muscles', icon: 'bi-activity', layers: ['muscle', 'skull']},
    glass: {label: 'Glass body', icon: 'bi-transparency', layers: ['glass', 'bone', 'organ', 'vessel', 'nerve', 'blood']},
    organ: {label: 'Organs', icon: 'bi-heart-pulse', layers: ['organ', 'vessel', 'blood', 'muscleFaint']},
    bone: {label: 'Skeleton', icon: 'bi-universal-access', layers: ['bone', 'skull']},
  };
  const LAYERS = [['skin', 'Skin'], ['muscle', 'Muscles'], ['bone', 'Skeleton'], ['organ', 'Organs'], ['vessel', 'Blood vessels'], ['nerve', 'Nerves'], ['blood', 'Blood cells']];
  const webgl = (() => { try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch (e) { return false; } })();

  async function mount(root, D, opts = {}) {
    D = D || {};
    opts = {capture: !!window.MF_B3_CAPTURE, ...opts};      // capture: render slowly (screenshots and automated tests)
    const F = (window.MFAnatomy && window.MFAnatomy.findings) ? window.MFAnatomy.findings(D) : {findings: [], skin: {}, muscle: {}, vessel: {}, organ: {}, bone: {fractures: []}, hr: 72, rr: 14};
    const groups = values(D);
    const female = (D.patient || {}).sex === 'F';
    const vit = D.vitals || {};
    const hrRaw = num(vit.heart_rate), rrRaw = num(vit.resp_rate);
    const hr = clamp(hrRaw ?? 72, 25, 220), rr = clamp(rrRaw ?? 14, 4, 60);
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const params = D.params || [];
    const lab = code => { const p = params.find(x => x.code === code); return p && p.latest && typeof p.latest.num === 'number' ? p.latest.num : null; };
    const state = {preset: opts.preset || 'atlas', labels: opts.labels || 'values', tone: TONES[3][1], expand: false, focus: null, spin: false};
    const levelCls = l => l >= 3 ? 'lv3' : l >= 2 ? 'lv2' : 'lv0';
    const metaNote = (D.vitals_meta && D.vitals_meta.source === 'bedside') ? `bedside observation ${D.vitals_meta.hours_ago} h ago` : D.vitals_meta ? 'last visit' : '';

    root.innerHTML = `<div class="b3-wrap">
      <div class="b3-stage">
        <canvas class="b3-canvas" aria-label="3D anatomy of ${esc((D.patient || {}).name || 'the patient')}, drawn from the entered values"></canvas>
        <svg class="b3-lines" aria-hidden="true"></svg><div class="b3-labels"></div><div class="b3-tip" hidden></div>
        <div class="b3-msg"><span class="spinner-border spinner-border-sm"></span> <span class="b3-msgt">Preparing 3D…</span></div>
        <div class="b3-tools">
          <div class="b3-seg" role="group" aria-label="View">${Object.entries(PRESETS).map(([k, p]) => `<button type="button" data-preset="${k}"><i class="bi ${p.icon}"></i>${p.label}</button>`).join('')}</div>
          <div class="b3-seg" role="group" aria-label="Labels"><span>Labels</span><button type="button" data-labels="values">Patient values</button><button type="button" data-labels="names">Names</button><button type="button" data-labels="off">Off</button></div>
        </div>
        <div class="b3-tools b3-tools2">
          <details class="b3-layers"><summary><i class="bi bi-layers"></i>Layers</summary><div>${LAYERS.map(([k, l]) => `<label><input type="checkbox" data-layer="${k}"> ${l}</label>`).join('')}</div></details>
          <div class="b3-tones" role="group" aria-label="Skin tone">${TONES.map(([n, c]) => `<button type="button" data-tone="${c}" style="--c:${c}" title="${n} skin" aria-label="${n} skin"></button>`).join('')}</div>
          <button type="button" class="b3-btn" data-act="spin"><i class="bi bi-arrow-repeat"></i>Rotate</button>
          <button type="button" class="b3-btn" data-act="expand" title="Show every value in the callouts"><i class="bi bi-arrows-angle-expand"></i>All values</button>
          <button type="button" class="b3-btn" data-act="reset"><i class="bi bi-bullseye"></i>Reset</button>
        </div>
        <div class="b3-dial"><span>360°</span><input type="range" min="-180" max="180" value="0" aria-label="Turn the body"><span><i class="bi bi-zoom-in"></i></span><input type="range" min="0" max="100" value="0" class="b3-zoom" aria-label="Zoom"></div>
        <div class="b3-vitals"></div>
        <p class="b3-help">Drag to turn · scroll to zoom · click an organ or a value · Esc resets</p>
      </div>
      <aside class="b3-side"></aside>
    </div>`;
    const $ = s => root.querySelector(s), $$ = s => [...root.querySelectorAll(s)];
    const stage = $('.b3-stage'), canvas = $('.b3-canvas'), labelsEl = $('.b3-labels'), linesEl = $('.b3-lines'), tip = $('.b3-tip');
    let alive = true, raf = 0, renderer = null, ro = null;
    const disposables = [];
    const destroy = () => {
      alive = false; cancelAnimationFrame(raf); ro && ro.disconnect(); document.removeEventListener('keydown', onKey);
      disposables.forEach(d => { try { d.dispose(); } catch (e) { /* gone */ } });
      if (renderer) { renderer.dispose(); renderer.forceContextLoss && renderer.forceContextLoss(); }
    };
    const handle = {destroy, values: groups, findings: F};

    /* ---------------- side panel: every value, where it is on the body */
    function renderSide() {
      const sel = state.focus;
      const list = sel ? groups.filter(g => g.anchor === sel) : groups;
      const fs = (F.findings || []);
      $('.b3-side').innerHTML = `
        <div class="b3-sh"><h3>${sel ? esc(ANCHOR_LABEL[sel] || sel) : 'Values on the body'}</h3>${sel ? '<button type="button" class="b3-back" data-act="all"><i class="bi bi-arrow-left"></i>All</button>' : ''}</div>
        <p class="b3-note">Exactly as entered: latest lab result per test${Object.keys(vit).length ? ` and vital signs (${esc(metaNote || 'last visit')})` : ''}. ▲ high · ▼ low · ▲▲/▼▼ critical.</p>
        ${!groups.length ? '<div class="b3-empty">No results or vital signs entered yet. The body shows a healthy baseline.</div>' : ''}
        ${list.map(g => `<section class="b3-g ${levelCls(g.level)}"><button type="button" class="b3-gh" data-anchor="${g.anchor}"><b>${esc(g.label)}</b><span>${g.items.length}</span><i class="bi bi-crosshair"></i></button>
          ${g.items.map(it => `<div class="b3-v ${levelCls(it.level)}" title="${esc([it.test, it.range ? 'Ref ' + it.range : '', it.date].filter(Boolean).join(' · '))}"><span>${esc(it.name)}</span><b>${esc(fmt(it))}</b><em>${arrow(it.flag)}</em></div>`).join('')}</section>`).join('')}
        ${fs.length && !sel ? `<h4>What the model shows</h4>${fs.slice(0, 12).map(f => `<div class="b3-f ${levelCls(f.level)}"><b>${esc(f.title)}</b><span>${esc(f.text)}</span></div>`).join('')}` : ''}
        <h4>Under the microscope</h4><div class="b3-tissue"></div>
        <h4>Animation from the values</h4>
        <div class="b3-f"><span>Heart beats at <b>${hrRaw !== null ? esc(vit.heart_rate) + ' bpm (entered)' : '72 bpm (not recorded)'}</b>; lungs breathe at <b>${rrRaw !== null ? esc(vit.resp_rate) + '/min (entered)' : '14/min (not recorded)'}</b>. Red cells follow the haemoglobin${lab('HB') !== null ? ` (${lab('HB')})` : ''}, white cells and platelets their counts.</span></div>
        <p class="b3-note">Teaching illustration built from the record. It does not replace the results, imaging or examination.</p>`;
      const th = $('.b3-tissue'); if (th) drawTissue(th, F, tissueVals(), still);
    }
    const tissueVals = () => ({hb: lab('HB'), wbc: lab('WBC'), plt: lab('PLT'), dens: lab('DENS')});
    renderSide();
    function renderVitals() {
      const chips = [];
      if (vit.bp) chips.push(['bi-speedometer2', 'BP', vit.bp + ' mmHg', vitalFlag('bp', vit.bp)]);
      if (hrRaw !== null) chips.push(['bi-heart-pulse-fill b3-beat', 'HR', vit.heart_rate + ' bpm', vitalFlag('heart_rate', vit.heart_rate)]);
      if (num(vit.spo2) !== null) chips.push(['bi-lungs', 'SpO₂', vit.spo2 + '%', vitalFlag('spo2', vit.spo2)]);
      if (rrRaw !== null) chips.push(['bi-wind', 'RR', vit.resp_rate + '/min', vitalFlag('resp_rate', vit.resp_rate)]);
      if (num(vit.temperature_c) !== null) chips.push(['bi-thermometer-half', 'Temp', vit.temperature_c + ' °C', vitalFlag('temperature_c', vit.temperature_c)]);
      $('.b3-vitals').innerHTML = chips.map(([ic, k, v, f]) => `<span class="b3-chip ${levelCls(({HH: 3, LL: 3, H: 2, L: 2})[f] || 0)}"><i class="bi ${ic}"></i>${k} <b>${esc(v)}</b>${arrow(f)}</span>`).join('')
        + (metaNote ? `<span class="b3-chip b3-src">${esc(metaNote)}</span>` : '');
      $('.b3-vitals').style.setProperty('--b3-beat', `${(60 / hr).toFixed(3)}s`);
    }
    renderVitals();

    if (!webgl || !window.MF_THREE) { $('.b3-msgt').textContent = 'This browser cannot show 3D. The values are listed on the right.'; $('.b3-msg .spinner-border').remove(); return handle; }
    let T, OrbitControls, RoomEnvironment;
    try {
      T = await import(window.MF_THREE.three);
      ({OrbitControls} = await import(window.MF_THREE.controls));
      ({RoomEnvironment} = await import(window.MF_THREE.room));
    } catch (e) { $('.b3-msgt').textContent = '3D could not be loaded. The values are listed on the right.'; $('.b3-msg .spinner-border').remove(); return handle; }
    if (!alive) return handle;
    const G = await buildGeometry(T, female, t => { $('.b3-msgt').textContent = t; });
    if (!alive) return handle;

    renderer = new T.WebGLRenderer({canvas, antialias: true, alpha: true, powerPreference: 'high-performance', preserveDrawingBuffer: !!opts.capture});
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    renderer.outputColorSpace = T.SRGBColorSpace;
    renderer.toneMapping = T.ACESFilmicToneMapping; renderer.toneMappingExposure = .85;
    renderer.localClippingEnabled = true;
    const scene = new T.Scene();
    const pmrem = new T.PMREMGenerator(renderer);
    const envTex = pmrem.fromScene(new RoomEnvironment(renderer), .04).texture;
    scene.environment = envTex; disposables.push(pmrem, envTex);
    const camera = new T.PerspectiveCamera(30, 1, .05, 30);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true; controls.dampingFactor = .08;
    controls.minDistance = .5; controls.maxDistance = 6;
    controls.addEventListener('start', () => { state.spin = false; $('[data-act=spin]').classList.remove('on'); });
    const key = new T.DirectionalLight('#fff3e6', 2.0); key.position.set(2.5, 4, 4); scene.add(key);
    const rim = new T.DirectionalLight('#8fd0ff', 1.6); rim.position.set(-3, 2.5, -3); scene.add(rim);
    const fill = new T.DirectionalLight('#ffd9c9', .5); fill.position.set(-3, 1, 3); scene.add(fill);
    scene.add(new T.HemisphereLight('#dbeeff', '#1a1012', .35));
    // floor glow
    const fc = document.createElement('canvas'); fc.width = fc.height = 128;
    const fg = fc.getContext('2d'), gr = fg.createRadialGradient(64, 64, 2, 64, 64, 62); gr.addColorStop(0, 'rgba(120,200,255,.35)'); gr.addColorStop(1, 'rgba(120,200,255,0)'); fg.fillStyle = gr; fg.fillRect(0, 0, 128, 128);
    const floorTex = new T.CanvasTexture(fc); disposables.push(floorTex);

    /* ---------------- shared uniforms driven by the values */
    const U = {uTime: {value: 0}, uHz: {value: hr / 60}, uAmp: {value: 1}, uSpark: {value: 1}, uTwitch: {value: 0}, uTetany: {value: 0},
      uGlowA: {value: new T.Color('#ff4a3a')}, uGlowV: {value: new T.Color('#4f8dff')}, uGlowN: {value: new T.Color('#ffe066')}};
    const V = F.vessel || {}, O = F.organ || {}, S = F.skin || {}, Bn = F.bone || {fractures: []}, Mu = F.muscle || {};
    U.uAmp.value = {crisis: 2.4, high: 1.6, low: .35, normal: 1}[V.pressure || 'normal'];
    U.uTwitch.value = (Mu.twitch || 0) + (Mu.inflam ? .8 : 0); U.uTetany.value = Mu.tetany ? 1 : 0;
    U.uSpark.value = O.brain ? 2.2 : 1;

    const M = {};
    M.skin = new T.MeshPhysicalMaterial({color: skinColor(T, state.tone, F), roughness: .55, metalness: 0, sheen: .5, sheenRoughness: .6, sheenColor: new T.Color('#ffd8c8'),
      clearcoat: .08, clearcoatRoughness: .6, envMapIntensity: .6, emissive: new T.Color('#ff3a10'), emissiveIntensity: 0, vertexColors: true});
    M.glass = glassMaterial(T, '#8fdcff');
    M.muscle = muscleMaterial(T, U);
    M.muscleFaint = muscleMaterial(T, U, .32);
    M.bone = new T.MeshPhysicalMaterial({color: '#ffffff', vertexColors: true, roughness: .55, clearcoat: .2, clearcoatRoughness: .5});
    M.boneCut = M.bone.clone(); M.boneCut.clippingPlanes = [new T.Plane(new T.Vector3(0, -1, 0), 1.705)];   // the glass figure's skull is opened to show the brain
    M.cartilage = new T.MeshPhysicalMaterial({color: '#ffffff', vertexColors: true, roughness: .35, clearcoat: .6, transmission: 0, transparent: true, opacity: .92});
    M.teeth = new T.MeshPhysicalMaterial({color: '#f5f1e6', roughness: .25, clearcoat: .8});
    M.artery = flowing(T, V.pressure === 'crisis' ? '#d0161b' : '#b81d22', U, 'artery');
    M.vein = flowing(T, '#2f4fa8', U, 'vein');
    M.nerve = flowing(T, '#f0c43a', U, 'nerve');
    Object.values(M).forEach(m => disposables.push(m));

    // skin vertex colours: blue lips and fingertips (cyanosis), redness on the face (fever)
    (() => {
      const p = G.skin.attributes.position.array, n = p.length / 3, col = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) {
        const x = p[i * 3], y = p[i * 3 + 1], z = p[i * 3 + 2];
        let r = 1, g = 1, b = 1;
        const lips = Math.exp(-(((y - 1.566) / .008) ** 2 + (x / .022) ** 2)) * (z > .07 ? 1 : 0);
        r *= 1 - .18 * lips; g *= 1 - .32 * lips; b *= 1 - .22 * lips;           // lips are darker and redder
        const tips = clamp((.72 - y) / .03, 0, 1) * (Math.abs(x) > .24 ? 1 : 0) + clamp((.03 - y) / .02, 0, 1) * clamp((z - .1) / .03, 0, 1);
        const cy = (S.cyanosis || 0) * Math.max(lips, tips);
        r *= 1 - .45 * cy; g *= 1 - .2 * cy; b *= 1 + .25 * cy;
        const n2 = 1 + fbm(x * 90, y * 90, z * 90, 2) * .04;
        col[i * 3] = r * n2; col[i * 3 + 1] = g * n2; col[i * 3 + 2] = b * n2;
      }
      G.skin.setAttribute('color', new T.BufferAttribute(col, 3));
    })();
    // swollen ankles (oedema): push the lower legs outwards
    const skinGeo = G.skin.clone();
    if (S.edema) {
      const p = skinGeo.attributes.position.array, nr = skinGeo.attributes.normal.array;
      for (let i = 0; i < p.length; i += 3) { const w = clamp((.32 - p[i + 1]) / .2, 0, 1) * clamp(p[i + 1] / .04, 0, 1); p[i] += nr[i] * .009 * S.edema * w; p[i + 2] += nr[i + 2] * .009 * S.edema * w; }
      skinGeo.attributes.position.needsUpdate = true;
    }
    disposables.push(skinGeo);

    /* ---------------- organs coloured by the findings */
    const orgMat = {};
    const om = (k, color, opt = {}) => { orgMat[k] = wet(T, color, {vc: true, p: {emissive: new T.Color('#ff2020'), emissiveIntensity: 0, ...opt}}); disposables.push(orgMat[k]); return orgMat[k]; };
    const organGeo = {};
    const pg = (k, color, o) => { organGeo[k] = paint(T, G.organ[k].clone(), color, o); disposables.push(organGeo[k]); };
    const yellow = new T.Color('#c9a227');
    pg('brain', O.brain ? '#e7a0a6' : '#e3a4a6', {f: 120, m: .16, patch: c => { if (S.jaundice) c.lerp(yellow, .1 * S.jaundice); }});
    pg('cerebellum', '#d98f96', {f: 140, m: .15});
    pg('heart', '#a8222a', {f: 70, m: .25, patch: (c, x, y, z) => {
      if (y > 1.27) c.lerp(new T.Color('#e2c290'), .45 * clamp((y - 1.27) / .03, 0, 1));                    // fat at the base
      if (O.infarct) { const w = Math.exp(-(((x - .045) / .025) ** 2 + ((y - 1.215) / .025) ** 2)); c.lerp(new T.Color('#3a1430'), .85 * O.infarct * w); }
    }});
    const lungPatch = side => (c, x, y, z) => {
      if (O.hypox) c.lerp(new T.Color('#8a6f9a'), .45 * O.hypox);
      if (O.congest) c.lerp(new T.Color('#9b3b3f'), .35 * clamp((1.25 - y) / .08, 0, 1));
      if (O.consolid && side < 0) c.lerp(new T.Color('#b8754a'), .7 * clamp((1.22 - y) / .05, 0, 1));
      if (O.effusion) c.lerp(new T.Color('#5d6f8f'), .5 * clamp((1.19 - y) / .03, 0, 1));
      if (F.findings.some(f => f.title === 'Tuberculosis') && y > 1.36) c.lerp(new T.Color('#e7ddc8'), .5);
      c.lerp(new T.Color('#4a3a3e'), .15 * Math.max(0, fbm(x * 220, y * 220, z * 220, 1)));                 // little dark spots
    };
    pg('lungR', '#e2a39e', {f: 110, m: .28, patch: lungPatch(-1)}); pg('lungL', '#e2a39e', {f: 110, m: .28, patch: lungPatch(1)});
    pg('liver', '#7e2a20', {f: 50, m: .2, patch: c => { if (O.liver) c.lerp(new T.Color('#c4442e'), .5 * O.liver); if (O.yellow) c.lerp(yellow, .5 * O.yellow); }});
    pg('gallbladder', '#5b7a3a', {f: 80, m: .15});
    pg('stomach', '#d38a7a', {f: 90, m: .18});
    pg('spleen', '#6a2638', {f: 80, m: .2});
    pg('pancreas', '#e3b07c', {f: 160, m: .25, patch: c => { if (O.pancreas) c.lerp(new T.Color('#e04a3a'), .55 * O.pancreas); }});
    const kp = c => { if (O.kidneys) c.lerp(new T.Color('#8d8a86'), .6 * O.kidneys); };
    pg('kidney', '#7d2c27', {f: 90, m: .2, patch: kp}); pg('kidneyR', '#7d2c27', {f: 90, m: .2, patch: kp});
    pg('adrenal', '#e2b84a', {f: 120, m: .2}); pg('adrenalR', '#e2b84a', {f: 120, m: .2});
    pg('bladder', F.findings.some(f => f.target === 'bladder') ? '#e08a6a' : '#e8b8a0', {f: 80, m: .15});
    pg('thyroid', O.thyroid ? '#c84a4a' : '#a8443e', {f: 120, m: .2});
    pg('larynx', '#dcc8b4', {f: 120, m: .1});
    pg('repro', female ? '#d98a8f' : '#b5706a', {f: 100, m: .15});
    pg('intestine', '#e4a094', {f: 70, m: .18});
    pg('colon', '#d99a82', {f: 60, m: .15});
    pg('trachea', '#e2d2c0', {f: 120, m: .08}); pg('bronchi', '#e2cfc0', {f: 120, m: .08});
    pg('esophagus', '#d48a80', {f: 100, m: .1}); pg('ureters', '#e8c2a8', {f: 100, m: .1});
    const ORGAN_LIST = [['brain', 'Brain', 'brain'], ['cerebellum', 'Cerebellum', 'brain'], ['heart', 'Heart', 'heart'], ['lungR', 'Right lung', 'lungs'], ['lungL', 'Left lung', 'lungs'],
      ['liver', 'Liver', 'liver'], ['gallbladder', 'Gallbladder', 'liver'], ['stomach', 'Stomach', 'stomach'], ['spleen', 'Spleen', 'spleen'], ['pancreas', 'Pancreas', 'pancreas'],
      ['kidney', 'Left kidney', 'kidneys'], ['kidneyR', 'Right kidney', 'kidneys'], ['adrenal', 'Adrenal gland', 'kidneys'], ['adrenalR', 'Adrenal gland', 'kidneys'],
      ['bladder', 'Bladder', 'bladder'], ['thyroid', 'Thyroid', 'thyroid'], ['larynx', 'Larynx', 'thyroid'], ['repro', female ? 'Uterus & ovaries' : 'Prostate', 'reproductive'],
      ['intestine', 'Small intestine', 'stomach'], ['colon', 'Large intestine', 'stomach'], ['trachea', 'Trachea', 'lungs'], ['bronchi', 'Bronchi', 'lungs'],
      ['esophagus', 'Oesophagus', 'stomach'], ['ureters', 'Ureters', 'kidneys']];
    ORGAN_LIST.forEach(([k]) => om(k, '#ffffff'));

    /* ---------------- bone colour: thin bones are greyer; fractures glow */
    const boneTint = c => { if (Bn.osteo) c.lerp(new T.Color('#b8ae9a'), .35 * Bn.osteo); };
    const recolor = g => { const c = g.attributes.color.array, t = new T.Color(); for (let i = 0; i < c.length; i += 3) { t.setRGB(c[i], c[i + 1], c[i + 2]); boneTint(t); c[i] = t.r; c[i + 1] = t.g; c[i + 2] = t.b; } return g; };
    const boneGeo = {skull: recolor(G.skull.clone()), mandible: recolor(G.mandible.clone()), axial: recolor(G.axial.clone()), ribs: recolor(G.ribs.clone()), vertebra: recolor(G.vertebra.clone()), extremity: recolor(G.extremity.clone()),
      limbs: G.limbL.map(g => { const m = recolor(g.clone()); m.userData.bone = g.userData.bone; m.userData.side = 'left'; return m; })
        .concat(G.limbR.map(g => { const m = recolor(g.clone()); m.userData.bone = g.userData.bone; m.userData.side = 'right'; return m; }))};
    Object.values(boneGeo).flat().forEach(g => disposables.push(g));
    const BONE_NAME = {humerus: 'Humerus', radius: 'Radius', ulna: 'Ulna', femur: 'Femur', patella: 'Patella', tibia: 'Tibia', fibula: 'Fibula'};

    /* ---------------- one figure: groups of layers that can be switched on and off */
    function figure(kind) {
      const fig = new T.Group(), L = {};
      const layer = k => { const g = new T.Group(); g.name = k; fig.add(g); L[k] = g; return g; };
      const mk = (geo, mat, name, anchor, parent) => { const m = new T.Mesh(geo, mat); m.userData = {name, anchor}; parent.add(m); return m; };
      mk(skinGeo, M.skin, 'Skin', 'skin', layer('skin'));
      mk(skinGeo, M.glass, 'Skin (glass)', 'skin', layer('glass')).renderOrder = 10;
      const mus = mk(G.muscle, kind === 2 ? M.muscleFaint : M.muscle, 'Muscle', null, layer('muscle')); mus.userData.muscle = true; if (kind === 2) mus.renderOrder = 9;
      const sk = layer('skull');
      mk(boneGeo.skull, kind === 1 ? M.boneCut : M.bone, 'Skull', 'bone', sk); mk(boneGeo.mandible, M.bone, 'Mandible', 'bone', sk); mk(G.teeth, M.teeth, 'Teeth', 'bone', sk);
      const bone = layer('bone');
      mk(boneGeo.axial, M.bone, 'Pelvis, sternum, clavicles & shoulder blades', 'bone', bone);
      mk(boneGeo.ribs, M.bone, 'Ribs', 'bone', bone); mk(G.cartilage, M.cartilage, 'Costal cartilage', 'bone', bone);
      mk(boneGeo.extremity, M.bone, 'Bones of the hands and feet', 'bone', bone);
      boneGeo.limbs.forEach(g => mk(g, M.bone, `${BONE_NAME[g.userData.bone] || g.userData.bone} (${g.userData.side})`, 'bone', bone).userData.bone = g.userData);
      // spine: one vertebra shape, placed 24 times along the curve
      const curve = new T.CatmullRomCurve3(SPINE.map(p => new T.Vector3(...p)));
      const vi = new T.InstancedMesh(boneGeo.vertebra, M.bone, 24); vi.userData = {name: 'Spine (vertebrae)', anchor: 'bone'};
      const mtx = new T.Matrix4(), q = new T.Quaternion(), up = new T.Vector3(0, 1, 0);
      for (let i = 0; i < 24; i++) {
        const t = i / 23, p = curve.getPointAt(t), tg = curve.getTangentAt(t).negate();
        const s = i < 7 ? .62 + i * .03 : i < 19 ? .85 + (i - 7) * .012 : 1.05 + (i - 19) * .06;
        q.setFromUnitVectors(up, tg);
        mtx.compose(p, q, new T.Vector3(s, s * (i < 7 ? .85 : 1), s)); vi.setMatrixAt(i, mtx);
      }
      bone.add(vi);
      const org = layer('organ');
      ORGAN_LIST.forEach(([k, name, anchor]) => { const m = mk(organGeo[k], orgMat[k], name, anchor, org); m.userData.organ = k; });
      const ves = layer('vessel');
      mk(G.arteries, M.artery, 'Arteries', 'blood', ves); mk(G.veins, M.vein, 'Veins', 'blood', ves);
      mk(G.nerves, M.nerve, 'Nerves & spinal cord', 'brain', layer('nerve'));
      layer('blood');
      const floor = new T.Mesh(new T.PlaneGeometry(.9, .9), new T.MeshBasicMaterial({map: floorTex, transparent: true, depthWrite: false}));
      floor.rotation.x = -Math.PI / 2; floor.position.y = .001; fig.add(floor); disposables.push(floor.geometry, floor.material);
      fig.userData.L = L;
      return fig;
    }
    const figs = [figure(0), figure(1), figure(2)];
    figs.forEach(f => scene.add(f));
    const organMeshes = f => f.userData.L.organ.children;

    /* ---------------- findings on the model: fractures, plaques, a clot, gout, petechiae */
    const fxMats = [];
    const glowMat = color => { const m = new T.MeshBasicMaterial({color, transparent: true, opacity: .55, depthWrite: false, blending: T.AdditiveBlending}); fxMats.push(m); disposables.push(m); return m; };
    const BONE_AT = {femur: .72, tibia: .3, fibula: .25, humerus: 1.25, radius: .98, ulna: .98, clavicle: 1.455, rib: 1.28, pelvis: .98, skull: 1.7, spine: 1.2, ankle: .07, hand: .78, foot: .03, knee: .5, toe: .02, marrow: .72};
    const BONE_X = {femur: .1, tibia: .095, fibula: .126, humerus: .21, radius: .272, ulna: .25, clavicle: .09, rib: .13, pelvis: .1, skull: 0, spine: 0, ankle: .09, hand: .3, foot: .11, knee: .098, toe: .1, marrow: .1};
    function addFindings(fig, kind) {
      const L = fig.userData.L, sph = r => new T.SphereGeometry(r, 16, 12);
      (Bn.fractures || []).forEach(fr => {
        const s = fr.side === 'left' ? 1 : -1, y = BONE_AT[fr.bone] ?? .7, x = s * (BONE_X[fr.bone] ?? .1);
        const g = new T.Mesh(sph(.034), glowMat('#ff3b30')); g.position.set(x, y, fr.bone === 'spine' ? -.05 : .0); g.userData = {name: `Fracture: ${fr.side} ${fr.bone}`, anchor: 'bone', pulse: 1}; L.bone.add(g);
        const crack = new T.Mesh(new T.TorusGeometry(.016, .0022, 6, 18), new T.MeshBasicMaterial({color: '#2a0505'})); crack.position.set(x, y, 0); crack.rotation.x = Math.PI / 2; L.bone.add(crack);
        disposables.push(g.geometry, crack.geometry, crack.material);
      });
      if (V.plaque > .05) for (const s of [-1, 1]) for (let i = 0; i < 3; i++) { const g = new T.Mesh(sph(.0045), new T.MeshStandardMaterial({color: '#f1d36b', roughness: .4})); g.position.set(s * (.026 + i * .002), 1.44 + i * .03, .033); L.vessel.add(g); disposables.push(g.geometry, g.material); }
      if (V.clot) { const g = new T.Mesh(sph(.009), new T.MeshStandardMaterial({color: '#2b0c12', roughness: .6})); g.position.set(-.078, .3, .0); g.userData = {name: 'Blood clot (deep vein)', anchor: 'blood'}; L.vessel.add(g); disposables.push(g.geometry, g.material); }
      if (Bn.gout) for (const s of [-1, 1]) { const g = new T.Mesh(sph(.012), glowMat('#fff2a0')); g.position.set(s * .086, .02, .11); g.userData = {name: 'Gout crystals', anchor: 'bone', pulse: 1}; L.bone.add(g); disposables.push(g.geometry); }
      if (Bn.arthritis) for (const s of [-1, 1]) { const g = new T.Mesh(sph(.03), glowMat('#ff8a3d')); g.position.set(s * .098, .5, .01); g.userData = {name: 'Inflamed joint', anchor: 'bone', pulse: 1}; L.bone.add(g); disposables.push(g.geometry); }
      if (Bn.marrow) for (const s of [-1, 1]) { const g = new T.Mesh(new T.CylinderGeometry(.008, .008, .3, 10), glowMat('#ff4d6d')); g.position.set(s * .104, .72, 0); g.userData = {name: 'Busy bone marrow', anchor: 'bone', pulse: 1}; L.bone.add(g); disposables.push(g.geometry); }
      if (S.petechiae && kind !== 1) {
        const n = 90, im = new T.InstancedMesh(new T.SphereGeometry(.0018, 6, 4), new T.MeshBasicMaterial({color: '#7a0f1a'}), n);
        const p = skinGeo.attributes.position.array, cand = [];
        for (let i = 0; i < p.length; i += 3) if (p[i + 1] > .1 && p[i + 1] < .55 && p[i + 2] > .01) cand.push(i);
        const mx = new T.Matrix4();
        for (let j = 0; j < n; j++) { const i = cand[Math.floor(hash(j, 3, 7) * cand.length)]; mx.makeTranslation(p[i], p[i + 1], p[i + 2] + .001); im.setMatrixAt(j, mx); }
        im.userData = {name: 'Bleeding spots (petechiae)', anchor: 'skin'}; L.skin.add(im); disposables.push(im.geometry, im.material);
      }
    }
    figs.forEach((f, i) => addFindings(f, i));

    /* ---------------- blood cells: how many and how fast come from the values */
    const hb = lab('HB'), wbc = lab('WBC'), plt = lab('PLT'), dens = lab('DENS');
    const nRed = Math.round(220 * clamp((hb ?? (female ? 13 : 14.5)) / (female ? 13.5 : 15), .2, 1.4));
    const nWhite = Math.round(clamp((wbc ?? 7) / 7 * 10, 1, 60));
    const nPlt = Math.round(clamp((plt ?? 250) / 250 * 40, 2, 140));
    const infectedShare = V.malaria ? clamp(dens !== null ? Math.log10(Math.max(dens, 10)) / 6 : .25, .08, .8) : 0;
    const cellGeo = {red: new T.SphereGeometry(.0042, 10, 6), white: new T.SphereGeometry(.0055, 12, 8), plt: new T.SphereGeometry(.0018, 6, 4), para: new T.SphereGeometry(.0018, 6, 4)};
    cellGeo.red.scale(1, .42, 1);
    const redCol = new T.Color('#d0161b'); if (V.anaemia) redCol.lerp(new T.Color('#f2a3a3'), .6 * V.anaemia); if (V.sickle) redCol.lerp(new T.Color('#9b1c3c'), .3);
    const cellMat = {red: new T.MeshStandardMaterial({color: redCol, roughness: .35, emissive: redCol, emissiveIntensity: .25}), white: new T.MeshStandardMaterial({color: '#f4f7ff', roughness: .5, emissive: '#9fb6ff', emissiveIntensity: .2}),
      plt: new T.MeshStandardMaterial({color: '#f3d36b', roughness: .5}), para: new T.MeshBasicMaterial({color: '#8b3fd9'})};
    Object.values(cellGeo).forEach(g => disposables.push(g)); Object.values(cellMat).forEach(m => disposables.push(m));
    const arteryPaths = G.flowPaths.filter(p => !p.vein), allPaths = G.flowPaths;
    const cellsDef = [['red', nRed, allPaths], ['white', nWhite, allPaths], ['plt', nPlt, arteryPaths], ['para', Math.round(nRed * infectedShare), arteryPaths]];
    const cellSets = figs.map(fig => cellsDef.map(([k, n, paths]) => {
      if (!n) return null;
      const im = new T.InstancedMesh(cellGeo[k], cellMat[k], n);
      im.userData = {name: {red: 'Red blood cells', white: 'White blood cells', plt: 'Platelets', para: 'Malaria parasites'}[k], anchor: 'blood'};
      const items = Array.from({length: n}, (_, i) => ({path: paths[i % paths.length], t: hash(i, k.length, 3), off: [(hash(i, 1, 2) - .5), (hash(i, 2, 1) - .5)], spin: hash(i, 9, 9) * 6}));
      fig.userData.L.blood.add(im);
      return {im, items};
    }).filter(Boolean));
    const flowSpeed = .035 * (hr / 72);   // fraction of a path per second
    const tmpM = new T.Matrix4(), tmpQ = new T.Quaternion(), tmpE = new T.Euler(), tmpS = new T.Vector3(1, 1, 1);
    function updateCells(dt) {
      cellSets.forEach((sets, fi) => {
        if (!figs[fi].visible || !figs[fi].userData.L.blood.visible) return;
        sets.forEach(({im, items}) => {
          items.forEach((it, i) => {
            if (!still) it.t = (it.t + dt * flowSpeed * (it.path.vein ? .6 : 1.1) * (.8 + .4 * Math.abs(it.off[0]))) % 1;
            const p = it.path.curve.getPointAt(it.t);
            p.x += it.off[0] * it.path.r * 1.3; p.z += it.off[1] * it.path.r * 1.3;
            tmpE.set(it.spin + it.t * 20, it.spin, 0); tmpQ.setFromEuler(tmpE);
            tmpM.compose(p, tmpQ, tmpS); im.setMatrixAt(i, tmpM);
          });
          im.instanceMatrix.needsUpdate = true;
        });
      });
    }

    /* ---------------- presets and layers */
    const layerKeys = ['skin', 'glass', 'muscle', 'skull', 'bone', 'organ', 'vessel', 'nerve', 'blood'];
    function setLayers(fig, on) {
      const L = fig.userData.L;
      layerKeys.forEach(k => { L[k].visible = on.includes(k); });
      if (on.includes('muscleFaint')) { L.muscle.visible = true; L.muscle.children[0].material = M.muscleFaint; L.muscle.children[0].renderOrder = 9; }
      else L.muscle.children[0].material = M.muscle;
      if (on.includes('bone')) L.skull.visible = true;
    }
    let single = ['glass', 'bone', 'organ', 'vessel', 'nerve', 'blood'];
    function applyPreset(p) {
      state.preset = p;
      $$('[data-preset]').forEach(b => b.classList.toggle('on', b.dataset.preset === p));
      if (p === 'atlas') {
        figs.forEach((f, i) => { f.visible = true; f.position.x = (i - 1) * .7; });
        setLayers(figs[0], ['muscle', 'skull']); setLayers(figs[1], ['glass', 'bone', 'organ', 'vessel', 'nerve', 'blood']); setLayers(figs[2], ['muscleFaint', 'organ', 'vessel', 'nerve', 'blood']);
        figs[1].userData.L.skull.children[0].material = M.boneCut;
      } else {
        figs.forEach((f, i) => { f.visible = i === 1; f.position.x = 0; });
        single = PRESETS[p].layers.slice();
        setLayers(figs[1], single);
        figs[1].userData.L.skull.children[0].material = single.includes('organ') ? M.boneCut : M.bone;
      }
      syncLayerBoxes();
      frame(true);
      buildLabels();
    }
    function syncLayerBoxes() {
      const L = figs[1].userData.L;
      $$('[data-layer]').forEach(b => {
        const k = b.dataset.layer;
        b.checked = k === 'skin' ? (L.skin.visible || L.glass.visible) : k === 'bone' ? L.bone.visible : L[k].visible;
        b.disabled = state.preset === 'atlas';
      });
    }
    $$('[data-layer]').forEach(b => b.addEventListener('change', () => {
      if (state.preset === 'atlas') return;
      const k = b.dataset.layer, L = figs[1].userData.L;
      if (k === 'skin') { const solid = !L.organ.visible && !L.bone.visible && !L.muscle.visible; L.skin.visible = b.checked && solid; L.glass.visible = b.checked && !solid; }
      else if (k === 'bone') { L.bone.visible = b.checked; L.skull.visible = b.checked || L.muscle.visible; }
      else L[k].visible = b.checked;
      if (k !== 'skin' && L.skin.visible && b.checked) { L.skin.visible = false; L.glass.visible = true; }    // open the skin to see inside
      L.skull.children[0].material = L.organ.visible ? M.boneCut : M.bone;
      $$('[data-preset]').forEach(x => x.classList.remove('on'));
      syncLayerBoxes(); buildLabels();
    }));

    /* ---------------- camera */
    const target = new T.Vector3(0, .9, 0);
    let fly = null, baseDist = 3.6;
    function frame(instant) {
      const w = stage.clientWidth || 800, h = stage.clientHeight || 600, asp = w / h;
      const width = state.preset === 'atlas' ? 2.3 : .95, height = 1.95;
      const vfov = camera.fov * Math.PI / 180, hfov = 2 * Math.atan(Math.tan(vfov / 2) * asp);
      // leave room at the sides for the callouts
      const pad = state.labels === 'off' ? 1.06 : state.preset === 'atlas' ? 1.3 : 1.9;
      baseDist = Math.max(height / 2 / Math.tan(vfov / 2), width * pad / 2 / Math.tan(hfov / 2)) * 1.04;
      flyTo(new T.Vector3(0, .9, 0), new T.Vector3(0, .95, baseDist), instant);
    }
    function flyTo(tgt, pos, instant) {
      if (instant || still) { target.copy(tgt); camera.position.copy(pos); controls.target.copy(tgt); controls.update(); fly = null; return; }
      fly = {t: 0, fromT: controls.target.clone(), fromP: camera.position.clone(), toT: tgt, toP: pos};
    }
    function focusAnchor(a) {
      state.focus = a; renderSide(); buildLabels();
      if (!a) { frame(false); return; }
      const fi = state.preset === 'atlas' ? (['heart', 'lungs', 'liver', 'stomach', 'pancreas', 'spleen', 'kidneys', 'bladder', 'brain', 'thyroid', 'reproductive'].includes(a) ? 2 : 1) : 1;
      const p = new T.Vector3(...anchorPos(a, female)); p.x += figs[fi].position.x;
      if (a === 'bone' && (Bn.fractures || []).length) { const fr = Bn.fractures[0]; p.set((fr.side === 'left' ? 1 : -1) * (BONE_X[fr.bone] ?? .1) + figs[fi].position.x, BONE_AT[fr.bone] ?? .7, 0); }
      flyTo(p, new T.Vector3(p.x + .12, p.y + .04, p.z + .75), false);
      pulseAnchor = a; pulseUntil = performance.now() + 2600;
    }
    let pulseAnchor = null, pulseUntil = 0;

    /* ---------------- callouts: patient values or atlas names, with leader lines */
    let labels = [];
    function buildLabels() {
      labelsEl.innerHTML = ''; labels = [];
      const add = (html, fi, pos, side, cls, anchor) => {
        const el = document.createElement('div');
        el.className = `b3-lab ${cls}`; el.innerHTML = html;
        if (anchor) { el.dataset.anchor = anchor; el.setAttribute('role', 'button'); el.tabIndex = 0; }
        labelsEl.appendChild(el);
        labels.push({el, fi, pos: new T.Vector3(...pos), side, anchor});
      };
      if (state.labels === 'names') {
        NAMES.forEach(([name, fi, pos, side]) => {
          const f = state.preset === 'atlas' ? fi : 1;
          if (state.preset !== 'atlas') {
            const L = figs[1].userData.L;
            const need = fi === 0 ? (name === 'Skeletal system' || name === 'Mandible' ? 'skull' : 'muscle') : fi === 1 ? 'bone' : 'organ';
            if (!L[need].visible && !(need === 'organ' && /artery|Aorta/.test(name) && L.vessel.visible) && !(name === 'Sciatic nerve' && L.nerve.visible) && !(name === 'Spinal cord' && L.nerve.visible)) return;
          }
          add(`<span>${esc(name)}</span>`, f, pos, state.preset === 'atlas' ? (fi === 0 ? -1 : fi === 2 ? 1 : side) : (pos[0] < 0 ? -1 : 1), 'b3-name');
        });
      } else if (state.labels === 'values') {
        const list = state.focus ? groups.filter(g => g.anchor === state.focus) : groups;
        list.forEach(g => {
          const shown = state.expand || state.focus ? g.items : g.items.filter(i => i.source === 'vital' || i.level).slice(0, 3).concat(g.items.some(i => i.source === 'vital' || i.level) ? [] : g.items.slice(0, 2));
          const more = g.items.length - shown.length;
          const fi = state.preset === 'atlas' ? (['heart', 'lungs', 'liver', 'stomach', 'pancreas', 'spleen', 'kidneys', 'bladder', 'brain', 'thyroid', 'reproductive'].includes(g.anchor) ? 2 : 0) : 1;
          let pos = anchorPos(g.anchor, female);
          if (g.anchor === 'bone' && (Bn.fractures || []).length) { const fr = Bn.fractures[0]; pos = [(fr.side === 'left' ? 1 : -1) * (BONE_X[fr.bone] ?? .1), BONE_AT[fr.bone] ?? .7, .01]; }
          const side = state.preset === 'atlas' ? (fi === 2 ? 1 : -1) : (pos[0] < -.005 ? -1 : pos[0] > .005 ? 1 : (g.anchor === 'skin' ? -1 : 1));
          add(`<b>${esc(g.label)}</b>${shown.map(it => `<div class="b3-li ${levelCls(it.level)}"><span>${esc(it.name)}</span><em>${esc(fmt(it))}</em><i>${arrow(it.flag)}</i></div>`).join('')}${more > 0 ? `<div class="b3-more">+${more} more</div>` : ''}`,
            fi, pos, side, `b3-val ${levelCls(g.level)}`, g.anchor);
        });
      }
      labelsEl.querySelectorAll('[data-anchor]').forEach(el => {
        el.addEventListener('click', () => focusAnchor(state.focus === el.dataset.anchor ? null : el.dataset.anchor));
        el.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); el.click(); } });
      });
      labels.forEach(l => { l.w = l.el.offsetWidth; l.h = l.el.offsetHeight; });
    }
    const v3 = new T.Vector3();
    function layoutLabels() {
      const W = stage.clientWidth, H = stage.clientHeight;
      if (!labels.length) { linesEl.innerHTML = ''; return; }
      const rect = {};
      // each figure's left/right edge on screen, so callouts sit just outside it
      figs.forEach((f, i) => {
        if (!f.visible) return;
        let mn = 1e9, mx = -1e9;
        for (const [x, y] of [[-.34, 1.2], [.34, 1.2], [-.34, .8], [.34, .8], [-.2, 1.65], [.2, 1.65], [-.15, .1], [.15, .1]]) {
          v3.set(x + f.position.x, y, 0).project(camera); const sx = (v3.x + 1) / 2 * W; mn = Math.min(mn, sx); mx = Math.max(mx, sx);
        }
        rect[i] = [mn, mx];
      });
      const cols = {};
      labels.forEach(l => {
        v3.copy(l.pos); v3.x += figs[l.fi].position.x; v3.project(camera);
        l.ax = (v3.x + 1) / 2 * W; l.ay = (1 - v3.y) / 2 * H; l.vis = v3.z < 1 && figs[l.fi].visible;
        const r = rect[l.fi] || [0, W];
        const edge = l.side < 0 ? Math.min(r[0] - 10, l.ax - 40) : Math.max(r[1] + 10, l.ax + 40);
        l.x = l.side < 0 ? Math.max(6, edge - l.w) : Math.min(W - l.w - 6, edge);
        const col = `${l.fi}:${l.side}`; (cols[col] ||= []).push(l);
      });
      // stack each column without overlaps, keeping each callout near its point
      Object.values(cols).forEach(col => {
        col.sort((a, b) => a.ay - b.ay);
        let y = 84;
        col.forEach(l => { l.y = Math.max(y, l.ay - l.h / 2); y = l.y + l.h + 5; });
        const over = y - 5 - (H - 70);
        if (over > 0) { let lim = H - 70; for (let i = col.length - 1; i >= 0; i--) { const l = col[i]; l.y = Math.min(l.y, lim - l.h); lim = l.y - 5; } }
      });
      let svg = '';
      labels.forEach(l => {
        l.el.style.transform = `translate(${l.x.toFixed(1)}px, ${l.y.toFixed(1)}px)`;
        l.el.style.opacity = l.vis ? 1 : 0;
        if (!l.vis) return;
        const lx = l.side < 0 ? l.x + l.w : l.x, ly = l.y + Math.min(l.h / 2, 11);
        const hot = l.el.classList.contains('lv3') ? '#ff6b6b' : l.el.classList.contains('lv2') ? '#ffb547' : 'rgba(220,236,246,.75)';
        svg += `<polyline points="${lx.toFixed(1)},${ly.toFixed(1)} ${(lx + l.side * -0).toFixed(1)},${ly.toFixed(1)} ${l.ax.toFixed(1)},${l.ay.toFixed(1)}" fill="none" stroke="${hot}" stroke-width="1"/><circle cx="${l.ax.toFixed(1)}" cy="${l.ay.toFixed(1)}" r="2.6" fill="${hot}"/>`;
      });
      linesEl.innerHTML = svg;
    }

    /* ---------------- hover names and click to focus */
    const ray = new T.Raycaster(), mouse = new T.Vector2();
    let downAt = null;
    const pick = ev => {
      const r = canvas.getBoundingClientRect();
      mouse.set((ev.clientX - r.left) / r.width * 2 - 1, -(ev.clientY - r.top) / r.height * 2 + 1);
      ray.setFromCamera(mouse, camera);
      const objs = [];
      figs.forEach(f => { if (f.visible) f.traverse(o => { if ((o.isMesh || o.isInstancedMesh) && o.visible && o.userData.name && o.material !== M.glass && !(o.material && o.material.opacity < .4)) objs.push(o); }); });
      const hits = ray.intersectObjects(objs, false).filter(h => { let o = h.object; while (o) { if (!o.visible) return false; o = o.parent; } return true; });
      if (!hits.length) return null;
      const h = hits[0], o = h.object;
      let name = o.userData.name;
      if (o.userData.muscle && h.face) { const mi = o.geometry.userData.muscleIndex[h.face.a]; name = (o.geometry.userData.names[mi] || 'Muscle'); }
      return {name, anchor: o.userData.anchor, organ: o.userData.organ};
    };
    canvas.addEventListener('pointermove', ev => {
      if (ev.buttons) { tip.hidden = true; return; }
      const h = pick(ev);
      if (!h) { tip.hidden = true; canvas.style.cursor = ''; return; }
      const g = groups.find(x => x.anchor === h.anchor);
      tip.innerHTML = `<b>${esc(h.name)}</b>${g ? `<span>${g.items.slice(0, 3).map(it => `${esc(it.name)} ${esc(fmt(it))} ${arrow(it.flag)}`).join('<br>')}${g.items.length > 3 ? `<br>+${g.items.length - 3} more` : ''}</span>` : ''}`;
      const r = stage.getBoundingClientRect();
      tip.style.transform = `translate(${Math.min(ev.clientX - r.left + 14, r.width - 240)}px, ${ev.clientY - r.top + 14}px)`; tip.hidden = false; canvas.style.cursor = g ? 'pointer' : '';
    });
    canvas.addEventListener('pointerleave', () => { tip.hidden = true; });
    canvas.addEventListener('pointerdown', ev => { downAt = [ev.clientX, ev.clientY]; });
    canvas.addEventListener('pointerup', ev => {
      if (!downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 5) return;
      const h = pick(ev);
      if (h && groups.some(g => g.anchor === h.anchor)) focusAnchor(h.anchor);
    });

    /* ---------------- toolbar */
    $$('[data-preset]').forEach(b => b.addEventListener('click', () => applyPreset(b.dataset.preset)));
    $$('[data-labels]').forEach(b => b.addEventListener('click', () => { state.labels = b.dataset.labels; $$('[data-labels]').forEach(x => x.classList.toggle('on', x === b)); frame(false); buildLabels(); }));
    $$('[data-tone]').forEach(b => b.addEventListener('click', () => { state.tone = b.dataset.tone; M.skin.color.copy(skinColor(T, state.tone, F)); $$('[data-tone]').forEach(x => x.classList.toggle('on', x === b)); }));
    $('[data-act=spin]').addEventListener('click', ev => { state.spin = !state.spin; ev.currentTarget.classList.toggle('on', state.spin); });
    $('[data-act=expand]').addEventListener('click', ev => { state.expand = !state.expand; ev.currentTarget.classList.toggle('on', state.expand); buildLabels(); });
    $('[data-act=reset]').addEventListener('click', () => { state.focus = null; renderSide(); dial.value = 0; zoom.value = 0; figs.forEach(f => { f.rotation.y = 0; }); frame(false); buildLabels(); });
    $('.b3-side').addEventListener('click', ev => {
      const a = ev.target.closest('[data-anchor]'); if (a) focusAnchor(a.dataset.anchor);
      if (ev.target.closest('[data-act=all]')) focusAnchor(null);
    });
    const dial = $('.b3-dial input'), zoom = $('.b3-zoom');
    dial.addEventListener('input', () => { const a = dial.value * Math.PI / 180; figs.forEach(f => { f.rotation.y = a; }); });
    zoom.addEventListener('input', () => {
      const d = baseDist * (1 - zoom.value / 100 * .7), dir = camera.position.clone().sub(controls.target).normalize();
      camera.position.copy(controls.target).addScaledVector(dir, d);
    });
    const onKey = ev => { if (ev.key === 'Escape' && root.contains(document.activeElement || document.body) && state.focus) { focusAnchor(null); } };
    document.addEventListener('keydown', onKey);
    $(`[data-labels=${state.labels}]`).classList.add('on');
    $(`[data-tone="${state.tone}"]`).classList.add('on');

    /* ---------------- size */
    function resize() {
      const w = stage.clientWidth, h = stage.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
      labels.forEach(l => { l.w = l.el.offsetWidth; l.h = l.el.offsetHeight; });
    }
    ro = new ResizeObserver(() => { resize(); });
    ro.observe(stage);
    resize();
    applyPreset(state.preset);
    $('.b3-msg').remove();

    /* ---------------- animation: beat at the heart rate, breathe at the respiratory rate */
    const heartMeshes = [], lungMeshes = [], spleenMeshes = [];
    figs.forEach(f => organMeshes(f).forEach(m => {
      if (m.userData.organ === 'heart') heartMeshes.push(m);
      if (m.userData.organ === 'lungR' || m.userData.organ === 'lungL') lungMeshes.push(m);
      if (m.userData.organ === 'spleen') spleenMeshes.push(m);
    }));
    const heartC = new T.Vector3(.022, 1.25, .048), lungC = {lungR: new T.Vector3(-.075, 1.28, 0), lungL: new T.Vector3(.075, 1.28, 0)}, spleenC = new T.Vector3(.112, 1.13, -.025);
    const scaleAbout = (m, c, sx, sy, sz) => { m.scale.set(sx, sy, sz); m.position.set(c.x * (1 - sx), c.y * (1 - sy), c.z * (1 - sz)); };
    const heartBig = 1 + .14 * (O.big || 0), spleenBig = 1 + .6 * (O.spleen || 0);
    spleenMeshes.forEach(m => scaleAbout(m, spleenC, spleenBig, spleenBig, spleenBig));
    const abnormalOrgans = new Set((F.findings || []).filter(f => f.layer === 'organ' && f.level >= 2).map(f => f.target));
    const orgAnchorOf = Object.fromEntries(ORGAN_LIST.map(([k, , a]) => [k, a]));
    let last = performance.now(), tAll = 0;
    function animate(now) {
      if (!alive) return;
      if (opts.capture) { setTimeout(() => animate(performance.now()), 900); } else raf = requestAnimationFrame(animate);
      const dt = Math.min(.05, (now - last) / 1000); last = now; if (!still) tAll += dt;
      U.uTime.value = tAll;
      // the heart: a quick contraction then relaxation, once per beat
      const bp = (tAll * hr / 60) % 1, beat = still ? 0 : Math.exp(-(((bp - .1) / .06) ** 2)) * .06 + Math.exp(-(((bp - .32) / .07) ** 2)) * .025;
      heartMeshes.forEach(m => scaleAbout(m, heartC, heartBig * (1 - beat), heartBig * (1 - beat * .7), heartBig * (1 - beat)));
      const br = still ? 0 : (Math.sin(tAll * rr / 60 * Math.PI * 2) * .5 + .5) * .045 * (O.hypox ? .55 : 1);
      lungMeshes.forEach(m => scaleAbout(m, lungC[m.userData.organ], 1 + br * .8, 1 + br * .6, 1 + br));
      M.skin.emissiveIntensity = S.fever ? (.05 + .12 * S.fever) * (0.75 + .25 * Math.sin(tAll * 2.2)) : 0;
      // findings glow gently; the organ chosen in the panel glows more
      const focusOn = now < pulseUntil ? pulseAnchor : state.focus;
      Object.entries(orgMat).forEach(([k, m]) => {
        const a = orgAnchorOf[k], ab = abnormalOrgans.has(a === 'kidneys' ? 'kidneys' : a === 'lungs' ? 'lungs' : k === 'heart' ? 'heart' : a);
        const foc = focusOn && a === focusOn;
        m.emissiveIntensity = (ab ? .1 + .08 * Math.sin(tAll * 3) : 0) + (foc ? .22 + .18 * Math.sin(tAll * 6) : 0);
      });
      fxMats.forEach(m => { m.opacity = .6 + .3 * Math.sin(tAll * 4); });
      updateCells(dt);
      if (fly) {
        fly.t = Math.min(1, fly.t + dt / .9); const e = fly.t < .5 ? 2 * fly.t * fly.t : 1 - (-2 * fly.t + 2) ** 2 / 2;
        controls.target.lerpVectors(fly.fromT, fly.toT, e); camera.position.lerpVectors(fly.fromP, fly.toP, e);
        if (fly.t >= 1) fly = null;
      }
      if (state.spin && !still) figs.forEach(f => { f.rotation.y += dt * .35; });
      controls.update();
      renderer.render(scene, camera);
      layoutLabels();
    }
    if (!opts.capture) raf = requestAnimationFrame(animate); else { last = performance.now(); tAll = 1.3; animate(performance.now()); }
    handle.render = () => { renderer.render(scene, camera); layoutLabels(); };
    handle.setPreset = applyPreset;
    handle.setLabels = l => { state.labels = l; frame(true); buildLabels(); };
    handle.focus = focusAnchor;
    return handle;
  }

  /* ================================================================== 7 · tissue cards (canvas), the blood smear counts come from the values */
  function drawTissue(host, F, L, still) {
    const cards = [['blood', 'Blood (from the counts)'], ['muscle', 'Muscle tissue'], ['nerve', 'Nerve tissue'], ['bone', 'Bone tissue']];
    host.innerHTML = cards.map(([k, t]) => `<figure><canvas width="132" height="92" data-tissue="${k}"></canvas><figcaption>${t}</figcaption></figure>`).join('');
    const V = F.vessel || {}, B = F.bone || {};
    const rnd = (i, j) => hash(i * 1.37, j * .71, 5.3);
    const draw = (cv, t) => {
      const g = cv.getContext('2d'), W = cv.width, H = cv.height, k = cv.dataset.tissue;
      g.clearRect(0, 0, W, H);
      if (k === 'blood') {
        g.fillStyle = '#f6e2d6'; g.fillRect(0, 0, W, H);
        const red = Math.round(70 * clamp((L.hb ?? 14) / 14.5, .15, 1.4)), white = Math.round(clamp((L.wbc ?? 7) / 7 * 2, 0, 12)), plt = Math.round(clamp((L.plt ?? 250) / 250 * 10, 0, 40));
        const inf = V.malaria ? clamp(L.dens !== null && L.dens !== undefined ? Math.log10(Math.max(L.dens, 10)) / 6 : .25, .08, .8) : 0;
        for (let i = 0; i < red; i++) {
          const x = (rnd(i, 1) * W + t * 9 * (.5 + rnd(i, 3))) % (W + 10) - 5, y = rnd(i, 2) * H;
          g.fillStyle = V.anaemia > .3 ? '#e9a0a0' : '#cf3b3b'; g.beginPath();
          if (V.sickle && i % 3 === 0) { g.ellipse(x, y, 6, 2.2, rnd(i, 4) * 3, 0, Math.PI * 2); } else g.arc(x, y, 4.2, 0, Math.PI * 2);
          g.fill(); g.fillStyle = 'rgba(255,220,220,.55)'; g.beginPath(); g.arc(x, y, 1.6, 0, Math.PI * 2); g.fill();
          if (rnd(i, 7) < inf) { g.fillStyle = '#6a2bb5'; g.beginPath(); g.arc(x + 1.5, y - 1, 1.1, 0, Math.PI * 2); g.fill(); }
        }
        for (let i = 0; i < white; i++) { const x = (rnd(i, 11) * W + t * 5) % (W + 10) - 5, y = rnd(i, 12) * H; g.fillStyle = '#e8e3f7'; g.beginPath(); g.arc(x, y, 6.5, 0, Math.PI * 2); g.fill(); g.fillStyle = '#5b3fa0'; g.beginPath(); g.arc(x - 1, y, 3.2, 0, Math.PI * 2); g.fill(); }
        for (let i = 0; i < plt; i++) { const x = (rnd(i, 21) * W + t * 11) % W, y = rnd(i, 22) * H; g.fillStyle = '#9a6ad0'; g.fillRect(x, y, 1.6, 1.6); }
      } else if (k === 'muscle') {
        g.fillStyle = '#b8323a'; g.fillRect(0, 0, W, H);
        for (let y = 0; y < H; y += 9) { g.fillStyle = 'rgba(255,190,190,.35)'; g.fillRect(0, y, W, 1.5); for (let x = (y % 18 ? 4 : 0); x < W; x += 5) { g.fillStyle = 'rgba(80,0,10,.35)'; g.fillRect(x, y + 2, 1.2, 6); } }
      } else if (k === 'nerve') {
        g.fillStyle = '#20163a'; g.fillRect(0, 0, W, H);
        const cells = [[30, 30], [95, 55], [60, 75]];
        cells.forEach(([x, y], i) => { for (let a = 0; a < 7; a++) { const an = a / 7 * 6.28 + i; g.strokeStyle = 'rgba(170,140,255,.7)'; g.lineWidth = 1.2; g.beginPath(); g.moveTo(x, y); g.quadraticCurveTo(x + Math.cos(an) * 20, y + Math.sin(an) * 12, x + Math.cos(an + .4) * 36, y + Math.sin(an + .4) * 26); g.stroke(); } });
        g.strokeStyle = '#ffd34a'; g.lineWidth = 2; g.beginPath(); g.moveTo(30, 30); g.bezierCurveTo(60, 20, 70, 70, 95, 55); g.stroke();
        cells.forEach(([x, y]) => { g.fillStyle = '#c9a8ff'; g.beginPath(); g.arc(x, y, 5, 0, 6.28); g.fill(); });
        const s = (t * .8) % 1; g.fillStyle = '#fff6b0'; g.beginPath(); g.arc(30 + 65 * s, 30 + 25 * Math.sin(s * 3.1), 2.6, 0, 6.28); g.fill();
      } else {
        g.fillStyle = B.osteo ? '#d9cdb3' : '#ead9b8'; g.fillRect(0, 0, W, H);
        [[24, 26], [70, 20], [112, 34], [40, 70], [92, 72]].forEach(([x, y]) => {
          for (let r = 18; r > 2; r -= 3) { g.strokeStyle = `rgba(150,110,60,${.25 + (r % 6 ? 0 : .2)})`; g.lineWidth = 1; g.beginPath(); g.arc(x, y, r, 0, 6.28); g.stroke(); }
          g.fillStyle = '#5a3a1c'; g.beginPath(); g.arc(x, y, 2.4, 0, 6.28); g.fill();
        });
        if (B.osteo) for (let i = 0; i < 26; i++) { g.fillStyle = 'rgba(255,255,255,.7)'; g.beginPath(); g.arc(rnd(i, 31) * W, rnd(i, 32) * H, 2 + rnd(i, 33) * 3, 0, 6.28); g.fill(); }
      }
    };
    const cvs = [...host.querySelectorAll('canvas')];
    let t0 = performance.now();
    const loop = now => { if (!host.isConnected) return; const t = (now - t0) / 1000; cvs.forEach(c => draw(c, t)); if (!still) requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }

  API.mount = mount;
  API._dev = {bounds, surface, field, buildGeometry, bodyShapes, muscleShapes, skullShapes, mandibleShapes, axialShapes, limbShapes, vertebraShapes, organShapes};
})();
