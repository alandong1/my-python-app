"use strict";
// 贪吃蛇：纯前端小游戏。电脑用键盘，手机用滑动或下方方向按钮。
// 游戏只在浏览器里运行；最高分保存在本机 localStorage（读写失败时只是不保存）。

(function () {
  const tr = (zh, ...args) => i18n.t(zh, ...args);

  const COLS = 20;           // 棋盘列数
  const ROWS = 20;           // 棋盘行数
  const SWIPE_MIN = 20;      // 滑动至少多少像素才算滑动，过滤误触；更短的算轻点
  const BEST_KEY = "snake.best";

  const canvas = document.getElementById("board");
  const ctx = canvas.getContext("2d");
  const scoreEl = document.getElementById("score");
  const bestEl = document.getElementById("best");
  const msgEl = document.getElementById("msg");
  const pauseBtn = document.getElementById("pauseBtn");

  const DIR_NAMES = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
  const KEY_DIRS = {
    ArrowUp: [0, -1], w: [0, -1], W: [0, -1],
    ArrowDown: [0, 1], s: [0, 1], S: [0, 1],
    ArrowLeft: [-1, 0], a: [-1, 0], A: [-1, 0],
    ArrowRight: [1, 0], d: [1, 0], D: [1, 0],
  };

  // ---------- 游戏状态 ----------
  let snake = [];                 // 蛇身，第 0 个是蛇头
  let dir = { x: 1, y: 0 };       // 当前正在走的方向
  let nextDir = dir;              // 下一步的方向（玩家刚按下的）
  let turnLocked = false;         // 同一步只接受一次转向，防止连按两下直接掉头送命
  let food = { x: 0, y: 0 };
  let score = 0;
  let best = loadBest();
  let newRecord = false;          // 本局是否破了纪录（用于结束提示）
  let state = "ready";            // ready 等待开始 | running 进行中 | paused 暂停 | over 结束
  let timer = null;
  let size = 0;                   // 画布的 CSS 像素宽度（画布是正方形）

  function loadBest() {
    try { return parseInt(localStorage.getItem(BEST_KEY), 10) || 0; } catch (e) { return 0; }
  }
  function saveBest() {
    try { localStorage.setItem(BEST_KEY, String(best)); } catch (e) { /* 隐私模式下无法保存，本次有效 */ }
  }

  function reset() {
    const mid = Math.floor(COLS / 2);
    const row = Math.floor(ROWS / 2);
    snake = [{ x: mid, y: row }, { x: mid - 1, y: row }, { x: mid - 2, y: row }];
    dir = { x: 1, y: 0 };
    nextDir = dir;
    turnLocked = false;
    score = 0;
    newRecord = false;
    placeFood();
  }

  function placeFood() {
    // 随机选一个没有被蛇占据的格子
    let p;
    do {
      p = { x: Math.floor(Math.random() * COLS), y: Math.floor(Math.random() * ROWS) };
    } while (snake.some((s) => s.x === p.x && s.y === p.y));
    food = p;
  }

  // ---------- 流程控制 ----------
  function start() {
    state = "running";
    schedule();
    draw();
    render();
  }

  // 吃得越多越快，最快每 70 毫秒走一步
  function schedule() {
    clearInterval(timer);
    timer = setInterval(tick, Math.max(70, 150 - score * 4));
  }

  function tick() {
    dir = nextDir;
    turnLocked = false;
    const head = { x: snake[0].x + dir.x, y: snake[0].y + dir.y };
    const eating = head.x === food.x && head.y === food.y;
    // 蛇尾会跟着移动，所以不吃东西时，撞到原来的蛇尾是安全的
    const body = eating ? snake : snake.slice(0, -1);
    const hitWall = head.x < 0 || head.y < 0 || head.x >= COLS || head.y >= ROWS;
    const hitSelf = body.some((s) => s.x === head.x && s.y === head.y);
    if (hitWall || hitSelf) {
      gameOver();
      return;
    }

    snake.unshift(head);
    if (eating) {
      score++;
      placeFood();
      schedule();   // 变快了，重新计时
    } else {
      snake.pop();
    }
    render();
    draw();
  }

  function gameOver() {
    clearInterval(timer);
    state = "over";
    if (score > 0 && score > best) {
      best = score;
      newRecord = true;
      saveBest();
    }
    render();
    draw();
  }

  function togglePause() {
    if (state === "running") {
      state = "paused";
      clearInterval(timer);
    } else if (state === "paused") {
      state = "running";
      schedule();
    }
    render();
  }

  // 空格 / 回车 / 轻点画布：开始、重新开始，或暂停 / 继续
  function action() {
    if (state === "ready") {
      start();
    } else if (state === "over") {
      reset();
      start();
    } else {
      togglePause();
    }
  }

  // 改变方向。不能直接掉头（向右时不能立刻向左）
  function turn(x, y) {
    if (state === "over" || state === "paused") return;
    if (turnLocked) return;
    if (x === -dir.x && y === -dir.y) return;
    nextDir = { x, y };
    turnLocked = true;
    if (state === "ready") start();
  }

  // ---------- 显示 ----------
  function render() {
    if (state === "ready") {
      msgEl.textContent = tr("按方向键或滑动屏幕开始");
    } else if (state === "paused") {
      msgEl.textContent = tr("已暂停。按 P 或点「继续」");
    } else if (state === "over") {
      msgEl.textContent = newRecord
        ? tr("游戏结束！新纪录 {0} 分，点击或按空格再来一局", score)
        : tr("游戏结束，得分 {0}。点击或按空格再来一局", score);
    } else {
      msgEl.textContent = "";
    }
    pauseBtn.textContent = state === "paused" ? tr("继续") : tr("暂停");
    pauseBtn.disabled = state === "ready" || state === "over";
    scoreEl.textContent = String(score);
    bestEl.textContent = String(best);
  }

  function draw() {
    if (!size) return;
    const cell = size / COLS;
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(0, 0, size, size);

    // 食物
    ctx.fillStyle = "#f43f5e";
    ctx.beginPath();
    ctx.arc((food.x + 0.5) * cell, (food.y + 0.5) * cell, cell * 0.38, 0, Math.PI * 2);
    ctx.fill();

    // 蛇：蛇头颜色更亮
    const pad = cell * 0.08;
    snake.forEach((s, i) => {
      ctx.fillStyle = i === 0 ? "#86efac" : "#22c55e";
      ctx.fillRect(s.x * cell + pad, s.y * cell + pad, cell - pad * 2, cell - pad * 2);
    });
  }

  // 按画布的实际宽度重新设置清晰度（手机屏幕像素密度高，画面会更清楚）
  function resize() {
    const dpr = window.devicePixelRatio || 1;
    size = canvas.clientWidth;
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  // ---------- 输入 ----------
  document.addEventListener("keydown", (e) => {
    const d = KEY_DIRS[e.key];
    if (d) {
      e.preventDefault();   // 阻止方向键滚动页面
      turn(d[0], d[1]);
    } else if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      action();
    } else if (e.key === "p" || e.key === "P") {
      togglePause();
    }
  });

  pauseBtn.addEventListener("click", togglePause);
  canvas.addEventListener("click", action);   // 电脑上点击画布

  // 手机：在画布上滑动改变方向，轻点开始 / 暂停
  let touch = null;
  canvas.addEventListener("touchstart", (e) => {
    const t = e.changedTouches[0];
    touch = { x: t.clientX, y: t.clientY };
  }, { passive: true });
  canvas.addEventListener("touchend", (e) => {
    if (!touch) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - touch.x;
    const dy = t.clientY - touch.y;
    touch = null;
    e.preventDefault();   // 阻止随后合成的 click 事件，避免一次轻点触发两次
    if (Math.max(Math.abs(dx), Math.abs(dy)) < SWIPE_MIN) {
      action();
    } else if (Math.abs(dx) > Math.abs(dy)) {
      turn(dx > 0 ? 1 : -1, 0);
    } else {
      turn(0, dy > 0 ? 1 : -1);
    }
  }, { passive: false });

  // 方向按钮（手机上显示）
  document.querySelectorAll(".pad button").forEach((b) => {
    b.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const d = DIR_NAMES[b.dataset.dir];
      turn(d[0], d[1]);
    });
  });

  // 切到别的标签页时自动暂停
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && state === "running") togglePause();
  });

  window.addEventListener("resize", resize);
  i18n.onChange(render);

  reset();
  resize();
  render();
})();
