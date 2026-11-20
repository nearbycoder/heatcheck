// Port of HCAI.cpp: CPU brains write into each player's input record or call actions directly.
import { HC, V, DEG, clamp, frand, dist2D, size2D } from './consts.js';
import { BallState } from './ball.js';

export function newAIState() {
  return {
    think: 0, spot: { x: 0, y: 0 }, spotTimer: 0, shootHold: -1, jumpAt: -1, holdTimer: 0,
    passAt: -1, wantTurbo: false, aggro: 0, intent: -1, intentSpot: { x: 0, y: 0 },
  };
}

const D2 = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const norm2 = (x, y) => {
  const l = Math.hypot(x, y);
  return l > 1e-6 ? { x: x / l, y: y / l } : { x: 0, y: 0 };
};

function reaction(g) {
  if (g.attract || g.mode === 3) return 0.24;
  return g.difficulty === 0 ? 0.42 : g.difficulty === 1 ? 0.26 : 0.15;
}

function moveTo(c, target, slow = 60) {
  const dx = target.x - c.pos.x, dy = target.y - c.pos.y;
  const l = Math.hypot(dx, dy);
  if (l < 10) { c.input.move.x = c.input.move.y = 0; return; }
  const mag = l < slow ? l / slow : 1;
  c.input.move.x = dx / l * mag;
  c.input.move.y = dy / l * mag;
}

function laneOpen(g, c, to, width) {
  const ax = c.pos.x, ay = c.pos.y;
  const abx = to.x - ax, aby = to.y - ay;
  const l2 = abx * abx + aby * aby;
  if (l2 < 1) return true;
  for (const o of g.players) {
    if (o.team === c.team || o.isDown()) continue;
    const t = ((o.pos.x - ax) * abx + (o.pos.y - ay) * aby) / l2;
    if (t < 0.05 || t > 1.05) continue;
    if (Math.hypot(o.pos.x - (ax + abx * t), o.pos.y - (ay + aby * t)) < width) return false;
  }
  return true;
}

function openSpace(g, p, defTeam) {
  let best = 1e4;
  for (const o of g.players) if (o.team === defTeam && !o.isDown()) best = Math.min(best, D2(p, o.pos));
  return best;
}

export function aiShootNow(g, c, s) {
  if (!c.canAct() || !c.hasBall()) return;
  const h = c.attackHoop();
  const rim = g.rimCenter(h);
  const d = g.distToHoop(c.pos, h);
  const turboOK = c.turbo > 0.1 || c.onFire;
  if (s.intent <= 0 && d < c.dunkRange() && turboOK && (d < 260 || laneOpen(g, c, rim, 80))) {
    c.input.turbo = true;
    c.startDunk(false);
  } else if (d < 200) {
    c.startLayup();
  } else {
    c.startJumpShot();
    c.input.shootDown = true;
    let noise = g.difficulty === 2 ? 0.035 : g.difficulty === 1 ? 0.07 : 0.12;
    if (g.attract || g.mode === 3) noise = 0.06;
    s.shootHold = g.time + 0.2 + 0.286 + frand(-noise, noise);
  }
  s.holdTimer = 0;
  s.intent = -1;
}

