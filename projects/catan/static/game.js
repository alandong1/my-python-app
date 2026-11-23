"use strict";
// 卡坦岛的前端：大厅（创建/加入房间）+ SVG 棋盘 + 操作面板。
// 规则全部在服务器判断。这里只负责：画图、把点击转成操作、只高亮服务器说「可以点」的位置。

// ============================================================ 状态与常量
const S = {
  ws: null, room: null, game: null, config: null,
  joinCode: new URLSearchParams(location.search).get("room"),
  mode: null,            // 建造模式：road / settlement / city（只在自己的回合里有意义）
  robberHex: null,       // 强盗选中的地块，等待选择被抢的玩家
  picker: null,          // 「丰收之年」或「垄断」的资源选择：{type, chosen}
  bankPanel: false,
  tradePanel: false,
  bank: { give: null, get: null },
  offer: { give: {}, want: {} },
  discardPick: {},
};
const RES = ["brick", "lumber", "wool", "grain", "ore"];
const RES_NAME = { brick: "砖块", lumber: "木材", wool: "羊毛", grain: "粮食", ore: "矿石" };
const RES_COLOR = { brick: "#c4572e", lumber: "#2f6b35", wool: "#9dcf6a", grain: "#f0d25a", ore: "#8a949e" };
const TERRAIN_FILL = { hills: "#c4572e", forest: "#2f6b35", pasture: "#9dcf6a",
                       fields: "#f0d25a", mountains: "#8a949e", desert: "#e6cf96" };
const DEV_NAME = { knight: "骑士", vp: "胜利点", road_building: "道路建设",
                   year_of_plenty: "丰收之年", monopoly: "垄断" };
const COST = {
  road: { brick: 1, lumber: 1 },
  settlement: { brick: 1, lumber: 1, wool: 1, grain: 1 },
  city: { grain: 2, ore: 3 },
  dev: { ore: 1, wool: 1, grain: 1 },
};
const NS = "http://www.w3.org/2000/svg";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sum = (o) => Object.values(o || {}).reduce((a, b) => a + b, 0);

// ============================================================ 网络
function goLogin() {
  location.href = "/?login=1&next=" + encodeURIComponent(location.pathname);
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const base = location.pathname.endsWith("/") ? location.pathname : location.pathname + "/";
  const ws = new WebSocket(`${proto}://${location.host}${base}ws`);
  S.ws = ws;
  ws.onopen = () => $("conn").classList.add("on");
  ws.onclose = () => {
    $("conn").classList.remove("on");
    if (S.ws === ws) setTimeout(() => S.ws === ws && connect(), 2000);   // 断线自动重连，会回到原来的房间
  };
  ws.onmessage = (e) => handle(JSON.parse(e.data));
}

function send(obj) {
  if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(obj));
  else toast("连接断开了，正在重连…");
}

function act(action, data = {}) {
  send({ type: "action", action, ...data });
}

function handle(m) {
  if (m.type === "auth") return goLogin();
  if (m.type === "error") return toast(m.text);
  if (m.type !== "state") return;
  S.room = m.room;
  S.game = m.game || null;
  if (m.config) S.config = m.config;
  if (!S.room && S.joinCode) {               // 从邀请链接进来：自动加入房间
    const code = S.joinCode;
    S.joinCode = null;
    send({ type: "join", code });
    return;
  }
  if (!S.game) { S.mode = null; S.robberHex = null; S.picker = null; }
  render();
}

// ============================================================ 小提示
let toastTimer = null;
function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

// ============================================================ 渲染入口
function render() {
  $("roomTag").hidden = !(S.room && S.room.code);
  $("roomTag").textContent = S.room ? "房间 " + S.room.code : "";
  if (!S.room) {
    showOnly("lobby");
    $("roomBox").hidden = true;
    return;
  }
  if (!S.game) {
    showOnly("lobby");
    renderLobbyRoom();
    return;
  }
  showOnly("game");
  renderGame();
}

function showOnly(id) {
  $("lobby").hidden = id !== "lobby";
  $("game").hidden = id !== "game";
}

