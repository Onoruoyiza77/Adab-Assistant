"""Chalkboard drawing: fonts, drawing helpers and board elements."""
import math
import os
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---- layout (video is 1280x720) ----
W, H = 1280, 720
BX, BY, BW, BH = 345, 55, 890, 520      # chalkboard inner area on the frame
CW = 840                                 # content width inside the board
TOP = 86                                 # where elements start (below heading)

BOARD = (36, 68, 56)
WHITE = (244, 244, 237)
YELLOW = (255, 226, 110)
PINK = (255, 160, 178)
BLUE = (138, 206, 255)
GREEN = (162, 232, 172)
ORANGE = (255, 180, 104)
PALETTE = [YELLOW, BLUE, PINK, GREEN, ORANGE]

# ---- fonts ----
DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEJAVU_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _find(query, fallback):
    """Locate a handwriting-style font (Comic Neue) if installed."""
    try:
        out = subprocess.check_output(
            ["fc-match", "-f", "%{family}|%{file}", query], text=True, timeout=10)
        fam, path = out.split("|", 1)
        if "comic" in fam.lower() and os.path.exists(path):
            return path
    except Exception:
        pass
    return fallback


HAND = _find("Comic Neue", DEJAVU)
HAND_B = _find("Comic Neue:bold", DEJAVU_B)
_fonts = {}


def get_font(size, bold=False, text="a"):
    """Handwriting font for plain text, DejaVu when symbols (arrows, subscripts) appear."""
    if text.isascii():
        path = HAND_B if bold else HAND
    else:
        path = DEJAVU_B if bold else DEJAVU
    key = (path, int(round(size)))
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype(path, key[1])
        except OSError:
            _fonts[key] = ImageFont.load_default()
    return _fonts[key]


def tw(text, size, bold=False):
    return get_font(size, bold, text).getlength(text)


def wrap(text, size, bold, maxw):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if tw(trial, size, bold) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


# ---- drawing wrapper (everything is drawn at 2x then shrunk, for smooth edges) ----
class G:
    def __init__(self, img=None, S=2):
        self.img, self.S = img, S
        self.dry = img is None
        self.d = None if self.dry else ImageDraw.Draw(img)

    def text(self, x, y, t, size, fill, bold=False, anchor="la"):
        if self.dry or not t:
            return
        self.d.text((x * self.S, y * self.S), t, font=get_font(size * self.S, bold, t),
                    fill=fill, anchor=anchor)

    def line(self, pts, fill, w=3):
        if self.dry:
            return
        self.d.line([(x * self.S, y * self.S) for x, y in pts], fill=fill,
                    width=max(1, int(w * self.S)), joint="curve")

    def rrect(self, box, r, outline=None, fill=None, w=3):
        if self.dry:
            return
        self.d.rounded_rectangle([v * self.S for v in box], radius=r * self.S,
                                 outline=outline, fill=fill, width=max(1, int(w * self.S)))

    def ellipse(self, box, outline=None, fill=None, w=3):
        if self.dry:
            return
        self.d.ellipse([v * self.S for v in box], outline=outline, fill=fill,
                       width=max(1, int(w * self.S)))

    def poly(self, pts, fill):
        if self.dry:
            return
        self.d.polygon([(x * self.S, y * self.S) for x, y in pts], fill=fill)

    def arrow(self, p0, p1, fill, w=3, head=13):
        self.line([p0, p1], fill, w)
        ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        a1, a2 = ang + 2.6, ang - 2.6
        self.poly([p1, (p1[0] + head * math.cos(a1), p1[1] + head * math.sin(a1)),
                   (p1[0] + head * math.cos(a2), p1[1] + head * math.sin(a2))], fill)


def clamp01(v):
    return max(0.0, min(1.0, v))


def reveal_lines(g, lines, x, y, lh, size, fill, bold, p):
    """Write text like chalk: characters appear left to right. Returns pen position."""
    total = sum(len(s) for s in lines)
    n = int(math.ceil(p * total)) if p > 0 else 0
    ax, ay = x, y + size * 0.6
    for i, s in enumerate(lines):
        if n <= 0:
            break
        seg = s[:n]
        n -= len(s)
        g.text(x, y + i * lh, seg, size, fill, bold)
        ax, ay = x + tw(seg, size, bold), y + i * lh + size * 0.6
    return ax, ay


# =============== elements ===============
# each element: measure(el, w) -> height, draw(g, el, x, y, w, p, col) -> (anchor_x, anchor_y)

def m_bullet(el, w):
    el["_l"] = wrap(el["text"], 30, False, w - 46)
    return len(el["_l"]) * 38 + 14


