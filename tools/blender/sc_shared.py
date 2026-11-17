"""
Render/compose steps shared by render_sc2026.py and render_sc2015.py (see sc_common.py for the
low-level scene, material, PNG and image helpers).

A controller script builds a model object with:
    parts    {key: part}  pressable controls; part = dict(expr, objs, mats=[(Mat, strength)], region,
                          labels=[Mat], depress=px, tint=0..1, dirmask=(DirMask, 'n'|'e'|'s'|'w'))
    triggers {'l'|'r': dict(c, w, h, objs, mats, labels)}
    caps     {'l'|'r': dict(c, r, objs, floor, mat)}
and these helpers turn it into PNG parts + theme nodes.
"""
import math
import os

import bpy
import numpy as np

import sc_common as C
from sc_common import W, H, S

LABEL = (168, 174, 186)          # printed legends at rest
PRESS_LABEL = (225, 243, 255)    # legends on a lit (pressed) part
GLOW = 0.38                      # emission strength of a pressed part


def bbox_c(c, hx, hy):
    return (c[0] - hx, c[1] - hy, c[0] + hx, c[1] + hy)


def expand(reg, m):
    return (int(reg[0] - m), int(reg[1] - m), int(reg[2] + m), int(reg[3] + m))


class DirMask:
    """World-space mask for one quarter of a cross/disc around centre c, direction set per render.
    Lights points within 45 degrees of the direction whose distance along it is >= start px (and
    within r_max px of the centre, if given)."""

    def __init__(self, c, start, r_max=None):
        self.c, self.start, self.r_max = c, start, r_max
        self.nodes = []  # (dx, dy, all) value nodes, one set per material using this mask

    def __call__(self, nt, L):
        geo = nt.nodes.new('ShaderNodeNewGeometry')
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        L.new(geo.outputs['Position'], sep.inputs[0])
        cx, cy, _ = C.wpos(*self.c)
        x = C.math_node(nt, L, 'SUBTRACT', sep.outputs['X'], cx)
        y = C.math_node(nt, L, 'SUBTRACT', sep.outputs['Y'], cy)
        vdx = nt.nodes.new('ShaderNodeValue')
        vdy = nt.nodes.new('ShaderNodeValue')
        vall = nt.nodes.new('ShaderNodeValue')
        for v in (vdx, vdy, vall):
            v.outputs[0].default_value = 0
        self.nodes.append((vdx, vdy, vall))
        dx, dy = vdx.outputs[0], vdy.outputs[0]
        t = C.math_node(nt, L, 'ADD', C.math_node(nt, L, 'MULTIPLY', x, dx), C.math_node(nt, L, 'MULTIPLY', y, dy))
        s = C.math_node(nt, L, 'ABSOLUTE', C.math_node(nt, L, 'SUBTRACT', C.math_node(nt, L, 'MULTIPLY', y, dx),
                                                       C.math_node(nt, L, 'MULTIPLY', x, dy)))
        a = nt.nodes.new('ShaderNodeMapRange')
        a.inputs['From Min'].default_value = (self.start - 3) * S
        a.inputs['From Max'].default_value = (self.start + 1) * S
        L.new(t, a.inputs['Value'])
        b = nt.nodes.new('ShaderNodeMapRange')
        b.inputs['From Min'].default_value = -0.02
        b.inputs['From Max'].default_value = 0.02
        L.new(C.math_node(nt, L, 'SUBTRACT', t, s), b.inputs['Value'])
        m = C.math_node(nt, L, 'MULTIPLY', a.outputs[0], b.outputs[0])
        if self.r_max:
            r = C.math_node(nt, L, 'SQRT', C.math_node(nt, L, 'ADD', C.math_node(nt, L, 'MULTIPLY', x, x),
                                                       C.math_node(nt, L, 'MULTIPLY', y, y)))
            c = nt.nodes.new('ShaderNodeMapRange')
            c.inputs['From Min'].default_value = self.r_max * S
            c.inputs['From Max'].default_value = (self.r_max - 4) * S
            L.new(r, c.inputs['Value'])
            m = C.math_node(nt, L, 'MULTIPLY', m, c.outputs[0])
        return C.math_node(nt, L, 'MAXIMUM', m, vall.outputs[0])

    def set(self, d):
        """d in n/e/s/w lights that quarter, 'all' lights everything, None nothing."""
        v = {'n': (0, 1), 's': (0, -1), 'e': (1, 0), 'w': (-1, 0), None: (0, 0), 'all': (0, 0)}[d]
        for vdx, vdy, vall in self.nodes:
            vdx.outputs[0].default_value, vdy.outputs[0].default_value = v
            vall.outputs[0].default_value = 1.0 if d == 'all' else 0.0


