"""HEAT CHECK player character generator.

Builds one shared athlete body (single skinned mesh), the skeleton, and a set of
modular skeletal-mesh parts that the game attaches with leader-pose:
hair styles, beards, headband, wristbands, jersey numbers and team chest text.

    blender -b --factory-startup -P Blender/gen_character.py

Outputs (Art/Export/Meshes): SK_Player.fbx, SK_Hair_*.fbx, SK_Beard_*.fbx,
SK_Headband.fbx, SK_Wristbands.fbx, SK_Num_{T,O,C}{0-9}.fbx, SK_JerseyText_<TEAM>.fbx
plus Art/Export/Materials/character.json and Art/Blend/character.blend
(used by gen_anims.py).
"""

import bpy
import bmesh
import json
import math
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hc_common as hc  # noqa: E402
import char_rig as rig  # noqa: E402
from mathutils import Vector, Matrix  # noqa: E402
from mathutils.bvhtree import BVHTree  # noqa: E402
from mathutils.kdtree import KDTree  # noqa: E402

random.seed(11)
S = 100.0                 # meters -> centimeters at export time
HEAD_SCALE = 1.12         # arcade "big head" proportion
HEAD_PIVOT = Vector((0.0, 0.0, 1.69))
hc.reset_scene()          # must happen before materials are created below

# ---------------------------------------------------------------------------
# Materials (slot names are the Unreal material instance names)
# ---------------------------------------------------------------------------
MATS = {}


def pmat(name, color, rough=0.6, metal=0.0):
    MATS[name] = {"shader": "character", "color": [round(c, 4) for c in color[:3]],
                  "roughness": rough, "metallic": metal}
    return hc.material(name, color, rough, metal)


M_SKIN = pmat("MI_PlayerSkin", hc.hex_color("8D5524"), 0.55)
M_JERSEY = pmat("MI_PlayerJersey", hc.hex_color("FFD60A"), 0.72)
M_JTRIM = pmat("MI_PlayerJerseyTrim", hc.hex_color("111111"), 0.72)
M_SHORTS = pmat("MI_PlayerShorts", hc.hex_color("FFD60A"), 0.72)
M_STRIM = pmat("MI_PlayerShortsTrim", hc.hex_color("111111"), 0.72)
M_SOCKS = pmat("MI_PlayerSocks", (0.92, 0.92, 0.92), 0.85)
M_SHOE = pmat("MI_PlayerShoe", hc.hex_color("16161A"), 0.4)
M_SOLE = pmat("MI_PlayerShoeSole", (0.93, 0.93, 0.93), 0.55)
M_SACC = pmat("MI_PlayerShoeAccent", hc.hex_color("FFD60A"), 0.4)
M_EYES = pmat("MI_PlayerEyes", (0.95, 0.95, 0.95), 0.25)
M_DARK = pmat("MI_PlayerFaceDark", (0.02, 0.015, 0.012), 0.45)
M_HAIR = pmat("MI_PlayerHair", (0.018, 0.012, 0.008), 0.9)
M_ACC = pmat("MI_PlayerAccessory", (0.95, 0.95, 0.95), 0.85)
M_NUM = pmat("MI_PlayerNumber", (0.03, 0.03, 0.03), 0.65)
M_JTEXT = pmat("MI_PlayerJerseyText", (0.03, 0.03, 0.03), 0.65)

# ---------------------------------------------------------------------------
# bmesh primitive helpers
# ---------------------------------------------------------------------------


def bm_sphere(bm, center, radii, seg=28, rings=16):
    ret = bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=rings, radius=1.0)
    c = Vector(center)
    for v in ret["verts"]:
        v.co = Vector((v.co.x * radii[0], v.co.y * radii[1], v.co.z * radii[2])) + c
    return ret["verts"]


