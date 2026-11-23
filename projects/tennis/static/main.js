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
  stroke: 'flat',
  stick: { f: 0, r: 0 },
  sent: { f: 0, r: 0 },
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
  $('dlg').hidden = false;
  $('roomName').focus();
}

async function createRoom(e) {
  e.preventDefault();
  const name = $('roomName').value.trim();
  const mode = document.querySelector('input[name=mode]:checked').value;
  if (!name) return toast('请填写房间名');
  const r = await fetch(BASE + 'api/rooms', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, mode }),
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
  $('roomMeta').textContent = `${room.modeName} · 房主 ${room.host} · 先到先得，满员后房主开始`;
  const seats = $('seats');
  seats.replaceChildren();
  state.seats.forEach((s, i) => {
    const team = i < state.seats.length / 2 ? '队 A' : '队 B';
    if (s) {
      seats.append(el('div', { class: 'seat' }, [
        el('span', { text: `${team} · ${s.name}${s.userId === room.hostId ? '（房主）' : ''}${s.userId === S.me.id ? '（你）' : ''}` }),
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
  $('roomHint').textContent = isHost
    ? (full ? '人已到齐，可以开始比赛了。' : '等待其他人加入…')
    : '等待房主开始比赛…';
}

// ------------------------------------------------------------ 三维场景

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x9fd6ff);
scene.fog = new THREE.Fog(0x9fd6ff, 70, 220);
const camera = new THREE.PerspectiveCamera(72, 1, 0.05, 400);
const renderer = new THREE.WebGLRenderer({ canvas: document.createElement('canvas'), antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
$('view').append(renderer.domElement);

scene.add(new THREE.HemisphereLight(0xffffff, 0x3a5a3a, 0.9));
const sun = new THREE.DirectionalLight(0xffffff, 0.7);
sun.position.set(10, 30, 6);
scene.add(sun);

function mat(color, extra = {}) { return new THREE.MeshLambertMaterial({ color, ...extra }); }
function addBox(w, h, d, x, y, z, material) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  m.position.set(x, y, z);
  scene.add(m);
  return m;
}

// 场地：草地外场 + 蓝色硬地 + 白线
const grass = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), mat(0x4f8f4a));
grass.rotation.x = -Math.PI / 2;
scene.add(grass);
const court = new THREE.Mesh(new THREE.PlaneGeometry(23.77, 10.97), mat(0x2f6fb0));
court.rotation.x = -Math.PI / 2;
court.position.y = 0.002;
scene.add(court);
const WHITE = new THREE.MeshBasicMaterial({ color: 0xffffff });
const LINE_T = 0.06;
addBox(LINE_T, 0.01, 10.97 + LINE_T, -11.885, 0.005, 0, WHITE);          // 底线
addBox(LINE_T, 0.01, 10.97 + LINE_T, 11.885, 0.005, 0, WHITE);
addBox(23.77, 0.01, LINE_T, 0, 0.005, -5.485, WHITE);                    // 双打边线
addBox(23.77, 0.01, LINE_T, 0, 0.005, 5.485, WHITE);
addBox(23.77, 0.01, LINE_T, 0, 0.005, -4.115, WHITE);                    // 单打边线
addBox(23.77, 0.01, LINE_T, 0, 0.005, 4.115, WHITE);
addBox(LINE_T, 0.01, 8.23, -6.4, 0.005, 0, WHITE);                       // 发球线
addBox(LINE_T, 0.01, 8.23, 6.4, 0.005, 0, WHITE);
addBox(12.8, 0.01, LINE_T, 0, 0.005, 0, WHITE);                          // 中线
// 看台：让远处有纵深感
const stand = mat(0x8a8f99);
for (const side of [-1, 1]) {
  addBox(4, 5, 60, side * 40, 2.5, 0, stand);
  addBox(60, 5, 4, 0, 2.5, side * 22, stand);
}

// 球网
const netCanvas = document.createElement('canvas');
netCanvas.width = 64; netCanvas.height = 32;
{
  const g = netCanvas.getContext('2d');
  g.fillStyle = 'rgba(255,255,255,0.0)'; g.fillRect(0, 0, 64, 32);
  g.strokeStyle = 'rgba(255,255,255,0.9)'; g.lineWidth = 2;
  for (let x = 0; x <= 64; x += 8) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, 32); g.stroke(); }
  for (let y = 0; y <= 32; y += 8) { g.beginPath(); g.moveTo(0, y); g.lineTo(64, y); g.stroke(); }
}
const netTex = new THREE.CanvasTexture(netCanvas);
netTex.wrapS = netTex.wrapT = THREE.RepeatWrapping;
netTex.repeat.set(4, 1);
const netMesh = new THREE.Mesh(
  new THREE.PlaneGeometry(12.8, 0.914),
  new THREE.MeshBasicMaterial({ map: netTex, transparent: true, side: THREE.DoubleSide, opacity: 0.85 }),
);
netMesh.rotation.y = Math.PI / 2;
netMesh.position.set(0, 0.457, 0);
scene.add(netMesh);
addBox(0.03, 0.05, 12.8, 0, 0.914, 0, WHITE);                           // 网顶白带
for (const z of [-6.4, 6.4]) {
  const post = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 1.07, 8), mat(0x222222));
  post.position.set(0, 0.535, z);
  scene.add(post);
}

