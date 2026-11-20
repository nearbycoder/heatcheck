// Port of UHCAnimInstance: a two-slot clip player with smoothstep crossfades, explicit
// time / rate control (the game freezes and scrubs clips for jump shots and dunks) and
// big-head scaling. Built on THREE.AnimationMixer with manual time stepping.
import * as THREE from 'three';

function advance(t, dt, rate, len, loop) {
  t += dt * rate;
  if (len <= 1e-4) return 0;
  if (loop) {
    t %= len;
    if (t < 0) t += len;
  } else {
    t = Math.min(Math.max(t, 0), len);
  }
  return t;
}

/** Shared clip library: two copies of every clip so one clip can crossfade with itself. */
export class ClipLibrary {
  constructor(clips) {
    this.sets = [new Map(), new Map()];
    for (const c of clips) {
      this.sets[0].set(c.name, c);
      const b = c.clone();
      b.name = c.name;
      this.sets[1].set(c.name, b);
    }
  }
  has(name) { return this.sets[0].has(name); }
  length(name) { const c = this.sets[0].get(name); return c ? c.duration : 0; }
}

export class AnimPlayer {
  constructor(root, lib, headBone = null) {
    this.lib = lib;
    this.mixer = new THREE.AnimationMixer(root);
    this.actions = [new Map(), new Map()];
    this.cur = null;   // { name, set, action, time, rate, loop, len }
    this.prev = null;
    this.alpha = 1;
    this.blendDuration = 0.15;
    this.headBone = headBone;
    this.headScale = 1;
  }

  _action(set, name) {
    let a = this.actions[set].get(name);
    if (!a) {
      const clip = this.lib.sets[set].get(name);
      if (!clip) return null;
      a = this.mixer.clipAction(clip);
      a.setLoop(THREE.LoopRepeat, Infinity);
      a.clampWhenFinished = true;
      this.actions[set].set(name, a);
    }
    return a;
  }

  play(name, loop, rate = 1, blend = 0.15, start = 0, restart = false) {
    if (!this.lib.has(name)) return;
    if (this.cur && this.cur.name === name && !restart) {
      this.cur.loop = loop;
      this.cur.rate = rate;
      return;
    }
    if (this.prev) this.prev.action.stop();
    const set = this.cur ? 1 - this.cur.set : 0;
    if (this.cur && blend > 0) {
      this.prev = this.cur;
      this.alpha = 0;
      this.blendDuration = blend;
    } else {
      if (this.cur) this.cur.action.stop();
      this.prev = null;
      this.alpha = 1;
    }
    const action = this._action(set, name);
    action.reset();
    action.play();
    action.paused = true;
    this.cur = { name, set, action, time: start, rate, loop, len: this.lib.length(name) };
  }

  get name() { return this.cur ? this.cur.name : ''; }
  getLength() { return this.cur ? this.cur.len : 0; }
  getTime() { return this.cur ? this.cur.time : 0; }
  getNormalizedTime() { return this.cur && this.cur.len > 0 ? this.cur.time / this.cur.len : 0; }
  setRate(r) { if (this.cur) this.cur.rate = r; }
  setTime(t) { if (this.cur) this.cur.time = Math.min(Math.max(t, 0), this.cur.len); }
  isFinished() { return this.cur && !this.cur.loop && this.cur.time >= this.cur.len - 1e-4; }

  update(dt) {
    const c = this.cur;
    if (!c) return;
    c.time = advance(c.time, dt, c.rate, c.len, c.loop);
    const p = this.prev;
    if (p && this.alpha < 1) {
      p.time = advance(p.time, dt, p.rate, p.len, p.loop);
      this.alpha = Math.min(1, this.alpha + dt / Math.max(0.01, this.blendDuration));
      if (this.alpha >= 1) {
        p.action.stop();
        this.prev = null;
      }
    }
    const a = Math.min(Math.max(this.alpha, 0), 1);
    const w = a * a * (3 - 2 * a);
    c.action.enabled = true;
    c.action.time = c.time;
    c.action.setEffectiveWeight(this.prev ? w : 1);
    if (this.prev) {
      this.prev.action.enabled = true;
      this.prev.action.time = this.prev.time;
      this.prev.action.setEffectiveWeight(1 - w);
    }
    this.mixer.update(0);
    if (this.headBone) this.headBone.scale.setScalar(this.headScale);
  }
}
