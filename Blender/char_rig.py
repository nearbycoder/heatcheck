"""HEAT CHECK player skeleton + procedural pose builder.

The skeleton is defined in meters with the character facing -Y (Blender front),
character-left = +X.  Bone local frames follow one convention so poses are easy
to author:

* vertical bones (root, pelvis, spine_*, neck, head): Y = up, X = +X (left), Z = forward (-Y)
      rx > 0 bends forward, rz > 0 leans to the character's right, ry > 0 twists to the left
* arm bones: Y along the limb, Z = backward (+Y) in rest; the elbow pole is "+Z"
* leg bones: Y along the limb (down), Z = backward (+Y); knees bend toward +Z
* feet: Y toward the toes, Z = down

Poses are authored with a small IK-based `Poser` so animations are written in
terms of hand/foot targets instead of raw joint angles.
"""

import bpy
import math
from mathutils import Vector, Matrix, Euler, Quaternion

ARM_ABDUCTION = math.radians(42.0)   # A-pose angle of the arms from vertical
UPPER_ARM = 0.315
FOREARM = 0.29
HAND = 0.19


def _arm_pts(side):
    shoulder = Vector((0.205 * side, 0.012, 1.525))
    d = Vector((math.sin(ARM_ABDUCTION) * side, 0.0, -math.cos(ARM_ABDUCTION)))
    elbow = shoulder + d * UPPER_ARM
    wrist = elbow + d * FOREARM
    tip = wrist + d * HAND
    return shoulder, elbow, wrist, tip, d


def _leg_pts(side):
    hip = Vector((0.105 * side, 0.0, 0.985))
    knee = Vector((0.115 * side, -0.014, 0.545))
    ankle = Vector((0.12 * side, 0.022, 0.095))
    ball = Vector((0.125 * side, -0.105, 0.028))
    toe = Vector((0.125 * side, -0.185, 0.028))
    return hip, knee, ankle, ball, toe


def bone_table():
    """(name, head, tail, parent, connected, z_reference, deform)"""
    fwd = Vector((0, -1, 0))
    back = Vector((0, 1, 0))
    up = Vector((0, 0, 1))
    down = Vector((0, 0, -1))
    t = [
        ("root", (0, 0, 0), (0, 0, 0.25), None, False, fwd, False),
        ("pelvis", (0, 0, 1.00), (0, 0, 1.10), "root", False, fwd, True),
        ("spine_01", (0, 0, 1.10), (0, 0.005, 1.27), "pelvis", True, fwd, True),
        ("spine_02", (0, 0.005, 1.27), (0, 0.010, 1.43), "spine_01", True, fwd, True),
        ("spine_03", (0, 0.010, 1.43), (0, 0.010, 1.57), "spine_02", True, fwd, True),
        ("neck", (0, 0.006, 1.57), (0, -0.004, 1.69), "spine_03", False, fwd, True),
        ("head", (0, -0.004, 1.69), (0, -0.004, 1.99), "neck", True, fwd, True),
    ]
    for side, s in (("l", 1), ("r", -1)):
        sh, el, wr, tip, d = _arm_pts(s)
        t += [
            ("clavicle_" + side, (0.03 * s, 0.0, 1.535), (0.19 * s, 0.012, 1.53), "spine_03", False, up, True),
            ("upperarm_" + side, tuple(sh), tuple(el), "clavicle_" + side, False, back, True),
            ("lowerarm_" + side, tuple(el), tuple(wr), "upperarm_" + side, True, back, True),
            ("hand_" + side, tuple(wr), tuple(tip), "lowerarm_" + side, True, back, True),
        ]
        hip, knee, ankle, ball, toe = _leg_pts(s)
        t += [
            ("thigh_" + side, tuple(hip), tuple(knee), "pelvis", False, back, True),
            ("calf_" + side, tuple(knee), tuple(ankle), "thigh_" + side, True, back, True),
            ("foot_" + side, tuple(ankle), tuple(ball), "calf_" + side, True, down, True),
            ("ball_" + side, tuple(ball), tuple(toe), "foot_" + side, True, down, True),
        ]
        # grip socket: where the ball center sits when palmed by this hand (non-deforming)
        palm_n = Vector((-math.cos(ARM_ABDUCTION) * s, 0.0, -math.sin(ARM_ABDUCTION)))
        g = wr + d * 0.085 + palm_n * 0.135
        t.append(("grip_" + side, tuple(g), tuple(g + d * 0.05), "hand_" + side, False, back, False))
    return t


