// DOM HUD and menus (port of AHCHUD's canvas drawing): scoreboard, player cards, popups,
// shot meter, title / menu / team select / pause / options / box score screens.
import * as THREE from 'three';
import { TEAMS } from './roster.js';
import { HC, V, clamp, toThree } from './consts.js';
import { Mode } from './game.js';
import { BUSES } from './audio.js';

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function fmtClock(t) {
  if (t < 10 && t > 0) return t.toFixed(1);
  const s = Math.ceil(t);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
function textColor(hex) {
  const c = new THREE.Color(hex);
  const l = 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
  return l > 0.35 ? '#111' : '#fff';
}
function brighten(hex) {
  const c = new THREE.Color(hex);
  const hsl = {};
  c.getHSL(hsl);
  if (hsl.l < 0.45) c.setHSL(hsl.h, Math.min(1, hsl.s + 0.1), 0.55);
  return '#' + c.getHexString();
}

export const QUALITY = ['PERFORMANCE', 'BALANCED', 'HIGH', 'ULTRA'];

export const GRAPHICS_ROWS = [
  { key: 'quality', label: 'PRESET', kind: 'enum', values: QUALITY },
  { key: 'renderScale', label: 'RENDER SCALE', kind: 'pct', min: 0.5, max: 1, step: 0.05 },
  { key: 'shadows', label: 'SHADOWS', kind: 'bool' },
  { key: 'bloom', label: 'BLOOM', kind: 'bool' },
  { key: 'crowd', label: 'ANIMATED CROWD', kind: 'bool' },
  { key: 'antialias', label: 'ANTI-ALIASING', kind: 'bool', note: 'reload' },
  { key: 'showFps', label: 'FPS METER', kind: 'bool' },
];
export const SOUND_ROWS = [
  ...BUSES.map((b) => ({ key: b, label: b === 'interface' ? 'MENU SOUNDS' : b === 'effects' ? 'GAMEPLAY EFFECTS' : b.toUpperCase(), kind: 'vol' })),
  { key: 'muted', label: 'MUTE ALL', kind: 'bool' },
];

export class HUD {
  constructor(app) {
    this.app = app;
    this.game = app.game;
    this.sb = $('#scoreboard');
    this.cards = $('#cards');
    this.popupsEl = $('#popups');
    this.meter = $('#meter');
    this.tags = $('#tags');
    this.fps = $('#fps');
    this.screens = $('#screens');
    this.screenKey = '';
    this.popupEls = new Map();
    this.cardEls = [];
    this.optRow = 0;
    this.lastScore = [0, 0];
    this.v = new THREE.Vector3();
    this.screens.addEventListener('click', (e) => this.onClick(e));
    this.screens.addEventListener('pointermove', (e) => this.onHover(e));
    this.fpsAcc = { t: 0, n: 0, worst: 0, text: '' };
  }

  // ------------------------------------------------------------------ projection
  project(p) {
    const cam = this.app.camera;
    const v = toThree(p, this.v).project(cam);
    const w = this.app.width, h = this.app.height;
    return { x: (v.x * 0.5 + 0.5) * w, y: (-v.y * 0.5 + 0.5) * h, ok: v.z < 1 };
  }

  // ------------------------------------------------------------------ per frame
  update(dt) {
    const g = this.game;
    const inGame = g.screen === 'Game';
    const showBoard = inGame && g.phase !== 'Intro' && !(g.phase === 'Break' || g.phase === 'GameOver');
    this.sb.hidden = !showBoard;
    this.cards.hidden = !showBoard;
    if (showBoard) {
      this.updateScoreboard();
      this.updateCards();
    }
    this.updatePopups();
    this.updateMeter();
    this.updateTags(inGame);
    this.updateScreens();
    this.updateFps(dt);
  }

  updateScoreboard() {
    const g = this.game;
    const sb = this.sb;
    for (let t = 0; t < 2; t++) {
      const td = g.teamDef(t);
      const el = sb.querySelector(t === 0 ? '.sb-left' : '.sb-right');
      if (el.dataset.abbr !== td.abbr) {
        el.dataset.abbr = td.abbr;
        el.style.background = td.primary;
        el.style.color = textColor(td.primary);
        el.style.setProperty('--team-2', td.secondary);
        el.querySelector('.sb-abbr').textContent = td.abbr;
        el.querySelector('.sb-name').textContent = td.name;
      }
      const sc = sb.querySelector(t === 0 ? '.sb-score-left' : '.sb-score-right');
      if (sc.textContent !== String(g.score[t])) {
        sc.textContent = g.score[t];
        if (g.score[t] > this.lastScore[t]) {
          sc.classList.remove('bump');
          void sc.offsetWidth;
          sc.classList.add('bump');
        }
        this.lastScore[t] = g.score[t];
      }
    }
    const q = g.quarter <= 4 ? `QUARTER ${g.quarter}` : g.quarter === 5 ? 'OVERTIME' : `OVERTIME ${g.quarter - 4}`;
    const qe = sb.querySelector('.sb-quarter');
    if (qe.textContent !== q) qe.textContent = q;
    const ck = sb.querySelector('.sb-clock');
    const ct = fmtClock(g.gameClock);
    if (ck.textContent !== ct) ck.textContent = ct;
    ck.classList.toggle('low', g.gameClock < 10);
    const shot = sb.querySelector('.sb-shot');
    const live = g.shotClockTeam >= 0 && (g.phase === 'Live' || g.phase === 'Inbound');
    shot.style.visibility = live ? 'visible' : 'hidden';
    const st = String(Math.ceil(Math.min(g.shotClock, 24)));
    if (shot.firstChild.textContent !== st) shot.firstChild.textContent = st;
    shot.classList.toggle('low', g.shotClock < 5);
  }

  updateCards() {
    const g = this.game;
    if (!this.cardEls.length) {
      const sides = [this.cards.querySelector('.cards-left'), this.cards.querySelector('.cards-right')];
      for (let i = 0; i < 4; i++) {
        const d = document.createElement('div');
        d.className = 'card';
        d.innerHTML = '<span class="who"></span><span class="nm"></span><span class="pts"></span><div class="tb"><div class="bar"><i></i></div><span class="tl">TURBO</span><span class="heat"></span></div>';
        sides[i >> 1].appendChild(d);
        this.cardEls.push(d);
      }
    }
    g.players.forEach((c, i) => {
      const el = this.cardEls[i];
      const td = g.teamDef(c.team);
      const who = c.human ? `P${c.humanIndex + 1}` : 'CPU';
      const key = `${who}|${c.def.number}|${c.def.last}|${td.primary}`;
      if (el.dataset.key !== key) {
        el.dataset.key = key;
        el.style.setProperty('--team', td.primary);
        el.classList.toggle('human', c.human);
        el.classList.toggle('p2', c.humanIndex === 1);
        el.querySelector('.who').textContent = who;
        el.querySelector('.nm').textContent = `#${c.def.number} ${c.def.last}`;
      }
      const pts = `${c.stats.points} PTS`;
      const pe = el.querySelector('.pts');
      if (pe.textContent !== pts) pe.textContent = pts;
      const bar = el.querySelector('.bar i');
      bar.style.width = `${Math.round(c.turbo * 100)}%`;
      bar.classList.toggle('low', c.turbo < 0.25);
      el.classList.toggle('fire', c.onFire);
      el.querySelector('.heat').classList.toggle('warm', c.streak >= 2 && !c.onFire);
    });
  }

  updatePopups() {
    const g = this.game;
    const seen = new Set();
    const w = this.app.width;
    const ui = Math.min(this.app.width / 100, this.app.height / 56.2);
    const scored = g.popups.length && g.phase === 'Scored';
    let center = w * 0.5;
    if (scored) {
      const rx = this.project(g.rimCenter(g.inboundHoop)).x;
      center = w * (rx >= center ? 0.27 : 0.73);
    }
    g.popups.forEach((p, i) => {
      seen.add(p.id);
      let el = this.popupEls.get(p.id);
      if (!el) {
        el = document.createElement('div');
        el.className = 'popup';
        el.innerHTML = `${esc(p.text)}${p.sub ? `<small>${esc(p.sub)}</small>` : ''}`;
        el.style.color = p.color;
        this.popupsEl.appendChild(el);
        this.popupEls.set(p.id, el);
      }
      const T = p.time / p.duration;
      const inn = clamp(p.time * 7, 0, 1);
      const pop = 1 + 0.35 * (1 - inn) * (1 - inn);
      const alpha = clamp((1 - T) * 5, 0, 1);
      const size = (scored ? 6.2 : 8.4) * p.scale * ui;
      el.style.fontSize = `${size}px`;
      el.style.left = `${center}px`;
      el.style.top = `${(23 + i * 11) * ui}px`;
      el.style.opacity = alpha;
      el.style.transform = `translate(-50%, -50%) scale(${pop})`;
    });
    for (const [id, el] of this.popupEls) {
      if (!seen.has(id)) {
        el.remove();
        this.popupEls.delete(id);
      }
    }
  }

  updateMeter() {
    const g = this.game;
    let shown = false;
    for (const c of g.players) {
      if (!c.human || !(c.state === 'ShootAir' || c.state === 'ShootWindup') || c.shotReleased) continue;
      const p = this.project(V(c.pos.x, c.pos.y, c.pos.z + 60));
      if (!p.ok) continue;
      let T = 0;
      if (c.state === 'ShootAir') T = (g.time - c.launchTime) / Math.max(0.05, c.apexTime - c.launchTime);
      const ui = Math.min(this.app.width / 100, this.app.height / 56.2);
      this.meter.style.left = `${p.x + 6 * ui}px`;
      this.meter.style.top = `${p.y - 6 * ui}px`;
      const fill = clamp(T, 0, 1.2) / 1.2;
      const good = Math.abs(T - 1) < 0.2;
      const f = this.meter.lastChild;
      f.style.height = `${fill * 100}%`;
      f.style.background = good ? '#4dff59' : T > 1.2 ? '#ff3319' : '#ffcc33';
      shown = true;
      break;
    }
    this.meter.hidden = !shown;
  }

  updateTags(inGame) {
    const g = this.game;
    const want = [];
    if (inGame && g.phase !== 'Break' && g.phase !== 'GameOver') {
      for (const c of g.players) if (c.human) want.push(c);
    }
    while (this.tags.children.length < want.length) {
      const d = document.createElement('div');
      d.className = 'tag';
      this.tags.appendChild(d);
    }
    [...this.tags.children].forEach((el, i) => {
      const c = want[i];
      if (!c) { el.hidden = true; return; }
      const p = this.project(V(c.pos.x, c.pos.y, c.pos.z + 125 * c.def.height + (g.bigHeads ? 40 : 0)));
      el.hidden = !p.ok;
      el.textContent = `P${c.humanIndex + 1}`;
      el.classList.toggle('p2', c.humanIndex === 1);
      el.style.left = `${p.x}px`;
      el.style.top = `${p.y}px`;
    });
  }

  updateFps(dt) {
    const a = this.fpsAcc;
    a.t += dt;
    a.n++;
    a.worst = Math.max(a.worst, dt);
    if (a.t > 0.5) {
      a.text = `${Math.round(a.n / a.t)} FPS  ${(1000 * a.t / a.n).toFixed(1)} ms  max ${(a.worst * 1000).toFixed(0)} ms`;
      a.t = 0; a.n = 0; a.worst = 0;
    }
    this.fps.hidden = !this.app.settings.showFps;
    if (!this.fps.hidden && this.fps.textContent !== a.text) this.fps.textContent = a.text;
  }

  // ------------------------------------------------------------------ screens
  screenState() {
    const g = this.game;
    if (g.optionsPage) return `opt|${g.optionsPage}|${this.optRow}|${JSON.stringify(this.app.settings)}|${JSON.stringify(this.app.audio.levels)}`;
    if (g.paused) return `pause|${g.pauseIndex}`;
    switch (g.screen) {
      case 'Title': return 'title';
      case 'Menu': return `menu|${g.menuIndex}|${g.menuItems().join()}`;
      case 'TeamSelect': return `ts|${g.teamIdx}|${g.selectSide}|${g.mode}`;
      default: break;
    }
    if (g.phase === 'Intro' && !g.attract) return `intro|${g.teamIdx}`;
    if (g.phase === 'Break') return `break|${g.quarter}|${g.score}`;
    if (g.phase === 'GameOver') return `over|${g.score}|${g.phaseTime > 1.5}`;
    return '';
  }

  updateScreens() {
    const key = this.screenState();
    if (key === this.screenKey) return;
    this.screenKey = key;
    const kind = key.split('|')[0];
    const html = {
      '': () => '',
      title: () => this.titleHTML(),
      menu: () => this.menuHTML(),
      ts: () => this.teamSelectHTML(),
      intro: () => this.introHTML(),
      pause: () => this.pauseHTML(),
      opt: () => this.optionsHTML(),
      break: () => this.boxHTML(false),
      over: () => this.boxHTML(true),
    }[kind]();
    this.screens.innerHTML = html;
  }

  controlsHint() {
    return `<div class="hint kb">MOVE <b>WASD / STICK</b> &nbsp; SHOOT <b>J / SPACE / A</b> &nbsp; PASS·STEAL <b>K / X</b> &nbsp; SHOVE <b>H / Y</b> &nbsp; TURBO <b>SHIFT / L / RB</b><br>
      TURBO + SHOOT NEAR THE RIM = <b>DUNK</b> &nbsp; TURBO + SHOVE = <b>KNOCKDOWN</b> &nbsp; TURBO + PASS = <b>ALLEY-OOP</b></div>
      <div class="hint touch-only">LEFT STICK MOVES &nbsp; HOLD <b>SHOOT</b>, RELEASE AT THE TOP &nbsp; <b>TURBO + SHOOT</b> NEAR THE RIM TO DUNK</div>`;
  }

  titleHTML() {
    return `<div class="screen">
      <img class="title-logo" src="assets/ui/UI_Logo.png" alt="HEAT CHECK">
      <button class="press" data-act="confirm">${document.body.classList.contains('touch') ? 'TAP TO START' : 'PRESS ENTER OR START'}</button>
      ${this.controlsHint()}
      <div class="foot"><span><a href="../">← HEAT CHECK HOME</a></span><span class="kb">ENTER / START &nbsp;PLAY</span></div>
    </div>`;
  }

  menuHTML() {
    const g = this.game;
    const items = g.menuItems().map((t, i) => {
      const adj = i >= 1 && i <= 4;
      return `<button class="${i === g.menuIndex ? 'sel' : ''}" data-act="menu" data-i="${i}">
        ${adj ? `<span class="arrows" data-act="menu-left" data-i="${i}">◀</span>` : ''}<span>${esc(t)}</span>${adj ? `<span class="arrows" data-act="menu-right" data-i="${i}">▶</span>` : '<span></span>'}</button>`;
    }).join('');
    return `<div class="screen dim"><h2>MAIN MENU</h2><div class="menu" role="menu">${items}</div>
      <div class="foot kb"><span>W / S &nbsp;SELECT</span><span>A / D &nbsp;CHANGE</span><span>ENTER &nbsp;CONFIRM</span><span>ESC &nbsp;BACK</span></div></div>`;
  }

  teamSelectHTML() {
    const g = this.game;
    const sideLabel = (s) => {
      if (g.mode === Mode.Watch) return 'CPU';
      if (g.mode === Mode.TwoPlayerCoop) return s === 0 ? 'PLAYERS 1 + 2' : 'CPU';
      if (g.mode === Mode.TwoPlayerVersus) return s === 0 ? 'PLAYER 1' : 'PLAYER 2';
      return s === 0 ? 'PLAYER 1' : 'CPU';
    };
    const card = (s) => {
      const td = TEAMS[g.teamIdx[s]];
      const players = td.players.map((p) => {
        const st = [['SPD', p.speed], ['3PT', p.three], ['DNK', p.dunk], ['PWR', p.power], ['STL', p.steal], ['BLK', p.block]]
          .map(([k, v]) => `<div>${k}<i><b class="${v < 6 ? 'lo' : ''}" style="width:${v * 10}%"></b></i></div>`).join('');
        return `<div class="ts-player"><div class="pn">#${p.number} &nbsp;${esc(p.first)} ${esc(p.last)}</div><div class="nick">"${esc(p.nick)}"</div><div class="ts-stats">${st}</div></div>`;
      }).join('');
      return `<div class="ts-card ${g.selectSide === s && g.mode !== Mode.TwoPlayerVersus ? 'sel' : ''}" style="--team:${td.primary};--team-text:${brighten(td.primary)}" data-act="side" data-s="${s}">
        <div class="ts-who">${sideLabel(s)}</div>
        <div class="ts-badge-row"><button class="ts-arrow" data-act="team-left" data-s="${s}" aria-label="Previous team">&lt;</button>
        <img class="ts-badge" src="assets/ui/UI_Team_${td.abbr}.png" alt="${esc(td.city)} ${esc(td.name)} badge">
        <button class="ts-arrow" data-act="team-right" data-s="${s}" aria-label="Next team">&gt;</button></div>
        <div class="ts-city">${esc(td.city)}</div><div class="ts-name">${esc(td.name)}</div>${players}</div>`;
    };
    const keys = g.mode === Mode.TwoPlayerVersus ? '<span>P1 A / D &nbsp;·&nbsp; P2 ← / → &nbsp;CHANGE TEAM</span>' : '<span>A / D &nbsp;CHANGE TEAM</span><span>W / S &nbsp;SWITCH SIDE</span>';
    return `<div class="screen dim"><h2>CHOOSE YOUR TEAMS</h2>
      <div class="ts">${card(0)}<div class="ts-vs">VS</div>${card(1)}</div>
      <div class="foot">${keys}<span><a href="#" data-act="confirm">ENTER &nbsp;TIP OFF!</a></span><span><a href="#" data-act="back">ESC &nbsp;BACK</a></span></div></div>`;
  }

  introHTML() {
    const g = this.game;
    const a = g.teamDef(0), b = g.teamDef(1);
    const t = (td, cls) => `<div class="intro-team ${cls}" style="color:${brighten(td.primary)}"><img src="assets/ui/UI_Team_${td.abbr}.png" alt="">${esc(td.city)} ${esc(td.name)}</div>`;
    return `<div class="intro-banner">${t(b, 'left')}<div class="intro-vs">VS</div>${t(a, 'right')}</div>`;
  }

  pauseHTML() {
    const g = this.game;
    const items = g.pauseItems().map((t, i) => `<button class="${i === g.pauseIndex ? 'sel' : ''}" data-act="pause" data-i="${i}"><span>${t}</span><span></span></button>`).join('');
    return `<div class="screen dim"><h2>PAUSED</h2><div class="menu">${items}</div>
      <div class="foot kb"><span>W / S &nbsp;SELECT</span><span>ENTER &nbsp;CONFIRM</span><span>ESC &nbsp;RESUME</span></div></div>`;
  }

  optionsHTML() {
    const g = this.game;
    const page = g.optionsPage;
    const tabs = ['graphics', 'sound', 'help'].map((p) => `<button class="${p === page ? 'on' : ''}" data-act="tab" data-p="${p}">${p === 'help' ? 'HOW TO PLAY' : p.toUpperCase()}</button>`).join('');
    let body = '';
    if (page === 'help') {
      body = this.helpHTML();
    } else {
      const rows = page === 'graphics' ? GRAPHICS_ROWS : SOUND_ROWS;
      const s = this.app.settings, L = this.app.audio.levels;
      body = rows.map((r, i) => {
        let val = '';
        const v = page === 'graphics' ? s[r.key] : L[r.key];
        if (r.kind === 'enum') val = r.values[v];
        else if (r.kind === 'bool') val = v ? 'ON' : 'OFF';
        else if (r.kind === 'pct') val = `${Math.round(v * 100)}%`;
        else if (r.kind === 'vol') val = `<span class="slider"><b style="width:${Math.round(v * 100)}%"></b></span>${Math.round(v * 100)}`;
        return `<div class="opt-row ${i === this.optRow ? 'sel' : ''}" data-act="opt" data-i="${i}"><span>${r.label}${r.note ? ' <small style="opacity:.6">(RELOAD)</small>' : ''}</span>
          <span class="val"><button data-act="opt-left" data-i="${i}" aria-label="Decrease">◀</button>${val}<button data-act="opt-right" data-i="${i}" aria-label="Increase">▶</button></span></div>`;
      }).join('');
    }
    return `<div class="screen dim"><div class="panel"><h2 style="font-size:calc(var(--ui)*4.6)">OPTIONS</h2><div class="opt-tabs">${tabs}</div>${body}
      <div style="margin-top:calc(var(--ui)*1.6);font-size:calc(var(--ui)*1.9);color:#ccc">↑↓ SELECT &nbsp; ←→ ADJUST &nbsp; TAB SWITCH &nbsp; <a href="#" data-act="back" style="color:var(--gold)">ESC BACK</a></div></div></div>`;
  }

  helpHTML() {
    return `<div class="help">
      <table><tr><th></th><th>Player 1 keyboard</th><th>Gamepad</th><th>Player 2 keyboard</th></tr>
      <tr><td>Move</td><td>W A S D</td><td>Left stick / D-pad</td><td>Arrow keys</td></tr>
      <tr><td>Shoot / jump / block</td><td>J or Space (hold, release at the top)</td><td>A</td><td>Numpad 1 or ,</td></tr>
      <tr><td>Pass / steal</td><td>K</td><td>X or B</td><td>Numpad 2 or .</td></tr>
      <tr><td>Shove</td><td>H</td><td>Y</td><td>M or Numpad 0</td></tr>
      <tr><td>Turbo</td><td>Shift or L</td><td>RB / LB / RT</td><td>Numpad 3, / or Right Shift</td></tr>
      <tr><td>Pause</td><td>Esc or P</td><td>Start</td><td></td></tr></table>
      <ul>
        <li><b>Turbo + Shoot</b> inside dunk range is a dunk: two-hand, windmill, 360, reverse, and a flip when you're on fire.</li>
        <li><b>Shove</b> a nearby opponent to knock the ball loose. <b>Turbo + Shove</b> knocks them down. No fouls.</li>
        <li><b>Turbo + Pass</b> to a teammate near the rim throws an <b>alley-oop</b>.</li>
        <li>When your CPU teammate has the ball, <b>Pass</b> calls for it and <b>Shoot</b> tells them to shoot.</li>
        <li>Release jump shots at the top of the jump: the meter turns green.</li>
        <li>Make 2 in a row to heat up. Make 3 and you're <b>ON FIRE</b>: unlimited turbo, deadly shooting, goaltending allowed.</li>
        <li>Only the 24-second shot clock and goaltending are called.</li>
      </ul></div>`;
  }

  boxHTML(over) {
    const g = this.game;
    const rows = [0, 1].map((t) => {
      const td = g.teamDef(t);
      const ps = g.players.filter((c) => c.team === t).map((c) => {
        const s = c.stats;
        return `<tr><td>#${c.def.number} ${esc(c.def.last)}</td><td>${s.points}</td><td>${s.fgm}-${s.fga}</td><td>${s.tpm}-${s.tpa}</td><td>${s.dunks}</td><td>${s.rebounds}</td><td>${s.assists}</td><td>${s.steals}</td><td>${s.blocks}</td><td>${s.shoves}</td></tr>`;
      }).join('');
      return `<tr class="teamrow"><td style="color:${brighten(td.primary)}">${esc(td.city)} ${esc(td.name)}</td><td>${g.score[t]}</td><td colspan="8"></td></tr>${ps}`;
    }).join('');
    const label = over ? '' : g.quarter === 2 ? 'HALFTIME' : g.quarter >= 4 ? 'END OF REGULATION' : `END OF QUARTER ${g.quarter}`;
    const head = over ? `<div class="winner">${esc(g.winnerText)}</div>` : `<h2>${label}</h2>`;
    const prompt = over ? (g.attract ? '' : '<a href="#" data-act="confirm">PRESS START FOR THE TITLE SCREEN</a>')
      : (g.attract || g.mode === Mode.Watch ? '' : '<a href="#" data-act="confirm">PRESS START TO CONTINUE</a>');
    return `<div class="screen dim"><div class="panel">${head}
      <div class="qs"><span>${esc(g.teamDef(0).abbr)} ${g.score[0]}</span><span>${esc(g.teamDef(1).abbr)} ${g.score[1]}</span></div>
      <table class="box"><tr><th>PLAYER</th><th>PTS</th><th>FG</th><th>3PT</th><th>DNK</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>SHV</th></tr>${rows}</table>
      <div style="text-align:center;margin-top:calc(var(--ui)*2);font-size:calc(var(--ui)*2.6)" class="press-sm">${prompt}</div></div></div>`;
  }

  // ------------------------------------------------------------------ options navigation (keyboard / pad)
  optionRows() {
    const p = this.game.optionsPage;
    return p === 'graphics' ? GRAPHICS_ROWS : p === 'sound' ? SOUND_ROWS : [];
  }
  optNav(nav) {
    const g = this.game;
    const rows = this.optionRows();
    if (nav.tab) {
      const order = ['graphics', 'sound', 'help'];
      g.optionsPage = order[(order.indexOf(g.optionsPage) + 1) % order.length];
      this.optRow = 0;
      this.app.audio.sfx('S_UI_Move', 0.6);
    }
    if (rows.length) {
      if (nav.up) { this.optRow = (this.optRow + rows.length - 1) % rows.length; this.app.audio.sfx('S_UI_Move', 0.6); }
      if (nav.down) { this.optRow = (this.optRow + 1) % rows.length; this.app.audio.sfx('S_UI_Move', 0.6); }
      if (nav.left1 || nav.left2) this.adjust(this.optRow, -1);
      if (nav.right1 || nav.right2) this.adjust(this.optRow, 1);
      if (nav.confirm) {
        const r = rows[this.optRow];
        if (r && r.kind === 'vol') this.app.audio.preview(r.key);
        else this.adjust(this.optRow, 1);
      }
    }
    if (nav.back) g.menuBack();
  }

  adjust(i, dir) {
    const rows = this.optionRows();
    const r = rows[i];
    if (!r) return;
    const page = this.game.optionsPage;
    if (page === 'graphics') {
      const s = this.app.settings;
      if (r.kind === 'enum') s[r.key] = (s[r.key] + r.values.length + dir) % r.values.length;
      else if (r.kind === 'bool') s[r.key] = !s[r.key];
      else if (r.kind === 'pct') s[r.key] = clamp(Math.round((s[r.key] + dir * r.step) * 100) / 100, r.min, r.max);
      this.app.applySettings(r.key);
    } else {
      const L = this.app.audio.levels;
      if (r.kind === 'bool') L[r.key] = !L[r.key];
      else L[r.key] = clamp(Math.round((L[r.key] + dir * 0.1) * 10) / 10, 0, 1);
      this.app.audio.applyLevels();
      this.app.saveSettings();
    }
    this.app.audio.sfx('S_UI_Move', 0.6);
  }

  // ------------------------------------------------------------------ pointer
  onHover(e) {
    const t = e.target.closest('[data-act]');
    if (!t) return;
    const g = this.game;
    const i = Number(t.dataset.i);
    if (t.dataset.act === 'menu' && g.menuIndex !== i) { g.menuIndex = i; }
    if (t.dataset.act === 'pause' && g.pauseIndex !== i) { g.pauseIndex = i; }
    if (t.dataset.act === 'opt' && this.optRow !== i) { this.optRow = i; }
  }

  onClick(e) {
    const t = e.target.closest('[data-act]');
    if (!t) return;
    e.preventDefault();
    e.stopPropagation();
    this.app.audio.unlock();
    const g = this.game;
    const act = t.dataset.act;
    const i = Number(t.dataset.i);
    const s = Number(t.dataset.s);
    switch (act) {
      case 'confirm': g.menuConfirm(); break;
      case 'back': g.menuBack(); break;
      case 'menu': g.menuIndex = i; g.menuConfirm(); break;
      case 'menu-left': g.menuIndex = i; g.menuSide(-1); break;
      case 'menu-right': g.menuIndex = i; g.menuSide(1); break;
      case 'pause': g.pauseIndex = i; g.menuConfirm(); break;
      case 'team-left': g.menuSide(-1, 0, s); break;
      case 'team-right': g.menuSide(1, 0, s); break;
      case 'side': if (g.selectSide !== s) { g.selectSide = s; g.audio.sfx('S_UI_Move', 0.6); } break;
      case 'tab': g.optionsPage = t.dataset.p; this.optRow = 0; break;
      case 'opt': this.optRow = i; this.adjust(i, 1); break;
      case 'opt-left': this.optRow = i; this.adjust(i, -1); break;
      case 'opt-right': this.optRow = i; this.adjust(i, 1); break;
      default: break;
    }
    this.screenKey = '';
  }
}
export { HC };
