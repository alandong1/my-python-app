// 荒岛求生：浏览器端。只负责显示和发送按键，所有规则都在服务器（game.py）里算。
import * as THREE from 'three';

const $ = (id) => document.getElementById(id);
const DEEP = 0, SHALLOW = 1, SAND = 2, GRASS = 3, FOREST = 4;
const TERRAIN_H = [-0.8, -0.3, 0.05, 0.25, 0.3];                       // 深海 浅海 沙滩 草地 森林
const TERRAIN_C = ['#1d4a72', '#3f93bd', '#e3cf93', '#6aa347', '#3a7535'];
const ROLE_COLOR = { chef: 0xe07b39, doctor: 0xf2f2f2, priest: 0x7a5cc4 };
const CROP_COLOR = { carrot: '#ff8c2b', potato: '#a77a3f', corn: '#f2c230' };
const HORIZON = '#cfe6f2';
// 远端玩家和动物按「过去 100 毫秒」的画面显示：服务器每 0.1 秒发一次，网络有快有慢，
// 延迟 100 毫秒后就有两个快照可以匀速插值，画面不会一顿一顿。（和 strike 的做法相同）
const INTERP_MS = 100;

let ws = null, role = null, myId = null, info = null;
let scene, roomScene, camera, renderer, sun, water, waterBase = null, me = null;
let yaw = Math.PI, dragging = false, lastX = 0;
const players = new Map(), animals = new Map(), buildings = new Map(), trees = new Map();
let roomGroup = null, roomKey = '', lastHouse = undefined;
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

// 「我面朝哪边」：就是镜头看的方向。建造、种田、放家具都用它决定放在哪里
function facing() {
  return { fx: -Math.sin(yaw), fz: -Math.cos(yaw) };
}

function act(action, extra = {}) {
  send({ type: 'action', action, ...facing(), ...extra });
}

function onMessage(msg) {
  if (msg.type === 'auth') {
    location.href = '/?login=1&next=' + encodeURIComponent(location.pathname);
  } else if (msg.type === 'welcome') {
    info = msg.info; myId = msg.id;
    startGame(msg.state);
  } else if (msg.type === 'state') {
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
  // 掉线重连时会再收到一次 welcome：场景、输入和循环只初始化一次
  if (!scene) {
    initScene();
    buildTerrain();
    buildDecor();
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
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;   // 让高光和阴影的过渡更像真实相机
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  scene = new THREE.Scene();
  scene.fog = new THREE.Fog(HORIZON, 70, 190);
  camera = new THREE.PerspectiveCamera(55, 1, 0.1, 500);
  scene.add(makeSky());

  // 天光 + 太阳（会投影的主光）
  scene.add(new THREE.HemisphereLight('#cfe6ff', '#4a5a3a', 1.0));
  sun = new THREE.DirectionalLight('#ffe6bd', 2.2);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -45, right: 45, top: 45, bottom: -45, near: 1, far: 260 });
  sun.shadow.bias = -0.0008;
  sun.shadow.normalBias = 0.03;
  scene.add(sun, sun.target);

  // 屋里的场景：没有太阳，靠天光和油灯照亮
  roomScene = new THREE.Scene();
  roomScene.background = new THREE.Color('#2b2620');
  roomScene.add(new THREE.HemisphereLight('#fff3e0', '#4a3a2a', 1.4));

  resize();
  window.addEventListener('resize', resize);

  // 海面：半透明，表面有缓慢起伏的波浪
  const waterGeo = new THREE.PlaneGeometry(info.w * 2, info.h * 2, 120, 120);
  waterGeo.rotateX(-Math.PI / 2);
  waterGeo.translate(info.w / 2, 0, info.h / 2);
  waterBase = Float32Array.from(waterGeo.attributes.position.array);
  water = new THREE.Mesh(waterGeo, new THREE.MeshStandardMaterial({
    color: '#2b78a8', roughness: 0.15, metalness: 0.1, transparent: true, opacity: 0.85,
  }));
  water.receiveShadow = true;
  scene.add(water);

  // 共用的几何体和材质，省内存
  shared.trunk = new THREE.CylinderGeometry(0.1, 0.17, 1.5, 7);
  shared.trunkMat = new THREE.MeshStandardMaterial({ color: '#6b4a2e', roughness: 0.95 });
  shared.cone1 = new THREE.ConeGeometry(0.95, 1.8, 8);
  shared.cone2 = new THREE.ConeGeometry(0.65, 1.4, 8);
  shared.leafMats = ['#2d6a2e', '#35773a', '#2a5e33'].map((c) =>
    new THREE.MeshStandardMaterial({ color: c, roughness: 0.85 }));
  shared.bush = new THREE.SphereGeometry(0.5, 10, 8);
  shared.bushMat = new THREE.MeshStandardMaterial({ color: '#3d7a2c', roughness: 0.9 });
  shared.berry = new THREE.SphereGeometry(0.08, 8, 6);
  shared.berryMat = new THREE.MeshStandardMaterial({ color: '#c0392b', roughness: 0.4 });
  shared.herb = new THREE.ConeGeometry(0.1, 0.5, 5);
  shared.herbMat = new THREE.MeshStandardMaterial({ color: '#9ccc65', roughness: 0.8 });
  shared.reed = new THREE.CylinderGeometry(0.02, 0.03, 1.2, 5);
  shared.reedMat = new THREE.MeshStandardMaterial({ color: '#b5c96b', roughness: 0.9 });
  shared.rock = new THREE.DodecahedronGeometry(0.32, 0);
  shared.rockMat = new THREE.MeshStandardMaterial({ color: '#8f8a80', roughness: 0.95, flatShading: true });
  shared.shell = new THREE.SphereGeometry(0.12, 8, 5);
  shared.shellMat = new THREE.MeshStandardMaterial({ color: '#f2e6d0', roughness: 0.4 });
  shared.capMat = new THREE.MeshStandardMaterial({ color: '#d9432f', roughness: 0.6 });
  shared.stem = new THREE.CylinderGeometry(0.04, 0.05, 0.2, 6);
  shared.stemMat = new THREE.MeshStandardMaterial({ color: '#efe6d2', roughness: 0.8 });
  shared.body = new THREE.CylinderGeometry(0.25, 0.25, 0.9, 12);
  shared.head = new THREE.SphereGeometry(0.22, 12, 10);
  shared.skin = new THREE.MeshStandardMaterial({ color: '#f1c9a5', roughness: 0.7 });
  shared.rabbit = new THREE.SphereGeometry(0.25, 10, 8);
  shared.rabbitMat = new THREE.MeshStandardMaterial({ color: '#c9b49a', roughness: 0.9 });
  shared.crab = new THREE.SphereGeometry(0.22, 10, 8);
  shared.crabMat = new THREE.MeshStandardMaterial({ color: '#d9573a', roughness: 0.6 });
  shared.flame = new THREE.ConeGeometry(0.2, 0.6, 6);
  shared.flameMat = new THREE.MeshBasicMaterial({ color: '#ff9a2e' });
  shared.ring = new THREE.RingGeometry(0.4, 0.5, 24);
  shared.ringMat = new THREE.MeshBasicMaterial({ color: '#ffe066', side: THREE.DoubleSide, transparent: true, opacity: 0.8 });
  shared.tuft = new THREE.ConeGeometry(0.07, 0.28, 4);
  shared.tuftMat = new THREE.MeshLambertMaterial({ color: '#ffffff' });
  shared.box = new THREE.BoxGeometry(1, 1, 1);
  shared.wood = new THREE.MeshStandardMaterial({ color: '#8a5d36', roughness: 0.9 });
  shared.woodLight = new THREE.MeshStandardMaterial({ color: '#b08a5a', roughness: 0.9 });
  shared.stone = new THREE.MeshStandardMaterial({ color: '#8c877d', roughness: 0.95, flatShading: true });
  shared.soil = new THREE.MeshStandardMaterial({ color: '#5a3d26', roughness: 1 });
  shared.leafGreen = new THREE.MeshStandardMaterial({ color: '#4f9a3a', roughness: 0.8 });
  shared.roofRed = new THREE.MeshStandardMaterial({ color: '#a3442f', roughness: 0.8 });
  shared.roofBlue = new THREE.MeshStandardMaterial({ color: '#37608f', roughness: 0.8 });
  shared.glow = new THREE.MeshBasicMaterial({ color: '#ffb347' });
  shared.furnMat = new THREE.MeshStandardMaterial({ color: '#5b5750', roughness: 0.9 });
  shared.cloth = new THREE.MeshStandardMaterial({ color: '#8b3a3a', roughness: 1 });
}

