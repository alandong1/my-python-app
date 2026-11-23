// 荒岛求生：浏览器端。只负责显示和发送按键，所有规则都在服务器（game.py）里算。
import * as THREE from 'three';

const $ = (id) => document.getElementById(id);
const TERRAIN_H = [-0.8, -0.3, 0.05, 0.25, 0.3];                       // 深海 浅海 沙滩 草地 森林
const TERRAIN_C = ['#1e4d7a', '#4fa3c7', '#e8d59a', '#6fae4d', '#3d7a3a'];
const ROLE_COLOR = { chef: 0xe07b39, doctor: 0xf2f2f2, priest: 0x7a5cc4 };
// 远端玩家和动物按「过去 100 毫秒」的画面显示：服务器每 0.1 秒发一次，网络有快有慢，
// 延迟 100 毫秒后就有两个快照可以匀速插值，画面不会一顿一顿。（和 strike 的做法相同）
const INTERP_MS = 100;

let ws = null, role = null, myId = null, info = null, latest = null;
let scene, camera, renderer, me = null;
let yaw = Math.PI, dragging = false, lastX = 0;
const players = new Map(), animals = new Map(), fires = new Map(), trees = new Map();
const keys = new Set();
let joy = { x: 0, y: 0 };
let lastInvKey = '', toastTimer = 0, lastFrame = 0;
const shared = {};
const focus = new THREE.Vector3();   // 镜头盯着的点

// ------------------------------------------------------------ 连接与消息

