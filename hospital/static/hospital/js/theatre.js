/* Operating theatre: the live day board (rooms × time, bars that fill while an operation runs) and the case page
   (the patient's journey from ward to recovery, pre-op checks, the WHO Surgical Safety Checklist, recovery scores).
   All rules are enforced on the server; this page sends JSON and redraws from the server's answer. */
(() => {
  'use strict';
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const hm = iso => iso ? new Date(iso).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : '—';
  const dur = ms => { if (ms < 0) ms = 0; const m = Math.floor(ms / 60000), h = Math.floor(m / 60); return h ? `${h} h ${String(m % 60).padStart(2, '0')} min` : `${m} min`; };
  const ACTIVE = ['in_theatre', 'operating', 'recovery'];
  let skew = 0;                                            // server clock minus browser clock
  const now = () => Date.now() + skew;

  /* ================================================================== board */
  const boardBoot = document.getElementById('theatre-board');
  if (boardBoot) {
    let B = JSON.parse(boardBoot.textContent);
    skew = new Date(B.now) - Date.now();
    const draw = () => {
      const k = B.kpi;
      $('#th-kpis').innerHTML = [
        ['bi-calendar-check', k.booked, 'cases booked'], ['bi-heart-pulse', k.active, 'in theatre or recovery', k.active ? 'live' : ''],
        ['bi-check2-circle', k.done, 'completed'], ['bi-hourglass-split', k.waiting, `waiting${k.emergencies ? ` · ${k.emergencies} urgent` : ''}`, k.emergencies ? 'warn' : ''],
        ['bi-speedometer2', `${k.utilisation}%`, 'session time booked'], ['bi-x-octagon', k.cancelled, 'cancelled today', k.cancelled ? 'warn' : ''],
      ].map(([i, n, l, cls]) => `<div class="kpi th-kpi ${cls || ''}"><i class="bi ${i}"></i><b>${n}</b><span>${l}</span></div>`).join('');
      const day0 = new Date(`${B.date}T00:00:00`);
      const mins = iso => (new Date(iso) - day0) / 60000;
      let lo = 7 * 60, hi = 20 * 60;
      for (const c of B.cases) if (c.start) { lo = Math.min(lo, Math.floor(mins(c.start) / 60) * 60); hi = Math.max(hi, Math.ceil((mins(c.start) + c.minutes) / 60) * 60); }
      lo = Math.max(0, lo); hi = Math.min(24 * 60 + 360, hi);
      const pct = m => ((m - lo) / (hi - lo) * 100).toFixed(3);
      let hours = '', grid = '';
      for (let m = lo; m <= hi; m += 60) {
        if ((m - lo) % ((hi - lo) > 12 * 60 ? 120 : 60) === 0) hours += `<span style="left:${pct(m)}%">${String(Math.floor(m / 60) % 24).padStart(2, '0')}:00</span>`;
        grid += `<i class="th-hr" style="left:${pct(m)}%"></i>`;
      }
      const rows = B.rooms.map(r => {
        const sess = r.session.map(t => { const [h, m] = t.split(':'); return Math.max(lo, Math.min(hi, +h * 60 + +m)); });
        const bars = B.cases.filter(c => c.room === r.id && c.start).map(c => {
          const s = mins(c.start);
          return `<a class="th-bar st-${c.status} u-${c.urgency}" href="${c.url}" data-id="${c.id}" style="left:${pct(s)}%;width:${(c.minutes / (hi - lo) * 100).toFixed(3)}%" title="${esc(c.number)} · ${esc(c.title)} · ${esc(c.patient)}">
            <i class="fill"></i><b>${esc(c.title)}</b><span>${hm(c.start)} · ${esc(c.patient)}${c.surgeon ? ` · ${esc(c.surgeon)}` : ''}</span>
            <em class="chk">${['sign_in', 'time_out', 'sign_out'].map(p => `<u class="${c.checklist[p] ? 'on' : ''}" title="WHO ${p.replace('_', ' ')}"></u>`).join('')}</em></a>`;
        }).join('');
        return `<div class="th-row"><div class="th-room"><b>${esc(r.name)}</b><span>${esc(r.kind)} · <em class="${r.utilisation > 100 ? 'over' : ''}">${r.utilisation}% booked</em></span></div>
          <div class="th-lane">${grid}<i class="th-session" style="left:${pct(sess[0])}%;width:${((sess[1] - sess[0]) / (hi - lo) * 100).toFixed(3)}%"></i>${bars}</div></div>`;
      }).join('');
      $('#th-gantt').innerHTML = `<div class="th-scale"><div></div><div class="th-hours">${hours}</div></div>${rows || '<div class="empty">No theatres are set up. Add them under Configuration → Operating rooms.</div>'}<div class="th-now" hidden><span></span></div>`;
      $('#th-gantt').dataset.lo = lo; $('#th-gantt').dataset.hi = hi;
      $('#th-wait').innerHTML = B.waiting.map(c => `<li class="u-${c.urgency}"><a href="${c.url}"><b>${esc(c.title)}</b><span>${esc(c.patient)} · ${c.age ?? '?'} yrs · ${esc(c.specialty)}</span></a>
        <span class="tag ${c.urgency === 'immediate' ? 'red' : c.urgency === 'urgent' ? 'amber' : ''}">${esc(c.urgency_label)}</span><small>${c.status === 'postponed' ? `postponed: ${esc(c.reason)}` : `waiting ${c.waited_h < 48 ? c.waited_h + ' h' : Math.round(c.waited_h / 24) + ' days'}`}</small></li>`).join('') || '<li class="muted small">Nobody is waiting.</li>';
      tick();
    };
    const tick = () => {
      const g = $('#th-gantt'), lo = +g.dataset.lo, hi = +g.dataset.hi, day0 = new Date(`${B.date}T00:00:00`), m = (now() - day0) / 60000;
      const line = g.querySelector('.th-now');
      if (line) { const on = m >= lo && m <= hi; line.hidden = !on; if (on) { line.style.left = `calc(${g.querySelector('.th-lane').offsetLeft}px + ${g.querySelector('.th-lane').offsetWidth}px * ${(m - lo) / (hi - lo)})`; line.querySelector('span').textContent = hm(new Date(now()).toISOString()); } }
      for (const c of B.cases) {
        const el = g.querySelector(`.th-bar[data-id="${c.id}"] .fill`); if (!el) continue;
        let f = 0;
        if (c.status === 'completed' || c.status === 'recovery') f = 1;
        else if (ACTIVE.includes(c.status) && c.times.in_room_at) f = (now() - new Date(c.times.in_room_at)) / (c.minutes * 60000);
        el.style.width = `${Math.min(100, f * 100)}%`;
        el.parentNode.classList.toggle('over', ACTIVE.includes(c.status) && c.status !== 'recovery' && f > 1);
      }
    };
    draw();
    setInterval(tick, reduce ? 30000 : 1000);
    setInterval(async () => {
      try { const r = await fetch(`/theatre/api/board/?date=${B.date}`, {credentials: 'same-origin'}); if (r.ok) { B = await r.json(); skew = new Date(B.now) - Date.now(); draw(); } } catch (e) { /* offline: keep the last board */ }
    }, 30000);
  }

  /* ================================================================== case page */
  const caseBoot = document.getElementById('theatre-case');
  if (!caseBoot) return;
  const boot = JSON.parse(caseBoot.textContent), CAT = boot.catalogue;
  let S = boot.state;
  skew = new Date(S.now) - Date.now();
  const STATIONS = [['ward', 'Ward', 'bi-hospital'], ['preop', 'Pre-op checks', 'bi-clipboard2-check'], ['theatre', 'Theatre', 'bi-heart-pulse'], ['recovery', 'Recovery', 'bi-activity'], ['back', 'Back to ward', 'bi-house-heart']];
  const stationOf = st => ({requested: 0, postponed: 0, scheduled: 1, ready: 1, in_theatre: 2, operating: 2, recovery: 3, completed: 4, cancelled: 0}[st]);

  async function post(url, body) {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(body), credentials: 'same-origin'});
    const d = await r.json().catch(() => ({ok: false, error: `The server answered ${r.status}.`}));
    if (!r.ok || !d.ok) throw new Error(d.error || 'That did not work.');
    return d;
  }
  async function send(url, body, okMsg) {
    try {
      const d = await post(url, body);
      const before = S.status; S = d.state; render(before !== S.status);
      toast(okMsg + ((d.detail.alerts || []).length ? ` · ${d.detail.alerts.join(' ')}` : ''), (d.detail.alerts || []).length > 0);
      if (before !== S.status && ['recovery', 'operating'].includes(S.status) && $('#note form') === null) setTimeout(() => location.reload(), 700);
    } catch (e) { toast(e.message, true); }
  }
  function toast(msg, bad) { const t = $('#th-toast'); t.textContent = msg; t.className = `th-toast show${bad ? ' bad' : ''}`; clearTimeout(t.__h); t.__h = setTimeout(() => t.classList.remove('show'), 5200); }

  /* ---------------------------------------------------------- the journey */
  let journey = null;
  function drawJourney(moved) {
    const W = 900, H = 150, xs = STATIONS.map((_, i) => 70 + i * 190), at = stationOf(S.status);
    const cancelled = S.status === 'cancelled';
    let s = `<svg viewBox="0 0 ${W} ${H}" class="th-journey" role="img" aria-label="Where the patient is: ${esc(S.status_label)}">
      <path d="M${xs[0]},70 L${xs[4]},70" stroke="#DCE4E0" stroke-width="8" stroke-linecap="round"/>
      <path class="th-track" d="M${xs[0]},70 L${xs[at]},70" stroke="${cancelled ? '#C9D5CF' : '#0F7B78'}" stroke-width="8" stroke-linecap="round"/>`;
    STATIONS.forEach(([k, label], i) => {
      const done = i < at || S.status === 'completed', here = i === at && !cancelled;
      s += `<g class="th-st ${done ? 'done' : ''} ${here ? 'here' : ''}"><circle cx="${xs[i]}" cy="70" r="${here ? 20 : 15}" fill="${done || here ? '#0F7B78' : '#fff'}" stroke="${done || here ? '#0F7B78' : '#C9D5CF'}" stroke-width="3"/>
        ${here ? `<circle class="th-ping" cx="${xs[i]}" cy="70" r="20" fill="none" stroke="#0F7B78" stroke-width="3"/>` : ''}
        <text x="${xs[i]}" y="${here ? 112 : 108}" text-anchor="middle" class="th-lbl">${label}</text>${done && !here ? `<path d="M${xs[i] - 6},70 l4,5 l9,-10" stroke="#fff" stroke-width="3" fill="none"/>` : ''}</g>`;
    });
    // the theatre itself: lamp, monitor trace while operating
    const tx = xs[2];
    s += `<g class="th-lamp ${S.status === 'operating' ? 'on' : ''}"><path d="M${tx - 22},0 L${tx + 22},0 L${tx + 14},9 L${tx - 14},9Z" fill="#5A6F7D"/><path class="beam" d="M${tx - 14},9 L${tx + 14},9 L${tx + 30},33 L${tx - 30},33Z" fill="#FFF6C8" opacity="0"/></g>
      <g transform="translate(${tx + 44},6)"><rect width="66" height="34" rx="5" fill="#0F2C3F"/><path class="th-ecg" d="" stroke="#3FE0B0" stroke-width="1.6" fill="none"/></g>
      <g class="th-trolley" transform="translate(${xs[at]},70)">${cancelled ? '' : `<rect x="-24" y="-30" width="48" height="12" rx="5" fill="#fff" stroke="#0F2C3F" stroke-width="2"/><circle cx="-14" cy="-36" r="7" fill="#8A5A3C"/><rect x="-6" y="-38" width="26" height="8" rx="4" fill="#4A5FC1"/><circle cx="-16" cy="-12" r="4" fill="#0F2C3F"/><circle cx="16" cy="-12" r="4" fill="#0F2C3F"/>`}</g>
      ${cancelled ? `<text x="${W / 2}" y="40" text-anchor="middle" class="th-cancel">Cancelled: ${esc(S.cancel_reason)}</text>` : ''}
      ${S.status === 'postponed' ? `<text x="${W / 2}" y="40" text-anchor="middle" class="th-cancel">Postponed: ${esc(S.cancel_reason)}</text>` : ''}</svg>`;
    $('#th-journey').innerHTML = s;
    const trolley = $('#th-journey .th-trolley'), ecg = $('#th-journey .th-ecg');
    if (moved && !reduce && trolley && at > 0) {
      trolley.animate([{transform: `translate(${xs[at - 1]}px,70px)`}, {transform: `translate(${xs[at]}px,70px)`}], {duration: 1200, easing: 'cubic-bezier(.2,.8,.2,1)'});
      $('#th-journey .th-track').animate([{strokeDasharray: '0 2000'}, {strokeDasharray: '2000 0'}], {duration: 1400});
    }
    cancelAnimationFrame(journey);
    const live = ['in_theatre', 'operating', 'recovery'].includes(S.status);
    const frame = ts => {
      const t = ts / 1000; let d = 'M0,20';
      for (let x = 0; x <= 66; x += 2) { const ph = ((x / 66 + t * .9) % 1); const y = live ? 20 - (ph > .42 && ph < .46 ? 14 : ph > .46 && ph < .5 ? -6 : 0) : 20; d += ` L${x},${y}`; }
      if (ecg) ecg.setAttribute('d', d);
      if (!reduce) journey = requestAnimationFrame(frame);
    };
    journey = requestAnimationFrame(frame);
  }

  /* ---------------------------------------------------------- clocks */
  function clocks() {
    const T = S.times, n = now(), c = [];
    if (T.in_room_at && !T.out_room_at) c.push(['In theatre', n - new Date(T.in_room_at), n - new Date(T.in_room_at) > S.minutes * 60000 * 1.25]);
    if (T.incision_at && !T.closure_at) c.push(['Operating (since incision)', n - new Date(T.incision_at), false]);
    if (T.out_room_at && !T.recovery_out_at) c.push(['In recovery', n - new Date(T.out_room_at), n - new Date(T.out_room_at) > 2 * 3600000]);
    if (T.in_room_at && T.out_room_at) c.push(['Time in theatre', new Date(T.out_room_at) - new Date(T.in_room_at), false]);
    if (S.start && !T.in_room_at && ['scheduled', 'ready'].includes(S.status)) { const d = new Date(S.start) - n; c.push([d >= 0 ? 'Starts in' : 'Late by', Math.abs(d), d < 0]); }
    $('#th-clocks').innerHTML = c.map(([l, ms, bad]) => `<div class="${bad ? 'bad' : ''}"><span>${l}</span><b>${dur(ms)}</b></div>`).join('');
  }

  /* ---------------------------------------------------------- the "now" panel: what has to happen next */
  const PHASE_AT = {ready: 'sign_in', in_theatre: 'time_out', operating: 'sign_out'};
  const NEXT = {ready: ['in_theatre', 'Patient into theatre · start anaesthesia', 'bi-door-open'], in_theatre: ['operating', 'Knife to skin', 'bi-scissors'],
    operating: ['recovery', 'Patient out to recovery', 'bi-activity'], scheduled: ['ready', 'Ready for theatre', 'bi-check2-all'], requested: null, postponed: null};
  function radios(name, val, na) {
    return `<span class="th-yn"><label class="${val === 'yes' ? 'on' : ''}"><input type="radio" name="${name}" value="yes" ${val === 'yes' ? 'checked' : ''}>Yes</label>${na ? `<label class="${val === 'na' ? 'on' : ''}"><input type="radio" name="${name}" value="na" ${val === 'na' ? 'checked' : ''}>N/A</label>` : ''}</span>`;
  }
  function phaseForm(phase) {
    const P = CAT.checklist[phase], saved = (S.checklist[phase] || {}).items || {};
    const extra = phase === 'time_out' ? `<label class="th-inline">Antibiotic given at <input type="time" class="form-control form-control-sm" name="antibiotic_time" value="${esc((S.checklist.time_out || {}).antibiotic_time || '')}"></label>`
      : phase === 'sign_out' ? `<label class="th-inline w-100">Count notes <input class="form-control form-control-sm" name="counts_note" maxlength="200" placeholder="e.g. 2 swabs added, all accounted for"></label>` : '';
    return `<form class="th-who" data-phase="${phase}"><div class="th-who-head"><span class="badge-who">WHO</span><div><b>${P.title}</b><small>${P.when}</small></div></div>
      <ul class="plain">${P.items.map(it => `<li><span>${esc(it.label)}</span>${radios(it.key, saved[it.key] || '', it.na)}</li>`).join('')}</ul>${extra}
      <button class="btn btn-ink btn-sm" type="submit"><i class="bi bi-pen"></i>Confirm ${P.title.toLowerCase()} (signed by you)</button></form>`;
  }
  function phaseDone(phase) {
    const d = S.checklist[phase]; if (!d || !S.phase_done[phase]) return '';
    return `<div class="th-who done"><div class="th-who-head"><span class="badge-who">WHO</span><div><b>${CAT.checklist[phase].title} ✓</b><small>by ${esc(d.by)} · ${hm(d.at)}${d.antibiotic_time ? ` · antibiotic ${esc(d.antibiotic_time)}` : ''}</small></div></div></div>`;
  }
  function renderNow() {
    const box = $('#th-now'), st = S.status, can = S.can.act;
    let h = `<div class="panel-head"><h2>${esc(S.status_label)}</h2><span class="tag ${st === 'cancelled' ? 'red' : st === 'completed' ? 'teal' : 'indigo'}">${esc(S.room || 'No theatre')} · ${S.start ? hm(S.start) : 'not scheduled'}</span></div>`;
    if (['requested', 'postponed'].includes(st)) h += `<p class="muted">On the waiting list. ${can ? 'Choose a theatre and a start time to schedule it.' : ''}</p>${can ? `<button class="btn btn-primary btn-sm" data-drawer="/theatre/cases/${S.id}/edit/" data-title="Schedule"><i class="bi bi-calendar-plus"></i>Schedule</button>` : ''}`;
    if (['scheduled', 'ready'].includes(st)) {
      const R = S.readiness;
      h += `<form class="th-preop" id="th-preop"><h3><i class="bi bi-clipboard2-check"></i> Ward checks before theatre</h3><ul class="plain">${R.items.map(it => `<li><span>${esc(it.label)}</span>${radios(it.key, it.value, it.na)}</li>`).join('')}</ul>
        <div class="th-fast"><label>Last food<input type="datetime-local" class="form-control form-control-sm" name="fasting_since" value="${esc(S.fasting_since)}"></label>
        <label>Last clear fluids<input type="datetime-local" class="form-control form-control-sm" name="clear_fluids_since" value="${esc(S.clear_fluids_since)}"></label></div>
        ${can ? '<button class="btn btn-ghost btn-sm" type="submit"><i class="bi bi-check2"></i>Save checks</button>' : ''}</form>`;
    }
    for (const ph of ['sign_in', 'time_out', 'sign_out']) h += phaseDone(ph);
    if (PHASE_AT[st] && !S.phase_done[PHASE_AT[st]] && can) h += phaseForm(PHASE_AT[st]);
    if (st === 'operating' && !S.note.procedure_performed) h += `<p class="small th-need"><i class="bi bi-journal-medical"></i> The surgeon writes the <a href="#note">operation note</a> before the patient leaves theatre.</p>`;
    const nx = NEXT[st];
    if (nx && can) {
      const blocked = (st === 'scheduled' && !S.readiness.complete) || (PHASE_AT[st] && !S.phase_done[PHASE_AT[st]] && st !== 'ready') || (st === 'ready' && !S.phase_done.sign_in) || (st === 'operating' && !S.note.procedure_performed);
      h += `<div class="th-go"><button class="btn btn-primary" data-to="${nx[0]}" ${blocked ? 'disabled' : ''}><i class="bi ${nx[2]}"></i>${nx[1]}</button>${blocked ? '<small class="muted">Complete the steps above first.</small>' : ''}</div>`;
    }
    if (can && S.next.length) {
      const side = S.next.filter(x => ['requested', 'scheduled', 'postponed', 'cancelled'].includes(x) && x !== (nx && nx[0]));
      if (side.length) h += `<div class="th-side">${side.map(x => `<button class="btn btn-sm btn-ghost ${x === 'cancelled' ? 'text-danger' : ''}" data-to="${x}">${{requested: 'Back to waiting list', scheduled: st === 'ready' ? 'Not ready after all' : 'Re-schedule', postponed: 'Postpone', cancelled: st === 'in_theatre' ? 'Abandon before incision' : 'Cancel'}[x]}</button>`).join('')}</div>`;
    }
    if (st === 'completed') h += `<p>Left recovery at ${hm(S.times.recovery_out_at)} to <b>${esc(S.discharge_to)}</b>.${S.discharge_override ? ` Discharged with a low score: ${esc(S.discharge_override)}.` : ''}</p>`;
    box.innerHTML = h;
    $('#th-edit').hidden = !S.can.edit;
  }

  function renderReady() {
    const R = S.readiness, L = R.labs, F = R.fasting;
    const lab = (code, label) => L[code] ? `<tr><th>${label}</th><td><b>${L[code].value}</b> ${esc(L[code].unit)}</td><td class="muted small">${new Date(L[code].at).toLocaleDateString()}</td></tr>` : '';
    const labs = lab('HB', 'Haemoglobin') + lab('K', 'Potassium') + lab('PLT', 'Platelets') + lab('INR', 'INR') + lab('FBG', 'Glucose') + lab('A1C', 'HbA1c');
    $('#th-ready').innerHTML = `<div class="panel-head"><h2>${['scheduled', 'ready', 'requested', 'postponed'].includes(S.status) ? 'Fit for theatre?' : 'Before theatre'}</h2>${R.complete ? '<span class="tag teal">Checks complete</span>' : `<span class="tag amber">${R.missing.length} check${R.missing.length > 1 ? 's' : ''} to do</span>`}</div>
      <div class="th-allergy ${R.allergies.length ? 'has' : ''}"><i class="bi bi-exclamation-triangle-fill"></i>${R.allergies.length ? `Allergies: <b>${R.allergies.map(esc).join(', ')}</b>` : 'No allergies recorded: confirm with the patient.'}</div>
      <div class="th-fastbar"><span>Fasting</span><div><i style="width:${Math.min(100, (F.food_hours || 0) / 6 * 100)}%" class="${F.ok ? 'ok' : ''}"></i></div><b>${F.food_hours != null ? `${F.food_hours} h food${F.clear_hours != null ? ` · ${F.clear_hours} h fluids` : ''}` : 'not recorded'}</b></div>
      ${labs ? `<table class="th-labs">${labs}</table>` : '<p class="small muted">No blood results in the last 30 days.</p>'}
      <ul class="plain th-warn">${R.warnings.map(w => `<li class="lv-${w.level}"><i class="bi ${w.level === 'high' ? 'bi-exclamation-octagon-fill' : 'bi-exclamation-triangle-fill'}"></i>${esc(w.text)}</li>`).join('')}</ul>`;
  }

  function renderTimes() {
    const T = S.times;
    const rows = [['Booked', S.start ? `for ${hm(S.start)}` : 'waiting list', true], ['Into theatre · anaesthesia', hm(T.in_room_at), !!T.in_room_at],
      ['WHO sign in', S.checklist.sign_in ? hm(S.checklist.sign_in.at) : '—', S.phase_done.sign_in], ['WHO time out', S.checklist.time_out ? hm(S.checklist.time_out.at) : '—', S.phase_done.time_out],
      ['Knife to skin', hm(T.incision_at), !!T.incision_at], ['WHO sign out', S.checklist.sign_out ? hm(S.checklist.sign_out.at) : '—', S.phase_done.sign_out],
      ['Out to recovery', hm(T.out_room_at), !!T.out_room_at], ['Left recovery', hm(T.recovery_out_at), !!T.recovery_out_at]];
    $('#th-times').innerHTML = rows.map(([l, v, d]) => `<li class="${d ? 'done' : ''}"><span>${l}</span><b>${v}</b></li>`).join('');
  }

  /* ---------------------------------------------------------- recovery and the Aldrete score */
  const ALD = {activity: ['Cannot move limbs', 'Moves 2 limbs', 'Moves all 4 limbs'], respiration: ['Not breathing', 'Shallow / limited breathing', 'Breathes deeply, coughs'],
    consciousness: ['Not responding', 'Rouses to voice', 'Fully awake']};
  function aldrete(o) {
    const p = {activity: o.activity, respiration: o.respiration, consciousness: o.consciousness};
    const base = S.baseline_sbp;
    p.circulation = o.systolic != null && base ? (Math.abs(o.systolic - base) / base * 100 <= 20 ? 2 : Math.abs(o.systolic - base) / base * 100 < 50 ? 1 : 0) : null;
    p.oxygen = o.spo2 != null ? (o.spo2 >= 92 && !o.on_oxygen ? 2 : o.spo2 >= 90 ? 1 : 0) : null;
    const v = Object.values(p); return {parts: p, total: v.every(x => x != null) ? v.reduce((a, b) => a + b, 0) : null};
  }
  function renderRecovery() {
    const panel = $('#th-recovery-panel'), show = ['recovery', 'completed'].includes(S.status) && (S.status === 'recovery' || S.recovery.length);
    panel.hidden = !show; if (!show) return;
    const obs = S.recovery, last = obs[obs.length - 1];
    const W = 360, H = 90, pts = obs.map((o, i) => [obs.length === 1 ? W / 2 : 10 + i / (obs.length - 1) * (W - 20), o.aldrete == null ? null : H - 10 - o.aldrete / 10 * (H - 20)]);
    const spark = `<svg viewBox="0 0 ${W} ${H}" class="th-spark"><rect x="0" y="${H - 10 - .9 * (H - 20)}" width="${W}" height="${.1 * (H - 20)}" fill="#DDF0EA"/><line x1="0" x2="${W}" y1="${H - 10 - .9 * (H - 20)}" y2="${H - 10 - .9 * (H - 20)}" stroke="#0F7B78" stroke-dasharray="4 3"/>
      <path d="M${pts.filter(p => p[1] != null).map(p => p.join(',')).join(' L')}" fill="none" stroke="#0F2C3F" stroke-width="2"/>${pts.filter(p => p[1] != null).map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="${obs[i].aldrete >= 9 ? '#0F7B78' : '#E0912A'}"/>`).join('')}<text x="4" y="${H - 10 - .9 * (H - 20) - 4}" class="th-lbl">9 = ready to leave</text></svg>`;
    const sel = (k, val) => `<select class="form-select form-select-sm" name="${k}"><option value="">—</option>${ALD[k].map((l, i) => `<option value="${i}" ${val === i ? 'selected' : ''}>${i} · ${l}</option>`).join('')}</select>`;
    let h = `<div class="panel-head"><h2><i class="bi bi-activity"></i> Recovery</h2><span class="hint">Modified Aldrete score: circulation and oxygen are worked out from the numbers</span></div>
      <div class="th-ald"><div class="th-gauge ${last && last.aldrete >= 9 ? 'ok' : last ? 'low' : ''}"><b>${last && last.aldrete != null ? last.aldrete : '–'}</b><span>/ 10 latest</span></div>${obs.length ? spark : '<p class="muted small">No observations yet.</p>'}</div>`;
    if (obs.length) h += `<table class="th-obs"><thead><tr><th>Time</th><th>HR</th><th>BP</th><th>SpO₂</th><th>Pain</th><th>Score</th></tr></thead><tbody>${obs.slice().reverse().slice(0, 8).map(o => `<tr><td>${hm(o.at)}</td><td>${o.heart_rate ?? '–'}</td><td>${o.systolic ?? '–'}/${o.diastolic ?? '–'}</td><td>${o.spo2 ?? '–'}${o.on_oxygen ? ' O₂' : ''}</td><td>${o.pain ?? '–'}</td><td><b>${o.aldrete ?? '–'}</b></td></tr>`).join('')}</tbody></table>`;
    if (S.status === 'recovery' && S.can.act) {
      h += `<form class="th-obsform" id="th-obsform"><div class="th-obsgrid">
        <label>Pulse<input class="form-control form-control-sm" type="number" name="heart_rate" min="20" max="250"></label>
        <label>Systolic<input class="form-control form-control-sm" type="number" name="systolic" min="40" max="260"></label>
        <label>Diastolic<input class="form-control form-control-sm" type="number" name="diastolic" min="20" max="160"></label>
        <label>SpO₂ %<input class="form-control form-control-sm" type="number" name="spo2" min="50" max="100"></label>
        <label>Resp. rate<input class="form-control form-control-sm" type="number" name="resp_rate" min="4" max="60"></label>
        <label>Temp °C<input class="form-control form-control-sm" type="number" step="0.1" name="temperature_c" min="30" max="43"></label>
        <label>Pain 0–10<input class="form-control form-control-sm" type="number" name="pain" min="0" max="10"></label>
        <label class="chk"><input type="checkbox" name="on_oxygen"> On oxygen</label>
        <label>Activity${sel('activity', last?.activity)}</label><label>Breathing${sel('respiration', last?.respiration)}</label><label>Consciousness${sel('consciousness', last?.consciousness)}</label>
        </div><div class="th-preview" id="th-preview"></div><button class="btn btn-ink btn-sm"><i class="bi bi-plus-lg"></i>Record observations</button></form>
        <form class="th-discharge" id="th-discharge"><h3>Leave recovery</h3><div class="th-obsgrid"><label>Going to<select class="form-select form-select-sm" name="discharge_to">${boot.discharge_to.map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join('')}</select></label>
        <label class="span-2">Reason if the score is below 9<input class="form-control form-control-sm" name="override" maxlength="200"></label></div>
        <button class="btn btn-primary btn-sm" ${last && last.aldrete >= 9 ? '' : 'data-low="1"'}><i class="bi bi-house-heart"></i>Discharge from recovery</button></form>`;
    }
    $('#th-recovery').innerHTML = h;
  }

  function tellDrFlow() {
    const R = S.readiness, last = (S.recovery || [])[S.recovery.length - 1], lines = [];
    if (['scheduled', 'ready', 'requested', 'postponed'].includes(S.status)) {
      R.warnings.forEach(w => lines.push({level: w.level === 'high' ? 'danger' : 'warn', text: w.text}));
      if (R.missing.length) lines.push({level: 'info', text: `Still to check on the ward: ${R.missing.slice(0, 3).join('; ')}${R.missing.length > 3 ? '…' : ''}.`});
    }
    if (R.allergies.length) lines.push({level: 'warn', text: `Allergies: ${R.allergies.join(', ')}.`});
    const ph = PHASE_AT[S.status];
    if (ph && !S.phase_done[ph]) lines.push({level: 'info', text: `Next: the WHO ${CAT.checklist[ph].title} (${CAT.checklist[ph].when.toLowerCase()}).`});
    if (S.status === 'recovery' && last) (last.alerts || []).forEach(t => lines.push({level: 'danger', text: `Recovery ${hm(last.at)}: ${t}`}));
    const msg = {lines};
    if (window.DrFlowPage) window.DrFlowPage.update(msg); else window.__drflowPending = msg;
  }
  function render(moved) { drawJourney(moved); clocks(); renderNow(); renderReady(); renderTimes(); renderRecovery(); tellDrFlow(); }

  /* ---------------------------------------------------------- events */
  const formData = f => Object.fromEntries([...new FormData(f).entries()]);
  document.addEventListener('change', ev => {
    const r = ev.target.closest('.th-yn input'); if (r) { r.closest('.th-yn').querySelectorAll('label').forEach(l => l.classList.toggle('on', l.contains(r) && r.checked)); }
  });
  document.addEventListener('input', ev => {
    const f = ev.target.closest('#th-obsform'); if (!f) return;
    const d = formData(f), n = k => d[k] === '' || d[k] == null ? null : +d[k];
    const a = aldrete({activity: n('activity'), respiration: n('respiration'), consciousness: n('consciousness'), systolic: n('systolic'), spo2: n('spo2'), on_oxygen: !!d.on_oxygen});
    $('#th-preview').innerHTML = `Score now: <b>${a.total ?? '…'}</b>${a.parts.circulation != null ? ` · circulation ${a.parts.circulation} (vs ${S.baseline_sbp} before surgery)` : ''}${a.parts.oxygen != null ? ` · oxygen ${a.parts.oxygen}` : ''}`;
  });
  document.addEventListener('submit', ev => {
    const f = ev.target;
    if (f.matches('.th-who')) {
      ev.preventDefault(); const d = formData(f), items = {};
      CAT.checklist[f.dataset.phase].items.forEach(it => { if (d[it.key]) items[it.key] = d[it.key]; });
      send(`${boot.urls.checklist.replace(/\/$/, '')}/${f.dataset.phase}/`, {items, antibiotic_time: d.antibiotic_time, counts_note: d.counts_note}, `WHO ${CAT.checklist[f.dataset.phase].title} recorded.`);
    } else if (f.id === 'th-preop') {
      ev.preventDefault(); const d = formData(f), preop = {};
      S.readiness.items.forEach(it => { if (d[it.key]) preop[it.key] = d[it.key]; });
      send(boot.urls.preop, {preop, fasting_since: d.fasting_since, clear_fluids_since: d.clear_fluids_since}, 'Pre-op checks saved.');
    } else if (f.id === 'th-obsform') {
      ev.preventDefault(); const d = formData(f); d.on_oxygen = !!d.on_oxygen;
      send(boot.urls.recovery, d, 'Observations recorded.');
    } else if (f.id === 'th-discharge') {
      ev.preventDefault(); const d = formData(f);
      send(boot.urls.action, {to: 'completed', discharge_to: d.discharge_to, override: d.override}, 'The patient has left recovery.');
    }
  });
  document.addEventListener('click', ev => {
    const b = ev.target.closest('[data-to]'); if (!b || b.disabled) return;
    const to = b.dataset.to; let reason = '';
    if (['cancelled', 'postponed'].includes(to)) { reason = prompt(to === 'cancelled' ? 'Why is the operation cancelled?' : 'Why is it postponed?') || ''; if (!reason.trim()) return; }
    send(boot.urls.action, {to, reason}, `Now: ${{in_theatre: 'in theatre', operating: 'operating', recovery: 'in recovery', ready: 'ready for theatre', scheduled: 'scheduled', requested: 'on the waiting list', postponed: 'postponed', cancelled: 'cancelled'}[to] || to}.`);
  });

  render(false);
  setInterval(clocks, 1000);
})();
