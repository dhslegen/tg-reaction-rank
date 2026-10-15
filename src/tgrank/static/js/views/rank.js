// 排行页：群名即切换器 → 榜单 → 时间/话题/搜索 → 比分栏列表
import { api } from '../api.js';
import { $, ago, debounce, esc, fmtDate, fmtNum, prefs } from '../ui.js';

const PAGE = 50;
const PRESETS = [['7d', '近 7 天'], ['30d', '近 30 天'], ['year', '今年'], ['all', '全部']];

export async function render(root) {
  const [chats, boards] = await Promise.all([api('/api/chats'), api('/api/boards')]);
  if (!chats.length) {
    root.innerHTML = `
      <h1>还没有群数据</h1>
      <p class="lede">两种方式把群消息收进来：登录 Telegram 账号后添加群并自动同步，或者上传 Telegram Desktop 导出的聊天记录。</p>
      <p class="inline" style="margin-top:2rem">
        <a class="btn" href="#/telegram" style="text-decoration:none">登录 Telegram</a>
        <a class="ghost" href="#/chats" style="text-decoration:none">导入聊天记录</a>
      </p>`;
    return;
  }

  const saved = prefs.get('rank', {});
  const st = {
    chat: chats.some(c => c.chat_id === saved.chat) ? saved.chat : chats[0].chat_id,
    board: boards.some(b => b.id === saved.board) ? saved.board : boards[0].id,
    range: 'all', from: '', to: '', topic: '', q: '',
    offset: 0, items: [], total: 0, link: null,
  };

  root.innerHTML = `
    <div class="head">
      <div class="switch ${chats.length > 1 ? 'many' : ''}">
        <h1 id="title"></h1>
        <label class="sr-only" for="chat">切换群</label>
        <select id="chat" ${chats.length > 1 ? '' : 'disabled tabindex="-1"'}>
          ${chats.map(c => `<option value="${c.chat_id}">${esc(c.title)}</option>`).join('')}
        </select>
      </div>
    </div>
    <p class="source" id="source"></p>

    <div class="boards-row">
      <div class="seg" id="boards" role="group" aria-label="榜单">
        ${boards.map(b => `<button type="button" data-id="${b.id}">${esc(b.name)}</button>`).join('')}
      </div>
      <a href="#/boards">管理榜单</a>
    </div>

    <div class="filters">
      <div class="seg" id="presets" role="group" aria-label="时间范围">
        ${PRESETS.map(([k, t]) => `<button type="button" data-k="${k}">${t}</button>`).join('')}
      </div>
      <label class="range">从 <input type="date" id="from"> 到 <input type="date" id="to"></label>
      <label class="topic" id="topicWrap" hidden>话题 <select id="topic"></select></label>
      <label class="search"><span class="sr-only">搜索</span><input type="search" id="q" placeholder="搜索消息内容" maxlength="100"></label>
    </div>

    <p class="summary" id="summary" role="status"></p>
    <ol class="board" id="list"></ol>
    <p class="none" id="none" hidden></p>
    <button class="ghost more" id="more" type="button" hidden>再显示 ${PAGE} 条</button>`;

  const chatSel = $(root, '#chat');
  const board = () => boards.find(b => b.id === st.board);
  const chat = () => chats.find(c => c.chat_id === st.chat);

  function paintHeader() {
    const c = chat();
    chatSel.value = String(c.chat_id);
    $(root, '#title').textContent = c.title;
    const sync = c.source === 'api'
      ? (c.sync_enabled ? (c.history_complete ? `上次同步 ${ago(c.last_sync_at)}` : '正在拉取历史消息…') : '已暂停同步')
      : '来自导入的聊天记录';
    $(root, '#source').innerHTML = `<span>共 ${fmtNum(c.messages)} 条消息，${fmtNum(c.reacted)} 条收到过反应</span><span>${esc(sync)}</span>`;
    root.querySelectorAll('#boards button').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.id) === st.board)));
    root.querySelectorAll('#presets button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.k === st.range)));
  }

  async function loadTopics() {
    const wrap = $(root, '#topicWrap');
    st.topic = '';
    if (!chat().is_forum) { wrap.hidden = true; return; }
    const topics = await api(`/api/chats/${st.chat}/topics`);
    $(root, '#topic').innerHTML = '<option value="">全部话题</option>' +
      topics.map(t => `<option value="${t.topic_id}">${esc(t.title)}</option>`).join('');
    wrap.hidden = !topics.length;
  }

  let req = 0;
  async function load(append = false) {
    const mine = ++req;
    if (!append) st.offset = 0;
    const p = new URLSearchParams({ board: st.board, range: st.range, offset: st.offset, limit: PAGE });
    if (st.range === 'custom') { if (st.from) p.set('from', st.from); if (st.to) p.set('to', st.to); }
    if (st.topic) p.set('topic', st.topic);
    if (st.q) p.set('q', st.q);
    const page = await api(`/api/chats/${st.chat}/ranking?${p}`);
    if (mine !== req) return;  // 已被更新的筛选取代
    st.items = append ? st.items.concat(page.items) : page.items;
    st.total = page.total;
    st.link = page.link_base;
    draw();
  }

  function draw() {
    const unit = board().builtin ? '个反应' : '分';
    $(root, '#summary').innerHTML = st.total
      ? `共有 <strong>${fmtNum(st.total)}</strong> 条消息上榜`
      : '';
    const none = $(root, '#none');
    none.hidden = st.total > 0;
    none.textContent = st.q ? `没有包含「${st.q}」的上榜消息。` : '这段时间里没有消息上榜。换一个时间范围或榜单试试。';
    $(root, '#list').innerHTML = st.items.map((i, n) => `
      <li class="entry${n < 3 ? ' top3' : ''}">
        <div class="score">
          <span class="rank">${n + 1}</span>
          <span class="num">${fmtNum(i.score)}</span>
          <span class="unit">${unit}</span>
        </div>
        <div class="body">
          <div class="meta">
            <span class="who">${esc(i.sender)}</span>
            <time datetime="${new Date(i.date * 1000).toISOString()}">${fmtDate(i.date)}</time>
            ${i.topic ? `<span class="tag">${esc(i.topic)}</span>` : ''}
          </div>
          <p class="text">${i.media ? `<span class="ph">${esc(i.media)}</span>${i.text ? ' ' : ''}` : ''}${esc(i.text)}</p>
          <div class="foot">
            <ul class="reacts" aria-label="反应明细">${i.reactions.map(r => `<li>${esc(r.label)}<b>${r.count}</b></li>`).join('')}</ul>
            ${st.link ? `<a class="open" href="${st.link}${i.msg_id}" target="_blank" rel="noopener">打开原消息</a>` : ''}
          </div>
        </div>
      </li>`).join('');
    const rest = st.total - st.items.length;
    const more = $(root, '#more');
    more.hidden = rest <= 0;
    more.textContent = `再显示 ${Math.min(PAGE, rest)} 条`;
  }

  const remember = () => prefs.set('rank', { chat: st.chat, board: st.board });

  chatSel.onchange = async () => {
    st.chat = Number(chatSel.value);
    remember();
    paintHeader();
    await loadTopics();
    load();
  };
  $(root, '#boards').onclick = e => {
    const b = e.target.closest('button');
    if (!b) return;
    st.board = Number(b.dataset.id);
    remember();
    paintHeader();
    load();
  };
  $(root, '#presets').onclick = e => {
    const b = e.target.closest('button');
    if (!b) return;
    st.range = b.dataset.k;
    $(root, '#from').value = $(root, '#to').value = '';
    paintHeader();
    load();
  };
  $(root, '#from').onchange = $(root, '#to').onchange = () => {
    st.from = $(root, '#from').value;
    st.to = $(root, '#to').value;
    st.range = st.from || st.to ? 'custom' : 'all';
    paintHeader();
    load();
  };
  $(root, '#topic').onchange = () => { st.topic = $(root, '#topic').value; load(); };
  $(root, '#q').oninput = debounce(() => { st.q = $(root, '#q').value.trim(); load(); }, 300);
  $(root, '#more').onclick = () => { st.offset = st.items.length; load(true); };

  remember();  // 榜单页的表情候选依赖「当前群」，进入排行页就记下
  paintHeader();
  await loadTopics();
  await load();
}
