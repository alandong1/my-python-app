"use strict";
// 突击行动的浏览器端：Three.js 画面、键鼠 / 触屏输入、移动预测、HUD。
// 判定都在服务器（projects/strike/game.py）；这里的 move() 必须和服务器的 move() 保持一致，用于预测。
import * as THREE from "three";

const tr = (...args) => i18n.t(...args);
const $ = (id) => document.getElementById(id);
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const SEND_MS = 33;            // 约每秒 30 次发送移动输入
const FIRE_MS = 120;           // 客户端的射速限制，和服务器一致
const MOUSE_SENS = 0.0022;     // 鼠标灵敏度（弧度 / 像素）
const TOUCH_SENS = 0.006;      // 手机滑动转向的灵敏度
const JOY_RADIUS = 70;         // 摇杆最大拖动距离（像素）
const COLORS = [0xe4572e, 0x29a19c, 0xf3a712, 0x7b5ea7, 0x3e92cc, 0xc2185b,
                0x8bc34a, 0xff7043, 0x26c6da, 0xab47bc, 0xffca28, 0x66bb6a];

// ---------------------------------------------------------------- 状态

let sim = null;                // 服务器发来的移动参数（欢迎消息）
let map = null;                // 地图：边界、障碍物、出生点
let myId = null;
let ws = null;
let lastError = "";
let playing = false;           // 已经进入房间
let arenaBuilt = false;

const me = { x: 0, z: 0, yaw: 0, pitch: 0, hp: 100, alive: true, respawnIn: 0, kills: 0, deaths: 0 };
const names = new Map();       // 玩家 id → 名字
let players = [];             // 最近一次收到的全员状态
const remotes = new Map();     // 玩家 id → 画面里的人物模型
const tracers = [];            // 正在显示的子弹轨迹
let pending = [];            // 已经发送、还没被服务器确认的移动输入（用于预测对齐）
let seq = 0;
let lastSend = 0;
let lastFire = 0;
let hitFlashUntil = 0;

const kb = { fwd: 0, side: 0 };   // 键盘输入
const joy = { fwd: 0, side: 0 };  // 摇杆输入（手机）
const input = { fwd: 0, side: 0, firing: false };
const keys = new Set();
let scoreHeld = false;         // 按住 Tab
let scoreToggled = false;      // 手机上点「记分」切换
let touchDevice = matchMedia("(pointer: coarse)").matches;

// ---------------------------------------------------------------- 画面

const canvas = $("view");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.setSize(window.innerWidth, window.innerHeight, false);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x9fb8cc);
scene.fog = new THREE.Fog(0x9fb8cc, 45, 120);
const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.05, 300);
camera.rotation.order = "YXZ";   // 先转左右（yaw），再抬头低头（pitch）
scene.add(new THREE.HemisphereLight(0xffffff, 0x445533, 0.9));
const sun = new THREE.DirectionalLight(0xffffff, 0.8);
sun.position.set(20, 40, 10);
scene.add(sun);

const tracerMat = new THREE.LineBasicMaterial({ color: 0xffe08a, transparent: true, opacity: 0.9 });

window.addEventListener("resize", () => {
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
});

function buildArena() {
  const h = map.half;
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(2 * h, 2 * h),
    new THREE.MeshLambertMaterial({ color: 0x5d6b4c }));
  floor.rotation.x = -Math.PI / 2;
  scene.add(floor);
  const grid = new THREE.GridHelper(2 * h, h, 0x2c3324, 0x2c3324);   // 每格 2 米
  grid.position.y = 0.01;
  scene.add(grid);

  for (const [x0, y0, z0, x1, y1, z1] of map.walls) {
    addBox((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2, x1 - x0, y1 - y0, z1 - z0,
      y1 < 2 ? 0xb08d57 : 0x8d8f99);
  }
  // 四周的边界墙：厚 1 米，内侧正好在 ±half
  addBox(0, 1.5, -h - 0.5, 2 * h + 2, 3, 1, 0x555a66);
  addBox(0, 1.5, h + 0.5, 2 * h + 2, 3, 1, 0x555a66);
  addBox(-h - 0.5, 1.5, 0, 1, 3, 2 * h, 0x555a66);
  addBox(h + 0.5, 1.5, 0, 1, 3, 2 * h, 0x555a66);
  arenaBuilt = true;
}

