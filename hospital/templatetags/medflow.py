from django import template
from django.utils import timezone

register = template.Library()


@register.simple_tag(takes_context=True)
def nav_active(context, *prefixes):
    """'active' when the current path is under any given prefix ('/' matches only the dashboard)."""
    path = context['request'].path
    for p in prefixes:
        if (p == '/' and path == '/') or (p != '/' and path.startswith(p)):
            return 'active'
    return ''


@register.filter
def user_initials(user):
    if not getattr(user, 'is_authenticated', False):
        return '?'
    name = (user.get_full_name() or user.get_username() or '?').split()
    return ''.join(n[0] for n in name[:2]).upper()


@register.filter
def display_name(user):
    if not user or not getattr(user, 'is_authenticated', True) or not hasattr(user, 'get_full_name'):
        return 'System'
    return user.get_full_name() or user.get_username()


@register.filter
def ago(value):
    """Compact relative time: 'now', '4m', '2h', '3d'."""
    if not value:
        return ''
    s = int((timezone.now() - value).total_seconds())
    if s < 60:
        return 'now'
    if s < 3600:
        return f'{s // 60}m'
    if s < 86400:
        return f'{s // 3600}h'
    return f'{s // 86400}d'


@register.filter
def get_item(d, key):
    return d.get(key) if hasattr(d, 'get') else None


@register.filter
def field_type(bound_field):
    return bound_field.field.widget.__class__.__name__.lower()


STATUS_TONE = {
    'waiting': 'amber', 'called': 'indigo', 'in_service': 'teal', 'completed': 'teal', 'skipped': '', 'cancelled': '',
    'open': 'teal', 'draft': 'amber', 'signed': 'indigo', 'dispensed': 'teal',
    'ordered': 'amber', 'collected': 'indigo', 'processing': 'indigo', 'resulted': 'plum', 'verified': 'teal',
    'sent': 'indigo', 'accepted': 'teal', 'declined': 'red', 'transferred': 'plum',
    'active': 'red', 'inactive': '', 'resolved': 'teal', 'history': '',
    'submitted': 'amber', 'approved': 'teal', 'rejected': 'red',
    'available': 'teal', 'occupied': 'ink', 'cleaning': 'amber', 'maintenance': '',
    'emergency': 'red', 'urgent': 'amber', 'routine': 'teal',
    'severe': 'red', 'moderate': 'amber', 'mild': '', 'unknown': '',
}


@register.filter
def tone(status):
    return STATUS_TONE.get(str(status), '')


@register.filter
def range_for_sex(parameter, sex):
    return parameter.range_label(sex)


@register.filter
def stars(value):
    """Rating out of 5 as star icons (full, half, empty), for display only."""
    from django.utils.html import format_html_join
    v = round(float(value or 0) * 2) / 2
    icons = ['bi-star-fill'] * int(v) + (['bi-star-half'] if v % 1 else []) 
    icons += ['bi-star'] * (5 - len(icons))
    return format_html_join('', '<i class="bi {}"></i>', ((i,) for i in icons))


_ASSET_CACHE = {}


@register.simple_tag
def asset(path):
    """Static URL with a content fingerprint (?v=…), so browsers fetch new CSS/JS after every update
    instead of reusing a stale cached copy."""
    import hashlib
    import os
    from django.contrib.staticfiles import finders
    from django.templatetags.static import static
    url = static(path)
    found = finders.find(path)
    if not found:
        return url
    mtime = os.path.getmtime(found)
    key = (path, mtime)
    if key not in _ASSET_CACHE:
        with open(found, 'rb') as fh:
            _ASSET_CACHE[key] = hashlib.md5(fh.read(), usedforsecurity=False).hexdigest()[:10]
    return f'{url}{"&" if "?" in url else "?"}v={_ASSET_CACHE[key]}'


@register.filter
def money(value):
    """Gambian dalasi with thousands separators, e.g. D1,250.00"""
    from decimal import Decimal
    try:
        return f'D{Decimal(value or 0):,.2f}'
    except Exception:
        return value


