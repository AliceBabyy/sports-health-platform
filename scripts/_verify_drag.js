// 临时验证：训练计划编辑弹窗动作行拖拽排序（原生 DnD 合成事件 → DOM 顺序 → 保存落库顺序）
const { spawn } = require('child_process');
const CHROME = 'C:\\Users\\admin\\AppData\\Local\\ms-playwright\\chromium_headless_shell-1243\\chrome-headless-shell-win64\\chrome-headless-shell.exe';
const PORT = 9226;
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

  // 种当日训练计划：3 个动作
  const iso = new Date().toISOString().slice(0, 10);
  const seed = await ev(`(async () => {
    const r = await fetch('${BASE}/api/training/plans', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ plan_date: '${iso}', items: [
      { exercise_name: '杠铃深蹲', body_part: '腿', weight_kg: 80, sets: 5, reps: '10+8+6', target_weight_kg: 85, checked: false },
      { exercise_name: '杠铃卧推', body_part: '胸', weight_kg: 60, sets: 4, reps: '8+8', target_weight_kg: 65, checked: false },
      { exercise_name: '硬拉', body_part: '臀腿', weight_kg: 100, sets: 3, reps: '5', target_weight_kg: 110, checked: false }
    ], remark: '拖拽验证种子' }) });
    const j = await r.json();
    return { status: r.status, id: (j.plan || {}).id };
  })()`);
  console.log('seed', JSON.stringify(seed));
  if (seed.status !== 200) throw new Error('seed failed');

  // 打开编辑弹窗（按 data-pid 定位种子计划卡，避免点到其他计划）
  await cmd('Page.navigate', { url: BASE + '/training?date=' + iso });
  await sleep(1600);
  const modalOpened = await ev(`(async () => {
    const card = document.querySelector('.plan-card[data-pid="${seed.id}"]');
    if (!card) return false;
    card.querySelector('[data-act="edit"]').click();
    await new Promise(r => setTimeout(r, 700));
    return document.getElementById('modalPlan').classList.contains('open');
  })()`);
  console.log('modal opened', modalOpened);
  if (!modalOpened) throw new Error('edit modal not opened for seed plan ' + seed.id);

  // 1. 手柄存在 + 初始顺序
  const before = await ev(`(() => ({
    handles: document.querySelectorAll('#planRows .drag-handle').length,
    order: [...document.querySelectorAll('#planRows .plan-form-item input[name="exercise_name"]')].map(i => i.value)
  }))()`);
  console.log('before', JSON.stringify(before));
  if (before.handles !== 3) throw new Error('handles expected 3, got ' + before.handles);
  await shot('training_drag_before_20261103.png');

  // 2. 合成 DnD：把第 1 行（深蹲）拖到第 3 行（硬拉）之后 → 期望 [卧推, 硬拉, 深蹲]
  const after = await ev(`(() => {
    const rows = [...document.querySelectorAll('#planRows .plan-form-item')];
    const dt = new DataTransfer();
    const h = rows[0].querySelector('.drag-handle');
    h.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
    const target = rows[2];
    const rect = target.getBoundingClientRect();
    target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt, clientY: rect.top + rect.height - 2 }));
    target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
    h.dispatchEvent(new DragEvent('dragend', { bubbles: true, cancelable: true, dataTransfer: dt }));
    return {
      order: [...document.querySelectorAll('#planRows .plan-form-item input[name="exercise_name"]')].map(i => i.value),
      draggingCleared: document.querySelectorAll('#planRows .dragging').length === 0
    };
  })()`);
  console.log('after drag', JSON.stringify(after));
  const expected = ['杠铃卧推', '硬拉', '杠铃深蹲'];
  if (JSON.stringify(after.order) !== JSON.stringify(expected)) throw new Error('drag reorder failed: ' + JSON.stringify(after.order));
  await shot('training_drag_after_20261103.png');

  // 3. 提交保存 → 等页面自行 reload（与用户真实操作一致，不额外 navigate 避免命中浏览器缓存） → GET 验证落库顺序
  await ev(`document.getElementById('formPlan').requestSubmit()`);
  await sleep(2600);
  const saved = await ev(`(async () => {
    const r = await fetch('${BASE}/api/training/plans?plan_date=${iso}&_t=' + Date.now(), { credentials: 'include' });
    const j = await r.json();
    const list = j.list || j.plans || [];
    const p = list.find(x => x.id === ${seed.id});
    return { keys: Object.keys(j), found: !!p, order: p ? (p.items || []).map(i => i.exercise_name) : null, listLen: list.length };
  })()`);
  console.log('saved diag', JSON.stringify(saved));
  if (!saved.found) throw new Error('seed plan not found after save: ' + JSON.stringify(saved));
  if (JSON.stringify(saved.order) !== JSON.stringify(expected)) throw new Error('saved order mismatch: ' + JSON.stringify(saved.order));
  // 4. 当前页面即保存后 reload 的结果：截图核对卡片渲染顺序（页面渲染 items 应同序）
  const pageOrder = await ev(`(() => {
    const card = document.querySelector('.plan-card[data-pid="${seed.id}"]');
    if (!card) return null;
    return [...card.querySelectorAll('tbody tr')].map(r => (r.querySelector('td:nth-child(2)') || {}).textContent || '');
  })()`);
  console.log('page order', JSON.stringify(pageOrder));
  if (JSON.stringify(pageOrder) !== JSON.stringify(expected)) throw new Error('page render order mismatch: ' + JSON.stringify(pageOrder));
  await shot('training_drag_saved_20261103.png');

  // 清理种子
  const del = await ev(`(async () => { const r = await fetch('${BASE}/api/training/plans/${seed.id}', { method: 'DELETE', credentials: 'include' }); return r.status; })()`);
  console.log('cleanup', del);
  ws.close();
}
main().then(() => { chrome.kill(); process.exit(0); }).catch(e => { console.error('ERR', e.message); chrome.kill(); process.exit(1); });
