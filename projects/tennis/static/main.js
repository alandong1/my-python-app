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

// ------------------------------------------------------------ 三维场景（抽象的小人，抬高的视角）

const ZONE_X = { back: 10.6, mid: 7.0, net: 2.6 };   // 站位对应的 x 坐标（队 1 的一侧）
const ZONE_TEXT = { back: '后场', mid: '中场', net: '网前' };
const SITUATION_TEXT = {
  serve: '轮到你发球',
  deep: '球落在你的后场',
  short: '对方打来短球',
  lob: '对方挑高过来',
};
const TEAM_COLOR = [0xe4572e, 0x2e86de];

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xa8dcff);
scene.fog = new THREE.Fog(0xa8dcff, 45, 120);
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 300);
const renderer = new THREE.WebGLRenderer({ canvas: document.createElement('canvas'), antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
$('view').append(renderer.domElement);

scene.add(new THREE.HemisphereLight(0xffffff, 0x3a5a3a, 1.0));
const sun = new THREE.DirectionalLight(0xffffff, 0.6);
sun.position.set(8, 30, 10);
scene.add(sun);

function mat(color, extra = {}) { return new THREE.MeshLambertMaterial({ color, ...extra }); }
function addBox(w, h, d, x, y, z, material) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  m.position.set(x, y, z);
  scene.add(m);
  return m;
}

// 场地：草地 + 硬地 + 白线
const grass = new THREE.Mesh(new THREE.PlaneGeometry(300, 300), mat(0x5a9a52));
grass.rotation.x = -Math.PI / 2;
grass.position.y = -0.05;          // 草地比硬地低一点，避免两个平面「打架」
scene.add(grass);
const court = new THREE.Mesh(new THREE.PlaneGeometry(23.77, 10.97), mat(0x2f6fb0));
court.rotation.x = -Math.PI / 2;
court.position.y = 0.01;
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
// 看台（抽象的几块灰色）
const stand = mat(0x8a8f99);
for (const side of [-1, 1]) {
  addBox(4, 5, 60, side * 34, 2.5, 0, stand);
  addBox(60, 5, 4, 0, 2.5, side * 22, stand);
}
// 球网
const netMesh = new THREE.Mesh(
  new THREE.PlaneGeometry(12.8, 0.914),
  new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.4, side: THREE.DoubleSide }),
);
netMesh.rotation.y = Math.PI / 2;
netMesh.position.set(0, 0.457, 0);
scene.add(netMesh);
addBox(0.04, 0.06, 12.8, 0, 0.914, 0, WHITE);

// 球：画得大一点，抬高视角后也能看清
const ball = new THREE.Mesh(new THREE.SphereGeometry(0.14, 14, 10), mat(0xd4ff3a, { emissive: 0x335500 }));
scene.add(ball);
const ballShadow = new THREE.Mesh(
  new THREE.CircleGeometry(0.28, 18),
  new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.3, depthWrite: false }),
);
ballShadow.rotation.x = -Math.PI / 2;
scene.add(ballShadow);

// 小人：圆柱身体、球形头、一只手臂（拿着球拍）
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
const figures = new Map();   // 座位号 -> {group, arm, x, z, tx, tz, team, swingT}

function makeFigure(seat) {
  const group = new THREE.Group();
  const color = TEAM_COLOR[seat.team];
  const body = new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.38, 1.2, 10), mat(color));
  body.position.y = 0.9;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.24, 12, 10), mat(0xf4d6b0));
  head.position.y = 1.7;
  // 手臂挂在肩膀上，转动它就是挥拍
  const arm = new THREE.Group();
  arm.position.set(0.36, 1.35, 0);
  const limb = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.75, 0.1), mat(0xf4d6b0));
  limb.position.y = -0.38;
  const racket = new THREE.Mesh(new THREE.TorusGeometry(0.2, 0.025, 6, 16), mat(0x222222));
  racket.position.set(0, -0.85, 0);
  racket.scale.set(1, 1.3, 1);
  arm.add(limb, racket);
  group.add(body, head, arm, nameSprite(seat.name));
  scene.add(group);
  return { group, arm, x: 0, z: seat.z, tx: 0, tz: seat.z, team: seat.team, swingT: -1 };
}

function zoneX(team, zone) {
  return (team === 0 ? -1 : 1) * ZONE_X[zone];
}

// 把服务器的站位同步到场景里（小人会平滑地走到新位置）
function applyState(state) {
  for (const s of state.seats) {
    if (!s) continue;
    let f = figures.get(s.index);
    if (!f || f.userId !== s.userId) {
      if (f) scene.remove(f.group);
      f = makeFigure(s);
      f.userId = s.userId;
      figures.set(s.index, f);
      f.x = f.tx = zoneX(s.team, s.zone);
    }
    f.tx = zoneX(s.team, s.zone);
    f.tz = s.z;
  }
  for (const [idx, f] of figures) {
    if (!state.seats[idx]) { scene.remove(f.group); figures.delete(idx); }
  }
  for (const ev of state.events) {
    if (ev.type === 'shot') startShotAnimation(ev);
  }
}

