// Keyboard, gamepad and touch input. Produces per-frame FHCInput-style records for two humans
// plus edge-triggered menu navigation, mirroring HCPlayerController.cpp.

export function makeInput() {
  return {
    move: { x: 0, y: 0 },
    turbo: false,
    shootDown: false,
    shootPressed: false,
    shootReleased: false,
    passPressed: false,
    shovePressed: false,
  };
}
export function clearEdges(i) {
  i.shootPressed = i.shootReleased = i.passPressed = i.shovePressed = false;
}

const GAME_KEYS = new Set([
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space', 'Tab', 'Slash', 'Quote', 'Backspace',
]);

export class Input {
  constructor() {
    this.down = new Set();
    this.pressed = new Set();
    this.released = new Set();
    this.padPrev = [[], []];
    this.padNow = [[], []];
    this.padAxes = [[0, 0, 0, 0], [0, 0, 0, 0]];
    this.padTriggers = [[0, 0], [0, 0]];
    this.navHeld = [0, 0, 0, 0];
    this.navTimer = [0, 0, 0, 0];
    this.touch = { active: false, move: { x: 0, y: 0 }, down: new Set(), pressed: new Set(), released: new Set() };
    this.lastDevice = 'keyboard';
    this.anyPressed = false;

    window.addEventListener('keydown', (e) => {
      if (e.metaKey || e.ctrlKey) return;
      if (GAME_KEYS.has(e.code)) e.preventDefault();
      if (!this.down.has(e.code)) this.pressed.add(e.code);
      this.down.add(e.code);
      this.lastDevice = 'keyboard';
      this.anyPressed = true;
    });
    window.addEventListener('keyup', (e) => {
      if (this.down.has(e.code)) this.released.add(e.code);
      this.down.delete(e.code);
    });
    window.addEventListener('blur', () => {
      for (const k of this.down) this.released.add(k);
      this.down.clear();
    });
  }

  /** Call once per frame before reading. */
  poll(dt) {
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    let slot = 0;
    this.padPrev = this.padNow;
    this.padNow = [[], []];
    for (const p of pads) {
      if (!p || !p.connected || slot > 1) continue;
      const b = p.buttons.map((x) => x.pressed || x.value > 0.5);
      this.padNow[slot] = b;
      const ax = p.axes;
      const dz = (v) => (Math.abs(v) < 0.18 ? 0 : v);
      this.padAxes[slot] = [dz(ax[0] || 0), dz(ax[1] || 0), dz(ax[2] || 0), dz(ax[3] || 0)];
      this.padTriggers[slot] = [p.buttons[6] ? p.buttons[6].value : 0, p.buttons[7] ? p.buttons[7].value : 0];
      if (b.some((x) => x) || Math.abs(this.padAxes[slot][0]) + Math.abs(this.padAxes[slot][1]) > 0.5) {
        this.lastDevice = 'gamepad';
      }
      if (b.some((x, i) => x && !(this.padPrev[slot] && this.padPrev[slot][i]))) this.anyPressed = true;
      slot++;
    }
    for (; slot < 2; slot++) {
      this.padAxes[slot] = [0, 0, 0, 0];
      this.padTriggers[slot] = [0, 0];
    }
    this._dt = dt;
  }

  /** Call once per frame after everything has read the edges. */
  endFrame() {
    this.pressed.clear();
    this.released.clear();
    this.touch.pressed.clear();
    this.touch.released.clear();
    this.anyPressed = false;
  }

  kd(c) { return this.down.has(c); }
  kp(c) { return this.pressed.has(c); }
  kr(c) { return this.released.has(c); }
  pd(s, i) { return !!(this.padNow[s] && this.padNow[s][i]); }
  pp(s, i) { return this.pd(s, i) && !(this.padPrev[s] && this.padPrev[s][i]); }
  pr(s, i) { return !this.pd(s, i) && !!(this.padPrev[s] && this.padPrev[s][i]); }
  td(n) { return this.touch.down.has(n); }
  tp(n) { return this.touch.pressed.has(n); }
  tr(n) { return this.touch.released.has(n); }

