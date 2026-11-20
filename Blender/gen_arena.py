"""HEAT CHECK - arena generator (bowl, crowd, LED ribbons, scorer's table, benches, jumbotron, light rig, banners).

Everything is modelled in arena/world coordinates (pivot = world origin, meters, Blender axes).
The game camera sits on the -Y side (~(x, -16, 9)) looking toward +Y, so the far sideline (+Y) is the
background of the game view. Nothing taller than 1.2 m is placed between y=-7.62 and y=-14 in front of the court.

Outputs (Art/Export/...)
  Meshes/SM_ArenaBowl.fbx            lower bowl, concourse, upper deck + facade, seats, aisle steps, shell (walls, roof)
  Meshes/SM_Crowd_<Lower|Upper><Far|Near|Left|Right>.fbx   low-poly fans (vertex colours, UV0 = (phase, amplitude))
  Meshes/SM_LedRibbon_Courtside.fbx  0.9 m LED boards on the lower-bowl front wall (far side + both baselines)
  Meshes/SM_LedRibbon_Facade.fbx     upper-deck facade ribbon (closed loop)
  Meshes/SM_ScorerTable.fbx, SM_TeamBenches.fbx, SM_Jumbotron.fbx, SM_LightRig.fbx, SM_Banners.fbx
  Textures/T_LedScroll.png (2048x256), T_JumboScreen.png (2048x1024), T_Banners.png (2048x1024)
  Materials/arena.json, Manifests/arena.json, Previews/arena_*.png

Run:  blender -b --factory-startup -P Blender/gen_arena.py   (after gen_branding.py for the banner badges)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import math  # noqa: E402
import time  # noqa: E402

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector  # noqa: E402

import env_helpers as eh  # noqa: E402
import hc_common as hc  # noqa: E402

T0 = time.time()


def log(*a):
    print("[arena %6.1fs]" % (time.time() - T0), *a, flush=True)


# ---------------------------------------------------------------------------
# Bowl layout: rounded rectangle rings, offset d measured outward from the lower-bowl front wall
# ---------------------------------------------------------------------------
HX, Y_FAR, Y_NEAR, RC = 19.3, 12.6, -14.6, 6.0
CY = (Y_FAR + Y_NEAR) / 2.0          # -0.8
HY = (Y_FAR - Y_NEAR) / 2.0          # 13.4
SX, SY = HX - RC, HY - RC            # straight half lengths (13.3, 7.4)

WALL_T, WALL_H = 0.30, 1.10          # lower front wall thickness / height
NL, ROW_D, ROW_RISE_L = 12, 0.85, 0.40
CONC_D0, CONC_D1, CONC_Z = NL * ROW_D, 12.0, WALL_H + NL * ROW_RISE_L      # concourse walkway
FAC_D, FAC_Z0, FAC_Z1 = 10.6, 8.2, 10.4                                    # upper deck facade face
UP_D0, UP_Z0, NU, ROW_RISE_U = 10.9, 9.5, 10, 0.55
UP_D1 = UP_D0 + NU * ROW_D                                                 # 19.4 = outer wall
ROOF_Z = 26.0
SEAT_PITCH = 0.55
AISLE_W = 1.1
AISLE_X = (-10.4, -3.5, 3.5, 10.4)   # aisles on the long sides (radial lines at fixed x)
AISLE_Y = (-3.8, 2.2)                # aisles on the baselines (fixed y)


def piece_lengths(d):
    a = (RC + d) * math.pi / 2
    return [2 * SY, a, 2 * SX, a, 2 * SY, a, 2 * SX, a]


def path_eval(d, s):
    """Point (x, y) and outward normal (nx, ny) at arclength s (CCW, s=0 at the right baseline's near end)."""
    L = piece_lengths(d)
    tot = sum(L)
    s = s % tot
    i = 0
    while s > L[i] and i < 7:
        s -= L[i]
        i += 1
    r = RC + d
    if i == 0:
        return (HX + d, CY - SY + s), (1.0, 0.0)
    if i == 2:
        return (SX - s, CY + HY + d), (0.0, 1.0)
    if i == 4:
        return (-HX - d, CY + SY - s), (-1.0, 0.0)
    if i == 6:
        return (-SX + s, CY - HY - d), (0.0, -1.0)
    cx, cy, a0 = {1: (SX, CY + SY, 0.0), 3: (-SX, CY + SY, 90.0), 5: (-SX, CY - SY, 180.0),
                  7: (SX, CY - SY, 270.0)}[i]
    a = math.radians(a0) + s / r
    return (cx + r * math.cos(a), cy + r * math.sin(a)), (math.cos(a), math.sin(a))


def piece_start(d, i):
    return sum(piece_lengths(d)[:i])


def aisle_s(d):
    out = []
    for y in AISLE_Y:
        out.append(piece_start(d, 0) + (y - (CY - SY)))
        out.append(piece_start(d, 4) + ((CY + SY) - y))
    for x in AISLE_X:
        out.append(piece_start(d, 2) + (SX - x))
        out.append(piece_start(d, 6) + (x + SX))
    for i in (1, 3, 5, 7):
        out.append(piece_start(d, i) + (RC + d) * math.pi / 4)
    return sorted(out)


def ring(d, arc_seg=24, pieces=range(8)):
    """Ring sample points (x, y) at offset d, consistent radial correspondence across offsets."""
    pts, nrm = [], []
    for i in pieces:
        if i in (0, 2, 4, 6):
            s0 = piece_start(d, i)
            for t in (0.0, 1.0):
                if t == 1.0 and i != pieces[-1]:
                    continue
                p, n = path_eval(d, s0 + t * piece_lengths(d)[i] - (1e-9 if t == 1.0 else 0.0))
                pts.append(p)
                nrm.append(n)
        else:
            s0 = piece_start(d, i)
            La = piece_lengths(d)[i]
            last = (i == pieces[-1])
            for k in range(arc_seg + (1 if last else 0)):
                p, n = path_eval(d, s0 + La * k / arc_seg - (1e-9 if k == arc_seg else 0.0))
                pts.append(p)
                nrm.append(n)
    return pts, nrm


def tread_z(row):
    """(z, d_front) of a tread. Rows 0..NL-1 lower bowl, NL..NL+NU-1 upper deck."""
    if row < NL:
        return WALL_H + ROW_RISE_L * row, ROW_D * row
    j = row - NL
    return UP_Z0 + ROW_RISE_U * j, UP_D0 + ROW_D * j


# ---------------------------------------------------------------------------
# Generic band builders (MeshBuilder quads)
# ---------------------------------------------------------------------------
def hband(mb, da, db, z, mat, up=True, arc_seg=24, closed=True):
    A, _ = ring(da, arc_seg)
    B, _ = ring(db, arc_seg)
    n = len(A)
    for i in range(n if closed else n - 1):
        j = (i + 1) % n
        a0, a1, b0, b1 = (A[i][0], A[i][1], z), (A[j][0], A[j][1], z), (B[i][0], B[i][1], z), (B[j][0], B[j][1], z)
        if up:
            mb.quad(a0, b0, b1, a1, mat=mat)
        else:
            mb.quad(a0, a1, b1, b0, mat=mat)


def vband(mb, d, za, zb, mat, inward=True, arc_seg=24):
    A, _ = ring(d, arc_seg)
    n = len(A)
    for i in range(n):
        j = (i + 1) % n
        p0, p1 = A[i], A[j]
        if inward:
            mb.quad((p0[0], p0[1], za), (p0[0], p0[1], zb), (p1[0], p1[1], zb), (p1[0], p1[1], za), mat=mat)
        else:
            mb.quad((p0[0], p0[1], za), (p1[0], p1[1], za), (p1[0], p1[1], zb), (p0[0], p0[1], zb), mat=mat)


# ---------------------------------------------------------------------------
# Numpy instancing (templates of quads with colour roles)
# ---------------------------------------------------------------------------
ROLE_SHIRT, ROLE_PANTS, ROLE_SKIN, ROLE_HAIR, ROLE_HAT, ROLE_PROP, ROLE_SLEEVE = range(7)


class Tpl:
    def __init__(self):
        self.v = []
        self.f = []
        self.r = []

    def _box8(self, P, roles, skip=()):
        """P: 8 corners (bottom ring CCW about the box axis, then top ring). roles: dict face->role."""
        base = len(self.v)
        self.v.extend(P)
        b = [base + i for i in range(4)]
        t = [base + 4 + i for i in range(4)]
        faces = {"s0": (b[0], b[1], t[1], t[0]), "s1": (b[1], b[2], t[2], t[1]), "s2": (b[2], b[3], t[3], t[2]),
                 "s3": (b[3], b[0], t[0], t[3]), "top": (t[0], t[1], t[2], t[3]), "bot": (b[3], b[2], b[1], b[0])}
        for k, f in faces.items():
            if k in skip:
                continue
            self.f.append(f)
            self.r.append(roles.get(k, roles.get("all", 0)))

    def frustum(self, c0, h0, c1, h1, roles, skip=("bot",)):
        P = []
        for (c, h) in ((c0, h0), (c1, h1)):
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                P.append((c[0] + sx * h[0], c[1] + sy * h[1], c[2]))
        self._box8(P, roles, skip)

    def obox(self, A, B, hw, hd, roles, skip=()):
        A, B = Vector(A), Vector(B)
        a = (B - A).normalized()
        up = Vector((0, 0, 1)) if abs(a.z) < 0.95 else Vector((1, 0, 0))
        e1 = a.cross(up).normalized()
        e2 = a.cross(e1)
        P = []
        for c in (A, B):
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                P.append(tuple(c + e1 * (sx * hw) + e2 * (sy * hd)))
        self._box8(P, roles, skip)

    def arrays(self):
        return np.array(self.v, np.float32), np.array(self.f, np.int32), np.array(self.r, np.int32)


def head(t, cx, cy, z0, s=1.0):
    t.frustum((cx, cy, z0), (0.07 * s, 0.08 * s), (cx, cy, z0 + 0.11 * s), (0.10 * s, 0.11 * s),
              {"all": ROLE_SKIN}, skip=("bot", "top"))
    t.frustum((cx, cy, z0 + 0.11 * s), (0.10 * s, 0.11 * s), (cx, cy - 0.01, z0 + 0.245 * s), (0.075 * s, 0.085 * s),
              {"all": ROLE_HAIR, "s2": ROLE_SKIN, "top": ROLE_HAIR}, skip=("bot",))
    return z0 + 0.245 * s


def make_templates():
    T = {}
    # seated: seat front edge at y=0, seat pan top z=0.46, facing +Y
    t = Tpl()
    t.frustum((0, -0.14, 0.46), (0.17, 0.22), (0, -0.14, 0.60), (0.17, 0.22), {"all": ROLE_PANTS})
    t.frustum((0, 0.03, 0.0), (0.155, 0.07), (0, 0.03, 0.52), (0.16, 0.07), {"all": ROLE_PANTS})
    t.frustum((0, -0.25, 0.58), (0.16, 0.10), (0, -0.29, 1.12), (0.21, 0.11), {"all": ROLE_SHIRT})
    head(t, 0, -0.29, 1.16)
    for sx in (-1, 1):
        t.obox((sx * 0.235, -0.29, 1.09), (sx * 0.19, 0.0, 0.66), 0.05, 0.05, {"all": ROLE_SLEEVE})
    T["seated"] = t.arrays()
    # standing variants: feet at z=0, body centre y=0.15
    def standing(arms):
        t = Tpl()
        t.frustum((0, 0.15, 0.0), (0.15, 0.09), (0, 0.15, 0.86), (0.165, 0.10), {"all": ROLE_PANTS})
        t.frustum((0, 0.15, 0.84), (0.16, 0.10), (0, 0.14, 1.42), (0.21, 0.11), {"all": ROLE_SHIRT})
        head(t, 0, 0.14, 1.46)
        for sx in (-1, 1):
            hand = arms(sx)
            t.obox((sx * 0.235, 0.14, 1.38), hand, 0.05, 0.05, {"all": ROLE_SLEEVE})
        return t
    T["standing"] = standing(lambda sx: (sx * 0.27, 0.17, 0.80)).arrays()
    T["clap"] = standing(lambda sx: (sx * 0.05, 0.43, 1.28)).arrays()
    T["armsup"] = standing(lambda sx: (sx * 0.50, 0.21, 2.02)).arrays()
    T["pump"] = standing(lambda sx: (0.30, 0.22, 2.05) if sx > 0 else (-0.27, 0.17, 0.80)).arrays()
    # extras
    def cap(cy, ztop):
        t = Tpl()
        t.frustum((0, cy, ztop - 0.045), (0.105, 0.115), (0, cy - 0.01, ztop + 0.025), (0.095, 0.105),
                  {"all": ROLE_HAT})
        t.frustum((0, cy + 0.16, ztop - 0.05), (0.09, 0.07), (0, cy + 0.16, ztop - 0.03), (0.09, 0.07),
                  {"all": ROLE_HAT}, skip=())
        return t.arrays()
    T["cap_seated"] = cap(-0.29, 1.16 + 0.245)
    T["cap_standing"] = cap(0.14, 1.46 + 0.245)
    t = Tpl()
    hand = Vector((0.50, 0.21, 2.02))
    dirv = (hand - Vector((0.235, 0.14, 1.38))).normalized()
    t.obox(tuple(hand - dirv * 0.05), tuple(hand + dirv * 0.40), 0.075, 0.03, {"all": ROLE_PROP})
    T["finger_armsup"] = t.arrays()
    t = Tpl()
    hand = Vector((0.30, 0.22, 2.05))
    dirv = (hand - Vector((0.235, 0.14, 1.38))).normalized()
    t.obox(tuple(hand - dirv * 0.05), tuple(hand + dirv * 0.40), 0.075, 0.03, {"all": ROLE_PROP})
    T["finger_pump"] = t.arrays()
    t = Tpl()
    t.frustum((0, 0.25, 1.86), (0.45, 0.015), (0, 0.25, 2.36), (0.45, 0.015), {"all": ROLE_PROP}, skip=())
    T["sign"] = t.arrays()
    # seat: pan + reclined back, single role
    t = Tpl()
    t.frustum((0, -0.21, 0.40), (0.22, 0.20), (0, -0.21, 0.46), (0.22, 0.20), {"all": 0})
    t.frustum((0, -0.43, 0.42), (0.22, 0.03), (0, -0.48, 0.88), (0.22, 0.03), {"all": 0})
    T["seat"] = t.arrays()
    return T


def instance(tpl, P, yaw, scale, role_cols=None, uv=None):
    """Instance template (V,F,R) N times. P (N,3), yaw (N,), scale (N,3); role_cols (N,nroles,3) linear;
    uv (N,2). Returns verts (N*V,3), faces (N*F,4), colors per corner (N*F*4,4) or None, uvs per corner or None."""
    V, F, R = tpl
    N = len(P)
    if N == 0:
        return None
    S = V[None, :, :] * scale[:, None, :]
    c, s = np.cos(yaw)[:, None], np.sin(yaw)[:, None]
    X = c * S[..., 0] - s * S[..., 1] + P[:, 0:1]
    Y = s * S[..., 0] + c * S[..., 1] + P[:, 1:2]
    Z = S[..., 2] + P[:, 2:3]
    verts = np.stack([X, Y, Z], -1).reshape(-1, 3).astype(np.float32)
    faces = (F[None, :, :] + (np.arange(N) * len(V))[:, None, None]).reshape(-1, 4).astype(np.int32)
    cols = None
    if role_cols is not None:
        fc = role_cols[:, R, :]                                   # (N, F, 3)
        fc = np.repeat(fc[:, :, None, :], 4, axis=2).reshape(-1, 3)
        cols = np.concatenate([fc, np.ones((len(fc), 1), np.float32)], 1).astype(np.float32)
    uvs = None
    if uv is not None:
        uvs = np.repeat(uv[:, None, :], len(F) * 4, axis=1).reshape(-1, 2).astype(np.float32)
    return verts, faces, cols, uvs


def merge(chunks):
    chunks = [c for c in chunks if c is not None]
    if not chunks:
        return None
    vs, fs, cs, us = [], [], [], []
    off = 0
    for v, f, c, u in chunks:
        vs.append(v)
        fs.append(f + off)
        off += len(v)
        cs.append(c)
        us.append(u)
    V = np.concatenate(vs)
    F = np.concatenate(fs)
    C = np.concatenate(cs) if all(c is not None for c in cs) else None
    U = np.concatenate(us) if all(u is not None for u in us) else None
    return V, F, C, U


# ---------------------------------------------------------------------------
# Seats + crowd
# ---------------------------------------------------------------------------
def seat_positions():
    """All seats: list of dict arrays: pos (x,y,z of seat-front edge at tread level), inward yaw, row, section."""
    P, YAW, ROW, ANG = [], [], [], []
    for row in range(NL + NU):
        z, d0 = tread_z(row)
        d = d0 + 0.38
        L = sum(piece_lengths(d))
        A = aisle_s(d)
        for k in range(len(A)):
            s0 = A[k] + AISLE_W / 2
            s1 = (A[(k + 1) % len(A)] + (L if k == len(A) - 1 else 0.0)) - AISLE_W / 2
            span = s1 - s0
            n = int(span // SEAT_PITCH)
            if n <= 0:
                continue
            start = s0 + (span - (n - 1) * SEAT_PITCH) / 2
            for m in range(n):
                (x, y), (nx, ny) = path_eval(d, start + m * SEAT_PITCH)
                if abs(x) < 17.6 and -14.3 < y < -7.0:
                    continue  # keep the near-side camera clear zone free (corner seats only)
                P.append((x, y, z))
                YAW.append(math.atan2(-ny, -nx) - math.pi / 2)  # template +Y -> inward
                ROW.append(row)
                ANG.append(math.atan2(y - CY, x))
    return (np.array(P, np.float32), np.array(YAW, np.float32), np.array(ROW, np.int32), np.array(ANG, np.float32))


def section_of(pos, row):
    x, y = pos[0], pos[1]
    ang = math.degrees(math.atan2((y - CY) / HY, x / HX))
    if -45 <= ang < 45:
        side = "Right"
    elif 45 <= ang < 135:
        side = "Far"
    elif -135 <= ang < -45:
        side = "Near"
    else:
        side = "Left"
    return ("Lower" if row < NL else "Upper") + side


SHIRTS_FLAME = ["#E63312", "#FF7A00", "#FFC300", "#C8200E", "#FF5A1F", "#B5170A"]
SHIRTS_MISC = ["#F2F2F2", "#E6E6E6", "#1A1A1E", "#24262B", "#2B3A55", "#1F4E8C", "#3B7A3B", "#6B3FA0",
               "#8C8C8C", "#C9B79C", "#0F6E6A", "#A8324A"]
PANTS = ["#2B3A55", "#1A1A1E", "#3D5A80", "#55585E", "#7D6E55", "#2A2A2A", "#3B4A63"]
SKINS = ["#FFDBAC", "#F1C27D", "#E0AC69", "#C68642", "#A86B3C", "#8D5524", "#6B3E1F", "#4A2A16"]
HAIRS = ["#140D07", "#2B1A0F", "#3B2416", "#6A4E2E", "#A5793F", "#C9A45C", "#8C3A1A", "#9A9A9A", "#D9D3C7"]
PROPS = ["#FFC300", "#FF7A00", "#E63312", "#F7F4EE", "#00E5FF", "#FFD60A"]


def build_crowd_and_seats(T, rng):
    P, YAW, ROW, ANG = seat_positions()
    N = len(P)
    log("seats", N)
    team_cols = [c for t in eh.TEAMS for c in (t["primary"], t["secondary"])]

    def lin_list(hexes):
        return np.array([eh.lin(h) for h in hexes], np.float32)
    flame, misc, pants, skins, hairs, props, teams = map(lin_list, (SHIRTS_FLAME, SHIRTS_MISC, PANTS, SKINS, HAIRS,
                                                                   PROPS, team_cols))
    occ = rng.random(N) < 0.90
    # energy: lower rows + baseline "hype" sections bounce more
    energy = np.where(ROW < 4, 0.45, np.where(ROW < NL, 0.30, 0.22))
    sec_boost = (np.sin(ANG * 3.0 + 1.3) > 0.55) * 0.15
    energy = energy + sec_boost
    r = rng.random(N)
    pose = np.full(N, "seated", dtype=object)
    p_stand = energy
    pose[r < p_stand] = "standing"
    r2 = rng.random(N)
    m = pose == "standing"
    pose[m & (r2 < 0.30)] = "clap"
    pose[m & (r2 >= 0.30) & (r2 < 0.50)] = "armsup"
    pose[m & (r2 >= 0.50) & (r2 < 0.62)] = "pump"
    # colours per fan
    kind = rng.random(N)
    shirt = np.where((kind < 0.24)[:, None], flame[rng.integers(0, len(flame), N)],
                     np.where((kind < 0.50)[:, None], teams[rng.integers(0, len(teams), N)],
                              misc[rng.integers(0, len(misc), N)]))
    shirt = shirt * rng.uniform(0.85, 1.1, (N, 1)).astype(np.float32)
    skin = skins[rng.integers(0, len(skins), N)]
    hair = hairs[rng.integers(0, len(hairs), N)]
    pant = pants[rng.integers(0, len(pants), N)]
    hat = np.where((rng.random(N) < 0.5)[:, None], flame[rng.integers(0, len(flame), N)],
                   teams[rng.integers(0, len(teams), N)])
    prop = props[rng.integers(0, len(props), N)]
    sleeve = np.where((rng.random(N) < 0.45)[:, None], shirt, skin)
    role_cols = np.stack([shirt, pant, skin, hair, hat, prop, sleeve], 1).astype(np.float32)
    # scale: build + height, a few kids
    hs = rng.uniform(0.93, 1.07, N)
    kid = rng.random(N) < 0.05
    hs[kid] *= 0.78
    ws = rng.uniform(0.92, 1.16, N) * np.where(kid, 0.82, 1.0)
    scale = np.stack([ws, np.ones(N) * np.where(kid, 0.85, 1.0), hs], 1).astype(np.float32)
    yaw = YAW + rng.normal(0, 0.12, N).astype(np.float32)
    phase = rng.random(N).astype(np.float32)
    amp = np.select([pose == "seated", pose == "standing", pose == "clap", pose == "pump", pose == "armsup"],
                    [rng.uniform(0.05, 0.35, N), rng.uniform(0.45, 0.8, N), rng.uniform(0.5, 0.85, N),
                     rng.uniform(0.65, 0.95, N), rng.uniform(0.75, 1.0, N)]).astype(np.float32)
    uv = np.stack([phase, amp], 1)
    secs = np.array([section_of(P[i], ROW[i]) for i in range(N)], dtype=object)
    has_cap = rng.random(N) < 0.14
    has_finger = (rng.random(N) < 0.30) & ((pose == "armsup") | (pose == "pump"))
    has_sign = (rng.random(N) < 0.10) & (pose == "armsup") & ~has_finger

    crowd = {}
    counts = {}
    for sec in sorted(set(secs)):
        chunks = []
        msec = (secs == sec) & occ
        for pname in ("seated", "standing", "clap", "armsup", "pump"):
            mm = msec & (pose == pname)
            idx = np.nonzero(mm)[0]
            if len(idx) == 0:
                continue
            chunks.append(instance(T[pname], P[idx], yaw[idx], scale[idx], role_cols[idx], uv[idx]))
            cap_t = T["cap_seated"] if pname == "seated" else T["cap_standing"]
            ci = idx[has_cap[idx]]
            chunks.append(instance(cap_t, P[ci], yaw[ci], scale[ci], role_cols[ci], uv[ci]))
            if pname in ("armsup", "pump"):
                fi = idx[has_finger[idx]]
                chunks.append(instance(T["finger_" + pname], P[fi], yaw[fi], scale[fi], role_cols[fi], uv[fi]))
            if pname == "armsup":
                si = idx[has_sign[idx]]
                chunks.append(instance(T["sign"], P[si], yaw[si], scale[si], role_cols[si], uv[si]))
        crowd[sec] = merge(chunks)
        counts[sec] = int(msec.sum())
    # seats (all seats, lower red / upper dark)
    seat_scale = np.ones((N, 3), np.float32)
    lower = ROW < NL
    seats_lo = instance(T["seat"], P[lower], YAW[lower], seat_scale[lower])
    seats_up = instance(T["seat"], P[~lower], YAW[~lower], seat_scale[~lower])
    stats = dict(seats=int(N), fans=int(occ.sum()), sections=counts,
                 poses={k: int(((pose == k) & occ).sum()) for k in ("seated", "standing", "clap", "armsup", "pump")})
    return crowd, seats_lo, seats_up, stats


# ---------------------------------------------------------------------------
# Textures (flat renders)
# ---------------------------------------------------------------------------
def wordmark_flat(name, text, cap_h, center, z, fill, outlines=(), font=eh.FONT_IMPACT, shear=0.14, width=None):
    o = eh.text_obj(name, text, 1.0, font=font, mat=fill, shear=shear, resolution=12)
    if width is not None:
        eh.fit_obj(o, width=width, center=center)
    else:
        eh.fit_obj(o, height=cap_h, center=center)
    eh.set_z(o, z)
    for i, (d, m) in enumerate(outlines):
        eh.dilate_mesh_obj(o, name + "_ol%d" % i, d, z=z - 0.002 * (i + 1), mat=m)
    return o


def flame_mats():
    return dict(red=eh.flat_mat("F_Red", eh.RED), orange=eh.flat_mat("F_Orange", eh.ORANGE),
                yellow=eh.flat_mat("F_Yellow", eh.YELLOW), ball=eh.flat_mat("F_Ball", "#F06A12"),
                seam=eh.flat_mat("F_Seam", "#17181C"), shine=eh.flat_mat("F_Shine", "#FF9A3D"),
                outline=eh.flat_mat("F_Deep", "#7A1005"), outline2=eh.flat_mat("F_White", "#FFFFFF"))


def led_grid(img, period=4, dark=0.88):
    h, w = img.shape[:2]
    gy = (np.arange(h) % period == period - 1)[:, None]
    gx = (np.arange(w) % period == period - 1)[None, :]
    m = np.where(gy | gx, dark, 1.0).astype(np.float32)
    out = img.copy()
    out[..., :3] *= m[..., None]
    return out


def render_led_texture():
    eh.clear_scene()
    W_, H_ = 8.0, 1.0
    black = eh.flat_mat("F_Black", "#050506")
    white = eh.flat_mat("F_White", "#FFFFFF")
    dark = eh.flat_mat("F_Dark", "#140504")
    eh.fill_obj("bg", [[(-0.1, -0.1), (W_ + 0.1, -0.1), (W_ + 0.1, H_ + 0.1), (-0.1, H_ + 0.1)]], 0.0, black)
    glow = eh.gradient_mat("F_Glow", [(0.0, "#5A1206"), (1.0, "#050506")], v0=0.0, v1=1.9, center=(2.4, 0.5))
    eh.fill_obj("glow", [[(0.2, 0.0), (4.4, 0.0), (4.4, 1.0), (0.2, 1.0)]], 0.0005, glow)
    FM = flame_mats()
    eh.build_flame_mark("lm", (0.62, 0.33), 0.16, 0.002, FM, outline=0.018, outline2=0.012, seam_w=0.11)
    fill = eh.gradient_mat("F_WG", [(0.0, "#D21E0A"), (0.45, eh.ORANGE), (1.0, "#FFE04A")], axis="Y", v0=0.22,
                           v1=0.78)
    wordmark_flat("wm", "HEAT CHECK", 0.54, (2.62, 0.50), 0.02, fill, outlines=((0.018, white), (0.04, dark)))
    # chevrons
    for k, col in enumerate((eh.RED, eh.ORANGE, eh.YELLOW)):
        x0 = 4.42 + 0.17 * k
        eh.fill_obj("chev%d" % k, [[(x0, 0.0), (x0 + 0.10, 0.0), (x0 + 0.22, 0.5), (x0 + 0.10, 1.0), (x0, 1.0),
                                    (x0 + 0.12, 0.5)]], 0.01, eh.flat_mat("F_ch%d" % k, col))
    panel = eh.gradient_mat("F_Panel", [(0.0, "#A3150A"), (0.5, "#E63312"), (1.0, "#FF6A1A")], axis="Y", v0=0.0,
                            v1=1.0)
    eh.fill_obj("panel", [[(5.02, 0.0), (7.62, 0.0), (7.86, 1.0), (5.26, 1.0)]], 0.005, panel)
    stripes = eh.flat_mat("F_Str", "#FFFFFF", alpha=0.10)
    for k in range(9):
        x0 = 5.15 + 0.30 * k
        eh.fill_obj("st%d" % k, [[(x0, 0.0), (x0 + 0.09, 0.0), (x0 + 0.33, 1.0), (x0 + 0.24, 1.0)]], 0.006, stripes)
    wordmark_flat("bth", "BRING THE HEAT", None, (6.44, 0.50), 0.02, white, outlines=((0.025, dark),),
                  width=2.3)
    eh.flat_scene(2048, 256, samples=16, transparent=False)
    eh.ortho_camera(W_ / 2, H_ / 2, W_)
    img = eh.render_rgba("led")
    img = led_grid(img, 4, 0.90)
    eh.save_png(img[..., :3], os.path.join(eh.TEX_DIR, "T_LedScroll.png"))
    return img


def render_jumbo_texture():
    eh.clear_scene()
    W_, H_ = 2.0, 1.0
    bg = eh.gradient_mat("F_JBg", [(0.0, "#7A1A08"), (0.45, "#3A0A05"), (1.0, "#0A0303")], v0=0.0, v1=1.15,
                         center=(1.0, 0.56))
    eh.fill_obj("bg", [[(-0.05, -0.05), (W_ + 0.05, -0.05), (W_ + 0.05, H_ + 0.05), (-0.05, H_ + 0.05)]], 0.0, bg)
    ray = eh.flat_mat("F_Ray", "#FF7A00", alpha=0.07)
    for k in range(14):
        a = 2 * math.pi * k / 14 + 0.1
        da = 0.07
        eh.fill_obj("ray%d" % k, [[(1.0, 0.56), (1.0 + 3 * math.cos(a - da), 0.56 + 3 * math.sin(a - da)),
                                   (1.0 + 3 * math.cos(a + da), 0.56 + 3 * math.sin(a + da))]], 0.001, ray)
    FM = flame_mats()
    eh.build_flame_mark("jm", (1.0, 0.505), 0.105, 0.003, FM, outline=0.012, outline2=0.008, seam_w=0.11)
    white = eh.flat_mat("F_White", "#FFFFFF")
    dark = eh.flat_mat("F_Dark", "#140504")
    fill = eh.gradient_mat("F_WG", [(0.0, "#D21E0A"), (0.45, eh.ORANGE), (1.0, "#FFE04A")], axis="Y", v0=0.165,
                           v1=0.335)
    wordmark_flat("wm", "HEAT CHECK", 0.17, (1.0, 0.25), 0.02, fill, outlines=((0.008, white), (0.018, dark)))
    wordmark_flat("arena", "A R E N A", 0.042, (1.0, 0.105), 0.02, white, font=eh.FONT_DIN, shear=0.0)
    line = eh.flat_mat("F_Line", eh.ORANGE)
    for sx in (-1, 1):
        eh.fill_obj("ln%d" % sx, [[(1.0 + sx * 0.13, 0.102), (1.0 + sx * 0.42, 0.102), (1.0 + sx * 0.42, 0.108),
                                   (1.0 + sx * 0.13, 0.108)]], 0.02, line)
    border = eh.flat_mat("F_Border", "#FF5A1F")
    eh.stroke_obj("border", [[(0.025, 0.04), (1.975, 0.04), (1.975, 0.96), (0.025, 0.96)]], 0.004, 0.02, border,
                  closed=True)
    eh.flat_scene(2048, 1024, samples=16, transparent=False)
    eh.ortho_camera(W_ / 2, H_ / 2, W_)
    img = eh.render_rgba("jumbo")
    img = led_grid(img, 4, 0.93)
    eh.save_png(img[..., :3], os.path.join(eh.TEX_DIR, "T_JumboScreen.png"))


def resize_bilinear(img, w, h):
    H0, W0 = img.shape[:2]
    ys = (np.arange(h) + 0.5) * H0 / h - 0.5
    xs = (np.arange(w) + 0.5) * W0 / w - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, H0 - 1)
    x0 = np.clip(np.floor(xs).astype(int), 0, W0 - 1)
    y1 = np.clip(y0 + 1, 0, H0 - 1)
    x1 = np.clip(x0 + 1, 0, W0 - 1)
    fy = np.clip(ys - y0, 0, 1)[:, None, None]
    fx = np.clip(xs - x0, 0, 1)[None, :, None]
    a = img[y0][:, x0] * (1 - fx) + img[y0][:, x1] * fx
    b = img[y1][:, x0] * (1 - fx) + img[y1][:, x1] * fx
    return (a * (1 - fy) + b * fy).astype(np.float32)


def render_banner_texture():
    """8 hanging banners (256x1024 each): 6 teams + 2 arena banners; alpha cuts a V notch at the bottom."""
    eh.clear_scene()
    W_, H_ = 8.0, 4.0
    entries = list(eh.TEAMS) + [None, None]
    order = [6, 0, 1, 2, 3, 4, 5, 7]  # arena banners at both ends
    white = eh.flat_mat("F_White", "#FFFFFF")
    dark = eh.flat_mat("F_Dark", "#0D0D10")
    for slot, ei in enumerate(order):
        t = entries[ei]
        x0 = float(slot)
        if t is None:
            bgm = eh.gradient_mat("F_Bg%d" % slot, [(0.0, "#2A0805"), (1.0, "#17181C")], axis="Y", v0=0.4, v1=3.6)
        else:
            c_hi = eh.srgb(t["primary"])
            c_lo = tuple(v * 0.55 for v in c_hi)
            bgm = eh.gradient_mat("F_Bg%d" % slot, [(0.0, c_lo), (1.0, c_hi)], axis="Y", v0=0.3, v1=3.9)
        eh.fill_obj("bg%d" % slot, [[(x0, 0.0), (x0 + 1, 0.0), (x0 + 1, 4.0), (x0, 4.0)]], 0.0, bgm)
        acc = eh.flat_mat("F_Acc%d" % slot, eh.ORANGE if t is None else t["secondary"])
        acc2 = eh.flat_mat("F_Acc2%d" % slot, eh.YELLOW if t is None else t["accent"])
        for (y, h, m) in ((3.86, 0.06, acc), (3.80, 0.025, acc2), (0.62, 0.05, acc), (0.70, 0.02, acc2)):
            eh.fill_obj("band%d_%f" % (slot, y), [[(x0, y), (x0 + 1, y), (x0 + 1, y + h), (x0, y + h)]], 0.001, m)
        if t is None:
            eh.build_flame_mark("bm%d" % slot, (x0 + 0.5, 2.62), 0.16, 0.003, flame_mats(), outline=0.02,
                                outline2=0.014, seam_w=0.11)
            wordmark_flat("bw%d" % slot, "HEAT", None, (x0 + 0.5, 1.82), 0.02, white, width=0.80,
                          outlines=((0.025, dark),))
            wordmark_flat("bw2%d" % slot, "CHECK", None, (x0 + 0.5, 1.42), 0.02, white, width=0.80,
                          outlines=((0.025, dark),))
            wordmark_flat("bw3%d" % slot, "ARENA", None, (x0 + 0.5, 1.07), 0.02,
                          eh.flat_mat("F_Yel", eh.YELLOW), font=eh.FONT_DIN, shear=0.0, width=0.5)
        else:
            txt = eh.flat_mat("F_Txt%d" % slot, "#FFFFFF" if t["abbr"] not in ("NEO", "FRB") else "#111111")
            wordmark_flat("tn%d" % slot, t["name"], None, (x0 + 0.5, 1.70), 0.02, txt, width=0.84)
            wordmark_flat("tc%d" % slot, t["city"], None, (x0 + 0.5, 1.30), 0.02, txt, font=eh.FONT_DIN, shear=0.0,
                          width=0.70)
            wordmark_flat("ta%d" % slot, t["abbr"], None, (x0 + 0.5, 0.98), 0.02,
                          eh.flat_mat("F_Ab%d" % slot, t["secondary"]), font=eh.FONT_ARIAL_BLACK, shear=0.0,
                          width=0.42)
    eh.flat_scene(2048, 1024, samples=16, transparent=False)
    eh.ortho_camera(W_ / 2, H_ / 2, W_)
    img = eh.render_rgba("banners")
    img[..., 3] = 1.0
    # paste team badges
    for slot, ei in enumerate(order):
        t = entries[ei]
        if t is None:
            continue
        p = os.path.join(eh.UI_DIR, "UI_Team_%s.png" % t["abbr"])
        if not os.path.exists(p):
            continue
        b = eh.load_png(p)
        bs = 214
        pm = np.concatenate([b[..., :3] * b[..., 3:4], b[..., 3:4]], -1)
        r = resize_bilinear(pm, bs, bs)
        x0 = slot * 256 + (256 - bs) // 2
        y0 = int(2.62 / 4.0 * 1024) - bs // 2
        dst = img[y0:y0 + bs, x0:x0 + bs, :3]
        img[y0:y0 + bs, x0:x0 + bs, :3] = r[..., :3] + dst * (1 - r[..., 3:4])
    # V notch at the bottom of every banner (alpha)
    yy, xx = np.mgrid[0:1024, 0:2048].astype(np.float32)
    u = (xx % 256) / 256.0
    v = yy / 1024.0
    notch = 0.09 * (1.0 - np.abs(u - 0.5) * 2.0)
    img[..., 3] = np.clip((v - notch) * 1024 / 1.5, 0, 1)
    eh.save_png(img, os.path.join(eh.TEX_DIR, "T_Banners.png"))


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------
def make_materials():
    lib = eh.MatLib("arena", emission_scale=0.35)
    M = dict(
        concrete=lib.opaque("MI_BowlConcrete", eh.lin("#2B2C31"), roughness=0.85),
        wall=lib.opaque("MI_BowlWall", eh.lin("#17181C"), roughness=0.55),
        step=lib.opaque("MI_AisleStep", eh.lin("#45474D"), roughness=0.8),
        seat_lo=lib.opaque("MI_SeatRed", eh.lin("#B01C0E"), roughness=0.5),
        seat_up=lib.opaque("MI_SeatDark", eh.lin("#4A1510"), roughness=0.55),
        shell=lib.opaque("MI_ArenaShell", eh.lin("#0E0F12"), roughness=0.9),
        steel=lib.opaque("MI_RoofSteel", eh.lin("#2A2D33"), roughness=0.5, metallic=0.6),
        glowstrip=lib.emissive("MI_ConcourseGlow", (1.0, 0.72, 0.42), emissive_strength=3.0),
        crowd=lib.crowd("MI_Crowd"),
        led=lib.emissive("MI_LedRibbon", (1.0, 1.0, 1.0), emissive_strength=6.0, texture="T_LedScroll", pan_u=0.05),
        led_fac=lib.emissive("MI_LedFacade", (1.0, 1.0, 1.0), emissive_strength=5.0, texture="T_LedScroll",
                             pan_u=0.03),
        table=lib.opaque("MI_ScorerTable", eh.lin("#1A1B20"), roughness=0.4),
        tabletop=lib.opaque("MI_ScorerTop", eh.lin("#0A0A0C"), roughness=0.18, specular=0.7),
        scorer_led=lib.emissive("MI_ScorerLed", (1.0, 1.0, 1.0), emissive_strength=5.0, texture="T_LedScroll",
                                pan_u=0.06),
        monitor=lib.emissive("MI_Monitor", (0.35, 0.55, 1.0), emissive_strength=1.5),
        chair=lib.opaque("MI_BenchChair", eh.lin("#B81E10"), roughness=0.5),
        frame=lib.opaque("MI_BenchFrame", eh.lin("#9EA3AB"), roughness=0.3, metallic=0.9),
        cooler=lib.opaque("MI_Cooler", eh.lin("#FF7A00"), roughness=0.4),
        jbody=lib.opaque("MI_JumboBody", eh.lin("#1A1B20"), roughness=0.4, metallic=0.5),
        jscreen=lib.emissive("MI_JumboScreen", (1.0, 1.0, 1.0), emissive_strength=4.0, texture="T_JumboScreen"),
        jring=lib.emissive("MI_JumboRing", (1.0, 1.0, 1.0), emissive_strength=5.0, texture="T_LedScroll", pan_u=0.04),
        truss=lib.opaque("MI_Truss", eh.lin("#3A3D44"), roughness=0.4, metallic=0.8),
        panel=lib.emissive("MI_LightPanel", (1.0, 0.95, 0.86), emissive_strength=25.0),
        housing=lib.opaque("MI_LightHousing", eh.lin("#15161A"), roughness=0.5),
        banner=lib.masked("MI_Banner", "T_Banners", (1.0, 1.0, 1.0), roughness=0.85),
        cable=lib.opaque("MI_Cable", eh.lin("#111111"), roughness=0.6),
    )
    return lib, M


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def build_bowl(M, seats_lo, seats_up):
    mats = [M["concrete"], M["wall"], M["step"], M["shell"], M["steel"], M["glowstrip"]]
    CON, WAL, STP, SHL, STL, GLO = range(6)
    mb = eh.MeshBuilder()
    # lower bowl: front wall face, merged wall-top + first tread, risers + treads
    vband(mb, -WALL_T, 0.0, WALL_H, WAL, inward=True)
    hband(mb, -WALL_T, ROW_D, WALL_H, CON)
    for i in range(1, NL):
        z0 = WALL_H + ROW_RISE_L * (i - 1)
        z1 = WALL_H + ROW_RISE_L * i
        vband(mb, ROW_D * i, z0, z1, CON)
        hband(mb, ROW_D * i, ROW_D * (i + 1), z1, CON)
    # concourse step, walkway, back wall, soffit, facade, parapet
    zl = WALL_H + ROW_RISE_L * (NL - 1)
    vband(mb, CONC_D0, zl, CONC_Z, WAL)
    hband(mb, CONC_D0, CONC_D1, CONC_Z, CON)
    vband(mb, CONC_D1, CONC_Z, FAC_Z0, SHL)
    hband(mb, FAC_D, CONC_D1, FAC_Z0, WAL, up=False)
    vband(mb, FAC_D, FAC_Z0, FAC_Z1, WAL)
    hband(mb, FAC_D, UP_D0, FAC_Z1, WAL)
    vband(mb, UP_D0, UP_Z0, FAC_Z1, WAL, inward=False)
    vband(mb, FAC_D - 0.02, FAC_Z0 + 0.02, FAC_Z0 + 0.10, GLO)       # light strip under the facade
    vband(mb, CONC_D1 - 0.02, CONC_Z + 2.0, CONC_Z + 2.12, GLO)      # concourse wall wash
    # upper deck
    hband(mb, UP_D0, UP_D0 + ROW_D, UP_Z0, CON)
    for j in range(1, NU):
        z0 = UP_Z0 + ROW_RISE_U * (j - 1)
        z1 = UP_Z0 + ROW_RISE_U * j
        vband(mb, UP_D0 + ROW_D * j, z0, z1, CON)
        hband(mb, UP_D0 + ROW_D * j, UP_D0 + ROW_D * (j + 1), z1, CON)
    # shell: back wall + roof (ceiling faces down) + roof trusses
    vband(mb, UP_D1, UP_Z0 + ROW_RISE_U * (NU - 1), ROOF_Z, SHL)
    ring_pts, _ = ring(UP_D1, 24)
    from mathutils import geometry
    tris = geometry.tessellate_polygon([[Vector((p[0], p[1], 0.0)) for p in ring_pts]])
    for (a, b, c) in tris:
        pa, pb, pc = ring_pts[a], ring_pts[b], ring_pts[c]
        cross = (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pc[0] - pa[0]) * (pb[1] - pa[1])
        if cross > 0:
            pb, pc = pc, pb
        mb.face((mb.v((pa[0], pa[1], ROOF_Z)), mb.v((pb[0], pb[1], ROOF_Z)), mb.v((pc[0], pc[1], ROOF_Z))), SHL)
    for x in (-30.0, -18.0, -6.0, 6.0, 18.0, 30.0):
        y0 = CY - HY - UP_D1 + 4.0
        y1 = CY + HY + UP_D1 - 4.0
        mb.box((x - 0.45, y0, ROOF_Z - 1.6), (x + 0.45, y1, ROOF_Z - 0.05), mat=STL, skip=("+z",))
    for y in (-18.0, -6.0, 6.0, 18.0):
        mb.box((-34.0, y - 0.3, ROOF_Z - 1.0), (34.0, y + 0.3, ROOF_Z - 0.05), mat=STL, skip=("+z",))
    # aisle steps (half-depth boxes on each tread, oriented along the path)
    for row in range(NL + NU):
        z, d0 = tread_z(row)
        rise = ROW_RISE_L if row < NL else ROW_RISE_U
        if row in (0, NL):
            continue
        dmid = d0 + 0.21
        for sa in aisle_s(dmid):
            (x, y), (nx, ny) = path_eval(dmid, sa)
            t = Vector((-ny, nx, 0))
            n = Vector((nx, ny, 0))
            c = Vector((x, y, z + rise * 0.25))
            mb.oriented_box(tuple(c), n, t, Vector((0, 0, 1)), 0.21, 0.5, rise * 0.25, mat=STP, skip=("-z",))
    o = mb.build("SM_ArenaBowl_shell", mats)
    parts = [o]
    if seats_lo is not None:
        v, f, _, _ = seats_lo
        parts.append(eh.mesh_from_arrays("bowl_seats_lo", v, f, materials=[M["seat_lo"]]))
    if seats_up is not None:
        v, f, _, _ = seats_up
        parts.append(eh.mesh_from_arrays("bowl_seats_up", v, f, materials=[M["seat_up"]]))
    return eh.join_objs(parts, "SM_ArenaBowl", uv_scale=0.5)


def ribbon_mesh(name, d, z0, z1, pieces, mat, repeat_len, closed=False, arc_seg=24):
    """Inward-facing LED strip on the ring at offset d. U increases clockwise (= left->right seen from inside)."""
    pts, _ = ring(d, arc_seg, pieces=list(pieces))
    if closed:
        pts = pts + [pts[0]]
    s = [0.0]
    for i in range(1, len(pts)):
        s.append(s[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    total = s[-1]
    if closed:
        reps = max(1, round(total / repeat_len))
        repeat_len = total / reps
    mb = eh.MeshBuilder()
    for i in range(len(pts) - 1):
        p0, p1 = pts[i], pts[i + 1]
        u0 = (total - s[i]) / repeat_len
        u1 = (total - s[i + 1]) / repeat_len
        mb.quad((p0[0], p0[1], z0), (p0[0], p0[1], z1), (p1[0], p1[1], z1), (p1[0], p1[1], z0), mat=0,
                uv=[(u0, 0.0), (u0, 1.0), (u1, 1.0), (u1, 0.0)])
    o = mb.build(name, [mat])
    return o, total, repeat_len


def build_led(M):
    out = {}
    o, L, rep = ribbon_mesh("SM_LedRibbon_Courtside", -WALL_T - 0.012, 0.12, 1.02, (0, 1, 2, 3, 4), M["led"], 7.2)
    out["SM_LedRibbon_Courtside"] = (o, dict(length_m=round(L, 3), repeat_m=round(rep, 3), z=[0.12, 1.02],
                                             offset_from_front_wall_m=-WALL_T - 0.012))
    o, L, rep = ribbon_mesh("SM_LedRibbon_Facade", FAC_D - 0.012, FAC_Z0 + 0.45, FAC_Z0 + 1.65, range(8),
                            M["led_fac"], 9.6, closed=True)
    out["SM_LedRibbon_Facade"] = (o, dict(length_m=round(L, 3), repeat_m=round(rep, 3),
                                          z=[round(FAC_Z0 + 0.45, 3), round(FAC_Z0 + 1.65, 3)], closed_loop=True))
    return out


def chair_parts(mb, x, y, yaw_face, seat_mat, frame_mat, z_seat=0.46):
    """Simple padded chair facing direction yaw_face (radians, 0 = -Y)."""
    c, s = math.cos(yaw_face), math.sin(yaw_face)
    fwd = Vector((s, -c, 0))
    side = Vector((c, s, 0))
    up = Vector((0, 0, 1))
    base = Vector((x, y, 0))
    mb.oriented_box(tuple(base + up * (z_seat - 0.04)), fwd, side, up, 0.23, 0.23, 0.04, mat=seat_mat)
    mb.oriented_box(tuple(base - fwd * 0.22 + up * (z_seat + 0.27)), fwd, side, up, 0.03, 0.23, 0.25, mat=seat_mat)
    for sx in (-1, 1):
        for sy in (-1, 1):
            mb.oriented_box(tuple(base + side * (sx * 0.19) + fwd * (sy * 0.19) + up * ((z_seat - 0.08) / 2)),
                            fwd, side, up, 0.015, 0.015, (z_seat - 0.08) / 2, mat=frame_mat, skip=("-z",))


def build_scorer_table(M):
    mb = eh.MeshBuilder()
    TAB, TOP, LED, MON, CHR, FRM = range(6)
    mb.box((-3.6, 9.05, 0.0), (3.6, 9.65, 0.74), mat=TAB, skip=("-z",))
    mb.box((-3.7, 8.98, 0.74), (3.7, 9.72, 0.79), mat=TOP, skip=())
    x0, x1, z0, z1 = -3.5, 3.5, 0.07, 0.70
    rep = (z1 - z0) * 8.0
    mb.quad((x0, 9.044, z0), (x1, 9.044, z0), (x1, 9.044, z1), (x0, 9.044, z1), mat=LED,
            uv=[(0.0, 0.0), ((x1 - x0) / rep, 0.0), ((x1 - x0) / rep, 1.0), (0.0, 1.0)])
    for k in range(6):
        x = -3.0 + 1.2 * k
        mb.box((x - 0.24, 9.42, 0.79), (x + 0.24, 9.46, 1.10), mat=TAB)
        mb.quad((x + 0.22, 9.461, 0.81), (x - 0.22, 9.461, 0.81), (x - 0.22, 9.461, 1.08), (x + 0.22, 9.461, 1.08),
                mat=MON)
    for k in range(8):
        chair_parts(mb, -3.15 + 0.9 * k, 10.15, 0.0, CHR, FRM)
    mats = [M["table"], M["tabletop"], M["scorer_led"], M["monitor"], M["chair"], M["frame"]]
    return mb.build("SM_ScorerTable", mats)


def build_benches(M):
    mb = eh.MeshBuilder()
    CHR, FRM, COOL = range(3)
    for sx in (-1, 1):
        for rowy in (9.95, 10.85):
            for k in range(13):
                x = sx * (5.2 + 0.6 * k)
                chair_parts(mb, x, rowy, 0.0, CHR, FRM)
        # water coolers on a small table at the far end of each bench
        xc = sx * 13.6
        mb.box((xc - 0.45, 9.85, 0.0), (xc + 0.45, 10.45, 0.72), mat=FRM, skip=("-z",))
        for k in range(2):
            cx = xc + (k - 0.5) * 0.42
            n = 14
            pts = [(cx + 0.17 * math.cos(2 * math.pi * i / n), 10.15 + 0.17 * math.sin(2 * math.pi * i / n))
                   for i in range(n)]
            for i in range(n):
                a, b = pts[i], pts[(i + 1) % n]
                mb.quad((a[0], a[1], 0.72), (b[0], b[1], 0.72), (b[0], b[1], 1.22), (a[0], a[1], 1.22), mat=COOL)
            ctr = mb.v((cx, 10.15, 1.22))
            for i in range(n):
                a, b = pts[i], pts[(i + 1) % n]
                mb.face((mb.v((a[0], a[1], 1.22)), mb.v((b[0], b[1], 1.22)), ctr), mat=COOL)
    return mb.build("SM_TeamBenches", [M["chair"], M["frame"], M["cooler"]])


def build_jumbotron(M):
    mb = eh.MeshBuilder()
    BODY, SCR, RING, CAB = range(4)
    bx, by, z0, z1 = 3.2, 2.2, 13.8, 17.2
    mb.box((-bx, -by, z0), (bx, by, z1), mat=BODY)
    screens = []
    sz0, sz1 = 14.0, 17.0

    def screen(name, corners, uvx0, uvx1, normal, right, size):
        mb.quad(*corners, mat=SCR, uv=[(uvx0, 0.0), (uvx1, 0.0), (uvx1, 1.0), (uvx0, 1.0)])
        cx = sum(c[0] for c in corners) / 4
        cy = sum(c[1] for c in corners) / 4
        cz = sum(c[2] for c in corners) / 4
        screens.append(dict(name=name, center=[round(cx, 4), round(cy, 4), round(cz, 4)], normal=list(normal),
                            right=list(right), up=[0, 0, 1], size_m=list(size), uv_rect=[uvx0, 0.0, uvx1, 1.0],
                            ue_center_cm=[round(cx * 100, 1), round(-cy * 100, 1), round(cz * 100, 1)]))
    e = 0.012
    sw, sd = 3.0, 2.0
    # -Y (faces the game camera): U increases toward +X
    screen("south_minusY", [(-sw, -by - e, sz0), (sw, -by - e, sz0), (sw, -by - e, sz1), (-sw, -by - e, sz1)],
           0.0, 1.0, (0, -1, 0), (1, 0, 0), (2 * sw, sz1 - sz0))
    screen("north_plusY", [(sw, by + e, sz0), (-sw, by + e, sz0), (-sw, by + e, sz1), (sw, by + e, sz1)],
           0.0, 1.0, (0, 1, 0), (-1, 0, 0), (2 * sw, sz1 - sz0))
    crop = (1.0 - (2 * sd / (sz1 - sz0)) / 2.0) / 2.0
    screen("east_plusX", [(bx + e, -sd, sz0), (bx + e, sd, sz0), (bx + e, sd, sz1), (bx + e, -sd, sz1)],
           crop, 1.0 - crop, (1, 0, 0), (0, 1, 0), (2 * sd, sz1 - sz0))
    screen("west_minusX", [(-bx - e, sd, sz0), (-bx - e, -sd, sz0), (-bx - e, -sd, sz1), (-bx - e, sd, sz1)],
           crop, 1.0 - crop, (-1, 0, 0), (0, -1, 0), (2 * sd, sz1 - sz0))
    # LED rings (bottom + top), U clockwise seen from outside
    for (rz0, rz1, inset) in ((13.30, 13.72, 0.25), (17.28, 17.70, 0.25)):
        mb.box((-bx + inset, -by + inset, rz0 - 0.02), (bx - inset, by - inset, rz1 + 0.02), mat=BODY)
        rx, ry = bx - inset + 0.01, by - inset + 0.01
        corners = [(rx, -ry), (rx, ry), (-rx, ry), (-rx, -ry)]  # CCW
        per = 0.42 * 8.0
        u = 0.0
        for i in range(4):
            a, b = corners[i], corners[(i + 1) % 4]
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            # outward-facing quad: text reads left->right from outside when U increases CCW
            mb.quad((b[0], b[1], rz0), (b[0], b[1], rz1), (a[0], a[1], rz1), (a[0], a[1], rz0), mat=RING,
                    uv=[(u + L / per, 0.0), (u + L / per, 1.0), (u, 1.0), (u, 0.0)])
            u += L / per
    # rigging cables to the light-rig truss
    for sx in (-1, 1):
        for sy in (-1, 1):
            mb.box((sx * 2.8 - 0.02, sy * 1.8 - 0.02, 17.7), (sx * 2.8 + 0.02, sy * 1.8 + 0.02, 21.0), mat=CAB)
    o = mb.build("SM_Jumbotron", [M["jbody"], M["jscreen"], M["jring"], M["cable"]])
    return o, screens


def build_light_rig(M):
    mb = eh.MeshBuilder()
    TR, HOUS, PAN, CAB = range(4)
    zb, zt = 21.0, 21.6
    hw = 0.3
    long_y = (-9.0, -3.0, 3.0, 9.0)
    cross_x = (-18.0, -9.0, 0.0, 9.0, 18.0)

    def truss(p0, p1):
        p0, p1 = Vector(p0), Vector(p1)
        a = (p1 - p0)
        L = a.length
        a.normalize()
        side = Vector((-a.y, a.x, 0))
        up = Vector((0, 0, 1))
        for sx in (-1, 1):
            for zz in (zb, zt):
                c = (p0 + p1) / 2 + side * (sx * hw)
                c.z = zz
                mb.oriented_box(tuple(c), a, side, up, L / 2, 0.03, 0.03, mat=TR)
        n = int(L / 0.9)
        for k in range(n):
            q0 = p0 + a * (k * L / n)
            q1 = p0 + a * ((k + 1) * L / n)
            for sx in (-1, 1):
                A = q0 + side * (sx * hw)
                B = q1 + side * (sx * hw)
                A.z, B.z = (zb, zt) if k % 2 == 0 else (zt, zb)
                d = (B - A)
                Ld = d.length
                d.normalize()
                s2 = side
                u2 = d.cross(s2).normalized()
                mb.oriented_box(tuple((A + B) / 2), d, s2, u2, Ld / 2, 0.018, 0.018, mat=TR)
    for y in long_y:
        truss((-18.0, y, 0), (18.0, y, 0))
    for x in cross_x:
        truss((x, -9.0, 0), (x, 9.0, 0))
    panels = []
    for y in long_y:
        tilt = math.radians(25.0) * (-1 if y > 5 else (1 if y < -5 else 0))
        for x in (-15.75, -11.25, -6.75, -2.25, 2.25, 6.75, 11.25, 15.75):
            c = Vector((x, y, zb - 0.45))
            # panel faces down, tilted toward the court centre line for the outer trusses
            nrm = Vector((0, math.sin(tilt), -math.cos(tilt)))
            ex = Vector((1, 0, 0))
            ey = nrm.cross(ex).normalized()  # along y in the panel plane
            hx_, hy_ = 0.6, 0.35
            mb.oriented_box(tuple(c - nrm * 0.12), ex, ey, nrm, hx_ + 0.05, hy_ + 0.05, 0.12, mat=HOUS)
            q = [c + nrm * 0.005 + ex * sx_ * hx_ + ey * sy_ * hy_ for sx_, sy_ in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            # winding so the emissive face points along nrm
            f = [tuple(p) for p in q]
            if (Vector(f[1]) - Vector(f[0])).cross(Vector(f[2]) - Vector(f[1])).dot(nrm) < 0:
                f = f[::-1]
            mb.quad(*f, mat=PAN)
            mb.box((x - 0.02, y - 0.02, zb - 0.32), (x + 0.02, y + 0.02, zb), mat=CAB)
            panels.append(dict(center=[round(c.x, 3), round(c.y, 3), round(c.z, 3)],
                               normal=[round(nrm.x, 4), round(nrm.y, 4), round(nrm.z, 4)], size_m=[1.2, 0.7],
                               ue_center_cm=[round(c.x * 100, 1), round(-c.y * 100, 1), round(c.z * 100, 1)]))
    # hang the rig from the roof
    for x in cross_x:
        for y in (-9.0, 9.0):
            mb.box((x - 0.025, y - 0.025, zt), (x + 0.025, y + 0.025, ROOF_Z - 1.6), mat=CAB)
    o = mb.build("SM_LightRig", [M["truss"], M["housing"], M["panel"], M["cable"]])
    spots = []
    for (x, y) in ((-18, -9), (18, -9), (-18, 9), (18, 9), (0, -9), (0, 9)):
        tgt = (x * 0.45, y * 0.2, 0.0)
        spots.append(dict(position=[x, y, zb - 0.2], target=[round(tgt[0], 2), round(tgt[1], 2), 0.0]))
    return o, panels, spots


def build_banners(M):
    mb = eh.MeshBuilder()
    BAN, CAB = range(2)
    y = 31.0
    zt = 25.4
    w, h = 2.2, 8.8
    info = []
    for i in range(8):
        x = -11.55 + 3.3 * i
        u0, u1 = i / 8.0, (i + 1) / 8.0
        mb.quad((x - w / 2, y, zt - h), (x + w / 2, y, zt - h), (x + w / 2, y, zt), (x - w / 2, y, zt), mat=BAN,
                uv=[(u0, 0.0), (u1, 0.0), (u1, 1.0), (u0, 1.0)])
        # back side (so it is not invisible from behind), mirrored U
        mb.quad((x + w / 2, y + 0.01, zt - h), (x - w / 2, y + 0.01, zt - h), (x - w / 2, y + 0.01, zt),
                (x + w / 2, y + 0.01, zt), mat=BAN, uv=[(u0, 0.0), (u1, 0.0), (u1, 1.0), (u0, 1.0)])
        mb.box((x - w / 2 - 0.08, y - 0.04, zt), (x + w / 2 + 0.08, y + 0.05, zt + 0.08), mat=CAB)
        mb.box((x - 0.02, y - 0.01, zt + 0.08), (x + 0.02, y + 0.03, ROOF_Z), mat=CAB)
        info.append(dict(center=[round(x, 3), y, round(zt - h / 2, 3)], size_m=[w, h], normal=[0, -1, 0]))
    return mb.build("SM_Banners", [M["banner"], M["cable"]]), info


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------
def preview(objs, panels):
    eh.preview_scene((1600, 900), samples=32, view="AgX", exposure=0.6, world=(0.01, 0.01, 0.012))
    lib = eh.MatLib("arena_preview")
    floor = eh.box_obj("floor", (-46, -42, -0.03), (46, 42, -0.01), lib.opaque("MI_PFloor", eh.lin("#1A1B20"), 0.45))
    court = eh.box_obj("court", (-17, -8.5, -0.01), (17, 8.5, 0.0), lib.opaque("MI_PCourt", eh.lin("#C9965E"), 0.3))
    for p in panels[::2]:
        eh.area_light("L", tuple(p["center"]), (p["center"][0], p["center"][1] * 0.3, 0), 2500, size=1.4)
    for (x, y) in ((-25, 0), (25, 0), (0, 25), (0, -25)):
        eh.area_light("B", (x * 0.8, y * 0.8, 20), (x, y, 4), 9000, size=10)
    eh.look_cam("CamGame", (0.0, -16.0, 9.0), (0.0, 2.0, 1.0), lens=22)
    eh.render_preview(os.path.join(eh.PREVIEW_DIR, "arena_gamecam.png"))
    eh.look_cam("CamCrowd", (-4.0, 4.0, 3.0), (2.0, 16.0, 3.0), lens=30)
    eh.render_preview(os.path.join(eh.PREVIEW_DIR, "arena_crowd_close.png"))
    eh.look_cam("CamWide", (-21.0, -19.0, 17.0), (3.0, 4.0, 5.0), lens=16)
    eh.render_preview(os.path.join(eh.PREVIEW_DIR, "arena_wide.png"))


def main():
    rng = np.random.default_rng(20261117)
    render_led_texture()
    render_jumbo_texture()
    render_banner_texture()
    log("textures done")
    eh.clear_scene()
    lib, M = make_materials()
    T = make_templates()
    for k, (V, F, R) in T.items():
        log("template %-14s tris=%d" % (k, len(F) * 2))
    crowd, seats_lo, seats_up, stats = build_crowd_and_seats(T, rng)
    log("crowd built", stats)
    objs = {}
    objs["SM_ArenaBowl"] = build_bowl(M, seats_lo, seats_up)
    for sec, data in crowd.items():
        if data is None:
            continue
        v, f, c, u = data
        o = eh.mesh_from_arrays("SM_Crowd_" + sec, v, f, uvs=u, colors=c, materials=[M["crowd"]])
        objs[o.name] = o
    led = build_led(M)
    for k, (o, _) in led.items():
        objs[k] = o
    objs["SM_ScorerTable"] = build_scorer_table(M)
    objs["SM_TeamBenches"] = build_benches(M)
    jumbo, screens = build_jumbotron(M)
    objs["SM_Jumbotron"] = jumbo
    rig, panels, spots = build_light_rig(M)
    objs["SM_LightRig"] = rig
    ban, banners = build_banners(M)
    objs["SM_Banners"] = ban
    log("geometry built")
    # make sure every mesh has UV0 (box projection where no explicit UVs were authored)
    for name, o in objs.items():
        if not o.data.uv_layers:
            eh.box_uv(o, 0.5)
    # camera clear-zone check (near side, in front of the court)
    viol = 0
    for name, o in objs.items():
        co = np.empty(len(o.data.vertices) * 3, np.float32)
        o.data.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        m = (co[:, 1] > -14.0) & (co[:, 1] < -7.62) & (np.abs(co[:, 0]) < 17.0) & (co[:, 2] > 1.2) & \
            (co[:, 2] < 12.0)
        viol += int(m.sum())
    log("clear-zone violations (|x|<17, -14<y<-7.62, 1.2<z<12):", viol)
    total = 0
    mesh_info = {}
    for name in sorted(objs):
        o = objs[name]
        hc.export_static_fbx([o], name + ".fbx")
        n = eh.report_mesh(o)
        total += n
        mesh_info[name] = dict(tris=n, materials=[m.name for m in o.data.materials])
    log("TOTAL arena tris", total)
    lib.write()
    eh.write_manifest("arena", dict(
        note="Blender meters (x right, y away from the game camera, z up). Unreal cm = (100x, -100y, 100z). "
             "All arena meshes use the world origin as pivot: place every mesh listed in static_meshes_at_origin "
             "at (0,0,0) with no rotation.",
        static_meshes_at_origin=sorted(objs.keys()),
        meshes=mesh_info,
        total_tris=total,
        bowl=dict(front_wall=dict(x=[-HX, HX], y_far=Y_FAR, y_near=Y_NEAR, corner_radius=RC, height=WALL_H),
                  lower_rows=NL, upper_rows=NU, row_depth=ROW_D, lower_rise=ROW_RISE_L, upper_rise=ROW_RISE_U,
                  facade=dict(offset=FAC_D, z=[FAC_Z0, FAC_Z1]), outer_wall_offset=UP_D1, roof_z=ROOF_Z),
        crowd=dict(stats, material="MI_Crowd",
                   uv0="x = per-fan phase 0..1, y = per-fan bounce amplitude 0..1 (Blender UV convention; Unreal's "
                       "FBX import flips V, so in UE amplitude = 1 - TexCoord0.y)",
                   vertex_colors="linear RGB per face corner (shirt/skin/hair/pants/props)"),
        led_ribbons={k: v for k, (o, v) in led.items()},
        scorer_table=dict(front_panel=dict(center=[0.0, 9.044, 0.385], normal=[0, -1, 0], size_m=[7.0, 0.63])),
        jumbotron=dict(center=[0.0, 0.0, 15.5], body_size_m=[6.4, 4.4, 3.4], screens=screens),
        light_rig=dict(truss_z=[21.0, 21.6], panels=panels, suggested_spotlights=spots),
        banners=banners,
        camera_clear_zone=dict(y=[-14.0, -7.62], max_height_m=1.2, violations=viol),
        environment_placement=dict(
            at_origin=["SM_CourtFloor", "SM_ArenaFloor"] + sorted(objs.keys()),
            hoops=dict(note="hoop-local meshes; see Manifests/hoop.json for part offsets",
                       instances=[dict(location_cm=[-1272.5, 0.0, 0.0], yaw_deg=0.0),
                                  dict(location_cm=[1272.5, 0.0, 0.0], yaw_deg=180.0)]),
            ball=dict(mesh="SM_Ball", pivot="ball centre", radius_m=0.12)),
    ))
    preview(objs, panels)
    eh.cleanup_tmp()
    log("done")


if __name__ == "__main__":
    main()
