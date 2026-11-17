#!/usr/bin/env python3
"""
Generates the "Steam Controller (2026)" themes for VSCView.

All artwork is drawn from scratch here (simple geometric shapes), so the generated PNGs are
original work under this repository's MIT license; no Valve artwork is used. The button layout
follows the physical controller.

Two styles share one layout:
  * graphite  - smooth, anti-aliased dark controller
  * vaporwave - chunky pixel art in a neon palette

Usage:  python tools/theme-gen/gen_steamcontroller2026.py
Requires Pillow (pip install pillow). Writes into VSCView/themes/steamcontroller2026/.
"""
import json
import math
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = os.path.join(ROOT, 'VSCView', 'themes', 'steamcontroller2026')

W, H = 1000, 760  # theme canvas

# ---------------------------------------------------------------- layout (theme pixels)
STICK_L, STICK_R = (368, 300), (632, 300)
STICK_WELL_R, STICK_CAP_R, STICK_TRAVEL = 66, 44, 20
FACE_C, FACE_D, FACE_R = (778, 242), 52, 25            # ABXY cluster centre, offset, button radius
DPAD_C = (222, 242)
STEAM_C, STEAM_R = (500, 236), 27
VIEW_C, MENU_C = (338, 172), (662, 172)
QAM_C = (500, 486)
PAD_L, PAD_R, PAD_SIZE, PAD_ROT = (326, 478), (674, 478), 184, 9.87   # pads tilt toward the centre
PAD_TRAVEL = 78
BACK = {  # back buttons (shown on the grips)
    'L4': (122, 566), 'L5': (148, 646),
    'R4': (878, 566), 'R5': (852, 646),
}
BUMPER_L, BUMPER_R = (232, 112), (768, 112)
TRIGGER_L, TRIGGER_R = (232, 52), (768, 52)
TRIGGER_W, TRIGGER_H = 168, 64


def body_outline():
    """Left-half control points of the controller silhouette (mirrored for the right)."""
    left = [(500, 106), (360, 108), (230, 116), (168, 132), (132, 160), (108, 214), (88, 300),
            (68, 400), (54, 500), (56, 590), (78, 660), (118, 708), (166, 728), (212, 716),
            (244, 680), (270, 636), (310, 610), (380, 600), (500, 598)]
    right = [(W - x, y) for (x, y) in reversed(left[1:-1])]
    pts = left + right
    for _ in range(5):  # Chaikin smoothing (closed)
        nxt = []
        for i in range(len(pts)):
            p, q = pts[i], pts[(i + 1) % len(pts)]
            nxt.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            nxt.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        pts = nxt
    return pts


def rrect_poly(cx, cy, w, h, r, rot_deg=0.0, steps=10):
    """Rounded rectangle as a polygon, rotated clockwise (screen coords) about its centre."""
    pts = []
    corners = [(w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180)]
    for (ox, oy, a0) in corners:
        for s in range(steps + 1):
            a = math.radians(a0 + 90 * s / steps)
            pts.append((ox + r * math.cos(a), oy + r * math.sin(a)))
    t = math.radians(rot_deg)
    c, s_ = math.cos(t), math.sin(t)
    return [(cx + x * c - y * s_, cy + x * s_ + y * c) for (x, y) in pts]


# ---------------------------------------------------------------- styles
class Style:
    def __init__(self, name, title, pixel, pal):
        self.name, self.title, self.pixel, self.p = name, title, pixel, pal
        # smooth: draw 4x then downsample. pixel: draw at 1/5 then upscale with nearest-neighbour.
        self.k = 0.2 if pixel else 4.0
        self.grid = 5 if pixel else 1


