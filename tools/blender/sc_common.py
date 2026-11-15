"""
Shared Blender (bpy) helpers for the "Realistic" Steam Controller overlay themes.

This module is imported by render_sc2026.py and render_sc2015.py; it is not run on its own.
Everything is procedural: geometry is generated from 2D layouts in theme pixels, materials are
node-built plastics/rubbers, lighting is a few area lights plus a gradient world. No external
models, textures, HDRIs or fonts are used (text uses Blender's built-in font).

Coordinate system
-----------------
Layouts are written in *theme pixels* (x right, y down, canvas W x H = 1000 x 760), exactly like
the hand-drawn graphite themes. One theme pixel is 0.01 Blender units; heights (z) also use the
pixel scale, so "z = 6" means the surface sits 6 theme pixels above the reference plane. An
orthographic camera looks straight down at the controller face, so every rendered pixel lines up
1:1 with the theme canvas.

Pipeline (see Renderer below)
-----------------------------
1. The base frame is rendered once at full size (sticks removed, every control at rest).
2. Each pressable control is switched to its "pressed" state (pushed in slightly and lit with an
   accent-coloured emission) and only its neighbourhood is re-rendered (render border).
3. The pressed crop is "un-composited" against the base: for every pixel we solve for the
   smallest alpha (and matching colour) that reproduces the pressed pixel when drawn over the base
   pixel. The result is a tight RGBA overlay that the engine can show/hide on top of base.png and
   that reproduces the pressed render exactly (including glow spilling onto the shell).
4. Moving parts (stick caps) are rendered on their own over a shadow catcher, so the sprite
   carries its own contact shadow.
5. Small UI sprites (touch dot, trail, pressure strip, grip-sense halo, gyro shading) are built
   with numpy from the renders / analytic shapes.

PNG files are written by a small numpy + zlib encoder (best-of-five row filters, level 9).
"""
import json
import math
import os
import struct
import sys
import time
import zlib

import bpy
import numpy as np
from mathutils import geometry as mgeo

W, H = 1000, 760
S = 0.01  # Blender units per theme pixel

ACCENT_SRGB = (54, 196, 255)  # same accent as the graphite themes


def log(*a):
    print('[sc]', *a, flush=True)


def srgb_to_lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lin(rgb):
    return tuple(srgb_to_lin(v) for v in rgb) + (1.0,)


ACCENT = lin(ACCENT_SRGB)


def wpos(x, y, z=0.0):
    """theme px -> world"""
    return ((x - W / 2) * S, (H / 2 - y) * S, z * S)


# ----------------------------------------------------------------------------- 2D geometry helpers
def chaikin(pts, it=5, closed=True):
    pts = [tuple(p) for p in pts]
    for _ in range(it):
        nxt = []
        n = len(pts)
        rng = range(n) if closed else range(n - 1)
        for i in rng:
            p, q = pts[i], pts[(i + 1) % n]
            nxt.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            nxt.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        if not closed:
            nxt = [pts[0]] + nxt + [pts[-1]]
        pts = nxt
    return pts


def mirrored_outline(left, it=5):
    """left: control points from top-centre round the left side to bottom-centre (x <= W/2)."""
    right = [(W - x, y) for (x, y) in reversed(left[1:-1])]
    return chaikin(left + right, it)


def rrect_pts(cx, cy, w, h, r, rot_deg=0.0, steps=10):
    """Rounded rectangle polygon (screen coords), rotated clockwise on screen by rot_deg."""
    pts = []
    corners = [(w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180)]
    for (ox, oy, a0) in corners:
        for s in range(steps + 1):
            a = math.radians(a0 + 90 * s / steps)
            pts.append((ox + r * math.cos(a), oy + r * math.sin(a)))
    t = math.radians(rot_deg)
    c, s_ = math.cos(t), math.sin(t)
    return [(cx + x * c - y * s_, cy + x * s_ + y * c) for (x, y) in pts]


def round_poly(pts, r, steps=6, min_turn=0.0):
    """Round the corners of a (sharp) polygon with radius r (fillets). Corners turning less than
    min_turn degrees are left alone."""
    out = []
    n = len(pts)
    for i in range(n):
        p0, p1, p2 = np.array(pts[i - 1], float), np.array(pts[i], float), np.array(pts[(i + 1) % n], float)
        a, b = p0 - p1, p2 - p1
        la, lb = np.linalg.norm(a), np.linalg.norm(b)
        a, b = a / la, b / lb
        ang = math.acos(max(-1.0, min(1.0, float(a @ b))))
        if ang > math.pi - 1e-3 or (math.pi - ang) < math.radians(min_turn):
            out.append(tuple(p1))
            continue
        t = r / math.tan(ang / 2)
        t = min(t, la / 2, lb / 2)
        rr = t * math.tan(ang / 2)
        s0, s1 = p1 + a * t, p1 + b * t
        bis = a + b
        bis /= np.linalg.norm(bis)
        c = p1 + bis * (rr / math.sin(ang / 2))
        a0 = math.atan2(s0[1] - c[1], s0[0] - c[0])
        a1 = math.atan2(s1[1] - c[1], s1[0] - c[0])
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        for k in range(steps + 1):
            aa = a0 + da * k / steps
            out.append((c[0] + rr * math.cos(aa), c[1] + rr * math.sin(aa)))
    return out


