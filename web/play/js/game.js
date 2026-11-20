// Port of AHCGameMode + HCGameModeEvents.cpp: match flow (tip-off, inbounds, quarters, OT),
// clocks, scoring, heat / fire, shot odds, dunks, alley-oops, steals, shoves, blocks,
// goaltending and the menu state machine. AI lives in ai.js.
import {
  HC, V, clamp, frand, lerp, randInt, dist2D, safeNormal2D, size2D, finterp,
} from './consts.js';
import { TEAMS } from './roster.js';
import { BallState } from './ball.js';
import { newStats } from './character.js';
import { tickAI, aiShootNow, newAIState } from './ai.js';

export const Mode = { OnePlayer: 0, TwoPlayerCoop: 1, TwoPlayerVersus: 2, Watch: 3 };
export const Difficulty = { Easy: 0, Normal: 1, Hard: 2 };
const MODE_NAMES = ['1 PLAYER  vs  CPU', '2 PLAYERS  CO-OP', '2 PLAYERS  HEAD-TO-HEAD', 'CPU  vs  CPU'];
const DIFF_NAMES = ['ROOKIE', 'PRO', 'LEGEND'];

export class Game {
  constructor({ ball, players, hoops, referee, arena, camera, audio, fx, options }) {
    this.ball = ball;
    this.players = players;
    this.hoops = hoops;
    this.referee = referee;
    this.arena = arena;
    this.cam = camera;
    this.audio = audio;
    this.fx = fx;
    this.options = options;

    this.mode = Mode.OnePlayer;
    this.difficulty = Difficulty.Normal;
    this.quarterMinutes = 3;
    this.bigHeads = false;
    this.teamIdx = [0, 1];

    this.screen = 'Title';
    this.phase = 'Intro';
    this.phaseTime = 0;
    this.paused = false;
    this.pauseIndex = 0;
    this.attract = true;
    this.score = [0, 0];
    this.quarterScores = [[0, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0, 0]];
    this.quarter = 1;
    this.gameClock = 180;
    this.shotClock = HC.ShotClockLength;
    this.shotClockTeam = -1;
    this.possessionTeam = -1;
    this.inboundTeam = 0;
    this.inboundHoop = 0;
    this.firstPossessionTeam = 0;
    this.buzzerPending = false;
    this.tipTouched = false;
    this.crowdHype = 0;
    this.menuIndex = 0;
    this.selectSide = 0;
    this.popups = [];
    this.ai = [newAIState(), newAIState(), newAIState(), newAIState()];
    this.lastPassTime = -10;
    this.lastPasser = null;
    this.tipJumpers = [null, null];
    this.breakTimer = 0;
    this.countdownBeep = 0;
    this.winnerText = '';
    this.time = 0;
    this.optionsPage = null; // 'graphics' | 'sound' | null (handled by the HUD)
    this.humanInput = [null, null];
    this.events = [];
  }

  // ---------------------------------------------------------------- queries
  teamDef(t) { return TEAMS[clamp(this.teamIdx[clamp(t, 0, 1)], 0, TEAMS.length - 1)]; }
  teammate(c) { return this.players.find((p) => p !== c && p.team === c.team) || null; }
  opponents(c) { return this.players.filter((p) => p.team !== c.team); }
  nearestOpponent(c) {
    let best = null, bd = 1e9;
    for (const p of this.players) {
      if (p.team !== c.team && !p.isDown()) {
        const d = dist2D(p.pos, c.pos);
        if (d < bd) { bd = d; best = p; }
      }
    }
    return { opp: best, dist: bd };
  }
  attackHoop(team) {
    const swap = this.quarter >= 3;
    const h = team === 0 ? 1 : 0;
    return swap ? 1 - h : h;
  }
  rimCenter(h) { return V(h === 0 ? -HC.RimX : HC.RimX, 0, HC.RimZ); }
  hoopFloor(h) { return V(h === 0 ? -HC.RimX : HC.RimX, 0, 0); }
  hoopFacing(h) { return V(h === 0 ? 1 : -1, 0, 0); }
  distToHoop(p, h) { return dist2D(p, this.hoopFloor(h)); }
  isThree(p, h) {
    return Math.abs(p.y) > HC.ThreeCornerY - 2 || this.distToHoop(p, h) > HC.ThreeRadius + 2;
  }
  isPlayLive() { return this.phase === 'Live' || this.phase === 'TipOff' || this.phase === 'Inbound'; }
  inMenus() { return this.screen !== 'Game'; }
  humanCount() { return this.players.filter((c) => c.human).length; }
  isHumanTeam(t) { return this.players.some((c) => c.team === t && c.human); }
  log(msg) {
    this.events.push(`[Q${this.quarter} ${this.gameClock.toFixed(1)}] ${msg}`);
    if (this.events.length > 400) this.events.shift();
  }

  // ---------------------------------------------------------------- setup / flow
  returnToTitle() {
    this.paused = false;
    this.screen = 'Title';
    this.attract = true;
    this.menuIndex = 0;
    this.setupTeams(true);
    this.startMatch();
    this.audio.playMusic('M_Title', 0.55);
  }

  setupTeams(forAttract) {
    const n = TEAMS.length;
    if (forAttract) {
      this.teamIdx[0] = randInt(0, n - 1);
      do { this.teamIdx[1] = randInt(0, n - 1); } while (this.teamIdx[1] === this.teamIdx[0]);
    }
    this.players.forEach((p, i) => {
      const team = i >> 1, slot = i & 1;
      const td = this.teamDef(team);
      p.setup(team, slot, td, td.players[Math.min(slot, td.players.length - 1)]);
      p.applyHeadScale(this.bigHeads ? 1.7 : 1);
    });
    this.assignControl();
  }

  assignControl() {
    for (const c of this.players) { c.human = false; c.humanIndex = -1; }
    if (this.attract || this.mode === Mode.Watch) return;
    this.players[0].human = true;
    this.players[0].humanIndex = 0;
    if (this.mode === Mode.TwoPlayerCoop) {
      this.players[1].human = true;
      this.players[1].humanIndex = 1;
    } else if (this.mode === Mode.TwoPlayerVersus) {
      this.players[2].human = true;
      this.players[2].humanIndex = 1;
    }
  }

