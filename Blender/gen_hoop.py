"""HEAT CHECK - hoop generator (one hoop, hoop-local space).

Hoop-local frame: origin = floor point under the rim center, court toward +X, baseline at x=-1.60,
backboard front face at x=-0.38 (glass x in [-0.41,-0.38], y in [-0.915,0.915], z in [2.90,3.97]).
Unreal places one hoop at x=-1272.5 cm (yaw 0) and one at x=+1272.5 cm (yaw 180).

Outputs (Art/Export/Meshes):
  SM_HoopStanchion  pivot = hoop origin   padded base + pole + boom + backboard mount
  SM_Backboard      pivot = hoop origin   glass panel only (MI_Glass)
  SM_BackboardFrame pivot = hoop origin   edge frame, border + inner rectangle, pads, LED strip, shot clock
  SM_Rim            pivot = rim mount point (-0.38, 0, 3.05)
  SM_Net            pivot = rim center (0, 0, 3.05)
  Art/Export/Textures/T_ShotClock.png, Art/Export/Materials/hoop.json, Art/Previews/hoop_*.png

Run:  blender -b --factory-startup -P Blender/gen_hoop.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import math  # noqa: E402

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector  # noqa: E402

import env_helpers as eh  # noqa: E402
import hc_common as hc  # noqa: E402

RIM_Z = 3.05
RIM_R_IN = 0.2286
RIM_TUBE = 0.010
RIM_R = RIM_R_IN + RIM_TUBE          # torus major radius
BOARD_X = -0.38                       # glass front face
GLASS = dict(x0=-0.41, x1=-0.38, y=0.915, z0=2.90, z1=3.97)
MOUNT = (-0.38, 0.0, RIM_Z)           # SM_Rim pivot


# ---------------------------------------------------------------------------
# Shot clock texture (seven-segment digits)
# ---------------------------------------------------------------------------
def make_shot_clock_texture():
    W, H = 256, 128
    img = np.zeros((H, W, 3), np.float32)
    img[:] = eh.srgb("#070707")
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32) + 0.5
    on = np.array(eh.srgb("#FF2A12"), np.float32)
    off = np.array(eh.srgb("#2A0905"), np.float32)
    segs = {"a": (0.5, 1.0, 1), "b": (1.0, 0.75, 0), "c": (1.0, 0.25, 0), "d": (0.5, 0.0, 1),
            "e": (0.0, 0.25, 0), "f": (0.0, 0.75, 0), "g": (0.5, 0.5, 1)}
    digits = {"2": "abged", "4": "fgbc"}

    def seg_cov(cx, cy, horiz, cw, ch, t):
        # hexagonal segment via |dx| + |dy| style SDF
        X = xx - cx
        Y = yy - cy
        X = X - 0.12 * Y  # italic slant
        if horiz:
            L = cw * 0.5 - t * 0.35
            d = np.maximum(np.abs(Y) - t * 0.5, np.abs(X) + np.abs(Y) - L)
        else:
            L = ch * 0.25 - t * 0.35
            d = np.maximum(np.abs(X) - t * 0.5, np.abs(Y) + np.abs(X) - L)
        return np.clip(0.5 - d, 0.0, 1.0)

    cw, ch, t = 62.0, 92.0, 13.0
    for di, (ch_, x0) in enumerate((("2", 52.0), ("4", 140.0))):
        y0 = 18.0
        for s, (fx, fy, horiz) in segs.items():
            cov = seg_cov(x0 + fx * cw, y0 + fy * ch, horiz, cw, ch, t)
            col = on if s in digits[ch_] else off
            img = img * (1 - cov[..., None]) + col * cov[..., None]
    # soft glow around lit segments
    lit = (np.abs(img - on).sum(axis=2) < 0.05).astype(np.float32)
    glow = eh.gauss_blur(lit, 3.0)[..., None]
    img = np.clip(img + on * glow * 0.35, 0, 1)
    eh.save_png(img, os.path.join(eh.TEX_DIR, "T_ShotClock.png"))


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------
def make_materials():
    lib = eh.MatLib("hoop")
    M = {
        "pad": lib.opaque("MI_StanchionPad", eh.lin("#D0230F"), roughness=0.45, specular=0.5),
        "dark": lib.opaque("MI_StanchionDark", eh.lin("#1B1C21"), roughness=0.5, specular=0.5),
        "metal": lib.opaque("MI_MetalDark", eh.lin("#30333A"), roughness=0.35, metallic=0.85),
        "white": lib.opaque("MI_HoopWhite", eh.lin("#F2F2F2"), roughness=0.35, specular=0.5),
        "glass": lib.glass("MI_Glass", (0.85, 0.93, 1.0), opacity=0.18, roughness=0.03),
        "led": lib.emissive("MI_BackboardLED", eh.lin("#FF2A10"), emissive_strength=2.0),
        "clock": lib.emissive("MI_ShotClock", (1.0, 1.0, 1.0), emissive_strength=3.0, texture="T_ShotClock"),
        "rim": lib.opaque("MI_RimOrange", (1.0, 0.25, 0.03), roughness=0.35, metallic=0.7),
        "net": lib.opaque("MI_Net", (0.92, 0.92, 0.90), roughness=0.9, specular=0.3),
    }
    return lib, M


def bevel_mesh(o, offset, segments=2):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.bevel(bm, geom=list(bm.edges), offset=offset, segments=segments, profile=0.5, affect="EDGES",
                    clamp_overlap=True)
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    return o


# ---------------------------------------------------------------------------
# Meshes
# ---------------------------------------------------------------------------
def build_stanchion(M):
    parts = []
    # base: charcoal kick plate, red padded body with sloped court-side face, charcoal top cap
    parts.append(eh.box_obj("st_kick", (-3.90, -0.655, 0.0), (-2.30, 0.655, 0.10), M["dark"], bevel=0.012))
    body = eh.prism_obj("st_body", [(-3.88, 0.10), (-2.30, 0.10), (-2.30, 0.52), (-2.56, 0.90), (-3.88, 0.90)],
                        "Y", -0.65, 0.65, M["pad"])
    parts.append(bevel_mesh(body, 0.045, 3))
    cap = eh.prism_obj("st_cap", [(-3.90, 0.885), (-2.57, 0.885), (-2.62, 0.975), (-3.90, 0.975)], "Y",
                       -0.66, 0.66, M["dark"])
    parts.append(bevel_mesh(cap, 0.012, 2))
    # side wordmarks (read correctly from outside on both faces)
    for side in (-1, 1):
        t = eh.text_obj("st_txt%d" % side, "HEAT CHECK", 1.0, font=eh.FONT_IMPACT, shear=0.14, extrude=0.004,
                        mat=M["white"], resolution=8)
        eh.fit_obj(t, width=1.18)
        # text lies in XY (tops +Y); stand it on the side face
        t.rotation_euler = (math.radians(90), 0, math.radians(0 if side < 0 else 180))
        t.location = (-3.12, side * 0.652, 0.50)
        eh.bake_obj(t)
        parts.append(t)
        stripe = eh.box_obj("st_stripe%d" % side, (-3.80, side * 0.652 - 0.002, 0.27),
                            (-2.40, side * 0.652 + 0.002, 0.30), M["white"])
        parts.append(stripe)
    # pole with padding, boom, brace, backboard mount
    parts.append(eh.box_obj("st_pole", (-3.40, -0.14, 0.95), (-3.10, 0.14, 3.72), M["metal"], bevel=0.02))
    parts.append(eh.box_obj("st_polepad", (-3.44, -0.18, 0.95), (-3.06, 0.18, 2.25), M["pad"], bevel=0.05,
                            segments=3))
    parts.append(eh.box_obj("st_polecap", (-3.42, -0.16, 3.62), (-3.08, 0.16, 3.76), M["dark"], bevel=0.02))
    parts.append(eh.oriented_box_obj("st_boom", (-3.25, 0, 3.47), (-0.47, 0, 3.47), 0.16, 0.18, M["metal"],
                                     bevel=0.012))
    parts.append(eh.oriented_box_obj("st_brace", (-3.25, 0, 2.50), (-2.02, 0, 3.40), 0.10, 0.10, M["metal"],
                                     bevel=0.01))
    parts.append(eh.oriented_box_obj("st_brace2", (-3.25, 0, 3.66), (-1.20, 0, 3.55), 0.06, 0.06, M["metal"],
                                     bevel=0.008))
    # open mounting frame behind the glass (keeps the see-through board readable)
    for sy in (-1, 1):
        parts.append(eh.box_obj("st_mount_v%d" % sy, (-0.475, min(sy * 0.30, sy * 0.36), 3.12),
                                (-0.425, max(sy * 0.30, sy * 0.36), 3.86), M["metal"], bevel=0.008))
    parts.append(eh.box_obj("st_mount_t", (-0.475, -0.36, 3.80), (-0.425, 0.36, 3.86), M["metal"], bevel=0.008))
    parts.append(eh.box_obj("st_mount_b", (-0.475, -0.36, 3.12), (-0.425, 0.36, 3.17), M["metal"], bevel=0.008))
    parts.append(eh.box_obj("st_mount_h", (-0.60, -0.36, 3.40), (-0.425, 0.36, 3.54), M["metal"], bevel=0.01))
    o = eh.join_objs(parts, "SM_HoopStanchion")
    return o


def build_backboard(M):
    g = GLASS
    o = eh.box_obj("SM_Backboard", (g["x0"], -g["y"], g["z0"]), (g["x1"], g["y"], g["z1"]), M["glass"])
    return eh.box_uv(o)


def build_frame(M):
    parts = []
    fx0, fx1 = -0.425, -0.365
    # edge frame bars around the glass
    parts.append(eh.box_obj("fr_top", (fx0, -0.935, 3.955), (fx1, 0.935, 3.99), M["metal"], bevel=0.006))
    parts.append(eh.box_obj("fr_bot", (fx0, -0.935, 2.88), (fx1, 0.935, 2.915), M["metal"], bevel=0.006))
    for s in (-1, 1):
        parts.append(eh.box_obj("fr_side%d" % s, (fx0, min(s * 0.90, s * 0.935), 2.88),
                                (fx1, max(s * 0.90, s * 0.935), 3.99), M["metal"], bevel=0.006))
    # white border stripe + inner shooter's rectangle, 4 mm thick just in front of the glass
    x0, x1 = BOARD_X, BOARD_X + 0.004

    def frame_rect(prefix, y_half, z0, z1, w):
        return [eh.box_obj(prefix + "_b", (x0, -y_half, z0), (x1, y_half, z0 + w), M["white"]),
                eh.box_obj(prefix + "_t", (x0, -y_half, z1 - w), (x1, y_half, z1), M["white"]),
                eh.box_obj(prefix + "_l", (x0, -y_half, z0 + w), (x1, -y_half + w, z1 - w), M["white"]),
                eh.box_obj(prefix + "_r", (x0, y_half - w, z0 + w), (x1, y_half, z1 - w), M["white"])]
    parts += frame_rect("border", 0.90, 2.915, 3.955, 0.05)
    parts += frame_rect("inner", 0.295, RIM_Z, RIM_Z + 0.45, 0.05)
    # LED strip on the frame face (top + sides) - lights up on "heat check" moments
    parts.append(eh.box_obj("led_top", (fx1, -0.90, 3.962), (fx1 + 0.004, 0.90, 3.984), M["led"]))
    for s in (-1, 1):
        parts.append(eh.box_obj("led_side%d" % s, (fx1, min(s * 0.906, s * 0.928), 3.0),
                                (fx1 + 0.004, max(s * 0.906, s * 0.928), 3.95), M["led"]))
    # padding along the bottom edge and lower sides
    parts.append(eh.box_obj("pad_bot", (-0.445, -0.955, 2.88), (-0.345, 0.955, 2.95), M["pad"], bevel=0.025,
                            segments=3))
    for s in (-1, 1):
        parts.append(eh.box_obj("pad_side%d" % s, (-0.445, min(s * 0.912, s * 0.958), 2.90),
                                (-0.345, max(s * 0.912, s * 0.958), 3.26), M["pad"], bevel=0.018, segments=2))
    # shot clock on top
    parts.append(eh.box_obj("clk_brk", (-0.44, -0.05, 3.985), (-0.38, 0.05, 4.03), M["metal"]))
    parts.append(eh.box_obj("clk_box", (-0.52, -0.33, 4.02), (-0.30, 0.33, 4.30), M["dark"], bevel=0.012))
    mb = eh.MeshBuilder()
    z0, z1 = 4.05, 4.27
    # front (+X) and back (-X) panels, full texture; side panels use the middle of the texture
    mb.quad((-0.299, -0.29, z0), (-0.299, 0.29, z0), (-0.299, 0.29, z1), (-0.299, -0.29, z1),
            uv=[(0, 0), (1, 0), (1, 1), (0, 1)])
    mb.quad((-0.521, 0.29, z0), (-0.521, -0.29, z0), (-0.521, -0.29, z1), (-0.521, 0.29, z1),
            uv=[(0, 0), (1, 0), (1, 1), (0, 1)])
    mb.quad((-0.32, 0.331, z0), (-0.50, 0.331, z0), (-0.50, 0.331, z1), (-0.32, 0.331, z1),
            uv=[(0.18, 0), (0.82, 0), (0.82, 1), (0.18, 1)])
    mb.quad((-0.50, -0.331, z0), (-0.32, -0.331, z0), (-0.32, -0.331, z1), (-0.50, -0.331, z1),
            uv=[(0.18, 0), (0.82, 0), (0.82, 1), (0.18, 1)])
    parts.append(mb.build("clk_faces", [M["clock"]]))
    return eh.join_objs(parts, "SM_BackboardFrame")


def build_rim(M):
    parts = [eh.torus_obj("rim_ring", (0.0, 0.0, RIM_Z), RIM_R, RIM_TUBE, seg=48, sides=10, mat=M["rim"])]
    parts.append(eh.box_obj("rim_flange", (-0.380, -0.09, 2.93), (-0.366, 0.09, 3.13), M["rim"], bevel=0.004))
    parts.append(eh.box_obj("rim_house", (-0.367, -0.07, 2.955), (-0.255, 0.07, 3.038), M["rim"], bevel=0.012))
    parts.append(eh.box_obj("rim_plate", (-0.37, -0.055, 3.030), (-0.215, 0.055, 3.042), M["rim"], bevel=0.003))
    braces = []
    for s in (-1, 1):
        a = math.radians(180 - s * 38)
        braces.append([(-0.31, s * 0.055, 2.975), (RIM_R * math.cos(a), RIM_R * math.sin(a), RIM_Z - 0.006)])
    parts.append(eh.tube_obj("rim_braces", braces, 0.0055, 6, M["rim"]))
    hooks = []
    for i in range(12):
        a = 2 * math.pi * i / 12
        c, s = math.cos(a), math.sin(a)
        prof = [(RIM_R - 0.002, RIM_Z - 0.006), (RIM_R + 0.002, RIM_Z - 0.018), (RIM_R + 0.010, RIM_Z - 0.024),
                (RIM_R + 0.016, RIM_Z - 0.018)]
        hooks.append([(r * c, r * s, z) for r, z in prof])
    parts.append(eh.tube_obj("rim_hooks", hooks, 0.0024, 4, M["rim"]))
    o = eh.join_objs(parts, "SM_Rim")
    eh.translate_mesh(o, (-MOUNT[0], -MOUNT[1], -MOUNT[2]))
    hc.shade(o, smooth=True, angle=50)
    return o


def build_net(M):
    K = 6
    z_top, z_bot = -0.014, -0.42
    r_top, r_bot = 0.235, 0.14

    def rad(t):
        return r_bot + (r_top - r_bot) * (1.0 - t) ** 1.5

    def knot(k, i):
        t = k / K
        a = 2 * math.pi * (i + 0.5 * k) / 12
        r = rad(t)
        return (r * math.cos(a), r * math.sin(a), z_top + (z_bot - z_top) * t)

    lines = []
    for i in range(12):
        for d in (0, 1):
            pts = []
            for k in range(K + 1):
                ii = i if d == 0 else i - k
                p = knot(k, ii)
                if k > 0:
                    q = pts[-1]
                    m = Vector(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, (p[2] + q[2]) / 2))
                    rr = math.hypot(m.x, m.y)
                    m.x *= (rr + 0.004) / rr
                    m.y *= (rr + 0.004) / rr
                    m.z -= 0.003
                    pts.append(tuple(m))
                pts.append(p)
            lines.append(pts)
    o1 = eh.tube_obj("net_strands", lines, 0.006, 5, M["net"])
    top = [(r_top * math.cos(2 * math.pi * j / 48), r_top * math.sin(2 * math.pi * j / 48), z_top) for j in range(48)]
    bot = [(r_bot * math.cos(2 * math.pi * j / 36), r_bot * math.sin(2 * math.pi * j / 36), z_bot) for j in range(36)]
    o2 = eh.tube_obj("net_rings", [top], 0.0065, 5, M["net"], closed=True)
    o3 = eh.tube_obj("net_rings2", [bot], 0.006, 5, M["net"], closed=True)
    o = eh.join_objs([o1, o2, o3], "SM_Net")
    hc.shade(o, smooth=True, angle=70)
    return o


# ---------------------------------------------------------------------------
# Previews
# ---------------------------------------------------------------------------
def render_previews(objs):
    rim, net = objs["SM_Rim"], objs["SM_Net"]
    # put the rim / net back at their in-hoop positions for viewing (verifies the pivots)
    rim.location = MOUNT
    net.location = (0, 0, RIM_Z)
    # floor + court hint
    lib = eh.MatLib("hoop_preview")
    floor = eh.box_obj("floor", (-6, -5, -0.02), (8, 5, 0.0), lib.opaque("MI_PrevFloor", eh.lin("#C9965E"), 0.3))
    eh.box_obj("baseline", (-1.625, -5, 0.0), (-1.575, 5, 0.002), lib.opaque("MI_PrevLine", (0.9, 0.9, 0.9), 0.4))
    eh.preview_scene((1400, 1000), samples=48, view="AgX", exposure=0.0, world=(0.05, 0.05, 0.06))
    eh.area_light("Key", (4, -5, 9), (-0.5, 0, 2.5), 2500, size=5)
    eh.area_light("Fill", (2, 6, 6), (-1, 0, 2), 900, size=6)
    eh.area_light("Rim", (-6, -2, 7), (-1, 0, 3), 900, size=4)
    eh.look_cam("CamA", (3.2, -6.5, 3.6), (-1.4, 0.0, 2.2), lens=32)
    eh.render_preview(os.path.join(eh.PREVIEW_DIR, "hoop_full.png"))
    eh.look_cam("CamB", (1.25, -1.15, 3.55), (-0.25, 0.0, 3.05), lens=35)
    eh.render_preview(os.path.join(eh.PREVIEW_DIR, "hoop_closeup.png"))
    eh.look_cam("CamC", (6.0, 0.0, 3.0), (0.0, 0.0, 3.3), lens=50)
    eh.render_preview(os.path.join(eh.PREVIEW_DIR, "hoop_front.png"))
    eh.look_cam("CamD", (0.0, -11.0, 3.2), (-1.4, 0.0, 2.0), lens=35)
    eh.render_preview(os.path.join(eh.PREVIEW_DIR, "hoop_side.png"))


def main():
    eh.clear_scene()
    make_shot_clock_texture()
    lib, M = make_materials()
    objs = {}
    objs["SM_HoopStanchion"] = build_stanchion(M)
    objs["SM_Backboard"] = build_backboard(M)
    objs["SM_BackboardFrame"] = build_frame(M)
    objs["SM_Rim"] = build_rim(M)
    objs["SM_Net"] = build_net(M)
    for o in (objs["SM_HoopStanchion"], objs["SM_BackboardFrame"], objs["SM_Backboard"]):
        hc.shade(o, smooth=True, angle=35)
    # constraint check: nothing of the stanchion may reach x > -1.60 below z = 2.9
    co = np.empty(len(objs["SM_HoopStanchion"].data.vertices) * 3, np.float32)
    objs["SM_HoopStanchion"].data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    bad = co[(co[:, 0] > -1.60) & (co[:, 2] < 2.9)]
    print("STANCHION constraint violations:", len(bad))
    for name, o in objs.items():
        hc.export_static_fbx([o], name + ".fbx")
        eh.report_mesh(o)
        print("   bounds", name, eh.mesh_world_bounds(o))
    lib.write()
    eh.write_manifest("hoop", dict(
        note="Hoop-local Blender meters: origin = floor point under the rim centre, court toward +X. "
             "Unreal cm = (100x, -100y, 100z). Place one hoop actor at x=-1272.5 cm yaw 0 and one at "
             "x=+1272.5 cm yaw 180; attach the parts below at their relative offsets.",
        parts={
            "SM_HoopStanchion": dict(pivot="hoop origin", offset_m=[0, 0, 0], ue_offset_cm=[0, 0, 0]),
            "SM_Backboard": dict(pivot="hoop origin", offset_m=[0, 0, 0], ue_offset_cm=[0, 0, 0]),
            "SM_BackboardFrame": dict(pivot="hoop origin", offset_m=[0, 0, 0], ue_offset_cm=[0, 0, 0]),
            "SM_Rim": dict(pivot="rim mount point on the glass", offset_m=list(MOUNT),
                           ue_offset_cm=[MOUNT[0] * 100, 0.0, MOUNT[2] * 100]),
            "SM_Net": dict(pivot="rim centre", offset_m=[0.0, 0.0, RIM_Z], ue_offset_cm=[0.0, 0.0, RIM_Z * 100]),
        },
        dimensions_m=dict(rim_center=[0.0, 0.0, RIM_Z], rim_inner_radius=RIM_R_IN, rim_tube_radius=RIM_TUBE,
                          glass=dict(x=[GLASS["x0"], GLASS["x1"]], y=[-GLASS["y"], GLASS["y"]],
                                     z=[GLASS["z0"], GLASS["z1"]]),
                          inner_rectangle=dict(width=0.59, height=0.45, bottom_z=RIM_Z, plane_x=BOARD_X + 0.004),
                          net=dict(top_radius=0.235, bottom_radius=0.14, length=0.42, diamonds_around=12),
                          stanchion_base=dict(x=[-3.90, -2.30], y=[-0.66, 0.66], z=[0.0, 0.975]),
                          shot_clock=dict(x=[-0.52, -0.30], y=[-0.33, 0.33], z=[4.02, 4.30])),
        animatable=dict(MI_BackboardLED="emissive strip around the board edge; pulse emissive_strength for "
                                        "'heat check' moments",
                        SM_Rim="rotate about its pivot (the mount) for dunk rim-bend",
                        SM_Net="scale/offset about its pivot (rim centre) for the swish"),
    ))
    render_previews(objs)
    eh.cleanup_tmp()


if __name__ == "__main__":
    main()
