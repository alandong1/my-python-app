"use strict";
// ============================================================ 状态
const S = {
  ws: null, info: null, me: null, myId: null,
  known: new Map(),        // "x,y" -> {t, owner, b, lv, npc}  (记忆中的地块)
  visible: new Set(),      // 当前可见
  armies: [],
  players: {}, board: [],
  sel: null,               // 选中格子 {x, y}
  selArmy: null,           // 选中的己方部队 id
  moveMode: null,          // {army, fraction}
  cam: { x: 0, y: 0, zoom: 1 },
  centered: false,
};
const BASE = 36;
const TERRAIN_COLOR = {
  plains: "#7fa65a", forest: "#3f7a3a", hills: "#a89060",
  gold: "#c9a227", mountain: "#6b6b6b", water: "#3a6ea5",
};
const TERRAIN_DECOR = { forest: "🌲", mountain: "⛰️", gold: "✨", hills: "" };
const $ = (id) => document.getElementById(id);
const key = (x, y) => x + "," + y;
// 翻译函数（译文在 static/lang.js；切换语言见 static/i18n.js）。
// 不叫 t，因为 tilePanelHTML 里有个局部变量 t 表示地块
const tr = (zh, ...args) => i18n.t(zh, ...args);

// ============================================================ 网络
// 登录状态保存在服务器设置的 HttpOnly cookie 里，WebSocket 连接时浏览器会自动带上
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  // 页面在 /apps/lordwar/ 下，WebSocket 地址是同目录下的 ws
  const base = location.pathname.endsWith("/") ? location.pathname : location.pathname + "/";
  const ws = new WebSocket(`${proto}://${location.host}${base}ws`);
  S.ws = ws;
  ws.onopen = () => {
    $("conn").classList.add("on");
    ws.send(JSON.stringify({ type: "join" }));
  };
  ws.onclose = () => {
    $("conn").classList.remove("on");
    if (S.ws === ws && S.account) setTimeout(() => S.ws === ws && connect(), 2000);
  };
  ws.onmessage = (e) => handle(JSON.parse(e.data));
}

function send(type, data = {}) {
  if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify({ type, ...data }));
}

function handle(m) {
  if (m.type === "welcome") {
    S.info = m.info; S.myId = m.id;
    for (const [x, y, t] of m.explored) {
      const k = key(x, y);
      if (!S.known.has(k)) S.known.set(k, { t, owner: null, b: null, lv: 0, npc: null });
    }
    $("game").hidden = false;
    resize();
  } else if (m.type === "state") {
    onState(m);
  } else if (m.type === "error") {
    toast(tr(m.text));
  } else if (m.type === "auth") {
    // 登录已过期
    S.account = null; S.ws = null;
    goLogin();
  }
}

function onState(m) {
  const wasAlive = S.me && S.me.alive;
  S.me = m.me;
  S.visible = new Set();
  for (const [x, y, t, owner, b, lv, npc] of m.tiles) {
    const k = key(x, y);
    S.visible.add(k);
    S.known.set(k, { t, owner, b, lv, npc });
  }
  S.armies = m.armies;
  S.board = m.players;
  S.players = Object.fromEntries(m.players.map((p) => [p.id, p]));
  for (const e of m.events) addLog(e);
  if (S.selArmy && !S.armies.some((a) => a.id === S.selArmy)) S.selArmy = null;
  if (S.moveMode && !S.armies.some((a) => a.id === S.moveMode.army)) setMoveMode(null);
  if ((!S.centered || (wasAlive === false && S.me.alive)) && S.me.hq) {
    centerOn(...S.me.hq); S.centered = true;
  }
  $("dead").hidden = S.me.alive;
  renderTop(); renderSide();
}

// ============================================================ 渲染：地图
const canvas = $("map");
const ctx = canvas.getContext("2d");

function resize() {
  const r = canvas.getBoundingClientRect();
  canvas.width = r.width * devicePixelRatio;
  canvas.height = r.height * devicePixelRatio;
}
window.addEventListener("resize", resize);

function ts() { return BASE * S.cam.zoom; }
function centerOn(x, y) {
  const r = canvas.getBoundingClientRect();
  S.cam.x = (x + 0.5) * ts() - r.width / 2;
  S.cam.y = (y + 0.5) * ts() - r.height / 2;
}
function screenToTile(sx, sy) {
  return [Math.floor((sx + S.cam.x) / ts()), Math.floor((sy + S.cam.y) / ts())];
}

