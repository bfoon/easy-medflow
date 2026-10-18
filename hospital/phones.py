"""Phone numbers: one way to store them for searching and one way to match what people type.

Phones are entered every way imaginable: "+220 341 5919", "3415919", "341-5919", "00220 3415919", "(220) 341 5919".
Each patient keeps digits-only copies for search:

* ``phone_digits``  all digits as typed (kept for messaging: SMS and WhatsApp need the country code);
* ``phone_local``   the subscriber number without the country code: what staff and patients actually say;
* ``phone_rev``     ``phone_local`` reversed, so "ends with 778" is a fast indexed "starts with 877";
* ``contact_digits`` / ``contact_local``: every number in the emergency contact, the local one padded with spaces
  (" 3467656778 9901234 ") so "starts with" and "ends with" work on each number in the list.

The search language (also explained next to the search boxes)::

    34 · 346          the number starts with these digits (two or three digits)
    *778 · …778       the number ends with these digits
    346*778           starts with 346 and ends with 778
    *765*             contains 765 anywhere
    6778              four or more digits: starts with, ends with or contains, in that order of relevance
    +220 346 7656 778 a whole number, with or without the country code

When a long number finds nothing, ``near_matches`` offers numbers one keystroke away (one digit wrong, one digit
missing or extra, two neighbouring digits swapped), the usual mistakes when a number is read out at the desk.
"""
import re
from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import Q

WILDCARDS = re.compile(r'\*|…|\.\.\.?')
PHONE_QUERY = re.compile(r'^[\d\s+().\-/*…]+$')
MIN_DIGITS = 2                       # "34" is enough to start a phone search; the number must start with it
MIN_ANYWHERE = 4                     # without a wildcard, four digits ("5919", the last four) also search the end and middle
MIN_CONTAINS = 3                     # *765* needs at least three digits, or it matches nearly everyone
LOCAL_LEN = 7                        # The Gambia: 7-digit subscriber numbers (longer local numbers also work)


def country_code():
    return str(getattr(settings, 'PHONE_COUNTRY_CODE', '220') or '').strip('+ ')


def digits(text):
    """All digits in the text, without the international 00 prefix."""
    d = re.sub(r'\D', '', text or '')
    return d[2:] if d.startswith('00') else d


def local(d):
    """The subscriber number: digits without the country code (only removed when what is left is a full number)."""
    cc = country_code()
    if cc and d.startswith(cc) and len(d) - len(cc) >= LOCAL_LEN:
        return d[len(cc):]
    return d


def contact_digits(text):
    """Every number found in free text such as "Mother: Fatou, +220 771 2345 / 990 1234", space-separated."""
    runs = re.findall(r'\+?\d[\d\s().\-]{5,}\d', text or '')
    return ' '.join(d for d in (digits(r) for r in runs) if len(d) >= 6)


def contact_local(text):
    """The emergency-contact numbers as local numbers, padded: " 7712345 9901234 " (empty when there are none)."""
    nums = [local(d) for d in contact_digits(text).split()]
    return f" {' '.join(nums)} " if nums else ''


def search_fields(phone, emergency_contact):
    """Every derived search field for a patient, in one place (used by Patient.save and the migration)."""
    d = digits(phone)
    loc = local(d)
    return {'phone_digits': d, 'phone_local': loc, 'phone_rev': loc[::-1],
            'contact_digits': contact_digits(emergency_contact), 'contact_local': contact_local(emergency_contact)}


# ------------------------------------------------------------------ understanding what was typed
@dataclass
class PhoneQuery:
    """What the person meant. ``kind`` is start, end, both, contains, any or full."""
    kind: str
    head: str = ''                    # digits the number starts with
    tail: str = ''                    # digits it ends with
    mids: list = field(default_factory=list)   # digits somewhere in between, in order
    raw: str = ''

    @property
    def wanted(self):
        return self.head + ''.join(self.mids) + self.tail

    def describe(self):
        h, t, m = self.head, self.tail, ' … '.join(self.mids)
        return {'start': f'starts with {h}', 'end': f'ends with {t}', 'both': f'starts with {h}, ends with {t}',
                'contains': f'contains {m}', 'full': f'number {h}', 'any': f'{h} anywhere in the number'}.get(self.kind, '')


