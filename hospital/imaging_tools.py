"""Process scan photos, e.g. a phone picture of an X-ray film on a light box.

Steps (all optional, applied in this order): straighten from four corners, rotate/flip, greyscale, remove noise,
level the exposure, adaptive contrast (CLAHE), gamma, sharpen, invert. The original upload is never changed:
the result is stored as a new image linked to it, with the steps recorded.

The imaging studio adds edge-preserving smoothing, glare roll-off, anatomical detail, illustrative colour, relief
lighting and edge outlines (see imaging_studio.py). When any of those is asked for, the tone steps run in floating
point in the same order as the browser preview, so the saved copy matches what the clinician saw.
"""
import io

import numpy as np
from PIL import Image, ImageFilter, ImageOps

MAX_SIDE = 3000


def _perspective_coeffs(dst, src):
    """Coefficients for PIL's PERSPECTIVE transform mapping output points `dst` back to input points `src`."""
    A, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    return np.linalg.solve(np.array(A, dtype=float), np.array(b, dtype=float)).tolist()


def straighten(img, corners):
    """corners: four [x, y] fractions of the image size, in order top-left, top-right, bottom-right, bottom-left."""
    w, h = img.size
    pts = [(max(0, min(1, float(x))) * w, max(0, min(1, float(y))) * h) for x, y in corners]
    tl, tr, br, bl = pts
    dist = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** .5
    ow, oh = int(max(dist(tl, tr), dist(bl, br))), int(max(dist(tl, bl), dist(tr, br)))
    if ow < 32 or oh < 32:
        raise ValueError('The selected area is too small.')
    coeffs = _perspective_coeffs([(0, 0), (ow, 0), (ow, oh), (0, oh)], pts)
    return img.transform((ow, oh), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)


def clahe(gray, clip=2.0, tiles=8):
    """Contrast-limited adaptive histogram equalisation on an 8-bit greyscale array.
    Each tile gets its own clipped histogram curve; curves are blended bilinearly so there are no tile seams."""
    h, w = gray.shape
    ty, tx = max(1, min(tiles, h // 16)), max(1, min(tiles, w // 16))
    ys, xs = np.linspace(0, h, ty + 1).astype(int), np.linspace(0, w, tx + 1).astype(int)
    luts = np.zeros((ty, tx, 256), dtype=np.float32)
    for i in range(ty):
        for j in range(tx):
            tile = gray[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            hist = np.bincount(tile.ravel(), minlength=256).astype(np.float32)
            limit = max(1.0, clip * tile.size / 256)
            excess = np.maximum(hist - limit, 0).sum()
            hist = np.minimum(hist, limit) + excess / 256          # spread what was clipped evenly
            cdf = hist.cumsum()
            luts[i, j] = (cdf - cdf.min()) / max(1.0, cdf.max() - cdf.min()) * 255
    cy, cx = (ys[:-1] + ys[1:]) / 2, (xs[:-1] + xs[1:]) / 2      # tile centres
    yy, xx = np.arange(h), np.arange(w)
    fy = np.clip(np.interp(yy, cy, np.arange(ty)), 0, ty - 1); fx = np.clip(np.interp(xx, cx, np.arange(tx)), 0, tx - 1)
    y0, x0 = np.floor(fy).astype(int), np.floor(fx).astype(int)
    y1, x1 = np.minimum(y0 + 1, ty - 1), np.minimum(x0 + 1, tx - 1)
    wy, wx = (fy - y0)[:, None], (fx - x0)[None, :]
    g = gray
    v00 = luts[y0[:, None], x0[None, :], g]; v01 = luts[y0[:, None], x1[None, :], g]
    v10 = luts[y1[:, None], x0[None, :], g]; v11 = luts[y1[:, None], x1[None, :], g]
    out = (v00 * (1 - wx) + v01 * wx) * (1 - wy) + (v10 * (1 - wx) + v11 * wx) * wy
    return np.clip(out, 0, 255).astype(np.uint8)


def process(src_file, opts):
    """Apply the requested steps to an image file object. Returns (PNG bytes, the steps actually applied)."""
    img = Image.open(src_file)
    img = ImageOps.exif_transpose(img)                 # phone photos carry their rotation in EXIF
    img = img.convert('RGB')
    applied = {}
    corners = opts.get('corners')
    if corners and len(corners) == 4 and corners != [[0, 0], [1, 0], [1, 1], [0, 1]]:
        img = straighten(img, corners); applied['corners'] = [[round(float(a), 4), round(float(b), 4)] for a, b in corners]
    rot = int(opts.get('rotate') or 0) % 360
    if rot in (90, 180, 270):
        img = img.rotate(-rot, expand=True); applied['rotate'] = rot
    if opts.get('flip'):
        img = ImageOps.mirror(img); applied['flip'] = True
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS); applied['resized'] = list(img.size)
    from . import imaging_studio as S
    st = S.clean_opts(opts)
    if st['colour']:
        opts = {**opts, 'grayscale': True}       # colour comes from brightness, so start from grey
    if opts.get('grayscale', True):
        img = img.convert('L'); applied['grayscale'] = True
    if opts.get('denoise'):
        img = img.filter(ImageFilter.MedianFilter(3)); applied['denoise'] = True
    if S.wants_studio(opts):
        img = _studio(img, opts, st, applied)
    else:
        img = _classic(img, opts, applied)
    buf = io.BytesIO()
    img.save(buf, 'PNG', compress_level=6)          # optimize=True costs seconds on big colour images for a few % size
    return buf.getvalue(), applied


def _classic(img, opts, applied):
    """The original photo-processing path (PIL), unchanged for requests without studio steps."""
    if opts.get('level'):
        img = ImageOps.autocontrast(img, cutoff=1); applied['level'] = True
    strength = float(opts.get('enhance') or 0)
    if strength > 0:
        strength = min(strength, 4.0)
        if img.mode == 'L':
            img = Image.fromarray(clahe(np.asarray(img), clip=1 + strength))
        else:                                           # colour: equalise brightness only, keep the colours
            ycc = img.convert('YCbCr'); y, cb, cr = ycc.split()
            img = Image.merge('YCbCr', (Image.fromarray(clahe(np.asarray(y), clip=1 + strength)), cb, cr)).convert('RGB')
        applied['enhance'] = round(strength, 2)
    gamma = float(opts.get('gamma') or 1)
    if abs(gamma - 1) > .02:
        gamma = max(.3, min(gamma, 3))
        lut = [min(255, int(255 * (i / 255) ** (1 / gamma) + .5)) for i in range(256)] * (1 if img.mode == 'L' else 3)
        img = img.point(lut); applied['gamma'] = round(gamma, 2)
    sharpen = float(opts.get('sharpen') or 0)
    if sharpen > 0:
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=int(min(sharpen, 3) * 100), threshold=2)); applied['sharpen'] = round(min(sharpen, 3), 2)
    if opts.get('invert'):
        img = ImageOps.invert(img); applied['invert'] = True
    return img


