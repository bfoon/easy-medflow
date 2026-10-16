/* 3D Organ Lab: rotatable, lit organs built in code (no downloads) with wet-tissue materials, like a game viewer.
   Heart, lungs, liver, kidneys, brain, stomach and spleen. The patient's results change them, as on the anatomy:
   a damaged heart wall, pneumonia in a lung, an inflamed or yellow liver, failing kidneys, a swollen brain, an
   enlarged spleen. Glowing pins mark the findings. Drag to rotate, scroll to zoom (limited, so it never gets stuck
   enlarged), "Cut open" slices through the organ, Escape closes. three.js is vendored (window.MF_THREE).
   MFOrgans3D.open(organKey, anatomyFindings, {onClose}) — used by anatomy-real.js. Teaching illustration only. */
(() => {
  'use strict';
  const CFG = window.MF_THREE;
  const webgl = (() => { try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch (e) { return false; } })();
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

  /* ---------------------------------------------------------------- value noise (deterministic) */
  const hash = (x, y, z) => { const s = Math.sin(x * 127.1 + y * 311.7 + z * 74.7) * 43758.5453; return s - Math.floor(s); };
  function noise(x, y, z) {
    const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z), xf = x - xi, yf = y - yi, zf = z - zi;
    const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf), w = zf * zf * (3 - 2 * zf);
    const L = (a, b, t) => a + (b - a) * t;
    const c = (dx, dy, dz) => hash(xi + dx, yi + dy, zi + dz);
    return L(L(L(c(0, 0, 0), c(1, 0, 0), u), L(c(0, 1, 0), c(1, 1, 0), u), v), L(L(c(0, 0, 1), c(1, 0, 1), u), L(c(0, 1, 1), c(1, 1, 1), u), v), w) * 2 - 1;
  }
  const fbm = (x, y, z, o = 4) => { let a = 0, f = 1, s = .5; for (let i = 0; i < o; i++) { a += s * noise(x * f, y * f, z * f); f *= 2.03; s *= .5; } return a; };

  /* ---------------------------------------------------------------- what to draw, from the anatomy findings */
  const ORGANS = {
    heart: {label: 'Heart', sys: 'vessel', blurb: 'Pumps blood: the right side to the lungs, the left side to the body. The coronary arteries on its surface feed the heart muscle itself.'},
    lungs: {label: 'Lungs', sys: 'resp', blurb: 'Spongy organs where oxygen enters the blood. Air reaches millions of tiny air sacs through the branching bronchi.'},
    liver: {label: 'Liver', sys: 'digest', blurb: 'The largest internal organ: it clears bilirubin and toxins, makes proteins such as albumin, and stores energy. The gallbladder sits underneath.'},
    kidneys: {label: 'Kidneys', sys: 'uro', blurb: 'Two bean-shaped filters that clean the blood, balance salts and water, and make urine that flows down the ureters.'},
    brain: {label: 'Brain', sys: 'nerve', blurb: 'The folded cerebral cortex thinks and feels; the cerebellum at the back coordinates movement; the brainstem keeps you breathing.'},
    stomach: {label: 'Stomach', sys: 'digest', blurb: 'A muscular J-shaped bag that churns food with acid before passing it to the small intestine.'},
    spleen: {label: 'Spleen', sys: 'lymph', blurb: 'Filters the blood, removes old and infected red cells, and helps fight infection. It swells in malaria.'},
  };
  const TARGET_OF = {heart: ['heart'], lungs: ['lungs'], liver: ['liver'], kidneys: ['kidneys'], brain: ['brain'], stomach: ['stomach'], spleen: ['spleen']};
  function stateFor(key, F) {
    const fs = (F.findings || []).filter(f => (TARGET_OF[key] || []).includes(f.target));
    return {fs, O: F.organ || {}, skin: F.skin || {}, hr: F.hr || 72, rr: F.rr || 14};
  }

  /* ---------------------------------------------------------------- the viewer */
  let open = null;
  async function show(key, F, opts = {}) {
    F = F || {findings: [], organ: {}};
    if (open) open.close();
    const overlay = document.createElement('div');
    overlay.className = 'o3-modal';
    overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-label', '3D organ viewer');
    overlay.innerHTML = `<div class="o3-box">
      <div class="o3-head"><div class="o3-tabs" role="tablist">${Object.entries(ORGANS).map(([k, o]) => `<button type="button" role="tab" data-organ="${k}">${o.label}</button>`).join('')}</div>
        <button type="button" class="o3-x" aria-label="Close 3D viewer">×</button></div>
      <div class="o3-stage"><canvas class="o3-canvas"></canvas><div class="o3-pins"></div><div class="o3-msg">Loading 3D…</div>
        <div class="o3-tools">
          <button type="button" data-o3="spin" class="on" title="Turn slowly"><i class="bi bi-arrow-repeat"></i>Auto-rotate</button>
          <label class="o3-cut" title="Slice through the organ"><i class="bi bi-scissors"></i>Cut open<input type="range" min="0" max="100" value="0" aria-label="Cut open"></label>
          <button type="button" data-o3="reset" title="Back to the starting view"><i class="bi bi-bullseye"></i>Reset view</button>
        </div>
        <p class="o3-help">Drag to turn · scroll or pinch to zoom · right-drag to move · Esc to close</p></div>
      <aside class="o3-side"></aside></div>`;
    document.body.appendChild(overlay);
    document.body.classList.add('o3-open');
    const prevFocus = document.activeElement;
    const $ = s => overlay.querySelector(s);
    let alive = true, raf = 0, renderer = null, controls = null, scene = null, camera = null, group = null, pins = [], clip = null, animate = () => {};
    const disposables = [];
    const close = () => {
      if (!alive) return; alive = false;
      cancelAnimationFrame(raf); document.removeEventListener('keydown', onKey); ro && ro.disconnect();
      disposables.forEach(d => { try { d.dispose(); } catch (e) { /* gone */ } });
      if (renderer) { renderer.dispose(); renderer.forceContextLoss && renderer.forceContextLoss(); }
      overlay.remove(); document.body.classList.remove('o3-open'); open = null;
      if (prevFocus && prevFocus.focus) prevFocus.focus();
      if (opts.onClose) opts.onClose();
    };
    const onKey = ev => { if (ev.key === 'Escape') { ev.preventDefault(); close(); } };
    document.addEventListener('keydown', onKey);
    overlay.addEventListener('click', ev => { if (ev.target === overlay) close(); });
    $('.o3-x').addEventListener('click', close);
    open = {close};
    let ro = null;
    $('.o3-x').focus();

    if (!webgl || !CFG) { $('.o3-msg').textContent = 'This browser cannot show 3D. The anatomy view shows the same findings.'; return open; }
    let T, OrbitControls, RoomEnvironment;
    try {
      T = await import(CFG.three);
      ({OrbitControls} = await import(CFG.controls));
      ({RoomEnvironment} = await import(CFG.room));
    } catch (e) { $('.o3-msg').textContent = '3D could not be loaded.'; return open; }
    if (!alive) return open;

    const canvas = $('.o3-canvas'), stage = $('.o3-stage');
    renderer = new T.WebGLRenderer({canvas, antialias: true, alpha: true, powerPreference: 'high-performance'});
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    const gl = renderer.getContext(), dbg = gl.getExtension('WEBGL_debug_renderer_info');
    const softwareGL = /swiftshader|llvmpipe|software|basic render/i.test(dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : '');
    if (softwareGL && !window.MF_O3_HQ) renderer.setPixelRatio(.6);
    renderer.outputColorSpace = T.SRGBColorSpace;
    renderer.toneMapping = T.ACESFilmicToneMapping; renderer.toneMappingExposure = .82;
    renderer.localClippingEnabled = true;
    let quality = 3, slow = 0, lastT = performance.now(), skip = 0, frames = 0;     // adaptive quality (see adapt below)
    scene = new T.Scene();
    const pmrem = new T.PMREMGenerator(renderer);
    const envTex = softwareGL && !window.MF_O3_HQ ? null : pmrem.fromScene(new RoomEnvironment(renderer), .04).texture;
    scene.environment = envTex; disposables.push(pmrem); if (envTex) disposables.push(envTex);
    camera = new T.PerspectiveCamera(32, 1, .05, 50);
    controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true; controls.dampingFactor = .08;
    controls.minDistance = 2.2; controls.maxDistance = 9;          // zoom is limited both ways
    controls.autoRotate = !still; controls.autoRotateSpeed = .9;
    controls.addEventListener('start', () => { controls.autoRotate = false; $('[data-o3=spin]').classList.remove('on'); });
    const keyLight = new T.DirectionalLight('#fff4ea', 1.7); keyLight.position.set(3, 4, 5); scene.add(keyLight);
    const rim = new T.DirectionalLight('#9fd8ff', 1.4); rim.position.set(-4, 2, -4); scene.add(rim);
    scene.add(new T.HemisphereLight('#ffffff', '#3a1f24', .35));
    // a soft shadow under the organ
    const sh = document.createElement('canvas'); sh.width = sh.height = 128;
    const sg = sh.getContext('2d'), grd = sg.createRadialGradient(64, 64, 4, 64, 64, 62); grd.addColorStop(0, 'rgba(0,0,0,.55)'); grd.addColorStop(1, 'rgba(0,0,0,0)'); sg.fillStyle = grd; sg.fillRect(0, 0, 128, 128);
    const shTex = new T.CanvasTexture(sh); disposables.push(shTex);
    const shadow = new T.Mesh(new T.PlaneGeometry(3.2, 3.2), new T.MeshBasicMaterial({map: shTex, transparent: true, depthWrite: false}));
    shadow.rotation.x = -Math.PI / 2; shadow.position.y = -1.35; scene.add(shadow); disposables.push(shadow.geometry, shadow.material);
    clip = new T.Plane(new T.Vector3(0, 0, -1), 5);

    /* textures made in code: a height field turned into a normal map */
    function normalMap(heightFn, size = 256, strength = 2.2) {
      const c = document.createElement('canvas'); c.width = c.height = size;
      const g = c.getContext('2d'), img = g.createImageData(size, size), H = new Float32Array(size * size);
      for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) H[y * size + x] = heightFn(x / size, y / size);
      const at = (x, y) => H[((y + size) % size) * size + ((x + size) % size)];
      for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
        const dx = (at(x + 1, y) - at(x - 1, y)) * strength, dy = (at(x, y + 1) - at(x, y - 1)) * strength;
        const len = Math.hypot(dx, dy, 1), i = (y * size + x) * 4;
        img.data[i] = (-dx / len * .5 + .5) * 255; img.data[i + 1] = (-dy / len * .5 + .5) * 255; img.data[i + 2] = (1 / len * .5 + .5) * 255; img.data[i + 3] = 255;
      }
      g.putImageData(img, 0, 0);
      const t = new T.CanvasTexture(c); t.wrapS = t.wrapT = T.RepeatWrapping; disposables.push(t); return t;
    }
    const tile = (u, v, f) => fbm(Math.cos(u * 6.2832) * f, Math.sin(u * 6.2832) * f, v * f * 6.2832 / 2);   // wraps left-right
    const texCache = {};
    const TEX0 = {
      fine: () => normalMap((u, v) => tile(u, v, 6) * .5 + tile(u, v, 18) * .25),
      alveoli: () => normalMap((u, v) => { const a = Math.sin(u * 220) * Math.sin(v * 220); return (1 - Math.abs(a)) * .6 + tile(u, v, 10) * .2; }, 256, 1.6),
      rugae: () => normalMap((u, v) => Math.sin(v * 60 + tile(u, v, 4) * 4) * .5 + tile(u, v, 12) * .2, 256, 2.6),
    };
    const TEX = Object.fromEntries(Object.keys(TEX0).map(k => [k, () => texCache[k] || (texCache[k] = TEX0[k]())]));
    const mat = (o, nm) => {
      const m = new T.MeshPhysicalMaterial(Object.assign({color: '#ffffff', roughness: .42, clearcoat: .7, clearcoatRoughness: .25, sheen: .12, sheenColor: new T.Color('#7a2a24'), envMapIntensity: .55,
        normalMap: nm || null, normalScale: new T.Vector2(.5, .5), clippingPlanes: [clip], clipShadows: true, side: T.FrontSide, vertexColors: true}, o));
      disposables.push(m); return m;
    };
    /* an organic shape: a sphere pushed in and out by a shape function; colour per vertex for lesions */
    function organic(shape, paint, seg = 140) {
      const g = new T.SphereGeometry(1, Math.round(seg * .8), Math.round(seg * .56));
      const p = g.attributes.position, col = new Float32Array(p.count * 3), v = new T.Vector3();
      for (let i = 0; i < p.count; i++) {
        v.fromBufferAttribute(p, i);
        const d = v.clone().normalize(), out = shape(d);
        p.setXYZ(i, out.x, out.y, out.z);
        const c = paint(d, out); col[i * 3] = c[0]; col[i * 3 + 1] = c[1]; col[i * 3 + 2] = c[2];
      }
      g.setAttribute('color', new T.BufferAttribute(col, 3));
      g.computeVertexNormals(); disposables.push(g); return g;
    }
    const rgb = h => { const c = new T.Color(h); return [c.r, c.g, c.b]; };
    const mixc = (a, b, t) => a.map((x, i) => x + (b[i] - x) * clamp(t, 0, 1));
    const tubeAlong = (pts, r, color, extra = {}) => {
      const curve = new T.CatmullRomCurve3(pts.map(q => new T.Vector3(...q)));
      const g = new T.TubeGeometry(curve, 64, r, 16, false); disposables.push(g);
      const n = g.attributes.position.count, cc = new Float32Array(n * 3).fill(1); g.setAttribute('color', new T.BufferAttribute(cc, 3));
      return new T.Mesh(g, mat(Object.assign({color}, extra), null));
    };
    const sphereAt = (pos, scale, color, nm) => { const m = new T.Mesh(organic(d => d.clone().multiply(new T.Vector3(...scale)), () => [1, 1, 1], 48), mat({color}, nm)); m.position.set(...pos); return m; };

    /* ------------------------------------------------------------ the organs */
    function build(key) {
      const st = stateFor(key, F), O = st.O, g = new T.Group(), P = [];       // P: pins [{pos, level, title}]
      const pinFor = (pos, sel) => st.fs.filter(sel || (() => true)).slice(0, 1).forEach(f => P.push({pos, level: f.level, title: f.title}));
      animate = () => {};
      if (key === 'heart') {
        const big = 1 + (O.big || 0) * .18, inf = O.infarct || 0;
        const base = rgb('#a3282a'), dead = rgb('#3d1630'), fat = rgb('#e8cf7a');
        const geo = organic(d => {
          let r = 1 + .08 * fbm(d.x * 2, d.y * 2, d.z * 2);
          const apex = smooth(.1, -1, d.y);                                         // narrows to the apex below
          const v = new T.Vector3(d.x * (1 - apex * .45), d.y * 1.15, d.z * (1 - apex * .5) * .85);
          return v.multiplyScalar(r * .95 * big);
        }, d => {
          let c = base;
          const groove = Math.exp(-Math.pow((d.x * .8 + d.y * .3 + .05) * 7, 2));            // the fatty groove between the ventricles
          c = mixc(c, fat, groove * .55);
          if (inf) c = mixc(c, dead, inf * smooth(.55, .9, d.z) * smooth(-.6, .2, -d.y) * smooth(-.2, .5, d.x));
          return c;
        });
        const heart = new T.Mesh(geo, mat({}, TEX.fine())); heart.rotation.z = -.45; g.add(heart);
        g.add(tubeAlong([[-.15, .7, 0], [-.2, 1.25, -.05], [.15, 1.55, -.15], [.55, 1.35, -.25], [.6, .8, -.35]], .17, '#b3262a'));     // aorta
        g.add(tubeAlong([[.15, .6, .3], [.3, 1.15, .25], [.55, 1.3, .05]], .15, '#3f55a8'));                                           // pulmonary trunk
        g.add(tubeAlong([[-.05, .62, .82], [.12, .2, .97], [.22, -.35, .88], [.12, -.8, .55]], .035, '#c3232b'));                      // coronary artery
        g.add(tubeAlong([[-.65, .45, .55], [-.85, 0, .45], [-.65, -.5, .35]], .03, '#c3232b'));
        pinFor([.25, -.2, .95]);
        g.position.y = -.15;
        const per = 60 / clamp(st.hr, 30, 200);
        animate = t => { const ph = (t % per) / per, beat = ph < .15 ? Math.sin(ph / .15 * Math.PI) : 0; heart.scale.setScalar(1 + beat * .05); };
      } else if (key === 'lungs') {
        const hy = O.hypox || 0, pink = mixc(rgb('#e39a9b'), rgb('#8e80b8'), hy), patch = rgb('#efe3cf');
        [-1, 1].forEach(s => {
          const geo = organic(d => {
            const v = new T.Vector3(d.x * .55, d.y * 1.05, d.z * .5);
            if (d.x * s < 0) v.x *= .45;                                                   // flat inner side facing the heart
            if (d.y > .55) { const k = 1 - (d.y - .55) * .9; v.x *= k; v.z *= k; }          // narrow apex
            if (d.y < -.7) v.y += (1 - Math.hypot(d.x, d.z)) * .25;                          // hollow base sitting on the diaphragm
            if (s > 0 && d.x < 0 && d.z > 0 && d.y < .1 && d.y > -.6) v.x *= .55;              // notch for the heart (left lung)
            return v.multiplyScalar(1 + .025 * fbm(d.x * 4, d.y * 4, d.z * 4));
          }, d => {
            let c = pink;
            const fissure = Math.exp(-Math.pow((d.y + d.x * s * .35 + .05) * 18, 2)); c = mixc(c, rgb('#7d3440'), fissure * .6);
            if (O.consolid && s < 0) c = mixc(c, patch, smooth(-.15, -.55, d.y) * .85);
            if (O.congest) c = mixc(c, rgb('#9fb6d8'), .25);
            return c;
          });
          const m = new T.Mesh(geo, mat({roughness: .55, clearcoat: .55, sheen: .6}, TEX.alveoli())); m.position.x = s * .62; g.add(m);
        });
        g.add(tubeAlong([[0, 1.5, 0], [0, .95, 0], [0, .6, .02]], .1, '#dcd0c0'));                                   // trachea
        [-1, 1].forEach(s => g.add(tubeAlong([[0, .62, .02], [s * .22, .45, .02], [s * .45, .2, .05]], .065, '#dcd0c0')));
        pinFor(O.consolid ? [-.62, -.55, .4] : [-.62, .1, .48]);
        animate = t => { const b = (Math.sin(t * Math.PI * 2 * st.rr / 60) + 1) / 2; g.scale.set(1 + b * .03, 1 + b * .045, 1 + b * .03); };
      } else if (key === 'liver') {
        const inf = O.liver || 0, yel = O.yellow || 0;
        const col = mixc(mixc(rgb('#7c2a1c'), rgb('#b8352a'), inf), rgb('#8a7a26'), yel * .7);
        const geo = organic(d => {
          const right = smooth(.6, -.6, d.x);                                               // the big right lobe (viewer's left)
          const v = new T.Vector3(d.x * 1.25, d.y * (.35 + .45 * right), d.z * (.45 + .3 * right));
          if (d.y < 0) v.y *= .55;                                                          // flatter underside
          return v.multiplyScalar((1 + inf * .08) * (1 + .03 * fbm(d.x * 3, d.y * 3, d.z * 3)));
        }, d => mixc(col, rgb('#4f1a12'), smooth(.2, -.8, d.y) * .25));
        g.add(new T.Mesh(geo, mat({roughness: .32, clearcoat: 1}, TEX.fine())));
        g.add(sphereAt([-.35, -.38, .28], [.14, .26, .14], '#4f8a3c'));                        // gallbladder
        pinFor([-.4, .3, .5]);
      } else if (key === 'kidneys') {
        const hurt = O.kidneys || 0, col = mixc(rgb('#8a2f2a'), rgb('#6e5a55'), hurt), sc = 1 - hurt * .12;
        [-1, 1].forEach(s => {
          const geo = organic(d => {
            const v = new T.Vector3(d.x * .42, d.y * .82, d.z * .3);
            if (d.x * s < 0) v.x -= s * .22 * Math.exp(-d.y * d.y * 9) * (-d.x * s);   // the hilum: the dent where vessels enter
            return v.multiplyScalar(sc * (1 + .02 * fbm(d.x * 5, d.y * 5, d.z * 5)));
          }, () => col);
          const k = new T.Mesh(geo, mat({roughness: .35, clearcoat: 1}, TEX.fine())); k.position.x = s * .75; g.add(k);
          g.add(sphereAt([s * .72, .82, 0], [.2, .1, .14], '#d7a05a'));                       // adrenal gland
          g.add(tubeAlong([[s * .55, 0, 0], [s * .3, -.4, .05], [s * .22, -1.25, .05]], .035, '#e8cfa8'));     // ureter
          g.add(tubeAlong([[s * .52, .08, .05], [s * .25, .1, .08], [0, .12, .08]], .045, '#c0282d'));         // renal artery
          g.add(tubeAlong([[s * .52, -.05, .1], [s * .25, -.06, .14], [0, -.06, .14]], .05, '#3a52a8'));          // renal vein
        });
        g.add(tubeAlong([[0, 1.1, -.05], [0, -1.2, -.05]], .1, '#b3262a'));                                      // aorta
        g.add(tubeAlong([[.1, 1.1, .15], [.1, -1.2, .15]], .11, '#33489a'));                                     // vena cava
        pinFor([.75, 0, .3]);
      } else if (key === 'brain') {
        const sw = O.brain ? .08 : 0, col = O.brain ? rgb('#e9a8a2') : rgb('#e2b6ad');
        [-1, 1].forEach(s => {
          const geo = organic(d => {
            const v = new T.Vector3(d.x * .62, d.y * .7, d.z * 1.05);
            if (d.x * s < 0) v.x *= .25;                                                      // the flat face between the halves
            if (d.y < -.2 && d.z > .2) v.y *= .8;
            const gyri = 1 - Math.abs(fbm(d.x * 5.5, d.y * 5.5, d.z * 5.5, 3));                 // ridges and grooves of the cortex
            return v.multiplyScalar((1 + sw) * (1 + .055 * gyri));
          }, d => { const gyri = 1 - Math.abs(fbm(d.x * 5.5, d.y * 5.5, d.z * 5.5, 3)); return mixc(rgb('#b98278'), col, smooth(.55, .8, gyri)); }, 180);
          const m = new T.Mesh(geo, mat({roughness: .5, clearcoat: .6}, TEX.fine())); m.position.x = s * .19; g.add(m);
        });
        const cb = organic(d => new T.Vector3(d.x * .62, d.y * .32, d.z * .42), d => mixc(rgb('#c89088'), rgb('#e6bdb4'), (Math.sin(d.y * 60) + 1) / 2));
        const cer = new T.Mesh(cb, mat({roughness: .5}, null)); cer.position.set(0, -.55, -.6); g.add(cer);
        g.add(tubeAlong([[0, -.2, -.15], [0, -.75, -.3], [0, -1.25, -.35]], .16, '#d9aaa0'));                     // brainstem
        pinFor([.4, .5, .6]);
        g.rotation.y = -.75;                                                                // a three-quarter view from the side
      } else if (key === 'stomach') {
        const path = new T.CatmullRomCurve3([[-.55, .9, 0], [-.2, 1.0, 0], [.35, .7, 0], [.5, .1, .05], [.25, -.55, .05], [-.35, -.75, 0], [-.85, -.45, 0]].map(q => new T.Vector3(...q)));
        const seg = 96, rad = 20, geo = new T.TubeGeometry(path, seg, 1, rad, false); disposables.push(geo);
        const p = geo.attributes.position, c = new T.Vector3(), q = new T.Vector3();
        const R = t => .18 + .32 * Math.exp(-Math.pow((t - .22) * 3.2, 2)) + .12 * smooth(.9, .55, t);            // wide fundus and body, narrow pylorus
        for (let i = 0; i <= seg; i++) {
          const t = i / seg; path.getPointAt(t, c);
          for (let j = 0; j <= rad; j++) { const k = i * (rad + 1) + j; q.fromBufferAttribute(p, k).sub(c).multiplyScalar(R(t)); p.setXYZ(k, c.x + q.x, c.y + q.y, c.z + q.z); }
        }
        geo.setAttribute('color', new T.BufferAttribute(new Float32Array(p.count * 3).fill(1), 3));
        geo.computeVertexNormals();
        g.add(new T.Mesh(geo, mat({color: '#d9a09a', roughness: .45}, TEX.rugae())));
        g.add(tubeAlong([[-.45, 1.6, -.05], [-.5, 1.2, 0], [-.55, .95, 0]], .09, '#d49a8f'));                     // oesophagus
        pinFor([.4, .3, .4]);
      } else if (key === 'spleen') {
        const big = 1 + (O.spleen || 0) * .5;
        const geo = organic(d => {
          const v = new T.Vector3(d.x * .45, d.y * .9, d.z * .3);
          if (d.x < 0) v.x -= .12 * Math.exp(-d.y * d.y * 6) * -d.x;                          // the inner, hollow face
          return v.multiplyScalar(big * (1 + .03 * fbm(d.x * 4, d.y * 4, d.z * 4)));
        }, () => rgb('#6e2a3c'));
        const m = new T.Mesh(geo, mat({roughness: .38, clearcoat: 1}, TEX.fine())); m.rotation.z = -.35; g.add(m);
        pinFor([.3, 0, .35]);
      }
      return {g, P, st};
    }

    /* ------------------------------------------------------------ show an organ */
    function setOrgan(k) {
      if (group) { scene.remove(group); }
      const b = build(k); group = b.g; scene.add(group);
      // the inside of every part: dark, matte cut tissue, seen only where "Cut open" slices through
      const inner = new T.MeshStandardMaterial({color: '#4a1012', roughness: .85, side: T.BackSide, clippingPlanes: [clip]}); disposables.push(inner);
      const insides = [];
      group.traverse(o => { if (o.isMesh) insides.push(o); });
      insides.forEach(o => { const m = new T.Mesh(o.geometry, inner); o.add(m); });
      if (quality === 0) cheap();
      overlay.querySelectorAll('[data-organ]').forEach(x => x.setAttribute('aria-selected', x.dataset.organ === k));
      const o = ORGANS[k];
      $('.o3-side').innerHTML = `<h3>${o.label}</h3><p>${esc(o.blurb)}</p>
        ${b.st.fs.length ? b.st.fs.map(f => `<div class="o3-find lv${f.level}"><b>${esc(f.title)}</b><span>${esc(f.text)}</span></div>`).join('') : '<p class="o3-ok"><i class="bi bi-check-circle"></i>Nothing abnormal recorded for this organ.</p>'}
        <p class="o3-note">Built from this patient's results. A teaching illustration, not a scan.</p>`;
      $('.o3-pins').innerHTML = b.P.map((p, i) => `<div class="o3-pin lv${p.level}" data-i="${i}"><i></i><span>${esc(p.title)}</span></div>`).join('');
      pins = b.P.map((p, i) => ({v: new T.Vector3(...p.pos), el: $(`.o3-pin[data-i="${i}"]`)}));
      resetView(); $('.o3-cut input').value = 0; cutV = 0;
    }
    let fitDist = 5.2, cutV = 0, cutR = 1.5;
    const cutC = new T.Vector3();
    function fitView() {                                       // the whole organ always fits, whatever its size
      const box = new T.Box3().setFromObject(group), sph = box.getBoundingSphere(new T.Sphere());
      const fov = camera.fov * Math.PI / 180, aspect = Math.max(.6, Math.min(camera.aspect || 1, 1.6));
      fitDist = sph.radius / Math.sin(Math.min(fov, fov * aspect) / 2) * 1.08;
      cutC.copy(sph.center); cutR = sph.radius;
      controls.target.copy(sph.center);
      controls.minDistance = fitDist * .45; controls.maxDistance = fitDist * 2.2;
      shadow.position.y = box.min.y - .05;
    }
    function resetView() { fitView(); camera.position.copy(controls.target).add(new T.Vector3(0, fitDist * .08, fitDist)); controls.update(); }
    function resize() { const w = stage.clientWidth, h = stage.clientHeight; if (!w || !h) return; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
    ro = new ResizeObserver(resize); ro.observe(stage); resize();
    overlay.querySelector('.o3-tabs').addEventListener('click', ev => { const b = ev.target.closest('[data-organ]'); if (b) setOrgan(b.dataset.organ); });
    $('[data-o3=reset]').addEventListener('click', () => { resetView(); controls.autoRotate = !still; $('[data-o3=spin]').classList.toggle('on', controls.autoRotate); });
    $('[data-o3=spin]').addEventListener('click', ev => { controls.autoRotate = !controls.autoRotate; ev.currentTarget.classList.toggle('on', controls.autoRotate); });
    $('.o3-cut input').addEventListener('input', ev => { cutV = +ev.target.value / 100; });
    $('.o3-msg').remove();
    setOrgan(ORGANS[key] ? key : 'heart');
    if (softwareGL && !window.MF_O3_HQ) { quality = 0; cheap(); }
    const clock = new T.Clock(), tmp = new T.Vector3();
    function cheap() {                                       // last resort: plain lit materials, no gloss or texture
      scene.traverse(o => {
        if (!o.isMesh || !o.material || !o.material.isMeshPhysicalMaterial) return;
        const m = o.material, l = new T.MeshLambertMaterial({color: m.color, vertexColors: m.vertexColors, side: T.FrontSide, clippingPlanes: m.clippingPlanes, transparent: m.transparent, opacity: m.opacity});
        disposables.push(l); o.material = l;
      });
      scene.environment = null;
    }
    function adapt(dt) {
      frames++;
      if (frames < 3) return;                                // the first frames include building the shaders
      if (window.MF_O3_HQ) return;                         // developer switch: keep full quality (screenshots)
      if (dt > 250 && quality > 0) { quality = 0; renderer.setPixelRatio(.5); cheap(); resize(); return; }   // a very slow machine: go straight to the lightest
      if (dt > 45) slow++; else slow = Math.max(0, slow - 1);
      if (slow < 6 || quality === 0) return;
      slow = 0; quality--;
      if (quality === 2) renderer.setPixelRatio(1);
      if (quality === 1) { renderer.setPixelRatio(.75); disposables.forEach(m => { if (m.isMeshPhysicalMaterial) { m.clearcoat = 0; m.sheen = 0; m.needsUpdate = true; } }); }
      if (quality === 0) { renderer.setPixelRatio(.5); cheap(); }
      resize();
    }
    const frame = () => {
      if (!alive) return;
      raf = requestAnimationFrame(frame);
      if (document.hidden) return;
      const now = performance.now(), dt = now - lastT; lastT = now; adapt(dt);
      if (quality === 0 && (skip = (skip + 1) % 2)) return;           // on the slowest machines draw every other frame
      const t = clock.getElapsedTime();
      animate(t); controls.update();
      clip.normal.set(0, 0, -1).applyQuaternion(camera.quaternion);              // the cut always faces the viewer
      // keep what lies behind a slice that moves from the near surface (0%) to the middle and beyond (100%)
      clip.constant = cutV ? cutR * (1 - 2 * cutV * .85) - clip.normal.dot(cutC) : 1e3;
      renderer.render(scene, camera);
      const w = stage.clientWidth, h = stage.clientHeight;
      pins.forEach(p => {
        tmp.copy(p.v).applyMatrix4(group.matrixWorld).project(camera);
        const vis = tmp.z < 1;
        p.el.style.transform = `translate(${((tmp.x + 1) / 2 * w).toFixed(1)}px,${((1 - tmp.y) / 2 * h).toFixed(1)}px)`;
        p.el.style.opacity = vis ? 1 : 0;
      });
    };
    frame();
    return open;
  }

  window.MFOrgans3D = {open: show, organs: Object.keys(ORGANS), labels: Object.fromEntries(Object.entries(ORGANS).map(([k, o]) => [k, o.label])), available: () => webgl && !!CFG};
})();