  /** Fill an input record for human P (0 or 1). Edges are OR-ed in, so the caller clears them. */
  readPlayer(p, out) {
    let mx = 0, my = 0;
    let turbo = false, shoot = false, shootP = false, shootR = false, passP = false, shoveP = false;
    if (p === 0) {
      if (this.kd('KeyD')) mx += 1;
      if (this.kd('KeyA')) mx -= 1;
      if (this.kd('KeyW')) my -= 1;
      if (this.kd('KeyS')) my += 1;
      turbo = this.kd('KeyL') || this.kd('ShiftLeft');
      shoot = this.kd('KeyJ') || this.kd('Space');
      shootP = this.kp('KeyJ') || this.kp('Space');
      shootR = this.kr('KeyJ') || this.kr('Space');
      passP = this.kp('KeyK');
      shoveP = this.kp('KeyH');
      // touch controls drive player 1
      const t = this.touch;
      if (t.active) {
        mx += t.move.x;
        my += t.move.y;
        turbo = turbo || this.td('turbo');
        shoot = shoot || this.td('shoot');
        shootP = shootP || this.tp('shoot');
        shootR = shootR || this.tr('shoot');
        passP = passP || this.tp('pass');
        shoveP = shoveP || this.tp('shove');
      }
    } else {
      if (this.kd('ArrowRight')) mx += 1;
      if (this.kd('ArrowLeft')) mx -= 1;
      if (this.kd('ArrowUp')) my -= 1;
      if (this.kd('ArrowDown')) my += 1;
      turbo = this.kd('Numpad3') || this.kd('Slash') || this.kd('ShiftRight');
      shoot = this.kd('Numpad1') || this.kd('Comma');
      shootP = this.kp('Numpad1') || this.kp('Comma');
      shootR = this.kr('Numpad1') || this.kr('Comma');
      passP = this.kp('Numpad2') || this.kp('Period');
      shoveP = this.kp('KeyM') || this.kp('Numpad0');
    }
    // gamepad p drives human p (A shoot, X/B pass, Y shove, bumpers/RT turbo)
    const s = p;
    const ax = this.padAxes[s];
    mx += ax[0];
    my += ax[1];
    if (this.pd(s, 15)) mx += 1;
    if (this.pd(s, 14)) mx -= 1;
    if (this.pd(s, 12)) my -= 1;
    if (this.pd(s, 13)) my += 1;
    turbo = turbo || this.pd(s, 4) || this.pd(s, 5) || this.padTriggers[s][1] > 0.3 || this.padTriggers[s][0] > 0.3;
    shoveP = shoveP || this.pp(s, 3);
    shoot = shoot || this.pd(s, 0);
    shootP = shootP || this.pp(s, 0);
    shootR = shootR || this.pr(s, 0);
    passP = passP || this.pp(s, 2) || this.pp(s, 1);

    const l = Math.hypot(mx, my);
    if (l > 1) { mx /= l; my /= l; }
    out.move.x = mx;
    out.move.y = my;
    out.turbo = turbo;
    out.shootDown = shoot;
    out.shootPressed = out.shootPressed || shootP;
    out.shootReleased = out.shootReleased || shootR;
    out.passPressed = out.passPressed || passP;
    out.shovePressed = out.shovePressed || shoveP;
  }

  _nav(i, held, pressedNow) {
    if (pressedNow) {
      this.navHeld[i] = 1;
      this.navTimer[i] = 0.38;
      return true;
    }
    if (!held) {
      this.navHeld[i] = 0;
      return false;
    }
    if (!this.navHeld[i]) {
      this.navHeld[i] = 1;
      this.navTimer[i] = 0.38;
      return true;
    }
    this.navTimer[i] -= this._dt || 0.016;
    if (this.navTimer[i] <= 0) {
      this.navTimer[i] = 0.12;
      return true;
    }
    return false;
  }

