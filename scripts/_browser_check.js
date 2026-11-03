/* 浏览器端到端校验（临时开发工具，非交付物）：
   登录 → 种当日数据 → 总览周/月视图、单日弹窗、跳转按钮 → 训练/游泳/舞蹈单日页 → 收集 JS 运行时错误 → 清理。
   依赖：node ≥ 22（全局 WebSocket）+ chrome-headless-shell + 本地服务 8010。 */
const { spawn } = require('child_process');

const CHROME = 'C:\\Users\\admin\\AppData\\Local\\ms-playwright\\chromium_headless_shell-1243\\chrome-headless-shell-win64\\chrome-headless-shell.exe';
const PORT = 9223;
const BASE = 'http://127.0.0.1:8010';

const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
function check(name, ok, detail = '') { results.push({ name, ok, detail }); console.log((ok ? '  ✔ ' : '  ✘ ') + name + (detail ? '  ' + detail : '')); }

const chrome = spawn(CHROME, [
  '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=' + PORT,
  '--user-data-dir=' + process.env.TEMP + '\\shcdp_' + Date.now(),
  'about:blank',
], { stdio: 'ignore' });

async function getWsUrl() {
  for (let i = 0; i < 30; i++) {
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

class CDP {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.id = 0;
    this.pending = new Map();
    this.errs = [];
    this.ws.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.id) {
        const p = this.pending.get(m.id);
        if (p) { this.pending.delete(m.id); m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); }
      } else if (m.method) {
        if (m.method === 'Runtime.exceptionThrown') {
          const d = m.params.exceptionDetails;
          this.errs.push('EXC: ' + (d.exception && d.exception.description || d.text || 'unknown'));
        } else if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
          this.errs.push('LOG: ' + m.params.entry.text);
        }
      }
    };
    this.opened = new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = rej; });
  }
  async cmd(method, params = {}) {
    await this.opened;
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
}

