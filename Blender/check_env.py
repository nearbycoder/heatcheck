"""HEAT CHECK - environment export validator.

Re-imports every environment FBX in Art/Export/Meshes and checks what the Unreal importer will see:
mesh/material slot names (all must exist in Art/Export/Materials/*.json), UV0 presence, vertex colours on
crowd meshes, pivots/bounds, triangle counts, court UV orientation and texture power-of-two sizes.
Prints a table and exits with status 1 if a check fails.

Run:  blender -b --factory-startup -P Blender/check_env.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
import numpy as np  # noqa: E402

import env_helpers as eh  # noqa: E402

ENV_PREFIXES = ("SM_Court", "SM_Arena", "SM_Hoop", "SM_Backboard", "SM_Rim", "SM_Net", "SM_Ball", "SM_Crowd_",
                "SM_LedRibbon_", "SM_ScorerTable", "SM_TeamBenches", "SM_Jumbotron", "SM_LightRig", "SM_Banners")


def main():
    errors = []
    specs = eh.load_material_specs()
    files = sorted(f for f in os.listdir(eh.MESH_DIR) if f.endswith(".fbx") and f.startswith(ENV_PREFIXES))
    total = 0
    for fn in files:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=os.path.join(eh.MESH_DIR, fn))
        objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
        if len(objs) != 1:
            errors.append("%s: expected 1 mesh object, got %d" % (fn, len(objs)))
            if not objs:
                continue
        o = objs[0]
        me = o.data
        lt = np.empty(len(me.polygons), np.int32)
        me.polygons.foreach_get("loop_total", lt)
        tris = int((lt - 2).sum())
        total += tris
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        M = np.array(o.matrix_world, np.float32)
        co = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
        lo, hi = co.min(0), co.max(0)
        mats = [m.name.split(".")[0] for m in me.materials]
        uvs = [u.name for u in me.uv_layers]
        cols = [c.name for c in me.color_attributes]
        for m in mats:
            if m not in specs:
                errors.append("%s: material slot %s has no JSON spec" % (fn, m))
            if not m.startswith("MI_"):
                errors.append("%s: material slot %s lacks MI_ prefix" % (fn, m))
        if not uvs:
            errors.append("%s: no UV0" % fn)
        if fn.startswith("SM_Crowd_"):
            if not cols:
                errors.append("%s: crowd mesh without vertex colours" % fn)
            uv = np.empty(len(me.loops) * 2, np.float32)
            me.uv_layers[0].data.foreach_get("uv", uv)
            uv = uv.reshape(-1, 2)
            if uv.min() < -1e-4 or uv.max() > 1 + 1e-4:
                errors.append("%s: crowd UV0 outside 0..1" % fn)
        if fn == "SM_CourtFloor.fbx":
            uv = np.empty(len(me.loops) * 2, np.float32)
            me.uv_layers[0].data.foreach_get("uv", uv)
            uv = uv.reshape(-1, 2)
            vi = np.empty(len(me.loops), np.int32)
            me.loops.foreach_get("vertex_index", vi)
            p = co[vi]
            exp = np.stack([(p[:, 0] + 17) / 34, (p[:, 1] + 8.5) / 17], 1)
            if np.abs(uv - exp).max() > 1e-3:
                errors.append("SM_CourtFloor: UVs do not follow u=(x+17)/34, v=(y+8.5)/17")
        print("%-28s tris=%7d  bounds=[%7.2f %7.2f %7.2f]..[%7.2f %7.2f %7.2f]  uv=%s col=%s mats=%s"
              % (fn[:-4], tris, lo[0], lo[1], lo[2], hi[0], hi[1], hi[2], uvs, cols, mats))
    print("TOTAL environment tris:", total)
    for d in (eh.TEX_DIR, eh.UI_DIR):
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".png"):
                continue
            img = bpy.data.images.load(os.path.join(d, fn))
            w, h = img.size
            pot = (w & (w - 1)) == 0 and (h & (h - 1)) == 0
            print("  %-26s %5dx%-5d ch=%d %s" % (fn, w, h, img.channels, "" if pot else "(not power of two)"))
            if d == eh.TEX_DIR and not pot:
                errors.append("%s is not power-of-two" % fn)
    for spec_name, spec in specs.items():
        t = spec.get("texture")
        if t and not os.path.exists(os.path.join(eh.TEX_DIR, t + ".png")):
            errors.append("%s references missing texture %s" % (spec_name, t))
    if errors:
        print("CHECK FAILED:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print("CHECK OK")


if __name__ == "__main__":
    main()
