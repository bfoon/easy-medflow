/* Dr. Flow on any page: the eyes & ears examination, the theatre case, the library and the pharmacy.
   The page describes itself on a hidden element:
     <div hidden data-drflow-page data-title data-greeting data-encounter data-topic data-focus
          data-lines='[{"level":"danger|warn|info","text":"..."}]' data-suggest='["question", ...]'></div>
   Dr. Flow greets with what matters on the page, offers suggested questions and "Ask me", and pages that change while
   the user works (the examination, the operation) call DrFlowPage.update({lines}) so he raises new serious findings
   once, with a shake. Questions go to the same Dr. Flow endpoint as on the patient chart. */
(() => {
  'use strict';
  const RD = window.RoboDoc, DF = window.DrFlow;
  const el = document.querySelector('[data-drflow-page]');
  if (!RD || !DF || !el) return;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const json = (s, d) => { try { return JSON.parse(s || ''); } catch { return d; } };
  const ctx = {title: el.dataset.title || 'this page', greeting: el.dataset.greeting || 'I am here if you need me.', encounter: el.dataset.encounter || '',
               topic: el.dataset.topic || '', lines: json(el.dataset.lines, []), suggest: json(el.dataset.suggest, [])};
  const seen = new Set(ctx.lines.filter(l => l.level === 'danger').map(l => l.text));
  const short = q => q.length > 44 ? q.slice(0, 42) + '…' : q;

  const ask = question => {
    const q = ctx.topic && !question.toLowerCase().includes(ctx.topic.toLowerCase()) ? `${ctx.topic}: ${question}` : question;
    return DF.ask({kind: 'free', question: q, encounter: ctx.encounter});
  };
  const openAsk = () => RD.summon().then(() => RD.card({
    title: 'Ask Dr. Flow', subtitle: ctx.topic ? `About ${ctx.topic}` : `About ${ctx.title}`, facts: [], ai: null, images: null,
    onAsk: ask, focusInput: true, askPlaceholder: ctx.suggest[0] ? `e.g. ${ctx.suggest[0]}` : 'Ask about a disease, medicine, test or operation…'}));
  const actions = () => [...ctx.suggest.slice(0, 2).map(q => ({label: short(q), icon: 'question-circle', onClick: () => ask(q)})),
                         {label: 'Ask me', icon: 'chat-dots', primary: true, onClick: openAsk}];
  const html = () => {
    const lines = ctx.lines.slice(0, 5).map(l => `<li class="${esc(l.level)}">${esc(l.text)}</li>`).join('');
    return `${esc(ctx.greeting)}${lines ? `<ul class="df-brief">${lines}</ul>` : ''}`;
  };

  document.addEventListener('click', e => { if (e.target.closest('[data-drflow-ask]')) { e.preventDefault(); openAsk(); } });
  const focusEl = document.querySelector(el.dataset.focus || '.topbar h1') || document.querySelector('h1');
  RD.focus(focusEl);
  const key = `rd-page-${location.pathname}`;
  let shown = false;
  try { shown = !!sessionStorage.getItem(key); sessionStorage.setItem(key, '1'); } catch { /* storage blocked */ }
  RD.summon().then(() => {
    const danger = ctx.lines.some(l => l.level === 'danger');
    if (danger && !shown) RD.alert(html(), actions());
    else RD.say(html(), actions(), {timeout: danger || ctx.lines.length ? 0 : 9000});
  });

  window.DrFlowPage = {
    ask: openAsk,
    /* new findings from the page: speak up once about anything serious that is new */
    update({lines = ctx.lines, greeting = ctx.greeting, encounter, suggest} = {}) {
      ctx.lines = lines; ctx.greeting = greeting;
      if (suggest && suggest.length) ctx.suggest = suggest;
      if (encounter !== undefined) ctx.encounter = encounter;
      const fresh = lines.filter(l => l.level === 'danger' && !seen.has(l.text));
      fresh.forEach(l => seen.add(l.text));
      if (fresh.length) RD.summon().then(() => RD.alert(`<b>Careful:</b><ul class="df-brief">${fresh.map(l => `<li class="danger">${esc(l.text)}</li>`).join('')}</ul>`, actions()));
    },
  };
  if (window.__drflowPending) { window.DrFlowPage.update(window.__drflowPending); delete window.__drflowPending; }
})();