GRAPHITE = Style('graphite', 'Graphite', False, {
    'body': (40, 42, 48, 255), 'body_hi': (58, 61, 70, 255), 'edge': (88, 94, 106, 255),
    'well': (24, 25, 29, 255), 'inset': (31, 32, 37, 255), 'label': (150, 156, 168, 255),
    'accent': (54, 196, 255, 255), 'accent2': (120, 230, 255, 255), 'press_text': (10, 20, 30, 255),
    'cap': (70, 74, 84, 255), 'cap_hi': (98, 103, 116, 255), 'cap_press': (54, 196, 255, 255),
    'glow': (54, 196, 255, 150), 'trail': (54, 196, 255, 255), 'dot': (240, 250, 255, 255),
    'trigger': (52, 55, 62, 255), 'meter': (54, 196, 255, 255),
})
VAPOR = Style('vaporwave', 'Vaporwave Pixel', True, {
    # palette: pink #ff71ce, cyan #01cdfe, mint #05ffa1, yellow #fffb96, lavender #b967ff, dusk #2d1b4e, ink #1a1030
    'body': (45, 27, 78, 255), 'body_hi': (70, 42, 112, 255), 'edge': (185, 103, 255, 255),
    'well': (26, 16, 48, 255), 'inset': (36, 22, 64, 255), 'label': (185, 103, 255, 255),
    'accent': (255, 113, 206, 255), 'accent2': (1, 205, 254, 255), 'press_text': (26, 16, 48, 255),
    'cap': (1, 205, 254, 255), 'cap_hi': (255, 251, 150, 255), 'cap_press': (5, 255, 161, 255),
    'glow': (5, 255, 161, 200), 'trail': (1, 205, 254, 255), 'dot': (255, 251, 150, 255),
    'trigger': (70, 42, 112, 255), 'meter': (5, 255, 161, 255),
})


class Layer:
    """An RGBA image covering theme-space bbox (x0,y0,x1,y1), drawn at style scale."""

    def __init__(self, st, bbox):
        g = st.grid
        x0, y0, x1, y1 = bbox
        x0, y0 = math.floor(x0 / g) * g, math.floor(y0 / g) * g
        x1, y1 = math.ceil(x1 / g) * g, math.ceil(y1 / g) * g
        self.st, self.x0, self.y0, self.w, self.h = st, x0, y0, x1 - x0, y1 - y0
        self.img = Image.new('RGBA', (max(1, round(self.w * st.k)), max(1, round(self.h * st.k))), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def P(self, x, y):
        return ((x - self.x0) * self.st.k, (y - self.y0) * self.st.k)

    def poly(self, pts, fill=None, outline=None, width=1):
        q = [self.P(x, y) for (x, y) in pts]
        self.d.polygon(q, fill=fill)
        if outline:
            self.d.line(q + [q[0]], fill=outline, width=self.lw(width), joint='curve')

    def circle(self, c, r, fill=None, outline=None, width=1):
        x, y = self.P(*c)
        rr = r * self.st.k
        self.d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=fill, outline=outline, width=self.lw(width) if outline else 0)

    def rrect(self, c, w, h, r, fill=None, outline=None, width=1, rot=0.0):
        self.poly(rrect_poly(c[0], c[1], w, h, r, rot), fill, outline, width)

    def lw(self, w):
        return max(1, round(w * self.st.k))

    def text(self, c, s, fill, size):
        if self.st.pixel:
            pixel_text(self, c, s, fill)
            return
        font = load_font(size * self.st.k)
        x, y = self.P(*c)
        self.d.text((x, y), s, fill=fill, font=font, anchor='mm')

    def finish(self):
        if self.st.pixel:
            return self.img.resize((self.w, self.h), Image.NEAREST)
        return self.img.resize((self.w, self.h), Image.LANCZOS)


_fonts = {}


def load_font(px):
    px = max(6, int(px))
    if px not in _fonts:
        for name in ('arialbd.ttf', 'DejaVuSans-Bold.ttf', 'Arial Bold.ttf'):
            try:
                _fonts[px] = ImageFont.truetype(name, px)
                break
            except OSError:
                continue
        else:
            _fonts[px] = ImageFont.load_default()
    return _fonts[px]


# 3x5 pixel glyphs for the vaporwave style
GLYPHS = {
    'A': ['010', '101', '111', '101', '101'], 'B': ['110', '101', '110', '101', '110'],
    'X': ['101', '101', '010', '101', '101'], 'Y': ['101', '101', '010', '010', '010'],
    'L': ['100', '100', '100', '100', '111'], 'R': ['110', '101', '110', '101', '101'],
    '4': ['101', '101', '111', '001', '001'], '5': ['111', '100', '110', '001', '110'],
}


