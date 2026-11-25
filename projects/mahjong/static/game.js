/* 湖北卡五星（三人）：大厅、房间和牌桌的界面。规则都在服务器上算，这里只负责显示和发送操作。 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const SUIT_NAMES = ['万', '条', '筒'];
  const SUIT_CLASS = ['wan', 'tiao', 'tong'];
  const HONOR_NAMES = ['中', '发', '白'];
  const HONOR_CLASS = ['zhong', 'fa', 'bai'];
  const ACTION_LABEL = { hu: '胡', pong: '碰', gang_ming: '明杠', pass: '过' };
  const BASE = location.pathname.endsWith('/') ? location.pathname : location.pathname + '/';
  const NAME_KEY = 'mahjong.name';

  let ws = null;          // 当前的 WebSocket
  let view = null;        // 服务器发来的最新画面
  let selectedKind = -1;  // 选中的牌（再点一次才打出，防止误触）
  let dismissedKey = null;

  // ------------------------------------------------------------ 小工具

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  function isHonor(kind) { return kind >= 27; }

  function tileName(kind) {
    if (isHonor(kind)) return HONOR_NAMES[kind - 27];
    return `${(kind % 9) + 1}${SUIT_NAMES[Math.floor(kind / 9)]}`;
  }

  // ---- 牌面图案（SVG，坐标系 100 × 140）。图案内容是固定的，不含用户输入。
  const NUM_CH = ['一', '二', '三', '四', '五', '六', '七', '八', '九'];
  const RED = '#b3262b', GREEN = '#1b7a3d', BLUE = '#1f4e9c';

  // 筒子的圆点位置（按麻将牌的常见排法）
  const DOT_LAYOUT = {
    1: [[50, 70]],
    2: [[50, 45], [50, 95]],
    3: [[50, 30], [50, 70], [50, 110]],
    4: [[32, 45], [68, 45], [32, 95], [68, 95]],
    5: [[32, 40], [68, 40], [50, 70], [32, 100], [68, 100]],
    6: [[32, 36], [68, 36], [32, 70], [68, 70], [32, 104], [68, 104]],
    7: [[50, 32], [32, 60], [68, 60], [32, 86], [68, 86], [32, 112], [68, 112]],
    8: [[32, 34], [68, 34], [50, 56], [32, 78], [68, 78], [50, 100], [32, 118], [68, 118]],
    9: [[30, 32], [50, 32], [70, 32], [30, 70], [50, 70], [70, 70], [30, 108], [50, 108], [70, 108]],
  };

  function dotFace(n) {
    const r = n === 1 ? 26 : (n <= 3 ? 14 : (n <= 6 ? 12 : 9));
    const dots = DOT_LAYOUT[n].map(([x, y]) => (
      `<circle cx="${x}" cy="${y}" r="${r}" fill="#fff" stroke="${BLUE}" stroke-width="3.5"/>` +
      `<circle cx="${x}" cy="${y}" r="${r * 0.55}" fill="none" stroke="${RED}" stroke-width="3"/>`
    )).join('');
    return `<svg viewBox="0 0 100 140" aria-hidden="true">${dots}</svg>`;
  }

  // 条子：n 根竹子，1 条是一只鸡（妖姬）
  function bambooFace(n) {
    if (n === 1) {
      return `<svg viewBox="0 0 100 140" aria-hidden="true">
        <ellipse cx="50" cy="82" rx="30" ry="24" fill="${GREEN}"/>
        <path d="M30 72 Q10 60 12 40 Q30 52 40 66 Z" fill="${RED}"/>
        <circle cx="66" cy="50" r="15" fill="${GREEN}"/>
        <path d="M60 36 q6 -10 12 0 q6 -8 10 2 q-8 4 -22 2 z" fill="${RED}"/>
        <path d="M80 52 l10 4 l-10 4 z" fill="#e0a526"/>
        <circle cx="70" cy="48" r="2.5" fill="#fff"/>
        <path d="M40 104 l-4 22 M56 104 l4 22" stroke="#e0a526" stroke-width="4"/>
      </svg>`;
    }
    const cols = n <= 3 ? n : Math.ceil(Math.sqrt(n));
    const rows = Math.ceil(n / cols);
    const w = cols === 1 ? 26 : (cols === 2 ? 22 : 18);
    const h = rows === 1 ? 92 : (rows === 2 ? 52 : 36);
    let out = '';
    for (let i = 0; i < n; i++) {
      const c = i % cols;
      const rr = Math.floor(i / cols);
      const cellW = 100 / cols, cellH = 140 / rows;
      const x = cellW * c + cellW / 2 - w / 2;
      const y = cellH * rr + cellH / 2 - h / 2;
      out += `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${w / 2}" fill="${GREEN}" stroke="#0f4d28" stroke-width="2.5"/>`;
      for (let j = 1; j < 4; j++) {
        const ly = y + (h * j) / 4;
        out += `<line x1="${x + 2}" y1="${ly}" x2="${x + w - 2}" y2="${ly}" stroke="#a8e6bd" stroke-width="2"/>`;
      }
    }
    return `<svg viewBox="0 0 100 140" aria-hidden="true">${out}</svg>`;
  }

  // 万子：大号数字（汉字）加一个「萬」
  function characterFace(n) {
    return `<svg viewBox="0 0 100 140" aria-hidden="true">
      <text x="50" y="66" text-anchor="middle" font-size="60" font-weight="700" fill="${RED}" font-family="serif">${NUM_CH[n - 1]}</text>
      <text x="50" y="126" text-anchor="middle" font-size="44" font-weight="700" fill="${RED}" font-family="serif">萬</text>
    </svg>`;
  }

  function honorFace(kind) {
    if (kind === 27) {   // 红中
      return `<svg viewBox="0 0 100 140" aria-hidden="true">
        <text x="50" y="92" text-anchor="middle" font-size="84" font-weight="700" fill="${RED}" font-family="serif">中</text></svg>`;
    }
    if (kind === 28) {   // 发财
      return `<svg viewBox="0 0 100 140" aria-hidden="true">
        <text x="50" y="92" text-anchor="middle" font-size="76" font-weight="700" fill="${GREEN}" font-family="serif">發</text></svg>`;
    }
    // 白板：只有一个蓝色边框
    return `<svg viewBox="0 0 100 140" aria-hidden="true">
      <rect x="16" y="22" width="68" height="96" rx="6" fill="none" stroke="${BLUE}" stroke-width="6"/>
      <rect x="24" y="30" width="52" height="80" rx="3" fill="none" stroke="${BLUE}" stroke-width="2" opacity=".5"/></svg>`;
  }

  function faceSvg(kind) {
    if (kind >= 27) return honorFace(kind);
    const suit = Math.floor(kind / 9);
    const n = (kind % 9) + 1;
    if (suit === 0) return characterFace(n);
    if (suit === 1) return bambooFace(n);
    return dotFace(n);
  }

  function tileEl(kind, opts = {}) {
    const t = el('span', 'tile');
    if (opts.small) t.classList.add('small');
    if (opts.back) {
      t.classList.add('back');
      return t;
    }
    t.classList.add(isHonor(kind) ? HONOR_CLASS[kind - 27] : SUIT_CLASS[Math.floor(kind / 9)]);
    t.innerHTML = faceSvg(kind);
    t.title = tileName(kind);
    return t;
  }

  let toastTimer = null;
  function toast(text) {
    const t = $('toast');
    t.textContent = text;
    t.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add('hidden'), 2600);
  }

  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }

  function nameValue() {
    const v = $('name').value.trim().slice(0, 12) || '玩家';
    try { localStorage.setItem(NAME_KEY, v); } catch (e) { /* 隐私模式下可能不能存，忽略 */ }
    return v;
  }

  function seatName(i) {
    const s = view && view.seats[i];
    return s ? s.name : `座位${i + 1}`;
  }

  // ------------------------------------------------------------ 连接

  function closeSocket() {
    const s = ws;
    ws = null;
    if (s) {
      try { s.close(); } catch (e) { /* 已经关闭 */ }
    }
  }

  function connect(first) {
    closeSocket();
    const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
    const sock = new WebSocket(proto + location.host + BASE + 'ws');
    ws = sock;
    sock.onopen = () => sock.send(JSON.stringify(first));
    sock.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === 'state') {
        view = msg;
        render();
      } else if (msg.type === 'error') {
        toast(msg.text);
      }
    };
    sock.onclose = () => {
      if (ws !== sock) return;   // 自己主动离开，不提示
      ws = null;
      if (view) toast('与服务器断开了连接');
      view = null;
      render();
    };
  }

  function leave() {
    closeSocket();
    view = null;
    render();
  }

  // ------------------------------------------------------------ 渲染总入口

  function render() {
    const lobby = !view;
    const room = !!view && view.state === 'waiting';
    const table = !!view && !room;
    $('lobby').classList.toggle('hidden', !lobby);
    $('room').classList.toggle('hidden', !room);
    $('table').classList.toggle('hidden', !table);
    if (room) renderRoom();
    if (table) renderTable();
    renderOverlay();
  }

  // ------------------------------------------------------------ 房间

  function renderRoom() {
    $('room-code').textContent = view.code;
    const list = $('room-seats');
    list.replaceChildren();
    view.seats.forEach((s, i) => {
      const li = el('li');
      li.append(el('span', null, s ? s.name : '空位'));
      let tag = '开局时由电脑补位';
      if (s) tag = s.bot ? '电脑' : (i === view.you ? (view.isHost ? '你（房主）' : '你') : '玩家');
      li.append(el('span', 'muted', tag));
      list.append(li);
    });
    $('btn-start').disabled = !view.isHost;
    $('btn-start').textContent = view.isHost ? '开始游戏' : '等待房主开始';
    $('rounds').value = String(view.rounds);
    $('rounds').disabled = !view.isHost;
  }

  // ------------------------------------------------------------ 牌桌

  function canDiscard() {
    const r = view.round;
    return r.phase === 'discard' && r.turn === view.you;
  }

  function renderTable() {
    const r = view.round;
    const me = view.you;
    const suitText = r.suits.map((s) => SUIT_NAMES[s]).join('、');
    $('info').textContent = `第 ${view.roundNo} 局 / 共 ${view.rounds} 局 · 本局 ${suitText} + 中发白 · 庄家：${seatName(view.dealer)} · 牌墙剩 ${r.wall} 张`;
    if (!canDiscard()) selectedKind = -1;

    // 三人：自己在下方，下家在右，上家在左
    const boxes = ['seat-bottom', 'seat-right', 'seat-left'];
    for (let i = 0; i < 3; i++) {
      const rel = (i - me + 3) % 3;
      $(boxes[rel]).replaceChildren(seatContent(i));
    }
    renderCenter();
    renderActions();
    renderHint();
  }

  function seatTags(i) {
    const r = view.round;
    const frag = [];
    if (view.dealer === i) frag.push(el('span', 'tag dealer', '庄'));
    if (r.opened[i]) frag.push(el('span', 'tag open', '明牌'));
    return frag;
  }

  function seatContent(i) {
    const r = view.round;
    const isMe = i === view.you;
    const frag = document.createDocumentFragment();

    const who = el('div', 'who' + (r.turn === i && r.phase !== 'over' ? ' turn' : ''));
    who.append(el('b', null, seatName(i)));
    who.append(el('span', 'score', String(view.scores[i])));
    seatTags(i).forEach((t) => who.append(t));
    frag.append(who);

    const melds = el('div', 'tiles small');
    for (const m of r.melds[i]) {
      const g = el('span', 'meld-group');
      const n = m.type === 'pong' ? 3 : 4;
      for (let k = 0; k < n; k++) g.append(tileEl(m.kind, { small: true }));
      melds.append(g);
    }
    if (r.melds[i].length) frag.append(melds);

    const disc = el('div', 'tiles small discards');
    r.discards[i].forEach((k, idx) => {
      const t = tileEl(k, { small: true });
      if (r.last && r.last[0] === i && idx === r.discards[i].length - 1) t.classList.add('last');
      disc.append(t);
    });
    frag.append(disc);

    if (isMe) {
      const hand = el('div', 'tiles hand hand-wrap');
      const clickable = canDiscard();
      r.hand.forEach((k) => {
        const t = tileEl(k);
        if (clickable) {
          t.classList.add('clickable');
          if (k === selectedKind) t.classList.add('selected');
          t.onclick = () => onTileClick(k);
        }
        hand.append(t);
      });
      frag.append(hand);
    } else if (r.openHands && r.openHands[i]) {
      // 明牌：所有人都能看到这家的手牌
      const shown = el('div', 'tiles small open-hand');
      r.openHands[i].forEach((k) => shown.append(tileEl(k, { small: true })));
      frag.append(shown);
    } else if (r.phase === 'over' && r.result && r.result.revealed) {
      const shown = el('div', 'tiles small open-hand');
      r.result.revealed[i].forEach((k) => shown.append(tileEl(k, { small: true })));
      frag.append(shown);
    } else {
      const backs = el('div', 'tiles small open-hand');
      for (let k = 0; k < r.handCounts[i]; k++) backs.append(tileEl(0, { small: true, back: true }));
      frag.append(backs);
    }
    return frag;
  }

  function onTileClick(kind) {
    if (selectedKind === kind) {
      selectedKind = -1;
      send({ type: 'discard', kind });
    } else {
      selectedKind = kind;
      renderTable();
    }
  }

  function renderCenter() {
    const r = view.round;
    const c = $('center');
    c.replaceChildren();
    if (r.last) {
      c.append(el('div', 'muted', `${seatName(r.last[0])} 打出`));
      c.append(tileEl(r.last[1]));
    } else {
      c.append(el('div', 'muted', '牌局开始'));
    }
  }

  function btn(text, cls, onClick) {
    const b = el('button', cls, text);
    b.onclick = onClick;
    return b;
  }

  function renderActions() {
    const r = view.round;
    const bar = $('actions');
    bar.replaceChildren();
    if (r.phase === 'discard' && r.turn === view.you) {
      for (const o of r.self) {
        if (o.action === 'hu') {
          bar.append(btn('自摸和牌', 'hu', () => send({ type: 'self', action: 'hu' })));
        } else if (o.action === 'open') {
          bar.append(btn('明牌', 'open', () => send({ type: 'self', action: 'open' })));
        } else {
          const label = o.action === 'gang_an' ? '暗杠' : '加杠';
          bar.append(btn(`${label} ${tileName(o.kind)}`, '', () => send({ type: 'self', action: o.action, kind: o.kind })));
        }
      }
    } else if (r.claim && r.claim.length) {
      for (const a of r.claim) {
        bar.append(btn(ACTION_LABEL[a] || a, a === 'hu' ? 'hu' : '', () => send({ type: 'claim', action: a })));
      }
      bar.append(btn('过', 'pass', () => send({ type: 'claim', action: 'pass' })));
    }
  }

  function renderHint() {
    const r = view.round;
    let text = '';
    if (r.phase === 'discard') {
      if (r.turn === view.you) {
        text = selectedKind >= 0 ? '再点一次这张牌，就打出去' : '轮到你出牌：点一张牌选中，再点一次打出';
      } else if (view.seats[r.turn] && view.seats[r.turn].bot) {
        text = `${seatName(r.turn)} 正在思考…`;
      } else {
        text = `等待 ${seatName(r.turn)} 出牌…`;
      }
    } else if (r.phase === 'claim') {
      text = r.claim && r.claim.length ? '有人打出了一张牌：可以碰、杠或胡（超时自动过）' : '等待其他玩家表态…';
    }
    $('hint').textContent = text;
  }

  // ------------------------------------------------------------ 一局结束 / 整场结束

  function renderOverlay() {
    const ov = $('overlay');
    if (!view || view.state === 'waiting' || view.state === 'playing') {
      ov.classList.add('hidden');
      return;
    }
    const key = `${view.state}:${view.roundNo}`;
    if (view.state === 'round_end' && dismissedKey === key) {
      ov.classList.add('hidden');
      return;
    }
    ov.classList.remove('hidden');
    const card = $('overlay-card');
    card.replaceChildren();
    const res = view.round.result;

    card.append(el('h2', null, view.state === 'match_end' ? '整场结束' : `第 ${view.roundNo} 局结束`));
    if (res.type === 'draw') {
      card.append(el('p', 'win-line', '流局：牌墙摸完，无人和牌'));
    }
    for (const w of res.winners) {
      const how = w.selfDraw ? '自摸' : `点炮（${seatName(res.from)} 放炮）`;
      const fanText = w.fan ? `${w.fan} 翻` : '屁胡（不翻）';
      card.append(el('p', 'win-line', `${seatName(w.seat)} ${how}：${fanText}，${w.points} 分`));
      card.append(el('p', 'detail', w.items.length ? w.items.map(([n, v]) => `${n} ${v} 翻`).join('，') : '底分 1 分'));
    }

    const table = el('table');
    const head = el('tr');
    ['座位', '本局', '总分'].forEach((t, idx) => {
      const th = el('th', null, t);
      if (idx > 0) th.className = 'num';
      head.append(th);
    });
    table.append(head);
    for (let i = 0; i < 3; i++) {
      const tr = el('tr');
      tr.append(el('td', null, seatName(i)));
      tr.append(el('td', 'num', (res.deltas[i] > 0 ? '+' : '') + res.deltas[i]));
      tr.append(el('td', 'num', String(view.scores[i])));
      table.append(tr);
    }
    card.append(table);

    const row = el('div', 'row');
    if (view.state === 'round_end') {
      card.append(el('p', 'muted', '6 秒后开始下一局'));
      row.append(btn('知道了', '', () => {
        dismissedKey = key;
        render();
      }));
    } else {
      if (view.isHost) row.append(btn('再来一局', '', () => send({ type: 'start' })));
      row.append(btn('离开牌桌', '', leave));
    }
    card.append(row);
  }

  // ------------------------------------------------------------ 按钮

  $('btn-solo').onclick = () => connect({ type: 'solo', name: nameValue(), rounds: Number($('rounds-lobby').value) });
  $('btn-create').onclick = () => connect({ type: 'create', name: nameValue(), rounds: Number($('rounds-lobby').value) });
  $('btn-join').onclick = () => {
    const code = $('code').value.trim().toUpperCase();
    if (!code) return toast('请输入房间号');
    connect({ type: 'join', code, name: nameValue() });
  };
  $('btn-start').onclick = () => send({ type: 'start' });
  $('rounds').onchange = () => send({ type: 'rounds', rounds: Number($('rounds').value) });
  $('btn-leave').onclick = leave;
  $('btn-quit').onclick = leave;

  try {
    const saved = localStorage.getItem(NAME_KEY);
    if (saved) $('name').value = saved;
  } catch (e) { /* 忽略 */ }
  render();
})();
