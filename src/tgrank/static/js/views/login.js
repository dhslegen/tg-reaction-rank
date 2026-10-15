import { api } from '../api.js';
import { $, setStatus } from '../ui.js';

export function render(root) {
  root.innerHTML = `
    <section class="login">
      <h1>群消息反应排行</h1>
      <p class="lede">输入部署时在 <code>.env</code> 里设置的 <code>ADMIN_PASSWORD</code>。</p>
      <form id="f">
        <label class="sr-only" for="pw">管理员密码</label>
        <input id="pw" type="password" autocomplete="current-password" required autofocus placeholder="管理员密码">
        <button class="btn" type="submit">登录</button>
      </form>
      <p class="status" id="st" role="status"></p>
    </section>`;
  $(root, '#f').onsubmit = async e => {
    e.preventDefault();
    const st = $(root, '#st');
    try {
      await api('/api/auth/login', { method: 'POST', body: { password: $(root, '#pw').value } });
      location.hash = '#/';
    } catch (err) {
      setStatus(st, err.message, 'err');
      $(root, '#pw').select();
    }
  };
}
