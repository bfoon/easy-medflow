/* Flow canvas. MFFlow.render(host, graph, opts) draws a flow (designer or read-only run map);
   the designer (when #flow-boot exists) adds editing, an inspector, auto-layout, checks and a simulator that walks
   the flow with sample answers using the same rule engine as the server (MFForm.check). */
(() => {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const NW = 196, NH = 78, reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const PORTS = {start: ['next'], fill: ['next'], approval: ['approved', 'rejected'], review: ['next'], signature: ['signed', 'declined'], condition: ['yes', 'no'],
    parallel: ['next'], join: ['next'], notify: ['next'], set: ['next'], end: []};
  const portsOf = n => n.type === 'route' ? [...((n.config || {}).branches || []).map(b => b.id), 'otherwise'] : PORTS[n.type] || [];
  const portLabel = (n, p, cat) => n.type === 'route' && p !== 'otherwise' ? (((n.config || {}).branches || []).find(b => b.id === p) || {}).label || p : (cat.ports || {})[p] || p;
  const BAD = new Set(['rejected', 'declined', 'no']);
  const nodeH = n => Math.max(NH, 34 + portsOf(n).length * 20);
  const portY = (n, i) => { const ps = portsOf(n); return n.y + nodeH(n) / 2 + (i - (ps.length - 1) / 2) * 20; };

  function summary(n, cat, staff) {
    const c = n.config || {}, a = c.assign;
    const who = !a ? '' : a.mode === 'role' ? `Any ${a.role}` : a.mode === 'users' ? (a.users || []).map(id => (staff.find(s => s.id === id) || {}).name || '?').join(', ') || 'Choose people' : (cat.assign_modes || {})[a.mode] || '';
    switch (n.type) {
      case 'approval': return `${who}${c.mode === 'all' ? ' · all must approve' : c.mode === 'quorum' ? ` · ${c.quorum} must approve` : ''}${c.due_hours ? ` · ${c.due_hours} h` : ''}`;
      case 'fill': case 'review': case 'notify': return `${who}${c.due_hours ? ` · ${c.due_hours} h` : ''}`;
      case 'signature': return (c.signers || []).map(s => s.source === 'role' ? s.role : s.source).join(', ') || 'Add signers';
      case 'condition': return c.rules ? `${(c.rules.all || c.rules.any || []).length} rule(s)` : 'Add rules';
      case 'route': return `${(c.branches || []).length} path(s) + otherwise`;
      case 'set': return c.field ? `${c.field} = ${c.formula || '…'}` : 'Choose a field';
      case 'end': return c.outcome === 'rejected' ? 'Ends as rejected' : 'Ends as completed';
      default: return '';
    }
  }

  /* ---------------------------------------------------------------- renderer */
  function render(host, graph, opts = {}) {
    const cat = opts.catalogue, types = cat.types;
    host.classList.add('fl-host');
    host.innerHTML = `<div class="fl-viewport"><div class="fl-layer"><svg class="fl-edges"><defs>
      <marker id="fl-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10z" fill="#8FA3AE"/></marker>
      <marker id="fl-arrow-on" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10z" fill="#0F7B78"/></marker></defs><g class="fl-e"></g><g class="fl-tokens"></g></svg><div class="fl-nodes"></div></div></div>`;
    const vp = host.querySelector('.fl-viewport'), layer = host.querySelector('.fl-layer'), svg = host.querySelector('.fl-edges');
    let view = {x: 30, y: 30, k: 1};
    const apply = () => layer.style.transform = `translate(${view.x}px,${view.y}px) scale(${view.k})`;

    function draw(sel = {}) {
      const st = opts.states || {}, taken = new Set((opts.taken || []).map(t => `${t.from}|${t.port}`));
      const W = Math.max(900, ...graph.nodes.map(n => n.x + NW + 200)), H = Math.max(420, ...graph.nodes.map(n => n.y + nodeH(n) + 120));
      svg.setAttribute('width', W); svg.setAttribute('height', H); layer.style.width = W + 'px'; layer.style.height = H + 'px';
      const byId = Object.fromEntries(graph.nodes.map(n => [n.id, n]));
      host.querySelector('.fl-e').innerHTML = graph.edges.map(e => {
        const a = byId[e.from], b = byId[e.to]; if (!a || !b) return '';
        const i = Math.max(0, portsOf(a).indexOf(e.port)), x1 = a.x + NW, y1 = portY(a, i), x2 = b.x, y2 = b.y + nodeH(b) / 2;
        const dx = Math.max(40, Math.abs(x2 - x1) / 2), d = `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
        const on = taken.has(`${e.from}|${e.port}`), lab = e.port !== 'next' ? portLabel(a, e.port, cat) : '';
        return `<g class="fl-edge ${BAD.has(e.port) ? 'bad' : ''} ${on ? 'taken' : ''} ${sel.edge === e.id ? 'sel' : ''}" data-edge="${e.id}">
          <path d="${d}" class="hit"/><path d="${d}" class="line" marker-end="url(#${on ? 'fl-arrow-on' : 'fl-arrow'})" id="fl-p-${e.id}"/>
          ${lab ? `<text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 6}" text-anchor="middle">${esc(lab)}</text>` : ''}</g>`;
      }).join('');
      host.querySelector('.fl-nodes').innerHTML = graph.nodes.map(n => {
        const t = types[n.type], ps = portsOf(n), state = st[n.id] || '', tk = (opts.tasks || {})[n.id] || [];
        return `<div class="fl-node t-${n.type} ${state ? 's-' + state : ''} ${sel.node === n.id ? 'sel' : ''} ${opts.problems && opts.problems.has(n.id) ? 'bad' : ''}" data-node="${n.id}" style="left:${n.x}px;top:${n.y}px;height:${nodeH(n)}px;--c:${t.color}" tabindex="0" role="button" aria-label="${esc(n.label)} (${esc(t.label)})">
          <div class="fl-node-h"><i class="bi ${t.icon}"></i><b>${esc(n.label)}</b></div>
          <div class="fl-node-s">${esc(summary(n, cat, opts.staff || []))}</div>
          ${tk.length ? `<div class="fl-node-who">${tk.map(x => `<span class="w-${x.status}${x.overdue ? ' late' : ''}" title="${esc(x.who)}: ${esc(x.status)}">${esc(x.who.split(' ').map(y => y[0]).join('').slice(0, 2))}</span>`).join('')}</div>` : ''}
          ${n.type !== 'start' ? '<span class="fl-in"></span>' : ''}
          ${ps.map((p, i) => `<span class="fl-port ${BAD.has(p) ? 'bad' : ''}" data-port="${esc(p)}" style="top:${portY(n, i) - n.y}px" title="${esc(portLabel(n, p, cat))}"><em>${p === 'next' ? '' : esc(portLabel(n, p, cat))}</em></span>`).join('')}
        </div>`;
      }).join('');
    }
    function fit() {
      if (!graph.nodes.length) return;
      const r = vp.getBoundingClientRect(), minX = Math.min(...graph.nodes.map(n => n.x)), minY = Math.min(...graph.nodes.map(n => n.y));
      const maxX = Math.max(...graph.nodes.map(n => n.x + NW)) + 70, maxY = Math.max(...graph.nodes.map(n => n.y + nodeH(n)));
      // keep text readable: never shrink below 60%; a wider flow starts at the left and can be panned
      view.k = Math.max(.6, Math.min(1.1, (r.width - 60) / (maxX - minX), (r.height - 60) / (maxY - minY)));
      view.x = 30 - minX * view.k + Math.max(0, (r.width - 60 - (maxX - minX) * view.k) / 2);
      view.y = 30 - minY * view.k + Math.max(0, (r.height - 60 - (maxY - minY) * view.k) / 3); apply();
    }
    // pan & zoom
    let pan = null;
    vp.addEventListener('pointerdown', ev => { if (ev.target.closest('.fl-node,.fl-edge')) return; pan = {x: ev.clientX - view.x, y: ev.clientY - view.y}; vp.setPointerCapture(ev.pointerId); vp.classList.add('panning'); opts.onBackground && opts.onBackground(); });
    vp.addEventListener('pointermove', ev => { if (pan) { view.x = ev.clientX - pan.x; view.y = ev.clientY - pan.y; apply(); } });
    vp.addEventListener('pointerup', () => { pan = null; vp.classList.remove('panning'); });
    vp.addEventListener('wheel', ev => { if (!ev.ctrlKey && !opts.editable) return; ev.preventDefault(); const r = vp.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top, k = Math.max(.3, Math.min(2, view.k * (ev.deltaY < 0 ? 1.1 : .9)));
      view.x = mx - (mx - view.x) * k / view.k; view.y = my - (my - view.y) * k / view.k; view.k = k; apply(); }, {passive: false});
    const toWorld = (cx, cy) => { const r = vp.getBoundingClientRect(); return {x: (cx - r.left - view.x) / view.k, y: (cy - r.top - view.y) / view.k}; };

    // token animation along edges (simulator and run map)
    function token(edgeId, cls = '') {
      return new Promise(res => {
        const p = host.querySelector(`#fl-p-${edgeId}`); if (!p || reduce) return res();
        const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        c.setAttribute('r', 7); c.setAttribute('class', `fl-token ${cls}`); host.querySelector('.fl-tokens').appendChild(c);
        const len = p.getTotalLength(), t0 = performance.now(), dur = Math.min(900, 250 + len * 1.4);
        const step = now => { const t = Math.min(1, (now - t0) / dur), pt = p.getPointAtLength(len * (t < .5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2)); c.setAttribute('cx', pt.x); c.setAttribute('cy', pt.y);
          if (t < 1) requestAnimationFrame(step); else { c.remove(); res(); } };
        requestAnimationFrame(step);
      });
    }
    draw(); apply();
    requestAnimationFrame(fit);
    return {draw, fit, token, toWorld, view, zoom(f) { const r = vp.getBoundingClientRect(); const k = Math.max(.3, Math.min(2, view.k * f)); view.x = r.width / 2 - (r.width / 2 - view.x) * k / view.k; view.y = r.height / 2 - (r.height / 2 - view.y) * k / view.k; view.k = k; apply(); }};
  }

  function layout(graph) {
    const out = {}, inc = {};
    graph.edges.forEach(e => { (out[e.from] ||= []).push(e.to); inc[e.to] = (inc[e.to] || 0) + 1; });
    const start = graph.nodes.find(n => n.type === 'start'), depth = {};
    const order = [];
    (function walk(id, d) { if (depth[id] != null && depth[id] >= d) return; depth[id] = d; if (!order.includes(id)) order.push(id); (out[id] || []).forEach(t => walk(t, d + 1)); })(start ? start.id : graph.nodes[0]?.id, 0);
    graph.nodes.forEach(n => { if (depth[n.id] == null) depth[n.id] = 0; });
    const cols = {};
    order.concat(graph.nodes.map(n => n.id).filter(id => !order.includes(id))).forEach(id => { (cols[depth[id]] ||= []).push(id); });
    for (const [d, ids] of Object.entries(cols)) ids.forEach((id, i) => { const n = graph.nodes.find(x => x.id === id); n.x = 40 + d * (NW + 70); n.y = 40 + i * 120 - (ids.length - 1) * 0; });
  }

  /* ---------------------------------------------------------------- simulator (mirrors flows.py routing) */
  async function simulate(graph, values, outcomes, ui, log) {
    const byId = Object.fromEntries(graph.nodes.map(n => [n.id, n])), K = window.MFForm;
    const arrived = {}, states = {}, path = [];
    let result = null, guard = 0;
    const leave = async (n, port) => {
      states[n.id] = 'done'; ui.states(states);
      const nxt = graph.edges.filter(e => e.from === n.id && e.port === port);
      if (!nxt.length) { if (BAD.has(port) && port !== 'no') result ||= 'rejected'; return; }
      await Promise.all(nxt.map(async e => { await ui.token(e.id, BAD.has(port) ? 'bad' : ''); const t = byId[e.to]; if (t.type === 'join') (arrived[t.id] ||= new Set()).add(e.id); await enter(t); }));
    };
    const enter = async n => {
      if (result === 'rejected' || ++guard > 200) return;
      states[n.id] = 'active'; ui.states(states);
      const c = n.config || {};
      await new Promise(r => setTimeout(r, reduce ? 0 : 260));
      switch (n.type) {
        case 'start': case 'parallel': case 'notify': log(`${n.label}`); return leave(n, 'next');
        case 'set': { values[c.field] = K.runFormula(c.formula || '', values); log(`${n.label}: ${c.field} = ${K.text(values[c.field])}`); return leave(n, 'next'); }
        case 'condition': { const ok = K.check(c.rules, values); log(`${n.label}: ${ok ? 'yes' : 'no'}`); return leave(n, ok ? 'yes' : 'no'); }
        case 'route': { const b = (c.branches || []).find(x => K.check(x.rules, values)); log(`${n.label}: ${b ? b.label : 'otherwise'}`); return leave(n, b ? b.id : 'otherwise'); }
        case 'join': { const need = graph.edges.filter(e => e.to === n.id).length; if ((arrived[n.id] || new Set()).size >= need) { log(`${n.label}: every branch arrived`); return leave(n, 'next'); } states[n.id] = 'waiting'; ui.states(states); return; }
        case 'end': log(`${n.label}: ${c.outcome === 'rejected' ? 'rejected' : 'branch complete'}`); states[n.id] = 'done'; ui.states(states); if (c.outcome === 'rejected') result = 'rejected'; return;
        default: { const o = outcomes[n.id] || PORTS[n.type][0]; log(`${n.label}: ${o}`); return leave(n, o); }
      }
    };
    const start = graph.nodes.find(n => n.type === 'start');
    if (!start) return {result: 'invalid'};
    await enter(start);
    const stuck = Object.entries(states).filter(([, s]) => s === 'waiting').map(([id]) => byId[id].label);
    return {result: result || (stuck.length ? 'stuck' : 'approved'), stuck, path};
  }

  window.MFFlow = {render, layout, simulate, portsOf, NW, nodeH};

  /* ================================================================ designer */
  const bootEl = document.getElementById('flow-boot');
  if (!bootEl) return;
  const boot = JSON.parse(bootEl.textContent), cat = boot.catalogue, $ = s => document.querySelector(s);
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
  let G = boot.graph && boot.graph.nodes && boot.graph.nodes.length ? structuredClone(boot.graph) : {nodes: [{id: 'start', type: 'start', label: 'Start', x: 40, y: 140, config: {}}, {id: 'end', type: 'end', label: 'Done', x: 560, y: 140, config: {outcome: 'completed'}}], edges: [{id: 'e1', from: 'start', port: 'next', to: 'end'}]};
  let meta = {name: boot.name, description: boot.description, active: boot.active, form: boot.form};
  let sel = {}, past = [], future = [], dirty = false, connecting = null;
  const fields = () => meta.form && boot.forms[meta.form] ? boot.forms[meta.form].fields : [];
  const snap = () => JSON.stringify({G, meta});
  const commit = fn => { past.push(snap()); if (past.length > 80) past.shift(); future = []; fn(); dirty = true; redraw(); };
  const nodeById = id => G.nodes.find(n => n.id === id);
  const newId = t => { let i = 1; while (G.nodes.some(n => n.id === `${t}${i}`)) i++; return `${t}${i}`; };
  const newEdgeId = () => { let i = 1; while (G.edges.some(e => e.id === `e${i}`)) i++; return `e${i}`; };

  function defaults(type) {
    const c = {};
    if (['approval', 'review', 'fill', 'notify'].includes(type)) c.assign = {mode: 'role', role: type === 'fill' ? 'nurse' : 'doctor'};
    if (type === 'approval') Object.assign(c, {mode: 'any', quorum: 2, allow_return: true});
    if (type === 'notify') c.message = 'A form has moved on.';
    if (type === 'signature') Object.assign(c, {signers: [{source: 'initiator', as: 'signer', order: 1}], require_full_read: false});
    if (type === 'condition') { const f = fields()[0]; c.rules = f ? {all: [{field: f.key, op: 'not_empty'}]} : null; }
    if (type === 'route') { const f = fields()[0]; c.branches = [{id: 'path1', label: 'Path 1', rules: f ? {all: [{field: f.key, op: 'not_empty'}]} : null}]; }
    if (type === 'set') { c.field = (fields()[0] || {}).key || ''; c.formula = ''; }
    if (type === 'end') c.outcome = 'completed';
    return c;
  }

  // ----- problems (mirror of flows.clean_graph)
  function problems() {
    const out = [], bad = new Set(), add = (msg, id) => { out.push({msg, id}); if (id) bad.add(id); };
    if (!meta.name.trim()) add('Give the flow a name.');
    const starts = G.nodes.filter(n => n.type === 'start');
    if (starts.length !== 1) add('A flow needs exactly one Start step.');
    const outE = {}; G.edges.forEach(e => (outE[e.from] ||= []).push(e.to));
    if (starts[0]) {
      const reach = new Set(), st = [starts[0].id]; while (st.length) { const x = st.pop(); if (!reach.has(x)) { reach.add(x); st.push(...(outE[x] || [])); } }
      G.nodes.filter(n => !reach.has(n.id)).forEach(n => add(`“${n.label}” cannot be reached from Start.`, n.id));
      const state = {}; let loop = null;
      const dfs = x => { state[x] = 1; for (const y of outE[x] || []) { if (state[y] === 1) loop ||= y; else if (!state[y]) dfs(y); } state[x] = 2; };
      dfs(starts[0].id);
      if (loop) add(`The flow loops back to “${nodeById(loop).label}”. Use “send back for changes” instead of loops.`, loop);
    }
    const keys = new Set(fields().map(f => f.key));
    const treeOk = t => t && ('op' in t ? keys.has(t.field.split('.')[0]) : (t.all || t.any || []).length && (t.all || t.any).every(treeOk));
    for (const n of G.nodes) {
      const c = n.config || {};
      if (n.type === 'join' && G.edges.filter(e => e.to === n.id).length < 2) add(`“${n.label}” waits for branches but fewer than two arrive.`, n.id);
      if (n.type === 'parallel' && G.edges.filter(e => e.from === n.id).length < 2) add(`“${n.label}” should start at least two branches.`, n.id);
      if (c.assign && c.assign.mode === 'users' && !(c.assign.users || []).length) add(`“${n.label}”: choose at least one person.`, n.id);
      if (n.type === 'signature' && !(c.signers || []).length) add(`“${n.label}”: add at least one signer.`, n.id);
      if (n.type === 'condition' && !treeOk(c.rules)) add(`“${n.label}”: add rules${meta.form ? '' : ' (choose a form first)'}.`, n.id);
      if (n.type === 'route' && (!(c.branches || []).length || !(c.branches || []).every(b => treeOk(b.rules)))) add(`“${n.label}”: every path needs rules${meta.form ? '' : ' (choose a form first)'}.`, n.id);
      if (n.type === 'set' && !keys.has(c.field)) add(`“${n.label}”: choose a form field to write to.`, n.id);
      if (n.type === 'set' && c.field) { const t = MFForm.tryFormula(c.formula || '', {}); if (!t.ok) add(`“${n.label}”: ${t.error}`, n.id); }
      if (n.type === 'fill' && meta.form && !fields().some(f => f.filled_by === n.id)) add(`“${n.label}”: no form fields are filled in at this step (set “Filled in at” to ${n.id} in the form designer).`, n.id);
    }
    return {list: out, nodes: bad};
  }

  // ----- drawing
  let R;
  function redraw() {
    const p = problems();
    R.draw(sel);
    host.querySelectorAll('.fl-node').forEach(el => el.classList.toggle('bad', p.nodes.has(el.dataset.node)));
    $('#wf-problems').className = `fd-problems ${p.list.length ? 'bad' : 'ok'}`;
    $('#wf-problems').innerHTML = p.list.length ? `<b><i class="bi bi-exclamation-triangle-fill"></i>${p.list.length} thing${p.list.length > 1 ? 's' : ''} to fix</b><ul>${p.list.slice(0, 8).map(x => `<li ${x.id ? `data-goto="${x.id}"` : ''}>${esc(x.msg)}</li>`).join('')}</ul>` : '<span><i class="bi bi-check-circle-fill"></i>The flow is valid</span>';
    $('#wf-save').disabled = !!p.list.length;
    $('#wf-undo').disabled = !past.length; $('#wf-redo').disabled = !future.length;
    $('#wf-dirty').hidden = !dirty;
    inspector();
  }
  const host = $('#wf-canvas');
  R = render(host, G, {catalogue: cat, editable: true, staff: boot.staff, onBackground: () => { if (sel.node || sel.edge) { sel = {}; redraw(); } }});

  // ----- node dragging, connecting, selecting
  host.addEventListener('pointerdown', ev => {
    const port = ev.target.closest('.fl-port'), node = ev.target.closest('.fl-node'), edge = ev.target.closest('.fl-edge');
    if (port) {
      ev.stopPropagation(); ev.preventDefault();
      const n = nodeById(node.dataset.node), p = port.dataset.port, i = portsOf(n).indexOf(p);
      connecting = {from: n.id, port: p, x1: n.x + NW, y1: portY(n, i)};
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'path'); line.setAttribute('class', 'fl-ghost'); host.querySelector('.fl-e').appendChild(line); connecting.line = line;
      host.setPointerCapture(ev.pointerId);
      return;
    }
    if (node) {
      ev.stopPropagation();
      const n = nodeById(node.dataset.node), w = R.toWorld(ev.clientX, ev.clientY);
      sel = {node: n.id}; let moved = false;
      const off = {x: w.x - n.x, y: w.y - n.y}, before = snap();
      const mv = e => { const p = R.toWorld(e.clientX, e.clientY); n.x = Math.round((p.x - off.x) / 10) * 10; n.y = Math.round((p.y - off.y) / 10) * 10; moved = true; R.draw(sel); };
      const up = () => { document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up); if (moved) { past.push(before); future = []; dirty = true; } redraw(); };
      document.addEventListener('pointermove', mv); document.addEventListener('pointerup', up);
      return;
    }
    if (edge) { ev.stopPropagation(); sel = {edge: edge.dataset.edge}; redraw(); }
  });
  host.addEventListener('pointermove', ev => {
    if (!connecting) return;
    const p = R.toWorld(ev.clientX, ev.clientY), {x1, y1} = connecting, dx = Math.max(40, Math.abs(p.x - x1) / 2);
    connecting.line.setAttribute('d', `M${x1},${y1} C${x1 + dx},${y1} ${p.x - dx},${p.y} ${p.x},${p.y}`);
    host.querySelectorAll('.fl-node').forEach(el => el.classList.toggle('target', el.contains(document.elementFromPoint(ev.clientX, ev.clientY)) && el.dataset.node !== connecting.from));
  });
  host.addEventListener('pointerup', ev => {
    if (!connecting) return;
    const tgt = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.fl-node'), c = connecting; connecting = null; c.line.remove();
    host.querySelectorAll('.target').forEach(x => x.classList.remove('target'));
    if (!tgt || tgt.dataset.node === c.from || nodeById(tgt.dataset.node).type === 'start') return;
    commit(() => {
      const from = nodeById(c.from);
      if (from.type !== 'parallel') G.edges = G.edges.filter(e => !(e.from === c.from && e.port === c.port));
      if (!G.edges.some(e => e.from === c.from && e.port === c.port && e.to === tgt.dataset.node)) G.edges.push({id: newEdgeId(), from: c.from, port: c.port, to: tgt.dataset.node});
    });
  });
  host.addEventListener('keydown', ev => { const n = ev.target.closest('.fl-node'); if (n && (ev.key === 'Enter' || ev.key === ' ')) { sel = {node: n.dataset.node}; redraw(); $('#wf-insp input')?.focus(); } });

  // palette
  $('#wf-palette').innerHTML = Object.entries(cat.types).filter(([t]) => t !== 'start').map(([t, d]) => `<button type="button" data-type="${t}" draggable="true" style="--c:${d.color}" title="${esc(d.hint)}"><i class="bi ${d.icon}"></i><span>${esc(d.label)}<small>${esc(d.hint)}</small></span></button>`).join('');
  const addNode = (type, at) => commit(() => {
    const id = newId(type), r = host.getBoundingClientRect(), p = at || R.toWorld(r.left + r.width / 2 - 90, r.top + r.height / 2 - 40);
    const n = {id, type, label: cat.types[type].label, x: Math.round(p.x / 10) * 10, y: Math.round(p.y / 10) * 10, config: defaults(type)};
    if (sel.node && !at) { const s = nodeById(sel.node); n.x = s.x + NW + 70; n.y = s.y; const port = portsOf(s).find(pp => !G.edges.some(e => e.from === s.id && e.port === pp)); if (port) G.edges.push({id: newEdgeId(), from: s.id, port, to: id}); }
    G.nodes.push(n); sel = {node: id};
  });
  $('#wf-palette').addEventListener('click', ev => { const b = ev.target.closest('[data-type]'); if (b) addNode(b.dataset.type); });
  $('#wf-palette').addEventListener('dragstart', ev => { const b = ev.target.closest('[data-type]'); if (b) ev.dataTransfer.setData('text/flow-type', b.dataset.type); });
  host.addEventListener('dragover', ev => { if (ev.dataTransfer.types.includes('text/flow-type')) ev.preventDefault(); });
  host.addEventListener('drop', ev => { const t = ev.dataTransfer.getData('text/flow-type'); if (!t) return; ev.preventDefault(); const p = R.toWorld(ev.clientX, ev.clientY); addNode(t, {x: p.x - NW / 2, y: p.y - NH / 2}); });

  // ----- inspector
  const roleOpts = v => cat.roles.map(r => `<option ${r === v ? 'selected' : ''}>${r}</option>`).join('');
  function assignHtml(a) {
    return `<label>Who<select class="form-select form-select-sm" data-c="assign.mode">${Object.entries(cat.assign_modes).map(([k, l]) => `<option value="${k}" ${a.mode === k ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></label>
      ${a.mode === 'role' ? `<label>Role<select class="form-select form-select-sm" data-c="assign.role">${roleOpts(a.role)}</select></label>` : ''}
      ${a.mode === 'users' ? `<div class="wf-people">${boot.staff.map(s => `<label class="fd-chk"><input type="checkbox" data-user="${s.id}" ${(a.users || []).includes(s.id) ? 'checked' : ''}>${esc(s.name)} <small class="muted">${esc(s.role)}</small></label>`).join('')}</div>` : ''}`;
  }
  function rulesHtml(t, path) {
    const fl = fields();
    if (!fl.length) return '<p class="small muted">Choose the form this flow is for (top bar) to write rules on its answers.</p>';
    const mode = t && 'any' in t ? 'any' : 'all', rules = t ? t[mode] || [] : [];
    return `<div class="wf-rules" data-path="${path}">${rules.length > 1 ? `<div class="fd-mode">Match <select class="form-select form-select-sm" data-rmode><option value="all" ${mode === 'all' ? 'selected' : ''}>all</option><option value="any" ${mode === 'any' ? 'selected' : ''}>any</option></select></div>` : ''}
      ${rules.map((r, i) => { const src = fl.find(f => f.key === r.field); return `<div class="fd-rule" data-i="${i}"><select class="form-select form-select-sm" data-r="field">${fl.map(f => `<option value="${f.key}" ${f.key === r.field ? 'selected' : ''}>${esc(f.label)}</option>`).join('')}</select>
        <select class="form-select form-select-sm" data-r="op">${Object.entries(cat.formkit.ops).map(([k, l]) => `<option value="${k}" ${k === r.op ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>
        ${cat.formkit.unary.includes(r.op) ? '' : src && src.options.length && ['eq', 'neq'].includes(r.op) ? `<select class="form-select form-select-sm" data-r="value">${src.options.map(o => `<option ${o === r.value ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>` : `<input class="form-control form-control-sm" data-r="value" value="${esc(r.value)}">`}
        ${cat.formkit.range.includes(r.op) ? `<input class="form-control form-control-sm" data-r="value2" value="${esc(r.value2)}">` : ''}<span class="fd-rule-tools"><button type="button" data-rdel aria-label="Remove rule"><i class="bi bi-x-lg"></i></button></span></div>`; }).join('')}
      <button type="button" class="btn btn-sm btn-ghost" data-radd><i class="bi bi-plus-lg"></i>Rule</button></div>`;
  }
  function inspector() {
    const box = $('#wf-insp');
    if (sel.edge) { const e = G.edges.find(x => x.id === sel.edge); if (!e) { sel = {}; return inspector(); } box.innerHTML = `<h3>Arrow</h3><p>${esc(nodeById(e.from).label)} → ${esc(nodeById(e.to).label)}${e.port !== 'next' ? ` when <b>${esc(portLabel(nodeById(e.from), e.port, cat))}</b>` : ''}</p><button type="button" class="btn btn-sm btn-ghost" data-del-edge><i class="bi bi-trash"></i>Remove arrow</button>`; return; }
    const n = sel.node && nodeById(sel.node);
    if (!n) { box.innerHTML = `<h3>How to build a flow</h3><ol class="small"><li>Add steps from the left, or drag them onto the canvas.</li><li>Drag from a coloured dot on the right of a step to the next step.</li><li>Click a step to set who does it and when it is due.</li><li>Press <b>Simulate</b> to test it with sample answers.</li></ol><p class="small muted">An unconnected Rejected/Declined exit rejects the whole flow; other unconnected exits simply finish that branch.</p>`; return; }
    const c = n.config, t = cat.types[n.type];
    let h = `<div class="wf-insp-h" style="--c:${t.color}"><i class="bi ${t.icon}"></i>${esc(t.label)} <code>${n.id}</code></div><p class="small muted">${esc(t.hint)}</p>
      <label>Name<input class="form-control form-control-sm" data-c="label" value="${esc(n.label)}"></label>`;
    if (c.assign) h += assignHtml(c.assign);
    if (n.type === 'approval') h += `<label>Decision<select class="form-select form-select-sm" data-c="mode"><option value="any" ${c.mode === 'any' ? 'selected' : ''}>The first approval moves it on</option><option value="all" ${c.mode === 'all' ? 'selected' : ''}>Everyone must approve</option><option value="quorum" ${c.mode === 'quorum' ? 'selected' : ''}>A number of people must approve</option></select></label>
      ${c.mode === 'quorum' ? `<label>How many<input type="number" min="1" max="10" class="form-control form-control-sm" data-c="quorum" value="${c.quorum}"></label>` : ''}<label class="fd-chk"><input type="checkbox" data-c="allow_return" ${c.allow_return ? 'checked' : ''}>Can send back for changes</label>`;
    if (['approval', 'review', 'fill'].includes(n.type)) h += `<div class="fd-row3"><label>Due within (hours)<input type="number" min="1" class="form-control form-control-sm" data-c="due_hours" value="${c.due_hours || ''}" placeholder="No deadline"></label>
      ${c.due_hours ? `<label>Then also alert<select class="form-select form-select-sm" data-c="escalate_role"><option value="">Nobody else</option>${roleOpts(c.escalate_role)}</select></label>` : ''}</div>`;
    if (n.type === 'fill') h += `<p class="small">Fields filled in here: ${fields().filter(f => f.filled_by === n.id).map(f => `<span class="tag">${esc(f.label)}</span>`).join(' ') || '<span class="muted">none yet (set “Filled in at” to <code>' + n.id + '</code> in the form designer)</span>'}</p>`;
    if (n.type === 'notify') h += `<label>Message<input class="form-control form-control-sm" data-c="message" value="${esc(c.message)}"></label>`;
    if (n.type === 'signature') h += `<h4>Signers</h4>${(c.signers || []).map((s, i) => `<div class="wf-signer" data-si="${i}"><select class="form-select form-select-sm" data-s="source">${Object.entries(cat.signer_sources).map(([k, l]) => `<option value="${k}" ${s.source === k ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>
        ${s.source === 'role' ? `<select class="form-select form-select-sm" data-s="role">${roleOpts(s.role)}</select>` : ''}
        <select class="form-select form-select-sm" data-s="as">${[['signer', 'Signs'], ['in_person', 'Signs in person'], ['witness', 'Witnesses'], ['approver', 'Approves']].map(([k, l]) => `<option value="${k}" ${s.as === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
        <label class="wf-order">Order<input type="number" min="1" max="9" class="form-control form-control-sm" data-s="order" value="${s.order}"></label><button type="button" class="btn btn-sm btn-ghost" data-sdel aria-label="Remove signer"><i class="bi bi-x-lg"></i></button></div>`).join('')}
      <button type="button" class="btn btn-sm btn-ghost" data-sadd><i class="bi bi-plus-lg"></i>Signer</button><p class="small muted">Same order number = sign at the same time. The patient signs on this device with a staff host who confirms their identity.</p>
      <label class="fd-chk"><input type="checkbox" data-c="require_full_read" ${c.require_full_read ? 'checked' : ''}>Signers must page through the whole document</label>`;
    if (n.type === 'condition') h += `<h4>Go to “Yes” when</h4>${rulesHtml(c.rules, 'rules')}`;
    if (n.type === 'route') h += (c.branches || []).map((b, i) => `<div class="wf-branch"><div class="d-flex gap-2 align-items-center"><input class="form-control form-control-sm" data-b="${i}" value="${esc(b.label)}" aria-label="Path name"><button type="button" class="btn btn-sm btn-ghost" data-bdel="${i}" aria-label="Remove path"><i class="bi bi-x-lg"></i></button></div>${rulesHtml(b.rules, `branches.${i}.rules`)}</div>`).join('') + `<button type="button" class="btn btn-sm btn-ghost" data-badd><i class="bi bi-plus-lg"></i>Path</button><p class="small muted">Paths are checked from the top; the first that matches is taken, otherwise “Otherwise”.</p>`;
    if (n.type === 'set') h += `<label>Write to<select class="form-select form-select-sm" data-c="field">${fields().map(f => `<option value="${f.key}" ${f.key === c.field ? 'selected' : ''}>${esc(f.label)}</option>`).join('')}</select></label><label>Formula<input class="form-control form-control-sm" data-c="formula" value="${esc(c.formula)}" spellcheck="false" placeholder="e.g. if(amount > 1000, &quot;High&quot;, &quot;Normal&quot;)"></label>`;
    if (n.type === 'end') h += `<label>Outcome<select class="form-select form-select-sm" data-c="outcome"><option value="completed" ${c.outcome !== 'rejected' ? 'selected' : ''}>Completed</option><option value="rejected" ${c.outcome === 'rejected' ? 'selected' : ''}>Rejected</option></select></label>`;
    if (n.type !== 'start') h += `<button type="button" class="btn btn-sm btn-ghost mt-2" data-del-node><i class="bi bi-trash"></i>Delete step</button>`;
    box.innerHTML = h;
  }
  const getPath = (o, p) => p.split('.').reduce((a, k) => a[k], o);
  $('#wf-insp').addEventListener('input', ev => {
    const el = ev.target, n = sel.node && nodeById(sel.node); if (!n) return;
    past.push(snap()); future = []; dirty = true;
    const c = n.config, val = el.type === 'checkbox' ? el.checked : el.type === 'number' ? (el.value === '' ? null : +el.value) : el.value;
    if (el.dataset.c === 'label') n.label = el.value;
    else if (el.dataset.c && el.dataset.c.startsWith('assign.')) { c.assign[el.dataset.c.slice(7)] = val; if (el.dataset.c === 'assign.mode' && val === 'role') c.assign.role ||= 'doctor'; }
    else if (el.dataset.c) { if (val === null || val === '') delete c[el.dataset.c]; else c[el.dataset.c] = val; }
    else if (el.dataset.user) { const set = new Set(c.assign.users || []); el.checked ? set.add(+el.dataset.user) : set.delete(+el.dataset.user); c.assign.users = [...set]; }
    else if (el.dataset.s) { const s = c.signers[+el.closest('[data-si]').dataset.si]; s[el.dataset.s] = el.dataset.s === 'order' ? Math.max(1, +el.value || 1) : el.value; if (el.dataset.s === 'source' && el.value === 'patient') s.as = 'in_person'; }
    else if (el.dataset.b !== undefined) c.branches[+el.dataset.b].label = el.value;
    else { const rb = el.closest('.wf-rules'); if (!rb) return; const holder = rb.dataset.path.split('.'), key = holder.pop(), parent = holder.length ? getPath(c, holder.join('.')) : c, t = parent[key], mode = 'any' in t ? 'any' : 'all';
      if (el.dataset.rmode !== undefined) parent[key] = {[el.value]: t[mode]}; else { const r = t[mode][+el.closest('.fd-rule').dataset.i]; r[el.dataset.r] = el.value; if (el.dataset.r === 'field') r.value = ''; } }
    if (el.tagName === 'SELECT' || el.type === 'checkbox') redraw(); else { R.draw(sel); const p = problems(); $('#wf-save').disabled = !!p.list.length; }
  });
  $('#wf-insp').addEventListener('click', ev => {
    const b = ev.target.closest('button'); if (!b) return;
    if (b.hasAttribute('data-del-edge')) return commit(() => { G.edges = G.edges.filter(e => e.id !== sel.edge); sel = {}; });
    const n = sel.node && nodeById(sel.node); if (!n) return; const c = n.config;
    if (b.hasAttribute('data-del-node')) return commit(() => { G.nodes = G.nodes.filter(x => x.id !== n.id); G.edges = G.edges.filter(e => e.from !== n.id && e.to !== n.id); sel = {}; });
    if (b.hasAttribute('data-sadd')) return commit(() => c.signers.push({source: 'clinician', as: 'signer', order: (c.signers.at(-1) || {order: 0}).order + 1}));
    if (b.hasAttribute('data-sdel')) return commit(() => c.signers.splice(+b.closest('[data-si]').dataset.si, 1));
    if (b.hasAttribute('data-badd')) return commit(() => { let i = c.branches.length + 1; while (c.branches.some(x => x.id === `path${i}`)) i++; const f = fields()[0]; c.branches.push({id: `path${i}`, label: `Path ${i}`, rules: f ? {all: [{field: f.key, op: 'not_empty'}]} : null}); });
    if (b.dataset.bdel !== undefined) return commit(() => { const [br] = c.branches.splice(+b.dataset.bdel, 1); G.edges = G.edges.filter(e => !(e.from === n.id && e.port === br.id)); });
    const rb = b.closest('.wf-rules'); if (!rb) return;
    const holder = rb.dataset.path.split('.'), key = holder.pop(), parent = holder.length ? getPath(c, holder.join('.')) : c;
    if (b.hasAttribute('data-radd')) return commit(() => { const f = fields()[0]; const r = {field: f.key, op: 'not_empty'}; if (!parent[key]) parent[key] = {all: [r]}; else parent[key]['any' in parent[key] ? 'any' : 'all'].push(r); });
    if (b.hasAttribute('data-rdel')) return commit(() => { const t = parent[key], m = 'any' in t ? 'any' : 'all'; t[m].splice(+b.closest('.fd-rule').dataset.i, 1); if (!t[m].length) parent[key] = null; });
  });

  // ----- toolbar
  $('#wf-name').value = meta.name; $('#wf-desc').value = meta.description; $('#wf-active').checked = meta.active;
  $('#wf-form').value = meta.form || '';
  $('#wf-name').oninput = e => { meta.name = e.target.value; dirty = true; redraw(); };
  $('#wf-desc').oninput = e => { meta.description = e.target.value; dirty = true; };
  $('#wf-active').onchange = e => { meta.active = e.target.checked; dirty = true; redraw(); };
  $('#wf-form').onchange = e => commit(() => { meta.form = e.target.value ? +e.target.value : null; });
  $('#wf-undo').onclick = () => { if (!past.length) return; future.push(snap()); ({G, meta} = JSON.parse(past.pop())); R = render(host, G, {catalogue: cat, editable: true, staff: boot.staff, onBackground: () => { sel = {}; redraw(); }}); redraw(); };
  $('#wf-redo').onclick = () => { if (!future.length) return; past.push(snap()); ({G, meta} = JSON.parse(future.pop())); R = render(host, G, {catalogue: cat, editable: true, staff: boot.staff, onBackground: () => { sel = {}; redraw(); }}); redraw(); };
  $('#wf-layout').onclick = () => commit(() => { layout(G); setTimeout(() => R.fit(), 0); });
  $('#wf-fit').onclick = () => R.fit();
  $('#wf-zin').onclick = () => R.zoom(1.15); $('#wf-zout').onclick = () => R.zoom(1 / 1.15);
  $('#wf-problems').addEventListener('click', ev => { const li = ev.target.closest('[data-goto]'); if (li) { sel = {node: li.dataset.goto}; redraw(); } });
  document.addEventListener('keydown', ev => {
    const typing = ev.target.matches('input, textarea, select'), mod = ev.ctrlKey || ev.metaKey;
    if (mod && ev.key.toLowerCase() === 's') { ev.preventDefault(); save(); }
    else if (!typing && mod && ev.key.toLowerCase() === 'z') { ev.preventDefault(); (ev.shiftKey ? $('#wf-redo') : $('#wf-undo')).click(); }
    else if (!typing && (ev.key === 'Delete' || ev.key === 'Backspace')) {
      if (sel.edge) commit(() => { G.edges = G.edges.filter(e => e.id !== sel.edge); sel = {}; });
      else if (sel.node && nodeById(sel.node).type !== 'start') commit(() => { G.nodes = G.nodes.filter(x => x.id !== sel.node); G.edges = G.edges.filter(e => e.from !== sel.node && e.to !== sel.node); sel = {}; });
    }
  });

  async function save() {
    if (problems().list.length) return;
    const body = new URLSearchParams({name: meta.name, description: meta.description || '', graph: JSON.stringify(G), form: meta.form || '', csrfmiddlewaretoken: csrf});
    if (meta.active) body.set('active', 'on');
    const b = $('#wf-save'); b.disabled = true; b.classList.add('busy');
    try {
      const r = await fetch(boot.save_url, {method: 'POST', body, headers: {Accept: 'application/json'}, credentials: 'same-origin'}), d = await r.json();
      if (!d.ok) { $('#wf-problems').className = 'fd-problems bad'; $('#wf-problems').innerHTML = `<b>The server found problems</b><ul>${d.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>`; }
      else { dirty = false; $('#wf-dirty').hidden = true; toast('Flow saved.'); if (location.pathname !== d.url) history.replaceState(null, '', d.url); boot.save_url = d.url; }
    } catch (e) { toast('Could not reach the server. Nothing was lost; try again.', true); }
    b.disabled = false; b.classList.remove('busy');
  }
  $('#wf-save').onclick = save;
  function toast(m, bad) { const t = $('#wf-toast'); t.textContent = m; t.className = `fd-toast show${bad ? ' bad' : ''}`; clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 3500); }
  window.addEventListener('beforeunload', ev => { if (dirty) { ev.preventDefault(); ev.returnValue = ''; } });

  // ----- simulator
  $('#wf-sim').onclick = () => {
    const panel = $('#wf-simpanel'); panel.hidden = !panel.hidden; if (panel.hidden) return;
    const fl = fields(), humans = G.nodes.filter(n => ['approval', 'signature'].includes(n.type));
    $('#wf-simform').innerHTML = (fl.length ? `<h4>Sample answers</h4>${fl.map(f => `<label>${esc(f.label)}${f.options.length ? `<select class="form-select form-select-sm" data-sim="${f.key}"><option value=""></option>${f.options.map(o => `<option>${esc(o)}</option>`).join('')}</select>` : f.type === 'checkbox' ? `<input type="checkbox" data-sim="${f.key}">` : f.type === 'yesno' ? `<select class="form-select form-select-sm" data-sim="${f.key}"><option value=""></option><option value="yes">Yes</option><option value="no">No</option></select>` : `<input class="form-control form-control-sm" data-sim="${f.key}" ${f.type === 'number' ? 'type="number"' : f.type === 'date' ? 'type="date"' : ''}>`}</label>`).join('')}` : '<p class="small muted">Choose a form to test rules with answers.</p>')
      + (humans.length ? `<h4>Decisions</h4>${humans.map(n => `<label>${esc(n.label)}<select class="form-select form-select-sm" data-out="${n.id}">${PORTS[n.type].map(p => `<option value="${p}">${esc(cat.ports[p])}</option>`).join('')}</select></label>`).join('')}` : '');
  };
  $('#wf-simrun').onclick = async () => {
    const vals = {}, outcomes = {};
    document.querySelectorAll('[data-sim]').forEach(el => { const f = fields().find(x => x.key === el.dataset.sim); vals[el.dataset.sim] = el.type === 'checkbox' ? el.checked : f.type === 'number' ? (el.value === '' ? null : +el.value) : el.value; });
    document.querySelectorAll('[data-out]').forEach(el => { outcomes[el.dataset.out] = el.value; });
    const log = $('#wf-simlog'); log.innerHTML = ''; $('#wf-simrun').disabled = true;
    const states = {};
    const res = await simulate(G, vals, outcomes, {
      token: (id, cls) => R.token(id, cls),
      states: s => { Object.assign(states, s); host.querySelectorAll('.fl-node').forEach(el => { el.classList.remove('s-active', 's-done', 's-waiting'); const v = states[el.dataset.node]; if (v) el.classList.add('s-' + v); }); },
    }, m => log.insertAdjacentHTML('beforeend', `<li>${esc(m)}</li>`));
    log.insertAdjacentHTML('beforeend', `<li class="res r-${res.result}">${{approved: 'Result: completed / approved', rejected: 'Result: rejected', stuck: `Stuck waiting at ${res.stuck.join(', ')}: a branch never reaches it`, invalid: 'The flow has no Start step'}[res.result]}</li>`);
    $('#wf-simrun').disabled = false;
    setTimeout(() => host.querySelectorAll('.fl-node').forEach(el => el.classList.remove('s-active', 's-done', 's-waiting')), 6000);
  };

  if (boot.errors && boot.errors.length) toast(boot.errors[0], true);
  redraw();
})();
