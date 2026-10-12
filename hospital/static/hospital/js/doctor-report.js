/* Doctor's report editor: live paper preview, autosave, quick inserts, file drop, AI helpers (with Dr. Flow), and a
   save before signing or downloading so the PDF and ZIP always match what is on screen. */
(() => {
  const ed = document.getElementById('dr-editor');
  const RD = window.RoboDoc;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const data = id => { try { return JSON.parse(document.getElementById(id)?.textContent || 'null'); } catch { return null; } };

  // same Markdown subset as the server's simple_md filter (text escaped first)
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/(^|[^\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])/g, '$1<i>$2</i>')
    .replace(/\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  function md(text) {
    const out = []; let open = null;
    for (const raw of String(text || '').split('\n')) {
      const line = raw.trim(), h = line.match(/^#{1,4}\s+(.*)/), ol = line.match(/^(\d+)[.)]\s+(.*)/), ul = line.match(/^[-*•]\s+(.*)/);
      if (ul && open === 'ol' && /^[ \t]/.test(raw) && out.length && out[out.length - 1].endsWith('</li>')) {
        out[out.length - 1] = out[out.length - 1].slice(0, -5) + `<span class="sub">${inline(ul[1])}</span></li>`; continue;
      }
      const kind = ol ? 'ol' : ul ? 'ul' : null;
      if (open && kind !== open && line) { out.push(`</${open}>`); open = null; }
      if (h) out.push(`<h4>${inline(h[1])}</h4>`);
      else if (kind) { if (!open) { out.push(`<${kind}>`); open = kind; } out.push(`<li>${inline(ol ? ol[2] : ul[1])}</li>`); }
      else if (line) out.push(`<p>${inline(line)}</p>`);
    }
    if (open) out.push(`</${open}>`);
    return out.join('');
  }

  if (!ed) return;   // signed report: read-only page
  const ta = ed.querySelector('.dr-text'), title = ed.querySelector('.dr-title'), paper = ed.querySelector('.dr-paper-body');
  const paperTitle = ed.querySelector('.dr-paper > header b'), stateEl = ed.querySelector('[data-save-state]');
  const follow = document.querySelector('[data-follow]');
  const rows = data('dr-rows') || [];
  const csrf = ed.dataset.csrf;

  // ---------------------------------------------------------------- autosave
  let dirty = new Set(), timer = null, saving = null;
  const render = () => { paper.innerHTML = md(ta.value); paperTitle.textContent = title.value; };
  function includeState() {
    const q = s => document.querySelector(s);
    return JSON.stringify({
      labs: q('[data-inc=labs]')?.checked ?? true, ai_sources: q('[data-inc=ai_sources]')?.checked ?? true,
      images: [...document.querySelectorAll('[data-img]:checked')].map(i => +i.dataset.img),
      attachments: [...document.querySelectorAll('[data-att]:checked')].map(i => +i.dataset.att),
    });
  }
  function mark(field) {
    dirty.add(field);
    stateEl.textContent = 'Editing…'; stateEl.className = '';
    clearTimeout(timer); timer = setTimeout(save, 900);
  }
  async function save() {
    clearTimeout(timer);
    if (saving) await saving;
    if (!dirty.size) return true;
    const body = new URLSearchParams(), fields = [...dirty];
    dirty.clear();
    for (const f of fields) {
      if (f === 'body') body.set('body', ta.value);
      else if (f === 'title') body.set('title', title.value);
      else if (f === 'follow_up') body.set('follow_up', follow?.value || '');
      else if (f === 'include') body.set('include', includeState());
    }
    stateEl.textContent = 'Saving…';
    saving = fetch(ed.dataset.save, {method: 'POST', body, credentials: 'same-origin', headers: {'X-CSRFToken': csrf}})
      .then(async r => {
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.error || 'Not saved');
        stateEl.textContent = `Saved ${j.saved_at}`;
        if (j.edited_pct != null) {
          document.querySelector('[data-edited]').textContent = `${j.edited_pct}%`;
          document.querySelector('.dr-meter-bar i').style.setProperty('--doc', `${j.edited_pct}%`);
        }
        return true;
      })
      .catch(err => { fields.forEach(f => dirty.add(f)); stateEl.innerHTML = `<span class="err"><i class="bi bi-exclamation-triangle"></i> ${esc(err.message)}, retrying</span>`; timer = setTimeout(save, 4000); return false; })
      .finally(() => { saving = null; });
    return saving;
  }
  ta.addEventListener('input', () => { render(); mark('body'); });
  title.addEventListener('input', () => { render(); mark('title'); });
  follow?.addEventListener('change', () => mark('follow_up'));
  document.querySelectorAll('[data-inc],[data-img],[data-att]').forEach(i => i.addEventListener('change', () => mark('include')));
  addEventListener('beforeunload', e => {
    if (!dirty.size) return;
    const body = new URLSearchParams({body: ta.value, title: title.value, include: includeState(), follow_up: follow?.value || ''});
    fetch(ed.dataset.save, {method: 'POST', body, keepalive: true, credentials: 'same-origin', headers: {'X-CSRFToken': csrf}});
    e.preventDefault();
  });
  // save first, then sign or download, so the signed hash and the files match the screen
  const signForm = document.querySelector('[data-sign]');
  signForm?.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = signForm.querySelector('button');
    btn.disabled = true;
    if (await save()) HTMLFormElement.prototype.submit.call(signForm);   // native submit: no second submit event
    else btn.disabled = false;
  });
  document.querySelectorAll('[data-dl]').forEach(a => a.addEventListener('click', async e => {
    if (!dirty.size && !saving) return;
    e.preventDefault();
    if (await save()) location.href = a.href;
  }));

  // ---------------------------------------------------------------- toolbar, inserts, views
  function insert(text, {block = true} = {}) {
    const s = ta.selectionStart, e = ta.selectionEnd, v = ta.value;
    const pre = block && s > 0 && v[s - 1] !== '\n' ? '\n\n' : '';
    const post = block && e < v.length && !v.slice(e).startsWith('\n\n') ? (v[e] === '\n' ? '\n' : '\n\n') : '';
    ta.setRangeText(pre + text + post, s, e, 'end');
    ta.selectionStart = ta.selectionEnd = ta.selectionEnd - post.length;
    ta.focus(); render(); mark('body');
  }
  function wrapLines(prefix) {
    const s = ta.selectionStart, e = ta.selectionEnd, v = ta.value;
    const a = v.lastIndexOf('\n', s - 1) + 1, b = e > s && v[e - 1] === '\n' ? e - 1 : (v.indexOf('\n', e) + 1 || v.length + 1) - 1;
    let n = 0;
    const lines = v.slice(a, b).split('\n').map(l => l.trim() ? (typeof prefix === 'function' ? prefix(++n) : prefix) + l.replace(/^(#{1,4}\s+|[-*•]\s+|\d+[.)]\s+)/, '') : l);
    ta.setRangeText(lines.join('\n'), a, b, 'select');
    ta.focus(); render(); mark('body');
  }
  ed.querySelectorAll('[data-md]').forEach(b => b.addEventListener('click', () => {
    const k = b.dataset.md;
    if (k === 'b') {
      const s = ta.selectionStart, e = ta.selectionEnd, sel = ta.value.slice(s, e) || 'important';
      ta.setRangeText(`**${sel}**`, s, e, 'select'); ta.focus(); render(); mark('body');
    } else wrapLines(k === 'h' ? '## ' : k === 'ul' ? '- ' : n => `${n}. `);
  }));
  ta.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); ed.querySelector('[data-md=b]').click(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(); }
    if (e.key === 'Enter' && !e.shiftKey) {        // continue lists
      const v = ta.value, s = ta.selectionStart, a = v.lastIndexOf('\n', s - 1) + 1, line = v.slice(a, s);
      const m = line.match(/^(\s*)([-*•]|(\d+)[.)])\s+(.*)$/);
      if (m) {
        e.preventDefault();
        if (!m[4]) { ta.setRangeText('', a, s, 'end'); }
        else ta.setRangeText(`\n${m[1]}${m[3] ? `${+m[3] + 1}.` : m[2]} `, s, ta.selectionEnd, 'end');
        render(); mark('body');
      }
    }
  });

  const menu = ed.querySelector('.dr-menu'), menuBtn = ed.querySelector('[data-dr-menu]');
  menuBtn.addEventListener('click', () => { menu.hidden = !menu.hidden; menuBtn.setAttribute('aria-expanded', String(!menu.hidden)); });
  document.addEventListener('click', e => { if (!e.target.closest('.dropdown')) { menu.hidden = true; menuBtn.setAttribute('aria-expanded', 'false'); } });
  const fmtRow = r => `${r.parameter} ${r.value}${r.unit ? ' ' + r.unit : ''} (${r.flag_label.toLowerCase()}${r.range ? `; ref ${r.range}` : ''})`;
  const INSERTS = {
    abnormal: () => {
      const ab = rows.filter(r => ['H', 'L', 'A', 'HH', 'LL'].includes(r.flag));
      return ab.length ? `**Abnormal results:** ${ab.map(fmtRow).join('; ')}.` : '**Results:** all reported values within the hospital range.';
    },
    critical: () => {
      const c = rows.filter(r => ['HH', 'LL'].includes(r.flag));
      return c.length ? `## Critical values\n${c.map(r => `- **${fmtRow(r)}** · acted on at ____ by ____`).join('\n')}` : '**Critical values:** none.';
    },
    exam: () => '## Examination\n- General: \n- Vital signs: \n- Chest: \n- Abdomen: \n- Other: ',
    followup: () => {
      const d = follow?.value ? new Date(follow.value + 'T00:00') : null;
      return d ? `**Follow-up:** review on ${d.toLocaleDateString(undefined, {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'})}, sooner if worse.`
               : '**Follow-up:** review in ____ days, sooner if worse.';
    },
    safety: () => '**Safety-netting:** advised to return at once if symptoms get worse or new warning signs appear (________). Understanding confirmed.',
  };
  menu.querySelectorAll('[data-insert]').forEach(b => b.addEventListener('click', () => { insert(INSERTS[b.dataset.insert]()); menu.hidden = true; }));

  const split = ed.querySelector('.dr-split');
  ed.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => {
    split.dataset.mode = b.dataset.view;
    ed.querySelectorAll('[data-view]').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-selected', String(x === b)); });
  }));
  ed.querySelector('[data-reset]')?.addEventListener('click', () => {
    const ai = data('dr-ai-draft');
    if (ai && confirm('Go back to the AI text as adopted? Your changes to the text will be lost.')) { ta.value = ai; render(); mark('body'); }
  });
  document.querySelectorAll('[data-days]').forEach(b => b.addEventListener('click', () => {
    if (!follow) return;
    if (!b.dataset.days) follow.value = '';
    else { const d = new Date(); d.setDate(d.getDate() + +b.dataset.days); follow.value = d.toISOString().slice(0, 10); }
    mark('follow_up');
  }));

  // ---------------------------------------------------------------- files: choose or drop, upload, reload
  const drop = document.querySelector('[data-drop]');
  if (drop) {
    const input = drop.querySelector('input[type=file]');
    const upload = async files => {
      if (!files?.length) return;
      await save();
      const fd = new FormData(drop);
      fd.delete('files');
      [...files].forEach(f => fd.append('files', f));
      drop.classList.add('busy');
      try {
        const r = await fetch(drop.action, {method: 'POST', body: fd, credentials: 'same-origin', headers: {'X-Requested-With': 'fetch'}});
        const j = await r.json().catch(() => ({}));
        (j.errors || []).forEach(m => window.mfToast?.(m, 'error'));
        if (j.added?.length) { location.hash = 'files'; location.reload(); }
      } catch { window.mfToast?.('Upload failed. Check the connection and try again.', 'error'); }
      drop.classList.remove('busy');
    };
    input.addEventListener('change', () => upload(input.files));
    ['dragenter', 'dragover'].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(t => drop.addEventListener(t, () => drop.classList.remove('over')));
    drop.addEventListener('drop', e => { e.preventDefault(); upload(e.dataTransfer.files); });
  }

  // ---------------------------------------------------------------- AI helpers
  const out = document.querySelector('[data-assist-out]');
  const LABELS = {safety: 'Safety check', patient: 'Patient-friendly explanation', tighten: 'Tighten wording', codes: 'Suggest ICD-10 codes'};
  const THINK = {
    safety: ['Reading your draft', 'Checking it against every result', 'Looking for critical values not addressed', 'Checking allergies and doses'],
    patient: ['Reading your draft', 'Finding plain words', 'Adding the warning signs'],
    tighten: ['Reading your draft', 'Keeping every fact, trimming the rest'],
    codes: ['Reading your assessment', 'Matching ICD-10 codes'],
  };
  let pendingCard = null;
  RD?.focus(() => pendingCard || out.querySelector('.dr-assist-card') || ta);

  function actionsFor(card, kind, text) {
    const f = card.querySelector('footer');
    f.innerHTML = '';
    const btn = (label, icon, fn, cls = 'btn-ghost') => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = `btn btn-sm ${cls}`; b.innerHTML = `<i class="bi bi-${icon}"></i>${esc(label)}`;
      b.addEventListener('click', fn); f.appendChild(b);
    };
    if (kind === 'tighten') btn('Replace my draft', 'arrow-repeat', () => {
      if (confirm('Replace your draft with the tightened version? You can undo with Ctrl+Z straight after.')) {
        ta.focus(); ta.select(); document.execCommand?.('insertText', false, text) || (ta.value = text); render(); mark('body');
      }
    }, 'btn-primary');
    if (kind === 'patient') btn('Add to report', 'plus-lg', () => { ta.setSelectionRange(ta.value.length, ta.value.length); insert(text.startsWith('##') ? text : `## For the patient\n${text}`); }, 'btn-primary');
    if (kind === 'codes') btn('Add to report', 'plus-lg', () => { ta.setSelectionRange(ta.value.length, ta.value.length); insert(`## Suggested codes (ICD-10, to confirm)\n${text}`); }, 'btn-primary');
    btn('Insert at cursor', 'cursor-text', () => insert(text));
    btn('Copy', 'clipboard', () => navigator.clipboard?.writeText(text).then(() => window.mfToast?.('Copied.')));
    if (kind === 'patient' && RD) btn('Read aloud', 'volume-up', () => RD.summon().then(() => RD.speak(text)));
    btn('Dismiss', 'x-lg', () => card.remove());
  }
  out.querySelectorAll('.dr-assist-card').forEach(c => actionsFor(c, c.dataset.kind, c.querySelector('textarea').value));

  async function poll(url, card, kind, tries = 0) {
    try {
      const j = await (await fetch(url, {credentials: 'same-origin'})).json();
      if (j.status === 'done') {
        card.classList.remove('pending');
        card.querySelector('.gd-ai-text').innerHTML = j.html;
        card.querySelector('header span').textContent = 'just now';
        actionsFor(card, kind, j.text);
        pendingCard = card;
        const msg = {safety: 'Safety check done. Have a look before you sign.', patient: 'Here is a version for the patient.',
                     tighten: 'Tightened. Compare it with yours before replacing.', codes: 'Here are some codes to consider.'}[kind];
        RD?.done(esc(msg), [{label: 'Show me', icon: 'eye', primary: true, onClick: () => card.scrollIntoView({behavior: 'smooth', block: 'center'})}]);
        setTimeout(() => { if (pendingCard === card) pendingCard = null; }, 8000);
        return;
      }
      if (j.status === 'failed') throw new Error(j.error || 'The AI could not answer');
      if (tries > 90) throw new Error('This is taking too long. Try again in a minute.');
      setTimeout(() => poll(url, card, kind, tries + 1), 2500);
    } catch (err) {
      card.classList.remove('pending'); card.classList.add('failed');
      card.querySelector('.gd-ai-text').innerHTML = `<p>${esc(err.message)}</p>`;
      card.querySelector('footer').innerHTML = '';
      pendingCard = null;
      RD?.fail('I could not finish that one. The rest of the report is safe.');
    }
  }

  document.querySelectorAll('[data-assist]').forEach(b => b.addEventListener('click', async () => {
    const kind = b.dataset.kind;
    b.classList.add('busy');
    await save();
    const card = document.createElement('article');
    card.className = 'dr-assist-card pending'; card.dataset.kind = kind;
    card.innerHTML = `<header><b>${esc(LABELS[kind])}</b><span class="small muted">working…</span></header><div class="gd-ai-text"><p><span class="spinner-border spinner-border-sm"></span> Thinking…</p></div><footer></footer>`;
    out.prepend(card);
    pendingCard = card;
    if (RD) { RD.summon().then(() => RD.think(THINK[kind])); }
    try {
      const r = await fetch(b.dataset.assist, {method: 'POST', credentials: 'same-origin', body: new URLSearchParams({body: ta.value}),
                                                headers: {'X-CSRFToken': document.getElementById('dr-assist').dataset.csrf}});
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || 'That did not work.');
      poll(j.poll, card, kind);
    } catch (err) {
      card.classList.remove('pending'); card.classList.add('failed');
      card.querySelector('.gd-ai-text').innerHTML = `<p>${esc(err.message)}</p>`;
      RD?.fail(esc(err.message));
    } finally { b.classList.remove('busy'); }
  }));

  // a first visit right after adopting: Dr. Flow explains what to do next
  if (RD && ed.hasAttribute('data-fresh')) {
    const key = `rd-greeted-${ed.dataset.save}`;
    try {
      if (!sessionStorage.getItem(key)) {
        sessionStorage.setItem(key, '1');
        setTimeout(() => RD.summon().then(() => RD.say('I copied the AI summary into your report. Change anything you like, add your examination, pick the images and files to include, then sign.',
          [{label: 'Run a safety check', icon: 'shield-check', primary: true, onClick: () => document.querySelector('[data-kind=safety]')?.click()},
           {label: 'Got it', icon: 'check2', onClick: () => RD.hide()}])), 600);
      }
    } catch { /* storage blocked: skip the greeting */ }
  }
})();