  resetMatchState() {
    this.score = [0, 0];
    this.quarterScores = [[0, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0, 0]];
    this.quarter = 1;
    this.gameClock = this.quarterMinutes * 60;
    this.shotClock = HC.ShotClockLength;
    this.shotClockTeam = -1;
    this.possessionTeam = -1;
    this.buzzerPending = false;
    this.popups = [];
    this.winnerText = '';
    for (let i = 0; i < 4; i++) {
      this.ai[i] = newAIState();
      this.ai[i].aggro = frand(0.3, 1);
    }
    for (const c of this.players) {
      c.stats = newStats();
      c.streak = 0;
      c.fireMakes = 0;
      c.setFire(false);
      c.turbo = 1;
    }
  }

  startMatch() {
    this.resetMatchState();
    this.setPhase('Intro');
    this.cam.snap();
  }

  setPhase(p) {
    this.phase = p;
    this.phaseTime = 0;
    const A = this.audio;
    switch (p) {
      case 'Intro':
        this.positionForTipOff();
        if (!this.attract) {
          A.stopMusic(1.5);
          A.voiceLine('VO_Welcome', 3);
        }
        break;
      case 'TipOff':
        this.positionForTipOff();
        this.tipTouched = false;
        break;
      case 'Scored':
      case 'Violation':
        this.ball.setDead();
        break;
      case 'Inbound':
        this.placeInbound();
        break;
      case 'QuarterEnd': {
        this.ball.setDead();
        A.sfx('S_Buzzer', 0.9);
        const over = this.quarter >= 4 && this.score[0] !== this.score[1];
        if (over) A.voiceLine('VO_FinalBuzzer', 3);
        else if (this.quarter === 2) A.voiceLine('VO_Halftime', 3);
        else if (this.quarter >= 4) A.voiceLine('VO_Overtime', 3);
        else A.voiceLine('VO_EndQuarter', 3);
        this.log(`Quarter end ${this.score[0]} - ${this.score[1]}`);
        break;
      }
      case 'Break':
        this.breakTimer = 0;
        if (!this.attract) A.playMusic('M_Halftime', 0.45);
        break;
      case 'GameOver': {
        const w = this.score[0] > this.score[1] ? 0 : 1;
        this.winner = w;
        this.winnerText = `${this.teamDef(w).city.toUpperCase()} ${this.teamDef(w).name.toUpperCase()} WIN!`;
        for (const c of this.players) if (c.team === w) c.celebrate();
        this.log(`GAME OVER ${this.score[0]} - ${this.score[1]}`);
        if (!this.attract) A.playMusic('M_Title', 0.5);
        break;
      }
      default: break;
    }
  }

  positionForTipOff() {
    this.referee.lineUp();
    this.ball.holdForTip(this.referee.poseToss(0));
    const side0 = this.attackHoop(0) === 1 ? -1 : 1;
    for (let t = 0; t < 2; t++) {
      const side = t === 0 ? side0 : -side0;
      const a = this.players[t * 2], b = this.players[t * 2 + 1];
      let jumper = (b.def.block + b.def.power >= a.def.block + a.def.power) ? b : a;
      if (a.human !== b.human) jumper = a.human ? a : b;
      this.ai[t * 2].jumpAt = this.ai[t * 2 + 1].jumpAt = -1;
      const other = jumper === a ? b : a;
      this.tipJumpers[t] = jumper;
      jumper.resetForPlay();
      other.resetForPlay();
      jumper.setLocation(side * 48, 0);
      other.setLocation(side * 430, (t === 0 ? -1 : 1) * 280);
      jumper.setYaw(side > 0 ? 180 : 0);
      other.setYaw(side > 0 ? 180 : 0);
      jumper.stop();
      other.stop();
    }
  }

  /** One fixed gameplay step (called by the main loop). */
  tick(dt) {
    this.dt = dt;
    this.time += dt;
    this.phaseTime += dt;
    for (let i = 0; i < this.players.length; i++) {
      const c = this.players[i];
      if (c.human && c.humanIndex >= 0 && this.humanInput[c.humanIndex]) {
        const H = this.humanInput[c.humanIndex];
        const prevDown = c.input.shootDown;
        c.input.move.x = H.move.x;
        c.input.move.y = H.move.y;
        c.input.turbo = H.turbo;
        c.input.shootDown = H.shootDown;
        c.input.shootPressed = H.shootPressed;
        c.input.shootReleased = H.shootReleased || (prevDown && !H.shootDown);
        c.input.passPressed = H.passPressed;
        c.input.shovePressed = H.shovePressed;
        H.shootPressed = H.shootReleased = H.passPressed = H.shovePressed = false;
      } else {
        tickAI(this, c, this.ai[i], dt);
      }
    }
    this.tickPhase(dt);
    this.tickShotDefense();
    this.tickPopups(dt);
    this.crowdHype = finterp(this.crowdHype, this.arena.excitement, dt, 2);
    this.audio.setCrowd(this.crowdHype);
  }

  /** Called after characters have moved so the referee tracks this frame's ball. */
  postTick(dt) {
    this.referee.trackPlay(dt, this.ball.pos);
  }

