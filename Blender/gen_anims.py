"""HEAT CHECK player animations.

Opens Art/Blend/character.blend (rig already converted to centimeters), authors
every gameplay animation procedurally with the IK `Poser`, exports one FBX per
animation to Art/Export/Anims/A_<Name>.fbx and renders contact sheets to
Art/Previews/anim_<Name>.png.

    blender -b --factory-startup -P Blender/gen_anims.py [-- Name1 Name2 ...]

Timing contract with the C++ game (frames @30fps) is written to
Art/Export/Manifests/anims.json (loop flags, event frames such as ball release).
"""

import bpy
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hc_common as hc  # noqa: E402
import char_rig as rig  # noqa: E402
from mathutils import Vector  # noqa: E402

BLEND = os.path.join(hc.ROOT, "Art", "Blend", "character.blend")
bpy.ops.wm.open_mainfile(filepath=BLEND)
ARM = bpy.data.objects["Armature"]
S = 100.0
P = rig.Poser(ARM, S=S)
BALL_R = 0.12
GRIP = 0.135      # palm center -> ball center
PALM = 0.085      # wrist -> palm center along the fingers

MANIFEST = {}


def V(*a):
    return Vector(a)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def attach(bone, pt_m):
    """Rest-space point (meters) rigidly carried by `bone` -> posed armature space (meters)."""
    pb = P.pb[bone]
    M = pb.matrix @ pb.bone.matrix_local.inverted()
    return (M @ (Vector(pt_m) * S)) / S


def adir(bone, d):
    pb = P.pb[bone]
    R = pb.matrix.to_3x3() @ pb.bone.matrix_local.to_3x3().inverted()
    return (R @ Vector(d)).normalized()


def ortho(a, b):
    """component of a perpendicular to b, normalized"""
    a = Vector(a)
    b = Vector(b).normalized()
    r = a - b * a.dot(b)
    return r.normalized()


def hand_on_ball(side, ball, contact, fingers, pole):
    """Place a hand so its palm presses the ball. All vectors in posed armature space (meters)."""
    contact = Vector(contact).normalized()
    fingers = ortho(fingers, contact)
    palm_c = Vector(ball) + contact * GRIP
    wrist = palm_c - fingers * PALM
    P.arm(side, wrist, elbow_pole=pole, fingers=fingers, palm=-contact)


def two_hands(ball_rest, bone="spine_03", spread=1.0, fingers=(0, -0.35, 0.94), lift=0.0,
              pole_l=(0.8, 0.5, -0.6), pole_r=(-0.8, 0.5, -0.6)):
    ball = attach(bone, ball_rest)
    for side, s, pole in (("l", 1, pole_l), ("r", -1, pole_r)):
        c = adir(bone, (s * spread, 0.18, -0.1 - lift))
        f = adir(bone, fingers)
        hand_on_ball(side, ball, c, f, adir(bone, pole))
    return ball


def arm_rel(side, wrist_rest, bone="spine_03", pole=None, fingers=None, palm=None):
    """Arm with a wrist target expressed in rest space but carried by the chest."""
    s = 1 if side == "l" else -1
    w = attach(bone, wrist_rest)
    pole = adir(bone, pole if pole else (0.3 * s, 1.0, -0.2))
    fingers = adir(bone, fingers) if fingers else None
    palm = adir(bone, palm) if palm else None
    P.arm(side, w, elbow_pole=pole, fingers=fingers, palm=palm)


def relaxed_arms(swing=0.0, bend=0.35, out=0.30, z=0.98, y=-0.03, bone="spine_03"):
    for side, s in (("l", 1), ("r", -1)):
        sw = swing * s
        arm_rel(side, (out * s, y - sw * 0.25, z + abs(sw) * 0.05), bone,
                pole=(0.35 * s, 1.0, 0.1), fingers=(0.12 * s, -0.25 - bend * 0.3, -1.0), palm=(-s, 0.25, 0.0))


def sole_lift(pitch):
    # Rotate the actual shoe footprint about the ankle. Raise the ankle by the
    # height lost at the toe on push-off (or at the heel on contact).
    delta = math.radians(pitch) - math.atan2(0.067, 0.127)
    lever = 0.246 if delta >= 0 else 0.072
    return 0.095 * (math.cos(delta) - 1) + lever * abs(math.sin(delta))


def feet(lx=0.16, ly=0.0, rx=-0.16, ry=0.0, lz=0.095, rz=0.095, lpitch=28.0, rpitch=28.0,
         lyaw=0.0, ryaw=0.0, pole_out=0.25, toe_l=0.0, toe_r=0.0):
    for side, x, y, z, pitch, yaw, toe in (("l", lx, ly, lz, lpitch, lyaw, toe_l), ("r", rx, ry, rz, rpitch, ryaw, toe_r)):
        s = 1 if side == "l" else -1
        pr, yr = math.radians(pitch), math.radians(yaw)
        fd = Vector((math.sin(yr) * math.cos(pr), -math.cos(yr) * math.cos(pr), -math.sin(pr)))
        if z == 0.095:
            z += sole_lift(pitch)
        P.leg(side, V(x, y, z), knee_pole=(pole_out * s + math.sin(yr), -1.0, 0.0), foot_dir=fd, toe_bend=toe)


def body(crouch=0.0, lean=0.0, twist=0.0, side_lean=0.0, dx=0.0, dy=0.0, prx=0.0, pry=0.0, prz=0.0,
         nod=0.0, turn=0.0, tilt=0.0):
    P.reset()
    P.pelvis(dx=dx, dy=dy, dz=-crouch, rx=prx, ry=pry, rz=prz)
    P.spine(bend=lean, twist=twist, lean=side_lean)
    P.head(nod=nod, turn=turn, tilt=tilt)
    P.update()


def stance(crouch=0.05, lean=6.0, width=0.17, stagger=0.0, twist=0.0, nod=0.0, prx=0.0, turn=0.0):
    body(crouch=crouch, lean=lean, twist=twist, prx=prx, nod=nod, turn=turn)
    feet(lx=width, ly=-stagger, rx=-width, ry=stagger)


