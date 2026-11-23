/* 大陆争霸 · 前端
 * 服务器算所有东西，这里只负责：画地图、把玩家的点击变成命令、定时刷新状态。
 * 所有来自服务器的文字都先经过 esc() 转义再放进 innerHTML。
 */
(() => {
  "use strict";

  const API = "/apps/continent/api/";
  const ZOOMS = [10, 14, 16, 20, 26];
  const TERRAIN_COLOR = { w: "#2a6fb0", p: "#c9b77a", f: "#4e7a3a", m: "#7d7f86", "?": "#07080a" };
  const TERRAIN_NAME = { w: "海", p: "平原", f: "森林", m: "山地" };

  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // 只有内容真的变了才替换 DOM：每秒刷新时，按钮不会被换掉，点击不会丢。
  function put(el, html) {
    if (el._html !== html) {
      el._html = html;
      el.innerHTML = html;
    }
  }

  const canvas = $("#map");
  const ctx = canvas.getContext("2d");

  const S = {
    data: null,          // 最新的服务器状态
    cat: null,           // 数值目录（只取一次）
    sel: new Set(),      // 选中的单位 id
    mode: null,          // null | "build" | "relocate"
    buildKind: null,
    tile: null,          // 点击查看的格子 [x, y]
    hover: null,
    drag: null,          // 框选：{x0,y0,x1,y1,sx,sy,moved}
    zoomIdx: 2,
  };

  // ------------------------------------------------------------ 网络

  async function api(path, body) {
    const opt = body
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : {};
    let r;
    try {
      r = await fetch(API + path, { credentials: "same-origin", cache: "no-store", ...opt });
    } catch (e) {
      setConn(false);
      throw new Error("网络连接失败");
    }
    if (r.status === 401) {
      location.href = "/?login=1&next=" + encodeURIComponent(location.pathname);
      throw new Error("请先登录");
    }
    setConn(true);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || data.detail || "操作失败");
    return data;
  }

  function setConn(ok) {
    const dot = $("#conn");
    dot.className = "dot " + (ok ? "ok" : "bad");
    dot.title = ok ? "已连接" : "连接断开，正在重试";
  }

  async function command(action, args = {}) {
    try {
      apply(await api("command", { action, ...args }));
    } catch (e) {
      toast(e.message);
    }
  }

  async function refresh() {
    try {
      apply(await api("state"));
    } catch (e) {
      if (!state_ok()) toast(e.message);
    }
  }
  const state_ok = () => $("#conn").classList.contains("ok");

  function apply(data) {
    S.data = data;
    // 选中的单位如果已经不存在了（死了、看不见了），去掉
    const alive = new Set(data.units.filter((u) => u.mine).map((u) => u.id));
    for (const id of [...S.sel]) if (!alive.has(id)) S.sel.delete(id);
    render();
  }

  // ------------------------------------------------------------ 工具函数

  const D = () => S.data;
  const tileIdx = (x, y) => y * D().w + x;
  const isVisible = (x, y) => D().visible[tileIdx(x, y)] === "1";
  const unitDef = (k) => S.cat.units[k];
  const bldDef = (k) => S.cat.buildings[k];
  const icon = (k) => (unitDef(k) || bldDef(k) || { icon: "❔" }).icon;
  const nameOf = (k) => (unitDef(k) || bldDef(k) || { name: k }).name;
  const playerOf = (id) => D().players.find((p) => p.id === id);
  const colorOf = (id) => (playerOf(id) || { color: "#888" }).color;
  const nameOfPlayer = (id) => (playerOf(id) || { name: "?" }).name;

  function entitiesAt(x, y) {
    const d = D();
    const units = d.units.filter((u) => u.x === x && u.y === y);
    const blds = d.buildings.filter((b) => b.x === x && b.y === y);
    return { units, blds };
  }

  // 点击一格：如果有自己的单位，优先选中自己的；否则是敌人（且看得见）
  function enemyAt(x, y) {
    const { units, blds } = entitiesAt(x, y);
    const u = units.find((e) => !e.mine);
    if (u) return u;
    return blds.find((b) => !b.mine) || null;
  }

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => (t.hidden = true), 2600);
  }

  function relocateCost(x, y) {
    const hq = D().me.hq;
    if (!hq || !S.cat) return null;
    const dist = Math.hypot(x - hq[0], y - hq[1]);
    return Math.round(S.cat.relocate.base + S.cat.relocate.perTile * dist);
  }

  // ------------------------------------------------------------ 画地图

  function render() {
    if (!D()) return;
    renderMap();
    renderTop();
    renderSide();
  }

  function renderMap() {
    const d = D();
    const T = ZOOMS[S.zoomIdx];
    const W = d.w, H = d.h;
    canvas.width = W * T;
    canvas.height = H * T;
    canvas.style.width = W * T + "px";
    canvas.style.height = H * T + "px";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    // 地形
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const t = d.terrain[tileIdx(x, y)];
        ctx.fillStyle = TERRAIN_COLOR[t] || "#000";
        ctx.fillRect(x * T, y * T, T, T);
      }
    }
    if (T >= 14) {
      ctx.strokeStyle = "rgba(0,0,0,.08)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = 0; x <= W; x++) { ctx.moveTo(x * T + .5, 0); ctx.lineTo(x * T + .5, H * T); }
      for (let y = 0; y <= H; y++) { ctx.moveTo(0, y * T + .5); ctx.lineTo(W * T, y * T + .5); }
      ctx.stroke();
    }

    // 矿点
    ctx.fillStyle = "#ffd54a";
    for (const i of d.ore) {
      const x = i % W, y = Math.floor(i / W);
      ctx.beginPath();
      ctx.moveTo(x * T + T / 2, y * T + T * .2);
      ctx.lineTo(x * T + T * .8, y * T + T / 2);
      ctx.lineTo(x * T + T / 2, y * T + T * .8);
      ctx.lineTo(x * T + T * .2, y * T + T / 2);
      ctx.closePath();
      ctx.fill();
    }

    // 迷雾：看过但现在看不见的，压暗
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const i = tileIdx(x, y);
        if (d.terrain[i] !== "?" && d.visible[i] !== "1") {
          ctx.fillStyle = "rgba(0,0,0,.45)";
          ctx.fillRect(x * T, y * T, T, T);
        }
      }
    }

    // 建筑
    ctx.font = `${Math.floor(T * .8)}px "Apple Color Emoji","Segoe UI Emoji",sans-serif`;
    for (const b of d.buildings) {
      const px = b.x * T, py = b.y * T;
      ctx.fillStyle = b.owner === d.me.id ? "rgba(255,255,255,.18)" : "rgba(0,0,0,.25)";
      ctx.fillRect(px + 1, py + 1, T - 2, T - 2);
      ctx.strokeStyle = colorOf(b.owner);
      ctx.lineWidth = Math.max(2, T / 7);
      ctx.strokeRect(px + 1, py + 1, T - 2, T - 2);
      ctx.fillStyle = "#fff";
      ctx.fillText(icon(b.kind), px + T / 2, py + T / 2 + 1);
      drawHp(b, px, py, T);
    }

    // 单位
    for (const u of d.units) {
      const cx = u.x * T + T / 2, cy = u.y * T + T / 2;
      ctx.beginPath();
      ctx.arc(cx, cy, T * .42, 0, Math.PI * 2);
      ctx.fillStyle = colorOf(u.owner);
      ctx.globalAlpha = .85;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#fff";
      ctx.fillText(icon(u.kind), cx, cy + 1);
      if (S.sel.has(u.id)) {
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(cx, cy, T * .5, 0, Math.PI * 2);
        ctx.stroke();
      }
      drawHp(u, u.x * T, u.y * T, T);
    }

    // 搬迁目标
    if (d.me.relocating) {
      const r = d.me.relocating;
      ctx.strokeStyle = "#ffd54a";
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 2;
      ctx.strokeRect(r.x * T + 2, r.y * T + 2, T - 4, T - 4);
      ctx.setLineDash([]);
    }

    // 鼠标指向的格子（建造和搬迁时显示）
    if (S.hover && (S.mode || S.drag)) {
      ctx.strokeStyle = "rgba(255,255,255,.9)";
      ctx.lineWidth = 2;
      ctx.strokeRect(S.hover[0] * T + 1, S.hover[1] * T + 1, T - 2, T - 2);
    }
    // 框选的矩形
    if (S.drag && S.drag.moved) {
      const x0 = Math.min(S.drag.sx, S.drag.ex), x1 = Math.max(S.drag.sx, S.drag.ex);
      const y0 = Math.min(S.drag.sy, S.drag.ey), y1 = Math.max(S.drag.sy, S.drag.ey);
      ctx.strokeStyle = "#fff";
      ctx.setLineDash([5, 4]);
      ctx.strokeRect(x0 * T, y0 * T, (x1 - x0 + 1) * T, (y1 - y0 + 1) * T);
      ctx.setLineDash([]);
    }
  }

  function drawHp(e, px, py, T) {
    if (e.hp >= e.maxhp) return;
    const w = T - 4, frac = Math.max(0, e.hp / e.maxhp);
    ctx.fillStyle = "rgba(0,0,0,.6)";
    ctx.fillRect(px + 2, py + 1, w, 3);
    ctx.fillStyle = frac > .5 ? "#5fd389" : frac > .25 ? "#f1c40f" : "#ff6b5b";
    ctx.fillRect(px + 2, py + 1, w * frac, 3);
  }

  // ------------------------------------------------------------ 顶部和侧边栏

  function renderTop() {
    const me = D().me;
    $("#gold").textContent = me.gold;
    $("#income").textContent = `+${me.income}/秒`;
    $("#time").textContent = `${D().tick} 秒`;
  }

  function renderSide() {
    renderBanner();
    renderSelection();
    renderTile();
    renderBuild();
    renderProduction();
    renderResearch();
    renderBase();
    renderPlayers();
  }

  function renderBanner() {
    const b = $("#banner");
    if (!S.mode) { b.hidden = true; return; }
    b.hidden = false;
    if (S.mode === "build") {
      $("#bannerText").textContent = `建造：${nameOf(S.buildKind)}，点击地图上的空地`;
    } else {
      const cost = S.hover ? relocateCost(S.hover[0], S.hover[1]) : null;
      $("#bannerText").textContent = cost
        ? `搬迁基地：点击目标格（这里约 ${cost} 金币）`
        : "搬迁基地：点击地图上的空地作为新基地";
    }
  }

  function renderSelection() {
    const el = $("#selection");
    const units = D().units.filter((u) => u.mine && S.sel.has(u.id));
    if (!units.length) {
      put(el, '<p class="muted">框选或点击自己的单位。选中后，点空地是移动，点敌人是攻击。</p>');
      return;
    }
    const rows = units.map((u) => `
      <div class="row">
        <span class="name">${icon(u.kind)} ${esc(nameOf(u.kind))}</span>
        <span class="bar"><i style="width:${Math.max(0, 100 * u.hp / u.maxhp)}%"></i></span>
        <span class="tag">${u.hp}/${u.maxhp}</span>
      </div>`).join("");
    put(el, `<p class="muted">已选 ${units.length} 个单位</p>${rows}
      <div class="row"><button class="small" data-act="deselect">取消选择</button></div>`);
  }

  function renderTile() {
    const el = $("#tileInfo");
    if (!S.tile) { put(el, '<p class="muted">点击地图查看。</p>'); return; }
    const [x, y] = S.tile;
    const i = tileIdx(x, y);
    const t = D().terrain[i];
    const lines = [`<div class="row"><span class="name">坐标 (${x}, ${y})</span></div>`];
    if (t === "?") {
      lines.push('<p class="muted">还没有探索过。派侦察机去看看吧。</p>');
    } else {
      const extra = D().ore.includes(i) ? "（矿点）" : "";
      lines.push(`<div class="row"><span class="name">${esc(TERRAIN_NAME[t])}${extra}</span></div>`);
      if (!isVisible(x, y)) lines.push('<p class="muted">现在看不见这里，显示的是上次看到的地形。</p>');
      const { units, blds } = entitiesAt(x, y);
      for (const b of blds) {
        lines.push(`<div class="row"><span class="swatch" style="background:${esc(colorOf(b.owner))}"></span>
          <span class="name">${icon(b.kind)} ${esc(nameOf(b.kind))}</span>
          <span class="tag">${esc(nameOfPlayer(b.owner))}</span></div>`);
      }
      for (const u of units) {
        lines.push(`<div class="row"><span class="swatch" style="background:${esc(colorOf(u.owner))}"></span>
          <span class="name">${icon(u.kind)} ${esc(nameOf(u.kind))}</span>
          <span class="tag">${esc(nameOfPlayer(u.owner))}</span></div>`);
      }
    }
    put(el, lines.join(""));
  }

  function reqText(kind) {
    const def = bldDef(kind);
    if (!def.requires) return "";
    return `需要${nameOf(def.requires)}`;
  }

  function renderBuild() {
    const me = D().me;
    const owned = new Set(D().buildings.filter((b) => b.mine).map((b) => b.kind));
    const rows = Object.entries(S.cat.buildings)
      .filter(([k]) => k !== "hq")
      .map(([k, def]) => {
        const need = def.requires && !owned.has(def.requires);
        const disabled = need || me.gold < def.cost;
        const hint = [reqText(k), def.ore ? "需建在矿点" : "", def.shore ? "需靠海" : ""]
          .filter(Boolean).join("，");
        const active = S.mode === "build" && S.buildKind === k ? " primary" : "";
        return `<div class="row">
          <span class="name">${def.icon} ${esc(def.name)} <span class="tag">${esc(hint)}</span></span>
          <button class="small${active}" data-build="${k}" ${disabled ? "disabled" : ""}>${def.cost} 金</button>
        </div>`;
      }).join("");
    put($("#buildList"), rows);
  }

  function renderProduction() {
    const me = D().me;
    const blds = D().buildings.filter((b) => b.mine && (bldDef(b.kind).produces || []).length);
    if (!blds.length) {
      put($("#prodList"), '<p class="muted">你还没有可以生产单位的建筑。</p>');
      return;
    }
    put($("#prodList"), blds.map((b) => {
      const def = bldDef(b.kind);
      const queue = (b.queue || []).map((q, idx) => `
        <div class="queue">▶ ${esc(nameOf(q.kind))} 还需 ${q.left} 秒
          <button class="small" data-cancel="${b.id}|${idx}">取消</button></div>`).join("");
      const btns = def.produces.map((k) => {
        const u = unitDef(k);
        const full = (b.queue || []).length >= S.cat.queueMax;
        const disabled = me.gold < u.cost || full;
        return `<button class="small" data-train="${b.id}|${k}" ${disabled ? "disabled" : ""}
          title="${esc(u.name)}：${u.time} 秒">${u.icon} ${esc(u.name)} ${u.cost}金</button>`;
      }).join(" ");
      return `<div class="card"><h4>${def.icon} ${esc(def.name)}</h4>
        ${queue || '<p class="muted">空闲</p>'}<div class="row">${btns}</div></div>`;
    }).join(""));
  }

  function renderResearch() {
    const me = D().me;
    const RES = S.cat.research;
    put($("#researchList"), Object.entries(RES).map(([cls, label]) => {
      const r = me.research[cls];
      const stars = "★".repeat(r.level) + "☆".repeat(S.cat.researchMax - r.level);
      const maxed = r.nextCost == null;
      const disabled = maxed || !me.hq || me.gold < r.nextCost;
      const btn = maxed ? "已满级" : `升级 ${r.nextCost} 金`;
      return `<div class="row">
        <span class="name">${esc(label)} <span class="tag">${stars}</span></span>
        <button class="small" data-research="${cls}" ${disabled ? "disabled" : ""}>${btn}</button>
      </div>`;
    }).join("") + '<p class="muted">升级会加强同类所有单位：攻击 +20%/级，生命 +10%/级。</p>');
  }

  function renderBase() {
    const me = D().me;
    const lines = [];
    if (me.hq) {
      lines.push(`<p class="muted">主基地在 (${me.hq[0]}, ${me.hq[1]})</p>`);
    } else {
      lines.push('<p class="muted">💀 你的基地被毁了，单位和建筑还在。</p>');
    }
    if (me.relocating) {
      lines.push(`<p class="muted">搬迁中，还需 ${me.relocating.left} 秒，去 (${me.relocating.x}, ${me.relocating.y})</p>`);
    }
    if (me.hq) {
      const cd = me.relocateReady;
      const r = S.cat.relocate;
      const busy = !!me.relocating || cd > 0;
      const tip = cd > 0 ? `冷却中，还需 ${cd} 秒` : me.relocating ? "正在搬迁" : "";
      lines.push(`<div class="row">
        <button class="small${S.mode === "relocate" ? " primary" : ""}" data-relocate="1" ${busy ? "disabled" : ""}>
          🚚 搬迁基地</button>
        <span class="tag">${esc(tip) || `${r.base} + ${r.perTile}金/格，${r.time}秒`}</span></div>`);
    } else {
      lines.push('<div class="row"><button class="small primary" data-respawn="1">🏗️ 重建基地（+500 金）</button></div>');
    }
    put($("#baseInfo"), lines.join(""));
  }

  function renderPlayers() {
    put($("#playerList"), D().players.map((p) => `
      <div class="row">
        <span class="swatch" style="background:${esc(p.color)}"></span>
        <span class="name">${esc(p.name)}${p.id === D().me.id ? "（你）" : ""}</span>
        <span class="tag">${p.hasHq ? "基地在" : "基地已毁"}</span>
      </div>`).join("") || '<p class="muted">还没有玩家</p>');
  }

  // ------------------------------------------------------------ 鼠标和键盘

  function tileFromEvent(e) {
    const rect = canvas.getBoundingClientRect();
    const T = ZOOMS[S.zoomIdx];
    const x = Math.floor((e.clientX - rect.left) / T);
    const y = Math.floor((e.clientY - rect.top) / T);
    if (x < 0 || y < 0 || x >= D().w || y >= D().h) return null;
    return [x, y];
  }

  function onMouseDown(e) {
    if (e.button !== 0 || !D()) return;
    const t = tileFromEvent(e);
    if (!t) return;
    S.drag = { sx: t[0], sy: t[1], ex: t[0], ey: t[1], moved: false, shift: e.shiftKey };
  }

  function onMouseMove(e) {
    const t = tileFromEvent(e);
    const prev = S.hover;
    S.hover = t;
    if (S.drag && t) {
      // 鼠标离开起点的格子，就算框选（否则是点击）
      if (t[0] !== S.drag.sx || t[1] !== S.drag.sy) S.drag.moved = true;
      S.drag.ex = t[0];
      S.drag.ey = t[1];
    }
    if (S.mode || S.drag || (prev && t && (prev[0] !== t[0] || prev[1] !== t[1]))) render();
    if (S.mode === "relocate") renderBanner();
  }

  function onMouseUp(e) {
    const drag = S.drag;
    S.drag = null;
    if (!drag || e.button !== 0) return;
    const t = tileFromEvent(e) || [drag.sx, drag.sy];
    if (drag.moved) {
      // 框选：选中矩形里自己的单位
      const x0 = Math.min(drag.sx, t[0]), x1 = Math.max(drag.sx, t[0]);
      const y0 = Math.min(drag.sy, t[1]), y1 = Math.max(drag.sy, t[1]);
      const picked = D().units.filter((u) => u.mine && u.x >= x0 && u.x <= x1 && u.y >= y0 && u.y <= y1);
      if (!drag.shift) S.sel.clear();
      picked.forEach((u) => S.sel.add(u.id));
      if (!picked.length) toast("框里没有自己的单位");
      render();
      return;
    }
    clickTile(t[0], t[1], drag.shift);
  }

  function clickTile(x, y, shift) {
    if (S.mode === "build") {
      command("build", { kind: S.buildKind, x, y });
      exitMode();
      return;
    }
    if (S.mode === "relocate") {
      command("relocate", { x, y });
      exitMode();
      return;
    }
    const { units } = entitiesAt(x, y);
    const own = units.filter((u) => u.mine);
    if (own.length) {
      if (!shift) S.sel.clear();
      for (const u of own) {
        if (shift && S.sel.has(u.id)) S.sel.delete(u.id);   // 按住 Shift 可以加选或取消
        else S.sel.add(u.id);
      }
      S.tile = [x, y];
      render();
      return;
    }
    if (S.sel.size) {
      issueOrder(x, y);
      return;
    }
    S.tile = [x, y];
    render();
  }

  function issueOrder(x, y) {
    const ids = [...S.sel];
    if (!ids.length) { toast("先框选或点击自己的单位"); return; }
    const enemy = enemyAt(x, y);
    if (enemy) {
      command("attack", { units: ids, target: enemy.id });
    } else {
      command("move", { units: ids, x, y });
    }
  }

  function exitMode() {
    S.mode = null;
    S.buildKind = null;
    render();
  }

  canvas.addEventListener("mousedown", onMouseDown);
  canvas.addEventListener("mousemove", onMouseMove);
  canvas.addEventListener("mouseleave", () => { S.hover = null; if (D()) render(); });
  window.addEventListener("mouseup", onMouseUp);
  canvas.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    const t = tileFromEvent(e);
    if (t && S.sel.size && !S.mode) issueOrder(t[0], t[1]);
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      S.sel.clear();
      exitMode();
    }
  });

  // 侧边栏的按钮：统一用事件委托处理
  $("#side").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn || btn.disabled) return;
    const ds = btn.dataset;
    if (ds.act === "deselect") { S.sel.clear(); render(); }
    else if (ds.build) { S.mode = "build"; S.buildKind = ds.build; render(); }
    else if (ds.train) {
      const [bid, kind] = ds.train.split("|");
      command("train", { building: Number(bid), kind });
    } else if (ds.cancel) {
      const [bid, index] = ds.cancel.split("|");
      command("cancel", { building: Number(bid), index: Number(index) });
    } else if (ds.research) command("research", { cls: ds.research });
    else if (ds.relocate) { S.mode = "relocate"; render(); }
    else if (ds.respawn) command("respawn");
  });
  $("#cancelMode").addEventListener("click", exitMode);

  $("#zoomIn").addEventListener("click", () => { S.zoomIdx = Math.min(ZOOMS.length - 1, S.zoomIdx + 1); if (D()) render(); });
  $("#zoomOut").addEventListener("click", () => { S.zoomIdx = Math.max(0, S.zoomIdx - 1); if (D()) render(); });

  // ------------------------------------------------------------ 启动

  async function start() {
    try {
      S.cat = await api("catalog");
    } catch (e) {
      toast(e.message);
      return;
    }
    await refresh();
    setInterval(refresh, 1000);
  }
  start();
})();
