"use strict";
// Dev Lab 首页：应用商店 + 登录 + 我的账号
// 翻译函数 t() 和切换逻辑见 static/i18n.js；英文译文见 static/lang.js
const $ = (id) => document.getElementById(id);
const t = (zh, ...args) => i18n.t(zh, ...args);
const S = { account: null, apps: [], providers: [], filter: "全部", next: null, version: null };

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// 项目名、简介有中英文两个版本（来自项目登记 name_en / description_en）
function pick(zh, en) {
  return i18n.lang === "en" && en ? en : zh;
}

let toastTimer;
function toast(text, ok = false) {
  const el = $("toast");
  el.textContent = text;
  el.classList.add("show");
  el.classList.toggle("ok", ok);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}

async function api(path, body) {
  const r = await fetch("/api/auth" + path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    const err = new Error(typeof d === "string" ? t(d) : t("请求失败，请检查输入"));
    err.status = r.status;
    throw err;
  }
  return data;
}

// 只允许跳转到本站的相对路径
function safeNext(p) {
  return p && p.startsWith("/") && !p.startsWith("//") ? p : null;
}

// ============================================================ 商店
function renderFilters() {
  const cats = ["全部", ...new Set(S.apps.map((a) => a.category))];
  $("filters").innerHTML = cats.length > 2
    ? cats.map((c) => `<button data-cat="${esc(c)}" class="${c === S.filter ? "active" : ""}">${esc(t(c))}</button>`).join("")
    : "";
}

function renderGrid() {
  const apps = S.apps.filter((a) => S.filter === "全部" || a.category === S.filter);
  let h = apps.map((a) => `
    <a class="card" href="${esc(a.url)}" data-slug="${esc(a.slug)}">
      <div class="head">
        <div class="icon">${esc(a.icon)}</div>
        <div>
          <h3>${esc(pick(a.name, a.nameEn))}</h3>
          <div class="meta"><span class="badge">${esc(t(a.category))}</span><span class="badge status">${esc(t(a.status))}</span></div>
        </div>
      </div>
      <p>${esc(pick(a.description, a.descriptionEn))}</p>
      <span class="open btn primary">${esc(t("打开"))}</span>
    </a>`).join("");
  if (S.filter === "全部") {
    h += `<div class="card soon"><div class="head"><div class="icon">✨</div><div><h3>${esc(t("更多项目"))}</h3>
      <div class="meta"><span class="badge">${esc(t("开发中"))}</span></div></div></div><p>${esc(t("新的游戏、工具和 AI 项目正在路上。"))}</p></div>`;
  }
  $("grid").innerHTML = h || `<p class="empty">${esc(t("这个分类下还没有项目。"))}</p>`;
}

$("filters").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-cat]");
  if (!b) return;
  S.filter = b.dataset.cat;
  renderFilters(); renderGrid();
});

// 需要登录的项目：没登录时先弹出登录，登录后再进入
$("grid").addEventListener("click", (e) => {
  const card = e.target.closest("a.card");
  if (!card) return;
  const app = S.apps.find((a) => a.slug === card.dataset.slug);
  if (app && app.requiresLogin && !S.account) {
    e.preventDefault();
    openLogin(app.url);
  }
});

// ============================================================ 登录
function openModal(id) { $(id).hidden = false; }
function closeModals() { document.querySelectorAll(".modal").forEach((m) => { m.hidden = true; }); }
document.querySelectorAll(".modal").forEach((m) => m.addEventListener("click", (e) => {
  if (e.target === m || e.target.closest("[data-close]")) closeModals();
}));
window.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModals(); });

function renderOauth() {
  const q = S.next ? `?next=${encodeURIComponent(S.next)}` : "";
  $("oauthBtns").innerHTML = S.providers.map((p) =>
    `<a href="/api/auth/oauth/${p.id}/start${q}">${PROVIDER_ICON[p.id] || ""} ${esc(t("使用 {0} 登录", t(p.label)))}</a>`).join("");
}

function openLogin(next) {
  S.next = safeNext(next);
  $("loginErr").textContent = "";
  renderOauth();
  openModal("loginModal");
}

// 游客凭证：第一次生成后一直保存在这个浏览器的 localStorage 里
function guestKey() {
  let k = null;
  try { k = localStorage.getItem("guestKey"); } catch (e) {}
  if (!k) {
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    k = btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    try { localStorage.setItem("guestKey", k); } catch (e) {}
  }
  return k;
}

async function doLogin(fn) {
  $("loginErr").textContent = "";
  try {
    setAccount(await fn());
    if (S.next) { location.href = S.next; return; }
    closeModals();
    toast(t("登录成功"), true);
  } catch (e) {
    $("loginErr").textContent = e.message;
  }
}

