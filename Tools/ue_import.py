"""HEAT CHECK - Unreal import pipeline.

Imports everything produced by the Blender/audio generators in Art/Export into
/Game/HeatCheck, builds the master materials + material instances from the JSON
material manifests, and creates the /Game/Maps/Arena map.

Run (headless):
  UnrealEditor HeatCheck.uproject -run=pythonscript -script=Tools/ue_import.py -unattended -nullrhi
Select steps with the env var HC_STEPS (comma list of: textures,materials,static,skeletal,anims,official,audio,audiomix,map).
A report is written to Saved/ue_import_report.txt.
"""

import glob
import json
import os
import traceback

import unreal

PROJECT = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
ART = os.path.join(PROJECT, "Art", "Export")
REPORT = os.path.join(PROJECT, "Saved", "ue_import_report.txt")
os.makedirs(os.path.dirname(REPORT), exist_ok=True)
_rep = open(REPORT, "w")


def log(*a):
    _rep.write(" ".join(str(x) for x in a) + "\n")
    _rep.flush()


unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX 0")
AT = unreal.AssetToolsHelpers.get_asset_tools()
MEL = unreal.MaterialEditingLibrary
EAL = unreal.EditorAssetLibrary

BASE = "/Game/HeatCheck"
D_MESH = BASE + "/Meshes"
D_CHAR = BASE + "/Characters"
D_ANIM = BASE + "/Anims"
D_MAT = BASE + "/Materials"
D_TEX = BASE + "/Textures"
D_UI = BASE + "/UI"
D_AUDIO = BASE + "/Audio"

EMISSIVE_SCALE = float(os.environ.get("HC_EMISSIVE_SCALE", "0.35"))
STEPS = [s.strip() for s in os.environ.get("HC_STEPS", "textures,materials,static,skeletal,anims,official,audio,map").split(",") if s.strip()]


def asset_path(folder, name):
    return "%s/%s.%s" % (folder, name, name)


def load(folder, name):
    p = asset_path(folder, name)
    return unreal.load_asset(p) if EAL.does_asset_exist(p) else None


def import_file(filename, dest, options=None, name=None):
    t = unreal.AssetImportTask()
    t.filename = filename
    t.destination_path = dest
    t.automated = True
    t.save = True
    t.replace_existing = True
    if name:
        t.destination_name = name
    if options is not None:
        t.options = options
    AT.import_asset_tasks([t])
    paths = list(t.imported_object_paths)
    if not paths:
        log("IMPORT FAILED", filename)
    return paths


# ---------------------------------------------------------------------------
# Textures
# ---------------------------------------------------------------------------

def import_textures():
    for f in sorted(glob.glob(os.path.join(ART, "Textures", "*.png"))):
        name = os.path.splitext(os.path.basename(f))[0]
        import_file(f, D_TEX, name=name)
        tex = load(D_TEX, name)
        if tex:
            if name.startswith(("T_Flame", "T_Glow", "T_Spark", "T_Smoke")):
                tex.set_editor_property("srgb", True)
            EAL.save_loaded_asset(tex)
            log("TEX", name, tex.blueprint_get_size_x(), tex.blueprint_get_size_y())
    for f in sorted(glob.glob(os.path.join(ART, "UI", "*.png"))):
        name = os.path.splitext(os.path.basename(f))[0]
        import_file(f, D_UI, name=name)
        tex = load(D_UI, name)
        if tex:
            tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_EDITOR_ICON)
            tex.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_UI)
            tex.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
            tex.set_editor_property("never_stream", True)
            EAL.save_loaded_asset(tex)
            log("UI", name)


# ---------------------------------------------------------------------------
# Master materials
# Existing masters are kept (editing graphs in place can trip engine asserts);
# list names in HC_REBUILD_MASTERS (or ALL) to delete + rebuild them.
# ---------------------------------------------------------------------------
REBUILD = set(x.strip() for x in os.environ.get("HC_REBUILD_MASTERS", "").split(",") if x.strip())
MASTER_BUILDERS = []


def master(key, name):
    def deco(fn):
        MASTER_BUILDERS.append((key, name, fn))
        return fn
    return deco


