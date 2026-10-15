// 榜单 = 名称 + 表情权重表；未列出的表情、自定义表情、Stars 打赏各有一个默认权重
import { api } from '../api.js';
import { $, busy, displayEmoji, esc, fmtNum, prefs, setStatus } from '../ui.js';

function describe(b) {
  if (b.builtin) return '每个反应记 1 分';
  const parts = Object.entries(b.weights).map(([e, w]) => `${displayEmoji(e)} ×${fmtNum(w)}`);
  const rest = [];
  if (b.default_weight !== 1) rest.push(`其余表情 ×${fmtNum(b.default_weight)}`);
  if (b.custom_emoji_weight !== 1) rest.push(`自定义表情 ×${fmtNum(b.custom_emoji_weight)}`);
  if (b.paid_weight !== 1) rest.push(`Stars ×${fmtNum(b.paid_weight)}`);
  return [...parts, ...rest].join('，') || '每个反应记 1 分';
}

export async function render(root) {
  root.innerHTML = `
    <div class="head"><h1>榜单</h1><button class="btn" id="new" type="button">新建榜单</button></div>
    <p class="lede">榜单决定每种表情反应算几分。比如「最好笑」只给 😂 计分，「争议」给 👎 加权、给 👍 扣分。分数在查看时实时计算，改完立即生效。</p>
    <ul class="rows" id="list" style="margin-top:2rem"></ul>
    <section id="editor" class="editor" hidden></section>`;

  let boards = [];
  let emojis = [];
  // 表情候选取自「当前群」：排行页记下的群，没有记录就用第一个群
  const chats = await api('/api/chats');
  const saved = prefs.get('rank', {}).chat;
  const chat = chats.some(c => c.chat_id === saved) ? saved : chats[0]?.chat_id;
  if (chat) emojis = await api(`/api/chats/${chat}/emojis`).catch(() => []);

  async function load() {
    boards = await api('/api/boards');
    $(root, '#list').innerHTML = boards.map(b => `
      <li class="row" data-id="${b.id}">
        <div>
          <div class="row-title">${esc(b.name)}</div>
          <div class="row-meta"><span>${esc(describe(b))}</span>${b.push_enabled ? '<span>参与定期推送</span>' : ''}</div>
        </div>
        <div class="row-actions">
          <button class="ghost" type="button" data-act="edit">${b.builtin ? '推送设置' : '编辑'}</button>
          ${b.builtin ? '' : '<button class="ghost danger" type="button" data-act="delete">删除</button>'}
        </div>
      </li>`).join('');
  }

  function weightRow(emoji = '', weight = 1) {
    return `<div class="w">
      <input aria-label="表情" value="${esc(emoji && displayEmoji(emoji))}" placeholder="😂" maxlength="16">
      <input aria-label="权重" type="number" step="0.1" min="-10" max="100" value="${weight}">
      <button class="textbtn" type="button" data-act="rm">移除</button>
    </div>`;
  }

  function openEditor(b) {
    const ed = $(root, '#editor');
    const isNew = !b;
    b = b || { name: '', default_weight: 0, custom_emoji_weight: 0, paid_weight: 0, weights: {}, push_enabled: false, builtin: false };
    const lock = b.builtin ? 'disabled' : '';
    ed.hidden = false;
    ed.innerHTML = `
      <h2 style="margin-top:0">${isNew ? '新建榜单' : `编辑「${esc(b.name)}」`}</h2>
      ${b.builtin ? '<p class="muted">内置的「综合」榜固定按反应总数计分，只能修改是否参与定期推送。</p>' : ''}
      <form id="f">
        <label class="field"><span>名称</span><input id="name" required maxlength="30" value="${esc(b.name)}" ${lock}></label>
        <div ${b.builtin ? 'hidden' : ''}>
          <span class="muted" style="font-size:.9rem">表情权重（-10 到 100，可以是小数，负数表示扣分）</span>
          <div class="weights" id="weights">${Object.entries(b.weights).map(([e, w]) => weightRow(e, w)).join('')}</div>
          <button class="ghost" type="button" id="addRow">添加表情</button>
          ${emojis.length ? `<p class="muted" style="font-size:.9rem;margin:1rem 0 0">当前群里出现过的表情，点一下加入：</p>
          <div class="chips" id="chips">${emojis.filter(e => e.kind === 'emoji').slice(0, 30)
            .map(e => `<button class="chip" type="button" data-e="${esc(e.label)}">${esc(e.label)}<b>${fmtNum(e.count)}</b></button>`).join('')}</div>` : ''}
          <div class="defaults" style="margin-top:1.25rem">
            <label class="field"><span>其余普通表情</span><input id="dw" type="number" step="0.1" min="-10" max="100" value="${b.default_weight}"></label>
            <label class="field"><span>自定义表情</span><input id="cw" type="number" step="0.1" min="-10" max="100" value="${b.custom_emoji_weight}"></label>
            <label class="field"><span>Stars 打赏</span><input id="pw" type="number" step="0.1" min="-10" max="100" value="${b.paid_weight}"></label>
          </div>
        </div>
        <label class="check" style="margin:.5rem 0 1.5rem"><input type="checkbox" id="push" ${b.push_enabled ? 'checked' : ''}> 参与定期精华推送</label>
        <div class="inline">
          <button class="btn" type="submit">${isNew ? '创建榜单' : '保存榜单'}</button>
          <button class="ghost" type="button" id="cancel">取消</button>
        </div>
        <p class="status" id="st" role="status"></p>
      </form>`;

    const weights = $(ed, '#weights');
    $(ed, '#addRow').onclick = () => { weights.insertAdjacentHTML('beforeend', weightRow()); weights.lastElementChild.querySelector('input').focus(); };
    weights.onclick = e => { if (e.target.dataset.act === 'rm') e.target.closest('.w').remove(); };
    const chips = $(ed, '#chips');
    if (chips) chips.onclick = e => {
      const c = e.target.closest('.chip');
      if (!c) return;
      const norm = v => v.replace(/\uFE0F/g, '').trim();
      const exists = [...weights.querySelectorAll('.w input:first-child')].some(i => norm(i.value) === norm(c.dataset.e));
      if (!exists) weights.insertAdjacentHTML('beforeend', weightRow(c.dataset.e, 1));
    };
    $(ed, '#cancel').onclick = () => { ed.hidden = true; };
    $(ed, '#f').onsubmit = async e => {
      e.preventDefault();
      const map = {};
      weights.querySelectorAll('.w').forEach(w => {
        const [emoji, weight] = w.querySelectorAll('input');
        if (emoji.value.trim()) map[emoji.value.trim()] = Number(weight.value);
      });
      const body = {
        name: $(ed, '#name').value,
        default_weight: Number($(ed, '#dw').value), custom_emoji_weight: Number($(ed, '#cw').value),
        paid_weight: Number($(ed, '#pw').value), weights: map, push_enabled: $(ed, '#push').checked,
      };
      if (b.builtin) Object.assign(body, { name: b.name, default_weight: 1, custom_emoji_weight: 1, paid_weight: 1, weights: {} });
      await busy(e.submitter, async () => {
        try {
          await api(isNew ? '/api/boards' : `/api/boards/${b.id}`, { method: isNew ? 'POST' : 'PUT', body });
          ed.hidden = true;
          await load();
        } catch (err) {
          setStatus($(ed, '#st'), err.message, 'err');
        }
      });
    };
    ed.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    $(ed, b.builtin ? '#push' : '#name').focus({ preventScroll: true });
  }

  $(root, '#new').onclick = () => openEditor(null);
  $(root, '#list').onclick = async e => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const b = boards.find(x => x.id === Number(btn.closest('.row').dataset.id));
    if (btn.dataset.act === 'edit') return openEditor(b);
    if (!confirm(`删除榜单「${b.name}」？`)) return;
    await busy(btn, async () => {
      try { await api(`/api/boards/${b.id}`, { method: 'DELETE' }); await load(); } catch (err) { alert(err.message); }
    });
  };

  await load();
}
