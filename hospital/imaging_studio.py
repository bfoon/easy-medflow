"""Imaging studio: Dr. Flow's quality check and enhancement recipe, and the extra processing steps of the studio.

Everything here runs on the server, on the hospital's own machine: no pixel leaves it. The browser (imaging-studio.js)
implements the same steps on a smaller working copy so sliders respond instantly; when the clinician saves, the server
recomputes the result at full resolution from the original with the recorded steps (the original is never changed).

Steps, in this order (all optional, each value 0 = off):
    smooth   0-1   edge-preserving smoothing (self-guided filter): removes grain and ultrasound speckle, keeps edges
    level    bool  stretch the darkest 0.5 % to black and the brightest 0.5 % to white
    glare    0-1   roll off blown highlights, e.g. the light box around a film photographed with a phone
    enhance  0-4   adaptive contrast (CLAHE, in imaging_tools)
    gamma    0.3-3 mid-tone brightness
    detail   0-2   local contrast at the scale of anatomy (large-radius unsharp mask): vessels, trabeculae, borders
    sharpen  0-3   fine edges (small-radius unsharp mask)
    invert   bool
    colour   name  ILLUSTRATIVE colour from brightness only (PALETTES); never a statement about tissue type
    relief   0-1   light the image as if brightness were height, for a photo-like 3-D look
    light    0-360 direction the light comes from, in degrees (0 = from the top, clockwise)
    edges    0-1   outline strong edges in cyan (cortex of bones, borders of organs, tubes and lines)

Radii are relative to the image size, so the small preview in the browser and the full-size saved copy look the same.
"""
import numpy as np

# brightness 0-1 -> colour, as stops (position, (r, g, b)); interpolated linearly
PALETTES = {
    'anatomy': {'label': 'Anatomy (illustrative)', 'stops': [
        (0.00, (6, 8, 14)), (0.12, (22, 30, 52)), (0.26, (92, 58, 40)), (0.38, (176, 128, 72)),
        (0.50, (178, 106, 92)), (0.64, (206, 142, 124)), (0.78, (230, 198, 172)), (0.90, (244, 236, 214)), (1.00, (255, 252, 244))]},
    'warm': {'label': 'Warm film', 'stops': [(0.0, (8, 5, 2)), (0.35, (88, 52, 26)), (0.7, (214, 170, 118)), (1.0, (255, 246, 226))]},
    'cool': {'label': 'Cool blue', 'stops': [(0.0, (2, 6, 14)), (0.4, (24, 72, 120)), (0.75, (140, 196, 226)), (1.0, (246, 252, 255))]},
    'heat': {'label': 'Heat', 'stops': [(0.0, (0, 0, 0)), (0.3, (120, 10, 10)), (0.55, (230, 90, 10)), (0.8, (255, 210, 60)), (1.0, (255, 255, 230))]},
    'spectrum': {'label': 'Spectrum', 'stops': [(0.0, (20, 0, 90)), (0.2, (0, 70, 220)), (0.4, (0, 190, 170)), (0.6, (120, 220, 40)),
                                                (0.8, (250, 170, 0)), (1.0, (230, 20, 20))]},
}
EDGE_COLOUR = np.array([63, 224, 208], dtype=np.float32) / 255
STUDIO_KEYS = ('smooth', 'glare', 'detail', 'colour', 'relief', 'light', 'edges')


# ------------------------------------------------------------------ small building blocks
def _box1(a, r, axis):
    """Running mean along one axis with the window shrunk at the ends. Plain slices only (fast on large images)."""
    a = np.moveaxis(a, axis, 0)
    n = a.shape[0]
    r = min(r, n - 1)
    c = np.empty((n + 1,) + a.shape[1:], dtype=np.float64)
    c[0] = 0
    np.cumsum(a, axis=0, out=c[1:])
    hi = np.concatenate([c[r + 1:n + 1], np.repeat(c[n:n + 1], r, 0)]) if r else c[1:]
    lo = np.concatenate([np.repeat(c[0:1], r, 0), c[0:n - r]]) if r else c[:-1]
    cnt = (np.minimum(np.arange(n) + r + 1, n) - np.maximum(np.arange(n) - r, 0)).reshape((n,) + (1,) * (a.ndim - 1))
    return np.moveaxis(((hi - lo) / cnt).astype(np.float32), 0, axis)