def X(mat, cls, x, y, **props):
    e = MEL.create_material_expression(mat, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def vparam(mat, name, default, x, y, group="Params"):
    return X(mat, unreal.MaterialExpressionVectorParameter, x, y, parameter_name=name,
             default_value=unreal.LinearColor(*default), group=group)


def sparam(mat, name, default, x, y, group="Params"):
    return X(mat, unreal.MaterialExpressionScalarParameter, x, y, parameter_name=name,
             default_value=default, group=group)


def mul(mat, a, b, x, y, ao="", bo=""):
    e = X(mat, unreal.MaterialExpressionMultiply, x, y)
    MEL.connect_material_expressions(a, ao, e, "A")
    MEL.connect_material_expressions(b, bo, e, "B")
    return e


def add(mat, a, b, x, y, ao="", bo=""):
    e = X(mat, unreal.MaterialExpressionAdd, x, y)
    MEL.connect_material_expressions(a, ao, e, "A")
    MEL.connect_material_expressions(b, bo, e, "B")
    return e


def const(mat, v, x, y):
    return X(mat, unreal.MaterialExpressionConstant, x, y, r=v)


def out(e, prop, o=""):
    MEL.connect_material_property(e, o, prop)


P = unreal.MaterialProperty


def finish(mat):
    MEL.layout_material_expressions(mat)
    MEL.recompile_material(mat)
    EAL.save_loaded_asset(mat)
    log("MASTER", mat.get_name())


def white_tex():
    return unreal.load_asset("/Engine/EngineResources/WhiteSquareTexture.WhiteSquareTexture")


def ensure_mpc():
    mpc_path = asset_path(D_MAT, "MPC_HeatCheck")
    if EAL.does_asset_exist(mpc_path):
        mpc = unreal.load_asset(mpc_path)
    else:
        mpc = AT.create_asset("MPC_HeatCheck", D_MAT, unreal.MaterialParameterCollection,
                              unreal.MaterialParameterCollectionFactoryNew())
    if len(mpc.get_editor_property("scalar_parameters")) < 2:
        sps = []
        for pname, dv in (("CrowdExcitement", 0.0), ("ArenaFlash", 0.0)):
            sp = unreal.CollectionScalarParameter()
            sp.set_editor_property("parameter_name", pname)
            sp.set_editor_property("default_value", dv)
            sps.append(sp)
        mpc.set_editor_property("scalar_parameters", sps)
        EAL.save_loaded_asset(mpc)
    return mpc


@master("opaque", "M_HC_Opaque")
def _m_opaque(m):
    tc = X(m, unreal.MaterialExpressionTextureCoordinate, -1200, 0)
    til = vparam(m, "Tiling", (1, 1, 0, 0), -1200, 150)
    msk = X(m, unreal.MaterialExpressionComponentMask, -1000, 150, r=True, g=True, b=False, a=False)
    MEL.connect_material_expressions(til, "", msk, "")
    uv = mul(m, tc, msk, -800, 50)
    tex = X(m, unreal.MaterialExpressionTextureSampleParameter2D, -600, 0, parameter_name="BaseTexture", texture=white_tex())
    MEL.connect_material_expressions(uv, "", tex, "UVs")
    col = vparam(m, "BaseColor", (1, 1, 1, 1), -600, 300)
    out(mul(m, tex, col, -300, 0, "RGB", ""), P.MP_BASE_COLOR)
    out(sparam(m, "Roughness", 0.5, -300, 200), P.MP_ROUGHNESS)
    out(sparam(m, "Metallic", 0.0, -300, 300), P.MP_METALLIC)
    out(sparam(m, "Specular", 0.5, -300, 400), P.MP_SPECULAR)
    ec = vparam(m, "EmissiveColor", (0, 0, 0, 1), -600, 500)
    es = sparam(m, "EmissiveStrength", 0.0, -600, 650)
    out(mul(m, ec, es, -300, 550), P.MP_EMISSIVE_COLOR)


@master("masked", "M_HC_Masked")
def _m_masked(m):
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    m.set_editor_property("two_sided", True)
    tc = X(m, unreal.MaterialExpressionTextureCoordinate, -1000, 0)
    tex = X(m, unreal.MaterialExpressionTextureSampleParameter2D, -700, 0, parameter_name="BaseTexture", texture=white_tex())
    MEL.connect_material_expressions(tc, "", tex, "UVs")
    col = vparam(m, "BaseColor", (1, 1, 1, 1), -700, 300)
    out(mul(m, tex, col, -300, 0, "RGB", ""), P.MP_BASE_COLOR)
    out(tex, P.MP_OPACITY_MASK, "A")
    out(sparam(m, "Roughness", 0.6, -300, 200), P.MP_ROUGHNESS)


@master("vertexcolor", "M_HC_VertexColor")
def _m_vertexcolor(m):
    vc = X(m, unreal.MaterialExpressionVertexColor, -700, 0)
    col = vparam(m, "BaseColor", (1, 1, 1, 1), -700, 200)
    out(mul(m, vc, col, -300, 0, "", ""), P.MP_BASE_COLOR)
    out(sparam(m, "Roughness", 0.7, -300, 200), P.MP_ROUGHNESS)
    out(sparam(m, "Metallic", 0.0, -300, 300), P.MP_METALLIC)


@master("character", "M_HC_Character")
def _m_character(m):
    m.set_editor_property("used_with_skeletal_mesh", True)
    col = vparam(m, "BaseColor", (0.8, 0.8, 0.8, 1), -700, 0)
    out(col, P.MP_BASE_COLOR)
    out(sparam(m, "Roughness", 0.6, -300, 150), P.MP_ROUGHNESS)
    out(sparam(m, "Metallic", 0.0, -300, 250), P.MP_METALLIC)
    out(sparam(m, "Specular", 0.5, -300, 350), P.MP_SPECULAR)
    fr = X(m, unreal.MaterialExpressionFresnel, -900, 500, exponent=3.0, base_reflect_fraction=0.0)
    rc = vparam(m, "RimColor", (1.0, 0.45, 0.08, 1), -900, 650)
    rs = sparam(m, "RimStrength", 0.0, -900, 800)
    fc = vparam(m, "FlashColor", (1, 1, 1, 1), -900, 950)
    fs = sparam(m, "FlashStrength", 0.0, -900, 1100)
    rim = mul(m, mul(m, fr, rc, -600, 550), rs, -400, 600)
    flash = mul(m, fc, fs, -600, 1000)
    out(add(m, rim, flash, -200, 700), P.MP_EMISSIVE_COLOR)


@master("glass", "M_HC_Glass")
def _m_glass(m):
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    m.set_editor_property("two_sided", True)
    try:
        m.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_SURFACE)
    except Exception as ex:
        log("glass lighting mode", ex)
    out(vparam(m, "BaseColor", (0.85, 0.93, 1.0, 1), -500, 0), P.MP_BASE_COLOR)
    out(sparam(m, "Opacity", 0.2, -500, 200), P.MP_OPACITY)
    out(sparam(m, "Roughness", 0.05, -500, 300), P.MP_ROUGHNESS)
    out(const(m, 1.0, -500, 400), P.MP_SPECULAR)