def d_bullet(g, el, x, y, w, p, col):
    if p > 0:
        g.ellipse((x + 6, y + 13, x + 22, y + 29), fill=col)
    a = reveal_lines(g, el["_l"], x + 38, y + 3, 38, 30, WHITE, False, p)
    if el.get("hot") and p >= 1:
        h = len(el["_l"]) * 38 + 8
        g.rrect((x - 6, y - 4, x + w - 40, y + h), 12, outline=YELLOW, w=3)
        g.text(x + w - 30, y + h / 2 - 4, "\u2605", 30, YELLOW, anchor="lm")
    return a


def m_term(el, w):
    el["_l"] = wrap(el["meaning"], 27, False, w - 40)
    return 52 + len(el["_l"]) * 34 + 14


def d_term(g, el, x, y, w, p, col):
    bw = tw(el["term"], 32, True) + 44
    a = (x + 10, y + 24)
    if p > 0:
        g.rrect((x, y, x + bw, y + 48), 14, outline=col, w=3)
        a = reveal_lines(g, [el["term"]], x + 22, y + 5, 40, 32, col, True, clamp01(p / 0.35))
    if p > 0.35:
        a = reveal_lines(g, el["_l"], x + 14, y + 58, 34, 27, WHITE, False, clamp01((p - 0.35) / 0.65))
    return a


def m_equation(el, w):
    size = 38
    while tw(el["text"], size, True) > w - 60 and size > 22:
        size -= 2
    el["_s"] = size
    return 88


def d_equation(g, el, x, y, w, p, col):
    size = el["_s"]
    full = tw(el["text"], size, True)
    x0 = x + (w - full) / 2
    if p > 0:
        g.rrect((x + 20, y + 4, x + w - 20, y + 80), 18, outline=col, w=3)
    return reveal_lines(g, [el["text"]], x0, y + 20, size * 1.2, size, col, True, p)


def m_flow(el, w):
    n = len(el["nodes"])
    gap = 54
    bw = (w - (n - 1) * gap) / n
    el["_bw"], el["_gap"] = bw, gap
    el["_nl"] = [wrap(t, 24, True, bw - 22)[:3] for t in el["nodes"]]
    el["_nh"] = max(len(l) for l in el["_nl"]) * 29 + 24
    return el["_nh"] + 12


def d_flow(g, el, x, y, w, p, col):
    n = len(el["nodes"])
    bw, gap, nh = el["_bw"], el["_gap"], el["_nh"]
    anchor = (x + 10, y + nh / 2)
    for i in range(n):
        pi = clamp01(p * n - i)
        if pi <= 0:
            break
        nx = x + i * (bw + gap)
        c = PALETTE[i % len(PALETTE)]
        g.rrect((nx, y + 4, nx + bw, y + 4 + nh), 14, outline=c, w=3)
        lines = el["_nl"][i]
        a = reveal_lines(g, lines, nx + 11, y + 4 + 11, 29, 24, WHITE, True, clamp01(pi / 0.8))
        anchor = (nx + bw / 2, y + 4 + nh + 2) if pi >= 0.8 else a
        if i < n - 1 and pi >= 0.8:
            ap = clamp01((pi - 0.8) / 0.2)
            x0, x1 = nx + bw + 8, nx + bw + gap - 8
            g.arrow((x0, y + 4 + nh / 2), (x0 + (x1 - x0) * ap, y + 4 + nh / 2), WHITE, 3)
    return anchor


def _ring(el, w, y, rx, ry):
    cx, cy = el["_x"] + w / 2, y + 135
    n = len(el["nodes"])
    boxes = []
    for i, t in enumerate(el["nodes"]):
        ang = -math.pi / 2 + i * 2 * math.pi / n
        lines = wrap(t, 22, True, 190)[:2]
        bw = min(210, max(110, max(tw(s, 22, True) for s in lines) + 26))
        bh = len(lines) * 27 + 16
        boxes.append((cx + rx * math.cos(ang), cy + ry * math.sin(ang), bw, bh, lines, ang))
    return cx, cy, boxes


def m_cycle(el, w):
    return 272


