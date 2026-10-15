// hash 路由：#/、#/boards、#/chats、#/telegram、#/settings、#/login
import { api } from './api.js';
import { esc } from './ui.js';

const views = {
  '': () => import('./views/rank.js'),
  boards: () => import('./views/boards.js'),
  chats: () => import('./views/chats.js'),
  telegram: () => import('./views/telegram.js'),
  settings: () => import('./views/settings.js'),
  login: () => import('./views/login.js'),
};

const view = document.getElementById('view');
const top = document.getElementById('top');
const banner = document.getElementById('banner');
let cleanup = null;
let seq = 0;

function route() {
  const name = location.hash.replace(/^#\/?/, '').split('?')[0];
  return name in views ? name : '';
}

async function refreshBanner(name) {
  if (name === 'login' || name === 'telegram') { banner.hidden = true; return; }
  try {
    const s = await api('/api/tg/status');
    const msg = {
      relogin_required: `Telegram 登录已失效，自动同步和推送已暂停。<a href="#/telegram">重新登录</a>`,
      offline: `暂时连不上 Telegram，会自动重试。${esc(s.last_error || '')}`,
    }[s.state];
    const flood = s.flood_until ? `Telegram 限流中，${new Date(s.flood_until * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} 后继续同步。` : '';
    banner.innerHTML = msg || flood ? `<span>${msg || flood}</span>` : '';
    banner.hidden = !(msg || flood);
  } catch { banner.hidden = true; }
}

async function render() {
  const mine = ++seq;
  const name = route();
  if (cleanup) { cleanup(); cleanup = null; }
  top.hidden = name === 'login';
  document.querySelectorAll('.nav a').forEach(a => {
    if (a.dataset.route === name) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  refreshBanner(name);
  const mod = await views[name]();
  if (mine !== seq) return;  // 用户已经切到别的页面
  view.innerHTML = '';
  window.scrollTo(0, 0);
  cleanup = (await mod.render(view)) || null;
  view.focus?.();
}

document.getElementById('logout').onclick = async () => {
  await api('/api/auth/logout', { method: 'POST' }).catch(() => {});
  location.hash = '#/login';
};

window.addEventListener('hashchange', render);

(async () => {
  if (route() !== 'login') {
    try { await api('/api/auth/me'); } catch { return; }  // api() 已跳转到登录页
  }
  render();
})();