@master("emissive", "M_HC_Emissive")
def _m_emissive(m):
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    tc = X(m, unreal.MaterialExpressionTextureCoordinate, -1300, 0)
    tm = X(m, unreal.MaterialExpressionTime, -1300, 150)
    pu = sparam(m, "PanU", 0.0, -1300, 250)
    pv = sparam(m, "PanV", 0.0, -1300, 350)
    ap = X(m, unreal.MaterialExpressionAppendVector, -1100, 300)
    MEL.connect_material_expressions(pu, "", ap, "A")
    MEL.connect_material_expressions(pv, "", ap, "B")
    uv = add(m, tc, mul(m, tm, ap, -950, 200), -800, 50)
    tex = X(m, unreal.MaterialExpressionTextureSampleParameter2D, -600, 0, parameter_name="BaseTexture", texture=white_tex())
    MEL.connect_material_expressions(uv, "", tex, "UVs")
    col = vparam(m, "BaseColor", (1, 1, 1, 1), -600, 300)
    st = sparam(m, "EmissiveStrength", 1.0, -600, 450)
    out(mul(m, mul(m, tex, col, -350, 0, "RGB", ""), st, -150, 100), P.MP_EMISSIVE_COLOR)


@master("crowd", "M_HC_Crowd")
def _m_crowd(m):
    mpc = ensure_mpc()
    vc = X(m, unreal.MaterialExpressionVertexColor, -600, -200)
    out(vc, P.MP_BASE_COLOR)
    out(const(m, 0.85, -300, -50), P.MP_ROUGHNESS)
    tc = X(m, unreal.MaterialExpressionTextureCoordinate, -1600, 200)
    ph = X(m, unreal.MaterialExpressionComponentMask, -1400, 150, r=True, g=False, b=False, a=False)
    MEL.connect_material_expressions(tc, "", ph, "")
    amv = X(m, unreal.MaterialExpressionComponentMask, -1500, 300, r=False, g=True, b=False, a=False)
    MEL.connect_material_expressions(tc, "", amv, "")
    am = X(m, unreal.MaterialExpressionOneMinus, -1400, 300)   # FBX import flips V
    MEL.connect_material_expressions(amv, "", am, "")
    ex = X(m, unreal.MaterialExpressionCollectionParameter, -1600, 450, collection=mpc, parameter_name="CrowdExcitement")
    tm = X(m, unreal.MaterialExpressionTime, -1600, 50)
    freq = add(m, mul(m, ex, const(m, 1.6, -1500, 600), -1350, 500), const(m, 0.9, -1350, 650), -1200, 550)
    arg = add(m, mul(m, tm, freq, -1100, 100), ph, -950, 150)
    sn = X(m, unreal.MaterialExpressionSine, -800, 150, period=1.0)
    MEL.connect_material_expressions(arg, "", sn, "")
    ab = X(m, unreal.MaterialExpressionAbs, -650, 150)
    MEL.connect_material_expressions(sn, "", ab, "")
    height = mul(m, mul(m, ab, am, -500, 200), add(m, const(m, 3.0, -650, 400), mul(m, ex, const(m, 24.0, -800, 500), -650, 500), -500, 400), -350, 250)
    up = X(m, unreal.MaterialExpressionConstant3Vector, -350, 450, constant=unreal.LinearColor(0, 0, 1, 1))
    out(mul(m, up, height, -150, 300), P.MP_WORLD_POSITION_OFFSET)


