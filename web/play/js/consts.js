// Court geometry and shared helpers.
// Gameplay runs in the same space as the Unreal original: centimetres, X along the court,
// Y across it, Z up. The renderer converts with toThree(): three = (x, z, y) / 100.
import * as THREE from 'three';

export const HC = {
  CourtHalfLength: 1432.5,
  CourtHalfWidth: 762,
  RimX: 1272.5,
  RimZ: 305,
  RimRadius: 22.86,
  RimTube: 1.0,
  BackboardX: 1310.5,
  BackboardHalfWidth: 91.5,
  BackboardBottom: 290,
  BackboardTop: 397,
  BallRadius: 12,
  ThreeRadius: 724,
  ThreeCornerY: 670,
  Gravity: 980,
  PlayerHalfHeight: 100,
  PlayerRadius: 38,
  BoundsMargin: 70,
  ShotClockLength: 24,
};

export const Anim = {
  Idle: 'Idle', Defense: 'Defense', DribbleIdle: 'DribbleIdle', Run: 'Run', Sprint: 'Sprint',
  RunDribble: 'RunDribble', HoldBall: 'HoldBall', JumpShot: 'JumpShot', Layup: 'Layup', Dunk: 'Dunk',
  DunkWindmill: 'DunkWindmill', Pass: 'Pass', Shove: 'Shove', Steal: 'Steal', Block: 'Block', Fall: 'Fall',
  GetUp: 'GetUp', Celebrate: 'Celebrate', ShuffleLeft: 'ShuffleLeft', ShuffleRight: 'ShuffleRight',
  Backpedal: 'Backpedal', Land: 'Land', Tip: 'Tip',
};

export const V = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);

const _t = new THREE.Vector3();
/** game-space (cm, Z up) -> three-space (m, Y up). Writes into out (or a new vector). */
export function toThree(p, out = new THREE.Vector3()) {
  return out.set(p.x / 100, p.z / 100, p.y / 100);
}
export function fromThree(p, out = new THREE.Vector3()) {
  return out.set(p.x * 100, p.z * 100, p.y * 100);
}
/** Unreal yaw (degrees, 0 = +X, 90 = +Y) -> three rotation.y for a model that faces +Z. */
export function yawToThree(yawDeg) {
  return Math.PI / 2 - yawDeg * DEG;
}

export const DEG = Math.PI / 180;
export const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
export const lerp = (a, b, t) => a + (b - a) * t;
export const frand = (a, b) => a + Math.random() * (b - a);
export const randInt = (a, b) => a + Math.floor(Math.random() * (b - a + 1));
export const frac = (v) => v - Math.floor(v);
export const smoothstep = (a, b, x) => {
  const t = clamp((x - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};
export function finterp(cur, target, dt, speed) {
  if (speed <= 0) return target;
  const d = target - cur;
  if (d * d < 1e-8) return target;
  return cur + d * clamp(dt * speed, 0, 1);
}
export function normalizeAxis(deg) {
  deg = ((deg + 180) % 360 + 360) % 360 - 180;
  return deg;
}
export function dist2D(a, b) {
  const dx = a.x - b.x, dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}
export function distSq2D(a, b) {
  const dx = a.x - b.x, dy = a.y - b.y;
  return dx * dx + dy * dy;
}
/** Planar unit direction (z = 0); zero vector if degenerate. */
export function safeNormal2D(v, out = new THREE.Vector3()) {
  const l = Math.hypot(v.x, v.y);
  if (l < 1e-4) return out.set(0, 0, 0);
  return out.set(v.x / l, v.y / l, 0);
}
export function size2D(v) {
  return Math.hypot(v.x, v.y);
}
export function yawOf(v) {
  return Math.atan2(v.y, v.x) / DEG;
}
export function randUnit(out = new THREE.Vector3()) {
  const u = Math.random() * 2 - 1;
  const a = Math.random() * Math.PI * 2;
  const s = Math.sqrt(1 - u * u);
  return out.set(s * Math.cos(a), s * Math.sin(a), u);
}
export const tmp = _t;

/** Simple 1D gradient noise in [-1, 1] for camera shake. */
export function perlin1D(x) {
  const i = Math.floor(x);
  const f = x - i;
  const g = (n) => {
    const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
    return (s - Math.floor(s)) * 2 - 1;
  };
  const u = f * f * (3 - 2 * f);
  return lerp(g(i) * f, g(i + 1) * (f - 1), u) * 2;
}