function connect() {
  const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
  const base = location.pathname.replace(/\/?$/, '/');
  ws = new WebSocket(proto + location.host + base + 'ws');
  ws.onopen = () => { $('pickMsg').textContent = ''; if (role) send({ type: 'join', role }); };
  ws.onmessage = (ev) => onMessage(JSON.parse(ev.data));
  ws.onclose = (ev) => {
    if (ev.code === 4401) return;                       // 未登录：onMessage 已跳转
    if (!info) { $('pickMsg').textContent = '连接失败，请刷新页面'; return; }
    toast('连接断开了，正在重连……');
    setTimeout(connect, 2000);
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

// 把当前的移动方向发给服务器；按键、拖动、摇杆变化时立即调用，不等下一次定时发送
function sendMove() {
  const v = moveVector();
  send({ type: 'move', dx: v.dx, dz: v.dz });
}

function onMessage(msg) {
  if (msg.type === 'auth') {
    location.href = '/?login=1&next=' + encodeURIComponent(location.pathname);
  } else if (msg.type === 'welcome') {
    info = msg.info; myId = msg.id;
    startGame(msg.state);
  } else if (msg.type === 'state') {
    latest = msg;
    applyState(msg);
  } else if (msg.type === 'error') {
    toast(msg.text);
    $('pickMsg').textContent = msg.text;
  }
}

// ------------------------------------------------------------ 选角色

document.querySelectorAll('.role').forEach((btn) => {
  btn.addEventListener('click', () => {
    role = btn.dataset.role;
    if (ws && ws.readyState === WebSocket.OPEN) send({ type: 'join', role });
    else $('pickMsg').textContent = '正在连接服务器……';
  });
});

connect();   // 打开页面就连上服务器；服务器会先检查是否登录

// ------------------------------------------------------------ 开始游戏与三维场景

function startGame(state) {
  $('pick').hidden = true;
  $('game').hidden = false;
  $('roleName').textContent = info.roles[role] || role;
  $('actions').classList.toggle('doctor', role === 'doctor');
  // 掉线重连时会再收到一次 welcome：场景、输入和循环只初始化一次
  if (!scene) {
    initScene();
    buildTerrain();
    setupInput();
    requestAnimationFrame(frame);
    sendMove();
    setInterval(sendMove, 100);
  }
  applyState(state);
}

function initScene() {
  renderer = new THREE.WebGLRenderer({ canvas: $('scene'), antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  scene = new THREE.Scene();
  scene.background = new THREE.Color('#9fd3ec');
  scene.fog = new THREE.Fog('#9fd3ec', 45, 110);
  camera = new THREE.PerspectiveCamera(60, 1, 0.1, 400);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.0));
  const sun = new THREE.DirectionalLight(0xffffff, 0.9);
  sun.position.set(60, 90, 30);
  scene.add(sun);
  resize();
  window.addEventListener('resize', resize);

  // 海面（半透明）
  const water = new THREE.Mesh(
    new THREE.PlaneGeometry(info.w * 3, info.h * 3),
    new THREE.MeshStandardMaterial({ color: '#3a8fc2', transparent: true, opacity: 0.7 }));
  water.rotation.x = -Math.PI / 2;
  water.position.set(info.w / 2, 0, info.h / 2);
  scene.add(water);

  // 共用的几何体和材质，省内存
  shared.trunk = new THREE.CylinderGeometry(0.12, 0.18, 1.3, 6);
  shared.brown = new THREE.MeshLambertMaterial({ color: '#7a5233' });
  shared.leaf = new THREE.ConeGeometry(0.75, 1.9, 7);
  shared.leafMat = new THREE.MeshLambertMaterial({ color: '#2e7d32' });
  shared.bush = new THREE.SphereGeometry(0.5, 8, 6);
  shared.bushMat = new THREE.MeshLambertMaterial({ color: '#3f7d2c' });
  shared.berry = new THREE.SphereGeometry(0.08, 6, 4);
  shared.berryMat = new THREE.MeshLambertMaterial({ color: '#c0392b' });
  shared.herb = new THREE.ConeGeometry(0.1, 0.5, 5);
  shared.herbMat = new THREE.MeshLambertMaterial({ color: '#9ccc65' });
  shared.body = new THREE.CylinderGeometry(0.25, 0.25, 0.9, 10);
  shared.head = new THREE.SphereGeometry(0.22, 10, 8);
  shared.skin = new THREE.MeshLambertMaterial({ color: '#f1c9a5' });
  shared.rabbit = new THREE.SphereGeometry(0.25, 8, 6);
  shared.rabbitMat = new THREE.MeshLambertMaterial({ color: '#c9b49a' });
  shared.crab = new THREE.SphereGeometry(0.22, 8, 6);
  shared.crabMat = new THREE.MeshLambertMaterial({ color: '#d9573a' });
  shared.flame = new THREE.ConeGeometry(0.2, 0.6, 6);
  shared.flameMat = new THREE.MeshBasicMaterial({ color: '#ff8a1f' });
  shared.ring = new THREE.RingGeometry(0.4, 0.5, 20);
  shared.ringMat = new THREE.MeshBasicMaterial({ color: '#ffe066', side: THREE.DoubleSide, transparent: true, opacity: 0.8 });
}

function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

// 地形顶点（格子的角）的高度。地形网格和 heightAt() 都用它，保证人站在地面上。
function vertexHeight(i, j) {
  const tx = Math.min(info.w - 1, i), tz = Math.min(info.h - 1, j);
  const t = info.terrain.charCodeAt(tz * info.w + tx) - 48;
  return TERRAIN_H[t] + (t >= 2 ? 0.05 * Math.sin(i * 0.7) * Math.cos(j * 0.6) : 0);
}

// 任意位置的地面高度：在周围四个顶点之间做双线性插值，所以走过格子边界时不会阶跃
function terrainHeight(x, z) {
  const i = Math.min(info.w - 1, Math.max(0, Math.floor(x)));
  const j = Math.min(info.h - 1, Math.max(0, Math.floor(z)));
  const fx = Math.min(1, Math.max(0, x - i)), fz = Math.min(1, Math.max(0, z - j));
  const h00 = vertexHeight(i, j), h10 = vertexHeight(i + 1, j);
  const h01 = vertexHeight(i, j + 1), h11 = vertexHeight(i + 1, j + 1);
  return h00 * (1 - fx) * (1 - fz) + h10 * fx * (1 - fz) + h01 * (1 - fx) * fz + h11 * fx * fz;
}

// 地形：每个格子的四个角是一个顶点，颜色来自地形编号
function buildTerrain() {
  const W = info.w, H = info.h, T = info.terrain;
  const pos = new Float32Array((W + 1) * (H + 1) * 3);
  const col = new Float32Array((W + 1) * (H + 1) * 3);
  const c = new THREE.Color();
  for (let j = 0; j <= H; j++) {
    for (let i = 0; i <= W; i++) {
      const tx = Math.min(i, W - 1), tz = Math.min(j, H - 1);
      const t = T.charCodeAt(tz * W + tx) - 48;
      const k = (j * (W + 1) + i) * 3;
      pos[k] = i; pos[k + 1] = vertexHeight(i, j); pos[k + 2] = j;
      c.set(TERRAIN_C[t]);
      col[k] = c.r; col[k + 1] = c.g; col[k + 2] = c.b;
    }
  }
  const index = new Uint32Array(W * H * 6);
  let n = 0;
  for (let j = 0; j < H; j++) {
    for (let i = 0; i < W; i++) {
      const a = j * (W + 1) + i, b = a + 1, d = a + (W + 1), e = d + 1;
      index[n++] = a; index[n++] = d; index[n++] = b;
      index[n++] = b; index[n++] = d; index[n++] = e;
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  geo.setIndex(new THREE.BufferAttribute(index, 1));
  geo.computeVertexNormals();
  scene.add(new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ vertexColors: true })));
}

// ------------------------------------------------------------ 模型

function makeTree(id) {
  const g = new THREE.Group();
  const trunk = new THREE.Mesh(shared.trunk, shared.brown);
  trunk.position.y = 0.65;
  const leaf = new THREE.Mesh(shared.leaf, shared.leafMat);
  leaf.position.y = 2.0;
  g.add(trunk, leaf);
  const s = 0.8 + ((id * 37) % 40) / 100;                  // 每棵树大小不一样
  g.scale.setScalar(s);
  return g;
}

function makeBush() {
  const g = new THREE.Group();
  const bush = new THREE.Mesh(shared.bush, shared.bushMat);
  bush.scale.set(1, 0.7, 1);
  bush.position.y = 0.3;
  g.add(bush);
  for (const [x, z] of [[0.3, 0.2], [-0.25, 0.3], [0.05, -0.4]]) {
    const b = new THREE.Mesh(shared.berry, shared.berryMat);
    b.position.set(x, 0.55, z);
    g.add(b);
  }
  return g;
}

function makeHerb() {
  const g = new THREE.Group();
  for (const [x, z] of [[0, 0], [0.15, 0.1], [-0.12, 0.08]]) {
    const h = new THREE.Mesh(shared.herb, shared.herbMat);
    h.position.set(x, 0.25, z);
    g.add(h);
  }
  return g;
}

function makeAnimal(kind) {
  const g = new THREE.Group();
  if (kind === 'rabbit') {
    const body = new THREE.Mesh(shared.rabbit, shared.rabbitMat);
    body.scale.set(1, 0.8, 1.3);
    body.position.y = 0.25;
    const head = new THREE.Mesh(shared.rabbit, shared.rabbitMat);
    head.scale.setScalar(0.5);
    head.position.set(0, 0.4, 0.3);
    g.add(body, head);
  } else {
    const body = new THREE.Mesh(shared.crab, shared.crabMat);
    body.scale.set(1.4, 0.5, 1);
    body.position.y = 0.12;
    g.add(body);
  }
  return g;
}

function makePlayer(p) {
  const [id, name, r] = p;
  const g = new THREE.Group();
  const body = new THREE.Mesh(shared.body, new THREE.MeshLambertMaterial({ color: ROLE_COLOR[r] || 0xffffff }));
  body.position.y = 0.45;
  const head = new THREE.Mesh(shared.head, shared.skin);
  head.position.y = 1.15;
  g.add(body, head);
  if (id === myId) {
    const ring = new THREE.Mesh(shared.ring, shared.ringMat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.03;
    g.add(ring);
  }
  g.add(nameTag(name));
  return g;
}

function nameTag(text) {
  const canvas = document.createElement('canvas');
  canvas.width = 256; canvas.height = 64;
  const ctx = canvas.getContext('2d');
  ctx.font = 'bold 30px sans-serif';
  ctx.textAlign = 'center';
  ctx.lineWidth = 6; ctx.strokeStyle = 'rgba(0,0,0,0.7)';
  ctx.strokeText(text, 128, 42);
  ctx.fillStyle = '#fff';
  ctx.fillText(text, 128, 42);
  const tex = new THREE.CanvasTexture(canvas);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  sprite.scale.set(2.2, 0.55, 1);
  sprite.position.y = 1.9;
  return sprite;
}

// ------------------------------------------------------------ 快照插值

// 记下服务器给的位置和收到的时间（用浏览器的时钟，不用服务器时间）
function pushSample(mesh, x, z) {
  const now = performance.now();
  const s = mesh.userData.samples;
  s.push({ t: now, x, z });
  while (s.length > 2 && s[0].t < now - 1000) s.shift();
}

// 取 renderT 时刻的位置：在两个快照之间匀速插值。返回 {x, z, vx, vz}
function sampleAt(mesh, renderT) {
  const s = mesh.userData.samples;
  if (!s || !s.length) return null;
  if (renderT <= s[0].t) return { x: s[0].x, z: s[0].z, vx: 0, vz: 0 };
  const last = s[s.length - 1];
  if (renderT >= last.t) return { x: last.x, z: last.z, vx: 0, vz: 0 };
  for (let i = s.length - 2; i >= 0; i--) {
    const a = s[i], b = s[i + 1];
    if (a.t <= renderT) {
      const k = (renderT - a.t) / ((b.t - a.t) || 1);
      return { x: a.x + (b.x - a.x) * k, z: a.z + (b.z - a.z) * k, vx: b.x - a.x, vz: b.z - a.z };
    }
  }
  return { x: s[0].x, z: s[0].z, vx: 0, vz: 0 };
}

// ------------------------------------------------------------ 把服务器状态画出来

function applyState(s) {
  if (!scene) return;
  const m = s.me;
  me = m;
  setBars(m);
  setInventory(m.inv);
  setLog(m.events);
  $('meName').textContent = m.name;
  $('dead').hidden = !m.dead;

  // 所有玩家（包括自己）
  const seen = new Set();
  for (const p of s.players) {
    const [id, , , x, z] = p;
    seen.add(id);
    let mesh = players.get(id);
    if (!mesh) {
      mesh = makePlayer(p);
      mesh.userData = { samples: [] };
      mesh.position.set(x, terrainHeight(x, z), z);
      scene.add(mesh);
      players.set(id, mesh);
    }
    pushSample(mesh, x, z);
    mesh.userData.dead = p[5];
  }
  removeMissing(players, seen);
  $('survivors').textContent = `岛上幸存者：${s.players.length} 人`;
  $('survivors').textContent += ' · ' + s.players.map((p) => p[1] + '（' + (info.roles[p[2]] || '') + '）').join('、');

  // 动物
  const aseen = new Set();
  for (const [id, kind, x, z] of s.animals) {
    aseen.add(id);
    let mesh = animals.get(id);
    if (!mesh) {
      mesh = makeAnimal(kind);
      mesh.userData = { samples: [] };
      mesh.position.set(x, terrainHeight(x, z), z);
      scene.add(mesh);
      animals.set(id, mesh);
    }
    pushSample(mesh, x, z);
  }
  removeMissing(animals, aseen);

  // 火堆
  const fseen = new Set();
  for (const [id, x, z] of s.fires) {
    fseen.add(id);
    if (!fires.has(id)) {
      const g = new THREE.Group();
      const flame = new THREE.Mesh(shared.flame, shared.flameMat);
      flame.position.y = 0.3;
      g.add(flame);
      g.position.set(x, terrainHeight(x, z), z);
      scene.add(g);
      fires.set(id, g);
    }
  }
  removeMissing(fires, fseen);

  // 资源（树、灌木丛、草本植物）：每秒才更新一次
  if (s.res) {
    const rseen = new Set();
    for (const [id, kind, x, z] of s.res) {
      rseen.add(id);
      if (!trees.has(id)) {
        const mesh = kind === 'tree' ? makeTree(id) : kind === 'bush' ? makeBush() : makeHerb();
        mesh.position.set(x + 0.5, terrainHeight(x + 0.5, z + 0.5), z + 0.5);
        scene.add(mesh);
        trees.set(id, mesh);
      }
    }
    removeMissing(trees, rseen);
  }
}

function removeMissing(map, seen) {
  for (const [id, obj] of map) {
    if (!seen.has(id)) { scene.remove(obj); map.delete(id); }
  }
}

function setBars(m) {
  const bar = (name, v) => {
    $('bar' + name).style.width = Math.max(0, Math.min(100, v)) + '%';
    $('val' + name).textContent = Math.round(v);
  };
  bar('Hunger', m.hunger);
  bar('Health', m.health);
  bar('Sanity', m.sanity);
  $('sickBadge').hidden = !m.sick;
}

const USABLE = {
  coconut: '吃', berry: '吃', raw_fish: '吃', raw_meat: '吃',
  cooked_fish: '吃', cooked_meat: '吃', medicine: '用',
};

function setInventory(inv) {
  const key = JSON.stringify(inv);
  if (key === lastInvKey) return;
  lastInvKey = key;
  const ul = $('inv');
  ul.replaceChildren();
  const entries = Object.entries(inv);
  if (!entries.length) {
    const li = document.createElement('li');
    li.textContent = '（空）';
    ul.append(li);
    return;
  }
  for (const [item, n] of entries) {
    const li = document.createElement('li');
    const label = document.createElement('span');
    label.textContent = `${info.items[item] || item} × ${n}`;
    li.append(label);
    if (item in USABLE) {
      const btn = document.createElement('button');
      btn.textContent = USABLE[item];
      btn.dataset.item = item;
      li.append(btn);
    }
    ul.append(li);
  }
}

function setLog(events) {
  for (const text of events || []) {
    const p = document.createElement('p');
    p.textContent = text;
    $('log').append(p);
  }
  while ($('log').children.length > 6) $('log').firstChild.remove();
}

function toast(text) {
  const el = $('toast');
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2500);
}

// ------------------------------------------------------------ 输入

function setupInput() {
  window.addEventListener('keydown', (e) => {
    if (!me || e.repeat) return;
    const k = e.key.toLowerCase();
    if (['w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'].includes(k)) {
      keys.add(k);
      e.preventDefault();
      sendMove();
      return;
    }
    const map = { e: 'interact', b: 'build_fire', c: 'cook', x: 'craft', h: 'heal' };
    if (map[k]) send({ type: 'action', action: map[k] });
  });
  window.addEventListener('keyup', (e) => { keys.delete(e.key.toLowerCase()); sendMove(); });
  window.addEventListener('blur', () => { keys.clear(); sendMove(); });

  // 禁止双击放大、捏合缩放（手机上会打断操作）
  for (const type of ['dblclick', 'gesturestart', 'gesturechange']) {
    document.addEventListener(type, (e) => e.preventDefault(), { passive: false });
  }

  document.querySelectorAll('#actions button').forEach((b) => {
    b.addEventListener('click', () => send({ type: 'action', action: b.dataset.action }));
  });
  $('inv').addEventListener('click', (e) => {
    const item = e.target.dataset && e.target.dataset.item;
    if (item) send({ type: 'action', action: 'use', item });
  });
  $('respawnBtn').addEventListener('click', () => send({ type: 'action', action: 'respawn' }));

  // 鼠标拖动转视角
  const canvas = $('scene');
  canvas.addEventListener('pointerdown', (e) => {
    dragging = true; lastX = e.clientX;
    canvas.setPointerCapture(e.pointerId);     // 拖出画布也不丢
  });
  window.addEventListener('pointerup', () => { dragging = false; });
  window.addEventListener('pointercancel', () => { dragging = false; });
  window.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    yaw -= (e.clientX - lastX) * 0.008;
    lastX = e.clientX;
    sendMove();                                // 转向后，移动方向立刻跟着变
  });

  // 手机：虚拟摇杆
  const joyEl = $('joy'), knob = $('knob');
  let joyId = null, cx = 0, cy = 0;
  joyEl.addEventListener('pointerdown', (e) => {
    joyId = e.pointerId;
    const r = joyEl.getBoundingClientRect();
    cx = r.left + r.width / 2; cy = r.top + r.height / 2;
    joyEl.setPointerCapture(joyId);
  });
  joyEl.addEventListener('pointermove', (e) => {
    if (e.pointerId !== joyId) return;
    const max = 45;
    let dx = e.clientX - cx, dy = e.clientY - cy;
    const len = Math.hypot(dx, dy);
    if (len > max) { dx = dx / len * max; dy = dy / len * max; }
    joy = { x: dx / max, y: dy / max };
    knob.style.transform = `translate(${dx}px, ${dy}px)`;
    sendMove();
  });
  const endJoy = () => { joyId = null; joy = { x: 0, y: 0 }; knob.style.transform = ''; sendMove(); };
  joyEl.addEventListener('pointerup', endJoy);
  joyEl.addEventListener('pointercancel', endJoy);
}

