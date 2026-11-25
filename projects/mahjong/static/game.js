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

  // 筒子：按麻将牌的标准排法摆圆点（坐标系 100 × 140）
  const DOT_LAYOUT = {
    1: [[50, 70]],
    2: [[32, 40], [68, 100]],
    3: [[32, 40], [50, 70], [68, 100]],
    4: [[32, 44], [68, 44], [32, 96], [68, 96]],
    5: [[32, 40], [68, 40], [50, 70], [32, 100], [68, 100]],
    6: [[32, 36], [68, 36], [32, 70], [68, 70], [32, 104], [68, 104]],
    7: [[26, 30], [46, 50], [68, 72], [30, 100], [52, 100], [30, 124], [52, 124]],
    8: [[32, 34], [68, 34], [32, 62], [68, 62], [32, 90], [68, 90], [32, 118], [68, 118]],
    9: [[30, 36], [50, 36], [70, 36], [30, 70], [50, 70], [70, 70], [30, 104], [50, 104], [70, 104]],
  };

  // 每个圆点的颜色（参照参考图）
  const GREEN_DOT = '#2e8b57', RED_DOT = '#c0392b', BLACK_DOT = '#333';
  function dotColor(n, i) {
    if (n === 4) return GREEN_DOT;
    if (n === 5) return i === 2 ? RED_DOT : GREEN_DOT;
    if (n === 6) return i < 2 ? GREEN_DOT : RED_DOT;
    if (n === 7) return i < 3 ? GREEN_DOT : RED_DOT;
    if (n === 8) return BLACK_DOT;
    if (n === 9) return Math.floor(i / 3) === 1 ? RED_DOT : GREEN_DOT;
    return BLUE;
  }

  function dotFace(n) {
    const r = n === 1 ? 26 : (n <= 3 ? 16 : (n <= 6 ? 13 : (n === 7 ? 11 : 10)));
    const dots = DOT_LAYOUT[n].map(([x, y], i) => {
      // 1 筒是同心圆：中间红、中间绿、外圈蓝
      if (n === 1) {
        return `<circle cx="${x}" cy="${y}" r="${r}" fill="#fff" stroke="${BLUE}" stroke-width="4"/>` +
          `<circle cx="${x}" cy="${y}" r="${r * 0.62}" fill="none" stroke="${GREEN}" stroke-width="4"/>` +
          `<circle cx="${x}" cy="${y}" r="${r * 0.28}" fill="${RED}"/>`;
      }
      const c = dotColor(n, i);
      return `<circle cx="${x}" cy="${y}" r="${r}" fill="#fff" stroke="${c}" stroke-width="3.5"/>` +
        `<circle cx="${x}" cy="${y}" r="${r * 0.55}" fill="none" stroke="${c}" stroke-width="3"/>`;
    }).join('');
    return `<svg viewBox="0 0 100 140" aria-hidden="true">${dots}</svg>`;
  }

  // 条子：按标准排法摆竹子；一条是一只孔雀
  const BAMBOO_LAYOUT = {
    2: { w: 16, h: 40, pos: [[50, 46], [50, 96]] },   // 上面一竖、下面一竖
    3: { w: 16, h: 46, pos: [[50, 40], [34, 100], [66, 100]] },
    4: { w: 16, h: 46, pos: [[34, 44], [66, 44], [34, 100], [66, 100]] },
    5: { w: 15, h: 44, pos: [[32, 40], [68, 40], [50, 70], [32, 100], [68, 100]], reds: [2] },
    6: { w: 13, h: 50, pos: [[30, 46], [50, 46], [70, 46], [30, 96], [50, 96], [70, 96]] },   // 三列两行的竖条
    7: { w: 14, h: 30, pos: [[50, 26], [30, 70], [50, 70], [70, 70], [30, 116], [50, 116], [70, 116]], reds: [0] },
    9: { w: 13, h: 26, pos: [[30, 34], [50, 34], [70, 34], [30, 70], [50, 70], [70, 70], [30, 106], [50, 106], [70, 106]], reds: [1, 4, 7] },
  };

  function stickSvg(x, y, w, h, red) {
    // 竹子：圆角竿，带两道竹节；红色的那根是 5 条中间的红竹
    const body = red ? RED : '#2e8b57';
    const lines = [0.33, 0.66].map((f) => {
      const ly = y + h * f;
      return `<line x1="${x + 1.5}" y1="${ly}" x2="${x + w - 1.5}" y2="${ly}" stroke="#c8f0d4" stroke-width="2"/>`;
    }).join('');
    return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${w / 2}" fill="${body}" stroke="#0f4d28" stroke-width="2"/>${lines}`;
  }

  function peacockSvg() {
    // 一条：孔雀。身子绿色，尾羽展开，有红色眼斑，头上有红冠。
    let tail = '';
    const fan = [-62, -40, -18, 4, 26];
    fan.forEach((a, i) => {
      const col = i % 2 ? '#1b7a3d' : '#2b6cb0';
      tail += `<ellipse cx="42" cy="58" rx="7" ry="34" fill="${col}" stroke="#0f4d28" stroke-width="1.5" transform="rotate(${a} 42 90)"/>` +
        `<circle cx="${42 + 30 * Math.sin((a * Math.PI) / 180)}" cy="${90 - 30 * Math.cos((a * Math.PI) / 180)}" r="4.5" fill="#f2b53a" stroke="#0f4d28" stroke-width="1"/>`;
    });
    return `<svg viewBox="0 0 100 140" aria-hidden="true">
      ${tail}
      <ellipse cx="54" cy="92" rx="18" ry="22" fill="#1b7a3d" stroke="#0f4d28" stroke-width="2"/>
      <path d="M68 62 q10 -14 16 -2 q-4 4 -4 8 z" fill="#2b6cb0"/>
      <circle cx="70" cy="58" r="10" fill="#1b7a3d" stroke="#0f4d28" stroke-width="2"/>
      <path d="M64 48 l-3 -8 l5 4 l1 -7 l4 6 l3 -5 l0 8 z" fill="${RED}"/>
      <circle cx="74" cy="56" r="2.6" fill="#fff"/><circle cx="74.6" cy="56" r="1.2" fill="#111"/>
      <path d="M80 60 l8 3 l-8 3 z" fill="#e0a526"/>
      <path d="M50 110 l-3 16 M60 110 l3 16" stroke="#e0a526" stroke-width="3"/>
    </svg>`;
  }

  // 8 条：两个 M 形，每个由左右两根竖竹和中间两根斜竹组成
  function bamboo8Svg() {
    const line = (x1, y1, x2, y2) =>
      `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#0f4d28" stroke-width="13" stroke-linecap="round"/>` +
      `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#2e8b57" stroke-width="9" stroke-linecap="round"/>`;
    let out = '';
    for (const y0 of [22, 84]) {
      out += line(28, y0, 28, y0 + 44) + line(72, y0, 72, y0 + 44);
      out += line(28, y0, 50, y0 + 26) + line(72, y0, 50, y0 + 26);
    }
    return `<svg viewBox="0 0 100 140" aria-hidden="true">${out}</svg>`;
  }

  function bambooFace(n) {
    if (n === 1) return peacockSvg();
    if (n === 8) return bamboo8Svg();
    const L = BAMBOO_LAYOUT[n];
    const reds = L.reds || [];
    const sticks = L.pos.map(([cx, cy], i) => stickSvg(cx - L.w / 2, cy - L.h / 2, L.w, L.h, reds.includes(i))).join('');
    return `<svg viewBox="0 0 100 140" aria-hidden="true">${sticks}</svg>`;
  }

  // 万子：大号数字（汉字）加一个「萬」
  function characterFace(n) {
    return `<svg viewBox="0 0 100 140" aria-hidden="true">
      <text x="50" y="66" text-anchor="middle" font-size="60" font-weight="700" fill="${RED}" font-family="serif">${NUM_CH[n - 1]}</text>
      <text x="50" y="126" text-anchor="middle" font-size="44" font-weight="700" fill="${RED}" font-family="serif">萬</text>
    </svg>`;
  }

  function windFace(kind) {
    const ch = ['东', '南', '西', '北'][kind - 30];
    return `<svg viewBox="0 0 100 140" aria-hidden="true">
      <text x="50" y="92" text-anchor="middle" font-size="76" font-weight="700" fill="#1d2a24" font-family="serif">${ch}</text></svg>`;
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
    if (kind >= 30) return windFace(kind);
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

  let targeting = null;   // 摸牌前选目标：{ item: 'swap' | 'lucky_pong' | 'miracle_hu' }

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
    targeting = null;
    render();
  }

  // ------------------------------------------------------------ 渲染总入口

  function render() {
    const lobby = !view;
    if (lobby) loadLobby();
    const room = !!view && view.state === 'waiting';
    const table = !!view && !room;
    $('lobby').classList.toggle('hidden', !lobby);
    $('room').classList.toggle('hidden', !room);
    $('table').classList.toggle('hidden', !table);
    if (room) renderRoom();
    if (table) {
      renderTable();
      renderScoreboard();
    }
    renderOverlay();
  }

  // ------------------------------------------------------------ 房间

  function renderRoom() {
    $('room-code').textContent = view.code;
    $('room-vis').textContent = view.visibility === 'public' ? '（公开）' : '（私密）';
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
    $('visibility').value = view.visibility;
    $('visibility').disabled = !view.isHost;
    $('items').disabled = !view.isHost;
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
    const pickingDiscard = targeting && (targeting.item === 'lucky_pong' || targeting.item === 'miracle_hu')
      && r.phase === 'predraw' && r.turn === view.you;
    r.discards[i].forEach((k, idx) => {
      const t = tileEl(k, { small: true });
      if (r.last && r.last[0] === i && idx === r.discards[i].length - 1) t.classList.add('last');
      if (pickingDiscard) {
        t.classList.add('clickable');
        t.onclick = () => {
          send({ type: 'predraw', action: 'item', item: targeting.item, kind: k, src: i });
          targeting = null;
        };
      }
      disc.append(t);
    });
    frag.append(disc);

    if (isMe) {
      const hand = el('div', 'tiles hand hand-wrap');
      const clickable = canDiscard();
      const swapping = targeting && targeting.item === 'swap' && r.phase === 'predraw' && r.turn === view.you;
      r.hand.forEach((k) => {
        const t = tileEl(k);
        if (swapping) {
          t.classList.add('clickable');
          t.onclick = () => {
            send({ type: 'predraw', action: 'item', item: 'swap', kind: k });
            targeting = null;
          };
        } else if (clickable) {
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
    if (r.phase === 'predraw' && r.turn === view.you) {
      bar.append(btn('直接摸牌', '', () => { targeting = null; send({ type: 'predraw', action: 'skip' }); }));
      for (const o of r.predraw) {
        if (o.action !== 'item') continue;
        const active = targeting && targeting.item === o.item;
        bar.append(btn(`${o.name}${active ? '（选择中）' : ''}`, 'item', () => {
          targeting = active ? null : { item: o.item };
          renderTable();
        }));
      }
      return;
    }
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
    if (r.phase === 'predraw') {
      if (r.turn === view.you) {
        if (targeting && targeting.item === 'swap') text = '偷天换日：点你手上一张要换出去的牌';
        else if (targeting) text = `${ITEM_LABEL[targeting.item]}：点一张已经打出的牌`;
        else text = '摸牌前：可以用一个道具，或者直接摸牌';
      } else {
        text = `${seatName(r.turn)} 摸牌前…`;
      }
    } else if (r.phase === 'discard') {
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

  // ------------------------------------------------------------ 计分板

  function renderScoreboard() {
    const list = $('score-list');
    list.replaceChildren();
    const hist = view.history || [];
    if (!hist.length) {
      list.append(el('p', 'muted', '还没有完成的局。'));
      return;
    }
    for (const h of hist.slice().reverse()) {
      const row = el('details', 'round-row');
      const sum = el('summary');
      if (h.type === 'draw') {
        sum.textContent = `第 ${h.round} 局：流局`;
      } else {
        const w = h.winners[0];
        const how = w.selfDraw ? '自摸' : `点炮（${seatName(h.from)} 放炮）`;
        const fanText = w.fan ? `${w.fan} 翻` : '屁胡';
        sum.textContent = `第 ${h.round} 局：${seatName(w.seat)} ${how}，${fanText}，${w.points} 分`;
      }
      row.append(sum);

      const body = el('div', 'round-body');
      for (const w of h.winners) {
        const names = w.items.length ? w.items.map(([n, v]) => `${n} ${v} 翻`).join('，') : '屁胡（不翻）';
        body.append(el('p', 'win-line', `${seatName(w.seat)} 胡牌：${names}`));
        const hand = el('div', 'tiles small open-hand');
        w.hand.forEach((k) => hand.append(tileEl(k, { small: true })));
        body.append(hand);
      }
      body.append(el('p', 'detail', '分数变化：' + [0, 1, 2]
        .map((i) => `${seatName(i)} ${h.deltas[i] > 0 ? '+' : ''}${h.deltas[i]}`).join('，')));
      row.append(body);
      list.append(row);
    }
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

  // ------------------------------------------------------------ 大厅数据（积分、商城、排行榜）

  let lobbyData = null;
  const ITEM_LABEL = { swap: '偷天换日', lucky_pong: '锦上添花', miracle_hu: '妙手回春' };

  async function loadLobby() {
    let data;
    try {
      const r = await fetch(BASE + 'api/lobby', { credentials: 'same-origin' });
      if (!r.ok) throw new Error(String(r.status));
      data = await r.json();
    } catch (e) {
      $('me').textContent = '请先登录（游客也可以）后再进入。';
      return;
    }
    lobbyData = data;
    $('me').textContent = `${data.me.name} · 积分 ${data.me.points}`;
    $('resume-box').classList.toggle('hidden', !data.myRoom);

    const items = $('me');
    const owned = Object.entries(data.shop).map(([k, v]) => `${v.name} ×${data.me.items[k] || 0}`).join('，');
    items.append(el('div', 'muted', `道具：${owned}`));

    const shop = $('shop');
    shop.replaceChildren();
    for (const [k, v] of Object.entries(data.shop)) {
      shop.append(btn(`购买${v.name}（${v.price} 积分）`, '', () => buyItem(k)));
    }

    const pub = $('public-rooms');
    pub.replaceChildren();
    if (!data.rooms.length) pub.append(el('li', 'muted', '暂时没有公开的房间。'));
    for (const r of data.rooms) {
      const li = el('li');
      li.append(el('span', null, `${r.host} 的房间 · ${r.seats}/3 人 · ${r.rounds} 局${r.items ? ' · 有道具' : ''}`));
      li.append(btn('加入', '', () => connect({ type: 'join', code: r.code })));
      pub.append(li);
    }

    const board = $('leaderboard');
    board.replaceChildren();
    if (!data.leaderboard.length) board.append(el('li', 'muted', '还没有积分记录。'));
    for (const row of data.leaderboard) {
      board.append(el('li', null, `${row.name}：${row.points} 分`));
    }
  }

  async function buyItem(item) {
    try {
      const r = await fetch(BASE + 'api/shop/buy', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item }),
      });
      const data = await r.json();
      toast(data.ok ? '购买成功' : data.text);
    } catch (e) {
      toast('购买失败，请稍后再试');
    }
    loadLobby();
  }

  // ------------------------------------------------------------ 按钮

  function visibilityValue() { return $('visibility-lobby').value; }

  $('btn-solo').onclick = () => connect({
    type: 'solo', rounds: Number($('rounds-lobby').value), items: $('items-lobby').checked,
  });
  $('btn-create').onclick = () => connect({
    type: 'create', rounds: Number($('rounds-lobby').value), visibility: visibilityValue(),
  });
  $('btn-join').onclick = () => {
    const code = $('code').value.trim();
    if (!/^\d{4}$/.test(code)) return toast('请输入四位房间号');
    connect({ type: 'join', code });
  };
  $('btn-resume').onclick = () => {
    if (lobbyData && lobbyData.myRoom) connect({ type: 'resume', code: lobbyData.myRoom });
  };
  $('btn-start').onclick = () => send({ type: 'start', items: $('items').checked });
  $('rounds').onchange = () => send({ type: 'rounds', rounds: Number($('rounds').value) });
  $('visibility').onchange = () => send({ type: 'visibility', visibility: $('visibility').value });
  $('btn-leave').onclick = leave;
  $('btn-quit').onclick = leave;

  render();
})();