  tickPhase(dt) {
    const A = this.audio;
    switch (this.phase) {
      case 'Intro':
        if (!this.attract) {
          if (this.phaseTime - dt < 0.9 && this.phaseTime >= 0.9) A.voiceLine(`VO_Team_${this.teamDef(1).abbr}`, 2);
          if (this.phaseTime - dt < 2.4 && this.phaseTime >= 2.4) A.voiceLine(`VO_Team_${this.teamDef(0).abbr}`, 2);
        }
        if (this.phaseTime > (this.attract ? 1.0 : 4.2)) this.setPhase('TipOff');
        break;
      case 'TipOff':
        this.tickTipOff();
        break;
      case 'Live':
        this.tickClocks(dt);
        this.tickLooseBall();
        break;
      case 'Scored':
        if (this.phaseTime > 1.7) {
          if (this.gameClock <= 0) this.setPhase('QuarterEnd');
          else this.beginInbound(this.inboundTeam, this.inboundHoop);
        }
        break;
      case 'Inbound': {
        this.tickLooseBall();
        const h = this.ball.getHolder();
        if (h && h.state === 'Inbound') {
          const limit = h.human ? 4.5 : 3.0;
          if (this.phaseTime > limit && !h.canAct()) {
            const mate = this.teammate(h);
            if (mate) h.startPass(mate, false);
          }
        } else if (this.ball.state === BallState.Loose || (h && h.state !== 'Inbound' && h.state !== 'Pass')) {
          for (const c of this.players) if (c.state === 'Inbound') c.setInbound(false);
          this.setPhase('Live');
        }
        break;
      }
      case 'Violation':
        if (this.phaseTime > 1.6) this.beginInbound(this.inboundTeam, this.inboundHoop);
        break;
      case 'QuarterEnd':
        if (this.phaseTime > 2.6) {
          if (this.quarter >= 4 && this.score[0] !== this.score[1]) this.setPhase('GameOver');
          else this.setPhase('Break');
        }
        break;
      case 'Break':
        this.breakTimer += dt;
        if ((this.attract || this.mode === Mode.Watch) && this.breakTimer > 4) this.startQuarter();
        else if (this.breakTimer > 15) this.startQuarter();
        break;
      case 'GameOver':
        if (this.attract && this.phaseTime > 6) {
          if (this.screen !== 'Title') this.startMatch();
          else this.returnToTitle();
        }
        break;
      default: break;
    }
  }

  tickTipOff() {
    const b = this.ball;
    if (b.state === BallState.Official) {
      const releaseTime = this.referee.releaseTime;
      const grip = this.referee.poseToss(Math.min(this.phaseTime, releaseTime));
      if (this.phaseTime < releaseTime) {
        b.holdForTip(grip);
        return;
      }
      b.toss(grip, 535);
      this.referee.followThrough();
      this.audio.sfx('S_Whistle', 0.7);
      this.audio.voiceVariant('VO_TipOff', 2, 2);
    }
    if (this.tipTouched) return;
    const bp = b.pos;
    let tipper = null;
    let closest = (HC.BallRadius + 11) ** 2;
    if (bp.z > 220 && b.isDescending()) {
      for (const j of this.tipJumpers) {
        if (!j || !j.isAirborne()) continue;
        const d = j.bone('grip_l').distanceToSquared(bp);
        if (d < closest) { closest = d; tipper = j; }
      }
    }
    if (tipper) {
      const to = safeNormal2D(V(this.teammate(tipper).pos.x - bp.x, this.teammate(tipper).pos.y - bp.y, 0));
      b.setLoose(V(to.x * 520, to.y * 520, 100), tipper);
      this.tipTouched = true;
      this.firstPossessionTeam = tipper.team;
      this.audio.sfx('S_Block', 0.6);
      this.log(`Tip won by team ${tipper.team} (${tipper.def.last})`);
      this.setPhase('Live');
      return;
    }
    if (b.state === BallState.Loose && bp.z < 140 && b.vel.z < 0) {
      this.tipTouched = true;
      this.firstPossessionTeam = -1;
      this.setPhase('Live');
    }
  }

  tickClocks(dt) {
    const b = this.ball;
    const bs = b.state;
    this.gameClock = Math.max(0, this.gameClock - dt);
    if (!this.attract && this.gameClock > 0 && this.gameClock < 5) {
      this.countdownBeep -= dt;
      if (this.countdownBeep <= 0) {
        this.audio.sfx('S_Countdown', 0.5);
        this.countdownBeep = 1;
      }
    }
    const holder = b.getHolder();
    let ctrl = -1;
    if (bs === BallState.Held && holder) ctrl = holder.team;
    else if (bs === BallState.Pass && b.passFrom) ctrl = b.passFrom.team;
    if (ctrl >= 0) {
      if (ctrl !== this.shotClockTeam) {
        this.shotClockTeam = ctrl;
        this.shotClock = HC.ShotClockLength;
      }
      this.shotClock = Math.max(0, this.shotClock - dt);
      if (this.shotClock <= 0 && this.gameClock > 0 && (bs === BallState.Held || bs === BallState.Pass)) {
        this.log(`Shot clock violation team ${ctrl}`);
        this.popup('SHOT CLOCK!', '#ff4d33', 1, 'VIOLATION');
        this.audio.sfx('S_ShotClock', 0.9);
        this.audio.voiceLine('VO_ShotClock', 2);
        this.inboundTeam = 1 - ctrl;
        this.inboundHoop = this.attackHoop(ctrl);
        this.shotClockTeam = -1;
        this.setPhase('Violation');
        return;
      }
    }
    if (this.gameClock <= 0) {
      if (bs === BallState.Shot) this.buzzerPending = true;
      else if (!this.buzzerPending) this.setPhase('QuarterEnd');
      else {
        this.buzzerPending = false;
        this.setPhase('QuarterEnd');
      }
    }
  }

  tickLooseBall() {
    const b = this.ball;
    if (b.state !== BallState.Loose) return;
    const bp = b.pos;
    let best = null, bd = 1e9;
    for (const c of this.players) {
      if (!c.canReceiveBall() || c.isDunking() || c.actionLock > 0) continue;
      if (c.isShooting() && c.shotReleased && c.stateTime < 0.4) continue;
      const d = dist2D(c.pos, bp);
      const reach = c.isAirborne() ? c.pos.z + 150 : 240;
      if (d < 64 && bp.z < reach && d < bd) { best = c; bd = d; }
    }
    if (best) {
      if (b.rimTouched || b.lastShooter) best.stats.rebounds++;
      b.giveTo(best);
      b.lastShooter = null;
      this.onBallCaught(best, null);
      if (best.isAirborne()) best.actionLock = 0.2;
    }
  }