def poly_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        a += x0 * y1 - x1 * y0
    return a / 2


def offset_poly(pts, d):
    """Offset a smooth closed polygon outward by d (screen coords, any winding)."""
    P = np.array(pts, float)
    if poly_area(pts) < 0:  # make clockwise-on-screen == positive area in y-down coords
        P = P[::-1]
    nxt, prv = np.roll(P, -1, 0), np.roll(P, 1, 0)
    t = nxt - prv
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    nrm = np.stack([t[:, 1], -t[:, 0]], 1)  # outward for positive-area (y-down) polygons
    Q = P + nrm * d
    if poly_area(pts) < 0:
        Q = Q[::-1]
    return [tuple(q) for q in Q]


# ----------------------------------------------------------------------------- SDFs (numpy, theme px)
def sdf_polygon(px, py, poly, chunk=6000):
    """Signed distance (positive inside) from points to a closed polygon."""
    P = np.asarray(poly, np.float64)
    A = P
    B = np.roll(P, -1, 0)
    ax, ay, bx, by = A[:, 0], A[:, 1], B[:, 0], B[:, 1]
    ex, ey = bx - ax, by - ay
    l2 = np.maximum(ex * ex + ey * ey, 1e-12)
    out = np.empty(px.shape[0], np.float64)
    for s in range(0, px.shape[0], chunk):
        x = px[s:s + chunk, None]
        y = py[s:s + chunk, None]
        dx, dy = x - ax, y - ay
        t = np.clip((dx * ex + dy * ey) / l2, 0, 1)
        qx, qy = dx - t * ex, dy - t * ey
        d = np.sqrt(np.min(qx * qx + qy * qy, axis=1))
        cond = (ay > y) != (by > y)
        xint = ax + (y - ay) * ex / np.where(np.abs(ey) < 1e-12, 1e-12, ey)
        inside = (np.sum(cond & (x < xint), axis=1) % 2) == 1
        out[s:s + chunk] = np.where(inside, d, -d)
    return out


def sdf_circle(px, py, c, r):
    return r - np.hypot(px - c[0], py - c[1])


def sdf_rrect(px, py, c, w, h, r, rot_deg=0.0):
    t = math.radians(rot_deg)
    dx, dy = px - c[0], py - c[1]
    lx = dx * math.cos(t) + dy * math.sin(t)
    ly = -dx * math.sin(t) + dy * math.cos(t)
    qx = np.abs(lx) - (w / 2 - r)
    qy = np.abs(ly) - (h / 2 - r)
    outside = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0)
    return -(outside - r)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def round_edge(d, R):
    """Quarter-circle bullnose profile 0..1 over the first R px inside an edge."""
    t = np.clip(d / R, 0, 1)
    return np.sqrt(np.clip(1 - (1 - t) ** 2, 0, 1))


# ----------------------------------------------------------------------------- scene
def reset_scene(samples=96):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    cy = sc.cycles
    cy.device = 'CPU'
    cy.samples = samples
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.006
    cy.use_denoising = True
    cy.denoiser = 'OPENIMAGEDENOISE'
    try:
        cy.denoising_prefilter = 'ACCURATE'
        cy.denoising_quality = 'HIGH'
    except Exception:
        pass
    cy.seed = 7
    cy.max_bounces = 6
    cy.diffuse_bounces = 3
    cy.glossy_bounces = 3
    cy.transparent_max_bounces = 8
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    cy.blur_glossy = 1.0
    sc.render.film_transparent = True
    sc.render.resolution_x, sc.render.resolution_y = W, H
    sc.render.resolution_percentage = 100
    sc.render.pixel_aspect_x = sc.render.pixel_aspect_y = 1
    sc.render.filter_size = 1.2
    sc.render.dither_intensity = 0.0
    sc.render.use_persistent_data = True
    sc.render.threads_mode = 'AUTO'
    im = sc.render.image_settings
    im.file_format = 'PNG'
    im.color_mode = 'RGBA'
    im.color_depth = '8'
    im.compression = 0
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0
    sc.display_settings.display_device = 'sRGB'

    cam_data = bpy.data.cameras.new('cam')
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = W * S
    cam_data.sensor_fit = 'HORIZONTAL'
    cam_data.clip_start = 0.1
    cam_data.clip_end = 100
    cam = bpy.data.objects.new('cam', cam_data)
    cam.location = (0, 0, 30)
    sc.collection.objects.link(cam)
    sc.camera = cam
    return sc


