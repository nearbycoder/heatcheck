// Port of AHCArena: arena meshes, broadcast lighting rig, crowd excitement (animated fans in a
// vertex shader matching the Unreal material), arena flash and scrolling LED ribbons.
import * as THREE from 'three';
import { finterp, clamp } from './consts.js';

export class Arena {
  constructor(scene, arenaGltf, courtGltf, settings) {
    this.scene = scene;
    this.excitement = 0.2;
    this.target = 0.2;
    this.flashAmt = 0;
    this.time = 0;
    this.crowdUniforms = { uTime: { value: 0 }, uExcite: { value: 0.2 }, uAnimate: { value: 1 } };
    this.ledTextures = [];
    this.emissive = [];
    this.root = new THREE.Group();
    scene.add(this.root);

    const court = courtGltf.scene;
    court.traverse((o) => {
      if (o.isMesh) {
        o.receiveShadow = true;
        o.castShadow = false;
        const m = o.material;
        if (m.map) {
          m.map.anisotropy = 8;
          m.map.colorSpace = THREE.SRGBColorSpace;
        }
        if (/Court/.test(m.name)) {
          m.roughness = Math.min(m.roughness, 0.42);
          m.envMapIntensity = 0.4;
        }
      }
    });
    this.root.add(court);

    const arena = arenaGltf.scene;
    this.crowd = [];
    arena.traverse((o) => {
      if (!o.isMesh) return;
      o.castShadow = false;
      o.receiveShadow = false;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      for (const m of mats) {
        if (m.name === 'MI_Crowd') this.setupCrowd(o, m);
        if (m.emissive && (m.emissiveIntensity > 0) && m.emissive.getHex() !== 0) {
          this.emissive.push({ m, base: m.emissiveIntensity });
        }
        if (/LedRibbon|LedFacade|ScorerLed/.test(m.name) && m.emissiveMap) {
          m.emissiveMap.wrapS = THREE.RepeatWrapping;
          this.ledTextures.push(m.emissiveMap);
        }
        if (/LedRibbon|LedFacade|ScorerLed/.test(m.name) && m.map && !m.emissiveMap) {
          m.map.wrapS = THREE.RepeatWrapping;
          this.ledTextures.push(m.map);
        }
        if (m.map) m.map.anisotropy = 4;
      }
      if (/SM_Crowd/.test(o.name)) this.crowd.push(o);
    });
    this.root.add(arena);

    // ---- lighting rig: dark bowl, bright court
    this.hemi = new THREE.HemisphereLight(0x9aa4c8, 0x2a1a12, 0.45);
    scene.add(this.hemi);
    this.key = new THREE.DirectionalLight(0xfff1de, 2.3);
    this.key.position.set(-3, 30, 9);
    this.key.target.position.set(0, 0, 0);
    this.key.castShadow = true;
    const sc = this.key.shadow.camera;
    sc.left = -17; sc.right = 17; sc.top = 10; sc.bottom = -10; sc.near = 5; sc.far = 60;
    this.key.shadow.bias = -0.0004;
    this.key.shadow.normalBias = 0.02;
    scene.add(this.key, this.key.target);
    // four overhead banks over the court for that broadcast sheen
    this.banks = [];
    for (const [x, z] of [[-8, -4], [8, -4], [-8, 4], [8, 4]]) {
      const s = new THREE.SpotLight(0xfff4e6, 200, 40, 0.75, 0.6, 1.6);
      s.position.set(x, 18, z);
      s.target.position.set(x * 0.8, 0, z * 0.3);
      scene.add(s, s.target);
      this.banks.push(s);
    }
    this.fill = new THREE.DirectionalLight(0xffc9a0, 0.35);
    this.fill.position.set(0, 8, 30);
    scene.add(this.fill);
    this.applySettings(settings);
  }

  setupCrowd(mesh, m) {
    m.vertexColors = true;
    m.color.set(0xffffff);
    m.roughness = 0.85;
    const U = this.crowdUniforms;
    const hasFan = !!mesh.geometry.attributes._fan;
    m.onBeforeCompile = (shader) => {
      shader.uniforms.uTime = U.uTime;
      shader.uniforms.uExcite = U.uExcite;
      shader.uniforms.uAnimate = U.uAnimate;
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', `#include <common>
uniform float uTime; uniform float uExcite; uniform float uAnimate;
${hasFan ? 'attribute vec2 _fan;' : ''}`)
        .replace('#include <begin_vertex>', `#include <begin_vertex>
${hasFan ? `{
  float freq = 0.9 + 1.6 * uExcite;
  float h = abs(sin(6.2831853 * (uTime * freq + _fan.x))) * _fan.y * (3.0 + 24.0 * uExcite) * 0.01;
  transformed.y += h * uAnimate;
}` : ''}`);
    };
    m.customProgramCacheKey = () => `hc-crowd-${hasFan}`;
  }

  applySettings(s) {
    const q = s.quality;
    this.crowdUniforms.uAnimate.value = s.crowd ? 1 : 0;
    this.key.castShadow = !!s.shadows;
    const size = q >= 3 ? 4096 : q >= 2 ? 2048 : 1024;
    if (this.key.shadow.mapSize.x !== size) {
      this.key.shadow.mapSize.set(size, size);
      if (this.key.shadow.map) {
        this.key.shadow.map.dispose();
        this.key.shadow.map = null;
      }
    }
    for (const b of this.banks) b.visible = q >= 1;
  }

  excite(a) { this.target = clamp(Math.max(this.target, a), 0, 1); }
  flash(a) { this.flashAmt = Math.max(this.flashAmt, a); }

  tick(dt) {
    this.time += dt;
    this.excitement = finterp(this.excitement, this.target, dt, 6);
    this.target = Math.max(0.12, this.target - dt * 0.22);
    this.flashAmt = Math.max(0, this.flashAmt - dt * 2.5);
    this.crowdUniforms.uTime.value = this.time;
    this.crowdUniforms.uExcite.value = this.excitement;
    for (const t of this.ledTextures) t.offset.x = (t.offset.x + dt * 0.04) % 1;
    const boost = 1 + 0.6 * this.excitement + 1.5 * this.flashAmt;
    for (const e of this.emissive) e.m.emissiveIntensity = e.base * boost;
    this.key.intensity = 2.3 * (1 + this.flashAmt * 0.6);
    for (const b of this.banks) b.intensity = 200 * (1 + 0.25 * this.excitement + 0.8 * this.flashAmt);
  }
}
