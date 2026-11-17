#!/usr/bin/env python3
"""
Generates Graphite and Vaporwave Pixel themes for the original (2015) Steam Controller.

Shares the drawing code and palettes of gen_steamcontroller2026.py. Like that script, the artwork is
drawn from scratch from simple shapes (no Valve artwork, no logos) and is covered by this repository's
license.

The silhouette follows the real controller seen from the front: one wide body with a gently curved top,
two big recessed circular trackpads in the upper corners, a large round centre button, small back/start
keys either side of it, a lighter centre panel holding the thumbstick (lower left) and the ABXY diamond
(lower right), and two handles that drop and flare outward around a broad arch.

Usage:  python tools/theme-gen/gen_steamcontroller2015.py
Writes VSCView/themes/steamcontroller/graphite and .../vaporwave, each with:
  Full.json     - everything, plus a gyro widget (basic3d1, mode "gyro") under the arch
  No Gyro.json  - the same layout without the gyro widget
"""
import glob
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageChops, ImageDraw, ImageFilter  # noqa: E402
import gen_steamcontroller2026 as g  # noqa: E402

OUT = os.path.join(g.ROOT, 'VSCView', 'themes', 'steamcontroller')
W, H = 1000, 760
DY = -24  # the whole layout was drawn 24px lower; lifted to fit the 1000x760 canvas


def up(p):
    return (p[0], p[1] + DY)


def ups(pts):
    return [up(q) for q in pts]

# extra 3x5 glyphs for the pixel style (local to this generator's process)
GLYPHS = dict(g.GLYPHS)
GLYPHS.update({'G': ['011', '100', '101', '101', '011'], 'T': ['111', '010', '010', '010', '010']})
g.GLYPHS = GLYPHS

# ---------------------------------------------------------------- layout (theme pixels)
# Body spans x 70..930 (860 px) and y 142..744; the face is ~1.45:1 like the real controller.
CX = W / 2
PAD_L, PAD_R = up((260, 329)), up((740, 329))  # multiples of 5 so pixel overlays sit on the grid
PAD_RAD, PAD_RIM, PAD_TRAVEL = 98, 112, 84      # touch surface radius, raised rim radius, trail travel
STEAM_C, STEAM_R = up((500, 306)), 33
VIEW_C, MENU_C = up((424, 324)), up((576, 324))
KEY_W, KEY_H = 48, 26
STICK = up((405, 464))
STICK_WELL_R, STICK_CAP_R, STICK_TRAVEL = 68, 46, 18
FACE_C, FACE_D, FACE_R = up((598, 458)), 49, 23
GRIP = {'l': up((58, 600)), 'r': up((W - 58, 600))}
GRIP_W, GRIP_H, GRIP_ROT = 52, 96, 4
TRIGGER = {'l': up((258, 92)), 'r': up((W - 258, 92))}
TRIGGER_W, TRIGGER_H, TRIGGER_ROT = 176, 70, -4
GYRO_C, GYRO_W, GYRO_H = up((500, 680)), 174, 120  # multiples of the mini pixel grid

LETTER = {  # ABXY letter colours per style
    'graphite': {'A': (96, 206, 112, 255), 'B': (232, 84, 84, 255), 'X': (74, 152, 240, 255), 'Y': (238, 206, 72, 255)},
    'vaporwave': {'A': (5, 255, 161, 255), 'B': (255, 113, 206, 255), 'X': (1, 205, 254, 255), 'Y': (255, 251, 150, 255)},
}
TONES = {  # extra body tones on top of the shared palettes
    'graphite': {'shell': (48, 51, 58, 255), 'face': (35, 37, 42, 255), 'plate': (52, 55, 63, 255),
                 'seam': (22, 23, 27, 255), 'rim': (64, 68, 77, 255), 'pad': (31, 32, 37, 255),
                 'emboss': (44, 46, 53, 255), 'button': (24, 25, 29, 255)},
    'vaporwave': {'shell': (70, 42, 112, 255), 'face': (45, 27, 78, 255), 'plate': (58, 35, 96, 255),
                  'seam': (26, 16, 48, 255), 'rim': (185, 103, 255, 255), 'pad': (36, 22, 64, 255),
                  'emboss': (70, 42, 112, 255), 'button': (26, 16, 48, 255)},
}


