"""Check loop seams, event markers, fall recovery and shoe contact on the authored player rig.

blender -b Art/Blend/player_actions.blend --python-exit-code 1 -P Blender/check_motion.py
"""
import json
import math
from pathlib import Path

import bpy

root = Path(__file__).resolve().parents[1]
clips = json.loads((root / "Art/Export/Manifests/anims.json").read_text())
scene = bpy.context.scene
rig = bpy.data.objects["Armature"]
player = bpy.data.objects["SK_Player"]
sole_vertices = {index for face in player.data.polygons
                 if player.data.materials[face.material_index].name == "MI_PlayerShoeSole"
                 for index in face.vertices}
grounded = {"Run", "Sprint", "RunDribble", "Defense", "ShuffleLeft", "ShuffleRight", "Backpedal", "Pass"}
ends = {}


def pose():
    return [(b.matrix.to_translation(), b.matrix.to_quaternion()) for b in rig.pose.bones]


def difference(a, b):
    distances, angles = [], []
    for (pa, qa), (pb, qb) in zip(a, b):
        distances.append((pa - pb).length)
        angles.append(math.degrees(2 * math.acos(min(1.0, abs(qa.dot(qb))))))
    return max(distances), max(angles)


for name, clip in clips.items():
    action = bpy.data.actions["A_" + name]
    rig.animation_data.action = action
    assert tuple(action.frame_range) == (0, clip["frames"]), name
    assert {m.name: m.frame for m in action.pose_markers} == clip["events"], name
    scene.frame_set(0)
    start = pose()
    prev = start
    peak_turn = 0.0
    floor = math.inf
    for frame in range(clip["frames"] + 1):
        scene.frame_set(frame)
        current = pose()
        peak_turn = max(peak_turn, difference(prev, current)[1])
        prev = current
        if name in grounded:
            obj = player.evaluated_get(bpy.context.evaluated_depsgraph_get())
            floor = min(floor, min((obj.matrix_world @ obj.data.vertices[i].co).z for i in sole_vertices))
    if clip["loop"]:
        cm, deg = difference(start, current)
        assert cm < 0.05 and deg < 0.2, (name, cm, deg)
    if name in grounded:
        assert floor >= -0.8, (name, "sole below floor (cm)", floor)
    ends[name] = (start, current)
    print(f"{name:14} {clip['frames'] + 1:3} samples   peak bone turn {peak_turn:5.1f} deg"
          + (f"   minimum sole {floor:5.2f} cm" if name in grounded else ""))

cm, deg = difference(ends["Fall"][1], ends["GetUp"][0])
assert cm < 0.05 and deg < 0.2, ("fall to get-up", cm, deg)
print(f"Verified {len(clips)} clips")