def key(f):
    P.key(f)


def begin(name, frames, loop=False, **events):
    act = P.begin_action("A_" + name)
    MANIFEST[name] = {"frames": frames, "fps": 30, "loop": loop, "events": events}
    return act


# ---------------------------------------------------------------------------
# Animations
# ---------------------------------------------------------------------------

def anim_idle():
    begin("Idle", 60, loop=True)
    for f in range(0, 61, 10):
        ph = 2 * math.pi * f / 60
        stance(crouch=0.035 + 0.006 * math.sin(ph), lean=5 + 1.5 * math.sin(ph), width=0.16,
               nod=-4, turn=8 * math.sin(ph * 0.5 * 2) if f not in (0, 60) else 0.0)
        relaxed_arms(swing=0.04 * math.sin(ph), z=0.97 + 0.01 * math.sin(ph))
        key(f)


def anim_defense():
    begin("Defense", 24, loop=True)
    for f in range(0, 25, 3):
        ph = 2 * math.pi * f / 12
        stance(crouch=0.20 + 0.018 * math.cos(ph), lean=20, width=0.31, nod=-18, prx=6)
        for side, s in (("l", 1), ("r", -1)):
            arm_rel(side, (0.56 * s, -0.24, 1.30 + 0.02 * math.cos(ph + s)), pole=(0.4 * s, 0.4, -1.0),
                    fingers=(0.35 * s, -0.3, 0.88), palm=(0.0, -1.0, 0.2))
        key(f)


def dribble_hand(t, base=(-0.31, -0.30, 1.0), drop=0.20):
    """Right-hand dribble cycle: t in [0,1). Hand at top at t=0, pushes down, returns."""
    if t < 0.22:
        k = t / 0.22
        z = base[2] - drop * math.sin(k * math.pi * 0.5)
    else:
        k = (t - 0.22) / 0.78
        z = base[2] - drop * (1 - k) ** 1.6
    return Vector((base[0], base[1], z))


def dribble_arm(t, base=(-0.31, -0.30, 1.0), bone="spine_03"):
    w = dribble_hand(t, base)
    flick = 25 * math.sin(min(1.0, t / 0.22) * math.pi) if t < 0.22 else 0.0
    arm_rel("r", tuple(w), bone, pole=(-0.6, 0.9, 0.2),
            fingers=(0.0, -0.95, -0.3 - flick / 60.0), palm=(0.0, -0.15, -1.0))


def anim_dribble_idle():
    n = 16
    begin("DribbleIdle", n, loop=True, ball_contact=0, ball_floor=7)
    for f in range(0, n + 1, 2):
        t = (f % n) / n
        bob = 0.012 * math.cos(2 * math.pi * t)
        body(crouch=0.11 + bob, lean=14, twist=-8, nod=-12, turn=8)
        feet(lx=0.21, ly=-0.08, rx=-0.19, ry=0.10)
        dribble_arm(t, base=(-0.32, -0.30, 1.02))
        arm_rel("l", (0.30, -0.40, 1.18), pole=(0.6, 0.5, -0.6), fingers=(0.2, -0.6, 0.75), palm=(0.3, -0.9, 0.2))
        key(f)


def run_legs(ph, A=0.50, H=0.30, stance_frac=0.42, crouch=0.06, cross=0.0):
    # ph: 0..2pi, left foot planted forward at ph=0
    for side, s, off in (("l", 1, 0.0), ("r", -1, math.pi)):
        q = (ph + off) % (2 * math.pi)
        u = q / (2 * math.pi)
        if u < stance_frac:          # stance: foot travels back along the ground
            k = u / stance_frac
            y = -A + 2 * A * k
            z = 0.095
            pitch = 25 + 40 * max(0.0, (k - 0.6) / 0.4)
        else:                         # swing: lift heel high, bring forward
            k = (u - stance_frac) / (1 - stance_frac)
            y = A - 2 * A * (0.5 - 0.5 * math.cos(math.pi * k))
            z = 0.095 + H * math.sin(math.pi * k) ** 1.5
            pitch = 25 + 40 * (1 + math.cos(math.pi * k)) / 2
        P.leg(side, V(0.12 * s + cross * s, y, z + sole_lift(pitch)), knee_pole=(0.15 * s, -1.0, 0.0),
              foot_dir=(0, -math.cos(math.radians(pitch)), -math.sin(math.radians(pitch))))


def anim_run():
    n = 18
    begin("Run", n, loop=True)
    for f in range(0, n + 1, 1):
        ph = 2 * math.pi * f / n
        body(crouch=0.10 + 0.04 * math.cos(2 * ph), lean=13, twist=-11 * math.cos(ph),
             pry=9 * math.cos(ph), nod=-8)
        run_legs(ph, A=0.50, H=0.32)
        for side, s in (("l", 1), ("r", -1)):
            sw = math.cos(ph + (math.pi if s > 0 else 0.0))   # left arm forward when right leg forward
            arm_rel(side, (0.24 * s, -0.04 - 0.30 * sw, 1.12 + 0.10 * max(0.0, sw)), pole=(0.25 * s, 1.0, -0.1),
                    fingers=(0.0, -0.6, 0.30 + 0.50 * sw), palm=(-s, 0.0, 0.0))
        key(f)


def anim_sprint():
    n = 16
    begin("Sprint", n, loop=True)
    for f in range(0, n + 1, 1):
        ph = 2 * math.pi * f / n
        body(crouch=0.125 + 0.055 * math.cos(2 * ph), lean=24, twist=-14 * math.cos(ph),
             pry=11 * math.cos(ph), nod=-20)
        run_legs(ph, A=0.55, H=0.34, stance_frac=0.38)
        for side, s in (("l", 1), ("r", -1)):
            sw = math.cos(ph + (math.pi if s > 0 else 0.0))
            arm_rel(side, (0.22 * s, -0.06 - 0.40 * sw, 1.10 + 0.16 * max(0.0, sw)), pole=(0.2 * s, 1.0, -0.1),
                    fingers=(0.0, -0.5, 0.28 + 0.58 * sw), palm=(-s, 0.0, 0.0))
        key(f)


