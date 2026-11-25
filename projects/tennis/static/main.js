// 网球前端：大厅 / 房间 / 三维比赛画面 / 摇杆和按键。
// 所有比赛计算都在服务器上（game.py），这里只负责显示和发送操作。
import * as THREE from './vendor/three.module.min.js';

const BASE = location.pathname.endsWith('/') ? location.pathname : location.pathname + '/';
const REACH = 1.35;                 // 与服务器 game.py 的 REACH 保持一致
const STROKE_KEYS = ['flat', 'top', 'back', 'side_l', 'side_r'];

const S = {
  me: null,             // {id, name}
  isGuest: false,
  ws: null,
  view: 'lobby',        // lobby | room | game
  rooms: [],
  room: null,           // 房间信息（从 state.room 来）
  state: null,          // 最新的比赛状态
};

// ------------------------------------------------------------ 小工具

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, children = []) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined || v === false) continue;   // 空值不写属性
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of children) n.append(c);
  return n;
};
let toastTimer = null;
function toast(text) {
  const t = $('toast');
  t.textContent = text;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 2200);
}
function send(msg) {
  if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(msg));
}
function mySeat(state = S.state) {
  if (!state || !S.me) return null;
  return state.seats.find((s) => s && s.userId === S.me.id) || null;
}
function myTeam() {
  const seat = mySeat();
  return seat ? seat.team : 0;
}
function showView(name) {
  S.view = name;
  $('lobby').hidden = name !== 'lobby';
  $('roomView').hidden = name !== 'room';
  $('game').hidden = name !== 'game';
  document.body.classList.toggle('in-game', name === 'game');   // 比赛时隐藏顶栏，画面占满屏幕
  if (name === 'game') resizeRenderer();
}
function goLogin() {
  location.href = '/?login=1&next=' + encodeURIComponent(location.pathname);
}

// ------------------------------------------------------------ 大厅

function renderLobby() {
  const box = $('rooms');
  box.replaceChildren();
  for (const r of S.rooms) {
    const waiting = r.status === 'waiting';
    const full = r.players >= r.capacity;
    let tag;
    if (waiting) tag = el('span', { class: 'tag wait', text: full ? '已满' : '等待中' });
    else if (r.status === 'playing') tag = el('span', { class: 'tag play', text: '进行中' });
    else tag = el('span', { class: 'tag done', text: '已结束' });
    const canJoin = waiting && !full;
    const btn = el('button', {
      class: canJoin ? 'primary' : '',
      disabled: canJoin ? null : 'disabled',
      text: canJoin ? '加入' : (waiting ? '已满' : '进行中'),
      onclick: () => joinRoom(r.id),
    });
    box.append(el('div', { class: 'room' }, [
      el('div', { class: 'info' }, [
        el('div', { class: 'name', text: r.name }),
        el('div', { class: 'muted', text: `${r.modeName} · 房主 ${r.host} · ${r.players}/${r.capacity} 人` }),
      ]),
      tag,
      btn,
    ]));
  }
  $('emptyRooms').hidden = S.rooms.length > 0;
}

function joinRoom(roomId) {
  send({ type: 'join', roomId });
}

// 离开房间：本地马上回到大厅（服务器随后会发来最新的房间列表）
function leaveRoom() {
  send({ type: 'leave' });
  S.state = null;
  S.room = null;
  showView('lobby');
  renderLobby();
}

function openCreate() {
  if (S.isGuest) return;
  $('roomName').value = '';
  document.querySelector('input[name=opponent][value=player]').checked = true;
  document.querySelector('input[name=mode][value=single]').checked = true;
  syncOpponent();
  $('dlg').hidden = false;
  $('roomName').focus();
}

// 选了「电脑」就锁定单打（双打选项不可选）
function syncOpponent() {
  const ai = document.querySelector('input[name=opponent]:checked').value === 'ai';
  const single = document.querySelector('input[name=mode][value=single]');
  const double = document.querySelector('input[name=mode][value=double]');
  if (ai) { single.checked = true; }
  double.disabled = ai;
  $('aiNote').hidden = !ai;
}
for (const r of document.querySelectorAll('input[name=opponent]')) {
  r.addEventListener('change', syncOpponent);
}

async function createRoom(e) {
  e.preventDefault();
  const name = $('roomName').value.trim();
  const mode = document.querySelector('input[name=mode]:checked').value;
  const opponent = document.querySelector('input[name=opponent]:checked').value;
  if (!name) return toast('请填写房间名');
  const r = await fetch(BASE + 'api/rooms', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, mode, opponent }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) return toast(data.detail || '建房失败');
  $('dlg').hidden = true;
  joinRoom(data.id);            // 建房后马上进入自己的房间（房主座位已经留好）
}

// ------------------------------------------------------------ 房间（等待开赛）

function renderRoom(state) {
  const room = state.room;
  $('roomTitle').textContent = room.name;
  $('roomMeta').textContent = room.ai
    ? `单打 · 人机对战（你对电脑）`
    : `${room.modeName} · 房主 ${room.host} · 先到先得，满员后房主开始`;
  const seats = $('seats');
  seats.replaceChildren();
  state.seats.forEach((s, i) => {
    const team = i < state.seats.length / 2 ? '队 A' : '队 B';
    if (s) {
      const tag = s.isAi ? '' : (s.userId === room.hostId ? '（房主）' : '') + (s.userId === S.me.id ? '（你）' : '');
      seats.append(el('div', { class: 'seat' }, [
        el('span', { text: `${team} · ${s.name}${tag}` }),
        el('span', { class: 'muted', text: `${i + 1} 号位` }),
      ]));
    } else {
      seats.append(el('div', { class: 'seat empty' }, [
        el('span', { text: `${team} · 空位` }),
        el('span', { text: `${i + 1} 号位` }),
      ]));
    }
  });
  const isHost = room.hostId === S.me.id;
  const full = state.seats.every(Boolean);
  $('startBtn').hidden = !isHost;
  $('startBtn').disabled = !full;
  $('roomHint').textContent = room.ai
    ? '电脑已就位，点「开始比赛」。你先发球。'
    : isHost
      ? (full ? '人已到齐，可以开始比赛了。' : '等待其他人加入…')
      : '等待房主开始比赛…';
}

