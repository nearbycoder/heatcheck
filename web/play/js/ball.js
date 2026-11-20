// Port of AHCBall: analytic ball physics (torus rim, backboard, floor, net drag), scripted
// makes and misses, synced dribbling, homing passes and the fire trail.
import * as THREE from 'three';
import { HC, V, clamp, frand, lerp, dist2D, safeNormal2D, size2D, toThree } from './consts.js';

export const BallState = { Official: 0, Held: 1, Shot: 2, Pass: 3, Loose: 4, Dead: 5 };
export const BallHold = { Dribble: 0, TwoHands: 1, RightHand: 2 };

const G = V(0, 0, -HC.Gravity);
const _a = V(), _b = V(), _c = V();

export class Ball {
  constructor(game, mesh, fx) {
    this.game = game;
    this.mesh = mesh;
    this.fx = fx;
    this.state = BallState.Loose;
    this.holder = null;
    this.vel = V();
    this.pos = V(0, 0, 200);
    this.dribblePrev = 0;
    this.shooter = null;
    this.lastShooter = null;
    this.lastTouchTeam = -1;
    this.shotHoop = 0;
    this.shotPoints = 2;
    this.shotMake = false;
    this.shotFire = false;
    this.shotScored = false;
    this.rimTouched = false;
    this.analytic = false;
    this.shotT = 0;
    this.shotDuration = 1;
    this.shotStart = V();
    this.shotV0 = V();
    this.netDrag = 0;
    this.passFrom = null;
    this.passTo = null;
    this.alley = false;
    this.alleyPoint = V();
    this.passStart = V();
    this.passT = 0;
    this.passDuration = 0.5;
    this.interceptTried = new Set();
    this.spin = new THREE.Quaternion();
    this.soundCooldown = 0;
    this.fireAccum = 0;
    this.sinceShot = 100;
    this.fireTrail = false;
  }

  get holderTeam() { return this.holder ? this.holder.team : -1; }
  getHolder() { return this.state === BallState.Held ? this.holder : null; }
  isDescending() { return this.vel.z < 0; }
  remainingPassTime() { return Math.max(0, this.passDuration - this.passT); }

  giveTo(c) {
    if (!c) return;
    this.state = BallState.Held;
    this.holder = c;
    this.passFrom = this.passTo = null;
    this.alley = false;
    this.vel.set(0, 0, 0);
    this.lastTouchTeam = c.team;
    this.fireTrail = c.onFire;
    this.dribblePrev = 0;
    this.netDrag = 0;
  }

  setLoose(v, toucher = null) {
    this.state = BallState.Loose;
    this.holder = this.passFrom = this.passTo = null;
    this.vel.copy(v);
    this.analytic = false;
    if (toucher) this.lastTouchTeam = toucher.team;
  }

  setDead() {
    this.state = BallState.Dead;
    this.holder = this.passFrom = this.passTo = null;
    this.analytic = false;
    this.fireTrail = false;
  }

  launchShot(shooter, hoop, points, make, fire, flight, target) {
    this.state = BallState.Shot;
    this.holder = null;
    this.shooter = shooter;
    this.lastShooter = shooter;
    this.lastTouchTeam = shooter ? shooter.team : -1;
    this.shotHoop = hoop;
    this.shotPoints = points;
    this.shotMake = make;
    this.shotFire = fire;
    this.shotScored = false;
    this.rimTouched = false;
    this.analytic = true;
    this.shotT = 0;
    this.sinceShot = 0;
    this.shotDuration = Math.max(0.25, flight);
    this.shotStart.copy(this.pos);
    const T = this.shotDuration;
    // v0 = (target - start)/T - 0.5 g T
    this.shotV0.copy(target).sub(this.shotStart).divideScalar(T).addScaledVector(G, -0.5 * T);
    this.vel.copy(this.shotV0);
    this.fireTrail = fire;
  }

  launchPass(from, to, alley, alleyPoint) {
    this.state = BallState.Pass;
    this.holder = null;
    this.passFrom = from;
    this.passTo = to;
    this.alley = alley;
    this.alleyPoint.copy(alleyPoint);
    this.passStart.copy(this.pos);
    this.passT = 0;
    const dest = alley ? this.alleyPoint.clone() : to.handsCenter().addScaledVector(to.vel, 0.2);
    const d = dest.distanceTo(this.passStart);
    this.passDuration = alley ? clamp(d / 1000, 0.55, 1.05) : clamp(d / 1500, 0.18, 0.85);
    this.interceptTried.clear();
    this.lastTouchTeam = from ? from.team : this.lastTouchTeam;
    this.fireTrail = !!(from && from.onFire);
  }

