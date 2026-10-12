/* Forms engine for the browser: the same conditions, formula language and checks as hospital/formkit.py.
   Used by the form designer (preview, formula tester, flow simulator) and by the fill-in page.
   Parity is tested in tests.FormkitParityTests by running the same cases through Node and Python. */
(function (root) {
  'use strict';
  const rnd = (x, d = 0) => { const m = 10 ** d; return Math.floor(x * m + 0.5) / m; };
  const isNum = v => typeof v === 'number' && Number.isFinite(v);

  const filled = v => v == null ? false : typeof v === 'string' ? v.trim() !== '' : Array.isArray(v) ? v.length > 0 : typeof v === 'object' ? Object.keys(v).length > 0 : true;
  function asNum(v) {
    if (typeof v === 'boolean') return v ? 1 : 0;
    if (typeof v === 'number') return Number.isFinite(v) ? v : null;
    if (v == null) return null;
    const s = String(v).trim();
    if (!/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(s) && !/^[-+]?(inf|infinity|nan)$/i.test(s)) return null;
    const x = parseFloat(s);
    return Number.isFinite(x) ? x : null;
  }
  // dates are whole days since 1970 (UTC) so "today" and differences are exact
  const dayNum = (y, m, d) => Date.UTC(y, m - 1, d) / 864e5;
  function todayStr(today) { if (today) return today; const n = new Date(); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`; }
  function asDate(v, today) {
    if (typeof v === 'string' && v.trim().toLowerCase() === 'today') v = today;
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v ?? ''));
    if (!m) return null;
    const y = +m[1], mo = +m[2], d = +m[3], dt = new Date(Date.UTC(y, mo - 1, d));
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null;
    return {y, m: mo, d, n: dayNum(y, mo, d)};
  }
  const truthy = v => typeof v === 'string' ? ['yes', 'true', '1', 'on', 'y'].includes(v.trim().toLowerCase()) : Array.isArray(v) ? v.length > 0 : (v && typeof v === 'object') ? Object.keys(v).length > 0 : !!v;
  function text(v) {
    if (v == null) return '';
    if (typeof v === 'boolean') return v ? 'yes' : 'no';
    if (typeof v === 'number') return String(v);
    if (Array.isArray(v)) return v.map(text).join(', ');
    return String(v);
  }
  const list = v => Array.isArray(v) ? v.map(x => text(x).trim().toLowerCase()) : text(v).split(',').map(x => x.trim().toLowerCase()).filter(Boolean);
  function get(values, path) {
    const [head, ...rest] = String(path).split('.');
    let v = values[head];
    if (rest.length && v && typeof v === 'object' && !Array.isArray(v)) v = v[rest.join('.')];
    return v;
  }

  /* ---------------------------------------------------------------- conditions */
  const UNARY = new Set(['empty', 'not_empty', 'truthy', 'falsy', 'in_past', 'in_future']);
  const RANGE = new Set(['between', 'not_between']);
  const LISTY = new Set(['in', 'not_in', 'includes_any', 'includes_all']);
  function checkRule(rule, values, today) {
    today = todayStr(today);
    const op = rule.op, left = get(values, rule.field || ''), right = rule.ref ? get(values, rule.ref) : rule.value;
    if (op === 'empty') return !filled(left);
    if (op === 'not_empty') return filled(left);
    if (op === 'truthy') return truthy(left);
    if (op === 'falsy') return !truthy(left);
    const T = asDate(today, today);
    if (op === 'in_past' || op === 'in_future') { const d = asDate(left, today); return !!d && (op === 'in_past' ? d.n < T.n : d.n > T.n); }
    if (op === 'within_days') { const d = asDate(left, today), n = asNum(right); return !!d && n != null && T.n <= d.n && d.n <= T.n + n; }
    if (op === 'before' || op === 'after') { const a = asDate(left, today), b = asDate(right, today); return !!a && !!b && (op === 'before' ? a.n < b.n : a.n > b.n); }
    if (LISTY.has(op)) {
      const options = list(right), have = Array.isArray(left) ? list(left) : [text(left).trim().toLowerCase()];
      if (op === 'in') return have.length ? options.includes(have[0]) : false;
      if (op === 'not_in') return !have.length || !options.includes(have[0]);
      if (op === 'includes_any') return have.some(x => options.includes(x));
      return options.every(x => have.includes(x));
    }
    if (['gt', 'gte', 'lt', 'lte'].includes(op) || RANGE.has(op)) {
      const a = asNum(left), b = asNum(right);
      if (RANGE.has(op)) {
        const c = asNum(rule.value2), inside = a != null && b != null && c != null && Math.min(b, c) <= a && a <= Math.max(b, c);
        return op === 'between' ? inside : (a != null && !inside);
      }
      if (a == null || b == null) return false;
      return {gt: a > b, gte: a >= b, lt: a < b, lte: a <= b}[op];
    }
    const ls = text(left).trim().toLowerCase(), rs = text(right).trim().toLowerCase();
    if (op === 'eq' || op === 'neq') {
      const a = asNum(left), b = asNum(right);
      const same = (a != null && b != null && typeof left !== 'boolean') ? a === b : (ls === rs || (typeof left === 'boolean' && truthy(left) === truthy(right)));
      return op === 'eq' ? same : !same;
    }
    if (op === 'contains') return ls.includes(rs);
    if (op === 'not_contains') return !ls.includes(rs);
    if (op === 'starts_with') return ls.startsWith(rs);
    return false;
  }
  function check(tree, values, today) {
    if (!tree) return true;
    if ('op' in tree) return checkRule(tree, values, today);
    const items = ('all' in tree ? tree.all : tree.any) || [];
    const res = items.map(x => check(x, values, today));
    const out = 'all' in tree ? res.every(Boolean) : res.length ? res.some(Boolean) : true;
    return tree.not ? !out : out;
  }

  /* ---------------------------------------------------------------- formulas */
  class FormulaError extends Error {}
  const TOKEN = /\s*(?:(\d+\.?\d*|\.\d+)|('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)|(==|!=|<=|>=|&&|\|\||[-+*/%^(),<>!]))/y;
  const FUNCS = new Set(['sum', 'min', 'max', 'avg', 'round', 'floor', 'ceil', 'abs', 'sqrt', 'if', 'coalesce', 'len', 'count', 'today', 'days_between', 'age', 'bmi', 'concat', 'upper', 'lower', 'col', 'number', 'text']);
  function tokenize(src) {
    src = String(src ?? '');
    if (src.length > 500) throw new FormulaError('Formula is too long (500 characters at most).');
    const out = []; let pos = 0;
    while (pos < src.length) {
      if (src.slice(pos).trim() === '') break;
      TOKEN.lastIndex = pos;
      const m = TOKEN.exec(src);
      if (!m || TOKEN.lastIndex === pos) throw new FormulaError(`Cannot read the formula near "${src.slice(pos, pos + 10).trim()}".`);
      const [, num, s, name, op] = m;
      if (num !== undefined) out.push(['num', parseFloat(num)]);
      else if (s !== undefined) out.push(['str', s.slice(1, -1).replace(/\\(.)/g, '$1')]);
      else if (name !== undefined) {
        const low = name.toLowerCase();
        if (low === 'and') out.push(['op', '&&']); else if (low === 'or') out.push(['op', '||']); else if (low === 'not') out.push(['op', '!']);
        else if (low === 'true') out.push(['lit', true]); else if (low === 'false') out.push(['lit', false]); else if (low === 'null') out.push(['lit', null]);
        else out.push(['name', name]);
      } else out.push(['op', op]);
      pos = TOKEN.lastIndex;
    }
    return out;
  }
  const PREC = {'||': 1, '&&': 2, '==': 3, '!=': 3, '<': 4, '<=': 4, '>': 4, '>=': 4, '+': 5, '-': 5, '*': 6, '/': 6, '%': 6, '^': 8};
  function parse(src) {
    const toks = tokenize(src); let i = 0;
    if (!toks.length) throw new FormulaError('The formula is empty.');
    const peek = () => toks[i] || ['end', null], take = () => toks[i++] || ['end', null];
    const isOp = (t, v) => t[0] === 'op' && t[1] === v;
    const expect = v => { if (!isOp(take(), v)) throw new FormulaError(`Expected "${v}" in the formula.`); };
    function primary() {
      const t = take();
      if (t[0] === 'num' || t[0] === 'str' || t[0] === 'lit') return ['lit', t[1]];
      if (isOp(t, '(')) { const e = expr(0); expect(')'); return e; }
      if (isOp(t, '-')) return ['neg', expr(7)];
      if (isOp(t, '!')) return ['not', expr(7)];
      if (t[0] === 'name') {
        if (isOp(peek(), '(')) {
          take();
          const fn = t[1].toLowerCase();
          if (!FUNCS.has(fn)) throw new FormulaError(`Unknown function "${t[1]}".`);
          const args = [];
          if (!isOp(peek(), ')')) { args.push(expr(0)); while (isOp(peek(), ',')) { take(); args.push(expr(0)); } }
          expect(')');
          return ['call', fn, args];
        }
        return ['var', t[1]];
      }
      throw new FormulaError(t[0] === 'end' ? 'The formula is incomplete.' : `Unexpected "${t[1]}" in the formula.`);
    }
    function expr(minPrec) {
      let left = primary();
      for (;;) {
        const t = peek();
        if (t[0] !== 'op' || !(t[1] in PREC) || PREC[t[1]] < minPrec) return left;
        take();
        left = ['bin', t[1], left, expr(PREC[t[1]] + (t[1] === '^' ? 0 : 1))];
      }
    }
    const tree = expr(0);
    if (i !== toks.length) throw new FormulaError(`Unexpected "${toks[i][1]}" in the formula.`);
    return tree;
  }
  function vars(tree) {
    if (tree[0] === 'var') return new Set([tree[1].split('.')[0]]);
    if (tree[0] === 'neg' || tree[0] === 'not') return vars(tree[1]);
    if (tree[0] === 'bin') return new Set([...vars(tree[2]), ...vars(tree[3])]);
    if (tree[0] === 'call') return new Set(tree[2].flatMap(a => [...vars(a)]));
    return new Set();
  }
  const flat = args => args.flatMap(a => Array.isArray(a) ? a : [a]);
  function evaluate(tree, values, today) {
    today = todayStr(today);
    const ev = n => {
      switch (n[0]) {
        case 'lit': return n[1];
        case 'var': return get(values, n[1]);
        case 'neg': { const x = asNum(ev(n[1])); return x == null ? null : -x; }
        case 'not': return !truthy(ev(n[1]));
        case 'bin': {
          const op = n[1];
          if (op === '&&') return truthy(ev(n[2])) && truthy(ev(n[3]));
          if (op === '||') return truthy(ev(n[2])) || truthy(ev(n[3]));
          const a = ev(n[2]), b = ev(n[3]);
          if (op === '==' || op === '!=') { const same = checkRule({field: '_a', op: 'eq', value: b}, {_a: a}, today); return op === '==' ? same : !same; }
          if (op === '+' && ((typeof a === 'string' && asNum(a) == null) || (typeof b === 'string' && asNum(b) == null))) return text(a) + text(b);
          const x = asNum(a), y = asNum(b);
          if (x == null || y == null) return null;
          switch (op) {
            case '<': return x < y; case '<=': return x <= y; case '>': return x > y; case '>=': return x >= y;
            case '+': return x + y; case '-': return x - y; case '*': return x * y;
            case '/': return y === 0 ? null : x / y;
            case '%': return y === 0 ? null : x % y;
            case '^': { const r = x ** y; return Number.isFinite(r) ? r : null; }
          }
          break;
        }
        case 'call': {
          const fn = n[1], raw = n[2];
          if (fn === 'if') { if (raw.length !== 3) throw new FormulaError('if() needs three parts: if(condition, then, otherwise).'); return truthy(ev(raw[0])) ? ev(raw[1]) : ev(raw[2]); }
          const args = raw.map(ev);
          if (['sum', 'min', 'max', 'avg', 'count'].includes(fn)) {
            if (fn === 'count') return flat(args).filter(filled).length;
            const nums = flat(args).filter(v => v != null && v !== '').map(asNum).filter(x => x != null);
            if (!nums.length) return fn === 'sum' ? 0 : null;
            const s = nums.reduce((p, q) => p + q, 0);
            return {sum: s, min: Math.min(...nums), max: Math.max(...nums), avg: s / nums.length}[fn];
          }
          if (['round', 'floor', 'ceil', 'abs', 'sqrt', 'number'].includes(fn)) {
            const x = args.length ? asNum(args[0]) : null;
            if (x == null) return null;
            if (fn === 'round') { const d = args.length > 1 ? Math.trunc(asNum(args[1]) || 0) : 0; return rnd(x, Math.max(0, Math.min(6, d))); }
            if (fn === 'sqrt') return x < 0 ? null : Math.sqrt(x);
            return {floor: Math.floor(x), ceil: Math.ceil(x), abs: Math.abs(x), number: x}[fn];
          }
          if (fn === 'coalesce') { const f = args.find(filled); return f === undefined ? null : f; }
          if (fn === 'len') { const a = args[0]; return Array.isArray(a) || typeof a === 'string' ? a.length : 0; }
          if (fn === 'today') return today;
          if (fn === 'days_between') { const a = asDate(args[0], today), b = asDate(args[1], today); return !a || !b ? null : b.n - a.n; }
          if (fn === 'age') { const d = asDate(args[0], today), t = asDate(today, today); return !d ? null : t.y - d.y - ((t.m < d.m || (t.m === d.m && t.d < d.d)) ? 1 : 0); }
          if (fn === 'bmi') { const w = asNum(args[0]), h = asNum(args[1]); return !w || !h ? null : w / ((h / 100) ** 2); }
          if (fn === 'concat' || fn === 'text') return args.map(text).join('');
          if (fn === 'upper' || fn === 'lower') { const s = text(args[0] ?? ''); return fn === 'upper' ? s.toUpperCase() : s.toLowerCase(); }
          if (fn === 'col') { const rows = args[0], name = args[1]; return Array.isArray(rows) ? rows.map(r => r ? r[String(name)] : undefined) : []; }
        }
      }
      throw new FormulaError('Cannot evaluate the formula.');
    };
    return ev(tree);
  }
  function runFormula(src, values, decimals = 2, today) {
    let out;
    try { out = evaluate(parse(src), values, today); } catch (e) { return null; }
    if (typeof out === 'boolean') return out;
    if (typeof out === 'number') return Number.isFinite(out) ? rnd(out, decimals) : null;
    return out === undefined ? null : out;
  }
  function tryFormula(src, values, decimals = 2, today) {
    try { const tree = parse(src); return {ok: true, value: runFormula(src, values, decimals, today), vars: [...vars(tree)]}; }
    catch (e) { return {ok: false, error: e.message}; }
  }

  /* ---------------------------------------------------------------- form evaluation (preview / fill-in) */
  const DISPLAY = new Set(['heading', 'paragraph', 'divider', 'patient']);
  function calcOrder(fields) {
    const calcs = fields.filter(f => f.type === 'calc'), keys = new Set(calcs.map(f => f.key)), deps = {};
    for (const f of calcs) { try { deps[f.key] = [...vars(parse(f.formula))].filter(k => keys.has(k)); } catch (e) { deps[f.key] = []; } }
    const order = [], done = new Set();
    while (done.size < calcs.length) {
      let ready = calcs.filter(f => !done.has(f.key) && deps[f.key].every(d => done.has(d)));
      if (!ready.length) ready = calcs.filter(f => !done.has(f.key));
      for (const f of ready) { done.add(f.key); order.push(f); }
    }
    return order;
  }
  const emptyFor = f => ({checkboxes: [], table: [], bodymap: [], vitals: {}, gcs: {}, checkbox: false, number: null, range: null, rating: null}[f.type] ?? '');
  // Returns {values, hidden:Set, required:Set}; values get calculated fields filled in and hidden fields cleared.
  function resolve(schema, raw, today) {
    const fields = schema.fields || [], values = {...raw};
    let hidden = new Set();
    for (let pass = 0; pass < 3; pass++) {
      for (const f of calcOrder(fields)) values[f.key] = hidden.has(f.key) ? null : runFormula(f.formula, values, f.decimals ?? 2, today);
      const now = new Set(fields.filter(f => f.show_if && !check(f.show_if, values, today)).map(f => f.key));
      for (const k of now) { const f = fields.find(x => x.key === k); if (f && !DISPLAY.has(f.type)) values[k] = emptyFor(f); }
      const same = now.size === hidden.size && [...now].every(k => hidden.has(k));
      hidden = now;
      if (same) break;
    }
    const required = new Set(fields.filter(f => !hidden.has(f.key) && !DISPLAY.has(f.type) && f.type !== 'calc' && (f.required || (f.require_if && check(f.require_if, values, today)))).map(f => f.key));
    return {values, hidden, required};
  }
  // Errors the user can fix before submitting (the server repeats every check).
  function validate(schema, values, hidden, required, scope = '', today) {
    today = todayStr(today);
    const errs = {};
    for (const f of schema.fields || []) {
      const k = f.key, t = f.type, v = values[k];
      if (DISPLAY.has(t) || t === 'calc' || hidden.has(k) || (f.filled_by || '') !== scope || f.readonly) continue;
      if (required.has(k) && (!filled(v) || (t === 'checkbox' && v === false))) { errs[k] = t === 'checkbox' ? 'Tick this box to continue.' : t === 'signature' ? 'Sign here.' : 'This is required.'; continue; }
      if (t === 'table' && (v || []).length < (f.min_rows || 0)) { errs[k] = `Add at least ${f.min_rows} row${f.min_rows !== 1 ? 's' : ''}.`; continue; }
      if (!filled(v)) continue;
      if ((t === 'number' || t === 'range') && asNum(v) != null) {
        if (f.min != null && asNum(v) < f.min) errs[k] = `Enter ${text(f.min)} or more.`;
        else if (f.max != null && asNum(v) > f.max) errs[k] = `Enter ${text(f.max)} or less.`;
      }
      if ((t === 'number' || t === 'range') && asNum(v) == null) errs[k] = 'Enter a number.';
      if (t === 'email' && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v)) errs[k] = 'Enter an email address like name@example.com.';
      if (t === 'phone' && !/^\+?[\d\s()-]{7,20}$/.test(v)) errs[k] = 'Enter a phone number.';
      if (t === 'date') {
        const d = asDate(v, today), lo = f.min ? asDate(f.min, today) : null, hi = f.max ? asDate(f.max, today) : null;
        if (lo && d && d.n < lo.n) errs[k] = f.min === 'today' ? 'Choose today or later.' : `Choose ${f.min} or later.`;
        else if (hi && d && d.n > hi.n) errs[k] = f.max === 'today' ? 'Choose today or earlier.' : `Choose ${f.max} or earlier.`;
      }
      if ((t === 'text' || t === 'textarea') && f.pattern && root.MF_PATTERNS && root.MF_PATTERNS[f.pattern]) {
        const [rx, msg] = root.MF_PATTERNS[f.pattern];
        if (!new RegExp(`^(?:${rx})$`).test(v)) errs[k] = msg;
      }
    }
    return errs;
  }

  const api = {rnd, asNum, filled, truthy, text, check, checkRule, parse, vars, evaluate, runFormula, tryFormula, resolve, validate, calcOrder, FormulaError, DISPLAY};
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.MFForm = api;
})(typeof window !== 'undefined' ? window : globalThis);
