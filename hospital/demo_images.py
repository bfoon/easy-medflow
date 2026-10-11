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


def mri_brain(lesion=None, seed=11):
    """Axial T2-style slice. lesion: None, 'infarct' (bright wedge) or 'meningitis' (bright meninges)."""
    random.seed(seed); w, h = 560, 560
    img = Image.new('L', (w, h), 0); d = ImageDraw.Draw(img)
    d.ellipse([80, 60, 480, 500], fill=40)                      # skull (dark on T2)
    d.ellipse([96, 76, 464, 484], fill=150 if lesion == 'meningitis' else 110)   # CSF / meninges
    d.ellipse([106, 86, 454, 474], fill=95)                     # cortex
    d.ellipse([150, 130, 410, 430], fill=70)                    # white matter
    for x0 in (170, 290):                                       # gyri
        for i in range(6):
            d.arc([x0, 130 + i * 48, x0 + 100, 180 + i * 48], 0, 360, fill=100, width=4)
    d.ellipse([238, 220, 268, 300], fill=235); d.ellipse([292, 220, 322, 300], fill=235)   # ventricles (bright fluid)
    if lesion == 'infarct':
        d.pieslice([120, 140, 300, 400], 150, 220, fill=210)    # bright wedge in the left MCA territory
    img = Image.blend(img.filter(ImageFilter.GaussianBlur(2)), Image.effect_noise((w, h), 25).convert('L'), .08).convert('RGB')
    d = ImageDraw.Draw(img); d.text((14, 14), 'MRI · axial T2', fill=(220, 220, 220)); _stamp(d, w, h); return _png(img)


def eeg_strip(spikes=True):
    w, h = 900, 380
    img = Image.new('RGB', (w, h), (255, 255, 255)); d = ImageDraw.Draw(img)
    for x in range(0, w, 45): d.line([x, 0, x, h], fill=(230, 236, 240))
    leads = ['Fp1-F3', 'F3-C3', 'C3-P3', 'P3-O1', 'Fp2-F4', 'F4-C4', 'C4-P4', 'P4-O2']
    for li, name in enumerate(leads):
        base = 30 + li * 42; pts = []
        for x in range(80, w):
            v = math.sin(x * .18 + li) * 4 + math.sin(x * .05 + li * 2) * 3
            if spikes and 420 < x < 600 and (x - 420) % 30 < 6:           # generalised 3 Hz spike-wave
                v += -16 if (x - 420) % 30 < 3 else 10
            pts.append((x, base + v))
        d.line(pts, fill=(30, 30, 60), width=1); d.text((6, base - 6), name, fill=(90, 90, 110))
    d.text((80, h - 40), '10 s/page · 7 µV/mm', fill=(90, 90, 110)); _stamp(d, w, h); return _png(img)


def xray_spine(view='lumbar', compression=None, seed=41):
    """Lateral spine radiograph. view: 'lumbar' or 'cervical'; compression: index of a wedge-compressed vertebra."""
    random.seed(seed); w, h = 480, 680
    img = Image.new('L', (w, h), 12); d = ImageDraw.Draw(img)
    d.rounded_rectangle([80, 0, 400, 680], 60, fill=58)                              # soft tissue
    n = 7 if view == 'cervical' else 5
    top, step = 40, (600 if view == 'cervical' else 560) // n
    for i in range(n):
        y = top + i * step + random.randint(-2, 2)
        x = 190 + (i * 10 if view == 'lumbar' else -abs(i - 3) * 6)                  # lordotic curve
        bh = step - 22
        if compression is not None and i == compression:                              # anterior wedge: front shorter than back
            d.polygon([(x, y + bh * .45), (x + 100, y), (x + 100, y + bh), (x, y + bh)], fill=200)
            d.line([(x, y + bh * .45), (x + 100, y)], fill=235, width=3)
        else:
            d.rounded_rectangle([x, y, x + 100, y + bh], 10, fill=185)
        d.rounded_rectangle([x + 104, y + 6, x + 150, y + bh - 6], 8, fill=150)       # posterior elements
        if i < n - 1:
            d.rectangle([x + 6, y + bh + 3, x + 94, y + step - 3], fill=70)            # disc space
    img = Image.blend(img.filter(ImageFilter.GaussianBlur(2.2)), Image.effect_noise((w, h), 12).convert('L'), .07).convert('RGB')
    d = ImageDraw.Draw(img); d.text((14, 14), f'{"C-spine" if view == "cervical" else "L-spine"} · lateral', fill=(230, 230, 230)); _stamp(d, w, h); return _png(img)


