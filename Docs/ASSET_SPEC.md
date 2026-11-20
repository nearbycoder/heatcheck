# HEAT CHECK — Asset Pipeline Spec

HEAT CHECK is an original 2-on-2 arcade basketball game (Unreal Engine 5.9 C++ + Blender 5.3).
Every 3D asset and texture is generated procedurally by Python scripts in `Blender/`, exported to
`Art/Export/`, then imported into Unreal by `Tools/ue_import.py`.

All branding, team names, player names, logos and announcer lines are ORIGINAL. Do not reference any
real league, team, player, or existing video game (no "NBA", no "Jam", no real team names/logos).

## Tools

* Blender 5.3: `/opt/homebrew/bin/blender -b --factory-startup -P Blender/<script>.py`
  (layered Actions only — `action.fcurves` does not exist; Eevee engine id is `BLENDER_EEVEE`).
* Shared helpers: `Blender/hc_common.py` (read-only for helpers/agents; add your own helpers in your own module).
* Fonts usable for rendered text: `/System/Library/Fonts/Supplemental/Impact.ttf`,
  `.../DIN Condensed Bold.ttf`, `.../Arial Black.ttf`, `.../Futura.ttc`.

## Units, axes, pivots (IMPORTANT)

* Blender: meters, Z up. Unreal: centimeters, Z up. FBX import maps Blender `(x, y, z)` m →
  Unreal `(100x, -100y, 100z)` cm (Y is mirrored).
* **Static meshes** are exported with `hc.export_static_fbx()` (FBX_SCALE_NONE). Unreal bakes object
  transforms, so **the static mesh pivot is the Blender WORLD ORIGIN**, not the object origin.
  To give a mesh a specific pivot, translate the geometry so the pivot sits at (0,0,0) before export.
* **Camera convention**: the in-game camera sits on the Blender **-Y** side of the court (Blender
  "front" view), elevated, looking toward +Y. Screen-right = +X. Anything with text or a "front"
  (floor text, LED boards, banners, logos, scorer's table) must read correctly from the Blender front
  view. The **far sideline** (background of the game view) is Blender **+Y**; the near sideline is -Y.
* Characters face Blender -Y.

## Court dimensions (meters, Blender coords, center court at origin, floor z = 0)

| Item | Value |
|---|---|
| Court boundary (outer edge of lines) | x ∈ [-14.325, 14.325], y ∈ [-7.62, 7.62] |
| Line width | 0.05 (drawn inside the boundary) |
| Rim centers | (±12.725, 0, 3.05) — 1.60 m in from each baseline |
| Rim inner radius / tube radius | 0.2286 / 0.010 |
| Backboard front face plane | x = ±13.105 (0.38 behind rim center); glass 1.83 wide (y ±0.915), z ∈ [2.90, 3.97], 0.03 thick |
| Backboard inner rectangle | 0.59 × 0.45, bottom edge at z = 3.05, centered on y = 0 |
| Three-point arc | radius 7.24 around floor point under rim (±12.725, 0) |
| Three-point corners | straight lines at y = ±6.70 from baseline to x = ±9.981 |
| Key / paint | y ∈ [-2.44, 2.44], from baseline to free-throw line at x = ±8.535 |
| Free-throw circle | radius 1.83 centered (±8.535, 0) (outer half solid, inner half dashed) |
| Restricted area arc | radius 1.22 around floor point under rim |
| Center circle | radius 1.83 (plus inner circle 0.61) |
| Ball radius | 0.12 |

## Material contract

Material slot names in Blender ARE the Unreal material-instance names (prefix `MI_`), unique
project-wide. Every generator writes a JSON file `Art/Export/Materials/<generator>.json`:

```json
{
  "MI_Court":     {"shader": "opaque", "texture": "T_Court", "color": [1,1,1], "roughness": 0.22, "metallic": 0.0, "specular": 0.6},
  "MI_RimOrange": {"shader": "opaque", "color": [1.0, 0.25, 0.03], "roughness": 0.35, "metallic": 0.7},
  "MI_Glass":     {"shader": "glass", "color": [0.85, 0.93, 1.0], "opacity": 0.18, "roughness": 0.03},
  "MI_LedRibbon": {"shader": "emissive", "texture": "T_LedScroll", "color": [1,1,1], "emissive_strength": 6.0, "pan_u": 0.04},
  "MI_Crowd":     {"shader": "crowd"}
}
```

* Colors are **linear** RGB 0..1 (same numbers you would type into Blender's Base Color).
* `shader` is one of:
  * `opaque` — BaseColor = color × texture(UV0 × `tiling` [u,v], default [1,1]); `roughness`, `metallic`,
    `specular`; optional `emissive` [r,g,b] and `emissive_strength`.
  * `vertexcolor` — opaque, BaseColor = vertex color × color.
  * `glass` — translucent; `color`, `opacity`, `roughness`.
  * `emissive` — unlit; Emissive = color × texture × `emissive_strength`; optional `pan_u`/`pan_v`
    (UV units per second, for scrolling LED boards).
  * `masked` — like opaque but texture alpha < 0.5 is cut out (requires `texture` with alpha).
  * `crowd` — crowd fans: BaseColor = vertex color; vertices bob with a per-fan phase read from
    **UV0.x** (0..1) and per-fan bounce amplitude from **UV0.y** (0..1). All verts of one fan share
    the same UV0.
* Textures: PNG in `Art/Export/Textures/T_<Name>.png`. Power-of-two sizes. Referenced by name
  (without extension) from the JSON.

## File naming

* `Art/Export/Meshes/SM_<Name>.fbx` static meshes, `SK_<Name>.fbx` skeletal meshes.
* `Art/Export/Anims/A_<Name>.fbx` animations (player skeleton).
* `Art/Export/Textures/T_<Name>.png`, UI images `Art/Export/UI/UI_<Name>.png` (sRGB, with alpha).
* `Art/Export/Audio/S_<Name>.wav` sound effects, `VO_<Name>.wav` announcer, `M_<Name>.wav` music.
* `Art/Previews/*.png` preview renders used for visual verification (not imported).
* `Art/Export/Manifests/<generator>.json` any extra placement data (screen rectangles, etc.).

## Teams (original)

| Abbr | City | Name | Primary | Secondary | Accent |
|---|---|---|---|---|---|
| NEO | Neon City | VOLTAGE | #FFD60A | #111111 | #00E5FF |
| BAY | Bay Harbor | KRAKENS | #0B7A75 | #FF6B1A | #F2F2F2 |
| RRK | Red Rock | SCORPIONS | #B3122E | #E9C46A | #1B1B1B |
| FRB | Frostburg | YETIS | #A9D6F5 | #0E2A47 | #FFFFFF |
| STV | Steel Valley | FORGE | #5A6270 | #FF8C1A | #FFD166 |
| SSC | Sunset Coast | SURGE | #FF4F79 | #2B2D9B | #2EC4B6 |

Arena: the **HEAT CHECK Arena**. Brand palette: flame red #E63312, flame orange #FF7A00,
flame yellow #FFC300, charcoal #15161A, white.