def anim_run_dribble():
    n = 18
    begin("RunDribble", n, loop=True, ball_contact=0, ball_floor=8)
    for f in range(0, n + 1, 1):
        ph = 2 * math.pi * f / n
        t = (f % n) / n
        body(crouch=0.11 + 0.035 * math.cos(2 * ph), lean=16, twist=-7 * math.cos(ph) - 6,
             pry=7 * math.cos(ph), nod=-12)
        run_legs(ph, A=0.46, H=0.28)
        dribble_arm(t, base=(-0.30, -0.42, 1.0))
        sw = math.cos(ph + math.pi)
        arm_rel("l", (0.25, -0.12 - 0.22 * sw, 1.15 + 0.06 * max(0.0, sw)), pole=(0.3, 1.0, -0.1),
                fingers=(0.0, -0.6, 0.8), palm=(-1, 0, 0))
        key(f)


def guard_steps(name, lateral):
    # Left and right never cross. The support foot travels against the root
    # while the free foot lifts, widens the stance, then accepts the weight.
    n = 16
    begin(name, n, loop=True)
    for frame in range(n + 1):
        t = (frame % n) / n
        wave = math.cos(2 * math.pi * t)
        body(crouch=0.17 + 0.018 * math.cos(4 * math.pi * t), lean=15,
             dx=0.035 * wave, pry=3 * wave, twist=3 * wave, nod=-12)
        for side, sign in (("l", 1), ("r", -1)):
            phase = (t + (0 if side == "l" else 0.5)) % 1
            stroke = math.cos(2 * math.pi * phase)
            lift = max(0, -math.sin(2 * math.pi * phase))
            x = sign * 0.28 + lateral * 0.16 * stroke
            y = 0.05 * sign + (0 if lateral else 0.26 * stroke)
            P.leg(side, V(x, y, 0.095 + 0.095 * lift), knee_pole=(0.3 * sign, -1, 0),
                  foot_dir=(0, -0.9, -0.43 - 0.25 * lift))
            arm_rel(side, (0.48 * sign, -0.23, 1.24 + 0.055 * sign * wave),
                    pole=(0.5 * sign, 0.4, -0.8), fingers=(0.35 * sign, -0.4, 0.8),
                    palm=(0, -1, 0.15))
        key(frame)


def anim_hold_ball():
    begin("HoldBall", 30, loop=True)
    for f in range(0, 31, 6):
        ph = 2 * math.pi * f / 30
        stance(crouch=0.07 + 0.006 * math.sin(ph), lean=9, width=0.18, stagger=0.05, nod=-6)
        two_hands((0.0, -0.31, 1.24 + 0.005 * math.sin(ph)))
        key(f)


def anim_jump_shot():
    n = 30
    begin("JumpShot", n, set_frame=13, release_frame=16)
    # f0 gather at chest
    stance(crouch=0.06, lean=8, width=0.17, stagger=0.04, nod=-6)
    two_hands((0.0, -0.30, 1.22))
    key(0)
    # f5 dip
    stance(crouch=0.17, lean=14, width=0.18, stagger=0.04, nod=-12)
    two_hands((0.0, -0.33, 1.10))
    key(5)
    # f9 takeoff: legs extend, toes down, ball rising
    body(crouch=-0.01, lean=4, nod=-4)
    feet(lx=0.15, ly=0.02, rx=-0.15, ry=0.05, lz=0.12, rz=0.12, lpitch=62, rpitch=62)
    two_hands((-0.02, -0.26, 1.55), fingers=(0, -0.2, 0.98))
    key(9)
    # set point: ball above the right eye, shooting hand under the ball, guide hand on the side
    body(crouch=-0.02, lean=-2, nod=4)
    feet(lx=0.14, ly=0.04, rx=-0.14, ry=0.08, lz=0.14, rz=0.14, lpitch=55, rpitch=55)
    ball = attach("spine_03", (-0.07, -0.13, 1.97))
    hand_on_ball("r", ball, adir("spine_03", (0.05, 0.30, -1.0)), adir("spine_03", (0.0, 0.55, 0.85)),
                 adir("spine_03", (-0.2, -1.0, -0.45)))
    hand_on_ball("l", ball, adir("spine_03", (1.0, 0.05, -0.1)), adir("spine_03", (0.0, -0.3, 0.95)),
                 adir("spine_03", (0.8, 0.2, -0.6)))
    key(13)
    # f16 release: shooting arm extends up/forward, wrist snaps
    body(crouch=-0.02, lean=-1, nod=6)
    feet(lx=0.14, ly=0.04, rx=-0.14, ry=0.08, lz=0.14, rz=0.14, lpitch=58, rpitch=58)
    arm_rel("r", (-0.10, -0.28, 2.10), pole=(-0.2, 0.2, -1.0), fingers=(0.0, -0.94, 0.34), palm=(0.0, -0.34, -0.94))
    arm_rel("l", (0.17, -0.22, 1.86), pole=(0.8, 0.3, -0.5), fingers=(0.0, -0.3, 0.95), palm=(-1.0, 0.0, 0.0))
    key(16)
    # f21 follow-through hold
    body(crouch=-0.01, lean=0, nod=8)
    feet(lx=0.14, ly=0.03, rx=-0.14, ry=0.06, lz=0.12, rz=0.12, lpitch=50, rpitch=50)
    arm_rel("r", (-0.10, -0.30, 2.08), pole=(-0.2, 0.2, -1.0), fingers=(0.0, -0.7, -0.7), palm=(0.0, 0.3, -1.0))
    arm_rel("l", (0.24, -0.18, 1.70), pole=(0.8, 0.3, -0.5), fingers=(0.2, -0.3, 0.9), palm=(-1.0, 0.0, 0.0))
    key(21)
    # f25 landing
    stance(crouch=0.13, lean=10, width=0.18, stagger=0.03, nod=-4)
    arm_rel("r", (-0.16, -0.30, 1.62), pole=(-0.4, 0.6, -0.8), fingers=(0.0, -0.8, -0.4), palm=(0.0, 0.2, -1.0))
    arm_rel("l", (0.28, -0.12, 1.20), pole=(0.6, 0.8, -0.2), fingers=(0.1, -0.4, -0.9), palm=(-1.0, 0.0, 0.0))
    key(25)
    stance(crouch=0.05, lean=6, width=0.17, nod=-4)
    relaxed_arms()
    key(30)