def xray_long_bone(bone='femur', fracture=True, healing=False, seed=43):
    """AP radiograph of a long bone. fracture: displaced transverse/oblique break; healing: callus around the line."""
    random.seed(seed); w, h = 420, 720
    img = Image.new('L', (w, h), 10); d = ImageDraw.Draw(img)
    width = {'femur': 70, 'tibia': 56, 'humerus': 52, 'radius': 30}.get(bone, 50)
    d.rounded_rectangle([210 - width * 1.9, 0, 210 + width * 1.9, 720], 80, fill=62)     # soft tissue
    if bone == 'humerus':                                                                   # child's elbow: humerus above, forearm below
        d.rounded_rectangle([210 - width / 2, 0, 210 + width / 2, 380], 18, fill=185)
        d.ellipse([150, 360, 270, 430], fill=190)
        d.rounded_rectangle([160, 440, 196, 720], 12, fill=175); d.rounded_rectangle([222, 440, 256, 720], 12, fill=175)
        if fracture:
            d.line([(150, 330), (270, 300)], fill=30, width=5)                              # supracondylar line
            d.polygon([(150, 334), (270, 304), (276, 330), (156, 362)], fill=160)
    else:
        if fracture and not healing:
            d.rounded_rectangle([210 - width / 2, 0, 210 + width / 2, 352], 16, fill=190)
            d.rounded_rectangle([210 - width / 2 + 24, 362, 210 + width / 2 + 24, 720], 16, fill=190)   # displaced distal fragment
            d.line([(210 - width / 2, 352), (210 + width / 2, 340)], fill=235, width=2)
            for _ in range(6):                                                              # small fragments
                x, y = random.randint(170, 260), random.randint(340, 372); d.ellipse([x, y, x + 7, y + 5], fill=215)
        else:
            d.rounded_rectangle([210 - width / 2, 0, 210 + width / 2, 720], 16, fill=190)
            if healing:
                d.ellipse([210 - width, 320, 210 + width, 400], fill=150)                   # callus
                d.rounded_rectangle([210 - width / 2, 0, 210 + width / 2, 720], 16, fill=195)
                d.line([(210 - width / 2, 360), (210 + width / 2, 356)], fill=160, width=2)
        d.rectangle([210 - width / 2 + 10, 0, 210 + width / 2 - 10, 720], fill=None)
        d.line([(210 - width / 2 + 12, 0), (210 - width / 2 + 12, 720)], fill=120, width=3)   # medullary canal hint
    img = Image.blend(img.filter(ImageFilter.GaussianBlur(1.8)), Image.effect_noise((w, h), 12).convert('L'), .06).convert('RGB')
    d = ImageDraw.Draw(img); d.text((14, 14), f'{bone.capitalize()} · AP', fill=(230, 230, 230)); _stamp(d, w, h); return _png(img)


def mri_spine(finding='disc', seed=45):
    """Sagittal T2 lumbar/thoracic spine MRI. finding: 'disc' (herniation), 'cord' (cord injury) or None."""
    random.seed(seed); w, h = 440, 680
    img = Image.new('L', (w, h), 18); d = ImageDraw.Draw(img)
    d.rectangle([60, 0, 380, 680], fill=60)
    d.rounded_rectangle([238, 0, 286, 680], 14, fill=225)                                 # CSF (bright on T2)
    d.rounded_rectangle([250, 0, 274, 520], 10, fill=120)                                 # spinal cord
    for i in range(7):
        y = 30 + i * 92
        d.rounded_rectangle([110, y, 220, y + 70], 10, fill=95)                          # vertebral bodies
        d.ellipse([112, y + 72, 218, y + 90], fill=165 if not (finding == 'disc' and i == 5) else 120)   # discs
    if finding == 'disc':
        d.ellipse([200, 30 + 5 * 92 + 64, 262, 30 + 5 * 92 + 98], fill=105)              # herniated disc pressing on the sac
    if finding == 'cord':
        d.ellipse([244, 300, 280, 360], fill=235)                                         # bright cord signal (oedema)
        d.polygon([(110, 300), (220, 290), (220, 362), (110, 350)], fill=140)             # injured vertebra
    img = Image.blend(img.filter(ImageFilter.GaussianBlur(1.6)), Image.effect_noise((w, h), 20).convert('L'), .08).convert('RGB')
    d = ImageDraw.Draw(img); d.text((14, 14), 'MRI · sagittal T2', fill=(220, 220, 220)); _stamp(d, w, h); return _png(img)