// ============================================================ 大厅
function renderLobbyRoom() {
  const r = S.room;
  $("roomBox").hidden = false;
  $("lobbyCode").textContent = r.code;
  $("lobbyPlayers").innerHTML = r.players.map((p) =>
    `<li><span class="dot ${p.online ? "on" : ""}"></span><span class="grow">${esc(p.name)}${p.isMe ? "（你）" : ""}</span>` +
    `${p.host ? '<span class="badge">房主</span>' : ""}</li>`).join("");
  const n = r.players.length;
  $("startBtn").hidden = !r.isHost;
  $("startBtn").disabled = n < r.min;
  $("lobbyHint").textContent = n < r.min
    ? `还差 ${r.min - n} 人（最多 ${r.max} 人）。把邀请链接发给朋友就行。`
    : (r.isHost ? "人数够了，房主可以开始游戏。" : "等待房主开始游戏…");
}

$("createBtn").onclick = () => send({ type: "create" });
$("joinBtn").onclick = () => {
  const code = $("codeInput").value.trim();
  if (code) send({ type: "join", code });
};
$("codeInput").onkeydown = (e) => { if (e.key === "Enter") $("joinBtn").click(); };
$("startBtn").onclick = () => send({ type: "start" });
$("leaveBtn").onclick = () => send({ type: "leave" });
$("backLobbyBtn").onclick = () => send({ type: "leave" });
$("copyBtn").onclick = async () => {
  const url = `${location.origin}${location.pathname}?room=${S.room.code}`;
  try { await navigator.clipboard.writeText(url); toast("邀请链接已复制"); }
  catch (e) { toast(url); }
};

// ============================================================ 游戏：总览
function renderGame() {
  const g = S.game;
  const me = g.me;
  if (S.mode && g.phase !== "play") S.mode = null;
  renderTurn();
  renderBoard();
  renderPlayers();
  renderHand();
  renderActions();
  renderTrade();
  renderLog();
  const over = g.phase === "ended";
  $("winner").hidden = !over;
  if (over) {
    const w = g.players[g.winner];
    $("winnerText").textContent = `🏆 ${w.name} 获胜！`;
  }
}

function seatName(seat) {
  const p = S.game.players[seat];
  return p ? p.name : "?";
}

function renderTurn() {
  const g = S.game;
  const me = g.me.seat;
  const mine = g.turn === me;
  let text;
  if (g.phase === "setup") {
    const step = g.setup.sub === "settlement" ? "放村庄" : "放道路";
    text = g.setup.seat === me
      ? `开局摆子：轮到你${step}（先放村庄，再放一条连着它的路）`
      : `开局摆子：等待 ${seatName(g.setup.seat)} ${step}`;
  } else if (g.phase === "roll") {
    text = mine ? "轮到你了：点击「掷骰子」" : `等待 ${seatName(g.turn)} 掷骰子`;
  } else if (g.phase === "play") {
    text = mine ? "你的回合：建造、交易，最后结束回合" : `${seatName(g.turn)} 的回合`;
  } else if (g.phase === "discard") {
    text = g.me.discard ? `掷出了 7！请弃掉 ${g.me.discard} 张牌` : "掷出了 7，等待其他玩家弃牌…";
  } else if (g.phase === "robber") {
    text = mine ? "请点击地图，把强盗移到一个地块上" : `${seatName(g.turn)} 正在移动强盗…`;
  } else if (g.phase === "road_building") {
    text = mine ? `道路建设：还可以免费放 ${g.roadLeft} 条路` : `${seatName(g.turn)} 正在放免费的路`;
  } else if (g.phase === "ended") {
    text = `游戏结束：${seatName(g.winner)} 获胜`;
  }
  const dice = g.dice ? `<span class="badge">🎲 ${g.dice[0]} + ${g.dice[1]} = ${g.dice[0] + g.dice[1]}</span>` : "";
  $("turnBox").innerHTML = `<div class="row" style="margin:0">${dice}<span class="grow">${esc(text)}</span></div>`;
  const h = $("hint");
  const target = currentTarget();
  h.hidden = !target;
  h.textContent = target ? targetHint(target) : "";
}