// ------------------------------------------------------------ 三维场景（小人、球拍、击球动作、特效）

const DEPTH_X = { back: 10.6, mid: 7.0, front: 3.4 };   // 站位对应的距离（队 0 在 x<0 一侧）
const LANE_Z = { 1: -2.3, 2: 2.3 };                       // 一区、二区对应的左右位置
const ARC_HEIGHT = { low: 0.3, normal: 1.0, high: 3.4 };  // 球飞行的弧线高度
const TEAM_COLOR = [0xe4572e, 0x2e86de];                  // 队 A 橙红，队 B 蓝
const TEAM_SHIRT = [0xff8a5c, 0x6fb4ff];
const SKIN = 0xf1c79a;
const HAIR = [0x2b2118, 0x6b4a2b, 0x1a1a1a];
const DUST = 0xe6e0d0;

// 小工具：用 canvas 画纹理
function canvasTexture(w, h, draw, repeat) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  if (repeat) { tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(repeat[0], repeat[1]); }
  return tex;
}

const scene = new THREE.Scene();
scene.background = canvasTexture(4, 256, (g, w, h) => {
  const grd = g.createLinearGradient(0, 0, 0, h);
  grd.addColorStop(0, '#2f7fd8');
  grd.addColorStop(0.55, '#9ed3ff');
  grd.addColorStop(1, '#e9f7ff');
  g.fillStyle = grd; g.fillRect(0, 0, w, h);
});
scene.fog = new THREE.Fog(0xcfeaff, 70, 170);
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 300);
const renderer = new THREE.WebGLRenderer({ canvas: document.createElement('canvas'), antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
$('view').append(renderer.domElement);

scene.add(new THREE.HemisphereLight(0xe8f6ff, 0x2d4a2d, 0.85));
const sun = new THREE.DirectionalLight(0xfff6e0, 1.1);
sun.position.set(-8, 28, 12);
sun.castShadow = true;
sun.shadow.mapSize.set(1024, 1024);
Object.assign(sun.shadow.camera, { left: -18, right: 18, top: 12, bottom: -12, near: 1, far: 80 });
sun.shadow.bias = -0.0005;
scene.add(sun);
const fill = new THREE.DirectionalLight(0xffe2b8, 0.35);
fill.position.set(10, 12, -14);
scene.add(fill);

function mat(color, extra = {}) { return new THREE.MeshLambertMaterial({ color, ...extra }); }
function addBox(w, h, d, x, y, z, material, receive = false) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  m.position.set(x, y, z);
  m.castShadow = true;
  m.receiveShadow = receive;
  scene.add(m);
  return m;
}

// 草地：修剪过的条纹
const grass = new THREE.Mesh(
  new THREE.PlaneGeometry(300, 300),
  new THREE.MeshLambertMaterial({
    map: canvasTexture(256, 256, (g, w, h) => {
      g.fillStyle = '#4f9a48'; g.fillRect(0, 0, w, h);
      for (let x = 0; x < w; x += 32) { g.fillStyle = x % 64 ? 'rgba(255,255,255,0.05)' : 'rgba(0,40,0,0.07)'; g.fillRect(x, 0, 32, h); }
      for (let i = 0; i < 400; i++) { g.fillStyle = `rgba(20,60,20,${Math.random() * 0.2})`; g.fillRect(Math.random() * w, Math.random() * h, 2, 2); }
    }, [40, 40]),
  }),
);
grass.rotation.x = -Math.PI / 2;
grass.position.y = -0.05;
grass.receiveShadow = true;
scene.add(grass);

// 硬地：有渐变，看起来像真的场地
const court = new THREE.Mesh(
  new THREE.PlaneGeometry(23.77, 10.97),
  new THREE.MeshLambertMaterial({
    map: canvasTexture(512, 256, (g, w, h) => {
      const grd = g.createLinearGradient(0, 0, w, 0);
      grd.addColorStop(0, '#3a7fc4'); grd.addColorStop(0.5, '#2f6fb0'); grd.addColorStop(1, '#3a7fc4');
      g.fillStyle = grd; g.fillRect(0, 0, w, h);
      g.fillStyle = 'rgba(255,255,255,0.04)';
      for (let i = 0; i < 300; i++) g.fillRect(Math.random() * w, Math.random() * h, 1, 1);
    }),
  }),
);
court.rotation.x = -Math.PI / 2;
court.position.y = 0.01;
court.receiveShadow = true;
scene.add(court);

const WHITE = new THREE.MeshBasicMaterial({ color: 0xffffff });
const LT = 0.07;
addBox(LT, 0.01, 10.97 + LT, -11.885, 0.005, 0, WHITE);
addBox(LT, 0.01, 10.97 + LT, 11.885, 0.005, 0, WHITE);
addBox(23.77, 0.01, LT, 0, 0.005, -5.485, WHITE);
addBox(23.77, 0.01, LT, 0, 0.005, 5.485, WHITE);
addBox(23.77, 0.01, LT, 0, 0.005, -4.115, WHITE);
addBox(23.77, 0.01, LT, 0, 0.005, 4.115, WHITE);
addBox(LT, 0.01, 8.23, -6.4, 0.005, 0, WHITE);
addBox(LT, 0.01, 8.23, 6.4, 0.005, 0, WHITE);
addBox(12.8, 0.01, LT, 0, 0.005, 0, WHITE);
// 前中后场的分界线（淡色，方便看位置）
const zoneLine = new THREE.MeshBasicMaterial({ color: 0xffe066, transparent: true, opacity: 0.22 });
for (const x of [-DEPTH_X.mid, DEPTH_X.mid]) addBox(0.04, 0.012, 10.97, x, 0.006, 0, zoneLine);

// 看台：灰色台阶 + 观众（一排排小色块）
const stand = mat(0x7f8792);
for (const side of [-1, 1]) {
  addBox(4, 5, 60, side * 34, 2.5, 0, stand);
  addBox(60, 5, 4, 0, 2.5, side * 22, stand);
}
{
  const crowdColors = [0xff6b6b, 0xffd166, 0x6bcb77, 0x4d96ff, 0xffffff, 0xff9f1c, 0xb388ff];
  const N = 360;
  const im = new THREE.InstancedMesh(new THREE.BoxGeometry(0.45, 0.6, 0.45), mat(0xffffff), N);
  const m4 = new THREE.Matrix4();
  const col = new THREE.Color();
  for (let i = 0; i < N; i++) {
    const side = i % 2 ? 1 : -1;
    const onX = i % 4 < 2;                       // 一半在长边，一半在短边
    const row = Math.floor(i / 60) % 3;
    const t = Math.random() * 2 - 1;
    const x = onX ? side * (33.2 + row * 0.9) : t * 28;
    const z = onX ? t * 28 : side * (21.2 + row * 0.9);
    m4.makeTranslation(x, 5.45 + row * 0.8, z);
    im.setMatrixAt(i, m4);
    im.setColorAt(i, col.set(crowdColors[Math.floor(Math.random() * crowdColors.length)]));
  }
  im.instanceMatrix.needsUpdate = true;
  im.instanceColor.needsUpdate = true;
  scene.add(im);
}

// 球网：白色边带 + 网格纹理
const netTex = canvasTexture(64, 32, (g, w, h) => {
  g.clearRect(0, 0, w, h);
  g.strokeStyle = 'rgba(255,255,255,0.95)'; g.lineWidth = 2;
  for (let x = 0; x <= w; x += 8) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
  for (let y = 0; y <= h; y += 8) { g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
});
netTex.wrapS = netTex.wrapT = THREE.RepeatWrapping;
netTex.repeat.set(4, 1);
const netMesh = new THREE.Mesh(
  new THREE.PlaneGeometry(12.8, 0.914),
  new THREE.MeshBasicMaterial({ map: netTex, transparent: true, side: THREE.DoubleSide, alphaTest: 0.1 }),
);
netMesh.rotation.y = Math.PI / 2;
netMesh.position.set(0, 0.457, 0);
scene.add(netMesh);
addBox(0.05, 0.07, 12.8, 0, 0.914, 0, WHITE);
for (const z of [-6.4, 6.4]) {
  const post = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 1.07, 8), mat(0x222222));
  post.position.set(0, 0.535, z);
  scene.add(post);
}

