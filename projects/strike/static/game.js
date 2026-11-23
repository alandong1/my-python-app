"use strict";
// 突击行动的浏览器端：Three.js 画面、键鼠 / 触屏输入、移动预测、武器与商店、HUD。
// 判定都在服务器（projects/strike/game.py）；这里的 move() 必须和服务器的 move() 保持一致，用于预测。
import * as THREE from "three";
import { EXRLoader } from "three/addons/loaders/EXRLoader.js";

const tr = (...args) => i18n.t(...args);
const $ = (id) => document.getElementById(id);
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const SEND_MS = 33;            // 约每秒 30 次发送移动输入
const MOUSE_SENS = 0.0022;     // 鼠标灵敏度（弧度 / 像素），开镜时会按视野缩小
const TOUCH_SENS = 0.006;      // 手机滑动转向的灵敏度
const JOY_RADIUS = 70;         // 摇杆最大拖动距离（像素）
const BASE_FOV = 75;           // 正常视野（度）
const DOUBLE_TAP_MS = 320;     // 两次点击在这个时间内算双击（用来开关狙击镜）
const COLORS = [0xe4572e, 0x29a19c, 0xf3a712, 0x7b5ea7, 0x3e92cc, 0xc2185b,
                0x8bc34a, 0xff7043, 0x26c6da, 0xab47bc, 0xffca28, 0x66bb6a];
const SHOP_ORDER = ["deagle", "smg", "rifle", "sniper"];   // 商店里的武器顺序
const RECOIL = { pistol: 1.0, deagle: 1.4, smg: 0.6, rifle: 0.8, sniper: 1.8 };   // 后坐力大小
const DEFAULT_WEAPON = "pistol";

// ---------------------------------------------------------------- 状态

let sim = null;                // 服务器发来的移动参数（欢迎消息）
let map = null;                // 地图：边界、障碍物、出生点
let weapons = {};              // 武器表（欢迎消息里来自服务器）
let myId = null;
let ws = null;
let lastError = "";
let playing = false;           // 已经进入房间
let arenaBuilt = false;
let wasAlive = false;          // 上一次收到的状态里，自己是否活着（用来判断刚出生或刚复活）
let shopOpen = false;          // 商店是否打开（打开时不能移动和开火）
let teamKills = [0, 0];        // 红队、蓝队的击杀数（服务器发来）
let lobby = { me: {}, rooms: [] };   // 大厅：我是谁、有哪些房间（服务器发来）
let inRoom = false;            // 是否已经在房间里
let roomInfo = null;           // 当前房间的信息（房主是谁、电脑多少、我是不是房主）
let myTeam = 0;                // 我在哪一队：0 红队，1 蓝队
const TEAM_COLORS = [0xe4572e, 0x3e92cc];   // 红队、蓝队的颜色
const TEAM_CSS = ["#ff7a5c", "#6fb8ff"];    // 同样的颜色，用在文字上
let scopeWanted = false;       // 玩家想不想开狙击镜
let curFov = BASE_FOV;         // 当前视野（开镜时会慢慢拉近）

const me = {
  x: 0, z: 0, yaw: 0, pitch: 0, hp: 100, alive: true, respawnIn: 0, kills: 0, deaths: 0,
  money: 0, slots: { primary: null, secondary: DEFAULT_WEAPON }, active: "secondary", scoped: false,
};
const names = new Map();       // 玩家 id → 名字
let players = [];              // 最近一次收到的全员状态
const remotes = new Map();     // 玩家 id → 画面里的人物模型
const tracers = [];            // 正在显示的子弹轨迹
let pending = [];              // 已经发送、还没被服务器确认的移动输入（用于预测对齐）
let seq = 0;
let lastSend = 0;
let lastFire = 0;
let hitFlashUntil = 0;
let lastRightTap = 0;         // 手机上右半边最近一次点击的时间（双击开关狙击镜）

const kb = { fwd: 0, side: 0 };   // 键盘输入
const joy = { fwd: 0, side: 0 };  // 摇杆输入（手机）
const input = { fwd: 0, side: 0, firing: false };
const keys = new Set();
let scoreHeld = false;         // 按住 Tab
let scoreToggled = false;      // 手机上点「记分」切换
const touchDevice = matchMedia("(pointer: coarse)").matches;

const activeWeapon = () => me.slots[me.active] || DEFAULT_WEAPON;

// ---------------------------------------------------------------- 画面

const canvas = $("view");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, touchDevice ? 1.5 : 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.setSize(window.innerWidth, window.innerHeight, false);

const scene = new THREE.Scene();
scene.background = gradientTexture();
scene.fog = new THREE.Fog(0xc9dcea, 60, 150);
const camera = new THREE.PerspectiveCamera(BASE_FOV, window.innerWidth / window.innerHeight, 0.05, 300);
camera.rotation.order = "YXZ";   // 先转左右（yaw），再抬头低头（pitch）
scene.add(camera);               // 手持武器挂在相机下面，所以相机也要在场景里

// 光照：天光 + 一盏带阴影的太阳光（手机用较小的阴影图，省性能）
scene.add(new THREE.HemisphereLight(0xdfeeff, 0x4a5a33, 0.8));
const sun = new THREE.DirectionalLight(0xfff0d2, 2.4);
sun.position.set(24, 46, 16);
sun.castShadow = true;
const shadowSize = touchDevice ? 1024 : 2048;
sun.shadow.mapSize.set(shadowSize, shadowSize);
Object.assign(sun.shadow.camera, { left: -34, right: 34, top: 34, bottom: -34, near: 1, far: 140 });
sun.shadow.camera.updateProjectionMatrix();
sun.shadow.bias = -0.0006;
sun.shadow.normalBias = 0.03;
scene.add(sun);

// 真实的环境光：加载真实拍摄的城市 HDRI（CC0），用它照亮场景、反射到金属和玻璃上，并作为天空背景。
// 加载在 loadAssets() 里完成；没加载成功时保留上面的渐变天空，游戏照常可以玩。
let envTexture = null;

// 加载真实拍摄的城市 HDRI（CC0）：照亮场景、反射到表面，并作为天空背景。没加载成功时保留渐变天空，游戏照常可以玩。
async function loadAssets() {
  try {
    const exr = await new EXRLoader().loadAsync("static/assets/city.exr");
    exr.mapping = THREE.EquirectangularReflectionMapping;
    const pmrem = new THREE.PMREMGenerator(renderer);
    envTexture = pmrem.fromEquirectangular(exr).texture;
    pmrem.dispose();
    scene.environment = envTexture;
    scene.background = envTexture;
  } catch (e) {
    // 没加载到环境光：保留渐变天空
  }
}

