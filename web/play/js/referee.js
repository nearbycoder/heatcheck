// Port of AHCReferee: lines up at centre court, poses the toss (the game samples the ball from
// the posed hands), follows through, then jogs to the sideline and tracks play.
import * as THREE from 'three';
import { HC, V, DEG, clamp, normalizeAxis, fromThree, toThree, yawToThree, yawOf } from './consts.js';
import { AnimPlayer } from './anim.js';

export class Referee {
  constructor(gltfScene, lib, scene) {
    this.root = new THREE.Group();
    this.model = gltfScene;
    this.root.add(this.model);
    scene.add(this.root);
    this.model.traverse((o) => {
      if (o.isMesh) { o.castShadow = true; o.frustumCulled = false; }
    });
    this.bones = new Map();
    this.model.traverse((o) => { if (o.isBone) this.bones.set(o.name, o); });
    this.anim = new AnimPlayer(this.model, lib);
    this.releaseTime = 27 / 30;
    this.pos = V(0, -36, 0);
    this.yaw = 0;
    this.sinceRelease = -1;
    this.onSideline = false;
    this.jogging = false;
    this.root.scale.setScalar(0.95);
  }

  place() {
    toThree(this.pos, this.root.position);
    // the official's mesh faces the actor's +Y in the original
    this.root.rotation.y = yawToThree(this.yaw + 90);
    this.root.updateMatrixWorld(true);
  }

  lineUp() {
    this.pos.set(0, -36, 0);
    this.yaw = 0;
    this.sinceRelease = -1;
    this.onSideline = false;
    this.jogging = false;
    this.anim.play('RefToss', false, 0, 0, 0, true);
    this.frozen = true;
  }

  poseToss(t) {
    this.anim.setTime(t);
    this.anim.update(0);
    this.place();
    const a = this.bones.get('grip_l').getWorldPosition(new THREE.Vector3());
    const b = this.bones.get('grip_r').getWorldPosition(new THREE.Vector3());
    return fromThree(a.add(b).multiplyScalar(0.5));
  }

  followThrough() {
    this.sinceRelease = 0;
    this.anim.setRate(1);
    this.frozen = false;
  }

  trackPlay(dt, ball) {
    if (this.sinceRelease < 0) return;
    this.sinceRelease += dt;
    if (this.sinceRelease < 0.48) return;
    const sideline = -HC.CourtHalfWidth - 48;
    const target = V(this.onSideline ? clamp(ball.x * 0.62, -740, 740) : 0, sideline, 0);
    const tx = target.x - this.pos.x, ty = target.y - this.pos.y;
    const dist = Math.hypot(tx, ty);
    this.jogging = dist > (this.jogging ? 16 : 150);
    this.onSideline = this.onSideline || Math.abs(this.pos.y - sideline) < 17;
    const facing = this.jogging ? { x: tx, y: ty } : { x: ball.x - this.pos.x, y: ball.y - this.pos.y };
    const want = yawOf(facing) - 90;
    const diff = normalizeAxis(want - this.yaw);
    const step = 380 * dt;
    this.yaw = normalizeAxis(this.yaw + clamp(diff, -step, step));
    if (this.jogging) {
      const speed = clamp(dist * 4, 115, 405);
      const m = Math.min(dist, speed * dt);
      this.pos.x += tx / dist * m;
      this.pos.y += ty / dist * m;
      this.anim.play('Run', true, speed / 350);
    } else {
      this.anim.play('Idle', true);
    }
  }

  updateVisual(dt) {
    if (!this.frozen) this.anim.update(dt);
    this.place();
  }
}
export { DEG };