function targetHint(t) {
  if (t.kind === "hex") return "点击高亮的地块放强盗";
  if (S.mode === "settlement") return "点击高亮的角放村庄（Esc 取消）";
  if (S.mode === "city") return "点击你的村庄升级成城市";
  return t.kind === "edge" ? "点击高亮的边放路" : "点击高亮的角放置";
}

// 当前可以点击的目标：{kind: "vertex"|"edge"|"hex", ids: [...], action}
function currentTarget() {
  const g = S.game;
  const L = g.legal;
  if (!L) return null;
  if (g.phase === "setup") {
    if (g.setup.seat !== g.me.seat) return null;
    return g.setup.sub === "settlement"
      ? { kind: "vertex", ids: L.vertices, action: "setup_settlement" }
      : { kind: "edge", ids: L.edges, action: "setup_road" };
  }
  if (g.phase === "road_building") return { kind: "edge", ids: L.edges, action: "free_road" };
  if (g.phase === "robber") return { kind: "hex", ids: Object.keys(L.hexes).map(Number), action: "move_robber" };
  if (g.phase === "play") {
    if (S.mode === "road") return { kind: "edge", ids: L.edges, action: "build_road" };
    if (S.mode === "settlement") return { kind: "vertex", ids: L.vertices, action: "build_settlement" };
    if (S.mode === "city") return { kind: "vertex", ids: L.cities, action: "build_city" };
  }
  return null;
}

function onTargetClick(t, id) {
  if (t.kind === "hex") {
    S.robberHex = id;
    renderActions();
    return;
  }
  if (t.kind === "vertex") {
    act(t.action, { vertex: id });
  } else {
    act(t.action, { edge: id });
  }
  S.mode = null;
}

