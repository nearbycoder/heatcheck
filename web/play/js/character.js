// Port of AHCCharacter: movement, turbo, every action state, dunk flights with spin and
// flip variants, knockdowns, team colours, fire glow and the floor ring.
import * as THREE from 'three';
import { clone as skeletonClone } from 'three/addons/utils/SkeletonUtils.js';
import {
  HC, Anim, V, DEG, clamp, frand, lerp, frac, smoothstep, normalizeAxis, dist2D, distSq2D,
  safeNormal2D, size2D, yawOf, toThree, fromThree, yawToThree, randInt, randUnit,
} from './consts.js';
import { AnimPlayer } from './anim.js';
import { BallState, BallHold } from './ball.js';
import { HairMesh, Beard } from './roster.js';
import { makeInput, clearEdges } from './input.js';

const JumpShotSetTime = 13 / 30;
const JumpShotReleaseTime = 16 / 30;
const DunkSlamTime = 24 / 30;
const GRAVITY_SCALE = 2.0;
const MAX_ACCEL = 3400;
const BRAKING = 3800;
const FRICTION = 9;
const AIR_CONTROL = 0.15;

const isDribbleAnim = (a) => a === Anim.DribbleIdle || a === Anim.RunDribble;
const isGuardStep = (a) => a === Anim.ShuffleLeft || a === Anim.ShuffleRight || a === Anim.Backpedal;
const isStride = (a) => a === Anim.Run || a === Anim.Sprint || a === Anim.RunDribble || isGuardStep(a);

export const DunkStyle = { TwoHand: 0, Windmill: 1, Spin360: 2, Reverse: 3, Flip: 4 };

/** Which source mesh (SK_Player, SK_Hair_Afro, ...) a three object belongs to. */
function partKey(o) {
  for (let n = o; n; n = n.parent) {
    const m = /^(SK_[A-Za-z]+(?:_[A-Za-z]+)?(?:_[A-Z]+[0-9]?)?)/.exec(n.name || '');
    if (m) {
      const k = n.name.replace(/_\d+$/, '');
      if (/^SK_(Player|Hair_\w+|Beard_\w+|Headband|Wristbands|Num_[TOC]\d|JerseyText_[A-Z]{3})$/.test(k)) return k;
    }
  }
  return 'SK_Player';
}

