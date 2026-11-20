"""HEAT CHECK - court generator.

Outputs
  Art/Export/Textures/T_Court.png      8192x4096, covers x in [-17,17], y in [-8.5,8.5] m (image top = +Y)
  Art/Export/Meshes/SM_CourtFloor.fbx  34x17 m plane at z=0, UV u=(x+17)/34, v=(y+8.5)/17   (MI_Court)
  Art/Export/Meshes/SM_ArenaFloor.fbx  dark floor at z=-0.01 under/around everything        (MI_ArenaFloor)
  Art/Export/Materials/court.json
  Art/Previews/court_top.png, court_detail_*.png, court_gamecam.png

Run:  blender -b --factory-startup -P Blender/gen_court.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import math  # noqa: E402
import time  # noqa: E402

import bpy  # noqa: E402
import numpy as np  # noqa: E402

import env_helpers as eh  # noqa: E402
import hc_common as hc  # noqa: E402

T0 = time.time()

# ---------------------------------------------------------------------------
# Texture frame + court dimensions (meters)
# ---------------------------------------------------------------------------
W, H = 8192, 4096
X0, X1, Y0, Y1 = -17.0, 17.0, -8.5, 8.5
PX = (X1 - X0) / W  # 4.15 mm per texel (square)

BX, BY = 14.325, 7.62        # boundary outer edges
HW = 0.025                   # half line width (lines are 5 cm)
RIM_X = 12.725               # floor point under rim
BB_X = 13.105                # backboard face
R3, Y3 = 7.24, 6.70          # three point radius / corner line (outer edges)
KEY_Y, FT_X = 2.44, 8.535    # key half-width, free throw line (court-side edge)
R_FT, R_RA, R_CC, R_CI = 1.83, 1.22, 1.83, 0.61

XS = (X0 + (np.arange(W, dtype=np.float32) + 0.5) * PX).astype(np.float32)
YS = (Y0 + (np.arange(H, dtype=np.float32) + 0.5) * PX).astype(np.float32)


def log(*a):
    print("[court %6.1fs]" % (time.time() - T0), *a, flush=True)


# ---------------------------------------------------------------------------
# Distance helpers (evaluated on bounding-box sub-grids)
# ---------------------------------------------------------------------------
def grid(x0, x1, y0, y1, pad=0.05):
    i0 = max(0, int(math.floor((x0 - pad - X0) / PX)))
    i1 = min(W, int(math.ceil((x1 + pad - X0) / PX)))
    j0 = max(0, int(math.floor((y0 - pad - Y0) / PX)))
    j1 = min(H, int(math.ceil((y1 + pad - Y0) / PX)))
    return (slice(j0, j1), slice(i0, i1)), XS[i0:i1][None, :], YS[j0:j1][:, None]


def d_seg(X, Y, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = np.clip(((X - ax) * dx + (Y - ay) * dy) / L2, 0.0, 1.0)
    return np.hypot(X - (ax + t * dx), Y - (ay + t * dy))


def sd_box(X, Y, cx, cy, hx, hy):
    qx = np.abs(X - cx) - hx
    qy = np.abs(Y - cy) - hy
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0)


def arc_rel(X, Y, cx, cy, a0):
    th = np.arctan2(Y - cy, X - cx)
    return np.mod(th - a0, 2 * math.pi)


def d_arc(X, Y, cx, cy, r, a0, a1):
    """Distance to an arc (CCW from a0 to a1)."""
    rel = arc_rel(X, Y, cx, cy, a0)
    span = a1 - a0
    rp = np.hypot(X - cx, Y - cy)
    e0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
    e1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
    dend = np.minimum(np.hypot(X - e0[0], Y - e0[1]), np.hypot(X - e1[0], Y - e1[1]))
    return np.where(rel <= span, np.abs(rp - r), dend)


def cov_band(d, hw=HW):
    return np.clip(0.5 - (d - hw) / PX, 0.0, 1.0).astype(np.float32)


def cov_fill(sd):
    return np.clip(0.5 - sd / PX, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# 1. Hardwood
# ---------------------------------------------------------------------------
def make_wood(seed=20261117):
    rng = np.random.default_rng(seed)
    BW = 0.0572
    rowf = (YS - Y0 + 0.021) / BW
    row = np.floor(rowf).astype(np.int32)
    vb = (rowf - row).astype(np.float32)
    nrows = int(row.max()) + 1
    seg = np.zeros((nrows, W), np.int32)
    jdist = np.zeros((nrows, W), np.float32)
    maxseg = 0
    for r in range(nrows):
        x = X0 - rng.uniform(0.0, 2.3)
        js = [x]
        while x < X1 + 0.05:
            x += rng.choice([rng.uniform(0.55, 1.2), rng.uniform(1.2, 2.45)], p=[0.35, 0.65])
            js.append(x)
        js = np.array(js, np.float32)
        idx = np.searchsorted(js, XS, side="right") - 1
        seg[r] = idx
        jdist[r] = np.minimum(XS - js[idx], js[idx + 1] - XS)
        maxseg = max(maxseg, len(js))
    tone = rng.normal(0.0, 1.0, (nrows, maxseg)).astype(np.float32)
    warm = rng.normal(0.0, 1.0, (nrows, maxseg)).astype(np.float32)
    kind = rng.random((nrows, maxseg)).astype(np.float32)
    offx = rng.uniform(0, 300, (nrows, maxseg)).astype(np.float32)
    offy = rng.uniform(0, 300, (nrows, maxseg)).astype(np.float32)
    log("planks laid out", nrows, "rows")

    R = row[:, None]
    S = seg[row]                                    # (H, W) segment index per texel
    T = tone[R, S]
    WM = warm[R, S]
    K = kind[R, S]
    OX = offx[R, S]
    OY = offy[R, S]
    JD = jdist[row]                                 # (H, W)
    del S
    X = XS[None, :]
    Y = YS[:, None]
    n1 = eh.LatticeNoise(101, (512, 1024))
    n2 = eh.LatticeNoise(202, (512, 512))
    n3 = eh.LatticeNoise(303, (64, 64))
    n4 = eh.LatticeNoise(404, (512, 1024))
    g1 = n1((X + OX) / 0.38, (Y + OY) / 0.0046)     # fine streaks (~1 texel across)
    g2 = n2((X + OX) / 1.10, (Y + OY) / 0.017)      # broader figure
    g4 = n4((X + OX) / 0.16, (Y + OY) / 0.0105)     # short darker flecks
    g3 = n3(X / 3.6, Y / 2.2)                       # large-scale mottling (continuous)
    log("grain noise")
    f = 1.0 + 0.028 * T + 0.040 * g1 + 0.034 * g2 + 0.020 * g3
    f -= 0.050 * eh.smoothstep(0.45, 0.95, g4)
    f -= 0.030 * eh.smoothstep(0.55, 0.95, g2)
    del g1, g2, g3, g4, OX, OY
    # board edges and butt joints (thin darker seams)
    de = (np.minimum(vb, 1.0 - vb) * BW)[:, None]
    f *= 1.0 - 0.20 * np.clip(1.0 - de / (0.9 * PX), 0.0, 1.0)
    f *= 1.0 - 0.17 * np.clip(1.0 - JD / (0.9 * PX), 0.0, 1.0)
    f = f.astype(np.float32)
    del JD
    base = np.array(eh.srgb("#D9A56C"), np.float32)  # warm honey maple
    rgb = np.empty((H, W, 3), np.float32)
    rgb[..., 0] = base[0] * (1.0 + 0.020 * WM)
    rgb[..., 1] = base[1] * (1.0 + 0.004 * WM)
    rgb[..., 2] = base[2] * (1.0 - 0.050 * WM)
    amber = K < 0.05
    light = K > 0.96
    rgb[amber] *= np.array([0.965, 0.905, 0.835], np.float32)
    rgb[light] *= np.array([1.03, 1.035, 1.05], np.float32)
    rgb *= f[..., None]
    log("wood done")
    return rgb, f


# ---------------------------------------------------------------------------
# 2. Paint, stain and lines
# ---------------------------------------------------------------------------
def paint_regions(rgb, f):
    mod = lambda k: (1.0 + k * (f - 1.0))[..., None]  # noqa: E731  grain modulation

    # two-tone: slightly deeper amber stain inside the three-point lines
    for s in (-1, 1):
        sl, X, Y = grid(min(s * BX, s * (RIM_X - R3)), max(s * BX, s * (RIM_X - R3)), -BY, BY)
        inside_arc = (np.hypot(X - s * RIM_X, Y) < (R3 - HW)) & (np.abs(Y) < (Y3 - HW))
        inside_corner = (np.abs(Y) < (Y3 - HW)) & ((X * s) > (RIM_X - 2.74))
        inside = (inside_arc | inside_corner) & (np.abs(X) < BX)
        tint = np.array([0.955, 0.915, 0.86], np.float32)
        sub = rgb[sl]
        sub[inside] *= tint
        rgb[sl] = sub

    # dark stained apron outside the boundary
    X = XS[None, :]
    Y = YS[:, None]
    sdb = sd_box(X, Y, 0.0, 0.0, BX - 0.01, BY - 0.01)
    ap = np.clip(0.5 + sdb / PX, 0.0, 1.0).astype(np.float32)
    apron = np.array(eh.srgb("#2A211C"), np.float32)[None, None, :] * mod(0.9)
    rgb[:] = eh.over(rgb, apron, ap)
    del sdb, ap, apron

    # keys painted flame red, gradient a touch brighter toward the free-throw line
    for s in (-1, 1):
        x_lo, x_hi = (FT_X, BX) if s > 0 else (-BX, -FT_X)
        sl, X, Y = grid(x_lo, x_hi, -KEY_Y, KEY_Y)
        sd = sd_box(X, Y, (x_lo + x_hi) / 2, 0.0, (x_hi - x_lo) / 2 - 0.01, KEY_Y - 0.01)
        cov = cov_fill(sd)
        t = np.clip((np.abs(X) - FT_X) / (BX - FT_X), 0, 1)  # 0 at FT line, 1 at baseline
        c0 = np.array(eh.srgb("#D42A10"), np.float32)
        c1 = np.array(eh.srgb("#B51A0A"), np.float32)
        col = c0[None, None, :] + (c1 - c0)[None, None, :] * t[..., None]
        col = np.broadcast_to(col, cov.shape + (3,)) * (1.0 + 0.55 * (f[sl] - 1.0))[..., None]
        rgb[sl] = eh.over(rgb[sl], col, cov)
    log("paint done")


def line_mask():
    L = np.zeros((H, W), np.float32)

    def add(cov, sl):
        L[sl] = np.maximum(L[sl], cov)

    # boundary (outer edge at BX/BY, drawn inside)
    for (x0, x1, y0, y1) in ((-BX, BX, BY - 0.1, BY), (-BX, BX, -BY, -BY + 0.1),
                             (-BX, -BX + 0.1, -BY, BY), (BX - 0.1, BX, -BY, BY)):
        sl, X, Y = grid(x0, x1, y0, y1)
        add(cov_band(np.abs(sd_box(X, Y, 0, 0, BX - HW, BY - HW))), sl)
    # midcourt line
    sl, X, Y = grid(-0.1, 0.1, -BY, BY)
    add(cov_band(d_seg(X, Y, 0, -BY + HW, 0, BY - HW)), sl)
    # center circle + inner circle
    for r in (R_CC, R_CI):
        sl, X, Y = grid(-r, r, -r, r)
        add(cov_band(np.abs(np.hypot(X, Y) - (r - HW))), sl)

    for s in (-1, 1):
        def mx(x):
            return s * x
        # key outline (free throw line + lane lines; baseline side merges with boundary)
        xa, xb = FT_X + HW, BX - HW
        sl, X, Y = grid(min(mx(FT_X), mx(BX)), max(mx(FT_X), mx(BX)), -KEY_Y, KEY_Y)
        add(cov_band(np.abs(sd_box(X, Y, s * (xa + xb) / 2, 0, (xb - xa) / 2, KEY_Y - HW))), sl)
        # free throw circle: outer half (toward center court) solid, inner half dashed
        cx = s * FT_X
        r = R_FT - HW
        sl, X, Y = grid(cx - R_FT, cx + R_FT, -R_FT, R_FT)
        a_out0 = math.pi / 2 if s > 0 else -math.pi / 2
        add(cov_band(d_arc(X, Y, cx, 0.0, r, a_out0, a_out0 + math.pi)), sl)
        a_in0 = -math.pi / 2 if s > 0 else math.pi / 2
        rel = arc_rel(X, Y, cx, 0.0, a_in0)
        S_len = r * math.pi
        n_d = 8
        Ld = S_len / (2 * n_d - 1)
        P = 2 * Ld
        s_arc = rel * r
        local = np.mod(s_arc + Ld / 2, P) - Ld / 2
        sd_cap = np.maximum(-local, local - Ld)
        in_rng = rel <= math.pi
        rp = np.hypot(X - cx, Y)
        cov = np.minimum(cov_band(np.abs(rp - r)), np.clip(0.5 - sd_cap / PX, 0, 1))
        cov = np.where(in_rng, cov, 0.0).astype(np.float32)
        add(cov, sl)
        # restricted area arc + short straights to the backboard plane
        cx = s * RIM_X
        r = R_RA - HW
        sl, X, Y = grid(cx - R_RA, cx + R_RA, -R_RA, R_RA)
        a0 = math.pi / 2 if s > 0 else -math.pi / 2
        d = d_arc(X, Y, cx, 0.0, r, a0, a0 + math.pi)
        for sy in (-1, 1):
            d = np.minimum(d, d_seg(X, Y, cx, sy * r, s * BB_X, sy * r))
        add(cov_band(d), sl)
        # three point line: corner straights + arc
        r3 = R3 - HW
        y3 = Y3 - HW
        dxj = math.sqrt(r3 * r3 - y3 * y3)
        xj = RIM_X - dxj
        th = math.atan2(y3, -dxj)  # ~112 deg
        sl, X, Y = grid(min(s * BX, s * (RIM_X - R3)), max(s * BX, s * (RIM_X - R3)), -Y3, Y3)
        if s > 0:
            d = d_arc(X, Y, RIM_X, 0.0, r3, th, 2 * math.pi - th)
        else:
            d = d_arc(X, Y, -RIM_X, 0.0, r3, -(math.pi - th), (math.pi - th))
        for sy in (-1, 1):
            d = np.minimum(d, d_seg(X, Y, s * xj, sy * y3, s * (BX - HW), sy * y3))
        add(cov_band(d), sl)
        # lane space marks (outside the lane lines)
        marks = [(2.13, 0.305, 0.20)] + [(dd, 0.05, 0.15) for dd in (3.35, 4.27, 5.18)]
        for (dist, wx, out) in marks:
            xc = s * (BX - dist - wx / 2)
            for sy in (-1, 1):
                yc = sy * (KEY_Y + out / 2)
                sl, X, Y = grid(xc - wx, xc + wx, yc - out, yc + out)
                add(cov_fill(sd_box(X, Y, xc, yc, wx / 2, out / 2 + 0.004)), sl)
    log("lines done")
    return L


# ---------------------------------------------------------------------------
# 3. Logos / wordmarks (flat Blender render)
# ---------------------------------------------------------------------------
def wordmark(name, text, cap_h, center, z, fill_mat, outline_mats=(), font=eh.FONT_IMPACT, shear=0.14,
             spacing=1.0, width=None, coll=None):
    """Text mesh scaled to cap height (or width), centered; returns (fill_obj, [outline objs])."""
    o = eh.text_obj(name, text, 1.0, font=font, mat=fill_mat, shear=shear, spacing=spacing, collection=coll,
                    resolution=12)
    if width is not None:
        eh.fit_obj(o, width=width, center=center)
    else:
        eh.fit_obj(o, height=cap_h, center=center)
    eh.set_z(o, z)
    outs = []
    for i, (d, m) in enumerate(outline_mats):
        oo = eh.dilate_mesh_obj(o, name + "_ol%d" % i, d, z=z - 0.002 * (i + 1), mat=m, collection=coll)
        outs.append(oo)
    return o, outs


def shifted_copy(o, name, dx, dy, z, mat):
    me = o.data.copy()
    c = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(c)
    c.location = (dx, dy, 0)
    eh.bake_obj(c)
    eh.set_z(c, z)
    c.data.materials.clear()
    c.data.materials.append(mat)
    return c


def build_overlay():
    eh.clear_scene()
    M = {
        "white": eh.flat_mat("F_White", "#F7F4EE"),
        "char": eh.flat_mat("F_Char", "#17181C"),
        "red": eh.flat_mat("F_Red", eh.RED),
        "orange": eh.flat_mat("F_Orange", eh.ORANGE),
        "yellow": eh.flat_mat("F_Yellow", eh.YELLOW),
        "ball": eh.flat_mat("F_Ball", "#F06A12"),
        "ballrim": eh.flat_mat("F_BallRim", "#17181C"),
        "seam": eh.flat_mat("F_Seam", "#17181C"),
        "shine": eh.flat_mat("F_Shine", "#FF9A3D"),
        "deep": eh.flat_mat("F_Deep", "#7A1005"),
    }
    # --- center logo -------------------------------------------------------
    disc_mat = eh.gradient_mat("F_Disc", [(0.0, "#6B1A08"), (0.45, "#33130F"), (1.0, "#17181C")],
                               v0=0.0, v1=R_CC, center=(0.0, 0.25))
    eh.fill_obj("cc_disc", [eh.circle_pts(0, 0, R_CC - 0.02, 256)], 0.000, disc_mat)
    bm = eh.bmesh.new()
    eh.bm_add_ring(bm, 0, 0, R_CC - 2 * HW, R_CC, 0.001, 360)
    eh.obj_from_bm("cc_ring", bm, M["white"])
    # flame mark: ball sits exactly inside the inner circle line
    eh.build_flame_mark("cm", (0.0, 0.0), 0.50, 0.002,
                        dict(red=M["red"], orange=M["orange"], yellow=M["yellow"], ball=M["ball"],
                             seam=M["seam"], shine=M["shine"], outline=M["deep"]),
                        outline=0.035, seam_w=0.085)
    bm = eh.bmesh.new()
    eh.bm_add_ring(bm, 0, 0, R_CI - 2 * HW, R_CI, 0.008, 256)
    eh.obj_from_bm("ci_ring", bm, M["white"])
    # wordmark banner across the lower half of the circle
    wm_y = -1.13
    fill = eh.gradient_mat("F_WordGrad", [(0.0, "#C81E0A"), (0.45, eh.ORANGE), (1.0, "#FFD23F")],
                           axis="Y", v0=wm_y - 0.33, v1=wm_y + 0.33)
    o, outs = wordmark("cc_word", "HEAT CHECK", 0.66, (0.0, wm_y), 0.020, fill,
                       outline_mats=((0.045, M["white"]), (0.10, M["char"])))
    # --- apron wordmarks (read from the front camera: glyph tops toward +Y) ---
    for sy in (-1, 1):
        yc = sy * (BY + (Y1 - BY) / 2) + 0.01
        for sx in (-1, 1):
            o, outs = wordmark("ap_%d_%d" % (sx, sy), "HEAT CHECK", 0.58, (sx * 7.4, yc), 0.020, M["white"])
            shifted_copy(o, o.name + "_sh", 0.04, -0.04, 0.015, M["red"])
    # baseline aprons: flame mark lockups above / below the stanchion
    for sx in (-1, 1):
        xc = sx * (BX + (X1 - BX) / 2)
        for sy in (-1, 1):
            yc = sy * 4.6
            eh.build_flame_mark("bl_%d_%d" % (sx, sy), (xc, yc + 0.30), 0.27, 0.002,
                                dict(red=M["red"], orange=M["orange"], yellow=M["yellow"], ball=M["ball"],
                                     seam=M["seam"], shine=M["shine"], outline=M["deep"]), outline=0.03,
                                seam_w=0.09)
            o, outs = wordmark("bl_w_%d_%d" % (sx, sy), "HEAT CHECK", None, (xc, yc - 0.42), 0.020, M["white"],
                               width=2.05)
    log("overlay scene built")
    eh.flat_scene(W, H, samples=12)
    eh.ortho_camera(0.0, 0.0, X1 - X0)
    ov = eh.render_rgba("court_overlay")
    log("overlay rendered", ov.shape)
    return ov


# ---------------------------------------------------------------------------
# 4. Meshes, materials, previews
# ---------------------------------------------------------------------------
def build_meshes(mats):
    # court floor plane, 16x8 quads
    nx, ny = 16, 8
    xs = np.linspace(X0, X1, nx + 1)
    ys = np.linspace(Y0, Y1, ny + 1)
    V = np.array([(x, y, 0.0) for y in ys for x in xs], np.float32)
    F = []
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            F.append((a, a + 1, a + nx + 2, a + nx + 1))
    F = np.array(F, np.int32)
    uv = np.array([((V[k, 0] - X0) / (X1 - X0), (V[k, 1] - Y0) / (Y1 - Y0)) for k in F.ravel()], np.float32)
    court = eh.mesh_from_arrays("SM_CourtFloor", V, F, uvs=uv, materials=[mats["MI_Court"]])
    # arena floor: big dark slab top at z=-0.01 out past the bowl walls
    ax, ay = 46.0, 42.0
    nx, ny = 8, 8
    xs = np.linspace(-ax, ax, nx + 1)
    ys = np.linspace(-ay, ay, ny + 1)
    V = np.array([(x, y, -0.01) for y in ys for x in xs], np.float32)
    F = []
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            F.append((a, a + 1, a + nx + 2, a + nx + 1))
    F = np.array(F, np.int32)
    uv = np.array([(V[k, 0] / 4.0, V[k, 1] / 4.0) for k in F.ravel()], np.float32)
    arena = eh.mesh_from_arrays("SM_ArenaFloor", V, F, uvs=uv, materials=[mats["MI_ArenaFloor"]])
    return court, arena


def preview_gamecam(court_png):
    eh.clear_scene()
    lib = eh.MatLib("court_preview")
    mats = {"MI_Court": lib.opaque("MI_Court", (1, 1, 1), 0.22, 0.0, 0.6, texture="T_Court"),
            "MI_ArenaFloor": lib.opaque("MI_ArenaFloor", eh.lin("#1A1B20"), 0.45)}
    build_meshes(mats)
    eh.preview_scene((1600, 900), samples=32, view="AgX", exposure=-0.2, world=(0.03, 0.03, 0.035))
    for i, x in enumerate((-10, 0, 10)):
        for j, y in enumerate((-5, 5)):
            eh.area_light("A%d%d" % (i, j), (x, y, 14), (x, y * 0.6, 0), 1600, size=6.0)
    eh.look_cam("Cam", (0.0, -16.0, 9.0), (0.0, 2.0, 1.0), lens=24)
    eh.render_preview(os.path.join(eh.PREVIEW_DIR, "court_gamecam.png"))
    eh.look_cam("Cam2", (-6.0, -12.0, 3.0), (-11.5, 0.0, 0.0), lens=30)
    eh.render_preview(os.path.join(eh.PREVIEW_DIR, "court_keycam.png"))


def main():
    rgb, f = make_wood()
    paint_regions(rgb, f)
    L = line_mask()
    white = np.array(eh.srgb("#F7F4EE"), np.float32)
    lines_rgb = white[None, None, :] * (1.0 + 0.12 * (f - 1.0))[..., None]
    rgb = eh.over(rgb, lines_rgb, L)
    del L, lines_rgb
    ov = build_overlay()
    ov_rgb = ov[..., :3] * (1.0 + 0.30 * (f - 1.0))[..., None]
    rgb = eh.over(rgb, ov_rgb, ov[..., 3])
    del ov, ov_rgb
    out_path = os.path.join(eh.TEX_DIR, "T_Court.png")
    eh.save_png(rgb, out_path)
    log("texture saved")
    # previews of the texture itself (image top = +Y)
    eh.save_png(eh.downsample(rgb, 4), os.path.join(eh.PREVIEW_DIR, "court_top.png"))
    cx0, cy0 = int((-3.6 - X0) / PX), int((-2.4 - Y0) / PX)
    eh.save_png(rgb[cy0:cy0 + int(4.8 / PX), cx0:cx0 + int(7.2 / PX)],
                os.path.join(eh.PREVIEW_DIR, "court_detail_center.png"))
    kx0, ky0 = int((7.6 - X0) / PX), int((-3.2 - Y0) / PX)
    eh.save_png(eh.downsample(rgb[ky0:ky0 + int(6.4 / PX), kx0:kx0 + int(9.4 / PX)], 1),
                os.path.join(eh.PREVIEW_DIR, "court_detail_key.png"))
    ax0, ay0 = int((11.0 - X0) / PX), int((2.0 - Y0) / PX)
    eh.save_png(rgb[ay0:ay0 + int(6.5 / PX), ax0:ax0 + int(6.0 / PX)],
                os.path.join(eh.PREVIEW_DIR, "court_detail_corner.png"))
    del rgb, f

    # meshes + materials + export
    eh.clear_scene()
    lib = eh.MatLib("court")
    mats = {
        "MI_Court": lib.opaque("MI_Court", (1.0, 1.0, 1.0), roughness=0.22, metallic=0.0, specular=0.6,
                               texture="T_Court"),
        "MI_ArenaFloor": lib.opaque("MI_ArenaFloor", eh.lin("#1A1B20"), roughness=0.45, metallic=0.0,
                                    specular=0.5),
    }
    court, arena = build_meshes(mats)
    hc.export_static_fbx([court], "SM_CourtFloor.fbx")
    hc.export_static_fbx([arena], "SM_ArenaFloor.fbx")
    eh.report_mesh(court)
    eh.report_mesh(arena)
    lib.write()
    eh.write_manifest("court", dict(
        note="Blender meters, Unreal cm = (100x, -100y, 100z). Both meshes use the world origin as pivot.",
        texture=dict(name="T_Court", size=[W, H], covers_x=[X0, X1], covers_y=[Y0, Y1],
                     uv="u=(x+17)/34, v=(y+8.5)/17 (image top = +Y, far sideline)", meters_per_texel=PX),
        court=dict(boundary_outer_x=[-BX, BX], boundary_outer_y=[-BY, BY], line_width=2 * HW,
                   rim_floor_points=[[-RIM_X, 0.0], [RIM_X, 0.0]], three_point_radius=R3, three_point_corner_y=Y3,
                   key_half_width=KEY_Y, free_throw_line_x=FT_X, free_throw_circle_radius=R_FT,
                   restricted_arc_radius=R_RA, center_circle_radius=R_CC, center_inner_circle_radius=R_CI),
        meshes=dict(SM_CourtFloor=dict(z=0.0, x=[X0, X1], y=[Y0, Y1], material="MI_Court"),
                    SM_ArenaFloor=dict(z=-0.01, x=[-46.0, 46.0], y=[-42.0, 42.0], material="MI_ArenaFloor")),
    ))
    preview_gamecam(out_path)
    eh.cleanup_tmp()
    log("done")


if __name__ == "__main__":
    main()