def pixel_text(layer, c, s, fill):
    # at k=0.2 one glyph pixel == one low-res pixel == 5 theme px
    cx, cy = layer.P(*c)
    width = len(s) * 4 - 1
    x0 = round(cx - width / 2)
    y0 = round(cy - 2.5)
    for i, ch in enumerate(s):
        for gy, row in enumerate(GLYPHS.get(ch, ['000'] * 5)):
            for gx, bit in enumerate(row):
                if bit == '1':
                    layer.d.point((x0 + i * 4 + gx, y0 + gy), fill=fill)


# ---------------------------------------------------------------- drawing
def face_positions():
    cx, cy = FACE_C
    return {'n': ('Y', (cx, cy - FACE_D)), 'e': ('B', (cx + FACE_D, cy)), 's': ('A', (cx, cy + FACE_D)), 'w': ('X', (cx - FACE_D, cy))}


DPAD_A, DPAD_B = 21, 54  # arm half-width, reach


def dpad_cross():
    cx, cy = DPAD_C
    a, b = DPAD_A, DPAD_B
    return [(cx - a, cy - b), (cx + a, cy - b), (cx + a, cy - a), (cx + b, cy - a), (cx + b, cy + a), (cx + a, cy + a),
            (cx + a, cy + b), (cx - a, cy + b), (cx - a, cy + a), (cx - b, cy + a), (cx - b, cy - a), (cx - a, cy - a)]


def dpad_arm(direction):
    cx, cy = DPAD_C
    a, b, m = DPAD_A, DPAD_B, 4
    if direction == 'n':
        return [(cx - a + m, cy - b + m), (cx + a - m, cy - b + m), (cx + a - m, cy - a), (cx - a + m, cy - a)]
    if direction == 's':
        return [(cx - a + m, cy + a), (cx + a - m, cy + a), (cx + a - m, cy + b - m), (cx - a + m, cy + b - m)]
    if direction == 'w':
        return [(cx - b + m, cy - a + m), (cx - a, cy - a + m), (cx - a, cy + a - m), (cx - b + m, cy + a - m)]
    return [(cx + a, cy - a + m), (cx + b - m, cy - a + m), (cx + b - m, cy + a - m), (cx + a, cy + a - m)]


def draw_base(st):
    p = st.p
    L = Layer(st, (0, 90, W, H))
    outline = body_outline()
    L.poly(outline, fill=p['body'], outline=p['edge'], width=3)
    if not st.pixel:
        # soft top highlight
        hi = Layer(st, (0, 90, W, H))
        hi.poly([(x, y - 6) for (x, y) in outline], fill=p['body_hi'])
        mask = Image.new('L', hi.img.size, 0)
        md = ImageDraw.Draw(mask)
        hh = hi.img.size[1]
        for yy in range(hh):
            t = yy / (hh * 0.55)
            md.line([(0, yy), (hi.img.size[0], yy)], fill=int(110 * max(0.0, 1 - t) ** 1.6))
        body_mask = Image.new('L', hi.img.size, 0)
        ImageDraw.Draw(body_mask).polygon([L.P(x, y) for (x, y) in outline], fill=255)
        from PIL import ImageChops
        mask = ImageChops.multiply(mask, body_mask)
        L.img.paste(hi.img, (0, 0), mask)
        L.d = ImageDraw.Draw(L.img)
        L.poly(outline, outline=p['edge'], width=3)

    # sticks
    for c in (STICK_L, STICK_R):
        L.circle(c, STICK_WELL_R, fill=p['well'], outline=p['edge'], width=2)
    # trackpads
    for c, rot in ((PAD_L, PAD_ROT), (PAD_R, -PAD_ROT)):
        L.rrect(c, PAD_SIZE, PAD_SIZE, 30, fill=p['inset'], outline=p['edge'], width=2, rot=rot)
        if not st.pixel:
            L.rrect(c, PAD_SIZE - 26, PAD_SIZE - 26, 22, outline=p['well'], width=1, rot=rot)
    # dpad
    cx, cy = DPAD_C
    L.circle(DPAD_C, 64, fill=p['well'])
    L.poly(dpad_cross(), fill=p['inset'], outline=p['edge'], width=2)
    if not st.pixel:
        L.circle(DPAD_C, 7, outline=p['well'], width=2)
    # face buttons
    L.circle(FACE_C, 88, fill=p['well'])
    for k, (lbl, c) in face_positions().items():
        L.circle(c, FACE_R, fill=p['inset'], outline=p['edge'], width=2)
        L.text(c, lbl, p['label'], 26)
    # steam / view / menu / qam
    L.circle(STEAM_C, STEAM_R, fill=p['inset'], outline=p['edge'], width=2)
    L.circle(STEAM_C, STEAM_R - 11, outline=p['label'], width=3)
    L.rrect(VIEW_C, 46, 26, 12, fill=p['inset'], outline=p['edge'], width=2)
    L.rrect(MENU_C, 46, 26, 12, fill=p['inset'], outline=p['edge'], width=2)
    draw_view_icon(L, VIEW_C, p['label'])
    draw_menu_icon(L, MENU_C, p['label'])
    L.rrect(QAM_C, 54, 26, 12, fill=p['inset'], outline=p['edge'], width=2)
    draw_qam_icon(L, QAM_C, p['label'])
    # back buttons (rear L4/L5/R4/R5)
    for name, c in BACK.items():
        L.rrect(c, 70, 34, 15, fill=p['inset'], outline=p['edge'], width=2)
        L.text(c, name, p['label'], 20)
    return L