def chaikin(pts, n=5, closed=True):
    for _ in range(n):
        nxt = []
        m = len(pts) if closed else len(pts) - 1
        if not closed:
            nxt.append(pts[0])
        for i in range(m):
            p, q = pts[i], pts[(i + 1) % len(pts)]
            nxt.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            nxt.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        if not closed:
            nxt.append(pts[-1])
        pts = nxt
    return pts


def mirror(left):
    """left-half control points (centre top .. centre bottom) -> closed symmetric polygon"""
    return left + [(W - x, y) for (x, y) in reversed(left[1:-1])]


# left half, clockwise from the top centre: straight-ish top, rounded shoulder, side that widens to the
# handle, flared rounded handle end, inner handle edge rising to the broad arch.
BODY_LEFT = ups([(500, 166), (350, 167), (250, 170), (196, 176), (164, 192), (146, 222), (128, 278), (108, 350),
             (90, 432), (76, 512), (66, 590), (66, 650), (80, 704), (110, 744), (152, 766), (196, 768),
             (230, 752), (256, 722), (280, 680), (304, 636), (326, 600), (350, 580), (400, 572), (500, 570)])

# darker inner face: the shell shows as a lip along the top and a band down the outside of each handle
FACE_LEFT = ups([(500, 196), (350, 197), (240, 201), (190, 212), (166, 236), (152, 290), (144, 360), (142, 440),
             (152, 520), (174, 596), (206, 664), (240, 720), (256, 722), (280, 680), (304, 636), (326, 600),
             (350, 580), (400, 572), (500, 570)])

# lighter centre panel holding the steam button, stick and ABXY; its upper corners run under the pads
PLATE_LEFT = ups([(500, 252), (340, 252), (250, 262), (196, 330), (240, 410), (300, 488), (338, 536), (370, 552),
              (500, 554)])


def body_outline():
    return chaikin(mirror(BODY_LEFT))


def face_outline():
    return chaikin(mirror(FACE_LEFT), 4)


def plate_outline():
    return chaikin(mirror(PLATE_LEFT), 4)


BUMPER_LEFT = ups([(392, 150), (260, 150), (200, 154), (156, 168), (130, 196), (120, 232), (150, 236), (176, 212),
               (214, 196), (270, 190), (392, 190)])


def bumper_shape(side):
    pts = chaikin(BUMPER_LEFT, 3)
    return pts if side == 'l' else [(W - x, y) for (x, y) in pts]


def trigger_shape(side):
    c = TRIGGER[side]
    return g.rrect_poly(c[0], c[1], TRIGGER_W, TRIGGER_H, 26, TRIGGER_ROT if side == 'l' else -TRIGGER_ROT)


def grip_shape(side):
    cx, cy = GRIP[side]
    return g.rrect_poly(cx, cy, GRIP_W, GRIP_H, 22, -GRIP_ROT if side == 'l' else GRIP_ROT)


def face_positions():
    cx, cy = FACE_C
    return {'n': ('Y', (cx, cy - FACE_D)), 'e': ('B', (cx + FACE_D, cy)), 's': ('A', (cx, cy + FACE_D)), 'w': ('X', (cx - FACE_D, cy))}


def pad_wedge(c, d):
    """Quarter of the left trackpad (the 2015 controller reports left-pad clicks as a d-pad)."""
    cx, cy = c
    r0, r1 = 30, PAD_RAD - 6
    a0 = {'e': -45, 's': 45, 'w': 135, 'n': 225}[d]
    pts = []
    for i in range(13):
        a = math.radians(a0 + 90 * i / 12)
        pts.append((cx + r1 * math.cos(a), cy + r1 * math.sin(a)))
    for i in range(12, -1, -1):
        a = math.radians(a0 + 90 * i / 12)
        pts.append((cx + r0 * math.cos(a), cy + r0 * math.sin(a)))
    return pts


