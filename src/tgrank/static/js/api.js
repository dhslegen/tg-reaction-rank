// 统一的 API 调用：写操作一律带 JSON Content-Type（后端据此防 CSRF），401 跳登录页
export class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

function messageOf(data) {
  if (!data) return '';
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map(d => String(d.msg || '').replace(/^Value error, /, '')).join('；');
  }
  return '';
}

export async function api(path, { method = 'GET', body, form } = {}) {
  const opt = { method, headers: {}, credentials: 'same-origin' };
  if (form) {
    opt.body = form;
  } else if (method !== 'GET' && method !== 'DELETE') {
    opt.headers['content-type'] = 'application/json';
    opt.body = JSON.stringify(body ?? {});
  }
  const r = await fetch(path, opt);
  if (r.status === 401 && path !== '/api/auth/login') {
    location.hash = '#/login';
    throw new ApiError(401, '登录已过期，请重新登录');
  }
  if (r.status === 204) return null;
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, messageOf(data) || `请求失败（${r.status}）`, data);
  return data;
}