def bumper_band(outline, side, x_lo, x_hi, out=15, inn=20):
    """Shoulder button following the shell's top edge (built on the left; mirrored for 'r')."""
    outer = C.offset_poly(outline, out)
    inner = C.offset_poly(outline, -inn)
    idx = [i for i, p in enumerate(outline) if x_lo <= p[0] <= x_hi and p[1] < 260]
    idx = idx[::max(1, len(idx) // 10)] + [idx[-1]]
    poly = C.round_poly([outer[i] for i in idx] + [inner[i] for i in idx][::-1], 9, steps=6, min_turn=30)
    poly = C.chaikin(poly, 3)
    if side == 'r':
        poly = [(W - x, y) for (x, y) in poly]
    return poly


def stick_cap_profile(top, R):
    """Concave rubber thumbstick: dished centre, raised knurled rim, rounded edge, short skirt."""
    rd = R - 10.0  # dish radius
    prof = []
    for i in range(14):
        r = rd * i / 13
        prof.append((r, top - 5.0 * (1 - (r / rd) ** 2)))
    for k in range(1, 9):  # rim crown rd .. R-4
        t = k / 8
        prof.append((rd + 6.0 * t, top + 1.4 * math.sin(math.pi * t * 0.75)))
    zc = top + 1.4 * math.sin(math.pi * 0.75)
    for k in range(1, 11):  # round over to the side
        a = (math.pi / 2) * k / 10
        prof.append((R - 4 + 4 * math.sin(a), zc - 4 + 4 * math.cos(a)))
    prof.append((R, zc - 12))
    prof.append((R - 5, zc - 17))
    prof.append((8, zc - 21))
    return prof


def stick_cap(name, c, floor, R, color=(40, 41, 46)):
    m = C.Mat(name, color, rough=0.72, spec=0.35,
              bump=C.knurl_bump(count=60, strength=0.5, r0=(R - 9) * S, r1=(R - 4) * S))
    ob = C.lathe(name, stick_cap_profile(floor + 30, R), c, 0, mat=m)
    return dict(c=c, r=R, objs=[ob], floor=floor, mat=m)


# ---------------------------------------------------------------- pressed state
def set_pressed(part, on):
    for (m, strength) in part['mats']:
        if on:
            m.glow(strength, tint_base=part.get('tint', 0.45))
        else:
            m.reset()
    for lm in part.get('labels', []):
        lm.set_color(part.get('label_on', PRESS_LABEL) if on else part.get('label_rest', LABEL))
    dz = part.get('depress', 2.0) * S * (-1 if on else 1)
    for ob in part['objs']:
        ob.location.z += dz
    if 'dirmask' in part:
        mask, d = part['dirmask']
        mask.set(d if on else None)


# ---------------------------------------------------------------- render steps
def render_base(R):
    """Objects-only base (reference for un-compositing overlays) and the final base with a soft
    contact shadow. Leaves the shadow catcher hidden for the part renders that follow."""
    catcher = bpy.data.objects['catcher']
    raw = R.render('base_raw')
    catcher.hide_render = True
    obj = R.render('base_obj')
    return obj, C.combine_shadow(raw, obj)


def save_overlay(R, base, img, reg, name):
    x0, y0, x1, y1 = [int(round(v)) for v in reg]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    ov = C.uncomposite(base[y0:y1, x0:x1], img[y0:y1, x0:x1])
    return R.save(name, ov, x0, y0)


def overlay(R, base, key, part, name):
    set_pressed(part, True)
    reg = part['region']
    img = R.render(key, expand(reg, 8))
    set_pressed(part, False)
    return save_overlay(R, base, img, reg, name)


def load(R, info):
    return C.read_png(os.path.join(R.out, info['file']))


def triggers(model, R, obj, final, split_y, click=False):
    """Trigger images are cut from the base render above split_y; the analog fill is the lit
    trigger (un-composited, cropped exactly to the trigger body so the pbar maps 0..1 onto it);
    with click=True a brighter full-pull overlay is made too. Returns theme nodes."""
    nodes, infos = [], {}
    for side, tr in model.triggers.items():
        c, tw, th = tr['c'], tr['w'], tr['h']
        x0, x1 = int(c[0] - tw / 2 - 12), int(c[0] + tw / 2 + 14)
        y0, y1 = 0, split_y
        info = R.save(f'trigger_{side}.png', final[y0:y1, x0:x1].copy(), x0, y0)
        ty0, ty1 = int(c[1] - th / 2 - 1), int(c[1] + th / 2 + 2)
        tx0, tx1 = int(c[0] - tw / 2 - 1), int(c[0] + tw / 2 + 2)
        part = dict(objs=[], mats=tr['mats'], labels=tr['labels'], depress=0)
        set_pressed(part, True)
        lit = R.render(f'trigger_{side}_lit', (x0 - 8, 0, x1 + 8, split_y + 8))
        ov = C.uncomposite(obj[y0:y1, x0:x1], lit[y0:y1, x0:x1], feather=1)
        finfo = R.save(f'trigger_{side}_fill.png', ov[ty0 - y0:ty1 - y0, tx0 - x0:tx1 - x0], tx0, ty0, crop=False)
        nodes.append(C.img_node(info))
        nodes.append(C.pbar(finfo, f'triggers:{side}:analog'))
        if click:
            for (m, s) in tr['mats']:
                m.glow(s * 2.4, tint_base=0.6)
            for ob in tr['objs']:
                ob.location.z -= 2 * S
            hot = R.render(f'trigger_{side}_click', (x0 - 8, 0, x1 + 8, split_y + 8))
            for ob in tr['objs']:
                ob.location.z += 2 * S
            reg = (x0, y0, x1, y1)
            ov2 = C.uncomposite(lit[y0:y1, x0:x1], hot[y0:y1, x0:x1], feather=1)
            cinfo = R.save(f'trigger_{side}_click.png', ov2, x0, y0)
            nodes.append(C.showhide(f'triggers:{side}:stage2', C.img_node(cinfo)))
        set_pressed(part, False)
        infos[side] = info
    return nodes


def render_caps(model, R):
    """Each stick cap alone over a shadow catcher at its well floor (rest + lit/clicked)."""
    hidden = []
    cap_objs = [ob for cap in model.caps.values() for ob in cap['objs']]
    for ob in bpy.context.scene.objects:
        if ob.type in ('MESH', 'FONT', 'CURVE') and ob.name != 'catcher' and ob not in cap_objs and not ob.hide_render:
            ob.hide_render = True
            hidden.append(ob)
    catcher = bpy.data.objects['catcher']
    old_z = catcher.location.z
    catcher.hide_render = False
    out = {}
    for side, cap in model.caps.items():
        for ob in cap['objs']:
            ob.hide_render = False
        catcher.location.z = cap['floor'] * S
        c = cap['c']
        reg = bbox_c(c, cap['r'] + 18, cap['r'] + 18)
        x0, y0, x1, y1 = [int(v) for v in reg]
        catcher.hide_render = False
        raw = R.render(f'cap_{side}_raw', expand(reg, 4))
        catcher.hide_render = True
        obj = R.render(f'cap_{side}', expand(reg, 4))
        rest = C.combine_shadow(raw[y0:y1, x0:x1], obj[y0:y1, x0:x1], spread=4.0, strength=0.9)
        a = R.save(f'stick_cap_{side}.png', rest, x0, y0)
        cap['mat'].glow(0.3, 0.4)
        img2 = R.render(f'cap_{side}_on', expand(reg, 4))
        cap['mat'].reset()
        b = R.save(f'stick_cap_{side}_on.png', img2[y0:y1, x0:x1], x0, y0)
        out[side] = (a, b)
        for ob in cap['objs']:
            ob.hide_render = True
    catcher.location.z = old_z
    catcher.hide_render = True
    for ob in hidden:
        ob.hide_render = False
    return out


def stick_nodes(side, c, travel, cap_pair):
    cap, cap_on = cap_pair
    return {'type': 'slider', 'x': c[0], 'y': c[1],
            'inputX': f'stick_{side}:x * {travel}', 'inputY': f'stick_{side}:y * {travel}',
            'children': [C.img_node(cap, cap['x'] - c[0], cap['y'] - c[1]),
                         C.showhide(f'stick_{side}:click', C.img_node(cap_on, cap_on['x'] - c[0], cap_on['y'] - c[1]))]}


def sprites(R, meter=True):
    """Touch dot, touch trail and (2026) pressure strip, built procedurally."""
    acc = np.array(C.ACCENT_SRGB, float) / 255
    n = 44
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    r = np.hypot(xx - n / 2, yy - n / 2)
    core = np.clip(10.5 - r, 0, 1)
    rim = np.clip(1.6 - np.abs(r - 10.0), 0, 1)
    glow = np.exp(-((r / 9.0) ** 2)) * 0.55
    img = np.zeros((n, n, 4))
    t = np.clip(r / 10.0, 0, 1)[..., None]
    col_core = (1 - t ** 3) * np.array([0.97, 0.99, 1.0]) + (t ** 3) * acc
    img[..., :3] = np.where(core[..., None] > 0, col_core, acc)
    img[..., 3] = np.maximum(core * 0.92, np.maximum(rim, glow))
    dot = R.save('pad_touch.png', img, -n / 2, -n / 2, crop=False)
    n = 36
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    r = np.hypot(xx - n / 2, yy - n / 2)
    img = np.zeros((n, n, 4))
    img[..., :3] = acc
    img[..., 3] = np.exp(-((r / 7.0) ** 2)) * 0.8
    trail = R.save('pad_trail.png', img, -n / 2, -n / 2, crop=False)
    if not meter:
        return dot, trail, None
    w, h = 9, 150
    yy, xx = np.mgrid[0:h, 0:w] + 0.5
    dx = np.abs(xx - w / 2)
    endfade = np.clip(np.minimum(yy, h - yy) / 6.0, 0, 1)
    img = np.zeros((h, w, 4))
    core = np.clip(1.6 - dx, 0, 1)
    img[..., :3] = core[..., None] * np.array([0.9, 0.98, 1.0]) + (1 - core[..., None]) * acc
    img[..., 3] = np.clip(np.exp(-(dx / 2.2) ** 2), 0, 1) * endfade
    m = R.save('pad_pressure.png', img, -w / 2, -h / 2, crop=False)
    return dot, trail, m


def trailpad(side, travel, trail, dot):
    return {'type': 'trailpad', 'image': trail['file'], 'x': 0, 'y': 0, 'width': trail['w'], 'height': trail['h'],
            'input': f'touch_{side}:0:touch',
            'inputX': f'touch_{side}:0:x * {travel}', 'inputY': f'touch_{side}:0:y * {travel}',
            'length': 24,
            'children': [C.showhide(f'touch_{side}:0:touch', C.img_node(dot, 0, 0))]}


def grip_sense(R, body, ylo=400, xin=300):
    """Accent halo around the lower outer grips (drawn behind the body)."""
    a = body[..., 3]
    halo = C.gauss(np.clip(C.gauss(a, 3) * 3, 0, 1), 9)
    nodes = []
    hh, ww = a.shape
    yy, xx = np.mgrid[0:hh, 0:ww]
    for side in 'lr':
        gx = xx / W if side == 'l' else 1 - xx / W
        ty = np.clip((yy - ylo) / 140.0, 0, 1)
        tx = np.clip((xin / W - gx) / 0.18, 0, 1)
        al = halo * ty * tx * 0.9
        img = np.zeros((hh, ww, 4))
        img[..., :3] = np.array(C.ACCENT_SRGB) / 255
        img[..., 3] = al
        img[al < 2 / 255] = 0
        info = R.save(f'grip_sense_{side}.png', img)
        nodes.append(C.showhide(f'grip_sense:{side}', C.img_node(info)))
    return nodes


def solid_crop(rest):
    solid = rest.copy()
    solid[solid[..., 3] < 0.6] = 0
    bx0, by0, bx1, by1 = C.alpha_bbox(solid, 2)
    return rest[by0:by1, bx0:bx1]


def gyro_widget(R, rest, center, maxwh):
    """basic3d1 gyro widget: a small copy of the rendered controller plus four edge-shading images."""
    crop = solid_crop(rest)
    sc = min(maxwh[0] / crop.shape[1], maxwh[1] / crop.shape[0])
    nw, nh = int(round(crop.shape[1] * sc)), int(round(crop.shape[0] * sc))
    small = C.resize_area(crop, nw, nh)
    small[..., 3] = np.where(small[..., 3] < 0.5 / 255, 0, small[..., 3])
    gi = R.save('gyro.png', small, 0, 0, crop=False)
    a = small[..., 3]
    hh, ww = a.shape
    yy, xx = np.mgrid[0:hh, 0:ww] + 0.5
    acc = np.array(C.ACCENT_SRGB) / 255
    names = {}
    for key, g in (('l', 1 - xx / ww), ('r', xx / ww), ('u', 1 - yy / hh), ('d', yy / hh)):
        shade = np.clip((g - 0.35) / 0.65, 0, 1) ** 1.6
        edge = np.clip((a - C.gauss(a, 2)) * 4, 0, 1) * np.clip((g - 0.55) / 0.45, 0, 1)
        img = np.zeros((hh, ww, 4))
        img[..., :3] = edge[..., None] * acc
        img[..., 3] = np.clip(shade * 0.55 + edge * 0.9, 0, 1) * a
        names[key] = R.save(f'gyro_{key}.png', img, 0, 0, crop=False)['file']
    node = {'type': 'basic3d1', 'image': gi['file'], 'x': center[0], 'y': center[1], 'width': nw, 'height': nh,
            'mode': 'gyro', 'shadowl': names['l'], 'shadowr': names['r'], 'shadowu': names['u'], 'shadowd': names['d']}
    node.update(C.INTERP)
    return node


def make_icon(R, rest):
    crop = solid_crop(rest)
    sc = 32 / max(crop.shape[:2])
    small = C.resize_area(crop, max(1, int(round(crop.shape[1] * sc))), max(1, int(round(crop.shape[0] * sc))))
    canvas = np.zeros((32, 32, 4))
    C.over(canvas, small, (32 - small.shape[1]) // 2, (32 - small.shape[0]) // 2)
    C.write_png(os.path.join(R.out, 'icon.png'), canvas)


def compose(R, nodes, pressed, bg=None):
    """Composite a theme node list the way the engine does (no rotation support needed except the
    pad groups, whose children here are only sprites at the group origin). pressed: set of input
    expressions treated as active; sliders at rest; trailpads/dots drawn at the group origin."""
    canvas = np.zeros((H, W, 4)) if bg is None else bg.copy()
    cache = {}

    def img(name):
        if name not in cache:
            cache[name] = C.read_png(os.path.join(R.out, name))
        return cache[name]

    def walk(n, ox, oy, rot):
        t = n.get('type')
        lx, ly = n.get('x', 0), n.get('y', 0)
        cr, sr = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        x, y = ox + lx * cr - ly * sr, oy + lx * sr + ly * cr
        if t == 'showhide':
            if n['input'] not in pressed:
                return
        if t in ('image', 'pbar') and 'image' in n:
            im = img(n['image'])
            if t == 'pbar' and n['input'] not in pressed:
                return
            C.over(canvas, im, int(round(x - n['width'] / 2)), int(round(y - n['height'] / 2)))
        if t == 'trailpad':
            if n['input'] not in pressed:
                return
        if t == 'basic3d1':
            im = img(n['image'])
            C.over(canvas, im, int(round(x - n['width'] / 2)), int(round(y - n['height'] / 2)))
        for ch in n.get('children', []):
            walk(ch, x, y, rot + n.get('rot', 0))
    for n in nodes:
        walk(n, 0, 0, 0)
    return canvas


def all_inputs(nodes):
    out = set()

    def walk(n):
        if 'input' in n:
            out.add(n['input'])
        for ch in n.get('children', []):
            walk(ch)
    for n in nodes:
        walk(n)
    return out
