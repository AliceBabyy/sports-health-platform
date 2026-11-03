// 临时视觉自检：健身页「完成训练」按钮 + 翻页 + 二次确认弹窗形态（2026-11-03）
const { spawn } = require('child_process');
const CHROME = 'C:\\Users\\admin\\AppData\\Local\\ms-playwright\\chromium_headless_shell-1243\\chrome-headless-shell-win64\\chrome-headless-shell.exe';
const PORT = 9225;
const BASE = 'http://127.0.0.1:8010';
const fs = require('fs');

const sleep = ms => new Promise(r => setTimeout(r, ms));

const chrome = spawn(CHROME, [
  '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=' + PORT,
  '--window-size=1440,1100',
  'about:blank'
], { stdio: 'ignore' });

async function getWsUrl() {
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch('http://127.0.0.1:' + PORT + '/json/list');
      const list = await r.json();
      const page = list.find(t => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch (e) { /* retry */ }
    await sleep(300);
  }
  throw new Error('CDP endpoint not ready');
}

async function main() {
  const ws = new WebSocket(await getWsUrl());
  const opened = new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  await opened;
  let seq = 0; const pending = new Map();
  ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
  const cmd = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pending.set(id, m => m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result)); ws.send(JSON.stringify({ id, method, params })); });
  const ev = async (expression) => {
    const r = await cmd('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    return r.result && r.result.value;
  };

  await cmd('Page.enable');
  await cmd('Runtime.enable');

  await cmd('Page.navigate', { url: BASE + '/login' });
  await sleep(1800);
  await ev(`(async () => { const r = await fetch('${BASE}/login', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'username=admin&password=admin123', credentials: 'include', redirect: 'manual' }); return r.status; })()`);
  await sleep(600);

  async function shot(name) {
    const r = await cmd('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(__dirname + '\\_shots\\' + name, Buffer.from(r.data, 'base64'));
    console.log('saved ' + name);
  }

  // 种当日训练计划（含备注）
  const iso = new Date().toISOString().slice(0, 10);
  const seed = await ev(`(async () => {
    const r = await fetch('${BASE}/api/training/plans', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ plan_date: '${iso}', items: [{ exercise_name: '杠铃深蹲', body_part: '腿', weight_kg: 80, sets: 5, reps: '10+8+6', target_weight_kg: 85, checked: false }], remark: '截图自检种子' }) });
    const j = await r.json();
    return { status: r.status, id: (j.plan || {}).id };
  })()`);
  console.log('seed', JSON.stringify(seed));

  // 1. 当日：计划卡 + 「完成训练」按钮
  await cmd('Page.navigate', { url: BASE + '/training?date=' + iso });
  await sleep(1800);
  await shot('training_complete_btn_20261103.png');

  // 2. 翻页到前一天：非当日形态（无完成按钮）
  await ev(`document.querySelector('.date-nav .dn-btn').click()`);
  await sleep(1200);
  await shot('training_prevday_20261103.png');

  // 3. 回当日 → 点「完成训练」→ 二次确认弹窗
  await cmd('Page.navigate', { url: BASE + '/training?date=' + iso });
  await sleep(1600);
  await ev(`document.querySelector('.plan-card [data-act="complete"]').click()`);
  await sleep(800);
  await shot('training_complete_modal_20261103.png');

  // 关闭弹窗（不真正提交），清理种子
  await ev(`document.querySelector('#modalComplete [data-close]').click()`);
  await sleep(400);
  const del = await ev(`(async () => { const r = await fetch('${BASE}/api/training/plans/${seed.id}', { method: 'DELETE', credentials: 'include' }); return r.status; })()`);
  console.log('cleanup delete', del);

  ws.close();
}
main().then(() => { chrome.kill(); process.exit(0); }).catch(e => { console.error('ERR', e.message); chrome.kill(); process.exit(1); });