def _strip_cc(part, typed):
    """Remove a country code the person typed (with +, 00 or in a full-length number)."""
    cc = country_code()
    explicit = typed.lstrip().startswith(('+', '00', '(')) or len(part) - len(cc) >= LOCAL_LEN
    if cc and explicit and part.startswith(cc) and len(part) > len(cc):
        return part[len(cc):]
    return part


def parse(q):
    """A PhoneQuery for text that looks like a phone search, or None."""
    q = (q or '').strip()
    if not q or not PHONE_QUERY.match(q):
        return None
    if WILDCARDS.search(q):
        parts = [digits(p) for p in WILDCARDS.split(q)]
        lead, trail = parts[0], parts[-1]
        mids = [p for p in parts[1:-1] if p]
        if lead:
            lead = _strip_cc(lead, q)
        if lead and trail and not mids:
            pq = PhoneQuery('both', head=lead, tail=trail, raw=q)
        elif lead and not trail and not mids:
            pq = PhoneQuery('start', head=lead, raw=q)
        elif trail and not lead and not mids:
            pq = PhoneQuery('end', tail=trail, raw=q)
        elif mids and not lead and not trail:
            pq = PhoneQuery('contains', mids=mids, raw=q)
        else:
            pq = PhoneQuery('both' if lead and trail else 'contains', head=lead, tail=trail, mids=mids, raw=q)
        need = MIN_CONTAINS if pq.kind == 'contains' else MIN_DIGITS
        return pq if len(pq.wanted) >= need else None
    d = digits(q)
    if len(d) < MIN_DIGITS:
        return None
    loc = _strip_cc(d, q)
    if loc != d or len(loc) >= LOCAL_LEN:
        return PhoneQuery('full', head=loc, raw=q)
    if len(loc) < MIN_ANYWHERE:
        return PhoneQuery('start', head=loc, raw=q)
    return PhoneQuery('any', head=loc, raw=q)


def is_phone_query(q):
    """Does the whole search look like a phone number or phone pattern rather than words?"""
    return parse(q) is not None


def _regex(pq):
    """A regular expression for one local number: ^head … mids … tail$ (digits only)."""
    rx = f'^{re.escape(pq.head)}' if pq.head else ''
    for m in pq.mids:
        rx += ('.*' if rx else '') + re.escape(m)
    if pq.tail:
        rx += ('.*' if rx else '') + f'{re.escape(pq.tail)}$'
    return rx


def phone_q(q, prefix=''):
    """A filter matching patients whose phone (or an emergency-contact phone) matches what was typed.
    ``prefix`` lets other models reach the patient, e.g. prefix='patient__'."""
    pq = q if isinstance(q, PhoneQuery) else parse(q)
    if not pq:
        return Q(pk__in=[])
    f = lambda name, lookup, value: Q(**{f'{prefix}{name}__{lookup}': value})
    if pq.kind in ('start', 'full'):
        cond = f('phone_local', 'startswith', pq.head) | f('contact_local', 'contains', f' {pq.head}')
    elif pq.kind == 'end':
        cond = f('phone_rev', 'startswith', pq.tail[::-1]) | f('contact_local', 'contains', f'{pq.tail} ')
    elif pq.kind == 'any':
        cond = f('phone_local', 'contains', pq.head) | f('contact_local', 'contains', pq.head)
    else:                                                   # both / contains: narrow with an index, confirm with a pattern
        rx = _regex(pq)
        own = f('phone_local', 'regex', rx)
        if pq.head:
            own &= f('phone_local', 'startswith', pq.head)
        elif pq.tail:
            own &= f('phone_rev', 'startswith', pq.tail[::-1])
        crx = rx.replace('^', r'(^| )').replace('$', r'( |$)').replace('.*', r'\d*')
        cond = own | f('contact_local', 'regex', crx)
    return cond