def world_studio(sc, strength=0.22):
    wd = bpy.data.worlds.new('studio')
    sc.world = wd
    wd.use_nodes = True
    nt = wd.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new('ShaderNodeTexCoord')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(tc.outputs['Generated'], sep.inputs[0])
    # brightness by elevation (z) with a softbox-ish band toward +y
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.02, 0.02, 0.022, 1)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.9, 0.92, 0.95, 1)
    mapr = nt.nodes.new('ShaderNodeMapRange')
    mapr.inputs['From Min'].default_value = -0.2
    mapr.inputs['From Max'].default_value = 1.0
    nt.links.new(sep.outputs['Z'], mapr.inputs['Value'])
    nt.links.new(mapr.outputs[0], ramp.inputs['Fac'])
    bg = nt.nodes.new('ShaderNodeBackground')
    bg.inputs['Strength'].default_value = strength
    nt.links.new(ramp.outputs['Color'], bg.inputs['Color'])
    out = nt.nodes.new('ShaderNodeOutputWorld')
    nt.links.new(bg.outputs[0], out.inputs['Surface'])
    return wd


def area_light(name, loc, target, size, energy, color=(1, 1, 1), size_y=None):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = energy
    ld.color = color
    if size_y:
        ld.shape = 'RECTANGLE'
        ld.size, ld.size_y = size, size_y
    else:
        ld.shape = 'DISK'
        ld.size = size
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    d = np.array(target, float) - np.array(loc, float)
    from mathutils import Vector
    ob.rotation_euler = Vector(d).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.collection.objects.link(ob)
    return ob


def studio_lights():
    # big soft key from the top-left (as held, i.e. above the far edge), soft fill, low rim
    area_light('key', (-4.0, 6.0, 9.0), (0, 0, 0), 9.0, 1100, (1.0, 0.98, 0.95))
    area_light('fill', (6.0, -3.0, 7.0), (0, 0, 0), 10.0, 260, (0.92, 0.96, 1.0))
    area_light('top', (0.0, 0.0, 14.0), (0, 0, 0), 12.0, 380, (1, 1, 1))
    area_light('rim', (0.0, 9.0, 1.2), (0, 0, 0), 14.0, 260, (1, 1, 1), size_y=1.0)


# ----------------------------------------------------------------------------- materials
class Mat:
    """A Principled material with a controllable accent glow.

    glow(strength) sets the emission strength; mask_fn(nt, links) may return a socket (0..1)
    multiplied into the emission so only part of the surface lights up.
    """

    def __init__(self, name, color_srgb, rough=0.45, spec=0.5, coat=0.0, bump=None, mask_fn=None,
                 alpha_attr=None, emit_color=None, sheen=0.0):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        nt = m.node_tree
        L = nt.links
        bsdf = nt.nodes['Principled BSDF']
        self.m, self.nt, self.bsdf = m, nt, bsdf
        bsdf.inputs['Roughness'].default_value = rough
        bsdf.inputs['Specular IOR Level'].default_value = spec
        bsdf.inputs['Coat Weight'].default_value = coat
        bsdf.inputs['Coat Roughness'].default_value = 0.25
        bsdf.inputs['Sheen Weight'].default_value = sheen
        bsdf.inputs['Emission Color'].default_value = emit_color or ACCENT
        self.base_color = lin(color_srgb)
        # base colour = mix(base, accent, tint * mask); emission strength = value * mask
        self.rgb = nt.nodes.new('ShaderNodeRGB')
        self.rgb.outputs[0].default_value = self.base_color
        self.val = nt.nodes.new('ShaderNodeValue')
        self.val.outputs[0].default_value = 0.0
        self.tint = nt.nodes.new('ShaderNodeValue')
        self.tint.outputs[0].default_value = 0.0
        mask = mask_fn(nt, L) if mask_fn is not None else None
        if mask is not None:
            L.new(math_node(nt, L, 'MULTIPLY', self.val.outputs[0], mask), bsdf.inputs['Emission Strength'])
            fac = math_node(nt, L, 'MULTIPLY', self.tint.outputs[0], mask)
        else:
            L.new(self.val.outputs[0], bsdf.inputs['Emission Strength'])
            fac = self.tint.outputs[0]
        mix = nt.nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        L.new(fac, mix.inputs['Factor'])
        L.new(self.rgb.outputs[0], mix.inputs[6])
        mix.inputs[7].default_value = ACCENT
        L.new(mix.outputs[2], bsdf.inputs['Base Color'])
        if bump is not None:
            L.new(bump(nt, L), bsdf.inputs['Normal'])
        if alpha_attr:
            a = nt.nodes.new('ShaderNodeAttribute')
            a.attribute_name = alpha_attr
            L.new(a.outputs['Fac'], bsdf.inputs['Alpha'])

    def glow(self, strength, tint_base=0.45):
        """Light the part: accent emission plus an accent tint of the base colour, as if the plastic
        were translucent and backlit (both limited to the mask, when the material has one)."""
        self.val.outputs[0].default_value = strength
        self.tint.outputs[0].default_value = float(tint_base or 0) if strength > 0 else 0.0

    def set_color(self, srgb):
        self.rgb.outputs[0].default_value = lin(srgb)

    def reset(self):
        self.val.outputs[0].default_value = 0.0
        self.tint.outputs[0].default_value = 0.0
        self.rgb.outputs[0].default_value = self.base_color


