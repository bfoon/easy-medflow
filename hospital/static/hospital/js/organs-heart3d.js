/* Rotatable 3D heart for the lab insights pop-out (three.js, vendored; no network needed).
   Every part is modelled and rendered with physically based, wet-tissue materials: chambers, auricles,
   great vessels, coronary arteries and veins, and the yellow fat that lies in the grooves.
   The patient's results decide what is highlighted, and red or amber pins mark where to look.
   Falls back to the 2D heart (organs-real.js) when WebGL is not available. Teaching illustration only. */
(() => {
  'use strict';
  const ART = window.__MF_ART, CFG = window.MF_THREE;
  if (!ART || !CFG || !ART.heart) return;
  const webgl = (() => { try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch (e) { return false; } })();
  if (!webgl) return;                          // keep the 2D heart
  const svgHeart = ART.heart;
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  /* ------------------------------------------------------------------ what each part does */
  const PARTS = {
    lv: ['Left ventricle', 'The strongest chamber. It pumps oxygen-rich blood to the whole body through the aorta. Raised troponin means some of this muscle is injured.'],
    rv: ['Right ventricle', 'Pumps used blood to the lungs. Raised BNP means the ventricles are stretched and struggling.'],
    ra: ['Right atrium', 'Collects used blood returning from the body through the venae cavae.'],
    la: ['Left atrium', 'Collects oxygen-rich blood returning from the lungs through the pulmonary veins.'],
    rau: ['Right auricle', 'A small ear-shaped pouch of the right atrium.'],
    lau: ['Left auricle', 'A pouch of the left atrium; clots can form here in atrial fibrillation.'],
    aorta: ['Aorta', 'The main artery of the body, arching over the heart and carrying blood from the left ventricle.'],
    arch: ['Arch branches', 'The brachiocephalic, left carotid and left subclavian arteries supply the head and arms.'],
    pt: ['Pulmonary trunk', 'Carries used blood from the right ventricle to both lungs.'],
    pv: ['Pulmonary veins', 'Four veins bringing oxygen-rich blood from the lungs into the left atrium.'],
    svc: ['Superior vena cava', 'Returns blood from the head and arms to the right atrium.'],
    ivc: ['Inferior vena cava', 'Returns blood from the lower body to the right atrium.'],
    lad: ['Left anterior descending artery', 'Runs down the front of the heart and feeds the front wall of the left ventricle. Blockage here causes most anterior heart attacks.'],
    cx: ['Circumflex artery', 'Curves around the left side to feed the side and back of the left ventricle.'],
    rca: ['Right coronary artery', 'Feeds the right ventricle, the back of the heart and usually the SA and AV nodes.'],
    gcv: ['Great cardiac vein', 'Drains used blood from the heart muscle back to the right atrium.'],
    fat: ['Epicardial fat', 'Normal fat that cushions the coronary arteries in the grooves between the chambers.'],
    sa: ['SA node (natural pacemaker)', 'Starts each heartbeat with an electrical signal. Potassium that is too high or too low disturbs this rhythm.'],
    apex: ['Apex', 'The tip of the heart, formed by the left ventricle. You can feel its beat below the left nipple.'],
  };

  function findings(r) {
    const out = [], lvl = (...codes) => codes.some(c => r.crit(c)) ? 'crit' : 'abn';
    const inj = r.abn('TNI') || r.abn('CKMB');
    if (inj) {
      out.push({part: 'lv', level: lvl('TNI', 'CKMB'), title: 'Muscle injury', detail: `Troponin ${r.txt('TNI') || '—'}${r.has('CKMB') ? `, CK-MB ${r.txt('CKMB')}` : ''}: the front wall of the left ventricle is shown injured (dark area).`});
      out.push({part: 'lad', level: lvl('TNI', 'CKMB'), title: 'Likely artery', detail: 'The LAD artery supplies the injured wall. Consider urgent ECG review and angiography.'});
    }
    if (r.abn('BNP')) out.push({part: 'rv', level: lvl('BNP'), title: 'Under strain', detail: `BNP ${r.txt('BNP')}: the ventricles are stretched (shown enlarged). Suggests heart failure.`});
    if (r.abn('K')) out.push({part: 'sa', level: lvl('K'), title: 'Rhythm risk', detail: `Potassium ${r.txt('K')}: disturbs the heart's electrical signal; the beat is shown irregular.`});
    const lip = ['LDL', 'TC', 'TG'].filter(c => r.abn(c)), lowHdl = ['L', 'LL'].includes(r.flag('HDL'));
    if (lip.length || lowHdl) out.push({part: 'rca', level: 'abn', title: 'Plaque risk', detail: `${[...lip.map(c => `${c} ${r.txt(c)}`), lowHdl && `HDL ${r.txt('HDL')}`].filter(Boolean).join(', ')}: cholesterol builds plaque inside the coronary arteries (yellow bumps).`});
    return out;
  }

  ART.heart = r => {
    const base = svgHeart(r), f = findings(r);
    const notes = [...base.notes];
    const plaque = f.find(x => x.part === 'rca');
    if (plaque) notes.push(plaque.detail);
    const parts = Object.fromEntries(Object.entries(PARTS).map(([k, [n, t]]) => [k, `${n}: ${t}`]));
    return {
      svg: `<div class="h3d-wrap"><div class="h3d" tabindex="0" aria-label="3D heart. Drag to rotate, scroll to zoom.">
        <canvas></canvas><div class="h3d-pins"></div>
        <div class="h3d-tools">
          <button type="button" data-h="reset" title="Reset view"><i class="bi bi-arrow-counterclockwise"></i></button>
          <button type="button" data-h="spin" title="Auto-rotate"><i class="bi bi-arrow-repeat"></i></button>
          <button type="button" data-h="back" title="Show the back"><i class="bi bi-arrow-left-right"></i></button>
          <button type="button" data-h="labels" title="Show or hide part labels"><i class="bi bi-tags"></i></button>
          <button type="button" data-h="full" title="Full screen"><i class="bi bi-arrows-fullscreen"></i></button>
        </div>
        <div class="h3d-hint">Drag to rotate · scroll or pinch to zoom · tap a part</div>
        <div class="h3d-loading"><i class="bi bi-heart-pulse"></i> Building 3D heart…</div></div>
        ${f.length ? `<div class="h3d-legend"><b>Needs attention</b>${f.map(x => `<button type="button" class="${x.level}" data-go="${x.part}"><span></span>${esc(PARTS[x.part][0])} <small>${esc(x.title)}</small></button>`).join('')}</div>` : '<div class="h3d-legend ok"><span></span>No heart findings in these results</div>'}</div>`,
      notes, parts,
      mount: (fig, say) => mount(fig, say, r, f, base),
    };
  };

  /* ------------------------------------------------------------------ fallback to the 2D drawing */
  function fallback(fig, say, base) {
    const box = fig.querySelector('.h3d-wrap');
    if (!box) return;
    box.outerHTML = base.svg;
    fig.querySelectorAll('.oa-part').forEach(el => el.addEventListener('click', () => say(base.parts[el.dataset.part] || el.getAttribute('aria-label'))));
  }

  /* ------------------------------------------------------------------ small maths helpers */
  const hash = (x, y, z) => { const s = Math.sin(x * 127.1 + y * 311.7 + z * 74.7) * 43758.5453; return s - Math.floor(s); };
  function noise3(x, y, z) {               // smooth value noise, 0..1
    const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z), xf = x - xi, yf = y - yi, zf = z - zi;
    const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf), w = zf * zf * (3 - 2 * zf);
    const L = (a, b, t) => a + (b - a) * t, h = (i, j, k) => hash(xi + i, yi + j, zi + k);
    return L(L(L(h(0, 0, 0), h(1, 0, 0), u), L(h(0, 1, 0), h(1, 1, 0), u), v), L(L(h(0, 0, 1), h(1, 0, 1), u), L(h(0, 1, 1), h(1, 1, 1), u), v), w);
  }
  const fbm = (x, y, z) => noise3(x, y, z) * .55 + noise3(x * 2.1, y * 2.1, z * 2.1) * .28 + noise3(x * 4.3, y * 4.3, z * 4.3) * .17;

  /* ------------------------------------------------------------------ the scene */
  async function mount(fig, say, r, f, base) {
    const box = fig.querySelector('.h3d');
    if (!box) return;
    let T, OrbitControls, RoomEnvironment;
    try {
      T = await import(CFG.three);
      ({OrbitControls} = await import(CFG.controls));
      ({RoomEnvironment} = await import(CFG.room));
    } catch (e) { console.error('3D heart: could not load three.js', e); return fallback(fig, say, base); }
    if (!box.isConnected) return;

    const canvas = box.querySelector('canvas'), pinBox = box.querySelector('.h3d-pins'), wrap = box.closest('.h3d-wrap') || box;
    let renderer;
    try {
      renderer = new T.WebGLRenderer({canvas, antialias: true, alpha: true, powerPreference: 'high-performance'});
    } catch (e) { return fallback(fig, say, base); }
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    renderer.outputColorSpace = T.SRGBColorSpace;
    renderer.toneMapping = T.ACESFilmicToneMapping;
    renderer.toneMappingExposure = .92;

    const scene = new T.Scene();
    const pmrem = new T.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), .04).texture;   // soft studio reflections give the wet look
    const camera = new T.PerspectiveCamera(30, 1, .1, 60);
    const HOME = new T.Vector3(.7, .7, 8.2), TARGET = new T.Vector3(.08, .38, 0);
    camera.position.copy(HOME);
    const key = new T.DirectionalLight(0xfff1e6, 2.3); key.position.set(-3, 4, 5); scene.add(key);
    const rim = new T.DirectionalLight(0xffc9c9, 1.4); rim.position.set(3, 1, -4); scene.add(rim);
    scene.add(new T.HemisphereLight(0xffffff, 0x3a1a1a, .35));

    const controls = new OrbitControls(camera, canvas);
    controls.target.copy(TARGET); controls.enableDamping = true; controls.dampingFactor = .08;
    controls.enablePan = false; controls.minDistance = 3.2; controls.maxDistance = 13;
    controls.autoRotate = false; controls.autoRotateSpeed = .9;   // starts still so labels are easy to read; the spin button turns rotation on
    controls.addEventListener('start', () => { controls.autoRotate = false; box.querySelector('[data-h=spin]').classList.remove('on'); });
    if (controls.autoRotate) box.querySelector('[data-h=spin]').classList.add('on');

    /* ---------------- textures: muscle-fibre normal map and lumpy fat normal map, drawn on a canvas */
    function normalMap(size, fx, fy, strength) {
      const c = document.createElement('canvas'); c.width = c.height = size;
      const g = c.getContext('2d'), img = g.createImageData(size, size), hgt = new Float32Array(size * size);
      for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
        const u = x / size * Math.PI * 2, v = y / size * Math.PI * 2;      // wrap seamlessly
        hgt[y * size + x] = fbm(Math.cos(u) * fx + 10, Math.sin(u) * fx + 10, v * fy / (Math.PI * 2) * 4);
      }
      for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
        const H = (i, j) => hgt[((j + size) % size) * size + ((i + size) % size)];
        const dx = (H(x + 1, y) - H(x - 1, y)) * strength, dy = (H(x, y + 1) - H(x, y - 1)) * strength;
        const len = Math.hypot(dx, dy, 1), k = (y * size + x) * 4;
        img.data[k] = (-dx / len * .5 + .5) * 255; img.data[k + 1] = (-dy / len * .5 + .5) * 255; img.data[k + 2] = (1 / len * .5 + .5) * 255; img.data[k + 3] = 255;
      }
      g.putImageData(img, 0, 0);
      const tex = new T.CanvasTexture(c); tex.wrapS = tex.wrapT = T.RepeatWrapping; tex.colorSpace = T.NoColorSpace;
      return tex;
    }
    const fibreTex = normalMap(256, 1.2, 18, 9); fibreTex.repeat.set(3, 2);
    const lumpTex = normalMap(128, 3, 6, 6); lumpTex.repeat.set(6, 2);

    const disposables = [fibreTex, lumpTex];
    const mat = (o, n = fibreTex) => { const m = new T.MeshPhysicalMaterial(Object.assign({roughness: .46, clearcoat: .85, clearcoatRoughness: .22, sheen: .22, sheenColor: new T.Color('#ff8a7a'), normalMap: n, normalScale: new T.Vector2(.35, .35)}, o)); disposables.push(m); return m; };

    const heart = new T.Group(); scene.add(heart);
    const ventricles = new T.Group(), atria = new T.Group(), vessels = new T.Group(), surface = new T.Group();
    heart.add(ventricles, atria, vessels); ventricles.add(surface);
    const registry = {};                      // part -> {meshes:[], anchor:{p,n}}
    const reg = (key, mesh) => { (registry[key] ||= {meshes: []}).meshes.push(mesh); mesh.userData.part = key; return mesh; };
    const geo = g => { disposables.push(g); return g; };

    /* ---------------- chambers: deformed spheres with mottled vertex colour */
    const MUSCLE_A = new T.Color('#4E0A12'), MUSCLE_B = new T.Color('#8A1C25'), ATRIUM_A = new T.Color('#4A0E1E'), ATRIUM_B = new T.Color('#7A2333');
    function chamber({len, rad, taper = 0, flatten = 1, center, apexDir, seg = 96, colA, colB, bumps = .03, bumpFreq = 3}) {
      const g = geo(new T.SphereGeometry(1, seg, seg));
      const pos = g.attributes.position, v = new T.Vector3(), cols = [];
      const q = new T.Quaternion().setFromUnitVectors(new T.Vector3(0, -1, 0), new T.Vector3(...apexDir).normalize());
      for (let i = 0; i < pos.count; i++) {
        v.fromBufferAttribute(pos, i);
        const w = 1 - taper * Math.max(0, -v.y) * .6;
        const n = 1 + (fbm(v.x * bumpFreq + 5, v.y * bumpFreq, v.z * bumpFreq) - .5) * bumps * 2;
        v.set(v.x * rad * w * n, v.y * len * n, v.z * rad * w * flatten * n).applyQuaternion(q).add(new T.Vector3(...center));
        pos.setXYZ(i, v.x, v.y, v.z);
        const m = fbm(v.x * 4 + 1, v.y * 4, v.z * 4);
        const c = colA.clone().lerp(colB, Math.min(1, Math.max(0, m * 1.4 - .2)));
        cols.push(c.r, c.g, c.b);
      }
      g.setAttribute('color', new T.Float32BufferAttribute(cols, 3));
      g.computeVertexNormals();
      return g;
    }
    const strain = f.some(x => x.part === 'rv'), injury = f.some(x => x.part === 'lv');
    const lvGeo = chamber({len: .98, rad: .74, taper: .55, center: [.22, -.2, -.1], apexDir: [.42, -1, .18], colA: MUSCLE_A, colB: MUSCLE_B});
    const rvGeo = chamber({len: .84, rad: .64, taper: .45, flatten: .72, center: [-.17, -.1, .27], apexDir: [.22, -1, .38], colA: MUSCLE_A, colB: MUSCLE_B});
    const lv = reg('lv', new T.Mesh(lvGeo, mat({vertexColors: true})));
    const rv = reg('rv', new T.Mesh(rvGeo, mat({vertexColors: true})));
    ventricles.add(lv, rv);
    const ra = reg('ra', new T.Mesh(chamber({len: .5, rad: .46, center: [-.62, .42, .02], apexDir: [-.2, -1, .1], colA: ATRIUM_A, colB: ATRIUM_B, bumps: .05}), mat({vertexColors: true})));
    const la = reg('la', new T.Mesh(chamber({len: .34, rad: .5, flatten: .78, center: [.18, .5, -.5], apexDir: [0, -1, -.2], colA: ATRIUM_A, colB: ATRIUM_B, bumps: .05}), mat({vertexColors: true})));
    const auricle = (center, dir, rad) => chamber({len: rad * .62, rad, flatten: .55, center, apexDir: dir, seg: 72, colA: ATRIUM_A, colB: ATRIUM_B, bumps: .085, bumpFreq: 5});
    const rau = reg('rau', new T.Mesh(auricle([-.4, .72, .4], [.9, -.4, .5], .3), mat({vertexColors: true, normalScale: new T.Vector2(.5, .5)})));
    const lau = reg('lau', new T.Mesh(auricle([.56, .64, .28], [-.6, -.5, .7], .25), mat({vertexColors: true, normalScale: new T.Vector2(.5, .5)})));
    atria.add(ra, la, rau, lau);
    scene.updateMatrixWorld(true);

    /* ---------------- vessels: tapered tubes along curves */
    function tube(pts, r0, r1, m, {seg = 120, radial = 28, wobble = 0} = {}) {
      const curve = new T.CatmullRomCurve3(pts.map(p => p.isVector3 ? p : new T.Vector3(...p)), false, 'catmullrom', .5);
      const g = geo(new T.TubeGeometry(curve, seg, 1, radial, false));
      const pos = g.attributes.position, v = new T.Vector3(), c = new T.Vector3();
      for (let i = 0; i <= seg; i++) {
        const t = i / seg; curve.getPointAt(t, c);
        const rr = r0 + (r1 - r0) * t;
        for (let j = 0; j <= radial; j++) {
          const k = i * (radial + 1) + j;
          v.fromBufferAttribute(pos, k).sub(c);
          const n = wobble ? 1 + (noise3(c.x * 9 + j * .3, c.y * 9, c.z * 9) - .5) * wobble : 1;
          v.multiplyScalar(rr * n).add(c); pos.setXYZ(k, v.x, v.y, v.z);
        }
      }
      g.computeVertexNormals();
      const mesh = new T.Mesh(g, m); mesh.userData.curve = curve;
      return mesh;
    }
    const ARTERY = mat({color: '#A8434B', roughness: .35, side: T.DoubleSide, normalScale: new T.Vector2(.15, .15)});
    const VEIN = mat({color: '#45508A', roughness: .38, sheenColor: new T.Color('#9aa6ff'), side: T.DoubleSide, normalScale: new T.Vector2(.15, .15)});
    const PVEIN = mat({color: '#9C3E58', roughness: .38, side: T.DoubleSide, normalScale: new T.Vector2(.15, .15)});
    const aorta = reg('aorta', tube([[0, .42, .04], [-.05, .9, .12], [-.03, 1.35, .05], [.17, 1.63, -.2], [.45, 1.5, -.55], [.52, 1.1, -.72], [.5, .4, -.78], [.48, -.45, -.72]], .21, .16, ARTERY));
    const arch = [[[.03, 1.55, -.04], [-.08, 1.85, 0], [-.17, 2.1, .02]], [[.2, 1.63, -.16], [.22, 1.9, -.12], [.24, 2.12, -.1]], [[.36, 1.6, -.33], [.5, 1.85, -.36], [.62, 2.05, -.38]]]
      .map((pts, i) => reg('arch', tube(pts, [.085, .065, .07][i], [.075, .058, .06][i], ARTERY, {seg: 30})));
    const pt = reg('pt', tube([[.1, .45, .4], [.2, .85, .38], [.25, 1.1, .12]], .19, .17, VEIN));
    const lpa = reg('pt', tube([[.25, 1.1, .12], [.55, 1.18, -.05], [.88, 1.1, -.26]], .14, .12, VEIN, {seg: 50}));
    const rpa = reg('pt', tube([[.25, 1.1, .12], [-.1, 1.2, -.26], [-.62, 1.12, -.36]], .14, .12, VEIN, {seg: 60}));
    const svc = reg('svc', tube([[-.62, .7, 0], [-.6, 1.25, -.02], [-.58, 1.88, -.05]], .14, .13, VEIN, {seg: 50}));
    const ivc = reg('ivc', tube([[-.58, .1, -.15], [-.6, -.35, -.25], [-.6, -.78, -.3]], .15, .14, VEIN, {seg: 40}));
    const pvs = [[[.45, .6, -.6], [.95, .75, -.62]], [[.45, .38, -.62], [.96, .3, -.72]], [[-.05, .6, -.62], [-.55, .72, -.72]], [[-.05, .38, -.64], [-.52, .28, -.78]]]
      .map(([a, b]) => reg('pv', tube([a, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + .03, (a[2] + b[2]) / 2], b], .08, .075, PVEIN, {seg: 24})));
    vessels.add(aorta, ...arch, pt, lpa, rpa, svc, ivc, ...pvs);
    scene.updateMatrixWorld(true);

    /* ---------------- surface paths: rough guide points projected onto the heart, then laid as tubes */
    const ray = new T.Raycaster(), HC = new T.Vector3(.08, -.15, 0), chambers = [lv, rv, ra, la, rau, lau];
    function onSurface(p, lift = 0, from = HC) {
      const dir = new T.Vector3(...p).sub(from).normalize();
      ray.set(from.clone().addScaledVector(dir, 4), dir.clone().negate());
      const hit = ray.intersectObjects(chambers, false)[0];
      if (!hit) return null;
      const n = hit.face.normal.clone().transformDirection(hit.object.matrixWorld);
      return {p: hit.point.clone().addScaledVector(n, lift), n};
    }
    function surfacePath(guide, lift, samples = 46) {
      const c = new T.CatmullRomCurve3(guide.map(p => new T.Vector3(...p)));
      const out = [];
      for (let i = 0; i <= samples; i++) { const s = onSurface(c.getPoint(i / samples).toArray(), lift); if (s) out.push(s.p); }
      return out;
    }
    const G = {
      lad: [[.12, .4, .62], [.27, .05, .75], [.36, -.3, .74], [.45, -.66, .62], [.53, -.96, .46], [.58, -1.16, .2]],
      cx: [[.26, .36, .4], [.62, .24, .32], [.88, .1, -.04], [.76, .02, -.46], [.42, -.04, -.68]],
      rca: [[-.1, .38, .52], [-.42, .22, .58], [-.7, .02, .38], [-.8, -.18, 0], [-.6, -.28, -.42], [-.2, -.34, -.66], [.05, -.62, -.62], [.28, -.98, -.38]],
      diag: [[.34, -.2, .74], [.62, -.32, .58], [.82, -.46, .32]],
      om: [[.8, .08, .02], [.88, -.3, .02], [.8, -.62, .04]],
      gcv: [[.18, .38, .64], [.33, .03, .78], [.42, -.3, .76], [.5, -.62, .64]],
    };
    const FAT = mat({color: '#D9AE52', roughness: .5, clearcoat: .55, sheen: .2, sheenColor: new T.Color('#fff2b0'), normalMap: lumpTex, normalScale: new T.Vector2(.9, .9)});
    const CORON = mat({color: '#C5232E', roughness: .3, clearcoat: .9, normalScale: new T.Vector2(.1, .1)});
    const CVEIN = mat({color: '#3E3568', roughness: .32, clearcoat: .85, normalScale: new T.Vector2(.1, .1)});
    const fatGroup = new T.Group(); surface.add(fatGroup);
    [['rca', .085], ['cx', .08], ['lad', .055]].forEach(([k, rr]) => fatGroup.add(reg('fat', tube(surfacePath(G[k], -.01), rr, rr * .6, FAT, {seg: 90, radial: 18, wobble: .7}))));
    const lad = reg('lad', tube(surfacePath(G.lad, .045), .032, .018, CORON, {seg: 90, radial: 14}));
    const cx = reg('cx', tube(surfacePath(G.cx, .05), .03, .02, CORON, {seg: 80, radial: 14}));
    const rca = reg('rca', tube(surfacePath(G.rca, .06), .034, .02, CORON, {seg: 120, radial: 14}));
    const diag = reg('lad', tube(surfacePath(G.diag, .025), .018, .01, CORON, {seg: 40, radial: 10}));
    const om = reg('cx', tube(surfacePath(G.om, .012), .016, .009, CORON, {seg: 40, radial: 10}));
    const gcv = reg('gcv', tube(surfacePath(G.gcv, .03), .026, .02, CVEIN, {seg: 70, radial: 12}));
    surface.add(lad, cx, rca, diag, om, gcv);

    /* ---------------- results drawn onto the heart */
    if (injury) {                                   // dark, mottled injured muscle on the front wall of the LV, in LAD territory
      const centre = onSurface([.48, -.5, .72]).p, dark = new T.Color('#2A0B18'), pale = new T.Color('#7D4B57');
      [lvGeo, rvGeo].forEach(g => {
        const pos = g.attributes.position, col = g.attributes.color, v = new T.Vector3(), c = new T.Color();
        for (let i = 0; i < pos.count; i++) {
          v.fromBufferAttribute(pos, i);
          const d = v.distanceTo(centre) + (fbm(v.x * 7, v.y * 7, v.z * 7) - .5) * .18;
          if (d > .62) continue;
          c.fromBufferAttribute(col, i);
          c.lerp(d < .42 ? dark : pale, d < .42 ? Math.min(1, (.42 - d) / .12) * .92 : (.62 - d) / .2 * .55);
          col.setXYZ(i, c.r, c.g, c.b);
        }
        col.needsUpdate = true;
      });
      registry.lv.anchor = onSurface([.48, -.5, .72], .02);
    }
    if (f.some(x => x.part === 'rca')) {            // cholesterol plaques bulging on the coronary arteries
      const PLAQ = mat({color: '#EBD47E', roughness: .45, clearcoat: .6, normalScale: new T.Vector2(.2, .2)});
      [[lad, .2], [lad, .42], [rca, .16], [cx, .3]].forEach(([m, t]) => {
        const s = new T.Mesh(geo(new T.SphereGeometry(.045, 20, 16)), PLAQ);
        s.position.copy(m.userData.curve.getPointAt(t)); s.scale.set(1.3, .8, 1); surface.add(reg('rca', s));
      });
    }
    if (strain) { ventricles.scale.setScalar(1.08); atria.scale.setScalar(1.05); }

    /* ---------------- anchors for the pins */
    const anchorOn = (key, guide, lift = .06) => { if (!registry[key].anchor) registry[key].anchor = onSurface(guide, lift); };
    anchorOn('lv', [.85, -.45, .25]); anchorOn('rv', [-.35, -.25, .78]); anchorOn('ra', [-1, .45, .15]); anchorOn('la', [.2, .55, -1]);
    anchorOn('rau', [-.45, .8, .8]); anchorOn('lau', [.75, .7, .55]);
    const along = (key, mesh, t) => { const p = mesh.userData.curve.getPointAt(t); registry[key].anchor = {p: p.clone(), n: p.clone().sub(HC).normalize()}; };
    along('aorta', aorta, .3); along('arch', arch[1], .7); along('pt', pt, .55); along('pv', pvs[0], .8); along('svc', svc, .65); along('ivc', ivc, .7);
    along('lad', lad, .45); along('cx', cx, .5); along('rca', rca, .28); along('gcv', gcv, .6); along('fat', fatGroup.children[0], .4);
    registry.sa = {meshes: [ra], anchor: onSurface([-.6, .82, .25], .05)};
    registry.apex = {meshes: [lv], anchor: onSurface([.6, -1.3, .25], .04)};

    /* ---------------- pins (HTML over the canvas, follow the heart as it turns) */
    const issue = Object.fromEntries(f.map(x => [x.part, x]));
    let showLabels = true;
    const pins = Object.entries(registry).filter(([, v]) => v.anchor).map(([key, v]) => {
      const el = document.createElement('button');
      const fi = issue[key];
      el.type = 'button';
      el.className = `h3d-pin ${fi ? 'issue ' + fi.level : 'part'}`;
      el.innerHTML = fi ? `<span class="ring"></span><span class="dot"></span><span class="tag">${esc(fi.title)}</span>` : `<span class="dot"></span><span class="tag">${esc(PARTS[key][0])}</span>`;
      el.title = PARTS[key][0] + (fi ? ': ' + fi.title : '');
      el.setAttribute('aria-label', PARTS[key][0] + (fi ? `, needs attention: ${fi.title}` : ''));
      el.addEventListener('click', e => { e.stopPropagation(); pick(key, true); });
      pinBox.appendChild(el);
      return {key, el, a: v.anchor, rank: fi ? (fi.level === 'crit' ? 0 : 1) : 2};
    }).sort((a, b) => a.rank - b.rank);

    /* ---------------- picking: tap a part or a pin to read about it, highlight it and turn it to face you */
    let glow = null, fly = null;
    function pick(key, turn) {
      const fi = issue[key];
      say(`${PARTS[key][0]}: ${fi ? fi.detail + ' ' : ''}${PARTS[key][1]}`);
      if (glow) glow.meshes.forEach(m => m.material.emissive && m.material.emissive.setHex(0));
      const meshes = [...new Set(registry[key].meshes)];
      meshes.forEach(m => { if (!m.userData.ownMat) { m.material = m.material.clone(); m.userData.ownMat = true; disposables.push(m.material); } });
      glow = {meshes, t0: performance.now(), colour: fi ? (fi.level === 'crit' ? 0xff2244 : 0xffaa22) : 0x2ad1c4};
      pins.forEach(p => p.el.classList.toggle('picked', p.key === key));
      if (turn && registry[key].anchor) {
        const a = registry[key].anchor, dist = camera.position.distanceTo(controls.target);
        const to = controls.target.clone().add(a.n.clone().setY(a.n.y * .6).normalize().multiplyScalar(dist));
        fly = {from: camera.position.clone(), to, t0: performance.now()};
        controls.autoRotate = false; box.querySelector('[data-h=spin]').classList.remove('on');
      }
    }
    let down = null;
    canvas.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
    canvas.addEventListener('pointerup', e => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;   // a drag, not a tap
      const rect = canvas.getBoundingClientRect();
      ray.setFromCamera(new T.Vector2((e.clientX - rect.left) / rect.width * 2 - 1, -(e.clientY - rect.top) / rect.height * 2 + 1), camera);
      const hit = ray.intersectObjects(heart.children, true).find(h => h.object.userData.part);
      if (hit) pick(hit.object.userData.part, false);
    });

    /* ---------------- toolbar */
    wrap.addEventListener('click', e => {
      const b = e.target.closest('[data-h]'), go = e.target.closest('[data-go]');
      if (go) return pick(go.dataset.go, true);
      if (!b) return;
      const h = b.dataset.h;
      if (h === 'reset') { fly = {from: camera.position.clone(), to: HOME.clone(), t0: performance.now()}; controls.target.copy(TARGET); }
      if (h === 'spin') { controls.autoRotate = !controls.autoRotate; b.classList.toggle('on', controls.autoRotate); }
      if (h === 'back') { const p = camera.position.clone().sub(controls.target); fly = {from: camera.position.clone(), to: controls.target.clone().add(new T.Vector3(-p.x, p.y, -p.z)), t0: performance.now()}; }
      if (h === 'labels') { showLabels = !showLabels; box.classList.toggle('no-labels', !showLabels); b.classList.toggle('on', !showLabels); }
      if (h === 'full') { document.fullscreenElement ? document.exitFullscreen() : box.requestFullscreen?.(); }
    });

    /* ---------------- size, beat, render loop */
    function resize() {
      const w = box.clientWidth, h = box.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
    }
    const ro = new ResizeObserver(resize); ro.observe(box); resize();

    const arrhythmia = f.some(x => x.part === 'sa');
    let period = 60 / 72, beatStart = 0, nextBeat = 0;
    const tmp = new T.Vector3(), camDir = new T.Vector3();
    let raf = 0, visible = true, last = 0, slowFrames = 0, quality = 2;
    const io = new IntersectionObserver(es => { visible = es[0].isIntersecting; }); io.observe(box);
    // Hospital PCs often have weak graphics: if frames are slow, step down resolution, then the costly gloss and sheen.
    function adapt(dt) {
      if (dt > 45) slowFrames++; else slowFrames = Math.max(0, slowFrames - 1);
      if (slowFrames < 20 || quality === 0) return;
      slowFrames = 0; quality--;
      if (quality === 1) renderer.setPixelRatio(1);
      if (quality === 0) {
        renderer.setPixelRatio(.75);
        disposables.forEach(m => { if (m.isMeshPhysicalMaterial) { m.clearcoat = 0; m.sheen = 0; m.needsUpdate = true; } });
      }
      resize();
    }
    function frame(now) {
      if (!box.isConnected) return dispose();
      raf = requestAnimationFrame(frame);
      if (!visible || document.hidden) { last = 0; return; }      // no work while scrolled away or in a background tab
      if (last) adapt(now - last);
      last = now;
      const t = now / 1000;
      if (!still) {                                 // atria squeeze first, then the ventricles; irregular gaps when the rhythm is disturbed
        if (t >= nextBeat) { beatStart = t; nextBeat = t + (arrhythmia ? period * (.55 + Math.random() * .95) : period); }
        const ph = (t - beatStart) / period;
        const pulse = (a, b) => ph < a || ph > b ? 0 : Math.sin(Math.PI * (ph - a) / (b - a));
        const s = strain ? 1.08 : 1, ca = pulse(0, .16), cv = pulse(.16, .5);
        atria.scale.setScalar((strain ? 1.05 : 1) * (1 - .055 * ca));
        ventricles.scale.set(s * (1 - .035 * cv), s * (1 - .05 * cv), s * (1 - .035 * cv));
        heart.rotation.y = .025 * cv;
      }
      if (fly) {
        const k = Math.min(1, (now - fly.t0) / 700), e = k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
        camera.position.lerpVectors(fly.from, fly.to, e);
        if (k >= 1) fly = null;
      }
      if (glow) {
        const k = (now - glow.t0) / 1000, amt = k > 2.4 ? 0 : (Math.sin(k * 7) * .5 + .5) * .55 * (1 - k / 2.4);
        glow.meshes.forEach(m => { m.material.emissive.setHex(glow.colour); m.material.emissiveIntensity = amt; });
        if (k > 2.4) glow = null;
      }
      controls.update();
      renderer.render(scene, camera);
      // pins: project each anchor; fade the ones on the far side so you know to turn the heart.
      // Positions are lightly smoothed, and a label only changes state after it has been steady for a moment,
      // so labels do not flicker as the heart turns or as pins pass each other.
      const w = box.clientWidth, h = box.clientHeight;
      camDir.copy(camera.position);
      for (const p of pins) {
        tmp.copy(p.a.p).applyMatrix4(heart.matrixWorld);
        const d = p.a.n.dot(camDir.clone().sub(tmp).normalize());
        p.facing = p.facing === undefined ? d > .05 : (p.facing ? d > -.04 : d > .14);     // dead zone at the edge
        tmp.project(camera);
        const x = (tmp.x + 1) / 2 * w, y = (1 - tmp.y) / 2 * h;
        p.x = p.x === undefined ? x : p.x + (x - p.x) * .45; p.y = p.y === undefined ? y : p.y + (y - p.y) * .45;
        p.el.style.transform = `translate(${p.x.toFixed(1)}px,${p.y.toFixed(1)}px)`;
        p.el.classList.toggle('behind', !p.facing);
      }
      const placed = [];                            // most urgent labels claim their space first
      for (const p of [...pins].sort((a, b) => a.rank - b.rank)) {
        if (p.rank === 2) continue;
        p.tw = p.tw || p.el.querySelector('.tag').offsetWidth;
        const rect = [p.x + 10, p.y - 12, p.x + 10 + p.tw, p.y + 10];
        const hide = !p.facing || placed.some(q => rect[0] < q[2] + 4 && rect[2] + 4 > q[0] && rect[1] < q[3] + 3 && rect[3] + 3 > q[1]);
        if (hide !== p.wantHide) { p.wantHide = hide; p.since = now; }
        if (p.hidden === undefined || (p.hidden !== hide && now - p.since > 350)) { p.hidden = hide; p.el.classList.toggle('tag-off', hide); }
        if (!p.hidden) placed.push(rect);
      }
    }
    raf = requestAnimationFrame(frame);
    box.classList.add('ready');

    function dispose() {
      cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); controls.dispose();
      disposables.forEach(d => d.dispose && d.dispose());
      scene.environment && scene.environment.dispose(); pmrem.dispose(); renderer.dispose();
    }
  }
})();
