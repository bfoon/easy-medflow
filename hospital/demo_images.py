"""Synthetic, clearly labelled illustration images for the demo. They are drawn, not real scans."""
import io
import math
import random

from PIL import Image, ImageDraw, ImageFilter

LABEL = 'SYNTHETIC DEMO IMAGE - NOT A REAL SCAN'


def _png(img):
    buf = io.BytesIO(); img.save(buf, 'PNG', optimize=True); return buf.getvalue()


def _stamp(d, w, h):
    d.rectangle([0, h - 26, w, h], fill=(0, 0, 0))
    d.text((10, h - 20), LABEL, fill=(255, 210, 0))


def chest_xray(cardiomegaly=True, congestion=True, seed=1):
    random.seed(seed); w, h = 640, 720
    img = Image.new('L', (w, h), 8); d = ImageDraw.Draw(img)
    d.ellipse([60, 80, 580, 760], fill=70)                                    # soft tissue of the chest
    for side in (-1, 1):                                                      # lung fields (dark = air)
        cx = 320 + side * 135
        d.ellipse([cx - 120, 130, cx + 120, 600], fill=28)
    hw = 150 if cardiomegaly else 105                                         # heart shadow, wider when enlarged
    d.ellipse([320 - hw + 30, 330, 320 + hw + 30, 600], fill=150)
    d.rectangle([300, 60, 340, 700], fill=165)                                # spine
    for i in range(10):                                                       # ribs
        y = 150 + i * 44
        for side in (-1, 1):
            d.arc([320 + (side < 0) * -260 - 10, y - 60, 320 + (side > 0) * 260 + 10, y + 60], 200 if side < 0 else -20, 340 if side < 0 else 160, fill=140, width=9)
    d.line([120, 120, 300, 100], fill=170, width=12); d.line([340, 100, 520, 120], fill=170, width=12)  # clavicles
    if congestion:
        for _ in range(140):                                                  # hazy vessels near the hila
            x, y = random.gauss(320, 90), random.gauss(380, 60)
            d.line([x, y, x + random.uniform(-25, 25), y + random.uniform(-25, 25)], fill=95, width=2)
    img = img.filter(ImageFilter.GaussianBlur(3))
    noise = Image.effect_noise((w, h), 10).convert('L')
    img = Image.blend(img, noise, .08).convert('RGB'); d = ImageDraw.Draw(img)
    d.text((20, 20), 'R', fill=(230, 230, 230)); d.text((w - 40, 20), 'PA', fill=(230, 230, 230))
    _stamp(d, w, h); return _png(img)


def ecg_strip(st_elevation=True):
    w, h = 900, 300
    img = Image.new('RGB', (w, h), (255, 240, 240)); d = ImageDraw.Draw(img)
    for x in range(0, w, 10): d.line([x, 0, x, h], fill=(250, 200, 200) if x % 50 else (240, 150, 150))
    for y in range(0, h, 10): d.line([0, y, w, y], fill=(250, 200, 200) if y % 50 else (240, 150, 150))
    base, pts = 160, []
    for x in range(w):
        t = (x % 150) / 150
        g = lambda c, s, a: a * math.exp(-((t - c) / s) ** 2)
        v = g(.15, .03, 12) - g(.29, .01, 15) + g(.31, .012, 95) - g(.335, .012, 25) + g(.55, .06, 22)
        if st_elevation and .34 < t < .5: v += 22                             # raised ST segment
        pts.append((x, base - v))
    d.line(pts, fill=(20, 20, 20), width=2)
    d.text((10, 10), 'Lead V3   25 mm/s   10 mm/mV', fill=(60, 0, 0)); _stamp(d, w, h); return _png(img)