$("loginBtn").onclick = () => openLogin(null);
$("guestBtn").onclick = () => doLogin(() => api("/guest", { guest_key: guestKey() }));
$("loginForm").onsubmit = (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  doLogin(() => api("/login", { username: f.get("username"), password: f.get("password") }));
};
$("registerForm").onsubmit = (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  doLogin(() => api("/register", {
    username: f.get("username"), password: f.get("password"), email: f.get("email") || null,
  }));
};
document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
  $("loginForm").hidden = b.dataset.tab !== "loginForm";
  $("registerForm").hidden = b.dataset.tab !== "registerForm";
  $("loginErr").textContent = "";
});

function setAccount(a) {
  S.account = a;
  $("loginBtn").hidden = !!a;
  $("accountBtn").hidden = !a;
  if (a) $("accountName").textContent = a.displayName;
}

// ============================================================ 我的账号
const PROVIDER_ICON = { google: "🔵", apple: "🍎", wechat: "💬" };

async function renderAccount() {
  const a = await api("/me");
  setAccount(a);
  let h = `<div class="row"><b>${esc(a.displayName)}</b>
    <span class="badge">${a.isGuest ? t("游客") : a.username ? t("正式账号") : t("第三方账号")}</span></div>`;
  if (a.username) h += `<div class="muted">${esc(t("用户名：{0}", a.username))}</div>`;
  if (a.isGuest) {
    h += `<p class="muted">${esc(t("游客身份只保存在这个浏览器里。绑定一个第三方账号后，就可以在其他设备上登录。"))}</p>`;
  } else {
    h += `<h3>${esc(t("📧 邮箱"))}</h3>`;
    if (a.email) h += `<div class="row">${esc(a.email)} <span class="badge ok">${esc(t("已验证"))}</span></div>`;
    if (a.pendingEmail) h += `<div class="row muted">${esc(a.pendingEmail)} <span class="badge">${esc(t("待验证，请查收邮件"))}</span></div>`;
    h += `<form id="emailForm" class="row"><input name="email" type="email" placeholder="${esc(a.email ? t("更换邮箱") : t("绑定邮箱"))}" required>
      <button>${esc(t("发送验证"))}</button></form>`;
  }
  if (S.providers.length) {
    h += `<h3>${esc(t("🔗 第三方账号"))}</h3>`;
    for (const p of S.providers) {
      h += a.linked.includes(p.id)
        ? `<div class="row">${PROVIDER_ICON[p.id] || ""} ${esc(t(p.label))} <span class="badge ok">${esc(t("已绑定"))}</span></div>`
        : `<div class="row">${PROVIDER_ICON[p.id] || ""} ${esc(t(p.label))} <span class="grow"></span><a href="/api/auth/oauth/${p.id}/start?link=1"><button type="button">${esc(t("绑定"))}</button></a></div>`;
    }
  }
  $("accountBody").innerHTML = h;
  const form = $("emailForm");
  if (form) form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("/email", { email: new FormData(form).get("email") });
      toast(t("验证邮件已发送，请查收"), true);
      renderAccount();
    } catch (err) { toast(err.message); }
  };
}

async function openAccount() {
  try { await renderAccount(); openModal("accountModal"); } catch (e) {
    if (e.status === 401) openLogin(null); else toast(e.message);
  }
}
$("accountBtn").onclick = openAccount;
$("logoutBtn").onclick = async () => {
  await api("/logout", {}).catch(() => {});
  setAccount(null);
  closeModals();
  toast(t("已退出登录"), true);
};

// ============================================================ 语言切换后重新渲染动态内容
// 静态文字由 i18n.js 自动替换；这里只处理用 JS 生成的部分
i18n.onChange(() => {
  renderFilters(); renderGrid();
  if (S.version) $("version").textContent = t("版本 {0}", S.version);
  if (!$("loginModal").hidden) renderOauth();
  if (!$("accountModal").hidden) renderAccount().catch(() => {});
});

// ============================================================ 启动
async function boot() {
  const q = new URLSearchParams(location.search);
  if ([...q.keys()].length) history.replaceState(null, "", "/");

  const [apps, providers, me, version] = await Promise.all([
    fetch("/api/apps").then((r) => r.json()).catch(() => ({ apps: [] })),
    api("/providers").catch(() => ({ providers: [] })),
    api("/me").catch(() => null),
    fetch("/version").then((r) => r.json()).catch(() => null),
  ]);
  S.apps = apps.apps;
  S.providers = providers.providers;
  $("oauthBox").hidden = !S.providers.length;
  setAccount(me);
  renderFilters(); renderGrid();
  if (version) { S.version = version.commit; $("version").textContent = t("版本 {0}", version.commit); }

  // 其他页面跳转过来时带的参数：login=1 打开登录；next=登录后要去的页面；account=1 打开我的账号
  const next = safeNext(q.get("next"));
  if (q.get("login")) {
    if (me && next) { location.href = next; return; }
    if (!me) openLogin(next);
  }
  if (q.get("account")) me ? openAccount() : openLogin(null);
  if (q.get("error")) toast(q.get("error"));
  if (q.get("info")) toast(q.get("info"), true);
}
boot();
