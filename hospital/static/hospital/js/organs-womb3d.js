/* Rotatable 3D pregnancy for the reproductive pop-out (three.js, served by E-MedFlow; uses window.MF_THREE and the
   page's import map). A translucent womb with amniotic fluid, placenta and umbilical cord, and the baby curled inside at
   the size for the gestational age, moving gently with its heart beating at the fetal heart rate. Before 10 weeks an
   embryo in its sac is shown. Teaching illustration only. */
window.MFWomb3D = (() => {
  'use strict';
  const webgl = () => { try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch (e) { return false; } };

  async function mount(box, preg, onFail) {
    const CFG = window.MF_THREE;
    if (!CFG || !webgl()) return onFail && onFail();
    let T, OrbitControls, RoomEnvironment;
    try {
      T = await import(CFG.three); ({OrbitControls} = await import(CFG.controls)); ({RoomEnvironment} = await import(CFG.room));
    } catch (e) { console.error('3D pregnancy: could not load three.js', e); return onFail && onFail(); }
    if (!box.isConnected) return;
    const canvas = box.querySelector('canvas');
    let renderer;
    try { renderer = new T.WebGLRenderer({canvas, antialias: true, alpha: true}); } catch (e) { return onFail && onFail(); }
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    renderer.outputColorSpace = T.SRGBColorSpace; renderer.toneMapping = T.ACESFilmicToneMapping; renderer.toneMappingExposure = .95;
    const scene = new T.Scene(), pmrem = new T.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), .04).texture;
    const camera = new T.PerspectiveCamera(32, 1, .1, 60);
    const HOME = new T.Vector3(.5, .2, 11);
    camera.position.copy(HOME);
    const key = new T.DirectionalLight(0xfff0e6, 2.1); key.position.set(-3, 4, 5); scene.add(key);
    const rim = new T.DirectionalLight(0xffd6d6, 1.3); rim.position.set(3, 1, -4); scene.add(rim);
    scene.add(new T.HemisphereLight(0xffffff, 0x402020, .4));
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true; controls.dampingFactor = .08; controls.minDistance = 4; controls.maxDistance = 16; controls.target.set(0, 0, 0);
    const disposables = [];
    const mat = o => { const m = new T.MeshPhysicalMaterial(o); disposables.push(m); return m; };
    const add = (geo, m, parent = scene) => { disposables.push(geo); const mesh = new T.Mesh(geo, m); parent.add(mesh); return mesh; };

    const weeks = Math.max(5, Math.min(40, preg.weeks || 20)), early = weeks < 10;
    const grow = early ? .35 + (weeks - 5) * .05 : .45 + (weeks - 10) / 30 * .55;     // 0.35 … 1

    // womb: pear-shaped, wider at the top, translucent muscular wall
    const wg = new T.SphereGeometry(1.95, 64, 48);
    const pos = wg.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const y = pos.getY(i), k = y < 0 ? 1 + y * .18 : 1 + y * .03;               // narrower towards the cervix
      pos.setX(i, pos.getX(i) * k); pos.setZ(i, pos.getZ(i) * k * .92); pos.setY(i, y * 1.12);
    }
    wg.computeVertexNormals();
    const wall = add(wg, mat({color: 0xE48C98, roughness: .35, transparent: true, opacity: .32, depthWrite: false, sheen: .7, sheenColor: 0xffc4c8, clearcoat: .4, side: T.DoubleSide}));
    wall.renderOrder = 3;                                                             // drawn last, over the baby
    const neck = add(new T.CylinderGeometry(.42, .55, .9, 32, 1, true), mat({color: 0xD98892, roughness: .45, transparent: true, opacity: .55, depthWrite: false, side: T.DoubleSide}));
    neck.position.y = -2.4;                                                           // cervix
    // amniotic sac and fluid
    const sac = add(new T.SphereGeometry(early ? .9 : 1.72, 48, 36), mat({color: 0xBFE0EE, roughness: .05, clearcoat: 1, transparent: true, opacity: .18, depthWrite: false}));
    sac.renderOrder = 2;
    // placenta on the back wall
    const pl = add(new T.SphereGeometry(.95, 40, 24), mat({color: 0x8E2A35, roughness: .55, sheen: .4, sheenColor: 0xff8a9a, clearcoat: .3}));
    const plSize = early ? .45 : Math.min(1, .6 + (weeks - 10) / 30 * .4);         // the placenta grows through pregnancy
    pl.scale.set(plSize, .85 * plSize, .28 * plSize); pl.position.set(.55, .7, early ? -.95 : -1.45); pl.rotation.x = .25;

    // the baby (or embryo)
    const skin = mat({color: early ? 0xF2C6BC : 0xF0B9A9, roughness: .55, sheen: .8, sheenColor: 0xffd9cf, clearcoat: .15, });
    const baby = new T.Group(); scene.add(baby);
    const sph = (r, x, y, z, sx = 1, sy = 1, sz = 1) => { const m = add(new T.SphereGeometry(r, 36, 24), skin, baby); m.position.set(x, y, z); m.scale.set(sx, sy, sz); return m; };
    const cap = (r, len, x, y, z, rx, rz) => { const m = add(new T.CapsuleGeometry(r, len, 8, 16), skin, baby); m.position.set(x, y, z); m.rotation.set(rx, 0, rz); return m; };
    const head = sph(early ? .42 : .52, -.12, .62, .15, 1, 1.05, 1);
    sph(early ? .3 : .44, .1, -.12, 0, .95, 1.35, .85).rotation.z = .5;               // curled body
    let legL = null, armR = null;
    if (!early) {
      armR = cap(.1, .5, -.05, .25, .38, .9, 1.1); cap(.1, .5, .25, .25, .32, .9, 1.4);                     // arms folded towards the face
      legL = cap(.13, .62, .42, -.55, .3, 1.2, -.6); cap(.13, .62, .2, -.6, .45, 1.1, -.9);                  // knees drawn up
      sph(.07, -.32, .72, .5); sph(.07, -.05, .74, .58);                                                    // closed eyes / brow hint
    } else {
      const tail = cap(.12, .35, .32, -.48, 0, 0, -.9); tail.scale.set(1, 1, .9);                           // embryo's curved tail
    }
    baby.scale.setScalar(grow * (early ? 1 : 1.25));
    baby.position.set(-.15, -.05, .2); baby.rotation.set(.1, .35, -.2);
    // heart: glowing, beating at the fetal heart rate
    const heartMat = mat({color: 0xC8323F, emissive: 0xff2a3a, emissiveIntensity: .6, roughness: .4});
    const heart = add(new T.SphereGeometry(early ? .09 : .1, 20, 16), heartMat, baby); heart.position.set(.02, .12, .34);
    // umbilical cord from the placenta to the belly, gently twisting
    const cordCurve = new T.CatmullRomCurve3([new T.Vector3(.5, .7, -1.25), new T.Vector3(1.1, .2, -.4), new T.Vector3(.9, -.6, .5), new T.Vector3(.35, -.15, .45)]);
    const cordMat = mat({color: 0xE6D3B3, roughness: .35, clearcoat: .6, sheen: .3, emissive: 0x401818, emissiveIntensity: 0});
    add(new T.TubeGeometry(cordCurve, 80, early ? .05 : .075, 12, false), cordMat);

    // size, resize and render loop
    const ro = new ResizeObserver(resize); ro.observe(box);
    function resize() { const w = box.clientWidth, h = box.clientHeight; if (!w || !h) return; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
    resize();
    let visible = true, raf = 0, kick = 0;
    const io = new IntersectionObserver(es => { visible = es[0].isIntersecting; }); io.observe(box);
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const bpm = preg.fhr || 140, base = baby.rotation.clone();
    box.querySelector('[data-w="reset"]')?.addEventListener('click', () => { camera.position.copy(HOME); controls.target.set(0, 0, 0); });
    function frame(now) {
      if (!box.isConnected) return dispose();
      raf = requestAnimationFrame(frame);
      if (!visible || document.hidden) return;
      const t = now / 1000;
      if (!still) {
        const beat = Math.pow(Math.max(0, Math.sin(t * Math.PI * 2 * bpm / 60)), 6);
        heart.scale.setScalar(1 + beat * .45); heartMat.emissiveIntensity = .4 + beat * 1.2;
        cordMat.emissiveIntensity = beat * .25;
        baby.position.y = -.05 + Math.sin(t * .9) * .04;                              // floating in the fluid
        baby.rotation.z = base.z + Math.sin(t * .5) * .05; head.rotation.y = Math.sin(t * .35) * .25;
        if (legL) { if (Math.random() < .004 && !kick) kick = t; const k = kick ? Math.sin(Math.min(1, (t - kick) / .6) * Math.PI) : 0; legL.rotation.x = 1.2 - k * .7; if (kick && t - kick > .6) kick = 0; }
        if (armR) armR.rotation.z = 1.1 + Math.sin(t * .7) * .08;
      }
      controls.update(); renderer.render(scene, camera);
    }
    raf = requestAnimationFrame(frame);
    box.classList.add('ready');
    function dispose() {
      cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); controls.dispose();
      disposables.forEach(d => d.dispose && d.dispose()); scene.environment && scene.environment.dispose(); pmrem.dispose(); renderer.dispose();
    }
  }
  return {mount};
})();