// 球
const ball = new THREE.Mesh(new THREE.SphereGeometry(0.0335, 14, 10), mat(0xd4ff3a, { emissive: 0x223300 }));
scene.add(ball);
const ballShadow = new THREE.Mesh(
  new THREE.CircleGeometry(0.22, 18),
  new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35, depthWrite: false }),
);
ballShadow.rotation.x = -Math.PI / 2;
scene.add(ballShadow);

// 人物（对手可见，自己是第一人称看不见身体）
function nameSprite(text) {
  const c = document.createElement('canvas');
  c.width = 256; c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = 'rgba(0,0,0,0.55)'; g.fillRect(0, 0, 256, 64);
  g.fillStyle = '#fff'; g.font = 'bold 30px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text.slice(0, 8), 128, 34);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false }));
  sp.scale.set(1.6, 0.4, 1);
  sp.position.y = 2.1;
  return sp;
}
const TEAM_COLOR = [0xe4572e, 0x2e86de];
const players = new Map();   // seat index -> {group, target:{x,z}, name, userId}

function makePlayer(seat) {
  const group = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.28, 1.35, 10), mat(TEAM_COLOR[seat.team]));
  body.position.y = 0.8;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.16, 12, 10), mat(0xf2c9a0));
  head.position.y = 1.65;
  group.add(body, head, nameSprite(seat.name));
  scene.add(group);
  return { group, name: seat.name, userId: seat.userId, x: seat.x, z: seat.z, tx: seat.x, tz: seat.z };
}

// 本地的球拍：挂在摄像机上，右下角
const racket = new THREE.Group();
{
  const head = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.013, 8, 26), mat(0x20262e));
  head.scale.set(1, 1.3, 1);
  const face = new THREE.Mesh(new THREE.CircleGeometry(0.17, 24), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.12, side: THREE.DoubleSide }));
  face.scale.set(1, 1.3, 1);
  const handle = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.26, 0.02), mat(0x111111));
  handle.position.y = -0.3;
  racket.add(head, face, handle);
  racket.position.set(0.3, -0.36, -0.55);
  racket.rotation.set(0.25, 0.2, -0.5);
  camera.add(racket);
  scene.add(camera);
}
let swingT = -1;   // 挥拍动画的进度（-1 表示没在挥）
function playSwing() { swingT = 0; }

// ------------------------------------------------------------ 渲染循环

function resizeRenderer() {
  const w = $('view').clientWidth || window.innerWidth;
  const h = $('view').clientHeight || window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resizeRenderer);

