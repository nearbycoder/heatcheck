"""HEAT CHECK web export: skinned characters -> raw glTF (meters, Y-up).

Run headless (the build script does this):
  blender -b Art/Blend/player_actions.blend --factory-startup --python-exit-code 1 \
      -P Tools/web/blender_characters.py -- player <out.glb> <stats.json>
  blender -b Art/Blend/referee.blend ... -- referee <out.glb> <stats.json>

Source scenes keep the rig in CENTIMETRES (objects scaled x100 and applied, scene
unit scale 0.01, see Docs/ASSET_SPEC.md). Here we rescale the armature rest pose,
every skinned mesh and every location F-curve by 0.01 so the glTF is in metres
with scale-1 bones and no root-node scale. Materials keep their MI_* names; the
post-process step (postprocess.mjs) writes the final PBR values.
"""
import bpy
import json
import os
import sys
from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BLEND = os.path.join(ROOT, "Art", "Blend")
ARGS = sys.argv[sys.argv.index("--") + 1:]
MODE, OUT, STATS = ARGS[0], ARGS[1], ARGS[2]
CM2M = 0.01

PLAYER_PARTS = (["SK_Player"]
                + ["SK_Hair_" + n for n in ("Buzz", "Flattop", "Afro", "Braids", "Mohawk", "Curls", "Bun")]
                + ["SK_Beard_Full", "SK_Beard_Goatee", "SK_Headband", "SK_Wristbands"]
                + ["SK_Num_%s%d" % (p, d) for p in "TOC" for d in range(10)]
                + ["SK_JerseyText_" + t for t in ("NEO", "BAY", "RRK", "FRB", "STV", "SSC")])


def fcurves(action):
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                yield from bag.fcurves


def append_action(blend, name):
    with bpy.data.libraries.load(blend, link=False) as (src, dst):
        if name not in src.actions:
            raise SystemExit("action %s not in %s" % (name, blend))
        dst.actions = [name]
    return bpy.data.actions[name]


arm = bpy.data.objects["Armature"]
if MODE == "player":
    keep_meshes = PLAYER_PARTS
    append_action(os.path.join(BLEND, "referee.blend"), "A_Tip")
    clips = None  # every A_* action
elif MODE == "referee":
    keep_meshes = ["SK_Referee"]
    for a in list(bpy.data.actions):
        if a.name != "A_RefToss":
            bpy.data.actions.remove(a)
    # the referee shares the player skeleton; reuse the player's idle loop
    append_action(os.path.join(BLEND, "player_actions.blend"), "A_Idle")
else:
    raise SystemExit("mode must be player|referee")

missing = [n for n in keep_meshes if n not in bpy.data.objects]
if missing:
    raise SystemExit("missing meshes: %s" % missing)

# --- strip everything that is not the rig or a contract mesh -----------------
for o in list(bpy.data.objects):
    if o is arm or o.name in keep_meshes:
        continue
    bpy.data.objects.remove(o, do_unlink=True)
for o in [arm] + [bpy.data.objects[n] for n in keep_meshes]:
    o.hide_set(False)
    o.hide_viewport = False
    o.hide_render = False
    for m in o.modifiers:
        m.show_viewport = m.show_render = True

# --- centimetres -> metres -----------------------------------------------------
assert arm.matrix_world == Matrix.Identity(4), arm.matrix_world
S = Matrix.Scale(CM2M, 4)
arm.data.transform(S)
for n in keep_meshes:
    o = bpy.data.objects[n]
    assert o.parent is arm and o.matrix_world == Matrix.Identity(4), (n, o.matrix_world)
    o.data.transform(S)
    o.data.update()
    if o.data.name != n:
        o.data.name = n
for act in bpy.data.actions:
    for fc in fcurves(act):
        if fc.data_path.endswith(".location"):
            for kp in fc.keyframe_points:
                kp.co.y *= CM2M
                kp.handle_left.y *= CM2M
                kp.handle_right.y *= CM2M
            fc.update()
bpy.context.scene.unit_settings.scale_length = 1.0
bpy.context.scene.render.fps = 30
bpy.context.scene.render.fps_base = 1.0

# --- name actions by their manifest key ----------------------------------------
for act in list(bpy.data.actions):
    if act.name.startswith("A_"):
        act.name = act.name[2:]
    act.use_fake_user = True
    act.pose_markers.clear() if hasattr(act.pose_markers, "clear") else None