  tickShotDefense() {
    if (this.phase !== 'Live') return;
    const b = this.ball;
    const bp = b.pos;
    const A = this.audio;
    if (b.state === BallState.Shot) {
      const shooter = b.shooter;
      if (!shooter) return;
      const rim = this.rimCenter(b.shotHoop);
      for (const o of this.players) {
        if (o.team === shooter.team || o.state !== 'Block' || !o.isAirborne()) continue;
        const hd = Math.min(o.bone('hand_l').distanceTo(bp), o.bone('hand_r').distanceTo(bp));
        if (hd > 38) continue;
        const desc = b.isDescending();
        const rimD = dist2D(bp, rim);
        if (desc && rimD < 130 && bp.z > rim.z - 5 && !o.onFire) {
          this.log(`Goaltending by ${o.def.last}`);
          this.popup('GOALTENDING!', '#ffd933', 1, 'BASKET COUNTS');
          A.sfx('S_Whistle', 0.8);
          A.voiceLine('VO_Goaltending', 3);
          b.deflect(V(frand(-200, 200), frand(-200, 200), -100), o);
          this.onBallScored(b.shotHoop, shooter, b.shotPoints, false);
          return;
        }
        if ((!desc || o.onFire) && !o.blockAttempted) {
          o.blockAttempted = true;
          const chance = 0.5 + (o.def.block - 5) * 0.05 + (o.onFire ? 0.2 : 0);
          if (Math.random() < chance) {
            const away = safeNormal2D(V(bp.x - o.pos.x, bp.y - o.pos.y, 0));
            const s = frand(380, 620);
            b.deflect(V(away.x * s, away.y * s, frand(-120, 160)), o);
            o.stats.blocks++;
            this.log(`BLOCK by ${o.def.last} on ${shooter.def.last}`);
            this.popup('REJECTED!', '#4dccff', 1.1);
            A.sfx('S_Block', 1);
            A.voiceVariant('VO_Block', 3, 2);
            A.sfx('S_CrowdOoh', 0.7);
            this.arena.excite(0.75);
            this.cam.shake(0.4);
            return;
          }
        }
      }
    }
    for (const d of this.players) {
      if (d.state !== 'DunkAir' || !d.hasBall() || d.dunkBlocked || d.stateTime > d.dunkDuration * 0.7) continue;
      for (const o of this.players) {
        if (o.team === d.team || o.state !== 'Block' || !o.isAirborne() || o.blockAttempted) continue;
        const hd = Math.min(o.bone('hand_l').distanceTo(bp), o.bone('hand_r').distanceTo(bp));
        if (hd >= 50) continue;
        o.blockAttempted = true;
        if (Math.random() < 0.35 + o.def.block * 0.03 - d.def.dunk * 0.02) {
          d.dunkBlocked = true;
          d.stats.fga++;
          const away = safeNormal2D(V(bp.x - o.pos.x, bp.y - o.pos.y, 0));
          b.deflect(V(away.x * 500, away.y * 500, 150), o);
          o.stats.blocks++;
          this.log(`DUNK BLOCKED by ${o.def.last}`);
          this.popup('DENIED!', '#4dccff', 1.25);
          A.sfx('S_Block', 1);
          A.voiceLine('VO_Block_02', 3);
          A.sfx('S_CrowdOoh', 0.9);
          this.arena.excite(1);
          return;
        }
      }
    }
  }

  giveBall(c) {
    this.ball.giveTo(c);
    c.onCaughtBall();
    if (c.team !== this.possessionTeam) this.changePossession(c.team);
  }

  changePossession(team) {
    this.possessionTeam = team;
    this.shotClockTeam = team;
    this.shotClock = HC.ShotClockLength;
    for (const s of this.ai) {
      s.holdTimer = 0;
      s.spotTimer = 0;
      s.aggro = frand(0.25, 1);
    }
  }

  beginInbound(team, hoop) {
    this.inboundTeam = team;
    this.inboundHoop = hoop;
    this.setPhase('Inbound');
  }

  placeInbound() {
    const a = this.players[this.inboundTeam * 2], b = this.players[this.inboundTeam * 2 + 1];
    const sign = this.inboundHoop === 0 ? -1 : 1;
    const spot = V(sign * (HC.CourtHalfLength + 40), 150, HC.PlayerHalfHeight);
    let inb;
    if (a.human !== b.human) inb = a.human ? b : a;
    else inb = dist2D(a.pos, spot) < dist2D(b.pos, spot) ? a : b;
    const recv = inb === a ? b : a;
    for (const c of this.players) if (c.state !== 'Free' && c.state !== 'Inbound') c.resetForPlay();
    inb.resetForPlay();
    inb.setLocation(spot.x, spot.y);
    inb.setYaw(sign > 0 ? 180 : 0);
    inb.stop();
    const rs = V(sign * (HC.CourtHalfLength - 420), -120, HC.PlayerHalfHeight);
    if (dist2D(recv.pos, rs) > 1500) recv.setLocation(rs.x, rs.y);
    this.ball.giveTo(inb);
    inb.setInbound(true);
    if (this.possessionTeam !== this.inboundTeam) this.changePossession(this.inboundTeam);
    this.shotClock = HC.ShotClockLength;
    this.shotClockTeam = this.inboundTeam;
    this.ai[this.players.indexOf(inb)].holdTimer = 0;
  }

  placeForQuarterStart(inTeam, hoop) {
    const sign = hoop === 0 ? -1 : 1;
    for (const c of this.players) {
      c.resetForPlay();
      const off = c.team === inTeam;
      const x = off ? sign * (HC.CourtHalfLength - 500) : sign * (HC.CourtHalfLength - 900);
      c.setLocation(x, (c.slot === 0 ? -1 : 1) * 250);
      c.stop();
    }
  }

  startQuarter() {
    this.quarter++;
    this.gameClock = this.quarter <= 4 ? this.quarterMinutes * 60 : 60;
    this.shotClock = HC.ShotClockLength;
    this.shotClockTeam = -1;
    this.buzzerPending = false;
    this.audio.stopMusic(1);
    if (this.quarter > 4) {
      this.setPhase('TipOff');
      return;
    }
    const fp = this.firstPossessionTeam < 0 ? 0 : this.firstPossessionTeam;
    const t = this.quarter === 4 ? fp : 1 - fp;
    const hoop = this.attackHoop(1 - t);
    this.placeForQuarterStart(t, hoop);
    this.beginInbound(t, hoop);
    this.cam.snap();
  }