function gradientTexture() {
  // 天空：上面是蓝天，靠近地平线逐渐变成雾的颜色
  const c = canvasOf(4, 256);
  const g = c.getContext("2d");
  const grd = g.createLinearGradient(0, 0, 0, 256);
  grd.addColorStop(0, "#3a68a8");
  grd.addColorStop(0.55, "#9cc3e0");
  grd.addColorStop(0.72, "#c9dcea");
  grd.addColorStop(1, "#c9dcea");
  g.fillStyle = grd;
  g.fillRect(0, 0, 4, 256);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// ---------------------------------------------------------------- 程序生成的表面纹理（不需要下载图片）

function canvasOf(w, h = w) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return c;
}

function finishTexture(c, tileM, srgb = true) {
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  t.userData.tileM = tileM;     // 这张贴图大约覆盖多少米，贴到不同大小的墙上时据此决定重复次数
  return t;
}

// 颜色贴图：颜色 + 噪点 + 色斑；可选地砖接缝、木板纹
function makeColorTexture(rgb, spread, tileM, opts = {}) {
  const S = 256;
  const c = canvasOf(S);
  const g = c.getContext("2d");
  const img = g.createImageData(S, S);
  const d = img.data;
  for (let y = 0; y < S; y++) {
    for (let x = 0; x < S; x++) {
      const i = (y * S + x) * 4;
      const n = (Math.random() - 0.5) * spread + (Math.sin(x * 0.09) + Math.cos(y * 0.11)) * spread * 0.2;
      d[i] = clamp(rgb[0] + n, 0, 255);
      d[i + 1] = clamp(rgb[1] + n, 0, 255);
      d[i + 2] = clamp(rgb[2] + n, 0, 255);
      d[i + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  if (opts.planks) {
    g.fillStyle = "rgba(40,25,10,0.55)";
    for (const y of [0, 64, 128, 192]) g.fillRect(0, y, S, 3);
  }
  if (opts.seams) {
    g.fillStyle = "rgba(0,0,0,0.35)";
    g.fillRect(0, 0, S, 3);
    g.fillRect(0, 0, 3, S);
  }
  return finishTexture(c, tileM, true);
}

// 凹凸贴图：灰度噪点，让地面和墙面有细微的凹凸感，光线打上去会有明暗变化
function makeBumpTexture(spread, tileM) {
  const S = 256;
  const c = canvasOf(S);
  const g = c.getContext("2d");
  const img = g.createImageData(S, S);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const v = 128 + (Math.random() - 0.5) * spread;
    d[i] = d[i + 1] = d[i + 2] = v;
    d[i + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  return finishTexture(c, tileM, false);
}

// 楼房外墙：灰色墙面 + 一排排带反光的窗户
function makeFacadeTexture() {
  const S = 256;
  const c = canvasOf(S);
  const g = c.getContext("2d");
  g.fillStyle = "#b9b4aa";
  g.fillRect(0, 0, S, S);
  for (let r = 0; r < 4; r++) {
    for (let k = 0; k < 4; k++) {
      const x = 14 + k * 60, y = 16 + r * 60;
      const grd = g.createLinearGradient(x, y, x, y + 44);
      grd.addColorStop(0, "#5d7a95");
      grd.addColorStop(1, "#243446");
      g.fillStyle = grd;
      g.fillRect(x, y, 40, 44);
      g.fillStyle = "rgba(255,255,255,0.25)";
      g.fillRect(x, y + 16, 40, 2);       // 窗户的反光
      g.fillStyle = "#8f8a80";
      g.fillRect(x - 3, y + 44, 46, 3);   // 窗台
    }
  }
  return finishTexture(c, 4, true);
}

const TEX = {
  plaza: makeColorTexture([122, 120, 113], 20, 3, { seams: true }),
  plazaBump: makeBumpTexture(40, 3),
  concrete: makeColorTexture([150, 149, 144], 24, 3),
  wood: makeColorTexture([158, 112, 64], 30, 1.2, { planks: true }),
  metal: makeColorTexture([88, 96, 108], 16, 3),
  facade: makeFacadeTexture(),
  bump: makeBumpTexture(50, 3),
};

// 按墙的大小复制一份贴图，让纹理在墙上重复排列，而不是被拉长
function tiled(tex, w, h) {
  const t = tex.clone();
  const m = tex.userData.tileM;
  t.repeat.set(Math.max(w, 0.01) / m, Math.max(h, 0.01) / m);
  return t;
}

// 共用的材质和模型零件
const skinMat = new THREE.MeshStandardMaterial({ color: 0xd9a57c, roughness: 0.65 });
const gearMat = new THREE.MeshStandardMaterial({ color: 0x2b2f36, roughness: 0.55, metalness: 0.2 });
const steelMat = new THREE.MeshStandardMaterial({ color: 0x2a2d33, roughness: 0.35, metalness: 0.7 });
const gunWoodMat = new THREE.MeshStandardMaterial({ color: 0x6b4a2b, roughness: 0.8 });
function part(geo, mat, x, y, z) {
  const m = new THREE.Mesh(geo, mat);
  m.position.set(x, y, z);
  m.castShadow = true;
  return m;
}

const tracerMat = new THREE.LineBasicMaterial({ color: 0xfff1b0, transparent: true, opacity: 0.85 });

// 枪口火光贴图
const flareTex = (() => {
  const c = canvasOf(64);
  const g = c.getContext("2d");
  const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, "rgba(255,245,200,1)");
  grd.addColorStop(0.3, "rgba(255,170,60,0.8)");
  grd.addColorStop(1, "rgba(255,120,20,0)");
  g.fillStyle = grd;
  g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
})();

// ---------------------------------------------------------------- 第一人称的枪（每种武器一把）

const viewmodel = new THREE.Group();   // 所有枪都挂在这里：跟着视线走，有摆动和后坐
viewmodel.position.set(0.24, -0.22, -0.5);
camera.add(viewmodel);
const gunModels = {};
let recoil = 0, bobT = 0, movingAmt = 0, muzzleUntil = 0;

function buildGuns() {
  const defs = {
    // [宽, 高, 长, 材质, x, y, z]；tip 是枪口的位置（z）
    pistol: { tip: -0.3, parts: [
      [0.05, 0.07, 0.2, steelMat, 0, 0, -0.1],
      [0.045, 0.12, 0.06, gearMat, 0, -0.11, -0.02],
    ] },
    deagle: { tip: -0.33, parts: [
      [0.06, 0.09, 0.25, steelMat, 0, 0, -0.12],
      [0.05, 0.13, 0.07, gunWoodMat, 0, -0.12, -0.02],
    ] },
    smg: { tip: -0.5, parts: [
      [0.07, 0.1, 0.3, steelMat, 0, 0, -0.1],
      [0.05, 0.2, 0.07, steelMat, 0, -0.15, -0.06],
      [0.03, 0.03, 0.2, gearMat, 0, 0, -0.4],
      [0.055, 0.09, 0.2, gunWoodMat, 0, -0.02, 0.2],
    ] },
    rifle: { tip: -0.7, parts: [
      [0.07, 0.1, 0.4, steelMat, 0, 0, -0.12],
      [0.035, 0.035, 0.3, steelMat, 0, 0.02, -0.5],
      [0.05, 0.16, 0.07, steelMat, 0, -0.13, -0.05],
      [0.06, 0.11, 0.26, gunWoodMat, 0, -0.02, 0.22],
    ] },
    sniper: { tip: -0.8, scope: true, parts: [
      [0.08, 0.11, 0.5, steelMat, 0, 0, -0.1],
      [0.035, 0.035, 0.4, steelMat, 0, 0.02, -0.55],
      [0.06, 0.13, 0.3, gunWoodMat, 0, -0.02, 0.3],
      [0.04, 0.04, 0.2, steelMat, 0, -0.1, -0.1],
    ] },
  };
  for (const [id, def] of Object.entries(defs)) {
    const g = new THREE.Group();
    for (const [w, h, d, mat, x, y, z] of def.parts) {
      g.add(part(new THREE.BoxGeometry(w, h, d), mat, x, y, z));
    }
    if (def.scope) {   // 狙击镜：一截圆筒（平时看得到，开镜时整把枪都会隐藏）
      const scope = part(new THREE.CylinderGeometry(0.03, 0.03, 0.24, 14), gearMat, 0, 0.1, -0.12);
      scope.rotation.x = Math.PI / 2;
      g.add(scope);
    }
    const muzzle = new THREE.Sprite(new THREE.SpriteMaterial({
      map: flareTex, transparent: true, depthTest: false, opacity: 0, blending: THREE.AdditiveBlending,
    }));
    muzzle.scale.set(0.3, 0.3, 1);
    muzzle.position.set(0, 0.02, def.tip);
    g.add(muzzle);
    g.traverse((o) => { if (o.isMesh) o.castShadow = false; });   // 手持的枪不往地上投影
    g.visible = false;
    viewmodel.add(g);
    gunModels[id] = { group: g, muzzle };
  }
}
buildGuns();

function kick(now, amount) {
  recoil = Math.max(recoil, amount);
  muzzleUntil = now + 60;
}

function updateViewmodel(dt, now, moving, gunId) {
  recoil *= Math.exp(-dt * 14);
  movingAmt += ((moving ? 1 : 0) - movingAmt) * Math.min(1, dt * 8);
  bobT += dt * (moving ? 9 : 2);
  viewmodel.position.set(
    0.24 + Math.cos(bobT * 0.5) * 0.012 * movingAmt,
    -0.22 + Math.abs(Math.sin(bobT)) * 0.012 * movingAmt,
    -0.5 + recoil * 0.05,
  );
  viewmodel.rotation.x = recoil * 0.12;
  for (const [id, m] of Object.entries(gunModels)) {
    const current = id === gunId;
    m.group.visible = current;
    m.muzzle.material.opacity = current && now < muzzleUntil ? 1 : 0;
  }
}

// 命中火花：一个粒子池，所有粒子共用一个 Points 对象，省性能
const PART_MAX = 240;
const partPos = new Float32Array(PART_MAX * 3);
const partVel = new Float32Array(PART_MAX * 3);
const partLife = new Float32Array(PART_MAX);
let partNext = 0;
const partGeo = new THREE.BufferGeometry();
partGeo.setAttribute("position", new THREE.BufferAttribute(partPos, 3));
const partMat = new THREE.PointsMaterial({
  color: 0xffd98a, size: 0.09, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
});
const particles = new THREE.Points(partGeo, partMat);
particles.frustumCulled = false;
scene.add(particles);
for (let i = 0; i < PART_MAX; i++) partPos[i * 3 + 1] = -1000;   // 没在用的粒子藏到地下

function spawnSparks(p, count = 8) {
  for (let n = 0; n < count; n++) {
    const i = partNext;
    partNext = (partNext + 1) % PART_MAX;
    partPos[i * 3] = p[0];
    partPos[i * 3 + 1] = p[1];
    partPos[i * 3 + 2] = p[2];
    partVel[i * 3] = (Math.random() - 0.5) * 4;
    partVel[i * 3 + 1] = Math.random() * 3 + 0.5;
    partVel[i * 3 + 2] = (Math.random() - 0.5) * 4;
    partLife[i] = 0.25 + Math.random() * 0.25;
  }
}

function updateParticles(dt) {
  let dirty = false;
  for (let i = 0; i < PART_MAX; i++) {
    if (partLife[i] <= 0) continue;
    dirty = true;
    partLife[i] -= dt;
    partVel[i * 3 + 1] -= 12 * dt;                  // 重力
    for (let k = 0; k < 3; k++) partPos[i * 3 + k] += partVel[i * 3 + k] * dt;
    if (partLife[i] <= 0) partPos[i * 3 + 1] = -1000;
  }
  if (dirty) partGeo.attributes.position.needsUpdate = true;
}

function fitToWindow() {
  // 用可见区域的真实尺寸（手机地址栏收起或展开时会变），而不是 CSS 的 100vh
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", fitToWindow);
window.addEventListener("orientationchange", () => setTimeout(fitToWindow, 300));
fitToWindow();

// ---------------------------------------------------------------- 全屏与防误缩放

const fsEl = document.documentElement;
const fullscreenSupported = !!(fsEl.requestFullscreen || fsEl.webkitRequestFullscreen);
const isFullscreen = () => !!(document.fullscreenElement || document.webkitFullscreenElement);

async function enterFullscreen() {
  if (!fullscreenSupported || isFullscreen()) return;
  try {
    const req = fsEl.requestFullscreen ? fsEl.requestFullscreen() : fsEl.webkitRequestFullscreen();
    await req;
    // Android Chrome 允许在全屏时锁定横屏（可选，不强制）；iPhone 的 Safari 不支持，失败就忽略
    if (screen.orientation && screen.orientation.lock) await screen.orientation.lock("landscape").catch(() => {});
  } catch (e) {
    // 浏览器拒绝全屏（例如 iPhone 的 Safari）：页面照常运行，只是没有全屏
  }
}

function exitFullscreen() {
  if (!isFullscreen()) return;
  (document.exitFullscreen || document.webkitExitFullscreen).call(document);
}

function updateFullscreenButton() {
  const btn = $("fullBtn");
  if (!fullscreenSupported) { btn.classList.add("hidden"); return; }
  btn.classList.remove("hidden");
  btn.textContent = isFullscreen() ? tr("退出全屏") : tr("全屏");
}
$("fullBtn").addEventListener("click", () => (isFullscreen() ? exitFullscreen() : enterFullscreen()));
document.addEventListener("fullscreenchange", () => { updateFullscreenButton(); setTimeout(fitToWindow, 100); });
document.addEventListener("webkitfullscreenchange", () => { updateFullscreenButton(); setTimeout(fitToWindow, 100); });
i18n.onChange(updateFullscreenButton);
updateFullscreenButton();

// 手机上双击、双指捏合会把页面放大，影响操作：全部拦住
document.addEventListener("gesturestart", (e) => e.preventDefault());
document.addEventListener("dblclick", (e) => e.preventDefault());
document.addEventListener("contextmenu", (e) => e.preventDefault());   // 右键用来开镜，不弹菜单
let lastTouchEnd = 0;
document.addEventListener("touchend", (e) => {
  const now = Date.now();
  if (now - lastTouchEnd < 350) e.preventDefault();   // 快速连点第二下不当作双击缩放
  lastTouchEnd = now;
}, { passive: false });
document.addEventListener("touchmove", (e) => { if (e.touches.length > 1) e.preventDefault(); }, { passive: false });

// ---------------------------------------------------------------- 场地和背景

function buildArena() {
  const h = map.half;
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(2 * h, 2 * h),
    new THREE.MeshStandardMaterial({
      map: tiled(TEX.plaza, 2 * h, 2 * h),
      bumpMap: tiled(TEX.plazaBump, 2 * h, 2 * h), bumpScale: 0.5,
      roughness: 0.9,
    }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);

  for (const [x0, y0, z0, x1, y1, z1] of map.walls) {
    const w = x1 - x0, d = z1 - z0, hgt = y1 - y0;
    const tex = y1 < 2 ? TEX.wood : TEX.facade;      // 矮箱子是木箱，高墙是有窗户的楼房外墙
    addBox((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2, w, hgt, d, tiled(tex, Math.max(w, d), hgt));
  }
  // 四周的边界墙：厚 1 米，内侧正好在 ±half
  addBox(0, 1.5, -h - 0.5, 2 * h + 2, 3, 1, tiled(TEX.metal, 2 * h + 2, 3));
  addBox(0, 1.5, h + 0.5, 2 * h + 2, 3, 1, tiled(TEX.metal, 2 * h + 2, 3));
  addBox(-h - 0.5, 1.5, 0, 1, 3, 2 * h, tiled(TEX.metal, 1, 3));
  addBox(h + 0.5, 1.5, 0, 1, 3, 2 * h, tiled(TEX.metal, 1, 3));
  buildSkyline();
  arenaBuilt = true;
}

// 竞技场外面的城市天际线：只用来做背景，玩家碰不到
function buildSkyline() {
  const rnd = (a, b) => a + Math.random() * (b - a);
  for (let i = 0; i < 60; i++) {
    const w = rnd(8, 18), d = rnd(8, 16), hgt = rnd(12, 55);
    const along = rnd(-90, 90), out = rnd(42, 80);
    let x, z;
    if (i % 4 === 0) { x = along; z = -out; }
    else if (i % 4 === 1) { x = along; z = out; }
    else if (i % 4 === 2) { x = -out; z = along; }
    else { x = out; z = along; }
    addBox(x, hgt / 2, z, w, hgt, d, tiled(TEX.facade, Math.max(w, d), hgt));
  }
}

function addBox(x, y, z, w, hgt, d, map_) {
  const mat = new THREE.MeshStandardMaterial({ map: map_, roughness: 0.85, metalness: 0.05 });
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, hgt, d), mat);
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  scene.add(mesh);
}

// ---------------------------------------------------------------- 其他玩家的人物模型

function nameSprite(text) {
  const c = canvasOf(256, 64);
  const g = c.getContext("2d");
  g.fillStyle = "rgba(0,0,0,0.5)";
  g.fillRect(0, 0, 256, 64);
  g.fillStyle = "#fff";
  g.font = "bold 34px sans-serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(text, 128, 34);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(c), depthTest: false, transparent: true,
  }));
  sprite.scale.set(1.6, 0.4, 1);
  sprite.position.y = 2.1;
  return sprite;
}