def cross_outline(c, arm, reach, r):
    """Rounded plus sign (the embossed d-pad marking on the left pad)."""
    cx, cy = c
    a, b = arm, reach
    pts = [(cx - a, cy - b), (cx + a, cy - b), (cx + a, cy - a), (cx + b, cy - a), (cx + b, cy + a), (cx + a, cy + a),
           (cx + a, cy + b), (cx - a, cy + b), (cx - a, cy + a), (cx - b, cy + a), (cx - b, cy - a), (cx - a, cy - a)]
    # round only the outer arm ends (keep the inner corners crisp)
    out = []
    for i, p in enumerate(pts):
        outer = i in (0, 1, 3, 4, 6, 7, 9, 10)
        if not outer:
            out.append(p)
            continue
        prv, nxt = pts[i - 1], pts[(i + 1) % len(pts)]
        d1 = (prv[0] - p[0], prv[1] - p[1]); l1 = math.hypot(*d1)
        d2 = (nxt[0] - p[0], nxt[1] - p[1]); l2 = math.hypot(*d2)
        p1 = (p[0] + d1[0] / l1 * r, p[1] + d1[1] / l1 * r)
        p2 = (p[0] + d2[0] / l2 * r, p[1] + d2[1] / l2 * r)
        for s in range(7):
            t = s / 6
            # quadratic bezier p1 -> p -> p2
            x = (1 - t) ** 2 * p1[0] + 2 * (1 - t) * t * p[0] + t * t * p2[0]
            y = (1 - t) ** 2 * p1[1] + 2 * (1 - t) * t * p[1] + t * t * p2[1]
            out.append((x, y))
    return out


def chevron(c, right, size=7):
    x, y = c
    s = 1 if right else -1
    return [(x - size * 0.5 * s, y - size), (x + size * 0.7 * s, y), (x - size * 0.5 * s, y + size)]


def draw_key(L, st, c, right, fill, outline, icon):
    """Small back/start key: a pill with a chevron. The pixel style places every pixel by hand
    (an 11x7 box with clipped corners and a 2x3 arrow) because the pill is only ~10 low-res px wide."""
    if not st.pixel:
        L.poly(g.rrect_poly(c[0], c[1], KEY_W, KEY_H, 13), fill=fill, outline=outline, width=2)
        L.poly(chevron(c, right), fill=icon)
        return
    cx, cy = L.P(*c)
    x0, y0 = math.floor(cx - 5.5), math.floor(cy - 3.5)  # floor: identical on any grid-aligned layer
    x1, y1 = x0 + 10, y0 + 6
    L.d.rectangle([x0 + 1, y0 + 1, x1 - 1, y1 - 1], fill=fill)
    L.d.line([(x0 + 1, y0), (x1 - 1, y0)], fill=outline)
    L.d.line([(x0 + 1, y1), (x1 - 1, y1)], fill=outline)
    L.d.line([(x0, y0 + 1), (x0, y1 - 1)], fill=outline)
    L.d.line([(x1, y0 + 1), (x1, y1 - 1)], fill=outline)
    xm, ym = x0 + 5, y0 + 3
    tip, back = (xm + 1, xm) if right else (xm - 1, xm)
    L.d.point((tip, ym), fill=icon)
    L.d.line([(back, ym - 1), (back, ym + 1)], fill=icon)


# ---------------------------------------------------------------- drawing helpers
class View:
    """Draws controller-space shapes onto a Layer through an optional uniform scale (for the gyro mini)."""

    def __init__(self, L, m=1.0, src=(0, 0), dst=(0, 0)):
        self.L, self.m, self.src, self.dst = L, m, src, dst

    def T(self, p):
        return (self.dst[0] + (p[0] - self.src[0]) * self.m, self.dst[1] + (p[1] - self.src[1]) * self.m)

    def w(self, width):
        return width * self.m if self.m < 1 else width

    def poly(self, pts, fill=None, outline=None, width=1):
        self.L.poly([self.T(p) for p in pts], fill=fill, outline=outline, width=self.w(width))

    def circle(self, c, r, fill=None, outline=None, width=1):
        self.L.circle(self.T(c), r * self.m, fill=fill, outline=outline, width=self.w(width))

    def line(self, pts, fill, width):
        q = [self.L.P(*self.T(p)) for p in pts]
        self.L.d.line(q, fill=fill, width=self.L.lw(self.w(width)), joint='curve')