# --- stats: height, facing, root motion ------------------------------------------
deps = bpy.context.evaluated_depsgraph_get()
arm.animation_data_create()
arm.animation_data.action = None
for pb in arm.pose.bones:
    pb.location = (0, 0, 0)
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.scale = (1, 1, 1)
bpy.context.view_layer.update()


def bbox(o):
    pts = [o.matrix_world @ v.co for v in o.data.vertices]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


stats = {"mode": MODE, "meshes": {}, "bones": [b.name for b in arm.data.bones], "clips": {}}
for n in keep_meshes:
    o = bpy.data.objects[n]
    lo, hi = bbox(o)
    me = o.data
    me.calc_loop_triangles()
    stats["meshes"][n] = {"tris": len(me.loop_triangles), "verts": len(me.vertices),
                          "materials": [m.name for m in me.materials],
                          "bbox_blender_m": [lo, hi]}
body = keep_meshes[0]
lo, hi = stats["meshes"][body]["bbox_blender_m"]
stats["rest_height_m"] = hi[2]
stats["rest_min_z_m"] = lo[2]
stats["max_attachment_height_m"] = max(m["bbox_blender_m"][1][2] for m in stats["meshes"].values())
head = arm.data.bones["head"]
stats["head_bone_head_m"] = list(head.head_local)
stats["head_bone_tail_m"] = list(head.tail_local)
# nose / face direction: eyes sit on the -Y side of the head in Blender
eyes = [i for i, m in enumerate(bpy.data.objects[body].data.materials) if m and m.name == "MI_PlayerEyes"]
if eyes:
    me = bpy.data.objects[body].data
    ys = [me.vertices[v].co.y for p in me.polygons if p.material_index == eyes[0] for v in p.vertices]
    stats["eyes_mean_blender_y"] = sum(ys) / len(ys)

for act in bpy.data.actions:
    arm.animation_data.action = act
    if arm.animation_data.action_slot is None and act.slots:
        arm.animation_data.action_slot = act.slots[0]
    f0, f1 = (int(round(x)) for x in act.frame_range)
    root_pts, pel_pts = [], []
    for f in range(f0, f1 + 1):
        bpy.context.scene.frame_set(f)
        root_pts.append(arm.matrix_world @ arm.pose.bones["root"].head)
        pel_pts.append(arm.matrix_world @ arm.pose.bones["pelvis"].head)
    rng = lambda pts, i: max(p[i] for p in pts) - min(p[i] for p in pts)
    stats["clips"][act.name] = {
        "frame_start": f0, "frame_end": f1, "frames": f1 - f0, "fps": 30,
        "duration_s": (f1 - f0) / 30.0,
        "root_motion_range_m": [rng(root_pts, i) for i in range(3)],
        "pelvis_range_m": [rng(pel_pts, i) for i in range(3)],
        "pelvis_net_xy_m": [pel_pts[-1][0] - pel_pts[0][0], pel_pts[-1][1] - pel_pts[0][1]],
        "pelvis_min_max_z_m": [min(p[2] for p in pel_pts), max(p[2] for p in pel_pts)],
    }
arm.animation_data.action = None
for pb in arm.pose.bones:
    pb.location = (0, 0, 0)
    pb.rotation_quaternion = (1, 0, 0, 0)
bpy.context.scene.frame_set(0)

# --- export -----------------------------------------------------------------------
bpy.ops.object.select_all(action="DESELECT")
for o in [arm] + [bpy.data.objects[n] for n in keep_meshes]:
    o.select_set(True)
bpy.context.view_layer.objects.active = arm
os.makedirs(os.path.dirname(OUT), exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=OUT, export_format="GLB", use_selection=True, export_yup=True, export_apply=False,
    export_image_format="NONE", export_materials="EXPORT", export_texcoords=True, export_normals=True,
    export_tangents=False, export_vertex_color="NONE", export_attributes=False,
    export_skins=True, export_influence_nb=4, export_def_bones=False, export_leaf_bone=False,
    export_rest_position_armature=True, export_hierarchy_flatten_bones=False,
    export_animations=True, export_animation_mode="ACTIONS", export_force_sampling=True,
    export_frame_range=False, export_frame_step=1, export_anim_slide_to_zero=True,
    export_optimize_animation_size=False, export_reset_pose_bones=True, export_anim_single_armature=True,
    export_morph=False, export_lights=False, export_cameras=False, export_extras=False)
with open(STATS, "w") as fp:
    json.dump(stats, fp, indent=1)
print("WEB_EXPORT_OK", MODE, OUT)
