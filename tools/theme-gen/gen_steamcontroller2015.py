#!/usr/bin/env python3
"""
Generates Graphite and Vaporwave Pixel themes for the original (2015) Steam Controller.

Shares the drawing code and palettes of gen_steamcontroller2026.py. Like that script, the artwork is
drawn from scratch from simple shapes (no Valve artwork) and is covered by this repository's license.

Usage:  python tools/theme-gen/gen_steamcontroller2015.py
Writes VSCView/themes/steamcontroller/graphite and .../vaporwave.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageChops, ImageDraw, ImageFilter  # noqa: E402
import gen_steamcontroller2026 as g  # noqa: E402

OUT = os.path.join(g.ROOT, 'VSCView', 'themes', 'steamcontroller')
W, H = 1000, 760

# ---------------------------------------------------------------- layout (theme pixels)
PAD_L, PAD_R, PAD_RAD, PAD_TRAVEL = (236, 252), (764, 252), 118, 100
STICK = (388, 392)
STICK_WELL_R, STICK_CAP_R, STICK_TRAVEL = 58, 40, 18
FACE_C, FACE_D, FACE_R = (612, 390), 50, 24
STEAM_C, STEAM_R = (500, 226), 34
VIEW_C, MENU_C = (420, 238), (580, 238)
GRIP = {'l': (214, 560), 'r': (786, 560)}
BUMPER_L, BUMPER_R = (232, 112), (768, 112)
TRIGGER_L, TRIGGER_R = (232, 52), (768, 52)
TRIGGER_W, TRIGGER_H = 168, 64


def body_outline():
    left = [(500, 108), (360, 110), (220, 118), (150, 140), (104, 186), (78, 262), (62, 360),
            (58, 460), (70, 560), (98, 650), (140, 714), (188, 736), (236, 724), (268, 686),
            (296, 640), (340, 612), (420, 600), (500, 598)]
    right = [(W - x, y) for (x, y) in reversed(left[1:-1])]
    pts = left + right
    for _ in range(5):
        nxt = []
        for i in range(len(pts)):
            p, q = pts[i], pts[(i + 1) % len(pts)]
            nxt.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            nxt.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        pts = nxt
    return pts


def save(layer, st, name):
    img = layer.finish()
    img.save(os.path.join(OUT, st.name, name), optimize=True)
    return {'x': layer.x0 + layer.w / 2, 'y': layer.y0 + layer.h / 2, 'w': layer.w, 'h': layer.h, 'file': name}


def face_positions():
    cx, cy = FACE_C
    return {'n': ('Y', (cx, cy - FACE_D)), 'e': ('B', (cx + FACE_D, cy)), 's': ('A', (cx, cy + FACE_D)), 'w': ('X', (cx - FACE_D, cy))}


def pad_wedge(c, d):
    """Quarter of the left trackpad (the 2015 controller reports left-pad clicks as a d-pad)."""
    cx, cy = c
    r0, r1 = 34, PAD_RAD - 10
    a0 = {'e': -45, 's': 45, 'w': 135, 'n': 225}[d]
    pts = []
    for i in range(13):
        a = math.radians(a0 + 90 * i / 12)
        pts.append((cx + r1 * math.cos(a), cy + r1 * math.sin(a)))
    for i in range(12, -1, -1):
        a = math.radians(a0 + 90 * i / 12)
        pts.append((cx + r0 * math.cos(a), cy + r0 * math.sin(a)))
    return pts


def grip_shape(side):
    cx, cy = GRIP[side]
    return g.rrect_poly(cx, cy, 64, 150, 30, -14 if side == 'l' else 14)


def draw_base(st):
    p = st.p
    L = g.Layer(st, (0, 90, W, H))
    outline = body_outline()
    L.poly(outline, fill=p['body'], outline=p['edge'], width=3)
    if not st.pixel:
        hi = g.Layer(st, (0, 90, W, H))
        hi.poly([(x, y - 6) for (x, y) in outline], fill=p['body_hi'])
        mask = Image.new('L', hi.img.size, 0)
        md = ImageDraw.Draw(mask)
        hh = hi.img.size[1]
        for yy in range(hh):
            t = yy / (hh * 0.55)
            md.line([(0, yy), (hi.img.size[0], yy)], fill=int(110 * max(0.0, 1 - t) ** 1.6))
        body_mask = Image.new('L', hi.img.size, 0)
        ImageDraw.Draw(body_mask).polygon([L.P(x, y) for (x, y) in outline], fill=255)
        L.img.paste(hi.img, (0, 0), ImageChops.multiply(mask, body_mask))
        L.d = ImageDraw.Draw(L.img)
        L.poly(outline, outline=p['edge'], width=3)

    # grips (rear buttons), drawn on the grips
    for side in 'lr':
        L.poly(grip_shape(side), fill=p['inset'], outline=p['edge'], width=2)
    # trackpads
    for c in (PAD_L, PAD_R):
        L.circle(c, PAD_RAD + 8, fill=p['well'])
        L.circle(c, PAD_RAD, fill=p['inset'], outline=p['edge'], width=2)
        if not st.pixel:
            L.circle(c, PAD_RAD - 16, outline=p['well'], width=1)
    # faint d-pad cross on the left pad
    cx, cy = PAD_L
    for (dx, dy) in ((0, -1), (1, 0), (0, 1), (-1, 0)):
        tip = (cx + dx * 72, cy + dy * 72)
        side = (dy * 12, -dx * 12)
        base = (cx + dx * 50, cy + dy * 50)
        L.poly([tip, (base[0] + side[0], base[1] + side[1]), (base[0] - side[0], base[1] - side[1])], fill=p['well'])
    # stick
    L.circle(STICK, STICK_WELL_R, fill=p['well'], outline=p['edge'], width=2)
    # face buttons
    L.circle(FACE_C, 86, fill=p['well'])
    for k, (lbl, c) in face_positions().items():
        L.circle(c, FACE_R, fill=p['inset'], outline=p['edge'], width=2)
        L.text(c, lbl, p['label'], 24)
    # steam / view / menu
    L.circle(STEAM_C, STEAM_R, fill=p['inset'], outline=p['edge'], width=2)
    L.circle(STEAM_C, STEAM_R - 13, outline=p['label'], width=3)
    for c, icon in ((VIEW_C, 'view'), (MENU_C, 'menu')):
        L.poly(arrow(c, icon == 'menu'), fill=p['inset'], outline=p['edge'], width=2)
    return L


def arrow(c, right):
    """The 2015 controller's back/start buttons are small arrow-shaped keys."""
    x, y = c
    s = 1 if right else -1
    return [(x - 22 * s, y - 13), (x + 8 * s, y - 13), (x + 24 * s, y), (x + 8 * s, y + 13), (x - 22 * s, y + 13)]