// 把服务器的状态同步到场景里（位置会在每一帧平滑追过去）
function applyState(state) {
  for (const s of state.seats) {
    if (!s) continue;
    let p = players.get(s.index);
    if (!p || p.userId !== s.userId) {
      if (p) scene.remove(p.group);
      p = makePlayer(s);
      players.set(s.index, p);
    }
    p.tx = s.x;
    p.tz = s.z;
  }
  for (const [idx, p] of players) {
    if (!state.seats[idx]) { scene.remove(p.group); players.delete(idx); }
  }
  for (const ev of state.events) {
    if (ev.type === 'hit' && ev.seat === mySeat(state)?.index) playSwing();
  }
}

const camPos = new THREE.Vector3(0, 1.7, 0);
const lookPos = new THREE.Vector3(0, 1.2, 0);
const ballTarget = new THREE.Vector3();
let lastFrame = performance.now();

function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - lastFrame) / 1000);
  lastFrame = now;
  const state = S.state;
  if (!state || S.view !== 'game') return;

  // 人物和球平滑移动
  const k = 1 - Math.pow(0.0001, dt);   // 每秒追上大部分距离
  for (const p of players.values()) {
    p.x += (p.tx - p.x) * k;
    p.z += (p.tz - p.z) * k;
    p.group.position.set(p.x, 0, p.z);
  }
  const b = state.ball;
  ballTarget.set(b.x, b.y, b.z);
  ball.position.lerp(ballTarget, Math.min(1, k * 1.5));
  ballShadow.position.set(ball.position.x, 0.004, ball.position.z);
  const hgt = Math.max(0.2, 1 - ball.position.y * 0.12);
  ballShadow.scale.set(hgt, hgt, hgt);

  // 摄像机：站在自己的位置，朝对面看；视线会慢慢转向球
  const seat = mySeat(state);
  const fwd = myTeam() === 0 ? 1 : -1;
  if (seat && players.get(seat.index)) {
    const p = players.get(seat.index);
    camPos.set(p.x, 1.7, p.z);
  } else {
    camPos.set(fwd * -12, 6, 0);
  }
  const toBall = new THREE.Vector3(ball.position.x - camPos.x, ball.position.y - 1.2, ball.position.z - camPos.z);
  const forward = new THREE.Vector3(fwd, -0.12, 0);
  let look = forward.clone();
  if (toBall.clone().setY(0).dot(forward) > 0) {
    look = forward.clone().multiplyScalar(0.45).add(toBall.clone().normalize().multiplyScalar(0.55));
  }
  look.normalize();
  lookPos.copy(camPos).addScaledVector(look, 10);
  camera.position.copy(camPos);
  camera.lookAt(lookPos);

  // 挥拍动画
  if (swingT >= 0) {
    swingT += dt / 0.28;
    const a = Math.sin(Math.min(1, swingT) * Math.PI);
    racket.rotation.set(0.25 - a * 1.2, 0.2 - a * 0.6, -0.5 + a * 0.3);
    if (swingT >= 1) { swingT = -1; racket.rotation.set(0.25, 0.2, -0.5); }
  }

  renderer.render(scene, camera);
}
requestAnimationFrame(frame);

// ------------------------------------------------------------ 比赛界面

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

function updateHitButton(state) {
  const seat = mySeat(state);
  const btn = $('hitBtn');
  let label = '击球';
  let ready = false;
  if (seat) {
    const isServer = seat.index === state.serveSeat;
    if (state.phase === 'serve_wait' && isServer) label = '抛球';
    else if (state.phase === 'toss' && isServer) {
      label = '发球';
      ready = state.ball.y > 1.0 && Math.hypot(state.ball.x - seat.x, state.ball.z - seat.z) < 1.0;
    } else if (state.phase === 'rally') {
      ready = seat.index !== state.lastSeat
        && Math.hypot(state.ball.x - seat.x, state.ball.z - seat.z) < REACH
        && state.ball.y > -0.1 && state.ball.y < 2.8;
    }
  }
  btn.firstChild.textContent = label;
  btn.classList.toggle('ready', ready);
}