def _box(a, r):
    """Mean over a (2r+1)^2 square, with the window shrunk at the borders (running sums; O(1) per pixel, separable)."""
    if r < 1:
        return a
    return _box1(_box1(a, r, 0), r, 1)


def _blur(a, r):
    """Close to a Gaussian: three box passes."""
    for _ in range(3):
        a = _box(a, r)
    return a


def radius(shape, frac):
    """A radius as a fraction of the short side, at least 1 pixel."""
    return max(1, int(round(min(shape) * frac)))


def guided_smooth(g, strength):
    """Self-guided filter (He et al.): flat areas are averaged, edges kept. g in 0-1."""
    if strength <= 0:
        return g
    r = radius(g.shape, 0.004 + 0.012 * strength)
    eps = (0.02 + 0.10 * strength) ** 2
    m, m2 = _box(g, r), _box(g * g, r)
    var = np.maximum(m2 - m * m, 0)
    a = var / (var + eps)
    b = m - a * m
    return np.clip(_box(a, r) * g + _box(b, r), 0, 1)


def level(g):
    lo, hi = np.percentile(g, [0.5, 99.5])
    if hi - lo < 1e-3:
        return g
    return np.clip((g - lo) / (hi - lo), 0, 1)


def glare(g, strength):
    """Soft knee above the 85th percentile: blown light-box white is pulled down, darker anatomy is untouched."""
    if strength <= 0:
        return g
    knee = float(np.percentile(g, 85))
    knee = min(max(knee, 0.55), 0.95)
    over = np.maximum(g - knee, 0)
    span = 1 - knee
    squashed = knee + span * (1 - np.exp(-over / max(span, 1e-3) * 2.2)) / (1 - np.exp(-2.2))
    rolled = np.where(g > knee, knee + (squashed - knee) * (1 - 0.6 * strength), g)
    return np.clip(rolled, 0, 1)


def gamma(g, value):
    if abs(value - 1) <= 0.02:
        return g
    return np.power(np.clip(g, 0, 1), 1 / max(0.3, min(value, 3)))


def unsharp(g, frac, amount):
    if amount <= 0:
        return g
    return np.clip(g + amount * (g - _blur(g, radius(g.shape, frac))), 0, 1)


def detail(g, amount):
    """Local contrast at anatomical scale. Damped in the darkest and brightest areas so noise and burn-out are not boosted."""
    if amount <= 0:
        return g
    base = _blur(g, radius(g.shape, 0.03))
    weight = 4 * g * (1 - g)
    return np.clip(g + amount * 0.9 * weight * (g - base), 0, 1)


def sobel(g):
    p = np.pad(g, 1, mode='edge')
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return gx / 8, gy / 8


def palette_lut(name):
    stops = PALETTES[name]['stops']
    xs = np.array([s[0] for s in stops]) * 255
    lut = np.stack([np.interp(np.arange(256), xs, [s[1][c] for s in stops]) for c in range(3)], 1)
    return (lut / 255).astype(np.float32)


def colourise(g, name):
    """Brightness -> RGB through a palette (0-1 floats, shape h x w x 3)."""
    return palette_lut(name)[np.clip(g * 255 + 0.5, 0, 255).astype(np.uint8)]