@master("fxadditive", "M_HC_FXAdditive")
def _m_fx(m):
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_ADDITIVE)
    m.set_editor_property("two_sided", True)
    m.set_editor_property("used_with_instanced_static_meshes", True)
    tc = X(m, unreal.MaterialExpressionTextureCoordinate, -1100, 0)
    tex = X(m, unreal.MaterialExpressionTextureSampleParameter2D, -900, 0, parameter_name="SpriteTexture", texture=white_tex())
    MEL.connect_material_expressions(tc, "", tex, "UVs")
    cds = [X(m, unreal.MaterialExpressionPerInstanceCustomData, -1100, 250 + i * 120, data_index=i) for i in range(4)]
    rg = X(m, unreal.MaterialExpressionAppendVector, -900, 300)
    MEL.connect_material_expressions(cds[0], "", rg, "A")
    MEL.connect_material_expressions(cds[1], "", rg, "B")
    rgb = X(m, unreal.MaterialExpressionAppendVector, -750, 330)
    MEL.connect_material_expressions(rg, "", rgb, "A")
    MEL.connect_material_expressions(cds[2], "", rgb, "B")
    inten = sparam(m, "Intensity", 4.0, -750, 600)
    c1 = mul(m, tex, rgb, -550, 100, "RGB", "")
    c2 = mul(m, c1, cds[3], -400, 200)
    c3 = mul(m, c2, tex, -250, 250, "", "A")
    out(mul(m, c3, inten, -100, 300), P.MP_EMISSIVE_COLOR)