// 球：稍微发光，拖尾和阴影跟着它
const ball = new THREE.Mesh(new THREE.SphereGeometry(0.16, 16, 12), mat(0xd4ff3a, { emissive: 0x3d5a00 }));
ball.castShadow = true;
scene.add(ball);
const ballShadow = new THREE.Mesh(
  new THREE.CircleGeometry(0.28, 20),
  new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.3, depthWrite: false }),
);
ballShadow.rotation.x = -Math.PI / 2;
scene.add(ballShadow);
const TRAIL_N = 14;
const trailGeo = new THREE.BufferGeometry();
trailGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(TRAIL_N * 3), 3));
const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0xf4ffb0, transparent: true, opacity: 0.55 }));
trail.frustumCulled = false;
scene.add(trail);
const trailPts = [];

// 粒子特效：火花、尘土、纸屑（一个 Points 对象，统一更新）
const softDot = canvasTexture(32, 32, (g, w, h) => {
  const grd = g.createRadialGradient(16, 16, 0, 16, 16, 16);
  grd.addColorStop(0, 'rgba(255,255,255,1)'); grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd; g.fillRect(0, 0, w, h);
});
const MAX_P = 420;
const pPos = new Float32Array(MAX_P * 3);
const pCol = new Float32Array(MAX_P * 3);
const pGeo = new THREE.BufferGeometry();
pGeo.setAttribute('position', new THREE.BufferAttribute(pPos, 3));
pGeo.setAttribute('color', new THREE.BufferAttribute(pCol, 3));
const particles = new THREE.Points(pGeo, new THREE.PointsMaterial({
  size: 0.28, map: softDot, vertexColors: true, transparent: true, depthWrite: false, alphaTest: 0.01,
}));
particles.frustumCulled = false;
scene.add(particles);
const parts = [];   // {x,y,z,vx,vy,vz,life,max,r,g,b,grav}
function burst(pos, colorHex, count, speed = 3, up = 2, grav = 6) {
  const c = new THREE.Color(colorHex);
  for (let i = 0; i < count; i++) {
    if (parts.length >= MAX_P) parts.shift();
    const a = Math.random() * Math.PI * 2;
    const s = speed * (0.4 + Math.random() * 0.8);
    parts.push({
      x: pos.x, y: pos.y, z: pos.z,
      vx: Math.cos(a) * s, vy: up * (0.5 + Math.random()), vz: Math.sin(a) * s,
      life: 0.7 + Math.random() * 0.5, max: 1.2, r: c.r, g: c.g, b: c.b, grav,
    });
  }
}
function updateParticles(dt) {
  for (let i = parts.length - 1; i >= 0; i--) {
    const p = parts[i];
    p.life -= dt;
    if (p.life <= 0) { parts.splice(i, 1); continue; }
    p.vy -= p.grav * dt;
    p.x += p.vx * dt; p.y += p.vy * dt; p.z += p.vz * dt;
    if (p.y < 0.02) { p.y = 0.02; p.vy *= -0.3; p.vx *= 0.6; p.vz *= 0.6; }
  }
  for (let i = 0; i < MAX_P; i++) {
    const p = parts[i];
    if (p) {
      const f = Math.max(0, p.life / p.max);
      pPos[i * 3] = p.x; pPos[i * 3 + 1] = p.y; pPos[i * 3 + 2] = p.z;
      pCol[i * 3] = p.r * f; pCol[i * 3 + 1] = p.g * f; pCol[i * 3 + 2] = p.b * f;
    } else {
      pPos[i * 3 + 1] = -100; pCol[i * 3] = pCol[i * 3 + 1] = pCol[i * 3 + 2] = 0;
    }
  }
  pGeo.attributes.position.needsUpdate = true;
  pGeo.attributes.color.needsUpdate = true;
}