// 根据按键和摇杆，算出在世界里走的方向（相对镜头）
function moveVector() {
  let fwd = (keys.has('w') || keys.has('arrowup') ? 1 : 0) - (keys.has('s') || keys.has('arrowdown') ? 1 : 0);
  let right = (keys.has('d') || keys.has('arrowright') ? 1 : 0) - (keys.has('a') || keys.has('arrowleft') ? 1 : 0);
  fwd += -joy.y; right += joy.x;
  const fx = -Math.sin(yaw), fz = -Math.cos(yaw);       // 镜头朝向
  const rx = Math.cos(yaw), rz = -Math.sin(yaw);        // 镜头右边
  const dx = fx * fwd + rx * right, dz = fz * fwd + rz * right;
  return { dx: Math.max(-1, Math.min(1, dx)), dz: Math.max(-1, Math.min(1, dz)) };
}

// ------------------------------------------------------------ 每一帧

function frame(now) {
  requestAnimationFrame(frame);
  if (!me || !scene) return;
  const t = now / 1000;
  const dt = lastFrame ? Math.min(0.05, (now - lastFrame) / 1000) : 0.016;
  lastFrame = now;

  // 人物和动物：按 100 毫秒前的时间线，在两个快照之间匀速移动
  const renderT = performance.now() - INTERP_MS;
  for (const mesh of players.values()) {
    const s = sampleAt(mesh, renderT);
    if (!s) continue;
    mesh.position.set(s.x, terrainHeight(s.x, s.z), s.z);
    if (Math.abs(s.vx) + Math.abs(s.vz) > 1e-4) mesh.rotation.y = Math.atan2(s.vx, s.vz);
    const target = mesh.userData.dead ? Math.PI / 2 : 0;
    mesh.rotation.z += (target - mesh.rotation.z) * Math.min(1, dt * 10);
  }
  for (const mesh of animals.values()) {
    const s = sampleAt(mesh, renderT);
    if (!s) continue;
    mesh.position.set(s.x, terrainHeight(s.x, s.z), s.z);
    if (Math.abs(s.vx) + Math.abs(s.vz) > 1e-4) mesh.rotation.y = Math.atan2(s.vx, s.vz);
  }
  for (const g of fires.values()) {
    g.children[0].scale.setScalar(0.9 + 0.15 * Math.sin(t * 12 + g.position.x));
  }

  // 镜头盯着自己的模型（同样是插值后的位置），再平滑地跟过去
  const mine = players.get(myId);
  const fx = mine ? mine.position.x : me.x;
  const fz = mine ? mine.position.z : me.z;
  focus.set(fx, terrainHeight(fx, fz) + 1.0, fz);
  const dist = 9, height = 5;
  const want = new THREE.Vector3(focus.x + Math.sin(yaw) * dist, focus.y + height, focus.z + Math.cos(yaw) * dist);
  camera.position.lerp(want, 1 - Math.exp(-dt * 8));
  camera.lookAt(focus);
  renderer.render(scene, camera);
}