def draw_view_icon(L, c, col):
    x, y = c
    L.rrect((x - 4, y - 3), 12, 9, 2, outline=col, width=2)
    L.rrect((x + 4, y + 3), 12, 9, 2, outline=col, width=2)


def draw_menu_icon(L, c, col):
    x, y = c
    for dy in (-6, 0, 6):
        L.poly([(x - 9, y + dy - 1.5), (x + 9, y + dy - 1.5), (x + 9, y + dy + 1.5), (x - 9, y + dy + 1.5)], fill=col)


def draw_qam_icon(L, c, col):
    x, y = c
    for dx in (-12, 0, 12):
        L.circle((x + dx, y), 3.5, fill=col)


def save(layer, st, name):
    img = layer.finish()
    path = os.path.join(OUT, st.name, name)
    img.save(path, optimize=True)
    return {'x': layer.x0 + layer.w / 2, 'y': layer.y0 + layer.h / 2, 'w': layer.w, 'h': layer.h, 'file': name}


def img_node(info, extra=None):
    n = {'type': 'image', 'image': info['file'], 'x': info['x'], 'y': info['y'],
         'width': info['w'], 'height': info['h'], 'center': True}
    if extra:
        n.update(extra)
    return n


def showhide(expr, *children):
    return {'type': 'showhide', 'input': expr, 'children': list(children)}


