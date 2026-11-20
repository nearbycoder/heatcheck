// HEAT CHECK web: boot, asset loading, settings and the main loop.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { HC, clamp, dist2D } from './consts.js';
import { Audio } from './audio.js';
import { Input } from './input.js';
import { ClipLibrary } from './anim.js';
import { Character } from './character.js';
import { Ball } from './ball.js';
import { Hoop } from './hoop.js';
import { Referee } from './referee.js';
import { Arena } from './arena.js';
import { SpriteFX } from './fx.js';
import { CameraDirector } from './camera.js';
import { Game, Mode } from './game.js';
import { HUD } from './hud.js';
import { makeInput } from './input.js';

const SOUNDS = [
  'M_Halftime', 'M_Title', 'S_Backboard', 'S_Block', 'S_Bounce_01', 'S_Bounce_02', 'S_Bounce_03', 'S_Buzzer', 'S_Countdown',
  'S_CrowdBigCheer', 'S_CrowdCheer_01', 'S_CrowdCheer_02', 'S_CrowdGroan', 'S_CrowdLoop', 'S_CrowdOoh', 'S_DunkSlam', 'S_Fall',
  'S_FireBasket', 'S_FireIgnite', 'S_Pass', 'S_RimHit_01', 'S_RimHit_02', 'S_RimHit_03', 'S_Score', 'S_ShotClock',
  'S_Shove', 'S_Squeak_01', 'S_Squeak_02', 'S_Squeak_03', 'S_Squeak_04', 'S_Steal', 'S_Swish_01', 'S_Swish_02', 'S_UI_Back',
  'S_UI_Move', 'S_UI_Select', 'S_UI_Start', 'S_Whistle', 'VO_AlleyOop', 'VO_Block_01', 'VO_Block_02', 'VO_Block_03', 'VO_Buzzer',
  'VO_Dunk_01', 'VO_Dunk_02', 'VO_Dunk_03', 'VO_Dunk_04', 'VO_Dunk_05', 'VO_EndQuarter', 'VO_FinalBuzzer', 'VO_FireOut',
  'VO_Fire_01', 'VO_Fire_02', 'VO_Fire_03', 'VO_Goaltending', 'VO_Halftime', 'VO_Miss_01', 'VO_Miss_02', 'VO_Overtime',
  'VO_Score_01', 'VO_Score_02', 'VO_Score_03', 'VO_ShotClock', 'VO_Shove_01', 'VO_Shove_02', 'VO_Steal_01', 'VO_Steal_02',
  'VO_Team_BAY', 'VO_Team_FRB', 'VO_Team_NEO', 'VO_Team_RRK', 'VO_Team_SSC', 'VO_Team_STV', 'VO_Three_01', 'VO_Three_02',
  'VO_Three_03', 'VO_TipOff', 'VO_TipOff_02', 'VO_Warm_01', 'VO_Warm_02', 'VO_Welcome',
];

const PRESETS = [
  { renderScale: 0.7, shadows: false, bloom: false, crowd: false, pixelCap: 1 },
  { renderScale: 0.85, shadows: true, bloom: false, crowd: true, pixelCap: 1.25 },
  { renderScale: 1, shadows: true, bloom: true, crowd: true, pixelCap: 1.5 },
  { renderScale: 1, shadows: true, bloom: true, crowd: true, pixelCap: 2 },
];
const SETTINGS_KEY = 'heatcheck.settings.v1';

const params = new URLSearchParams(location.search);
const SPEED = Math.max(1, Math.min(32, Number(params.get('speed')) || 1));
const isTouch = matchMedia('(pointer: coarse)').matches || params.has('touch');

function defaultSettings() {
  const mobile = isTouch || /Android|iPhone|iPad/i.test(navigator.userAgent);
  const q = mobile ? 0 : 2;
  return { quality: q, ...PRESETS[q], antialias: !mobile, showFps: params.has('fps') };
}