function addBox(x, y, z, w, hgt, d, color) {
  const geo = new THREE.BoxGeometry(w, hgt, d);
  const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color }));
  mesh.position.set(x, y, z);
  scene.add(mesh);
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo),
    new THREE.LineBasicMaterial({ color: 0x1b1b1b, transparent: true, opacity: 0.5 }));
  edges.position.copy(mesh.position);
  scene.add(edges);
}

function nameSprite(text) {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 64;
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
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.7, 1.3, 0.5),
    new THREE.MeshLambertMaterial({ color: COLORS[p.id % COLORS.length] }));
  body.position.y = 0.65;
  const head = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.34, 0.34),
    new THREE.MeshLambertMaterial({ color: 0xf1c27d }));
  head.position.y = 1.55;
  const gunPivot = new THREE.Group();     // 枪挂在肩膀上，随视线上下转动
  gunPivot.position.set(0.25, 1.3, 0);
  const gun = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.14, 0.6),
    new THREE.MeshLambertMaterial({ color: 0x222222 }));
  gun.position.z = -0.3;
  gunPivot.add(gun);
  group.add(body, head, gunPivot, nameSprite(p.name));
  group.position.set(p.x, 0, p.z);
  scene.add(group);
  const r = { group, gunPivot, target: p };
  remotes.set(p.id, r);
  return r;
}

function updateRemotes() {
  for (const r of remotes.values()) {
    const t = r.target;
    const g = r.group;
    g.position.x += (t.x - g.position.x) * 0.35;
    g.position.z += (t.z - g.position.z) * 0.35;
    g.rotation.y = t.yaw;
    r.gunPivot.rotation.x = t.pitch;
  }
}

function tracer(from, to) {
  const geo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(...from), new THREE.Vector3(...to),
  ]);
  const line = new THREE.Line(geo, tracerMat);
  scene.add(line);
  tracers.push({ line, until: performance.now() + 110 });
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

// 鼠标（电脑）：点击画面进入 Pointer Lock，之后鼠标移动转向、左键开火
const isLocked = () => document.pointerLockElement === canvas;
canvas.addEventListener("mousedown", (e) => {
  if (!playing || touchDevice || e.button !== 0) return;
  if (!isLocked()) canvas.requestPointerLock();
  else input.firing = true;
});
window.addEventListener("mouseup", (e) => { if (e.button === 0) input.firing = false; });
document.addEventListener("mousemove", (e) => {
  if (!playing || !isLocked()) return;
  me.yaw -= e.movementX * MOUSE_SENS;
  me.pitch = clamp(me.pitch - e.movementY * MOUSE_SENS, -sim.maxPitch, sim.maxPitch);
});
document.addEventListener("pointerlockchange", () => {
  if (!isLocked()) input.firing = false;
  updateHint();
});

// 触屏（手机）：左半边拖动摇杆移动，右半边滑动转向；右下角按钮开火
const joyBase = $("joyBase");
const joyKnob = $("joyKnob");
const fireBtn = $("fireBtn");
let joyId = null, joyX0 = 0, joyY0 = 0;
let lookId = null, lookX = 0, lookY = 0;

