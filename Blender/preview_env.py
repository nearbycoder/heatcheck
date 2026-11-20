"""HEAT CHECK - environment assembly preview.

Re-imports every exported environment FBX from Art/Export/Meshes plus the material JSON files, places
them the way the game does (arena meshes at the origin, hoops at x = -12.725 m yaw 0 and x = +12.725 m
yaw 180, SM_Rim at the rim mount point, SM_Net at the rim centre) and renders verification shots:

  Art/Previews/env_gamecam.png        game camera (0,-16,9) -> (0,2,1)
  Art/Previews/env_gamecam_right.png  game camera following play to the right
  Art/Previews/env_baseline.png       low baseline shot of a hoop
  Art/Previews/env_overview.png       high corner overview (jumbotron, rig, banners)

Run (after the generators):  blender -b --factory-startup -P Blender/preview_env.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json  # noqa: E402
import math  # noqa: E402

import bpy  # noqa: E402

import env_helpers as eh  # noqa: E402

RIM_X = 12.725
ENV_MESHES_SKIP = {"SM_Ball"}


def import_fbx(name):
    path = os.path.join(eh.MESH_DIR, name + ".fbx")
    if not os.path.exists(path):
        print("WARN missing", path)
        return None
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path)
    new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if not new:
        return None
    o = new[0]
    o.name = name
    return o


def instance_of(src, name, loc=(0, 0, 0), rot_z=0.0):
    o = bpy.data.objects.new(name, src.data)
    bpy.context.scene.collection.objects.link(o)
    o.matrix_world = src.matrix_world.copy()
    from mathutils import Matrix
    o.matrix_world = Matrix.Translation(loc) @ Matrix.Rotation(rot_z, 4, "Z") @ src.matrix_world
    return o


def place(o, loc=(0, 0, 0), rot_z=0.0):
    from mathutils import Matrix
    o.matrix_world = Matrix.Translation(loc) @ Matrix.Rotation(rot_z, 4, "Z") @ o.matrix_world


def main():
    eh.clear_scene()
    specs = eh.load_material_specs()
    names = sorted(os.path.splitext(f)[0] for f in os.listdir(eh.MESH_DIR)
                   if f.startswith("SM_") and f.endswith(".fbx"))
    hoop_parts = ["SM_HoopStanchion", "SM_Backboard", "SM_BackboardFrame", "SM_Rim", "SM_Net"]
    char_like = [n for n in names if n not in hoop_parts and n not in ENV_MESHES_SKIP]
    imported = {}
    for n in char_like:
        o = import_fbx(n)
        if o is not None:
            imported[n] = o
    # hoops: hoop-local meshes; pivots: stanchion/board/frame = hoop origin, rim = mount point, net = rim centre
    for n in hoop_parts:
        o = import_fbx(n)
        if o is None:
            continue
        base_off = {"SM_Rim": (-0.38, 0.0, 3.05), "SM_Net": (0.0, 0.0, 3.05)}.get(n, (0.0, 0.0, 0.0))
        # left hoop (yaw 0) at x = -12.725
        from mathutils import Matrix, Vector
        local = Matrix.Translation(base_off) @ o.matrix_world
        o.matrix_world = Matrix.Translation((-RIM_X, 0, 0)) @ local
        o2 = bpy.data.objects.new(n + "_R", o.data)
        bpy.context.scene.collection.objects.link(o2)
        o2.matrix_world = Matrix.Translation((RIM_X, 0, 0)) @ Matrix.Rotation(math.pi, 4, "Z") @ local
    ball = import_fbx("SM_Ball")
    if ball is not None:
        from mathutils import Matrix
        ball.matrix_world = Matrix.Translation((-10.6, -0.4, 4.1)) @ ball.matrix_world
    # materials from JSON
    for m in bpy.data.materials:
        if m.name in specs:
            eh.build_preview_material(m.name, specs[m.name], emission_scale=0.4)
        elif m.name.split(".")[0] in specs:
            eh.build_preview_material(m.name, specs[m.name.split(".")[0]], emission_scale=0.4)
    missing = sorted({m.name for m in bpy.data.materials if m.name.split(".")[0] not in specs})
    print("MATERIALS without JSON spec:", missing)
    # lights: light-rig panels from the arena manifest + soft fill for the stands
    man_path = os.path.join(eh.MANIFEST_DIR, "arena.json")
    sc = eh.preview_scene((1920, 1080), samples=48, view="AgX", exposure=0.0, world=(0.01, 0.01, 0.012),
                          world_strength=1.0)
    if os.path.exists(man_path):
        man = json.load(open(man_path))
        for i, p in enumerate(man["light_rig"]["panels"]):
            c = p["center"]
            n = p["normal"]
            tgt = (c[0] + n[0] * 10, c[1] + n[1] * 10, c[2] + n[2] * 10)
            eh.area_light("Panel%d" % i, tuple(c), tgt, 1500, size=1.2, size_y=0.7, color=(1.0, 0.95, 0.88),
                          shadow=(i % 4 == 0))
    for (x, y, tx, ty) in ((0, -6, 0, 18), (0, 6, 0, -18), (-12, 0, -26, 0), (12, 0, 26, 0)):
        eh.area_light("Fill", (x, y, 18), (tx, ty, 4), 6000, size=8, color=(1.0, 0.9, 0.8), shadow=False)
    shots = [("env_gamecam", (0.0, -16.0, 9.0), (0.0, 2.0, 1.0), 26),
             ("env_gamecam_right", (9.0, -16.0, 9.0), (9.0, 2.0, 1.0), 26),
             ("env_baseline", (-4.5, -5.5, 2.2), (-12.4, 0.0, 2.6), 24),
             ("env_overview", (-22.0, -18.0, 15.5), (2.0, 5.0, 4.0), 18)]
    for name, loc, tgt, lens in shots:
        eh.look_cam("Cam_" + name, loc, tgt, lens=lens)
        eh.render_preview(os.path.join(eh.PREVIEW_DIR, name + ".png"))


if __name__ == "__main__":
    main()