function expandable() {
  const set = new Set();
  if (!S.me || !S.me.alive) return set;
  for (const [k, t] of S.known) {
    if (t.owner !== S.myId) continue;
    const [x, y] = k.split(",").map(Number);
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const nk = key(x + dx, y + dy), n = S.known.get(nk);
      if (n && !n.owner && n.t !== "water" && n.t !== "mountain" && !(n.npc && S.visible.has(nk)))
        set.add(nk);
    }
  }
  return set;
}

function draw() {
  requestAnimationFrame(draw);
  if (!S.info) return;
  const dpr = devicePixelRatio, size = ts();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const W = canvas.width / dpr, H = canvas.height / dpr;
  ctx.fillStyle = "#0b0c0f";
  ctx.fillRect(0, 0, W, H);
  const x0 = Math.max(0, Math.floor(S.cam.x / size)), y0 = Math.max(0, Math.floor(S.cam.y / size));
  const x1 = Math.min(S.info.w - 1, Math.floor((S.cam.x + W) / size));
  const y1 = Math.min(S.info.h - 1, Math.floor((S.cam.y + H) / size));
  const px = (x) => x * size - S.cam.x, py = (y) => y * size - S.cam.y;
  const exp = expandable();

  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  // 地形 + 领地底色
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    const t = S.known.get(key(x, y));
    if (!t) continue;
    ctx.fillStyle = TERRAIN_COLOR[t.t];
    ctx.fillRect(px(x), py(y), size, size);
    const deco = TERRAIN_DECOR[t.t];
    if (deco && !t.b && size > 20) {
      ctx.globalAlpha = 0.55;
      ctx.font = `${size * 0.45}px serif`;
      ctx.fillText(deco, px(x) + size / 2, py(y) + size / 2);
      ctx.globalAlpha = 1;
    }
    if (t.owner && S.players[t.owner]) {
      ctx.fillStyle = S.players[t.owner].color;
      ctx.globalAlpha = 0.32;
      ctx.fillRect(px(x), py(y), size, size);
      ctx.globalAlpha = 1;
    }
  }
  // 网格线
  ctx.strokeStyle = "rgba(0,0,0,.18)"; ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = x0; x <= x1 + 1; x++) { ctx.moveTo(px(x), py(y0)); ctx.lineTo(px(x), py(y1 + 1)); }
  for (let y = y0; y <= y1 + 1; y++) { ctx.moveTo(px(x0), py(y)); ctx.lineTo(px(x1 + 1), py(y)); }
  ctx.stroke();
  // 领地边界
  ctx.lineWidth = Math.max(2, size / 14);
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    const t = S.known.get(key(x, y));
    if (!t || !t.owner || !S.players[t.owner]) continue;
    ctx.strokeStyle = S.players[t.owner].color;
    const edges = [[0, -1, 0, 0, 1, 0], [1, 0, 1, 0, 1, 1], [0, 1, 0, 1, 1, 1], [-1, 0, 0, 0, 0, 1]];
    ctx.beginPath();
    for (const [dx, dy, ax, ay, bx, by] of edges) {
      const n = S.known.get(key(x + dx, y + dy));
      if (n && n.owner === t.owner) continue;
      ctx.moveTo(px(x + ax), py(y + ay)); ctx.lineTo(px(x + bx), py(y + by));
    }
    ctx.stroke();
  }
  // 可拓展提示
  ctx.setLineDash([4, 4]); ctx.strokeStyle = "rgba(255,255,255,.55)"; ctx.lineWidth = 1.5;
  for (const k of exp) {
    const [x, y] = k.split(",").map(Number);
    if (x < x0 || x > x1 || y < y0 || y > y1) continue;
    ctx.strokeRect(px(x) + 3, py(y) + 3, size - 6, size - 6);
  }
  ctx.setLineDash([]);
  // 建筑、野怪
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    const k = key(x, y), t = S.known.get(k);
    if (!t) continue;
    const vis = S.visible.has(k);
    if (t.b) {
      ctx.font = `${size * (t.b === "hq" ? 0.7 : 0.55)}px serif`;
      ctx.fillText(S.info.buildings[t.b].icon, px(x) + size / 2, py(y) + size / 2);
      if (size > 22) {
        ctx.font = `bold ${size * 0.28}px sans-serif`;
        ctx.fillStyle = "#fff"; ctx.strokeStyle = "#000"; ctx.lineWidth = 3;
        ctx.strokeText(t.lv, px(x) + size * 0.82, py(y) + size * 0.18);
        ctx.fillText(t.lv, px(x) + size * 0.82, py(y) + size * 0.18);
      }
    }
    if (t.npc && vis) {
      const [type, pw, max] = t.npc;
      ctx.font = `${size * (type === "dragon" ? 0.8 : 0.6)}px serif`;
      ctx.fillText(S.info.npcs[type].icon, px(x) + size / 2, py(y) + size / 2);
      if (pw < max) {
        ctx.fillStyle = "#000"; ctx.fillRect(px(x) + 3, py(y) + size - 6, size - 6, 3);
        ctx.fillStyle = "#e5534b"; ctx.fillRect(px(x) + 3, py(y) + size - 6, (size - 6) * pw / max, 3);
      }
    }
  }
  // 战争迷雾
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    const k = key(x, y);
    if (!S.known.has(k)) continue;
    if (!S.visible.has(k)) {
      ctx.fillStyle = "rgba(10,12,18,.55)";
      ctx.fillRect(px(x), py(y), size, size);
    }
  }
  // 己方部队路线
  for (const a of S.armies) {
    if (a.owner !== S.myId || !a.path || !a.path.length) continue;
    ctx.strokeStyle = a.id === S.selArmy ? "#fff" : "rgba(255,255,255,.5)";
    ctx.setLineDash([5, 5]); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(px(a.x) + size / 2, py(a.y) + size / 2);
    for (const [x, y] of a.path) ctx.lineTo(px(x) + size / 2, py(y) + size / 2);
    ctx.stroke(); ctx.setLineDash([]);
    const [tx, ty] = a.path[a.path.length - 1];
    ctx.font = `${size * 0.4}px serif`; ctx.fillText("🚩", px(tx) + size / 2, py(ty) + size / 2);
  }
  // 部队
  const byTile = new Map();
  for (const a of S.armies) {
    const k = key(a.x, a.y);
    if (!byTile.has(k)) byTile.set(k, []);
    byTile.get(k).push(a);
  }
  for (const [k, list] of byTile) {
    const [x, y] = k.split(",").map(Number);
    list.forEach((a, i) => {
      const cx = px(x) + size * (0.3 + 0.4 * (i % 2)), cy = py(y) + size * (0.72 - 0.4 * Math.floor(i / 2));
      const r = Math.max(7, size * 0.22);
      const p = S.players[a.owner];
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = p ? p.color : "#999"; ctx.fill();
      ctx.lineWidth = a.id === S.selArmy ? 3 : 1.5;
      ctx.strokeStyle = a.id === S.selArmy ? "#fff" : "#000"; ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.font = `bold ${Math.max(9, size * 0.24)}px sans-serif`;
      ctx.strokeStyle = "#000"; ctx.lineWidth = 2.5;
      ctx.strokeText(a.size, cx, cy); ctx.fillText(a.size, cx, cy);
    });
  }
  // 选中框
  if (S.sel) {
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 2.5;
    ctx.strokeRect(px(S.sel.x) + 1, py(S.sel.y) + 1, size - 2, size - 2);
  }
  if (hover && S.moveMode) {
    ctx.strokeStyle = "#ffd34d"; ctx.lineWidth = 2;
    ctx.strokeRect(px(hover[0]) + 1, py(hover[1]) + 1, size - 2, size - 2);
  }
}
requestAnimationFrame(draw);