@master("ring", "M_HC_Ring")
def _m_ring(m):
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    tc = X(m, unreal.MaterialExpressionTextureCoordinate, -1300, 0)
    c2 = X(m, unreal.MaterialExpressionConstant2Vector, -1300, 150, r=0.5, g=0.5)
    dist = X(m, unreal.MaterialExpressionDistance, -1100, 50)
    MEL.connect_material_expressions(tc, "", dist, "A")
    MEL.connect_material_expressions(c2, "", dist, "B")
    d2 = mul(m, dist, const(m, 2.0, -1100, 200), -950, 100)
    inner = sparam(m, "Inner", 0.72, -1100, 300)
    outer = sparam(m, "Outer", 0.95, -1100, 400)
    sub1 = X(m, unreal.MaterialExpressionSubtract, -800, 150)
    MEL.connect_material_expressions(d2, "", sub1, "A")
    MEL.connect_material_expressions(inner, "", sub1, "B")
    sub2 = X(m, unreal.MaterialExpressionSubtract, -800, 300)
    MEL.connect_material_expressions(outer, "", sub2, "A")
    MEL.connect_material_expressions(d2, "", sub2, "B")
    s1 = X(m, unreal.MaterialExpressionSaturate, -500, 150)
    MEL.connect_material_expressions(mul(m, sub1, const(m, 25.0, -800, 450), -650, 150), "", s1, "")
    s2 = X(m, unreal.MaterialExpressionSaturate, -500, 300)
    MEL.connect_material_expressions(mul(m, sub2, const(m, 25.0, -800, 550), -650, 300), "", s2, "")
    ring = mul(m, s1, s2, -350, 200)
    fill = sparam(m, "Fill", 0.12, -500, 450)
    sub3 = X(m, unreal.MaterialExpressionSubtract, -650, 600)
    MEL.connect_material_expressions(const(m, 1.0, -800, 650), "", sub3, "A")
    MEL.connect_material_expressions(d2, "", sub3, "B")
    s3 = X(m, unreal.MaterialExpressionSaturate, -500, 600)
    MEL.connect_material_expressions(sub3, "", s3, "")
    fillm = mul(m, s3, fill, -350, 550)
    alpha = sparam(m, "Alpha", 0.85, -350, 700)
    mx = X(m, unreal.MaterialExpressionMax, -200, 350)
    MEL.connect_material_expressions(ring, "", mx, "A")
    MEL.connect_material_expressions(fillm, "", mx, "B")
    out(mul(m, mx, alpha, -50, 400), P.MP_OPACITY)
    col = vparam(m, "Color", (1, 0.5, 0.1, 1), -350, 850)
    out(mul(m, col, sparam(m, "Intensity", 2.0, -350, 1000), -100, 900), P.MP_EMISSIVE_COLOR)


def build_masters():
    ensure_mpc()
    masters = {}
    for key, name, fn in MASTER_BUILDERS:
        existing = load(D_MAT, name)
        if existing is not None and name not in REBUILD and "ALL" not in REBUILD:
            masters[key] = existing
            continue
        if existing is not None:
            EAL.delete_asset(asset_path(D_MAT, name))
        m = AT.create_asset(name, D_MAT, unreal.Material, unreal.MaterialFactoryNew())
        fn(m)
        finish(m)
        masters[key] = m
    return masters


# ---------------------------------------------------------------------------
# Material instances from the JSON manifests
# ---------------------------------------------------------------------------

def lc(c, a=1.0):
    c = list(c) + [a] * (4 - len(c))
    return unreal.LinearColor(c[0], c[1], c[2], c[3])