def anim_layup():
    n = 26
    begin("Layup", n, release_frame=12)
    stance(crouch=0.10, lean=12, width=0.15, stagger=0.18, nod=-8)
    two_hands((0.0, -0.32, 1.18))
    key(0)
    # f5 takeoff off the left foot, right knee drives
    body(crouch=0.02, lean=6, twist=-6, nod=-6)
    P.leg("l", V(0.13, 0.12, 0.10), knee_pole=(0.2, -1, 0), foot_dir=(0, -0.6, -0.8))
    P.leg("r", V(-0.13, -0.25, 0.52), knee_pole=(-0.2, -1, 0.2), foot_dir=(0, -0.7, -0.7))
    two_hands((-0.08, -0.32, 1.45), fingers=(0, -0.2, 0.98))
    key(5)
    for fr in (10, 12):
        body(crouch=-0.02, lean=2, twist=-10, nod=8, side_lean=-4)
        P.leg("l", V(0.13, 0.15, 0.14), knee_pole=(0.2, -1, 0), foot_dir=(0, -0.5, -0.86))
        P.leg("r", V(-0.12, -0.30, 0.62), knee_pole=(-0.2, -1, 0.3), foot_dir=(0, -0.6, -0.8))
        if fr == 10:
            ball = attach("spine_03", (-0.16, -0.22, 2.20))
            hand_on_ball("r", ball, adir("spine_03", (0.0, 0.25, -1.0)), adir("spine_03", (0.0, -0.4, 0.92)),
                         adir("spine_03", (-0.4, -0.3, -1.0)))
        else:
            arm_rel("r", (-0.16, -0.30, 2.14), pole=(-0.4, -0.3, -1.0), fingers=(0.0, -0.6, 0.8), palm=(0.0, -0.4, 0.9))
        arm_rel("l", (0.30, -0.25, 1.45), pole=(0.8, 0.2, -0.6), fingers=(0.2, -0.5, 0.8), palm=(0.0, -1.0, 0.0))
        key(fr)
    body(crouch=0.0, lean=4, twist=-4, nod=4)
    feet(lx=0.15, ly=0.05, rx=-0.15, ry=-0.08, lz=0.11, rz=0.16, lpitch=50, rpitch=45)
    arm_rel("r", (-0.20, -0.25, 1.80), pole=(-0.4, 0.3, -1.0), fingers=(0.0, -0.6, 0.8), palm=(0.0, -0.4, 0.9))
    arm_rel("l", (0.30, -0.15, 1.25), pole=(0.8, 0.5, -0.4))
    key(18)
    stance(crouch=0.12, lean=10, width=0.17, stagger=0.05, nod=-4)
    relaxed_arms(z=1.0)
    key(22)
    stance(crouch=0.05, lean=6, width=0.17, nod=-4)
    relaxed_arms()
    key(26)


def dunk_air_legs(tuck=1.0):
    P.leg("l", V(0.15, 0.20 + 0.10 * tuck, 0.30 + 0.30 * tuck), knee_pole=(0.2, -1, 0.3), foot_dir=(0, -0.3, -0.95))
    P.leg("r", V(-0.15, 0.10 + 0.15 * tuck, 0.24 + 0.36 * tuck), knee_pole=(-0.2, -1, 0.3), foot_dir=(0, -0.3, -0.95))


def anim_dunk():
    n = 40
    begin("Dunk", n, air_frame=12, slam_frame=24, hang_frame=28)
    stance(crouch=0.24, lean=26, width=0.20, stagger=0.10, nod=-20)
    two_hands((0.0, -0.30, 1.08))
    key(0)
    body(crouch=0.02, lean=8, nod=-6)
    feet(lx=0.14, ly=0.06, rx=-0.14, ry=0.10, lz=0.12, rz=0.12, lpitch=62, rpitch=62)
    two_hands((0.0, -0.26, 1.55), fingers=(0, -0.1, 1.0))
    key(5)
    for fr, tuck, back in ((12, 1.0, 0.08), (18, 1.0, 0.12)):
        body(crouch=-0.02, lean=-10, nod=8)
        dunk_air_legs(tuck)
        two_hands((0.0, back, 2.02), fingers=(0, 0.9, 0.42), pole_l=(0.6, -1.0, 0.3), pole_r=(-0.6, -1.0, 0.3))
        key(fr)
    # slam: arms whip forward/down, torso crunches, legs kick back
    body(crouch=-0.02, lean=24, nod=-14)
    P.leg("l", V(0.15, 0.30, 0.25), knee_pole=(0.2, -1, -0.2), foot_dir=(0, 0.2, -0.98))
    P.leg("r", V(-0.15, 0.36, 0.30), knee_pole=(-0.2, -1, -0.2), foot_dir=(0, 0.2, -0.98))
    two_hands((0.0, -0.50, 1.58), fingers=(0, -0.95, -0.3), pole_l=(0.7, 0.5, 0.5), pole_r=(-0.7, 0.5, 0.5))
    key(24)
    # hang on the rim
    for fr, sw in ((28, 1.0), (34, -0.6), (40, 0.3)):
        body(crouch=-0.04, lean=-4 + 3 * sw, nod=6)
        P.leg("l", V(0.15, -0.10 - 0.06 * sw, 0.14), knee_pole=(0.2, -1, 0), foot_dir=(0, -0.3, -0.95))
        P.leg("r", V(-0.15, -0.04 - 0.06 * sw, 0.16), knee_pole=(-0.2, -1, 0), foot_dir=(0, -0.3, -0.95))
        for side, s in (("l", 1), ("r", -1)):
            arm_rel(side, (0.20 * s, -0.34, 2.22), pole=(0.6 * s, 0.4, -0.5), fingers=(0.0, -0.6, 0.8),
                    palm=(0.0, 0.4, -0.9))
        key(fr)