function makeRemote(p) {
  const group = new THREE.Group();
  const suit = new THREE.MeshStandardMaterial({ color: TEAM_COLORS[p.team] ?? 0xffffff, roughness: 0.7 });
  const pants = new THREE.MeshStandardMaterial({ color: 0x3a3f2e, roughness: 0.9 });
  const boots = new THREE.MeshStandardMaterial({ color: 0x1a1a1a, roughness: 0.9 });
  group.add(
    part(new THREE.CapsuleGeometry(0.1, 0.5, 6, 12), pants, -0.12, 0.5, 0),
    part(new THREE.CapsuleGeometry(0.1, 0.5, 6, 12), pants, 0.12, 0.5, 0),
    part(new THREE.BoxGeometry(0.16, 0.1, 0.26), boots, -0.12, 0.05, -0.04),
    part(new THREE.BoxGeometry(0.16, 0.1, 0.26), boots, 0.12, 0.05, -0.04),
    part(new THREE.CapsuleGeometry(0.2, 0.42, 6, 14), suit, 0, 1.2, 0),
    part(new THREE.BoxGeometry(0.42, 0.4, 0.22), gearMat, 0, 1.2, -0.06),
    part(new THREE.CapsuleGeometry(0.075, 0.4, 4, 10), suit, -0.29, 1.18, -0.02),
    part(new THREE.CapsuleGeometry(0.075, 0.4, 4, 10), suit, 0.29, 1.18, -0.02),
    part(new THREE.SphereGeometry(0.075, 10, 8), skinMat, -0.25, 0.95, -0.12),
    part(new THREE.SphereGeometry(0.075, 10, 8), skinMat, 0.25, 0.95, -0.12),
    part(new THREE.CylinderGeometry(0.06, 0.06, 0.1, 10), skinMat, 0, 1.46, 0),
    part(new THREE.SphereGeometry(0.13, 16, 12), skinMat, 0, 1.6, 0),
    part(new THREE.SphereGeometry(0.155, 16, 10, 0, Math.PI * 2, 0, Math.PI * 0.55), gearMat, 0, 1.64, 0),
  );
  const gunPivot = new THREE.Group();     // 枪挂在胸前，随视线上下转动
  gunPivot.position.set(0, 1.25, -0.05);
  gunPivot.add(part(new THREE.BoxGeometry(0.1, 0.12, 0.62), gearMat, 0.05, 0, -0.35));
  group.add(gunPivot, nameSprite(p.name));
  group.position.set(p.x, 0, p.z);
  scene.add(group);
  const r = { group, gunPivot, snaps: [] };
  remotes.set(p.id, r);
  return r;
}