def highlight(L, st, outline, strength=110, frac=0.55):
    """Soft vertical sheen on the upper part of a filled shape (smooth style only)."""
    p = st.p
    hi = g.Layer(st, (L.x0, L.y0, L.x0 + L.w, L.y0 + L.h))
    hi.poly([(x, y - 6) for (x, y) in outline], fill=p['body_hi'])
    mask = Image.new('L', hi.img.size, 0)
    md = ImageDraw.Draw(mask)
    hh = hi.img.size[1]
    for yy in range(hh):
        t = yy / (hh * frac)
        md.line([(0, yy), (hi.img.size[0], yy)], fill=int(strength * max(0.0, 1 - t) ** 1.6))
    body_mask = Image.new('L', hi.img.size, 0)
    ImageDraw.Draw(body_mask).polygon([L.P(x, y) for (x, y) in outline], fill=255)
    L.img.paste(hi.img, (0, 0), ImageChops.multiply(mask, body_mask))
    L.d = ImageDraw.Draw(L.img)


def draw_controller(V, st, mini=False):
    """The controller face. With mini=True only the shapes that still read at gyro-widget size."""
    p, t = st.p, TONES[st.name]
    outline = body_outline()
    V.poly(outline, fill=t['shell'] if st.pixel else p['body'])
    if not st.pixel and not mini:
        highlight(V.L, st, outline)
    V.poly(face_outline(), fill=t['face'])
    V.poly(plate_outline(), fill=t['plate'], outline=None if mini else t['seam'], width=2)
    V.poly(outline, outline=p['edge'], width=3 if not mini else 2)

    # trackpads: raised rim, recessed surface
    for c in (PAD_L, PAD_R):
        V.circle(c, PAD_RIM, fill=t['rim'] if not st.pixel else p['edge'])
        if not mini:
            V.circle(c, PAD_RIM, outline=p['edge'], width=2)
        V.circle(c, PAD_RAD + 4, fill=t['seam'])
        V.circle(c, PAD_RAD, fill=t['pad'])
        if not mini and not st.pixel:
            V.circle(c, PAD_RAD - 3, outline=p['well'], width=3)
    if not mini:
        V.poly(cross_outline(PAD_L, 17, 78, 13), outline=t['emboss'], width=3 if not st.pixel else 2)

    # stick
    V.circle(STICK, STICK_WELL_R, fill=p['well'], outline=None if mini else p['edge'], width=2)
    if mini:
        V.circle(STICK, STICK_CAP_R, fill=p['cap'])

    # ABXY
    for k, (lbl, c) in face_positions().items():
        if mini:
            V.circle(c, FACE_R + 2, fill=LETTER[st.name][lbl])
        else:
            V.circle(c, FACE_R, fill=t['button'], outline=p['edge'], width=2)
            V.L.text(c, lbl, LETTER[st.name][lbl], 24)

    # steam button (plain disc), back / start keys
    V.circle(STEAM_C, STEAM_R, fill=t['button'], outline=p['edge'] if not mini else None, width=2)
    if not mini:
        V.circle(STEAM_C, STEAM_R - 9, outline=t['plate'] if st.pixel else p['inset'], width=3 if not st.pixel else 2)
        for c, right in ((VIEW_C, False), (MENU_C, True)):
            draw_key(V.L, st, c, right, t['button'], p['edge'], p['label'])


def draw_base(st):
    p = st.p
    L = g.Layer(st, (0, 120, W, H))
    draw_controller(View(L), st)
    # grip buttons: labelled tabs on the outer edge of each handle
    for side in 'lr':
        L.poly(grip_shape(side), fill=TONES[st.name]['button'], outline=p['edge'], width=2)
        L.text(GRIP[side], 'LG' if side == 'l' else 'RG', p['label'], 18)
    return L


def save(layer, st, name):
    img = layer.finish()
    img.save(os.path.join(OUT, st.name, name), optimize=True)
    return {'x': layer.x0 + layer.w / 2, 'y': layer.y0 + layer.h / 2, 'w': layer.w, 'h': layer.h, 'file': name}


