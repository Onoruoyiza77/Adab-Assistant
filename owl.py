"""The classroom, Professor Hoot (cartoon owl), his pointer, and captions."""
import math

from PIL import Image, ImageDraw

from board import BH, BW, BX, BY, H, W, WHITE, get_font, tw, wrap

OWL_CX, OWL_CY = 172, 462

BROWN = (140, 96, 62)
BROWN_D = (96, 62, 38)
WING = (112, 74, 46)
BELLY = (238, 210, 162)
ORANGE = (244, 166, 52)


# ---------- static classroom ----------
def make_base():
    img = Image.new("RGB", (W, H), (234, 224, 202))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 64):                      # faint wallpaper stripes
        d.rectangle((x, 0, x + 30, 606), fill=(229, 218, 195))
    d.rectangle((0, 606, W, H), fill=(146, 106, 74))      # floor
    for y in (640, 676):
        d.line((0, y, W, y), fill=(122, 86, 58), width=3)
    d.rectangle((0, 600, W, 608), fill=(112, 78, 52))     # skirting
    d.rounded_rectangle((328, 36, 1252, 594), radius=10, fill=(120, 80, 48))   # wood frame
    d.rounded_rectangle((336, 44, 1244, 586), radius=6, fill=(96, 62, 36))
    d.rectangle((BX - 2, BY - 2, BX + BW + 2, BY + BH + 2), fill=(70, 46, 28))
    d.rectangle((333, 575, 1247, 594), fill=(150, 104, 62))                      # chalk tray
    d.rectangle((333, 575, 1247, 580), fill=(170, 124, 80))
    d.rounded_rectangle((900, 566, 960, 578), radius=4, fill=(246, 246, 240))    # chalk
    d.rounded_rectangle((972, 568, 1010, 578), radius=4, fill=(255, 226, 110))
    d.rounded_rectangle((1040, 562, 1100, 578), radius=5, fill=(70, 70, 76))     # eraser
    d.rectangle((1040, 570, 1100, 578), fill=(230, 225, 210))
    return img


def scene_base(base, part, total):
    img = base.copy()
    d = ImageDraw.Draw(img)
    d.line((90, 30, 90, 66), fill=(90, 66, 46), width=3)
    d.line((250, 30, 250, 66), fill=(90, 66, 46), width=3)
    d.rounded_rectangle((40, 66, 300, 128), radius=10, fill=(176, 126, 78), outline=(110, 74, 44), width=4)
    f = get_font(30, True, "A")
    d.text((170, 97), f"PART {part} / {total}", font=f, fill=(255, 244, 214), anchor="mm")
    return img


# ---------- the owl ----------
def ellipse_poly(cx, cy, rx, ry, ang, n=28):
    pts = []
    ca, sa = math.cos(ang), math.sin(ang)
    for i in range(n):
        t = 2 * math.pi * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return pts