def relief(rgb, g, strength, light_deg=315):
    """Light the picture as if brightness were height: Lambert shading plus a soft highlight."""
    if strength <= 0:
        return rgb
    h = _blur(g, radius(g.shape, 0.002))
    gx, gy = sobel(h)
    k = 6.0 * min(g.shape) / 512               # same slope whatever the image size
    nx, ny, nz = -gx * k, -gy * k, np.ones_like(g)
    n = np.sqrt(nx * nx + ny * ny + 1)
    a = np.deg2rad(light_deg)
    lx, ly, lz = np.sin(a) * 0.62, -np.cos(a) * 0.62, 0.78     # light from above the picture, tilted toward light_deg
    lam = np.clip((nx * lx + ny * ly + nz * lz) / n, 0, 1)
    spec = np.power(lam, 24) * 0.35
    shade = (0.45 + 0.75 * lam)[..., None]
    lit = np.clip(rgb * shade + spec[..., None], 0, 1)
    return rgb * (1 - strength) + lit * strength


def edges(rgb, g, strength):
    if strength <= 0:
        return rgb
    gx, gy = sobel(guided_smooth(g, 0.4))
    mag = np.sqrt(gx * gx + gy * gy)
    hi = float(np.percentile(mag, 97)) or 1e-3
    alpha = (np.clip((mag - hi * 0.45) / (hi * 0.75), 0, 1) * strength)[..., None]
    return rgb * (1 - alpha) + EDGE_COLOUR * alpha


# ------------------------------------------------------------------ options
def _f(opts, key, lo, hi, default=0.0):
    try:
        v = float(opts.get(key, default) or 0)
    except (TypeError, ValueError):
        return default
    return min(max(v, lo), hi)


def clean_opts(opts):
    """The studio part of a processing request, checked and clamped. Unknown keys are ignored."""
    o = {'smooth': _f(opts, 'smooth', 0, 1), 'glare': _f(opts, 'glare', 0, 1), 'detail': _f(opts, 'detail', 0, 2),
         'relief': _f(opts, 'relief', 0, 1), 'light': _f(opts, 'light', 0, 360, 315), 'edges': _f(opts, 'edges', 0, 1)}
    c = str(opts.get('colour') or '')
    o['colour'] = c if c in PALETTES else ''
    return o


def wants_studio(opts):
    o = clean_opts(opts)
    return bool(o['smooth'] or o['glare'] or o['detail'] or o['colour'] or o['relief'] or o['edges'])


def early_steps(g, o, applied):
    """Tone steps that come before CLAHE (smoothing removes grain that CLAHE would otherwise amplify)."""
    if o['smooth']:
        g = guided_smooth(g, o['smooth']); applied['smooth'] = round(o['smooth'], 2)
    return g


def late_steps(g, o, applied):
    if o['glare']:
        g = glare(g, o['glare']); applied['glare'] = round(o['glare'], 2)
    if o['detail']:
        g = detail(g, o['detail']); applied['detail'] = round(o['detail'], 2)
    return g


def colour_steps(g, o, applied):
    """Returns an RGB float array, or None when no colour, relief or edges were asked for."""
    if not (o['colour'] or o['relief'] or o['edges']):
        return None
    rgb = colourise(g, o['colour']) if o['colour'] else np.repeat(g[..., None], 3, 2)
    if o['colour']:
        applied['colour'] = o['colour']
    if o['relief']:
        rgb = relief(rgb, g, o['relief'], o['light']); applied['relief'] = round(o['relief'], 2); applied['light'] = int(o['light'])
    if o['edges']:
        rgb = edges(rgb, g, o['edges']); applied['edges'] = round(o['edges'], 2)
    return rgb


# ------------------------------------------------------------------ Dr. Flow: quality check and recipe
def _gray_small(img, side=1024):
    from PIL import Image
    im = img.copy()
    im.thumbnail((side, side), Image.Resampling.LANCZOS)
    rgb = np.asarray(im.convert('RGB'), dtype=np.float32) / 255
    g = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    sat = (rgb.max(2) - rgb.min(2)).mean()
    return g, float(sat)


