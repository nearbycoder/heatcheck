"""HEAT CHECK - branding generator (UI images + FX sprites).

Outputs
  Art/Export/UI/UI_Logo.png             2048x1024 RGBA  3D extruded/bevelled HEAT CHECK title logo with flames
  Art/Export/UI/UI_Team_<ABBR>.png      512x512 RGBA    team emblem badges (NEO BAY RRK FRB STV SSC)
  Art/Export/Textures/T_Flame.png       256x256 RGBA    soft flame sprite (RGB premultiplied: usable additively)
  Art/Export/Textures/T_Glow.png        128x128 RGBA    radial glow
  Art/Export/Textures/T_Spark.png       64x64  RGBA     spark/star
  Art/Export/Materials/branding.json    {} (no meshes; FX materials are built by the game code)
  Art/Previews/branding_*.png           contact sheets on dark/light backgrounds

Run:  blender -b --factory-startup -P Blender/gen_branding.py   (run gen_ball.py first for the 3D ball texture)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json  # noqa: E402
import math  # noqa: E402
import random  # noqa: E402

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector  # noqa: E402

import env_helpers as eh  # noqa: E402
import hc_common as hc  # noqa: E402

DARK = "#0D0D10"


# ---------------------------------------------------------------------------
# small 2D helpers
# ---------------------------------------------------------------------------
def rot_pts(pts, ang, c=(0, 0)):
    ca, sa = math.cos(ang), math.sin(ang)
    return [((x - c[0]) * ca - (y - c[1]) * sa + c[0], (x - c[0]) * sa + (y - c[1]) * ca + c[1]) for x, y in pts]


def rect_pts(cx, cy, w, h, ang=0.0):
    p = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
    return rot_pts(p, ang, (cx, cy)) if ang else p


def capsule_pts(p0, p1, r, n=10):
    p0, p1 = Vector(p0), Vector(p1)
    d = (p1 - p0)
    a = math.atan2(d.y, d.x)
    pts = []
    for i in range(n + 1):
        t = a - math.pi / 2 + math.pi * i / n
        pts.append((p1.x + r * math.cos(t), p1.y + r * math.sin(t)))
    for i in range(n + 1):
        t = a + math.pi / 2 + math.pi * i / n
        pts.append((p0.x + r * math.cos(t), p0.y + r * math.sin(t)))
    return pts


def ribbon_poly(centerline, widths):
    """Closed polygon around a 2D centerline with per-point widths."""
    L, Rr = [], []
    n = len(centerline)
    for i in range(n):
        a = Vector(centerline[max(i - 1, 0)])
        b = Vector(centerline[min(i + 1, n - 1)])
        t = (b - a)
        t = t.normalized() if t.length > 1e-9 else Vector((1, 0))
        nn = Vector((-t.y, t.x))
        p = Vector(centerline[i])
        L.append(tuple(p + nn * widths[i] * 0.5))
        Rr.append(tuple(p - nn * widths[i] * 0.5))
    return L + Rr[::-1]


def star_pts(cx, cy, r_out, r_in, n=5, rot=math.pi / 2):
    pts = []
    for i in range(2 * n):
        r = r_out if i % 2 == 0 else r_in
        a = rot + math.pi * i / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def arc_text(prefix, text, radius, center_angle, cap, font, mat, z, top=True, spacing=0.02):
    """Place characters along a circular arc. top=True: reads left->right over the top, tops outward.
    top=False: reads left->right along the bottom, tops toward the center."""
    chars = []
    widths = []
    for i, ch in enumerate(text):
        if ch == " ":
            chars.append(None)
            widths.append(cap * 0.32)
            continue
        o = eh.text_obj("%s_%d" % (prefix, i), ch, 1.0, font=font, mat=mat, align_x="CENTER",
                        align_y="BOTTOM_BASELINE", resolution=10)
        # scale so the cap height matches
        lo, hi = eh.mesh_bounds(o)
        o.scale = (cap / 0.72, cap / 0.72, 1.0)
        eh.bake_obj(o)
        lo, hi = eh.mesh_bounds(o)
        chars.append(o)
        widths.append(hi.x - lo.x)
    total = sum(widths) + spacing * (len(text) - 1)
    span = total / radius
    acc = 0.0
    for o, w in zip(chars, widths):
        mid = acc + w / 2
        acc += w + spacing
        if o is None:
            continue
        if top:
            th = center_angle + span / 2 - mid / radius
            o.rotation_euler = (0, 0, th - math.pi / 2)
        else:
            th = center_angle - span / 2 + mid / radius
            o.rotation_euler = (0, 0, th + math.pi / 2)
        o.location = (radius * math.cos(th), radius * math.sin(th), z)
        eh.bake_obj(o)
    return [c for c in chars if c is not None]


def fit_text(name, text, font, mat, max_w, max_h, center, z, shear=0.0, spacing=1.0):
    o = eh.text_obj(name, text, 1.0, font=font, mat=mat, shear=shear, spacing=spacing, resolution=12)
    lo, hi = eh.mesh_bounds(o)
    w, h = hi.x - lo.x, hi.y - lo.y
    s = min(max_w / w, max_h / h)
    eh.fit_obj(o, width=w * s, center=center)
    eh.set_z(o, z)
    return o


# ---------------------------------------------------------------------------
# Team icons (unit space, roughly within a radius ~0.55 box centred on 0,0)
# ---------------------------------------------------------------------------
def icon_bolt():
    bolt = [(0.10, 0.60), (-0.30, 0.02), (-0.05, 0.02), (-0.20, -0.56), (0.33, 0.13), (0.07, 0.13), (0.26, 0.60)]
    return [("outline_dark", [bolt], 0.075), ("outline_acc", [bolt], 0.04), ("fill_pri", [bolt], 0.0),
            ("hl_white", [[(0.13, 0.53), (0.18, 0.53), (-0.17, 0.06), (-0.22, 0.06)]], 0.0)]


def icon_tentacle():
    C = Vector((0.08, 0.10))
    cl, ws = [], []
    root = [(-0.62, -0.62), (-0.55, -0.40), (-0.45, -0.18)]
    for p in root:
        cl.append(p)
        ws.append(0.24)
    n = 70
    for i in range(n + 1):
        t = i / n
        a = math.radians(205 - 560 * t)
        r = 0.50 * (1 - 0.86 * t)
        cl.append((C.x + r * math.cos(a), C.y + r * math.sin(a)))
        ws.append(0.22 * (1 - t) ** 0.85 + 0.018)
    body = ribbon_poly(cl, ws)
    # suckers along the inner side
    suck = []
    for i in range(4, len(cl) - 12, 5):
        a = Vector(cl[i - 1])
        b = Vector(cl[i + 1])
        t = (b - a).normalized()
        nn = Vector((-t.y, t.x))
        p = Vector(cl[i])
        # inner side = toward C for the spiral part
        side = -1.0 if (p + nn * 0.01 - C).length > (p - nn * 0.01 - C).length else 1.0
        q = p + nn * side * ws[i] * 0.22
        suck.append(eh.circle_pts(q.x, q.y, ws[i] * 0.2, 16))
    return [("outline_dark", [body], 0.045), ("fill_sec", [body], 0.0), ("acc", suck, 0.0)]


def icon_scorpion():
    C = Vector((0.02, 0.02))
    R = 0.36
    layers = []
    n = 7
    angs = np.linspace(math.radians(250), math.radians(18), n)
    sizes = np.linspace(0.25, 0.13, n)
    for i in range(n):
        a = angs[i]
        c = Vector((C.x + R * math.cos(a), C.y + R * math.sin(a)))
        t = Vector((math.sin(a), -math.cos(a)))       # clockwise tangent
        nrm = Vector((math.cos(a), math.sin(a)))      # outward
        L = sizes[i] * 0.78
        Wd = sizes[i] * 0.95
        # rounded plate: wider on the outside, slightly tapered inside
        pts = []
        for k in range(12):
            ang = 2 * math.pi * k / 12
            lx = math.cos(ang) * L
            ly = math.sin(ang) * Wd * (0.62 if math.sin(ang) > 0 else 0.48)
            p = c + t * lx + nrm * ly
            pts.append((p.x, p.y))
        layers.append(("outline_dark", [pts], 0.032))
        layers.append(("fill_sec", [pts], 0.0))
        # ridge highlight
        q0 = c - t * L * 0.55 + nrm * Wd * 0.22
        q1 = c + t * L * 0.55 + nrm * Wd * 0.22
        layers.append(("stroke_hl", [[(q0.x, q0.y), (q1.x, q1.y)]], 0.012))
    a = angs[-1]
    b = Vector((C.x + R * math.cos(a), C.y + R * math.sin(a)))
    t = Vector((math.sin(a), -math.cos(a)))
    bc = b + t * 0.11
    bulb = [(bc.x + 0.10 * math.cos(2 * math.pi * k / 32) * 1.15, bc.y + 0.075 * math.sin(2 * math.pi * k / 32))
            for k in range(32)]
    bulb = rot_pts(bulb, math.atan2(t.y, t.x), (bc.x, bc.y))
    tip = (bc.x - 0.21, bc.y - 0.20)
    needle = eh.bezier((bc.x + 0.06, bc.y - 0.05), (bc.x + 0.05, bc.y - 0.22), (tip[0] + 0.14, tip[1] - 0.05),
                       tip, 18, include_end=True)
    needle += eh.bezier(tip, (tip[0] + 0.12, tip[1] + 0.03), (bc.x - 0.03, bc.y - 0.12),
                        (bc.x - 0.06, bc.y - 0.02), 18)[1:]
    layers.append(("outline_dark", [needle, bulb], 0.032))
    layers.append(("needle", [needle], 0.0))
    layers.append(("fill_sec", [bulb], 0.0))
    return layers


def icon_mountain():
    mtn = [(-0.62, -0.36), (-0.30, 0.06), (-0.18, -0.02), (0.02, 0.44), (0.30, 0.10), (0.40, 0.18),
           (0.64, -0.36)]
    shade = [(0.02, 0.44), (0.30, 0.10), (0.40, 0.18), (0.64, -0.36), (0.10, -0.36)]
    snow = [(-0.10, 0.17), (0.02, 0.44), (0.16, 0.12), (0.10, 0.17), (0.05, 0.11), (-0.01, 0.19), (-0.05, 0.12)]
    snow2 = [(-0.38, -0.04), (-0.30, 0.06), (-0.22, -0.01), (-0.27, 0.01), (-0.31, -0.03), (-0.34, 0.0)]
    flake = []
    fx, fy, fr = 0.40, 0.43, 0.14
    for k in range(6):
        b = math.pi / 2 + k * math.pi / 3
        tipx, tipy = fx + fr * math.cos(b), fy + fr * math.sin(b)
        flake.append([(fx, fy), (tipx, tipy)])
        bx, by = fx + 0.58 * fr * math.cos(b), fy + 0.58 * fr * math.sin(b)
        for e in (-0.9, 0.9):
            flake.append([(bx, by), (bx + 0.36 * fr * math.cos(b + e), by + 0.36 * fr * math.sin(b + e))])
    return [("outline_dark", [mtn], 0.045), ("fill_pri", [mtn], 0.0), ("shade_pri", [shade], 0.0),
            ("acc", [snow, snow2], 0.0), ("stroke_acc", flake, 0.028)]


def icon_forge():
    anvil = [(-0.60, 0.10), (-0.20, 0.10), (0.42, 0.10), (0.42, -0.04), (0.20, -0.08), (0.14, -0.22),
             (0.30, -0.36), (0.36, -0.36), (0.36, -0.46), (-0.28, -0.46), (-0.28, -0.36), (-0.22, -0.36),
             (-0.06, -0.22), (-0.12, -0.08), (-0.22, -0.05), (-0.42, -0.02)]
    handle = rect_pts(0.26, 0.27, 0.065, 0.50, math.radians(45))
    tx, ty = 0.26 - 0.25 * math.sin(math.radians(45)), 0.27 + 0.25 * math.cos(math.radians(45))
    head = rect_pts(tx, ty, 0.32, 0.13, math.radians(45))
    sparks = [star_pts(0.47, 0.27, 0.065, 0.02, 4, 0.3), star_pts(0.56, 0.13, 0.045, 0.015, 4, 0.0),
              star_pts(-0.46, 0.28, 0.055, 0.017, 4, 0.5), star_pts(0.34, 0.44, 0.04, 0.013, 4, 0.2)]
    return [("outline_dark", [anvil, handle, head], 0.045), ("anvil", [anvil], 0.0),
            ("fill_sec", [handle], 0.0), ("head", [head], 0.0), ("acc", sparks, 0.0)]


def icon_surge():
    scx, scy, sr = 0.02, 0.15, 0.33
    sun = eh.circle_pts(scx, scy, sr, 96)
    bars = []
    for (y, h) in ((0.09, 0.028), (0.025, 0.036), (-0.04, 0.045)):
        dy = abs(y - scy)
        if dy < sr:
            hw = math.sqrt(sr * sr - dy * dy) + 0.02
            bars.append(rect_pts(scx, y, 2 * hw, h))
    rays = []
    for k in range(9):
        a = math.radians(180 - k * 22.5)
        rays.append(capsule_pts((scx + (sr + 0.055) * math.cos(a), scy + (sr + 0.055) * math.sin(a)),
                                (scx + (sr + 0.105) * math.cos(a), scy + (sr + 0.105) * math.sin(a)), 0.02, 6))
    S, oy = 0.95, -0.13
    def W(pts):
        return [(x * S, y * S + oy) for x, y in pts]
    wave = [(-0.66, -0.50)]
    wave += eh.bezier((-0.66, -0.50), (-0.62, -0.18), (-0.30, 0.10), (0.10, 0.10), 22)[1:]
    wave += eh.bezier((0.10, 0.10), (0.32, 0.10), (0.46, 0.00), (0.40, -0.12), 18)
    wave += eh.bezier((0.40, -0.12), (0.36, -0.21), (0.26, -0.22), (0.21, -0.15), 12)
    wave += eh.bezier((0.21, -0.15), (0.16, -0.32), (0.42, -0.48), (0.66, -0.50), 18)
    wave += [(0.66, -0.50), (0.66, -0.62), (-0.66, -0.62)]
    foam = eh.bezier((-0.50, -0.26), (-0.36, -0.04), (-0.12, 0.05), (0.10, 0.05), 18, include_end=True)
    foam2 = eh.bezier((-0.30, -0.42), (-0.12, -0.30), (0.02, -0.30), (0.12, -0.36), 12, include_end=True)
    return [("outline_dark", [sun] + rays, 0.035), ("sun", [sun] + rays, 0.0), ("cut", bars, 0.0),
            ("outline_dark2", [W(wave)], 0.04), ("fill_acc", [W(wave)], 0.0),
            ("stroke_white", [W(foam), W(foam2)], 0.022)]


ICONS = {"NEO": icon_bolt, "BAY": icon_tentacle, "RRK": icon_scorpion, "FRB": icon_mountain, "STV": icon_forge,
         "SSC": icon_surge}

# per-team colour roles: field (gradient light, dark), ring, accent ring, icon roles, ribbon, ribbon text, ring text
STYLE = {
    "NEO": dict(field=("#2A2A2E", "#08080A"), ring="#FFD60A", acc_ring="#00E5FF", ribbon="#FFD60A",
                ribbon_txt="#111111", ring_txt="#111111", roles=dict(fill_pri="#FFD60A", outline_acc="#00E5FF",
                                                                     hl_white="#FFF6C2")),
    "BAY": dict(field=("#14A39C", "#06504D"), ring="#FF6B1A", acc_ring="#F2F2F2", ribbon="#F2F2F2",
                ribbon_txt="#0B7A75", ring_txt="#FFFFFF", roles=dict(fill_sec="#FF6B1A", acc="#FFE2CF")),
    "RRK": dict(field=("#D21C3C", "#7A0A1E"), ring="#1B1B1B", acc_ring="#E9C46A", ribbon="#E9C46A",
                ribbon_txt="#1B1B1B", ring_txt="#E9C46A", roles=dict(fill_sec="#E9C46A", stroke_hl="#FFF1C9",
                                                                     needle="#F6DC9A")),
    "FRB": dict(field=("#1C4A78", "#0A1E35"), ring="#A9D6F5", acc_ring="#FFFFFF", ribbon="#FFFFFF",
                ribbon_txt="#0E2A47", ring_txt="#0E2A47", roles=dict(fill_pri="#A9D6F5", shade_pri="#78AFD6",
                                                                     acc="#FFFFFF", stroke_acc="#FFFFFF")),
    "STV": dict(field=("#7A8392", "#3A404A"), ring="#FF8C1A", acc_ring="#FFD166", ribbon="#2B2F37",
                ribbon_txt="#FF8C1A", ring_txt="#1E2127", roles=dict(anvil="#262A31", fill_sec="#FF8C1A",
                                                                     head="#C9CFD8", acc="#FFD166")),
    "SSC": dict(field=("#3C3FC4", "#191A66"), ring="#FF4F79", acc_ring="#2EC4B6", ribbon="#2EC4B6",
                ribbon_txt="#1B1C6E", ring_txt="#FFFFFF", roles=dict(sun="#FF4F79", cut="#2B2D9B",
                                                                     fill_acc="#2EC4B6", stroke_white="#FFFFFF")),
}


def make_badge(team):
    abbr = team["abbr"]
    st = STYLE[abbr]
    eh.clear_scene()
    dark = eh.flat_mat("F_dark", DARK)
    mats = {}

    def M(key, col):
        if key not in mats:
            mats[key] = eh.flat_mat("F_%s_%s" % (abbr, key), col)
        return mats[key]

    z = 0.0
    eh.fill_obj("b_out", [eh.circle_pts(0, 0, 1.0, 256)], z, dark)
    eh.fill_obj("b_ring", [eh.circle_pts(0, 0, 0.955, 256)], z + 0.001, M("ring", st["ring"]))
    eh.fill_obj("b_acc", [eh.circle_pts(0, 0, 0.785, 256)], z + 0.002, M("acc_ring", st["acc_ring"]))
    eh.fill_obj("b_inner", [eh.circle_pts(0, 0, 0.765, 256)], z + 0.003, dark)
    field = eh.gradient_mat("F_%s_field" % abbr, [(0.0, st["field"][0]), (1.0, st["field"][1])], v0=0.0, v1=0.95,
                            center=(-0.25, 0.35))
    eh.fill_obj("b_field", [eh.circle_pts(0, 0, 0.745, 256)], z + 0.004, field)
    # subtle diagonal sheen across the upper field
    sheen = eh.flat_mat("F_sheen", "#FFFFFF", alpha=0.07)
    sheen_poly = [(0.745 * math.cos(a), 0.745 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 256)
                  if 0.745 * math.sin(a) > 0.30 + 0.745 * math.cos(a) / 3.0]
    eh.fill_obj("b_sheen", [sheen_poly], z + 0.0045, sheen)
    # icon
    layers = ICONS[abbr]()
    zz = z + 0.006
    icon_objs = []
    for role, polys, d in layers:
        if role.startswith("outline_dark"):
            o = eh.outline_obj("ic_" + role, polys, d, zz, dark)
        elif role.startswith("outline_"):
            o = eh.outline_obj("ic_" + role, polys, d, zz, M(role, st["roles"][role]))
        elif role.startswith("stroke_"):
            o = eh.stroke_obj("ic_" + role, polys, d, zz, M(role, st["roles"][role]))
        else:
            o = eh.fill_obj("ic_" + role, polys, zz, M(role, st["roles"][role]))
        icon_objs.append(o)
        zz += 0.0007
    # icon placement: scale/translate into the field above the ribbon
    k = 0.90 if abbr == "STV" else 0.98
    for o in icon_objs:
        o.location = (0.0, 0.10 if abbr == "STV" else 0.12, 0.0)
        o.scale = (k, k, 1.0)
        eh.bake_obj(o)
    # name ribbon
    zr = z + 0.03
    rib = [(-0.93, -0.70), (0.93, -0.70), (0.97, -0.37), (-0.89, -0.37)]
    tail_l = [(-1.08, -0.76), (-0.86, -0.76), (-0.86, -0.46), (-1.08, -0.46), (-1.00, -0.61)]
    tail_r = [(1.08, -0.76), (1.00, -0.61), (1.08, -0.46), (0.86, -0.46), (0.86, -0.76)]
    eh.outline_obj("rb_tails_ol", [tail_l, tail_r], 0.03, zr, dark)
    shade_col = tuple(c * 0.72 for c in eh.srgb(st["ribbon"]))
    eh.fill_obj("rb_tails", [tail_l, tail_r], zr + 0.001, eh.flat_mat("F_%s_ribshade" % abbr, shade_col))
    eh.outline_obj("rb_ol", [rib], 0.03, zr + 0.002, dark)
    eh.fill_obj("rb", [rib], zr + 0.003, M("ribbon", st["ribbon"]))
    fit_text("rb_txt", team["name"], eh.FONT_ARIAL_BLACK if len(team["name"]) <= 7 else eh.FONT_IMPACT,
             M("ribbon_txt", st["ribbon_txt"]), 1.52, 0.235, (0.02, -0.535), zr + 0.004, shear=0.10)
    # city along the top of the ring, abbreviation along the bottom
    arc_text("city", team["city"], 0.818, math.pi / 2, 0.112, eh.FONT_DIN, M("ring_txt", st["ring_txt"]),
             z + 0.02, top=True, spacing=0.018)
    arc_text("abbr", abbr, 0.9325, -math.pi / 2, 0.085, eh.FONT_DIN, M("ring_txt", st["ring_txt"]), z + 0.02,
             top=False, spacing=0.03)
    for sx in (-1, 1):
        a = math.radians(-90 + sx * 22)
        eh.fill_obj("dot%d" % sx, [star_pts(0.868 * math.cos(a), 0.868 * math.sin(a), 0.035, 0.014, 5)],
                    z + 0.02, M("ring_txt", st["ring_txt"]))
    eh.flat_scene(1024, 1024, samples=16)
    eh.ortho_camera(0.0, 0.0, 2.24)
    img = eh.render_rgba("badge_" + abbr)
    img = premult_downsample(img, 2)
    eh.save_png(img, os.path.join(eh.UI_DIR, "UI_Team_%s.png" % abbr))
    return img


def premult_downsample(img, f):
    """Downsample straight-alpha RGBA correctly (average in premultiplied space)."""
    a = img[..., 3:4]
    pm = np.concatenate([img[..., :3] * a, a], axis=-1)
    d = eh.downsample(pm, f)
    out = d.copy()
    aa = np.maximum(d[..., 3:4], 1e-6)
    out[..., :3] = np.where(d[..., 3:4] > 1e-6, d[..., :3] / aa, 0.0)
    return out


# ---------------------------------------------------------------------------
# 3D title logo
# ---------------------------------------------------------------------------
def principled(name, color, rough=0.35, metal=0.0, emit=None, emit_strength=0.0, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = tuple(eh.lin3(eh.srgb(color) if isinstance(color, str) else color)) + (1,)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if coat:
        b.inputs["Coat Weight"].default_value = coat
        b.inputs["Coat Roughness"].default_value = 0.08
    if emit is not None:
        b.inputs["Emission Color"].default_value = tuple(eh.lin3(eh.srgb(emit))) + (1,)
        b.inputs["Emission Strength"].default_value = emit_strength
    return m


def gradient_principled(name, stops, axis, v0, v1, rough=0.3, metal=0.0, emit_strength=0.0, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sep.inputs[0])
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = v0
    mr.inputs["From Max"].default_value = v1
    nt.links.new(sep.outputs["XYZ".index(axis)], mr.inputs["Value"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    els = ramp.color_ramp.elements
    while len(els) > 1:
        els.remove(els[-1])
    for i, (p, c) in enumerate(stops):
        e = els[0] if i == 0 else els.new(p)
        e.position = p
        e.color = tuple(eh.lin3(eh.srgb(c))) + (1,)
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    if emit_strength > 0:
        nt.links.new(ramp.outputs["Color"], b.inputs["Emission Color"])
        b.inputs["Emission Strength"].default_value = emit_strength
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if coat:
        b.inputs["Coat Weight"].default_value = coat
        b.inputs["Coat Roughness"].default_value = 0.06
    return m


def extrude_flat(o, depth, z_front):
    """Turn a flat (XY) mesh object into a slab from z_front-depth to z_front."""
    import bmesh
    eh.bake_obj(o)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    for v in bm.verts:
        v.co.z = z_front - depth
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    res = bmesh.ops.extrude_face_region(bm, geom=list(bm.faces))
    verts = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
    for v in verts:
        v.co.z = z_front
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    return o


def assign_by_normal(o, front_mat, side_mat, bevel_mat=None, back_mat=None):
    me = o.data
    me.materials.clear()
    mats = [front_mat, side_mat] + ([bevel_mat] if bevel_mat else []) + ([back_mat] if back_mat else [])
    for m in mats:
        me.materials.append(m)
    n = len(me.polygons)
    nrm = np.empty(n * 3, np.float32)
    me.polygons.foreach_get("normal", nrm)
    nz = nrm.reshape(-1, 3)[:, 2]
    idx = np.ones(n, np.int32)  # side
    idx[nz > 0.92] = 0
    if bevel_mat:
        idx[(nz > 0.25) & (nz <= 0.92)] = 2
    if back_mat:
        idx[nz < -0.9] = len(mats) - 1
    me.polygons.foreach_set("material_index", idx)
    me.update()


def flame_bed_polys(x0, x1, y_base, rng, h_min, h_max, step):
    polys = []
    x = x0
    while x < x1:
        h = rng.uniform(h_min, h_max)
        w = step * rng.uniform(0.9, 1.25)
        lean = rng.uniform(-0.25, 0.25) * h
        bx = x + w / 2
        base_l, base_r = (bx - w / 2, y_base), (bx + w / 2, y_base)
        tip = (bx + lean, y_base + h)
        p = eh.bezier(base_l, (bx - w * 0.62, y_base + h * 0.45), (tip[0] - w * 0.18, tip[1] - h * 0.3), tip, 14)
        p += eh.bezier(tip, (tip[0] + w * 0.08, tip[1] - h * 0.42), (bx + w * 0.62, y_base + h * 0.4), base_r, 14)
        p += [(bx + w / 2, y_base - 0.30), (bx - w / 2, y_base - 0.30)]
        polys.append(p)
        x += step
    return polys


def make_logo():
    eh.clear_scene()
    sc = eh.preview_scene((2048, 1024), samples=64, view="Standard", exposure=0.0, world=(0.32, 0.30, 0.30),
                          world_strength=0.6, transparent=True)
    sc.render.film_transparent = True
    s = sc.render.image_settings
    s.color_mode = "RGBA"
    # --- wordmark ---------------------------------------------------------
    face = gradient_principled("L_Face", [(0.0, "#C3150A"), (0.38, "#FF5A00"), (0.72, "#FFA200"), (1.0, "#FFE36A")],
                               "Y", -0.50, 0.52, rough=0.28, emit_strength=0.35, coat=0.6)
    side = principled("L_Side", "#5E0C04", rough=0.45)
    bevel = principled("L_Bevel", "#FFE7A8", rough=0.18, metal=0.85)
    back = principled("L_Back", "#2A0603", rough=0.5)
    word = eh.text_obj("L_word", "HEAT CHECK", 1.0, font=eh.FONT_IMPACT, shear=0.16, spacing=1.02, resolution=16)
    eh.fit_obj(word, height=1.0, center=(0, 0))
    flat_copy = word.data.copy()
    # extruded + bevelled version via curve settings is lost after mesh conversion -> rebuild as text curve
    bpy.data.objects.remove(word)
    cu = bpy.data.curves.new("L_word3d", "FONT")
    cu.body = "HEAT CHECK"
    cu.font = bpy.data.fonts.load(eh.FONT_IMPACT, check_existing=True)
    cu.shear = 0.16
    cu.space_character = 1.02
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.resolution_u = 16
    cu.extrude = 0.10
    cu.bevel_depth = 0.035
    cu.bevel_resolution = 3
    w3 = bpy.data.objects.new("L_word3d", cu)
    bpy.context.scene.collection.objects.link(w3)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(w3.evaluated_get(dg))
    bpy.data.objects.remove(w3)
    w3 = bpy.data.objects.new("L_word3d", me)
    bpy.context.scene.collection.objects.link(w3)
    lo, hi = eh.mesh_bounds(w3)
    s_ = 1.0 / (hi.y - lo.y - 2 * 0.035)
    from mathutils import Matrix
    w3.data.transform(Matrix.Translation((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, 0)))
    w3.data.transform(Matrix.Diagonal((s_, s_, s_, 1)))
    w3.location = (0, 0, 0.15)
    eh.bake_obj(w3)
    assign_by_normal(w3, face, side, bevel, back)
    hc.shade(w3, smooth=True, angle=30)
    # backing plates from the flat text (dilated)
    flat = bpy.data.objects.new("L_flat", flat_copy)
    bpy.context.scene.collection.objects.link(flat)
    eh.set_z(flat, 0.0)
    plate = eh.dilate_mesh_obj(flat, "L_plate", 0.085, z=0.0, seg=12)
    extrude_flat(plate, 0.16, 0.10)
    plate_mat = principled("L_Plate", "#16171B", rough=0.25, coat=0.5)
    plate_side = principled("L_PlateSide", "#0B0B0D", rough=0.5)
    assign_by_normal(plate, plate_mat, plate_side)
    rim = eh.dilate_mesh_obj(flat, "L_rim", 0.135, z=0.0, seg=12)
    extrude_flat(rim, 0.10, -0.02)
    rim_mat = principled("L_Rim", "#FFC300", rough=0.22, metal=0.6, emit="#FF8A00", emit_strength=0.6)
    assign_by_normal(rim, rim_mat, principled("L_RimSide", "#A34A00", rough=0.4))
    outer = eh.dilate_mesh_obj(flat, "L_outer", 0.18, z=0.0, seg=12)
    extrude_flat(outer, 0.06, -0.10)
    assign_by_normal(outer, principled("L_Outer", "#120606", rough=0.5), principled("L_OuterSide", "#000000"))
    bpy.data.objects.remove(flat)
    # --- flames + ball -------------------------------------------------------
    ball_r = 0.62
    bc = (0.0, 0.98)
    rng = random.Random(7)
    fl_mats = [gradient_principled("L_Fl%d" % i, stops, "Y", bc[1] - 0.8, bc[1] + 3.0, rough=0.5,
                                   emit_strength=es)
               for i, (stops, es) in enumerate((
                   ([(0.0, "#7A0A02"), (0.5, "#D62208"), (1.0, "#FF4A10")], 1.2),
                   ([(0.0, "#D63A00"), (0.5, "#FF7A00"), (1.0, "#FFA12A")], 1.6),
                   ([(0.0, "#FFB000"), (0.6, "#FFD23F"), (1.0, "#FFF2A8")], 2.0)))]
    for li in range(3):
        polys = eh.flame_polys(li, ball_r, bc)
        o = eh.fill_obj("L_fl%d" % li, polys, 0.0, None)
        extrude_flat(o, 0.05, -0.90 + 0.06 * li)
        o.data.materials.append(fl_mats[li])
    # flame bed licking up behind the whole wordmark
    olo, ohi = eh.mesh_bounds(outer)
    bx0, bx1 = olo.x + 0.25, ohi.x - 0.55
    bed = eh.fill_obj("L_bed", flame_bed_polys(bx0, bx1, 0.40, rng, 0.55, 1.15, 0.40), 0.0, None)
    extrude_flat(bed, 0.04, -0.94)
    bed.data.materials.append(fl_mats[0])
    bed2 = eh.fill_obj("L_bed2", flame_bed_polys(bx0 + 0.15, bx1 - 0.1, 0.40, rng, 0.38, 0.80, 0.34), 0.0, None)
    extrude_flat(bed2, 0.04, -0.88)
    bed2.data.materials.append(fl_mats[1])
    # dark outline behind the flame silhouette for separation
    ol = eh.outline_obj("L_flol", eh.flame_polys(0, ball_r, bc), 0.07, 0.0, None)
    extrude_flat(ol, 0.04, -0.98)
    ol.data.materials.append(principled("L_FlOl", "#1A0402", rough=0.6))
    # 3D ball
    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=ball_r * 0.98,
                                         location=(bc[0], bc[1], -0.50))
    ball = bpy.context.active_object
    ball.rotation_euler = (math.radians(70), math.radians(8), math.radians(-28))
    tex = os.path.join(eh.TEX_DIR, "T_Ball.png")
    bm = bpy.data.materials.new("L_Ball")
    bm.use_nodes = True
    bsdf = bm.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.5
    if os.path.exists(tex):
        tn = bm.node_tree.nodes.new("ShaderNodeTexImage")
        tn.image = bpy.data.images.load(tex, check_existing=True)
        bm.node_tree.links.new(tn.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = tuple(eh.lin("#D65A1C")) + (1,)
    ball.data.materials.append(bm)
    for p in ball.data.polygons:
        p.use_smooth = True
    # --- lights / camera ---------------------------------------------------
    eh.area_light("K", (-3.0, -2.5, 7.0), (0, 0.6, 0), 900, size=4.0, color=(1.0, 0.96, 0.9))
    eh.area_light("F", (4.0, -1.0, 5.0), (0, 0.6, 0), 350, size=5.0, color=(1.0, 0.85, 0.7))
    eh.area_light("R", (0.0, 5.0, 2.0), (0, 0.6, 0), 600, size=6.0, color=(1.0, 0.45, 0.1))
    eh.area_light("B", (0.0, -4.0, -1.5), (0, 0.4, 0), 250, size=6.0, color=(1.0, 0.6, 0.3))
    cam = eh.look_cam("LogoCam", (0.0, -3.1, 24.0), (0.0, 1.15, 0.0), lens=135)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 7.9
    sc.render.filepath = os.path.join(eh._tmpdir(), "logo_raw.png")
    bpy.ops.render.render(write_still=True)
    img = eh.load_png(sc.render.filepath)
    # warm outer glow (premultiplied add under the logo)
    a = img[..., 3]
    glow = eh.gauss_blur(a, 22.0) * 0.55 + eh.gauss_blur(a, 6.0) * 0.25
    glow_col = np.array(eh.srgb("#FF6A00"), np.float32)
    ga = np.clip(glow, 0, 1) * (1 - a)
    out_a = a + ga
    out_rgb = (img[..., :3] * a[..., None] + glow_col * ga[..., None]) / np.maximum(out_a, 1e-6)[..., None]
    out = np.concatenate([out_rgb, out_a[..., None]], axis=-1)
    eh.save_png(out, os.path.join(eh.UI_DIR, "UI_Logo.png"))
    return out


# ---------------------------------------------------------------------------
# FX sprites
# ---------------------------------------------------------------------------
def make_fx():
    # T_Flame: teardrop flame (round base, flickering tapered tip), white-yellow core -> orange -> red
    N = 256
    y, x = np.mgrid[0:N, 0:N].astype(np.float32)
    u = (x + 0.5) / N * 2 - 1           # -1..1
    v = (y + 0.5) / N                   # 0 bottom .. 1 top
    n = eh.LatticeNoise(9, (64, 64))
    vb, rb, vt = 0.38, 0.35, 0.97
    warp = eh.fbm(n, u * 1.6 + 5.0, v * 3.0, 3) * 0.30 * np.clip((v - vb) / (vt - vb), 0, 1) ** 1.2
    uu = u + warp
    circ = np.sqrt(np.clip(rb * rb - (v - vb) ** 2, 0, None))
    taper = rb * np.clip(1.0 - (v - vb) / (vt - vb), 0, 1) ** 1.35
    width = np.where(v < vb, circ * 1.9, taper * 1.9)
    d = np.abs(uu) / np.maximum(width, 1e-4)
    I = np.clip(1.0 - d, 0, 1) ** 1.25
    I *= np.clip(1.0 - (v - 0.86) / 0.11, 0, 1) * eh.smoothstep(0.0, 0.16, v) * eh.smoothstep(0.0, 0.12, 1.0 - np.abs(u))
    I *= 0.88 + 0.12 * eh.fbm(n, u * 5 + 3, v * 7 - 1, 2)
    I = eh.gauss_blur(I, 1.6)
    core = np.clip(1.0 - np.hypot(u / 0.26, (v - 0.36) / 0.24), 0, 1) ** 0.8
    c_red = np.array(eh.srgb("#E63312"), np.float32)
    c_or = np.array(eh.srgb("#FF8A00"), np.float32)
    c_core = np.array(eh.srgb("#FFF3C4"), np.float32)
    col = c_red + (c_or - c_red) * np.clip(I * 1.8, 0, 1)[..., None]
    col = col + (c_core - col) * np.clip(core * 1.2, 0, 1)[..., None]
    A = np.clip(I * 1.25 + core * 0.3, 0, 1)
    eh.save_png(np.concatenate([col * A[..., None], A[..., None]], -1), os.path.join(eh.TEX_DIR, "T_Flame.png"))
    # T_Glow: radial glow
    N = 128
    y, x = np.mgrid[0:N, 0:N].astype(np.float32)
    r = np.hypot((x + 0.5) / N * 2 - 1, (y + 0.5) / N * 2 - 1)
    I = np.clip(np.exp(-(r / 0.42) ** 2) * 1.05 - 0.02, 0, 1) * np.clip((1.0 - r) / 0.08, 0, 1)
    eh.save_png(np.concatenate([np.repeat(I[..., None], 3, -1), I[..., None]], -1),
                os.path.join(eh.TEX_DIR, "T_Glow.png"))
    # T_Spark: hot dot + 4 thin rays
    N = 64
    y, x = np.mgrid[0:N, 0:N].astype(np.float32)
    px = (x + 0.5) / N * 2 - 1
    py = (y + 0.5) / N * 2 - 1
    r = np.hypot(px, py)
    dot = np.exp(-(r / 0.16) ** 2)
    rays = np.exp(-(np.abs(px) / 0.035) ** 2) * np.clip(1 - np.abs(py), 0, 1) ** 2 + \
        np.exp(-(np.abs(py) / 0.035) ** 2) * np.clip(1 - np.abs(px), 0, 1) ** 2
    I = np.clip(dot + rays * 0.8, 0, 1) * np.clip((1.0 - r) / 0.1, 0, 1)
    col = np.array(eh.srgb("#FFF4C8"), np.float32)
    eh.save_png(np.concatenate([col * I[..., None], I[..., None]], -1), os.path.join(eh.TEX_DIR, "T_Spark.png"))


# ---------------------------------------------------------------------------
# Contact sheets for review
# ---------------------------------------------------------------------------
def composite_on(img, bg):
    a = img[..., 3:4]
    return img[..., :3] * a + np.array(eh.srgb(bg), np.float32) * (1 - a)


def contact_sheets(logo, badges):
    lg = eh.downsample(logo, 2)  # 1024x512
    eh.save_png(np.concatenate([composite_on(lg, "#101014"), composite_on(lg, "#E8E4DC")], axis=0),
                os.path.join(eh.PREVIEW_DIR, "branding_logo.png"))
    row_d = np.concatenate([composite_on(b, "#101014") for b in badges], axis=1)
    row_l = np.concatenate([composite_on(b, "#E8E4DC") for b in badges], axis=1)
    eh.save_png(np.concatenate([row_l, row_d], axis=0), os.path.join(eh.PREVIEW_DIR, "branding_badges.png"))


def main():
    make_fx()
    badges = [make_badge(t) for t in eh.TEAMS]
    logo = make_logo()
    contact_sheets(logo, [b for b in badges][::-1][::-1])
    with open(os.path.join(eh.MAT_DIR, "branding.json"), "w") as f:
        json.dump({}, f)
    print("WROTE", os.path.join(eh.MAT_DIR, "branding.json"))
    eh.cleanup_tmp()


if __name__ == "__main__":
    main()