  /** Menu navigation edges (with key repeat for held sticks). */
  menu() {
    const ly = this.padAxes[0][1], lx = this.padAxes[0][0];
    const ly2 = this.padAxes[1][1], lx2 = this.padAxes[1][0];
    const t = this.touch;
    const up = this._nav(0, this.pd(0, 12) || ly < -0.6, this.kp('KeyW') || this.kp('ArrowUp') || this.pp(0, 12) || this.pp(1, 12));
    const down = this._nav(1, this.pd(0, 13) || ly > 0.6, this.kp('KeyS') || this.kp('ArrowDown') || this.pp(0, 13) || this.pp(1, 13));
    const left1 = this._nav(2, this.pd(0, 14) || lx < -0.6, this.kp('KeyA') || this.pp(0, 14));
    const right1 = this._nav(3, this.pd(0, 15) || lx > 0.6, this.kp('KeyD') || this.pp(0, 15));
    const left2 = this.kp('ArrowLeft') || this.pp(1, 14) || (lx2 < -0.6 && !(this._l2));
    const right2 = this.kp('ArrowRight') || this.pp(1, 15) || (lx2 > 0.6 && !(this._r2));
    this._l2 = lx2 < -0.6;
    this._r2 = lx2 > 0.6;
    return {
      up, down, left1, right1, left2, right2,
      confirm: this.kp('Enter') || this.kp('NumpadEnter') || this.kp('Space') || this.kp('KeyJ') || this.pp(0, 0) || this.pp(0, 9) || this.pp(1, 0) || this.pp(1, 9) || t.pressed.has('confirm'),
      back: this.kp('Escape') || this.kp('Backspace') || this.pp(0, 1) || this.pp(1, 1) || t.pressed.has('back'),
      pause: this.kp('Escape') || this.kp('KeyP') || this.pp(0, 9) || this.pp(1, 9) || t.pressed.has('pause'),
      tab: this.kp('Tab') || this.pp(0, 4) || this.pp(0, 5),
    };
  }

  /** Attach on-screen touch controls (virtual stick + four buttons). */
  attachTouch(root) {
    const stick = root.querySelector('.tc-stick');
    const knob = root.querySelector('.tc-knob');
    const t = this.touch;
    let stickId = null, cx = 0, cy = 0;
    const R = 56;
    const setKnob = (dx, dy) => { knob.style.transform = `translate(${dx}px, ${dy}px)`; };
    stick.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      stickId = e.pointerId;
      stick.setPointerCapture(e.pointerId);
      const r = stick.getBoundingClientRect();
      cx = r.left + r.width / 2;
      cy = r.top + r.height / 2;
      t.active = true;
      move(e);
    });
    const move = (e) => {
      if (e.pointerId !== stickId) return;
      let dx = e.clientX - cx, dy = e.clientY - cy;
      const l = Math.hypot(dx, dy);
      if (l > R) { dx *= R / l; dy *= R / l; }
      setKnob(dx, dy);
      const m = Math.min(1, l / R);
      const n = l > 1 ? 1 / l : 0;
      t.move.x = (e.clientX - cx) * n * (m < 0.18 ? 0 : m);
      t.move.y = (e.clientY - cy) * n * (m < 0.18 ? 0 : m);
    };
    const end = (e) => {
      if (e.pointerId !== stickId) return;
      stickId = null;
      t.move.x = t.move.y = 0;
      setKnob(0, 0);
    };
    stick.addEventListener('pointermove', move);
    stick.addEventListener('pointerup', end);
    stick.addEventListener('pointercancel', end);
    for (const b of root.querySelectorAll('[data-tc]')) {
      const name = b.dataset.tc;
      const on = (e) => {
        e.preventDefault();
        b.setPointerCapture?.(e.pointerId);
        t.active = true;
        if (!t.down.has(name)) t.pressed.add(name);
        t.down.add(name);
        b.classList.add('on');
        this.anyPressed = true;
      };
      const off = () => {
        if (t.down.has(name)) t.released.add(name);
        t.down.delete(name);
        b.classList.remove('on');
      };
      b.addEventListener('pointerdown', on);
      b.addEventListener('pointerup', off);
      b.addEventListener('pointercancel', off);
      b.addEventListener('lostpointercapture', off);
    }
  }
}