def noise_bump(scale=900.0, strength=0.08, detail=6.0, distance=0.002):
    def f(nt, L):
        tc = nt.nodes.new('ShaderNodeTexCoord')
        nz = nt.nodes.new('ShaderNodeTexNoise')
        nz.inputs['Scale'].default_value = scale
        nz.inputs['Detail'].default_value = detail
        L.new(tc.outputs['Object'], nz.inputs['Vector'])
        b = nt.nodes.new('ShaderNodeBump')
        b.inputs['Strength'].default_value = strength
        b.inputs['Distance'].default_value = distance
        L.new(nz.outputs['Fac'], b.inputs['Height'])
        return b.outputs['Normal']
    return f


def rings_bump(scale=180.0, strength=0.06, noise_strength=0.05):
    """Fine concentric grooves (2015 trackpads) plus a little noise."""
    def f(nt, L):
        tc = nt.nodes.new('ShaderNodeTexCoord')
        wv = nt.nodes.new('ShaderNodeTexWave')
        wv.wave_type = 'RINGS'
        wv.inputs['Scale'].default_value = scale
        wv.inputs['Distortion'].default_value = 0.0
        L.new(tc.outputs['Object'], wv.inputs['Vector'])
        nz = nt.nodes.new('ShaderNodeTexNoise')
        nz.inputs['Scale'].default_value = 900
        L.new(tc.outputs['Object'], nz.inputs['Vector'])
        mix = nt.nodes.new('ShaderNodeMath')
        mix.operation = 'MULTIPLY_ADD'
        mix.inputs[1].default_value = noise_strength / max(strength, 1e-6)
        L.new(nz.outputs['Fac'], mix.inputs[0])
        L.new(wv.outputs['Fac'], mix.inputs[2])
        b = nt.nodes.new('ShaderNodeBump')
        b.inputs['Strength'].default_value = strength
        b.inputs['Distance'].default_value = 0.002
        L.new(mix.outputs[0], b.inputs['Height'])
        return b.outputs['Normal']
    return f


def knurl_bump(count=48, strength=0.35, r0=0.34, r1=0.40):
    """Radial ridges around a stick cap rim (object space, z-up)."""
    def f(nt, L):
        tc = nt.nodes.new('ShaderNodeTexCoord')
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        L.new(tc.outputs['Object'], sep.inputs[0])
        at = nt.nodes.new('ShaderNodeMath')
        at.operation = 'ARCTAN2'
        L.new(sep.outputs['Y'], at.inputs[0])
        L.new(sep.outputs['X'], at.inputs[1])
        mul = nt.nodes.new('ShaderNodeMath')
        mul.operation = 'MULTIPLY'
        mul.inputs[1].default_value = count
        L.new(at.outputs[0], mul.inputs[0])
        sn = nt.nodes.new('ShaderNodeMath')
        sn.operation = 'SINE'
        L.new(mul.outputs[0], sn.inputs[0])
        # only on the rim: radius mask
        ln = nt.nodes.new('ShaderNodeVectorMath')
        ln.operation = 'LENGTH'
        cmb = nt.nodes.new('ShaderNodeCombineXYZ')
        L.new(sep.outputs['X'], cmb.inputs['X'])
        L.new(sep.outputs['Y'], cmb.inputs['Y'])
        L.new(cmb.outputs[0], ln.inputs[0])
        return sn, ln, L, nt
    def g(nt, L):
        sn, ln, L, nt = f(nt, L)
        rng = nt.nodes.new('ShaderNodeMapRange')
        rng.inputs['From Min'].default_value = r0
        rng.inputs['From Max'].default_value = r1
        L.new(ln.outputs['Value'], rng.inputs['Value'])
        m2 = nt.nodes.new('ShaderNodeMath')
        m2.operation = 'MULTIPLY'
        L.new(sn.outputs[0], m2.inputs[0])
        L.new(rng.outputs[0], m2.inputs[1])
        b = nt.nodes.new('ShaderNodeBump')
        b.inputs['Strength'].default_value = strength
        b.inputs['Distance'].default_value = 0.003
        L.new(m2.outputs[0], b.inputs['Height'])
        return b.outputs['Normal']
    return g


def math_node(nt, L, op, a, b=None, v=None):
    n = nt.nodes.new('ShaderNodeMath')
    n.operation = op
    if isinstance(a, (int, float)):
        n.inputs[0].default_value = a
    else:
        L.new(a, n.inputs[0])
    if b is not None:
        if isinstance(b, (int, float)):
            n.inputs[1].default_value = b
        else:
            L.new(b, n.inputs[1])
    return n.outputs[0]


