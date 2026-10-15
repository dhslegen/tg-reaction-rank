// 群管理：已收录的群、从 Telegram 添加、导入 Desktop 导出
import { api } from '../api.js';
import { $, ago, busy, esc, fmtNum, setStatus } from '../ui.js';

export async function render(root) {
  root.innerHTML = `
    <h1>群</h1>
    <p class="lede">在这里管理收录的群。通过 Telegram 账号添加的群会自动同步；导入的聊天记录是一次性的快照。</p>
    <ul class="rows" id="list" style="margin-top:2rem"></ul>
    <p class="none" id="empty" hidden>还没有收录任何群。</p>

    <h2>从 Telegram 添加</h2>
    <div id="dialogs"></div>

    <h2>导入 Telegram Desktop 导出</h2>
    <div class="drop" id="drop">
      <ol>
        <li>在 Telegram Desktop 打开这个群，点右上角 <kbd>⋮</kbd>，选择「导出聊天记录」。</li>
        <li>取消勾选所有媒体类型，格式选「机器可读的 JSON」，时间范围选全部。</li>
        <li>把导出得到的 <kbd>result.json</kbd> 拖到这里，或者点右侧按钮选择。</li>
      </ol>
      <button class="btn" id="pick" type="button">选择 result.json</button>
    </div>
    <p class="status" id="importSt" role="status"></p>
    <input type="file" id="file" accept=".json,application/json" hidden>`;

  let timer = null;
  let alive = true;  // 离开页面后，进行中的请求不再写 DOM

  async function loadChats() {
    const chats = await api('/api/chats');
    if (!alive) return chats;
    $(root, '#empty').hidden = chats.length > 0;
    $(root, '#list').innerHTML = chats.map(c => {
      const state = c.source !== 'api' ? '导入的快照'
        : !c.sync_enabled ? '已暂停同步'
        : !c.history_complete ? '正在拉取历史消息…'
        : `上次同步 ${ago(c.last_sync_at)}`;
      return `
      <li class="row" data-id="${c.chat_id}">
        <div>
          <div class="row-title">${esc(c.title)}</div>
          <div class="row-meta">
            <span>${c.kind.endsWith('_channel') ? '频道' : '群'}${c.is_forum ? '（话题群）' : ''}</span>
            <span>${state}</span>
            ${c.last_error ? `<span class="err">${esc(c.last_error)}</span>` : ''}
          </div>
          <div class="stats">
            <div><b class="num-inline">${fmtNum(c.messages)}</b><span>条消息</span></div>
            <div><b class="num-inline">${fmtNum(c.reacted)}</b><span>条收到反应</span></div>
          </div>
        </div>
        <div class="row-actions">
          ${c.source === 'api' && c.sync_enabled ? '<button class="ghost" data-act="sync" type="button">立即同步</button>' : ''}
          ${c.source === 'api' ? `<button class="ghost" data-act="toggle" type="button">${c.sync_enabled ? '暂停同步' : '恢复同步'}</button>` : ''}
          <button class="ghost danger" data-act="delete" type="button">删除</button>
        </div>
      </li>`;
    }).join('');
    // 有群在回填历史时每 5 秒刷新一次进度
    clearTimeout(timer);
    if (chats.some(c => c.sync_enabled && !c.history_complete)) timer = setTimeout(loadChats, 5000);
    return chats;
  }

  $(root, '#list').onclick = async e => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const row = btn.closest('.row');
    const id = row.dataset.id;
    const title = $(row, '.row-title').textContent;
    await busy(btn, async () => {
      try {
        if (btn.dataset.act === 'sync') {
          const r = await api(`/api/chats/${id}/sync`, { method: 'POST' });
          btn.textContent = r.queued ? '已开始同步' : r.reason;
          setTimeout(loadChats, 3000);
          return;
        }
        if (btn.dataset.act === 'toggle') {
          await api(`/api/chats/${id}`, { method: 'PATCH', body: { sync_enabled: btn.textContent === '恢复同步' } });
        } else if (confirm(`删除「${title}」及其全部消息数据？这个操作无法撤销。`)) {
          await api(`/api/chats/${id}`, { method: 'DELETE' });
        }
        await loadChats();
        loadDialogs();
      } catch (err) {
        alert(err.message);
      }
    });
  };

  async function loadDialogs() {
    const box = $(root, '#dialogs');
    const tg = await api('/api/tg/status');
    if (!alive) return;
    if (tg.state !== 'authorized') {
      box.innerHTML = `<p class="muted">要自动同步，先<a href="#/telegram">登录 Telegram 账号</a>。</p>`;
      return;
    }
    box.innerHTML = `<p class="muted">正在读取你加入的群和频道…</p>`;
    try {
      const list = await api('/api/tg/dialogs');
      if (!alive) return;
      box.innerHTML = list.length ? `<ul class="rows">${list.map(d => `
        <li class="row" data-id="${d.chat_id}">
          <div><div class="row-title">${esc(d.title)}</div>
            <div class="row-meta"><span>${d.kind_label}${d.is_forum ? '（话题群）' : ''}</span></div></div>
          <div class="row-actions">${d.added ? '<span class="muted">已添加</span>'
            : '<button class="ghost" type="button" data-act="add">添加并同步</button>'}</div>
        </li>`).join('')}</ul>` : '<p class="muted">这个账号没有加入任何群或频道。</p>';
    } catch (err) {
      box.innerHTML = `<p class="status err">${esc(err.message)}</p>`;
    }
  }

  $(root, '#dialogs').onclick = async e => {
    const btn = e.target.closest('button[data-act="add"]');
    if (!btn) return;
    await busy(btn, async () => {
      try {
        await api('/api/chats', { method: 'POST', body: { chat_id: Number(btn.closest('.row').dataset.id) } });
        btn.replaceWith(Object.assign(document.createElement('span'), { className: 'muted', textContent: '已添加，正在拉取历史' }));
        loadChats();
      } catch (err) { alert(err.message); }
    });
  };

  // ---------- 导入 ----------
  const file = $(root, '#file');
  const drop = $(root, '#drop');
  const st = $(root, '#importSt');
  $(root, '#pick').onclick = () => file.click();
  file.onchange = () => file.files[0] && upload(file.files[0]);
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => {
    e.preventDefault();
    drop.classList.remove('over');
    const f = e.dataTransfer.files[0];
    if (f) upload(f);
  };

  async function upload(f) {
    setStatus(st, `正在上传 ${f.name}（${(f.size / 1048576).toFixed(1)} MB）…`);
    const form = new FormData();
    form.append('file', f);
    try {
      const { job_id } = await api('/api/imports', { method: 'POST', form });
      for (;;) {
        const job = await api(`/api/jobs/${job_id}`);
        if (job.state === 'running') {
          setStatus(st, `正在导入，已读取 ${fmtNum(job.processed)} 条消息…`);
          await new Promise(r => setTimeout(r, 800));
          continue;
        }
        if (job.state === 'failed') throw new Error(job.error);
        const r = job.result;
        const kept = r.stats.kept ? `，${fmtNum(r.stats.kept)} 条已有 API 同步的较新版本，保留不变` : '';
        setStatus(st, r.reacted
          ? `已导入「${r.title}」：读取 ${fmtNum(r.messages)} 条消息，新增 ${fmtNum(r.stats.inserted)} 条，更新 ${fmtNum(r.stats.updated)} 条${kept}。`
          : `已导入「${r.title}」的 ${fmtNum(r.messages)} 条消息，但其中没有任何反应数据。把 Telegram Desktop 升级到最新版后重新导出。`,
        r.reacted ? 'ok' : 'err');
        break;
      }
      loadChats();
    } catch (err) {
      setStatus(st, err.message, 'err');
    } finally {
      file.value = '';
    }
  }

  await loadChats();
  loadDialogs();
  return () => { alive = false; clearTimeout(timer); };
}
