"""Build the striped official and the center-court toss using the player rig."""
import math
import os
import sys

import bmesh
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_anims as g
import hc_common as hc

dest = os.path.join(hc.EXPORT_DIR, "Official")
os.makedirs(dest, exist_ok=True)
arm = g.ARM
body = bpy.data.objects["SK_Player"]
hair = bpy.data.objects["SK_Hair_Buzz"]
for obj in list(bpy.context.scene.objects):
    if obj not in (arm, body, hair):
        bpy.data.objects.remove(obj, do_unlink=True)
for obj in (arm, body, hair):
    obj.hide_set(False)
    obj.hide_viewport = obj.hide_render = False

# Cut each shirt stripe into the skinned surface. The dark collar and sleeve
# hems keep the uniform readable from the broadcast camera.
mesh = body.data
slots = {mat.name.removeprefix("MI_Player"): i for i, mat in enumerate(mesh.materials)}
bm = bmesh.new()
bm.from_mesh(mesh)
for face in bm.faces:
    x, y, z = face.calc_center_median()
    if face.material_index == slots["Skin"] and 109 < z < 160 and 14 < abs(x) < 38:
        face.material_index = slots["Jersey"] if abs(x) < 36 else slots["JerseyTrim"]
    elif face.material_index in (slots["Shorts"], slots["ShoeAccent"]):
        face.material_index = slots["ShortsTrim"]
for cut in range(-36, 37, 4):
    faces = [f for f in bm.faces if f.material_index == slots["Jersey"]]
    geom = set(faces)
    for face in faces:
        geom.update(face.edges)
        geom.update(face.verts)
    bmesh.ops.bisect_plane(bm, geom=list(geom), dist=0.0001,
                           plane_co=(cut, 0, 0), plane_no=(1, 0, 0))
for face in bm.faces:
    if face.material_index == slots["Jersey"]:
        face.material_index = slots["Socks" if math.floor(face.calc_center_median().x / 4) % 2 else "JerseyTrim"]
bm.to_mesh(mesh)
bm.free()

# Straight trouser legs overlap the existing waistband and bend with the knee.
for side in ("l", "r"):
    thigh = arm.data.bones["thigh_" + side]
    calf = arm.data.bones["calf_" + side]
    vertices, faces, weights = [], [], []
    for center, rx, ry, upper in (
        (thigh.head_local.lerp(thigh.tail_local, .25), 11.8, 12.5, 1),
        (thigh.head_local.lerp(thigh.tail_local, .68), 11, 10.8, 1),
        (thigh.tail_local, 9.5, 9.8, .5),
        (calf.head_local.lerp(calf.tail_local, .35), 8.8, 9.8, 0),
        (calf.head_local.lerp(calf.tail_local, .91), 7.3, 8.3, 0)):
        start = len(vertices)
        for i in range(20):
            a = 2 * math.pi * i / 20
            vertices.append((center.x + rx * math.cos(a), center.y + ry * math.sin(a), center.z))
            weights.append(upper)
            if start:
                j = (i + 1) % 20
                faces.append((start-20+i, start+i, start+j, start-20+j))
    data = bpy.data.meshes.new("Trouser")
    data.from_pydata(vertices, [], faces)
    data.materials.append(mesh.materials[slots["ShortsTrim"]])
    obj = bpy.data.objects.new("Trouser", data)
    bpy.context.collection.objects.link(obj)
    for poly in data.polygons:
        poly.use_smooth = True
    up = obj.vertex_groups.new(name=thigh.name)
    low = obj.vertex_groups.new(name=calf.name)
    for i, weight in enumerate(weights):
        up.add([i], weight, "REPLACE")
        low.add([i], 1-weight, "REPLACE")
    hc.join([body, obj], "SK_Referee")
hc.join([body, hair], "SK_Referee")
hc.export_skeletal_fbx(arm, [body], "SK_Referee.fbx", directory=dest)

# Both participants share this rig. The jumper reaches across the center
# circle with one hand and keeps the other arm out for balance.
g.set_meshes_deform(False)
hc.ANIM_DIR = dest
bpy.context.scene.render.fps = 30
g.begin("Tip", 24, reach_frame=12)
for frame, crouch, lean, wrist, balance in (
        (0, .16, 11, (.19, -.23, 1.27), 1.13),
        (3, .09, 8, (.17, -.28, 1.55), 1.23),
        (7, .005, 5, (.10, -.35, 1.93), 1.30),
        (12, -.01, 2, (.065, -.38, 2.10), 1.35),
        (15, -.01, 1, (.06, -.40, 2.09), 1.33),
        (19, .015, 6, (.12, -.43, 1.79), 1.23),
        (24, .13, 12, (.24, -.28, 1.32), 1.12)):
    g.stance(crouch=crouch, lean=lean, width=.18, stagger=.04, nod=7)
    g.arm_rel("l", wrist, pole=(.65, .25, -.35), fingers=(-.1, -.4, 1), palm=(0, -1, 0))
    g.arm_rel("r", (-.39, -.13, balance), fingers=(-.5, -.4, .75))
    g.key(frame)
g.export_action("Tip")
bpy.data.actions["A_Tip"].pose_markers.new("Reach").frame = 12

g.begin("RefToss", 45, release_frame=27)
for frame, crouch, lean, nod, reach, height in (
        (0, .045, 5, -4, .34, 1.29), (8, .05, 6, -4, .34, 1.28),
        (17, .16, 12, -9, .34, 1.10), (21, .12, 8, -4, .38, 1.24),
        (24, .055, 4, 1, .40, 1.57), (27, .006, 0, 8, .37, 1.96),
        (30, .005, -1, 10, .34, 2.07)):
    g.stance(crouch=crouch, lean=lean, stagger=.055, nod=nod)
    g.two_hands((0, -reach, height), lift=.55, fingers=(0, -.8, .6))
    g.key(frame)
for frame, z, y, width in ((34, 1.88, -.32, .25), (40, 1.25, -.20, .34), (45, .98, -.03, .30)):
    g.stance(crouch=.03, lean=3, stagger=.055, nod=5)
    g.relaxed_arms(out=width, z=z, y=y)
    g.key(frame)
g.export_action("RefToss")
g.set_meshes_deform(True)
bpy.context.scene.timeline_markers.new("Release", frame=27)
bpy.context.scene.frame_set(0)
hc.save_blend("referee.blend")
