"""HEAT CHECK web export: static meshes (FBX) -> raw glTF groups (metres, Y-up).

  blender -b --factory-startup --python-exit-code 1 -P Tools/web/blender_static.py -- <build_dir>

Static FBX files were written with FBX_SCALE_NONE in metres (pivot = Blender world
origin), so a plain FBX import round-trips them to the original Blender coordinates.
Writes <build_dir>/{court,arena,arena_lite,hoop,ball}_raw.glb and static_stats.json.
"""
import bpy
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPORT = os.path.join(ROOT, "Art", "Export")
MESHES = os.path.join(EXPORT, "Meshes")
OUTDIR = sys.argv[sys.argv.index("--") + 1]
LITE_RATIO = {"crowd": 0.45, "SM_ArenaBowl": 0.5}   # Decimate (collapse) ratios for arena_lite

with open(os.path.join(EXPORT, "Manifests", "arena.json")) as fp:
    ARENA = json.load(fp)["static_meshes_at_origin"]
with open(os.path.join(EXPORT, "Manifests", "hoop.json")) as fp:
    HOOP = json.load(fp)["parts"]

GROUPS = {
    "court": {n: (0, 0, 0) for n in ("SM_CourtFloor", "SM_ArenaFloor")},
    "arena": {n: (0, 0, 0) for n in ARENA},
    "hoop": {n: tuple(p["offset_m"]) for n, p in HOOP.items()},
    "ball": {"SM_Ball": (0, 0, 0)},
}
SUFFIX = re.compile(r"\.\d{3}$")


def tris(o):
    o.data.calc_loop_triangles()
    return len(o.data.loop_triangles)


def import_mesh(name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=os.path.join(MESHES, name + ".fbx"), colors_type="LINEAR",
                             use_custom_normals=True)
    new = [o for o in set(bpy.data.objects) - before]
    meshes = [o for o in new if o.type == "MESH"]
    for o in new:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    if len(meshes) > 1:
        bpy.ops.object.select_all(action="DESELECT")
        for o in meshes:
            o.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.join()
    o = meshes[0]
    o.name = name
    o.data.name = name
    # FBX import can leave float noise (or the axis conversion) on the object: bake it
    M = o.matrix_world.copy()
    err = max(abs(M[i][j] - (1.0 if i == j else 0.0)) for i in range(4) for j in range(4))
    assert err < 1e-4, (name, M)
    o.data.transform(M)
    o.matrix_world.identity()
    # canonical material names (FBX import adds .001 when a name repeats across files)
    for slot in o.material_slots:
        if slot.material and SUFFIX.search(slot.material.name):
            base = SUFFIX.sub("", slot.material.name)
            slot.material = bpy.data.materials.get(base) or slot.material
            slot.material.name = base
    is_crowd = name.startswith("SM_Crowd_")
    me = o.data
    if is_crowd:
        # per-fan data: UV0 = (phase, amplitude) in Blender's V-up convention. Copy it into a
        # point attribute exported verbatim as glTF "_FAN" (three.js: geometry.attributes._fan).
        uv = me.uv_layers[0].data
        vals = [0.0] * (2 * len(me.vertices))
        for li, loop in enumerate(me.loops):
            u, v = uv[li].uv
            vals[2 * loop.vertex_index] = u
            vals[2 * loop.vertex_index + 1] = v
        a = me.attributes.new("_fan", "FLOAT2", "POINT")
        a.data.foreach_set("vector", vals)
        me.color_attributes.active_color = me.color_attributes[0]
    else:
        for ca in list(me.color_attributes):
            me.color_attributes.remove(ca)
    return o


def export(objs, path, crowd=False):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(
        filepath=path, export_format="GLB", use_selection=True, export_yup=True, export_apply=True,
        export_image_format="NONE", export_materials="EXPORT", export_texcoords=True, export_normals=True,
        export_tangents=False, export_vertex_color="ACTIVE" if crowd else "NONE",
        export_all_vertex_colors=False, export_active_vertex_color_when_no_material=crowd,
        export_attributes=crowd, export_animations=False, export_skins=False, export_morph=False,
        export_lights=False, export_cameras=False, export_extras=False)


stats = {}
for group, parts in GROUPS.items():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    objs = []
    for name, offset in parts.items():
        o = import_mesh(name)
        o.location = offset          # pivot stays in the mesh; node is translated (hoop rim/net)
        objs.append(o)
        lo = [min((o.matrix_world @ v.co)[i] for v in o.data.vertices) for i in range(3)]
        hi = [max((o.matrix_world @ v.co)[i] for v in o.data.vertices) for i in range(3)]
        stats.setdefault(group, {})[name] = {
            "tris": tris(o), "verts": len(o.data.vertices),
            "materials": [s.material.name for s in o.material_slots if s.material],
            "node_offset_blender_m": list(offset), "bbox_blender_m": [lo, hi],
            "has_fan_attr": "_fan" in o.data.attributes}
    export(objs, os.path.join(OUTDIR, group + "_raw.glb"), crowd=(group == "arena"))
    if group == "arena":
        # low-end variant: collapse-decimate the bowl (seats) and every crowd mesh
        for o in objs:
            r = LITE_RATIO["crowd"] if o.name.startswith("SM_Crowd_") else LITE_RATIO.get(o.name)
            if r:
                m = o.modifiers.new("Lite", "DECIMATE")
                m.decimate_type = "COLLAPSE"
                m.ratio = r
                m.use_collapse_triangulate = False
                m.delimit = {"MATERIAL"}
        export(objs, os.path.join(OUTDIR, "arena_lite_raw.glb"), crowd=True)
        dg = bpy.context.evaluated_depsgraph_get()
        lite = {}
        for o in objs:
            me = o.evaluated_get(dg).to_mesh()
            me.calc_loop_triangles()
            lite[o.name] = len(me.loop_triangles)
            o.evaluated_get(dg).to_mesh_clear()
        stats["arena_lite"] = lite

with open(os.path.join(OUTDIR, "static_stats.json"), "w") as fp:
    json.dump(stats, fp, indent=1)
print("WEB_STATIC_OK")
