// 运行期设置：同步节奏、精华推送；保存后立即按新节奏排程
import { api } from '../api.js';
import { $, busy, esc, fmtDate, setStatus, WEEKDAYS } from '../ui.js';

const weekdayOptions = sel => WEEKDAYS.map((w, i) => `<option value="${i}" ${i === sel ? 'selected' : ''}>${w}</option>`).join('');

function pushResult(r) {
  if (!r) return '还没有推送过。';
  const when = fmtDate(r.at);
  if (!r.ok) return `${when} 推送失败：${r.error}`;
  if (!r.sent) return `${when}：${r.error}`;
  return `${when} 推送成功，共 ${r.sent} 条消息。`;
}

export async function render(root) {
  const [s, sched, tg] = await Promise.all([api('/api/settings'), api('/api/schedule'), api('/api/tg/status')]);
  let channels = [];
  if (tg.state === 'authorized') {
    channels = (await api('/api/tg/dialogs').catch(() => [])).filter(d => d.kind_label === '频道');
  }
  const targetKnown = s.push.target === 'me' || channels.some(c => String(c.chat_id) === s.push.target);

  root.innerHTML = `
    <h1>设置</h1>
    <p class="lede">保存后立即生效，不需要重启。部署相关的参数（密码、API 凭据、时区、代理）在 <code>.env</code> 里修改。</p>
    <form id="f">
      <h2>同步</h2>
      <div class="defaults">
        <label class="field"><span>拉取新消息间隔（分钟）</span><input id="newInt" type="number" min="5" max="1440" value="${s.sync.new_interval_min}" required></label>
        <label class="field"><span>刷新近期反应间隔（分钟）</span><input id="refInt" type="number" min="15" max="1440" value="${s.sync.refresh_interval_min}" required></label>
        <label class="field"><span>刷新最近几天的消息</span><input id="refDays" type="number" min="1" max="90" value="${s.sync.refresh_days}" required></label>
      </div>
      <div class="field">
        <span>每周全量校准（修正较早消息的编辑与删除）</span>
        <div class="inline"><select id="calDay" aria-label="校准星期">${weekdayOptions(s.sync.calibrate_weekday)}</select>
        <input id="calTime" type="time" value="${s.sync.calibrate_time}" required aria-label="校准时间"></div>
      </div>

      <h2>定期精华推送</h2>
      <label class="check" style="margin-bottom:1rem"><input type="checkbox" id="pushOn" ${s.push.enabled ? 'checked' : ''}> 定期把各榜单前 10 名推送给自己</label>
      <div id="pushBox">
        <div class="field">
          <span>频率</span>
          <div class="inline">
            <select id="freq" aria-label="频率">
              <option value="weekly" ${s.push.frequency === 'weekly' ? 'selected' : ''}>每周</option>
              <option value="monthly" ${s.push.frequency === 'monthly' ? 'selected' : ''}>每月</option>
            </select>
            <select id="weekday" aria-label="星期">${weekdayOptions(s.push.weekday)}</select>
            <label class="inline" id="mdWrap">第 <input id="monthday" type="number" min="1" max="28" value="${s.push.monthday}" style="width:4.5rem"> 日</label>
            <input id="time" type="time" value="${s.push.time}" required aria-label="推送时间">
          </div>
          <small>每期统计上一次推送日到本次推送日之间的消息，推送当天的消息归下一期。</small>
        </div>
        <label class="field"><span>改为统计推送前的固定天数（留空则按上面的周期）</span>
          <input id="rangeDays" type="number" min="1" max="366" value="${s.push.range_days ?? ''}" placeholder="按周期" style="width:8rem"></label>
        <label class="field"><span>发送到</span>
          <select id="target">
            <option value="me">收藏夹（Saved Messages）</option>
            ${channels.map(c => `<option value="${c.chat_id}">频道：${esc(c.title)}</option>`).join('')}
            ${targetKnown ? '' : `<option value="${esc(s.push.target)}">频道 ${esc(s.push.target)}（当前账号不可见）</option>`}
          </select>
          <small>不会推送回原群。要发到频道，请用你自己创建的私人频道。</small>
        </label>
        <p class="muted" style="font-size:.9rem">哪些榜单参与推送，在<a href="#/boards">榜单</a>页逐个设置。</p>
      </div>

      <div class="inline" style="margin-top:1.5rem"><button class="btn" type="submit">保存设置</button></div>
      <p class="status" id="st" role="status"></p>
    </form>

    <h2>运行情况</h2>
    <ul class="rows" id="jobs"></ul>
    <p style="margin-top:1.25rem" id="lastPush"></p>
    <button class="ghost" id="testPush" type="button">立即推送一次</button>
    <p class="status" id="pushSt" role="status"></p>`;

  $(root, '#target').value = s.push.target;
  const sync = () => {
    const weekly = $(root, '#freq').value === 'weekly';
    $(root, '#weekday').hidden = !weekly;
    $(root, '#mdWrap').hidden = weekly;
    $(root, '#pushBox').style.opacity = $(root, '#pushOn').checked ? '' : '.5';
  };
  $(root, '#freq').onchange = $(root, '#pushOn').onchange = sync;
  sync();

  function paintSchedule(view) {
    $(root, '#jobs').innerHTML = view.jobs.map(j => `
      <li class="row"><div class="row-title">${esc(j.label)}</div>
      <div class="row-meta">${j.next_run ? `下次 ${fmtDate(j.next_run)}` : '已关闭'}</div></li>`).join('');
    $(root, '#lastPush').textContent = `上次推送：${pushResult(view.last_push)}`;
  }
  paintSchedule(sched);

  $(root, '#f').onsubmit = async e => {
    e.preventDefault();
    const num = id => Number($(root, id).value);
    const body = {
      sync: {
        new_interval_min: num('#newInt'), refresh_interval_min: num('#refInt'), refresh_days: num('#refDays'),
        calibrate_weekday: num('#calDay'), calibrate_time: $(root, '#calTime').value,
      },
      push: {
        enabled: $(root, '#pushOn').checked, frequency: $(root, '#freq').value,
        weekday: num('#weekday'), monthday: num('#monthday'), time: $(root, '#time').value,
        range_days: $(root, '#rangeDays').value ? num('#rangeDays') : null, target: $(root, '#target').value,
      },
    };
    await busy(e.submitter, async () => {
      try {
        await api('/api/settings', { method: 'PUT', body });
        setStatus($(root, '#st'), '设置已保存，新的节奏已生效。', 'ok');
        paintSchedule(await api('/api/schedule'));
      } catch (err) {
        setStatus($(root, '#st'), err.message, 'err');
      }
    });
  };

  $(root, '#testPush').onclick = e => busy(e.target, async () => {
    setStatus($(root, '#pushSt'), '正在推送最近一期…');
    try {
      await api('/api/push/test', { method: 'POST' });
      setStatus($(root, '#pushSt'), '');  // 结果统一显示在「上次推送」一行
      paintSchedule(await api('/api/schedule'));
    } catch (err) {
      setStatus($(root, '#pushSt'), err.message, 'err');
    }
  });
}