// ============================================================ 棋盘（SVG）
function renderBoard() {
  const b = S.game.board;
  const svg = $("board");
  svg.innerHTML = "";
  const xs = b.vertices.map((v) => v.x), ys = b.vertices.map((v) => v.y);
  const pad = 1.25;
  const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad;
  const y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
  svg.setAttribute("viewBox", `${x0} ${y0} ${x1 - x0} ${y1 - y0}`);
  const V = b.vertices;     // 顶点 id 就是下标
  const E = b.edges;
  const target = currentTarget();
  const legalSet = new Set(target ? target.ids : []);
  const root = el("g", {}, svg);
  el("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, fill: "#2b7fbb" }, root);

  // 地块
  for (const h of b.hexes) {
    const pts = h.corners.map((c) => `${V[c].x},${V[c].y}`).join(" ");
    const isTarget = target && target.kind === "hex" && legalSet.has(h.id);
    el("polygon", { points: pts, class: "hex", fill: TERRAIN_FILL[h.terrain] }, root);
    if (isTarget) {
      const hl = el("polygon", { points: pts, class: "legal-hex" }, root);
      hl.addEventListener("click", () => onTargetClick(target, h.id));
    }
  }
  // 数字圆片和强盗
  for (const h of b.hexes) {
    if (h.number) {
      const g = el("g", { class: "hex-num" }, root);
      el("circle", { cx: h.cx, cy: h.cy - 0.06, r: 0.3 }, g);
      const red = h.number === 6 || h.number === 8;
      const t = el("text", { x: h.cx, y: h.cy - 0.12, "font-size": 0.34, class: red ? "red" : "black" }, g);
      t.textContent = h.number;
      const pips = 6 - Math.abs(7 - h.number);
      for (let i = 0; i < pips; i++) {
        const x = h.cx + (i - (pips - 1) / 2) * 0.075;
        el("circle", { cx: x, cy: h.cy + 0.13, r: 0.028, fill: red ? "#b3261e" : "#222", stroke: "none" }, g);
      }
    }
  }
  // 港口：沿海岸边外侧的小标签
  for (const hb of b.harbors) {
    const e = E[hb.edge];
    const a = V[e.a], c = V[e.b];
    const mx = (a.x + c.x) / 2, my = (a.y + c.y) / 2;
    const len = Math.hypot(mx, my) || 1;
    const lx = mx + (mx / len) * 0.42, ly = my + (my / len) * 0.42;
    const g = el("g", { class: "harbor" }, root);
    el("line", { x1: a.x, y1: a.y, x2: lx, y2: ly }, g);
    el("line", { x1: c.x, y1: c.y, x2: lx, y2: ly }, g);
    el("rect", { x: lx - 0.24, y: ly - 0.12, width: 0.48, height: 0.24, rx: 0.06 }, g);
    const t = el("text", { x: lx + (hb.type === "any" ? 0 : 0.04), y: ly + 0.01, "font-size": 0.15 }, g);
    t.textContent = hb.type === "any" ? "3:1" : "2:1";
    if (hb.type !== "any") {       // 特定资源的港口：用颜色圆点标出是哪种资源
      el("circle", { cx: lx - 0.16, cy: ly, r: 0.065, fill: RES_COLOR[hb.type], stroke: "#111", "stroke-width": 0.01 }, g);
    }
  }
  // 道路
  for (const [eid, seat] of Object.entries(S.game.roads)) {
    const e = E[eid];
    const a = V[e.a], c = V[e.b];
    el("line", { x1: a.x, y1: a.y, x2: c.x, y2: c.y, class: "road-under" }, root);
    el("line", { x1: a.x, y1: a.y, x2: c.x, y2: c.y, class: "road", stroke: S.game.players[seat].color }, root);
  }
  // 村庄和城市
  for (const [vid, [seat, type]] of Object.entries(S.game.buildings)) {
    const v = V[vid];
    const color = S.game.players[seat].color;
    const shape = type === "city" ? CITY : HOUSE;
    const pts = shape.map(([dx, dy]) => `${v.x + dx},${v.y + dy}`).join(" ");
    el("polygon", { points: pts, class: "house", fill: color }, root);
  }
  // 强盗
  const rh = b.hexes[S.game.robber];
  const rg = el("g", { class: "robber" }, root);
  el("circle", { cx: rh.cx, cy: rh.cy + 0.02, r: 0.2 }, rg);
  const rt = el("text", { x: rh.cx, y: rh.cy + 0.04 }, rg);
  rt.textContent = "🥷";
  rg.setAttribute("pointer-events", "none");

  // 可点击的目标（放在最上层）
  if (target && target.kind === "edge") {
    for (const eid of target.ids) {
      const e = E[eid];
      const a = V[e.a], c = V[e.b];
      const line = el("line", { x1: a.x, y1: a.y, x2: c.x, y2: c.y, class: "legal-edge" }, root);
      line.addEventListener("click", () => onTargetClick(target, eid));
    }
  }
  if (target && target.kind === "vertex") {
    for (const vid of target.ids) {
      const v = V[vid];
      const c = el("circle", { cx: v.x, cy: v.y, r: 0.1, class: "legal-vertex" }, root);
      c.addEventListener("click", () => onTargetClick(target, vid));
    }
  }
}

const HOUSE = [[-0.13, 0.11], [-0.13, -0.03], [0, -0.16], [0.13, -0.03], [0.13, 0.11]];
const CITY = [[-0.2, 0.12], [-0.2, -0.1], [-0.08, -0.1], [-0.08, -0.2], [0.08, -0.2], [0.08, -0.1], [0.2, -0.1], [0.2, 0.12]];

function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

// ============================================================ 玩家列表
function renderPlayers() {
  const g = S.game;
  $("players").innerHTML = g.players.map((p) => {
    const badges = [
      p.longest ? '<span class="badge" title="最长道路 +2 分">🛣️ 最长道路</span>' : "",
      p.army ? '<span class="badge" title="最大骑士团 +2 分">⚔️ 最大骑士团</span>' : "",
    ].join("");
    return `<div class="player ${g.turn === p.seat ? "turn" : ""}">
      <span class="swatch" style="background:${p.color}"></span>
      <span class="grow">${esc(p.name)}${p.isMe ? "（你）" : ""}
        <small class="muted">${p.online ? "" : "· 离线"}</small></span>
      ${badges}
      <span class="badge" title="胜利点（不含手里的胜利点卡）">${p.vp} 分</span>
      <span class="badge" title="手牌数">🃏 ${p.cards}</span>
      <span class="badge" title="发展卡">🎴 ${p.devCount}</span>
    </div>`;
  }).join("");
}

// ============================================================ 手牌
function renderHand() {
  const g = S.game;
  const hand = g.me.hand;
  $("hand").innerHTML = `<div class="res-grid">${RES.map((r) =>
    `<div class="res"><i style="background:${RES_COLOR[r]}"></i>${RES_NAME[r]}<b>${hand[r]}</b></div>`).join("")}</div>`;
  const devs = Object.entries(g.me.dev).map(([k, n]) => `${DEV_NAME[k]} × ${n}`);
  const news = Object.entries(g.me.devNew).map(([k, n]) => `${DEV_NAME[k]} × ${n}（下回合可用）`);
  const all = devs.concat(news);
  $("devs").innerHTML = all.length
    ? `<div class="cards-row">${all.map((t) => `<span class="badge">🎴 ${esc(t)}</span>`).join("")}</div>`
    : `<p class="muted" style="margin:8px 0 0">没有发展卡</p>`;
}

// ============================================================ 行动面板
function costText(cost) {
  return Object.entries(cost).map(([r, n]) => `${n}${RES_NAME[r]}`).join(" ");
}

function canAfford(cost) {
  return Object.entries(cost).every(([r, n]) => S.game.me.hand[r] >= n);
}

function renderActions() {
  const g = S.game;
  const box = $("actions");
  const mine = g.turn === g.me.seat;
  const L = g.legal || {};
  let html = "";

  if (g.phase === "roll" && mine) {
    html += `<div class="actions"><button class="primary" data-act="roll">🎲 掷骰子</button></div>`;
  }
  if (g.phase === "play" && mine) {
    const bld = (kind, label, enabled, cost) =>
      `<button data-mode="${kind}" class="${S.mode === kind ? "on" : ""}" ${enabled ? "" : "disabled"}>` +
      `${label}<span class="cost">${costText(cost)}</span></button>`;
    html += `<div class="panel-title">建造</div><div class="actions">` +
      bld("road", "🛣️ 道路", (L.edges || []).length > 0 && canAfford(COST.road), COST.road) +
      bld("settlement", "🏘️ 村庄", (L.vertices || []).length > 0 && canAfford(COST.settlement), COST.settlement) +
      bld("city", "🏙️ 城市", (L.cities || []).length > 0 && canAfford(COST.city), COST.city) +
      `<button data-act="buy_dev" ${canAfford(COST.dev) ? "" : "disabled"}>🎴 发展卡<span class="cost">${costText(COST.dev)}</span></button>` +
      `</div>`;
    const plays = g.me.devPlayable || [];
    if (plays.length) {
      html += `<div class="panel-title">打出发展卡</div><div class="actions">` + plays.map((k) => {
        if (k === "knight") return `<button data-act="knight">⚔️ 骑士<span class="cost">移动强盗</span></button>`;
        if (k === "road_building") return `<button data-act="road_building">🛣️ 道路建设<span class="cost">免费放 2 条路</span></button>`;
        if (k === "year_of_plenty") return `<button data-pick="yop">🌾 丰收之年<span class="cost">从银行拿 2 张</span></button>`;
        if (k === "monopoly") return `<button data-pick="mono">💰 垄断<span class="cost">拿走一种资源</span></button>`;
        return "";
      }).join("") + `</div>`;
    }
    html += `<div class="panel-title">交易</div><div class="actions">` +
      `<button data-toggle="bank" class="${S.bankPanel ? "on" : ""}">🏦 银行交易<span class="cost">4:1 / 港口更便宜</span></button>` +
      `<button data-toggle="trade" class="${S.tradePanel ? "on" : ""}">🤝 玩家交易<span class="cost">和其他玩家换</span></button>` +
      `</div>`;
    html += `<div class="row"><button class="primary" data-act="end_turn">⏭️ 结束回合</button></div>`;
  }

  if (g.phase === "discard" && g.me.discard) {
    html += renderDiscard();
  }
  if (g.phase === "robber" && mine) {
    html += renderRobberPanel();
  }
  if (g.phase === "road_building" && mine) {
    html += `<p class="muted">点击高亮的边放免费的路（还剩 ${g.roadLeft} 条），也可以点结束回合取消。</p>`;
  }
  if (S.picker) {
    html += renderPicker();
  }
  if (S.bankPanel && g.phase === "play" && mine) html += renderBankPanel();
  if (S.tradePanel && g.phase === "play" && mine) html += tradeForm();
  box.innerHTML = html;
  bindActions(box);
}

function bindActions(box) {
  box.querySelectorAll("[data-act]").forEach((b) => {
    b.onclick = () => {
      const a = b.dataset.act;
      if (a === "end_turn") { S.mode = null; S.bankPanel = false; S.tradePanel = false; }
      act(a);
    };
  });
  box.querySelectorAll("[data-mode]").forEach((b) => {
    b.onclick = () => { S.mode = S.mode === b.dataset.mode ? null : b.dataset.mode; renderGame(); };
  });
  box.querySelectorAll("[data-toggle]").forEach((b) => {
    b.onclick = () => {
      if (b.dataset.toggle === "bank") S.bankPanel = !S.bankPanel;
      else S.tradePanel = !S.tradePanel;
      renderGame();
    };
  });
  box.querySelectorAll("[data-pick]").forEach((b) => {
    b.onclick = () => { S.picker = { type: b.dataset.pick, chosen: [] }; renderGame(); };
  });
  box.querySelectorAll("[data-robber]").forEach((b) => {
    b.onclick = () => {
      const victim = b.dataset.robber === "none" ? null : Number(b.dataset.robber);
      act("move_robber", { hex: S.robberHex, victim });
      S.robberHex = null;
    };
  });
  box.querySelectorAll("[data-pickres]").forEach((b) => {
    b.onclick = () => onPickRes(b.dataset.pickres);
  });
  box.querySelectorAll("[data-bank]").forEach((b) => {
    b.onclick = () => {
      const [kind, r] = b.dataset.bank.split(":");
      S.bank[kind] = r;
      renderGame();
    };
  });
  box.querySelectorAll("[data-bankgo]").forEach((b) => {
    b.onclick = () => act("bank_trade", { give: S.bank.give, get: S.bank.get });
  });
  box.querySelectorAll("[data-cnt]").forEach((b) => {
    b.onclick = () => onCounter(b.dataset.cnt);
  });
  const confirmDiscard = box.querySelector("#confirmDiscard");
  if (confirmDiscard) confirmDiscard.onclick = () => {
    act("discard", { cards: S.discardPick });
    S.discardPick = {};
  };
  const cancelPick = box.querySelector("#cancelPick");
  if (cancelPick) cancelPick.onclick = () => { S.picker = null; renderGame(); };
  const offerBtn = box.querySelector("[data-offer]");
  if (offerBtn) offerBtn.onclick = () => {
    act("offer_trade", { give: S.offer.give, want: S.offer.want });
    S.offer = { give: {}, want: {} };
  };
}

function renderDiscard() {
  const g = S.game;
  const need = g.me.discard;
  const pick = S.discardPick;
  const picked = sum(pick);
  const rows = RES.filter((r) => g.me.hand[r] > 0).map((r) => counterRow("discard", r, pick[r] || 0)).join("");
  return `<div class="panel-title">选择要弃掉的牌（已选 ${picked} / ${need}）</div>${rows}` +
    `<div class="row"><button class="primary" id="confirmDiscard" ${picked === need ? "" : "disabled"}>确认弃牌</button></div>`;
}

// 一行「资源名 − 数量 +」。scope 是 discard / give / want，点击由 bindActions 统一处理
function counterRow(scope, r, value) {
  return `<div class="counter"><span><i style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${RES_COLOR[r]};margin-right:6px"></i>${RES_NAME[r]}</span><span>` +
    `<button data-cnt="${scope}:${r}:-1" ${value <= 0 ? "disabled" : ""}>−</button> ` +
    `<span class="n">${value}</span> ` +
    `<button data-cnt="${scope}:${r}:1">+</button></span></div>`;
}

function renderRobberPanel() {
  const g = S.game;
  const hex = S.robberHex;
  if (hex === null || hex === undefined) return `<p class="muted">点击高亮的地块，把强盗放上去。</p>`;
  const victims = (g.legal.hexes && g.legal.hexes[hex]) || [];
  if (victims.length === 0) {
    return `<div class="row"><span>强盗放在这里（周围没有可抢的玩家）</span>` +
      `<button class="primary" data-robber="none">确定</button></div>`;
  }
  if (victims.length === 1) {
    return `<div class="row"><span>强盗放在这里，抢 ${esc(seatName(victims[0]))} 一张牌</span>` +
      `<button class="primary" data-robber="${victims[0]}">确定</button></div>`;
  }
  return `<div class="panel-title">选择要抢劫的玩家</div><div class="actions">` +
    victims.map((s) => `<button data-robber="${s}">${esc(seatName(s))}</button>`).join("") + `</div>`;
}

function renderPicker() {
  const p = S.picker;
  const need = p.type === "yop" ? 2 : 1;
  const title = p.type === "yop" ? "丰收之年：选两种资源，从银行拿取" : "垄断：选一种资源，其他人的这种资源全部给你";
  const chosen = p.chosen.map((r) => RES_NAME[r]).join("、") || "（还没选）";
  return `<div class="trade-offer"><div>${title}</div><div class="muted">已选：${chosen}</div>` +
    `<div class="actions">${RES.map((r) => `<button data-pickres="${r}"><i style="display:inline-block;width:12px;height:12px;background:${RES_COLOR[r]};border-radius:3px;margin-right:4px"></i>${RES_NAME[r]}</button>`).join("")}</div>` +
    `<div class="row"><button data-cancelpick="1" id="cancelPick">取消</button><span class="muted">需要选 ${need} 种</span></div></div>`;
}

// 计数器的加减：discard 有手牌和弃牌数量限制；give/want 是交易表单
function onCounter(key) {
  const [scope, r, d] = key.split(":");
  const delta = Number(d);
  const g = S.game;
  if (scope === "discard") {
    const cur = S.discardPick[r] || 0;
    if (delta > 0 && (cur >= g.me.hand[r] || sum(S.discardPick) >= g.me.discard)) return;
    if (delta < 0 && cur <= 0) return;
    S.discardPick[r] = cur + delta;
  } else {
    const cur = S.offer[scope][r] || 0;
    const max = scope === "give" ? g.me.hand[r] : 9;
    S.offer[scope][r] = Math.max(0, Math.min(max, cur + delta));
  }
  renderGame();
}

function onPickRes(r) {
  const p = S.picker;
  if (!p) return;
  if (p.type === "mono") {
    S.picker = null;
    act("monopoly", { resource: r });
    return;
  }
  p.chosen.push(r);
  if (p.chosen.length === 2) {
    S.picker = null;
    act("year_of_plenty", { first: p.chosen[0], second: p.chosen[1] });
    return;
  }
  renderGame();
}

function renderBankPanel() {
  const g = S.game;
  const bk = S.bank;
  const give = bk.give, get = bk.get;
  const rate = give ? g.me.rates[give] : null;
  const ok = give && get && give !== get && g.me.hand[give] >= rate && g.bank[get] >= 1;
  const giveBtns = RES.map((r) => `<button class="${give === r ? "on" : ""}" data-bank="give:${r}">${RES_NAME[r]}（${g.me.rates[r]}:1）</button>`).join("");
  const getBtns = RES.map((r) => `<button class="${get === r ? "on" : ""}" data-bank="get:${r}" ${r === give ? "disabled" : ""}>${RES_NAME[r]}</button>`).join("");
  return `<div class="trade-offer"><div class="panel-title">我想用……换银行的……</div>` +
    `<div class="actions">${giveBtns}</div><div class="actions" style="margin-top:6px">${getBtns}</div>` +
    `<div class="row"><button class="primary" data-bankgo="1" ${ok ? "" : "disabled"}>交换 1 张</button>` +
    `<span class="muted">${give && get ? (ok ? `用 ${rate} 张${RES_NAME[give]}换 1 张${RES_NAME[get]}` : "手牌或银行数量不够") : "先选要给出和要换的资源"}</span></div></div>`;
}

// ============================================================ 玩家交易
function renderTrade() {
  const g = S.game;
  const t = g.trade;
  const box = $("tradeBox");
  const mine = g.turn === g.me.seat;
  if (t) {
    const from = t.from;
    const giveTxt = resText(t.give), wantTxt = resText(t.want);
    if (t.from === g.me.seat) {
      const acc = t.accepted.length
        ? t.accepted.map((s) => `<button data-partner="${s}">与 ${esc(seatName(s))} 成交</button>`).join(" ")
        : `<span class="muted">等待其他玩家同意…</span>`;
      box.innerHTML = `<h3>🤝 你的交易提议</h3><div class="trade-offer">你给出 ${giveTxt}，换 ${wantTxt}</div>` +
        `<div class="row">${acc}</div><div class="row"><button id="cancelTrade">取消提议</button></div>`;
    } else {
      const myHand = g.me.hand;
      const canAccept = Object.entries(t.want).every(([r, n]) => myHand[r] >= n);
      const already = t.accepted.includes(g.me.seat);
      box.innerHTML = `<h3>🤝 ${esc(seatName(from))} 的交易提议</h3>` +
        `<div class="trade-offer">他给出 ${giveTxt}，想要你的 ${wantTxt}</div>` +
        `<div class="row"><button class="primary" id="acceptTrade" ${canAccept && !already ? "" : "disabled"}>` +
        `${already ? "已同意，等待对方确认" : canAccept ? "同意交易" : "你的牌不够"}</button></div>`;
    }
    box.hidden = false;
    const cancel = $("cancelTrade");
    if (cancel) cancel.onclick = () => act("cancel_trade");
    const acceptBtn = $("acceptTrade");
    if (acceptBtn) acceptBtn.onclick = () => act("accept_trade");
    box.querySelectorAll("[data-partner]").forEach((b) => {
      b.onclick = () => act("confirm_trade", { partner: Number(b.dataset.partner) });
    });
    return;
  }
  box.hidden = true;
  box.innerHTML = "";
}

// 发起交易的表单（显示在行动面板的「玩家交易」展开后）
function tradeForm() {
  const g = S.game;
  const give = RES.map((r) => counterRow("give", r, S.offer.give[r] || 0)).join("");
  const want = RES.map((r) => counterRow("want", r, S.offer.want[r] || 0)).join("");
  const ok = sum(S.offer.give) > 0 && sum(S.offer.want) > 0 && !g.trade;
  return `<div class="trade-offer"><div class="panel-title">我给出</div>${give}` +
    `<div class="panel-title">我想要</div>${want}` +
    `<div class="row"><button class="primary" data-offer="1" ${ok ? "" : "disabled"}>发起交易提议</button>` +
    `<span class="muted">${g.trade ? "已有一个交易在进行中" : "其他玩家同意后，你再选择和谁成交"}</span></div></div>`;
}

function resText(o) {
  return Object.entries(o).filter(([, n]) => n > 0).map(([r, n]) => `${n} 张${RES_NAME[r]}`).join("、") || "无";
}

// ============================================================ 战报
function renderLog() {
  const box = $("log");
  const lines = S.game.log.slice(-40);
  box.innerHTML = lines.map((l) => `<div>${esc(l)}</div>`).join("");
  box.scrollTop = box.scrollHeight;
}

// ============================================================ 键盘
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && S.mode) { S.mode = null; renderGame(); }
});

// ============================================================ 启动
async function boot() {
  const r = await fetch("/api/auth/me");
  if (r.status === 401) return goLogin();
  if (!r.ok) { toast("服务器暂时无法访问，请稍后刷新"); return; }
  const account = await r.json();
  $("accountName").textContent = account.displayName;
  connect();
}
boot();