def d_cycle(g, el, x, y, w, p, col):
    el["_x"] = x
    n = len(el["nodes"])
    cx, cy, boxes = _ring(el, w, y, min(330, w / 2 - 110), 100)
    anchor = (cx, y + 20)
    if el.get("center") and p > 0.05:
        for k, s in enumerate(wrap(el["center"], 24, True, 200)[:2]):
            g.text(cx, cy - 14 + k * 28, s, 24, PINK, True, anchor="ma")
    rx, ry = min(330, w / 2 - 110), 100
    for i, (bx, by, bw, bh, lines, ang) in enumerate(boxes):
        pi = clamp01(p * n - i)
        if pi <= 0:
            break
        c = PALETTE[i % len(PALETTE)]
        g.rrect((bx - bw / 2, by - bh / 2, bx + bw / 2, by + bh / 2), 12, outline=c, w=3)
        a = reveal_lines(g, lines, bx - bw / 2 + 12, by - bh / 2 + 7, 27, 22, WHITE, True, clamp01(pi / 0.7))
        anchor = (bx, by + bh / 2 + 2) if pi >= 0.7 else a
        # arc to the next node (the last one closes the cycle)
        if pi >= 0.7 and (i < n - 1 or p >= 1):
            ap = clamp01((pi - 0.7) / 0.3) if i < n - 1 else 1.0
            d0 = min(0.5, 1.25 / n * 0.5 + 0.12)
            a0 = ang + d0 * (2 * math.pi / n) * 0.9
            a1 = ang + (2 * math.pi / n) - d0 * (2 * math.pi / n) * 0.9
            steps = 14
            pts = []
            for s in range(int(steps * ap) + 1):
                aa = a0 + (a1 - a0) * s / steps
                pts.append((cx + rx * math.cos(aa), cy + ry * math.sin(aa)))
            if len(pts) >= 2:
                g.arrow(pts[-2] if len(pts) > 2 else pts[0], pts[-1], WHITE, 3, 12) if ap >= 1 else g.line(pts, WHITE, 3)
                if ap >= 1 and len(pts) > 2:
                    g.line(pts[:-1], WHITE, 3)
    return anchor


def m_hub(el, w):
    return 272


def d_hub(g, el, x, y, w, p, col):
    el["_x"] = x
    n = len(el["nodes"])
    rx = min(340, w / 2 - 110)
    cx, cy, boxes = _ring(el, w, y, rx, 104)
    ctext = el["center"]
    cwid = tw(ctext, 26, True) + 50
    anchor = (cx, cy)
    shown = [i for i in range(n) if clamp01(p * (n + 1) - 1 - i) > 0]
    for i in shown:
        bx, by = boxes[i][0], boxes[i][1]
        g.line([(cx, cy), (bx, by)], (200, 200, 190), 2)
    if p > 0:
        g.ellipse((cx - cwid / 2, cy - 34, cx + cwid / 2, cy + 34), outline=YELLOW, fill=BOARD, w=4)
        a = reveal_lines(g, [ctext], cx - tw(ctext, 26, True) / 2, cy - 18, 30, 26, YELLOW, True, clamp01(p * (n + 1)))
        anchor = a
    for i in shown:
        bx, by, bw, bh, lines, ang = boxes[i]
        pi = clamp01(p * (n + 1) - 1 - i)
        c = PALETTE[i % len(PALETTE)]
        g.rrect((bx - bw / 2, by - bh / 2, bx + bw / 2, by + bh / 2), 12, outline=c, fill=BOARD, w=3)
        a = reveal_lines(g, lines, bx - bw / 2 + 12, by - bh / 2 + 7, 27, 22, WHITE, True, clamp01(pi / 0.8))
        anchor = (bx, by + bh / 2 + 2) if pi >= 0.8 else a
    return anchor


def m_compare(el, w):
    cw = (w - 50) / 2 - 24
    el["_cw"] = cw
    el["_li"] = [wrap(t, 24, False, cw) for t in el["left"]]
    el["_ri"] = [wrap(t, 24, False, cw) for t in el["right"]]
    hl = sum(len(l) * 30 + 8 for l in el["_li"])
    hr = sum(len(l) * 30 + 8 for l in el["_ri"])
    return 54 + max(hl, hr) + 8


