"""Forms engine: what a form may contain, when fields show, what they calculate and how answers are checked.

Shared with the browser: static/hospital/js/formkit.js implements the same conditions and formula language with
the same rounding, so the form behaves identically while it is filled in and when the server re-checks it on submit.
The server never trusts calculated or hidden values sent by the browser; it recomputes them here.

Schema (stored in FormDefinition.schema; the old {"fields": [...]} format with six types is still valid):
    {"version": 2, "pages": [{"id": "p1", "title": "Details"}],
     "settings": {"submit_label": "Submit"},
     "fields": [{"key": "pain", "label": "Pain score", "type": "rating", "page": "p1", "width": "half",
                 "required": true, "show_if": {"all": [{"field": "in_pain", "op": "truthy"}]},
                 "require_if": {...}, "filled_by": "", "help": "...", ...}]}
"""
import math
import re
from datetime import date, datetime, timedelta

from .injury import rnd

# ------------------------------------------------------------------ field types
INPUT_TYPES = {
    'text': 'Short text', 'textarea': 'Long text', 'number': 'Number', 'date': 'Date', 'time': 'Time',
    'email': 'Email', 'phone': 'Phone', 'select': 'Dropdown', 'radio': 'Choose one', 'checkboxes': 'Choose several',
    'checkbox': 'Tick box', 'yesno': 'Yes / No', 'rating': 'Score 0–10', 'range': 'Slider', 'calc': 'Calculated',
    'table': 'Table (repeating rows)', 'signature': 'Signature', 'bodymap': 'Body map', 'vitals': 'Vital signs + NEWS2',
    'gcs': 'Glasgow Coma Scale',
}
DISPLAY_TYPES = {'heading': 'Section heading', 'paragraph': 'Text / instructions', 'divider': 'Divider', 'patient': 'Patient details'}
FIELD_TYPES = {**INPUT_TYPES, **DISPLAY_TYPES}
CHOICE_TYPES = {'select', 'radio', 'checkboxes'}
TABLE_COLUMN_TYPES = {'text', 'number', 'date', 'select', 'checkbox'}
PATTERNS = {'digits': (r'\d+', 'Use digits only.'), 'letters': (r"[A-Za-zÀ-ÿ' .-]+", 'Use letters only.'),
            'gm_phone': (r'(\+220)?\s?\d{7}', 'Enter a 7-digit Gambian number, optionally with +220.'),
            'mrn': (r'MF-[A-F0-9]{10}', 'Patient numbers look like MF-1A2B3C4D5E.')}
PREFILL = {'patient.full_name': 'Patient name', 'patient.mrn': 'Patient number', 'patient.age': 'Patient age',
           'patient.sex': 'Patient sex', 'patient.dob': 'Date of birth', 'patient.phone': 'Patient phone',
           'patient.allergies': 'Allergies', 'patient.blood_group': 'Blood group', 'today': "Today's date",
           'user.name': 'Person filling in'}
WIDTHS = ('full', 'half', 'third')
MAX_FIELDS, MAX_PAGES, MAX_OPTIONS, MAX_ROWS, MAX_TEXT = 150, 12, 100, 60, 4000
SIG_MAX = 300_000
NUM_RE = re.compile(r'^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$')
KEY_RE = re.compile(r'^[a-z][a-z0-9_]{0,39}$')

# ------------------------------------------------------------------ conditions
OPS = {
    'eq': 'is', 'neq': 'is not', 'contains': 'contains', 'not_contains': 'does not contain', 'starts_with': 'starts with',
    'gt': 'is more than', 'gte': 'is at least', 'lt': 'is less than', 'lte': 'is at most', 'between': 'is between',
    'not_between': 'is not between', 'empty': 'is empty', 'not_empty': 'is filled in', 'truthy': 'is yes / ticked',
    'falsy': 'is no / not ticked', 'in': 'is one of', 'not_in': 'is not one of', 'includes_any': 'includes any of',
    'includes_all': 'includes all of', 'before': 'is before', 'after': 'is after', 'in_past': 'is in the past',
    'in_future': 'is in the future', 'within_days': 'is within the next … days',
}
UNARY = {'empty', 'not_empty', 'truthy', 'falsy', 'in_past', 'in_future'}
LISTY = {'in', 'not_in', 'includes_any', 'includes_all'}
RANGE = {'between', 'not_between'}


