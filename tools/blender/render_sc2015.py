"""
Renders the "Realistic" theme for the original (2015) Steam Controller with Blender (Cycles).

    blender -b --factory-startup -P tools/blender/render_sc2015.py -- [--samples 96] [--out DIR] [--tmp DIR]

Writes VSCView/themes/steamcontroller/realistic/ (PNG parts, Full.json, "No Gyro.json",
theme.json, icon.png). Input bindings mirror themes/steamcontroller/graphite
(tools/theme-gen/gen_steamcontroller2015.py); see sc_common.py for the render pipeline.

Shape (front view): one wide ~1.6:1 body with a gently curved top edge, handles that drop and
flare out, a broad arch between them; two large circular trackpads in raised rims (left one with
an embossed cross), a large plain centre button flanked by chevron back/start buttons, the stick
lower-left and the ABXY diamond lower-right, bumpers on the top edge and a labelled grip tab under
each handle. Triggers are shown above the body like the graphite theme.
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import sc_common as C  # noqa: E402
import sc_shared as X  # noqa: E402
from sc_common import W, H  # noqa: E402
from sc_shared import GLOW, LABEL, bbox_c  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# ---------------------------------------------------------------- layout (theme px)
PAD_L, PAD_R, PAD_RAD = (250, 282), (750, 282), 112      # pad diameter ~ 1/4 of the body width
PAD_TRAVEL = 95
STEAM_C, STEAM_R = (500, 252), 36                         # a little above the pad centres
BACK_C, START_C = (424, 268), (576, 268)
STICK = (386, 440)
STICK_WELL_R, STICK_CAP_R, STICK_TRAVEL = 58, 40, 18
FACE_C, FACE_D, FACE_R = (614, 440), 46, 22
GRIP = {'l': (150, 612), 'r': (850, 612)}
TRIGGER_L, TRIGGER_R = (236, 64), (764, 64)
TRIGGER_W, TRIGGER_H = 168, 56
GYRO_C, GYRO_MAX = (500, 664), (172, 112)

BODY_LEFT = [(500, 124), (380, 126), (270, 133), (190, 146), (132, 170), (96, 210), (76, 270), (64, 350),
             (56, 440), (50, 530), (52, 600), (68, 650), (100, 682), (146, 694), (190, 684), (226, 656),
             (262, 612), (300, 574), (360, 546), (430, 532), (500, 528)]
OUTLINE = C.mirrored_outline(BODY_LEFT, 5)

SHELL = (31, 32, 36)
BUTTON = (27, 28, 31)
LETTERS = {'A': (92, 200, 104), 'B': (226, 78, 72), 'X': (84, 152, 242), 'Y': (236, 198, 64)}


def face_positions():
    cx, cy = FACE_C
    return {'n': ('Y', (cx, cy - FACE_D)), 'e': ('B', (cx + FACE_D, cy)), 's': ('A', (cx, cy + FACE_D)), 'w': ('X', (cx - FACE_D, cy))}


def chevron(c, right, grow=0.0):
    x, y = c
    s = 1 if right else -1
    w, h, tip = 21 + grow, 12 + grow, 12
    pts = [(x - w * s, y - h), (x + (w - tip) * s, y - h), (x + (w + 1) * s, y), (x + (w - tip) * s, y + h), (x - w * s, y + h)]
    return C.round_poly(pts, 4 + grow * 0.5, steps=5)


def cross(c, a=13, b=60):
    cx, cy = c
    pts = [(cx - a, cy - b), (cx + a, cy - b), (cx + a, cy - a), (cx + b, cy - a), (cx + b, cy + a), (cx + a, cy + a),
           (cx + a, cy + b), (cx - a, cy + b), (cx - a, cy + a), (cx - b, cy + a), (cx - b, cy - a), (cx - a, cy - a)]
    return C.round_poly(pts, 5, steps=5)


# ---------------------------------------------------------------- body shell heightfield
def shell_profile(d):
    return 28.0 * C.round_edge(d, 26.0) + 14.0 * C.smoothstep(0, 230, d)


def surf(x, y):
    d = C.sdf_polygon(np.array([float(x)]), np.array([float(y)]), OUTLINE)
    return float(shell_profile(d)[0])


def recess(h, sd, soft, floor):
    m = C.smoothstep(-soft, soft, sd)
    return h * (1 - m) + np.minimum(h, floor) * m


def height_fn(px, py, d):
    h = shell_profile(d)
    for c in (PAD_L, PAD_R):
        r = np.hypot(px - c[0], py - c[1])
        # raised rim around the pad, then the recessed pad bed
        h = h + 9.0 * np.exp(-((r - (PAD_RAD + 9.0)) / 5.5) ** 2) + 2.0 * C.smoothstep(PAD_RAD + 30, PAD_RAD + 9, r)
        h = recess(h, PAD_RAD + 3.0 - r, 1.5, surf(*c) - 8.0)
    sd = C.sdf_circle(px, py, STICK, STICK_WELL_R)
    h = h + 3.0 * np.exp(-((sd + 5.0) / 3.2) ** 2)
    h = recess(h, sd, 3.5, surf(*STICK) - 22.0)
    h = h - 3.0 * C.smoothstep(-8, 8, C.sdf_circle(px, py, FACE_C, 82))
    for _, (lbl, c) in face_positions().items():
        h = recess(h, C.sdf_circle(px, py, c, FACE_R + 3), 1.5, surf(*c) - 10.0)
    h = recess(h, C.sdf_circle(px, py, STEAM_C, STEAM_R + 3), 1.5, surf(*STEAM_C) - 9.0)
    for c, right in ((BACK_C, False), (START_C, True)):
        h = recess(h, C.sdf_polygon(px, py, chevron(c, right, 3)), 1.5, surf(*c) - 8.0)
    return h


# ---------------------------------------------------------------- model
class Model:
    def __init__(self):
        self.parts = {}
        self.caps = {}
        self.triggers = {}

    def build(self):
        C.studio_lights()
        self.shell_mat = C.Mat('shell', SHELL, rough=0.5, spec=0.45, bump=C.noise_bump(1400, 0.05), alpha_attr='mask')
        C.heightfield('shell', (36, 100, 964, 712), height_fn, lambda px, py: C.sdf_polygon(px, py, OUTLINE), self.shell_mat)
        C.shadow_catcher(-8)

        # trackpads: slightly dished discs with fine concentric texture; the left one carries an
        # embossed cross and reports d-pad quarters (quad_left) when clicked off-centre
        for side, c in (('l', PAD_L), ('r', PAD_R)):
            z = surf(*c) - 8
            mask = X.DirMask(c, 24, PAD_RAD - 3)
            m = C.Mat(f'pad_{side}', (30, 31, 35), rough=0.55, spec=0.45, bump=C.rings_bump(260, 0.05, 0.04), mask_fn=mask)
            ob = C.lathe(f'pad_{side}', C.arc_profile(z + 6, PAD_RAD, 3.0, z - 6, dome=-1.8, steps=8), c, 0, mat=m, segs=192)
            objs, mats = [ob], [(m, 0.1)]
            if side == 'l':
                cm = C.Mat('pad_cross', (31, 32, 36), rough=0.5, spec=0.45, bump=C.noise_bump(1800, 0.05), mask_fn=mask)
                objs.append(C.slab('pad_cross', cross(c), z + 6.2, 1.2, z + 2, cm, steps=4))
                mats.append((cm, 0.1))
                for d in 'nesw':
                    self.parts[f'pad_dpad_{d}'] = dict(expr=f'quad_left:{d}', objs=[], mats=[(m, 0.3), (cm, 0.3)], tint=0.25,
                                                       dirmask=(mask, d), depress=0, region=bbox_c(c, PAD_RAD + 6, PAD_RAD + 6))
            self.parts[f'pad_click_{side}'] = dict(expr=f'touch_{"left" if side == "l" else "right"}:click', objs=objs,
                                                    mats=[(mm, 0.1) for mm, _ in mats], tint=0.12, depress=1.5,
                                                    dirmask=(mask, 'all'), region=bbox_c(c, PAD_RAD + 26, PAD_RAD + 26))

        # big plain centre button
        z = surf(*STEAM_C) - 5
        m = C.Mat('steam', BUTTON, rough=0.28, spec=0.55, coat=0.3)
        ob = C.lathe('steam', C.arc_profile(z + 8, STEAM_R, 5.0, z - 7, dome=2.2), STEAM_C, 0, mat=m)
        self.parts['steam'] = dict(expr='home', objs=[ob], mats=[(m, GLOW)], region=bbox_c(STEAM_C, STEAM_R + 14, STEAM_R + 14))

        # chevron back / start
        for key, c, right, expr in (('back', BACK_C, False, 'menu:l'), ('start', START_C, True, 'menu:r')):
            z = surf(*c) - 4
            m = C.Mat(key, BUTTON, rough=0.3, spec=0.55, coat=0.2)
            ob = C.slab(key, chevron(c, right), z + 6, 3.0, z - 6, m)
            self.parts[key] = dict(expr=expr, objs=[ob], mats=[(m, GLOW)], region=bbox_c(c, 24 + 14, 13 + 14))

        # ABXY: dark caps with coloured letters
        for d, (lbl, c) in face_positions().items():
            z = surf(*c) - 4
            m = C.Mat(f'btn_{lbl}', BUTTON, rough=0.3, spec=0.55, coat=0.25)
            ob = C.lathe(f'btn_{lbl}', C.arc_profile(z + 6, FACE_R, 4.5, z - 9, dome=1.6), c, 0, mat=m)
            lm = C.Mat(f'lbl_{lbl}', LETTERS[lbl], rough=0.4)
            t = C.text_obj(f'txt_{lbl}', lbl, c, z + 7.45, 22, lm, extrude_px=0.15)
            self.parts[f'face_{lbl.lower()}'] = dict(expr=f'quad_right:{d}', objs=[ob, t], mats=[(m, GLOW)], labels=[lm],
                                                     label_rest=LETTERS[lbl], label_on=(235, 248, 255),
                                                     region=bbox_c(c, FACE_R + 14, FACE_R + 14))

        # grip buttons: labelled tabs under each handle
        for side, c in GRIP.items():
            z = surf(*c)
            m = C.Mat(f'grip_{side}', (39, 40, 45), rough=0.62, spec=0.35, bump=C.noise_bump(900, 0.06))
            ob = C.slab(f'grip_{side}', C.rrect_pts(c[0], c[1], 72, 34, 15), z + 5, 3.5, z - 4, m)
            lm = C.Mat(f'lbl_grip_{side}', LABEL, rough=0.45)
            t = C.text_obj(f'txt_grip_{side}', 'LG' if side == 'l' else 'RG', c, z + 5.05, 20, lm, extrude_px=0.15)
            self.parts[f'grip_{side}'] = dict(expr=f'grip:{side}', objs=[ob, t], mats=[(m, GLOW)], labels=[lm],
                                              region=bbox_c(c, 36 + 14, 17 + 14))

        # bumpers along the top edge
        for side in 'lr':
            m = C.Mat(f'bumper_{side}', (37, 38, 43), rough=0.42, spec=0.5)
            poly = X.bumper_band(OUTLINE, side, 152, 344)
            ob = C.slab(f'bumper_{side}', poly, 16, 10, -12, m, steps=10)
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            self.parts[f'bumper_{side}'] = dict(expr=f'bumpers:{side}', objs=[ob], mats=[(m, GLOW)], depress=0,
                                                region=(min(xs) - 14, min(ys) - 14, max(xs) + 14, max(ys) + 18))

        # triggers above the body
        for side, c in (('l', TRIGGER_L), ('r', TRIGGER_R)):
            m = C.Mat(f'trigger_{side}', (37, 38, 43), rough=0.4, spec=0.5)
            ob = C.slab(f'trigger_{side}', C.rrect_pts(c[0], c[1], TRIGGER_W, TRIGGER_H, 22), 24, 13, -2, m, steps=10)
            lm = C.Mat(f'lbl_trig_{side}', LABEL, rough=0.45)
            t = C.text_obj(f'txt_trig_{side}', 'LT' if side == 'l' else 'RT', c, 24.05, 22, lm, extrude_px=0.15)
            self.triggers[side] = dict(c=c, w=TRIGGER_W, h=TRIGGER_H, objs=[ob, t], mats=[(m, GLOW)], labels=[lm])

        self.caps['l'] = X.stick_cap('cap_l', STICK, surf(*STICK) - 22, STICK_CAP_R)
        return self


# ---------------------------------------------------------------- rendering
def main():
    args = C.parse_args()
    out = args.out or os.path.join(ROOT, 'VSCView', 'themes', 'steamcontroller', 'realistic')
    tmp = args.tmp or os.path.join(os.environ.get('TEMP', '/tmp'), 'padsight_sc2015_render')
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
        folder = args.check or tmp
        os.makedirs(folder, exist_ok=True)
        allin = X.all_inputs(nodes)
        C.write_png(os.path.join(folder, 'sc2015_rest.png'), X.compose(R, nodes + [gyro], set()))
        C.write_png(os.path.join(folder, 'sc2015_all_pressed.png'), X.compose(R, nodes + [gyro], allin))
    C.log(f'done: {R.n} renders in {time.time() - t_start:.0f}s')


def build_parts(model, R, base, final):
    split_y = int(min(p[1] for p in X.bumper_band(OUTLINE, 'l', 152, 344)) - 3)
    trig_nodes = X.triggers(model, R, base, final, split_y, click=True)
    body = final.copy()
    body[:split_y] = 0
    binfo = R.save('base.png', body)

    names = {'steam': 'steam_on.png', 'back': 'back_on.png', 'start': 'start_on.png',
             'bumper_l': 'bumper_l_on.png', 'bumper_r': 'bumper_r_on.png', 'grip_l': 'grip_l_on.png', 'grip_r': 'grip_r_on.png'}
    order = ['bumper_l', 'bumper_r', 'grip_l', 'grip_r', 'pad_dpad_n', 'pad_dpad_e', 'pad_dpad_s', 'pad_dpad_w',
             'face_y', 'face_b', 'face_a', 'face_x', 'steam', 'back', 'start', 'pad_click_l', 'pad_click_r']
    infos = {k: X.overlay(R, base, k, model.parts[k], names.get(k, f'{k}.png')) for k in order}
    caps = X.render_caps(model, R)
    dot, trail, _ = X.sprites(R, meter=False)

    nodes = trig_nodes + [C.img_node(binfo)]
    for k in order[:-2]:
        nodes.append(C.showhide(model.parts[k]['expr'], C.img_node(infos[k])))
    for side, c in (('left', PAD_L), ('right', PAD_R)):
        nodes.append(C.showhide(f'touch_{side}:click', C.img_node(infos[f'pad_click_{side[0]}'])))
        nodes.append({'x': c[0], 'y': c[1], 'children': [X.trailpad(side, PAD_TRAVEL, trail, dot)]})
    nodes.append(X.stick_nodes('left', STICK, STICK_TRAVEL, caps['l']))

    rest = body.copy()
    inf = caps['l'][0]
    C.over(rest, X.load(R, inf), inf['x0'], inf['y0'])
    gyro = X.gyro_widget(R, rest, GYRO_C, GYRO_MAX)
    X.make_icon(R, rest)
    return nodes, gyro


if __name__ == '__main__':
    main()