const RING_VERT = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`;
const RING_FRAG = `
uniform vec3 uColor; uniform float uAlpha; uniform float uInner;
varying vec2 vUv;
void main(){
  float r = length(vUv - 0.5) * 2.0;
  float ring = smoothstep(uInner - 0.04, uInner, r) * (1.0 - smoothstep(0.94, 1.0, r));
  float fill = (1.0 - smoothstep(uInner - 0.06, uInner, r)) * 0.16;
  float a = (ring + fill) * uAlpha;
  if (a < 0.002) discard;
  gl_FragColor = vec4(uColor * (0.7 + ring * 0.6), a);
}`;

/** Adds a fresnel rim term (fire glow) to a standard material. */
function addRim(mat, rim) {
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uRim = rim.strength;
    shader.uniforms.uRimColor = rim.color;
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform float uRim;\nuniform vec3 uRimColor;')
      .replace('#include <emissivemap_fragment>',
        '#include <emissivemap_fragment>\n totalEmissiveRadiance += uRimColor * uRim * pow(1.0 - saturate(dot(normal, normalize(vViewPosition))), 2.2);');
  };
  mat.customProgramCacheKey = () => 'hc-rim';
}

export class Character {
  constructor(game, template, lib, scene) {
    this.game = game;
    this.team = 0;
    this.slot = 0;
    this.def = null;
    this.teamColor = new THREE.Color();
    this.human = false;
    this.humanIndex = -1;
    this.input = makeInput();
    this.turbo = 1;
    this.streak = 0;
    this.onFire = false;
    this.fireMakes = 0;
    this.stats = newStats();
    this.state = 'Free';
    this.stateTime = 0;
    this.stealCooldown = 0;
    this.shoveCooldown = 0;
    this.actionLock = 0;
    this.squeakCooldown = 0;
    // movement
    this.pos = V(0, 0, HC.PlayerHalfHeight);
    this.visualPos = V(0, 0, HC.PlayerHalfHeight);
    this.vel = V();
    this.yaw = 0;
    this.desiredYaw = 0;
    this.mode = 'walk';
    this.maxWalkSpeed = 600;
    this.pendingMove = V();
    this.guardingBall = false;
    // dunk
    this.dunkStart = V();
    this.dunkEnd = V();
    this.dunkDuration = 1;
    this.dunkApex = 100;
    this.dunkStyle = DunkStyle.TwoHand;
    this.alleyDunk = false;
    this.dunkBlocked = false;
    this.blockAttempted = false;
    this.dunkBaseYaw = 0;
    // shot
    this.launchTime = 0;
    this.apexTime = 0;
    this.releaseQueued = false;
    this.tapShot = false;
    this.shotReleased = false;
    this.releaseQuality = 0;
    // action targets
    this.actionTarget = null;
    this.actionAlley = false;
    this.actionDone = false;
    this.powerShove = false;
    this.fireAccum = 0;

    // ---- visuals
    this.root = new THREE.Group();          // capsule centre, yaw
    this.flip = new THREE.Group();          // dunk flip pivot
    this.model = skeletonClone(template);   // feet at origin, faces +Z
    this.model.position.y = -HC.PlayerHalfHeight / 100;
    this.root.add(this.flip);
    this.flip.add(this.model);
    scene.add(this.root);
    this.rim = { strength: { value: 0 }, color: { value: new THREE.Color(1, 0.42, 0.05) } };
    this.parts = new Map();
    this.mats = new Map();
    this.bones = new Map();
    const matCache = new Map();
    this.model.traverse((o) => {
      if (o.isBone) this.bones.set(o.name, o);
      if (o.isMesh || o.isSkinnedMesh) {
        o.frustumCulled = false;
        const key = partKey(o);
        if (!this.parts.has(key)) this.parts.set(key, []);
        this.parts.get(key).push(o);
        o.castShadow = key === 'SK_Player';
        o.receiveShadow = false;
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        const out = mats.map((m) => {
          let c = matCache.get(m);
          if (!c) {
            c = m.clone();
            addRim(c, this.rim);
            matCache.set(m, c);
            const base = (m.name || '').replace(/\.\d+$/, '');
            if (!this.mats.has(base)) this.mats.set(base, []);
            this.mats.get(base).push(c);
          }
          return c;
        });
        o.material = Array.isArray(o.material) ? out : out[0];
      }
    });
    this.anim = new AnimPlayer(this.model, lib, this.bones.get('head') || null);
    this.curAnim = '';

    // floor ring
    this.ringMat = new THREE.ShaderMaterial({
      uniforms: { uColor: { value: new THREE.Color(1, 1, 1) }, uAlpha: { value: 0.6 }, uInner: { value: 0.8 } },
      vertexShader: RING_VERT,
      fragmentShader: RING_FRAG,
      transparent: true,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -2,
    });
    this.ring = new THREE.Mesh(new THREE.PlaneGeometry(1.55, 1.55), this.ringMat);
    this.ring.rotation.x = -Math.PI / 2;
    this.ring.renderOrder = 2;
    scene.add(this.ring);
  }

  // ------------------------------------------------------------------ setup
  setup(team, slot, teamDef, def) {
    this.team = team;
    this.slot = slot;
    this.def = def;
    this.teamColor.set(teamDef.primary);
    this.stats = newStats();
    this.streak = 0;
    this.onFire = false;
    this.fireMakes = 0;
    this.turbo = 1;
    const show = new Set(['SK_Player']);
    if (HairMesh[def.hair]) show.add(HairMesh[def.hair]);
    if (def.beard === Beard.Full) show.add('SK_Beard_Full');
    if (def.beard === Beard.Goatee) show.add('SK_Beard_Goatee');
    if (def.headband) show.add('SK_Headband');
    if (def.wristbands) show.add('SK_Wristbands');
    const n = clamp(def.number, 0, 99);
    if (n >= 10) {
      show.add(`SK_Num_T${Math.floor(n / 10)}`);
      show.add(`SK_Num_O${n % 10}`);
    } else {
      show.add(`SK_Num_C${n}`);
    }
    show.add(`SK_JerseyText_${teamDef.abbr}`);
    for (const [k, list] of this.parts) for (const o of list) o.visible = show.has(k);
    this.model.scale.set(def.build, def.height, def.build);
    this.applyColors(teamDef);
    this.resetForPlay();
  }

  applyHeadScale(s) {
    this.anim.headScale = s;
  }

  applyColors(td) {
    const d = this.def;
    const set = (name, col) => {
      for (const m of this.mats.get(name) || []) m.color.set(col);
    };
    const white = new THREE.Color(0.92, 0.92, 0.92);
    set('MI_PlayerSkin', d.skin);
    set('MI_PlayerJersey', td.primary);
    set('MI_PlayerShorts', td.primary);
    set('MI_PlayerJerseyTrim', td.secondary);
    set('MI_PlayerShortsTrim', td.secondary);
    set('MI_PlayerSocks', white);
    set('MI_PlayerShoe', td.secondary);
    set('MI_PlayerShoeAccent', td.primary);
    set('MI_PlayerShoeSole', white);
    set('MI_PlayerHair', d.hairColor);
    set('MI_PlayerAccessory', td.accent);
    set('MI_PlayerNumber', td.secondary);
    set('MI_PlayerJerseyText', td.secondary);
    this.setFire(this.onFire);
  }

  setFire(f) {
    this.onFire = f;
    this.rim.strength.value = f ? 3.0 : 0;
  }

  resetForPlay() {
    this.state = 'Free';
    this.stateTime = 0;
    this.actionLock = 0;
    this.alleyDunk = false;
    this.dunkBlocked = false;
    const i = this.input;
    Object.assign(i, makeInput());
    this.mode = 'walk';
    this.pos.z = HC.PlayerHalfHeight;
    this.flip.rotation.set(0, 0, 0);
    this.flip.position.set(0, 0, 0);
    this.playAnim(Anim.Idle, true, 1, 0.1);
  }

  setLocation(x, y, z = HC.PlayerHalfHeight) {
    this.pos.set(x, y, z);
  }
  setYaw(y) {
    this.yaw = y;
    this.desiredYaw = y;
  }
  stop() {
    this.vel.set(0, 0, 0);
  }

  // ------------------------------------------------------------------ queries
  hasBall() {
    const b = this.game.ball;
    return b.state === BallState.Held && b.holder === this;
  }
  isAirborne() { return this.mode === 'fall' || this.isDunking(); }
  isFalling() { return this.mode === 'fall'; }
  isDown() { return this.state === 'KnockedDown' || this.state === 'GetUp'; }
  canReceiveBall() { return !this.isDown() && this.state !== 'Stagger' && this.state !== 'Shove'; }
  canAct() { return this.state === 'Free' && this.actionLock <= 0; }
  isShooting() { return this.state === 'ShootWindup' || this.state === 'ShootAir' || this.state === 'Layup'; }
  isDunking() { return this.state === 'DunkWindup' || this.state === 'DunkAir' || this.state === 'DunkHang'; }
  forward() { return V(Math.cos(this.yaw * DEG), Math.sin(this.yaw * DEG), 0); }
  right() { return V(-Math.sin(this.yaw * DEG), Math.cos(this.yaw * DEG), 0); }
  planar() { return { x: this.pos.x, y: this.pos.y }; }
  attackHoop() { return this.game.attackHoop(this.team); }

  /** Bone position in game space: last evaluated pose, carried along with this frame's movement. */
  bone(name) {
    const b = this.bones.get(name);
    if (!b) return this.pos.clone();
    const w = b.getWorldPosition(new THREE.Vector3());
    fromThree(w, w);
    return w.add(this.pos).sub(this.visualPos);
  }
  handsCenter() {
    return this.bone('grip_l').add(this.bone('grip_r')).multiplyScalar(0.5);
  }

  getBallHold() {
    switch (this.state) {
      case 'ShootWindup': case 'ShootAir': case 'Pass': case 'Inbound':
        return BallHold.TwoHands;
      case 'Layup':
        return this.stateTime < 0.22 ? BallHold.TwoHands : BallHold.RightHand;
      case 'DunkWindup': case 'DunkAir': case 'DunkHang':
        if (this.dunkStyle === DunkStyle.Windmill && this.state === 'DunkAir') return BallHold.RightHand;
        return BallHold.TwoHands;
      default: break;
    }
    if (this.curAnim === Anim.HoldBall) return BallHold.TwoHands;
    return BallHold.Dribble;
  }

  getDribblePhase() {
    if (isDribbleAnim(this.curAnim)) return frac(this.anim.getNormalizedTime());
    return frac(this.game.time * 1.8);
  }

  dunkRange() { return 430 + this.def.dunk * 30 + (this.onFire ? 120 : 0); }

  maxSpeed() {
    let s = 505 + this.def.speed * 14;
    if (this.hasBall()) s *= 0.94;
    if (this.input.turbo && (this.turbo > 0.02 || this.onFire)) s *= 1.4;
    return s;
  }

  playAnim(a, loop, rate = 1, blend = 0.15, start = 0, restart = false) {
    if (!restart && a !== this.curAnim && ((isDribbleAnim(a) && isDribbleAnim(this.curAnim)) || (isStride(a) && isStride(this.curAnim)))) {
      start = frac(this.anim.getNormalizedTime()) * this.anim.lib.length(a);
    }
    this.anim.play(a, loop, rate, blend, start, restart);
    this.curAnim = a;
  }

  // ------------------------------------------------------------------ movement primitives
  launch(v) {
    this.vel.copy(v);
    this.mode = 'fall';
  }

  setState(s) {
    this.state = s;
    this.stateTime = 0;
    this.actionDone = false;
  }

  faceTowards(p) {
    const dx = p.x - this.pos.x, dy = p.y - this.pos.y;
    if (dx * dx + dy * dy > 1) this.desiredYaw = Math.atan2(dy, dx) / DEG;
  }

  // ------------------------------------------------------------------ actions
  startJumpShot() {
    this.setState('ShootWindup');
    this.shotReleased = false;
    this.releaseQueued = false;
    this.tapShot = false;
    this.playAnim(Anim.JumpShot, false, 1, 0.08, 0, true);
    this.faceTowards(this.game.rimCenter(this.attackHoop()));
    this.vel.multiplyScalar(0.3);
  }

  startLayup() {
    this.setState('Layup');
    this.shotReleased = false;
    this.playAnim(Anim.Layup, false, 1.1, 0.06, 0, true);
    this.faceTowards(this.game.rimCenter(this.attackHoop()));
  }

  startDunk(alley = false) {
    const g = this.game;
    this.setState('DunkWindup');
    this.alleyDunk = alley;
    this.dunkBlocked = false;
    const rim = g.rimCenter(this.attackHoop());
    const d = dist2D(this.pos, rim);
    const r = Math.random();
    if (this.onFire && d > 300) this.dunkStyle = DunkStyle.Flip;
    else if (d < 260) this.dunkStyle = r < 0.75 ? DunkStyle.TwoHand : DunkStyle.Windmill;
    else if (d < 450) this.dunkStyle = r < 0.4 ? DunkStyle.Windmill : r < 0.75 ? DunkStyle.Spin360 : DunkStyle.TwoHand;
    else this.dunkStyle = r < 0.4 ? DunkStyle.Spin360 : r < 0.75 ? DunkStyle.Windmill : DunkStyle.Reverse;
    if (alley) this.dunkStyle = r < 0.5 ? DunkStyle.TwoHand : DunkStyle.Spin360;
    this.playAnim(this.dunkStyle === DunkStyle.Windmill ? Anim.DunkWindmill : Anim.Dunk, false, 1, 0.06, 0, true);
    this.faceTowards(rim);
    if (!this.onFire) this.turbo = Math.max(0, this.turbo - 0.12);
  }

  startPass(target, alley) {
    this.setState('Pass');
    this.actionTarget = target;
    this.actionAlley = alley;
    this.playAnim(Anim.Pass, false, 1.35, 0.06, 0, true);
    if (target) this.faceTowards(target.pos);
  }

  findShoveOpponent(facing, reach) {
    let best = null, bestScore = Infinity;
    for (const o of this.game.players) {
      if (o.team === this.team || o.isDown() || o.state === 'Stagger' || o.state === 'DunkAir' || o.state === 'DunkHang') continue;
      const dx = o.pos.x - this.pos.x, dy = o.pos.y - this.pos.y, dz = o.pos.z - this.pos.z;
      const dist = Math.hypot(dx, dy);
      const align = dist > 1e-3 ? (facing.x * dx + facing.y * dy) / dist : 0;
      const score = dist - align * 50;
      if (dist <= reach && Math.abs(dz) <= 64 && align >= 0.4 && score < bestScore) {
        best = o;
        bestScore = score;
      }
    }
    return best;
  }

  startShove(target) {
    if (!this.canAct() || this.isAirborne() || this.hasBall() || this.shoveCooldown > 0 || this.game.phase !== 'Live') return;
    const m = this.input.move;
    const aim = Math.hypot(m.x, m.y) < 1e-3 ? this.forward() : safeNormal2D(V(m.x, m.y, 0));
    if (!target) target = this.findShoveOpponent(aim, 155);
    const dir = target ? safeNormal2D(V(target.pos.x - this.pos.x, target.pos.y - this.pos.y, 0)) : aim;
    this.powerShove = this.onFire || (this.input.turbo && this.turbo >= 0.2);
    this.setState('Shove');
    this.shoveCooldown = 0.9;
    if (this.powerShove && !this.onFire) this.turbo = Math.max(0, this.turbo - 0.2);
    this.playAnim(Anim.Shove, false, 1.25, 0.05, 0, true);
    this.faceTowards(V(this.pos.x + dir.x * 100, this.pos.y + dir.y * 100, 0));
    this.vel.set(dir.x * 450, dir.y * 450, this.mode === 'walk' ? 0 : this.vel.z);
  }

  startSteal() {
    this.setState('Steal');
    this.stealCooldown = 0.55;
    this.playAnim(Anim.Steal, false, 1.3, 0.05, 0, true);
    const h = this.game.ball.getHolder();
    if (h) this.faceTowards(h.pos);
  }

  startBlock() {
    this.blockAttempted = false;
    this.setState('Block');
    this.playAnim(this.game.phase === 'TipOff' ? Anim.Tip : Anim.Block, false, 1, 0.05, 0, true);
  }

  takeShove(dir, speed, knockDown) {
    if (this.isDunking()) {
      this.flip.rotation.set(0, 0, 0);
      this.flip.position.set(0, 0, 0);
    }
    this.setState(knockDown ? 'KnockedDown' : 'Stagger');
    this.desiredYaw = yawOf(V(-dir.x, -dir.y, 0));
    this.yaw = this.desiredYaw;
    this.launch(V(dir.x * speed, dir.y * speed, knockDown ? 220 : 95));
    this.playAnim(knockDown ? Anim.Fall : Anim.Backpedal, !knockDown, 1, 0.05, 0, true);
  }

  celebrate() {
    if (this.state === 'Free') {
      this.setState('Celebrate');
      this.playAnim(Anim.Celebrate, false, 1, 0.1, 0, true);
    }
  }

  setInbound(on) {
    if (on) {
      this.setState('Inbound');
      this.playAnim(Anim.HoldBall, true, 1, 0.1);
    } else if (this.state === 'Inbound') {
      this.setState('Free');
    }
  }

  releaseShot() {
    if (this.state === 'ShootAir' && !this.shotReleased) {
      this.shotReleased = true;
      const off = Math.abs(this.game.time - this.apexTime);
      this.releaseQuality = 1 - clamp(off / 0.24, 0, 1);
      this.anim.setRate(clamp((JumpShotReleaseTime - this.anim.getTime()) / 0.065, 1, 3));
      this.game.releaseShot(this, this.releaseQuality, false);
    } else if (this.state === 'ShootWindup') {
      this.releaseQueued = true;
    }
  }

  onCaughtBall() {
    this.actionLock = 0.1;
  }

  // ------------------------------------------------------------------ tick
  tick(dt) {
    const g = this.game;
    this.stateTime += dt;
    this.actionLock -= dt;
    this.stealCooldown -= dt;
    this.shoveCooldown -= dt;
    this.squeakCooldown -= dt;

    if (this.state === 'Free' && g.isPlayLive()) {
      this.handleActionInput();
    } else if (this.state === 'Inbound' && this.input.passPressed && g.isPlayLive()) {
      const mate = g.teammate(this);
      if (mate) this.startPass(mate, false);
    }
    this.tickState(dt);
    this.tickMovement(dt);
    this.tickTurbo(dt);
    this.tickFacing(dt);
    if (this.state === 'Free') this.tickLocomotionAnim();
    this.tickFX(dt);

    if (this.state !== 'Inbound' && !this.isDunking()) {
      const MX = HC.CourtHalfLength + HC.BoundsMargin;
      const MY = HC.CourtHalfWidth + HC.BoundsMargin;
      if (Math.abs(this.pos.x) > MX || Math.abs(this.pos.y) > MY) {
        this.pos.x = clamp(this.pos.x, -MX, MX);
        this.pos.y = clamp(this.pos.y, -MY, MY);
      }
    }
    clearEdges(this.input);
  }

  handleActionInput() {
    if (!this.canAct()) return;
    const g = this.game;
    const b = g.ball;
    const mate = g.teammate(this);
    const inp = this.input;
    const turboOK = inp.turbo && (this.turbo > 0.05 || this.onFire);

    if (g.phase === 'TipOff') {
      if (inp.shootPressed && !this.isAirborne() && g.tipJumpers[this.team] === this && b.state === BallState.Loose) this.startBlock();
      return;
    }
    if (this.hasBall()) {
      if (inp.shootPressed) {
        const d = g.distToHoop(this.pos, this.attackHoop());
        if (turboOK && d < this.dunkRange()) this.startDunk(false);
        else if (d < 200) {
          if (this.def.dunk >= 7 && inp.turbo) this.startDunk(false);
          else this.startLayup();
        } else this.startJumpShot();
      } else if (inp.passPressed && mate && !mate.isDown()) {
        const alley = inp.turbo && mate.canAct() && !mate.hasBall() && g.distToHoop(mate.pos, this.attackHoop()) < mate.dunkRange() + 60;
        this.startPass(mate, alley);
      }
      return;
    }
    const holder = b.getHolder();
    const mateHas = holder && holder === mate;
    if (inp.shovePressed || (inp.passPressed && inp.turbo && !mateHas)) {
      this.startShove(null);
      return;
    }
    if (inp.passPressed) {
      if (mateHas) g.requestPass(mate, this);
      else if (this.stealCooldown <= 0) this.startSteal();
    }
    if (inp.shootPressed && this.state === 'Free') {
      if (mateHas) g.requestShot(mate);
      else if (!this.isAirborne()) this.startBlock();
    }
  }

  tickState(dt) {
    const g = this.game;
    const a = this.anim;
    switch (this.state) {
      case 'Free':
        break;

      case 'ShootWindup':
        if (!this.input.shootDown) {
          this.releaseQueued = true;
          if (this.stateTime < 0.12) this.tapShot = true;
        }
        if (this.stateTime >= 0.2) {
          const vz = 560;
          this.launch(V(this.vel.x * 0.25, this.vel.y * 0.25, vz));
          this.launchTime = g.time;
          this.apexTime = this.launchTime + vz / (HC.Gravity * GRAVITY_SCALE);
          this.setState('ShootAir');
          g.onJump(this);
        }
        break;

      case 'ShootAir':
        if (this.shotReleased && a.getTime() >= JumpShotReleaseTime) a.setRate(1);
        if (!this.shotReleased) {
          if (a.getTime() >= JumpShotSetTime) a.setRate(0);
          const now = g.time;
          const wants = this.tapShot ? now >= this.apexTime - 0.035
            : (!this.input.shootDown || (this.releaseQueued && now - this.launchTime > 0.08));
          const late = this.vel.z < -380;
          if ((wants && this.stateTime > 0.06) || late) this.releaseShot();
        }
        if (this.stateTime > 0.15 && this.mode !== 'fall') {
          if (!this.shotReleased) this.releaseShot();
          this.setState('Free');
        }
        break;

      case 'Layup':
        if (this.stateTime >= 0.1 && !this.actionDone) {
          this.actionDone = true;
          const rim = g.rimCenter(this.attackHoop());
          const dir = safeNormal2D(V(rim.x - this.pos.x, rim.y - this.pos.y, 0));
          const d = dist2D(rim, this.pos);
          const s = clamp(d * 1.4, 80, 320);
          this.launch(V(dir.x * s, dir.y * s, 560));
          g.onJump(this);
        }
        if (this.stateTime >= 0.36 && !this.shotReleased) {
          this.shotReleased = true;
          g.releaseShot(this, 0.85, true);
        }
        if (this.stateTime > 0.3 && this.mode !== 'fall') this.setState('Free');
        break;

      case 'DunkWindup': {
        const windup = this.alleyDunk ? 0.05 : 0.14;
        if (this.stateTime >= windup) {
          const rim = g.rimCenter(this.attackHoop());
          this.dunkStart.copy(this.pos);
          let app = safeNormal2D(V(rim.x - this.pos.x, rim.y - this.pos.y, 0));
          if (app.lengthSq() < 1e-6) {
            const f = g.hoopFacing(this.attackHoop());
            app = V(-f.x, -f.y, 0);
          }
          const d = dist2D(rim, this.dunkStart);
          const off = this.dunkStyle === DunkStyle.Reverse ? 46 : -46;
          this.dunkEnd.set(rim.x + app.x * off, rim.y + app.y * off, HC.RimZ + 18 - 158 * this.def.height + HC.PlayerHalfHeight);
          this.dunkDuration = clamp(0.48 + d / 950, 0.55, 1.15);
          if (this.alleyDunk && g.ball.state === BallState.Pass) {
            this.dunkDuration = Math.max(this.dunkDuration, g.ball.remainingPassTime() + 0.14);
          }
          this.dunkApex = 50 + d * 0.07;
          this.dunkBaseYaw = yawOf(app);
          this.mode = 'fly';
          this.vel.set(0, 0, 0);
          this.setState('DunkAir');
          g.dunkTakeoff(this);
        }
        break;
      }

      case 'DunkAir': {
        const lobInFlight = this.alleyDunk && g.ball.state === BallState.Pass && g.ball.passTo === this;
        if (this.dunkBlocked || (!this.hasBall() && !lobInFlight)) {
          this.dropFromDunk();
          break;
        }
        const T = clamp(this.stateTime / this.dunkDuration, 0, 1);
        const ease = T * T * (3 - 2 * T) * 0.35 + T * 0.65;
        const prev = this.pos.clone();
        this.pos.lerpVectors(this.dunkStart, this.dunkEnd, ease);
        this.pos.z = lerp(this.dunkStart.z, this.dunkEnd.z, T) + this.dunkApex * 4 * T * (1 - T);
        this.vel.copy(this.pos).sub(prev).divideScalar(Math.max(dt, 1e-3));
        let yaw = this.dunkBaseYaw;
        const S = smoothstep(0.05, 0.85, T);
        this.flip.rotation.set(0, 0, 0);
        if (this.dunkStyle === DunkStyle.Spin360) yaw += 360 * S;
        else if (this.dunkStyle === DunkStyle.Reverse) yaw += 180 * S;
        else if (this.dunkStyle === DunkStyle.Flip) this.flip.rotation.x = Math.PI * 2 * S;
        this.yaw = yaw;
        this.desiredYaw = yaw;
        a.setRate(0);
        const takeoff = this.alleyDunk ? 0.05 : 0.14;
        a.setTime(lerp(takeoff, DunkSlamTime, T));
        if (T >= 1) {
          this.flip.rotation.set(0, 0, 0);
          this.setState('DunkHang');
          a.setTime(DunkSlamTime);
          a.setRate(1);
          const had = this.hasBall();
          g.dunkSlam(this);
          if (!had || this.dunkBlocked) this.dropFromDunk();
        }
        break;
      }

      case 'DunkHang': {
        const rim = g.rimCenter(this.attackHoop());
        const f = this.forward();
        const anchor = V(rim.x - f.x * 16, rim.y - f.y * 16, rim.z);
        const wrist = this.dunkStyle === DunkStyle.Windmill ? this.bone('hand_r')
          : this.bone('hand_l').add(this.bone('hand_r')).multiplyScalar(0.5);
        const corr = anchor.sub(wrist).sub(V(0, 0, 7));
        const maxStep = 400 * dt;
        if (corr.length() > maxStep) corr.setLength(maxStep);
        this.pos.add(corr);
        if (this.stateTime >= 0.46) this.dropFromDunk();
        break;
      }

      case 'DunkLand':
        if (this.mode === 'walk' && a.getTime() >= 7 / 30) this.setState('Free');
        break;

      case 'Pass':
        if (this.stateTime >= 0.15 && !this.actionDone) {
          this.actionDone = true;
          if (this.hasBall()) g.releasePass(this, this.actionTarget, this.actionAlley);
        }
        if (this.stateTime >= 0.36) this.setState('Free');
        break;

      case 'Shove':
        if (this.stateTime >= 0.16 && !this.actionDone) {
          this.actionDone = true;
          g.resolveShove(this, this.findShoveOpponent(this.forward(), 112));
        }
        if (this.stateTime >= 0.5) this.setState('Free');
        break;

      case 'Steal':
        if (this.stateTime >= 0.13 && !this.actionDone) {
          this.actionDone = true;
          g.resolveSteal(this);
        }
        if (this.stateTime >= 0.38) this.setState('Free');
        break;

      case 'Block':
        if (this.stateTime >= 0.06 && !this.actionDone) {
          this.actionDone = true;
          this.launch(V(this.vel.x * 0.3, this.vel.y * 0.3, 660));
          g.onJump(this);
        }
        if (this.stateTime > 0.2 && this.mode !== 'fall') this.setState('Free');
        break;

      case 'Stagger':
        if (this.stateTime >= 0.32 && this.mode !== 'fall') this.setState('Free');
        break;

      case 'KnockedDown':
        if (this.stateTime >= 1.0 && this.mode !== 'fall') {
          this.setState('GetUp');
          this.playAnim(Anim.GetUp, false, 1.15, 0.1, 0, true);
        }
        break;

      case 'GetUp':
        if (this.stateTime >= 0.72) this.setState('Free');
        break;

      case 'Celebrate':
        if (this.stateTime > 0.9 && this.mode !== 'fall') this.setState('Free');
        break;

      case 'Inbound':
        this.vel.set(0, 0, 0);
        break;
    }
  }

  dropFromDunk() {
    this.flip.rotation.set(0, 0, 0);
    this.setState('DunkLand');
    const f = this.forward();
    this.launch(V(-f.x * 90, -f.y * 90, 0));
    this.playAnim(Anim.Land, false, 0, 0.14, 0, true);
  }

  tickMovement(dt) {
    const g = this.game;
    const handler = g.ball.getHolder();
    const m = this.input.move;
    let guarding = false;
    if (this.state === 'Free' && handler && handler.team !== this.team && g.isPlayLive() && !this.input.turbo
      && distSq2D(this.pos, handler.pos) < 380 * 380) {
      const ml = Math.hypot(m.x, m.y);
      const tx = handler.pos.x - this.pos.x, ty = handler.pos.y - this.pos.y;
      const tl = Math.hypot(tx, ty) || 1;
      const dot = ml > 1e-4 ? (m.x * tx + m.y * ty) / (ml * tl) : 0;
      guarding = dot < 0.65;
    }
    this.guardingBall = guarding;
    this.maxWalkSpeed = guarding ? this.maxSpeed() * 0.58 : this.maxSpeed();
    let scale = 0;
    switch (this.state) {
      case 'Free': scale = 1; break;
      case 'Pass': scale = 0.55; break;
      case 'Steal': scale = 0.6; break;
      case 'Celebrate': scale = 0.5; break;
      default: scale = 0;
    }
    let ax = 0, ay = 0, amag = 0;
    const ml = Math.hypot(m.x, m.y);
    if (scale > 0 && g.phase !== 'Intro' && g.phase !== 'TipOff' && ml > 1e-3) {
      amag = Math.min(1, ml) * scale;
      ax = m.x / ml;
      ay = m.y / ml;
    }
    // squeak on sharp cuts
    const sp2 = this.vel.x * this.vel.x + this.vel.y * this.vel.y;
    if (this.state === 'Free' && this.mode === 'walk' && this.squeakCooldown <= 0 && sp2 > 300 * 300 && ml * ml > 0.25) {
      const sp = Math.sqrt(sp2);
      if ((this.vel.x * m.x + this.vel.y * m.y) / (sp * ml) < 0.55) {
        g.audio.sfxVariant('S_Squeak', 4, 0.35, 0.1);
        this.squeakCooldown = 0.45;
      }
    }
    this.integrate(dt, ax, ay, amag);
  }

  /** Simplified CharacterMovementComponent: walking with acceleration/braking, falling with gravity. */
  integrate(dt, ax, ay, amag) {
    const v = this.vel;
    if (this.mode === 'fly') return;
    if (this.mode === 'walk') {
      if (amag > 0) {
        const max = this.maxWalkSpeed * amag;
        const sp = Math.hypot(v.x, v.y);
        const k = Math.min(dt * FRICTION, 1);
        v.x -= (v.x - ax * sp) * k;
        v.y -= (v.y - ay * sp) * k;
        v.x += ax * MAX_ACCEL * amag * dt;
        v.y += ay * MAX_ACCEL * amag * dt;
        const ns = Math.hypot(v.x, v.y);
        if (ns > max) {
          // over the cap (e.g. after a shove): brake down toward it instead of snapping
          const target = Math.max(max, sp - (BRAKING + FRICTION * sp) * dt);
          if (ns > target) { v.x *= target / ns; v.y *= target / ns; }
        }
      } else {
        const sp = Math.hypot(v.x, v.y);
        if (sp > 0) {
          const ns = Math.max(0, sp - (FRICTION * sp + BRAKING) * dt);
          v.x *= ns / sp;
          v.y *= ns / sp;
        }
      }
      v.z = 0;
      this.pos.x += v.x * dt;
      this.pos.y += v.y * dt;
      this.pos.z = HC.PlayerHalfHeight;
    } else {
      // falling
      v.z -= HC.Gravity * GRAVITY_SCALE * dt;
      if (amag > 0) {
        v.x += ax * MAX_ACCEL * AIR_CONTROL * amag * dt;
        v.y += ay * MAX_ACCEL * AIR_CONTROL * amag * dt;
      }
      this.pos.addScaledVector(v, dt);
      if (this.pos.z <= HC.PlayerHalfHeight && v.z <= 0) {
        this.pos.z = HC.PlayerHalfHeight;
        v.z = 0;
        this.mode = 'walk';
        this.landed();
      }
    }
  }

  landed() {
    if (this.state === 'DunkLand') this.anim.setRate(1);
    if (this.state === 'Celebrate' || this.state === 'Block' || this.state === 'ShootAir') {
      this.game.audio.sfxVariant('S_Squeak', 4, 0.25, 0.1);
    }
  }

  tickTurbo(dt) {
    if (this.onFire) { this.turbo = 1; return; }
    const using = this.input.turbo && size2D(this.vel) > 250 && this.state === 'Free';
    if (using) this.turbo = Math.max(0, this.turbo - dt * 0.36);
    else if (!this.input.turbo) this.turbo = Math.min(1, this.turbo + dt * 0.17);
  }

  tickFacing(dt) {
    const s = this.state;
    if (s === 'DunkAir' || s === 'DunkHang' || s === 'KnockedDown' || s === 'GetUp') return;
    const g = this.game;
    if (s === 'Free' || s === 'Celebrate') {
      if (this.guardingBall) this.faceTowards(g.ball.getHolder().pos);
      else if (size2D(this.vel) > 70) this.desiredYaw = yawOf(this.vel);
      else if (this.hasBall()) this.faceTowards(g.rimCenter(this.attackHoop()));
      else this.faceTowards(g.ball.pos);
    } else if (s === 'Inbound') {
      const mate = g.teammate(this);
      if (mate) this.faceTowards(mate.pos);
    }
    const diff = normalizeAxis(this.desiredYaw - this.yaw);
    const step = clamp(diff, -900 * dt, 900 * dt);
    this.yaw = normalizeAxis(this.yaw + step);
  }

  tickLocomotionAnim() {
    const g = this.game;
    const sp = size2D(this.vel);
    const moving = sp > (isStride(this.curAnim) ? 40 : 75);
    const stride = sp / this.def.build;
    if (this.hasBall()) {
      if (g.phase === 'Scored' || g.phase === 'Violation') this.playAnim(Anim.HoldBall, true, 1, 0.15);
      else if (moving) this.playAnim(Anim.RunDribble, true, clamp(stride / 365, 0.48, 2.25), 0.15);
      else this.playAnim(Anim.DribbleIdle, true, 1, 0.15);
      return;
    }
    if (moving) {
      const dir = safeNormal2D(this.vel);
      const r = this.right(), f = this.forward();
      const side = r.x * dir.x + r.y * dir.y;
      const fwd = f.x * dir.x + f.y * dir.y;
      if (this.guardingBall && fwd < 0.65) {
        const back = fwd < -0.7;
        const step = back ? Anim.Backpedal : side < 0 ? Anim.ShuffleLeft : Anim.ShuffleRight;
        this.playAnim(step, true, clamp(stride / (back ? 195 : 120), 0.45, 2.35), 0.12);
      } else if (this.input.turbo && sp > (this.curAnim === Anim.Sprint ? 570 : 625)) {
        this.playAnim(Anim.Sprint, true, clamp(stride / 543, 0.7, 1.65), 0.15);
      } else {
        this.playAnim(Anim.Run, true, clamp(stride / 397, 0.45, 1.85), 0.15);
      }
    } else {
      const defending = g.possessionTeam >= 0 && g.possessionTeam !== this.team && g.isPlayLive();
      this.playAnim(defending ? Anim.Defense : Anim.Idle, true, 1, 0.2);
    }
  }

  tickFX(dt) {
    const g = this.game;
    if (this.onFire) {
      this.fireAccum += dt * 40;
      const names = ['foot_l', 'foot_r', 'hand_l', 'hand_r'];
      const u = V();
      while (this.fireAccum >= 1) {
        this.fireAccum -= 1;
        const p = this.bone(names[randInt(0, 3)]).add(randUnit(u).multiplyScalar(6));
        g.fx.emit(p, V(0, 0, frand(80, 160)), frand(0.25, 0.45), frand(16, 26), 4, [1, 0.75, 0.3, 1], [0.9, 0.12, 0.02, 0], -50, 2);
      }
    }
    let c = this.teamColor, alpha = 0.55, inner = 0.8;
    if (this.human) {
      c = this.humanIndex === 0 ? HUMAN_COLORS[0] : HUMAN_COLORS[1];
      alpha = 0.95;
      inner = 0.7;
    }
    if (this.onFire) {
      c = FIRE_COLOR;
      alpha = 0.8 + 0.2 * Math.sin(g.time * 12);
    }
    this.ringMat.uniforms.uColor.value.copy(c);
    this.ringMat.uniforms.uAlpha.value = g.inMenus() ? alpha * 0.5 : alpha;
    this.ringMat.uniforms.uInner.value = inner;
  }

  /** Animate and place the model; called once per frame after gameplay. */
  updateVisual(dt) {
    this.anim.update(dt);
    toThree(this.pos, this.root.position);
    this.root.rotation.y = yawToThree(this.yaw);
    this.root.updateMatrixWorld(true);
    this.visualPos.copy(this.pos);
    this.ring.position.set(this.pos.x / 100, 0.015, this.pos.y / 100);
  }
}

const HUMAN_COLORS = [new THREE.Color(1, 0.85, 0.1), new THREE.Color(0.15, 0.75, 1)];
const FIRE_COLOR = new THREE.Color(1, 0.35, 0.02);

export function newStats() {
  return { points: 0, fgm: 0, fga: 0, tpm: 0, tpa: 0, dunks: 0, steals: 0, blocks: 0, shoves: 0, rebounds: 0, assists: 0 };
}
