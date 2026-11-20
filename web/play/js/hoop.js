// Port of AHCHoop: rim shake, net swish, flaming net and glass sparks.
import * as THREE from 'three';
import { HC, V, frand, lerp } from './consts.js';

export class Hoop {
  constructor(index, template, scene, fx) {
    this.index = index;
    this.fx = fx;
    this.root = template.clone(true);
    this.root.position.set((index === 0 ? -HC.RimX : HC.RimX) / 100, 0, 0);
    this.root.rotation.y = index === 0 ? 0 : Math.PI;
    scene.add(this.root);
    this.rim = this.root.getObjectByName('SM_Rim');
    this.net = this.root.getObjectByName('SM_Net');
    // the net hangs from the rim in the original, so it follows the rim shake
    if (this.rim && this.net) {
      this.rim.attach(this.net);
    }
    this.root.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = o.name !== 'SM_Net' && o.name !== 'SM_Backboard';
        o.receiveShadow = false;
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        for (const m of mats) {
          if (/Glass/.test(m.name)) {
            m.transparent = true;
            m.depthWrite = false;
            if (m.opacity > 0.5) m.opacity = 0.22;
          }
          if (/Net/.test(m.name)) {
            m.side = THREE.DoubleSide;
            m.alphaTest = Math.max(m.alphaTest || 0, 0.3);
          }
        }
        o.material = Array.isArray(o.material) ? mats.map((m) => m.clone()) : o.material.clone();
      }
    });
    this.netBaseScale = this.net ? this.net.scale.clone() : new THREE.Vector3(1, 1, 1);
    this.ledMats = [];
    this.root.traverse((o) => {
      if (o.isMesh) {
        for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
          if (/BackboardLED/.test(m.name)) this.ledMats.push({ m, base: m.emissiveIntensity || 1 });
        }
      }
    });
    this.shakeAmt = 0;
    this.shakeT = 10;
    this.swishAmt = 0;
    this.swishT = 10;
    this.fireTime = 0;
    this.fireAccum = 0;
    this.led = 0;
  }

  rimCenter() { return V(this.index === 0 ? -HC.RimX : HC.RimX, 0, HC.RimZ); }
  facing() { return V(this.index === 0 ? 1 : -1, 0, 0); }
  shake(a) { this.shakeAmt = a; this.shakeT = 0; }
  swish(a) { this.swishAmt = a; this.swishT = 0; this.led = 1; }
  setNetFire(s) { this.fireTime = Math.max(this.fireTime, s); }
  flashGlass() {
    const c = this.rimCenter();
    this.fx.emitSparks(V(c.x + (this.index === 0 ? -30 : 30), 0, c.z + 40), 40, 500, [0.6, 0.8, 1, 1]);
  }

  tick(dt) {
    this.shakeT += dt;
    this.swishT += dt;
    const pitch = -this.shakeAmt * Math.sin(this.shakeT * 34) * Math.exp(-this.shakeT * 4);
    if (this.rim) this.rim.rotation.z = pitch * Math.PI / 180;
    const sw = this.swishAmt * Math.sin(this.swishT * 20) * Math.exp(-this.swishT * 4.5);
    if (this.net) {
      const b = this.netBaseScale;
      this.net.scale.set(b.x * (1 - 0.22 * sw), b.y * (1 + 0.5 * sw), b.z * (1 - 0.22 * sw));
    }
    this.led = Math.max(0, this.led - dt * 0.8);
    for (const { m, base } of this.ledMats) m.emissiveIntensity = base * (1 + 3 * this.led + (this.fireTime > 0 ? 2 : 0));
    if (this.fireTime > 0) {
      this.fireTime -= dt;
      this.fireAccum += dt * 110;
      const c = this.rimCenter();
      const p = V(), v = V();
      while (this.fireAccum >= 1) {
        this.fireAccum -= 1;
        const a = frand(0, Math.PI * 2);
        const z = frand(-40, 2);
        const r = lerp(14, 24, (z + 40) / 42);
        p.set(c.x + Math.cos(a) * r, c.y + Math.sin(a) * r, c.z + z);
        v.set(0, 0, frand(90, 220));
        this.fx.emit(p, v, frand(0.3, 0.6), frand(22, 36), 6, [1, 0.8, 0.35, 1], [1, 0.15, 0.02, 0], -80, 1.5);
      }
    }
  }
}
