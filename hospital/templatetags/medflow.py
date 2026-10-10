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
    name = (user.get_full_name() or user.get_username() or '?').split()
    return ''.join(n[0] for n in name[:2]).upper()


@register.filter
def display_name(user):
    return user.get_full_name() or user.get_username() if user else 'System'


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