function updateRemotes(now) {
  // 远端玩家按「过去 interp 毫秒」的画面显示。服务器判定打中时也是按这个时间回推，两边对齐。
  const renderT = now - (sim ? sim.interp : 100);
  for (const r of remotes.values()) {
    const s = r.snaps;
    if (!s.length) continue;
    let a = s[0], b = s[s.length - 1];
    if (renderT <= s[0].t) { a = b = s[0]; }
    else if (renderT >= s[s.length - 1].t) { a = b = s[s.length - 1]; }
    else {
      for (let i = 0; i + 1 < s.length; i++) {
        if (s[i].t <= renderT && renderT <= s[i + 1].t) { a = s[i]; b = s[i + 1]; break; }
      }
    }
    const k = b.t === a.t ? 0 : (renderT - a.t) / (b.t - a.t);
    const lerp = (u, v) => u + (v - u) * k;
    r.group.position.set(lerp(a.x, b.x), 0, lerp(a.z, b.z));
    r.group.rotation.y = lerp(a.yaw, b.yaw);
    r.gunPivot.rotation.x = lerp(a.pitch, b.pitch);
    r.group.visible = b.alive;
  }
}

function tracer(from, to, spark = true) {
  const geo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(...from), new THREE.Vector3(...to),
  ]);
  const line = new THREE.Line(geo, tracerMat);
  scene.add(line);
  tracers.push({ line, until: performance.now() + 90 });
  if (spark) spawnSparks(to);
}