def echo(ef_low=True, seed=3):
    random.seed(seed); w, h = 640, 520
    img = Image.new('L', (w, h), 0); d = ImageDraw.Draw(img)
    d.pieslice([-140, -300, 780, 620], 55, 125, fill=35)                      # ultrasound sector
    noise = Image.effect_noise((w, h), 60).convert('L')
    mask = Image.new('L', (w, h), 0); ImageDraw.Draw(mask).pieslice([-140, -300, 780, 620], 55, 125, fill=255)
    img = Image.composite(Image.blend(img, noise, .35), img, mask); d = ImageDraw.Draw(img)
    r = 95 if ef_low else 70                                                  # dilated left ventricle when EF is low
    d.ellipse([320 - r, 230 - r * 1.3, 320 + r, 230 + r * 1.3], outline=210, width=14)
    d.ellipse([320 - r + 18, 230 - r * 1.3 + 18, 320 + r - 18, 230 + r * 1.3 - 18], fill=10)
    img = img.filter(ImageFilter.GaussianBlur(1.5)).convert('RGB'); d = ImageDraw.Draw(img)
    d.text((14, 14), 'Apical 4-chamber', fill=(200, 200, 200)); _stamp(d, w, h); return _png(img)


def knee_xray(seed=5):
    random.seed(seed); w, h = 480, 640
    img = Image.new('L', (w, h), 10); d = ImageDraw.Draw(img)
    d.rounded_rectangle([120, 0, 360, 640], 120, fill=60)
    d.rounded_rectangle([175, 0, 305, 300], 40, fill=185); d.ellipse([150, 250, 330, 340], fill=190)   # femur
    d.ellipse([160, 335, 320, 395], fill=185); d.rounded_rectangle([185, 360, 295, 640], 30, fill=180)  # tibia
    d.ellipse([210, 220, 290, 290], fill=200)                                                          # patella
    img = Image.blend(img.filter(ImageFilter.GaussianBlur(2.5)), Image.effect_noise((w, h), 10).convert('L'), .06).convert('RGB')
    d = ImageDraw.Draw(img); d.text((14, 14), 'L  AP', fill=(230, 230, 230)); _stamp(d, w, h); return _png(img)


def ct_head(seed=7):
    random.seed(seed); w, h = 560, 560
    img = Image.new('L', (w, h), 0); d = ImageDraw.Draw(img)
    d.ellipse([70, 50, 490, 510], fill=235)                     # skull
    d.ellipse([88, 68, 472, 492], fill=95)                      # brain
    for x0, x1 in ((150, 260), (300, 410)):                     # sulci
        for i in range(7):
            y = 120 + i * 45
            d.arc([x0, y, x1, y + 50], 0, 180, fill=70, width=3)
    d.ellipse([235, 210, 268, 300], fill=25); d.ellipse([292, 210, 325, 300], fill=25)   # ventricles
    d.line([280, 80, 280, 480], fill=80, width=2)               # midline
    img = Image.blend(img.filter(ImageFilter.GaussianBlur(1.6)), Image.effect_noise((w, h), 20).convert('L'), .07).convert('RGB')
    d = ImageDraw.Draw(img); d.text((14, 14), 'Axial · no contrast', fill=(220, 220, 220)); _stamp(d, w, h); return _png(img)


def ultrasound_abdomen(gallstones=True, seed=9):
    random.seed(seed); w, h = 640, 520
    img = Image.new('L', (w, h), 0)
    sector = Image.new('L', (w, h), 0); ImageDraw.Draw(sector).pieslice([-140, -300, 780, 620], 55, 125, fill=255)
    tissue = Image.blend(Image.new('L', (w, h), 70), Image.effect_noise((w, h), 70).convert('L'), .45)
    img = Image.composite(tissue, img, sector); d = ImageDraw.Draw(img)
    d.ellipse([230, 190, 420, 300], fill=12)                    # fluid-filled gallbladder (dark)
    if gallstones:
        for cx, cy in ((300, 282), (335, 288)):
            d.ellipse([cx - 13, cy - 13, cx + 13, cy + 13], fill=245)            # bright stones
            d.rectangle([cx - 11, cy + 13, cx + 11, h], fill=8)                  # acoustic shadow
    img = Image.composite(img.filter(ImageFilter.GaussianBlur(1.2)), Image.new('L', (w, h), 0), sector).convert('RGB')
    d = ImageDraw.Draw(img); d.text((14, 14), 'RUQ · gallbladder', fill=(200, 200, 200)); _stamp(d, w, h); return _png(img)