export function tickAI(g, c, s, dt) {
  const inp = c.input;
  inp.move.x = inp.move.y = 0;
  inp.turbo = false;
  inp.shootPressed = inp.shootReleased = inp.passPressed = inp.shovePressed = false;
  if (s.shootHold >= 0 && (c.state === 'ShootWindup' || c.state === 'ShootAir')) {
    inp.shootDown = g.time < s.shootHold;
  } else {
    s.shootHold = -1;
    inp.shootDown = false;
  }
  if (c.isDown() || c.isDunking()) return;
  s.think -= dt;
  s.spotTimer -= dt;
  const ball = g.ball;

  switch (g.phase) {
    case 'Intro': case 'QuarterEnd': case 'Break': case 'GameOver':
      return;
    case 'TipOff':
      if (c === g.tipJumpers[c.team] && ball.state === BallState.Loose && !g.tipTouched) {
        if (s.jumpAt < 0 && ball.vel.z < 425 && ball.pos.z > 230) s.jumpAt = g.time + frand(0.025, 0.115);
        if (s.jumpAt >= 0 && g.time >= s.jumpAt) {
          s.jumpAt = -1;
          if (c.canAct() && !c.isAirborne()) c.startBlock();
        }
      }
      return;
    case 'Scored': case 'Violation': {
      if (c.team === g.inboundTeam) {
        const sign = g.inboundHoop === 0 ? -1 : 1;
        moveTo(c, { x: sign * (HC.CourtHalfLength - 380), y: (c.slot === 0 ? -1 : 1) * 220 }, 60);
      } else {
        const r = g.rimCenter(g.attackHoop(g.inboundTeam));
        moveTo(c, { x: r.x * 0.5, y: (c.slot === 0 ? -1 : 1) * 260 }, 60);
      }
      return;
    }
    case 'Inbound':
      if (c.state === 'Inbound') {
        s.holdTimer += dt;
        if (s.holdTimer > 0.7 + Math.random() * 0.6 && c.stateTime > 0.5) {
          const mate = g.teammate(c);
          if (mate) c.startPass(mate, false);
        }
        return;
      }
      if (c.team === g.inboundTeam) {
        const sign = g.inboundHoop === 0 ? -1 : 1;
        moveTo(c, { x: sign * (HC.CourtHalfLength - 400), y: (c.slot === 0 ? -1 : 1) * 200 }, 40);
        return;
      }
      aiDefense(g, c, s);
      return;
    case 'Live':
      break;
    default:
      return;
  }

  const holder = ball.getHolder();
  const bs = ball.state;
  if (holder === c) { offenseWithBall(g, c, s, dt); return; }
  const teamBall = (holder && holder.team === c.team) || (bs === BallState.Pass && ball.passFrom && ball.passFrom.team === c.team);
  if (teamBall) { offenseOffBall(g, c, s, dt); return; }
  if (bs === BallState.Loose || bs === BallState.Shot) { chaseBall(g, c, s); return; }
  aiDefense(g, c, s);
}

function offenseWithBall(g, c, s, dt) {
  const h = c.attackHoop();
  const rim = g.rimCenter(h);
  const d = g.distToHoop(c.pos, h);
  const mate = g.teammate(c);
  s.holdTimer += dt;
  if (!c.canAct()) return;
  const defD = g.nearestOpponent(c).dist;
  const open = defD > 220;
  const turboOK = c.turbo > 0.15 || c.onFire;
  const clockLeft = Math.min(g.shotClock, g.gameClock);
  const F = g.hoopFacing(h);

  if (s.intent < 0) {
    const pThree = clamp((c.def.three - 4) * 0.08, 0, 0.45);
    const pPull = clamp(0.22 + (c.def.shoot - 5) * 0.05, 0.05, 0.45);
    const r = Math.random();
    s.intent = r < pThree ? 2 : r < pThree + pPull ? 1 : 0;
    if (c.onFire && Math.random() < 0.5) s.intent = 2;
    const ang = frand(-68, 68) * DEG;
    const rad = s.intent === 2 ? HC.ThreeRadius + 55 : frand(380, 520);
    s.intentSpot = { x: rim.x + F.x * Math.cos(ang) * rad, y: clamp(rim.y + Math.sin(ang) * rad, -700, 700) };
  }
  if (s.think <= 0) {
    s.think = reaction(g) * frand(0.7, 1.3);
    if (clockLeft < 2.2) { aiShootNow(g, c, s); return; }
    if (s.intent > 0) {
      const spotD = D2(c.pos, s.intentSpot);
      if (spotD < 90 && s.holdTimer > 0.5 && (defD > 140 || Math.random() < 0.15)) { aiShootNow(g, c, s); return; }
      if (s.holdTimer > 3.0 && spotD > 200) s.intent = 0;
    }
    if (s.intent === 0 && d < c.dunkRange() && turboOK && laneOpen(g, c, rim, 85) && Math.random() < 0.3 + c.def.dunk * 0.04) {
      c.input.turbo = true;
      c.startDunk(false);
      s.holdTimer = 0;
      return;
    }
    if (d < 200 && Math.random() < 0.6) { aiShootNow(g, c, s); return; }
    const three = g.isThree(c.pos, h);
    const rating = three ? c.def.three : c.def.shoot;
    let want = 0;
    if (d < HC.ThreeRadius) want = open ? 0.05 + rating * 0.022 : 0.015;
    else if (d < 880) want = open ? (rating >= 7 ? 0.16 + (rating - 7) * 0.08 : 0.03) : 0.01;
    if (c.onFire && d < 900) want = want * 2.5 + 0.1;
    else if (c.streak >= 2) want *= 1.4;
    if (s.holdTimer < 0.9) want *= 0.25;
    if (clockLeft < 6 && d < 900) want += 0.25;
    if (Math.random() < want) { aiShootNow(g, c, s); return; }
    if (mate && !mate.isDown() && !mate.isAirborne() && s.holdTimer > 0.8) {
      const md = g.distToHoop(mate.pos, h);
      const mateOpen = openSpace(g, mate.pos, 1 - c.team);
      const myOpen = openSpace(g, c.pos, 1 - c.team);
      let pw = 0;
      if (md < d - 120 && mateOpen > 180) pw += 0.35;
      if (myOpen < 130 && mateOpen > 200) pw += 0.35;
      if (s.holdTimer > 4.5) pw += 0.4;
      if (mate.onFire) pw += 0.3;
      if (mate.human) pw += 0.15;
      if (!laneOpen(g, c, mate.pos, 60)) pw *= 0.3;
      if (Math.random() < pw) {
        const alley = !mate.human && md < mate.dunkRange() && mateOpen > 150 && mate.canAct() && Math.random() < 0.45;
        c.startPass(mate, alley);
        s.holdTimer = 0;
        return;
      }
    }
    s.wantTurbo = turboOK && (laneOpen(g, c, rim, 110) || d > 950) && Math.random() < 0.6;
  }
  // drive toward the basket, slipping around defenders
  let goal = { x: rim.x + F.x * 100, y: rim.y + F.y * 100 };
  if (s.intent > 0) goal = s.intentSpot;
  let dir = norm2(goal.x - c.pos.x, goal.y - c.pos.y);
  for (const o of g.players) {
    if (o.team === c.team || o.isDown()) continue;
    const tx = o.pos.x - c.pos.x, ty = o.pos.y - c.pos.y;
    const dO = Math.hypot(tx, ty);
    if (dO < 280 && dO > 1) {
      const along = (tx / dO) * dir.x + (ty / dO) * dir.y;
      if (along > 0.2) {
        const px = -dir.y, py = dir.x;
        const sd = tx * px + ty * py > 0 ? -1 : 1;
        const k = sd * 1.3 * (1 - dO / 280) * along;
        dir = { x: dir.x + px * k, y: dir.y + py * k };
      }
    }
  }
  dir = norm2(dir.x, dir.y);
  const close = D2(goal, c.pos) < 60 ? 0.2 : 1;
  c.input.move.x = dir.x * close;
  c.input.move.y = dir.y * close;
  c.input.turbo = s.wantTurbo;
}

