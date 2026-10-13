/* Dr. Flow on the patient chart, the prescription form and the lab order form.
   Chart: a short safety brief, and "ask me anything".
   Prescribing: checks every line as it is filled in (interactions, duplicates, pregnancy, age, G6PD, results, dose) and
   warns, with a shake for anything serious. Ordering tests: repeats, overlaps and tests worth adding.
   Everywhere: a "?" next to a medicine or test opens Dr. Flow's card with the hospital's facts, an AI explanation and
   pictures from open medical sources. Forms opened in the drawer drive the chart's Dr. Flow, who stands beside it. */
(() => {
  const RD = window.RoboDoc;
  if (!RD) return;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  const U = window.MEDFLOW || {};
  const inFrame = (() => { try { return window.parent !== window && window.parent.RoboDoc === RD; } catch { return false; } })();
  const host = inFrame ? window.parent : window;
  if (inFrame) RD.trackFrame(window);
  const post = async (url, data) => {
    const r = await fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf}, body: new URLSearchParams(data)});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || 'That did not work. Try again.');
    return j;
  };
  const LEVEL_ICON = {danger: 'exclamation-octagon-fill', warn: 'exclamation-triangle-fill', info: 'info-circle'};

  // ---------------------------------------------------------------- ask Dr. Flow
  const THINK = {
    med: ['Looking up this medicine', 'Checking it against this patient', 'Finding pictures from the sources'],
    test: ['Looking up this test', 'Checking this patient\'s earlier results', 'Finding pictures from the sources'],
    free: ['Thinking about your question', 'Checking trusted medical sources', 'Finding pictures'],
  };
  async function ask({kind, id = '', question = '', encounter = '', personal = '1'}) {
    await RD.summon();
    RD.think(THINK[kind] || THINK.free);
    let card;
    try {
      const j = await post(U.drflowAsk, {kind, id, question, encounter, personal});
      const follow = q => ask({kind: 'free', question: kind === 'free' ? q : `${j.title}: ${q}`, encounter, personal});
      card = RD.card({title: j.title, subtitle: j.subtitle, facts: j.facts, warnings: j.warnings, ai: j.ai ? 'loading' : 'off',
                      images: j.images ? 'loading' : null, onAsk: follow, askPlaceholder: `Ask more about ${j.title}…`});
      if (!j.ai && !j.images) { RD.done(`Here is what the hospital records say about <b>${esc(j.title)}</b>.`); return; }
      for (let i = 0; i < 90; i++) {
        await new Promise(r => setTimeout(r, i < 3 ? 1200 : 2000));
        const s = await fetch(j.poll, {credentials: 'same-origin'}).then(r => r.json());
        if (s.status === 'running') continue;
        card.update({ai: !j.ai ? 'off' : s.html ? 'html' : s.error ? 'error' : 'off', html: s.html, error: s.error, model: s.model,
                     images: j.images ? s.images : null, sources: s.sources});
        RD.done(`Here is what I found about <b>${esc(j.title)}</b>.${s.images?.length ? ' Tap a picture to enlarge it.' : ''}`);
        return;
      }
      card.update({ai: 'error', error: 'It took too long.', images: []});
      RD.fail('That took too long. Try again in a minute.');
    } catch (err) {
      RD.fail(esc(err.message));
    }
  }
  window.DrFlow = {ask};

  const qButton = (label, onClick) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'df-q'; b.title = label; b.setAttribute('aria-label', label);
    b.innerHTML = '<i class="bi bi-question-lg"></i>';
    b.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); onClick(); });
    return b;
  };

  // announce new serious findings once; info only shows inline
  function announcer() {
    const said = new Set();
    return (findings, {focus, actionsFor, quietClear}) => {
      const fresh = findings.filter(f => f.level !== 'info' && !said.has(f.title));
      findings.forEach(f => said.add(f.title));
      if (!fresh.length) {
        if (quietClear && RD.state !== 'hidden') quietClear();
        return;
      }
      const top = fresh[0], more = fresh.length - 1;
      RD.focus(() => focus(top));
      const html = `<b>${esc(top.title)}</b><br>${esc(top.detail)}${top.basis ? `<small>${esc(top.basis)}</small>` : ''}` +
                   (more ? `<small>${more} more warning${more > 1 ? 's' : ''} shown on the form.</small>` : '');
      RD.summon().then(() => (top.level === 'danger' ? RD.alert : RD.say)(html, actionsFor(top)));
    };
  }

  // ---------------------------------------------------------------- prescribing
  function prescribing(form) {
    const enc = form.querySelector('[name="encounter"]'), lines = document.getElementById('lines');
    const announce = announcer();
    let timer, lastJson = '', clearedOnce = false;
    const q = (line, name) => line.querySelector(`[name$="-${name}"]`);
    const live = () => [...lines.querySelectorAll('[data-line]')].filter(l => !l.hidden);
    const MEDS = JSON.parse(document.getElementById('rx-meds')?.textContent || '{}');
    const lineOf = name => live().find(l => MEDS[q(l, 'medication').value]?.name === name);

    function decorate() {
      live().forEach(l => {
        const lab = l.querySelector('.g-med label');
        if (lab && !lab.querySelector('.df-q')) lab.appendChild(qButton('Ask Dr. Flow about this medicine', () => {
          const id = q(l, 'medication').value;
          if (!id) { RD.summon().then(() => RD.say('Choose a medicine first, then I can tell you about it.', [], {timeout: 3500})); return; }
          ask({kind: 'med', id, encounter: enc.value});
        }));
        if (!l.querySelector('[data-drflow]')) l.querySelector('[data-safety]').insertAdjacentHTML('afterend', '<div class="df-inline" data-drflow></div>');
      });
    }
    async function check() {
      decorate();
      const data = live().map(l => ({med: q(l, 'medication').value, dose: q(l, 'dose').value, units: q(l, 'units_per_dose').value,
                                     frequency: q(l, 'frequency').value, days: q(l, 'duration_days').value, quantity: q(l, 'quantity').value,
                                     route: q(l, 'route').value})).filter(x => x.med);
      const payload = JSON.stringify([enc.value, data]);
      if (!enc.value || !data.length || payload === lastJson) { if (!data.length) live().forEach(l => { l.querySelector('[data-drflow]').innerHTML = ''; }); return; }
      lastJson = payload;
      let j;
      try { j = await post(U.drflowRx, {encounter: enc.value, lines: JSON.stringify(data), prescription: form.dataset.prescription || ''}); } catch { return; }
      if (!j.ready) return;
      window.drflowBlocking = j.blocking;
      const wrap = document.getElementById('override-wrap');
      if (wrap && j.blocking) wrap.hidden = false;
      document.getElementById('df-override-note')?.remove();
      if (wrap && j.blocking) wrap.insertAdjacentHTML('afterbegin', `<p class="df-override-note" id="df-override-note"><i class="bi bi-robot"></i> Dr. Flow found ${j.blocking} serious problem${j.blocking > 1 ? 's' : ''}. To go ahead, write your clinical reason here.</p>`);
      live().forEach(l => {
        const name = MEDS[q(l, 'medication').value]?.name;
        const mine = j.findings.filter(f => f.meds.includes(name));
        l.querySelector('[data-drflow]').innerHTML = mine.map(f => `<button type="button" class="df-chip ${f.level}" data-df-ask="${f.ask ? f.ask.id : ''}" title="${esc(f.detail)}">
          <i class="bi bi-${LEVEL_ICON[f.level]}"></i>${esc(f.title)}</button>`).join('');
        l.classList.toggle('df-danger', mine.some(f => f.level === 'danger'));
      });
      announce(j.findings, {
        focus: f => (lineOf(f.meds[0]) || form).querySelector('[data-drflow]') || form,
        actionsFor: f => [
          ...(f.ask ? [{label: 'Tell me more', icon: 'question-circle', primary: true, onClick: () => ask({kind: 'med', id: f.ask.id, encounter: enc.value})}] : []),
          {label: 'Show me', icon: 'eye', onClick: () => lineOf(f.meds[0])?.scrollIntoView({behavior: 'smooth', block: 'center'})},
          {label: 'Got it', icon: 'check2', onClick: () => RD.say('Okay. I will keep checking as you go.', [], {timeout: 2500})},
        ],
        quietClear: () => {
          if (!j.findings.some(f => f.level !== 'info') && !clearedOnce) {
            clearedOnce = true;
            RD.say(`My checks found no problems with ${data.length === 1 ? 'this medicine' : `these ${data.length} medicines`}. The pharmacist still reviews every prescription.`, [], {timeout: 4500});
          }
        },
      });
      if (j.findings.some(f => f.level !== 'info')) clearedOnce = false;
    }
    const soon = () => { clearTimeout(timer); timer = setTimeout(check, 650); };
    form.addEventListener('input', soon);
    form.addEventListener('change', soon);
    document.getElementById('add-line')?.addEventListener('click', () => setTimeout(decorate, 0));
    form.addEventListener('click', e => {
      const chip = e.target.closest('[data-df-ask]');
      if (chip && chip.dataset.dfAsk) ask({kind: 'med', id: chip.dataset.dfAsk, encounter: enc.value});
    });
    decorate();
    RD.summon().then(() => {
      RD.focus(() => live()[0] || form);
      RD.say('I will check each medicine as you add it: interactions, pregnancy, age, kidney and liver results, G6PD and doses. Tap <b>?</b> to ask me about a medicine.', [], {timeout: 6000});
    });
    check();
  }

  // ---------------------------------------------------------------- ordering tests
  function ordering(form) {
    const enc = form.querySelector('#enc'), boxes = [...form.querySelectorAll('input[name="tests"]')];
    const announce = announcer();
    let timer, last = '', suggested = '';
    const panel = document.createElement('div');
    panel.className = 'df-list';
    panel.id = 'df-lab';
    document.getElementById('ds')?.after(panel);
    boxes.forEach(b => {
      const lab = b.closest('label');
      lab?.appendChild(qButton(`Ask Dr. Flow about ${b.dataset.name}`, () => ask({kind: 'test', id: b.value, encounter: enc.value})));
    });
    const pick = id => boxes.find(b => b.value === String(id));
    function act(a) {
      if (a.test) { const b = pick(a.test); if (b) { b.checked = true; b.dispatchEvent(new Event('change', {bubbles: true})); b.closest('label')?.scrollIntoView({behavior: 'smooth', block: 'center'}); } }
      else if (a.untick) { const b = pick(a.untick); if (b) { b.checked = false; b.dispatchEvent(new Event('change', {bubbles: true})); } }
      else if (a.url) window.open(a.url, '_blank', 'noopener');
    }
    async function check() {
      const ids = boxes.filter(b => b.checked).map(b => b.value);
      const key = `${enc.value}|${ids}`;
      if (!enc.value || key === last) return;
      last = key;
      let j;
      try { j = await post(U.drflowLab, {encounter: enc.value, tests: ids.join(',')}); } catch { return; }
      if (!j.ready) return;
      const own = j.findings.map((f, i) => ({f, i})).filter(x => x.f.basis !== 'Hospital safety rules');   // the Decision support panel shows the rest
      panel.innerHTML = own.length ? `<div class="df-list-head"><i class="bi bi-robot"></i> Dr. Flow</div>` + own.map(({f, i}) => `<div class="df-item ${f.level}">
          <i class="bi bi-${LEVEL_ICON[f.level]}"></i><div><b>${esc(f.title)}</b><span>${esc(f.detail)}</span>
          <span class="df-acts">${(f.actions || []).map((a, k) => `<button type="button" data-f="${i}" data-a="${k}">${esc(a.label)}</button>`).join('')}
          ${f.ask ? `<button type="button" data-ask="${f.ask.id}">About this test</button>` : ''}</span></div></div>`).join('') : '';
      panel.querySelectorAll('[data-a]').forEach(b => b.addEventListener('click', () => act(j.findings[+b.dataset.f].actions[+b.dataset.a])));
      panel.querySelectorAll('[data-ask]').forEach(b => b.addEventListener('click', () => ask({kind: 'test', id: b.dataset.ask, encounter: enc.value})));
      const suggestions = j.findings.filter(f => f.kind === 'suggest' && !ids.includes(String(f.actions[0]?.test)));
      announce(j.findings, {
        focus: f => (f.ask && pick(f.ask.id)?.closest('label')) || panel,
        actionsFor: f => [...(f.actions || []).slice(0, 2).map(a => ({label: a.label, icon: a.test ? 'plus-lg' : a.untick ? 'dash-lg' : 'box-arrow-up-right', primary: true, onClick: () => act(a)})),
                          ...(f.ask ? [{label: 'About this test', icon: 'question-circle', onClick: () => ask({kind: 'test', id: f.ask.id, encounter: enc.value})}] : [])],
        quietClear: () => {
          const sk = suggestions.map(f => f.title).join('|');
          if (suggestions.length && ids.length && sk !== suggested) {
            suggested = sk;
            RD.focus(() => panel);
            RD.say(`You might also add: ${suggestions.slice(0, 3).map(f => `<b>${esc(f.actions[0].label.replace(/^Add /, ''))}</b>`).join(', ')}.`,
                   suggestions.slice(0, 3).map(f => ({label: f.actions[0].label, icon: 'plus-lg', onClick: () => act(f.actions[0])})), {timeout: 9000});
          }
        },
      });
    }
    const soon = () => { clearTimeout(timer); timer = setTimeout(check, 450); };
    form.addEventListener('change', soon);
    RD.summon().then(() => {
      RD.focus(() => form.querySelector('.test-grid') || form);
      RD.say('Tick the tests you need. I will tell you if one was done recently, is already ordered or overlaps another, and suggest what may be missing. Tap <b>?</b> on a test to learn about it.', [], {timeout: 6500});
    });
    check();
  }

  // ---------------------------------------------------------------- patient chart
  function chart(el) {
    const enc = el.dataset.encounter || '';
    const header = () => document.querySelector('.wristband') || el;
    host.__drflowChartFocus = header;
    RD.focus(header);
    const openAsk = () => {
      RD.summon().then(() => RD.card({title: 'Ask Dr. Flow', subtitle: 'About a medicine, a test, or this patient', facts: [], ai: null, images: null,
                                      onAsk: question => ask({kind: 'free', question, encounter: enc}), focusInput: true,
                                      askPlaceholder: 'e.g. First-line treatment for uncomplicated malaria in pregnancy?'}));
    };
    const click = sel => () => document.querySelector(sel)?.click();
    const actions = [
      ...(document.querySelector('[data-drawer*="/labs/new/"]') ? [{label: 'Order tests', icon: 'droplet-half', onClick: click('[data-drawer*="/labs/new/"]')}] : []),
      ...(document.querySelector('[data-drawer*="/prescriptions/new/"]') ? [{label: 'Prescribe', icon: 'capsule', onClick: click('[data-drawer*="/prescriptions/new/"]')}] : []),
      {label: 'Ask me', icon: 'chat-dots', primary: true, onClick: openAsk},
    ];
    document.addEventListener('click', e => { if (e.target.closest('[data-drflow-ask]')) { e.preventDefault(); openAsk(); } });
    const key = `rd-brief-${el.dataset.brief}`;
    let seen = false;
    try { seen = !!sessionStorage.getItem(key); sessionStorage.setItem(key, '1'); } catch { /* storage blocked */ }
    fetch(el.dataset.brief, {credentials: 'same-origin'}).then(r => r.json()).then(b => {
      RD.summon().then(() => {
        const lines = b.lines.map(l => `<li class="${esc(l.level)}">${esc(l.text)}</li>`).join('');
        const html = `${b.alerts ? '<b>Before you start:</b>' : `I am here for ${esc(b.first_name)}'s visit.`}${lines ? `<ul class="df-brief">${lines}</ul>` : ' Nothing urgent on file.'}`;
        if (b.alerts && !seen) RD.alert(html, actions);
        else if (b.alerts || !seen) RD.say(html, actions, {timeout: b.alerts || lines ? 0 : 7000});
      });
    }).catch(() => RD.summon());
    // when the drawer closes, look back at the patient
    new MutationObserver(() => { if (!document.body.classList.contains('drawer-open')) RD.focus(header); })
      .observe(document.body, {attributes: true, attributeFilter: ['class']});
  }

  const rxForm = document.getElementById('rx-form'), labForm = document.getElementById('order-form'), chartEl = document.querySelector('[data-drflow-chart]');
  if (rxForm) prescribing(rxForm);
  else if (labForm) ordering(labForm);
  else if (chartEl) chart(chartEl);
  // the form in the drawer is closing: its card and warnings no longer apply
  if (inFrame) addEventListener('pagehide', () => { try { RD.closeCard(); RD.focus(host.__drflowChartFocus || null); } catch { /* ignore */ } });
})();