def measure(img):
    """Numbers that describe how readable the picture is. img: a PIL image."""
    g, sat = _gray_small(img)
    h, w = g.shape
    p1, p50, p99 = (float(v) for v in np.percentile(g, [1, 50, 99]))
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)        # Immerkær's noise estimator
    p = np.pad(g, 1, mode='edge')
    conv = sum(k[i, j] * p[i:i + h, j:j + w] for i in range(3) for j in range(3))
    noise = float(np.sqrt(np.pi / 2) / (6 * max(1, (w - 2) * (h - 2))) * np.abs(conv).sum())
    gx, gy = sobel(g)
    grad = np.sqrt(gx * gx + gy * gy)
    spread = max(p99 - p1, 1e-3)
    sharp = float(np.percentile(grad, 99) / spread)
    # exposure of the subject, ignoring the black background around an X-ray or a CT slice
    body = g[g > max(0.06, p1 + 0.04)]
    body_median = float(np.median(body)) if body.size > g.size * 0.1 else p50
    return {'mean': round(float(g.mean()), 3), 'median': round(p50, 3), 'p1': round(p1, 3), 'p99': round(p99, 3),
            'body_median': round(body_median, 3), 'spread': round(spread, 3), 'dark_clip': round(float((g <= 0.02).mean()), 3), 'bright_clip': round(float((g >= 0.98).mean()), 3),
            'noise': round(noise, 4), 'sharpness': round(sharp, 3), 'colour': round(sat, 3), 'width': img.width, 'height': img.height}


PRESETS = {
    # name: (label, recipe)
    'original': ('Original', {}),
    'lungs': ('Lungs', {'smooth': .25, 'level': True, 'enhance': 2.5, 'gamma': .95, 'detail': .8, 'sharpen': .5}),
    'bone': ('Bone', {'smooth': .2, 'level': True, 'enhance': 2, 'gamma': .85, 'detail': 1.1, 'sharpen': 1.1, 'edges': .25}),
    'soft': ('Soft tissue', {'smooth': .45, 'level': True, 'enhance': 1.5, 'gamma': 1.2, 'detail': .5}),
    'ultrasound': ('Ultrasound', {'smooth': .8, 'level': True, 'enhance': 1, 'gamma': 1.1, 'detail': .4}),
    'film': ('Film photo', {'smooth': .35, 'level': True, 'glare': .8, 'enhance': 2, 'gamma': 1, 'detail': .7, 'sharpen': .6}),
    'night': ('Night reading', {'smooth': .25, 'level': True, 'enhance': 2, 'detail': .6, 'invert': True}),
    'photo': ('Photo-real', {'smooth': .45, 'level': True, 'enhance': 1.8, 'detail': .9, 'colour': 'anatomy', 'relief': .55, 'light': 315}),
}