def bm_limb(bm, p0, p1, r0, r1, seg=24):
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    L = d.length
    ret = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                                radius1=r0, radius2=r1, depth=L)
    rot = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=Matrix.Translation((p0 + p1) / 2) @ rot, verts=ret["verts"])
    bm_sphere(bm, p0, (r0, r0, r0), seg, max(8, seg // 2))
    bm_sphere(bm, p1, (r1, r1, r1), seg, max(8, seg // 2))


def obj_from_bm(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def remesh(obj, voxel, smooth_iter=4, smooth_factor=0.6, target_tris=None):
    m = obj.modifiers.new("Remesh", "REMESH")
    m.mode = "VOXEL"
    m.voxel_size = voxel
    m.adaptivity = 0.0
    hc.apply_modifiers(obj)
    if smooth_iter:
        sm = obj.modifiers.new("Smooth", "SMOOTH")
        sm.factor = smooth_factor
        sm.iterations = smooth_iter
        hc.apply_modifiers(obj)
    if target_tris:
        tris = tri_count(obj)
        if tris > target_tris:
            dm = obj.modifiers.new("Decimate", "DECIMATE")
            dm.ratio = target_tris / tris
            hc.apply_modifiers(obj)
    return obj


def tri_count(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def mirror_x_copy(obj, name):
    """Duplicate a mesh object mirrored across X=0 (faces reversed to keep normals outward)."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for v in bm.verts:
        v.co.x = -v.co.x
    bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in obj.data.materials:
        me.materials.append(m)
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def solidify(obj, thickness, offset=-1.0):
    sol = obj.modifiers.new("Solid", "SOLIDIFY")
    sol.thickness = thickness
    sol.offset = offset
    hc.apply_modifiers(obj)


# ---------------------------------------------------------------------------
# Skeleton reference data (rest pose, meters)
# ---------------------------------------------------------------------------
SEGS = {b[0]: (Vector(b[1]), Vector(b[2])) for b in rig.bone_table() if b[6]}


def seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (a + ab * t - p).length


def nearest_bone(p):
    best, bd = None, 1e9
    for n, (a, b) in SEGS.items():
        d = seg_dist(p, a, b)
        if d < bd:
            best, bd = n, d
    return best, bd


# ---------------------------------------------------------------------------
# BODY
# ---------------------------------------------------------------------------


def build_body():
    bm = bmesh.new()
    bm_sphere(bm, (0, 0.012, 0.965), (0.152, 0.116, 0.120))          # hips
    bm_sphere(bm, (0, 0.014, 1.15), (0.146, 0.098, 0.160))           # abdomen
    bm_sphere(bm, (0, 0.006, 1.37), (0.212, 0.134, 0.175))           # rib cage
    bm_sphere(bm, (0, 0.018, 1.468), (0.236, 0.122, 0.100))          # shoulder girdle
    bm_sphere(bm, (0, 0.050, 1.31), (0.184, 0.090, 0.155))           # lats / back
    for s in (1, -1):
        bm_sphere(bm, (0.086 * s, -0.074, 1.405), (0.092, 0.054, 0.074))   # pecs
        bm_sphere(bm, (0.068 * s, 0.064, 0.950), (0.074, 0.060, 0.084))    # glutes
        bm_sphere(bm, (0.214 * s, 0.010, 1.500), (0.088, 0.088, 0.085))    # deltoids
    bm_sphere(bm, (0, 0.030, 1.560), (0.140, 0.080, 0.070))          # trapezius
    bm_limb(bm, (0, 0.010, 1.50), (0, -0.004, 1.735), 0.071, 0.063)  # neck
    for s in (1, -1):
        sh, el, wr, tip, d = rig._arm_pts(s)
        bm_limb(bm, sh, el, 0.074, 0.054)                              # upper arm
        bm_sphere(bm, sh + d * 0.13 + Vector((0, -0.014, 0)), (0.064, 0.064, 0.066))  # bicep
        bm_limb(bm, el, wr, 0.057, 0.038)                              # forearm
        bm_sphere(bm, el + d * 0.08, (0.059, 0.059, 0.059))           # forearm mass
        hip, knee, ankle, ball, toe = rig._leg_pts(s)
        bm_limb(bm, hip + Vector((0.006 * s, 0, 0.02)), knee, 0.100, 0.066)   # thigh
        bm_sphere(bm, hip + (knee - hip) * 0.35 + Vector((0.008 * s, -0.012, 0)), (0.088, 0.088, 0.105))
        bm_limb(bm, knee, ankle + Vector((0, 0, 0.02)), 0.064, 0.043)          # shin
        bm_sphere(bm, knee + (ankle - knee) * 0.28 + Vector((0, 0.026, 0)), (0.062, 0.058, 0.085))  # calf
    body = obj_from_bm("Body", bm)
    remesh(body, voxel=0.0070, smooth_iter=6, smooth_factor=0.65, target_tris=30000)
    return body


def _plane(p0, n):
    return (Vector(p0), Vector(n).normalized())


# jersey boundaries
ARMHOLE_L = _plane((0.182, 0.0, 1.33), (0.983, 0.0, 0.18))
ARMHOLE_R = _plane((-0.182, 0.0, 1.33), (-0.983, 0.0, 0.18))


def _vplane(side):
    B = Vector((0.0, -0.118, 1.430))
    T = Vector((0.080 * side, -0.030, 1.580))
    n = (T - B).cross(Vector((0, 1, 0)))
    if n.z < 0:
        n = -n
    return (B, n.normalized())


VNECK_L = _vplane(1)
VNECK_R = _vplane(-1)
BACKNECK = _plane((0.0, 0.10, 1.535), (0.0, -0.50, 0.866))


def sd(p, plane):
    return (p - plane[0]).dot(plane[1])


def in_neck_hole(c):
    return sd(c, VNECK_L) > 0 and sd(c, VNECK_R) > 0 and sd(c, BACKNECK) > 0


def classify_body_face(c, n):
    nb, _ = nearest_bone(c)
    x, y, z = c
    if nb in ("neck", "head"):
        return M_SKIN
    if 1.055 <= z < 1.66 and abs(x) < 0.30:
        # torso: purely plane based so the jersey edges follow the bisect cuts exactly
        side = 1 if x >= 0 else -1
        if sd(c, ARMHOLE_L if side > 0 else ARMHOLE_R) > 0:
            return M_SKIN
        if in_neck_hole(c):
            return M_SKIN
        if nb.startswith(("hand", "lowerarm")):
            return M_SKIN
        return M_JERSEY
    if nb.startswith(("hand", "lowerarm", "upperarm")):
        return M_SKIN
    if nb.startswith(("calf", "foot", "ball")):
        return M_SOCKS if z < 0.315 else M_SKIN
    if z < 0.63:
        return M_SKIN if z < 0.595 else M_STRIM
    if z > 1.005:
        return M_STRIM
    side = 1 if x >= 0 else -1
    if nb.startswith("thigh") and z < 0.95 and n.x * side > 0.93:
        return M_STRIM  # side stripe
    return M_SHORTS


def dress_body(body):
    for m in (M_SKIN, M_JERSEY, M_JTRIM, M_SHORTS, M_STRIM, M_SOCKS):
        hc.add_material_slot(body, m)
    slot = {m.name: i for i, m in enumerate(body.data.materials)}
    bm = bmesh.new()
    bm.from_mesh(body.data)

    def cut(plane, region=None):
        if region:
            faces = [f for f in bm.faces if region(f.calc_center_median())]
            vs = {v for f in faces for v in f.verts}
            es = {e for f in faces for e in f.edges}
            geom = list(vs) + list(es) + faces
        else:
            geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-6, plane_co=plane[0], plane_no=plane[1])

    def torso(c):
        return c.z > 1.0 and abs(c.x) < 0.26

    def torso_top(c):
        return c.z > 1.38 and abs(c.x) < 0.2

    for z in (1.055, 1.005, 0.63, 0.595, 0.315):
        cut(_plane((0, 0, z), (0, 0, 1)))
    cut(ARMHOLE_L, torso)
    cut(ARMHOLE_R, torso)
    for pl in (VNECK_L, VNECK_R, BACKNECK):
        cut(pl, torso_top)
    bm.normal_update()
    for f in bm.faces:
        f.material_index = slot[classify_body_face(f.calc_center_median(), f.normal).name]

    # puff clothing outward; shared boundary verts take the larger offset so seams stay smooth
    off = {slot["MI_PlayerSkin"]: 0.0, slot["MI_PlayerSocks"]: 0.0015,
           slot["MI_PlayerJersey"]: 0.0045, slot["MI_PlayerJerseyTrim"]: 0.0045}

    def shorts_off(z):
        return 0.006 + 0.012 * max(0.0, min(1.0, (1.0 - z) / 0.37))

    moves = []
    for v in bm.verts:
        mats = [f.material_index for f in v.link_faces]
        if not mats:
            continue
        amts = []
        for mi in mats:
            if mi in (slot["MI_PlayerShorts"], slot["MI_PlayerShortsTrim"]):
                amts.append(shorts_off(v.co.z))
            else:
                amts.append(off.get(mi, 0.0))
        has_skin = slot["MI_PlayerSkin"] in mats
        a = max(amts)
        if has_skin and a > 0.004:
            a *= 0.5  # hem / armhole edges: half step so the cloth edge reads as a lip
        moves.append((v, v.normal * a))
    for v, dv in moves:
        v.co += dv
    bm.to_mesh(body.data)
    bm.free()
    body.data.update()


def _walk_component(comp, adj):
    ends = [v for v in comp if len(adj[v]) == 1]
    start = ends[0] if ends else comp[0]
    order = [start]
    seen = {start}
    prev_dir = None
    cur = start
    while True:
        cands = [w for w in adj[cur] if w not in seen]
        if not cands:
            break
        if prev_dir is not None and len(cands) > 1:
            cands.sort(key=lambda w: -(w.co - cur.co).normalized().dot(prev_dir))
        nxt = cands[0]
        prev_dir = (nxt.co - cur.co).normalized()
        seen.add(nxt)
        order.append(nxt)
        cur = nxt
    closed = len(order) > 3 and start in adj[order[-1]]
    return order, closed


def _resample(pts, step, closed):
    seq = pts + ([pts[0]] if closed else [])
    lens = [0.0]
    for a, b in zip(seq[:-1], seq[1:]):
        lens.append(lens[-1] + (b - a).length)
    total = lens[-1]
    n = max(4, int(total / step))
    out = []
    j = 0
    for i in range(n if closed else n + 1):
        d = total * i / n
        while j < len(lens) - 2 and lens[j + 1] < d:
            j += 1
        seg = lens[j + 1] - lens[j]
        t = 0.0 if seg < 1e-9 else (d - lens[j]) / seg
        out.append(seq[j].lerp(seq[j + 1], t))
    return out


def build_trim_ribbons(body, width=0.024, lift=0.0035, step=0.007, smooth_iters=10):
    """Clean uniform trim bands centered on the jersey neckline and armhole edges."""
    jersey = body.data.materials.find("MI_PlayerJersey")
    skin = body.data.materials.find("MI_PlayerSkin")
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.normal_update()
    bvh = BVHTree.FromBMesh(bm)
    adj = defaultdict(set)
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        ms = {e.link_faces[0].material_index, e.link_faces[1].material_index}
        if ms == {jersey, skin} and min(v.co.z for v in e.verts) > 1.2:
            a, b = e.verts
            adj[a].add(b)
            adj[b].add(a)
    comps, seen = [], set()
    for v in list(adj.keys()):
        if v in seen:
            continue
        stack, comp = [v], []
        seen.add(v)
        while stack:
            u = stack.pop()
            comp.append(u)
            for w in adj[u]:
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        comps.append(comp)
    out = bmesh.new()
    nloops = 0
    for comp in comps:
        if len(comp) < 10:
            continue
        order, closed = _walk_component(comp, adj)
        pts = [v.co.copy() for v in order]
        n = len(pts)
        for _ in range(smooth_iters):
            new = []
            for i in range(n):
                if closed:
                    a, b = pts[i - 1], pts[(i + 1) % n]
                else:
                    a, b = pts[max(i - 1, 0)], pts[min(i + 1, n - 1)]
                new.append(a * 0.25 + pts[i] * 0.5 + b * 0.25)
            pts = [bvh.find_nearest(p)[0] for p in new]
        pts = _resample(pts, step, closed)
        n = len(pts)
        left, right = [], []
        for i in range(n):
            if closed:
                a, b = pts[i - 1], pts[(i + 1) % n]
            else:
                a, b = pts[max(i - 1, 0)], pts[min(i + 1, n - 1)]
            t = (b - a).normalized()
            loc, nrm, _, _ = bvh.find_nearest(pts[i])
            side = nrm.cross(t).normalized()
            for sgn, lst in ((1, left), (-1, right)):
                q = pts[i] + side * (width * 0.5 * sgn)
                ql, qn, _, _ = bvh.find_nearest(q)
                lst.append(out.verts.new(ql + qn * lift))
        rng = n if closed else n - 1
        for i in range(rng):
            j = (i + 1) % n
            f = out.faces.new((left[i], left[j], right[j], right[i]))
            f.normal_update()
            _, nrm, _, _ = bvh.find_nearest((left[i].co + right[j].co) * 0.5)
            if f.normal.dot(nrm) < 0:
                f.normal_flip()
        nloops += 1
    bm.free()
    rib = obj_from_bm("TrimRibbons", out)
    sol = rib.modifiers.new("Solid", "SOLIDIFY")
    sol.thickness = 0.0025
    sol.offset = -1
    hc.apply_modifiers(rib)
    hc.assign_material(rib, M_JTRIM)
    print("TRIM loops", nloops, "faces", len(rib.data.polygons))
    return rib


# ---------------------------------------------------------------------------
# HEAD + FACE  (built at 1.0 scale, scaled by HEAD_SCALE about HEAD_PIVOT later)
# ---------------------------------------------------------------------------
HEAD_C = Vector((0.0, -0.004, 1.845))


def build_head():
    bm = bmesh.new()
    bm_sphere(bm, (0, 0.006, 1.868), (0.113, 0.123, 0.128), 40, 24)        # cranium
    bm_sphere(bm, (0, -0.018, 1.785), (0.098, 0.100, 0.088), 32, 20)       # jaw/cheeks
    bm_sphere(bm, (0, -0.062, 1.738), (0.052, 0.046, 0.046), 24, 14)       # chin
    bm_sphere(bm, (0, -0.083, 1.882), (0.088, 0.038, 0.030), 24, 14)       # brow ridge
    for s in (1, -1):
        bm_sphere(bm, (0.056 * s, -0.078, 1.812), (0.034, 0.024, 0.026), 20, 12)  # cheekbones
    bm_limb(bm, (0, -0.112, 1.862), (0, -0.136, 1.812), 0.014, 0.020, 16)  # nose bridge
    bm_sphere(bm, (0, -0.128, 1.806), (0.030, 0.022, 0.018), 20, 12)       # nostrils
    for s in (1, -1):
        bm_sphere(bm, (0.112 * s, 0.002, 1.832), (0.020, 0.032, 0.044), 20, 12)  # ears
    bm_limb(bm, (0, 0.0, 1.70), (0, -0.004, 1.80), 0.060, 0.066)           # neck top inside head
    head = obj_from_bm("Head", bm)
    remesh(head, voxel=0.0042, smooth_iter=4, smooth_factor=0.5, target_tris=9000)
    hc.assign_material(head, M_SKIN)
    return head


def surface_point(bvh, origin, direction):
    hit = bvh.ray_cast(Vector(origin), Vector(direction).normalized(), 2.0)
    if hit[0] is None:
        raise RuntimeError("ray missed surface from %s" % (origin,))
    return hit[0], hit[1]


def build_face(head):
    bvh = BVHTree.FromObject(head, bpy.context.evaluated_depsgraph_get())
    bm = bmesh.new()
    feat = bmesh.new()
    for s in (1, -1):
        p, n = surface_point(bvh, (0.041 * s, -0.5, 1.846), (0, 1, 0))
        c = p + Vector((0, 0.010, 0))
        bm_sphere(bm, c, (0.0235, 0.016, 0.0185), 20, 12)
        bm_sphere(feat, c + Vector((0.0, -0.0135, 0.0005)), (0.0115, 0.0055, 0.0125), 16, 10)
    eyes = obj_from_bm("Eyes", bm)
    hc.assign_material(eyes, M_EYES)
    # eyebrows
    for s in (1, -1):
        pts = []
        for x, z in ((0.014, 1.880), (0.030, 1.887), (0.047, 1.890), (0.063, 1.888), (0.077, 1.882)):
            p, n = surface_point(bvh, (x * s, -0.5, z), (0, 1, 0))
            pts.append(p + n * 0.004)
        for i, (a, b) in enumerate(zip(pts[:-1], pts[1:])):
            r0 = 0.0080 - 0.0006 * i
            bm_limb(feat, a, b, r0, r0 - 0.0006, 12)
    # mouth
    mpts = []
    for x, z in ((-0.031, 1.752), (-0.016, 1.747), (0.0, 1.746), (0.016, 1.747), (0.032, 1.753)):
        p, n = surface_point(bvh, (x, -0.5, z), (0, 1, 0))
        mpts.append(p + n * 0.0015)
    for a, b in zip(mpts[:-1], mpts[1:]):
        bm_limb(feat, a, b, 0.0050, 0.0050, 12)
    dark = obj_from_bm("FaceDark", feat)
    remesh(dark, voxel=0.0014, smooth_iter=2, smooth_factor=0.5, target_tris=2500)
    hc.assign_material(dark, M_DARK)
    return [eyes, dark]


# ---------------------------------------------------------------------------
# HANDS
# ---------------------------------------------------------------------------
HAND_SCALE = 1.15


def build_hand_canonical():
    """Left hand in canonical space: +X = palm normal, +Y = fingers, +Z = thumb side. Wrist at origin."""
    bm = bmesh.new()
    bm_sphere(bm, (0.0, 0.050, 0.0), (0.020, 0.058, 0.046), 20, 12)
    bm_sphere(bm, (0.002, 0.020, 0.0), (0.020, 0.030, 0.038), 16, 10)
    for zc, length in ((0.030, 0.082), (0.010, 0.090), (-0.010, 0.085), (-0.029, 0.070)):
        base = Vector((0.0, 0.098, zc))
        mid = base + Vector((0.006, length * 0.55, -zc * 0.05))
        tip = base + Vector((0.020, length, -zc * 0.1))
        bm_limb(bm, base, mid, 0.0122, 0.0112, 12)
        bm_limb(bm, mid, tip, 0.0112, 0.0098, 12)
    t0 = Vector((0.004, 0.028, 0.034))
    t1 = Vector((0.012, 0.066, 0.058))
    t2 = Vector((0.026, 0.098, 0.060))
    bm_limb(bm, t0, t1, 0.016, 0.0135, 12)
    bm_limb(bm, t1, t2, 0.0135, 0.0115, 12)
    bmesh.ops.scale(bm, vec=(HAND_SCALE, HAND_SCALE, HAND_SCALE), verts=bm.verts[:])
    o = obj_from_bm("HandCanon", bm)
    remesh(o, voxel=0.0030, smooth_iter=3, smooth_factor=0.5, target_tris=2200)
    hc.assign_material(o, M_SKIN)
    return o


def place_hand(canon, side):
    sh, el, wr, tip, d = rig._arm_pts(1)
    A = rig.ARM_ABDUCTION
    palm_n = Vector((-math.cos(A), 0.0, -math.sin(A)))
    thumb = Vector((0.0, -1.0, 0.0))
    M = Matrix((palm_n, d, thumb)).transposed().to_4x4()
    M.translation = wr - d * 0.008
    o = bpy.data.objects.new("Hand_" + side, canon.data.copy())
    bpy.context.scene.collection.objects.link(o)
    o.data.transform(M)
    if side == "r":
        m2 = mirror_x_copy(o, "Hand_r")
        bpy.data.objects.remove(o)
        o = m2
    return o


# ---------------------------------------------------------------------------
# SHOES (left built, right mirrored)
# ---------------------------------------------------------------------------


def build_shoe_left():
    cx = 0.1225
    y_heel, y_toe = 0.088, -0.218
    L = y_heel - y_toe

    def width(t):
        return 0.086 + 0.036 * math.sin(math.pi * min(1.0, t * 1.05)) ** 0.8 - 0.012 * max(0, t - 0.85) / 0.15

    def height(t):
        return 0.178 - 0.106 * min(1.0, max(0.0, (t - 0.18) / 0.55)) ** 0.9

    nsec, narc = 22, 18
    bm = bmesh.new()
    rings = []
    for i in range(nsec + 1):
        t = i / nsec
        y = y_heel - L * t
        w = width(t) * 0.5
        h = height(t)
        ring = []
        for j in range(narc + 1):
            a = math.pi * j / narc
            x = cx + w * math.cos(a)
            z = 0.03 + (h - 0.03) * math.sin(a) ** 0.85
            ring.append(bm.verts.new((x, y, z)))
        rings.append(ring)
    for i in range(nsec):
        for j in range(narc):
            bm.faces.new((rings[i][j], rings[i + 1][j], rings[i + 1][j + 1], rings[i][j + 1]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    upper = obj_from_bm("ShoeUpper", bm)
    sm = upper.modifiers.new("Sub", "SUBSURF")
    sm.levels = 1
    hc.apply_modifiers(upper)
    hc.assign_material(upper, M_SHOE)
    bm = bmesh.new()
    bm.from_mesh(upper.data)
    hc.add_material_slot(upper, M_SACC)
    for f in bm.faces:
        c = f.calc_center_median()
        t = (y_heel - c.y) / L
        band = 0.055 + 0.05 * (1 - t)
        if abs(c.x - cx) > 0.035 and band - 0.018 < c.z < band + 0.012 and 0.08 < t < 0.75:
            f.material_index = 1
        if c.z > height(max(0.0, min(1.0, t))) - 0.022 and t < 0.25:
            f.material_index = 1
    bm.to_mesh(upper.data)
    bm.free()
    bm = bmesh.new()
    outline = []
    for i in range(40):
        a = 2 * math.pi * i / 40
        t = 0.5 - 0.5 * math.cos(a)
        y = y_heel + 0.006 - (L + 0.012) * t
        w = width(min(1.0, t)) * 0.5 + 0.007
        x = cx + w * (1 if math.sin(a) >= 0 else -1) * min(1.0, abs(math.sin(a)) * 3.0)
        outline.append((x, y))
    bot = [bm.verts.new((x, y, 0.0)) for x, y in outline]
    top = [bm.verts.new((x, y, 0.036)) for x, y in outline]
    n = len(outline)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((bot[i], bot[j], top[j], top[i]))
    bm.faces.new(list(reversed(bot)))
    bm.faces.new(top)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    sole = obj_from_bm("ShoeSole", bm)
    bev = sole.modifiers.new("Bevel", "BEVEL")
    bev.width = 0.006
    bev.segments = 2
    hc.apply_modifiers(sole)
    hc.assign_material(sole, M_SOLE)
    laces = []
    for k in range(5):
        t = 0.30 + k * 0.085
        y = y_heel - L * t
        h = height(t)
        laces.append(hc.box("Lace%d" % k, (width(t) * 0.55, 0.012, 0.008), location=(cx, y, h - 0.004), mat=M_SOLE))
    return hc.join([upper, sole] + laces, "Shoe_l")


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------


def smooth_weights(obj, blend=0.022, max_inf=4):
    groups = {n: obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n) for n in rig.DEFORM_BONES}
    for v in obj.data.vertices:
        p = v.co
        ds = [(n, seg_dist(p, a, b)) for n, (a, b) in SEGS.items()]
        dmin = min(d for _, d in ds)
        ws = [(n, math.exp(-((d - dmin) / blend) ** 2)) for n, d in ds if d - dmin < blend * 2.5]
        ws.sort(key=lambda t: -t[1])
        ws = ws[:max_inf]
        tot = sum(w for _, w in ws)
        for n, w in ws:
            if w / tot > 0.01:
                groups[n].add([v.index], w / tot, "REPLACE")


def rigid_weights(obj, bone):
    g = obj.vertex_groups.get(bone) or obj.vertex_groups.new(name=bone)
    g.add([v.index for v in obj.data.vertices], 1.0, "REPLACE")


def shoe_weights(obj, side):
    gf = obj.vertex_groups.new(name="foot_" + side)
    gb = obj.vertex_groups.new(name="ball_" + side)
    gc = obj.vertex_groups.new(name="calf_" + side)
    for v in obj.data.vertices:
        y, z = v.co.y, v.co.z
        tb = max(0.0, min(1.0, (-0.07 - y) / 0.05))
        tc = max(0.0, min(1.0, (z - 0.15) / 0.05)) * (1.0 - tb)
        wf = (1 - tb) * (1 - tc)
        if tb > 0:
            gb.add([v.index], tb, "REPLACE")
        if tc > 0:
            gc.add([v.index], tc * 0.6, "REPLACE")
        if wf + tc * 0.4 > 0:
            gf.add([v.index], wf + tc * 0.4, "REPLACE")


def transfer_weights(target, source):
    """Copy weights from the closest vertex of `source` (numbers/text/trim on the jersey)."""
    src_groups = {g.index: g.name for g in source.vertex_groups}
    verts = source.data.vertices
    kd = KDTree(len(verts))
    for v in verts:
        kd.insert(v.co, v.index)
    kd.balance()
    groups = {}
    for v in target.data.vertices:
        co, idx, dist = kd.find(v.co)
        for ge in verts[idx].groups:
            name = src_groups[ge.group]
            g = groups.get(name) or target.vertex_groups.get(name) or target.vertex_groups.new(name=name)
            groups[name] = g
            g.add([v.index], ge.weight, "REPLACE")


# ---------------------------------------------------------------------------
# HAIR / ACCESSORIES (built against the 1.0-scale head surface)
# ---------------------------------------------------------------------------


def hairline_z(c):
    phi = math.atan2(c.x, -(c.y - HEAD_C.y))  # 0 = front
    return 1.928 - 0.092 * (1 - math.cos(phi)) * 0.5


def scalp_cap(head, offset, extra=None, name="Cap", lower=0.0, thickness=None):
    bm = bmesh.new()
    bm.from_mesh(head.data)
    bm.normal_update()
    keep = set()
    for f in bm.faces:
        c = f.calc_center_median()
        if c.z > hairline_z(c) - lower:
            if abs(c.x) > 0.095 and 1.795 < c.z < 1.875 and abs(c.y) < 0.04:
                continue  # keep ears exposed
            keep.add(f)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f not in keep], context="FACES")
    for v in bm.verts:
        v.co += v.normal * (offset + (extra(v.co, v.normal) if extra else 0.0))
    o = obj_from_bm(name, bm)
    solidify(o, thickness if thickness else offset * 0.9 + 0.002, -1)
    return o


def ray_scalp(bvh, x0, ang_deg, center_z=1.84):
    ang = math.radians(ang_deg)
    dirv = Vector((0.0, -math.cos(ang), math.sin(ang)))
    origin = Vector((x0, HEAD_C.y, center_z)) + dirv * 0.4
    hit = bvh.ray_cast(origin, -dirv, 1.0)
    return hit[0], hit[1]


def build_hair_styles(head):
    styles = {}
    bvh = BVHTree.FromObject(head, bpy.context.evaluated_depsgraph_get())

    buzz = scalp_cap(head, 0.0035, name="Hair_Buzz")
    hc.assign_material(buzz, M_HAIR)
    styles["Buzz"] = buzz

    # high-top flat-top: faded sides + tall flat block
    sides = scalp_cap(head, 0.0028, name="FlatSides")
    bm = bmesh.new()
    ret = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=40,
                                radius1=0.109, radius2=0.115, depth=0.13)
    for v in ret["verts"]:
        v.co.y *= 1.10
        v.co += Vector((0, 0.008, 1.968))
    block = obj_from_bm("FlatBlock", bm)
    bev = block.modifiers.new("Bevel", "BEVEL")
    bev.width = 0.018
    bev.segments = 4
    bev.limit_method = "ANGLE"
    hc.apply_modifiers(block)
    ft = hc.join([sides, block], "Hair_Flattop")
    hc.assign_material(ft, M_HAIR)
    styles["Flattop"] = ft

    # afro: big rounded volume conforming to the hairline
    def afro_extra(c, n):
        z0 = hairline_z(c)
        t = max(0.0, min(1.0, (c.z - z0) / 0.05))
        t = t * t * (3 - 2 * t)
        back = max(0.0, c.y - HEAD_C.y) * 0.15
        return 0.004 + 0.072 * t + back
    af = scalp_cap(head, 0.004, extra=afro_extra, name="Hair_Afro", thickness=0.02)
    remesh(af, voxel=0.0055, smooth_iter=8, smooth_factor=0.7)
    # curly surface texture
    bm = bmesh.new()
    bm.from_mesh(af.data)
    bm.normal_update()
    for v in bm.verts:
        p = v.co
        v.co += v.normal * 0.0035 * (math.sin(p.x * 210) * math.sin(p.y * 190 + 1.3) * math.sin(p.z * 230 + 0.7))
    bm.to_mesh(af.data)
    bm.free()
    remesh(af, voxel=0.0045, smooth_iter=1, smooth_factor=0.3, target_tris=5000)
    hc.assign_material(af, M_HAIR)
    styles["Afro"] = af

    # cornrows
    bm = bmesh.new()
    for k in range(-4, 5):
        x0 = k * 0.021
        pts = []
        for i in range(17):
            p, n = ray_scalp(bvh, x0, -12 + 160 * i / 16.0)
            if p is None or p.z < hairline_z(p) - 0.002:
                continue
            pts.append(p + n * 0.006)
        for a, b in zip(pts[:-1], pts[1:]):
            bm_limb(bm, a, b, 0.0085, 0.0085, 8)
            bm_sphere(bm, (a + b) / 2, (0.0095, 0.0095, 0.0095), 8, 6)
    rows = obj_from_bm("Rows", bm)
    remesh(rows, voxel=0.003, smooth_iter=1, smooth_factor=0.3, target_tris=5000)
    braids = hc.join([scalp_cap(head, 0.0025, name="RowsBase"), rows], "Hair_Braids")
    hc.assign_material(braids, M_HAIR)
    styles["Braids"] = braids

    # mohawk: shaved sides + swept-back fin
    bm = bmesh.new()
    pts = []
    for i in range(16):
        p, n = ray_scalp(bvh, 0.0, 40 + 150 * i / 15.0)
        if p is None or p.z < hairline_z(p) - 0.01:
            continue
        pts.append((p, n))
    for k, (p, n) in enumerate(pts):
        t = k / max(1, len(pts) - 1)
        hgt = 0.045 + 0.03 * math.sin(math.pi * min(1.0, t * 1.2))
        tip = p + (n + Vector((0, 0.55, 0.15))).normalized() * hgt
        bm_limb(bm, p, tip, 0.020, 0.005, 10)
    fin = obj_from_bm("Fin", bm)
    remesh(fin, voxel=0.004, smooth_iter=2, smooth_factor=0.5, target_tris=3000)
    mohawk = hc.join([scalp_cap(head, 0.0022, name="MohawkBase"), fin], "Hair_Mohawk")
    hc.assign_material(mohawk, M_HAIR)
    styles["Mohawk"] = mohawk

    # short curls
    capc = scalp_cap(head, 0.006, name="CurlBase")
    bm = bmesh.new()
    for v in list(capc.data.vertices)[::7]:
        bm_sphere(bm, capc.matrix_world @ v.co, (0.011, 0.011, 0.011), 8, 6)
    curls = hc.join([capc, obj_from_bm("Bumps", bm)], "Hair_Curls")
    remesh(curls, voxel=0.004, smooth_iter=1, smooth_factor=0.3, target_tris=4500)
    hc.assign_material(curls, M_HAIR)
    styles["Curls"] = curls

    # bun
    bm = bmesh.new()
    bm_sphere(bm, (0, 0.085, 1.975), (0.048, 0.045, 0.045), 20, 12)
    bun = hc.join([scalp_cap(head, 0.0035, name="BunBase"), obj_from_bm("BunBall", bm)], "Hair_Bun")
    hc.assign_material(bun, M_HAIR)
    styles["Bun"] = bun
    return styles


def _head_region_shell(head, keep_fn, offset, thick, name):
    bm = bmesh.new()
    bm.from_mesh(head.data)
    bm.normal_update()
    keep = {f for f in bm.faces if keep_fn(f.calc_center_median())}
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f not in keep], context="FACES")
    for v in bm.verts:
        v.co += v.normal * offset
    o = obj_from_bm(name, bm)
    solidify(o, thick, -1)
    hc.assign_material(o, M_HAIR)
    return o


def build_beards(head):
    def full(c):
        ang = math.atan2(c.x, -(c.y - HEAD_C.y))
        if not (1.70 < c.z < 1.805 and abs(ang) < math.radians(100) and c.y < 0.04):
            return False
        return not (abs(c.x) < 0.038 and 1.735 < c.z < 1.765 and c.y < -0.06)

    def goatee(c):
        return (abs(c.x) < 0.04 and c.z < 1.742 and c.y < -0.03) or \
               (abs(c.x) < 0.034 and 1.758 < c.z < 1.772 and c.y < -0.06)

    return {"Full": _head_region_shell(head, full, 0.0055, 0.005, "Beard_Full"),
            "Goatee": _head_region_shell(head, goatee, 0.005, 0.005, "Beard_Goatee")}


def build_headband(head):
    bvh = BVHTree.FromObject(head, bpy.context.evaluated_depsgraph_get())
    bm = bmesh.new()
    n = 48
    rows = []
    for zz in (1.890, 1.925):
        ring = []
        for i in range(n):
            a = 2 * math.pi * i / n
            dirv = Vector((math.sin(a), -math.cos(a), 0.0))
            origin = Vector((0, HEAD_C.y, zz)) + dirv * 0.5
            hit = bvh.ray_cast(origin, -dirv, 1.0)
            p = hit[0] if hit[0] is not None else Vector((0, HEAD_C.y, zz)) + dirv * 0.12
            ring.append(bm.verts.new(p + dirv * 0.007))
        rows.append(ring)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((rows[0][i], rows[0][j], rows[1][j], rows[1][i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    o = obj_from_bm("Headband", bm)
    solidify(o, 0.008, 1)
    hc.assign_material(o, M_ACC)
    return o


def build_wristbands():
    parts = []
    for s in (1, -1):
        sh, el, wr, tip, d = rig._arm_pts(s)
        c0 = wr - d * 0.075
        c1 = wr - d * 0.005
        bm = bmesh.new()
        ret = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=24,
                                    radius1=0.0455, radius2=0.043, depth=(c1 - c0).length)
        rot = Vector((0, 0, 1)).rotation_difference(d).to_matrix().to_4x4()
        bmesh.ops.transform(bm, matrix=Matrix.Translation((c0 + c1) / 2) @ rot, verts=ret["verts"])
        o = obj_from_bm("Wrist_%d" % s, bm)
        bev = o.modifiers.new("Bevel", "BEVEL")
        bev.width = 0.004
        bev.segments = 2
        hc.apply_modifiers(o)
        parts.append(o)
    wb = hc.join(parts, "Wristbands")
    hc.assign_material(wb, M_ACC)
    return wb


def scale_head_parts(objs):
    M = Matrix.Translation(HEAD_PIVOT) @ Matrix.Scale(HEAD_SCALE, 4) @ Matrix.Translation(-HEAD_PIVOT)
    for o in objs:
        o.data.transform(M)
        o.data.update()


# ---------------------------------------------------------------------------
# Jersey numbers + team text wrapped on the chest/back
# ---------------------------------------------------------------------------


def wrap_text(body_bvh, text, center_x, center_z, height, front=True, depth=0.0018, name="Txt",
              font=hc.FONT_DIN, max_width=None, arc=0.0):
    o = hc.text_mesh(name, text, size=1.0, font_path=font, extrude=0.5, align_x="CENTER", align_y="CENTER")
    me = o.data
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    gh = max(ys) - min(ys)
    gw = max(xs) - min(xs)
    sc = height / gh
    sc_x = max_width / gw if (max_width and gw * sc > max_width) else sc
    yc = (max(ys) + min(ys)) / 2
    xc = (max(xs) + min(xs)) / 2
    for v in me.vertices:
        lx = (v.co.x - xc) * sc_x
        lz = (v.co.y - yc) * sc + center_z + arc * (lx * lx)
        dz = (v.co.z + 0.5)
        wx = center_x + (lx if front else -lx)
        if front:
            p, n = surface_point(body_bvh, (wx, -0.6, lz), (0, 1, 0))
        else:
            p, n = surface_point(body_bvh, (wx, 0.6, lz), (0, -1, 0))
        v.co = p + n * (0.0028 + depth * dz)
    me.update()
    return o


def build_numbers(body_bvh):
    out = {}
    for d in range(10):
        ch = str(d)
        for pos, fx, bx in (("T", -0.045, 0.056), ("O", 0.045, -0.056), ("C", 0.0, 0.0)):
            f = wrap_text(body_bvh, ch, fx, 1.272, 0.150, True, name="nf")
            b = wrap_text(body_bvh, ch, bx, 1.318, 0.190, False, name="nb")
            o = hc.join([f, b], "Num_%s%d" % (pos, d))
            hc.assign_material(o, M_NUM)
            out["%s%d" % (pos, d)] = o
    return out


TEAM_TEXT = {"NEO": "VOLTAGE", "BAY": "KRAKENS", "RRK": "SCORPIONS", "FRB": "YETIS", "STV": "FORGE", "SSC": "SURGE"}


def build_team_text(body_bvh):
    out = {}
    for abbr, word in TEAM_TEXT.items():
        o = wrap_text(body_bvh, word, 0.0, 1.398, 0.050, True, name="JT_" + abbr, font=hc.FONT_IMPACT,
                      max_width=0.20, arc=-0.9)
        hc.assign_material(o, M_JTEXT)
        o.name = "JerseyText_" + abbr
        out[abbr] = o
    return out


# ---------------------------------------------------------------------------
# Previews / export
# ---------------------------------------------------------------------------


def render_previews(player, hair, beards, headband, wrist, numbers, texts):
    show = [player, hair["Flattop"], headband, wrist, numbers["T2"], numbers["O3"], texts["NEO"]]
    hidden = [o for o in bpy.context.scene.objects if o.type == "MESH" and o not in show]
    for o in hidden:
        o.hide_render = True
    hc.setup_preview_render(res=(1400, 1000), samples=32)
    hc.add_sun("Key", rotation=(math.radians(55), 0, math.radians(-35)), energy=3.2)
    hc.add_sun("Fill", rotation=(math.radians(70), 0, math.radians(150)), energy=1.2)
    cam = hc.add_camera("Cam", (0.0, -5.2, 1.15), (0, 0, 1.0), lens=50)

    def shot(loc, target, name):
        cam.location = loc
        cam.rotation_euler = hc.look_at_rotation(loc, target)
        hc.render_to(os.path.join(hc.PREVIEW_DIR, name))

    shot((0.0, -5.2, 1.15), (0, 0, 1.0), "char_front.png")
    shot((5.2, 0.0, 1.15), (0, 0, 1.0), "char_side.png")
    shot((0.0, 5.2, 1.15), (0, 0, 1.0), "char_back.png")
    shot((0.38, -1.05, 1.93), (0, -0.02, 1.88), "char_face.png")
    shot((0.0, -1.6, 0.35), (0.0, -0.05, 0.12), "char_feet.png")
    shot((0.55, -1.25, 1.45), (0.0, 0.0, 1.32), "char_torso.png")
    shot((-0.5, 1.3, 1.45), (0.0, 0.0, 1.32), "char_torso_back.png")
    for o in [hair["Flattop"], headband]:
        o.hide_render = True
    styles = list(hair.items()) + [("Beard_" + k, v) for k, v in beards.items()] + [("Headband", headband)]
    for name, o in styles:
        o.hide_render = False
        shot((0.46, -1.0, 2.0), (0, 0, 1.9), "char_hair_%s.png" % name)
        o.hide_render = True
    for o in hidden + show:
        o.hide_render = False


def to_centimeters(objs):
    for o in objs:
        o.location = (0, 0, 0)
        o.rotation_euler = (0, 0, 0)
        o.scale = (S, S, S)
        hc.apply_transforms(o)


def bind(obj, arm):
    obj.parent = arm
    obj.matrix_parent_inverse = Matrix.Identity(4)
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm


def main():
    arm = rig.build_armature("Armature")

    body = build_body()
    dress_body(body)
    print("BODY tris after dress", tri_count(body))
    head = build_head()
    face = build_face(head)
    hair = build_hair_styles(head)
    beards = build_beards(head)
    headband = build_headband(head)
    scale_head_parts([head] + face + list(hair.values()) + list(beards.values()) + [headband])

    canon = build_hand_canonical()
    hand_l = place_hand(canon, "l")
    hand_r = place_hand(canon, "r")
    bpy.data.objects.remove(canon)
    shoe_l = build_shoe_left()
    shoe_r = mirror_x_copy(shoe_l, "Shoe_r")
    wrist = build_wristbands()

    # weights
    smooth_weights(body)
    trims = build_trim_ribbons(body)
    transfer_weights(trims, body)
    for o in [head] + face + list(hair.values()) + list(beards.values()) + [headband]:
        rigid_weights(o, "head")
    rigid_weights(hand_l, "hand_l")
    rigid_weights(hand_r, "hand_r")
    shoe_weights(shoe_l, "l")
    shoe_weights(shoe_r, "r")
    smooth_weights(wrist)

    body_bvh = BVHTree.FromObject(body, bpy.context.evaluated_depsgraph_get())
    numbers = build_numbers(body_bvh)
    texts = build_team_text(body_bvh)
    for o in list(numbers.values()) + list(texts.values()):
        transfer_weights(o, body)

    player = hc.join([body, trims, head] + face + [hand_l, hand_r, shoe_l, shoe_r], "SK_Player")
    for o in [player] + list(hair.values()) + list(beards.values()) + [headband, wrist]:
        hc.shade(o, smooth=True, angle=None)
    print("PLAYER tris", tri_count(player))

    render_previews(player, hair, beards, headband, wrist, numbers, texts)

    parts = {"SK_Player": player}
    for k, o in hair.items():
        parts["SK_Hair_" + k] = o
    for k, o in beards.items():
        parts["SK_Beard_" + k] = o
    parts["SK_Headband"] = headband
    parts["SK_Wristbands"] = wrist
    for k, o in numbers.items():
        parts["SK_Num_" + k] = o
    for k, o in texts.items():
        parts["SK_JerseyText_" + k] = o
    bpy.context.scene.unit_settings.scale_length = 0.01
    to_centimeters([arm] + list(parts.values()))
    for name, o in parts.items():
        o.name = name
        o.data.name = name
        bind(o, arm)
    for name, o in parts.items():
        hc.export_skeletal_fbx(arm, [o], name + ".fbx")

    mdir = os.path.join(hc.EXPORT_DIR, "Materials")
    os.makedirs(mdir, exist_ok=True)
    with open(os.path.join(mdir, "character.json"), "w") as fp:
        json.dump(MATS, fp, indent=2)
    man = os.path.join(hc.EXPORT_DIR, "Manifests")
    os.makedirs(man, exist_ok=True)
    stats = {n: tri_count(o) for n, o in parts.items()}
    with open(os.path.join(man, "character.json"), "w") as fp:
        json.dump({"tris": stats, "bones": [b[0] for b in rig.bone_table()],
                   "head_scale": HEAD_SCALE}, fp, indent=2)
    hc.save_blend("character.blend")
    print("CHARACTER DONE", stats["SK_Player"])


if __name__ == "__main__":
    main()