def anim_dunk_windmill():
    n = 40
    begin("DunkWindmill", n, air_frame=10, slam_frame=24, hang_frame=28)
    stance(crouch=0.24, lean=26, width=0.20, stagger=0.10, nod=-20)
    two_hands((0.0, -0.30, 1.08))
    key(0)
    body(crouch=0.02, lean=8, nod=-6)
    feet(lx=0.14, ly=0.06, rx=-0.14, ry=0.10, lz=0.12, rz=0.12, lpitch=62, rpitch=62)
    two_hands((0.0, -0.26, 1.45), fingers=(0, -0.1, 1.0))
    key(5)
    # windmill: ball palmed in the right hand sweeping down, back, up and over
    path = [(9, (-0.30, -0.30, 1.05)), (13, (-0.42, 0.25, 1.15)), (17, (-0.35, 0.35, 1.85)),
            (20, (-0.22, -0.05, 2.25))]
    for fr, w in path:
        body(crouch=-0.02, lean=-6, twist=-8, nod=6)
        dunk_air_legs(1.0)
        ball = attach("spine_03", w)
        out = (ball - attach("spine_03", (-0.20, 0.01, 1.52))).normalized()
        hand_on_ball("r", ball, -out, ortho(adir("spine_03", (0, -1, 0)), out), adir("spine_03", (-1, 0.2, -0.3)))
        arm_rel("l", (0.55, -0.10, 1.45), pole=(0.3, 1.0, -0.3), fingers=(0.8, -0.2, 0.5), palm=(0, -1, 0))
        key(fr)
    body(crouch=-0.02, lean=22, twist=-4, nod=-12)
    P.leg("l", V(0.15, 0.30, 0.25), knee_pole=(0.2, -1, -0.2), foot_dir=(0, 0.2, -0.98))
    P.leg("r", V(-0.15, 0.36, 0.30), knee_pole=(-0.2, -1, -0.2), foot_dir=(0, 0.2, -0.98))
    ball = attach("spine_03", (-0.10, -0.55, 1.60))
    hand_on_ball("r", ball, adir("spine_03", (0.0, 0.3, 1.0)), adir("spine_03", (0.0, -1.0, 0.2)),
                 adir("spine_03", (-0.6, 0.6, 0.4)))
    arm_rel("l", (0.45, -0.05, 1.30), pole=(0.3, 1.0, -0.3), fingers=(0.8, -0.2, 0.3), palm=(0, -1, 0))
    key(24)
    for fr, sw in ((28, 1.0), (34, -0.6), (40, 0.3)):
        body(crouch=-0.04, lean=-4 + 3 * sw, side_lean=6, nod=6)
        P.leg("l", V(0.15, -0.10 - 0.06 * sw, 0.14), knee_pole=(0.2, -1, 0), foot_dir=(0, -0.3, -0.95))
        P.leg("r", V(-0.15, -0.04 - 0.06 * sw, 0.16), knee_pole=(-0.2, -1, 0), foot_dir=(0, -0.3, -0.95))
        arm_rel("r", (-0.12, -0.34, 2.24), pole=(-0.6, 0.4, -0.5), fingers=(0.0, -0.6, 0.8), palm=(0.0, 0.4, -0.9))
        arm_rel("l", (0.40, -0.10, 1.35), pole=(0.3, 1.0, -0.3))
        key(fr)


def anim_pass():
    n = 14
    begin("Pass", n, release_frame=6)
    # Keep wrists behind the ball through the gather and extend both elbows
    # through release. A small stagger transfers weight onto the lead foot.
    for fr, reach, dip in ((0, 0.0, 0.0), (2, -0.10, 0.035), (4, 0.43, 0.025),
                           (6, 1.0, 0.0), (8, 0.94, 0.0), (10, 0.65, 0.0)):
        body(crouch=0.08 + dip, lean=8 + 8 * reach, dy=-0.06 * reach, nod=-7)
        feet(lx=0.18, ly=-0.13, rx=-0.18, ry=0.11, rpitch=28 + 14 * reach)
        for side, sign in (("l", 1), ("r", -1)):
            arm_rel(side, (sign * (0.15 + 0.035 * reach), -0.24 - 0.37 * reach, 1.28 + 0.08 * reach),
                    pole=(0.75 * sign, 0.55, -0.55), fingers=(-0.22 * sign, -0.75, 0.65 - 0.92 * reach),
                    palm=(-sign * 0.90, -0.40 - 0.25 * reach, -0.10 * reach))
        key(fr)
    stance(crouch=0.05, lean=6, width=0.17, nod=-4)
    relaxed_arms()
    key(14)