function renderStrokes() {
  for (const b of document.querySelectorAll('#strokes button')) {
    b.classList.toggle('sel', b.dataset.stroke === S.stroke);
  }
}

function selectStroke(name) {
  S.stroke = name;
  renderStrokes();
}

function hitNow() {
  if (!S.state || S.state.status !== 'playing') return;
  send({ type: 'swing', stroke: S.stroke, aimR: S.stick.r, aimF: S.stick.f });
}

function renderGame(state) {
  renderScore(state);
  $('hudMsg').textContent = state.message || '';
  updateHitButton(state);

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

// ------------------------------------------------------------ 摇杆与键盘

const joy = $('joy');
const knob = $('knob');
function moveKnob(e) {
  const rect = joy.getBoundingClientRect();
  const R = rect.width / 2;
  let dx = e.clientX - (rect.left + R);
  let dy = e.clientY - (rect.top + R);
  const mag = Math.hypot(dx, dy);
  if (mag > R) { dx *= R / mag; dy *= R / mag; }
  knob.style.transform = `translate(${dx}px, ${dy}px)`;
  S.stick.r = dx / R;
  S.stick.f = -dy / R;   // 摇杆向上 = 朝对面
}
let joyActive = false;   // 手指正在摇杆上
function resetKnob() {
  joyActive = false;
  knob.style.transform = '';
  S.stick.f = 0;
  S.stick.r = 0;
}
joy.addEventListener('pointerdown', (e) => { joyActive = true; joy.setPointerCapture(e.pointerId); moveKnob(e); });
joy.addEventListener('pointermove', (e) => { if (joy.hasPointerCapture(e.pointerId)) moveKnob(e); });
joy.addEventListener('pointerup', resetKnob);
joy.addEventListener('pointercancel', resetKnob);

const keysDown = new Set();
function keyStick() {
  const f = (keysDown.has('KeyW') || keysDown.has('ArrowUp') ? 1 : 0) - (keysDown.has('KeyS') || keysDown.has('ArrowDown') ? 1 : 0);
  const r = (keysDown.has('KeyD') || keysDown.has('ArrowRight') ? 1 : 0) - (keysDown.has('KeyA') || keysDown.has('ArrowLeft') ? 1 : 0);
  return { f, r };
}
window.addEventListener('keydown', (e) => {
  if (S.view !== 'game') return;
  if (e.target && e.target.tagName === 'INPUT') return;
  if (e.repeat) return;
  keysDown.add(e.code);
  const n = Number(e.key);
  if (n >= 1 && n <= 5) selectStroke(STROKE_KEYS[n - 1]);
  if (e.code === 'Space' || e.code === 'KeyJ') { e.preventDefault(); hitNow(); }
  if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space'].includes(e.code)) e.preventDefault();
});
window.addEventListener('keyup', (e) => keysDown.delete(e.code));

// 键盘控制摇杆（手指按着触屏摇杆时，以摇杆为准）
setInterval(() => {
  if (S.view !== 'game') return;
  if (!joyActive) {
    const k = keyStick();
    S.stick.f = k.f;
    S.stick.r = k.r;
  }
  // 每 50 毫秒把摇杆方向发给服务器（有变化或者不为零时）
  const { f, r } = S.stick;
  if (f !== S.sent.f || r !== S.sent.r || f || r) {
    send({ type: 'stick', f: round2(f), r: round2(r) });
    S.sent = { f, r };
  }
}, 50);
function round2(v) { return Math.round(v * 100) / 100; }

for (const b of document.querySelectorAll('#strokes button')) {
  b.addEventListener('click', () => selectStroke(b.dataset.stroke));
}
$('hitBtn').addEventListener('click', hitNow);
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
      if (m.status === 'waiting') {
        if (S.view !== 'room') showView('room');
        renderRoom(m);
      } else {
        if (S.view !== 'game') { showView('game'); }
        renderGame(m);
        renderStrokes();
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
  renderStrokes();
  connect();
}
boot();