// 天空：从地平线的雾色渐变到头顶的蓝
function makeSky() {
  const geo = new THREE.SphereGeometry(400, 32, 16);
  const top = new THREE.Color('#3f86cf'), horizon = new THREE.Color(HORIZON);
  const pos = geo.attributes.position;
  const cols = new Float32Array(pos.count * 3);
  const c = new THREE.Color();
  for (let i = 0; i < pos.count; i++) {
    const t = Math.max(0, Math.min(1, pos.getY(i) / 220));
    c.copy(horizon).lerp(top, Math.pow(t, 0.55));
    cols.set([c.r, c.g, c.b], i * 3);
  }
  geo.setAttribute('color', new THREE.BufferAttribute(cols, 3));
  return new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide, fog: false }));
}

function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

// 地形顶点（格子的角）的高度。地形网格和 terrainHeight() 都用它，保证人站在地面上。
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

// 确定性的「随机」：同一个格子每次都得到同一个数，草的位置每次刷新都一样
function hash(x, z, s) {
  const v = Math.sin(x * 127.1 + z * 311.7 + s * 74.7) * 43758.5453;
  return v - Math.floor(v);
}

// 地形：每个格子的四个角是一个顶点，颜色来自地形编号，加一点明暗变化；表面有颗粒感的纹理
function buildTerrain() {
  const W = info.w, H = info.h, T = info.terrain;
  const pos = new Float32Array((W + 1) * (H + 1) * 3);
  const col = new Float32Array((W + 1) * (H + 1) * 3);
  const uv = new Float32Array((W + 1) * (H + 1) * 2);
  const c = new THREE.Color();
  for (let j = 0; j <= H; j++) {
    for (let i = 0; i <= W; i++) {
      const tx = Math.min(i, W - 1), tz = Math.min(j, H - 1);
      const t = T.charCodeAt(tz * W + tx) - 48;
      const k = (j * (W + 1) + i) * 3;
      pos[k] = i; pos[k + 1] = vertexHeight(i, j); pos[k + 2] = j;
      const jitter = 0.92 + 0.08 * hash(i, j, 9);
      c.set(TERRAIN_C[t]).multiplyScalar(jitter);
      col[k] = c.r; col[k + 1] = c.g; col[k + 2] = c.b;
      uv[(j * (W + 1) + i) * 2] = i / W;
      uv[(j * (W + 1) + i) * 2 + 1] = j / H;
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
  geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  geo.setIndex(new THREE.BufferAttribute(index, 1));
  geo.computeVertexNormals();
  const map = grainTexture();
  map.repeat.set(W / 3, H / 3);
  const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, map, roughness: 0.95 }));
  mesh.receiveShadow = true;
  scene.add(mesh);
}