def d_compare(g, el, x, y, w, p, col):
    mid = x + w / 2
    cw = el["_cw"]
    anchor = (x + 10, y + 20)
    tp = clamp01(p / 0.15)
    if tp > 0:
        a = reveal_lines(g, [el["left_title"]], x + 14, y + 2, 36, 30, BLUE, True, tp)
        anchor = a
        g.line([(x + 10, y + 42), (x + 10 + (mid - x - 40) * tp, y + 42)], BLUE, 3)
        b = reveal_lines(g, [el["right_title"]], mid + 24, y + 2, 36, 30, PINK, True, tp)
        g.line([(mid + 20, y + 42), (mid + 20 + (x + w - mid - 30) * tp, y + 42)], PINK, 3)
        g.line([(mid, y + 4), (mid, y + el_height(el))], (190, 190, 180), 2)
    order = []
    for i in range(max(len(el["left"]), len(el["right"]))):
        if i < len(el["left"]):
            order.append(("l", i))
        if i < len(el["right"]):
            order.append(("r", i))
    ly, ry_ = y + 54, y + 54
    pos = {}
    for side, i in order:
        if side == "l":
            pos[(side, i)] = ly
            ly += len(el["_li"][i]) * 30 + 8
        else:
            pos[(side, i)] = ry_
            ry_ += len(el["_ri"][i]) * 30 + 8
    for k, (side, i) in enumerate(order):
        pk = clamp01((p - 0.15) / 0.85 * len(order) - k)
        if pk <= 0:
            break
        lines = el["_li"][i] if side == "l" else el["_ri"][i]
        px = (x + 14) if side == "l" else (mid + 24)
        c = BLUE if side == "l" else PINK
        g.ellipse((px, pos[(side, i)] + 9, px + 9, pos[(side, i)] + 18), fill=c)
        anchor = reveal_lines(g, lines, px + 18, pos[(side, i)], 30, 24, WHITE, False, pk)
    return anchor


def el_height(el):
    return el.get("_h", 200)


def m_table(el, w):
    n = len(el["columns"])
    cw = w / n
    el["_cw"] = cw
    el["_hl"] = [wrap(c, 24, True, cw - 18)[:2] for c in el["columns"]]
    el["_rl"] = [[wrap(c, 22, False, cw - 18)[:3] for c in row] for row in el["rows"]]
    hh = max(len(l) for l in el["_hl"]) * 30 + 14
    rh = [max(len(c) for c in row) * 27 + 12 for row in el["_rl"]]
    el["_hh"], el["_rh"] = hh, rh
    return hh + sum(rh) + 8


def d_table(g, el, x, y, w, p, col):
    n = len(el["columns"])
    cw = el["_cw"]
    anchor = (x + 10, y + 20)
    hp = clamp01(p / 0.2)
    if hp > 0:
        for i in range(n):
            anchor = reveal_lines(g, el["_hl"][i], x + i * cw + 10, y + 5, 30, 24, YELLOW, True, hp)
        g.line([(x, y + el["_hh"]), (x + w * hp, y + el["_hh"])], YELLOW, 3)
    rows = el["_rl"]
    yy = y + el["_hh"]
    for r, row in enumerate(rows):
        pr = clamp01((p - 0.2) / 0.8 * len(rows) - r)
        if pr <= 0:
            break
        for i in range(n):
            anchor = reveal_lines(g, row[i], x + i * cw + 10, yy + 6, 27, 22, WHITE, False, pr)
        yy += el["_rh"][r]
        g.line([(x, yy), (x + w * min(1, pr * 2), yy)], (160, 170, 165), 2)
    top, bot = y, yy
    if hp > 0:
        for i in range(1, n):
            g.line([(x + i * cw, top + 2), (x + i * cw, bot)], (160, 170, 165), 2)
    return anchor


def _curve(kind, x):
    if kind == "sigmoid":
        f = lambda v: 1 / (1 + math.exp(-12 * (v - 0.5)))
        return (f(x) - f(0)) / (f(1) - f(0))
    if kind == "bell":
        return math.exp(-(((x - 0.5) / 0.19) ** 2))
    if kind == "decay":
        return (math.exp(-3.5 * x) - math.exp(-3.5)) / (1 - math.exp(-3.5))
    if kind == "linear":
        return x
    k = 0.18  # saturation
    return (1 + k) * x / (k + x)


def m_curve(el, w):
    return 252


def d_curve(g, el, x, y, w, p, col):
    pw, ph = 430, 176
    px, py = x + (w - pw) / 2, y + 36
    ap = clamp01(p / 0.25)
    anchor = (px, py)
    if ap > 0:
        g.arrow((px, py + ph), (px, py + ph - (ph + 14) * ap), WHITE, 3)
        g.arrow((px, py + ph), (px + (pw + 16) * ap, py + ph), WHITE, 3)
        g.text(px + 8, py - 26, el["y_label"], 22, BLUE, True)
        g.text(px + pw, py + ph + 8, el["x_label"], 22, BLUE, True, anchor="ra")
        anchor = (px, py + ph)
    cp = clamp01((p - 0.25) / 0.75)
    if cp > 0:
        n = 60
        pts = []
        for i in range(int(n * cp) + 1):
            v = i / n
            pts.append((px + v * pw, py + ph - _curve(el["kind"], v) * ph * 0.96))
        if len(pts) >= 2:
            g.line(pts, YELLOW, 4)
        anchor = pts[-1]
        if cp >= 1 and el.get("note"):
            if el["kind"] == "bell":
                top = min(pts, key=lambda q: q[1])
                g.text(top[0], top[1] - 32, el["note"], 22, PINK, True, anchor="ma")
            else:
                g.text(pts[-1][0] - 6, pts[-1][1] - 34, el["note"], 22, PINK, True, anchor="ra")
    return anchor