function offenseOffBall(g, c, s, dt) {
  const h = c.attackHoop();
  const rim = g.rimCenter(h);
  const F = g.hoopFacing(h);
  const holder = g.ball.getHolder();
  if (s.spotTimer <= 0 || D2(c.pos, s.spot) < 40) {
    s.spotTimer = frand(1.0, 2.2);
    const R = (fx, y) => ({ x: rim.x + F.x * fx, y });
    const spots = [
      R(480, 470), R(480, -470), R(760, 0),
      { x: rim.x + F.x * 90, y: 630 }, { x: rim.x + F.x * 90, y: -630 },
      R(230, 190), R(230, -190), R(150, 0),
    ];
    let best = -1e9;
    spots.forEach((sp, i) => {
      let score = Math.min(500, openSpace(g, sp, 1 - c.team)) + Math.random() * 140;
      if (holder && D2(sp, holder.pos) < 320) score -= 400;
      if (i === 7 && holder && g.distToHoop(holder.pos, h) > 600) score += 90;
      if (c.def.three >= 8 && i <= 4) score += 60;
      if (score > best) { best = score; s.spot = sp; }
    });
  }
  moveTo(c, s.spot, 50);
  c.input.turbo = D2(c.pos, s.spot) > 450 && (c.turbo > 0.4 || c.onFire);
  if (holder && c.canAct() && c.shoveCooldown <= 0 && (c.turbo > 0.35 || c.onFire)) {
    const { opp: def, dist: dd } = g.nearestOpponent(holder);
    if (def && dd < 160 && dist2D(def.pos, c.pos) < 170 && Math.random() < s.aggro * 0.12 * dt) c.startShove(def);
  }
}