// 球拍的线：一张半透明的网格纹理
const stringTex = canvasTexture(64, 64, (g, w, h) => {
  g.clearRect(0, 0, w, h);
  g.strokeStyle = 'rgba(255,255,255,0.8)'; g.lineWidth = 2;
  for (let x = 0; x <= w; x += 8) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
  for (let y = 0; y <= h; y += 8) { g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
});

// 小人：有头发、身体、两条腿、两条手臂、手和球拍
function nameSprite(text) {
  const c = document.createElement('canvas');
  c.width = 256; c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = 'rgba(0,0,0,0.55)'; g.fillRect(0, 0, 256, 64);
  g.fillStyle = '#fff'; g.font = 'bold 30px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text.slice(0, 8), 128, 34);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false }));
  sp.scale.set(2.2, 0.55, 1);
  sp.position.y = 2.25;
  return sp;
}
// 对方头顶的气泡：「如果我……，你该如何应对？」
function bubbleSprite(text) {
  const c = document.createElement('canvas');
  c.width = 640; c.height = 150;
  const g = c.getContext('2d');
  g.fillStyle = 'rgba(255,255,255,0.95)';
  g.beginPath(); g.roundRect(6, 6, 628, 110, 18); g.fill();
  g.beginPath(); g.moveTo(300, 116); g.lineTo(320, 146); g.lineTo(340, 116); g.fill();
  g.fillStyle = '#1d2733'; g.font = 'bold 40px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text, 320, 61);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false }));
  sp.scale.set(7.0, 1.64, 1);
  sp.position.y = 3.2;
  sp.userData.text = text;
  return sp;
}

function limb(radius, length, color, castShadow = true) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius * 0.9, length, 10), mat(color));
  m.position.y = -length / 2;
  m.castShadow = castShadow;
  return m;
}

const figures = new Map();   // 座位号 -> 小人的各个部件和动画状态

function makeFigure(seat) {
  const root = new THREE.Group();          // 整个人：位置在这里，朝向网
  const team = seat.team;
  // 腿
  const legs = [];
  for (const side of [-1, 1]) {
    const hip = new THREE.Group();
    hip.position.set(0, 0.95, side * 0.15);
    const thigh = limb(0.12, 0.5, 0xf2f2f2);
    const shin = new THREE.Group(); shin.position.y = -0.5;
    shin.add(limb(0.1, 0.45, SKIN));
    const shoe = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.14, 0.2), mat(0x222222));
    shoe.position.set(0.06, -0.5, 0);
    shoe.castShadow = true;
    shin.add(shoe);
    hip.add(thigh, shin);
    root.add(hip);
    legs.push({ hip, shin });
  }
  // 躯干（可以左右转）
  const torso = new THREE.Group();
  torso.position.y = 0.95;
  const shirt = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.34, 0.85, 12), mat(TEAM_SHIRT[team]));
  shirt.position.y = 0.45;
  shirt.castShadow = true;
  const shorts = new THREE.Mesh(new THREE.CylinderGeometry(0.31, 0.27, 0.3, 12), mat(0xf2f2f2));
  shorts.position.y = 0.0;
  shorts.castShadow = true;
  torso.add(shirt, shorts);
  // 头：肤色 + 头发
  const head = new THREE.Group();
  head.position.y = 1.36;
  const skull = new THREE.Mesh(new THREE.SphereGeometry(0.2, 14, 12), mat(SKIN));
  skull.castShadow = true;
  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.21, 14, 10, 0, Math.PI * 2, 0, Math.PI * 0.55), mat(HAIR[seat.index % HAIR.length]));
  hair.position.y = 0.03;
  hair.castShadow = true;
  head.add(skull, hair);
  torso.add(head);
  const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.2, 8), mat(SKIN));
  neck.position.y = 1.13;
  torso.add(neck);
  // 手臂：肩膀 → 上臂 → 前臂 → 手（右手握着球拍）
  function arm(side) {
    const shoulder = new THREE.Group();
    shoulder.position.set(0, 0.8, side * 0.36);
    const upper = limb(0.085, 0.45, TEAM_SHIRT[team]);
    const elbow = new THREE.Group();
    elbow.position.y = -0.45;
    elbow.add(limb(0.075, 0.4, SKIN));
    const hand = new THREE.Mesh(new THREE.SphereGeometry(0.1, 10, 8), mat(SKIN));
    hand.position.y = -0.45;
    hand.castShadow = true;
    elbow.add(hand);
    shoulder.add(upper, elbow);
    torso.add(shoulder);
    return { shoulder, elbow, hand };
  }
  const leftArm = arm(-1);
  const rightArm = arm(1);
  // 球拍：握在右手里（手柄 + 椭圆拍框 + 拍线）
  const racket = new THREE.Group();
  racket.position.set(0, -0.5, 0);
  const handle = new THREE.Mesh(new THREE.CylinderGeometry(0.028, 0.028, 0.3, 8), mat(0x1d1d1d));
  handle.position.y = -0.15;
  const frameMesh = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.018, 8, 24), mat(0x2a2a2a));
  frameMesh.scale.set(1, 1.3, 1);
  frameMesh.position.y = -0.46;
  frameMesh.castShadow = true;
  const strings = new THREE.Mesh(
    new THREE.CircleGeometry(0.16, 24),
    new THREE.MeshBasicMaterial({ map: stringTex, transparent: true, opacity: 0.45, side: THREE.DoubleSide, depthWrite: false }),
  );
  strings.scale.set(1, 1.3, 1);
  strings.position.y = -0.46;
  racket.add(handle, frameMesh, strings);
  racket.rotation.x = 0;
  rightArm.elbow.add(racket);
  // 球拍的方向：拍面朝前
  racket.rotation.z = 0;
  racket.rotation.y = Math.PI / 2;
  root.add(torso);
  const nameTag = nameSprite(seat.name);
  root.add(nameTag);
  scene.add(root);
  // 手的世界位置（击球时用）
  const handTip = new THREE.Object3D();
  handTip.position.set(0, -0.48, 0);
  rightArm.elbow.add(handTip);
  return {
    root, torso, legs, leftArm, rightArm, racket, handTip,
    x: 0, z: 0, tx: 0, tz: 0, team, userId: seat.userId,
    anim: null, bubble: null, runPhase: 0, moving: false, idle: Math.random() * 6,
  };
}