// ============================================================ 输入
let drag = null, hover = null;
canvas.addEventListener("pointerdown", (e) => {
  if (e.button !== 0) return;
  drag = { sx: e.clientX, sy: e.clientY, cx: S.cam.x, cy: S.cam.y, moved: false };
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointermove", (e) => {
  const r = canvas.getBoundingClientRect();
  hover = screenToTile(e.clientX - r.left, e.clientY - r.top);
  if (!drag) return;
  const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
  if (Math.abs(dx) + Math.abs(dy) > 5) drag.moved = true;
  if (drag.moved) { S.cam.x = drag.cx - dx; S.cam.y = drag.cy - dy; }
});
canvas.addEventListener("pointerup", (e) => {
  if (!drag) return;
  const moved = drag.moved;
  drag = null;
  if (moved) return;
  const r = canvas.getBoundingClientRect();
  const [x, y] = screenToTile(e.clientX - r.left, e.clientY - r.top);
  if (S.moveMode) {
    send("move", { army: S.moveMode.army, x, y, fraction: S.moveMode.fraction });
    setMoveMode(null);
    return;
  }
  selectTile(x, y);
});
canvas.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  if (!S.selArmy) return;
  const r = canvas.getBoundingClientRect();
  const [x, y] = screenToTile(e.clientX - r.left, e.clientY - r.top);
  send("move", { army: S.selArmy, x, y, fraction: e.shiftKey ? 0.5 : 1 });
});
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const r = canvas.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  const wx = (mx + S.cam.x) / ts(), wy = (my + S.cam.y) / ts();
  S.cam.zoom = Math.min(2.5, Math.max(0.35, S.cam.zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
  S.cam.x = wx * ts() - mx; S.cam.y = wy * ts() - my;
}, { passive: false });
const keys = new Set();
window.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  keys.add(e.key.toLowerCase());
  if (e.key === "Escape") { setMoveMode(null); S.selArmy = null; }
  if (e.key.toLowerCase() === "h" && S.me && S.me.hq) centerOn(...S.me.hq);
});
window.addEventListener("keyup", (e) => keys.delete(e.key.toLowerCase()));
setInterval(() => {
  const v = 14;
  if (keys.has("w") || keys.has("arrowup")) S.cam.y -= v;
  if (keys.has("s") || keys.has("arrowdown")) S.cam.y += v;
  if (keys.has("a") || keys.has("arrowleft")) S.cam.x -= v;
  if (keys.has("d") || keys.has("arrowright")) S.cam.x += v;
}, 16);