def xray_hand(kind='ra', seed=51):
    """PA hand radiograph. kind: 'ra' (periarticular erosions, narrowed joints), 'fracture' (5th metacarpal neck) or 'normal'."""
    random.seed(seed); w, h = 460, 620
    img = Image.new('L', (w, h), 10); d = ImageDraw.Draw(img)
    d.polygon([(120, 620), (110, 420), (60, 300), (90, 270), (150, 360), (160, 120), (200, 110), (210, 300), (230, 80), (270, 80), (270, 300), (300, 110), (340, 120), (320, 320),
               (370, 180), (410, 200), (350, 420), (330, 620)], fill=55)                       # soft tissue
    for i in range(8):
        x, y = 170 + (i % 4) * 34, 470 + (i // 4) * 34; d.ellipse([x, y, x + 30, y + 28], fill=180)          # carpals
    rays = [(110, 440, 70, 300, 2), (185, 450, 175, 260, 3), (235, 450, 245, 240, 3), (280, 450, 295, 250, 3), (320, 455, 345, 285, 3)]
    for k, (x0, y0, x1, y1, nph) in enumerate(rays):
        d.line([(x0, y0), (x1, y1)], fill=190, width=18)                                          # metacarpal
        if kind == 'fracture' and k == 4:
            mx, my = x0 + (x1 - x0) * .78, y0 + (y1 - y0) * .78
            d.line([(mx - 12, my - 4), (mx + 12, my + 6)], fill=25, width=4)                      # neck fracture line
        px, py = x1, y1
        for j in range(nph):
            nx, ny = px + (x1 - x0) * .18, py - 62 + j * 8
            gap = 3 if kind != 'ra' else 1
            d.ellipse([px - 11, py - 11, px + 11, py + 11], fill=40 if kind == 'ra' and j == 0 else 60)   # joint space (narrow in RA)
            d.line([(px, py - gap - 8), (nx, ny)], fill=185, width=14 - j * 2)
            if kind == 'ra' and j < 2:
                d.ellipse([px + 4, py - 6, px + 11, py + 1], fill=55)                             # marginal erosion
            px, py = nx, ny
    img = Image.blend(img.filter(ImageFilter.GaussianBlur(1.6)), Image.effect_noise((w, h), 12).convert('L'), .06).convert('RGB')
    d = ImageDraw.Draw(img); d.text((14, 14), 'Hand · PA', fill=(230, 230, 230)); _stamp(d, w, h); return _png(img)


def xray_foot(kind='gout', seed=53):
    """Dorsoplantar foot / ankle radiograph. kind: 'gout' (1st MTP erosion and tophus), 'ankle' (bimalleolar fracture) or 'osteomyelitis'."""
    random.seed(seed); w, h = 460, 640
    img = Image.new('L', (w, h), 10); d = ImageDraw.Draw(img)
    d.polygon([(150, 640), (120, 440), (130, 160), (190, 60), (330, 70), (360, 200), (350, 440), (320, 640)], fill=55)
    d.rounded_rectangle([170, 470, 300, 640], 40, fill=175)                                      # talus/calcaneus region
    if kind == 'ankle':
        d.rectangle([150, 560, 190, 640], fill=180); d.rectangle([290, 560, 325, 640], fill=170)     # malleoli
        d.line([(150, 590), (190, 600)], fill=25, width=4); d.line([(290, 584), (326, 596)], fill=25, width=4)
    for i in range(5):
        x0, x1 = 190 + i * 26, 160 + i * 38
        fill = 190
        if kind == 'osteomyelitis' and i == 0:
            fill = 120
        d.line([(x0, 460), (x1, 210)], fill=fill, width=20 if i == 0 else 15)                   # metatarsals
        d.line([(x1, 200), (x1 - 4, 120 + i * 8)], fill=185, width=16 if i == 0 else 10)       # toes
    if kind == 'gout':
        d.ellipse([140, 192, 182, 228], fill=90)                                                # soft-tissue tophus
        d.ellipse([168, 200, 184, 214], fill=30)                                                # punched-out erosion
    if kind == 'osteomyelitis':
        for _ in range(14):
            x, y = random.randint(150, 182), random.randint(200, 260); d.ellipse([x, y, x + 6, y + 5], fill=45)   # bone destruction
    img = Image.blend(img.filter(ImageFilter.GaussianBlur(1.7)), Image.effect_noise((w, h), 12).convert('L'), .06).convert('RGB')
    d = ImageDraw.Draw(img); d.text((14, 14), 'Ankle · AP' if kind == 'ankle' else 'Foot · DP', fill=(230, 230, 230)); _stamp(d, w, h); return _png(img)


def ultrasound_obstetric(weeks=28, kind='normal', seed=61):
    """Obstetric ultrasound. kind: 'normal' (fetus sized by weeks; early = embryo in a sac) or 'ectopic' (empty uterus, adnexal mass)."""
    random.seed(seed); w, h = 640, 520
    sector = Image.new('L', (w, h), 0); ImageDraw.Draw(sector).pieslice([-140, -300, 780, 620], 55, 125, fill=255)
    tissue = Image.blend(Image.new('L', (w, h), 75), Image.effect_noise((w, h), 70).convert('L'), .45)
    img = Image.composite(tissue, Image.new('L', (w, h), 0), sector); d = ImageDraw.Draw(img)
    if kind == 'ectopic':
        d.ellipse([230, 170, 410, 300], fill=110)                                     # empty uterus with thickened lining
        d.ellipse([440, 220, 500, 270], fill=40); d.ellipse([458, 236, 482, 256], fill=160)   # adnexal ring
        d.ellipse([200, 330, 420, 380], fill=20)                                      # free fluid
    elif weeks < 11:
        d.ellipse([250, 170, 390, 290], fill=15)                                      # gestational sac (dark fluid)
        d.ellipse([300, 220, 340, 248], fill=170)                                     # embryo
        d.ellipse([340, 205, 352, 216], fill=200)                                     # yolk sac
    else:
        s = min(1.0, .45 + (weeks - 11) / 29 * .55)
        d.ellipse([170, 120, 470, 420], fill=12)                                      # amniotic fluid
        cx, cy = 300, 270
        d.ellipse([cx - 95 * s, cy - 110 * s, cx + 5 * s, cy - 10 * s], fill=175)     # fetal head
        d.ellipse([cx - 80 * s + 2, cy - 92 * s, cx - 10 * s, cy - 28 * s], fill=120) # brain
        d.ellipse([cx - 20 * s, cy - 40 * s, cx + 120 * s, cy + 80 * s], fill=160)    # body
        d.line([(cx + 60 * s, cy + 70 * s), (cx + 120 * s, cy + 120 * s)], fill=170, width=int(16 * s))   # leg
        d.line([(cx, cy - 20 * s), (cx - 30 * s, cy + 30 * s)], fill=170, width=int(12 * s))              # arm
        d.ellipse([cx + 30 * s, cy - 2 * s, cx + 48 * s, cy + 16 * s], fill=230)      # heart (bright)
        d.rectangle([420, 140, 470, 300], fill=140)                                   # placenta
    img = Image.composite(img.filter(ImageFilter.GaussianBlur(1.3)), Image.new('L', (w, h), 0), sector).convert('RGB')
    d = ImageDraw.Draw(img); d.text((14, 14), 'Ectopic: adnexa' if kind == 'ectopic' else f'Obstetric · {weeks} weeks', fill=(200, 200, 200)); _stamp(d, w, h); return _png(img)


def ultrasound_prostate(enlarged=True, seed=63):
    random.seed(seed); w, h = 640, 520
    sector = Image.new('L', (w, h), 0); ImageDraw.Draw(sector).pieslice([-140, -300, 780, 620], 55, 125, fill=255)
    tissue = Image.blend(Image.new('L', (w, h), 70), Image.effect_noise((w, h), 70).convert('L'), .45)
    img = Image.composite(tissue, Image.new('L', (w, h), 0), sector); d = ImageDraw.Draw(img)
    d.ellipse([230, 80, 410, 200], fill=12)                                           # bladder (urine is dark)
    r = 95 if enlarged else 60
    d.ellipse([320 - r, 230 - r * .7, 320 + r, 230 + r * .7], fill=120)               # prostate
    d.ellipse([320 - r * .55, 230 - r * .4, 320 + r * .55, 230 + r * .4], fill=95)    # transition zone
    img = Image.composite(img.filter(ImageFilter.GaussianBlur(1.3)), Image.new('L', (w, h), 0), sector).convert('RGB')
    d = ImageDraw.Draw(img); d.text((14, 14), 'Prostate · transabdominal', fill=(200, 200, 200)); _stamp(d, w, h); return _png(img)
