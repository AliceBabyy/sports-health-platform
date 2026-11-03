// 临时校验：周/月视图点「运动标签」→ 当日详情弹窗；点「日期格空白」→ 选运动弹窗。两者互不干扰。
const { spawn } = require('child_process');
const CHROME = 'C:\\Users\\admin\\AppData\\Local\\ms-playwright\\chromium_headless_shell-1243\\chrome-headless-shell-win64\\chrome-headless-shell.exe';
const PORT = 9227, BASE = 'http://127.0.0.1:8010';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const chrome = spawn(CHROME, ['--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=' + PORT, '--window-size=1440,1000', 'about:blank'], { stdio: 'ignore' });

async function getWsUrl() {
  for (let i = 0; i < 40; i++) {
    try { const r = await fetch('http://127.0.0.1:' + PORT + '/json/list'); const l = await r.json(); const p = l.find(t => t.type === 'page'); if (p) return p.webSocketDebuggerUrl; } catch (e) {}
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
  const ev = async x => (await cmd('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true })).result.value;
  await cmd('Page.enable'); await cmd('Runtime.enable');
  await cmd('Page.navigate', { url: BASE + '/login' }); await sleep(1500);
  await ev(`fetch('${BASE}/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'username=admin&password=admin123',credentials:'include',redirect:'manual'})`);
  await sleep(600);
  let failed = 0;
  const check = (n, ok, d='') => { console.log((ok?'  ✔ ':'  ✘ ')+n+(d?'  '+d:'')); if (!ok) failed++; };

  // 周视图：点标签 → 详情弹窗；点格空白处 → 选运动弹窗
  await cmd('Page.navigate', { url: BASE + '/overview' });
  await sleep(2000);
  const hasChip = await ev(`!!document.querySelector('#ovWeekStrip .ov-chip')`);
  if (hasChip) {
    await ev(`document.querySelector('#ovWeekStrip .ov-chip').click()`); await sleep(800);
    let open = await ev(`document.getElementById('modalOvDay').classList.contains('open')`);
    check('周视图点运动标签 → 当日详情弹窗', open);
    await ev(`document.querySelector('#modalOvDay [data-close]').click()`); await sleep(300);
  } else console.log('  · 本周无标签，跳过');
  await ev(`document.querySelector('#ovWeekStrip .ws-day .wd-num').click()`); await sleep(500);
  let pick = await ev(`document.getElementById('modalOvPick').classList.contains('open')`);
  check('周视图点日期格空白 → 选运动弹窗', pick);
  await ev(`document.querySelector('#modalOvPick [data-close]').click()`); await sleep(300);

  // 月视图：点标签 → 详情弹窗
  await cmd('Page.navigate', { url: BASE + '/overview?mode=month' });
  await sleep(2000);
  const mChip = await ev(`document.querySelector('#ovCalGrid .ov-cal-cell:not(.blank) .ov-chip')`);
  if (mChip) {
    await ev(`document.querySelector('#ovCalGrid .ov-cal-cell:not(.blank) .ov-chip').click()`); await sleep(800);
    const open = await ev(`document.getElementById('modalOvDay').classList.contains('open')`);
    check('月视图点运动标签 → 当日详情弹窗', open);
  } else console.log('  · 本月无标签，跳过');

  ws.close(); chrome.kill();
  console.log('结果：', failed === 0 ? '全部通过' : '失败 ' + failed);
  process.exit(failed ? 1 : 0);
}
main().catch(e => { console.error('ERR', e.message); chrome.kill(); process.exit(2); });