function selectTile(x, y) {
  if (x < 0 || y < 0 || x >= S.info.w || y >= S.info.h) return;
  S.sel = { x, y };
  const mine = S.armies.filter((a) => a.x === x && a.y === y && a.owner === S.myId);
  S.selArmy = mine.length ? mine[0].id : null;
  renderSide(true);
}

function setMoveMode(m) {
  S.moveMode = m;
  canvas.style.cursor = m ? "crosshair" : "";
  const h = $("hint");
  h.style.display = m ? "block" : "none";
  h.textContent = m
    ? (m.fraction < 1 ? tr("点击目标：派出一半的部队进军（Esc 取消）") : tr("点击目标：全军进军（Esc 取消）"))
    : "";
}

// ============================================================ 渲染：面板
const RES_ICON = { gold: "💰", wood: "🪵" };
function costText(cost, mult = 1) {
  return Object.entries(cost).map(([k, v]) => `${RES_ICON[k]}${Math.round(v * mult)}`).join(" ");
}
function affordable(cost, mult = 1) {
  return Object.entries(cost).every(([k, v]) => S.me.res[k] >= v * mult);
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function unitsText(units) {
  return Object.entries(units).map(([u, n]) => `${S.info.units[u].icon}${tr(S.info.units[u].name)}×${n}`).join(" ");
}
function btn(label, action, data, enabled = true, cls = "") {
  const attrs = Object.entries(data).map(([k, v]) => `data-${k}="${esc(v)}"`).join(" ");
  return `<button class="${cls}" data-action="${action}" ${attrs} ${enabled ? "" : "disabled"}>${label}</button>`;
}

function renderTop() {
  const m = S.me;
  $("gold").textContent = m.res.gold; $("wood").textContent = m.res.wood;
  $("goldInc").textContent = `+${m.income.gold}/s`; $("woodInc").textContent = `+${m.income.wood}/s`;
  const me = S.players[S.myId];
  $("tileCount").textContent = me ? me.tiles : 0;
}

const lastHTML = {};
function setHTML(id, html, force) {
  if (!force && lastHTML[id] === html) return;
  lastHTML[id] = html;
  $(id).innerHTML = html;
}

function renderSide(force = false) {
  if (!S.me || !S.info) return;
  setHTML("tilePanel", tilePanelHTML(), force);
  renderTrain(); renderResearch(); renderBoard();
}

function tilePanelHTML() {
  if (!S.sel) return `<p class="muted">${tr("点击地图上的格子查看详情")}</p>`;
  const { x, y } = S.sel, k = key(x, y), t = S.known.get(k), vis = S.visible.has(k);
  if (!t) return `<h3>(${x}, ${y})</h3><p class="muted">${tr("未探索区域。派部队过去看看吧。")}</p>`;
  const I = S.info;
  let h = `<h3>(${x}, ${y}) ${tr(I.terrainNames[t.t])}${vis ? "" : ` <small>${tr("· 迷雾中（旧情报）")}</small>`}</h3>`;
  const owner = t.owner ? S.players[t.owner] : null;
  if (owner) h += `<div class="row"><span class="swatch" style="background:${owner.color}"></span>${tr("领主：{0}", esc(owner.name))}${t.owner === S.myId ? tr("（你）") : ""}</div>`;
  else h += `<div class="row muted">${tr("无主之地")}</div>`;
  if (t.t === "hills") h += `<div class="muted">${tr("丘陵：防守方战力 ×1.25")}</div>`;
  if (t.t === "forest") h += `<div class="muted">${tr("森林：防守方战力 ×1.1")}</div>`;

  // 野怪
  if (t.npc && vis) {
    const [type, pw, max] = t.npc, n = I.npcs[type];
    h += `<div class="card"><b>${n.icon} ${tr(n.name)}</b> ${tr("战力")} ${pw}/${max}
      <div class="bar"><i style="width:${100 * pw / max}%"></i></div>
      <div class="cost">${tr("击败奖励：")}${costText(n.reward)}</div>
      <div class="muted">${tr("选中你的部队后右键这里进攻")}</div></div>`;
  }
  // 建筑
  const mine = t.owner === S.myId && S.me.alive;
  if (t.b) {
    const b = I.buildings[t.b];
    h += `<div class="card"><b>${b.icon} ${tr(b.name)}</b> Lv${t.lv}<div class="muted">${tr(b.desc)}</div>`;
    if (mine) {
      if (t.lv < I.maxLevel) {
        const c = b.cost, m = t.lv + 1;
        h += `<div class="row">${btn(tr("升级"), "upgrade", { x, y }, affordable(c, m), "primary")}<span class="cost">${costText(c, m)}</span>`;
      } else h += `<div class="row"><span class="muted">${tr("已满级")}</span>`;
      if (t.b !== "hq") h += `<span class="grow"></span>${btn(tr("拆除"), "demolish", { x, y })}`;
      h += `</div>`;
    }
    h += `</div>`;
  } else if (mine) {
    const opts = Object.entries(I.buildings).filter(([, b]) => b.buildable && (!b.terrain || b.terrain.includes(t.t)));
    if (opts.length) {
      h += `<div class="muted" style="margin-top:6px">${tr("可建造：")}</div>`;
      for (const [id, b] of opts) {
        h += `<div class="card"><div class="row"><b>${b.icon} ${tr(b.name)}</b><span class="grow"></span>
          ${btn(tr("建造"), "build", { x, y, building: id }, affordable(b.cost), "primary")}</div>
          <div class="cost">${costText(b.cost)}</div><div class="muted" style="font-size:12px">${tr(b.desc)}</div></div>`;
      }
    } else h += `<div class="muted">${tr("这种地形上没有可建造的建筑。")}</div>`;
  }
  // 拓展
  if (expandable().has(k)) {
    const c = { gold: S.me.expandCost };
    h += `<div class="row" style="margin-top:8px">${btn("🚩 " + tr("拓展领地"), "expand", { x, y }, affordable(c), "primary")}<span class="cost">${costText(c)}</span></div>`;
  }
  // 部队
  const armies = vis ? S.armies.filter((a) => a.x === x && a.y === y) : [];
  for (const a of armies) {
    const p = S.players[a.owner];
    if (a.owner === S.myId) {
      const moving = a.path && a.path.length;
      h += `<div class="card" style="${a.id === S.selArmy ? "outline:1px solid #fff" : ""}">
        <div class="row"><b>🛡️ ${tr("你的部队")}</b><span class="grow"></span>${tr("战力 {0}", a.power)}</div>
        <div style="font-size:13px">${unitsText(a.units)}</div>
        <div class="row">${btn(tr("全军出发"), "go", { army: a.id, f: 1 }, true, "primary")}
          ${btn(tr("派出一半"), "go", { army: a.id, f: 0.5 }, a.size > 1)}
          ${moving ? btn(tr("停止"), "stop", { army: a.id }) : ""}</div></div>`;
    } else {
      h += `<div class="card"><b style="color:${p ? p.color : "#ccc"}">⚔️ ${tr("{0} 的部队", esc(p ? p.name : "?"))}</b>
        <div>${tr("人数 {0} · 战力 {1}", a.size, a.power)}</div></div>`;
    }
  }
  return h;
}

function renderTrain() {
  const I = S.info, lv = S.me.barracks;
  $("barracksLv").textContent = lv ? `Lv${lv}` : tr("（未建造）");
  let h = "";
  for (const [id, u] of Object.entries(I.units)) {
    const ok = lv >= u.barracks;
    h += `<div class="card"><div class="row"><b>${u.icon} ${tr(u.name)}</b>
      <small>${tr("战力 {0}", S.me.unitPower[id])}${u.speed === 1 ? " · " + tr("快速") : u.speed >= 4 ? " · " + tr("缓慢") : ""}${u.siege ? " · " + tr("攻城") + "×" + u.siege : ""}</small></div>`;
    if (ok) {
      h += `<div class="row"><span class="cost grow">${costText(u.cost)}</span>
        ${[1, 5, 10].map((n) => btn("×" + n, "train", { unit: id, count: n }, affordable(u.cost, n))).join("")}</div>`;
    } else h += `<div class="muted">${tr("需要 {0} 级兵营", u.barracks)}</div>`;
    h += `</div>`;
  }
  setHTML("trainPanel", h);
  const q = S.me.queue.map((j) => `${I.units[j.unit].icon}${tr(I.units[j.unit].name)}×${j.count}`).join(" → ");
  $("queue").textContent = q ? tr("训练中：") + q : "";
}

function renderResearch() {
  const I = S.info, lv = S.me.smithy;
  $("smithyLv").textContent = lv ? `Lv${lv}` : tr("（未建造）");
  let h = "";
  for (const [id, r] of Object.entries(I.research)) {
    const cur = S.me.research[id], m = cur + 1;
    h += `<div class="card"><div class="row"><b>${tr(r.name)}</b> Lv${cur}<span class="grow"></span>
      ${btn(tr("研究"), "research", { kind: id }, cur < lv && affordable(r.cost, m))}</div>
      <div class="cost">${tr(r.desc)} · ${costText(r.cost, m)}${cur >= lv ? " · " + tr("需升级铁匠铺") : ""}</div></div>`;
  }
  setHTML("researchPanel", h);
}

function renderBoard() {
  const h = S.board.map((p, i) => `<div class="row"><span>${i + 1}.</span>
    <span class="swatch" style="background:${p.color}"></span>
    <span class="grow">${esc(p.name)}${p.id === S.myId ? tr("（你）") : ""}${p.alive ? "" : " 💀"}${p.online ? "" : " <small>" + tr("离线") + "</small>"}</span>
    <small>🗺️${p.tiles} 🛡️${p.army}</small></div>`).join("");
  setHTML("board", h);
}

function addLog(e) {
  const d = document.createElement("div");
  d.className = e.kind;
  d.textContent = e.text;
  const log = $("log");
  log.prepend(d);
  while (log.children.length > 60) log.lastChild.remove();
}

let toastTimer;
function toast(text, ok = false) {
  const t = $("toast");
  t.textContent = text; t.classList.add("show");
  t.classList.toggle("ok", ok);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
}

// 面板按钮（事件委托）
$("side").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-action]");
  if (!b || b.disabled) return;
  const d = b.dataset, a = d.action;
  if (a === "go") {
    S.selArmy = +d.army;
    setMoveMode({ army: +d.army, fraction: +d.f });
  } else if (a === "stop") send("stop", { army: +d.army });
  else if (a === "train") send("train", { unit: d.unit, count: +d.count });
  else if (a === "research") send("research", { kind: d.kind });
  else if (a === "build") send("build", { x: +d.x, y: +d.y, building: d.building });
  else if (a === "demolish") { if (confirm(tr("确定拆除这个建筑？"))) send("demolish", { x: +d.x, y: +d.y }); }
  else send(a, { x: +d.x, y: +d.y });
});

// ============================================================ 启动
$("homeBtn").onclick = () => S.me && S.me.hq && centerOn(...S.me.hq);
$("respawnBtn").onclick = () => send("respawn");

// 切换语言：面板是用 JS 生成的，需要按新语言重画一遍
i18n.onChange(() => {
  if (S.me && S.info) {
    renderTop(); renderSide(true);
    if (S.moveMode) setMoveMode(S.moveMode);
  }
});

// ============================================================ 登录检查
// 登录在 Dev Lab 首页完成。这里只检查是否已登录，没有就跳到首页登录，登录后再回来
function goLogin() {
  location.href = "/?login=1&next=" + encodeURIComponent(location.pathname);
}

async function boot() {
  const r = await fetch("/api/auth/me");
  if (r.status === 401) return goLogin();
  if (!r.ok) { toast(tr("服务器暂时无法访问，请稍后刷新")); return; }
  const account = await r.json();
  S.account = account;
  $("accountName").textContent = account.displayName;
  $("game").hidden = false;
  resize();
  connect();
}
boot();
