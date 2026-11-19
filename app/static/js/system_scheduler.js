/* 定时任务管理页（2026-11-17）：任务卡渲染、新建/编辑、立即执行、启停、删除、执行历史 */
(function () {
  const API = '/api/system/scheduler';
  const boot = window.SCHEDULER_BOOT || {
    jobs: [], catalog: [], runs: [], graceDefault: 300, timezone: 'Asia/Shanghai',
  };
  const PAGE_SIZE = 20;
  const esc = (v) => App.escapeHtml(v == null ? '' : String(v));

  const jobListEl = document.getElementById('jobList');
  const jobEmptyEl = document.getElementById('jobEmpty');
  const runBodyEl = document.getElementById('runBody');
  const runFootEl = document.getElementById('runFoot');

  let jobs = boot.jobs || [];
  let editingId = null;
  let runPage = 1;

  /* ---------- 任务列表 ---------- */

  function cardHtml(job) {
    const statusCls = job.last_status || 'none';
    const nextRun = job.next_run_at ? job.next_run_at : '—';
    const lastRun = job.last_run_at ? job.last_run_at : '—';
    return (
      '<article class="sch-card ' + (job.enabled ? '' : 'is-off') + '">' +
        '<div class="sch-card-head">' +
          '<div class="sch-name-wrap">' +
            '<span class="sch-name">' + esc(job.name) + '</span>' +
            '<code class="sch-key">' + esc(job.job_key) + '</code>' +
          '</div>' +
          '<div class="sch-badges">' +
            '<span class="sch-badge ' + (job.enabled ? 'on' : 'off') + '">' +
              (job.enabled ? '已启用' : '已停用') + '</span>' +
            '<span class="sch-badge ' + esc(statusCls) + '">上次 ' +
              esc(job.last_status_label) + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="sch-grid">' +
          '<div class="sch-cell">' +
            '<span class="sch-label">触发</span>' +
            '<span class="sch-value">' + esc(job.trigger_display) + '</span>' +
            '<code class="sch-expr" title="' + esc(job.trigger_type + ' ' + job.trigger_expr) + '">' +
              esc(job.trigger_type + ' · ' + job.trigger_expr) + '</code>' +
          '</div>' +
          '<div class="sch-cell">' +
            '<span class="sch-label">下次执行（' + esc(job.timezone) + '）</span>' +
            '<span class="sch-value">' + esc(nextRun) + '</span>' +
          '</div>' +
          '<div class="sch-cell">' +
            '<span class="sch-label">上次执行</span>' +
            '<span class="sch-value">' + esc(lastRun) + '</span>' +
            '<span class="sch-note">' + esc(job.last_message || '') + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="sch-card-foot">' +
          '<span class="sch-desc">' + esc(job.job_desc) + '</span>' +
          '<div class="sch-actions">' +
            '<button class="btn" type="button" data-act="run" data-id="' + job.id + '">立即执行</button>' +
            '<button class="btn" type="button" data-act="edit" data-id="' + job.id + '">编辑</button>' +
            '<button class="btn" type="button" data-act="toggle" data-id="' + job.id + '">' +
              (job.enabled ? '停用' : '启用') + '</button>' +
            '<button class="btn btn-danger" type="button" data-act="del" data-id="' + job.id + '">删除</button>' +
          '</div>' +
        '</div>' +
      '</article>'
    );
  }

  function renderJobs() {
    jobListEl.innerHTML = jobs.map(cardHtml).join('');
    jobEmptyEl.hidden = jobs.length > 0;
  }

  function loadJobs() {
    return App.api(API + '/jobs')
      .then((data) => { jobs = data.list || []; renderJobs(); })
      .catch((err) => App.toast(err.message, true));
  }

  jobListEl.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const job = jobs.find((item) => item.id === id);
    if (!job) return;
    if (btn.dataset.act === 'run') runNow(job, btn);
    else if (btn.dataset.act === 'edit') openEditor(job);
    else if (btn.dataset.act === 'toggle') toggleJob(job);
    else if (btn.dataset.act === 'del') removeJob(job);
  });

  function runNow(job, btn) {
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = '执行中…';
    App.api(API + '/jobs/' + job.id + '/run', { method: 'POST' })
      .then((result) => {
        App.toast('执行完成：' + result.message);
        return Promise.all([loadJobs(), loadRuns(runPage)]);
      })
      .catch((err) => {
        App.toast(err.message, true);
        btn.disabled = false;
        btn.textContent = original;
      });
  }

  function toggleJob(job) {
    App.api(API + '/jobs/' + job.id, { method: 'PATCH', body: { enabled: !job.enabled } })
      .then((row) => {
        App.toast(row.enabled ? '已启用' : '已停用');
        return loadJobs();
      })
      .catch((err) => App.toast(err.message, true));
  }

  function removeJob(job) {
    App.confirmDialog({ title: '删除任务', message: '删除「' + job.name + '」及其执行记录？' })
      .then((ok) => {
        if (!ok) return;
        App.api(API + '/jobs/' + job.id, { method: 'DELETE' })
          .then(() => { App.toast('已删除'); return Promise.all([loadJobs(), loadRuns(1)]); })
          .catch((err) => App.toast(err.message, true));
      });
  }

  /* ---------- 新建 / 编辑 ---------- */

  const modal = document.getElementById('modalJob');
  const form = document.getElementById('jobForm');
  const fJobKey = document.getElementById('fJobKey');
  const fTriggerType = document.getElementById('fTriggerType');
  const fTriggerExpr = document.getElementById('fTriggerExpr');
  const fTimezone = document.getElementById('fTimezone');
  const fName = document.getElementById('fName');
  const fGrace = document.getElementById('fGrace');
  const fEnabled = document.getElementById('fEnabled');
  const triggerHint = document.getElementById('triggerHint');
  const formMsg = document.getElementById('jobFormMsg');
  const modalTitle = document.getElementById('modalJobTitle');

  const HINTS = {
    cron: '五段式「分 时 日 月 星期」，如 0 8 * * mon = 每周一 08:00；星期只写 mon~sun，不写数字。',
    date: '一次性执行，如 2026-11-20 15:40；必须是未来的时间。',
    interval: '固定间隔，如 10m、2h、1d；最小 60 秒。',
  };

  function syncHint() {
    triggerHint.textContent = HINTS[fTriggerType.value] || '';
  }

  fTriggerType.addEventListener('change', syncHint);

  fJobKey.addEventListener('change', () => {
    if (editingId) return;
    const option = fJobKey.selectedOptions[0];
    if (!option) return;
    fTriggerType.value = option.dataset.tt || 'cron';
    fTriggerExpr.value = option.dataset.texpr || '';
    fName.value = '';
    syncHint();
  });

  function openEditor(job) {
    editingId = job ? job.id : null;
    modalTitle.textContent = job ? '编辑定时任务' : '新建定时任务';
    formMsg.textContent = '';
    fJobKey.disabled = !!job;
    if (job) {
      fJobKey.value = job.job_key;
      fTriggerType.value = job.trigger_type;
      fTriggerExpr.value = job.trigger_expr;
      fTimezone.value = job.timezone;
      fName.value = job.name;
      fGrace.value = job.misfire_grace_seconds == null ? '' : job.misfire_grace_seconds;
      fEnabled.checked = !!job.enabled;
    } else {
      const option = fJobKey.selectedOptions[0];
      fTriggerType.value = (option && option.dataset.tt) || 'cron';
      fTriggerExpr.value = (option && option.dataset.texpr) || '';
      fTimezone.value = boot.timezone || 'Asia/Shanghai';
      fName.value = '';
      fGrace.value = '';
      fEnabled.checked = true;
    }
    syncHint();
    App.openModal('modalJob');
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    formMsg.textContent = '';
    const body = {
      trigger_type: fTriggerType.value,
      trigger_expr: fTriggerExpr.value.trim(),
      timezone: fTimezone.value.trim() || boot.timezone,
      name: fName.value.trim() || null,
      enabled: fEnabled.checked,
      misfire_grace_seconds: fGrace.value === '' ? null : Number(fGrace.value),
    };
    const request = editingId
      ? App.api(API + '/jobs/' + editingId, { method: 'PATCH', body })
      : App.api(API + '/jobs', { method: 'POST', body: Object.assign({ job_key: fJobKey.value }, body) });
    request
      .then(() => {
        App.closeModal('modalJob');
        App.toast(editingId ? '已保存' : '已创建');
        return loadJobs();
      })
      .catch((err) => { formMsg.textContent = err.message; });
  });

  /* ---------- 执行历史 ---------- */

  function runRow(run) {
    return (
      '<tr>' +
        '<td class="num">' + esc(run.started_at || '—') + '</td>' +
        '<td>' + esc(run.job_name) + '</td>' +
        '<td>' + esc(run.source_label) + '</td>' +
        '<td><span class="sch-run-status ' + esc(run.status) + '">' + esc(run.status_label) + '</span></td>' +
        '<td class="num">' + (run.duration_ms || 0) + ' ms</td>' +
        '<td class="msg">' + esc(run.message || '') + '</td>' +
      '</tr>'
    );
  }

  function renderRuns(data) {
    const rows = (data.list || []).map(runRow).join('');
    runBodyEl.innerHTML = rows ||
      '<tr><td colspan="6" class="msg">暂无执行记录</td></tr>';
    const pages = Math.max(Number(data.pages) || 1, 1);
    runFootEl.innerHTML =
      '<span>共 ' + (data.total || 0) + ' 条 · 第 ' + (data.page || 1) + ' / ' + pages + ' 页</span>' +
      '<button class="btn btn-ghost btn-sm" type="button" data-page="' + ((data.page || 1) - 1) + '"' +
        ((data.page || 1) <= 1 ? ' disabled' : '') + '>上一页</button>' +
      '<button class="btn btn-ghost btn-sm" type="button" data-page="' + ((data.page || 1) + 1) + '"' +
        ((data.page || 1) >= pages ? ' disabled' : '') + '>下一页</button>';
  }

  function loadRuns(page) {
    runPage = page || 1;
    return App.api(API + '/runs?page=' + runPage + '&page_size=' + PAGE_SIZE)
      .then(renderRuns)
      .catch((err) => App.toast(err.message, true));
  }

  runFootEl.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-page]');
    if (!btn || btn.disabled) return;
    loadRuns(Number(btn.dataset.page));
  });

  /* ---------- 初始化 ---------- */

  document.getElementById('btnNewJob').addEventListener('click', () => openEditor(null));
  document.getElementById('btnReloadRuns').addEventListener('click', () => loadRuns(runPage));

  document.querySelectorAll('[data-close]').forEach((btn) => {
    btn.addEventListener('click', () => App.closeModal(btn.dataset.close));
  });
  modal.addEventListener('click', (e) => { if (e.target === modal) App.closeModal('modalJob'); });

  renderJobs();
  renderRuns({ list: boot.runs || [], total: (boot.runs || []).length, page: 1, pages: 1 });
  loadRuns(1);
})();
