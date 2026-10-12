/* Lab result guidance panel (lab request page). The server renders the panel; this script loads it, fills the
   general next steps from knowledge.js, posts the buttons (refresh sources, ask AI, mark reviewed, rate) and reloads
   the panel while sources are being fetched or the AI is thinking. */
(() => {
  const host = document.getElementById('guidance');
  if (!host) return;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  let tries = 0, timer = null, first = true;

  function fillKnowledge() {
    const KB = window.MFKnowledge || {};
    host.querySelectorAll('[data-kb]').forEach(ol => {
      const kb = KB[ol.dataset.kb] || {}, f = ol.dataset.flag || '';
      const steps = kb[f] || kb[f[0]] || (KB._default || {})[f[0]] || [];
      ol.innerHTML = steps.length ? steps.map(s => `<li>${esc(s)}</li>`).join('') : '<li class="muted">No general guidance written for this result yet; see the sources and AI below.</li>';
    });
    host.querySelectorAll('[data-kb-about]').forEach(p => {
      const kb = KB[p.dataset.kbAbout] || {};
      if (kb.about) p.textContent = kb.about; else p.remove();
    });
  }

  async function load() {
    clearTimeout(timer);
    const url = host.dataset.src + (first ? '?first=1' : '');
    first = false;
    try {
      const r = await fetch(url, {credentials: 'same-origin', headers: {'X-Requested-With': 'fetch'}});
      if (!r.ok) throw new Error(r.status);
      host.innerHTML = await r.text();
    } catch (err) {
      console.error('guidance load failed', err);
      host.innerHTML = '<div class="empty"><i class="bi bi-wifi-off"></i>Guidance could not be loaded. <button type="button" class="btn btn-sm btn-ghost" data-gd-reload>Try again</button></div>';
      return;
    }
    fillKnowledge();
    const root = host.querySelector('.gd');
    if (root && root.dataset.pending === '1' && tries++ < 75) timer = setTimeout(load, 4000);
  }

  host.addEventListener('click', async e => {
    if (e.target.closest('[data-gd-reload]')) { tries = 0; load(); return; }
    const b = e.target.closest('[data-gd-post]');
    if (!b) return;
    e.preventDefault();
    b.disabled = true; b.classList.add('busy');
    try {
      const body = new URLSearchParams(b.dataset.body ? JSON.parse(b.dataset.body) : {});
      const r = await fetch(b.dataset.gdPost, {method: 'POST', credentials: 'same-origin', body, headers: {'X-CSRFToken': host.dataset.csrf}});
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || 'That did not work. Try again.');
      if (j.message) window.mfToast?.(j.message);
    } catch (err) {
      window.mfToast?.(err.message, 'error');
    }
    tries = 0;
    load();
  });

  load();
})();