// 站位（前中后场 × 一区二区）换算成世界坐标
function cellX(team, depth) { return (team === 0 ? -1 : 1) * DEPTH_X[depth]; }
function cellZ(lane) { return LANE_Z[lane]; }

// 挥拍动作：每种打法的关键姿势（zAngle 手臂前后，elbow 手肘，yaw 身体转动，lateral 手臂左右）
const POSES = {
  fore: [
    { t: 0.00, sh: [-1.2, 0.4], el: -1.2, yaw: -0.7, lx: 0.4 },
    { t: 0.45, sh: [0.9, 0.0], el: -0.3, yaw: 0.5, lx: 0.0 },
    { t: 1.00, sh: [1.5, -0.3], el: -0.2, yaw: 0.9, lx: -0.3 },
  ],
  lob: [
    { t: 0.00, sh: [-0.9, 0.3], el: -1.4, yaw: -0.4, lx: 0.3 },
    { t: 0.45, sh: [1.8, 0.0], el: -0.4, yaw: 0.3, lx: 0.0 },
    { t: 1.00, sh: [2.7, -0.2], el: -0.2, yaw: 0.6, lx: -0.2 },
  ],
  smash: [
    { t: 0.00, sh: [2.9, 0.2], el: -0.9, yaw: 0.2, lx: 0.2 },
    { t: 0.45, sh: [1.1, 0.0], el: -0.2, yaw: 0.6, lx: 0.0 },
    { t: 1.00, sh: [0.4, -0.2], el: -0.1, yaw: 0.8, lx: -0.2 },
  ],
  volley: [
    { t: 0.00, sh: [0.6, 0.3], el: -1.3, yaw: -0.2, lx: 0.3 },
    { t: 0.40, sh: [1.1, 0.0], el: -0.6, yaw: 0.2, lx: 0.0 },
    { t: 1.00, sh: [1.2, -0.1], el: -0.5, yaw: 0.3, lx: -0.1 },
  ],
  drop: [
    { t: 0.00, sh: [0.1, 0.3], el: -1.7, yaw: -0.2, lx: 0.3 },
    { t: 0.45, sh: [0.6, 0.0], el: -1.0, yaw: 0.1, lx: 0.0 },
    { t: 1.00, sh: [0.9, -0.1], el: -0.8, yaw: 0.2, lx: -0.1 },
  ],
  slice: [
    { t: 0.00, sh: [1.6, 0.4], el: -0.8, yaw: -0.5, lx: 0.4 },
    { t: 0.45, sh: [-0.2, 0.0], el: -0.6, yaw: 0.5, lx: 0.0 },
    { t: 1.00, sh: [-0.9, -0.3], el: -0.5, yaw: 0.8, lx: -0.2 },
  ],
  serve: [
    { t: 0.00, sh: [2.8, 0.3], el: -1.5, yaw: -0.3, lx: 0.3 },
    { t: 0.50, sh: [2.3, 0.0], el: -0.2, yaw: 0.4, lx: 0.0 },
    { t: 1.00, sh: [0.8, -0.2], el: -0.2, yaw: 0.7, lx: -0.2 },
  ],
};
POSES.back = POSES.fore;
const IDLE_POSE = { sh: [0.5, 0.1], el: -0.9, yaw: 0, lx: 0.2 };
function poseAt(kind, u) {
  const keys = POSES[kind] || POSES.fore;
  let a = keys[0], b = keys[keys.length - 1];
  for (let i = 0; i < keys.length - 1; i++) {
    if (u >= keys[i].t && u <= keys[i + 1].t) { a = keys[i]; b = keys[i + 1]; break; }
  }
  const span = b.t - a.t || 1;
  const k = (u - a.t) / span;
  const e = k * k * (3 - 2 * k);          // 平滑一点
  const mix = (p, q) => p + (q - p) * e;
  return { sh: [mix(a.sh[0], b.sh[0]), mix(a.sh[1], b.sh[1])], el: mix(a.el, b.el), yaw: mix(a.yaw, b.yaw), lx: mix(a.lx, b.lx) };
}