def draw_owl(frame, t, mouth, blink, look, tip, hop):
    """Draw Professor Hoot onto the frame. Returns the hand position (frame coords)."""
    S = 2
    lw, lh = 360, 430
    lx, ly = OWL_CX - 180, OWL_CY - 255
    layer = Image.new("RGBA", (lw * S, lh * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")

    def P(x, y):
        return (x * S, y * S)

    def E(x0, y0, x1, y1, **kw):
        d.ellipse([x0 * S, y0 * S, x1 * S, y1 * S], **kw)

    def PL(pts, **kw):
        d.polygon([P(x, y) for x, y in pts], **kw)

    ox, oy = OWL_CX - lx, OWL_CY - ly
    bob = 4 * math.sin(t * 2 * math.pi / 2.4) - 4 * mouth - hop
    cy = oy + bob

    # shadow + feet
    E(ox - 95, oy + 146, ox + 95, oy + 172, fill=(60, 40, 25, 70))
    for fx in (-42, 14):
        E(ox + fx, oy + 132, ox + fx + 34, oy + 158, fill=ORANGE, outline=(190, 120, 30), width=2 * S)
    # body + belly
    E(ox - 106, cy - 112, ox + 106, cy + 146, fill=BROWN, outline=BROWN_D, width=4 * S)
    E(ox - 70, cy - 6, ox + 70, cy + 136, fill=BELLY)
    for r in range(3):
        for k in range(4 - (r % 2)):
            x0 = ox - 48 + k * 26 + (13 if r % 2 else 0)
            d.arc([x0 * S, (cy + 22 + r * 30) * S, (x0 + 26) * S, (cy + 46 + r * 30) * S], 0, 180,
                  fill=(196, 156, 106), width=3 * S)
    # left wing (sways)
    sway = 0.12 + 0.07 * math.sin(t * 2.1) + 0.1 * mouth
    PL(ellipse_poly(ox - 104, cy + 36, 30, 80, sway), fill=WING, outline=BROWN_D)
    # head
    E(ox - 98, cy - 182, ox + 98, cy - 30, fill=BROWN, outline=BROWN_D, width=4 * S)
    PL([(ox - 92, cy - 138), (ox - 84, cy - 192), (ox - 44, cy - 166)], fill=BROWN)
    PL([(ox + 92, cy - 138), (ox + 84, cy - 192), (ox + 44, cy - 166)], fill=BROWN)
    # face discs, pupils, blink
    for sx in (-1, 1):
        ex, ey = ox + sx * 43, cy - 106
        E(ex - 41, ey - 41, ex + 41, ey + 41, fill=(252, 247, 235), outline=BROWN_D, width=3 * S)
        px, py = ex + look[0] * 9, ey + look[1] * 8
        if blink > 0.66:
            E(ex - 41, ey - 41, ex + 41, ey + 41, fill=(236, 226, 206), outline=BROWN_D, width=3 * S)
            d.arc([(ex - 20) * S, (ey - 6) * S, (ex + 20) * S, (ey + 14) * S], 200, 340,
                  fill=(40, 30, 30), width=4 * S)
        else:
            ry = 17 * (1 - 0.6 * blink)
            E(px - 17, py - ry, px + 17, py + ry, fill=(32, 26, 28))
            if blink < 0.3:
                E(px + 2, py - 12, px + 11, py - 3, fill=(255, 255, 255))
    # glasses
    for sx in (-1, 1):
        ex, ey = ox + sx * 43, cy - 106
        E(ex - 49, ey - 49, ex + 49, ey + 49, outline=(40, 40, 48), width=5 * S)
    d.line([P(ox - 8, cy - 112), P(ox + 8, cy - 112)], fill=(40, 40, 48), width=5 * S)
    d.line([P(ox - 90, cy - 114), P(ox - 100, cy - 124)], fill=(40, 40, 48), width=4 * S)
    d.line([P(ox + 90, cy - 114), P(ox + 100, cy - 124)], fill=(40, 40, 48), width=4 * S)
    # beak (opens with speech)
    gap = 15 * mouth
    PL([(ox - 17, cy - 80), (ox + 17, cy - 80), (ox, cy - 48)], fill=ORANGE, outline=(190, 120, 30))
    if mouth > 0.08:
        PL([(ox - 12, cy - 51), (ox + 12, cy - 51), (ox, cy - 49 + gap)], fill=(120, 30, 40))
    PL([(ox - 11, cy - 50 + gap * 0.6), (ox + 11, cy - 50 + gap * 0.6), (ox, cy - 36 + gap)],
       fill=(228, 148, 40), outline=(190, 120, 30))
    # bow tie
    PL([(ox - 30, cy - 34), (ox - 30, cy - 8), (ox, cy - 21)], fill=(200, 50, 60))
    PL([(ox + 30, cy - 34), (ox + 30, cy - 8), (ox, cy - 21)], fill=(200, 50, 60))
    E(ox - 7, cy - 28, ox + 7, cy - 14, fill=(150, 30, 42))
    # graduation cap
    PL([(ox - 50, cy - 176), (ox + 50, cy - 176), (ox + 42, cy - 150), (ox - 42, cy - 150)], fill=(52, 52, 64))
    PL([(ox - 92, cy - 184), (ox, cy - 218), (ox + 92, cy - 184), (ox, cy - 158)], fill=(34, 34, 44),
       outline=(20, 20, 28))
    d.line([P(ox + 74, cy - 187), P(ox + 86, cy - 150)], fill=(236, 190, 60), width=3 * S)
    E(ox + 80, cy - 154, ox + 92, cy - 140, fill=(236, 190, 60))
    # right wing = arm holding the pointer
    shx, shy = ox + 94, cy - 4
    tx, ty = tip[0] - lx, tip[1] - ly
    ang = max(-1.35, min(1.0, math.atan2(ty - shy, tx - shx)))
    hx, hy = shx + 96 * math.cos(ang), shy + 96 * math.sin(ang)
    d.line([P(shx, shy), P(hx, hy)], fill=BROWN_D, width=46 * S)
    E(shx - 23, shy - 23, shx + 23, shy + 23, fill=BROWN_D)
    E(hx - 23, hy - 23, hx + 23, hy + 23, fill=BROWN_D)
    d.line([P(shx, shy), P(hx, hy)], fill=WING, width=38 * S)
    E(shx - 19, shy - 19, shx + 19, shy + 19, fill=WING)
    E(hx - 19, hy - 19, hx + 19, hy + 19, fill=WING)

    small = layer.reduce(S)
    frame.paste(small, (lx, ly), small)
    return (hx + lx, hy + ly)


def draw_pointer(frame, hand, tip):
    """Teacher's stick from the owl's hand to the tip."""
    S = 2
    pad = 24
    x0, y0 = int(min(hand[0], tip[0]) - pad), int(min(hand[1], tip[1]) - pad)
    x1, y1 = int(max(hand[0], tip[0]) + pad), int(max(hand[1], tip[1]) + pad)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    if x1 <= x0 or y1 <= y0:
        return
    layer = Image.new("RGBA", ((x1 - x0) * S, (y1 - y0) * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")

    def P(p):
        return ((p[0] - x0) * S, (p[1] - y0) * S)

    ang = math.atan2(tip[1] - hand[1], tip[0] - hand[0])
    back = (hand[0] - 34 * math.cos(ang), hand[1] - 34 * math.sin(ang))
    d.line([P(back), P(tip)], fill=(120, 80, 44), width=8 * S)
    d.line([P(back), P(tip)], fill=(190, 140, 84), width=5 * S)
    r = 7 * S
    c = P(tip)
    d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=(220, 60, 60), outline=(150, 30, 30), width=S)
    g = P(hand)
    r = 17 * S
    d.ellipse([g[0] - r, g[1] - r, g[0] + r, g[1] + r], fill=(112, 74, 46), outline=(96, 62, 38), width=2 * S)
    small = layer.reduce(S)
    frame.paste(small, (x0, y0), small)


def blink_amount(t):
    ph = (t % 3.9)
    if 3.55 <= ph < 3.9:
        return 1 - abs((ph - 3.725) / 0.175)
    return 0.0


# ---------- captions ----------
_cap_cache = {}


def caption_image(text):
    if text in _cap_cache:
        return _cap_cache[text]
    for size in (28, 25, 22):
        lines = wrap(text, size, False, 1120)
        if len(lines) <= 2:
            break
    lines = lines[:2]
    f = get_font(size, False, text)
    h = len(lines) * (size + 8) + 20
    img = Image.new("RGBA", (1160, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle((0, 0, 1160, h), radius=16, fill=(22, 22, 30, 205))
    for i, ln in enumerate(lines):
        d.text((580, 12 + i * (size + 8)), ln, font=f, fill=(255, 255, 255), anchor="ma")
    _cap_cache[text] = img
    return img