def build_instances(masters):
    defs = {}
    for f in sorted(glob.glob(os.path.join(ART, "Materials", "*.json"))):
        with open(f) as fp:
            defs.update(json.load(fp))
    out_map = {}
    for name, d in defs.items():
        shader = d.get("shader", "opaque")
        parent = masters.get(shader, masters["opaque"])
        mi = load(D_MAT, name)
        if mi is None:
            mi = AT.create_asset(name, D_MAT, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(mi, parent)
        col = d.get("color", [1, 1, 1])
        if shader == "crowd":
            pass
        elif shader == "glass":
            MEL.set_material_instance_vector_parameter_value(mi, "BaseColor", lc(col))
            MEL.set_material_instance_scalar_parameter_value(mi, "Opacity", float(d.get("opacity", 0.2)))
            MEL.set_material_instance_scalar_parameter_value(mi, "Roughness", float(d.get("roughness", 0.05)))
        elif shader == "emissive":
            MEL.set_material_instance_vector_parameter_value(mi, "BaseColor", lc(col))
            MEL.set_material_instance_scalar_parameter_value(mi, "EmissiveStrength", float(d.get("emissive_strength", 1.0)) * EMISSIVE_SCALE)
            MEL.set_material_instance_scalar_parameter_value(mi, "PanU", float(d.get("pan_u", 0.0)))
            MEL.set_material_instance_scalar_parameter_value(mi, "PanV", float(d.get("pan_v", 0.0)))
        else:
            MEL.set_material_instance_vector_parameter_value(mi, "BaseColor", lc(col))
            MEL.set_material_instance_scalar_parameter_value(mi, "Roughness", float(d.get("roughness", 0.5)))
            if shader in ("opaque", "character", "vertexcolor"):
                MEL.set_material_instance_scalar_parameter_value(mi, "Metallic", float(d.get("metallic", 0.0)))
            if shader in ("opaque", "character"):
                MEL.set_material_instance_scalar_parameter_value(mi, "Specular", float(d.get("specular", 0.5)))
            if shader == "opaque":
                til = d.get("tiling", [1, 1])
                MEL.set_material_instance_vector_parameter_value(mi, "Tiling", unreal.LinearColor(til[0], til[1], 0, 0))
                if "emissive" in d or "emissive_strength" in d:
                    MEL.set_material_instance_vector_parameter_value(mi, "EmissiveColor", lc(d.get("emissive", col)))
                    MEL.set_material_instance_scalar_parameter_value(mi, "EmissiveStrength", float(d.get("emissive_strength", 1.0)))
        tex_name = d.get("texture")
        if tex_name and shader in ("opaque", "emissive", "masked"):
            tex = load(D_TEX, tex_name) or load(D_UI, tex_name)
            if tex:
                MEL.set_material_instance_texture_parameter_value(mi, "BaseTexture", tex)
            else:
                log("MISSING TEXTURE", tex_name, "for", name)
        MEL.update_material_instance(mi)
        EAL.save_loaded_asset(mi)
        out_map[name] = mi
    # extra instances used directly by gameplay code
    extra = {
        "MI_FXFire": ("fxadditive", {"SpriteTexture": "T_Flame"}, {"Intensity": 6.0}),
        "MI_FXGlow": ("fxadditive", {"SpriteTexture": "T_Glow"}, {"Intensity": 4.0}),
        "MI_FXSpark": ("fxadditive", {"SpriteTexture": "T_Spark"}, {"Intensity": 8.0}),
        "MI_PlayerRing": ("ring", {}, {}),
    }
    for name, (shader, texs, scalars) in extra.items():
        mi = load(D_MAT, name) or AT.create_asset(name, D_MAT, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(mi, masters[shader])
        for p, tname in texs.items():
            tex = load(D_TEX, tname)
            if tex:
                MEL.set_material_instance_texture_parameter_value(mi, p, tex)
            else:
                log("MISSING FX TEXTURE", tname)
        for p, v in scalars.items():
            MEL.set_material_instance_scalar_parameter_value(mi, p, v)
        MEL.update_material_instance(mi)
        EAL.save_loaded_asset(mi)
        out_map[name] = mi
    log("INSTANCES", len(out_map))
    return out_map


def mat_for_slot(slot_name):
    name = str(slot_name)
    mi = load(D_MAT, name)
    if mi is None:
        log("NO MATERIAL FOR SLOT", name)
    return mi


# ---------------------------------------------------------------------------
# Meshes
# ---------------------------------------------------------------------------

def static_options():
    o = unreal.FbxImportUI()
    o.import_mesh = True
    o.import_as_skeletal = False
    o.import_materials = False
    o.import_textures = False
    o.import_animations = False
    o.mesh_type_to_import = unreal.FBXImportType.FBXIT_STATIC_MESH
    d = o.static_mesh_import_data
    d.set_editor_property("combine_meshes", True)
    d.set_editor_property("auto_generate_collision", False)
    d.set_editor_property("generate_lightmap_u_vs", False)
    d.set_editor_property("normal_import_method", unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS)
    d.set_editor_property("remove_degenerates", True)
    d.set_editor_property("vertex_color_import_option", unreal.VertexColorImportOption.REPLACE)
    return o


def import_static():
    for f in sorted(glob.glob(os.path.join(ART, "Meshes", "SM_*.fbx"))):
        name = os.path.splitext(os.path.basename(f))[0]
        import_file(f, D_MESH, static_options(), name=name)
        sm = load(D_MESH, name)
        if not sm:
            continue
        mats = sm.get_editor_property("static_materials")
        for i, sm_mat in enumerate(mats):
            mi = mat_for_slot(sm_mat.get_editor_property("material_slot_name"))
            if mi:
                sm.set_material(i, mi)
        EAL.save_loaded_asset(sm)
        b = sm.get_bounds()
        log("STATIC", name, "slots", [str(x.get_editor_property("material_slot_name")) for x in mats],
            "origin", b.origin, "extent", b.box_extent)


def skeletal_options(skeleton=None):
    o = unreal.FbxImportUI()
    o.import_mesh = True
    o.import_as_skeletal = True
    o.import_materials = False
    o.import_textures = False
    o.import_animations = False
    o.create_physics_asset = False
    o.mesh_type_to_import = unreal.FBXImportType.FBXIT_SKELETAL_MESH
    if skeleton:
        o.skeleton = skeleton
    d = o.skeletal_mesh_import_data
    d.set_editor_property("normal_import_method", unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS)
    d.set_editor_property("import_morph_targets", False)
    d.set_editor_property("update_skeleton_reference_pose", False)
    return o


def assign_skeletal_materials(skm):
    mats = skm.get_editor_property("materials")
    new = []
    for m in mats:
        slot = m.get_editor_property("material_slot_name")
        mi = mat_for_slot(slot)
        if mi:
            m.set_editor_property("material_interface", mi)
        new.append(m)
    skm.set_editor_property("materials", new)


def import_skeletal():
    main = os.path.join(ART, "Meshes", "SK_Player.fbx")
    import_file(main, D_CHAR, skeletal_options(), name="SK_Player")
    skm = load(D_CHAR, "SK_Player")
    if not skm:
        log("SK_Player import failed")
        return
    skel = skm.get_editor_property("skeleton")
    assign_skeletal_materials(skm)
    EAL.save_loaded_asset(skm)
    EAL.save_loaded_asset(skel)   # the import task does not save the generated skeleton
    log("SKELETON", skel.get_path_name())
    pose = unreal.AnimPoseExtensions.get_reference_pose(skel)
    for bn in unreal.AnimPoseExtensions.get_bone_names(pose):
        tw = unreal.AnimPoseExtensions.get_bone_pose(pose, bn, unreal.AnimPoseSpaces.WORLD)
        log("BONE", bn, "%.1f %.1f %.1f" % (tw.translation.x, tw.translation.y, tw.translation.z))
    for f in sorted(glob.glob(os.path.join(ART, "Meshes", "SK_*.fbx"))):
        name = os.path.splitext(os.path.basename(f))[0]
        if name == "SK_Player":
            continue
        import_file(f, D_CHAR, skeletal_options(skel), name=name)
        part = load(D_CHAR, name)
        if part:
            assign_skeletal_materials(part)
            EAL.save_loaded_asset(part)
    log("SKELETAL parts done")


def import_anims():
    skel = load(D_CHAR, "SK_Player_Skeleton")
    if not skel:
        log("no skeleton for anims")
        return
    for f in sorted(glob.glob(os.path.join(ART, "Anims", "A_*.fbx"))):
        import_animation(f, skel)


def import_official():
    skel = load(D_CHAR, "SK_Player_Skeleton")
    folder = os.path.join(ART, "Official")
    import_file(os.path.join(folder, "SK_Referee.fbx"), D_CHAR, skeletal_options(skel), name="SK_Referee")
    mesh = load(D_CHAR, "SK_Referee")
    assign_skeletal_materials(mesh)
    EAL.save_loaded_asset(mesh)
    for clip in ("RefToss", "Tip"):
        import_animation(os.path.join(folder, "A_" + clip + ".fbx"), skel)


def import_animation(f, skel):
    name = os.path.splitext(os.path.basename(f))[0]
    o = unreal.FbxImportUI()
    o.import_mesh = False
    o.import_as_skeletal = True
    o.import_animations = True
    o.import_materials = False
    o.import_textures = False
    o.skeleton = skel
    o.mesh_type_to_import = unreal.FBXImportType.FBXIT_ANIMATION
    ad = o.anim_sequence_import_data
    ad.set_editor_property("animation_length", unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME)
    ad.set_editor_property("remove_redundant_keys", False)
    ad.set_editor_property("import_bone_tracks", True)
    import_file(f, D_ANIM, o, name=name)
    a = load(D_ANIM, name)
    if a:
        a.set_editor_property("enable_root_motion", False)
        EAL.save_loaded_asset(a)
        log("ANIM", name, "%.3f" % a.get_play_length())


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

def import_audio():
    man_path = os.path.join(ART, "Audio", "manifest.json")
    manifest = {}
    if os.path.exists(man_path):
        with open(man_path) as fp:
            raw = json.load(fp)
        if isinstance(raw, dict) and "files" in raw:
            raw = raw["files"]
        if isinstance(raw, list):
            for e in raw:
                n = os.path.splitext(os.path.basename(e.get("file", e.get("name", ""))))[0]
                manifest[n] = e
        elif isinstance(raw, dict):
            for k, e in raw.items():
                manifest[os.path.splitext(k)[0]] = e
    for f in sorted(glob.glob(os.path.join(ART, "Audio", "*.wav"))):
        name = os.path.splitext(os.path.basename(f))[0]
        import_file(f, D_AUDIO, name=name)
        sw = load(D_AUDIO, name)
        if not sw:
            continue
        e = manifest.get(name, {})
        loop = bool(e.get("loop", False)) or name.startswith("M_") or name.endswith("Loop")
        sw.set_editor_property("looping", loop)
        EAL.save_loaded_asset(sw)
        log("AUDIO", name, "loop" if loop else "")


def build_audio_mix():
    folder = D_AUDIO + "/Mix"

    def ensure(name, cls, factory):
        asset = load(folder, name) or AT.create_asset(name, folder, cls, factory())
        EAL.save_loaded_asset(asset)
        return asset

    ensure("Mix_Options", unreal.SoundMix, unreal.SoundMixFactory)
    classes = {key: ensure("SC_" + key, unreal.SoundClass, unreal.SoundClassFactory)
               for key in ("Effects", "Music", "Announcer", "Crowd", "Interface")}
    counts = dict.fromkeys(classes, 0)
    for path in EAL.list_assets(D_AUDIO, recursive=False, include_folder=False):
        wave = unreal.load_asset(path)
        if not isinstance(wave, unreal.SoundWave):
            continue
        name = wave.get_name()
        bus = next((bus for prefix, bus in (("M_", "Music"), ("VO_", "Announcer"),
                                            ("S_Crowd", "Crowd"), ("S_UI_", "Interface"))
                    if name.startswith(prefix)), "Effects")
        wave.set_editor_property("sound_class_object", classes[bus])
        if wave.get_editor_property("looping"):
            wave.set_editor_property("virtualization_mode", unreal.VirtualizationMode.PLAY_WHEN_SILENT)
        EAL.save_loaded_asset(wave)
        counts[bus] += 1
    log("AUDIO MIX", counts)


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

def create_map():
    path = "/Game/Maps/Arena"
    if EAL.does_asset_exist(path + ".Arena"):
        log("MAP exists")
        return
    w = AT.create_asset("Arena", "/Game/Maps", unreal.World, unreal.WorldFactory())
    EAL.save_loaded_asset(w)
    log("MAP created", w)


def main():
    log("STEPS", STEPS)
    masters = None
    for step in STEPS:
        try:
            if step == "textures":
                import_textures()
            elif step == "materials":
                masters = build_masters()
                build_instances(masters)
            elif step == "static":
                import_static()
            elif step == "skeletal":
                import_skeletal()
            elif step == "anims":
                import_anims()
            elif step == "official":
                import_official()
            elif step == "audio":
                import_audio()
                build_audio_mix()
            elif step == "audiomix":
                build_audio_mix()
            elif step == "map":
                create_map()
        except Exception:
            log("STEP FAILED", step, traceback.format_exc())
    EAL.save_directory(BASE, only_if_is_dirty=True, recursive=True)
    log("IMPORT DONE")


main()
