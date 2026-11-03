// 临时校验：表单弹窗点击遮罩不关闭、内容不丢；信息弹窗遮罩仍可关闭。
const { spawn } = require('child_process');
const CHROME = 'C:\\Users\\admin\\AppData\\Local\\ms-playwright\\chromium_headless_shell-1243\\chrome-headless-shell-win64\\chrome-headless-shell.exe';
const PORT = 9225;
const BASE = 'http://127.0.0.1:8010';
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
  await ev(`(async () => { const r = await fetch('${BASE}/login', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'username=admin&password=admin123', credentials: 'include', redirect: 'manual' }); return r.status; })()`);
  await sleep(500);

  const today = new Date();
  const iso = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
  let failed = 0;
  const check = (name, ok, detail = '') => { console.log((ok ? '  ✔ ' : '  ✘ ') + name + (detail ? '  ' + detail : '')); if (!ok) failed++; };

  // 1. 训练计划弹窗：填备注 → 点遮罩 → 弹窗应仍在、内容应保留
  await cmd('Page.navigate', { url: BASE + '/training?date=' + iso });
  await sleep(1500);
  await ev(`document.getElementById('btnNewPlan').click()`);
  await sleep(600);
  await ev(`document.querySelector('#formPlan [name="remark"]').value = '临时测试备注不要丢'; document.querySelector('#formPlan [name="remark"]').dispatchEvent(new Event('input', {bubbles:true}));`);
  // 点击遮罩空白处（modal-mask 自身，避开 .modal）
  await ev(`document.getElementById('modalPlan').click()`);
  await sleep(300);
  const r1 = await ev(`(() => {
    const m = document.getElementById('modalPlan');
    return { open: m.classList.contains('open'), remark: (document.querySelector('#formPlan [name="remark"]') || {}).value || '' };
  })()`);
  check('训练计划弹窗：点遮罩不关闭', r1.open === true, JSON.stringify(r1));
  check('训练计划弹窗：已填内容保留', r1.remark === '临时测试备注不要丢', 'remark=' + r1.remark);
  // 取消按钮仍可关闭
  await ev(`document.querySelector('#modalPlan [data-close]').click()`);
  await sleep(300);
  const r1b = await ev(`document.getElementById('modalPlan').classList.contains('open')`);
  check('训练计划弹窗：取消按钮可正常关闭', r1b === false);

  // 2. 游泳计划弹窗：同样验证
  await cmd('Page.navigate', { url: BASE + '/swim?date=' + iso });
  await sleep(1500);
  await ev(`document.getElementById('btnAddSwimPlan').click()`);
  await sleep(600);
  await ev(`document.querySelector('#formSwim [name="remark"]').value = '游泳备注保留';`);
  await ev(`document.getElementById('modalSwim').click()`);
  await sleep(300);
  const r2 = await ev(`(() => ({ open: document.getElementById('modalSwim').classList.contains('open'), remark: (document.querySelector('#formSwim [name="remark"]')||{}).value || '' }))()`);
  check('游泳计划弹窗：点遮罩不关闭且内容保留', r2.open === true && r2.remark === '游泳备注保留', JSON.stringify(r2));
  await ev(`document.querySelector('#modalSwim [data-close]').click()`);

  // 3. 信息弹窗（总览单日详情）：点遮罩仍可关闭
  await cmd('Page.navigate', { url: BASE + '/overview' });
  await sleep(1800);
  const hasChip = await ev(`!!document.querySelector('#ovWeekStrip .ov-chip')`);
  if (hasChip) {
    await ev(`document.querySelector('#ovWeekStrip .ov-chip').click()`);
    await sleep(800);
    const before = await ev(`document.getElementById('modalOvDay').classList.contains('open')`);
    await ev(`document.getElementById('modalOvDay').click()`);
    await sleep(300);
    const after = await ev(`document.getElementById('modalOvDay').classList.contains('open')`);
    check('总览单日详情弹窗：点遮罩仍可关闭', before === true && after === false, 'before=' + before + ' after=' + after);
  } else {
    console.log('  · 总览当日无标签，跳过信息弹窗遮罩关闭校验');
  }

  ws.close();
  chrome.kill();
  console.log('结果：', failed === 0 ? '全部通过' : `失败 ${failed}`);
  process.exit(failed ? 1 : 0);
}
main().catch(e => { console.error('ERR', e.message); chrome.kill(); process.exit(2); });
