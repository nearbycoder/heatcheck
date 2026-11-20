// WebAudio port of UHCAudio: one-shot effects, an announcer queue with priorities,
// looping music with fades and a crowd bed whose level follows the arena excitement.
import { clamp, finterp, randInt, frand } from './consts.js';

export const BUSES = ['master', 'music', 'announcer', 'crowd', 'effects', 'interface'];

export class Audio {
  constructor(base) {
    this.base = base;
    this.ctx = null;
    this.buffers = new Map();
    this.names = [];
    this.voice = null;
    this.voicePriority = 0;
    this.music = null;
    this.currentMusic = '';
    this.crowd = null;
    this.crowdVolume = 0.3;
    this.crowdEnergy = 0.2;
    this.levels = { master: 0.8, music: 0.7, announcer: 1, crowd: 0.8, effects: 0.9, interface: 0.8, muted: false };
    this.pendingMusic = null;
  }

  async init(names, onProgress) {
    this.names = names;
    const AC = window.AudioContext || window.webkitAudioContext;
    this.ctx = new AC({ latencyHint: 'interactive' });
    this.master = this.ctx.createGain();
    this.master.connect(this.ctx.destination);
    this.bus = {};
    for (const b of BUSES.slice(1)) {
      const g = this.ctx.createGain();
      g.connect(this.master);
      this.bus[b] = g;
    }
    this.applyLevels();
    let done = 0;
    await Promise.all(names.map(async (n) => {
      try {
        const res = await fetch(`${this.base}/${n}.mp3`);
        const data = await res.arrayBuffer();
        const buf = await new Promise((ok, fail) => this.ctx.decodeAudioData(data, ok, fail));
        this.buffers.set(n, buf);
      } catch (e) {
        console.warn('audio failed', n, e);
      }
      done++;
      onProgress && onProgress(done / names.length);
    }));
  }

  /** Browsers only start audio after a user gesture. */
  unlock() {
    if (this.ctx && this.ctx.state !== 'running') this.ctx.resume();
    if (this.pendingMusic) {
      const [n, v] = this.pendingMusic;
      this.pendingMusic = null;
      this.playMusic(n, v);
    }
  }
  get running() { return this.ctx && this.ctx.state === 'running'; }

  applyLevels() {
    if (!this.ctx) return;
    const L = this.levels;
    const t = this.ctx.currentTime;
    this.master.gain.setTargetAtTime(L.muted ? 0 : L.master, t, 0.04);
    for (const b of BUSES.slice(1)) this.bus[b].gain.setTargetAtTime(L[b], t, 0.04);
  }

  _src(name, bus, volume = 1, pitch = 1, loop = false) {
    const buf = this.buffers.get(name);
    if (!buf || !this.ctx) return null;
    const s = this.ctx.createBufferSource();
    s.buffer = buf;
    s.loop = loop;
    s.playbackRate.value = pitch;
    const g = this.ctx.createGain();
    g.gain.value = volume;
    s.connect(g);
    g.connect(this.bus[bus]);
    s.start();
    return { src: s, gain: g, name, ended: false, start: this.ctx.currentTime, dur: buf.duration / pitch };
  }

  has(name) { return this.buffers.has(name); }

  sfx(name, volume = 1, pitch = 1) {
    if (!this.running) return;
    const bus = name.startsWith('S_UI') ? 'interface' : name.startsWith('S_Crowd') ? 'crowd' : 'effects';
    this._src(name, bus, volume, pitch);
  }

  sfxVariant(base, count, volume = 1, jitter = 0) {
    const n = `${base}_${String(randInt(1, Math.max(1, count))).padStart(2, '0')}`;
    const pitch = 1 + frand(-jitter, jitter);
    this.sfx(this.has(n) ? n : base, volume, pitch);
  }

  voiceLine(name, priority) {
    if (!this.running || !this.has(name)) return;
    if (this.voice && !this.voice.ended && this.ctx.currentTime < this.voice.start + this.voice.dur) {
      if (priority <= this.voicePriority) return;
      try { this.voice.src.stop(); } catch (e) { /* already stopped */ }
    }
    this.voice = this._src(name, 'announcer', 1, 1);
    if (this.voice) {
      const v = this.voice;
      v.src.onended = () => { v.ended = true; };
    }
    this.voicePriority = priority;
  }

  voiceVariant(base, count, priority) {
    this.voiceLine(`${base}_${String(randInt(1, Math.max(1, count))).padStart(2, '0')}`, priority);
  }

  playMusic(name, volume) {
    if (!this.running) {
      this.pendingMusic = [name, volume];
      return;
    }
    if (this.currentMusic === name && this.music) {
      this.music.gain.gain.setTargetAtTime(volume, this.ctx.currentTime, 0.3);
      return;
    }
    this.stopMusic(0.8);
    const m = this._src(name, 'music', 0, 1, true);
    if (m) {
      m.gain.gain.setTargetAtTime(volume, this.ctx.currentTime, 0.33);
      this.music = m;
      this.currentMusic = name;
    }
  }

  stopMusic(fade = 1) {
    this.pendingMusic = null;
    if (this.music) {
      const m = this.music;
      const t = this.ctx.currentTime;
      m.gain.gain.cancelScheduledValues(t);
      m.gain.gain.setTargetAtTime(0, t, Math.max(0.05, fade / 3));
      try { m.src.stop(t + fade + 0.1); } catch (e) { /* ignore */ }
      this.music = null;
    }
    this.currentMusic = '';
  }

  setCrowd(e) { this.crowdEnergy = e; }

  preview(bus) {
    const samples = { master: 'S_UI_Select', music: 'M_Title', announcer: 'VO_TipOff', crowd: 'S_CrowdCheer_01', effects: 'S_Bounce_01', interface: 'S_UI_Move' };
    if (bus === 'music' && this.music) return;
    const p = this._src(samples[bus], bus === 'master' ? 'effects' : bus, 1, 1);
    if (p && bus === 'music') p.gain.gain.setTargetAtTime(0, this.ctx.currentTime + 1.5, 0.4);
    if (p && bus === 'music') p.src.stop(this.ctx.currentTime + 3);
  }

  tick(dt) {
    if (!this.running) return;
    if (!this.crowd) {
      this.crowd = this._src('S_CrowdLoop', 'crowd', 0.3, 1, true);
    }
    if (this.crowd) {
      const target = 0.28 + 0.55 * clamp(this.crowdEnergy, 0, 1);
      this.crowdVolume = finterp(this.crowdVolume, target, dt, 2);
      this.crowd.gain.gain.value = this.crowdVolume;
    }
  }
}