  dunkThrough(hoop) {
    const r = this.game.rimCenter(hoop);
    this.state = BallState.Loose;
    this.holder = null;
    this.pos.copy(r).add(_a.set(0, 0, 6));
    this.vel.set(0, 0, -520);
    this.shotScored = true;
    this.analytic = false;
    this.netDrag = 0.35;
    this.shotHoop = hoop;
  }

  holdForTip(grip) {
    if (this.state !== BallState.Official) {
      this.setDead();
      this.state = BallState.Official;
      this.vel.set(0, 0, 0);
      this.lastTouchTeam = -1;
      this.lastShooter = null;
      this.shooter = null;
      this.rimTouched = false;
      this.alley = false;
      this.netDrag = 0;
    }
    this.pos.copy(grip);
  }

  toss(from, up) {
    this.state = BallState.Loose;
    this.holder = null;
    this.pos.copy(from);
    this.vel.set(0, 0, up);
    this.lastShooter = null;
    this.shotScored = true;
    this.analytic = false;
    this.fireTrail = false;
  }

  deflect(v, by) {
    this.state = BallState.Loose;
    this.holder = null;
    this.vel.copy(v);
    this.analytic = false;
    this.shotScored = true;
    this.lastShooter = null;
    if (by) this.lastTouchTeam = by.team;
  }

  predictRebound() {
    if (this.state === BallState.Shot) {
      const r = this.game.rimCenter(this.shotHoop);
      const f = this.game.hoopFacing(this.shotHoop);
      return V(r.x + f.x * 160, r.y + f.y * 160, 0);
    }
    const p = this.pos.clone(), v = this.vel.clone();
    for (let i = 0; i < 60; i++) {
      const h = 0.03;
      v.addScaledVector(G, h);
      p.addScaledVector(v, h);
      if (v.z < 0 && p.z < 180) break;
    }
    return V(p.x, p.y, 0);
  }

  tick(dtIn) {
    const dt = Math.min(dtIn, 1 / 20);
    this.soundCooldown -= dt;
    this.sinceShot += dt;
    switch (this.state) {
      case BallState.Official: break;
      case BallState.Held: this.updateHeld(dt); break;
      case BallState.Shot: this.updateShot(dt); break;
      case BallState.Pass: this.updatePass(dt); break;
      default: this.stepPhysics(dt, true); break;
    }
    this.spinVisual(dt);
    if (this.fireTrail && this.state !== BallState.Dead && this.state !== BallState.Official) {
      this.fireAccum += dt * 90;
      const back = _b;
      const vl = this.vel.length();
      while (this.fireAccum >= 1) {
        this.fireAccum -= 1;
        if (vl > 1) back.copy(this.vel).multiplyScalar(-frand(0, 10) / vl); else back.set(0, 0, 0);
        this.fx.emit(
          _a.copy(this.pos).add(back).add(_c.set(frand(-6, 6), frand(-6, 6), frand(-6, 6))),
          _c.set(-this.vel.x * 0.08, -this.vel.y * 0.08, frand(60, 160) - this.vel.z * 0.08),
          frand(0.25, 0.5), frand(24, 34), 6, [1, 0.78, 0.3, 1], [0.9, 0.15, 0.02, 0], -60, 2);
      }
    }
  }

  /** Called after characters have been animated so the dribble follows this frame's hand. */
  syncVisual() {
    toThree(this.pos, this.mesh.position);
    this.mesh.quaternion.copy(this.spin);
  }

  updateHeld(dt) {
    const h = this.holder;
    if (!h) { this.state = BallState.Loose; return; }
    this.fireTrail = h.onFire;
    const hold = h.getBallHold();
    const target = _a;
    if (hold === BallHold.Dribble) {
      const hand = h.bone('grip_r');
      const t = h.getDribblePhase();
      const floorZ = HC.BallRadius;
      const handZ = Math.max(hand.z, floorZ + 30);
      let z;
      if (t < 0.45) {
        const k = t / 0.45;
        z = handZ + (floorZ - handZ) * k * k;
      } else {
        const k = (t - 0.45) / 0.55;
        z = floorZ + (handZ - floorZ) * (1 - (1 - k) * (1 - k));
      }
      if (this.dribblePrev < 0.45 && t >= 0.45) this.game.onBallBounce(300);
      this.dribblePrev = t;
      const lead = 0.05 * (1 - (2 * t - 1) * (2 * t - 1));
      target.set(hand.x + h.vel.x * lead, hand.y + h.vel.y * lead, z);
    } else if (hold === BallHold.TwoHands) {
      target.copy(h.handsCenter());
    } else {
      target.copy(h.bone('grip_r'));
    }
    this.vel.copy(target).sub(this.pos).divideScalar(Math.max(dt, 1e-3));
    this.pos.copy(target);
  }

