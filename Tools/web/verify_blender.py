"""HEAT CHECK web assets: re-import the FINAL GLBs in Blender, check the contract, render previews.

  blender -b --factory-startup --python-exit-code 1 -P Tools/web/verify_blender.py -- <assets_dir> <preview_dir> [--no-render]

Blender's glTF importer converts back to Blender axes (glTF (x, y, z) -> Blender (x, -z, y)),
so the checks below are in Blender coordinates. Writes <preview_dir>/verify_report.json and
exits non-zero if any check fails.
"""
import bpy
import json
import math
import os
import sys
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPORT = os.path.join(ROOT, "Art", "Export")
argv = sys.argv[sys.argv.index("--") + 1:]
ASSETS, PREV = argv[0], argv[1]
RENDER = "--no-render" not in argv
os.makedirs(PREV, exist_ok=True)


def J(*p):
    with open(os.path.join(EXPORT, *p)) as fp:
        return json.load(fp)


CHAR = J("Manifests", "character.json")
ANIMS = J("Manifests", "anims.json")
HOOP = J("Manifests", "hoop.json")
ARENA = J("Manifests", "arena.json")
MATS = {}
for f in os.listdir(os.path.join(EXPORT, "Materials")):
    MATS.update(J("Materials", f))

PLAYER_PARTS = (["SK_Player"]
                + ["SK_Hair_" + n for n in ("Buzz", "Flattop", "Afro", "Braids", "Mohawk", "Curls", "Bun")]
                + ["SK_Beard_Full", "SK_Beard_Goatee", "SK_Headband", "SK_Wristbands"]
                + ["SK_Num_%s%d" % (p, d) for p in "TOC" for d in range(10)]
                + ["SK_JerseyText_" + t for t in ("NEO", "BAY", "RRK", "FRB", "STV", "SSC")])

report = {"checks": [], "facts": {}}
FAILS = []


def check(ok, what, detail=None):
    report["checks"].append({"ok": bool(ok), "check": what, "detail": detail})
    print(("PASS " if ok else "FAIL ") + what + ("" if detail is None else "  " + str(detail)))
    if not ok:
        FAILS.append(what)


def imp(rel):
    before = set(bpy.data.objects)
    acts_before = set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=os.path.join(ASSETS, rel), import_shading="NORMALS", disable_bone_shape=True)
    new = [o for o in bpy.data.objects if o not in before]
    return new, [a for a in bpy.data.actions if a not in acts_before]


def world_bbox(objs, dg=None):
    pts = []
    for o in objs:
        if o.type != "MESH":
            continue
        if dg:
            ev = o.evaluated_get(dg)
            me = ev.to_mesh()
            pts += [o.matrix_world @ v.co for v in me.vertices]
            ev.to_mesh_clear()
        else:
            pts += [o.matrix_world @ v.co for v in o.data.vertices]
    return Vector([min(p[i] for p in pts) for i in range(3)]), Vector([max(p[i] for p in pts) for i in range(3)])


def mat_names(objs):
    return {s.material.name for o in objs if o.type == "MESH" for s in o.material_slots if s.material}


def base_name(n):
    return n.split(".")[0]


def tris(objs):
    t = 0
    for o in objs:
        if o.type == "MESH":
            o.data.calc_loop_triangles()
            t += len(o.data.loop_triangles)
    return t


def clean():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def clip_name(a):
    # importer names actions "<anim>" or "<anim>_<object>" depending on version
    return a.name.split("_Armature")[0]