  // ---------------------------------------------------------------- popups
  popup(text, color, scale = 1, sub = '', duration = 1.8) {
    if (this.popups.length >= 3) this.popups.shift();
    this.popups.push({ text, sub, color, scale, duration, time: 0, id: Math.random() });
  }
  tickPopups(dt) {
    for (let i = this.popups.length - 1; i >= 0; i--) {
      this.popups[i].time += dt;
      if (this.popups[i].time > this.popups[i].duration) this.popups.splice(i, 1);
    }
  }

  // ---------------------------------------------------------------- odds
  cpuBias(team) {
    if (this.attract || this.mode === Mode.Watch) return 0;
    const human = this.isHumanTeam(team);
    const diff = this.score[team] - this.score[1 - team];
    let b = 0;
    if (!human) {
      b += this.difficulty === Difficulty.Easy ? -0.07 : this.difficulty === Difficulty.Normal ? -0.01 : 0.04;
      if (diff <= -7) b += 0.05;
      else if (diff >= 9) b -= 0.04;
    } else if (this.difficulty === Difficulty.Easy) {
      b += 0.04;
    }
    return b;
  }

  shotChance(s, quality, layup, three, dist) {
    let p;
    if (layup) {
      p = 0.78 + (s.def.dunk + s.def.shoot - 10) * 0.01;
    } else {
      if (dist < 400) p = lerp(0.66, 0.54, dist / 400);
      else if (dist < HC.ThreeRadius) p = lerp(0.54, 0.46, (dist - 400) / (HC.ThreeRadius - 400));
      else if (dist < 900) p = lerp(0.42, 0.34, (dist - HC.ThreeRadius) / (900 - HC.ThreeRadius));
      else p = lerp(0.30, 0.04, clamp((dist - 900) / 650, 0, 1));
      const K = clamp(1 - (dist - 900) / 600, 0.2, 1);
      const rating = three ? s.def.three : s.def.shoot;
      p += K * (rating - 5) * (three ? 0.025 : 0.02);
      p += lerp(-0.22, 0.12 * K, quality);
      if (s.onFire) p += 0.28 * K - 0.28;
    }
    const { opp, dist: dd } = this.nearestOpponent(s);
    if (opp && dd < 170) {
      const c = 1 - dd / 170;
      p -= c * (opp.isAirborne() ? 0.26 : 0.15);
    }
    if (s.onFire) p += 0.28;
    else if (s.streak >= 2) p += 0.05;
    if (this.quarter >= 4 && this.gameClock < 12 && Math.abs(this.score[0] - this.score[1]) <= 5) {
      p += (s.def.clutch - 5) * 0.02;
    }
    p += this.cpuBias(s.team);
    return clamp(p, 0.03, layup ? 0.95 : 0.93);
  }

  // ---------------------------------------------------------------- events (characters)
  releaseShot(s, quality, layup) {
    if (!s || !s.hasBall()) return;
    const hoop = this.attackHoop(s.team);
    const rim = this.rimCenter(hoop);
    const loc = s.pos;
    const dist = this.distToHoop(loc, hoop);
    const three = !layup && this.isThree(loc, hoop);
    const points = three ? 3 : 2;
    const chance = this.shotChance(s, quality, layup, three, dist);
    const make = Math.random() < chance;
    const flight = layup ? 0.55 : clamp(0.78 + dist / 1500, 0.82, 1.55);
    const dir = safeNormal2D(V(rim.x - loc.x, rim.y - loc.y, 0));
    const side = V(-dir.y, dir.x, 0);
    const tgt = rim.clone();
    if (make) {
      tgt.addScaledVector(dir, frand(-2, 4)).addScaledVector(side, frand(-3, 3)).add(V(0, 0, 3));
    } else {
      const r = Math.random();
      const edge = HC.RimRadius + frand(3, 9);
      if (quality < 0.15 && !layup && Math.random() < 0.3) {
        tgt.addScaledVector(dir, -75).add(V(0, 0, -50));
      } else if (r < 0.45) {
        tgt.addScaledVector(dir, -edge).addScaledVector(side, frand(-8, 8)).add(V(0, 0, 8));
      } else if (r < 0.8) {
        tgt.addScaledVector(dir, edge).addScaledVector(side, frand(-8, 8)).add(V(0, 0, 8));
      } else {
        tgt.addScaledVector(side, Math.random() < 0.5 ? edge : -edge).add(V(0, 0, 8));
      }
    }
    this.ball.launchShot(s, hoop, points, make, s.onFire, flight, tgt);
    s.stats.fga++;
    if (three) s.stats.tpa++;
    this.log(`${s.def.last} shoots ${layup ? 'layup' : three ? '3PT' : '2PT'} from ${dist.toFixed(0)} (q=${quality.toFixed(2)} p=${chance.toFixed(2)}) -> ${make ? 'MAKE' : 'miss'}`);
    this.audio.sfx('S_Pass', 0.35, 0.8);
  }

  dunkTakeoff() {
    this.audio.sfxVariant('S_Squeak', 4, 0.6);
    this.audio.sfx('S_CrowdOoh', 0.55);
    this.arena.excite(0.6);
  }