  updateShot(dt) {
    this.shotT += dt;
    if (this.analytic) {
      const prev = _b.copy(this.pos);
      const t = this.shotT;
      this.pos.copy(this.shotStart).addScaledVector(this.shotV0, t).addScaledVector(G, 0.5 * t * t);
      this.vel.copy(this.shotV0).addScaledVector(G, t);
      if (this.shotMake) {
        this.checkThroughHoop(this.shotHoop, prev, this.pos);
      } else {
        const r = this.game.rimCenter(this.shotHoop);
        if (this.pos.distanceTo(r) < 48 || this.shotT >= this.shotDuration * 0.97) this.analytic = false;
      }
      if (this.shotT > this.shotDuration + 0.6) this.analytic = false;
    } else {
      this.stepPhysics(dt, true);
    }
  }

  updatePass(dt) {
    const to = this.passTo;
    if (!to) { this.setLoose(this.vel.clone().multiplyScalar(0.4)); return; }
    this.passT += dt;
    const u = clamp(this.passT / this.passDuration, 0, 1);
    let dest = this.alley ? this.alleyPoint.clone() : to.handsCenter();
    if (this.alley && to.isDunking() && u > 0.55) {
      dest = this.alleyPoint.clone().lerp(to.handsCenter(), clamp((u - 0.55) / 0.35, 0, 1));
    }
    const dist = this.passStart.distanceTo(dest);
    const arc = this.alley ? 110 : 18 + 0.03 * dist;
    const p = _a.copy(this.passStart).lerp(dest, u);
    p.z += arc * 4 * u * (1 - u);
    this.vel.copy(p).sub(this.pos).divideScalar(Math.max(dt, 1e-3));
    this.pos.copy(p);

    const game = this.game;
    if (this.passFrom) {
      for (const o of game.players) {
        if (o.team === this.passFrom.team || !o.canReceiveBall() || this.interceptTried.has(o)) continue;
        const d = o.handsCenter().distanceTo(this.pos);
        if (d < 58) {
          this.interceptTried.add(o);
          let chance = 0.14 + o.def.steal * 0.025;
          if (o.state === 'Steal' || o.state === 'Block') chance += 0.25;
          if (this.alley) chance *= 0.5;
          if (game.phase === 'Inbound') chance *= 0.25;
          if (Math.random() < chance) {
            const from = this.passFrom;
            this.giveTo(o);
            game.onPassIntercepted(o, from);
            return;
          }
        }
      }
    }
    if (u >= 1) {
      const from = this.passFrom;
      const reachable = !this.alley || (to.state === 'DunkAir' && this.pos.distanceToSquared(to.handsCenter()) < 50 * 50);
      if (to.canReceiveBall() && reachable) {
        this.giveTo(to);
        game.onBallCaught(to, from);
      } else {
        this.setLoose(this.vel.clone().multiplyScalar(0.3));
      }
    }
  }

  stepPhysics(dt, collide) {
    const n = clamp(Math.ceil(this.vel.length() * dt / 3), 1, 16);
    const h = dt / n;
    const R = HC.BallRadius;
    const game = this.game;
    for (let i = 0; i < n; i++) {
      const prev = _b.copy(this.pos);
      this.vel.addScaledVector(G, h);
      if (this.netDrag > 0) {
        this.netDrag -= h;
        const rc = game.rimCenter(this.shotHoop);
        const k = Math.min(1, 10 * h);
        this.vel.x = lerp(this.vel.x, (rc.x - this.pos.x) * 4, k);
        this.vel.y = lerp(this.vel.y, (rc.y - this.pos.y) * 4, k);
        this.vel.z = Math.max(this.vel.z, -240);
      }
      this.pos.addScaledVector(this.vel, h);
      if (this.pos.z < R) {
        this.pos.z = R;
        if (this.vel.z < 0) {
          const sp = -this.vel.z;
          if (sp > 60) {
            this.vel.z = sp * 0.74;
            if (this.soundCooldown <= 0) {
              game.onBallBounce(sp);
              this.soundCooldown = 0.05;
            }
          } else {
            this.vel.z = 0;
          }
          this.vel.x *= 0.93;
          this.vel.y *= 0.93;
          if (this.state === BallState.Shot) this.state = BallState.Loose;
        }
      }
      if (this.pos.z <= R + 0.5 && Math.abs(this.vel.z) < 1) {
        const f = Math.max(0, 1 - 0.9 * h);
        this.vel.x *= f;
        this.vel.y *= f;
      }
      const WX = HC.CourtHalfLength + 170, WY = HC.CourtHalfWidth + 150;
      if (Math.abs(this.pos.x) > WX) { this.pos.x = Math.sign(this.pos.x) * WX; this.vel.x *= -0.45; }
      if (Math.abs(this.pos.y) > WY) { this.pos.y = Math.sign(this.pos.y) * WY; this.vel.y *= -0.45; }
      if (collide) {
        for (let hi = 0; hi < 2; hi++) {
          this.collideRim(hi);
          this.collideBackboard(hi);
        }
      }
      if (!this.shotScored && this.lastShooter && this.sinceShot < 5) this.checkThroughHoop(this.shotHoop, prev, this.pos);
    }
  }