function loadSettings() {
  const s = defaultSettings();
  let levels = null;
  try {
    const raw = JSON.parse(localStorage.getItem(SETTINGS_KEY) || 'null');
    if (raw && raw.settings) Object.assign(s, raw.settings);
    if (raw && raw.levels) levels = raw.levels;
  } catch (e) { /* private mode */ }
  delete s.pixelCap;
  return { settings: s, levels };
}

class App {
  constructor() {
    const { settings, levels } = loadSettings();
    this.settings = settings;
    this.savedLevels = levels;
    this.canvas = document.getElementById('view');
    this.width = innerWidth;
    this.height = innerHeight;
    this.loadingEl = document.getElementById('loading');
    this.fill = this.loadingEl.querySelector('.load-fill');
    this.loadText = this.loadingEl.querySelector('.load-text');
    this.progress = { gltf: 0, audio: 0 };
  }

  setProgress(k, v) {
    this.progress[k] = v;
    const p = this.progress.gltf * 0.75 + this.progress.audio * 0.25;
    this.fill.style.width = `${Math.round(p * 100)}%`;
  }

  fail(msg) {
    this.loadText.innerHTML = `<p class="load-error">${msg}</p>`;
    this.loadText.classList.remove('load-text');
  }

  async boot() {
    if (isTouch) document.body.classList.add('touch');
    try {
      this.renderer = new THREE.WebGLRenderer({
        canvas: this.canvas, antialias: this.settings.antialias, powerPreference: 'high-performance', stencil: false,
      });
    } catch (e) {
      this.fail('Your browser could not start WebGL. Try a recent Chrome, Edge, Firefox or Safari with hardware acceleration enabled. <a href="../">Back to the HEAT CHECK site</a>');
      return;
    }
    const r = this.renderer;
    r.outputColorSpace = THREE.SRGBColorSpace;
    r.toneMapping = THREE.ACESFilmicToneMapping;
    r.toneMappingExposure = 0.95;
    r.shadowMap.enabled = true;
    r.shadowMap.type = THREE.PCFSoftShadowMap;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x050507);
    this.scene.fog = new THREE.Fog(0x050507, 60, 140);
    this.camera = new THREE.PerspectiveCamera(36, this.width / this.height, 0.5, 400);
    const pmrem = new THREE.PMREMGenerator(r);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environmentIntensity = 0.35;