  dunkSlam(d) {
    const hoop = this.attackHoop(d.team);
    const A = this.audio;
    if (d.dunkBlocked || !d.hasBall()) {
      this.hoops[hoop].shake(4);
      A.sfx('S_RimHit_01', 0.7);
      return;
    }
    let stuffChance = 0, stuffer = null;
    const rimC = this.rimCenter(hoop);
    for (const o of this.players) {
      if (o.team === d.team || o.state !== 'Block' || !o.isAirborne() || o.blockAttempted) continue;
      const dr = dist2D(o.pos, rimC);
      const hd = Math.min(o.bone('hand_l').distanceTo(rimC), o.bone('hand_r').distanceTo(rimC));
      if (dr < 140 && hd < 65) {
        const c = (1 - dr / 180) * (0.5 + (o.def.block - d.def.dunk) * 0.05 + (o.onFire ? 0.2 : 0));
        if (c > stuffChance) { stuffChance = c; stuffer = o; }
      }
    }
    if (d.onFire) stuffChance *= 0.4;
    if (stuffer) stuffer.blockAttempted = true;
    if (stuffer && Math.random() < stuffChance) {
      d.dunkBlocked = true;
      const away = safeNormal2D(V(rimC.x - stuffer.pos.x, rimC.y - stuffer.pos.y, 0));
      this.ball.deflect(V(away.x * -450, away.y * -450, 250), stuffer);
      stuffer.stats.blocks++;
      d.stats.fga++;
      this.hoops[hoop].shake(6);
      this.log(`STUFFED ${d.def.last} at the rim by ${stuffer.def.last}`);
      this.popup('STUFFED!', '#4dccff', 1.25);
      A.sfx('S_Block', 1);
      A.sfx('S_RimHit_02', 0.8);
      A.voiceVariant('VO_Block', 3, 3);
      A.sfx('S_CrowdOoh', 0.9);
      this.arena.excite(0.9);
      return;
    }
    this.ball.dunkThrough(hoop);
    d.stats.dunks++;
    const h = this.hoops[hoop];
    h.shake(11);
    h.swish(1.4);
    if (d.onFire) {
      h.setNetFire(4);
      h.flashGlass();
    }
    this.cam.shake(1);
    this.arena.excite(1);
    this.arena.flash(1);
    A.sfx('S_DunkSlam', 1);
    A.sfx('S_CrowdBigCheer', 0.9);
    this.onBallScored(hoop, d, 2, true);
  }

  releasePass(from, to, alley) {
    if (!from || !to || !from.hasBall()) return;
    const ap = V();
    if (alley && to.canAct() && !to.isAirborne()) {
      const hoop = this.attackHoop(to.team);
      const rim = this.rimCenter(hoop);
      const app = safeNormal2D(V(rim.x - to.pos.x, rim.y - to.pos.y, 0));
      ap.set(rim.x - app.x * 70, rim.y - app.y * 70, rim.z + 55);
      to.startDunk(true);
      this.log(`Alley-oop lob ${from.def.last} -> ${to.def.last}`);
    } else {
      alley = false;
    }
    this.ball.launchPass(from, to, alley, ap);
    this.lastPasser = from;
    this.lastPassTime = this.time;
    this.audio.sfx('S_Pass', 0.6);
  }

  resolveShove(shover, target) {
    if (!target || this.phase !== 'Live') return;
    const hadBall = target.hasBall();
    const hard = shover.powerShove;
    const dir = safeNormal2D(V(target.pos.x - shover.pos.x, target.pos.y - shover.pos.y, 0));
    const speed = (hard ? 450 : 310) + (shover.def.power - target.def.power) * 9;
    target.takeShove(dir, speed, hard);
    shover.stats.shoves++;
    if (hadBall) {
      this.ball.setLoose(V(dir.x * 260 + frand(-100, 100), dir.y * 260 + frand(-100, 100), 330), target);
    }
    this.log(`SHOVE ${shover.def.last} ${hard ? 'knocks down' : 'pushes back'} ${target.def.last}${hadBall ? ' (ball loose)' : ''}`);
    const A = this.audio;
    A.sfx('S_Shove', 0.9);
    if (hard) A.sfx('S_Fall', 0.8);
    if (hadBall || Math.random() < 0.35) A.voiceVariant('VO_Shove', 2, 1);
    A.sfx('S_CrowdOoh', 0.6);
    this.arena.excite(0.5);
    this.cam.shake(0.35);
    if (hadBall) this.popup('SHOVED!', '#ff8c26', 0.9);
  }

  resolveSteal(st) {
    const h = this.ball.getHolder();
    if (!st || !h || h.team === st.team || !this.isPlayLive() || h.state === 'Inbound') return;
    const tx = h.pos.x - st.pos.x, ty = h.pos.y - st.pos.y, tz = h.pos.z - st.pos.z;
    const d = Math.hypot(tx, ty);
    if (d > 140 || Math.abs(tz) > 70 || h.isDunking()) return;
    const f = st.forward();
    const facing = d > 1e-3 ? (f.x * tx + f.y * ty) / d : 0;
    if (facing < 0.15) return;
    let chance = 0.15 + (st.def.steal - 5) * 0.025 - (h.def.pass - 5) * 0.015;
    if (h.input.turbo) chance += 0.07;
    if (h.isShooting() || h.isDunking()) chance -= 0.12;
    if (this.ball.pos.distanceTo(st.handsCenter()) < 75) chance += 0.15;
    if (st.onFire) chance += 0.1;
    chance += this.cpuBias(st.team) * 0.6;
    if (Math.random() < chance) {
      st.stats.steals++;
      this.log(`STEAL ${st.def.last} from ${h.def.last}`);
      if (h.isShooting()) h.resetForPlay();
      if (Math.random() < 0.55) {
        this.giveBall(st);
      } else {
        const n = safeNormal2D(V(st.pos.x - h.pos.x, st.pos.y - h.pos.y, 0));
        this.ball.setLoose(V(n.x * 280, n.y * 280, 160), st);
      }
      this.popup('STEAL!', '#66ff80', 0.95);
      this.audio.sfx('S_Steal', 0.9);
      this.audio.voiceVariant('VO_Steal', 2, 1);
      this.arena.excite(0.45);
    } else {
      this.audio.sfx('S_Steal', 0.25, 1.3);
    }
  }

  requestPass(holder, to) {
    if (!holder || holder.human || !holder.canAct() || !holder.hasBall()) return;
    const hoop = this.attackHoop(to.team);
    const alley = to.input.turbo && this.distToHoop(to.pos, hoop) < to.dunkRange() + 60 && to.canAct();
    holder.startPass(to, alley);
  }

  requestShot(holder) {
    if (!holder || holder.human || !holder.canAct() || !holder.hasBall()) return;
    aiShootNow(this, holder, this.ai[this.players.indexOf(holder)]);
  }

  onJump() {
    this.audio.sfxVariant('S_Squeak', 4, 0.3, 0.1);
  }

