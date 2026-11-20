// Port of UHCSpriteFX: a pooled additive billboard particle system (flames and sparks).
// Positions/velocities are in game space (cm); rendering converts to three space.
import * as THREE from 'three';
import { clamp, frand, randUnit, V } from './consts.js';

const VERT = /* glsl */`
attribute float aSize;
attribute vec4 aColor;
attribute float aSpin;
varying vec4 vColor;
varying float vSpin;
uniform float uScale;
void main() {
  vColor = aColor;
  vSpin = aSpin;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = aSize * uScale / max(0.1, -mv.z);
}`;
const FRAG = /* glsl */`
uniform sampler2D uMap;
varying vec4 vColor;
varying float vSpin;
void main() {
  vec2 p = gl_PointCoord - 0.5;
  float c = cos(vSpin), s = sin(vSpin);
  p = vec2(c * p.x - s * p.y, s * p.x + c * p.y) + 0.5;
  vec4 t = texture2D(uMap, p);
  float a = t.a * vColor.a;
  if (a < 0.003) discard;
  gl_FragColor = vec4(vColor.rgb * t.rgb * a * 1.6, 0.0);
}`;

export class SpriteFX {
  constructor(scene, map, max = 1600) {
    this.max = max;
    this.next = 0;
    this.p = [];
    for (let i = 0; i < max; i++) {
      this.p.push({ pos: V(), vel: V(), age: 0, life: 0, s0: 0, s1: 0, c0: [1, 1, 1, 1], c1: [1, 1, 1, 0], g: 0, drag: 0, spin: 0 });
    }
    const geo = new THREE.BufferGeometry();
    this.aPos = new Float32Array(max * 3);
    this.aSize = new Float32Array(max);
    this.aColor = new Float32Array(max * 4);
    this.aSpin = new Float32Array(max);
    geo.setAttribute('position', new THREE.BufferAttribute(this.aPos, 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute('aSize', new THREE.BufferAttribute(this.aSize, 1).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute('aColor', new THREE.BufferAttribute(this.aColor, 4).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute('aSpin', new THREE.BufferAttribute(this.aSpin, 1).setUsage(THREE.DynamicDrawUsage));
    geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e4);
    this.mat = new THREE.ShaderMaterial({
      uniforms: { uMap: { value: map }, uScale: { value: 600 } },
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    this.points = new THREE.Points(geo, this.mat);
    this.points.frustumCulled = false;
    this.points.renderOrder = 10;
    scene.add(this.points);
    this.geo = geo;
    this.alive = 0;
  }

  /** Pixels per metre at distance 1, from the camera projection and viewport height. */
  setViewport(heightPx, fovYDeg) {
    this.mat.uniforms.uScale.value = heightPx / (2 * Math.tan(fovYDeg * Math.PI / 360));
  }

  emit(pos, vel, life, size0, size1, c0, c1, gravity = 0, drag = 0) {
    const P = this.p[this.next];
    P.pos.copy(pos);
    P.vel.copy(vel);
    P.age = 0;
    P.life = Math.max(0.05, life);
    P.s0 = size0;
    P.s1 = size1;
    P.c0 = c0;
    P.c1 = c1;
    P.g = gravity;
    P.drag = drag;
    P.spin = frand(-2, 2);
    this.next = (this.next + 1) % this.max;
  }

  emitSparks(pos, count, speed, color) {
    const u = V();
    for (let i = 0; i < count; i++) {
      randUnit(u).multiplyScalar(speed * frand(0.4, 1)).add(V(0, 0, speed * 0.4));
      this.emit(pos, u, frand(0.4, 0.9), 9, 2, color, [color[0], color[1] * 0.4, 0, 0], 900, 1);
    }
  }

  tick(dt) {
    let alive = 0;
    const ap = this.aPos, as = this.aSize, ac = this.aColor, sp = this.aSpin;
    for (let i = 0; i < this.max; i++) {
      const P = this.p[i];
      if (P.life <= 0) {
        as[i] = 0;
        ac[i * 4 + 3] = 0;
        continue;
      }
      P.age += dt;
      P.vel.z -= P.g * dt;
      P.vel.multiplyScalar(Math.max(0, 1 - P.drag * dt));
      P.pos.addScaledVector(P.vel, dt);
      const t = clamp(P.age / P.life, 0, 1);
      const a = (P.c0[3] + (P.c1[3] - P.c0[3]) * t) * clamp((1 - t) * 3, 0, 1);
      const size = P.s0 + (P.s1 - P.s0) * t;
      if (P.age >= P.life) P.life = 0; else alive++;
      ap[i * 3] = P.pos.x / 100;
      ap[i * 3 + 1] = P.pos.z / 100;
      ap[i * 3 + 2] = P.pos.y / 100;
      as[i] = size / 100;
      ac[i * 4] = P.c0[0] + (P.c1[0] - P.c0[0]) * t;
      ac[i * 4 + 1] = P.c0[1] + (P.c1[1] - P.c0[1]) * t;
      ac[i * 4 + 2] = P.c0[2] + (P.c1[2] - P.c0[2]) * t;
      ac[i * 4 + 3] = a;
      sp[i] = P.spin * P.age;
    }
    this.alive = alive;
    for (const k of ['position', 'aSize', 'aColor', 'aSpin']) this.geo.attributes[k].needsUpdate = true;
  }
}