    // ---- assets
    const manager = new THREE.LoadingManager();
    const loader = new GLTFLoader(manager);
    loader.setMeshoptDecoder(MeshoptDecoder);
    const files = {
      player: 'assets/characters/player.glb',
      referee: 'assets/characters/referee.glb',
      // the Performance preset (default on phones) loads the decimated bowl and crowd
      arena: this.settings.quality === 0 ? 'assets/arena/arena_lite.glb' : 'assets/arena/arena.glb',
      court: 'assets/arena/court.glb',
      hoop: 'assets/arena/hoop.glb',
      ball: 'assets/arena/ball.glb',
    };
    const sizes = {};
    const loaded = {};
    const update = () => {
      let a = 0, b = 0;
      for (const k of Object.keys(files)) {
        a += (sizes[k] && sizes[k].loaded) || 0;
        b += (sizes[k] && sizes[k].total) || 4e6;
      }
      this.setProgress('gltf', b ? a / b : 0);
    };
    this.audio = new Audio('assets/audio');
    if (this.savedLevels) Object.assign(this.audio.levels, this.savedLevels);
    const texLoader = new THREE.TextureLoader(manager);
    const flameP = texLoader.loadAsync('assets/textures/T_Flame.png');
    try {
      const gl = Object.entries(files).map(([k, url]) => loader.loadAsync(url, (e) => {
        sizes[k] = { loaded: e.loaded, total: e.total || 4e6 };
        update();
      }).then((g) => { loaded[k] = g; sizes[k] = { loaded: 1, total: 1 }; update(); }));
      const au = this.audio.init(SOUNDS, (p) => this.setProgress('audio', p));
      await Promise.all([...gl, au]);
    } catch (e) {
      console.error(e);
      this.fail('Something went wrong loading the game files. Check your connection and reload. <a href="../">Back to the HEAT CHECK site</a>');
      return;
    }
    const flame = await flameP;
    flame.colorSpace = THREE.SRGBColorSpace;
    this.loadText.textContent = 'TIPPING OFF…';
    await new Promise((res) => setTimeout(res, 30));
    this.build(loaded, flame);
    this.loadingEl.classList.add('done');
    setTimeout(() => this.loadingEl.remove(), 800);
  }

  build(L, flame) {
    const scene = this.scene;
    this.fx = new SpriteFX(scene, flame, 1800);
    this.arena = new Arena(scene, L.arena, L.court, this.settings);
    const clips = new ClipLibrary(L.player.animations);
    const refClips = new ClipLibrary([
      ...L.referee.animations,
      ...L.player.animations.filter((c) => c.name === 'Run'),
    ]);
    // ball
    const ballMesh = L.ball.scene;
    ballMesh.traverse((o) => { if (o.isMesh) { o.castShadow = true; } });
    scene.add(ballMesh);
    // hoops
    const hoops = [0, 1].map((i) => new Hoop(i, L.hoop.scene, scene, this.fx));
    // players: one template, four skeleton clones
    const template = L.player.scene;
    const players = [];
    this.camDirector = new CameraDirector(this.camera);
    const referee = new Referee(L.referee.scene, refClips, scene);
    const game = new Game({
      ball: null, players, hoops, referee, arena: this.arena, camera: this.camDirector, audio: this.audio, fx: this.fx, options: this.settings,
    });
    this.game = game;
    for (let i = 0; i < 4; i++) players.push(new Character(game, template, clips, scene));
    game.ball = new Ball(game, ballMesh, this.fx);
    game.humanInput = [makeInput(), makeInput()];
    this.hud = new HUD(this);
    this.input = new Input();
    if (isTouch) {
      const t = document.getElementById('touch');
      this.input.attachTouch(t);
    }
    this.composerSetup();
    this.resize();
    addEventListener('resize', () => this.resize());
    const unlock = () => this.audio.unlock();
    addEventListener('keydown', unlock);
    addEventListener('pointerdown', unlock);
    addEventListener('gamepadconnected', unlock);
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && game.screen === 'Game' && !game.paused && !game.attract) game.togglePause();
    });
    game.returnToTitle();
    // warm up shaders with everything visible
    this.renderer.compile(scene, this.camera);
    this.last = performance.now();
    this.renderer.setAnimationLoop((t) => this.frame(t));
    window.heatcheck = this; // handy for debugging from the console
    const q = Number(params.get('quarter'));
    if (q > 0) game.quarterMinutes = q;
    if (params.has('watch')) {
      game.mode = Mode.Watch;
      game.screen = 'Game';
      game.attract = false;
      game.setupTeams(false);
      game.startMatch();
    }
  }

  composerSetup() {
    const r = this.renderer;
    this.composer = new EffectComposer(r);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.45, 0.4, 2.2);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());
  }

  pixelRatio() {
    const cap = PRESETS[this.settings.quality].pixelCap;
    return Math.min(devicePixelRatio || 1, cap) * this.settings.renderScale;
  }

  resize() {
    this.width = innerWidth;
    this.height = innerHeight;
    const pr = this.pixelRatio();
    this.renderer.setPixelRatio(pr);
    this.renderer.setSize(this.width, this.height, false);
    this.composer.setPixelRatio(pr);
    this.composer.setSize(this.width, this.height);
    this.camera.aspect = this.width / this.height;
    this.camera.updateProjectionMatrix();
    this.fx.setViewport(this.height * pr, this.camera.fov);
    const rot = document.getElementById('rotate');
    rot.hidden = !(isTouch && this.height > this.width * 1.1);
    document.getElementById('touch').hidden = !isTouch;
  }

  applySettings(key) {
    const s = this.settings;
    if (key === 'quality') Object.assign(s, PRESETS[s.quality]);
    delete s.pixelCap;
    this.renderer.shadowMap.enabled = true;
    this.arena.applySettings(s);
    if (key === 'shadows' || key === 'quality') {
      this.scene.traverse((o) => { if (o.material) { for (const m of [].concat(o.material)) m.needsUpdate = true; } });
    }
    this.resize();
    this.saveSettings();
  }

  saveSettings() {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({ settings: this.settings, levels: this.audio.levels }));
    } catch (e) { /* ignore */ }
  }

  handleMenus(dt) {
    const g = this.game;
    const inp = this.input;
    const nav = inp.menu();
    if (g.optionsPage) {
      this.hud.optNav(nav);
      return;
    }
    if (g.paused) {
      if (nav.up) g.menuUp();
      if (nav.down) g.menuDown();
      if (nav.confirm) g.menuConfirm();
      else if (nav.back || inp.kp('KeyP')) g.togglePause();
      return;
    }
    if (g.screen !== 'Game') {
      if (g.screen === 'Title') {
        if (nav.confirm || inp.anyPressed && !nav.back) g.menuConfirm();
        else if (nav.back) location.href = '../';
        return;
      }
      if (nav.up) g.menuUp();
      if (nav.down) g.menuDown();
      if (nav.left1) g.menuSide(-1, 0);
      if (nav.right1) g.menuSide(1, 0);
      if (nav.left2) g.menuSide(-1, 1);
      if (nav.right2) g.menuSide(1, 1);
      if (nav.confirm) g.menuConfirm();
      else if (nav.back) g.menuBack();
      return;
    }
    if (nav.pause && !g.attract) {
      g.togglePause();
      return;
    }
    if ((g.phase === 'Break' || g.phase === 'GameOver') && nav.confirm) g.menuConfirm();
    void dt;
  }

  /** Capsule blocking between players (the original relies on Unreal's capsule collision). */
  separate() {
    const ps = this.game.players;
    const R2 = HC.PlayerRadius * 2;
    for (let i = 0; i < ps.length; i++) {
      for (let j = i + 1; j < ps.length; j++) {
        const a = ps[i], b = ps[j];
        if (a.mode === 'fly' || b.mode === 'fly' || a.state === 'Inbound' || b.state === 'Inbound') continue;
        if (Math.abs(a.pos.z - b.pos.z) > 190) continue;
        const dx = b.pos.x - a.pos.x, dy = b.pos.y - a.pos.y;
        const d = Math.hypot(dx, dy);
        if (d >= R2 || d < 1e-3) continue;
        const push = (R2 - d) * 0.5;
        const nx = dx / d, ny = dy / d;
        a.pos.x -= nx * push; a.pos.y -= ny * push;
        b.pos.x += nx * push; b.pos.y += ny * push;
        const va = a.vel.x * nx + a.vel.y * ny, vb = b.vel.x * nx + b.vel.y * ny;
        if (va > 0) { a.vel.x -= nx * va; a.vel.y -= ny * va; }
        if (vb < 0) { b.vel.x -= nx * vb; b.vel.y -= ny * vb; }
      }
    }
  }

  frame(now) {
    const raw = (now - this.last) / 1000;
    this.last = now;
    const dt = Math.min(raw, 0.05);
    const g = this.game;
    const inp = this.input;
    inp.poll(dt);
    this.handleMenus(dt);
    if (g.screen === 'Game' && !g.paused) {
      inp.readPlayer(0, g.humanInput[0]);
      inp.readPlayer(1, g.humanInput[1]);
    }
    const steps = g.paused ? 0 : SPEED;
    for (let k = 0; k < steps; k++) {
      if (k > 0) inp.endFrame();
      g.tick(dt);
      for (const c of g.players) c.tick(dt);
      this.separate();
      g.postTick(dt);
      for (const c of g.players) c.updateVisual(dt);
      g.referee.updateVisual(dt);
      g.ball.tick(dt);
      g.ball.syncVisual();
      for (const h of g.hoops) h.tick(dt);
      this.fx.tick(dt);
      this.arena.tick(dt);
      this.camDirector.tick(dt, g);
    }
    this.audio.tick(dt);
    this.hud.update(raw);
    inp.endFrame();
    if (this.settings.bloom) this.composer.render(dt);
    else this.renderer.render(this.scene, this.camera);
  }
}

const app = new App();
app.boot();
export { clamp, dist2D };