  updateHeat(sc) {
    const A = this.audio;
    for (const p of this.players) {
      if (p.team !== sc.team) {
        if (p.onFire) {
          p.setFire(false);
          this.log(`${p.def.last}'s fire is out`);
          this.popup("FIRE'S OUT", '#80bfff', 0.8, p.def.last.toUpperCase(), 1.5);
          A.voiceLine('VO_FireOut', 2);
        }
        p.streak = 0;
        p.fireMakes = 0;
      }
    }
    sc.streak++;
    if (sc.onFire) {
      sc.fireMakes++;
      if (sc.fireMakes >= 4) {
        sc.setFire(false);
        sc.streak = 0;
        sc.fireMakes = 0;
        this.log(`${sc.def.last} cools off after 4 fire baskets`);
        this.popup('COOLED OFF', '#80bfff', 0.8, sc.def.last.toUpperCase(), 1.5);
      }
    } else if (sc.streak === 2) {
      this.log(`${sc.def.last} is heating up`);
      this.popup('HEATING UP!', '#ff9e1a', 1, sc.def.last.toUpperCase(), 2);
      A.voiceVariant('VO_Warm', 2, 2);
    } else if (sc.streak >= 3) {
      sc.setFire(true);
      sc.fireMakes = 0;
      this.log(`${sc.def.last} is ON FIRE`);
      this.popup('ON FIRE!', '#ff520a', 1.35, sc.def.last.toUpperCase(), 2.6);
      A.sfx('S_FireIgnite', 1);
      A.voiceVariant('VO_Fire', 3, 3);
      this.arena.excite(1);
      this.arena.flash(0.7);
      this.cam.shake(0.5);
    }
  }

  announceScore(sc, points, dunk) {
    const A = this.audio;
    if (dunk && sc.alleyDunk) {
      this.popup('ALLEY-OOP!', '#ffd926', 1.25);
      A.voiceLine('VO_AlleyOop', 3);
      return;
    }
    if (dunk) {
      const words = ['SLAM!', 'THROW DOWN!', 'POSTERIZED!', 'MONSTER SLAM!', 'RIM ROCKER!'];
      const i = randInt(0, 4);
      this.popup(words[i], '#ff731a', 1.3);
      A.voiceLine(`VO_Dunk_0${i + 1}`, 3);
      return;
    }
    if (points === 3) {
      const words = ['BANG! THREE!', 'SPLASH!', 'FROM DEEP!'];
      this.popup(words[randInt(0, 2)], '#59d9ff', 1.15, '3 POINTS');
      A.voiceVariant('VO_Three', 3, 2);
      A.sfx('S_CrowdCheer_01', 0.8);
      return;
    }
    if (Math.random() < 0.35) A.voiceVariant('VO_Score', 3, 1);
    A.sfx(Math.random() < 0.5 ? 'S_CrowdCheer_01' : 'S_CrowdCheer_02', 0.55);
  }

  // ---------------------------------------------------------------- events (ball)
  onBallScored(hoop, sc, points, dunk) {
    if (!sc || this.phase !== 'Live') return;
    const t = sc.team;
    this.score[t] += points;
    this.quarterScores[t][clamp(this.quarter - 1, 0, 7)] += points;
    sc.stats.points += points;
    sc.stats.fgm++;
    if (points === 3) sc.stats.tpm++;
    if (dunk) sc.stats.fga++;
    if (this.lastPasser && this.lastPasser.team === t && this.lastPasser !== sc && this.time - this.lastPassTime < 4) {
      this.lastPasser.stats.assists++;
    }
    this.lastPasser = null;
    this.log(`SCORE ${sc.def.last} +${points}${dunk ? ' (DUNK)' : ''} -> ${this.score[0]} - ${this.score[1]}`);
    const fire = sc.onFire || this.ball.shotFire;
    this.updateHeat(sc);
    const h = this.hoops[hoop];
    h.swish(dunk ? 1.4 : 1);
    if (fire || sc.onFire) {
      h.setNetFire(3.5);
      this.audio.sfx('S_FireBasket', 0.9);
    }
    if (!dunk) this.audio.sfxVariant('S_Swish', 2, 0.9);
    this.audio.sfx('S_Score', 0.4);
    this.announceScore(sc, points, dunk);
    if (this.gameClock <= 0 || this.buzzerPending) {
      this.buzzerPending = false;
      this.popup('AT THE BUZZER!', '#ffe64d', 1.2);
      this.audio.voiceLine('VO_Buzzer', 3);
    }
    this.arena.excite(dunk || points === 3 || fire ? 1 : 0.6);
    this.inboundTeam = 1 - t;
    this.inboundHoop = hoop;
    this.setPhase('Scored');
  }

  onBallRim(hoop, speed) {
    this.audio.sfxVariant('S_RimHit', 3, clamp(speed / 500, 0.25, 1));
    this.hoops[hoop].shake(clamp(speed / 120, 0.5, 4));
    this.shotClockTeam = -1;
  }
  onBallBoard(hoop, speed) {
    this.audio.sfx('S_Backboard', clamp(speed / 500, 0.3, 1));
  }
  onBallBounce(speed) {
    this.audio.sfxVariant('S_Bounce', 3, clamp(speed / 600, 0.15, 0.8), 0.08);
  }

  onBallCaught(c, passedBy) {
    if (!c) return;
    c.onCaughtBall();
    if (this.firstPossessionTeam < 0) this.firstPossessionTeam = c.team;
    if (c.team !== this.possessionTeam) this.changePossession(c.team);
    const s = this.ai[this.players.indexOf(c)];
    if (s) { s.intent = -1; s.holdTimer = 0; }
    if (this.phase === 'Inbound') {
      for (const p of this.players) if (p.state === 'Inbound') p.setInbound(false);
      this.setPhase('Live');
    }
    if (passedBy) {
      this.lastPasser = passedBy;
      this.lastPassTime = this.time;
    }
  }