# ------------------------------------------------------------------ how well it matched, and where
def where(number, pq):
    """(rank, spans) for one local number, or None. Lower rank is better:
    0 the whole number · 1 starts with · 2 ends with · 3 both ends · 4 in the middle. spans: [(start, end), ...]."""
    if not number:
        return None
    n, h, t = len(number), pq.head, pq.tail
    if pq.kind in ('full', 'any') and number == h:
        return 0, [(0, n)]
    if pq.kind in ('full', 'start', 'any') and number.startswith(h):
        return 1, [(0, len(h))]
    if pq.kind == 'end' and number.endswith(t):
        return 2, [(n - len(t), n)]
    if pq.kind == 'any':
        if number.endswith(h):
            return 2, [(n - len(h), n)]
        i = number.find(h)
        return (4, [(i, i + len(h))]) if i >= 0 else None
    if pq.kind not in ('both', 'contains') or not re.search(_regex(pq), number):
        return None
    spans, pos = [], 0
    if h:
        spans.append((0, len(h))); pos = len(h)
    for m in pq.mids:
        i = number.find(m, pos)
        spans.append((i, i + len(m))); pos = i + len(m)
    if t:
        spans.append((n - len(t), n))
    return (3 if h and t else 4), spans


def best_match(phone_local_value, contact_local_value, pq):
    """The best place this patient matches: {'rank', 'own', 'number', 'spans'} or None. Contacts rank after own phones."""
    pq = pq if isinstance(pq, PhoneQuery) else parse(pq)
    if not pq:
        return None
    best = None
    w = where(phone_local_value or '', pq)
    if w:
        best = {'rank': w[0], 'own': True, 'number': phone_local_value, 'spans': w[1]}
    for n in (contact_local_value or '').split():
        w = where(n, pq)
        if w and (best is None or w[0] + 10 < best['rank']):
            best = {'rank': w[0] + 10, 'own': False, 'number': n, 'spans': w[1]}
    return best


# ------------------------------------------------------------------ "did you mean": one keystroke away
def one_edit_apart(a, b):
    """True when a and b differ by one substitution, one insertion/deletion, or one swap of neighbouring digits."""
    if a == b:
        return False
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diff = [i for i in range(la) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    s, t = (a, b) if la < lb else (b, a)
    i = 0
    while i < len(s) and s[i] == t[i]:
        i += 1
    return s[i:] == t[i + 1:]


def near_matches(q, queryset, limit=8):
    """Patients whose own number is one keystroke from a long typed number (a whole number, or 6+ digits).
    Candidates share the first three or the last three digits, which any single mistake leaves intact."""
    pq = q if isinstance(q, PhoneQuery) else parse(q)
    if not pq or pq.kind not in ('full', 'any') or len(pq.head) < 6:
        return []
    d = pq.head
    cands = queryset.filter(Q(phone_local__startswith=d[:3]) | Q(phone_rev__startswith=d[-3:][::-1])).only('pk', 'phone', 'phone_local')[:500]
    out = []
    for p in cands:
        n = p.phone_local
        if pq.kind == 'any' and len(n) > len(d):
            ok = any(one_edit_apart(n[i:i + len(d)], d) for i in range(len(n) - len(d) + 1))
        else:
            ok = one_edit_apart(n, d)
        if ok:
            out.append(p)
            if len(out) >= limit:
                break
    return out


# ------------------------------------------------------------------ showing the match
def mark_segments(phone, pq_or_text):
    """Split a phone *as displayed* into [(text, matched), ...] so the matched digits can be highlighted.
    Works on the formatted number ("+220 346 7656 778"), skipping the country code. None if nothing matches."""
    pq = pq_or_text if isinstance(pq_or_text, PhoneQuery) else parse(pq_or_text)
    if not phone or not pq:
        return None
    d = digits(phone)
    loc = local(d)
    w = where(loc, pq)
    if not w:
        return None
    skip = len(d) - len(loc) + (2 if re.sub(r'\D', '', phone).startswith('00') else 0)   # digits before the local number
    positions = [i for i, ch in enumerate(phone) if ch.isdigit()][skip:]
    hit = [False] * len(phone)
    for s, e in w[1]:
        if 0 <= s < e <= len(positions):
            for i in range(positions[s], positions[e - 1] + 1):
                hit[i] = True
    segs = []
    for ch, h in zip(phone, hit):
        if segs and segs[-1][1] == h:
            segs[-1] = (segs[-1][0] + ch, h)
        else:
            segs.append((ch, h))
    return segs if any(h for _, h in segs) else None