class RingMask:
    """World-space ring mask for the body shell (used for the stick-touch light rings).
    The ring centre is set per render, so one material serves any number of rings."""

    def __init__(self):
        self.cx = self.cy = None

    def __call__(self, nt, L):
        tc = nt.nodes.new('ShaderNodeNewGeometry')
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        L.new(tc.outputs['Position'], sep.inputs[0])
        self.cx = nt.nodes.new('ShaderNodeValue')
        self.cy = nt.nodes.new('ShaderNodeValue')
        self.r = nt.nodes.new('ShaderNodeValue')
        self.cx.outputs[0].default_value = 999
        self.cy.outputs[0].default_value = 999
        self.r.outputs[0].default_value = 0.6
        dx = math_node(nt, L, 'SUBTRACT', sep.outputs['X'], self.cx.outputs[0])
        dy = math_node(nt, L, 'SUBTRACT', sep.outputs['Y'], self.cy.outputs[0])
        d = math_node(nt, L, 'SQRT', math_node(nt, L, 'ADD', math_node(nt, L, 'MULTIPLY', dx, dx), math_node(nt, L, 'MULTIPLY', dy, dy)))
        e = math_node(nt, L, 'ABSOLUTE', math_node(nt, L, 'SUBTRACT', d, self.r.outputs[0]))
        m = nt.nodes.new('ShaderNodeMapRange')
        m.inputs['From Min'].default_value = 0.035
        m.inputs['From Max'].default_value = 0.0
        L.new(e, m.inputs['Value'])
        return m.outputs[0]

    def set(self, c, r):
        x, y, _ = wpos(*c)
        self.cx.outputs[0].default_value = x
        self.cy.outputs[0].default_value = y
        self.r.outputs[0].default_value = r * S

    def off(self):
        self.cx.outputs[0].default_value = 999


# ----------------------------------------------------------------------------- meshes
def link(ob):
    bpy.context.scene.collection.objects.link(ob)
    return ob


def mesh_from_arrays(name, co, faces_quads=None, tris=None, smooth=True, mat=None):
    me = bpy.data.meshes.new(name)
    co = np.asarray(co, np.float32)
    me.vertices.add(len(co))
    me.vertices.foreach_set('co', co.ravel())
    polys = []
    if faces_quads is not None and len(faces_quads):
        polys.append((np.asarray(faces_quads, np.int32), 4))
    if tris is not None and len(tris):
        polys.append((np.asarray(tris, np.int32), 3))
    loops = np.concatenate([p.ravel() for p, _ in polys])
    sizes = np.concatenate([np.full(len(p), k, np.int32) for p, k in polys])
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]]).astype(np.int32)
    me.loops.add(len(loops))
    me.loops.foreach_set('vertex_index', loops)
    me.polygons.add(len(sizes))
    me.polygons.foreach_set('loop_start', starts)
    me.update(calc_edges=True)
    if smooth:
        me.shade_smooth()
    if mat is not None:
        me.materials.append(mat.m if isinstance(mat, Mat) else mat)
    ob = bpy.data.objects.new(name, me)
    return link(ob)


def heightfield(name, bbox, height_fn, sdf_fn, mat):
    """Body shell as a 1px heightfield with an anti-aliased alpha attribute ('mask').

    bbox: (x0,y0,x1,y1) theme px; height_fn(px,py,d) -> z px; sdf_fn(px,py) -> signed distance.
    """
    t0 = time.time()
    x0, y0, x1, y1 = [int(v) for v in bbox]
    xs = np.arange(x0, x1 + 1, dtype=np.float64)
    ys = np.arange(y0, y1 + 1, dtype=np.float64)
    gx, gy = np.meshgrid(xs, ys)
    px, py = gx.ravel(), gy.ravel()
    d = sdf_fn(px, py)
    z = height_fn(px, py, d)
    z = np.where(d > 0, z, 0.0)
    nx, ny = len(xs), len(ys)
    keepv = (d > -2.5).reshape(ny, nx)
    # quads whose 4 corners are all near/inside
    q = keepv[:-1, :-1] & keepv[1:, :-1] & keepv[:-1, 1:] & keepv[1:, 1:]
    jj, ii = np.nonzero(q)
    idx = lambda j, i: j * nx + i
    quads = np.stack([idx(jj, ii), idx(jj + 1, ii), idx(jj + 1, ii + 1), idx(jj, ii + 1)], 1)  # CCW in world (y flipped)
    used = np.zeros(nx * ny, bool)
    used[quads.ravel()] = True
    remap = -np.ones(nx * ny, np.int64)
    remap[used] = np.arange(used.sum())
    quads = remap[quads]
    co = np.stack([(px[used] - W / 2) * S, (H / 2 - py[used]) * S, z[used] * S], 1)
    ob = mesh_from_arrays(name, co, faces_quads=quads, mat=mat)
    att = ob.data.attributes.new('mask', 'FLOAT', 'POINT')
    att.data.foreach_set('value', np.clip(d[used] + 0.5, 0, 1).astype(np.float32))
    log(f'heightfield {name}: {len(co)} verts in {time.time() - t0:.1f}s')
    return ob