  collideRim(hi) {
    const C = this.game.rimCenter(hi);
    const P = this.pos, Vv = this.vel;
    const dx = P.x - C.x, dy = P.y - C.y, dz = P.z - C.z;
    if (Math.abs(dz) > 30 || Math.hypot(dx, dy) > 60) return;
    const L = Math.hypot(dx, dy);
    const Rr = HC.RimRadius + HC.RimTube;
    const q = L < 1e-3 ? _c.set(C.x + Rr, C.y, C.z) : _c.set(C.x + dx / L * Rr, C.y + dy / L * Rr, C.z);
    const nrm = _a.copy(P).sub(q);
    const d = nrm.length();
    const minD = HC.BallRadius + HC.RimTube;
    if (d < minD && d > 1e-4) {
      nrm.divideScalar(d);
      P.copy(q).addScaledVector(nrm, minD);
      const vn = Vv.dot(nrm);
      if (vn < 0) {
        Vv.addScaledVector(nrm, -(1 + 0.55) * vn);
        Vv.multiplyScalar(0.9);
        Vv.x += frand(-25, 25);
        Vv.y += frand(-25, 25);
        if (!this.rimTouched || this.soundCooldown <= 0) {
          this.rimTouched = true;
          this.game.onBallRim(hi, -vn);
          this.soundCooldown = 0.06;
        }
        if (this.state === BallState.Shot) this.state = BallState.Loose;
      }
    }
  }

  collideBackboard(hi) {
    const sign = hi === 1 ? 1 : -1;
    const face = sign * HC.BackboardX;
    const minX = sign > 0 ? face : face - 3;
    const maxX = sign > 0 ? face + 3 : face;
    const P = this.pos, Vv = this.vel;
    const cl = _c.set(clamp(P.x, minX, maxX), clamp(P.y, -HC.BackboardHalfWidth, HC.BackboardHalfWidth), clamp(P.z, HC.BackboardBottom, HC.BackboardTop));
    const d = _a.copy(P).sub(cl);
    const dist = d.length();
    if (dist < HC.BallRadius) {
      const nrm = dist > 1e-4 ? d.divideScalar(dist) : d.set(-sign, 0, 0);
      P.copy(cl).addScaledVector(nrm, HC.BallRadius);
      const vn = Vv.dot(nrm);
      if (vn < 0) {
        Vv.addScaledVector(nrm, -(1 + 0.6) * vn);
        if (this.soundCooldown <= 0) {
          this.game.onBallBoard(hi, -vn);
          this.soundCooldown = 0.06;
        }
        if (this.state === BallState.Shot) this.state = BallState.Loose;
      }
    }
  }

  checkThroughHoop(hi, prev, p) {
    if (this.shotScored) return;
    const R = this.game.rimCenter(hi);
    if (prev.z >= R.z && p.z < R.z) {
      const a = (prev.z - R.z) / Math.max(1e-4, prev.z - p.z);
      const x = prev.x + (p.x - prev.x) * a, y = prev.y + (p.y - prev.y) * a;
      if (Math.hypot(x - R.x, y - R.y) < HC.RimRadius - 1.5) {
        this.shotScored = true;
        this.analytic = false;
        this.netDrag = 0.45;
        this.vel.x *= 0.3;
        this.vel.y *= 0.3;
        this.vel.z = Math.min(this.vel.z, -150);
        if (this.state === BallState.Shot) this.state = BallState.Loose;
        this.game.onBallScored(hi, this.lastShooter, this.shotPoints, false);
      }
    }
  }

  spinVisual(dt) {
    // game-space axis = up x planar velocity; convert to three-space for the quaternion
    const n = safeNormal2D(this.vel, _a);
    let ax = -n.y, ay = n.x; // cross((0,0,1), n) = (-n.y, n.x, 0)
    let w;
    if (this.state === BallState.Shot) {
      w = -14;
    } else {
      w = size2D(this.vel) / HC.BallRadius * 0.6;
      if (this.state === BallState.Held) {
        w = Math.min(w, 6) + 2;
        if (ax === 0 && ay === 0) { ax = 0; ay = 1; }
      }
    }
    if ((ax !== 0 || ay !== 0) && w !== 0) {
      // the game space is left-handed relative to three: flip the angle
      const axis = _b.set(ax, 0, ay).normalize();
      const q = new THREE.Quaternion().setFromAxisAngle(axis, -w * dt);
      this.spin.premultiply(q).normalize();
    }
  }
}

export { dist2D };