def bbox_of(pts, pad):
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


# ---------------------------------------------------------------- gyro widget
def mini_style(st):
    """Gyro mini uses a finer pixel grid than the body so the small silhouette stays legible."""
    if not st.pixel:
        return st
    m = g.Style(st.name, st.title, True, st.p)
    m.k, m.grid = 1 / 3, 3
    return m


def gyro_images(st):
    """Small front-view silhouette for the basic3d1 widget plus four edge-highlight overlays."""
    ms = mini_style(st)
    body = body_outline()
    xs, ys = [q[0] for q in body], [q[1] for q in body]
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    m = min((GYRO_W - 8) / bw, (GYRO_H - 8) / bh)
    src = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)
    bb = (-GYRO_W / 2, -GYRO_H / 2, GYRO_W / 2, GYRO_H / 2)

    L = g.Layer(ms, bb)
    draw_controller(View(L, m, src, (0, 0)), ms, mini=True)
    files = {'image': save(L, st, 'gyro.png')}

    # silhouette mask at layer resolution
    M = g.Layer(ms, bb)
    View(M, m, src, (0, 0)).poly(body, fill=(255, 255, 255, 255))
    mask = M.img.getchannel('A')
    sw, sh = mask.size
    col = st.p['accent2'] if st.pixel else st.p['accent']
    for d in 'lrud':
        grad = Image.new('L', (sw, sh), 0)
        gd = ImageDraw.Draw(grad)
        n = sw if d in 'lr' else sh
        for i in range(n):
            f = i / (n - 1)
            if d in 'rd':
                f = 1 - f
            a = max(0.0, 1 - f / 0.55) ** 1.5
            if st.pixel:  # three hard bands instead of a smooth fade
                a = 1.0 if a > 0.6 else 0.55 if a > 0.25 else 0.25 if a > 0.05 else 0.0
            v = int(220 * a)
            if d in 'lr':
                gd.line([(i, 0), (i, sh)], fill=v)
            else:
                gd.line([(0, i), (sw, i)], fill=v)
        S = g.Layer(ms, bb)
        S.img = Image.new('RGBA', (sw, sh), col[:3] + (0,))
        S.img.putalpha(ImageChops.multiply(grad, mask))
        files[d] = save(S, st, f'gyro_{d}.png')
    return files