# ---------------------------------------------------------------------------- player
def verify_character(rel, meshes, clips_expected, label):
    clean()
    objs, acts = imp(rel)
    arms = [o for o in objs if o.type == "ARMATURE"]
    check(len(arms) == 1, f"{label}: exactly one armature", [a.name for a in arms])
    arm = arms[0]
    bones = [b.name for b in arm.data.bones]
    check(sorted(bones) == sorted(CHAR["bones"]), f"{label}: bone names match character.json", len(bones))
    mnames = sorted(base_name(o.name) for o in objs if o.type == "MESH")
    check(mnames == sorted(meshes), f"{label}: mesh object names", len(mnames))
    for o in objs:
        if o.type == "MESH":
            mod = [m for m in o.modifiers if m.type == "ARMATURE"]
            if not (mod and mod[0].object == arm):
                check(False, f"{label}: {o.name} skinned to the shared armature")
    check(all(any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers) for o in objs if o.type == "MESH"),
          f"{label}: every mesh skinned to the same armature")
    mats = mat_names(objs)
    check(mats <= set(MATS) and all(MATS[m]["shader"] == "character" for m in mats), f"{label}: material names are MI_* from character.json", sorted(mats))
    sc = arm.matrix_world.to_scale()
    check(all(abs(s - 1) < 1e-4 for s in sc), f"{label}: armature object scale 1", tuple(round(s, 5) for s in sc))
    names = {clip_name(a): a for a in acts}
    check(sorted(names) == sorted(clips_expected), f"{label}: animation names", sorted(names))
    durs = {}
    for n, a in names.items():
        f0, f1 = a.frame_range
        fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
        durs[n] = (f1 - f0) / fps
        exp = clips_expected[n]
        if exp is not None and abs(durs[n] - exp) > 1.0 / 60:
            check(False, f"{label}: {n} duration", (durs[n], exp))
    check(all(clips_expected[n] is None or abs(durs[n] - clips_expected[n]) <= 1.0 / 60 for n in durs), f"{label}: clip durations = frames/30")
    # rest pose height / facing
    arm.animation_data_create()
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    body = [o for o in objs if base_name(o.name) == meshes[0]][0]
    lo, hi = world_bbox([body], dg)
    report["facts"][label + "_rest_height_m"] = round(hi.z, 4)
    report["facts"][label + "_rest_min_z_m"] = round(lo.z, 4)
    check(1.85 < hi.z < 2.2 and abs(lo.z) < 0.02, f"{label}: standing height ~2 m, feet on floor", (round(lo.z, 3), round(hi.z, 3)))
    me = body.data
    eye = [i for i, s in enumerate(body.material_slots) if s.material and s.material.name == "MI_PlayerEyes"]
    if eye:
        ys = [(body.matrix_world @ me.vertices[v].co).y for p in me.polygons if p.material_index == eye[0] for v in p.vertices]
        my = sum(ys) / len(ys)
        report["facts"][label + "_eyes_blender_y"] = round(my, 4)
        check(my < -0.05, f"{label}: faces Blender -Y (= glTF +Z)", round(my, 3))
    return objs, arm, names


def pose(arm, action, frame):
    arm.animation_data_create()
    arm.animation_data.action = action
    if arm.animation_data.action_slot is None and action.slots:
        arm.animation_data.action_slot = action.slots[0]
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()


clips = {k: v["frames"] / v["fps"] for k, v in ANIMS.items()}
clips["Tip"] = 24 / 30
objs, arm, acts = verify_character("characters/player.glb", PLAYER_PARTS, clips, "player")
# skinning sanity mid-Run: every visible mesh stays near the rig
pose(arm, acts["Run"], 9)
dg = bpy.context.evaluated_depsgraph_get()
lo, hi = world_bbox([o for o in objs if o.type == "MESH"], dg)
check((hi - lo).length < 3.2 and lo.z > -0.1, "player: mid-Run deformed bbox sane (no exploded skinning)", [tuple(round(x, 2) for x in lo), tuple(round(x, 2) for x in hi)])
pose(arm, acts["Dunk"], 24)
dg = bpy.context.evaluated_depsgraph_get()
_, hi = world_bbox([o for o in objs if base_name(o.name) == "SK_Player"], dg)
report["facts"]["player_dunk_slam_top_m"] = round(hi.z, 3)
if RENDER:
    keep = {"SK_Player", "SK_Hair_Flattop", "SK_Headband", "SK_Wristbands", "SK_Num_T2", "SK_Num_O3", "SK_JerseyText_NEO"}
    for o in objs:
        if o.type == "MESH":
            o.hide_render = base_name(o.name) not in keep
    pose(arm, acts["Run"], 9)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = 900, 1100
    sc.render.film_transparent = False
    sc.world = bpy.data.worlds.new("W")
    sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.05, 0.06, 1)
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(50), 0, math.radians(-30))
    sc.collection.objects.link(sun)
    bpy.ops.mesh.primitive_plane_add(size=6)
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    for nm, loc in (("player_run_3q.png", (2.2, -3.4, 1.4)), ("player_run_side.png", (4.0, 0.0, 1.1))):
        cam.location = loc
        d = Vector((0, 0, 1.0)) - Vector(loc)
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(PREV, nm)
        bpy.ops.render.render(write_still=True)

