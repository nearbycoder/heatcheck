"""HEAT CHECK web assets: write characters/anims.json, characters/referee_anims.json and the
root manifest.json from the build stats.  python3 Tools/web/make_manifest.py <build_dir> <assets_out_dir>"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPORT = os.path.join(ROOT, "Art", "Export")
BUILD, OUT = sys.argv[1], sys.argv[2]


def J(path):
    with open(path) as fp:
        return json.load(fp)


def g2(v):
    """Blender (x, y, z) -> glTF (x, z, -y)"""
    return [round(v[0], 4), round(v[2], 4), round(-v[1], 4) + 0.0]


post = J(os.path.join(BUILD, "post_stats.json"))
pstats = J(os.path.join(BUILD, "player_stats.json"))
rstats = J(os.path.join(BUILD, "referee_stats.json"))
sstats = J(os.path.join(BUILD, "static_stats.json"))
anims = J(os.path.join(EXPORT, "Manifests", "anims.json"))
charman = J(os.path.join(EXPORT, "Manifests", "character.json"))
hoop = J(os.path.join(EXPORT, "Manifests", "hoop.json"))
court = J(os.path.join(EXPORT, "Manifests", "court.json"))
arena_man = J(os.path.join(EXPORT, "Manifests", "arena.json"))
audio = J(os.path.join(OUT, "audio", "manifest.json"))

# ---- characters/anims.json (source manifest + Tip from Blender/gen_referee.py) -------------
anims_out = dict(anims)
anims_out["Tip"] = {"frames": 24, "fps": 30, "loop": False, "events": {"reach_frame": 12},
                    "source": "Art/Export/Official/A_Tip.fbx (Blender/gen_referee.py: begin('Tip', 24, reach_frame=12))"}
os.makedirs(os.path.join(OUT, "characters"), exist_ok=True)
with open(os.path.join(OUT, "characters", "anims.json"), "w") as fp:
    json.dump(anims_out, fp, indent=2)
ref_anims = {
    "RefToss": {"frames": 45, "fps": 30, "loop": False, "events": {"release_frame": 27},
                "source": "Art/Export/Official/A_RefToss.fbx (Blender/gen_referee.py)"},
    "Idle": dict(anims["Idle"], source="player Idle clip (same skeleton)"),
}
with open(os.path.join(OUT, "characters", "referee_anims.json"), "w") as fp:
    json.dump(ref_anims, fp, indent=2)

# ---- file list --------------------------------------------------------------------------
files = []
for dp, _, fns in os.walk(OUT):
    for fn in sorted(fns):
        if fn.startswith(".") or fn == "manifest.json" and dp == OUT:
            continue
        p = os.path.join(dp, fn)
        files.append({"path": os.path.relpath(p, OUT), "bytes": os.path.getsize(p)})
files.sort(key=lambda f: f["path"])


def clip_table(stats, post_anims, manifest):
    out = {}
    for name, dur in sorted(post_anims.items()):
        c = stats["clips"][name]
        m = manifest.get(name, {})
        out[name] = {"duration_s": dur, "frames": c["frames"], "fps": 30, "loop": m.get("loop"),
                     "events": m.get("events", {}),
                     "pelvis_range_m_gltf_xyz": [round(c["pelvis_range_m"][0], 3), round(c["pelvis_range_m"][2], 3),
                                                 round(c["pelvis_range_m"][1], 3)],
                     "pelvis_net_displacement_m_gltf_xz": [round(c["pelvis_net_xy_m"][0], 3), round(-c["pelvis_net_xy_m"][1], 3) + 0.0]}
    return out


def char_entry(key, stats, manifest, extra):
    p = post[key]
    return dict({
        "file": p["file"], "bytes": p["bytes"], "compression": p["compression"],
        "tris_total": p["tris"],
        "meshes": {n: {"tris": m["tris"], "materials": m["materials"]} for n, m in sorted(p["meshes"].items())},
        "materials": sorted(p["materials"]),
        "bones": stats["bones"],
        "skeleton_root": "root (child of the 'Armature' node); every bone has scale 1, metres",
        "animations": clip_table(stats, p["animations"], manifest),
        "facing": "+Z (glTF). Blender -Y. Rotate the model so +Z points along the character's heading.",
        "up": "+Y",
        "feet_at_y": round(stats["rest_min_z_m"], 4),
        "standing_height_m": round(stats["rest_height_m"], 4),
        "max_height_with_attachments_m": round(stats["max_attachment_height_m"], 4),
        "root_motion": "none: the 'root' bone is never keyed away from the origin in any clip (in-place). "
                       "The pelvis carries the body bob/jump height; Fall ends with the pelvis 0.4 m behind "
                       "the character (glTF -Z) lying down and GetUp starts there and returns to the origin.",
    }, **extra)


player = char_entry("player", pstats, anims_out, {
    "attachments": {
        "hair": ["SK_Hair_" + n for n in ("Buzz", "Flattop", "Afro", "Braids", "Mohawk", "Curls", "Bun")],
        "beard": ["SK_Beard_Full", "SK_Beard_Goatee"],
        "accessories": ["SK_Headband", "SK_Wristbands"],
        "numbers": "SK_Num_{T,O,C}{0-9}: T = tens digit (viewer-left on the front), O = ones digit, C = centred single digit; show one T+O pair or one C",
        "jersey_text": ["SK_JerseyText_" + t for t in ("NEO", "BAY", "RRK", "FRB", "STV", "SSC")],
        "note": "all attachments are SkinnedMeshes bound to the same skeleton; show/hide by node name",
    },
    "head": {
        "bone": "head",
        "bone_head_position_m_gltf": g2(pstats["head_bone_head_m"]),
        "bone_tail_position_m_gltf": g2(pstats["head_bone_tail_m"]),
        "head_scale_baked": charman.get("head_scale"),
        "note": "head_scale (1.12) is already baked into the mesh. Big-head mode in the Unreal game sets the "
                "'head' bone scale to 1.7 (HCGameMode ApplyHeadScale(1.7)); it scales about the bone's head "
                "joint (top of the neck). Hair, beards and the headband are rigidly weighted to 'head', so they "
                "follow.",
    },
    "recolor": "team colours are applied at runtime by material name (MI_PlayerJersey, MI_PlayerShorts, ...). "
               "Base colours in the file are the defaults from Art/Export/Materials/character.json (linear).",
})
referee = char_entry("referee", rstats, ref_anims, {
    "note": "Same 25-bone skeleton as the player. Uses MI_Player* material names with the default colours; "
            "stripes are MI_PlayerSocks (white) / MI_PlayerJerseyTrim (black). Do not team-recolour it. "
            "There is no referee idle in referee.blend; 'Idle' is the player's idle clip.",
})

arena_meshes = {n: {"tris": m["tris"], "materials": m["materials"]} for n, m in sorted(post["arena"]["meshes"].items())}
lite_meshes = {n: m["tris"] for n, m in sorted(post["arena_lite"]["meshes"].items())}
crowd_doc = {
    "meshes": [n for n in arena_meshes if n.startswith("SM_Crowd_")],
    "material": "MI_Crowd (extras.shader = 'crowd')",
    "attributes": {
        "COLOR_0": "unorm8 RGBA, linear RGB per face corner (shirt/skin/hair/pants/props), alpha = 1. "
                   "three.js: geometry.attributes.color; GLTFLoader turns vertexColors on.",
        "_FAN": "float32 VEC2, identical for every vertex of one fan. x = phase 0..1, y = bounce amplitude 0..1 "
                "(seated 0.05-0.35, standing 0.45-0.8, clap 0.5-0.85, pump 0.65-0.95, arms-up 0.75-1.0). "
                "three.js: geometry.attributes._fan (GLTFLoader lower-cases custom attribute names).",
        "TEXCOORD_0": "removed (it held the same phase/amplitude with V flipped; _FAN replaces it)",
    },
    "unreal_formula": "height_m = abs(sin(2*pi*(time*(0.9 + 1.6*excitement) + phase))) * amplitude * (0.03 + 0.24*excitement); "
                      "offset world +Y (up). excitement 0..1 (idles at 0.12, 1 on big plays; AHCArena::Tick).",
    "positions": "float32 metres at identity node transforms, so a vertex-shader offset of h metres along "
                 "local +Y is h metres in the world.",
    "unreal_quality": "Unreal hides the upper-deck crowd (SM_Crowd_Upper*) at the lowest view-distance setting "
                      "and only animates it at the higher ones.",
    "stats": {k: v for k, v in arena_man.get("crowd", {}).items() if k in ("seats", "fans", "poses")},
}

manifest = {
    "generated_by": "Tools/web/build_web_assets.sh",
    "conventions": {
        "axes": "glTF 2.0, +Y up, metres. Blender (x, y, z) -> glTF (x, z, -y). Court length along X; the "
                "game camera's near sideline is glTF +Z (Blender -Y), the far sideline glTF -Z.",
        "materials": "material names are the MI_* names from Art/Export/Materials/*.json; extras.shader holds "
                     "the source shader type (opaque, character, emissive, glass, masked, crowd) and "
                     "extras.pan_u (UV units/s) is set on scrolling LED materials.",
        "emissive": "emissive materials have black base colour, emissiveFactor = colour, emissiveTexture = "
                    "texture and KHR_materials_emissive_strength = emissive_strength * 0.35 (the same factor "
                    "Unreal uses). extras.emissive_strength_authored keeps the raw value.",
        "colour_space": "base colours are linear (as authored). Textures are sRGB JPEG/PNG embedded in the GLBs.",
    },
    "compression": {
        "geometry": "EXT_meshopt_compression + KHR_mesh_quantization on characters/player.glb, "
                    "characters/referee.glb, arena/arena.glb and arena/arena_lite.glb (POSITION stays float32; "
                    "normals/uv/colour/weights are quantized). court/hoop/ball are uncompressed.",
        "three_js": "loader.setMeshoptDecoder(MeshoptDecoder) with "
                    "import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js'. "
                    "No Draco, no KTX2.",
        "extensions_used": sorted({e for p in post.values() for e in p["extensionsUsed"]}),
    },
    "characters": {"player": player, "referee": referee},
    "arena": {
        "court": {"file": post["court"]["file"], "bytes": post["court"]["bytes"], "tris": post["court"]["tris"],
                  "meshes": sorted(post["court"]["meshes"]), "texture": "T_Court 4096x2048 JPEG (embedded)",
                  "dimensions": court["court"], "court_texture": court["texture"], "mesh_extents": court["meshes"],
                  "note": "coordinates in court.json are Blender (x, y); glTF z = -y."},
        "arena": {"file": post["arena"]["file"], "bytes": post["arena"]["bytes"], "tris": post["arena"]["tris"],
                  "meshes": arena_meshes, "placement": "all nodes at the origin with identity transforms",
                  "crowd": crowd_doc},
        "arena_lite": {"file": post["arena_lite"]["file"], "bytes": post["arena_lite"]["bytes"],
                       "tris": post["arena_lite"]["tris"], "meshes": lite_meshes,
                       "note": "Blender collapse-decimate: SM_ArenaBowl 50%, every SM_Crowd_* 45%; everything else "
                               "unchanged. Same node/material names and crowd attributes."},
        "hoop": {"file": post["hoop"]["file"], "bytes": post["hoop"]["bytes"], "tris": post["hoop"]["tris"],
                 "space": "hoop-local: origin = floor point under the rim centre, court toward +X. Place one at "
                          "x=-12.725 (no rotation) and one at x=+12.725 rotated 180 deg about Y.",
                 "nodes": {n: {"translation_gltf": m["translation"],
                               "pivot": hoop["parts"][n]["pivot"]} for n, m in sorted(post["hoop"]["meshes"].items())},
                 "dimensions_m": hoop["dimensions_m"], "animatable": hoop["animatable"],
                 "note": "hoop.json values are Blender (x, y, z); glTF = (x, z, -y)."},
        "ball": {"file": post["ball"]["file"], "bytes": post["ball"]["bytes"], "tris": post["ball"]["tris"],
                 "radius_m": round((sstats["ball"]["SM_Ball"]["bbox_blender_m"][1][0]
                                    - sstats["ball"]["SM_Ball"]["bbox_blender_m"][0][0]) / 2, 4),
                 "pivot": "ball centre", "texture": "T_Ball 1024x512 JPEG (embedded)"},
    },
    "textures": {"dir": "textures/", "files": sorted(f["path"] for f in files if f["path"].startswith("textures/")),
                 "note": "loose sprites for FX (additive): T_Flame, T_Glow, T_Spark; T_ShotClock digits"},
    "ui": {"dir": "ui/", "files": sorted(f["path"] for f in files if f["path"].startswith("ui/"))},
    "audio": {"manifest": "audio/manifest.json", "count": audio["count"],
              "loops_with_ogg": [r["name"] for r in audio["files"] if r.get("ogg")]},
    "files": files,
    "total_bytes": sum(f["bytes"] for f in files),
}
with open(os.path.join(OUT, "manifest.json"), "w") as fp:
    json.dump(manifest, fp, indent=1)
print("MANIFEST_OK", len(files), "files", round(manifest["total_bytes"] / 1048576, 2), "MB")
