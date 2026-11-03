// 临时视觉自检：总览 日/周/月 三视图卡片重排形态核对
const { spawn } = require('child_process');
const CHROME = 'C:\\Users\\admin\\AppData\\Local\\ms-playwright\\chromium_headless_shell-1243\\chrome-headless-shell-win64\\chrome-headless-shell.exe';
const PORT = 9224;
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

  await cmd('Page.navigate', { url: BASE + '/overview' });
  await sleep(2000);
  await shot('overview_week_20261103.png');

  await ev(`document.querySelector('#ovModeSeg button[data-mode="day"]').click()`);
  await sleep(1400);
  await shot('overview_day_20261103.png');

  await ev(`document.querySelector('#ovModeSeg button[data-mode="month"]').click()`);
  await sleep(1400);
  await ev(`document.getElementById('ovMonthSummary').scrollIntoView({block: 'start'})`);
  await sleep(900);
  await shot('overview_month_chart_20261103.png');

  ws.close();
}
main().then(() => { chrome.kill(); process.exit(0); }).catch(e => { console.error('ERR', e.message); chrome.kill(); process.exit(1); });