// 击球动画：球从击球的小人身上沿弧线飞向落点
let shotAnim = null;   // {t, dur, from, to, arc, seat, result}
function startShotAnimation(ev) {
  const f = figures.get(ev.seat);
  if (!f) return;
  f.swingT = 0;
  const from = new THREE.Vector3(f.x, 1.2, f.tz);
  let to;
  if (ev.toZone === 'far') {
    to = new THREE.Vector3((ev.toTeam === 0 ? -1 : 1) * 15, 0.2, f.tz * 1.6);
  } else if (ev.toZone === 'net') {
    to = new THREE.Vector3(0, 0.3, f.tz);
  } else {
    to = new THREE.Vector3(zoneX(ev.toTeam, ev.toZone), 0.2, (Math.random() - 0.5) * 3);
  }
  shotAnim = { t: 0, dur: 1.3, from, to, arc: ev.arc ? 3.4 : 1.0, result: ev.result, fail: ev.fail };
}

const camLook = new THREE.Vector3(0, 0.6, 0);
const camPos = new THREE.Vector3();
let lastFrame = performance.now();

function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - lastFrame) / 1000);
  lastFrame = now;
  const state = S.state;
  if (!state || S.view !== 'game') return;

  // 小人平滑移动并挥拍
  const k = 1 - Math.pow(0.001, dt);
  for (const f of figures.values()) {
    f.x += (f.tx - f.x) * k;
    f.z += (f.tz - f.z) * k;
    f.group.position.set(f.x, 0, f.z);
    if (f.swingT >= 0) {
      f.swingT += dt / 0.45;
      const a = Math.sin(Math.min(1, f.swingT) * Math.PI);
      f.arm.rotation.z = -a * 1.6;
      if (f.swingT >= 1) { f.swingT = -1; f.arm.rotation.z = 0; }
    }
  }

  // 球：击球动画中沿弧线飞；平时停在击球方身前；得分后隐藏
  if (shotAnim) {
    shotAnim.t += dt;
    const u = Math.min(1, shotAnim.t / shotAnim.dur);
    ball.position.lerpVectors(shotAnim.from, shotAnim.to, u);
    ball.position.y += Math.sin(Math.PI * u) * shotAnim.arc;
    ball.visible = true;
    if (u >= 1) shotAnim = null;
  } else {
    const hitter = state.hitter != null ? figures.get(state.hitter) : null;
    if (hitter && (state.phase === 'menu' || state.phase === 'serve_menu')) {
      ball.position.set(hitter.x + (hitter.team === 0 ? 0.8 : -0.8), 1.4 + Math.sin(now / 300) * 0.1, hitter.tz);
      ball.visible = true;
    } else if (state.phase === 'animating') {
      ball.visible = true;
    } else {
      ball.visible = false;
    }
  }
  ballShadow.position.set(ball.position.x, 0.005, ball.position.z);
  const hgt = Math.max(0.35, 1 - ball.position.y * 0.1);
  ballShadow.scale.set(hgt, hgt, hgt);
  ballShadow.visible = ball.visible;

  // 摄像机：抬高，站在自己这一边的后面，斜着往下看整个球场
  const side = myTeam() === 0 ? -1 : 1;
  camPos.set(side * 19.5, 8.6, 0);
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

// 当前这一次选择：是不是轮到我、局面是什么、对方站在哪里
let choiceKey = null;   // 已经发送过选择的那一次（防止重复点击）

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
  const key = `${state.phase}-${state.hitter}-${menu.options.map((o) => o.id).join(',')}`;
  const oppZone = menu.oppZone ? `对方站在${ZONE_TEXT[menu.oppZone]}` : '';
  if (!myTurn) {
    $('menuTitle').textContent = '对方在选择…';
    $('menuSub').textContent = [SITUATION_TEXT[menu.situation], oppZone].filter(Boolean).join(' · ');
    $('menuCards').replaceChildren();
    $('menuTimer').textContent = '';
    return;
  }
  $('menuTitle').textContent = menu.situation === 'serve' ? '轮到你发球，选一种发球' : '轮到你，选一种打法';
  $('menuSub').textContent = menu.situation === 'serve'
    ? oppZone
    : [SITUATION_TEXT[menu.situation], oppZone].filter(Boolean).join(' · ');
  $('menuTimer').textContent = `${Math.ceil(menu.deadline)} 秒内选择`;
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

// ------------------------------------------------------------ 键盘

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