def anim_shove():
    n = 18
    begin("Shove", n, impact_frame=6)
    stance(crouch=0.07, lean=6, width=0.18, nod=-4)
    for side, sign in (("l", 1), ("r", -1)):
        arm_rel(side, (0.25 * sign, -0.23, 1.13), pole=(0.55 * sign, 0.6, -0.4),
                fingers=(0.2 * sign, -0.7, 0.55), palm=(-0.4 * sign, -0.8, -0.2))
    key(0)
    stance(crouch=0.10, lean=-2, width=0.18, stagger=0.06, nod=-2)
    for side, s in (("l", 1), ("r", -1)):
        arm_rel(side, (0.17 * s, -0.20, 1.32), pole=(0.8 * s, 0.6, -0.3), fingers=(0.0, -0.3, 0.95), palm=(0.0, -1.0, 0.0))
    key(3)
    body(crouch=0.12, lean=25, nod=-17, dy=-0.10)
    feet(lx=0.16, ly=-0.42, rx=-0.16, ry=0.30, lpitch=20, rpitch=55)
    for side, s in (("l", 1), ("r", -1)):
        arm_rel(side, (0.19 * s, -0.66, 1.36), pole=(0.6 * s, 0.4, -0.8), fingers=(0.0, -0.2, 0.98), palm=(0.0, -1.0, 0.0))
    key(6)
    key(10)
    stance(crouch=0.05, lean=6, width=0.17, nod=-4)
    relaxed_arms()
    key(18)


def anim_steal():
    n = 14
    begin("Steal", n, contact_frame=5)
    stance(crouch=0.18, lean=18, width=0.28, nod=-16, prx=4)
    for side, s in (("l", 1), ("r", -1)):
        arm_rel(side, (0.45 * s, -0.25, 1.15), pole=(0.4 * s, 0.4, -1.0), fingers=(0.3 * s, -0.4, 0.8), palm=(0, -1, 0.2))
    key(0)
    body(crouch=0.20, lean=34, twist=-10, nod=-24, prx=6)
    feet(lx=0.26, ly=-0.18, rx=-0.26, ry=0.10)
    arm_rel("r", (-0.22, -0.66, 1.10), pole=(-0.5, 0.6, -0.6), fingers=(0.0, -0.9, -0.4), palm=(0.4, 0.0, -0.9))
    arm_rel("l", (0.40, -0.20, 1.20), pole=(0.6, 0.6, -0.6))
    key(4)
    body(crouch=0.20, lean=32, twist=14, nod=-22, prx=6)
    feet(lx=0.26, ly=-0.18, rx=-0.26, ry=0.10)
    arm_rel("r", (0.20, -0.58, 1.05), pole=(-0.5, 0.6, -0.6), fingers=(0.8, -0.6, -0.2), palm=(0.9, 0.0, -0.4))
    arm_rel("l", (0.42, -0.10, 1.25), pole=(0.6, 0.6, -0.6))
    key(8)
    stance(crouch=0.18, lean=18, width=0.28, nod=-16, prx=4)
    for side, s in (("l", 1), ("r", -1)):
        arm_rel(side, (0.45 * s, -0.25, 1.15), pole=(0.4 * s, 0.4, -1.0), fingers=(0.3 * s, -0.4, 0.8), palm=(0, -1, 0.2))
    key(14)


def anim_block():
    n = 26
    begin("Block", n, apex_frame=9)
    stance(crouch=0.20, lean=14, width=0.22, nod=-10)
    relaxed_arms(z=1.10, out=0.34)
    key(0)
    body(crouch=0.0, lean=2, nod=4)
    feet(lx=0.15, ly=0.03, rx=-0.15, ry=0.03, lz=0.12, rz=0.12, lpitch=60, rpitch=60)
    for side, s in (("l", 1), ("r", -1)):
        arm_rel(side, (0.22 * s, -0.20, 1.95), pole=(0.6 * s, 0.4, -0.5), fingers=(0.0, -0.2, 0.98), palm=(0, -1, 0))
    key(4)
    for fr in (9, 15):
        body(crouch=-0.02, lean=-3, nod=12)
        feet(lx=0.14, ly=0.05, rx=-0.14, ry=0.0, lz=0.16, rz=0.14, lpitch=62, rpitch=62)
        arm_rel("l", (0.16, -0.12, 2.18), pole=(0.6, 0.4, -0.5), fingers=(0.0, -0.1, 1.0), palm=(0, -1, 0))
        arm_rel("r", (-0.20, -0.08, 2.10), pole=(-0.6, 0.4, -0.5), fingers=(0.0, -0.1, 1.0), palm=(0, -1, 0))
        key(fr)
    body(crouch=0.0, lean=4, nod=6)
    feet(lx=0.15, ly=0.03, rx=-0.15, ry=0.03, lz=0.12, rz=0.12, lpitch=50, rpitch=50)
    for side, s in (("l", 1), ("r", -1)):
        arm_rel(side, (0.26 * s, -0.20, 1.85), pole=(0.6 * s, 0.4, -0.5), fingers=(0.0, -0.3, 0.95), palm=(0, -1, 0))
    key(20)
    stance(crouch=0.12, lean=10, width=0.2, nod=-4)
    relaxed_arms(z=1.05)
    key(26)


def lying_pose(arms_spread=1.0):
    body(crouch=0.84, dy=0.40, prx=-84, lean=4, nod=-8)
    P.leg("l", V(0.20, -0.40, 0.10), knee_pole=(0.3, 0.0, 1.0), foot_dir=(0.1, -0.2, 0.97))
    P.leg("r", V(-0.18, -0.36, 0.12), knee_pole=(-0.3, 0.0, 1.0), foot_dir=(-0.1, -0.2, 0.97))
    P.arm("l", V(0.52 * arms_spread, 0.70, 0.10), elbow_pole=(0, 0, 1), fingers=(0.4, 0.8, 0.0), palm=(0, 0, -1))
    P.arm("r", V(-0.52 * arms_spread, 0.70, 0.10), elbow_pole=(0, 0, 1), fingers=(-0.4, 0.8, 0.0), palm=(0, 0, -1))