DEFORM_BONES = [b[0] for b in bone_table() if b[6]]


def build_armature(name="Armature"):
    data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = data.edit_bones
    for name_, head, tail, parent, connected, zref, deform in bone_table():
        b = eb.new(name_)
        b.head = head
        b.tail = tail
        if parent:
            b.parent = eb[parent]
            b.use_connect = connected
        b.align_roll(zref)
        b.use_deform = deform
    bpy.ops.object.mode_set(mode="OBJECT")
    data.display_type = "STICK"
    return arm


# ---------------------------------------------------------------------------
# Pose builder
# ---------------------------------------------------------------------------
def _frame_from_yz(y, zref):
    y = Vector(y).normalized()
    z = Vector(zref) - y * Vector(zref).dot(y)
    if z.length < 1e-6:
        z = Vector((0, 1, 0)) - y * y.y
        if z.length < 1e-6:
            z = Vector((0, 0, 1)) - y * y.z
    z.normalize()
    x = y.cross(z)
    x.normalize()
    return Matrix((x, y, z)).transposed()


def _frame_from_yx(y, xref):
    y = Vector(y).normalized()
    x = Vector(xref) - y * Vector(xref).dot(y)
    if x.length < 1e-6:
        x = Vector((1, 0, 0)) - y * y.x
    x.normalize()
    z = x.cross(y)
    z.normalize()
    return Matrix((x, y, z)).transposed()


