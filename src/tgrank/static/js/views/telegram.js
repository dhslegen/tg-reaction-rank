// Telegram 账号：状态 + 登录向导（手机号 → 验证码 → 两步验证密码）
import { api } from '../api.js';
import { $, busy, esc, setStatus } from '../ui.js';

const STATE_TEXT = {
  connecting: '正在连接 Telegram…',
  logged_out: '还没有登录 Telegram 账号。',
  relogin_required: 'Telegram 登录已失效，自动同步和推送已暂停。重新登录后会自动恢复。',
  offline: '暂时连不上 Telegram，服务会自动重试。如果一直连不上，检查服务器网络或 .env 里的 TG_PROXY。',
};

export async function render(root) {
  let alive = true;
  let timer = null;
  let phone = '';  // 重绘后保留已填的手机号

  async function paint() {
    const s = await api('/api/tg/status');
    if (!alive) return;
    clearTimeout(timer);

    if (s.state === 'unconfigured') {
      root.innerHTML = `
        <h1>Telegram</h1>
        <p class="lede">还没有配置 Telegram API 凭据。在 <a href="https://my.telegram.org" target="_blank" rel="noopener">my.telegram.org</a>
        的 API development tools 里申请，把 <code>TG_API_ID</code> 和 <code>TG_API_HASH</code> 填进 <code>.env</code>，然后重启服务。</p>`;
      return;
    }

    if (s.state === 'authorized') {
      const me = s.me || {};
      root.innerHTML = `
        <h1>Telegram</h1>
        <p class="lede">已登录 <strong>${esc(me.name)}</strong>${me.username ? `（@${esc(me.username)}）` : ''}${me.phone ? `，${esc(me.phone)}` : ''}。
        ${s.proxy ? '通过 TG_PROXY 代理连接。' : ''}</p>
        <p style="margin-top:2rem"><a class="btn" href="#/chats" style="text-decoration:none">去添加要同步的群</a></p>
        <h2>退出登录</h2>
        <p class="muted">退出后自动同步和推送都会停止，已收录的数据保留。换号登录时，当前账号访问不到的群会自动暂停同步。</p>
        <button class="ghost danger" id="logout" type="button">退出 Telegram 登录</button>`;
      $(root, '#logout').onclick = e => busy(e.target, async () => {
        if (!confirm('退出当前 Telegram 账号的登录？')) return;
        await api('/api/tg/logout', { method: 'POST' });
        paint();
      });
      return;
    }

    if (s.state === 'connecting') timer = setTimeout(paint, 1500);
    const step = s.login_step;  // null | 'code' | 'password'
    const cls = n => (n === 1 ? (step ? 'done' : 'current') : n === 2 ? (step === 'code' ? 'current' : step === 'password' ? 'done' : '') : step === 'password' ? 'current' : '');
    root.innerHTML = `
      <h1>Telegram</h1>
      <p class="lede">${STATE_TEXT[s.state] || ''}${s.last_error && s.state !== 'relogin_required' ? ` ${esc(s.last_error)}` : ''}</p>
      <ol class="steps">
        <li class="${cls(1)}"><div>
          <h3>手机号</h3>
          <form id="fPhone" class="inline">
            <label class="sr-only" for="phone">手机号</label>
            <input id="phone" type="tel" autocomplete="tel" placeholder="+8613800000000" required value="${esc(phone)}">
            <button class="${step ? 'ghost' : 'btn'}" type="submit">${step ? '重新发送验证码' : '发送验证码'}</button>
          </form>
          <p class="muted" style="font-size:.9rem;margin:.5rem 0 0">验证码会发到你已登录的 Telegram 客户端里，而不是短信。</p>
        </div></li>
        <li class="${cls(2)}"><div>
          <h3>验证码</h3>
          <form id="fCode" class="inline">
            <label class="sr-only" for="code">验证码</label>
            <input id="code" inputmode="numeric" autocomplete="one-time-code" placeholder="12345" required ${step === 'code' ? '' : 'disabled'}>
            <button class="btn" type="submit" ${step === 'code' ? '' : 'disabled'}>登录</button>
          </form>
        </div></li>
        <li class="${cls(3)}"><div>
          <h3>两步验证密码</h3>
          <p class="muted" style="font-size:.9rem;margin:0 0 .5rem">只有账号开启了两步验证才需要这一步。</p>
          <form id="fPw" class="inline">
            <label class="sr-only" for="pw">两步验证密码</label>
            <input id="pw" type="password" autocomplete="current-password" required ${step === 'password' ? '' : 'disabled'}>
            <button class="btn" type="submit" ${step === 'password' ? '' : 'disabled'}>确认</button>
          </form>
        </div></li>
      </ol>
      <p class="status" id="st" role="status"></p>
      <p class="muted" style="font-size:.9rem;margin-top:2rem">也可以在服务器上运行 <code>docker compose run --rm app login</code> 完成登录，然后执行 <code>docker compose restart app</code>。</p>`;

    const st = $(root, '#st');
    const submit = (id, path, body) => $(root, id).onsubmit = async e => {
      e.preventDefault();
      const btn = e.target.querySelector('button');
      await busy(btn, async () => {
        try {
          const r = await api(path, { method: 'POST', body: body() });
          await paint();
          if (r.next === 'code') setStatus($(root, '#st'), '验证码已发送，请在 Telegram 客户端里查看。', 'ok');
          if (r.next === 'code') $(root, '#code')?.focus();
          if (r.next === 'password') $(root, '#pw')?.focus();
        } catch (err) {
          setStatus(st, err.message, 'err');
        }
      });
    };
    submit('#fPhone', '/api/tg/login/phone', () => ({ phone: (phone = $(root, '#phone').value) }));
    submit('#fCode', '/api/tg/login/code', () => ({ code: $(root, '#code').value }));
    submit('#fPw', '/api/tg/login/password', () => ({ password: $(root, '#pw').value }));
  }

  await paint();
  return () => { alive = false; clearTimeout(timer); };
}