def lathe(name, profile, center, z0=0.0, segs=128, mat=None):
    """Surface of revolution. profile: list of (r_px, z_px) from the axis (top) outward/downward."""
    prof = [(float(r), float(z)) for r, z in profile]
    verts, quads, tris = [], [], []
    ring_index = []
    for (r, z) in prof:
        if r < 1e-6:
            ring_index.append([len(verts)])
            verts.append((0.0, 0.0, z * S))
        else:
            idxs = []
            for k in range(segs):
                a = 2 * math.pi * k / segs
                idxs.append(len(verts))
                verts.append((r * S * math.cos(a), r * S * math.sin(a), z * S))
            ring_index.append(idxs)
    for a, b in zip(ring_index[:-1], ring_index[1:]):
        if len(a) == 1 and len(b) > 1:
            for k in range(segs):
                tris.append((a[0], b[k], b[(k + 1) % segs]))
        elif len(a) > 1 and len(b) == 1:
            for k in range(segs):
                tris.append((a[k], b[0], a[(k + 1) % segs]))
        else:
            for k in range(segs):
                quads.append((a[k], b[k], b[(k + 1) % segs], a[(k + 1) % segs]))
    ob = mesh_from_arrays(name, verts, faces_quads=quads, tris=tris, mat=mat)
    ob.location = wpos(center[0], center[1], z0)
    fix_normals(ob)
    return ob


def fix_normals(ob):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.shade_smooth()


def arc_profile(top_z, r_outer, bevel, bottom_z, dome=0.0, steps=10, inner=None):
    """(r,z) profile for a round button: domed/dished top, rounded edge, straight side.
    dome > 0 raises the centre, dome < 0 dishes it."""
    prof = []
    rt = r_outer - bevel
    n = 12
    for i in range(n + 1):
        r = rt * i / n
        prof.append((r, top_z + dome * (1 - (r / rt) ** 2) if rt > 0 else top_z))
    for k in range(1, steps + 1):
        a = (math.pi / 2) * k / steps
        prof.append((rt + bevel * math.sin(a), top_z - bevel + bevel * math.cos(a)))
    prof.append((r_outer, bottom_z))
    return prof


def slab(name, poly, top_z, bevel, bottom_z, mat=None, steps=8):
    """Extruded 2D shape (theme px polygon) with a quarter-round top edge of radius bevel."""
    pts = list(poly)
    if poly_area(pts) > 0:  # want counter-clockwise in world coords == negative area in y-down screen
        pts = pts[::-1]
    n = len(pts)
    rings = []  # (offset, z)
    rings.append((0.0, bottom_z))
    for k in range(steps + 1):
        a = (math.pi / 2) * k / steps
        rings.append((-bevel * (1 - math.cos(a)), top_z - bevel + bevel * math.sin(a)))
    verts, quads = [], []
    for (off, z) in rings:
        ring = offset_poly(pts, off) if off != 0 else pts
        for (x, y) in ring:
            verts.append(((x - W / 2) * S, (H / 2 - y) * S, z * S))
    for r in range(len(rings) - 1):
        a0, b0 = r * n, (r + 1) * n
        for k in range(n):
            quads.append((a0 + k, a0 + (k + 1) % n, b0 + (k + 1) % n, b0 + k))
    top = offset_poly(pts, -bevel)
    tri = mgeo.tessellate_polygon([[(x, -y, 0) for (x, y) in top]])
    base = (len(rings) - 1) * n
    tris = [(base + a, base + b, base + c) for (a, b, c) in tri]
    ob = mesh_from_arrays(name, verts, faces_quads=quads, tris=tris, mat=mat)
    fix_normals(ob)
    # flat-shade the cap so the triangulation never shows
    me = ob.data
    sm = np.ones(len(me.polygons), bool)
    sm[len(quads):] = False
    me.polygons.foreach_set('use_smooth', sm)
    me.update()
    return ob


def text_obj(name, s, center, z, size_px, mat, extrude_px=0.4, rot_deg=0.0, bold=False):
    cu = bpy.data.curves.new(name, 'FONT')
    cu.body = s
    cu.size = size_px * S
    cu.align_x = 'CENTER'
    cu.align_y = 'CENTER'
    cu.extrude = extrude_px * S
    cu.resolution_u = 6
    if bold:
        cu.offset = 0.35 * S
    ob = bpy.data.objects.new(name, cu)
    ob.location = wpos(center[0], center[1], z)
    ob.rotation_euler = (0, 0, -math.radians(rot_deg))
    cu.materials.append(mat.m if isinstance(mat, Mat) else mat)
    return link(ob)


def shadow_catcher(z_px, size=14.0):
    me = bpy.data.meshes.new('catcher')
    s = size / 2
    me.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new('catcher', me)
    ob.location = (0, 0, z_px * S)
    ob.is_shadow_catcher = True
    m = bpy.data.materials.new('catcher')
    me.materials.append(m)
    return link(ob)


