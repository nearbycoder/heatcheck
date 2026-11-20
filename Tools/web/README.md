# Web asset pipeline (three.js build)

`Tools/web/build_web_assets.sh` rebuilds `web/play/assets/` from `Art/` (about 25 s). It wipes and
recreates that folder, so never hand-edit anything in it. Add `--no-render` to skip the preview PNGs.

| Step | Script | Notes |
|---|---|---|
| Characters | `blender_characters.py` | Opens `Art/Blend/player_actions.blend` (+ `A_Tip` from `referee.blend`) and `referee.blend`, converts the cm rig, meshes and location keys to metres, then exports glTF with every action |
| Statics | `blender_static.py` | Imports the static FBXs (metres), sets the hoop rim/net node offsets, adds the crowd `_fan` attribute, and builds `arena_lite` with Decimate |
| Images | `prepare_images.sh` | `sips` resize: court 4096x2048 JPEG, other textures ≤2048, UI logo ≤1024, badges ≤256 |
| Post-process | `postprocess.mjs` | gltf-transform: materials from `Art/Export/Materials/*.json`, embedded textures, meshopt on the big files |
| Audio | `convert_audio.py` | ffmpeg: MP3 for everything, Ogg Opus copies of the four loops, `audio/manifest.json` |
| Manifests | `make_manifest.py` | `manifest.json`, `characters/anims.json` (+ `Tip`), `characters/referee_anims.json` |
| Checks | `validate.mjs`, `verify_blender.py` | Khronos glTF-Validator, then a Blender re-import with contract checks and previews in `Tools/web/previews/` |

Runtime: `player.glb`, `referee.glb`, `arena.glb` and `arena_lite.glb` need
`loader.setMeshoptDecoder(MeshoptDecoder)` (`three/addons/libs/meshopt_decoder.module.js`).
See `web/play/assets/manifest.json` for the full contract: axes, facing, heights, clips, crowd attributes and hoop/court dimensions.

`glbjson.py file.glb` prints a quick node/material/animation summary of any GLB.