window.addEventListener("pointerdown", (e) => {
  if (!playing || e.pointerType !== "touch" || e.target.closest(".ui-btn")) return;
  if (e.clientX < window.innerWidth * 0.5 && joyId === null) {
    joyId = e.pointerId;
    joyX0 = e.clientX; joyY0 = e.clientY;
    joyBase.style.left = joyX0 + "px";
    joyBase.style.top = joyY0 + "px";
    joyBase.classList.remove("hidden");
  } else if (lookId === null) {
    lookId = e.pointerId;
    lookX = e.clientX; lookY = e.clientY;
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
    me.yaw -= (e.clientX - lookX) * TOUCH_SENS;
    me.pitch = clamp(me.pitch - (e.clientY - lookY) * TOUCH_SENS, -sim.maxPitch, sim.maxPitch);
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

// ---------------------------------------------------------------- 网络

function sendJSON(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

// 每 SEND_MS 毫秒：发送移动输入，并在本地先预测移动；按住开火就发开火消息。
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
  if (input.firing && me.alive && now - lastFire >= FIRE_MS) {
    lastFire = now;
    sendJSON({ t: "fire" });
    const o = [me.x, sim.eye, me.z];
    const d = aimDir(me.yaw, me.pitch);
    tracer(o, o.map((v, i) => v + d[i] * 60));   // 自己的子弹立刻显示，不等服务器
  }
}

function connect(name) {
  lastError = "";
  setStatus(tr("正在连接…"), false);
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const sock = new WebSocket(`${proto}//${location.host}${location.pathname}ws`);
  ws = sock;
  sock.onopen = () => sock.send(JSON.stringify({ t: "join", name }));
  sock.onmessage = (ev) => {
    if (ws !== sock) return;
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (msg.t === "welcome") onWelcome(msg);
    else if (msg.t === "state") onState(msg);
    else if (msg.t === "error") lastError = tr(msg.text);
  };
  sock.onclose = () => {
    if (ws !== sock) return;
    ws = null;
    leave(lastError || tr("连接已断开，请重新进入"));
  };
}

function leave(message = "") {
  playing = false;
  input.firing = false;
  if (document.pointerLockElement) document.exitPointerLock();
  const sock = ws;
  ws = null;
  if (sock) sock.close();
  $("hud").classList.add("hidden");
  $("menu").classList.remove("hidden");
  setStatus(message);
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
  if (!arenaBuilt) buildArena();
  for (const r of remotes.values()) scene.remove(r.group);
  remotes.clear();
  names.clear();
  pending.length = 0;
  seq = 0;
  lastSend = 0;
  playing = true;
  $("menu").classList.add("hidden");
  $("hud").classList.remove("hidden");
  $("joyBase").classList.add("hidden");
  updateHint();
}

function onState(msg) {
  if (!sim) return;              // 还没收到欢迎消息（地图和参数），先忽略
  const you = msg.you;
  if (you) {
    me.hp = you.hp; me.alive = you.alive; me.respawnIn = you.respawn_in;
    me.kills = you.kills; me.deaths = you.deaths;
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

  players = msg.players;
  const seen = new Set();
  for (const p of players) {
    names.set(p.id, p.name);
    if (p.id === myId) continue;
    seen.add(p.id);
    const r = remotes.get(p.id) || makeRemote(p);
    r.target = p;
    r.group.visible = p.alive;
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
  const pct = clamp(me.hp / sim.maxHp, 0, 1) * 100;
  $("hpfill").style.width = pct + "%";
  $("hpfill").style.background = pct > 35 ? "var(--ok)" : "var(--danger)";
  $("hptext").textContent = me.alive ? me.hp : 0;
  $("dead").classList.toggle("hidden", me.alive);
  if (!me.alive) $("respawn").textContent = tr("{0} 秒后复活", Math.ceil(me.respawnIn));
  $("crosshair").classList.toggle("hit", performance.now() < hitFlashUntil);
  const showBoard = scoreHeld || scoreToggled;
  $("scoreboard").classList.toggle("hidden", !showBoard);
  $("scoreBtn").classList.toggle("active", scoreToggled);
  if (showBoard) renderBoard();
}

function renderBoard() {
  const rows = [...players].sort((a, b) => (b.kills - a.kills) || (a.deaths - b.deaths));
  const tbody = $("rows");
  tbody.textContent = "";
  for (const p of rows) {
    const tr_ = document.createElement("tr");
    if (p.id === myId) tr_.className = "me";
    const cells = [p.name + (p.id === myId ? tr("（你）") : ""), p.kills, p.deaths];
    for (const v of cells) {
      const td = document.createElement("td");
      td.textContent = v;
      tr_.appendChild(td);
    }
    tbody.appendChild(tr_);
  }
}

function updateHint() {
  const hint = $("hint");
  if (!playing) { hint.textContent = ""; return; }
  if (touchDevice) hint.textContent = tr("左下摇杆移动 · 右侧滑动转向 · 右下按钮开火");
  else hint.textContent = isLocked() ? "" : tr("点击画面开始控制视角 · WASD 移动 · 左键开火 · Tab 记分板 · Esc 释放鼠标");
}

// ---------------------------------------------------------------- 主循环

function frame(now) {
  requestAnimationFrame(frame);
  if (!arenaBuilt) return;
  networkTick(now);
  updateRemotes();
  updateTracers(now);
  if (playing) {
    camera.position.set(me.x, sim.eye, me.z);
    camera.rotation.set(me.pitch, me.yaw, 0);
  }
  renderer.render(scene, camera);
}

// ---------------------------------------------------------------- 进入界面

const nameInput = $("nameInput");
try { nameInput.value = localStorage.getItem("strike-name") || ""; } catch (e) { /* 隐私模式下忽略 */ }
$("joinForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const name = nameInput.value.trim().slice(0, 12) || tr("匿名玩家");
  try { localStorage.setItem("strike-name", name); } catch (e2) { /* 忽略 */ }
  connect(name);
});
i18n.onChange(() => { if (playing) updateHint(); });

requestAnimationFrame(frame);