def filled(v):
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ''
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def _as_num(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if v is None or not NUM_RE.match(str(v).strip()):
        return None
    x = float(str(v).strip())
    return x if math.isfinite(x) else None


def _as_date(v, today):
    if isinstance(v, str) and v.strip().lower() == 'today':
        return today
    try:
        return datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _truthy(v):
    if isinstance(v, str):
        return v.strip().lower() in ('yes', 'true', '1', 'on', 'y')
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return bool(v)


def _list(v):
    if isinstance(v, list):
        return [_text(x).strip().lower() for x in v]
    return [x.strip().lower() for x in _text(v).split(',') if x.strip()]


def _get(values, path):
    """Field value; `vitals.heart_rate` reaches inside composite answers."""
    head, _, rest = str(path).partition('.')
    v = values.get(head)
    if rest and isinstance(v, dict):
        v = v.get(rest)
    return v


def check_rule(rule, values, today=None):
    today = today or date.today()
    op = rule.get('op')
    left = _get(values, rule.get('field', ''))
    right = _get(values, rule['ref']) if rule.get('ref') else rule.get('value')
    if op == 'empty':
        return not filled(left)
    if op == 'not_empty':
        return filled(left)
    if op == 'truthy':
        return _truthy(left)
    if op == 'falsy':
        return not _truthy(left)
    if op in ('in_past', 'in_future'):
        d = _as_date(left, today)
        return d is not None and (d < today if op == 'in_past' else d > today)
    if op == 'within_days':
        d, n = _as_date(left, today), _as_num(right)
        return d is not None and n is not None and today <= d <= today + timedelta(days=n)
    if op in ('before', 'after'):
        a, b = _as_date(left, today), _as_date(right, today)
        return a is not None and b is not None and (a < b if op == 'before' else a > b)
    if op in LISTY:
        options = _list(right)
        have = _list(left) if isinstance(left, list) else [_text(left).strip().lower()]
        if op == 'in':
            return have[0] in options if have else False
        if op == 'not_in':
            return not have or have[0] not in options
        if op == 'includes_any':
            return any(x in options for x in have)
        return all(x in have for x in options)
    if op in ('gt', 'gte', 'lt', 'lte') or op in RANGE:
        a, b = _as_num(left), _as_num(right)
        if op in RANGE:
            c = _as_num(rule.get('value2'))
            inside = a is not None and b is not None and c is not None and min(b, c) <= a <= max(b, c)
            return inside if op == 'between' else (a is not None and not inside)
        if a is None or b is None:
            return False
        return {'gt': a > b, 'gte': a >= b, 'lt': a < b, 'lte': a <= b}[op]
    ls = _text(left).strip().lower()
    rs = _text(right).strip().lower()
    if op in ('eq', 'neq'):
        a, b = _as_num(left), _as_num(right)
        same = (a == b) if (a is not None and b is not None and not isinstance(left, bool)) else (ls == rs or (isinstance(left, bool) and _truthy(left) == _truthy(right)))
        return same if op == 'eq' else not same
    if op == 'contains':
        return rs in ls
    if op == 'not_contains':
        return rs not in ls
    if op == 'starts_with':
        return ls.startswith(rs)
    return False


def check(tree, values, today=None):
    """Evaluate a condition tree. An empty tree is true."""
    if not tree:
        return True
    if 'op' in tree:
        return check_rule(tree, values, today)
    items = tree.get('all') if 'all' in tree else tree.get('any') or []
    results = [check(x, values, today) for x in items]
    out = all(results) if 'all' in tree else any(results) if results else True
    return (not out) if tree.get('not') else out


def clean_tree(tree, keys, depth=0, errors=None):
    """Keep only valid rules that point at existing fields. Returns the cleaned tree (or None if empty)."""
    errors = errors if errors is not None else []
    if not isinstance(tree, dict) or depth > 4:
        return None
    if 'op' in tree:
        op, field = tree.get('op'), str(tree.get('field', ''))
        if op not in OPS:
            errors.append(f'Unknown condition "{op}".'); return None
        if field.split('.')[0] not in keys:
            errors.append(f'A condition refers to a field that does not exist ({field or "none"}).'); return None
        out = {'field': field[:60], 'op': op}
        if op not in UNARY:
            if tree.get('ref'):
                if str(tree['ref']).split('.')[0] not in keys:
                    errors.append(f'A condition compares with a field that does not exist ({tree["ref"]}).'); return None
                out['ref'] = str(tree['ref'])[:60]
            else:
                out['value'] = str(tree.get('value', ''))[:300]
            if op in RANGE:
                out['value2'] = str(tree.get('value2', ''))[:300]
        return out
    mode = 'any' if 'any' in tree else 'all'
    items = [x for x in (clean_tree(t, keys, depth + 1, errors) for t in (tree.get(mode) or [])[:40]) if x]
    if not items:
        return None
    out = {mode: items}
    if tree.get('not'):
        out['not'] = True
    return out


def tree_fields(tree):
    if not tree:
        return set()
    if 'op' in tree:
        return {tree['field'].split('.')[0]} | ({tree['ref'].split('.')[0]} if tree.get('ref') else set())
    return set().union(*[tree_fields(x) for x in tree.get('all') or tree.get('any') or []])


# ------------------------------------------------------------------ formula language
class FormulaError(ValueError):
    pass


TOKEN_RE = re.compile(r"\s*(?:(\d+\.?\d*|\.\d+)|('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")|([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)|(==|!=|<=|>=|&&|\|\||[-+*/%^(),<>!]))")
FUNCS = {'sum', 'min', 'max', 'avg', 'round', 'floor', 'ceil', 'abs', 'sqrt', 'if', 'coalesce', 'len', 'count', 'today',
         'days_between', 'age', 'bmi', 'concat', 'upper', 'lower', 'col', 'number', 'text'}
KEYWORDS = {'and': '&&', 'or': '||', 'not': '!', 'true': True, 'false': False, 'null': None}


def tokenize(src):
    src = str(src or '')
    if len(src) > 500:
        raise FormulaError('Formula is too long (500 characters at most).')
    pos, out = 0, []
    while pos < len(src):
        if src[pos:].strip() == '':
            break
        m = TOKEN_RE.match(src, pos)
        if not m or m.end() == pos:
            raise FormulaError(f'Cannot read the formula near "{src[pos:pos + 10].strip()}".')
        num, s, name, op = m.groups()
        if num is not None:
            out.append(('num', float(num)))
        elif s is not None:
            out.append(('str', re.sub(r'\\(.)', r'\1', s[1:-1])))
        elif name is not None:
            low = name.lower()
            if low in ('and', 'or', 'not'):
                out.append(('op', KEYWORDS[low]))
            elif low in ('true', 'false', 'null'):
                out.append(('lit', KEYWORDS[low]))
            else:
                out.append(('name', name))
        else:
            out.append(('op', op))
        pos = m.end()
    return out


PREC = {'||': 1, '&&': 2, '==': 3, '!=': 3, '<': 4, '<=': 4, '>': 4, '>=': 4, '+': 5, '-': 5, '*': 6, '/': 6, '%': 6, '^': 8}


def parse(src):
    """Formula text → tree of tuples. Raises FormulaError with a readable message."""
    toks, i = tokenize(src), [0]
    if not toks:
        raise FormulaError('The formula is empty.')

    def peek():
        return toks[i[0]] if i[0] < len(toks) else ('end', None)

    def take():
        t = peek(); i[0] += 1; return t

    def expect(v):
        t = take()
        if t != ('op', v):
            raise FormulaError(f'Expected "{v}" in the formula.')

    def primary():
        t = take()
        if t[0] in ('num', 'str', 'lit'):
            return ('lit', t[1])
        if t == ('op', '('):
            e = expr(0); expect(')'); return e
        if t == ('op', '-'):
            return ('neg', expr(7))
        if t == ('op', '!'):
            return ('not', expr(7))
        if t[0] == 'name':
            if peek() == ('op', '('):
                take()
                fn = t[1].lower()
                if fn not in FUNCS:
                    raise FormulaError(f'Unknown function "{t[1]}".')
                args = []
                if peek() != ('op', ')'):
                    args.append(expr(0))
                    while peek() == ('op', ','):
                        take(); args.append(expr(0))
                expect(')')
                return ('call', fn, args)
            return ('var', t[1])
        raise FormulaError('The formula is incomplete.' if t[0] == 'end' else f'Unexpected "{t[1]}" in the formula.')

    def expr(min_prec):
        left = primary()
        while True:
            t = peek()
            if t[0] != 'op' or t[1] not in PREC or PREC[t[1]] < min_prec:
                return left
            take()
            nxt = PREC[t[1]] + (0 if t[1] == '^' else 1)
            left = ('bin', t[1], left, expr(nxt))

    tree = expr(0)
    if i[0] != len(toks):
        raise FormulaError(f'Unexpected "{toks[i[0]][1]}" in the formula.')
    return tree


def formula_vars(tree):
    if tree[0] == 'var':
        return {tree[1].split('.')[0]}
    if tree[0] in ('neg', 'not'):
        return formula_vars(tree[1])
    if tree[0] == 'bin':
        return formula_vars(tree[2]) | formula_vars(tree[3])
    if tree[0] == 'call':
        out = set()
        for a in tree[2]:
            out |= formula_vars(a)
        return out
    return set()


def _flat(args):
    out = []
    for a in args:
        out.extend(a if isinstance(a, list) else [a])
    return out


def evaluate(tree, values, today=None):
    """Evaluate a parsed formula. Missing numbers give null rather than errors; division by zero gives null."""
    today = today or date.today()

    def ev(n):
        k = n[0]
        if k == 'lit':
            return n[1]
        if k == 'var':
            return _get(values, n[1])
        if k == 'neg':
            x = _as_num(ev(n[1])); return None if x is None else -x
        if k == 'not':
            return not _truthy(ev(n[1]))
        if k == 'bin':
            op = n[1]
            if op == '&&':
                return _truthy(ev(n[2])) and _truthy(ev(n[3]))
            if op == '||':
                return _truthy(ev(n[2])) or _truthy(ev(n[3]))
            a, b = ev(n[2]), ev(n[3])
            if op in ('==', '!='):
                same = check_rule({'field': '_a', 'op': 'eq', 'value': b}, {'_a': a})
                return same if op == '==' else not same
            if op == '+' and (isinstance(a, str) and _as_num(a) is None or isinstance(b, str) and _as_num(b) is None):
                return f'{_text(a)}{_text(b)}'
            x, y = _as_num(a), _as_num(b)
            if x is None or y is None:
                return None
            if op in ('<', '<=', '>', '>='):
                return {'<': x < y, '<=': x <= y, '>': x > y, '>=': x >= y}[op]
            if op == '+':
                return x + y
            if op == '-':
                return x - y
            if op == '*':
                return x * y
            if op == '/':
                return None if y == 0 else x / y
            if op == '%':
                return None if y == 0 else math.fmod(x, y)
            if op == '^':
                try:
                    r = x ** y
                    return r if isinstance(r, float) and math.isfinite(r) or isinstance(r, int) else None
                except (OverflowError, ZeroDivisionError, ValueError):
                    return None
        if k == 'call':
            fn, raw = n[1], n[2]
            if fn == 'if':
                if len(raw) != 3:
                    raise FormulaError('if() needs three parts: if(condition, then, otherwise).')
                return ev(raw[1]) if _truthy(ev(raw[0])) else ev(raw[2])
            args = [ev(a) for a in raw]
            if fn in ('sum', 'min', 'max', 'avg', 'count'):
                nums = [x for x in (_as_num(v) for v in _flat(args) if v is not None and v != '') if x is not None]
                if fn == 'count':
                    return float(len([v for v in _flat(args) if filled(v)]))
                if not nums:
                    return 0.0 if fn == 'sum' else None
                return {'sum': sum(nums), 'min': min(nums), 'max': max(nums), 'avg': sum(nums) / len(nums)}[fn]
            if fn in ('round', 'floor', 'ceil', 'abs', 'sqrt', 'number'):
                x = _as_num(args[0]) if args else None
                if x is None:
                    return None
                if fn == 'round':
                    d = int(_as_num(args[1]) or 0) if len(args) > 1 else 0
                    return rnd(x, max(0, min(6, d)))
                if fn == 'sqrt':
                    return None if x < 0 else math.sqrt(x)
                return {'floor': math.floor(x), 'ceil': math.ceil(x), 'abs': abs(x), 'number': x}[fn] * 1.0
            if fn == 'coalesce':
                return next((a for a in args if filled(a)), None)
            if fn == 'len':
                a = args[0] if args else None
                return float(len(a)) if isinstance(a, (list, str)) else 0.0
            if fn == 'today':
                return today.isoformat()
            if fn == 'days_between':
                a, b = (_as_date(x, today) for x in (args + [None, None])[:2])
                return None if a is None or b is None else float((b - a).days)
            if fn == 'age':
                d = _as_date(args[0] if args else None, today)
                return None if d is None else float(today.year - d.year - ((today.month, today.day) < (d.month, d.day)))
            if fn == 'bmi':
                w, h = (_as_num(x) for x in (args + [None, None])[:2])
                return None if not w or not h else w / ((h / 100) ** 2)
            if fn in ('concat', 'text'):
                return ''.join(_text(a) for a in args)
            if fn in ('upper', 'lower'):
                s = _text(args[0] if args else '')
                return s.upper() if fn == 'upper' else s.lower()
            if fn == 'col':
                rows, name = (args + [None, None])[:2]
                return [r.get(str(name)) for r in rows] if isinstance(rows, list) else []
        raise FormulaError('Cannot evaluate the formula.')
    return ev(tree)


def _text(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'yes' if v else 'no'
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    if isinstance(v, list):
        return ', '.join(_text(x) for x in v)
    return str(v)


def run_formula(src, values, decimals=2, today=None):
    try:
        out = evaluate(parse(src), values, today)
    except (FormulaError, RecursionError):
        return None
    if isinstance(out, bool):
        return out
    if isinstance(out, (int, float)):
        return rnd(float(out), decimals) if math.isfinite(out) else None
    return out


# ------------------------------------------------------------------ schema cleaning
def _s(v, n):
    return str(v if v is not None else '').strip()[:n]


def clean_schema(raw):
    """Return (schema, errors). Accepts the legacy {"fields": [...]} format."""
    errors = []
    raw = raw if isinstance(raw, dict) else {}
    pages = []
    for p in (raw.get('pages') or [])[:MAX_PAGES]:
        if isinstance(p, dict) and re.match(r'^[A-Za-z0-9_-]{1,20}$', str(p.get('id', ''))):
            pages.append({'id': p['id'], 'title': _s(p.get('title'), 80) or 'Page'})
    if not pages:
        pages = [{'id': 'p1', 'title': _s((raw.get('settings') or {}).get('title'), 80) or 'Form'}]
    page_ids = {p['id'] for p in pages}
    fields_in = raw.get('fields')
    if not isinstance(fields_in, list) or not fields_in:
        return None, ['Add at least one field.']
    if len(fields_in) > MAX_FIELDS:
        return None, [f'A form can have at most {MAX_FIELDS} fields.']
    keys, out = set(), []
    for n, f in enumerate(fields_in, 1):
        if not isinstance(f, dict) or f.get('type') not in FIELD_TYPES:
            errors.append(f'Field {n} has an unknown type.'); continue
        t = f['type']
        label = _s(f.get('label') or f.get('text'), 200)
        if t in INPUT_TYPES:
            key = str(f.get('key', ''))
            if not (key.isidentifier() and KEY_RE.match(key)) or key in keys:
                errors.append(f'Field “{label or n}” has an invalid or duplicate key (use lowercase letters, digits and _).'); continue
            keys.add(key)
        else:
            key = str(f.get('key') or f'_{t}{n}')[:40]
        c = {'key': key, 'type': t, 'label': label, 'page': f.get('page') if f.get('page') in page_ids else pages[0]['id'],
             'width': f.get('width') if f.get('width') in WIDTHS else 'full'}
        if t == 'paragraph':
            c['text'] = _s(f.get('text') or f.get('label'), 2000)
        if t in INPUT_TYPES:
            c['required'] = bool(f.get('required'))
            for k, n_ in (('help', 300), ('placeholder', 120), ('unit', 20)):
                if f.get(k):
                    c[k] = _s(f[k], n_)
            if f.get('filled_by'):
                c['filled_by'] = _s(f['filled_by'], 40)
            if f.get('prefill') in PREFILL:
                c['prefill'] = f['prefill']
            if f.get('readonly'):
                c['readonly'] = True
        if t in CHOICE_TYPES:
            opts = [_s(o, 120) for o in (f.get('options') or []) if _s(o, 120)][:MAX_OPTIONS]
            if not opts or len(set(opts)) != len(opts):
                errors.append(f'“{label}” needs at least one option, without repeats.'); continue
            c['options'] = opts
        if t in ('number', 'range', 'rating'):
            for k in ('min', 'max', 'step'):
                if _as_num(f.get(k)) is not None:
                    c[k] = _as_num(f[k])
            if t == 'range':
                c.setdefault('min', 0.0); c.setdefault('max', 100.0)
            if 'min' in c and 'max' in c and c['min'] > c['max']:
                errors.append(f'“{label}”: the minimum is above the maximum.')
        if t == 'date':
            for k in ('min', 'max'):
                v = _s(f.get(k), 10)
                if v == 'today' or _as_date(v, date.today()):
                    c[k] = v
        if t in ('text', 'textarea'):
            if f.get('pattern') in PATTERNS:
                c['pattern'] = f['pattern']
            ml = _as_num(f.get('maxlength'))
            if ml:
                c['maxlength'] = int(max(1, min(MAX_TEXT, ml)))
        if t == 'calc':
            c['formula'] = _s(f.get('formula'), 500)
            c['decimals'] = int(max(0, min(6, _as_num(f.get('decimals')) if _as_num(f.get('decimals')) is not None else 2)))
            try:
                c['_vars'] = sorted(formula_vars(parse(c['formula'])))
            except FormulaError as exc:
                errors.append(f'“{label}”: {exc}'); continue
        if t == 'table':
            cols = []
            for col in (f.get('columns') or [])[:12]:
                if isinstance(col, dict) and KEY_RE.match(str(col.get('key', ''))) and col.get('type', 'text') in TABLE_COLUMN_TYPES:
                    cc = {'key': col['key'], 'label': _s(col.get('label') or col['key'], 80), 'type': col.get('type', 'text')}
                    if cc['type'] == 'select':
                        cc['options'] = [_s(o, 80) for o in col.get('options') or [] if _s(o, 80)][:40] or ['—']
                    cols.append(cc)
            if not cols or len({x['key'] for x in cols}) != len(cols):
                errors.append(f'Table “{label}” needs columns with different keys.'); continue
            c['columns'] = cols
            c['min_rows'] = int(max(0, min(MAX_ROWS, _as_num(f.get('min_rows')) or 0)))
            c['max_rows'] = int(max(1, min(MAX_ROWS, _as_num(f.get('max_rows')) or 20)))
        if t == 'bodymap':
            c['multiple'] = f.get('multiple', True) is not False
        c['_show'], c['_req'] = f.get('show_if'), f.get('require_if')
        out.append(c)
    # second pass: conditions and formulas may only refer to fields that exist; calculated fields may not loop
    for c in out:
        for k, raw_tree in (('show_if', c.pop('_show')), ('require_if', c.pop('_req'))):
            if raw_tree:
                errs = []
                t = clean_tree(raw_tree, keys, errors=errs)
                errors += [f'“{c["label"]}”: {e}' for e in errs]
                if t:
                    c[k] = t
        if c['type'] == 'calc':
            missing = [v for v in c.pop('_vars') if v not in keys]
            if missing:
                errors.append(f'“{c["label"]}” uses fields that do not exist: {", ".join(missing)}.')
    calcs = {c['key']: set(formula_vars(parse(c['formula']))) & keys for c in out if c['type'] == 'calc' and c.get('formula')}
    seen, stack = set(), set()

    def visit(k):
        if k in stack:
            errors.append(f'Calculated field “{k}” depends on itself through other calculations.'); return
        if k in seen or k not in calcs:
            return
        stack.add(k)
        for d in calcs[k]:
            visit(d)
        stack.discard(k); seen.add(k)
    for k in calcs:
        visit(k)
    settings = raw.get('settings') if isinstance(raw.get('settings'), dict) else {}
    schema = {'version': 2, 'pages': pages, 'fields': out,
              'settings': {'submit_label': _s(settings.get('submit_label'), 40) or 'Submit',
                           'intro': _s(settings.get('intro'), 1000)}}
    return (None if errors else schema), errors


def calc_order(fields):
    """Calculated fields in dependency order."""
    calcs = {f['key']: f for f in fields if f['type'] == 'calc'}
    deps = {}
    for k, f in calcs.items():
        try:
            deps[k] = formula_vars(parse(f['formula'])) & calcs.keys()
        except FormulaError:
            deps[k] = set()
    order, done = [], set()
    while len(done) < len(calcs):
        ready = [k for k in calcs if k not in done and deps[k] <= done]
        if not ready:                       # a loop slipped through: evaluate the rest in schema order
            ready = [k for k in calcs if k not in done]
        for k in ready:
            done.add(k); order.append(calcs[k])
    return order


# ------------------------------------------------------------------ answers
def _coerce(f, v, errors):
    t, key = f['type'], f['key']
    if t in ('text', 'textarea', 'email', 'phone'):
        s = str(v if v is not None else '').strip()
        lim = f.get('maxlength', MAX_TEXT if t == 'textarea' else 300)
        if len(s) > lim:
            errors[key] = f'Use at most {lim} characters.'
        return s[:lim]
    if t in ('number', 'range', 'rating'):
        if v in (None, ''):
            return None
        x = _as_num(v)
        if x is None:
            errors[key] = 'Enter a number.'
        if t == 'rating' and x is not None and not (0 <= x <= 10):
            errors[key] = 'Choose a score from 0 to 10.'
        return x
    if t == 'date':
        if not v:
            return ''
        d = _as_date(v, date.today())
        if not d:
            errors[key] = 'Enter a date.'
            return ''
        return d.isoformat()
    if t == 'time':
        s = str(v or '')[:5]
        if s and not re.match(r'^([01]\d|2[0-3]):[0-5]\d$', s):
            errors[key] = 'Enter a time like 14:30.'
        return s
    if t in ('select', 'radio'):
        s = str(v or '')
        if s and s not in f['options']:
            errors[key] = 'Choose one of the options.'
            return ''
        return s
    if t == 'checkboxes':
        items = v if isinstance(v, list) else ([v] if v else [])
        return [o for o in f['options'] if o in [str(x) for x in items]]
    if t == 'checkbox':
        return _truthy(v)
    if t == 'yesno':
        s = str(v or '').lower()
        return s if s in ('yes', 'no') else ''
    if t == 'signature':
        s = str(v or '')
        if s and (not s.startswith('data:image/png;base64,') or len(s) > SIG_MAX):
            errors[key] = 'The signature could not be read. Sign again.'
            return ''
        return s
    if t == 'bodymap':
        items = v if isinstance(v, list) else []
        from .injury import LUND_BROWDER
        ok = [str(x)[:40] for x in items if str(x).split('|')[0] in LUND_BROWDER][:40]
        return ok if f.get('multiple', True) else ok[:1]
    if t == 'table':
        rows = []
        for r in (v if isinstance(v, list) else [])[:f.get('max_rows', 20)]:
            if not isinstance(r, dict):
                continue
            row = {}
            for col in f['columns']:
                cv = r.get(col['key'])
                if col['type'] == 'number':
                    cv = _as_num(cv)
                elif col['type'] == 'checkbox':
                    cv = _truthy(cv)
                elif col['type'] == 'date':
                    d = _as_date(cv, date.today()) if cv else None
                    cv = d.isoformat() if d else ''
                elif col['type'] == 'select':
                    cv = str(cv or '') if str(cv or '') in col['options'] else ''
                else:
                    cv = str(cv or '')[:300]
                row[col['key']] = cv
            if any(filled(x) and x is not False for x in row.values()):
                rows.append(row)
        return rows
    if t == 'vitals':
        from .bedside import clean_observation, news2
        try:
            o = clean_observation(v if isinstance(v, dict) else {})
        except ValueError as exc:
            if 'at least one' in str(exc):
                return {}
            errors[key] = str(exc)
            return {}
        score = news2(o)
        o['news2'] = score['total'] if score else None
        return o
    if t == 'gcs':
        d = v if isinstance(v, dict) else {}
        try:
            e, vb, m = int(d.get('eye')), int(d.get('verbal')), int(d.get('motor'))
        except (TypeError, ValueError):
            return {}
        if not (1 <= e <= 4 and 1 <= vb <= 5 and 1 <= m <= 6):
            errors[key] = 'Choose a score for eyes, speech and movement.'
            return {}
        return {'eye': e, 'verbal': vb, 'motor': m, 'total': e + vb + m}
    return v


def evaluate_form(schema, raw, *, scope=None, today=None, previous=None):
    """Check answers. Returns (values, errors, hidden_keys).

    scope: None = the submitter (fields without `filled_by`); a step id = only that step's fields may change;
    previous: answers already stored (kept for fields outside the scope).
    """
    today = today or date.today()
    fields = schema.get('fields', [])
    previous = previous or {}
    errors, values = {}, {}
    in_scope = lambda f: (f.get('filled_by', '') or None) == scope
    for f in fields:
        if f['type'] in DISPLAY_TYPES:
            continue
        if f['type'] == 'calc':
            continue
        if f.get('readonly') and f['key'] in previous:
            values[f['key']] = previous[f['key']]           # read-only answers never change after the first save
        elif in_scope(f):
            values[f['key']] = _coerce(f, raw.get(f['key']), errors)
        else:
            values[f['key']] = previous.get(f['key'], _coerce(f, None, {}))
    hidden = set()
    for _ in range(3):                       # hiding a field can change calculations and other conditions
        for f in calc_order(fields):
            values[f['key']] = None if f['key'] in hidden else run_formula(f['formula'], values, f.get('decimals', 2), today)
        now_hidden = {f['key'] for f in fields if f.get('show_if') and not check(f['show_if'], values, today)}
        for k in now_hidden:
            f = next(x for x in fields if x['key'] == k)
            if f['type'] in INPUT_TYPES:
                values[k] = _coerce(f, None, {})
        if now_hidden == hidden:
            break
        hidden = now_hidden
    for f in fields:
        k, t = f['key'], f['type']
        if t not in INPUT_TYPES or k in hidden or k in errors or not in_scope(f) or t == 'calc':
            continue
        v = values.get(k)
        need = f.get('required') or (f.get('require_if') and check(f['require_if'], values, today))
        if need and (not filled(v) or (t == 'checkbox' and v is False)):
            errors[k] = 'Tick this box to continue.' if t == 'checkbox' else 'Sign here.' if t == 'signature' else 'This is required.'
            continue
        if t == 'table' and len(v or []) < f.get('min_rows', 0):
            errors[k] = f'Add at least {f["min_rows"]} row{"s" if f["min_rows"] != 1 else ""}.'
            continue
        if not filled(v):
            continue
        if t in ('number', 'range') and v is not None:
            if 'min' in f and v < f['min']:
                errors[k] = f'Enter {_text(f["min"])} or more.'
            elif 'max' in f and v > f['max']:
                errors[k] = f'Enter {_text(f["max"])} or less.'
        if t == 'date':
            d = _as_date(v, today)
            lo, hi = _as_date(f.get('min'), today) if f.get('min') else None, _as_date(f.get('max'), today) if f.get('max') else None
            if lo and d < lo:
                errors[k] = f'Choose {"today" if f["min"] == "today" else lo.strftime("%d %b %Y")} or later.'
            elif hi and d > hi:
                errors[k] = f'Choose {"today" if f["max"] == "today" else hi.strftime("%d %b %Y")} or earlier.'
        if t == 'email' and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', v):
            errors[k] = 'Enter an email address like name@example.com.'
        if t == 'phone' and not re.match(r'^\+?[\d\s()-]{7,20}$', v):
            errors[k] = 'Enter a phone number.'
        if t in ('text', 'textarea') and f.get('pattern'):
            rx, msg = PATTERNS[f['pattern']]
            if not re.fullmatch(rx, v):
                errors[k] = msg
    return values, errors, hidden


def prefill_values(schema, patient=None, user=None, today=None):
    today = today or date.today()
    src = {'today': today.isoformat()}
    if patient is not None:
        src.update({'patient.full_name': patient.full_name, 'patient.mrn': patient.mrn, 'patient.age': patient.age,
                    'patient.sex': patient.get_sex_display(), 'patient.dob': patient.dob.isoformat() if patient.dob else '',
                    'patient.phone': patient.phone, 'patient.blood_group': patient.blood_group,
                    'patient.allergies': ', '.join(a.substance for a in patient.allergies.filter(status='active')) or 'None recorded'})
    if user is not None:
        src['user.name'] = user.get_full_name() or user.username
    return {f['key']: src.get(f['prefill']) for f in schema.get('fields', []) if f.get('prefill') in src}


def display_value(f, v):
    """Answer as readable text (summaries, PDFs)."""
    t = f['type']
    if v is None or v == '' or v == [] or v == {}:
        return '—'
    if t == 'checkbox':
        return 'Yes' if v else 'No'
    if t == 'yesno':
        return v.capitalize()
    if t == 'checkboxes':
        return ', '.join(v)
    if t == 'signature':
        return '[signed]'
    if t == 'bodymap':
        from .injury import REGION_LABELS
        return ', '.join(f"{(x.split('|')[1] + ' ') if len(x.split('|')) > 1 and x.split('|')[1] else ''}{REGION_LABELS.get(x.split('|')[0], x)}".strip() for x in v)
    if t == 'vitals':
        bits = [f"HR {v['heart_rate']}" if v.get('heart_rate') else '', f"BP {v['systolic']}/{v.get('diastolic') or '–'}" if v.get('systolic') else '',
                f"RR {v['resp_rate']}" if v.get('resp_rate') else '', f"SpO₂ {v['spo2']}%" if v.get('spo2') else '',
                f"T {v['temperature_c']}°C" if v.get('temperature_c') else '', f"NEWS2 {v['news2']}" if v.get('news2') is not None else '']
        return ' · '.join(b for b in bits if b)
    if t == 'gcs':
        return f"GCS {v['total']} (E{v['eye']} V{v['verbal']} M{v['motor']})"
    if t == 'table':
        return f'{len(v)} row{"s" if len(v) != 1 else ""}'
    if t in ('number', 'range', 'rating', 'calc') and isinstance(v, float):
        s = _text(v)
        return f"{s} {f['unit']}" if f.get('unit') else s
    return _text(v)


def catalogue():
    return {'types': FIELD_TYPES, 'input_types': sorted(INPUT_TYPES), 'display_types': sorted(DISPLAY_TYPES), 'ops': OPS,
            'unary': sorted(UNARY), 'listy': sorted(LISTY), 'range': sorted(RANGE), 'patterns': {k: v[1] for k, v in PATTERNS.items()},
            'prefill': PREFILL, 'funcs': sorted(FUNCS), 'table_column_types': sorted(TABLE_COLUMN_TYPES)}