// 把服务器的站位和气泡同步到场景里（小人会平滑地走到新位置）
function applyState(state) {
  for (const s of state.seats) {
    if (!s) continue;
    let f = figures.get(s.index);
    if (!f || f.userId !== s.userId) {
      if (f) scene.remove(f.root);
      f = makeFigure(s);
      figures.set(s.index, f);
      f.x = f.tx = cellX(s.team, s.depth);
      f.z = f.tz = cellZ(s.lane);
      f.root.rotation.y = s.team === 0 ? 0 : Math.PI;   // 面向球网
    }
    f.tx = cellX(s.team, s.depth);
    f.tz = cellZ(s.lane);
  }
  for (const [idx, f] of figures) {
    if (!state.seats[idx]) { scene.remove(f.root); figures.delete(idx); }
  }
  // 气泡：只在对方击球之后、他的那一拍结束之前显示
  for (const f of figures.values()) {
    const seatIdx = [...figures.entries()].find(([, v]) => v === f)[0];
    const b = state.bubble && state.bubble.seat === seatIdx ? state.bubble.text : null;
    if (b && f.bubble?.userData.text !== b) {
      if (f.bubble) f.root.remove(f.bubble);
      f.bubble = bubbleSprite(b);
      f.root.add(f.bubble);
    } else if (!b && f.bubble) {
      f.root.remove(f.bubble);
      f.bubble = null;
    }
  }
  for (const ev of state.events) {
    if (ev.type === 'shot') startShot(ev);
    if (ev.type === 'point') pointEffects(ev);
  }
}

// 击球动画：挥拍和球的飞行，都和选择的打法、落点一致
let shotBall = null;   // {delay, t, dur, from, to, arc, result, fail, toZone, figure}
let landing = null;    // 球最后停的位置（等对方接球时悬在这里）
let shake = 0;         // 镜头震动的强度

function startShot(ev) {
  const f = figures.get(ev.seat);
  if (!f) return;
  f.anim = { t: 0, dur: 0.95, kind: ev.anim || 'fore' };
  const from = new THREE.Vector3(f.x, 1.2, f.z);
  let to;
  if (ev.toZone === 'court') {
    to = new THREE.Vector3(cellX(ev.toTeam, ev.toDepth), 0.15, cellZ(ev.toLane));
  } else if (ev.toZone === 'far') {
    to = new THREE.Vector3((ev.toTeam === 0 ? -1 : 1) * 16, 0.15, f.z * 1.3);
  } else {
    to = new THREE.Vector3(0, 0.5, f.z);            // 下网
  }
  shotBall = {
    delay: 0.42, t: 0, dur: ev.flight || 1.0, from, to, fromVec: from.clone(),
    arc: ARC_HEIGHT[ev.arc] ?? ARC_HEIGHT.normal, result: ev.result, fail: ev.fail, toZone: ev.toZone,
    figure: f, kind: ev.anim, toTeam: ev.toTeam, landed: false,
  };
  trailPts.length = 0;
}

// 得分：纸屑 + 镜头震动；失误下网：白色碎片
function pointEffects(ev) {
  const colorHex = ev.winner === 0 ? TEAM_COLOR[0] : TEAM_COLOR[1];
  for (let i = 0; i < 3; i++) {
    burst(new THREE.Vector3((Math.random() - 0.5) * 10, 3 + Math.random() * 2, (Math.random() - 0.5) * 6), colorHex, 40, 4, 3, 4);
  }
  burst(new THREE.Vector3(0, 0.6, 0), 0xffffff, 40, 3, 2, 5);
  shake = Math.max(shake, 0.35);
}

const camLook = new THREE.Vector3(0, 0.6, 0);
const camPos = new THREE.Vector3();
const camBase = new THREE.Vector3();
const tmpV = new THREE.Vector3();
let lastFrame = performance.now();
let clock = 0;

// 小人的动作：走路、站立、挥拍（挥拍时身体跟着转）
function animateFigure(f, dt) {
  const dx = f.tx - f.x, dz = f.tz - f.z;
  f.x += dx * (1 - Math.pow(0.001, dt));
  f.z += dz * (1 - Math.pow(0.001, dt));
  f.root.position.set(f.x, 0, f.z);
  const speed = Math.hypot(dx, dz);
  f.moving = speed > 0.05;
  f.runPhase += dt * (f.moving ? 9 : 0);
  f.idle += dt;

  // 腿：走路时交替摆动，站着时不动
  const swing = f.moving ? Math.sin(f.runPhase) * 0.6 : 0;
  f.legs[0].hip.rotation.z = swing;
  f.legs[1].hip.rotation.z = -swing;
  f.legs[0].shin.rotation.z = f.moving ? Math.max(0, -Math.sin(f.runPhase)) * 0.6 : 0;
  f.legs[1].shin.rotation.z = f.moving ? Math.max(0, Math.sin(f.runPhase)) * 0.6 : 0;
  f.torso.position.y = 0.95 + (f.moving ? Math.abs(Math.sin(f.runPhase)) * 0.04 : Math.sin(f.idle * 2) * 0.01);

  // 手臂：默认姿势（准备接球）
  let pose = IDLE_POSE;
  if (f.anim) {
    f.anim.t += dt;
    const u = Math.min(1, f.anim.t / f.anim.dur);
    pose = poseAt(f.anim.kind, u);
    if (u >= 1) f.anim = null;
  }
  f.torso.rotation.y = pose.yaw;
  f.rightArm.shoulder.rotation.set(0, 0, pose.sh[0]);
  f.rightArm.shoulder.rotation.x = pose.sh[1];
  f.rightArm.elbow.rotation.z = pose.el;
  f.leftArm.shoulder.rotation.set(0, 0, 0.25 + Math.sin(f.idle * 3) * 0.03);
  f.leftArm.elbow.rotation.z = -0.9;
  if (f.anim && f.anim.kind === 'serve' && f.anim.t < 0.5) {
    // 发球抛球：左手举起来
    f.leftArm.shoulder.rotation.set(0, 0, 2.6);
  }
  f.rightArm.shoulder.rotation.y = pose.lx;
  // 球拍跟着手转，拍面朝前
  f.racket.rotation.set(0, Math.PI / 2, 0);
}

