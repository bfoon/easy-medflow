/* Decision-support panel shared by the prescribing, lab and imaging forms:
   allergy reminder (always visible), safety findings and suggestions from this hospital's past visits. */
(() => {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const ICON = {danger: 'bi-exclamation-octagon-fill', warn: 'bi-exclamation-triangle-fill', info: 'bi-info-circle-fill'};
  const FREQ = {OD: 'once daily', BD: 'twice daily', TDS: 'three times daily', QDS: 'four times daily', Q4H: 'every 4 h', Q6H: 'every 6 h', Q8H: 'every 8 h', Q12H: 'every 12 h', MANE: 'mornings', NOCTE: 'at night', PRN: 'when required', STAT: 'once', WEEKLY: 'weekly', ASDIR: 'as directed'};
  window.MFDecision = {
    mount({box, url, encounter, meds = () => [], tests = () => [], mode, onAddMed, onAddTest}) {
      let timer, last = '';
      const run = async () => {
        if (!encounter()) { box.innerHTML = '<div class="ds-empty"><i class="bi bi-person-vcard"></i>Choose a visit to see allergies, safety checks and suggestions.</div>'; return; }
        const q = `${url}?encounter=${encounter()}&meds=${meds().join(',')}&tests=${tests().join(',')}`;
        if (q === last) return; last = q;
        const d = await fetch(q, {credentials: 'same-origin'}).then(r => r.json()).catch(() => null);
        if (!d || !d.ready) return;
        const allergy = d.allergies.length
          ? `<div class="ds-allergy"><i class="bi bi-exclamation-triangle-fill"></i><div><b>Allergies · ${esc(d.patient)}</b><div>${d.allergies.map(a => `<span class="tag">${esc(a.substance)}${a.severity ? ' · ' + esc(a.severity) : ''}</span>`).join(' ')}</div></div></div>`
          : `<div class="ds-allergy none"><i class="bi bi-question-circle-fill"></i><div><b>No allergies documented · ${esc(d.patient)}</b><div class="small">Ask the patient before ${mode === 'imaging' ? 'giving contrast' : mode === 'lab' ? 'procedures' : 'prescribing'}.</div></div></div>`;
        const findings = d.findings.length ? d.findings.map(f => `<div class="ds-f ${f.level}"><i class="bi ${ICON[f.level]}"></i><div><b>${esc(f.title)}</b><div class="small">${esc(f.detail)}</div>${f.actions.map(a => `<a class="small fw-semibold" href="${esc(a.url)}" target="_top">${esc(a.label)} →</a>`).join(' ')}</div></div>`).join('')
          : '<div class="small muted mb-2"><i class="bi bi-shield-check"></i> No safety issues found by the rule-based checks.</div>';
        const sg = d.suggestions;
        let sugg = '';
        if (mode === 'rx' && sg.meds.length) sugg = sg.meds.map(m => `<div class="ds-s"><div class="flex-fill"><b>${esc(m.name)}</b><div class="small muted">${m.pct}% of ${sg.n} similar visits · usually ${esc(m.units)} ${esc(FREQ[m.frequency] || m.frequency)}${m.frequency in {PRN: 1, STAT: 1, ASDIR: 1} ? '' : ` for ${m.days} days`} · ${m.success}% improved</div></div><button type="button" class="btn btn-sm btn-ghost" data-add-med='${esc(JSON.stringify(m))}'>Add</button></div>`).join('');
        if (mode === 'lab' && sg.tests.length) sugg = sg.tests.map(t => `<div class="ds-s"><div class="flex-fill"><b>${esc(t.name)}</b><div class="small muted">ordered in ${t.pct}% of ${sg.n} similar visits</div></div><button type="button" class="btn btn-sm btn-ghost" data-add-test="${t.id}">Add</button></div>`).join('');
        box.innerHTML = allergy + `<div class="ds-h">Safety checks</div>${findings}` +
          (mode !== 'imaging' ? `<div class="ds-h">What colleagues usually ${mode === 'rx' ? 'prescribe' : 'order'}${sg.term ? ` for “${esc(sg.term)}”` : ''}</div>${sugg || `<div class="small muted">${sg.term ? 'Not enough similar past visits yet (needs 3).' : 'Add a diagnosis to the visit to see suggestions.'}</div>`}` : '') +
          `<div class="ds-ai small">${d.ai ? '<i class="bi bi-stars"></i> AI review connected.' : '<i class="bi bi-stars"></i> AI review not connected; rule-based checks shown.'}</div>`;
      };
      box.addEventListener('click', e => {
        const m = e.target.closest('[data-add-med]'); if (m && onAddMed) { onAddMed(JSON.parse(m.dataset.addMed)); m.disabled = true; m.textContent = 'Added'; }
        const t = e.target.closest('[data-add-test]'); if (t && onAddTest) { onAddTest(t.dataset.addTest); t.disabled = true; t.textContent = 'Added'; }
      });
      const schedule = () => { clearTimeout(timer); timer = setTimeout(run, 250); };
      run();
      return {refresh: schedule};
    },
  };
})();
