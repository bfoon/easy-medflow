"""The queue ticket as a picture (PNG), drawn to look like the slip on screen, for WhatsApp and email.

Two versions:
* private (sent to the patient): first name and initial, and the same QR code as the printed slip (it opens the record
  only after a staff member signs in);
* public (link previews of the status page): no name, and the QR code opens the patient's own status page.
Drawn at twice the display size so it stays sharp on phones.
"""
import io
import os
from functools import lru_cache

from django.conf import settings
from django.utils import timezone

INK, MUTED, LINE, BG, WHITE = (15, 44, 63), (90, 111, 125), (201, 213, 207), (242, 245, 243), (255, 255, 255)
W = 720                     # px; shown at 360 px wide
PAD, CARD_PAD = 28, 44
FONT_DIR = os.path.join(os.path.dirname(__file__), 'static', 'hospital', 'vendor', 'fonts')


@lru_cache(maxsize=32)
def _font(name, size, weight=None):
    from PIL import ImageFont
    try:
        f = ImageFont.truetype(os.path.join(FONT_DIR, name), size)
        if weight:
            try:
                f.set_variation_by_axes([96, weight])        # Bricolage: optical size, weight
            except Exception:
                pass
        return f
    except Exception:                                         # a Pillow without WOFF2 support: plain but readable
        return ImageFont.load_default(size)


def _fonts():
    return {'head': _font('public-sans-700.woff2', 31), 'dept': _font('public-sans-400.woff2', 29),
            'num': _font('bricolage-grotesque-var.woff2', 168, 800), 'meta': _font('public-sans-400.woff2', 25),
            'name': _font('public-sans-700.woff2', 29), 'foot': _font('public-sans-400.woff2', 25)}


def _wrap(draw, text, font, width):
    words, lines, cur = text.split(' '), [], ''          # split on plain spaces only: non-breaking spaces keep a phrase together
    for w in words:
        test = f'{cur} {w}'.strip()
        if draw.textlength(test, font=font) <= width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _qr(data, px):
    import segno
    from PIL import Image
    buf = io.BytesIO()
    q = segno.make(data, error='m')
    scale = max(2, px // (q.symbol_size(border=2)[0]))
    q.save(buf, kind='png', scale=scale, dark='#0F2C3F', light='#ffffff', border=2)
    buf.seek(0)
    return Image.open(buf).convert('RGB')


def meta_line(t, ahead, est):
    nb = lambda x: x.replace(' ', '\u00a0')
    d = timezone.localtime(t.created_at)
    s = nb(f'{d:%a} {d.day} {d:%b %Y}') + ' · ' + f'{d:%H:%M}'
    if ahead:
        s += ' · ' + nb(f'{ahead} ahead of you') + (', ' + nb(f'about {est} min') if est else '')
    return s


def render(t, *, ahead=0, est=0, qr_data='', private=True):
    """PNG bytes of the ticket."""
    from PIL import Image, ImageDraw
    f = _fonts()
    hospital = getattr(settings, 'HOSPITAL_NAME', '') or 'E-MedFlow Hospital'
    inner = W - 2 * PAD - 2 * CARD_PAD
    probe = ImageDraw.Draw(Image.new('RGB', (10, 10)))
    meta = _wrap(probe, meta_line(t, ahead, est), f['meta'], inner)
    foot = _wrap(probe, 'Please wait until your number is called on the screen. Show this ticket at the desk.', f['foot'], inner)
    name = f'{t.patient.first_name} {t.patient.last_name[:1]}.' if private and t.patient_id else ''
    qr_px = 250
    # vertical layout: (kind, content, font, gap-before)
    rows = [('text', hospital, f['head'], 0), ('text', str(t.department), f['dept'], 12), ('num', t.display_code, f['num'], 20)]
    rows += [('text', line, f['meta'], 26 if i == 0 else 6) for i, line in enumerate(meta)]
    if name:
        rows.append(('text', name, f['name'], 24))
    if qr_data:
        rows.append(('qr', qr_data, None, 22))
    rows += [('text', line, f['foot'], 26 if i == 0 else 6) for i, line in enumerate(foot)]

    def height(kind, content, font):
        if kind == 'qr':
            return qr_px
        box = probe.textbbox((0, 0), content, font=font)
        return (box[3] - box[1]) if kind == 'num' else font.size + 6

    card_h = CARD_PAD * 2 + sum(g + height(k, c, fo) for k, c, fo, g in rows)
    img = Image.new('RGB', (W, card_h + 2 * PAD), BG)
    d = ImageDraw.Draw(img)
    box = (PAD, PAD, W - PAD, PAD + card_h)
    d.rounded_rectangle(box, radius=34, fill=WHITE)
    _dashed_round(d, box, 34, LINE, width=3)
    y = PAD + CARD_PAD
    for kind, content, font, gap in rows:
        y += gap
        h = height(kind, content, font)
        if kind == 'qr':
            q = _qr(content, qr_px).resize((qr_px, qr_px), Image.NEAREST)
            img.paste(q, ((W - qr_px) // 2, y))
        elif kind == 'num':
            bb = d.textbbox((0, 0), content, font=font)
            d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], y - bb[1]), content, font=font, fill=INK)
        else:
            colour = MUTED if font in (f['dept'], f['meta'], f['foot']) else INK
            d.text((W / 2, y), content, font=font, fill=colour, anchor='ma')
        y += h
    out = io.BytesIO()
    img.save(out, format='PNG', optimize=True)
    return out.getvalue()


def _dashed_round(d, box, r, colour, width=3, dash=14, gap=10):
    """Dashed outline like the slip's dashed border (straight edges dashed, corners drawn as arcs)."""
    x0, y0, x1, y1 = box
    for a, b, fixed, horizontal in ((x0 + r, x1 - r, y0, True), (x0 + r, x1 - r, y1, True), (y0 + r, y1 - r, x0, False), (y0 + r, y1 - r, x1, False)):
        p = a
        while p < b:
            q = min(p + dash, b)
            d.line([(p, fixed), (q, fixed)] if horizontal else [(fixed, p), (fixed, q)], fill=colour, width=width)
            p = q + gap
    for cx, cy, start in ((x0, y0, 180), (x1 - 2 * r, y0, 270), (x1 - 2 * r, y1 - 2 * r, 0), (x0, y1 - 2 * r, 90)):
        d.arc([cx, cy, cx + 2 * r, cy + 2 * r], start=start, end=start + 90, fill=colour, width=width)
