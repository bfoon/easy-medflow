"""Phone numbers: one way to store them for searching and one way to match what people type.

Phones are entered every way imaginable: "+220 341 5919", "3415919", "341-5919", "00220 3415919", "(220) 341 5919".
Each patient keeps a digits-only copy (Patient.phone_digits, and contact_digits for numbers in the emergency contact)
so a search compares digits with digits. Gambian numbers are 7 digits after the 220 country code, so a query with a
country code also finds a number stored without one, and the other way round.
"""
import re

from django.db.models import Q

PHONE_QUERY = re.compile(r'^[\d\s+().\-/]+$')
MIN_DIGITS = 4                       # "5919" (last four digits, as staff often say) is enough; fewer is too vague
LOCAL_LEN = 7                        # The Gambia: 7-digit subscriber numbers


def digits(text):
    """All digits in the text, without the international 00 prefix."""
    d = re.sub(r'\D', '', text or '')
    return d[2:] if d.startswith('00') else d


def contact_digits(text):
    """Every number found in free text such as "Mother: Fatou, +220 771 2345 / 990 1234", space-separated."""
    runs = re.findall(r'\+?\d[\d\s().\-]{5,}\d', text or '')
    return ' '.join(d for d in (digits(r) for r in runs) if len(d) >= 6)


def is_phone_query(q):
    """Does the whole search look like a phone number (digits, spaces, + ( ) - . /) rather than words?"""
    q = (q or '').strip()
    return bool(q) and bool(PHONE_QUERY.match(q)) and len(digits(q)) >= MIN_DIGITS


def phone_q(q, prefix=''):
    """A filter matching patients whose phone (or emergency-contact phone) contains the typed number.
    `prefix` lets other models reach the patient, e.g. prefix='patient__'."""
    d = digits(q)
    if len(d) < MIN_DIGITS:
        return Q(pk__in=[])
    cond = Q(**{f'{prefix}phone_digits__contains': d}) | Q(**{f'{prefix}contact_digits__contains': d})
    if len(d) > LOCAL_LEN:                       # typed with a country code: also match the number stored without it
        local = d[-LOCAL_LEN:]
        cond |= Q(**{f'{prefix}phone_digits__endswith': local}) | Q(**{f'{prefix}contact_digits__contains': local})
    return cond

