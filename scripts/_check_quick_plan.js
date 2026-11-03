// 临时校验：总览点日期格 → 选运动 → 自动开新建计划表单 → 保存落库 → 跳回总览可见。
// 只删除本次自建的那条计划（按 remark 匹配 + DELETE by id），不碰用户其他数据。
const { spawn } = require('child_process');
const CHROME = 'C:\\Users\\admin\\AppData\\Local\\ms-playwright\\chromium_headless_shell-1243\\chrome-headless-shell-win64\\chrome-headless-shell.exe';
const PORT = 9226;
const BASE = 'http://127.0.0.1:8010';
const REMARK = 'UI自测-总览快捷建计划-可删';
const sleep = ms => new Promise(r => setTimeout(r, ms));

const chrome = spawn(CHROME, [
  '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=' + PORT, '--window-size=1440,1000', 'about:blank'
], { stdio: 'ignore' });

async function getWsUrl() {
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch('http://127.0.0.1:' + PORT + '/json/list');
      const list = await r.json();
      const page = list.find(t => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch (e) {}
    await sleep(300);
  }
  throw new Error('CDP not ready');
}

async function main() {
  const ws = new WebSocket(await getWsUrl());
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let seq = 0; const pending = new Map();
  ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
  const cmd = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pending.set(id, m => m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result)); ws.send(JSON.stringify({ id, method, params })); });
  const ev = async expression => { const r = await cmd('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); return r.result && r.result.value; };

  await cmd('Page.enable'); await cmd('Runtime.enable');
  await cmd('Page.navigate', { url: BASE + '/login' });
  await sleep(1500);
  await ev(`fetch('${BASE}/login', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'username=admin&password=admin123', credentials: 'include', redirect: 'manual' })`);
  await sleep(600);

  let failed = 0;
  const check = (name, ok, detail = '') => { console.log((ok ? '  ✔ ' : '  ✘ ') + name + (detail ? '  ' + detail : '')); if (!ok) failed++; };

  // 1) 周视图：点一个日期格 → 应弹出选运动弹窗
  await cmd('Page.navigate', { url: BASE + '/overview' });
  await sleep(2000);
  const targetDay = await ev(`(() => { const c = document.querySelector('#ovWeekStrip .ws-day'); return c ? c.dataset.addDay : null; })()`);
  check('周视图渲染出日期格', !!targetDay, 'targetDay=' + targetDay);
  await ev(`document.querySelector('#ovWeekStrip .ws-day .wd-add').click()`);
  await sleep(500);
  let pickOpen = await ev(`document.getElementById('modalOvPick').classList.contains('open')`);
  check('点日期格 → 弹出「选运动」弹窗', pickOpen);

  // 2) 选游泳 → 应跳到 /swim?date=X&newplan=1 且新建计划表单已自动打开、日期已预选
  await ev(`document.querySelector('#modalOvPick [data-pick="swim"]').click()`);
  await sleep(2200);
  const afterJump = await ev(`(() => ({ url: location.href, modal: document.getElementById('modalSwim').classList.contains('open'), date: (document.querySelector('#formSwim [name="record_date"]')||{}).value || '', title: document.getElementById('modalSwimTitle').textContent }))()`);
  check('跳转游泳页且新建计划弹窗自动打开', afterJump.modal === true, JSON.stringify(afterJump));
  check('日期预选为点击的那天', afterJump.date === targetDay, 'expect=' + targetDay + ' got=' + afterJump.date);

  // 3) 填表保存
  await ev(`(() => {
    const f = document.forms.formSwim;
    f.distance_m.value = '1000';
    f.duration_min.value = '30';
    f.main_stroke.value = 'freestyle';
    f.remark.value = '${REMARK}';
    f.requestSubmit();
  })()`);
  await sleep(3800);

  // 4) 保存后应跳回总览当天
  const back = await ev(`(() => ({ url: location.href, day: (document.querySelector('#ovWeekStrip .ws-day[data-add-day="${targetDay}"] .ov-chip.swim')||{}).textContent || '' }))()`);
  check('保存后跳回总览', back.url.indexOf('/overview') >= 0 && back.url.indexOf(targetDay) >= 0, back.url);
  check('该天出现游泳计划标签', back.day.indexOf('游泳') >= 0, back.day);

  // 5) 月视图：点日历格 → 选运动弹窗
  await cmd('Page.navigate', { url: BASE + '/overview?mode=month' });
  await sleep(2000);
  await ev(`document.querySelector('#ovCalGrid .ov-cal-cell:not(.blank)').click()`);
  await sleep(500);
  const pick2 = await ev(`document.getElementById('modalOvPick').classList.contains('open')`);
  check('月视图点日期格 → 弹出选运动弹窗', pick2);
  await ev(`document.querySelector('#modalOvPick [data-close]').click()`);

  // 6) 日视图：运动卡头部「＋ 计划」→ 直接跳游泳页新建
  await cmd('Page.navigate', { url: BASE + '/overview?mode=day' });
  await sleep(2000);
  await ev(`document.querySelector('.ov-sport-card [data-newplan="swim"]').click()`);
  await sleep(2200);
  const dayJump = await ev(`(() => ({ url: location.href, modal: document.getElementById('modalSwim').classList.contains('open') }))()`);
  check('日视图点「＋ 计划」→ 直接开游泳新建计划弹窗', dayJump.modal === true, JSON.stringify(dayJump));
  await ev(`document.querySelector('#modalSwim [data-close]').click()`);

  // 7) 清理：仅删除本次自建的那条（按 remark 匹配 + 精确 id DELETE）
  const cleaned = await ev(`(async () => {
    const r = await fetch('${BASE}/api/swim-records/daily?date=' + '${targetDay}', { credentials: 'include' });
    const data = await r.json();
    const mine = (data.list || []).find(x => x.remark === '${REMARK}');
    if (!mine) return 'NOT_FOUND';
    const del = await fetch('${BASE}/api/swim-records/' + mine.id, { method: 'DELETE', credentials: 'include' });
    return 'DELETED id=' + mine.id + ' status=' + del.status;
  })()`);
  check('清理本次自建数据（不动其他）', cleaned.indexOf('DELETED') === 0, cleaned);

  ws.close();
  chrome.kill();
  console.log('结果：', failed === 0 ? '全部通过' : '失败 ' + failed);
  process.exit(failed ? 1 : 0);
}
main().catch(e => { console.error('ERR', e.message); chrome.kill(); process.exit(2); });