def suggest(m, modality='', region=''):
    """A recipe for the studio controls and the reasons for each step, from measure() and the type of study."""
    r = {'smooth': 0.0, 'level': False, 'glare': 0.0, 'enhance': 0.0, 'gamma': 1.0, 'detail': 0.0, 'sharpen': 0.0}
    why = []
    region = (region or '').lower()
    us = modality in ('ultrasound', 'echo')
    bone_region = any(w in region for w in ('knee', 'hip', 'femur', 'tibia', 'ankle', 'wrist', 'hand', 'foot', 'elbow', 'shoulder',
                                            'spine', 'pelvis', 'skull', 'humerus', 'radius', 'fibula', 'bone'))
    chest = 'chest' in region or 'lung' in region or 'thorax' in region
    # noise and speckle first: everything after would amplify it
    if us:
        r['smooth'] = 0.75 if m['noise'] > 0.02 else 0.55
        why.append(('smooth', f'Ultrasound speckle softened with edge-preserving smoothing ({int(r["smooth"] * 100)} %), keeping organ borders sharp.'))
    elif m['noise'] > 0.03:
        r['smooth'] = 0.6
        why.append(('smooth', f'Grainy picture (noise {m["noise"]:.3f}): strong edge-preserving smoothing before any contrast boost.'))
    elif m['noise'] > 0.015:
        r['smooth'] = 0.35
        why.append(('smooth', 'Some grain: light edge-preserving smoothing.'))
    # range
    if m['spread'] < 0.75 or m['p1'] > 0.08 or m['p99'] < 0.9:
        r['level'] = True
        why.append(('level', f'Only {int(m["spread"] * 100)} % of the grey range is used: stretched to full black and white.'))
    # phone photo of a film on a light box
    if m['bright_clip'] > 0.06 or (m['colour'] > 0.06 and m['bright_clip'] > 0.02):
        r['glare'] = 0.8 if m['bright_clip'] > 0.15 else 0.5
        why.append(('glare', f'{int(m["bright_clip"] * 100)} % of the picture is blown white (light box or glare): highlights rolled off.'))
    # exposure
    expo = m.get('body_median', m['median'])
    if expo < 0.3:
        r['gamma'] = 1.35 if expo < 0.2 else 1.2
        why.append(('gamma', f'Dark picture (the subject sits at {int(expo * 255)}/255): mid-tones brightened.'))
    elif expo > 0.72 and not r['glare']:
        r['gamma'] = 0.8
        why.append(('gamma', f'Washed-out picture (the subject sits at {int(expo * 255)}/255): mid-tones darkened.'))
    # contrast
    r['enhance'] = 1.0 if us else 2.5 if chest else 2.0 if m['spread'] < 0.6 else 1.5
    why.append(('enhance', 'Adaptive contrast so detail shows in both the dark and the bright areas'
                + (' (chest: lung fields and mediastinum together).' if chest else '.')))
    r['detail'] = 1.0 if bone_region else 0.8 if chest else 0.4 if us else 0.6
    why.append(('detail', 'Local contrast raised at the scale of ' + ('bone cortex and trabeculae.' if bone_region else
                'vessels and fissures.' if chest else 'organ borders.' if us else 'anatomical structures.')))
    if not us:
        r['sharpen'] = 1.0 if m['sharpness'] < 0.35 or bone_region else 0.5
        why.append(('sharpen', 'Soft picture: fine edges sharpened.' if m['sharpness'] < 0.35 else 'Fine edges crisped a little.'))
    if r['smooth'] and r['sharpen'] > 0.6:
        r['sharpen'] = 0.6                      # do not undo the smoothing
    score = score_of(m)
    return {'recipe': {k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()}, 'reasons': [{'step': k, 'text': t} for k, t in why],
            'score': score, 'verdict': verdict(score), 'issues': issues(m)}


def score_of(m):
    s = 100.0
    s -= max(0, 0.8 - m['spread']) * 60
    s -= min(25, m['noise'] * 700)
    s -= min(20, max(0, m['bright_clip'] - 0.02) * 120)
    s -= min(15, max(0, m['dark_clip'] - 0.25) * 60)
    s -= max(0, 0.45 - m['sharpness']) * 40
    s -= abs(m.get('body_median', m['median']) - 0.5) * 20
    return int(max(5, min(100, round(s))))


def verdict(score):
    return 'Good' if score >= 75 else 'Fair' if score >= 50 else 'Poor'


def issues(m):
    out = []
    if m['noise'] > 0.03:
        out.append('Very grainy')
    elif m['noise'] > 0.015:
        out.append('Some grain')
    if m['spread'] < 0.6:
        out.append('Flat contrast')
    if m['bright_clip'] > 0.06:
        out.append('Glare or blown highlights')
    expo = m.get('body_median', m['median'])
    if expo < 0.25:
        out.append('Dark')
    elif expo > 0.75:
        out.append('Washed out')
    if m['sharpness'] < 0.35:
        out.append('Blurred')
    if m['colour'] > 0.06:
        out.append('Colour photo of a film')
    return out
