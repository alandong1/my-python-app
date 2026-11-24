/* 记账本前端。
 *
 * 截图识别流程：快速双击页面空白处（或点按钮）→ 截图 → 用 Tesseract.js 在浏览器里识别文字
 * → 服务器从文字里挑出可能的金额（/api/parse-numbers）→ 用户点一个数字填进金额。
 *
 * 为什么不自动决定金额：屏幕上的数字很多（时间、订单号、余额……），自动猜错的代价
 * 比多点一下的麻烦大，所以让用户来选。
 */
(function () {
  "use strict";

  // 文字识别引擎（Tesseract.js 5.1.1，运行在浏览器里，不占服务器资源）
  const TESSERACT_URL = "https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js";
  const MAX_SIDE = 2000;        // 图片最长边超过这个像素数就缩小，识别更快
  const DOUBLE_TAP_MS = 350;    // 两次点击间隔不超过这个时间，算双击
  const DOUBLE_TAP_PX = 40;     // 两次点击位置相差不超过这么多像素，算同一个地方

  const $ = (id) => document.getElementById(id);
  let kind = "expense";         // 当前选的类型：expense 支出 / income 收入
  let categories = { expense: [], income: [] };
  let sourceOfNext = "manual";  // 下一笔账的来源；截图识别填进金额后改成 screenshot
  let capturing = false;
  let previewUrl = null;

  // ------------------------------------------------------------ 通用工具

  async function api(path, options = {}) {
    const res = await fetch("api/" + path, {
      method: options.method || "GET",
      headers: options.body ? { "Content-Type": "application/json" } : {},
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: "no-store",
    });
    if (res.status === 401) {
      // 没登录：跳到平台的登录框，登录后回到这个页面
      location.href = "/?login=1&next=" + encodeURIComponent(location.pathname);
      throw new Error("请先登录");
    }
    let data = null;
    try { data = await res.json(); } catch (_) { /* 不是 JSON 就忽略 */ }
    if (!res.ok) {
      const detail = data && data.detail;
      throw new Error(typeof detail === "string" ? detail : "请求失败，请稍后再试");
    }
    return data;
  }

  // 金额用「分」的整数计算，避免 0.1 + 0.2 这类小数误差
  const toCents = (s) => Math.round(parseFloat(s) * 100);
  const fmt = (cents) => (cents / 100).toFixed(2);

  function localDate(d = new Date()) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  function showError(err) {
    alert(err && err.message ? err.message : String(err));
  }

  // ------------------------------------------------------------ 账目

  async function loadMonth() {
    const data = await api("entries?month=" + encodeURIComponent($("month").value));
    categories = data.categories;
    $("sumExpense").textContent = data.totals.expense;
    $("sumIncome").textContent = data.totals.income;
    $("sumBalance").textContent = fmt(toCents(data.totals.income) - toCents(data.totals.expense));
    renderList(data.entries);
  }

  function renderList(entries) {
    const list = $("list");
    list.innerHTML = "";
    $("empty").hidden = entries.length > 0;
    for (const e of entries) {
      const li = document.createElement("li");

      const meta = document.createElement("div");
      meta.className = "meta";
      const title = document.createElement("b");
      title.textContent = e.category + (e.source === "screenshot" ? "  📷" : "");
      const sub = document.createElement("small");
      sub.textContent = [e.occurredOn, e.note].filter(Boolean).join("  ");
      meta.append(title, sub);

      const amt = document.createElement("span");
      amt.className = "amt " + e.kind;
      amt.textContent = (e.kind === "expense" ? "-" : "+") + e.amount;

      const del = document.createElement("button");
      del.type = "button";
      del.className = "del";
      del.textContent = "删除";
      del.addEventListener("click", () => removeEntry(e.id));

      li.append(meta, amt, del);
      list.appendChild(li);
    }
  }

  async function removeEntry(id) {
    if (!confirm("确定删除这条账目？")) return;
    try {
      await api("entries/" + id, { method: "DELETE" });
      await loadMonth();
    } catch (err) {
      showError(err);
    }
  }

  function setKind(k) {
    kind = k;
    document.querySelectorAll(".seg button").forEach((b) => b.classList.toggle("on", b.dataset.kind === k));
    const sel = $("category");
    sel.innerHTML = "";
    for (const c of categories[k] || []) {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      sel.appendChild(opt);
    }
  }

  function say(text, isError = false) {
    const el = $("formMsg");
    el.textContent = text;
    el.classList.toggle("error", isError);
  }

  $("entryForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    say("");
    const body = {
      kind,
      category: $("category").value,
      amount: $("amount").value.trim(),
      note: $("note").value.trim(),
      occurredOn: $("occurredOn").value,
      source: sourceOfNext,
    };
    try {
      await api("entries", { method: "POST", body });
      $("amount").value = "";
      $("note").value = "";
      sourceOfNext = "manual";
      say("已保存 ✓");
      // 保存的如果是别的月份，就切换过去，免得看不到
      const savedMonth = body.occurredOn.slice(0, 7);
      if ($("month").value !== savedMonth) $("month").value = savedMonth;
      await loadMonth();
    } catch (err) {
      say(err.message, true);
    }
  });

  // ------------------------------------------------------------ 截图

  // 双击检测：两次按下间隔很短、位置很近。点在按钮、输入框、弹窗上不算，那是正常操作。
  let lastTap = null;
  document.addEventListener("pointerdown", (ev) => {
    if (ev.pointerType === "mouse" && ev.button !== 0) return;
    if (ev.target.closest && ev.target.closest("input, select, textarea, button, a, label, details, summary, .panel")) {
      lastTap = null;
      return;
    }
    const now = performance.now();
    const close = lastTap && now - lastTap.time < DOUBLE_TAP_MS &&
      Math.hypot(ev.clientX - lastTap.x, ev.clientY - lastTap.y) < DOUBLE_TAP_PX;
    if (close) {
      lastTap = null;
      startCapture();
    } else {
      lastTap = { time: now, x: ev.clientX, y: ev.clientY };
    }
  });

  $("shotBtn").addEventListener("click", startCapture);

  // 能不能用屏幕共享：浏览器要有这个接口，而且设备不是触屏（手机上屏幕共享支持不可靠，直接走相册）
  function canShareScreen() {
    const hasApi = !!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia);
    const isTouchDevice = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
    return hasApi && !isTouchDevice;
  }

  function startCapture() {
    if (capturing || !$("shotPanel").hidden) return;
    if (canShareScreen()) {
      // 电脑浏览器：弹出「选择要共享的屏幕或窗口」，抓一帧画面
      capturing = true;
      grabScreen()
        .then(recognize)
        .catch((err) => {
          // 用户在选择窗口里点了取消，不用提示
          if (err && err.name === "NotAllowedError") return;
          showError(err);
        })
        .finally(() => { capturing = false; });
    } else {
      // 手机浏览器：网页没法直接截整个屏幕，所以打开相册，选刚才按电源+音量键截的图
      $("filePick").click();
    }
  }

  async function grabScreen() {
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    try {
      const video = document.createElement("video");
      video.muted = true;
      video.playsInline = true;
      video.srcObject = stream;
      await video.play();
      await new Promise((r) => setTimeout(r, 300));   // 等第一帧真正画出来
      if (!video.videoWidth) throw new Error("没有拿到屏幕画面，请重试");
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      return canvas;
    } finally {
      stream.getTracks().forEach((t) => t.stop());   // 用完立刻关掉屏幕共享
    }
  }

  $("filePick").addEventListener("change", async () => {
    const input = $("filePick");
    const file = input.files[0];
    input.value = "";
    if (!file) return;
    try {
      const bitmap = await createImageBitmap(file);
      await recognize(toCanvas(bitmap, bitmap.width, bitmap.height));
    } catch (err) {
      showError(err);
    }
  });

  // 缩小到最长边 MAX_SIDE 以内，识别更快
  function toCanvas(source, w, h) {
    const scale = Math.min(1, MAX_SIDE / Math.max(w, h));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(w * scale));
    canvas.height = Math.max(1, Math.round(h * scale));
    canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
    return canvas;
  }

  // ------------------------------------------------------------ 识别

  function loadTesseract() {
    if (window.Tesseract) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = TESSERACT_URL;
      s.onload = resolve;
      s.onerror = () => reject(new Error("识别组件加载失败，请检查网络"));
      document.head.appendChild(s);
    });
  }

  async function recognize(source) {
    const canvas = source.tagName === "CANVAS" ? toCanvas(source, source.width, source.height) : source;
    showPanel(canvas);
    setStatus("正在加载识别组件…（第一次会慢一点）");
    try {
      await loadTesseract();
      setStatus("正在识别数字…");
      const worker = await window.Tesseract.createWorker("eng", 1, {
        logger: (m) => {
          if (m.status === "recognizing text") setStatus(`正在识别数字…${Math.round(m.progress * 100)}%`);
        },
      });
      let text = "";
      try {
        await worker.setParameters({
          tessedit_char_whitelist: "0123456789.,",   // 只认数字，减少误认
          tessedit_pageseg_mode: "11",               // 稀疏文字：屏幕上的数字散落在各处
        });
        const { data } = await worker.recognize(canvas);
        text = data.text || "";
      } finally {
        await worker.terminate();
      }
      $("ocrText").textContent = text;
      const res = await api("parse-numbers", { method: "POST", body: { text } });
      renderCandidates(res.numbers);
      setStatus(res.numbers.length
        ? "点一个数字，填进金额："
        : "没有找到数字。可以再截一次，或者手动输入。");
    } catch (err) {
      setStatus("识别失败：" + err.message);
    }
  }

  function showPanel(canvas) {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    $("candidates").innerHTML = "";
    $("ocrText").textContent = "";
    $("shotPanel").hidden = false;
    canvas.toBlob((blob) => {
      if (!blob) return;
      previewUrl = URL.createObjectURL(blob);
      $("shotImg").src = previewUrl;
    }, "image/png");
  }

  function closePanel() {
    $("shotPanel").hidden = true;
    $("shotImg").removeAttribute("src");
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
  }

  function setStatus(text) {
    $("ocrStatus").textContent = text;
  }

  function renderCandidates(numbers) {
    const box = $("candidates");
    box.innerHTML = "";
    for (const n of numbers) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = n;
      b.addEventListener("click", () => {
        $("amount").value = n;
        sourceOfNext = "screenshot";
        closePanel();
        say(`已填入 ${n}，选好分类后点保存`);
      });
      box.appendChild(b);
    }
  }

  $("shotClose").addEventListener("click", closePanel);
  $("shotPanel").addEventListener("click", (ev) => {
    if (ev.target === $("shotPanel")) closePanel();   // 点背景也关闭
  });

  // ------------------------------------------------------------ 启动

  async function init() {
    $("month").value = localDate().slice(0, 7);
    $("occurredOn").value = localDate();
    $("month").addEventListener("change", () => loadMonth().catch(showError));
    document.querySelectorAll(".seg button").forEach((b) =>
      b.addEventListener("click", () => setKind(b.dataset.kind)));
    await loadMonth();   // 先拿到分类列表
    setKind(kind);
  }

  init().catch(showError);
})();