function updateTracers(now) {
  while (tracers.length && tracers[0].until <= now) {
    const t = tracers.shift();
    scene.remove(t.line);
    t.line.geometry.dispose();
  }
}

// ---------------------------------------------------------------- 移动（与服务器 game.py 的 move() 一致）

function blocked(x, z) {
  const r = sim.radius;
  for (const [x0, , z0, x1, , z1] of map.walls) {
    if (x + r > x0 && x - r < x1 && z + r > z0 && z - r < z1) return true;
  }
  return false;
}

function move(x, z, fwd, side, yaw, dt) {
  dt = clamp(dt, 0, sim.maxDt);
  fwd = clamp(fwd, -1, 1);
  side = clamp(side, -1, 1);
  const m = Math.hypot(fwd, side);
  if (m > 1) { fwd /= m; side /= m; }
  const s = Math.sin(yaw), c = Math.cos(yaw);
  const fx = -s, fz = -c, rx = c, rz = -s;
  const step = sim.speed * dt;
  const dx = (fx * fwd + rx * side) * step;
  const dz = (fz * fwd + rz * side) * step;
  const bound = map.half - sim.radius;
  const nx = clamp(x + dx, -bound, bound);
  if (!blocked(nx, z)) x = nx;
  const nz = clamp(z + dz, -bound, bound);
  if (!blocked(x, nz)) z = nz;
  return [x, z];
}

function aimDir(yaw, pitch) {
  const cp = Math.cos(pitch);
  return [-Math.sin(yaw) * cp, Math.sin(pitch), -Math.cos(yaw) * cp];
}

// ---------------------------------------------------------------- 输入

function syncInput() {
  if (shopOpen) {               // 逛商店时不能移动
    input.fwd = 0;
    input.side = 0;
    return;
  }
  input.fwd = clamp(kb.fwd + joy.fwd, -1, 1);
  input.side = clamp(kb.side + joy.side, -1, 1);
}

function syncKeys() {
  const has = (...codes) => codes.some((c) => keys.has(c));
  kb.fwd = (has("KeyW", "ArrowUp") ? 1 : 0) - (has("KeyS", "ArrowDown") ? 1 : 0);
  kb.side = (has("KeyD", "ArrowRight") ? 1 : 0) - (has("KeyA", "ArrowLeft") ? 1 : 0);
  syncInput();
}

window.addEventListener("keydown", (e) => {
  if (!playing) return;
  if (e.code === "Tab") { e.preventDefault(); scoreHeld = true; return; }
  if (e.code === "KeyB") { toggleShop(); return; }
  if (e.code === "Digit1") { equipSlot("primary"); return; }
  if (e.code === "Digit2") { equipSlot("secondary"); return; }
  keys.add(e.code);
  syncKeys();
});
window.addEventListener("keyup", (e) => {
  if (e.code === "Tab") scoreHeld = false;
  keys.delete(e.code);
  syncKeys();
});
window.addEventListener("blur", () => {
  keys.clear(); scoreHeld = false; input.firing = false; syncKeys();
});

// 鼠标（电脑）：点击画面进入 Pointer Lock；左键开火，右键开关狙击镜
const isLocked = () => document.pointerLockElement === canvas;
canvas.addEventListener("mousedown", (e) => {
  if (!playing || touchDevice || shopOpen) return;
  if (e.button === 0) {
    if (!isLocked()) canvas.requestPointerLock();
    else input.firing = true;
  } else if (e.button === 2 && isLocked()) {
    toggleScope();
  }
});
window.addEventListener("mouseup", (e) => { if (e.button === 0) input.firing = false; });
document.addEventListener("mousemove", (e) => {
  if (!playing || !isLocked() || shopOpen) return;
  const k = MOUSE_SENS * (curFov / BASE_FOV);   // 开镜时转动慢一点，瞄得准
  me.yaw -= e.movementX * k;
  me.pitch = clamp(me.pitch - e.movementY * k, -sim.maxPitch, sim.maxPitch);
});
document.addEventListener("pointerlockchange", () => {
  if (!isLocked()) input.firing = false;
  updateHint();
});

// 触屏（手机）：左半边拖动摇杆移动，右半边滑动转向（双击开关狙击镜）；右下角按钮开火
const joyBase = $("joyBase");
const joyKnob = $("joyKnob");
const fireBtn = $("fireBtn");
let joyId = null, joyX0 = 0, joyY0 = 0;
let lookId = null, lookX = 0, lookY = 0;