def build(st, gyro_free=True):
    os.makedirs(os.path.join(OUT, st.name), exist_ok=True)
    p = st.p
    interp = {'winform.interpolation': 'NearestNeighbor', 'winform.smoothing': 'None'} if st.pixel else {'winform.interpolation': 'HighQualityBicubic'}

    def rel(info, cx, cy):
        """image node positioned relative to (cx,cy)"""
        n = img_node(info, interp)
        n['x'], n['y'] = info['x'] - cx, info['y'] - cy
        return n

    nodes = []

    # --- grip sense halos (behind the body)
    for side, xs in (('l', (20, 300)), ('r', (W - 300, W - 20))):
        L = Layer(st, (xs[0], 380, xs[1], H))
        outline = body_outline()
        pts = [(x, y) for (x, y) in outline if (x < 290 if side == 'l' else x > W - 290) and y > 400]
        if st.pixel:
            L.poly(outline, fill=None, outline=p['glow'], width=10)
        else:
            L.poly(outline, fill=None, outline=p['glow'], width=26)
            L.img = L.img.filter(ImageFilter.GaussianBlur(10 * st.k))
        # fade the halo out toward the top and the middle so only the grip glows
        fade = Image.new('L', L.img.size, 0)
        fd = ImageDraw.Draw(fade)
        fw, fh = L.img.size
        for yy in range(fh):
            ty = min(1.0, max(0.0, (yy / fh - 0.15) / 0.35))
            for xx in range(0, fw, max(1, fw // 64)):
                gx = xx / fw if side == 'l' else 1 - xx / fw
                tx = min(1.0, max(0.0, (0.85 - gx) / 0.35))
                fd.line([(xx, yy), (xx + max(1, fw // 64), yy)], fill=int(255 * ty * tx))
        if st.pixel:
            fade = fade.point(lambda v: 255 if v > 110 else 0)
        a = L.img.getchannel('A')
        from PIL import ImageChops
        L.img.putalpha(ImageChops.multiply(a, fade))
        info = save(L, st, f'grip_sense_{side}.png')
        nodes.append(showhide(f'grip_sense:{side}', img_node(info, interp)))

    # --- triggers (pbar fill) and bumpers (above the body edge)
    for side, c in (('l', TRIGGER_L), ('r', TRIGGER_R)):
        bb = (c[0] - TRIGGER_W / 2 - 4, c[1] - TRIGGER_H / 2 - 4, c[0] + TRIGGER_W / 2 + 4, c[1] + TRIGGER_H / 2 + 4)
        L = Layer(st, bb)
        L.rrect(c, TRIGGER_W, TRIGGER_H, 20, fill=p['trigger'], outline=p['edge'], width=2)
        L.text(c, 'L' if side == 'l' else 'R', p['label'], 22) if not st.pixel else None
        base = save(L, st, f'trigger_{side}.png')
        F = Layer(st, bb)
        F.rrect(c, TRIGGER_W, TRIGGER_H, 20, fill=p['accent'], outline=p['accent2'], width=2)
        fill = save(F, st, f'trigger_{side}_fill.png')
        nodes.append(img_node(base, interp))
        n = {'type': 'pbar', 'image': fill['file'], 'x': fill['x'], 'y': fill['y'], 'width': fill['w'], 'height': fill['h'],
             'center': True, 'direction': 'up', 'input': f'triggers:{side}:analog'}
        n.update(interp)
        nodes.append(n)
    for side, c in (('l', BUMPER_L), ('r', BUMPER_R)):
        bb = (c[0] - 104, c[1] - 20, c[0] + 104, c[1] + 20)
        L = Layer(st, bb)
        L.rrect(c, 200, 30, 14, fill=p['trigger'], outline=p['edge'], width=2)
        nodes.append(img_node(save(L, st, f'bumper_{side}.png'), interp))
        L = Layer(st, bb)
        L.rrect(c, 200, 30, 14, fill=p['accent'], outline=p['accent2'], width=2)
        nodes.append(showhide(f'bumpers:{side}', img_node(save(L, st, f'bumper_{side}_on.png'), interp)))

    # --- body
    nodes.append(img_node(save(draw_base(st), st, 'base.png'), interp))

    # --- d-pad
    for d in 'nesw':
        pts = dpad_arm(d)
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        L = Layer(st, (min(xs) - 4, min(ys) - 4, max(xs) + 4, max(ys) + 4))
        L.poly(pts, fill=p['accent'])
        nodes.append(showhide(f'quad_left:{d}', img_node(save(L, st, f'dpad_{d}.png'), interp)))

    # --- face buttons
    for d, (lbl, c) in face_positions().items():
        L = Layer(st, (c[0] - FACE_R - 4, c[1] - FACE_R - 4, c[0] + FACE_R + 4, c[1] + FACE_R + 4))
        L.circle(c, FACE_R, fill=p['accent'], outline=p['accent2'], width=2)
        L.text(c, lbl, p['press_text'], 26)
        nodes.append(showhide(f'quad_right:{d}', img_node(save(L, st, f'face_{lbl.lower()}.png'), interp)))

    # --- small buttons
    def small(name, expr, c, w, h, r, icon):
        L = Layer(st, (c[0] - w / 2 - 4, c[1] - h / 2 - 4, c[0] + w / 2 + 4, c[1] + h / 2 + 4))
        if r is None:
            L.circle(c, w / 2, fill=p['accent'], outline=p['accent2'], width=2)
        else:
            L.rrect(c, w, h, r, fill=p['accent'], outline=p['accent2'], width=2)
        icon(L, c, p['press_text'])
        nodes.append(showhide(expr, img_node(save(L, st, name), interp)))

    small('steam_on.png', 'home', STEAM_C, STEAM_R * 2, STEAM_R * 2, None,
          lambda L, c, col: L.circle(c, STEAM_R - 11, outline=col, width=3))
    small('view_on.png', 'menu:l', VIEW_C, 46, 26, 12, draw_view_icon)
    small('menu_on.png', 'menu:r', MENU_C, 46, 26, 12, draw_menu_icon)
    small('qam_on.png', 'qam', QAM_C, 54, 26, 12, draw_qam_icon)

    # --- back buttons
    for name, c in BACK.items():
        L = Layer(st, (c[0] - 39, c[1] - 21, c[0] + 39, c[1] + 21))
        L.rrect(c, 70, 34, 15, fill=p['accent'], outline=p['accent2'], width=2)
        L.text(c, name, p['press_text'], 20)
        side = 'l' if name[0] == 'L' else 'r'
        key = 'grip' if name[1] == '4' else 'grip2'
        nodes.append(showhide(f'{key}:{side}', img_node(save(L, st, f'back_{name.lower()}.png'), interp)))

    # --- trackpads: click overlay, pressure meter, touch trail (in the pad's rotated frame)
    PL = Layer(st, (-PAD_SIZE / 2 - 4, -PAD_SIZE / 2 - 4, PAD_SIZE / 2 + 4, PAD_SIZE / 2 + 4))
    PL.rrect((0, 0), PAD_SIZE, PAD_SIZE, 30, fill=p['accent'][:3] + (90,), outline=p['accent2'], width=3)
    pad_click = save(PL, st, 'pad_click.png')
    ML = Layer(st, (-6, -70, 6, 70))
    ML.rrect((0, 0), 10, 140, 5, fill=p['meter'])
    meter = save(ML, st, 'pad_pressure.png')
    TL = Layer(st, (-18, -18, 18, 18))
    if st.pixel:
        TL.rrect((0, 0), 20, 20, 0, fill=p['trail'])
    else:
        TL.circle((0, 0), 12, fill=p['trail'])
        TL.img = TL.img.filter(ImageFilter.GaussianBlur(3 * st.k))
    trail = save(TL, st, 'pad_trail.png')
    DL = Layer(st, (-22, -22, 22, 22))
    if st.pixel:
        DL.rrect((0, 0), 30, 30, 0, fill=p['dot'], outline=p['accent'], width=5)
    else:
        DL.circle((0, 0), 16, fill=p['dot'], outline=p['accent'], width=3)
    dot = save(DL, st, 'pad_touch.png')

    for side, c, rot in (('left', PAD_L, PAD_ROT), ('right', PAD_R, -PAD_ROT)):
        meter_x = -PAD_SIZE / 2 - 14 if side == 'left' else PAD_SIZE / 2 + 14
        n_click = img_node(pad_click, interp); n_click['x'] = n_click['y'] = 0
        n_meter = {'type': 'pbar', 'image': meter['file'], 'x': meter_x, 'y': 0, 'width': meter['w'], 'height': meter['h'],
                   'center': True, 'direction': 'up', 'input': f'touch_{side}:0:pressure'}
        n_meter.update(interp)
        n_dot = img_node(dot, interp); n_dot['x'] = n_dot['y'] = 0
        nodes.append({
            'x': c[0], 'y': c[1], 'rot': rot,
            'children': [
                showhide(f'touch_{side}:click', n_click),
                showhide(f'touch_{side}:0:touch', n_meter),
                {'type': 'trailpad', 'image': trail['file'], 'x': 0, 'y': 0, 'width': trail['w'], 'height': trail['h'],
                 'input': f'touch_{side}:0:touch',
                 'inputX': f'touch_{side}:0:x * {PAD_TRAVEL}', 'inputY': f'touch_{side}:0:y * {PAD_TRAVEL}',
                 'length': 24,
                 'children': [showhide(f'touch_{side}:0:touch', n_dot)]},
            ]})

    # --- sticks: touch ring, cap (moves), click overlay
    for side, c in (('left', STICK_L), ('right', STICK_R)):
        s = 'l' if side == 'left' else 'r'
        RL = Layer(st, (c[0] - STICK_WELL_R - 6, c[1] - STICK_WELL_R - 6, c[0] + STICK_WELL_R + 6, c[1] + STICK_WELL_R + 6))
        RL.circle(c, STICK_WELL_R - 1, outline=p['accent2'], width=5)
        nodes.append(showhide(f'stick_touch:{s}', img_node(save(RL, st, f'stick_touch_{s}.png'), interp)))

        CL = Layer(st, (-STICK_CAP_R - 4, -STICK_CAP_R - 4, STICK_CAP_R + 4, STICK_CAP_R + 4))
        CL.circle((0, 0), STICK_CAP_R, fill=p['cap'], outline=p['edge'], width=2)
        CL.circle((0, 0), STICK_CAP_R - 12, fill=p['cap_hi'] if not st.pixel else None, outline=p['cap_hi'], width=2)
        cap = save(CL, st, 'stick_cap.png')
        PCL = Layer(st, (-STICK_CAP_R - 4, -STICK_CAP_R - 4, STICK_CAP_R + 4, STICK_CAP_R + 4))
        PCL.circle((0, 0), STICK_CAP_R, fill=p['cap_press'], outline=p['accent2'], width=3)
        cap_on = save(PCL, st, 'stick_cap_on.png')
        n_cap = img_node(cap, interp); n_cap['x'] = n_cap['y'] = 0
        n_on = img_node(cap_on, interp); n_on['x'] = n_on['y'] = 0
        nodes.append({'type': 'slider', 'x': c[0], 'y': c[1],
                      'inputX': f'stick_{side}:x * {STICK_TRAVEL}', 'inputY': f'stick_{side}:y * {STICK_TRAVEL}',
                      'children': [n_cap, showhide(f'stick_{side}:click', n_on)]})

    theme = {'name': 'Full', 'width': W, 'height': H, 'version': 1, 'children': nodes}
    with open(os.path.join(OUT, st.name, 'Full.json'), 'w', encoding='utf-8') as f:
        json.dump(theme, f, indent=2)
    with open(os.path.join(OUT, st.name, 'theme.json'), 'w', encoding='utf-8') as f:
        json.dump({'name': st.title, 'authors': [{'name': 'VSCView contributors'}]}, f, indent=2)

    # menu icon
    base = Image.open(os.path.join(OUT, st.name, 'base.png'))
    icon = base.crop((0, 0, base.width, base.height))
    icon.thumbnail((32, 32), Image.NEAREST if st.pixel else Image.LANCZOS)
    canvas = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    canvas.paste(icon, ((32 - icon.width) // 2, (32 - icon.height) // 2))
    canvas.save(os.path.join(OUT, st.name, 'icon.png'))
    return canvas


def main():
    os.makedirs(OUT, exist_ok=True)
    icon = None
    for st in (GRAPHITE, VAPOR):
        i = build(st)
        icon = icon or i
    icon.save(os.path.join(OUT, 'icon.png'))
    # controller-menu device icon (same footprint as icons/DEVICE_SC.png)
    base = Image.open(os.path.join(OUT, GRAPHITE.name, 'base.png'))
    dev = base.copy()
    dev.thumbnail((138, 96), Image.LANCZOS)
    canvas = Image.new('RGBA', (142, 100), (0, 0, 0, 0))
    canvas.paste(dev, ((142 - dev.width) // 2, (100 - dev.height) // 2))
    canvas.save(os.path.join(ROOT, 'VSCView', 'icons', 'DEVICE_SC2026.png'))
    with open(os.path.join(OUT, 'name.txt'), 'w', encoding='utf-8') as f:
        f.write('Valve Steam Controller (2026)')
    print('wrote', OUT)


if __name__ == '__main__':
    main()