# medicine type icons: small inline SVGs so they read clearly at any size
_MED_ICONS = {
    'tablet': ('Tablet', '<circle cx="12" cy="12" r="8" fill="#fff" stroke="currentColor" stroke-width="1.8"/><path d="M7 12h10" stroke="currentColor" stroke-width="1.8"/>'),
    'capsule': ('Capsule', '<g transform="rotate(-35 12 12)"><rect x="3" y="8" width="18" height="8" rx="4" fill="#fff" stroke="currentColor" stroke-width="1.8"/><path d="M12 8v8" stroke="currentColor" stroke-width="1.8"/><path d="M12 8h5a4 4 0 0 1 0 8h-5z" fill="currentColor" opacity=".35"/></g>'),
    'injection': ('Injection', '<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M14 4l6 6M17 7l-9 9-3 1 1-3 9-9"/><path d="M11 10l3 3M9 12l2 2"/><path d="M5 19l-2 2"/></g>'),
    'syrup': ('Syrup / liquid', '<g fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 3h6v3l2 3v11a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V9l2-3z"/></g><path d="M7.9 13h8.2v6.8H7.9z" fill="currentColor" opacity=".35"/>'),
    'sachet': ('Sachet', '<path d="M5 4h14l-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1 2H5l1-2-1-2 1-2-1-2 1-2-1-2 1-2z" fill="#fff" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>'),
    'cream': ('Cream / ointment', '<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 9h11l4 2v2l-4 2H4z"/><path d="M19 11h2v2h-2"/></g>'),
    'drops': ('Drops', '<path d="M12 3c3 4 6 7.5 6 11a6 6 0 0 1-12 0c0-3.5 3-7 6-11z" fill="currentColor" opacity=".35" stroke="currentColor" stroke-width="1.6"/>'),
    'inhaler': ('Inhaler', '<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M9 3h4v7h4v8a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3v-5h3z"/></g>'),
    'infusion': ('Infusion / drip', '<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M8 3h8v8l-4 3-4-3z"/><path d="M12 14v7"/></g><path d="M9 7h6v3.5l-3 2.2-3-2.2z" fill="currentColor" opacity=".35"/>'),
}


def med_kind(medication, route=''):
    form = f'{getattr(medication, "form", "")} {route}'.lower()
    for key, words in (('infusion', ('infusion', 'drip')), ('injection', ('inject', 'iv', 'im ', 'vial', 'ampoule', ' sc')), ('capsule', ('capsule',)),
                       ('syrup', ('syrup', 'suspension', 'liquid', 'solution', 'elixir')), ('sachet', ('sachet', 'powder')),
                       ('cream', ('cream', 'ointment', 'gel', 'topical')), ('drops', ('drop', 'eye', 'ear')), ('inhaler', ('inhal', 'puff', 'nebul'))):
        if any(w in form + ' ' for w in words):
            return key
    return 'tablet'


@register.filter
def med_icon(medication, route=''):
    """Icon showing how a medicine is given (tablet, capsule, injection, syrup, sachet, cream, drops, inhaler)."""
    from django.utils.safestring import mark_safe
    route = route if isinstance(route, str) else getattr(route, 'route', '') or ''
    label, svg = _MED_ICONS[med_kind(medication, route)]
    return mark_safe(f'<svg class="med-ic k-{med_kind(medication, route)}" viewBox="0 0 24 24" width="20" height="20" role="img" aria-label="{label}"><title>{label}</title>{svg}</svg>')


@register.simple_tag(takes_context=True)
def patient_qr(context, patient, size=4):
    """QR code linking to the patient's record. It contains only a link; opening it still requires signing in."""
    import segno
    from django.urls import reverse
    from django.utils.safestring import mark_safe
    url = context['request'].build_absolute_uri(reverse('patient_qr', args=[patient.mrn]))
    return mark_safe(segno.make(url, error='m').svg_inline(scale=size, dark='#0F2C3F', light='#ffffff', border=2))


@register.filter
def split_pairs(value):
    """'7:Last 7 days,30:Last 30 days' -> [('7', 'Last 7 days'), ('30', 'Last 30 days')] for small fixed option lists."""
    return [tuple(x.split(':', 1)) for x in value.split(',')]


@register.filter
def safe_json(value):
    """JSON for a data attribute (single-quoted), with quotes escaped so it cannot break out of the attribute."""
    import json
    from django.utils.safestring import mark_safe
    return mark_safe(json.dumps(value).replace("'", '&#39;').replace('<', '\\u003c'))
