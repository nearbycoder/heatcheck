// Port of AHCCameraDirector: broadcast sideline camera with lead, dunk zoom, menu drift and shake.
import * as THREE from 'three';
import { V, clamp, finterp, lerp, perlin1D, toThree } from './consts.js';

export class CameraDirector {
  constructor(camera) {
    this.camera = camera;
    this.focus = V(0, 0, 150);
    this.zoom = 1;
    this.shakeAmt = 0;
    this.time = 0;
    this.snapNext = true;
    this.hfov = 56;
    this.loc = V();
    this.look = V();
  }

  snap() { this.snapNext = true; }
  shake(a) { this.shakeAmt = Math.max(this.shakeAmt, a); }

  tick(dt, g) {
    dt = Math.min(dt, 0.05);
    this.time += dt;
    const target = g.ball.pos.clone();
    if (g.possessionTeam >= 0 && g.phase === 'Live') {
      target.x += (g.attackHoop(g.possessionTeam) === 1 ? 1 : -1) * 260;
    }
    if (g.phase === 'Intro' || g.phase === 'TipOff') target.set(0, 0, 150);
    target.x = clamp(target.x, -860, 860);
    const jump = g.phase === 'Intro' || g.phase === 'TipOff';
    let want = jump ? 0.86 : 1;
    for (const c of g.players) {
      if (c.isDunking()) {
        want = 0.86;
        target.x = clamp(c.pos.x, -1000, 1000);
      }
    }
    if (g.inMenus()) want = 1.05;
    // portrait screens need to pull back to keep the court in frame
    const aspect = this.camera.aspect;
    const portraitPull = aspect < 1.3 ? clamp((1.3 - aspect) * 0.35, 0, 0.3) : 0;
    if (this.snapNext) {
      this.focus.copy(target);
      this.zoom = want;
      this.snapNext = false;
    }
    this.focus.x = finterp(this.focus.x, target.x, dt, 2.6);
    this.focus.y = finterp(this.focus.y, clamp(target.y, -400, 400), dt, 1.5);
    this.zoom = finterp(this.zoom, want, dt, 2.5);
    const z = this.zoom + portraitPull;
    const loc = this.loc.set(this.focus.x * 0.9, 1640 * z + this.focus.y * 0.15, 870 * z);
    const look = this.look.set(this.focus.x, this.focus.y * 0.35 - 40, 90 + (1 - this.zoom) * 280);
    if (g.inMenus()) loc.x += Math.sin(this.time * 0.15) * 250;
    this.shakeAmt = Math.max(0, this.shakeAmt - dt * 1.8);
    if (this.shakeAmt > 0) {
      const a = this.shakeAmt * this.shakeAmt * 14;
      loc.x += perlin1D(this.time * 23) * a;
      loc.y += perlin1D(this.time * 19 + 7) * a;
      loc.z += perlin1D(this.time * 29 + 3) * a;
    }
    const cam = this.camera;
    toThree(loc, cam.position);
    cam.lookAt(toThree(look, new THREE.Vector3()));
    // the original uses a horizontal FOV of 56 deg (narrowed slightly when zoomed)
    const hfov = this.hfov * lerp(1, this.zoom, 0.6);
    const vfov = 2 * Math.atan(Math.tan(hfov * Math.PI / 360) / Math.max(aspect, 1.0)) * 180 / Math.PI;
    if (Math.abs(cam.fov - vfov) > 0.01) {
      cam.fov = vfov;
      cam.updateProjectionMatrix();
    }
  }
}