class Poser:
    """Sets pose-bone rotations from intuitive targets. Positions are given in
    meters in armature space (character facing -Y) and scaled by `S` (armature
    units per meter, 100 after the rig is converted to centimeters)."""

    def __init__(self, arm, S=1.0):
        self.obj = arm
        self.S = S
        self.pb = arm.pose.bones
        for p in self.pb:
            p.rotation_mode = "QUATERNION"
        self._prev = {}

    # -- basics -------------------------------------------------------------
    def reset(self):
        for p in self.pb:
            p.location = (0, 0, 0)
            p.rotation_quaternion = (1, 0, 0, 0)
            p.scale = (1, 1, 1)
        self.update()

    def update(self):
        bpy.context.view_layer.update()

    def v(self, p):
        return Vector(p) * self.S

    def euler(self, name, rx=0.0, ry=0.0, rz=0.0):
        q = Euler((math.radians(rx), math.radians(ry), math.radians(rz)), "XYZ").to_quaternion()
        self.pb[name].rotation_quaternion = q

    def pelvis(self, dx=0.0, dy=0.0, dz=0.0, rx=0.0, ry=0.0, rz=0.0):
        pb = self.pb["pelvis"]
        rest = pb.bone.matrix_local.to_3x3()
        pb.location = rest.inverted() @ self.v((dx, dy, dz))
        self.euler("pelvis", rx, ry, rz)

    def spine(self, bend=0.0, twist=0.0, lean=0.0, weights=(0.3, 0.35, 0.35)):
        for name, w in zip(("spine_01", "spine_02", "spine_03"), weights):
            self.euler(name, bend * w, twist * w, lean * w)

    def head(self, nod=0.0, turn=0.0, tilt=0.0):
        self.euler("neck", nod * 0.4, turn * 0.4, tilt * 0.4)
        self.euler("head", nod * 0.6, turn * 0.6, tilt * 0.6)

    # -- aiming -------------------------------------------------------------
    def _set_world_rot(self, name, R):
        pb = self.pb[name]
        R_rest = pb.bone.matrix_local.to_3x3()
        if pb.parent:
            Mp = pb.parent.matrix.to_3x3().normalized()
            Rp_rest = pb.parent.bone.matrix_local.to_3x3()
            base = Mp @ Rp_rest.inverted() @ R_rest
        else:
            base = R_rest
        basis = base.inverted() @ R
        q = basis.to_quaternion()
        pb.rotation_quaternion = q

    def aim(self, name, direction, zref):
        self._set_world_rot(name, _frame_from_yz(direction, zref))
        self.update()

    def aim_x(self, name, direction, xref):
        self._set_world_rot(name, _frame_from_yx(direction, xref))
        self.update()

    def head_pos(self, name):
        return self.pb[name].head.copy()

    def tail_pos(self, name):
        return self.pb[name].tail.copy()

    # -- IK -----------------------------------------------------------------
    def _two_bone(self, upper, lower, target, pole, zsign):
        self.update()
        pu = self.pb[upper]
        pl = self.pb[lower]
        S0 = pu.head.copy()
        L1 = (pu.bone.tail_local - pu.bone.head_local).length
        L2 = (pl.bone.tail_local - pl.bone.head_local).length
        T = Vector(target)
        D = T - S0
        dist = max(min(D.length, (L1 + L2) * 0.9995), abs(L1 - L2) + 1e-4)
        Dn = D.normalized()
        a = (L1 * L1 - L2 * L2 + dist * dist) / (2.0 * dist)
        h = math.sqrt(max(L1 * L1 - a * a, 0.0))
        P = Vector(pole)
        P = P - Dn * P.dot(Dn)
        if P.length < 1e-6:
            P = Vector((0, 1, 0)) - Dn * Dn.y
        P.normalize()
        E = S0 + Dn * a + P * h
        W = S0 + Dn * dist
        self.aim(upper, E - S0, P * zsign)
        self.aim(lower, W - E, P * zsign)
        return E, W

    def arm(self, side, hand, elbow_pole=(0, 1, 0), fingers=None, palm=None):
        """hand: wrist target (meters, armature space). elbow_pole: direction the elbow points.
        fingers: direction of the hand bone; palm: palm normal direction."""
        s = 1 if side == "l" else -1
        E, W = self._two_bone("upperarm_" + side, "lowerarm_" + side, self.v(hand), Vector(elbow_pole), +1)
        if fingers is None:
            fingers = (W - E).normalized()
        if palm is None:
            palm = Vector((-s, 0, 0))
        palm = Vector(palm)
        # left palm normal = -X_local, right palm normal = +X_local
        self.aim_x("hand_" + side, Vector(fingers), palm * (-s))
        return W

    def leg(self, side, ankle, knee_pole=(0, -1, 0), foot_dir=None, toe_bend=0.0):
        s = 1 if side == "l" else -1
        self._two_bone("thigh_" + side, "calf_" + side, self.v(ankle), Vector(knee_pole), -1)
        if foot_dir is None:
            foot_dir = (0.0, -0.88, -0.47)
        self.aim_x("foot_" + side, Vector(foot_dir), Vector((1, 0, 0)))
        self.euler("ball_" + side, toe_bend, 0, 0)

    def clavicle(self, side, shrug=0.0, forward=0.0):
        # rx>0 shrugs up for both sides; rz swings forward (sign differs per side)
        s = 1 if side == "l" else -1
        self.euler("clavicle_" + side, shrug, 0.0, -forward * s)

    # -- keys ---------------------------------------------------------------
    def key(self, frame, bones=None):
        self.update()
        for pb in self.pb:
            if bones and pb.name not in bones:
                continue
            q = pb.rotation_quaternion.copy()
            prev = self._prev.get(pb.name)
            if prev is not None and prev.dot(q) < 0:
                q.negate()
                pb.rotation_quaternion = q
            self._prev[pb.name] = q.copy()
            pb.keyframe_insert("rotation_quaternion", frame=frame)
            if pb.name in ("pelvis", "root"):
                pb.keyframe_insert("location", frame=frame)

    def begin_action(self, name):
        ad = self.obj.animation_data or self.obj.animation_data_create()
        act = bpy.data.actions.new(name)
        act.use_fake_user = True
        ad.action = act
        self._prev = {}
        return act
