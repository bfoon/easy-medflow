"""Filters for the lab guidance panel."""
import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


def _inline(s):
    s = escape(s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'<i>\1</i>', s)
    # [text](https://…) links only; everything else stays escaped text
    return re.sub(r'\[([^\]]+)\]\((https://[^)\s]+)\)', r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', s)


@register.filter
def simple_md(text):
    """Render the small Markdown subset AI answers use (headings, numbered and bulleted lists, bold, links) as safe
    HTML. All text is escaped first, so nothing from the AI service can inject markup."""
    out, open_list = [], None
    for raw in (text or '').splitlines():
        line = raw.strip()
        h = re.match(r'^#{1,4}\s+(.*)', line)
        ol = re.match(r'^(\d+)[.)]\s+(.*)', line)
        ul = re.match(r'^[-*•]\s+(.*)', line)
        if ul and open_list == 'ol' and raw[:1] in (' ', '\t') and out and out[-1].endswith('</li>'):
            out[-1] = out[-1][:-5] + f'<span class="sub">{_inline(ul.group(1))}</span></li>'   # indented note under a numbered step
            continue
        kind = 'ol' if ol else 'ul' if ul else None
        if open_list and kind != open_list and line:
            out.append(f'</{open_list}>')
            open_list = None
        if h:
            out.append(f'<h4>{_inline(h.group(1))}</h4>')
        elif kind:
            if not open_list:
                out.append(f'<{kind}>')
                open_list = kind
            out.append(f'<li>{_inline(ol.group(2) if ol else ul.group(1))}</li>')
        elif line:
            out.append(f'<p>{_inline(line)}</p>')
    if open_list:
        out.append(f'</{open_list}>')
    return mark_safe(''.join(out))


@register.filter
def source_short(name):
    return {'World Health Organization': 'WHO'}.get(name, name)


@register.filter
def age_months(months):
    if months is None:
        return ''
    return f'{months} months' if months < 24 else f'{months // 12} years'
