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

  function tileEl(kind, opts = {}) {
    const t = el('span', 'tile');
    if (opts.small) t.classList.add('small');
    if (opts.back) {
      t.classList.add('back');
      return t;
    }
    if (isHonor(kind)) {
      t.classList.add(HONOR_CLASS[kind - 27]);
      t.append(el('b', null, HONOR_NAMES[kind - 27]));
    } else {
      t.classList.add(SUIT_CLASS[Math.floor(kind / 9)]);
      t.append(el('b', null, String((kind % 9) + 1)), el('i', null, SUIT_NAMES[Math.floor(kind / 9)]));
    }
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
      card.append(el('p', 'win-line', `${seatName(w.seat)} ${how}：${w.fan} 番`));
      card.append(el('p', 'detail', w.items.map(([n, v]) => `${n} ${v} 番`).join('，')));
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