// 一小块随机的灰度噪声，叠在地面颜色上，让草地和沙滩不像一张纯色的纸
function grainTexture() {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(size, size);
  for (let i = 0; i < img.data.length; i += 4) {
    const v = 185 + Math.random() * 70;
    img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
    img.data[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  return tex;
}

// 地面装饰：草丛（成千上万个用「实例」一次画完，不会拖慢画面）。石头、树木都是服务器的资源点，不在这里画。
function buildDecor() {
  const W = info.w, H = info.h;
  const tufts = [];
  for (let j = 0; j < H; j++) {
    for (let i = 0; i < W; i++) {
      const t = info.terrain.charCodeAt(j * W + i) - 48;
      const r = hash(i, j, 1);
      if ((t === GRASS && r < 0.22) || (t === FOREST && r < 0.06)) {
        tufts.push([i + 0.15 + 0.7 * hash(i, j, 2), j + 0.15 + 0.7 * hash(i, j, 3), hash(i, j, 4)]);
      }
    }
  }
  const dummy = new THREE.Object3D();
  const color = new THREE.Color();
  const tuftMesh = new THREE.InstancedMesh(shared.tuft, shared.tuftMat, tufts.length);
  tufts.forEach(([x, z, v], k) => {
    const s = 0.6 + 0.8 * v;
    dummy.position.set(x, terrainHeight(x, z) + 0.2 * s, z);
    dummy.rotation.set(0, v * 6.28, 0);
    dummy.scale.set(s, s, s);
    dummy.updateMatrix();
    tuftMesh.setMatrixAt(k, dummy.matrix);
    color.setHSL(0.24 + 0.05 * v, 0.4, 0.22 + 0.1 * v);
    tuftMesh.setColorAt(k, color);
  });
  scene.add(tuftMesh);
}

// ------------------------------------------------------------ 模型：自然资源

function cast(g) {
  g.traverse((o) => { if (o.isMesh) o.castShadow = true; });
  return g;
}

function makeTree(id) {
  const g = new THREE.Group();
  const trunk = new THREE.Mesh(shared.trunk, shared.trunkMat);
  trunk.position.y = 0.75;
  const mat = shared.leafMats[id % shared.leafMats.length];
  const low = new THREE.Mesh(shared.cone1, mat);
  low.position.y = 1.9;
  const high = new THREE.Mesh(shared.cone2, mat);
  high.position.y = 2.8;
  g.add(trunk, low, high);
  g.scale.setScalar(0.8 + ((id * 37) % 40) / 100);      // 每棵树大小不一样
  return cast(g);
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
  return cast(g);
}

function makeHerb() {
  const g = new THREE.Group();
  for (const [x, z] of [[0, 0], [0.15, 0.1], [-0.12, 0.08]]) {
    const h = new THREE.Mesh(shared.herb, shared.herbMat);
    h.position.set(x, 0.25, z);
    g.add(h);
  }
  return cast(g);
}

function makeReed(id) {
  const g = new THREE.Group();
  for (let k = 0; k < 5; k++) {
    const r = new THREE.Mesh(shared.reed, shared.reedMat);
    const a = hash(id, k, 11) * 0.5 - 0.25;
    r.position.set(Math.cos(k * 1.3) * 0.12, 0.6, Math.sin(k * 1.3) * 0.12);
    r.rotation.z = a;
    g.add(r);
  }
  return g;
}

function makeRock(id) {
  const g = new THREE.Group();
  const r = new THREE.Mesh(shared.rock, shared.rockMat);
  r.position.y = 0.2;
  r.rotation.set(id * 0.7, id * 1.3, 0);
  r.scale.set(1.1, 0.8, 1);
  g.add(r);
  return cast(g);
}

function makeShell() {
  const g = new THREE.Group();
  const s = new THREE.Mesh(shared.shell, shared.shellMat);
  s.scale.set(1, 0.4, 1.2);
  s.position.y = 0.05;
  g.add(s);
  return g;
}

function makeMushroom() {
  const g = new THREE.Group();
  const stem = new THREE.Mesh(shared.stem, shared.stemMat);
  stem.position.y = 0.1;
  const cap = new THREE.Mesh(shared.rabbit, shared.capMat);
  cap.scale.set(0.45, 0.25, 0.45);
  cap.position.y = 0.22;
  g.add(stem, cap);
  return cast(g);
}

function makeResource(kind, id) {
  if (kind === 'tree') return makeTree(id);
  if (kind === 'bush') return makeBush();
  if (kind === 'herb') return makeHerb();
  if (kind === 'reed') return makeReed(id);
  if (kind === 'rock') return makeRock(id);
  if (kind === 'shell') return makeShell();
  return makeMushroom();
}

// ------------------------------------------------------------ 模型：动物和玩家

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
  return cast(g);
}

function makePlayer(p) {
  const [id, name, r] = p;
  const g = new THREE.Group();
  const body = new THREE.Mesh(shared.body, new THREE.MeshStandardMaterial({ color: ROLE_COLOR[r] || 0xffffff, roughness: 0.6 }));
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
  return cast(g);
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
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  sprite.scale.set(2.2, 0.55, 1);
  sprite.position.y = 1.9;
  return sprite;
}

// ------------------------------------------------------------ 模型：建筑和农田

function box(w, h, d, mat, x, y, z) {
  const m = new THREE.Mesh(shared.box, mat);
  m.scale.set(w, h, d);
  m.position.set(x, y, z);
  return m;
}

function makeBuilding(kind, level, state) {
  const g = new THREE.Group();
  if (kind === 'workbench') {
    g.add(box(1.0, 0.1, 0.7, shared.woodLight, 0, 0.8, 0));          // 台面
    for (const [x, z] of [[-0.42, -0.27], [0.42, -0.27], [-0.42, 0.27], [0.42, 0.27]]) {
      g.add(box(0.1, 0.8, 0.1, shared.wood, x, 0.4, z));           // 四条腿
    }
    g.add(box(0.3, 0.12, 0.2, shared.stone, -0.2, 0.9, 0.05));    // 工具：石头
    if (level >= 2) g.add(box(0.8, 0.08, 0.2, shared.woodLight, 0, 0.3, -0.25));   // 2 级：下层搁板
    if (level >= 3) g.add(box(0.6, 0.12, 0.6, shared.stone, 0.25, 1.0, 0));       // 3 级：砧台
  } else if (kind === 'campfire') {
    const lit = state === 'lit';
    for (let k = 0; k < 6; k++) {
      const a = (k / 6) * Math.PI * 2;
      const s = new THREE.Mesh(shared.rock, shared.stone);
      s.scale.setScalar(0.5);
      s.position.set(Math.cos(a) * 0.4, 0.08, Math.sin(a) * 0.4);
      g.add(s);
    }
    for (let k = 0; k < 3; k++) {                                       // 柴
      const log = box(0.08, 0.08, 0.6, shared.wood, 0, 0.1, 0);
      log.rotation.y = k * 1.05;
      g.add(log);
    }
    if (lit) {
      const flame = new THREE.Mesh(shared.flame, shared.flameMat);
      flame.position.y = 0.45;
      flame.userData.flame = true;
      g.add(flame);
    }
  } else if (kind === 'furnace') {
    g.add(box(0.9, 1.1, 0.9, shared.furnMat, 0, 0.55, 0));
    g.add(box(0.4, 0.3, 0.05, shared.glow, 0, 0.45, 0.47));            // 炉口
    if (level >= 2) g.add(box(0.2, 0.9, 0.2, shared.furnMat, 0.3, 1.35, -0.2));   // 2 级：烟囱
  } else if (kind === 'house') {
    const wallMat = level === 1 ? shared.wood : level === 2 ? shared.stone : shared.woodLight;
    const roofMat = level === 3 ? shared.roofBlue : shared.roofRed;
    g.add(box(2.9, 1.6, 2.9, wallMat, 0, 0.8, 0));                      // 墙
    const roof = new THREE.Mesh(new THREE.ConeGeometry(2.4, 1.2, 4), roofMat);
    roof.rotation.y = Math.PI / 4;
    roof.position.y = 2.2;
    g.add(roof);
    g.add(box(0.7, 1.0, 0.1, shared.wood, 0, 0.5, 1.5));                 // 门（朝向镜头这一侧）
    g.add(box(0.5, 0.4, 0.1, shared.glow, -0.9, 1.0, 1.5));              // 窗
    g.add(box(0.5, 0.4, 0.1, shared.glow, 0.9, 1.0, 1.5));
  } else if (kind === 'plot') {
    g.add(box(0.95, 0.12, 0.95, shared.soil, 0, 0.02, 0));
    if (state && state !== 'empty') {
      const [crop, stage] = state.split(':');
      const s = [0.25, 0.5, 0.8][Number(stage)] || 0.25;
      const leaf = new THREE.Mesh(shared.tuft, shared.leafGreen);
      leaf.scale.setScalar(s * 2.2);
      leaf.position.y = 0.1 + s * 0.4;
      g.add(leaf);
      if (Number(stage) === 2) {                                         // 成熟：露出果实
        const fruit = new THREE.Mesh(shared.berry, new THREE.MeshStandardMaterial({ color: CROP_COLOR[crop] || '#ff8c2b' }));
        fruit.scale.setScalar(2.5);
        fruit.position.set(0.15, 0.2, 0.1);
        g.add(fruit);
      }
    }
  }
  return cast(g);
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
  updateActions(s);
  const house = m.house;                        // null 表示在室外；数字是房子的编号
  if (house !== lastHouse) {                    // 进屋或出屋：之前的位置不能拿来插值
    for (const mesh of players.values()) mesh.userData.samples = [];
    lastHouse = house;
  }
  setBars(m);
  setInventory(m.inv, house !== null);
  setLog(m.events);
  $('meName').textContent = m.name;
  $('dead').hidden = !m.dead;
  $('houseBar').hidden = house === null;

  // 所有玩家：只显示和自己在同一个地方（室外，或同一间屋子）的
  const seen = new Set();
  for (const p of s.players) {
    const [id, , , x, z] = p;
    seen.add(id);
    let mesh = players.get(id);
    if (!mesh) {
      mesh = makePlayer(p);
      mesh.userData = { samples: [] };
      scene.add(mesh);
      players.set(id, mesh);
    }
    pushSample(mesh, x, z);
    mesh.userData.dead = p[5];
  }
  removeMissing(players, seen);
  $('survivors').textContent = `岛上幸存者：${s.players.length} 人 · ` +
    s.players.map((p) => p[1] + '（' + (info.roles[p[2]] || '') + '）').join('、');

  if (house !== null) {
    showRoom(s.room);
    // 屋里只有室内的玩家：把他们挪到房间里，别的屋子的玩家藏起来
    for (const [id, mesh] of players) {
      mesh.visible = s.players.some((p) => p[0] === id);
      if (mesh.visible) roomScene.add(mesh);
    }
    for (const mesh of animals.values()) scene.remove(mesh);
    animals.clear();
    setBuildingsVisible(false);
    return;
  }

  // 室外
  if (roomGroup) { roomScene.remove(roomGroup); roomGroup = null; roomKey = ''; }
  for (const mesh of players.values()) { mesh.visible = true; scene.add(mesh); }
  setBuildingsVisible(true);
  syncAnimals(s.animals);
  syncResources(s);
  syncBuildings(s.buildings || []);
}

// 底部按钮：只显示附近能做的事，避免屏幕上堆满按钮。
// 判断顺序和服务器的「互动」一致：动物 → 门口 → 树 → 其他资源 → 房子 → 钓鱼。
let lastRes = [], lastBuildings = [];
let interactAnchor = null;      // 互动目标的三维位置（每个快照更新）
let currentStation = null;      // 附近的设施：点了它就打开它的菜单
let roomLevel = 1;
const STATION_LABEL = { workbench: '合成', campfire: '烹饪', furnace: '冶炼' };
const STATION_NAME = { workbench: '工作台', campfire: '火堆', furnace: '石炉' };

// 底部按钮和互动按钮：只显示附近能做的事。
// 互动的优先级和服务器一致：动物 → 门口 → 树 → 其他资源 → 房子 → 设施 → 钓鱼。
function updateActions(s) {
  if (s.res) lastRes = s.res;
  const inside = me.house !== null && me.house !== undefined;
  lastBuildings = inside ? [] : (s.buildings || []);
  if (inside && s.room) roomLevel = s.room.level;
  const near = (x, z, r) => (x - me.x) ** 2 + (z - me.z) ** 2 <= r * r;
  const show = {};
  let label = null, anchor = null, station = null;
  if (me.work) {
    // 正在做事：按钮变成进度条，贴在目标旁边
    label = me.work.label;
    anchor = [me.work.x, me.work.z];
  } else if (inside) {
    show.exit = true;
    if (s.room && s.room.furniture.some((f) => near(f[2], f[3], 1.6))) {
      label = '拿回家具';
      anchor = [me.x, me.z];
    }
  } else {
    const animal = s.animals.find((a) => near(a[2], a[3], 2));
    const door = lastBuildings.find((b) => b[1] === 'house' && near(b[2], b[3], 2.2));
    const tree = lastRes.find((r) => r[1] === 'tree' && near(r[2] + 0.5, r[3] + 0.5, 2.5));
    const plant = lastRes.find((r) => r[1] !== 'tree' && near(r[2] + 0.5, r[3] + 0.5, 2));
    const house = lastBuildings.find((b) => b[1] === 'house' && near(b[2], b[3], 3));
    const sta = lastBuildings.find((b) => STATION_LABEL[b[1]] && near(b[2], b[3], 3.5));
    // 按钮贴在目标旁边：动物、门、树、资源、房子、设施、海边（海边就贴在自己身上）
    if (animal) { label = '攻击'; anchor = [animal[2], animal[3]]; }
    else if (door) { label = '进屋'; anchor = [door[2], door[3]]; }
    else if (tree) { label = '砍树'; anchor = [tree[2] + 0.5, tree[3] + 0.5]; }
    else if (plant) { label = '采集'; anchor = [plant[2] + 0.5, plant[3] + 0.5]; }
    else if (house) { label = '进屋'; anchor = [house[2], house[3]]; }
    else if (sta) { label = STATION_LABEL[sta[1]]; anchor = [sta[2], sta[3]]; station = sta[1]; }
    else if (nearShallowWater()) { label = '钓鱼'; anchor = [me.x, me.z]; }
    if (lastBuildings.some((b) => b[1] === 'plot' && near(b[2], b[3], 1.6)) || (me.inv.hoe || 0) > 0) {
      show.farm = true;
    }
    if (role === 'doctor' && (me.inv.medicine || 0) > 0 &&
        s.players.some((p) => p[0] !== myId && !p[5] && near(p[3], p[4], 3))) {
      show.heal = true;
    }
  }
  if (label) show.interact = true;
  currentStation = station && !me.work ? station : null;
  for (const b of document.querySelectorAll('#actions button')) {
    const a = b.dataset.action;
    b.hidden = a === 'build' ? inside : !show[a];      // 建造常驻（屋里除外）
  }
  const ib = $('interactBtn');
  ib.hidden = !label;
  if (label) {
    const pct = me.work ? Math.round(me.work.progress * 100) : 0;
    ib.textContent = me.work ? `${label}… ${pct}%` : `${label} E`;
    // 进度条：按钮的背景从左到右填满
    ib.style.background = me.work
      ? `linear-gradient(90deg, #2f7d5b ${pct}%, rgba(40, 60, 50, 0.92) ${pct}%)` : '';
  }
  // 互动按钮要摆在哪里（三维位置，每帧换算成屏幕坐标）
  if (anchor) {
    interactAnchor = new THREE.Vector3(anchor[0], terrainHeight(anchor[0], anchor[1]) + 1.6, anchor[1]);
    if (inside) interactAnchor.y = 1.6;
  } else {
    interactAnchor = null;
  }
}

// 把互动按钮放到目标的屏幕位置上（目标在身后、看不见时就藏起来）
function placeInteract() {
  const btn = $('interactBtn');
  if (btn.hidden || !interactAnchor) return;
  const v = interactAnchor.clone().project(camera);
  btn.style.visibility = v.z > 1 || v.z < -1 ? 'hidden' : 'visible';
  btn.style.left = ((v.x + 1) / 2 * window.innerWidth) + 'px';
  btn.style.top = ((1 - v.y) / 2 * window.innerHeight) + 'px';
}

// 身边一格之内有没有浅海（钓鱼要站在海边）
function nearShallowWater() {
  const tx = Math.floor(me.x), tz = Math.floor(me.z);
  for (let dz = -1; dz <= 1; dz++) {
    for (let dx = -1; dx <= 1; dx++) {
      const x = tx + dx, z = tz + dz;
      if (x < 0 || z < 0 || x >= info.w || z >= info.h) continue;
      if (info.terrain.charCodeAt(z * info.w + x) - 48 === SHALLOW) return true;
    }
  }
  return false;
}

function setBuildingsVisible(v) {
  for (const b of buildings.values()) b.visible = v;
}

function syncAnimals(list) {
  const aseen = new Set();
  for (const [id, kind, x, z] of list) {
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
}

// 资源（树、石头、灌木丛……）每秒才更新一次
function syncResources(s) {
  if (!s.res) return;
  const rseen = new Set();
  for (const [id, kind, x, z] of s.res) {
    rseen.add(id);
    if (!trees.has(id)) {
      const mesh = makeResource(kind, id);
      mesh.position.set(x + 0.5, terrainHeight(x + 0.5, z + 0.5), z + 0.5);
      scene.add(mesh);
      trees.set(id, mesh);
    }
  }
  removeMissing(trees, rseen);
}

// 建筑和农田：外观（等级、火堆是否点着、农田上的作物）变了，就重新做一个
function syncBuildings(list) {
  const seen = new Set();
  for (const [id, kind, cx, cz, level, state] of list) {
    seen.add(id);
    const key = `${kind}|${level}|${state}`;
    let entry = buildings.get(id);
    if (!entry || entry.key !== key) {
      if (entry) scene.remove(entry.group);
      const group = makeBuilding(kind, level, state);
      group.position.set(cx, terrainHeight(cx, cz), cz);
      scene.add(group);
      entry = { key, group, kind };
      buildings.set(id, entry);
    }
    entry.group.visible = true;
  }
  for (const [id, entry] of buildings) {
    if (!seen.has(id)) { scene.remove(entry.group); buildings.delete(id); }
  }
  // 火堆的火苗闪动，在 frame 里做
}

// 屋里的画面：地板、墙（前面有门）、家具、油灯的光。房间变了（大小、家具）才重新做。
function showRoom(room) {
  const key = room ? `${room.id}|${room.size}|${JSON.stringify(room.furniture)}` : '';
  if (key === roomKey) return;
  roomKey = key;
  if (roomGroup) roomScene.remove(roomGroup);
  roomGroup = new THREE.Group();
  const S = room.size;
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(S, S), shared.woodLight);
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(S / 2, 0, S / 2);
  floor.receiveShadow = true;
  roomGroup.add(floor);
  const wallH = 2.6, t = 0.3;
  const walls = [
    [S / 2, S, S, t],       // 后墙
    [0, S / 2, t, S],       // 左墙
    [S, S / 2, t, S],       // 右墙
  ];
  for (const [x, z, w, d] of walls) {
    roomGroup.add(box(w, wallH, d, shared.wood, x, wallH / 2, z));
  }
  // 前墙（有门的一面）：门在中间，留出 1.6 格宽的口子
  const gap = 1.6;
  roomGroup.add(box((S - gap) / 2, wallH, t, shared.wood, (S - gap) / 4, wallH / 2, S));
  roomGroup.add(box((S - gap) / 2, wallH, t, shared.wood, S - (S - gap) / 4, wallH / 2, S));
  for (const [, kind, x, z] of room.furniture) {
    const f = furnitureMesh(kind);
    f.position.set(x, 0, z);
    roomGroup.add(f);
    if (kind === 'lamp') {
      const light = new THREE.PointLight('#ffc27a', 6, 7);
      light.position.set(x, 1.4, z);
      roomGroup.add(light);
    }
  }
  roomScene.add(roomGroup);
}

function furnitureMesh(kind) {
  const g = new THREE.Group();
  if (kind === 'bed') {
    g.add(box(1.0, 0.35, 1.8, shared.wood, 0, 0.2, 0));                   // 床架
    g.add(box(0.95, 0.15, 1.7, shared.cloth, 0, 0.42, 0));                // 被子
    g.add(box(0.8, 0.12, 0.3, shared.woodLight, 0, 0.5, -0.7));           // 枕头
  } else if (kind === 'table') {
    g.add(box(1.2, 0.08, 0.8, shared.woodLight, 0, 0.8, 0));
    for (const [x, z] of [[-0.5, -0.32], [0.5, -0.32], [-0.5, 0.32], [0.5, 0.32]]) g.add(box(0.08, 0.8, 0.08, shared.wood, x, 0.4, z));
  } else if (kind === 'chair') {
    g.add(box(0.6, 0.08, 0.6, shared.woodLight, 0, 0.45, 0));
    g.add(box(0.6, 0.6, 0.08, shared.woodLight, 0, 0.75, -0.26));
    for (const [x, z] of [[-0.24, -0.24], [0.24, -0.24], [-0.24, 0.24], [0.24, 0.24]]) g.add(box(0.07, 0.45, 0.07, shared.wood, x, 0.22, z));
  } else if (kind === 'chest') {
    g.add(box(0.9, 0.55, 0.6, shared.wood, 0, 0.28, 0));
    g.add(box(0.92, 0.08, 0.62, shared.stone, 0, 0.58, 0));
  } else if (kind === 'rug') {
    g.add(box(1.6, 0.02, 1.1, shared.cloth, 0, 0.02, 0));
  } else if (kind === 'lamp') {
    g.add(box(0.12, 1.1, 0.12, shared.wood, 0, 0.55, 0));
    g.add(box(0.3, 0.25, 0.3, shared.glow, 0, 1.2, 0));
  }
  return cast(g);
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
  coconut: '吃', berry: '吃', raw_fish: '吃', raw_meat: '吃', mushroom: '吃', carrot: '吃', potato: '吃',
  corn: '吃', cooked_fish: '吃', cooked_meat: '吃', roasted_corn: '吃', jam: '吃', veg_soup: '吃',
  fish_stew: '吃', skewer: '吃', medicine: '用',
};

// 背包：默认收起成一个小按钮，点开才显示列表。屋里的家具可以直接放下。
function setInventory(inv, inside) {
  const entries = Object.entries(inv);
  $('invCount').textContent = entries.length ? `(${entries.length})` : '';
  const key = JSON.stringify(inv) + inside;
  if (key === lastInvKey) return;
  lastInvKey = key;
  const ul = $('inv');
  ul.replaceChildren();
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
      btn.dataset.use = item;
      li.append(btn);
    } else if (inside && info.furniture.includes(item)) {
      const btn = document.createElement('button');
      btn.textContent = '放';
      btn.dataset.place = item;
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

// ------------------------------------------------------------ 菜单：建造 / 合成 / 升级，设施的菜单

function costText(obj) {
  return Object.entries(obj).map(([k, n]) => `${info.items[k] || k}×${n}`).join('、');
}

function canAfford(obj) {
  return Object.entries(obj).every(([k, n]) => (me.inv[k] || 0) >= n);
}

// 打开一个带标签页的面板。tabs = [{name, rows, empty}]；rows = [{label, sub, ok, button, run}]
function openPanel(title, tabs, active) {
  const cur = tabs.find((t) => t.name === active) || tabs[0];
  $('menuTitle').textContent = title;
  const bar = $('menuTabs');
  bar.replaceChildren();
  for (const t of tabs) {
    const b = document.createElement('button');
    b.textContent = t.name;
    b.className = 'tab' + (t === cur ? ' on' : '');
    b.addEventListener('click', () => openPanel(title, tabs, t.name));
    bar.append(b);
  }
  bar.hidden = tabs.length < 2;
  const ul = $('menuList');
  ul.replaceChildren();
  if (!cur.rows.length) {
    const li = document.createElement('li');
    li.textContent = cur.empty || '（这里没有可以做的东西）';
    ul.append(li);
  }
  for (const row of cur.rows) {
    const li = document.createElement('li');
    if (!row.ok) li.classList.add('dim');
    const text = document.createElement('div');
    text.className = 'menu-text';
    const name = document.createElement('b');
    name.textContent = row.label;
    const sub = document.createElement('small');
    sub.textContent = row.sub;
    text.append(name, sub);
    li.append(text);
    const btn = document.createElement('button');
    btn.textContent = row.button || '做';
    btn.disabled = !row.run;
    btn.addEventListener('click', () => { row.run(); closeMenu(); });
    li.append(btn);
    ul.append(li);
  }
  $('menu').hidden = false;
}

function closeMenu() {
  $('menu').hidden = true;
}

function recipeRow(id, r) {
  const need = r.station ? `需要${info.stationNames[r.station]}${r.level ? ' ' + r.level + ' 级' : ''}` : '随手可做';
  const useOther = r.role && me.role !== r.role && r.in_other;
  const mine = useOther ? r.in_other : r.in;
  let who = '';
  if (r.role) {
    who = r.in_other
      ? `（${info.roles[r.role]}只要${costText(r.in)}，其他人要${costText(r.in_other)}）`
      : `（只有${info.roles[r.role]}会做）`;
  }
  return {
    label: r.name,
    sub: `${costText(mine)} → ${costText(r.out)}　${need}${who}`,
    ok: canAfford(mine),
    run: () => act('craft', { recipe: id }),
  };
}

// 附近能升级的建筑（室内就是这间房子）
function upgradeRows() {
  const inside = me.house !== null && me.house !== undefined;
  const list = inside
    ? [{ kind: 'house', level: roomLevel }]
    : lastBuildings.filter((b) => b[1] !== 'plot' && (b[2] - me.x) ** 2 + (b[3] - me.z) ** 2 <= 3.5 * 3.5)
      .map((b) => ({ kind: b[1], level: b[4] }));
  return list.map(({ kind, level }) => {
    const spec = info.builds[kind];
    const name = STATION_NAME[kind] || spec.name;
    if (level >= spec.maxLevel) {
      return { label: `${name}（${level} 级）`, sub: '已经是最高级了', ok: false, run: null };
    }
    const cost = info.upgrades[kind][String(level + 1)];
    return {
      label: `${name}：${level} 级 → ${level + 1} 级`,
      sub: costText(cost),
      ok: canAfford(cost),
      button: '升',
      run: () => act('upgrade'),
    };
  });
}

// 建造面板：建造 / 合成 / 升级 三个标签页
function openBuildPanel(tab) {
  if (!me) return;
  const inside = me.house !== null && me.house !== undefined;
  const builds = inside ? [] : Object.entries(info.builds).map(([kind, b]) => ({
    label: b.name,
    sub: `${costText(b.cost)}　占 ${b.size}×${b.size} 格，最高 ${b.maxLevel} 级`,
    ok: canAfford(b.cost),
    button: '建',
    run: () => act('build', { kind }),
  }));
  const recipes = Object.entries(info.recipes)
    .filter(([, r]) => !r.station || r.station === 'workbench')
    .map(([id, r]) => recipeRow(id, r));
  const tabs = [
    { name: '建造', rows: builds, empty: '在屋里不能建造，先按 Q 出屋' },
    { name: '合成', rows: recipes },
    { name: '升级', rows: upgradeRows(), empty: '附近没有可以升级的东西（靠近工作台、火堆、石炉或房子）' },
  ];
  openPanel('建造与合成', tabs, tab);
}

// 设施的菜单：点工作台、火堆、石炉打开
function openStation(kind) {
  if (!me || me.work) return;
  if (kind === 'campfire') {
    const fire = Object.entries(info.recipes).filter(([, r]) => r.station === 'fire').map(([id, r]) => recipeRow(id, r));
    const wood = me.inv.wood || 0;
    openPanel('火堆', [
      { name: '烹饪', rows: fire, empty: '还没有可以做的菜' },
      { name: '加柴', rows: [{
        label: '加一根木材当柴', sub: `背包里有木材 ${wood} 根；每根能烧一会儿，火一直烧着才能做饭`,
        ok: wood > 0, button: '加', run: () => act('fuel'),
      }] },
    ], '烹饪');
  } else if (kind === 'workbench') {
    const rows = Object.entries(info.recipes).filter(([, r]) => r.station === 'workbench').map(([id, r]) => recipeRow(id, r));
    openPanel('工作台', [{ name: '合成', rows, empty: '没有可以做的东西' }], '合成');
  } else {
    const rows = Object.entries(info.recipes).filter(([, r]) => r.station === 'furnace').map(([id, r]) => recipeRow(id, r));
    openPanel('石炉', [{ name: '冶炼', rows, empty: '没有可以冶炼的东西' }], '冶炼');
  }
}

// 点互动按钮（或按 E）：附近是设施就打开它的菜单，否则做互动的事
function interactClick() {
  if (!me) return;
  if (currentStation) return openStation(currentStation);
  act('interact');
}

// ------------------------------------------------------------ 输入

function setupInput() {
  window.addEventListener('keydown', (e) => {
    if (!me || e.repeat) return;
    const k = e.key.toLowerCase();
    if (k === 'escape') { closeMenu(); return; }
    if (['w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'].includes(k)) {
      keys.add(k);
      e.preventDefault();
      sendMove();
      return;
    }
    if (!$('menu').hidden) return;                 // 菜单开着时，别的键不处理
    if (k === 'e') return interactClick();
    if (k === 'b') return openBuildPanel('建造');
    if (k === 't') return openBuildPanel('合成');
    if (k === 'c') {
      if (currentStation === 'campfire') return openStation('campfire');
      return toast('要站在火堆旁边才能烹饪');
    }
    const direct = { h: 'heal', q: 'exit', u: 'upgrade', g: 'farm', f: 'fuel' };
    if (direct[k]) { act(direct[k]); return; }
    if (k === 'x') act('craft', { recipe: 'medicine' });
  });
  window.addEventListener('keyup', (e) => { keys.delete(e.key.toLowerCase()); sendMove(); });
  window.addEventListener('blur', () => { keys.clear(); sendMove(); });

  // 禁止双击放大、捏合缩放（手机上会打断操作）
  for (const type of ['dblclick', 'gesturestart', 'gesturechange']) {
    document.addEventListener(type, (e) => e.preventDefault(), { passive: false });
  }

  // 底部按钮（建造常驻；种田、治疗、出屋只在需要时显示）和互动按钮
  const buttons = {
    build: () => openBuildPanel('建造'), farm: () => act('farm'), heal: () => act('heal'), exit: () => act('exit'),
  };
  document.querySelectorAll('#actions button').forEach((b) => {
    b.addEventListener('click', () => buttons[b.dataset.action]?.());
  });
  $('interactBtn').addEventListener('click', interactClick);
  $('menuClose').addEventListener('click', closeMenu);
  $('menu').addEventListener('click', (e) => { if (e.target.id === 'menu') closeMenu(); });

  $('invToggle').addEventListener('click', () => {
    const open = $('inv').hidden;                       // 原来收着 → 展开
    $('inv').hidden = !open;
    $('invArrow').textContent = open ? '▾' : '▸';
  });
  $('inv').addEventListener('click', (e) => {
    const d = e.target.dataset || {};
    if (d.use) send({ type: 'action', action: 'use', item: d.use });
    if (d.place) act('place', { item: d.place });
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
  const inside = me.house !== null && me.house !== undefined;

  // 人物和动物：按 100 毫秒前的时间线，在两个快照之间匀速移动
  const renderT = performance.now() - INTERP_MS;
  const ground = (x, z) => (inside ? 0 : terrainHeight(x, z));
  for (const mesh of players.values()) {
    const s = sampleAt(mesh, renderT);
    if (!s) continue;
    mesh.position.set(s.x, ground(s.x, s.z), s.z);
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
  // 火堆的火苗闪动
  for (const entry of buildings.values()) {
    entry.group.children.forEach((c) => { if (c.userData.flame) c.scale.setScalar(0.9 + 0.15 * Math.sin(t * 12 + c.position.y)); });
  }

  // 镜头盯着自己的模型（插值后的位置），再平滑地跟过去
  const mine = players.get(myId);
  const fx = mine ? mine.position.x : me.x;
  const fz = mine ? mine.position.z : me.z;
  focus.set(fx, ground(fx, fz) + 1.0, fz);
  const dist = inside ? 8 : 9, height = inside ? 9 : 5;
  const want = new THREE.Vector3(focus.x + Math.sin(yaw) * dist, focus.y + height, focus.z + Math.cos(yaw) * dist);
  camera.position.lerp(want, 1 - Math.exp(-dt * 8));
  camera.lookAt(focus);
  placeInteract();

  if (!inside) {
    // 太阳和阴影跟着镜头走：阴影只需要覆盖身边这一块，清晰又省资源
    sun.position.set(focus.x + 60, focus.y + 90, focus.z + 30);
    sun.target.position.copy(focus);
    sun.target.updateMatrixWorld();
    animateWater(t);
  }
  renderer.render(inside ? roomScene : scene, camera);
}

// 水面起伏：每个顶点高度按时间变化，法线重新计算，高光会跟着波浪动
function animateWater(t) {
  const arr = water.geometry.attributes.position.array;
  for (let i = 0; i < arr.length; i += 3) {
    const x = waterBase[i], z = waterBase[i + 2];
    arr[i + 1] = 0.035 * Math.sin(x * 0.45 + t * 1.3) + 0.025 * Math.cos(z * 0.38 - t * 1.1);
  }
  water.geometry.attributes.position.needsUpdate = true;
  water.geometry.computeVertexNormals();
}