def _num(opts, key, lo, hi, default):
    try:
        v = float(opts.get(key, default))
    except (TypeError, ValueError):
        return default
    return min(max(v, lo), hi)


def _studio(img, opts, st, applied):
    """Studio path: float tone curve in the same order as imaging-studio.js, then optional colour, relief and edges.
    A colour photo kept in colour has the tone steps applied to its brightness only."""
    from . import imaging_studio as S
    chroma = None
    if img.mode == 'L':
        g = np.asarray(img, dtype=np.float32) / 255
    else:
        y, cb, cr = img.convert('YCbCr').split()
        g, chroma = np.asarray(y, dtype=np.float32) / 255, (cb, cr)
    g = S.early_steps(g, st, applied)
    if opts.get('level'):
        g = S.level(g); applied['level'] = True
    g = S.late_steps(g, {**st, 'detail': 0}, applied)            # glare before CLAHE so the light box is not equalised
    strength = _num(opts, 'enhance', 0, 4, 0)
    if strength > 0:
        g = clahe((g * 255 + .5).astype(np.uint8), clip=1 + strength).astype(np.float32) / 255; applied['enhance'] = round(strength, 2)
    gm = _num(opts, 'gamma', .3, 3, 1)
    if abs(gm - 1) > .02:
        g = S.gamma(g, gm); applied['gamma'] = round(gm, 2)
    g = S.late_steps(g, {**st, 'glare': 0}, applied)             # anatomical detail
    sh = _num(opts, 'sharpen', 0, 3, 0)
    if sh > 0:
        g = S.unsharp(g, .0015, sh * .8); applied['sharpen'] = round(sh, 2)
    if opts.get('invert'):
        g = 1 - g; applied['invert'] = True
    rgb = S.colour_steps(g, st, applied)
    if rgb is not None:
        return Image.fromarray(np.clip(rgb * 255 + .5, 0, 255).astype(np.uint8), 'RGB')
    out = Image.fromarray(np.clip(g * 255 + .5, 0, 255).astype(np.uint8), 'L')
    if chroma:
        out = Image.merge('YCbCr', (out, *chroma)).convert('RGB')
    return out


def describe(applied):
    """Short human description of the steps, e.g. for the caption."""
    from .imaging_studio import PALETTES
    names = [('corners', 'straightened'), ('rotate', 'rotated'), ('flip', 'flipped'), ('denoise', 'denoised'), ('smooth', 'smoothed'),
             ('level', 'levelled'), ('glare', 'glare removed'), ('enhance', 'contrast enhanced'), ('gamma', 'gamma'), ('detail', 'detail'),
             ('sharpen', 'sharpened'), ('invert', 'inverted'), ('relief', 'relief'), ('edges', 'edges outlined')]
    words = [n for k, n in names if k in applied]
    if applied.get('colour') in PALETTES:
        words.append(PALETTES[applied['colour']]['label'].lower().replace('(illustrative)', 'colour (illustrative)'))
    return ', '.join(words) or 'greyscale copy'