# ---------------------------------------------------------------- theme
def build(st):
    d = os.path.join(OUT, st.name)
    os.makedirs(d, exist_ok=True)
    for f in glob.glob(os.path.join(d, '*.png')) + glob.glob(os.path.join(d, '*.json')):
        os.remove(f)
    p, t = st.p, TONES[st.name]
    interp = {'winform.interpolation': 'NearestNeighbor', 'winform.smoothing': 'None'} if st.pixel else {'winform.interpolation': 'HighQualityBicubic'}
    nodes = []

    # triggers (analog fill + full-pull outline) and bumpers, behind the body's top edge
    for side in 'lr':
        shape = trigger_shape(side)
        bb = bbox_of(shape, 8)
        L = g.Layer(st, bb)
        L.poly(shape, fill=p['trigger'], outline=p['edge'], width=2)
        L.text(TRIGGER[side], 'LT' if side == 'l' else 'RT', p['label'], 22)
        nodes.append(g.img_node(save(L, st, f'trigger_{side}.png'), interp))
        F = g.Layer(st, bb)
        F.poly(shape, fill=p['accent'])
        F.text(TRIGGER[side], 'LT' if side == 'l' else 'RT', p['press_text'], 22)
        fill = save(F, st, f'trigger_{side}_fill.png')
        n = {'type': 'pbar', 'image': fill['file'], 'x': fill['x'], 'y': fill['y'], 'width': fill['w'], 'height': fill['h'],
             'center': True, 'direction': 'up', 'input': f'triggers:{side}:analog'}
        n.update(interp)
        nodes.append(n)
        c = TRIGGER[side]
        S = g.Layer(st, bb)
        S.poly(g.rrect_poly(c[0], c[1], TRIGGER_W + 4, TRIGGER_H + 4, 28, TRIGGER_ROT if side == 'l' else -TRIGGER_ROT),
               outline=p['accent2'], width=5)
        nodes.append(g.showhide(f'triggers:{side}:stage2', g.img_node(save(S, st, f'trigger_{side}_click.png'), interp)))
    for side in 'lr':
        shape = bumper_shape(side)
        bb = bbox_of(shape, 6)
        L = g.Layer(st, bb)
        L.poly(shape, fill=p['trigger'], outline=p['edge'], width=2)
        nodes.append(g.img_node(save(L, st, f'bumper_{side}.png'), interp))
        L = g.Layer(st, bb)
        L.poly(shape, fill=p['accent'], outline=p['accent2'], width=2)
        nodes.append(g.showhide(f'bumpers:{side}', g.img_node(save(L, st, f'bumper_{side}_on.png'), interp)))

    nodes.append(g.img_node(save(draw_base(st), st, 'base.png'), interp))

    # grips
    for side in 'lr':
        pts = grip_shape(side)
        L = g.Layer(st, bbox_of(pts, 4))
        L.poly(pts, fill=p['accent'], outline=p['accent2'], width=2)
        L.text(GRIP[side], 'LG' if side == 'l' else 'RG', p['press_text'], 18)
        nodes.append(g.showhide(f'grip:{side}', g.img_node(save(L, st, f'grip_{side}_on.png'), interp)))

    # left pad d-pad wedges (left pad click direction)
    for dd in 'nesw':
        pts = pad_wedge(PAD_L, dd)
        L = g.Layer(st, bbox_of(pts, 2))
        L.poly(pts, fill=p['accent'][:3] + (150,))
        nodes.append(g.showhide(f'quad_left:{dd}', g.img_node(save(L, st, f'pad_dpad_{dd}.png'), interp)))

    # face buttons: lit in their own letter colour
    for dd, (lbl, c) in face_positions().items():
        L = g.Layer(st, (c[0] - FACE_R - 4, c[1] - FACE_R - 4, c[0] + FACE_R + 4, c[1] + FACE_R + 4))
        L.circle(c, FACE_R, fill=LETTER[st.name][lbl], outline=p['dot'], width=2)
        L.text(c, lbl, p['press_text'], 24)
        nodes.append(g.showhide(f'quad_right:{dd}', g.img_node(save(L, st, f'face_{lbl.lower()}.png'), interp)))

    # steam, back, start
    L = g.Layer(st, (STEAM_C[0] - STEAM_R - 4, STEAM_C[1] - STEAM_R - 4, STEAM_C[0] + STEAM_R + 4, STEAM_C[1] + STEAM_R + 4))
    L.circle(STEAM_C, STEAM_R, fill=p['accent'], outline=p['accent2'], width=2)
    L.circle(STEAM_C, STEAM_R - 9, outline=p['press_text'], width=3 if not st.pixel else 2)
    nodes.append(g.showhide('home', g.img_node(save(L, st, 'steam_on.png'), interp)))
    for c, key, name in ((VIEW_C, 'menu:l', 'back_on.png'), (MENU_C, 'menu:r', 'start_on.png')):
        L = g.Layer(st, (c[0] - KEY_W / 2 - 10, c[1] - KEY_H / 2 - 10, c[0] + KEY_W / 2 + 10, c[1] + KEY_H / 2 + 10))
        draw_key(L, st, c, key == 'menu:r', p['accent'], p['accent2'], p['press_text'])
        nodes.append(g.showhide(key, g.img_node(save(L, st, name), interp)))

    # trackpads: click ring + touch trail (shared images)
    CL = g.Layer(st, (-PAD_RAD - 6, -PAD_RAD - 6, PAD_RAD + 6, PAD_RAD + 6))
    CL.circle((0, 0), PAD_RAD, fill=p['accent'][:3] + (70,), outline=p['accent2'], width=4)
    pad_click = save(CL, st, 'pad_click.png')
    TL = g.Layer(st, (-18, -18, 18, 18))
    if st.pixel:
        TL.rrect((0, 0), 20, 20, 0, fill=p['trail'])
    else:
        TL.circle((0, 0), 12, fill=p['trail'])
        TL.img = TL.img.filter(ImageFilter.GaussianBlur(3 * st.k))
    trail = save(TL, st, 'pad_trail.png')
    DL = g.Layer(st, (-22, -22, 22, 22))
    if st.pixel:
        DL.rrect((0, 0), 30, 30, 0, fill=p['dot'], outline=p['accent'], width=5)
    else:
        DL.circle((0, 0), 16, fill=p['dot'], outline=p['accent'], width=3)
    dot = save(DL, st, 'pad_touch.png')
    for side, c in (('left', PAD_L), ('right', PAD_R)):
        n_click = g.img_node(pad_click, interp); n_click['x'] = n_click['y'] = 0
        n_dot = g.img_node(dot, interp); n_dot['x'] = n_dot['y'] = 0
        nodes.append({'x': c[0], 'y': c[1], 'children': [
            g.showhide(f'touch_{side}:click', n_click),
            {'type': 'trailpad', 'image': trail['file'], 'x': 0, 'y': 0, 'width': trail['w'], 'height': trail['h'],
             'input': f'touch_{side}:0:touch',
             'inputX': f'touch_{side}:0:x * {PAD_TRAVEL}', 'inputY': f'touch_{side}:0:y * {PAD_TRAVEL}',
             'length': 24,
             'children': [g.showhide(f'touch_{side}:0:touch', n_dot)]},
        ]})

    # stick
    CL = g.Layer(st, (-STICK_CAP_R - 4, -STICK_CAP_R - 4, STICK_CAP_R + 4, STICK_CAP_R + 4))
    CL.circle((0, 0), STICK_CAP_R, fill=p['cap'], outline=p['edge'], width=2)
    CL.circle((0, 0), STICK_CAP_R - 12, fill=p['cap_hi'] if not st.pixel else None, outline=p['cap_hi'], width=2)
    cap = save(CL, st, 'stick_cap.png')
    PCL = g.Layer(st, (-STICK_CAP_R - 4, -STICK_CAP_R - 4, STICK_CAP_R + 4, STICK_CAP_R + 4))
    PCL.circle((0, 0), STICK_CAP_R, fill=p['cap_press'], outline=p['accent2'], width=3)
    cap_on = save(PCL, st, 'stick_cap_on.png')
    n_cap = g.img_node(cap, interp); n_cap['x'] = n_cap['y'] = 0
    n_on = g.img_node(cap_on, interp); n_on['x'] = n_on['y'] = 0
    nodes.append({'type': 'slider', 'x': STICK[0], 'y': STICK[1],
                  'inputX': f'stick_left:x * {STICK_TRAVEL}', 'inputY': f'stick_left:y * {STICK_TRAVEL}',
                  'children': [n_cap, g.showhide('stick_left:click', n_on)]})

    # gyro widget (Full layout only)
    gy = gyro_images(st)
    gyro = {'type': 'basic3d1', 'image': gy['image']['file'], 'x': GYRO_C[0], 'y': GYRO_C[1],
            'width': gy['image']['w'], 'height': gy['image']['h'], 'mode': 'gyro',
            'shadowl': gy['l']['file'], 'shadowr': gy['r']['file'], 'shadowu': gy['u']['file'], 'shadowd': gy['d']['file']}
    gyro.update(interp)

    for name, extra in (('Full', [gyro]), ('No Gyro', [])):
        theme = {'name': name, 'width': W, 'height': H, 'version': 1, 'children': nodes + extra}
        with open(os.path.join(d, f'{name}.json'), 'w', encoding='utf-8') as f:
            json.dump(theme, f, indent=2)
    with open(os.path.join(d, 'theme.json'), 'w', encoding='utf-8') as f:
        json.dump({'name': st.title, 'authors': [{'name': 'VSCView contributors'}]}, f, indent=2)
    base = Image.open(os.path.join(d, 'base.png'))
    icon = base.crop(base.getbbox())
    icon.thumbnail((32, 32), Image.NEAREST if st.pixel else Image.LANCZOS)
    canvas = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    canvas.paste(icon, ((32 - icon.width) // 2, (32 - icon.height) // 2))
    canvas.save(os.path.join(d, 'icon.png'))


def main():
    for st in (g.GRAPHITE, g.VAPOR):
        build(st)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