function aiDefense(g, c, s) {
  const ball = g.ball;
  const holder = ball.getHolder();
  const defHoop = g.attackHoop(1 - c.team);
  const rim = g.rimCenter(defHoop);
  const opp = g.opponents(c);
  if (!opp.length) return;
  const mate = g.teammate(c);
  let man;
  if (holder && holder.team !== c.team) {
    const guardBall = !mate || mate.isDown() || dist2D(c.pos, holder.pos) <= dist2D(mate.pos, holder.pos) + 40;
    man = guardBall ? holder : (opp[0] === holder ? opp[opp.length - 1] : opp[0]);
  } else {
    man = opp[c.slot] || opp[0];
  }
  const onBall = man === holder;
  let gap = onBall ? 105 : 170 + 0.12 * (holder ? D2(man.pos, holder.pos) : 0);
  gap = Math.min(gap, 0.5 * D2(man.pos, rim));
  const n = norm2(rim.x - man.pos.x, rim.y - man.pos.y);
  let target = { x: man.pos.x + n.x * gap, y: man.pos.y + n.y * gap };
  if (!onBall && holder) {
    const mx = (man.pos.x + holder.pos.x) * 0.5, my = (man.pos.y + holder.pos.y) * 0.5;
    target = { x: target.x + (mx - target.x) * 0.25, y: target.y + (my - target.y) * 0.25 };
  }
  moveTo(c, target, 30);
  c.input.turbo = D2(c.pos, target) > 260 && (c.turbo > 0.25 || c.onFire);
  if (!c.canAct()) return;
  const distMan = D2(c.pos, man.pos);
  const react = reaction(g);
  let skill = g.difficulty === 2 ? 1.5 : g.difficulty === 1 ? 1 : 0.55;
  if (g.attract || g.mode === 3) skill = 1;
  const dt = 1 / 60;
  if (onBall) {
    if ((holder.isShooting() && distMan < 240) || (holder.isDunking() && distMan < 450)) {
      if (s.jumpAt < 0) s.jumpAt = g.time + react * frand(0.5, 1.3);
    }
    if (s.jumpAt >= 0 && g.time >= s.jumpAt) {
      s.jumpAt = -1;
      if (!c.isAirborne()) c.startBlock();
      return;
    }
    if (g.phase === 'Live' && distMan < 140 && c.stealCooldown <= 0 && Math.random() < skill * (0.25 + c.def.steal * 0.04) * g.dt) {
      c.startSteal();
      return;
    }
    if (g.phase === 'Live' && distMan < 175 && c.shoveCooldown <= 0 && (c.turbo > 0.3 || c.onFire)) {
      const p = s.aggro * skill * 0.22 * g.dt * (holder.onFire ? 2.5 : 1) * (holder.isShooting() ? 2 : 1);
      if (Math.random() < p) {
        c.input.turbo = true;
        c.startShove(holder);
        return;
      }
    }
  } else {
    if (holder && holder.state === 'DunkAir' && g.distToHoop(c.pos, defHoop) < 320 && !c.isAirborne()) {
      if (s.jumpAt < 0) s.jumpAt = g.time + react * frand(0.4, 1.0);
    }
    if (s.jumpAt >= 0 && g.time >= s.jumpAt) {
      s.jumpAt = -1;
      if (!c.isAirborne()) c.startBlock();
      return;
    }
    if (holder && mate && g.distToHoop(holder.pos, defHoop) < 420 && D2(mate.pos, holder.pos) > 160) {
      const hn = norm2(rim.x - holder.pos.x, rim.y - holder.pos.y);
      moveTo(c, { x: holder.pos.x + hn.x * 90, y: holder.pos.y + hn.y * 90 }, 20);
      c.input.turbo = c.turbo > 0.1 || c.onFire;
    }
    if (ball.state === BallState.Pass && ball.passTo === man) {
      if (dist2D(ball.pos, c.pos) < 220) moveTo(c, ball.pos, 5);
    }
  }
  void dt;
}

function chaseBall(g, c, s) {
  const ball = g.ball;
  const t3 = ball.state === BallState.Shot ? ball.predictRebound()
    : V(ball.pos.x + ball.vel.x * 0.25, ball.pos.y + ball.vel.y * 0.25, 0);
  const mate = g.teammate(c);
  const myD = D2(c.pos, t3);
  const mateD = mate && !mate.isDown() ? D2(mate.pos, t3) : 1e9;
  if (myD <= mateD + 50) {
    moveTo(c, t3, 10);
    c.input.turbo = myD > 180 && (c.turbo > 0.15 || c.onFire);
    const bp = ball.pos;
    if (ball.state === BallState.Loose && bp.z > 235 && bp.z < 430 && ball.vel.z < 80 && dist2D(bp, c.pos) < 110
      && !c.isAirborne() && c.canAct() && s.jumpAt < 0) {
      s.jumpAt = g.time + frand(0.02, 0.15);
    }
    if (s.jumpAt >= 0 && g.time >= s.jumpAt) {
      s.jumpAt = -1;
      if (c.canAct() && !c.isAirborne()) c.startBlock();
    }
  } else {
    const r = g.rimCenter(g.attackHoop(1 - c.team));
    moveTo(c, { x: t3.x + (r.x - t3.x) * 0.45, y: t3.y + (r.y - t3.y) * 0.45 }, 40);
  }
}

export { size2D };