function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - lastFrame) / 1000);
  lastFrame = now;
  clock += dt;
  const state = S.state;
  if (!state || S.view !== 'game') return;

  for (const f of figures.values()) animateFigure(f, dt);

  // 球：先停在击球的球拍上，挥拍到位后飞出去；飞行中留拖尾；飞完悬在落点
  if (shotBall) {
    const sb = shotBall;
    if (sb.delay > 0) {
      sb.delay -= dt;
      sb.figure.handTip.getWorldPosition(tmpV);
      ball.position.copy(tmpV);
      ball.visible = true;
      if (sb.delay <= 0) {
        sb.from = tmpV.clone();
        burst(tmpV, sb.result === 'winner' ? 0xffd54a : 0xfff3c4, 18, 2.2, 1.5, 6);   // 击球的火花
      }
    } else {
      sb.t += dt;
      const u = Math.min(1, sb.t / sb.dur);
      ball.position.lerpVectors(sb.from, sb.to, u);
      ball.position.y += Math.sin(Math.PI * u) * sb.arc;
      ball.visible = true;
      if (u >= 1 && !sb.landed) {
        sb.landed = true;
        if (sb.toZone === 'court') {
          burst(sb.to, DUST, 14, 1.6, 1.0, 5);                   // 落地的尘土
        } else if (sb.toZone === 'net') {
          burst(sb.to, 0xffffff, 20, 2.0, 1.5, 6);
        }
      }
      trailPts.push(ball.position.clone());
      if (trailPts.length > TRAIL_N) trailPts.shift();
      if (u >= 1 && sb.landed && sb.t > sb.dur + 0.6) shotBall = null;
    }
  } else if (landing && (state.phase === 'menu' || state.phase === 'swing' || state.phase === 'shot')) {
    ball.position.copy(landing);
    ball.position.y = 0.15 + Math.sin(clock * 6) * 0.02;
    ball.visible = true;
    trailPts.length = 0;
  } else if (state.phase === 'serve_menu') {
    const server = figures.get(state.serveSeat);
    if (server) {
      ball.position.set(server.x, 1.4, server.z);
      ball.visible = true;
    }
    trailPts.length = 0;
  } else {
    ball.visible = false;
    trailPts.length = 0;
  }
  // 拖尾
  const tp = trail.geometry.attributes.position;
  for (let i = 0; i < TRAIL_N; i++) {
    const p = trailPts[Math.max(0, trailPts.length - TRAIL_N) + i] || ball.position;
    tp.setXYZ(i, p.x, p.y, p.z);
  }
  tp.needsUpdate = true;
  trail.visible = trailPts.length > 1;
  trail.geometry.setDrawRange(0, trailPts.length);

  ballShadow.position.set(ball.position.x, 0.005, ball.position.z);
  const hgt = Math.max(0.35, 1 - ball.position.y * 0.1);
  ballShadow.scale.set(hgt, hgt, hgt);
  ballShadow.visible = ball.visible;

  updateParticles(dt);

  // 摄像机：抬高，站在自己这一边的后面；得分时轻微震动
  const side = myTeam() === 0 ? -1 : 1;
  camBase.set(side * 19.5, 8.6, 0);
  camPos.copy(camBase);
  camPos.y += Math.sin(clock * 0.6) * 0.08;
  if (shake > 0) {
    shake = Math.max(0, shake - dt);
    camPos.x += (Math.random() - 0.5) * shake * 0.8;
    camPos.y += (Math.random() - 0.5) * shake * 0.8;
  }
  camera.position.lerp(camPos, 0.2);
  camLook.set(0, 0.6, 0);
  camera.lookAt(camLook);

  renderer.render(scene, camera);
}
requestAnimationFrame(frame);

function resizeRenderer() {
  const w = $('view').clientWidth || window.innerWidth;
  const h = $('view').clientHeight || window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resizeRenderer);

// ------------------------------------------------------------ 比赛界面（三个选项）

function renderScore(state) {
  const sc = state.score;
  const me = myTeam();
  const op = 1 - me;
  const sets = sc.sets.map((s) => `${s[me]}-${s[op]}`).join('  ');
  const head = `<b>${sc.setsWon[me]} : ${sc.setsWon[op]}</b> 盘`;
  const games = `局 ${sc.games[me]}-${sc.games[op]}`;
  const points = sc.tiebreak
    ? `抢七 <b>${sc.labels[me]} : ${sc.labels[op]}</b>`
    : `<b>${sc.labels[me]} : ${sc.labels[op]}</b>${sc.deuce ? '（平分）' : ''}`;
  $('scoreBoard').innerHTML = `我方 ${head} · ${games} · ${points}${sets ? `<br><span style="opacity:.75">已完成：${sets}</span>` : ''}`;
}

// 当前这一次选择（防止同一次重复点击）
let choiceKey = null;