  onPassIntercepted(by) {
    if (!by) return;
    by.stats.steals++;
    this.log(`INTERCEPTION by ${by.def.last}`);
    this.popup('PICKED OFF!', '#66ff80', 1);
    this.audio.sfx('S_Steal', 0.9);
    this.audio.voiceVariant('VO_Steal', 2, 1);
    for (const p of this.players) {
      if (p.state === 'Inbound') p.setInbound(false);
      if (p.alleyDunk && p.isDunking() && !p.hasBall()) p.dunkBlocked = true;
    }
    this.onBallCaught(by, null);
    if (this.phase === 'Inbound') this.setPhase('Live');
  }

  // ---------------------------------------------------------------- menus
  menuItems() {
    return [
      'START GAME',
      `MODE:  ${MODE_NAMES[this.mode]}`,
      `QUARTER LENGTH:  ${this.quarterMinutes} MIN`,
      `DIFFICULTY:  ${DIFF_NAMES[this.difficulty]}`,
      `BIG HEAD MODE:  ${this.bigHeads ? 'ON' : 'OFF'}`,
      'GRAPHICS',
      'SOUND',
      'HOW TO PLAY',
      'BACK TO TITLE',
    ];
  }
  pauseItems() { return ['RESUME', 'GRAPHICS', 'SOUND', 'HOW TO PLAY', 'RESTART GAME', 'BACK TO TITLE']; }
  modeName() { return MODE_NAMES[this.mode]; }
  difficultyName() { return DIFF_NAMES[this.difficulty]; }

  menuUp() {
    if (this.paused) this.pauseIndex = (this.pauseIndex + this.pauseItems().length - 1) % this.pauseItems().length;
    else if (this.screen === 'Menu') this.menuIndex = (this.menuIndex + this.menuItems().length - 1) % this.menuItems().length;
    else if (this.screen === 'TeamSelect') this.selectSide = 1 - this.selectSide;
    this.audio.sfx('S_UI_Move', 0.6);
  }
  menuDown() {
    if (this.paused) this.pauseIndex = (this.pauseIndex + 1) % this.pauseItems().length;
    else if (this.screen === 'Menu') this.menuIndex = (this.menuIndex + 1) % this.menuItems().length;
    else if (this.screen === 'TeamSelect') this.selectSide = 1 - this.selectSide;
    this.audio.sfx('S_UI_Move', 0.6);
  }
  /** dir = -1 / +1, player = 0 / 1 (which human pressed it, for head-to-head team select) */
  menuSide(dir, player = 0, side = null) {
    if (this.screen === 'Menu') {
      switch (this.menuIndex) {
        case 1: this.mode = (this.mode + 4 + dir) % 4; break;
        case 2: {
          const lens = [1, 2, 3, 4, 5];
          const i = Math.max(0, lens.indexOf(this.quarterMinutes));
          this.quarterMinutes = lens[(i + 5 + dir) % 5];
          break;
        }
        case 3: this.difficulty = (this.difficulty + 3 + dir) % 3; break;
        case 4: this.bigHeads = !this.bigHeads; break;
        default: break;
      }
    } else if (this.screen === 'TeamSelect') {
      const n = TEAMS.length;
      let s = side != null ? side : this.selectSide;
      if (side == null && this.mode === Mode.TwoPlayerVersus) s = player;
      this.teamIdx[s] = (this.teamIdx[s] + n + dir) % n;
      if (this.teamIdx[0] === this.teamIdx[1]) this.teamIdx[s] = (this.teamIdx[s] + n + dir) % n;
      this.setupTeams(false);
      for (const c of this.players) c.human = false;
    }
    this.audio.sfx('S_UI_Move', 0.6);
  }

  menuConfirm() {
    const A = this.audio;
    if (this.paused) {
      switch (this.pauseIndex) {
        case 0: this.togglePause(); break;
        case 1: this.optionsPage = 'graphics'; break;
        case 2: this.optionsPage = 'sound'; break;
        case 3: this.optionsPage = 'help'; break;
        case 4: this.togglePause(); this.setupTeams(false); this.startMatch(); break;
        case 5: this.returnToTitle(); break;
        default: break;
      }
      A.sfx('S_UI_Select', 0.7);
      return;
    }
    switch (this.screen) {
      case 'Title':
        this.screen = 'Menu';
        this.menuIndex = 0;
        A.sfx('S_UI_Start', 0.8);
        return;
      case 'Menu':
        if (this.menuIndex === 0) {
          this.screen = 'TeamSelect';
          this.selectSide = 0;
          if (this.teamIdx[0] === this.teamIdx[1]) this.teamIdx[1] = (this.teamIdx[0] + 1) % TEAMS.length;
        } else if (this.menuIndex === 5) this.optionsPage = 'graphics';
        else if (this.menuIndex === 6) this.optionsPage = 'sound';
        else if (this.menuIndex === 7) this.optionsPage = 'help';
        else if (this.menuIndex === 8) this.screen = 'Title';
        else { this.menuSide(1); return; }
        break;
      case 'TeamSelect':
        this.screen = 'Game';
        this.attract = false;
        this.setupTeams(false);
        this.startMatch();
        A.sfx('S_UI_Start', 0.9);
        return;
      case 'Game':
        if (this.phase === 'Break' && this.breakTimer > 0.6) this.startQuarter();
        else if (this.phase === 'GameOver' && this.phaseTime > 1.5) this.returnToTitle();
        return;
      default: break;
    }
    A.sfx('S_UI_Select', 0.7);
  }

  menuBack() {
    if (this.optionsPage) { this.optionsPage = null; this.audio.sfx('S_UI_Back', 0.6); return; }
    if (this.paused) { this.togglePause(); return; }
    if (this.screen === 'TeamSelect') this.screen = 'Menu';
    else if (this.screen === 'Menu') this.screen = 'Title';
    this.audio.sfx('S_UI_Back', 0.6);
  }

  togglePause() {
    if (this.screen !== 'Game' || this.attract) return;
    this.paused = !this.paused;
    this.pauseIndex = 0;
    this.optionsPage = null;
  }

  // ---------------------------------------------------------------- testing helper
  summary() {
    return {
      score: [...this.score], quarter: this.quarter, clock: this.gameClock, phase: this.phase,
      stats: this.players.map((c) => ({ name: c.def.last, team: c.team, ...c.stats })),
    };
  }
}

export { size2D };