window.addEventListener("pointerdown", (e) => {
  if (!playing || shopOpen || e.pointerType !== "touch" || e.target.closest(".ui-btn, #shop")) return;
  if (e.clientX < window.innerWidth * 0.5 && joyId === null) {
    joyId = e.pointerId;
    joyX0 = e.clientX; joyY0 = e.clientY;
    joyBase.style.left = joyX0 + "px";
    joyBase.style.top = joyY0 + "px";
    joyBase.classList.remove("hidden");
  } else if (lookId === null) {
    lookId = e.pointerId;
    lookX = e.clientX; lookY = e.clientY;
    const now = performance.now();
    if (now - lastRightTap < DOUBLE_TAP_MS) toggleScope();   // 右半边双击：开关狙击镜
    lastRightTap = now;
  }
});
window.addEventListener("pointermove", (e) => {
  if (e.pointerId === joyId) {
    let dx = e.clientX - joyX0, dy = e.clientY - joyY0;
    const len = Math.hypot(dx, dy);
    if (len > JOY_RADIUS) { dx *= JOY_RADIUS / len; dy *= JOY_RADIUS / len; }
    joy.side = dx / JOY_RADIUS;
    joy.fwd = -dy / JOY_RADIUS;
    joyKnob.style.transform = `translate(${dx}px, ${dy}px)`;
    syncInput();
  } else if (e.pointerId === lookId) {
    const k = TOUCH_SENS * (curFov / BASE_FOV);
    me.yaw -= (e.clientX - lookX) * k;
    me.pitch = clamp(me.pitch - (e.clientY - lookY) * k, -sim.maxPitch, sim.maxPitch);
    lookX = e.clientX; lookY = e.clientY;
  }
});
function endTouch(e) {
  if (e.pointerId === joyId) {
    joyId = null; joy.fwd = 0; joy.side = 0;
    joyBase.classList.add("hidden");
    joyKnob.style.transform = "";
    syncInput();
  }
  if (e.pointerId === lookId) lookId = null;
}
window.addEventListener("pointerup", endTouch);
window.addEventListener("pointercancel", endTouch);

fireBtn.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  fireBtn.setPointerCapture(e.pointerId);
  input.firing = true;
  fireBtn.classList.add("active");
});
const stopFire = () => { input.firing = false; fireBtn.classList.remove("active"); };
fireBtn.addEventListener("pointerup", stopFire);
fireBtn.addEventListener("pointercancel", stopFire);
$("scoreBtn").addEventListener("click", () => { scoreToggled = !scoreToggled; });
$("leaveBtn").addEventListener("click", () => leave());
$("botAddBtn").addEventListener("click", () => sendJSON({ t: "bots", delta: 1 }));
$("botDelBtn").addEventListener("click", () => sendJSON({ t: "bots", delta: -1 }));
$("disbandBtn").addEventListener("click", () => leave());
$("shopBtn").addEventListener("click", () => toggleShop());
$("shopClose").addEventListener("click", () => toggleShop(false));
$("swapBtn").addEventListener("click", () => swapSlot());
$("scopeBtn").addEventListener("click", () => toggleScope());

// ---------------------------------------------------------------- 武器、狙击镜和商店

// 切换主武器 / 副武器（只能切到自己有的）。切换时狙击镜会关闭。
function equipSlot(slot) {
  if (!me.slots[slot] || me.active === slot) return;
  me.active = slot;
  if (scopeWanted) setScope(false);
  sendJSON({ t: "equip", slot });
  updateHud();
}

function swapSlot() {
  equipSlot(me.active === "primary" ? "secondary" : "primary");
}

function setScope(on) {
  scopeWanted = on;
  sendJSON({ t: "scope", on });
}

// 开关狙击镜：只有带镜的武器才能开
function toggleScope() {
  const w = weapons[activeWeapon()];
  if (!w || !w.zoom || !me.alive) return;
  setScope(!scopeWanted);
}

function toggleShop(force) {
  shopOpen = force === undefined ? !shopOpen : force;
  $("shop").classList.toggle("hidden", !shopOpen);
  if (shopOpen) {
    shopSig = "";
    if (document.pointerLockElement) document.exitPointerLock();
    input.firing = false;
    fireBtn.classList.remove("active");
    kb.fwd = kb.side = 0;
    joy.fwd = joy.side = 0;
    syncInput();
    renderShop();
  }
  updateHint();
}

let shopSig = "";              // 商店内容的签名：只有内容变了才重建按钮（否则点击会被半路替换掉）

function renderShop() {
  const sig = [me.money, me.alive, me.slots.primary, me.slots.secondary].join("|");
  if (sig === shopSig) return;
  shopSig = sig;
  $("shopMoney").textContent = "$" + me.money;
  $("shopNote").textContent = me.alive ? "" : tr("死亡后不能购买，复活后再来");
  const list = $("shopList");
  list.textContent = "";
  for (const id of SHOP_ORDER) {
    const w = weapons[id];
    if (!w) continue;
    const owned = me.slots[w.slot] === id;
    const row = document.createElement("div");
    row.className = "shop-row";
    const info = document.createElement("span");
    info.className = "shop-name";
    info.textContent = tr(w.name);
    const slot = document.createElement("small");
    slot.textContent = w.slot === "primary" ? tr("主武器") : tr("副武器");
    info.appendChild(slot);
    const price = document.createElement("span");
    price.className = "price";
    price.textContent = "$" + w.price;
    const btn = document.createElement("button");
    btn.className = "ui-btn";
    btn.textContent = owned ? tr("已拥有") : tr("购买");
    btn.disabled = owned || !me.alive || me.money < w.price;
    btn.addEventListener("click", () => sendJSON({ t: "buy", weapon: id }));
    row.append(info, price, btn);
    list.appendChild(row);
  }
}

// ---------------------------------------------------------------- 网络

function sendJSON(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

// 每 SEND_MS 毫秒：发送移动输入，并在本地先预测移动；按住开火就按当前武器的射速开火。
function networkTick(now) {
  if (!playing || !ws || ws.readyState !== WebSocket.OPEN) return;
  if (now - lastSend < SEND_MS) return;
  const dt = lastSend ? (now - lastSend) / 1000 : sim.maxDt;
  lastSend = now;
  seq += 1;
  const { fwd, side } = input;
  sendJSON({ t: "in", seq, fwd, side, yaw: me.yaw, pitch: me.pitch, dt: Math.min(dt, sim.maxDt) });
  if (me.alive) {
    [me.x, me.z] = move(me.x, me.z, fwd, side, me.yaw, Math.min(dt, sim.maxDt));
    pending.push({ seq, fwd, side, yaw: me.yaw, dt: Math.min(dt, sim.maxDt) });
    if (pending.length > 120) pending.shift();
  }
  const w = weapons[activeWeapon()];
  if (input.firing && me.alive && !shopOpen && w && now - lastFire >= w.interval * 1000) {
    lastFire = now;
    sendJSON({ t: "fire" });
    const o = [me.x, sim.eye, me.z];
    const d = aimDir(me.yaw, me.pitch);
    tracer(o, o.map((v, i) => v + d[i] * 60), false);   // 自己的子弹立刻显示，不等服务器
    kick(now, RECOIL[activeWeapon()] || 1);
  }
}

function openSocket() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const sock = new WebSocket(`${proto}//${location.host}${location.pathname}ws`);
  ws = sock;
  sock.onmessage = (ev) => {
    if (ws !== sock) return;
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (msg.t === "lobby") onLobby(msg);
    else if (msg.t === "welcome") onWelcome(msg);
    else if (msg.t === "state") onState(msg);
    else if (msg.t === "error") onError(msg.text);
  };
  sock.onclose = (e) => {
    if (ws !== sock) return;
    ws = null;
    playing = false;
    inRoom = false;
    roomInfo = null;
    $("hud").classList.add("hidden");
    $("menu").classList.remove("hidden");
    if (e.code === 4401) {       // 没登录：去首页登录，登录后回到这里
      location.href = `/?login=1&next=${encodeURIComponent(location.pathname)}`;
      return;
    }
    setStatus(tr("连接已断开"), true);
    $("reconnectBtn").classList.remove("hidden");
  };
}

