"""
Renders the "Realistic" theme for the 2026 Steam Controller with Blender (Cycles).

    blender -b --factory-startup -P tools/blender/render_sc2026.py -- [--samples 96] [--out DIR] [--tmp DIR]

Writes VSCView/themes/steamcontroller2026/realistic/ (PNG parts, Full.json, "No Gyro.json",
theme.json, icon.png). Layout and input bindings mirror themes/steamcontroller2026/graphite
(tools/theme-gen/gen_steamcontroller2026.py); see sc_common.py for the render pipeline.
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import sc_common as C  # noqa: E402
import sc_shared as X  # noqa: E402
from sc_shared import GLOW, LABEL, bbox_c  # noqa: E402
from sc_common import W, H, S  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# ---------------------------------------------------------------- layout (theme px, same as graphite)
STICK_L, STICK_R = (368, 300), (632, 300)
STICK_WELL_R, STICK_CAP_R, STICK_TRAVEL = 66, 44, 20
FACE_C, FACE_D, FACE_R = (778, 242), 52, 25
DPAD_C = (222, 242)
DPAD_A, DPAD_B = 21, 54
STEAM_C, STEAM_R = (500, 236), 27
VIEW_C, MENU_C = (338, 172), (662, 172)
QAM_C = (500, 486)
PAD_L, PAD_R, PAD_SIZE, PAD_ROT = (326, 478), (674, 478), 184, 9.87
PAD_TRAVEL = 78
BACK = {'L4': (122, 566), 'L5': (148, 646), 'R4': (878, 566), 'R5': (852, 646)}
BUMPER_L, BUMPER_R = (232, 112), (768, 112)
TRIGGER_L, TRIGGER_R = (232, 50), (768, 50)
TRIGGER_W, TRIGGER_H = 168, 60
GYRO_C, GYRO_MAX = (500, 690), (172, 118)

BODY_LEFT = [(500, 106), (360, 108), (230, 116), (168, 132), (132, 160), (108, 214), (88, 300),
             (68, 400), (54, 500), (56, 590), (78, 660), (118, 708), (166, 728), (212, 716),
             (244, 680), (270, 636), (310, 610), (380, 600), (500, 598)]
OUTLINE = C.mirrored_outline(BODY_LEFT, 5)

SHELL = (31, 32, 36)
BUTTON = (27, 28, 31)


def face_positions():
    cx, cy = FACE_C
    return {'n': ('Y', (cx, cy - FACE_D)), 'e': ('B', (cx + FACE_D, cy)), 's': ('A', (cx, cy + FACE_D)), 'w': ('X', (cx - FACE_D, cy))}


def dpad_cross(grow=0.0):
    cx, cy = DPAD_C
    a, b = DPAD_A + grow, DPAD_B + grow
    pts = [(cx - a, cy - b), (cx + a, cy - b), (cx + a, cy - a), (cx + b, cy - a), (cx + b, cy + a), (cx + a, cy + a),
           (cx + a, cy + b), (cx - a, cy + b), (cx - a, cy + a), (cx - b, cy + a), (cx - b, cy - a), (cx - a, cy - a)]
    return C.round_poly(pts, 6 + grow * 0.5, steps=6)


# ---------------------------------------------------------------- body shell heightfield
def shell_profile(d):
    return 28.0 * C.round_edge(d, 26.0) + 14.0 * C.smoothstep(0, 230, d)


def surf(x, y):
    """Shell height (no recesses) at a point."""
    d = C.sdf_polygon(np.array([float(x)]), np.array([float(y)]), OUTLINE)
    return float(shell_profile(d)[0])


def recess(h, sd, depth, soft=2.5, floor=None):
    """Sink the shell inside shape sd (>0 inside). With floor given the bottom is flat at that height."""
    m = C.smoothstep(-soft, soft, sd)
    if floor is None:
        return h - depth * m
    return h * (1 - m) + np.minimum(h, floor) * m


def height_fn(px, py, d):
    h = shell_profile(d)
    # stick wells: raised lip, then a deep round well
    for c in (STICK_L, STICK_R):
        sd = C.sdf_circle(px, py, c, STICK_WELL_R)
        h = h + 3.0 * np.exp(-((sd + 5.0) / 3.2) ** 2)
        h = recess(h, sd, 0, 3.5, floor=surf(*c) - 22.0)
    # d-pad dish + cross opening
    h = recess(h, C.sdf_circle(px, py, DPAD_C, 66), 4.0, 6.0)
    h = recess(h, C.sdf_polygon(px, py, dpad_cross(3.0)), 0, 1.5, floor=surf(*DPAD_C) - 12.0)
    # face button openings in a shallow dish
    h = recess(h, C.sdf_circle(px, py, FACE_C, 90), 3.0, 8.0)
    for _, (lbl, c) in face_positions().items():
        h = recess(h, C.sdf_circle(px, py, c, FACE_R + 3), 0, 1.5, floor=surf(*c) - 9.0)
    h = recess(h, C.sdf_circle(px, py, STEAM_C, STEAM_R + 3), 0, 1.5, floor=surf(*STEAM_C) - 9.0)
    for c, w in ((VIEW_C, 46), (MENU_C, 46), (QAM_C, 54)):
        h = recess(h, C.sdf_rrect(px, py, c, w + 6, 32, 15), 0, 1.5, floor=surf(*c) - 8.0)
    for c, rot in ((PAD_L, PAD_ROT), (PAD_R, -PAD_ROT)):
        h = recess(h, C.sdf_rrect(px, py, c, PAD_SIZE + 8, PAD_SIZE + 8, 34, rot), 0, 2.0, floor=surf(*c) - 9.0)
    return h


def bumper_band(side):
    return X.bumper_band(OUTLINE, side, 146, 322)


# ---------------------------------------------------------------- model
class Model:
    def __init__(self):
        self.parts = {}
        self.caps = {}

    def build(self):
        C.studio_lights()
        self.ring = C.RingMask()
        self.shell_mat = C.Mat('shell', SHELL, rough=0.5, spec=0.45, bump=C.noise_bump(1400, 0.05),
                               alpha_attr='mask', mask_fn=self.ring)
        # alpha via mix with transparent: Principled Alpha handles it in Cycles
        bbox = (40, 84, 960, 744)
        C.heightfield('shell', bbox, height_fn, lambda px, py: C.sdf_polygon(px, py, OUTLINE), self.shell_mat)
        C.shadow_catcher(-8)

        # d-pad (one rocker; per-direction glow via a direction mask)
        self.dpad_mask = X.DirMask(DPAD_C, DPAD_A)
        self.dpad_mat = C.Mat('dpad', BUTTON, rough=0.36, spec=0.5, mask_fn=self.dpad_mask)
        sz = surf(*DPAD_C) - 4
        self.dpad = C.slab('dpad', dpad_cross(0), sz + 4, 3.0, sz - 8, self.dpad_mat)
        # small embossed arrows
        self.dpad_lbl = C.Mat('dpad_lbl', (96, 100, 110), rough=0.5)
        cx, cy = DPAD_C
        for (dx, dy) in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            tip = (cx + dx * 44, cy + dy * 44)
            b = (cx + dx * 35, cy + dy * 35)
            side = (dy * 6, -dx * 6)
            tri = [tip, (b[0] + side[0], b[1] + side[1]), (b[0] - side[0], b[1] - side[1])]
            C.slab('dpad_arrow', C.round_poly(tri, 1.5, 3), sz + 4.3, 0.2, sz + 2, self.dpad_lbl, steps=2)
        for d in 'nesw':
            self.parts[f'dpad_{d}'] = dict(expr=f'quad_left:{d}', objs=[], mats=[(self.dpad_mat, GLOW)], dirmask=(self.dpad_mask, d),
                                           region=bbox_c(DPAD_C, 64, 64))

        # face buttons
        for d, (lbl, c) in face_positions().items():
            z = surf(*c) - 3
            m = C.Mat(f'btn_{lbl}', BUTTON, rough=0.3, spec=0.55, coat=0.25)
            ob = C.lathe(f'btn_{lbl}', C.arc_profile(z + 6, FACE_R, 4.5, z - 9, dome=1.6), c, 0, mat=m)
            lm = C.Mat(f'lbl_{lbl}', LABEL, rough=0.45)
            t = C.text_obj(f'txt_{lbl}', lbl, c, z + 7.45, 23, lm, extrude_px=0.15, bold=True)
            self.parts[f'face_{lbl.lower()}'] = dict(expr=f'quad_right:{d}', objs=[ob, t], mats=[(m, GLOW)],
                                                     labels=[lm], region=bbox_c(c, FACE_R + 14, FACE_R + 14))

        # steam (plain round button with a printed ring), view, menu, qam
        z = surf(*STEAM_C) - 4
        m = C.Mat('steam', BUTTON, rough=0.3, spec=0.55, coat=0.25)
        ob = C.lathe('steam', C.arc_profile(z + 6, STEAM_R, 4.0, z - 8, dome=-1.2), STEAM_C, 0, mat=m)
        lm = C.Mat('lbl_steam', LABEL, rough=0.45)
        ring = C.lathe('steam_ring', [(13.0, z + 5.55), (16.2, z + 5.55)], STEAM_C, 0, mat=lm)
        ring2 = C.lathe('steam_ring_b', [(16.2, z + 5.55), (13.0, z + 5.55)], STEAM_C, 0, mat=lm)
        self.parts['steam'] = dict(expr='home', objs=[ob, ring, ring2], mats=[(m, GLOW)], labels=[lm],
                                   region=bbox_c(STEAM_C, STEAM_R + 14, STEAM_R + 14))
        for key, c, w, expr, icon in (('view', VIEW_C, 46, 'menu:l', view_icon), ('menu', MENU_C, 46, 'menu:r', menu_icon),
                                      ('qam', QAM_C, 54, 'qam', qam_icon)):
            z = surf(*c) - 3
            m = C.Mat(key, BUTTON, rough=0.3, spec=0.55, coat=0.2)
            ob = C.slab(key, C.rrect_pts(c[0], c[1], w, 26, 12), z + 5, 3.0, z - 7, m)
            lm = C.Mat(f'lbl_{key}', LABEL, rough=0.45)
            objs = [ob] + icon(c, z + 5.2, lm)
            self.parts[key] = dict(expr=expr, objs=objs, mats=[(m, GLOW)], labels=[lm],
                                   region=bbox_c(c, w / 2 + 14, 13 + 14))

        # back buttons as labelled tabs on the grips
        for name, c in BACK.items():
            z = surf(*c)
            m = C.Mat(f'back_{name}', (39, 40, 45), rough=0.62, spec=0.35, bump=C.noise_bump(900, 0.06))
            ob = C.slab(f'back_{name}', C.rrect_pts(c[0], c[1], 70, 34, 15), z + 5, 3.5, z - 4, m)
            lm = C.Mat(f'lbl_{name}', LABEL, rough=0.45)
            t = C.text_obj(f'txt_{name}', name, c, z + 5.05, 20, lm, extrude_px=0.15, bold=True)
            side = 'l' if name[0] == 'L' else 'r'
            key = 'grip' if name[1] == '4' else 'grip2'
            self.parts[f'back_{name.lower()}'] = dict(expr=f'{key}:{side}', objs=[ob, t], mats=[(m, GLOW)], labels=[lm],
                                                       region=bbox_c(c, 35 + 14, 17 + 14))

        # trackpads
        for side, c, rot in (('l', PAD_L, PAD_ROT), ('r', PAD_R, -PAD_ROT)):
            z = surf(*c) - 7
            m = C.Mat(f'pad_{side}', (29, 30, 34), rough=0.62, spec=0.4, bump=C.noise_bump(2200, 0.12, detail=4))
            ob = C.slab(f'pad_{side}', C.rrect_pts(c[0], c[1], PAD_SIZE, PAD_SIZE, 30, rot), z + 5.2, 2.5, z - 6, m)
            self.parts[f'pad_click_{side}'] = dict(expr=f'touch_{"left" if side == "l" else "right"}:click', objs=[ob],
                                                    mats=[(m, 0.09)], depress=1.5, tint=0.12,
                                                    region=bbox_c(c, PAD_SIZE / 2 + 30, PAD_SIZE / 2 + 30))

        # bumpers (tucked under the shell's top edge)
        for side in 'lr':
            m = C.Mat(f'bumper_{side}', (37, 38, 43), rough=0.42, spec=0.5)
            poly = bumper_band(side)
            ob = C.slab(f'bumper_{side}', poly, 16, 10, -12, m, steps=10)
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            self.parts[f'bumper_{side}'] = dict(expr=f'bumpers:{side}', objs=[ob], mats=[(m, GLOW)], depress=0,
                                                region=(min(xs) - 14, min(ys) - 14, max(xs) + 14, max(ys) + 18))
        # triggers (shown above the controller, like the graphite theme)
        self.triggers = {}
        for side, c in (('l', TRIGGER_L), ('r', TRIGGER_R)):
            m = C.Mat(f'trigger_{side}', (37, 38, 43), rough=0.4, spec=0.5)
            ob = C.slab(f'trigger_{side}', C.rrect_pts(c[0], c[1], TRIGGER_W, TRIGGER_H, 22), 24, 13, -2, m, steps=10)
            lm = C.Mat(f'lbl_trig_{side}', LABEL, rough=0.45)
            t = C.text_obj(f'txt_trig_{side}', 'LT' if side == 'l' else 'RT', c, 24.05, 22, lm, extrude_px=0.15, bold=True)
            self.triggers[side] = dict(c=c, w=TRIGGER_W, h=TRIGGER_H, objs=[ob, t], mats=[(m, GLOW)], labels=[lm])

        # stick caps (rendered as separate sprites)
        for side, c in (('l', STICK_L), ('r', STICK_R)):
            self.caps[side] = X.stick_cap(f'cap_{side}', c, surf(*c) - 22, STICK_CAP_R)
        return self


def bar(name, c, w, h, z, m, r=1.2):
    return C.slab(name, C.rrect_pts(c[0], c[1], w, h, min(r, w / 2 - 0.01, h / 2 - 0.01)), z, 0.25, z - 2, m, steps=2)


def rect_outline(name, c, w, h, t, z, m):
    x, y = c
    return [bar(name, (x, y - h / 2 + t / 2), w, t, z, m, 0.6), bar(name, (x, y + h / 2 - t / 2), w, t, z, m, 0.6),
            bar(name, (x - w / 2 + t / 2, y), t, h, z, m, 0.6), bar(name, (x + w / 2 - t / 2, y), t, h, z, m, 0.6)]


def view_icon(c, z, m):
    x, y = c
    return rect_outline('view_a', (x - 3.5, y - 2.5), 12, 9, 2, z, m) + rect_outline('view_b', (x + 3.5, y + 2.5), 12, 9, 2, z + 0.05, m)


def menu_icon(c, z, m):
    x, y = c
    return [bar('menu_bar', (x, y + dy), 18, 2.6, z, m, 1.2) for dy in (-5.5, 0, 5.5)]


def qam_icon(c, z, m):
    x, y = c
    out = []
    for dx in (-11, 0, 11):
        out.append(C.lathe('qam_dot', [(0, z + 0.2), (2.6, z + 0.2), (3.4, z - 0.4), (3.4, z - 2)], (x + dx, y), 0, segs=32, mat=m))
    return out


# ---------------------------------------------------------------- rendering
def main():
    args = C.parse_args()
    out = args.out or os.path.join(ROOT, 'VSCView', 'themes', 'steamcontroller2026', 'realistic')
    tmp = args.tmp or os.path.join(os.environ.get('TEMP', '/tmp'), 'padsight_sc2026_render')
    t_start = time.time()
    sc = C.reset_scene(args.samples)
    C.world_studio(sc)
    model = Model().build()
    R = C.Renderer(sc, tmp, out)
    for cap in model.caps.values():
        for ob in cap['objs']:
            ob.hide_render = True
    obj, final = X.render_base(R)
    if args.preview:
        C.write_png(os.path.join(tmp, 'preview_base.png'), final)
    else:
        nodes, gyro = build_parts(model, R, obj, final)
        C.write_theme(out, nodes, gyro)
        checks(R, nodes, gyro, args.check or tmp, 'sc2026')
    C.log(f'done: {R.n} renders in {time.time() - t_start:.0f}s')


def build_parts(model, R, base, final):
    split_y = int(min(min(p[1] for p in bumper_band('l')) - 3, 88))
    trig_nodes = X.triggers(model, R, base, final, split_y)
    body = final.copy()
    body[:split_y] = 0
    binfo = R.save('base.png', body)
    halo_nodes = X.grip_sense(R, body)

    names = {'steam': 'steam_on.png', 'view': 'view_on.png', 'menu': 'menu_on.png', 'qam': 'qam_on.png',
             'bumper_l': 'bumper_l_on.png', 'bumper_r': 'bumper_r_on.png'}
    order = ['bumper_l', 'bumper_r', 'dpad_n', 'dpad_e', 'dpad_s', 'dpad_w', 'face_y', 'face_b', 'face_a', 'face_x',
             'steam', 'view', 'menu', 'qam', 'back_l4', 'back_l5', 'back_r4', 'back_r5', 'pad_click_l', 'pad_click_r']
    infos = {k: X.overlay(R, base, k, model.parts[k], names.get(k, f'{k}.png')) for k in order}

    # stick touch: the shell lip around each well lights up
    touch = {}
    for side, c in (('l', STICK_L), ('r', STICK_R)):
        model.ring.set(c, STICK_WELL_R + 5)
        model.shell_mat.val.outputs[0].default_value = 1.6
        reg = bbox_c(c, STICK_WELL_R + 26, STICK_WELL_R + 26)
        img = R.render(f'stick_touch_{side}', X.expand(reg, 8))
        model.shell_mat.val.outputs[0].default_value = 0.0
        model.ring.off()
        touch[side] = X.save_overlay(R, base, img, reg, f'stick_touch_{side}.png')

    caps = X.render_caps(model, R)
    dot, trail, meter = X.sprites(R)

    nodes = halo_nodes + trig_nodes + [C.img_node(binfo)]
    for k in order[:-2]:
        nodes.append(C.showhide(model.parts[k]['expr'], C.img_node(infos[k])))
    for side, c, rot in (('left', PAD_L, PAD_ROT), ('right', PAD_R, -PAD_ROT)):
        nodes.append(C.showhide(f'touch_{side}:click', C.img_node(infos[f'pad_click_{side[0]}'])))
        meter_x = -PAD_SIZE / 2 - 1.5 if side == 'left' else PAD_SIZE / 2 + 1.5
        nodes.append({'x': c[0], 'y': c[1], 'rot': rot, 'children': [
            C.showhide(f'touch_{side}:0:touch', C.pbar(meter, f'touch_{side}:0:pressure', x=meter_x, y=0)),
            X.trailpad(side, PAD_TRAVEL, trail, dot)]})
    for side, c in (('left', STICK_L), ('right', STICK_R)):
        nodes.append(C.showhide(f'stick_touch:{side[0]}', C.img_node(touch[side[0]])))
        nodes.append(X.stick_nodes(side, c, STICK_TRAVEL, caps[side[0]]))

    rest = body.copy()
    for s in 'lr':
        inf = caps[s][0]
        C.over(rest, X.load(R, inf), inf['x0'], inf['y0'])
    gyro = X.gyro_widget(R, rest, GYRO_C, GYRO_MAX)
    X.make_icon(R, rest)
    return nodes, gyro


def checks(R, nodes, gyro, folder, tag):
    os.makedirs(folder, exist_ok=True)
    allin = X.all_inputs(nodes)
    C.write_png(os.path.join(folder, f'{tag}_rest.png'), X.compose(R, nodes + [gyro], set()))
    C.write_png(os.path.join(folder, f'{tag}_all_pressed.png'), X.compose(R, nodes + [gyro], allin))


if __name__ == '__main__':
    main()
