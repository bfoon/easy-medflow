/* Dr. Flow: a robot doctor (white coat, stethoscope, ECG-trace mouth) that jumps in when the AI is asked.
   Its eyes follow you, and between glances it watches the place where the AI summary is being written.
   window.RoboDoc = {summon, hide, think, done, fail, say, speak, focus, state}. On the lab request page it is wired to
   the guidance panel; other pages (the report editor) drive it through the same API. */
(() => {
  if (window.RoboDoc) return;
  try {   // a form opened in the drawer (same-origin iframe) uses the page's Dr. Flow, who stands beside the drawer
    if (window.parent !== window && window.parent.RoboDoc) { window.RoboDoc = window.parent.RoboDoc; return; }
  } catch { /* cross-origin parent: use our own */ }
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const rand = (a, b) => a + Math.random() * (b - a);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const EYES = [[64, 56], [96, 56]];

  const SVG = `<svg viewBox="0 0 160 200" aria-hidden="true" focusable="false">
  <ellipse cx="80" cy="193" rx="40" ry="5" fill="rgba(15,44,63,.16)"/>
  <g class="rd-torso">
    <rect x="61" y="166" width="12" height="18" rx="4" fill="#18405A"/><rect x="87" y="166" width="12" height="18" rx="4" fill="#18405A"/>
    <rect x="54" y="181" width="23" height="10" rx="5" fill="#0F2C3F"/><rect x="83" y="181" width="23" height="10" rx="5" fill="#0F2C3F"/>
    <rect x="72" y="90" width="16" height="16" fill="#18405A"/>
    <path d="M47 104 Q80 95 113 104 L125 168 Q80 179 35 168 Z" fill="#fff" stroke="#C9D5CF" stroke-width="1.6" stroke-linejoin="round"/>
    <path d="M66 102 L80 128 L94 102 Z" fill="#DDF0EA"/>
    <path d="M78 107 h4 l2 15 -4 6 -4 -6 Z" fill="#0F7B78"/>
    <path d="M66 102 L80 128 L71 141 M94 102 L80 128 L89 141" fill="none" stroke="#C9D5CF" stroke-width="1.6" stroke-linejoin="round"/>
    <rect x="62" y="121" width="3" height="12" rx="1.5" fill="#0F7B78"/><rect x="66.5" y="119" width="3" height="14" rx="1.5" fill="#4A5FC1"/>
    <path d="M51 129 h20 v12 q0 3 -3 3 h-14 q-3 0 -3 -3 Z" fill="#fff" stroke="#C9D5CF" stroke-width="1.4"/>
    <rect x="94" y="126" width="18" height="12" rx="2.5" fill="#F2F5F3" stroke="#C9D5CF" stroke-width="1.2"/>
    <rect x="96.5" y="129.5" width="5" height="5" rx="1" fill="#C8323F"/><path d="M99 130.5v3M97.5 132h3" stroke="#fff" stroke-width="1.1"/>
    <path d="M104 130.5h6M104 133.5h4" stroke="#C9D5CF" stroke-width="1.2" stroke-linecap="round"/>
    <circle cx="80" cy="152" r="1.8" fill="#C9D5CF"/><circle cx="80" cy="162" r="1.8" fill="#C9D5CF"/>
    <g class="rd-steth">
      <path d="M70 99 q-5 -4 -1 -9 M90 99 q5 -4 1 -9" fill="none" stroke="#5A6F7D" stroke-width="2" stroke-linecap="round"/>
      <circle cx="69.5" cy="89.5" r="1.8" fill="#5A6F7D"/><circle cx="90.5" cy="89.5" r="1.8" fill="#5A6F7D"/>
      <path d="M70 99 C58 116 63 135 80 137 C97 135 102 116 90 99" fill="none" stroke="#0B5F5D" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M80 137 v6" stroke="#0B5F5D" stroke-width="3" stroke-linecap="round"/>
      <circle cx="80" cy="148" r="6.4" fill="#C9D5CF" stroke="#5A6F7D" stroke-width="1.4"/><circle cx="80" cy="148" r="2.8" fill="#fff"/>
    </g>
    <g class="rd-arm l"><rect x="35" y="107" width="14" height="40" rx="7" fill="#fff" stroke="#C9D5CF" stroke-width="1.5"/>
      <rect x="35.8" y="140" width="12.4" height="6" rx="2" fill="#DDF0EA"/><circle cx="42" cy="153" r="6.6" fill="#9FB3BF" stroke="#5A6F7D" stroke-width="1.3"/></g>
    <g class="rd-arm r"><rect x="111" y="107" width="14" height="40" rx="7" fill="#fff" stroke="#C9D5CF" stroke-width="1.5"/>
      <rect x="111.8" y="140" width="12.4" height="6" rx="2" fill="#DDF0EA"/><circle cx="118" cy="153" r="6.6" fill="#9FB3BF" stroke="#5A6F7D" stroke-width="1.3"/></g>
    <g class="rd-head">
      <path d="M80 26 V13" stroke="#18405A" stroke-width="3" stroke-linecap="round"/>
      <g class="rd-bulb"><circle cx="80" cy="9" r="6.5" fill="#C8323F"/><path d="M80 5.6v6.8M76.6 9h6.8" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/></g>
      <rect x="23" y="48" width="9" height="20" rx="3.5" fill="#0F7B78"/><rect x="128" y="48" width="9" height="20" rx="3.5" fill="#0F7B78"/>
      <rect x="29" y="24" width="102" height="72" rx="23" fill="#18405A"/>
      <rect x="38" y="33" width="84" height="54" rx="16" fill="#0F2C3F"/>
      <path d="M46 40 q10 -3 22 -2" stroke="rgba(255,255,255,.18)" stroke-width="2.4" fill="none" stroke-linecap="round"/>
      ${EYES.map(([x, y], i) => `<g class="rd-eye" data-i="${i}">
        <ellipse cx="${x}" cy="${y}" rx="13.5" ry="15" fill="#3FE0B0" opacity=".14"/>
        <ellipse class="rd-eyeball" cx="${x}" cy="${y}" rx="10" ry="11.5" fill="#3FE0B0"/>
        <g class="rd-pupil"><circle cx="${x}" cy="${y}" r="5.2" fill="#0F2C3F"/><circle cx="${x - 1.8}" cy="${y - 2}" r="1.7" fill="#fff"/></g>
        <path class="rd-happy" d="M${x - 8} ${y + 3} Q${x} ${y - 9} ${x + 8} ${y + 3}" fill="none" stroke="#3FE0B0" stroke-width="3.6" stroke-linecap="round"/>
        <path class="rd-sad" d="M${x - 8} ${y - 2} Q${x} ${y + 6} ${x + 8} ${y - 2}" fill="none" stroke="#3FE0B0" stroke-width="3.6" stroke-linecap="round"/>
      </g>`).join('')}
      <circle class="rd-cheek" cx="49" cy="74" r="5" fill="#E06A7A"/><circle class="rd-cheek" cx="111" cy="74" r="5" fill="#E06A7A"/>
      <path class="rd-smile" d="M68 75 Q80 82 92 75" fill="none" stroke="#3FE0B0" stroke-width="2.6" stroke-linecap="round"/>
      <path class="rd-trace" d="M56 77 H68 L71.5 71 L75.5 83 L80 66 L84.5 80 L87.5 77 H104" fill="none" stroke="#3FE0B0" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
    </g>
  </g></svg>`;

  let root, bodyEl, svg, bubble, textEl, actsEl, head, pupils, eyeGroups, armL, armR;
  let state = 'hidden', focusFn = null, pointer = null, lastMove = 0, gaze = 'you', pointing = false;
  let gazeTimer = 0, blinkTimer = 0, msgTimer = 0, moodTimer = 0, raf = 0, lookedEl = null;

  function build() {
    if (root) return;
    root = document.createElement('div');
    root.className = 'rd';
    root.hidden = true;
    root.innerHTML = `<div class="rd-bubble" role="status" aria-live="polite"><div class="rd-bubble-name">Dr. Flow <span>AI assistant</span></div>
      <div class="rd-bubble-text"></div><div class="rd-bubble-actions"></div></div>
      <button type="button" class="rd-close" aria-label="Send Dr. Flow away"><i class="bi bi-x-lg"></i></button>
      <div class="rd-body" tabindex="0" role="button" aria-label="Dr. Flow, AI assistant. Show the summary">${SVG}</div>`;
    document.body.appendChild(root);
    bodyEl = root.querySelector('.rd-body'); svg = root.querySelector('svg');
    bubble = root.querySelector('.rd-bubble'); textEl = root.querySelector('.rd-bubble-text'); actsEl = root.querySelector('.rd-bubble-actions');
    head = root.querySelector('.rd-head'); pupils = [...root.querySelectorAll('.rd-pupil')]; eyeGroups = [...root.querySelectorAll('.rd-eye')];
    armL = root.querySelector('.rd-arm.l'); armR = root.querySelector('.rd-arm.r');
    root.querySelector('.rd-close').addEventListener('click', () => { hide(); document.dispatchEvent(new CustomEvent('robodoc:dismissed')); });
    const activate = () => {
      const el = target();
      if (el) { el.scrollIntoView({behavior: reduced.matches ? 'auto' : 'smooth', block: 'center'}); setGaze('summary', 2600); }
      bubble.classList.toggle('show', !bubble.classList.contains('show') || !el);
    };
    bodyEl.addEventListener('click', activate);
    bodyEl.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); } });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && state !== 'hidden') { bubble.classList.remove('show'); stopSpeaking(); } });
    new MutationObserver(place).observe(document.body, {attributes: true, attributeFilter: ['class']});
    addEventListener('resize', place);
    addEventListener('pointermove', e => { pointer = {x: e.clientX, y: e.clientY}; lastMove = performance.now(); }, {passive: true});
    addEventListener('pointerdown', e => { pointer = {x: e.clientX, y: e.clientY}; lastMove = performance.now(); }, {passive: true});
  }

  function rectOf(el) {
    const r = el.getBoundingClientRect();
    const fr = el.ownerDocument !== document && el.ownerDocument.defaultView?.frameElement;
    if (!fr) return r;
    const f = fr.getBoundingClientRect();
    return {left: r.left + f.left, top: r.top + f.top, width: r.width, height: r.height};
  }

  function trackFrame(win) {    // follow the pointer inside the drawer too
    try {
      const fr = win.frameElement;
      if (!fr || win.__rdTracked) return;
      win.__rdTracked = true;
      const h = e => { const f = fr.getBoundingClientRect(); pointer = {x: e.clientX + f.left, y: e.clientY + f.top}; lastMove = performance.now(); };
      win.addEventListener('pointermove', h, {passive: true});
      win.addEventListener('pointerdown', h, {passive: true});
    } catch { /* ignore */ }
  }

  // stand beside the drawer when it is open, so the form stays visible
  function place() {
    if (!root) return;
    const d = document.getElementById('drawer'), open = !!(d && d.classList.contains('open'));
    const w = open ? d.getBoundingClientRect().width : 0;
    root.style.right = open && innerWidth - w > 200 ? `${Math.round(w + 16)}px` : '';
    root.classList.toggle('by-drawer', open);
  }

  function target() {
    try {
      const el = focusFn ? focusFn() : null;
      return el && el.isConnected && el.ownerDocument.defaultView ? el : null;
    } catch { return null; }
  }

  // ---------------------------------------------------------------- gaze: you ↔ the summary
  function setGaze(g, ms) {
    clearTimeout(gazeTimer);
    gaze = g;
    gazeTimer = setTimeout(() => {
      const toSummary = gaze === 'you' && target();
      const bias = state === 'thinking' ? [1800, 3200] : [1400, 2600];
      setGaze(toSummary ? 'summary' : 'you', toSummary ? rand(...bias) : rand(1600, 3000));
    }, ms ?? rand(1600, 2800));
  }

  function toBox(pt) {
    const r = svg.getBoundingClientRect(), k = 160 / r.width;
    return {x: (pt.x - r.left) * k, y: (pt.y - r.top) * k};
  }

  function tick() {
    raf = requestAnimationFrame(tick);
    if (!svg || state === 'hidden') return;
    const now = performance.now();
    let pt = null, looking = null;
    if (pointer && now - lastMove < 1800) pt = pointer;
    else if (gaze === 'summary') {
      const el = target();
      if (el) {
        const r = rectOf(el);
        pt = {x: clamp(r.left + Math.min(r.width, 420) / 2, 0, innerWidth), y: clamp(r.top + Math.min(r.height, 260) / 2, 0, innerHeight)};
        looking = el;
      }
    }
    if (looking !== lookedEl) { lookedEl?.classList.remove('rd-looking'); looking?.classList.add('rd-looking'); lookedEl = looking; }
    let tilt = 0;
    if (pt) {
      const b = toBox(pt);
      EYES.forEach(([ex, ey], i) => {
        const dx = b.x - ex, dy = b.y - ey, d = Math.hypot(dx, dy) || 1, k = Math.min(1, d / 120);
        pupils[i].style.transform = `translate(${(dx / d * 4.6 * k).toFixed(2)}px,${(dy / d * 5.4 * k).toFixed(2)}px)`;
      });
      tilt = clamp((b.x - 80) / 260, -1, 1) * 8 + clamp((b.y - 60) / 400, -1, 1) * 2;
    } else {
      pupils.forEach(p => { p.style.transform = 'translate(0,0) scale(1.06)'; });   // looking straight at you
    }
    head.style.transform = `rotate(${tilt.toFixed(2)}deg)`;
    if (pointing) {
      const el = target();
      if (el) {
        const r = rectOf(el), b = toBox({x: r.left + Math.min(r.width, 420) / 2, y: r.top + Math.min(r.height, 200) / 2});
        const deg = Math.atan2(b.y - 112, b.x - 42) * 180 / Math.PI;      // arm hangs at 90°
        armL.style.transform = `rotate(${clamp(deg - 90, 25, 165).toFixed(1)}deg)`;
      }
    } else {
      armL.style.transform = `rotate(${state === 'thinking' ? 0 : 6}deg)`;
    }
    if (!root.classList.contains('wave')) armR.style.transform = `rotate(${state === 'thinking' ? -28 : -6}deg)`;  // hand to "chin" while thinking
  }

  function blinkLoop() {
    clearTimeout(blinkTimer);
    blinkTimer = setTimeout(() => {
      eyeGroups.forEach(e => { e.classList.remove('blink'); void e.getBBox(); e.classList.add('blink'); });
      if (Math.random() < .25) setTimeout(() => eyeGroups.forEach(e => { e.classList.remove('blink'); void e.getBBox(); e.classList.add('blink'); }), 220);
      blinkLoop();
    }, rand(2400, 5200));
  }

  function anim(cls, ms) {
    root.classList.remove(cls); void root.offsetWidth; root.classList.add(cls);
    return new Promise(res => setTimeout(() => { root.classList.remove(cls); res(); }, reduced.matches ? 10 : ms));
  }

  function mood(cls, ms) {
    clearTimeout(moodTimer);
    root.classList.remove('happy', 'sad', 'alarm');
    if (cls) { root.classList.add(cls); if (ms) moodTimer = setTimeout(() => root.classList.remove(cls), ms); }
  }

  // ---------------------------------------------------------------- public API
  async function summon() {
    build();
    if (state !== 'hidden' && !root.classList.contains('leave')) return;
    root.classList.remove('leave');
    root.hidden = false;
    place();
    state = 'idle';
    root.classList.add('idle');
    cancelAnimationFrame(raf); raf = requestAnimationFrame(tick);
    blinkLoop(); setGaze('you', 900);
    await anim('enter', 950);
  }

  async function hide() {
    if (!root || state === 'hidden') return;
    stopSpeaking(); clearInterval(msgTimer); clearTimeout(gazeTimer); clearTimeout(blinkTimer);
    bubble.classList.remove('show');
    pointing = false;
    await anim('leave', 550);
    root.hidden = true; state = 'hidden';
    root.classList.remove('thinking', 'idle', 'happy', 'sad', 'speaking');
    lookedEl?.classList.remove('rd-looking'); lookedEl = null;
    cancelAnimationFrame(raf);
  }

  function say(html, actions = [], opts = {}) {
    build();
    clearInterval(msgTimer);
    textEl.innerHTML = html;
    bubble.classList.remove('alert');
    actsEl.innerHTML = '';
    actions.forEach(a => {
      const b = document.createElement('button');
      b.type = 'button';
      if (a.primary) b.className = 'primary';
      b.innerHTML = (a.icon ? `<i class="bi bi-${esc(a.icon)}"></i>` : '') + esc(a.label);
      b.addEventListener('click', ev => { ev.stopPropagation(); a.onClick?.(); });
      actsEl.appendChild(b);
    });
    bubble.classList.add('show');
    if (opts.timeout) setTimeout(() => { if (textEl.innerHTML === html) bubble.classList.remove('show'); }, opts.timeout);
  }

  function think(messages = ['Thinking']) {
    build();
    state = 'thinking';
    pointing = false;
    mood(null);
    root.classList.add('thinking');
    let i = 0;
    const show = () => { say(`<span class="dots">${esc(messages[i % messages.length])}</span>`); i++; };
    show();
    clearInterval(msgTimer);
    msgTimer = setInterval(() => { textEl.innerHTML = `<span class="dots">${esc(messages[i % messages.length])}</span>`; i++; }, 2600);
    setGaze('summary', 1200);
  }

  async function done(html, actions = []) {
    build();
    clearInterval(msgTimer);
    root.classList.remove('thinking');
    state = 'idle';
    mood('happy', 2600);
    pointing = true;
    setTimeout(() => { pointing = false; }, 5200);
    say(html, actions);
    bubble.classList.remove('alert');
    setGaze('summary', 2400);
    root.classList.add('wave');
    setTimeout(() => root.classList.remove('wave'), 2300);
    await anim('hop', 600);
  }

  function fail(html, actions = []) {
    build();
    clearInterval(msgTimer);
    root.classList.remove('thinking');
    state = 'idle';
    mood('sad', 4000);
    say(html, actions);
  }

  // a serious warning: wide eyes, steady red light, a shake and a red-edged bubble
  async function alert(html, actions = []) {
    build();
    clearInterval(msgTimer);
    root.classList.remove('thinking');
    state = 'idle';
    mood('alarm', 5000);
    pointing = true;
    setTimeout(() => { pointing = false; }, 4000);
    say(html, actions);
    bubble.classList.add('alert');
    setGaze('summary', 3000);
    await anim('shake', 520);
  }

  // ---------------------------------------------------------------- information card (facts, AI answer, pictures)
  let card = null, cardOpts = {}, lightbox = null;
  function closeCard() { card?.remove(); card = null; root?.classList.remove('has-card'); }
  function openLightbox(img) {
    lightbox?.remove();
    lightbox = document.createElement('div');
    lightbox.className = 'rd-lightbox';
    lightbox.setAttribute('role', 'dialog');
    lightbox.setAttribute('aria-label', img.caption || 'Picture');
    lightbox.innerHTML = `<figure><img src="${esc(img.full)}" alt="${esc(img.caption)}" referrerpolicy="no-referrer">
      <figcaption>${esc(img.caption)}<span>${esc(img.credit || '')} · <a href="${esc(img.page)}" target="_blank" rel="noopener noreferrer">${esc(img.source)} <i class="bi bi-box-arrow-up-right"></i></a>
      · check the licence on the source before reusing</span></figcaption></figure><button type="button" class="rd-lightbox-x" aria-label="Close picture"><i class="bi bi-x-lg"></i></button>`;
    const close = () => { lightbox?.remove(); lightbox = null; };
    lightbox.addEventListener('click', e => { if (e.target === lightbox || e.target.closest('.rd-lightbox-x')) close(); });
    document.addEventListener('keydown', function k(e) { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', k); } });
    document.body.appendChild(lightbox);
    lightbox.querySelector('.rd-lightbox-x').focus();
  }
  function renderCard() {
    const o = cardOpts, lvl = {danger: 'exclamation-octagon-fill', warn: 'exclamation-triangle-fill', info: 'info-circle'};
    card.querySelector('.rd-card-title').textContent = o.title || 'Dr. Flow';
    card.querySelector('.rd-card-sub').textContent = o.subtitle || '';
    card.querySelector('.rd-card-warn').innerHTML = (o.warnings || []).map(w => `<div class="rd-w ${esc(w.level)}"><i class="bi bi-${lvl[w.level] || 'info-circle'}"></i>
      <div><b>${esc(w.title)}</b><span>${esc(w.detail)}</span>${w.basis ? `<small>${esc(w.basis)}</small>` : ''}</div></div>`).join('');
    card.querySelector('.rd-card-facts').innerHTML = (o.facts || []).map(f => `<dt>${esc(f.label)}</dt><dd>${esc(f.value)}</dd>`).join('');
    const ai = card.querySelector('.rd-card-ai');
    ai.innerHTML = o.ai === 'loading' ? '<p class="rd-load"><span class="spinner-border spinner-border-sm"></span> Asking the AI, with trusted medical sites…</p>'
      : o.ai === 'html' ? `<div class="rd-ai-label"><i class="bi bi-stars"></i> AI explanation${o.model ? ` · ${esc(o.model)}` : ''}</div>${o.html}`
      : o.ai === 'error' ? `<p class="rd-err"><i class="bi bi-wifi-off"></i> The AI could not answer this time. ${esc(o.error || '')}</p>`
      : o.ai === 'off' ? '<p class="rd-note">AI is not connected on this server, so you see the hospital\'s own facts and the rule checks only.</p>' : '';
    const imgs = card.querySelector('.rd-card-imgs');
    imgs.innerHTML = o.images === 'loading' ? '<p class="rd-load"><span class="spinner-border spinner-border-sm"></span> Finding pictures from the sources…</p>'
      : Array.isArray(o.images) && o.images.length ? `<div class="rd-ai-label"><i class="bi bi-images"></i> Pictures from the sources</div><div class="rd-gallery">${o.images.map((im, i) =>
          `<button type="button" data-img="${i}" title="${esc(im.caption)}"><img src="${esc(im.thumb)}" alt="${esc(im.caption)}" loading="lazy" referrerpolicy="no-referrer"><span>${esc(im.source)}</span></button>`).join('')}</div>`
      : Array.isArray(o.images) ? '<p class="rd-note">No pictures found for this in the open sources.</p>' : '';
    imgs.querySelectorAll('[data-img]').forEach(b => b.addEventListener('click', () => openLightbox(o.images[+b.dataset.img])));
    imgs.querySelectorAll('img').forEach(im => im.addEventListener('error', () => im.closest('button')?.remove()));
    card.querySelector('.rd-card-src').innerHTML = (o.sources || []).length ? `<div class="rd-ai-label"><i class="bi bi-link-45deg"></i> Sources</div><ol>${o.sources.map(s =>
      `<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title || s.url)}</a></li>`).join('')}</ol>` : '';
    const form = card.querySelector('.rd-card-ask');
    form.hidden = !o.onAsk;
    form.querySelector('input').placeholder = o.askPlaceholder || 'Ask a follow-up question…';
  }
  function showCard(opts) {
    build();
    cardOpts = {...opts};
    if (!card) {
      card = document.createElement('section');
      card.className = 'rd-card';
      card.setAttribute('role', 'dialog');
      card.setAttribute('aria-label', 'Dr. Flow');
      card.innerHTML = `<header><div><b class="rd-card-title"></b><span class="rd-card-sub"></span></div>
        <button type="button" class="rd-card-x" aria-label="Close"><i class="bi bi-x-lg"></i></button></header>
        <div class="rd-card-body"><div class="rd-card-warn"></div><dl class="rd-card-facts"></dl><div class="rd-card-imgs"></div>
        <div class="rd-card-ai gd-ai-text"></div><div class="rd-card-src"></div></div>
        <form class="rd-card-ask"><input type="text" maxlength="400" aria-label="Question for Dr. Flow"><button type="submit" class="btn btn-sm btn-primary"><i class="bi bi-send"></i>Ask</button></form>`;
      card.querySelector('.rd-card-x').addEventListener('click', closeCard);
      card.querySelector('.rd-card-ask').addEventListener('submit', e => {
        e.preventDefault();
        const q = e.target.querySelector('input').value.trim();
        if (q.length < 3) return;
        e.target.querySelector('input').value = '';
        try { cardOpts.onAsk?.(q); } catch { say('That form was closed. Ask me again from the page.'); }
      });
      root.appendChild(card);
    }
    root.classList.add('has-card');
    renderCard();
    card.scrollTop = 0;
    if (opts.focusInput) setTimeout(() => card.querySelector('.rd-card-ask input')?.focus(), 50);
    return {update(more) { if (card) { Object.assign(cardOpts, more); renderCard(); } }, close: closeCard, get open() { return !!card; }};
  }

  // ---------------------------------------------------------------- reading aloud (the trace mouth beats as it talks)
  function stopSpeaking() {
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    root?.classList.remove('speaking');
  }

  function speak(text) {
    if (!('speechSynthesis' in window)) { say('Your browser cannot read aloud. The summary is highlighted on the page.'); return; }
    stopSpeaking();
    const clean = String(text).replace(/https?:\/\/\S+/g, '').replace(/\[[^\]]*\]/g, '').replace(/[#*_`>]/g, '').replace(/\s+/g, ' ').trim();
    if (!clean) return;
    const voices = speechSynthesis.getVoices();
    const voice = voices.find(v => /en[-_](GB|GH|NG|ZA)/i.test(v.lang)) || voices.find(v => /^en/i.test(v.lang));
    const parts = clean.match(/[^.!?]+[.!?]*/g) || [clean];     // short chunks: some browsers stop long utterances
    root.classList.add('speaking');
    setGaze('you', 4000);
    parts.forEach((p, i) => {
      const u = new SpeechSynthesisUtterance(p.trim());
      if (voice) u.voice = voice;
      u.rate = 1; u.pitch = 1.05;
      if (i === parts.length - 1) { u.onend = u.onerror = () => root.classList.remove('speaking'); }
      speechSynthesis.speak(u);
    });
  }

  window.RoboDoc = {
    summon, hide, think, done, fail, say, speak, stopSpeaking, alert, card: showCard, closeCard, trackFrame,
    focus(fn) { focusFn = typeof fn === 'function' ? fn : () => fn; },
    get state() { return state; },
  };

  // ---------------------------------------------------------------- lab request page: the guidance panel
  function guidance() {
    const host = document.getElementById('guidance');
    if (!host) return;
    const RD = window.RoboDoc;
    RD.focus(() => host.querySelector('#gd-ai .gd-ai-text, #gd-ai .gd-busy, #gd-ai'));
    const THINK = ['Reading the de-identified results', 'Comparing hospital and WHO ranges', 'Checking what clinicians here did next',
                   'Looking up trusted guidance', 'Weighing malaria, sickle cell and the usual suspects', 'Writing your summary'];
    let last = null, engaged = false;

    const summaryText = () => {
      const el = host.querySelector('#gd-ai .gd-ai-text');
      if (!el) return '';
      const c = el.cloneNode(true);
      c.querySelectorAll('.gd-adopt-hint').forEach(x => x.remove());
      const hs = [...c.querySelectorAll('h4')];
      if (hs.length > 2) { let n = hs[2]; while (n) { const nx = n.nextSibling; n.remove(); n = nx; } }   // summary + red flags only
      return c.innerText.slice(0, 1400);
    };
    const doneActions = () => {
      const form = document.getElementById('gd-adopt-form');
      return [
        ...(form ? [{label: 'Adopt as report', icon: 'file-earmark-medical', primary: true, onClick: () => form.requestSubmit()}] : []),
        {label: 'Read it to me', icon: 'volume-up', onClick: () => RD.speak(summaryText())},
        {label: 'Show me', icon: 'eye', onClick: () => host.querySelector('#gd-ai .gd-ai-text')?.scrollIntoView({behavior: 'smooth', block: 'center'})},
      ];
    };
    const greet = st => {
      if (st === 'busy') RD.think(THINK);
      else if (st === 'done') RD.done('Here is the summary. Tap it to adopt it as your report, then edit and sign.', doneActions());
      else if (st === 'failed') RD.fail('The AI did not answer last time. Try asking again.');
      else if (st === 'off') RD.say('AI is not connected on this server yet. An administrator can switch it on.');
      else RD.say('Hello, I am Dr. Flow. Press <b>Ask AI</b> and I will read these results, compare them with hospital and WHO ranges, and draft next steps for you.');
    };

    function sync() {
      const sec = host.querySelector('#gd-ai');
      if (!sec) return;
      const st = sec.dataset.aiState, key = `${st}:${sec.dataset.aiId || ''}`;
      if (key === last) return;
      last = key;
      if (st === 'busy') { engaged = true; RD.summon().then(() => { if (RD.state !== 'thinking') RD.think(THINK); }); }
      else if (engaged && (st === 'done' || st === 'failed')) RD.summon().then(() => greet(st));
    }
    new MutationObserver(sync).observe(host, {childList: true});
    document.addEventListener('robodoc:dismissed', () => { engaged = false; });
    sync();

    document.addEventListener('click', e => {
      if (e.target.closest('[data-ai-ask]')) { engaged = true; RD.summon().then(() => RD.think(THINK)); }
      else if (e.target.closest('[data-robodoc-call]')) {
        engaged = true;
        RD.summon().then(() => greet(host.querySelector('#gd-ai')?.dataset.aiState));
      }
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', guidance); else guidance();
})();