function onLobby(msg) {
  lobby = msg;
  if (!msg.me.room) {          // 不在房间里：显示大厅
    if (inRoom) {
      inRoom = false;
      playing = false;
      roomInfo = null;
      input.firing = false;
      scopeWanted = false;
      toggleShop(false);
      if (document.pointerLockElement) document.exitPointerLock();
      $("hud").classList.add("hidden");
    }
    $("menu").classList.remove("hidden");
  }
  if (msg.notice) setStatus(tr(msg.notice), true);
  renderLobby();
}

function renderLobby() {
  const me = lobby.me || {};
  $("myName").textContent = me.name || "";
  $("createBtn").disabled = !me.canCreate;
  $("createHint").textContent = me.isGuest ? tr("注册账号后才能建房") : (me.ownedRoom ? tr("你已经有一个房间了") : "");
  const back = $("backRoomBtn");
  back.classList.toggle("hidden", !me.ownedRoom || !!me.room);
  const list = $("roomList");
  list.textContent = "";
  if (!lobby.rooms || !lobby.rooms.length) {
    const empty = document.createElement("p");
    empty.className = "room-empty";
    empty.textContent = tr("现在还没有房间");
    list.appendChild(empty);
    return;
  }
  for (const r of lobby.rooms) {
    const card = document.createElement("div");
    card.className = "room-card";
    const info = document.createElement("div");
    info.className = "info";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = r.name;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${tr("房主")}：${r.host} · ${r.humans}/${r.capacity} ${tr("人")} · ${r.bots} ${tr("电脑")}` +
      (r.hostOnline ? "" : ` · ${tr("房主不在线")}`);
    info.append(title, meta);
    const btn = document.createElement("button");
    btn.className = "ui-btn";
    btn.textContent = tr("加入");
    btn.disabled = r.humans >= r.capacity;
    btn.addEventListener("click", () => { enterFullscreen(); sendJSON({ t: "join", room: r.id }); });
    card.append(info, btn);
    list.appendChild(card);
  }
}

function onError(text) {
  if (inRoom) toast(tr(text));
  else setStatus(tr(text), true);
}

// 房间里的小提示（显示在左上角的信息栏里，几秒后消失）
function toast(text) {
  const item = document.createElement("div");
  item.className = "feed-item";
  item.textContent = text;
  const feed = $("feed");
  feed.appendChild(item);
  while (feed.children.length > 5) feed.firstChild.remove();
  setTimeout(() => { item.classList.add("fade"); setTimeout(() => item.remove(), 700); }, 4000);
}

function leave() {
  // 房主离开 = 解散房间，先确认一下
  if (roomInfo && roomInfo.isHost && !confirm(tr("确定解散房间吗？房间里的人都会回到大厅。"))) return;
  sendJSON({ t: "leave" });
}

function setStatus(text, isError = true) {
  const el = $("status");
  el.textContent = text;
  el.style.color = isError ? "" : "var(--muted)";
}

function onWelcome(msg) {
  myId = msg.id;
  sim = msg.sim;
  map = msg.map;
  weapons = msg.sim.weapons;
  if (!arenaBuilt) buildArena();
  for (const r of remotes.values()) scene.remove(r.group);
  remotes.clear();
  names.clear();
  wasAlive = false;
  pending.length = 0;
  seq = 0;
  lastSend = 0;
  scopeWanted = false;
  curFov = BASE_FOV;
  camera.fov = BASE_FOV;
  camera.updateProjectionMatrix();
  playing = true;
  inRoom = true;
  roomInfo = msg.room;
  $("menu").classList.add("hidden");
  $("hud").classList.remove("hidden");
  $("joyBase").classList.add("hidden");
  updateRoomBar();
  updateHint();
}

function onState(msg) {
  if (!sim) return;              // 还没收到欢迎消息（地图和参数），先忽略
  const you = msg.you;
  if (you) {
    if (you.alive && !wasAlive) {
      // 刚出生或刚复活：面向竞技场中心，避免一出来就对着边界墙
      me.yaw = Math.atan2(you.x, you.z);
      me.pitch = 0;
    }
    wasAlive = you.alive;
    me.hp = you.hp; me.alive = you.alive; me.respawnIn = you.respawn_in;
    me.kills = you.kills; me.deaths = you.deaths;
    me.money = you.money; me.slots = you.slots; me.active = you.active;
    myTeam = you.team ?? 0;
    if (you.alive) {
      // 以服务器的位置为准，再把还没被确认的输入重放一遍，得到当前应该在的位置
      pending = pending.filter((p) => p.seq > you.ack);
      let x = you.x, z = you.z;
      for (const p of pending) [x, z] = move(x, z, p.fwd, p.side, p.yaw, p.dt);
      me.x = x; me.z = z;
    } else {
      pending.length = 0;
      me.x = you.x; me.z = you.z;
    }
  }

  if (msg.room) {
    roomInfo = msg.room;
    updateRoomBar();
  }

  players = msg.players;
  const seen = new Set();
  const now = performance.now();
  for (const p of players) {
    names.set(p.id, p.name);
    if (p.id === myId) continue;
    seen.add(p.id);
    const r = remotes.get(p.id) || makeRemote(p);
    r.snaps.push({ t: now, x: p.x, z: p.z, yaw: p.yaw, pitch: p.pitch, alive: p.alive });
    if (r.snaps.length > 40) r.snaps.shift();
  }
  for (const [id, r] of remotes) {
    if (!seen.has(id)) { scene.remove(r.group); remotes.delete(id); }
  }

  for (const ev of msg.events) {
    if (ev.e === "shot") {
      if (ev.by !== myId) tracer(ev.from, ev.to);
    } else if (ev.e === "hit") {
      if (ev.by === myId) flash("hitmark");
      if (ev.to === myId) flash("hurt");
    } else if (ev.e === "kill") {
      addFeed(ev);
    }
  }
  if (msg.teams) teamKills = msg.teams;
  if (shopOpen) renderShop();
  updateHud();
}

// ---------------------------------------------------------------- HUD

function flash(id) {
  if (id === "hitmark") hitFlashUntil = performance.now() + 150;
  const el = $(id);
  el.classList.remove("on");
  void el.offsetWidth;               // 重新触发动画
  el.classList.add("on");
  setTimeout(() => el.classList.remove("on"), 160);
}

function addFeed(ev) {
  const by = names.get(ev.by) || "?";
  const to = names.get(ev.to) || "?";
  const text = ev.head ? tr("{0} 击败了 {1}（爆头）", by, to) : tr("{0} 击败了 {1}", by, to);
  const item = document.createElement("div");
  item.className = "feed-item";
  item.textContent = text;
  const feed = $("feed");
  feed.appendChild(item);
  while (feed.children.length > 5) feed.firstChild.remove();
  setTimeout(() => { item.classList.add("fade"); setTimeout(() => item.remove(), 700); }, 4000);
}

function updateHud() {
  $("kills").textContent = me.kills;
  $("deaths").textContent = me.deaths;
  $("money").textContent = "$" + me.money;
  $("teamScores").innerHTML = `<b style="color:${TEAM_CSS[0]}">${tr("红队")} ${teamKills[0]}</b> : <b style="color:${TEAM_CSS[1]}">${teamKills[1]} ${tr("蓝队")}</b>` +
    ` <small style="color:var(--muted)">${tr("我在")}${tr(myTeam === 0 ? "红队" : "蓝队")}</small>`;
  const pct = clamp(me.hp / sim.maxHp, 0, 1) * 100;
  $("hpfill").style.width = pct + "%";
  $("hpfill").style.background = pct > 35 ? "var(--ok)" : "var(--danger)";
  $("hptext").textContent = me.alive ? me.hp : 0;
  $("dead").classList.toggle("hidden", me.alive);
  if (!me.alive) $("respawn").textContent = tr("{0} 秒后复活", Math.ceil(me.respawnIn));
  $("crosshair").classList.toggle("hit", performance.now() < hitFlashUntil);
  const w = weapons[activeWeapon()];
  $("weaponName").textContent = w ? tr(w.name) : "";
  $("scopeBtn").classList.toggle("hidden", !(w && w.zoom));
  const showBoard = scoreHeld || scoreToggled;
  $("scoreboard").classList.toggle("hidden", !showBoard);
  $("scoreBtn").classList.toggle("active", scoreToggled);
  if (showBoard) renderBoard();
}

function updateRoomBar() {
  const r = roomInfo;
  $("roomBar").classList.toggle("hidden", !r);
  if (!r) return;
  $("roomTitle").textContent = `${r.name} · ${r.humans}${tr("人")} · ${r.bots}${tr("电脑")}`;
  for (const id of ["botAddBtn", "botDelBtn", "disbandBtn"]) {
    $(id).classList.toggle("hidden", !r.isHost);
  }
}

function renderBoard() {
  const rows = [...players].sort((a, b) => (b.kills - a.kills) || (a.deaths - b.deaths));
  const tbody = $("rows");
  tbody.textContent = "";
  const isHost = !!(roomInfo && roomInfo.isHost);
  for (const p of rows) {
    const tr_ = document.createElement("tr");
    if (p.id === myId) tr_.className = "me";
    const cells = [p.name + (p.id === myId ? tr("（你）") : ""), p.kills, p.deaths];
    for (const v of cells) {
      const td = document.createElement("td");
      td.textContent = v;
      tr_.appendChild(td);
    }
    // 房主可以踢掉别的人类玩家（电脑直接用「-电脑」来减）
    const last = document.createElement("td");
    if (isHost && !p.bot && p.id !== myId) {
      const btn = document.createElement("button");
      btn.className = "ui-btn kick-btn";
      btn.textContent = tr("踢出");
      btn.addEventListener("click", () => sendJSON({ t: "kick", id: p.id }));
      last.appendChild(btn);
    }
    tr_.appendChild(last);
    tbody.appendChild(tr_);
  }
}

function updateHint() {
  const hint = $("hint");
  if (!playing || shopOpen) { hint.textContent = ""; return; }
  if (touchDevice) hint.textContent = tr("左下摇杆移动 · 右侧滑动转向 · 右下按钮开火 · 双击右侧或点「瞄准」开镜");
  else hint.textContent = isLocked() ? "" : tr("点击画面开始控制视角 · WASD 移动 · 左键开火 · 右键瞄准 · 1/2 换枪 · B 商店 · Tab 记分板 · Esc 释放鼠标");
}

// ---------------------------------------------------------------- 主循环

let lastFrameAt = 0;
function frame(now) {
  requestAnimationFrame(frame);
  const dt = lastFrameAt ? Math.min((now - lastFrameAt) / 1000, 0.05) : 0;
  lastFrameAt = now;
  if (!arenaBuilt) return;
  networkTick(now);
  updateRemotes(now);
  updateTracers(now);
  updateParticles(dt);

  // 狙击镜：开镜时视野拉近，并显示镜子的黑框；这时看不到手里的枪
  const alive = playing && me.alive;
  const w = weapons[activeWeapon()];
  const zoomOn = !!(alive && scopeWanted && w && w.zoom > 0);
  me.scoped = zoomOn;
  const targetFov = zoomOn ? BASE_FOV / w.zoom : BASE_FOV;
  if (Math.abs(curFov - targetFov) > 0.05) {
    curFov += (targetFov - curFov) * Math.min(1, dt * 12);
    camera.fov = curFov;
    camera.updateProjectionMatrix();
  }
  $("scopeOverlay").classList.toggle("hidden", !zoomOn);
  $("crosshair").classList.toggle("hidden", zoomOn);
  viewmodel.visible = alive && !zoomOn;
  updateViewmodel(dt, now, alive && (input.fwd !== 0 || input.side !== 0), activeWeapon());

  if (playing) {
    camera.position.set(me.x, sim.eye, me.z);
    camera.rotation.set(me.pitch, me.yaw, 0);
  }
  renderer.render(scene, camera);
}

// ---------------------------------------------------------------- 大厅入口

$("createBtn").addEventListener("click", () => {
  const name = $("roomName").value.trim().slice(0, 16);
  enterFullscreen();     // 点击按钮是用户操作，这时进入全屏才允许
  sendJSON({ t: "create", name });
});
$("backRoomBtn").addEventListener("click", () => {
  enterFullscreen();
  sendJSON({ t: "join", room: lobby.me.ownedRoom });
});
$("reconnectBtn").addEventListener("click", () => {
  $("reconnectBtn").classList.add("hidden");
  setStatus(tr("正在连接…"), false);
  openSocket();
});
i18n.onChange(() => { if (playing) { updateHint(); if (shopOpen) renderShop(); updateHud(); } if (lobby.me) renderLobby(); });

loadAssets();                 // 环境光在后台加载，不影响进入大厅
setStatus(tr("正在连接…"), false);
openSocket();
requestAnimationFrame(frame);