# ----------------------------------------------------------------------------- PNG IO
def write_png(path, arr):
    """arr: HxWx4 float (0..1, straight alpha, display-referred) or uint8."""
    if arr.dtype != np.uint8:
        arr = np.clip(np.round(arr * 255.0), 0, 255).astype(np.uint8)
    # zero colour where fully transparent: compresses better
    arr = arr.copy()
    arr[arr[..., 3] == 0] = 0
    h, w, _ = arr.shape
    raw = arr.reshape(h, w * 4).astype(np.int16)
    bpp = 4
    left = np.zeros_like(raw)
    left[:, bpp:] = raw[:, :-bpp]
    up = np.zeros_like(raw)
    up[1:] = raw[:-1]
    ul = np.zeros_like(raw)
    ul[1:, bpp:] = raw[:-1, :-bpp]
    p = left + up - ul
    pa, pb, pc = np.abs(p - left), np.abs(p - up), np.abs(p - ul)
    paeth = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, up, ul))
    cands = [raw, raw - left, raw - up, raw - ((left + up) >> 1), raw - paeth]
    cands = [(c & 0xFF).astype(np.uint8) for c in cands]
    score = np.stack([np.abs(c.astype(np.int8).astype(np.int32)).sum(1) for c in cands], 1)
    best = score.argmin(1)
    rows = np.empty((h, w * 4 + 1), np.uint8)
    rows[:, 0] = best
    for f in range(5):
        sel = best == f
        rows[sel, 1:] = cands[f][sel]
    data = zlib.compress(rows.tobytes(), 9)

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + chunk(b'IDAT', data) + chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)


def read_png(path):
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return a.reshape(h, w, 4)[::-1].copy()


# ----------------------------------------------------------------------------- image ops
def box_blur(a, r):
    """separable box blur on a 2D array (radius r, int)"""
    if r < 1:
        return a
    k = 2 * r + 1
    p = np.pad(a, ((r + 1, r), (0, 0)), mode='edge')
    c = np.cumsum(p, 0)
    a = (c[k:] - c[:-k]) / k
    p = np.pad(a, ((0, 0), (r + 1, r)), mode='edge')
    c = np.cumsum(p, 1)
    return (c[:, k:] - c[:, :-k]) / k


def gauss(a, sigma):
    r = max(1, int(round(sigma * 0.9)))
    for _ in range(3):
        a = box_blur(a, r)
    return a


def over(dst, src, x, y):
    """alpha-composite src (straight RGBA float) onto dst at integer x,y (both straight)."""
    h, w = src.shape[:2]
    X0, Y0 = max(0, x), max(0, y)
    X1, Y1 = min(dst.shape[1], x + w), min(dst.shape[0], y + h)
    if X1 <= X0 or Y1 <= Y0:
        return dst
    s = src[Y0 - y:Y1 - y, X0 - x:X1 - x]
    d = dst[Y0:Y1, X0:X1]
    sa, da = s[..., 3:4], d[..., 3:4]
    oa = sa + da * (1 - sa)
    oc = (s[..., :3] * sa + d[..., :3] * da * (1 - sa)) / np.maximum(oa, 1e-6)
    dst[Y0:Y1, X0:X1, :3] = oc
    dst[Y0:Y1, X0:X1, 3:4] = oa
    return dst


def uncomposite(base, pressed, thresh=2.5 / 255, feather=6):
    """Smallest-alpha overlay O such that O over base == pressed (straight RGBA float crops)."""
    ab = base[..., 3:4]
    ap = pressed[..., 3:4]
    Bp = base[..., :3] * ab
    Pp = pressed[..., :3] * ap
    d = Pp - Bp
    d = np.sign(d) * np.maximum(np.abs(d) - thresh, 0)
    with np.errstate(divide='ignore', invalid='ignore'):
        up = np.where(d > 0, d / np.maximum(1 - Bp, 1e-4), 0)
        dn = np.where(d < 0, -d / np.maximum(Bp, 1e-4), 0)
    a = np.max(np.maximum(up, dn), axis=2, keepdims=True)
    agrow = np.where(ab < 0.999, np.maximum(ap - ab, 0) / np.maximum(1 - ab, 1e-4), 0)
    a = np.clip(np.maximum(a, agrow), 0, 1)
    # feather the crop border so region edges never show
    h, w = a.shape[:2]
    fy = np.clip(np.minimum(np.arange(h), np.arange(h)[::-1]) / feather, 0, 1)
    fx = np.clip(np.minimum(np.arange(w), np.arange(w)[::-1]) / feather, 0, 1)
    win = (fy[:, None] * fx[None, :])[..., None]
    a_safe = np.maximum(a, 1e-4)
    C = np.clip(Bp + d / a_safe, 0, 1)
    a = a * win
    a[a < 1.5 / 255] = 0
    return np.concatenate([C, a], 2)


def alpha_bbox(img, pad=1):
    ys, xs = np.nonzero(img[..., 3] > 0)
    if len(xs) == 0:
        return None
    return (max(0, xs.min() - pad), max(0, ys.min() - pad), min(img.shape[1], xs.max() + 1 + pad), min(img.shape[0], ys.max() + 1 + pad))


def resize_area(img, nw, nh):
    """Area-averaging resize of premultiplied data (returns straight RGBA)."""
    h, w = img.shape[:2]
    pm = img.copy()
    pm[..., :3] *= pm[..., 3:4]

    def mat(n_out, n_in):
        M = np.zeros((n_out, n_in))
        sc = n_in / n_out
        for i in range(n_out):
            a, b = i * sc, (i + 1) * sc
            for j in range(int(math.floor(a)), min(n_in, int(math.ceil(b)))):
                M[i, j] = max(0.0, min(b, j + 1) - max(a, j))
            M[i] /= M[i].sum()
        return M
    My, Mx = mat(nh, h), mat(nw, w)
    out = np.einsum('ij,jkc->ikc', My, pm)
    out = np.einsum('ij,kjc->kic', Mx, out)
    a = out[..., 3:4]
    out[..., :3] = np.where(a > 1e-6, out[..., :3] / np.maximum(a, 1e-6), 0)
    return out