def anim_fall():
    n = 26
    begin("Fall", n, ground_frame=11)
    stance(crouch=0.06, lean=6, width=0.18, nod=-4)
    relaxed_arms()
    key(0)
    body(crouch=0.12, dy=0.18, lean=-26, prx=-16, nod=-16)
    feet(lx=0.18, ly=-0.20, rx=-0.16, ry=-0.05, lpitch=0, rpitch=10)
    for side, s in (("l", 1), ("r", -1)):
        arm_rel(side, (0.30 * s, -0.55, 1.75), pole=(0.6 * s, 0.4, -0.6), fingers=(0.3 * s, -0.6, 0.7), palm=(0, -0.5, -0.8))
    key(4)
    body(crouch=0.55, dy=0.36, lean=-10, prx=-55, nod=10)
    P.leg("l", V(0.20, -0.30, 0.30), knee_pole=(0.3, -0.5, 1.0), foot_dir=(0.1, -0.4, 0.9))
    P.leg("r", V(-0.18, -0.28, 0.24), knee_pole=(-0.3, -0.5, 1.0), foot_dir=(-0.1, -0.4, 0.9))
    P.arm("l", V(0.50, 0.40, 0.55), elbow_pole=(0.3, 0.5, 1.0))
    P.arm("r", V(-0.50, 0.40, 0.55), elbow_pole=(-0.3, 0.5, 1.0))
    key(8)
    lying_pose(1.0)
    key(11)
    body(crouch=0.80, dy=0.40, prx=-80, lean=6, nod=-14)
    P.leg("l", V(0.20, -0.38, 0.16), knee_pole=(0.3, 0.0, 1.0), foot_dir=(0.1, -0.2, 0.97))
    P.leg("r", V(-0.18, -0.34, 0.20), knee_pole=(-0.3, 0.0, 1.0), foot_dir=(-0.1, -0.2, 0.97))
    P.arm("l", V(0.52, 0.66, 0.16), elbow_pole=(0, 0, 1))
    P.arm("r", V(-0.52, 0.66, 0.16), elbow_pole=(0, 0, 1))
    key(15)
    lying_pose(1.0)
    key(26)


def anim_get_up():
    n = 26
    begin("GetUp", n)
    lying_pose(1.0)
    key(0)
    # sit up, hands behind on the floor
    body(crouch=0.80, dy=0.30, prx=-20, lean=36, nod=-10)
    P.leg("l", V(0.20, -0.30, 0.10), knee_pole=(0.3, -0.3, 1.0), foot_dir=(0.1, -0.3, 0.95))
    P.leg("r", V(-0.18, -0.15, 0.10), knee_pole=(-0.3, -0.3, 1.0), foot_dir=(-0.1, -0.5, 0.86))
    P.arm("l", V(0.36, 0.55, 0.10), elbow_pole=(0.5, 0.6, -0.2), fingers=(0.2, 0.9, -0.3), palm=(0, 0, -1))
    P.arm("r", V(-0.36, 0.55, 0.10), elbow_pole=(-0.5, 0.6, -0.2), fingers=(-0.2, 0.9, -0.3), palm=(0, 0, -1))
    key(8)
    # crouch with feet under
    body(crouch=0.50, dy=0.05, prx=10, lean=40, nod=-20)
    feet(lx=0.20, ly=0.05, rx=-0.20, ry=0.10, lpitch=20, rpitch=20)
    P.arm("l", V(0.30, -0.30, 0.55), elbow_pole=(0.5, 1.0, 0.0))
    P.arm("r", V(-0.30, -0.25, 0.55), elbow_pole=(-0.5, 1.0, 0.0))
    key(16)
    stance(crouch=0.10, lean=12, width=0.18, nod=-6)
    relaxed_arms(z=1.0)
    key(22)
    stance(crouch=0.05, lean=6, width=0.17, nod=-4)
    relaxed_arms()
    key(26)


def anim_land():
    begin("Land", 11, ground_frame=2)
    for fr, crouch, lean, arms in ((0, 0.04, 5, 0.41), (2, 0.12, 11, 0.44),
                                    (4, 0.22, 21, 0.48), (7, 0.13, 13, 0.39),
                                    (11, 0.05, 6, 0.30)):
        stance(crouch=crouch, lean=lean, width=0.20, stagger=0.05, nod=-lean * 0.7)
        relaxed_arms(out=arms, z=1.05 + (arms - 0.30) * 1.2)
        key(fr)


def anim_celebrate():
    n = 32
    begin("Celebrate", n)
    for fr, up in ((0, 0.0), (6, 1.0), (11, 0.55), (16, 1.0), (22, 0.6), (32, 0.0)):
        stance(crouch=0.06 + 0.04 * (1 - up), lean=2 - 6 * up, width=0.19, nod=6 * up - 4)
        if up > 0:
            arm_rel("r", (-0.24, -0.06, 1.70 + 0.45 * up), pole=(-0.8, 0.3, -0.4), fingers=(0.0, 0.1, 1.0), palm=(0.3, 0.0, 0.0))
            arm_rel("l", (0.30, -0.22, 1.05 + 0.08 * up), pole=(0.8, 0.6, 0.0), fingers=(0.0, -0.3, 0.95), palm=(-1, 0, 0))
        else:
            relaxed_arms()
        key(fr)


ALL = {
    "Idle": anim_idle, "Defense": anim_defense, "DribbleIdle": anim_dribble_idle, "Run": anim_run,
    "Sprint": anim_sprint, "RunDribble": anim_run_dribble, "HoldBall": anim_hold_ball,
    "JumpShot": anim_jump_shot, "Layup": anim_layup, "Dunk": anim_dunk, "DunkWindmill": anim_dunk_windmill,
    "Pass": anim_pass, "Shove": anim_shove, "Steal": anim_steal, "Block": anim_block, "Fall": anim_fall,
    "GetUp": anim_get_up, "Celebrate": anim_celebrate,
    "ShuffleLeft": lambda: guard_steps("ShuffleLeft", 1),
    "ShuffleRight": lambda: guard_steps("ShuffleRight", -1),
    "Backpedal": lambda: guard_steps("Backpedal", 0), "Land": anim_land,
}