function renderMenu(state) {
  const box = $('menu');
  const mine = mySeat(state);
  const menu = state.menu;
  if (!menu || state.status !== 'playing') {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const myTurn = mine && state.hitter === mine.index;
  const serve = menu.attack === 'serve';
  const bubbleText = state.bubble ? state.bubble.text : '';
  if (!myTurn) {
    $('menuTitle').textContent = serve ? '对方发球中…' : '对方在选择…';
    $('menuSub').textContent = bubbleText;
    $('menuCards').replaceChildren();
    $('menuTimer').textContent = '';
    return;
  }
  $('menuTitle').textContent = serve ? '轮到你发球，选一种发球和落点' : '轮到你，选一种应对';
  $('menuSub').textContent = serve ? '发球要落在对角的发球区' : bubbleText;
  $('menuTimer').textContent = `${Math.ceil(menu.deadline)} 秒内选择`;
  const key = `${state.phase}-${state.hitter}-${menu.options.map((o) => o.id).join(',')}`;
  if (key === choiceKey) return;   // 已经选过了，等服务器的动画
  const cards = menu.options.map((o, i) => el('button', {
    class: 'choice',
    onclick: () => choose(o.id, key),
  }, [
    el('span', { class: 'num', text: String(i + 1) }),
    el('span', { class: 'cname', text: o.name }),
    el('span', { class: 'cdesc', text: o.desc }),
  ]));
  $('menuCards').replaceChildren(...cards);
}

function choose(option, key) {
  if (choiceKey === key) return;
  choiceKey = key;
  send({ type: 'choose', option });
  for (const b of document.querySelectorAll('#menuCards button')) b.disabled = true;
}

function renderGame(state) {
  renderScore(state);
  $('hudMsg').textContent = state.message || '';
  renderMenu(state);

  if (state.status === 'finished') {
    const sc = state.score;
    const won = sc.winner === myTeam();
    $('overTitle').textContent = state.phase === 'match_over' && sc.winner !== null
      ? (won ? '🏆 你们赢了！' : '😅 这一场输了')
      : '比赛作废';
    $('overText').textContent = `${sc.setsWon[0]} : ${sc.setsWon[1]}（队 A : 队 B）· ${state.message || ''}`;
    const isHost = state.room.hostId === S.me.id;
    $('againBtn').hidden = !isHost;
    $('over').hidden = false;
  } else {
    $('over').hidden = true;
  }
}

// 击球结果的小字（显示在计分板下面）
function showShotLog(ev) {
  const seat = S.state && S.state.seats[ev.seat];
  const who = seat ? (seat.userId === S.me.id ? '你' : seat.name) : '';
  const res = { ok: '', winner: '（直接得分）', fail: ev.fail === 'net' ? '（下网）' : ev.fail === 'out' ? '（出界）' : '' }[ev.result] || '';
  $('shotLog').textContent = `${who}：${ev.name}${res}`;
}

// ------------------------------------------------------------ 键盘与按钮

window.addEventListener('keydown', (e) => {
  if (S.view !== 'game' || e.repeat) return;
  if (e.target && e.target.tagName === 'INPUT') return;
  const n = Number(e.key);
  if (n >= 1 && n <= 3) {
    const btns = document.querySelectorAll('#menuCards button:not([disabled])');
    if (btns[n - 1]) btns[n - 1].click();
  }
});

$('exitBtn').addEventListener('click', leaveRoom);
$('overLeaveBtn').addEventListener('click', leaveRoom);
$('againBtn').addEventListener('click', () => send({ type: 'restart' }));
$('startBtn').addEventListener('click', () => send({ type: 'start' }));
$('leaveBtn').addEventListener('click', leaveRoom);
$('createBtn').addEventListener('click', openCreate);
$('dlgCancel').addEventListener('click', () => { $('dlg').hidden = true; });
$('createForm').addEventListener('submit', createRoom);

// ------------------------------------------------------------ 连接与消息

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}${BASE}ws`);
  S.ws = ws;
  ws.onopen = () => $('conn').classList.add('on');
  ws.onclose = () => {
    $('conn').classList.remove('on');
    toast('和服务器断开了，请刷新页面');
  };
  ws.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }
    onMessage(m);
  };
}

function onMessage(m) {
  switch (m.type) {
    case 'auth':
      return goLogin();
    case 'hello':
      S.me = m.me;
      $('who').textContent = S.me.name;
      return;
    case 'lobby':
      S.rooms = m.rooms;
      if (S.view === 'lobby') renderLobby();
      return;
    case 'state': {
      S.state = m;
      S.room = m.room;
      applyState(m);
      for (const ev of m.events) {
        if (ev.type === 'shot') { showShotLog(ev); choiceKey = null; }   // 新的一次击球：选项要重新给
      }
      if (m.status === 'waiting') {
        if (S.view !== 'room') showView('room');
        renderRoom(m);
      } else {
        if (S.view !== 'game') { showView('game'); }
        renderGame(m);
      }
      return;
    }
    case 'closed':
      toast(m.text);
      S.state = null;
      S.room = null;
      $('over').hidden = true;
      showView('lobby');
      renderLobby();
      return;
    case 'error':
      toast(m.text);
      return;
  }
}

async function boot() {
  const r = await fetch('/api/auth/me');
  if (r.status === 401) return goLogin();
  if (!r.ok) { toast('服务器暂时无法访问，请稍后刷新'); return; }
  const account = await r.json();
  S.isGuest = !!account.isGuest;
  $('guestNote').hidden = !S.isGuest;
  $('createBtn').disabled = S.isGuest;
  $('createBtn').title = S.isGuest ? '注册账号后才能建房' : '';
  showView('lobby');
  connect();
}
boot();