def build(st):
    os.makedirs(os.path.join(OUT, st.name), exist_ok=True)
    p = st.p
    interp = {'winform.interpolation': 'NearestNeighbor', 'winform.smoothing': 'None'} if st.pixel else {'winform.interpolation': 'HighQualityBicubic'}
    nodes = []

    # triggers: analog fill + full-pull (stage 2) outline; bumpers
    for side, c in (('l', TRIGGER_L), ('r', TRIGGER_R)):
        bb = (c[0] - TRIGGER_W / 2 - 6, c[1] - TRIGGER_H / 2 - 6, c[0] + TRIGGER_W / 2 + 6, c[1] + TRIGGER_H / 2 + 6)
        L = g.Layer(st, bb)
        L.rrect(c, TRIGGER_W, TRIGGER_H, 20, fill=p['trigger'], outline=p['edge'], width=2)
        if not st.pixel:
            L.text(c, 'L' if side == 'l' else 'R', p['label'], 22)
        nodes.append(g.img_node(save(L, st, f'trigger_{side}.png'), interp))
        F = g.Layer(st, bb)
        F.rrect(c, TRIGGER_W, TRIGGER_H, 20, fill=p['accent'])
        fill = save(F, st, f'trigger_{side}_fill.png')
        n = {'type': 'pbar', 'image': fill['file'], 'x': fill['x'], 'y': fill['y'], 'width': fill['w'], 'height': fill['h'],
             'center': True, 'direction': 'up', 'input': f'triggers:{side}:analog'}
        n.update(interp)
        nodes.append(n)
        S = g.Layer(st, bb)
        S.rrect(c, TRIGGER_W + 4, TRIGGER_H + 4, 22, outline=p['accent2'], width=5)
        nodes.append(g.showhide(f'triggers:{side}:stage2', g.img_node(save(S, st, f'trigger_{side}_click.png'), interp)))
    for side, c in (('l', BUMPER_L), ('r', BUMPER_R)):
        bb = (c[0] - 104, c[1] - 20, c[0] + 104, c[1] + 20)
        L = g.Layer(st, bb)
        L.rrect(c, 200, 30, 14, fill=p['trigger'], outline=p['edge'], width=2)
        nodes.append(g.img_node(save(L, st, f'bumper_{side}.png'), interp))
        L = g.Layer(st, bb)
        L.rrect(c, 200, 30, 14, fill=p['accent'], outline=p['accent2'], width=2)
        nodes.append(g.showhide(f'bumpers:{side}', g.img_node(save(L, st, f'bumper_{side}_on.png'), interp)))

    nodes.append(g.img_node(save(draw_base(st), st, 'base.png'), interp))

    # grips
    for side in 'lr':
        pts = grip_shape(side)
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        L = g.Layer(st, (min(xs) - 4, min(ys) - 4, max(xs) + 4, max(ys) + 4))
        L.poly(pts, fill=p['accent'], outline=p['accent2'], width=2)
        nodes.append(g.showhide(f'grip:{side}', g.img_node(save(L, st, f'grip_{side}_on.png'), interp)))

    # left pad d-pad wedges (left pad click direction)
    for d in 'nesw':
        pts = pad_wedge(PAD_L, d)
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        L = g.Layer(st, (min(xs) - 2, min(ys) - 2, max(xs) + 2, max(ys) + 2))
        L.poly(pts, fill=p['accent'][:3] + (150,))
        nodes.append(g.showhide(f'quad_left:{d}', g.img_node(save(L, st, f'pad_dpad_{d}.png'), interp)))

    # face buttons
    for d, (lbl, c) in face_positions().items():
        L = g.Layer(st, (c[0] - FACE_R - 4, c[1] - FACE_R - 4, c[0] + FACE_R + 4, c[1] + FACE_R + 4))
        L.circle(c, FACE_R, fill=p['accent'], outline=p['accent2'], width=2)
        L.text(c, lbl, p['press_text'], 24)
        nodes.append(g.showhide(f'quad_right:{d}', g.img_node(save(L, st, f'face_{lbl.lower()}.png'), interp)))

    # steam, back, start
    L = g.Layer(st, (STEAM_C[0] - STEAM_R - 4, STEAM_C[1] - STEAM_R - 4, STEAM_C[0] + STEAM_R + 4, STEAM_C[1] + STEAM_R + 4))
    L.circle(STEAM_C, STEAM_R, fill=p['accent'], outline=p['accent2'], width=2)
    L.circle(STEAM_C, STEAM_R - 13, outline=p['press_text'], width=3)
    nodes.append(g.showhide('home', g.img_node(save(L, st, 'steam_on.png'), interp)))
    for c, key, name in ((VIEW_C, 'menu:l', 'back_on.png'), (MENU_C, 'menu:r', 'start_on.png')):
        pts = arrow(c, key == 'menu:r')
        L = g.Layer(st, (c[0] - 28, c[1] - 17, c[0] + 28, c[1] + 17))
        L.poly(pts, fill=p['accent'], outline=p['accent2'], width=2)
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
    CL.circle((0, 0), STICK_CAP_R - 11, fill=p['cap_hi'] if not st.pixel else None, outline=p['cap_hi'], width=2)
    cap = save(CL, st, 'stick_cap.png')
    PCL = g.Layer(st, (-STICK_CAP_R - 4, -STICK_CAP_R - 4, STICK_CAP_R + 4, STICK_CAP_R + 4))
    PCL.circle((0, 0), STICK_CAP_R, fill=p['cap_press'], outline=p['accent2'], width=3)
    cap_on = save(PCL, st, 'stick_cap_on.png')
    n_cap = g.img_node(cap, interp); n_cap['x'] = n_cap['y'] = 0
    n_on = g.img_node(cap_on, interp); n_on['x'] = n_on['y'] = 0
    nodes.append({'type': 'slider', 'x': STICK[0], 'y': STICK[1],
                  'inputX': f'stick_left:x * {STICK_TRAVEL}', 'inputY': f'stick_left:y * {STICK_TRAVEL}',
                  'children': [n_cap, g.showhide('stick_left:click', n_on)]})

    theme = {'name': 'Full', 'width': W, 'height': H, 'version': 1, 'children': nodes}
    with open(os.path.join(OUT, st.name, 'Full.json'), 'w', encoding='utf-8') as f:
        json.dump(theme, f, indent=2)
    with open(os.path.join(OUT, st.name, 'theme.json'), 'w', encoding='utf-8') as f:
        json.dump({'name': st.title, 'authors': [{'name': 'VSCView contributors'}]}, f, indent=2)
    base = Image.open(os.path.join(OUT, st.name, 'base.png'))
    icon = base.copy()
    icon.thumbnail((32, 32), Image.NEAREST if st.pixel else Image.LANCZOS)
    canvas = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    canvas.paste(icon, ((32 - icon.width) // 2, (32 - icon.height) // 2))
    canvas.save(os.path.join(OUT, st.name, 'icon.png'))


def main():
    for st in (g.GRAPHITE, g.VAPOR):
        build(st)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
