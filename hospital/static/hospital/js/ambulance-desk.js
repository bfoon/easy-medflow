/* Service desk: live triage verdict, caller lookup, and placing the patient on the map. */
(() => {
  const E = window.EmsMap, $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)], esc = E.esc;
  const rules = JSON.parse($('#rules').textContent), meta = JSON.parse($('#pmeta').textContent), home = JSON.parse($('#home').textContent);
  const byKey = Object.fromEntries(rules.map(r => [r.key, r]));
  const answers = {};

  /* ------------------------------------------------------------ questions + verdict */
  function current() { return byKey[($('input[name=complaint]:checked') || {}).value] || byKey.other; }
  function drawQuestions() {
    const r = current();
    $('#qlist').innerHTML = r.questions.map(q => `<div class="q" data-q="${q.key}"><p>${esc(q.text)}</p><div class="yn" role="radiogroup" aria-label="${esc(q.text)}">
      <label><input type="radio" name="q_${q.key}" value="yes" ${answers[q.key] === 'yes' ? 'checked' : ''}><span>Yes</span></label>
      <label><input type="radio" name="q_${q.key}" value="no" ${answers[q.key] === 'no' ? 'checked' : ''}><span>No</span></label></div></div>`).join('')
      || '<p class="muted mb-0">No set questions. Write what the caller says below.</p>';
    $('#firstaid').innerHTML = r.first_aid.map(t => `<li>${esc(t)}</li>`).join('');
    verdict();
  }
  function verdict() {
    const r = current();
    let p = r.base; const why = [];
    r.questions.forEach(q => {
      const hit = answers[q.key] && answers[q.key] === q.trigger;
      const row = document.querySelector(`.q[data-q="${q.key}"]`); if (row) row.classList.toggle('hit', !!hit && q.p <= 2);
      if (hit) { p = Math.min(p, q.p); why.push(q.why); }
    });
    if (r.key === 'arrest') why.unshift('Cardiac arrest');
    const o = +$('#override').value; const shown = o || p;
    const v = $('#verdict'); v.className = `verdict pri-${shown}`; v.style.setProperty('--pc', meta.colors[shown]);
    $('#v-p').textContent = `P${shown}`; $('#v-word').textContent = meta.words[shown];
    $('#v-why').textContent = (o && o !== p ? `Set by you (triage says P${p}). ` : '') + (why.length ? why.join(' · ') : `${r.label}: starting priority`);
    $('#v-target').textContent = `Target: crew with the patient within ${meta.targets[shown]} minutes`;
  }
  document.addEventListener('change', e => {
    if (e.target.name === 'complaint') drawQuestions();
    if (e.target.name && e.target.name.startsWith('q_')) { answers[e.target.name.slice(2)] = e.target.value; verdict(); }
    if (e.target.id === 'override') verdict();
  });

  /* ------------------------------------------------------------ map pin */
  const map = E.map('pickmap', JSON.parse($('#ems-tiles').textContent), {layers: false});
  L.marker([home.lat, home.lon], {icon: E.hospIcon(true)}).bindTooltip(esc(home.name)).addTo(map);
  let pin = null;
  function place(ll, zoom) {
    $('#lat').value = ll.lat.toFixed(6); $('#lon').value = ll.lng.toFixed(6);
    if (!pin) { pin = L.marker(ll, {draggable: true, icon: E.youIcon()}).addTo(map); pin.on('dragend', () => place(pin.getLatLng())); } else pin.setLatLng(ll);
    if (zoom) map.setView(ll, Math.max(map.getZoom(), 15));
    $('#pinhint').innerHTML = `<i class="bi bi-geo-alt-fill text-success"></i> Patient placed at ${ll.lat.toFixed(5)}, ${ll.lng.toFixed(5)}. Drag the pin to correct it.`;
  }
  map.on('click', e => place(e.latlng));
  $('#location').addEventListener('change', e => {
    const o = e.target.selectedOptions[0]; if (!o || !o.dataset.lat) return;
    const ll = L.latLng(+o.dataset.lat, +o.dataset.lon);
    map.setView(ll, 15); if (!pin) place(ll);
  });

  /* ------------------------------------------------------------ caller lookup */
  let t = null;
  $('#caller_phone').addEventListener('input', e => {
    clearTimeout(t);
    t = setTimeout(async () => {
      const v = e.target.value.trim(); const box = $('#known');
      if (v.replace(/\D/g, '').length < 7) { box.innerHTML = ''; return; }
      const r = await fetch(`${window.DESK.lookup}?phone=${encodeURIComponent(v)}`, {credentials: 'same-origin'}).then(x => x.json()).catch(() => ({results: []}));
      box.innerHTML = r.results.map(p => `<div class="known" data-p='${esc(JSON.stringify(p))}' role="button" tabindex="0">
        <i class="bi bi-person-vcard fs-4 text-muted"></i><div class="flex-fill"><b>${esc(p.name)}</b> <span class="muted small">${esc(p.mrn)} · ${p.age ?? '?'} y · ${esc(p.sex)}${p.town ? ' · ' + esc(p.town) : ''}</span>
        <div class="small">${p.own ? 'Own number' : 'Emergency contact number'}${p.allergies.length ? ` · <span class="text-danger">Allergies: ${p.allergies.map(esc).join(', ')}</span>` : ''}${p.blood_group ? ' · ' + esc(p.blood_group) : ''}</div></div>
        <span class="small fw-bold text-nowrap">This is the patient</span></div>`).join('');
    }, 350);
  });
  $('#known').addEventListener('click', e => {
    const k = e.target.closest('.known'); if (!k) return;
    const p = JSON.parse(k.dataset.p), on = !k.classList.contains('on');
    $$('#known .known').forEach(x => x.classList.remove('on'));
    k.classList.toggle('on', on);
    $('#patient').value = on ? p.id : '';
    if (on) {
      $('#patient_name').value = p.name; $('#patient_age').value = p.age ?? ''; $('#patient_sex').value = ['F', 'M'].includes(p.sex) ? p.sex : 'X';
      if (p.lat != null && !pin) { map.setView([p.lat, p.lon], 15); }
    }
  });

  $('#deskform').addEventListener('submit', e => {
    if (!$('#lat').value && !$('#location').value) {
      if (!confirm('The patient is not on the map yet. Save anyway? You will need to place them before sending an ambulance.')) e.preventDefault();
    }
  });
  drawQuestions();
})();