# How the preview places a stand-in ball (verifies hand placement)
BALL_MODE = {
    "DribbleIdle": "dribble", "RunDribble": "dribble", "HoldBall": "two", "Pass": ("two", 6),
    "JumpShot": ("two", 16), "Layup": ("right", 12), "Dunk": ("two", 26), "DunkWindmill": ("right_from", 9, 26),
}


# ---------------------------------------------------------------------------
# Export + preview
# ---------------------------------------------------------------------------

def set_meshes_deform(enabled):
    for o in bpy.data.objects:
        if o.type == "MESH":
            for m in o.modifiers:
                if m.type == "ARMATURE":
                    m.show_viewport = enabled
                    m.show_render = enabled


def export_action(name):
    act = bpy.data.actions["A_" + name]
    ARM.animation_data.action = act
    sc = bpy.context.scene
    sc.frame_start = 0
    sc.frame_end = MANIFEST[name]["frames"]
    hc.export_anim_fbx(ARM, "A_%s.fbx" % name)


def grip_world(side):
    pb = ARM.pose.bones["grip_" + side]
    return ARM.matrix_world @ pb.head


def preview(name, ncols=6):
    act = bpy.data.actions["A_" + name]
    ARM.animation_data.action = act
    n = MANIFEST[name]["frames"]
    frames = [round(n * i / (ncols - 1)) for i in range(ncols)]
    ball = bpy.data.objects.get("PreviewBall")
    mode = BALL_MODE.get(name)
    paths = []
    for i, f in enumerate(frames):
        bpy.context.scene.frame_set(f)
        bpy.context.view_layer.update()
        show = False
        if mode == "two" or (isinstance(mode, tuple) and mode[0] == "two" and f <= mode[1]):
            ball.location = (grip_world("l") + grip_world("r")) * 0.5
            show = True
        elif isinstance(mode, tuple) and mode[0] == "right" and f <= mode[1]:
            ball.location = grip_world("r")
            show = True
        elif isinstance(mode, tuple) and mode[0] == "right_from" and mode[1] <= f <= mode[2]:
            ball.location = grip_world("r")
            show = True
        elif isinstance(mode, tuple) and mode[0] == "two" and name == "DunkWindmill":
            pass
        elif mode == "dribble":
            t = (f % n) / n
            g = grip_world("r")
            # ball: in the hand at t=0, floor around t=0.45, back in hand at t=1
            hand_z = g.z
            u = t
            zf = BALL_R * S
            if u < 0.45:
                k = u / 0.45
                z = hand_z + (zf - hand_z) * (k ** 2)
            else:
                k = (u - 0.45) / 0.55
                z = zf + (hand_z - zf) * (1 - (1 - k) ** 2)
            ball.location = (g.x, g.y, z)
            show = True
        if name == "Dunk" and isinstance(mode, tuple) and f <= 26:
            ball.location = (grip_world("l") + grip_world("r")) * 0.5
            show = True
        ball.hide_render = not show
        path = os.path.join(hc.PREVIEW_DIR, "tmp_%s_%02d.png" % (name, i))
        hc.render_to(path)
        paths.append(path)
    return paths


def setup_preview_scene():
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = o.name not in ("SK_Player", "SK_Hair_Flattop", "SK_Num_T2", "SK_Num_O3", "SK_JerseyText_NEO", "SK_Wristbands", "SK_Headband")
    hc.setup_preview_render(res=(420, 560), samples=16)
    hc.add_sun("Key", rotation=(math.radians(55), 0, math.radians(-35)), energy=3.2)
    hc.add_sun("Fill", rotation=(math.radians(70), 0, math.radians(150)), energy=1.2)
    cam = hc.add_camera("Cam", (1.85 * S, -2.95 * S, 1.30 * S), (0, -0.1 * S, 1.0 * S), lens=40)
    cam.data.clip_end = 100000
    ball = hc.sphere("PreviewBall", BALL_R * S, mat=hc.material("PrevBallMat", (0.9, 0.3, 0.05, 1), 0.6))
    ball.hide_render = True
    # floor
    fl = hc.box("PrevFloor", (6 * S, 6 * S, 0.02 * S), location=(0, 0, -0.01 * S), mat=hc.material("PrevFloorMat", (0.55, 0.42, 0.28, 1), 0.5))
    fl.hide_render = False


def save_action_library():
    # Save the same actions that were baked to FBX, with their sparse IK keys
    # intact so contacts and release poses can be inspected in the Action Editor.
    for name, clip in MANIFEST.items():
        action = bpy.data.actions["A_" + name]
        for event, frame in clip["events"].items():
            action.pose_markers.new(event).frame = frame
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            obj.hide_set(obj.hide_render)
    bpy.ops.object.select_all(action="DESELECT")
    ARM.hide_set(False)
    ARM.select_set(True)
    bpy.context.view_layer.objects.active = ARM
    ARM.animation_data.action = bpy.data.actions["A_RunDribble"]
    scene = bpy.context.scene
    scene.frame_end = MANIFEST["RunDribble"]["frames"]
    scene.frame_set(0)
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.region_3d.view_perspective = "CAMERA"
            area.spaces.active.overlay.show_overlays = False
        elif area.type == "DOPESHEET_EDITOR":
            area.spaces.active.mode = "ACTION"
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(os.path.dirname(BLEND), "player_actions.blend"), copy=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    names = argv if argv else list(ALL.keys())
    set_meshes_deform(False)
    for nme in ALL:          # author all (actions are cheap) so the manifest is complete
        ALL[nme]()
    for nme in ALL:
        export_action(nme)
    os.makedirs(os.path.join(hc.EXPORT_DIR, "Manifests"), exist_ok=True)
    with open(os.path.join(hc.EXPORT_DIR, "Manifests", "anims.json"), "w") as fp:
        json.dump(MANIFEST, fp, indent=2)
    set_meshes_deform(True)
    setup_preview_scene()
    save_action_library()
    for nme in names:
        paths = preview(nme)
        print("PREVIEW", nme, " ".join(paths))
    print("ANIMS DONE")


if __name__ == "__main__":
    main()