MEASURE = {"bullet": m_bullet, "term": m_term, "equation": m_equation, "flow": m_flow,
           "cycle": m_cycle, "hub": m_hub, "compare": m_compare, "table": m_table,
           "curve": m_curve}
DRAW = {"bullet": d_bullet, "term": d_term, "equation": d_equation, "flow": d_flow,
        "cycle": d_cycle, "hub": d_hub, "compare": d_compare, "table": d_table,
        "curve": d_curve}


def reveal_seconds(el, speech_dur):
    """How long the writing/drawing animation of an element should take."""
    t = el["type"]
    if t == "bullet":
        nominal = 0.055 * len(el["text"])
    elif t == "term":
        nominal = 0.05 * (len(el["term"]) + len(el["meaning"]))
    elif t == "equation":
        nominal = 0.08 * len(el["text"]) + 0.6
    elif t in ("flow", "cycle", "hub"):
        nominal = 1.6 * len(el["nodes"])
    elif t == "compare":
        nominal = 1.6 * (len(el["left"]) + len(el["right"])) + 1
    elif t == "table":
        nominal = 1.8 * len(el["rows"]) + 1.5
    else:
        nominal = 5
    return max(1.0, min(nominal, 0.92 * speech_dur))


def plan_pages(elements):
    """Stack elements down the board; start a fresh page when one doesn't fit."""
    y, page = TOP, 0
    for el in elements:
        h = MEASURE[el["type"]](el, CW)
        el["_h"] = h
        if y + h > BH - 14 and y > TOP:
            page += 1
            y = TOP
        el["_x"], el["_y"], el["_w"], el["_page"] = 25, y, CW, page
        y += h + (8 if el["type"] == "bullet" else 16)
    for el in elements:
        el["_col"] = PALETTE[(elements.index(el)) % len(PALETTE)]
        el["_anchor"] = DRAW[el["type"]](G(None), el, el["_x"], el["_y"], CW, 1.0, el["_col"])
    return page + 1


# ---- the board surface ----
_bg2 = None


def board_bg2():
    """Clean chalkboard with faint chalk smudges (2x size). Cached."""
    global _bg2
    if _bg2 is None:
        img = Image.new("RGB", (BW * 2, BH * 2), BOARD)
        sm = Image.new("RGB", (BW * 2, BH * 2), (0, 0, 0))
        d = ImageDraw.Draw(sm)
        import random
        rnd = random.Random(7)
        for _ in range(14):
            x, y = rnd.randint(0, BW * 2), rnd.randint(0, BH * 2)
            r = rnd.randint(80, 260)
            d.ellipse((x - r, y - r // 2, x + r, y + r // 2), fill=(26, 26, 26))
        sm = sm.filter(ImageFilter.GaussianBlur(60))
        _bg2 = Image.blend(img, Image.composite(Image.new("RGB", img.size, (88, 118, 104)), img,
                                                sm.convert("L")), 0.55)
    return _bg2


def blank_board():
    return board_bg2().reduce(2)


def draw_heading(g, text, p):
    size = 44
    while tw(text, size, True) > BW - 70 and size > 26:
        size -= 2
    a = reveal_lines(g, [text], 25, 8, size * 1.2, size, YELLOW, True, p)
    if p >= 1:
        y = 8 + size * 1.2 + 4
        e = min(25 + tw(text, size, True), BW - 30)
        pts = [(25 + (e - 25) * i / 40, y + 2.5 * math.sin(i * 0.9)) for i in range(41)]
        g.line(pts, WHITE, 3)
    return a


def render_board(heading, hp, items, marker=True):
    """items: list of (element, progress).
    Returns (board image at 1x, y of the chalk arrow where the teacher points)."""
    layer = board_bg2().copy()
    g = G(layer, 2)
    my = 34
    if heading and hp > 0:
        my = draw_heading(g, heading, hp)[1]
    for el, p in items:
        my = DRAW[el["type"]](g, el, el["_x"], el["_y"], el["_w"], p, el["_col"])[1]
    my = max(22, min(BH - 22, my))
    if marker and (items or hp > 0):
        g.poly([(3, my - 9), (3, my + 9), (19, my)], YELLOW)
    return layer.reduce(2), my