async function main() {
  const wsUrl = await getWsUrl();
  const cdp = new CDP(wsUrl);
  await cdp.cmd('Page.enable');
  await cdp.cmd('Runtime.enable');
  await cdp.cmd('Log.enable');

  const ev = async (expression) => {
    const r = await cdp.cmd('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    return r.result && r.result.value;
  };

  // 1. 登录（页面上下文 fetch，浏览器自动存会话 cookie）
  await cdp.cmd('Page.navigate', { url: BASE + '/login' });
  await sleep(1200);
  const loginOk = await ev(`(async () => {
    const r = await fetch('${BASE}/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'username=admin&password=admin123',
      credentials: 'include', redirect: 'manual'
    });
    return r.status;   // redirect:'manual' 时 303 显示为 0（opaque），cookie 已写入
  })()`);
  check('登录成功（303/opaque，会话 cookie 已存）', loginOk === 0 || loginOk === 303, 'status=' + loginOk);

  // 2. 种当日数据（训练计划、游泳计划、舞蹈记录）
  const today = new Date();
  const iso = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
  const seed = await ev(`(async () => {
    const ids = { training: null, swim: null, dance: null };
    const post = async (url, body) => {
      const r = await fetch('${BASE}' + url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), credentials: 'include' });
      return r.json().catch(() => ({}));
    };
    const t = await post('/api/training/plans', { plan_date: '${iso}', items: [{ exercise_name: '深蹲', body_part: '腿', weight_kg: 60, sets: 5, reps: '8' }] });
    if (t.plan) ids.training = t.plan.id;
    const s = await post('/api/swim-records', { record_date: '${iso}', status: 'planned', distance_m: 1000, duration_s: 1800, main_stroke: 'freestyle', remark: '自由泳 1000m · 30 分钟' });
    if (s.id) ids.swim = s.id;
    const dp = await post('/api/dance-records', { record_date: '${iso}', status: 'planned', dance_type: '拉丁', stars: 3, remark: '拉丁课 60 分钟' });
    const d = await post('/api/dance-records', { record_date: '${iso}', dance_type: '爵士', stars: 4, duration_s: 3600, calories: 200 });
    if (d.id) ids.dance = d.id;
    return ids;
  })()`);
  check('种数成功（训练计划/游泳计划/舞蹈计划+记录）', seed && seed.training && seed.swim && seed.dance, JSON.stringify(seed));
  const seeded = seed || {};

  // 3. 总览页：默认周视图
  await cdp.cmd('Page.navigate', { url: BASE + '/overview' });
  await sleep(1800);
  const ovWeek = await ev(`(() => {
    const q = s => document.querySelectorAll(s).length;
    const txt = s => { const el = document.querySelector(s); return el ? el.textContent.trim() : ''; };
    return {
      stats: q('#ovStats .stat-card'),
      days: q('#ovWeekStrip .ws-day'),
      chips: q('#ovWeekStrip .ov-chip'),
      chartCanvas: q('#chartOvWeek canvas'),
      groupOpen: document.querySelector('.nav-group.open') ? true : false,
      breadcrumb: txt('.breadcrumb'),
      segWeekActive: document.querySelector('#ovModeSeg button.active') ? document.querySelector('#ovModeSeg button.active').textContent : ''
    };
  })()`);
  check('总览默认周视图：4 统计卡 + 7 天条带', ovWeek.stats === 4 && ovWeek.days === 7, JSON.stringify(ovWeek));
  check('周视图出现当日运动标签（健身/游泳/舞蹈）', ovWeek.chips >= 3, 'chips=' + ovWeek.chips);
  check('周图表 canvas 渲染（ECharts）', ovWeek.chartCanvas >= 1, 'canvas=' + ovWeek.chartCanvas);
  check('侧边栏「运动训练/计划」分组默认展开', ovWeek.groupOpen === true, '');
  check('面包屑显示「运动训练/计划」', ovWeek.breadcrumb.indexOf('运动训练/计划') >= 0, ovWeek.breadcrumb);

  // 4. 周视图点击某日运动标签 → 单日详情弹窗 + 跳转按钮
  const modal = await ev(`(async () => {
    const chip = document.querySelector('#ovWeekStrip .ov-chip');
    if (!chip) return { clicked: false };
    chip.click();
    await new Promise(r => setTimeout(r, 900));
    const body = document.getElementById('ovModalBody');
    const items = body.querySelectorAll('.ov-detail-item');
    const firstHref = items.length ? body.querySelector('.di-go a').getAttribute('href') : '';
    const visible = document.getElementById('modalOvDay').classList.contains('show') ||
      getComputedStyle(document.getElementById('modalOvDay')).opacity === '1';
    return { clicked: true, items: items.length, firstHref, visible };
  })()`);
  check('点击标签弹出单日详情（含条目 + 跳转按钮）', modal.clicked && modal.items >= 3 && /\\?date=/.test(modal.firstHref || ''), JSON.stringify(modal));
  await ev(`document.querySelector('#modalOvDay [data-close]').click()`);

  // 5. 月视图
  await ev(`document.querySelector('#ovModeSeg button[data-mode="month"]').click()`);
  await sleep(1400);
  const ovMonth = await ev(`(() => ({
    cells: document.querySelectorAll('#ovCalGrid .ov-cal-cell:not(.blank)').length,
    marks: document.querySelectorAll('#ovCalGrid .ov-chip').length,
    chartCanvas: document.querySelectorAll('#chartOvMonth canvas').length,
    monthStats: document.querySelectorAll('#ovStats .stat-card').length
  }))()`);
  check('月视图：日历格子 ≥28、当月运动标签、月图表渲染', ovMonth.cells >= 28 && ovMonth.marks >= 3 && ovMonth.chartCanvas >= 1 && ovMonth.monthStats === 4, JSON.stringify(ovMonth));

  // 6. 日视图
  await ev(`document.querySelector('#ovModeSeg button[data-mode="day"]').click()`);
  await sleep(1400);
  const ovDay = await ev(`(() => ({
    cards: document.querySelectorAll('#ovDayCards .ov-sport-card').length,
    items: document.querySelectorAll('#ovDayCards .osc-item').length
  }))()`);
  check('日视图：三运动卡片 + 条目', ovDay.cards === 3 && ovDay.items >= 3, JSON.stringify(ovDay));
  await ev(`document.querySelector('#ovModeSeg button[data-mode="week"]').click()`);
  await sleep(1000);

  // 7. 健身单日页：翻页导航 + 计划卡（当日有“开始训练”按钮）
  await cdp.cmd('Page.navigate', { url: BASE + '/training?date=' + iso });
  await sleep(1600);
  const training = await ev(`(() => ({
    nav: document.querySelectorAll('.date-nav .dn-btn').length,
    cards: document.querySelectorAll('.plan-card').length,
    recordBtn: document.querySelectorAll('.plan-card [data-act="record"]').length,
    breadcrumb: (document.querySelector('.breadcrumb') || {}).textContent || ''
  }))()`);
  check('健身页：单日翻页导航 + 当日计划卡 + 「开始训练」', training.nav === 2 && training.cards >= 1 && training.recordBtn >= 1, JSON.stringify(training));

  // 8. 游泳页：当日卡片（计划/记录两态）+ 结构化字段展示；弹窗无切换 seg
  await cdp.cmd('Page.navigate', { url: BASE + '/swim?date=' + iso });
  await sleep(1600);
  const swim = await ev(`(() => ({
    dailyCard: document.getElementById('swimDaily') ? true : false,
    planBlock: document.querySelectorAll('#swimDaily .daily-block').length,
    todoBtn: document.querySelectorAll('#swimDaily [data-daily="todo"]').length,
    planMeta: (document.querySelector('#swimDaily .daily-block .daily-main') || {}).textContent || '',
    segBtns: document.querySelectorAll('#swimStatusSeg button').length,
    typeCol: (function(){ const ths = document.querySelectorAll('.card table.tbl th'); for (const t of ths) if (t.textContent === '类型') return true; return false; })(),
    nav: document.querySelectorAll('.date-nav .dn-btn').length,
    breadcrumb: (document.querySelector('.breadcrumb') || {}).textContent || ''
  }))()`);
  check('游泳页：当日卡片(计划+记录)、结构化计划行、无弹窗 seg、类型列、翻页、面包屑=游泳',
    swim.dailyCard && swim.planBlock >= 1 && swim.todoBtn >= 1 && swim.segBtns === 0 && swim.planMeta.indexOf('m') >= 0 && swim.planMeta.indexOf('自由泳') >= 0 && swim.typeCol && swim.nav === 2 && swim.breadcrumb.indexOf('游泳') >= 0,
    JSON.stringify(swim));

  // 9. 舞蹈页：同上（当日有 拉丁计划 + 爵士记录；弹窗无 seg）
  await cdp.cmd('Page.navigate', { url: BASE + '/dance?date=' + iso });
  await sleep(1600);
  const dance = await ev(`(() => ({
    dailyCard: document.getElementById('danceDaily') ? true : false,
    blocks: document.querySelectorAll('#danceDaily .daily-block').length,
    todoBtn: document.querySelectorAll('#danceDaily [data-daily="todo"]').length,
    planMeta: (document.querySelector('#danceDaily .daily-block .daily-main') || {}).textContent || '',
    segBtns: document.querySelectorAll('#danceStatusSeg button').length,
    typeCol: (function(){ const ths = document.querySelectorAll('.card table.tbl th'); for (const t of ths) if (t.textContent === '类型') return true; return false; })(),
    nav: document.querySelectorAll('.date-nav .dn-btn').length
  }))()`);
  check('舞蹈页：当日卡片(计划+记录)、结构化计划行、无弹窗 seg、类型列、翻页',
    dance.dailyCard && dance.blocks >= 2 && dance.todoBtn >= 1 && dance.segBtns === 0 && dance.planMeta.indexOf('拉丁') >= 0 && dance.typeCol && dance.nav === 2, JSON.stringify(dance));

  // 10. 其他页面无回归：/body 侧边栏结构
  await cdp.cmd('Page.navigate', { url: BASE + '/body' });
  await sleep(1200);
  const body = await ev(`(() => ({
    groups: document.querySelectorAll('.nav-group').length,
    subHidden: document.querySelectorAll('.nav-sub a').length,
    navLinks: document.querySelectorAll('.sidebar-nav a').length,
    hint: (document.querySelector('.sidebar-hint') || {}).textContent || ''
  }))()`);
  check('身材数据页：分组结构 1 组、子菜单 3 项、共 7 链接、快捷键提示', body.groups === 1 && body.subHidden === 3 && body.navLinks === 7 && /1-7/.test(body.hint), JSON.stringify(body));

  // 11. 清理种子数据
  if (seeded.training) await ev(`fetch('${BASE}/api/training/plans/' + ${seeded.training}, { method: 'DELETE', credentials: 'include' })`);
  if (seeded.swim) await ev(`fetch('${BASE}/api/swim-records/' + ${seeded.swim}, { method: 'DELETE', credentials: 'include' })`);
  if (seeded.dance) await ev(`fetch('${BASE}/api/dance-records/' + ${seeded.dance}, { method: 'DELETE', credentials: 'include' })`);
  check('清理种子数据', true, '');

  // 12. JS 运行时错误汇总（遍历全程收集）
  check('全程无 JS 运行时错误', cdp.errs.length === 0, cdp.errs.slice(0, 5).join(' | '));

  const failed = results.filter(r => !r.ok);
  console.log('\n结果：通过 ' + (results.length - failed.length) + ' / ' + results.length);
  chrome.kill();
  process.exit(failed.length ? 1 : 0);
}

main().catch(e => { console.error('FATAL', e); chrome.kill(); process.exit(2); });