def combine_shadow(raw, obj, spread=10.0, strength=0.85):
    """Rebuild the base from an objects-only render (obj) and a render over the shadow catcher
    (raw): the catcher's shadow is kept only close to the controller (soft contact shadow)."""
    obj = obj.copy()
    # drop faint denoiser haze far away from anything solid
    far = gauss((obj[..., 3] > 0.5).astype(np.float64), 8) < 1e-3
    obj[far & (obj[..., 3] < 0.1)] = 0
    ao = obj[..., 3]
    s = np.clip((raw[..., 3] - ao) / np.maximum(1 - ao, 1e-3), 0, 1)
    near = np.clip(gauss(ao, spread) * 2.2, 0, 1)
    s = s * near * strength
    out = np.zeros_like(obj)
    out[..., 3] = s
    out[out[..., 3] < 1.5 / 255] = 0
    return over(out, obj, 0, 0)


# ----------------------------------------------------------------------------- renderer
class Renderer:
    def __init__(self, sc, tmpdir, outdir):
        self.sc = sc
        self.tmp = tmpdir
        self.out = outdir
        os.makedirs(tmpdir, exist_ok=True)
        os.makedirs(outdir, exist_ok=True)
        self.n = 0
        self.files = {}

    def render(self, tag, region=None):
        """Render the full frame or only region=(x0,y0,x1,y1) theme px. Returns HxWx4 float of the
        full canvas (outside the region is transparent)."""
        sc = self.sc
        r = sc.render
        if region is None:
            r.use_border = False
        else:
            x0, y0, x1, y1 = region
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(W, x1), min(H, y1)
            r.use_border = True
            r.use_crop_to_border = False
            r.border_min_x, r.border_max_x = x0 / W, x1 / W
            r.border_min_y, r.border_max_y = 1 - y1 / H, 1 - y0 / H
        path = os.path.join(self.tmp, f'{tag}.png')
        r.filepath = path
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        self.n += 1
        log(f'render {tag} {region} {time.time() - t0:.1f}s')
        return read_png(path)

    def save(self, name, img, x0=0, y0=0, crop=True):
        """Save an RGBA image whose top-left sits at canvas (x0,y0); crops to alpha. Returns placement."""
        if crop:
            bb = alpha_bbox(img)
            if bb is None:
                raise RuntimeError(f'{name}: empty image')
            bx0, by0, bx1, by1 = bb
            img = img[by0:by1, bx0:bx1]
            x0, y0 = x0 + bx0, y0 + by0
        write_png(os.path.join(self.out, name), img)
        h, w = img.shape[:2]
        info = {'file': name, 'x': x0 + w / 2, 'y': y0 + h / 2, 'w': w, 'h': h, 'x0': x0, 'y0': y0}
        self.files[name] = info
        return info


# ----------------------------------------------------------------------------- theme JSON helpers
INTERP = {'winform.interpolation': 'HighQualityBicubic'}


def img_node(info, x=None, y=None):
    n = {'type': 'image', 'image': info['file'],
         'x': info['x'] if x is None else x, 'y': info['y'] if y is None else y,
         'width': info['w'], 'height': info['h'], 'center': True}
    n.update(INTERP)
    return n


def showhide(expr, *children):
    return {'type': 'showhide', 'input': expr, 'children': list(children)}


def pbar(info, expr, direction='up', x=None, y=None):
    n = {'type': 'pbar', 'image': info['file'], 'x': info['x'] if x is None else x, 'y': info['y'] if y is None else y,
         'width': info['w'], 'height': info['h'], 'center': True, 'direction': direction, 'input': expr}
    n.update(INTERP)
    return n


def write_theme(outdir, nodes, gyro_node):
    for name, with_gyro in (('Full.json', True), ('No Gyro.json', False)):
        ch = list(nodes) + ([gyro_node] if with_gyro and gyro_node else [])
        theme = {'name': name[:-5], 'width': W, 'height': H, 'version': 1, 'children': ch}
        with open(os.path.join(outdir, name), 'w', encoding='utf-8') as f:
            json.dump(theme, f, indent=2)
    with open(os.path.join(outdir, 'theme.json'), 'w', encoding='utf-8') as f:
        json.dump({'name': 'Realistic', 'authors': [{'name': 'VSCView contributors'}]}, f, indent=2)


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--samples', type=int, default=96)
    ap.add_argument('--out', default=None, help='theme output folder (default: in-repo theme folder)')
    ap.add_argument('--tmp', default=None, help='scratch folder for intermediate renders')
    ap.add_argument('--preview', action='store_true', help='render the base only (look-dev)')
    ap.add_argument('--check', default=None, help='folder for the rest / everything-pressed check composites (default: --tmp)')
    return ap.parse_args(argv)