# ---------------------------------------------------------------------------- referee
verify_character("characters/referee.glb", ["SK_Referee"], {"RefToss": 45 / 30, "Idle": 60 / 30}, "referee")

# ---------------------------------------------------------------------------- statics
clean()
objs, _ = imp("arena/ball.glb")
lo, hi = world_bbox(objs)
r = (hi - lo).x / 2
report["facts"]["ball_radius_m"] = round(r, 4)
check([o.name for o in objs] == ["SM_Ball"] and abs(r - 0.12) < 0.002, "ball: SM_Ball radius 0.12", round(r, 4))
img = [i for i in bpy.data.images if i.size[0]]
check(img and max(img[0].size) <= 1024, "ball: T_Ball <= 1024 px", [tuple(i.size) for i in img])

clean()
objs, _ = imp("arena/hoop.glb")
byname = {o.name: o for o in objs}
check(sorted(byname) == sorted(HOOP["parts"]), "hoop: node names", sorted(byname))
for n, p in HOOP["parts"].items():
    o = byname[n]
    ok = (o.location - Vector(p["offset_m"])).length < 1e-4 and o.rotation_euler.to_quaternion().angle < 1e-4
    check(ok, f"hoop: {n} node at offset {p['offset_m']}", tuple(round(x, 4) for x in o.location))
rlo, rhi = world_bbox([byname["SM_Rim"]])
rim_ring_z = (byname["SM_Rim"].matrix_world @ Vector((0.38, 0, 0))).z
report["facts"]["rim_height_m"] = round(rim_ring_z, 4)
check(abs(rim_ring_z - 3.05) < 1e-3, "hoop: rim centre at 3.05 m", rim_ring_z)
glass = bpy.data.materials.get("MI_Glass")
gl = [n for n in glass.node_tree.nodes if n.type == "BSDF_PRINCIPLED"][0]
check(gl.inputs["Alpha"].default_value < 0.5, "hoop: MI_Glass transparent", gl.inputs["Alpha"].default_value)
check(mat_names(objs) <= set(MATS), "hoop: material names from hoop.json", sorted(mat_names(objs)))

clean()
objs, _ = imp("arena/court.glb")
check(sorted(o.name for o in objs) == ["SM_ArenaFloor", "SM_CourtFloor"], "court: node names")
lo, hi = world_bbox([o for o in objs if o.name == "SM_CourtFloor"])
check(abs(lo.x + 17) < 1e-3 and abs(hi.y - 8.5) < 1e-3 and abs(hi.z) < 1e-4, "court: SM_CourtFloor spans x+-17, y+-8.5 at z=0")
img = [i for i in bpy.data.images if i.size[0]]
check(img and tuple(img[0].size) == (4096, 2048), "court: T_Court 4096x2048", [tuple(i.size) for i in img])

for rel, label in (("arena/arena.glb", "arena"), ("arena/arena_lite.glb", "arena_lite")):
    clean()
    objs, _ = imp(rel)
    names = sorted(o.name for o in objs)
    check(names == sorted(ARENA["static_meshes_at_origin"]), f"{label}: mesh node names", len(names))
    check(all(o.matrix_world.is_identity for o in objs), f"{label}: every node at the origin, identity transform")
    t = tris(objs)
    report["facts"][label + "_tris"] = t
    check(mat_names(objs) <= set(MATS), f"{label}: material names from arena.json", sorted(mat_names(objs) - set(MATS)))
    crowd = [o for o in objs if o.name.startswith("SM_Crowd_")]
    fan_ok = all(any(a.name.upper() == "_FAN" for a in o.data.attributes) for o in crowd)
    col_ok = all(len(o.data.color_attributes) > 0 for o in crowd)
    check(fan_ok and col_ok, f"{label}: crowd meshes carry _FAN + COLOR_0", [a.name for a in crowd[0].data.attributes])
    if label == "arena":
        o = crowd[0]
        a = [a for a in o.data.attributes if a.name.upper() == "_FAN"][0]
        vals = [tuple(d.vector) for d in a.data]
        mn = [min(v[i] for v in vals) for i in (0, 1)]
        mx = [max(v[i] for v in vals) for i in (0, 1)]
        report["facts"]["crowd_fan_range"] = [mn, mx]
        check(0 <= mn[0] and mx[0] <= 1 and 0.04 <= mn[1] and mx[1] <= 1.0, "arena: _FAN = (phase 0..1, amplitude 0.05..1)", [mn, mx])

