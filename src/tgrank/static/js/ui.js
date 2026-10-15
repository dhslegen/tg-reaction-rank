// 小工具：转义、格式化、状态行、本地偏好
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const $ = (root, sel) => root.querySelector(sel);

export const fmtNum = n => Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 });

const fmtFull = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });
export const fmtDate = ts => fmtFull.format(ts * 1000);

export function ago(ts) {
  if (!ts) return '从未';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return '刚刚';
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  return `${Math.floor(s / 86400)} 天前`;
}

export function setStatus(el, msg, kind) {
  el.textContent = msg || '';
  el.classList.toggle('err', kind === 'err');
  el.classList.toggle('ok', kind === 'ok');
}

export const prefs = {
  get: (k, d = null) => { try { return JSON.parse(localStorage.getItem(`tgrank.${k}`)) ?? d; } catch { return d; } },
  set: (k, v) => localStorage.setItem(`tgrank.${k}`, JSON.stringify(v)),
};

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// 按钮执行异步操作期间禁用，避免重复提交
export async function busy(btn, fn) {
  btn.disabled = true;
  try { return await fn(); } finally { btn.disabled = false; }
}

export const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
