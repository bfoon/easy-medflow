/* E-sign in the browser.
   MFPdf: draws PDF pages (pdf.js, served locally) with an overlay layer per page; positions are fractions of the page.
   Prepare (#prepare-boot): place, move, resize fields for each recipient; auto-place; save; send.
   Sign (#sign-boot): guided field-by-field signing, adopt a signature (draw / type / upload), reading tracker,
   in-person mode with an identity check, approve, decline. */
(() => {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const $ = s => document.querySelector(s);
  const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  const post = async (url, body) => {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()}, credentials: 'same-origin', body: JSON.stringify(body)});
    const d = await r.json().catch(() => ({ok: false, error: `The server answered ${r.status}.`}));
    if (!r.ok || d.ok === false) throw new Error(d.error || 'Something went wrong.');
    return d;
  };
  const toast = (m, bad) => { const t = $('#es-toast'); if (!t) return alert(m); t.textContent = m; t.className = `fd-toast show${bad ? ' bad' : ''}`; clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 4000); };
  const KIND_LABEL = {signature: 'Sign', initials: 'Initial', date_signed: 'Date', full_name: 'Name', text: 'Text', checkbox: '✓', choice: 'Choose'};
  const KIND_ICON = {signature: 'bi-pen', initials: 'bi-type', date_signed: 'bi-calendar-check', full_name: 'bi-person', text: 'bi-input-cursor-text', checkbox: 'bi-check2-square', choice: 'bi-menu-button-wide'};

  /* ---------------------------------------------------------------- PDF pages */
  const MFPdf = {
    async mount(host, url, sizes, onPage) {
      const lib = window.pdfjsLib;
      lib.GlobalWorkerOptions.workerSrc = host.dataset.worker;
      const doc = await lib.getDocument({url, withCredentials: true, isEvalSupported: false}).promise;
      host.innerHTML = ''; host.classList.remove('loading');
      const pages = [];
      for (let i = 1; i <= doc.numPages; i++) {
        const [w, h] = sizes[i - 1] || [612, 792];
        const pg = document.createElement('div');
        pg.className = 'es-page'; pg.dataset.page = i; pg.style.aspectRatio = `${w} / ${h}`;
        pg.innerHTML = `<canvas aria-hidden="true"></canvas><div class="es-layer" data-page="${i}"></div><span class="es-pno">Page ${i} of ${doc.numPages}</span>`;
        host.appendChild(pg); pages.push(pg);
      }
      const drawn = new Set();
      const draw = async pg => {
        const i = +pg.dataset.page; if (drawn.has(i)) return; drawn.add(i);
        const page = await doc.getPage(i), base = page.getViewport({scale: 1}), ratio = window.devicePixelRatio || 1;
        const scale = pg.clientWidth / base.width * ratio, vp = page.getViewport({scale});
        const c = pg.querySelector('canvas'); c.width = vp.width; c.height = vp.height;
        await page.render({canvasContext: c.getContext('2d'), viewport: vp}).promise;
      };
      const io = new IntersectionObserver(ents => ents.forEach(e => { if (e.isIntersecting) { draw(e.target); onPage && e.intersectionRatio > .55 && onPage(+e.target.dataset.page); } }), {threshold: [0, .6]});
      pages.forEach(p => io.observe(p));
      return {doc, pages, layer: i => host.querySelector(`.es-layer[data-page="${i}"]`)};
    },
  };
  window.MFPdf = MFPdf;

  /* ================================================================ prepare */
  const pb = document.getElementById('prepare-boot');
  if (pb) (async () => {
    const boot = JSON.parse(pb.textContent);
    const signers = boot.recipients.filter(r => r.fields);
    let fields = boot.fields.map((f, i) => ({...f, _id: `f${i}`})), cur = signers[0] ? signers[0].id : null, sel = null, placing = null, seq = fields.length;
    const rc = id => boot.recipients.find(r => r.id === id) || {};
    $('#pp-recips').innerHTML = signers.map(r => `<button type="button" data-r="${r.id}" style="--c:${r.color}"><i></i>${esc(r.name)}<small>${r.role.replace('_', ' ')} · order ${r.order}</small></button>`).join('') || '<p class="small muted">Nobody here needs fields (copies and approvers do not sign).</p>';
    $('#pp-kinds').innerHTML = Object.entries(boot.kinds).map(([k, l]) => `<button type="button" data-k="${k}" draggable="true"><i class="bi ${KIND_ICON[k]}"></i>${esc(l)}</button>`).join('');
    const pdf = await MFPdf.mount($('#pp-pages'), boot.pdf, boot.sizes);
    function drawFields() {
      document.querySelectorAll('.es-layer').forEach(l => l.innerHTML = '');
      for (const f of fields) {
        const r = rc(f.recipient), l = pdf.layer(f.page); if (!l) continue;
        l.insertAdjacentHTML('beforeend', `<div class="es-f k-${f.kind} ${sel === f._id ? 'sel' : ''}" data-id="${f._id}" tabindex="0" style="left:${f.x * 100}%;top:${f.y * 100}%;width:${f.w * 100}%;height:${f.h * 100}%;--c:${r.color}" title="${esc(r.name)}: ${esc(boot.kinds[f.kind])}">
          <span><i class="bi ${KIND_ICON[f.kind]}"></i>${f.kind === 'checkbox' ? '' : esc(f.label || KIND_LABEL[f.kind])}${f.required ? '' : ' <em>optional</em>'}</span><b class="es-grip" aria-hidden="true"></b></div>`);
      }
      document.querySelectorAll('#pp-recips [data-r]').forEach(b => { b.classList.toggle('on', +b.dataset.r === cur); b.querySelector('small').textContent = `${fields.filter(f => f.recipient === +b.dataset.r).length} field(s) · order ${rc(+b.dataset.r).order}`; });
      const missing = signers.filter(r => !fields.some(f => f.recipient === r.id && ['signature', 'initials'].includes(f.kind)));
      $('#pp-check').innerHTML = missing.length ? `<i class="bi bi-exclamation-triangle-fill"></i>${missing.map(r => esc(r.name)).join(', ')} still need${missing.length === 1 ? 's' : ''} a signature field.` : '<i class="bi bi-check-circle-fill"></i>Everyone who signs has a signature field.';
      $('#pp-check').className = missing.length ? 'pp-check bad' : 'pp-check ok';
      $('#pp-send').disabled = !!missing.length;
      inspector();
    }
    function inspector() {
      const f = fields.find(x => x._id === sel), box = $('#pp-insp');
      if (!f) { box.innerHTML = '<p class="small muted">Pick a person, then a field type, then click on the page where it goes. Drag fields to move them; drag the corner to resize.</p>'; return; }
      box.innerHTML = `<h4>${esc(boot.kinds[f.kind])}</h4><label>For<select class="form-select form-select-sm" data-fp="recipient">${signers.map(r => `<option value="${r.id}" ${r.id === f.recipient ? 'selected' : ''}>${esc(r.name)}</option>`).join('')}</select></label>
        ${['text', 'checkbox', 'choice'].includes(f.kind) ? `<label>Label / question<input class="form-control form-control-sm" data-fp="label" value="${esc(f.label)}"></label>` : ''}
        ${f.kind === 'choice' ? `<label>Options, one per line<textarea class="form-control form-control-sm" rows="3" data-fp="options">${esc((f.options || []).join('\n'))}</textarea></label>` : ''}
        ${['text', 'checkbox', 'choice'].includes(f.kind) ? `<label class="fd-chk"><input type="checkbox" data-fp="required" ${f.required ? 'checked' : ''}>Required</label>` : ''}
        <button type="button" class="btn btn-sm btn-ghost" id="pp-del"><i class="bi bi-trash"></i>Remove field</button>`;
    }
    $('#pp-insp').addEventListener('input', ev => { const f = fields.find(x => x._id === sel), p = ev.target.dataset.fp; if (!f || !p) return; f[p] = p === 'recipient' ? +ev.target.value : p === 'required' ? ev.target.checked : p === 'options' ? ev.target.value.split('\n').map(x => x.trim()).filter(Boolean) : ev.target.value; dirty(); if (p !== 'label' && p !== 'options') drawFields(); });
    $('#pp-insp').addEventListener('click', ev => { if (ev.target.closest('#pp-del')) { fields = fields.filter(x => x._id !== sel); sel = null; dirty(); drawFields(); } });
    $('#pp-recips').addEventListener('click', ev => { const b = ev.target.closest('[data-r]'); if (b) { cur = +b.dataset.r; drawFields(); } });
    $('#pp-kinds').addEventListener('click', ev => { const b = ev.target.closest('[data-k]'); if (!b || !cur) return; placing = b.dataset.k; document.body.classList.add('es-placing'); $('#pp-hint').textContent = `Click on the page to place “${boot.kinds[placing]}” for ${rc(cur).name}. Esc to cancel.`; });
    $('#pp-kinds').addEventListener('dragstart', ev => { const b = ev.target.closest('[data-k]'); if (b) ev.dataTransfer.setData('text/es-kind', b.dataset.k); });
    const place = (kind, layer, cx, cy) => {
      const r = layer.getBoundingClientRect(), [w, h] = boot.sizes_default[kind];
      const f = {_id: `f${++seq}`, recipient: cur, kind, page: +layer.dataset.page, w, h, x: Math.max(0, Math.min(1 - w, (cx - r.left) / r.width - w / 2)), y: Math.max(0, Math.min(1 - h, (cy - r.top) / r.height - h / 2)), required: kind !== 'checkbox', label: '', options: kind === 'choice' ? ['Yes', 'No'] : []};
      fields.push(f); sel = f._id; dirty(); drawFields();
    };
    $('#pp-pages').addEventListener('dragover', ev => { if (ev.dataTransfer.types.includes('text/es-kind')) ev.preventDefault(); });
    $('#pp-pages').addEventListener('drop', ev => { const k = ev.dataTransfer.getData('text/es-kind'), l = ev.target.closest('.es-page')?.querySelector('.es-layer'); if (k && l && cur) { ev.preventDefault(); place(k, l, ev.clientX, ev.clientY); } });
    $('#pp-pages').addEventListener('click', ev => {
      const l = ev.target.closest('.es-page')?.querySelector('.es-layer');
      if (placing && l) { place(placing, l, ev.clientX, ev.clientY); placing = null; document.body.classList.remove('es-placing'); $('#pp-hint').textContent = ''; return; }
      const fe = ev.target.closest('.es-f'); sel = fe ? fe.dataset.id : null; if (fe) cur = fields.find(x => x._id === sel).recipient; drawFields();
    });
    // move / resize
    $('#pp-pages').addEventListener('pointerdown', ev => {
      const fe = ev.target.closest('.es-f'); if (!fe || placing) return;
      ev.preventDefault();
      const f = fields.find(x => x._id === fe.dataset.id), layer = fe.parentNode, r = layer.getBoundingClientRect(), resize = ev.target.classList.contains('es-grip');
      const start = {x: ev.clientX, y: ev.clientY, fx: f.x, fy: f.y, fw: f.w, fh: f.h};
      sel = f._id; cur = f.recipient;
      const mv = e => {
        const dx = (e.clientX - start.x) / r.width, dy = (e.clientY - start.y) / r.height;
        if (resize) { f.w = Math.max(.02, Math.min(1 - f.x, start.fw + dx)); f.h = Math.max(.012, Math.min(1 - f.y, start.fh + dy)); }
        else { f.x = Math.max(0, Math.min(1 - f.w, start.fx + dx)); f.y = Math.max(0, Math.min(1 - f.h, start.fy + dy)); }
        Object.assign(fe.style, {left: f.x * 100 + '%', top: f.y * 100 + '%', width: f.w * 100 + '%', height: f.h * 100 + '%'});
      };
      const up = () => { document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up); dirty(); drawFields(); };
      document.addEventListener('pointermove', mv); document.addEventListener('pointerup', up);
    });
    document.addEventListener('keydown', ev => {
      if (ev.key === 'Escape') { placing = null; document.body.classList.remove('es-placing'); $('#pp-hint').textContent = ''; }
      if ((ev.key === 'Delete' || ev.key === 'Backspace') && sel && !ev.target.matches('input,textarea,select')) { fields = fields.filter(x => x._id !== sel); sel = null; dirty(); drawFields(); }
      const f = fields.find(x => x._id === sel);
      if (f && ev.key.startsWith('Arrow') && !ev.target.matches('input,textarea,select')) { ev.preventDefault(); const s = ev.shiftKey ? .01 : .002; if (ev.key === 'ArrowLeft') f.x = Math.max(0, f.x - s); if (ev.key === 'ArrowRight') f.x = Math.min(1 - f.w, f.x + s); if (ev.key === 'ArrowUp') f.y = Math.max(0, f.y - s); if (ev.key === 'ArrowDown') f.y = Math.min(1 - f.h, f.y + s); dirty(); drawFields(); }
    });
    $('#pp-auto').onclick = () => {
      const last = boot.pages;
      signers.forEach((r, i) => { if (fields.some(f => f.recipient === r.id && f.kind === 'signature')) return; const y = Math.min(.9, .62 + i * .085);
        fields.push({_id: `f${++seq}`, recipient: r.id, kind: 'signature', page: last, x: .08, y, w: .3, h: .055, required: true}, {_id: `f${++seq}`, recipient: r.id, kind: 'date_signed', page: last, x: .7, y: y + .02, w: .2, h: .03, required: true}); });
      dirty(); drawFields(); pdf.pages[last - 1].scrollIntoView({behavior: 'smooth', block: 'center'});
    };
    let isDirty = false; const dirty = () => { isDirty = true; $('#pp-dirty').hidden = false; };
    const payload = () => fields.map(({_id, id, ...f}) => f);
    $('#pp-save').onclick = async () => { try { await post(boot.save_url, {fields: payload()}); isDirty = false; $('#pp-dirty').hidden = true; toast('Fields saved.'); } catch (e) { toast(e.message, true); } };
    $('#pp-send').onclick = async () => { const b = $('#pp-send'); b.disabled = true; try { const d = await post(boot.save_url, {fields: payload(), send: true}); isDirty = false; location.href = d.url; } catch (e) { toast(e.message, true); b.disabled = false; } };
    window.addEventListener('beforeunload', ev => { if (isDirty) { ev.preventDefault(); ev.returnValue = ''; } });
    drawFields();
  })();

  /* ================================================================ sign */
  const sb = document.getElementById('sign-boot');
  if (sb) (async () => {
    const boot = JSON.parse(sb.textContent);
    const done = ['signed', 'approved', 'declined', 'copied'].includes(boot.status) || boot.env_status !== 'sent';
    let sig = boot.saved_signature || '', ini = boot.saved_initials || '', values = {}, seen = new Set(boot.pages_seen || []), seenTimer = null;
    boot.fields.forEach(f => { if (f.kind === 'checkbox') values[f.id] = f.value === 'yes'; else if (['text', 'choice'].includes(f.kind)) values[f.id] = f.value || ''; });
    const today = new Date().toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'});   // same as the sealed PDF
    const pdf = await MFPdf.mount($('#sg-pages'), boot.pdf, boot.sizes, p => {
      if (done || seen.has(p)) return; seen.add(p); progress();
      clearTimeout(seenTimer); seenTimer = setTimeout(() => post(boot.act_url, {action: 'viewed', pages: [...seen]}).catch(() => {}), 700);
    });
    const isFilled = f => f.kind === 'signature' ? !!f._signed : f.kind === 'initials' ? !!f._signed : ['date_signed', 'full_name'].includes(f.kind) ? true : f.kind === 'checkbox' ? !!values[f.id] : !!String(values[f.id] || '').trim();
    const todo = () => boot.fields.filter(f => f.required && !isFilled(f));
    function drawFields() {
      document.querySelectorAll('.es-layer').forEach(l => l.innerHTML = '');
      for (const o of boot.others) {
        const l = pdf.layer(o.page); if (!l) continue;
        l.insertAdjacentHTML('beforeend', `<div class="es-o ${o.value ? 'filled' : ''}" style="left:${o.x * 100}%;top:${o.y * 100}%;width:${o.w * 100}%;height:${o.h * 100}%;--c:${o.color}" title="${esc(o.name)}">${o.image ? `<img src="${esc(o.image)}" alt="Signature of ${esc(o.name)}">` : o.value ? `<span>${esc(o.kind === 'checkbox' ? '✓' : o.value)}</span>` : `<span class="muted">${esc(o.name)}</span>`}</div>`);
      }
      for (const f of boot.fields) {
        const l = pdf.layer(f.page); if (!l) continue;
        const filled = done ? !!f.value : isFilled(f);
        let inner;
        if (f.kind === 'signature' || f.kind === 'initials') { const img = f.kind === 'signature' ? sig : ini; inner = (done ? f.value : f._signed) && img ? `<img src="${esc(img)}" alt="Your ${f.kind}">` : `<span><i class="bi bi-pen"></i>${f.kind === 'signature' ? 'Sign here' : 'Initial'}</span>`; }
        else if (f.kind === 'date_signed') inner = `<span>${esc(done ? f.value : today)}</span>`;
        else if (f.kind === 'full_name') inner = `<span>${esc(boot.name)}</span>`;
        else if (f.kind === 'checkbox') inner = `<input type="checkbox" data-fid="${f.id}" ${values[f.id] ? 'checked' : ''} ${done ? 'disabled' : ''} aria-label="${esc(f.label || 'Tick')}">`;
        else if (f.kind === 'choice') inner = `<select data-fid="${f.id}" ${done ? 'disabled' : ''} aria-label="${esc(f.label || 'Choose')}"><option value=""></option>${f.options.map(o => `<option ${o === values[f.id] ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
        else inner = `<input data-fid="${f.id}" value="${esc(values[f.id])}" placeholder="${esc(f.label || 'Type here')}" ${done ? 'disabled' : ''} aria-label="${esc(f.label || 'Text')}">`;
        l.insertAdjacentHTML('beforeend', `<div class="es-m k-${f.kind} ${filled ? 'filled' : ''} ${f.required ? 'req' : ''}" data-id="${f.id}" tabindex="0" style="left:${f.x * 100}%;top:${f.y * 100}%;width:${f.w * 100}%;height:${f.h * 100}%;--c:${boot.color}">${inner}</div>`);
      }
      progress();
    }
    function progress() {
      if (done) return;
      const t = todo(), total = boot.fields.filter(f => f.required).length;
      $('#sg-count').textContent = t.length ? `${t.length} of ${total} left` : 'All fields done';
      $('#sg-ring').style.setProperty('--p', total ? (total - t.length) / total : 1);
      $('#sg-next').innerHTML = t.length ? `${boot.fields.length && t.length === total ? 'Start' : 'Next'}<i class="bi bi-arrow-down ms-1"></i>` : 'Finish<i class="bi bi-check2 ms-1"></i>';
      if (boot.require_full_read) { const n = seen.size; $('#sg-read').hidden = false; $('#sg-read').innerHTML = n >= boot.pages ? '<i class="bi bi-check-circle-fill"></i>You have seen every page' : `<i class="bi bi-book"></i>Read every page before finishing: ${n} of ${boot.pages}`; }
      $('#sg-finish').disabled = !!t.length || (boot.require_full_read && seen.size < boot.pages);
    }
    $('#sg-next').onclick = () => {
      const t = todo();
      if (!t.length) { $('#sg-finishbox').scrollIntoView({behavior: 'smooth', block: 'center'}); $('#sg-consent').focus(); return; }
      const f = t[0], pg = pdf.pages[f.page - 1];
      pg.scrollIntoView({behavior: 'smooth', block: 'center'});
      setTimeout(() => { const el = document.querySelector(`.es-m[data-id="${f.id}"]`); el?.classList.add('pulse'); (el?.querySelector('input,select') || el)?.focus({preventScroll: true}); setTimeout(() => el?.classList.remove('pulse'), 1600); }, 450);
    };
    $('#sg-pages').addEventListener('input', ev => { const id = ev.target.dataset.fid; if (!id) return; values[id] = ev.target.type === 'checkbox' ? ev.target.checked : ev.target.value; ev.target.closest('.es-m').classList.toggle('filled', isFilled(boot.fields.find(f => String(f.id) === id))); progress(); });
    $('#sg-pages').addEventListener('click', ev => {
      if (done) return;
      const el = ev.target.closest('.es-m'); if (!el) return;
      const f = boot.fields.find(x => String(x.id) === el.dataset.id);
      if (f.kind === 'signature' || f.kind === 'initials') {
        const have = f.kind === 'signature' ? sig : ini;
        if (have && !f._signed) { f._signed = true; drawFields(); }
        else adopt(f.kind, () => { f._signed = true; drawFields(); });
      }
    });
    $('#sg-pages').addEventListener('keydown', ev => { if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.classList.contains('es-m')) { ev.preventDefault(); ev.target.click(); } });

    /* ----- adopt a signature */
    function adopt(kind, then) {
      const m = $('#sg-adopt'), initials = boot.name.split(/\s+/).map(x => x[0]).join('').slice(0, 3).toUpperCase();
      m.hidden = false; m.querySelector('h2').textContent = kind === 'signature' ? 'Adopt your signature' : 'Adopt your initials';
      $('#sg-typed').value = kind === 'signature' ? boot.name : initials;
      let mode = 'draw', inked = false, upload = null;
      const tabs = m.querySelectorAll('[data-mode]'), pad = $('#sg-pad'), g = pad.getContext('2d');
      const setMode = md => { mode = md; tabs.forEach(t => t.setAttribute('aria-selected', t.dataset.mode === md)); m.querySelectorAll('[data-pane]').forEach(p => p.hidden = p.dataset.pane !== md); if (md === 'draw') sizePad(); if (md === 'type') typed(); };
      const sizePad = () => { const r = pad.getBoundingClientRect(), k = window.devicePixelRatio || 1; pad.width = r.width * k; pad.height = r.height * k; g.setTransform(k, 0, 0, k, 0, 0); g.lineCap = g.lineJoin = 'round'; g.strokeStyle = '#0F2C3F'; inked = false; };
      const typed = () => { m.querySelectorAll('.sg-font').forEach(b => { b.textContent = $('#sg-typed').value || initials; }); };
      tabs.forEach(t => t.onclick = () => setMode(t.dataset.mode));
      $('#sg-typed').oninput = typed;
      let font = 'Caveat'; m.querySelectorAll('.sg-font').forEach(b => b.onclick = () => { font = b.dataset.font; m.querySelectorAll('.sg-font').forEach(x => x.setAttribute('aria-pressed', x === b)); });
      // drawing with ink-like width
      let down = false, last = null, lw = 2.6;
      pad.onpointerdown = e => { down = true; const r = pad.getBoundingClientRect(); last = {x: e.clientX - r.left, y: e.clientY - r.top, t: performance.now()}; pad.setPointerCapture(e.pointerId); };
      pad.onpointermove = e => { if (!down) return; const r = pad.getBoundingClientRect(), p = {x: e.clientX - r.left, y: e.clientY - r.top, t: performance.now()}, v = Math.hypot(p.x - last.x, p.y - last.y) / Math.max(1, p.t - last.t);
        lw = lw * .65 + Math.max(1.3, Math.min(4.2, 4.2 - v * 1.7)) * .35; g.lineWidth = lw; g.beginPath(); g.moveTo(last.x, last.y); g.quadraticCurveTo(last.x, last.y, (last.x + p.x) / 2, (last.y + p.y) / 2); g.lineTo(p.x, p.y); g.stroke(); last = p; inked = true; };
      pad.onpointerup = pad.onpointercancel = () => { down = false; };
      $('#sg-clear').onclick = sizePad;
      $('#sg-file').onchange = e => { const f = e.target.files[0]; if (!f) return; if (!/^image\/(png|jpeg)$/.test(f.type) || f.size > 2e6) { toast('Choose a PNG or JPG under 2 MB.', true); return; } const rd = new FileReader(); rd.onload = () => { upload = rd.result; $('#sg-uprev').innerHTML = `<img src="${upload}" alt="Uploaded signature">`; }; rd.readAsDataURL(f); };
      const trim = src => { // crop to the ink and return a PNG data URL
        const c = document.createElement('canvas'), x = c.getContext('2d'); c.width = src.width; c.height = src.height; x.drawImage(src, 0, 0);
        const d = x.getImageData(0, 0, c.width, c.height).data; let t = c.height, l = c.width, b = 0, r = 0;
        for (let y = 0; y < c.height; y++) for (let xx = 0; xx < c.width; xx++) { const a = d[(y * c.width + xx) * 4 + 3], lum = d[(y * c.width + xx) * 4]; if (a > 20 && lum < 235) { if (y < t) t = y; if (y > b) b = y; if (xx < l) l = xx; if (xx > r) r = xx; } }
        if (r <= l) return null;
        const out = document.createElement('canvas'), pad2 = 8; out.width = r - l + pad2 * 2; out.height = b - t + pad2 * 2; out.getContext('2d').drawImage(c, l - pad2, t - pad2, out.width, out.height, 0, 0, out.width, out.height);
        const max = 600; if (out.width > max) { const s = document.createElement('canvas'); s.width = max; s.height = Math.round(out.height * max / out.width); s.getContext('2d').drawImage(out, 0, 0, s.width, s.height); return s.toDataURL('image/png'); }
        return out.toDataURL('image/png');
      };
      $('#sg-adopt-ok').onclick = async () => {
        let url = null;
        if (mode === 'draw') { if (!inked) return toast('Draw your signature in the box first.', true); url = trim(pad); }
        else if (mode === 'type') { const text = $('#sg-typed').value.trim(); if (!text) return toast('Type your name first.', true); await document.fonts.load(`64px "${font}"`); const c = document.createElement('canvas'); c.width = 900; c.height = 200; const x = c.getContext('2d'); x.font = `${kind === 'signature' ? 84 : 96}px "${font}"`; x.fillStyle = '#0F2C3F'; x.textBaseline = 'middle'; x.fillText(text, 20, 104); url = trim(c); }
        else { if (!upload) return toast('Choose an image of your signature.', true); const img = new Image(); img.src = upload; await img.decode(); const c = document.createElement('canvas'); c.width = img.width; c.height = img.height; const x = c.getContext('2d'); x.fillStyle = '#fff'; x.drawImage(img, 0, 0); url = trim(c); }
        if (!url) return toast('Nothing to adopt yet.', true);
        if (kind === 'signature') sig = url; else ini = url;
        m.hidden = true; then();
        // other fields of the same kind get the same image once clicked; initials are offered automatically
        if (kind === 'signature' && !ini && boot.fields.some(f => f.kind === 'initials')) { const c = document.createElement('canvas'); c.width = 400; c.height = 160; const x = c.getContext('2d'); x.font = `96px "${font}"`; x.fillStyle = '#0F2C3F'; x.textBaseline = 'middle'; x.fillText(initials, 10, 84); ini = trim(c) || ''; }
      };
      $('#sg-adopt-cancel').onclick = () => { m.hidden = true; };
      setMode('draw');
    }

    /* ----- finish / approve / decline */
    if (!done) {
      $('#sg-finish').onclick = async () => {
        if (!$('#sg-consent').checked) { toast('Tick the box to agree to sign electronically.', true); return; }
        const b = $('#sg-finish'); b.disabled = true; b.classList.add('busy');
        try {
          const d = await post(boot.act_url, boot.role === 'approver' ? {action: 'approve', consent: true} : {action: 'sign', consent: true, signature: sig, initials: ini, values, identity_check: $('#sg-identity')?.value || ''});
          finished(d);
        } catch (e) { toast(e.message, true); b.disabled = false; b.classList.remove('busy'); }
      };
      $('#sg-decline').onclick = () => { $('#sg-declinebox').hidden = false; $('#sg-reason').focus(); };
      $('#sg-decline-cancel').onclick = () => { $('#sg-declinebox').hidden = true; };
      $('#sg-decline-ok').onclick = async () => { try { const d = await post(boot.act_url, {action: 'decline', reason: $('#sg-reason').value}); $('#sg-declinebox').hidden = true; finished(d, true); } catch (e) { toast(e.message, true); } };
    }
    function finished(d, declined) {
      $('#sg-bar').hidden = true;
      const box = $('#sg-done'); box.hidden = false;
      box.innerHTML = `<div class="sg-done-icon ${declined ? 'bad' : ''}"><i class="bi ${declined ? 'bi-x-circle' : 'bi-check-circle'}"></i></div>
        <h2>${declined ? 'You declined to sign' : boot.role === 'approver' ? 'Approved' : 'Signed. Thank you.'}</h2>
        <p>${declined ? 'The sender has been told and will be in touch.' : d.envelope === 'completed' ? 'Everyone has now signed. The sealed document is ready.' : 'The next person has been sent the document. You will be told when everyone has signed.'}</p>
        ${d.next ? `<a class="btn btn-primary" href="${esc(d.next)}">${boot.in_person ? 'Hand back to staff' : 'Continue'}</a>` : ''}
        ${d.envelope === 'completed' && !boot.in_person ? `<a class="btn btn-ghost" href="${esc(boot.pdf)}?signed=1">Download the signed copy</a>` : ''}`;
      box.scrollIntoView({behavior: 'smooth'});
    }
    drawFields();
    window.addEventListener('resize', () => { clearTimeout(window._esr); window._esr = setTimeout(drawFields, 200); });
  })();
})();