# ---------------------------------------------------------------------------- full scene preview
if RENDER:
    clean()
    sc = bpy.context.scene
    imp("arena/court.glb")
    imp("arena/arena.glb")
    for x, yaw in ((-12.725, 0.0), (12.725, math.pi)):
        objs, _ = imp("arena/hoop.glb")
        root = bpy.data.objects.new("Hoop", None)
        sc.collection.objects.link(root)
        for o in objs:
            if o.parent is None:
                o.parent = root
        root.location = (x, 0, 0)
        root.rotation_euler = (0, 0, yaw)
    objs, _ = imp("arena/ball.glb")
    objs[0].location = (10.5, -1.0, 2.6)
    pobjs, pacts = imp("characters/player.glb")
    parm = [o for o in pobjs if o.type == "ARMATURE"][0]
    keep = {"SK_Player", "SK_Hair_Afro", "SK_Wristbands", "SK_Num_T2", "SK_Num_O3", "SK_JerseyText_NEO"}
    for o in pobjs:
        if o.type == "MESH":
            o.hide_render = base_name(o.name) not in keep
    parm.location = (9.6, -1.0, 0)
    parm.rotation_mode = "XYZ"     # the glTF importer leaves armatures in quaternion mode
    parm.rotation_euler = (0, 0, math.radians(90))     # face +X toward the right hoop
    pose(parm, {clip_name(a): a for a in pacts}["Run"], 9)
    robjs, racts = imp("characters/referee.glb")
    rarm = [o for o in robjs if o.type == "ARMATURE"][0]
    rarm.location = (0, 0, 0)
    pose(rarm, {clip_name(a): a for a in racts}["RefToss"], 27)
    # crowd materials: wire COLOR_0 into base colour (Blender's importer leaves it unused)
    m = bpy.data.materials.get("MI_Crowd")
    if m:
        nt = m.node_tree
        bsdf = [n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"][0]
        ca = nt.nodes.new("ShaderNodeVertexColor")
        nt.links.new(ca.outputs["Color"], bsdf.inputs["Base Color"])
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = 1600, 900
    sc.world = bpy.data.worlds.new("W")
    sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.02, 0.025, 1)
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 4.0
    sun.data.use_shadow = False    # the arena has a roof; light the court as the game's rig would
    sun.rotation_euler = (math.radians(25), 0, math.radians(15))
    sc.collection.objects.link(sun)
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    cam.data.lens = 24
    cam.data.clip_end = 400
    sc.collection.objects.link(cam)
    sc.camera = cam
    for nm, loc, tgt in (("arena_sideline.png", (0, -21.0, 8.5), (0, 1.0, 1.5)),
                         ("arena_hoop_close.png", (7.5, -6.5, 3.2), (12.4, 0, 2.6)),
                         ("arena_wide.png", (0, -32.0, 15.0), (0, 4.0, 4.0))):
        cam.location = loc
        d = Vector(tgt) - Vector(loc)
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(PREV, nm)
        bpy.ops.render.render(write_still=True)
    # same sideline shot with the low-end arena
    for n in ARENA["static_meshes_at_origin"]:
        bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
    imp("arena/arena_lite.glb")
    m = bpy.data.materials.get("MI_Crowd")
    if m and not any(n.type == "VERTEX_COLOR" for n in m.node_tree.nodes):
        bsdf = [n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"][0]
        m.node_tree.links.new(m.node_tree.nodes.new("ShaderNodeVertexColor").outputs["Color"], bsdf.inputs["Base Color"])
    cam.location = (0, -21.0, 8.5)
    cam.rotation_euler = (Vector((0, 1.0, 1.5)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = os.path.join(PREV, "arena_lite_sideline.png")
    bpy.ops.render.render(write_still=True)

with open(os.path.join(PREV, "verify_report.json"), "w") as fp:
    json.dump(report, fp, indent=1)
print("VERIFY", "FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS", len(report["checks"]), "checks")
sys.exit(1 if FAILS else 0)
