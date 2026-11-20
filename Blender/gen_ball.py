"""HEAT CHECK - game ball generator.

Outputs
  Art/Export/Meshes/SM_Ball.fbx     UV sphere radius 0.12 m at the origin (pivot = ball center), equirect UVs
  Art/Export/Textures/T_Ball.png    2048x1024 equirect: pebbled orange leather, black 8-panel channel seams,
                                    small HEAT CHECK wordmark + flame mark
  Art/Export/Materials/ball.json    MI_Ball
  Art/Previews/ball.png

Seam layout (sphere axes): great circle A = equator (z=0), great circle B = meridian plane x=0,
two curved "side" seams centred on the +X / -X axes (the poles of B), each crossing A twice.

Run:  blender -b --factory-startup -P Blender/gen_ball.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import math  # noqa: E402

import bpy  # noqa: E402
import numpy as np  # noqa: E402

import env_helpers as eh  # noqa: E402
import hc_common as hc  # noqa: E402

R = 0.12
TW, TH = 2048, 1024
SEG, RINGS = 44, 22


def build_ball_mesh(mat):
    """UV sphere with exact equirect UVs: u = lon/2pi + 0.5, v = lat/pi + 0.5 (seam at lon = +-180)."""
    verts, uvs, faces = [], [], []
    vidx = {}

    def vert(i, j):
        # i: 0..SEG (longitude index, SEG duplicates 0 for the UV seam); j: 0..RINGS (latitude, 0 = south pole)
        key = (i, j)
        if key in vidx:
            return vidx[key]
        lat = -math.pi / 2 + math.pi * j / RINGS
        lon = -math.pi + 2 * math.pi * i / SEG
        verts.append((R * math.cos(lat) * math.cos(lon), R * math.cos(lat) * math.sin(lon), R * math.sin(lat)))
        vidx[key] = len(verts) - 1
        return vidx[key]

    corner_uv = []
    for j in range(RINGS):
        for i in range(SEG):
            u0, u1 = i / SEG, (i + 1) / SEG
            v0, v1 = j / RINGS, (j + 1) / RINGS
            if j == 0:  # south pole fan
                um = (u0 + u1) / 2
                faces.append((vert(i, 0), vert(i + 1, 1), vert(i, 1)))
                corner_uv += [(um, 0.0), (u1, v1), (u0, v1)]
            elif j == RINGS - 1:  # north pole fan
                um = (u0 + u1) / 2
                faces.append((vert(i, j), vert(i + 1, j), vert(i, j + 1)))
                corner_uv += [(u0, v0), (u1, v0), (um, 1.0)]
            else:
                faces.append((vert(i, j), vert(i + 1, j), vert(i + 1, j + 1), vert(i, j + 1)))
                corner_uv += [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    # pole vertices: collapse duplicates so the sphere is closed
    V = np.array(verts, np.float32)
    sizes = [len(f) for f in faces]
    corners = [c for f in faces for c in f]
    o = eh.mesh_from_arrays("SM_Ball", V, corners, sizes, uvs=np.array(corner_uv, np.float32), materials=[mat])
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    hc.shade(o, smooth=True, angle=None)
    return o


# ---------------------------------------------------------------------------
# Texture
# ---------------------------------------------------------------------------
def sphere_dirs():
    u = (np.arange(TW, dtype=np.float32) + 0.5) / TW
    v = (np.arange(TH, dtype=np.float32) + 0.5) / TH
    lon = (u - 0.5) * 2 * math.pi
    lat = (v - 0.5) * math.pi
    LON, LAT = np.meshgrid(lon, lat)
    d = np.stack([np.cos(LAT) * np.cos(LON), np.cos(LAT) * np.sin(LON), np.sin(LAT)], axis=-1).astype(np.float32)
    return d, LAT


def noise3(n, d, freq):
    x, y, z = d[..., 0] * freq, d[..., 1] * freq, d[..., 2] * freq
    return (n(x + 11.1, y + 3.7) + n(y + 51.3, z + 17.9) + n(z + 91.7, x + 33.1)) / 3.0


def seam_distance(d):
    """Angular distance (radians) to the nearest seam centre-line."""
    dA = np.abs(np.arcsin(np.clip(d[..., 2], -1, 1)))          # equator z=0
    dB = np.abs(np.arcsin(np.clip(d[..., 0], -1, 1)))          # meridian x=0
    dist = np.minimum(dA, dB)
    th0, dth = math.radians(47.0), math.radians(25.0)
    for sx in (1.0, -1.0):
        alpha = np.arccos(np.clip(sx * d[..., 0], -1, 1))      # angle from the cap centre (+-X)
        phi = np.arctan2(d[..., 1], d[..., 2])                 # azimuth around X, 0 toward +Z
        a_s = th0 + dth * np.cos(phi) ** 2
        # convert the radial offset to an approximate perpendicular distance (curve is not a circle)
        dadphi = -2 * dth * np.cos(phi) * np.sin(phi)
        stretch = np.sqrt(1.0 + (dadphi / np.maximum(np.sin(a_s), 1e-3)) ** 2)
        dist = np.minimum(dist, np.abs(alpha - a_s) / stretch)
    return dist


def panel_id(d):
    """Integer id for the 8 leather panels (for subtle tone variation)."""
    th0, dth = math.radians(47.0), math.radians(25.0)
    pid = (d[..., 2] > 0).astype(np.int32) * 1 + (d[..., 0] > 0).astype(np.int32) * 2
    alpha = np.arccos(np.clip(np.abs(d[..., 0]), -1, 1))
    phi = np.arctan2(d[..., 1], d[..., 2])
    in_cap = alpha < (th0 + dth * np.cos(phi) ** 2)
    return pid + in_cap.astype(np.int32) * 4


def render_label(text_mode):
    """Flat render of a small decal (white bg = paper -> we use alpha) returned as RGBA array."""
    eh.clear_scene()
    dark = eh.flat_mat("F_Dark", "#16120F")
    if text_mode == "word":
        o = eh.text_obj("lbl", "HEAT CHECK", 1.0, font=eh.FONT_IMPACT, shear=0.12, mat=dark, resolution=12)
        eh.fit_obj(o, width=3.6, center=(0, 0))
        o2 = eh.text_obj("lbl2", "OFFICIAL  GAME  BALL", 1.0, font=eh.FONT_DIN, mat=dark, resolution=8)
        eh.fit_obj(o2, width=2.4, center=(0, -0.62))
        eh.flat_scene(1024, 512, samples=16)
        eh.ortho_camera(0, -0.1, 4.0)
    else:
        M = dict(red=dark, orange=None, yellow=None, ball=eh.flat_mat("F_Ball", "#D9581A"), seam=dark)
        eh.build_flame_mark("fm", (0, 0), 1.0, 0.0, M, seam_w=0.11)
        eh.flat_scene(512, 512, samples=16)
        eh.ortho_camera(0, 1.05, 4.4)
    return eh.render_rgba("label_" + text_mode)


def apply_decal(rgb, d, label, center_lon, center_lat, width, aspect):
    """Gnomonic projection of a decal image onto the sphere texture."""
    c = np.array([math.cos(center_lat) * math.cos(center_lon), math.cos(center_lat) * math.sin(center_lon),
                  math.sin(center_lat)], np.float32)
    east = np.array([-math.sin(center_lon), math.cos(center_lon), 0.0], np.float32)
    north = np.cross(c, east)
    dot = (d * c).sum(-1)
    mask = dot > 0.5
    p = d / np.maximum(dot, 1e-3)[..., None]
    x = (p * east).sum(-1) / width + 0.5
    y = (p * north).sum(-1) / (width * aspect) + 0.5
    h, w = label.shape[:2]
    inside = mask & (x >= 0) & (x < 1) & (y >= 0) & (y < 1)
    xi = np.clip((x * (w - 1)), 0, w - 1.001)
    yi = np.clip((y * (h - 1)), 0, h - 1.001)
    x0 = np.floor(xi).astype(np.int32)
    y0 = np.floor(yi).astype(np.int32)
    fx = (xi - x0)[..., None]
    fy = (yi - y0)[..., None]
    s = (label[y0, x0] * (1 - fx) * (1 - fy) + label[y0, x0 + 1] * fx * (1 - fy) +
         label[y0 + 1, x0] * (1 - fx) * fy + label[y0 + 1, x0 + 1] * fx * fy)
    a = np.where(inside, s[..., 3], 0.0) * 0.92
    return rgb * (1 - a[..., None]) + s[..., :3] * a[..., None]


def make_texture():
    d, LAT = sphere_dirs()
    pix = math.pi / TH
    n = eh.LatticeNoise(77, (256, 256))
    n2 = eh.LatticeNoise(78, (256, 256))
    # pebbles: sharpened high-frequency noise in 3D (no pole pinching)
    peb = noise3(n, d, 95.0)
    peb = eh.smoothstep(-0.05, 0.45, peb)
    grime = noise3(n2, d, 6.0)
    base = np.array(eh.srgb("#D65A1C"), np.float32)
    pid = panel_id(d)
    tone = np.array([1.0, 0.975, 1.02, 0.99, 1.015, 0.985, 1.0, 1.025], np.float32)[pid]
    shade = (0.90 + 0.10 * peb) * tone * (1.0 + 0.035 * grime)
    rgb = base[None, None, :] * shade[..., None]
    # seams: black rubber channel with a darker recess edge
    sd = seam_distance(d)
    hw = 0.024
    cov = np.clip(0.5 - (sd - hw) / pix, 0, 1)
    recess = np.clip(0.5 - (sd - hw * 1.9) / (pix * 3.0), 0, 1) * (1 - cov)
    rgb = rgb * (1.0 - 0.35 * recess[..., None])
    seam_col = np.array(eh.srgb("#141210"), np.float32)
    seam_rgb = seam_col * (0.9 + 0.2 * eh.smoothstep(-0.5, 0.5, noise3(n2, d, 140.0)))[..., None]
    rgb = rgb * (1 - cov[..., None]) + seam_rgb * cov[..., None]
    rgb = rgb.astype(np.float32)
    # decals (rendered flat, projected)
    word = render_label("word")
    rgb = apply_decal(rgb, d, word, 0.0, math.radians(21.0), 0.62, 0.5)
    mark = render_label("mark")
    rgb = apply_decal(rgb, d, mark, math.pi, math.radians(22.0), 0.42, 1.0)
    eh.save_png(rgb, os.path.join(eh.TEX_DIR, "T_Ball.png"))


def main():
    make_texture()
    eh.clear_scene()
    lib = eh.MatLib("ball")
    mat = lib.opaque("MI_Ball", (1.0, 1.0, 1.0), roughness=0.65, metallic=0.0, specular=0.45, texture="T_Ball")
    ball = build_ball_mesh(mat)
    hc.export_static_fbx([ball], "SM_Ball.fbx")
    eh.report_mesh(ball)
    print("   bounds", eh.mesh_world_bounds(ball))
    lib.write()
    # preview: three balls at different rotations
    eh.preview_scene((1500, 600), samples=48, view="AgX", exposure=0.0, world=(0.06, 0.06, 0.07))
    for k, rot in enumerate(((0, 0, 0), (math.radians(90), 0, math.radians(30)), (0, 0, math.radians(180)))):
        o = ball if k == 0 else bpy.data.objects.new("b%d" % k, ball.data)
        if k:
            bpy.context.scene.collection.objects.link(o)
        o.location = ((k - 1) * 0.3, 0, 0)
        o.rotation_euler = rot
    eh.area_light("Key", (0.6, -1.2, 1.0), (0, 0, 0), 60, size=0.8)
    eh.area_light("Rim", (-0.8, 0.8, 0.6), (0, 0, 0), 25, size=0.8)
    eh.look_cam("Cam", (0.0, -1.35, 0.25), (0, 0, 0), lens=50)
    eh.render_preview(os.path.join(eh.PREVIEW_DIR, "ball.png"))
    # texture preview (downsampled)
    eh.cleanup_tmp()


if __name__ == "__main__":
    main()
