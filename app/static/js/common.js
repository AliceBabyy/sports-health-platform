/* 通用工具：fetch 封装、弹窗、分钟/秒换算、日期格式化、toast（FE 基础件） */
(function () {
  const App = {
    api: async function (path, opts = {}) {
      const options = { headers: { 'Content-Type': 'application/json' }, ...opts };
      if (options.body && typeof options.body === 'object') options.body = JSON.stringify(options.body);
      const res = await fetch(path, options);
      if (res.status === 401) { location.href = '/login'; throw new Error('未登录'); }
      let data = null;
      try { data = await res.json(); } catch (e) { /* 非 JSON 响应 */ }
      if (!res.ok) {
        const msg = (data && data.error) ? data.error : ('请求失败（' + res.status + '）');
        const err = new Error(msg); err.status = res.status; throw err;
      }
      return data;
    },

    toast: function (msg, isError = false) {
      const wrap = document.getElementById('toastWrap') || (() => {
        const w = document.createElement('div'); w.id = 'toastWrap'; w.className = 'toast-wrap';
        document.body.appendChild(w); return w;
      })();
      const el = document.createElement('div');
      el.className = 'toast' + (isError ? ' error' : '');
      el.textContent = msg;
      wrap.appendChild(el);
      requestAnimationFrame(() => el.classList.add('show'));
      setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 220); }, 2600);
    },

    openModal(id) { const m = document.getElementById(id); if (m) m.classList.add('open'); },
    closeModal(id) { const m = document.getElementById(id); if (m) m.classList.remove('open'); },

    /* 时长：秒 → 展示文本 */
    fmtClock(s) {
      if (s == null) return '—';
      const m = Math.floor(s / 60), ss = s % 60;
      return m + 'm ' + String(ss).padStart(2, '0') + 's';
    },
    fmtMin(s) { return s == null ? '—' : Math.round(s / 60) + '分钟'; },
    /* 配速 min/100m → "2'12\"/100m" */
    fmtPace(pace) {
      if (pace == null) return '—';
      const total = Math.round(pace * 60);
      const m = Math.floor(total / 60), ss = total % 60;
      return m + "'" + String(ss).padStart(2, '0') + '"/100m';
    },
    fmtDuration(s) {
      if (s == null) return '—';
      const h = Math.floor(s / 3600);
      if (h > 0) return h + ' 小时';
      return Math.round(s / 60) + ' 分钟';
    },
    todayStr() {
      const d = new Date();
      return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    },
    fmtDate(s) { return s ? s.slice(0, 10) : '—'; },
    escapeHtml(s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    },
    confirm(msg) { return window.confirm(msg); },

    /* 统一二次确认弹窗（删除等危险操作）→ Promise<boolean>（确认 true / 取消或遮罩点击 false） */
    confirmDialog(opts = {}) {
      const o = {
        title: opts.title || '确认操作',
        message: opts.message || '',
        confirmText: opts.confirmText || '确认',
        cancelText: opts.cancelText || '取消',
        danger: opts.danger !== false,
      };
      return new Promise(function (resolve) {
        let mask = document.getElementById('confirmMask');
        const finish = function (ok) {
          const r = mask._resolve;
          mask._resolve = null;
          mask.classList.remove('open');
          if (r) r(ok);
        };
        if (!mask) {
          mask = document.createElement('div');
          mask.id = 'confirmMask';
          mask.className = 'modal-mask confirm-mask';
          mask.innerHTML =
            '<div class="modal confirm-modal">' +
            '<div class="modal-title confirm-title"></div>' +
            '<div class="modal-desc confirm-msg"></div>' +
            '<div class="modal-actions">' +
            '<button type="button" class="btn confirm-cancel"></button>' +
            '<button type="button" class="btn confirm-ok"></button>' +
            '</div></div>';
          document.body.appendChild(mask);
          mask.addEventListener('click', function (e) {
            if (e.target === mask) { finish(false); return; }
            const b = e.target.closest('button');
            if (!b) return;
            if (b.classList.contains('confirm-ok')) finish(true);
            else if (b.classList.contains('confirm-cancel')) finish(false);
          });
        }
        mask.querySelector('.confirm-title').textContent = o.title;
        mask.querySelector('.confirm-msg').textContent = o.message;
        const ok = mask.querySelector('.confirm-ok');
        ok.textContent = o.confirmText;
        ok.className = 'btn confirm-ok' + (o.danger ? ' danger' : '');
        mask.querySelector('.confirm-cancel').textContent = o.cancelText;
        mask._resolve = resolve;
        mask.classList.add('open');
      });
    },
  };
  window.App = App;
  document.addEventListener('click', function (e) {
    const mask = e.target.closest('.modal-mask');
    if (!mask || e.target !== mask) return;
    // 含表单的弹窗：点击遮罩不关闭——避免误触空白处丢失已填内容（只能由取消/保存按钮关闭）；
    // 纯展示类弹窗（无表单，如总览单日详情、庆祝弹窗）保持遮罩点击即关闭。
    if (mask.querySelector('.modal form, .modal textarea, .modal input, .modal select')) return;
    mask.classList.remove('open');
  });

  /* ---------- 侧边栏收起/展开（顶栏按钮 + 窄屏自动收起 + localStorage 记忆） ---------- */
  (function sidebar() {
    const shell = document.querySelector('.app-shell');
    if (!shell) return;
    const KEY = 'sh.sidebar.collapsed';
    const btn = document.getElementById('sidebarToggle');

    function apply() {
      const saved = localStorage.getItem(KEY);
      let collapsed;
      if (window.innerWidth <= 768) collapsed = true;                    // 窄屏强制收起
      else if (window.innerWidth <= 1100 && saved === null) collapsed = true; // 中屏默认收起
      else collapsed = saved === '1';
      shell.classList.toggle('sidebar-collapsed', collapsed);
      if (btn) btn.classList.toggle('collapsed', collapsed);
    }

    if (btn) {
      btn.addEventListener('click', () => {
        const now = shell.classList.contains('sidebar-collapsed');
        localStorage.setItem(KEY, now ? '0' : '1'); // 当前收起→展开；当前展开→收起
        apply();
      });
    }
    apply();
    let timer;
    window.addEventListener('resize', () => { clearTimeout(timer); timer = setTimeout(apply, 120); });
  })();

  /* ---------- 侧边栏分组展开/收起（chevron，点击不跳转） ---------- */
  (function navGroup() {
    const nav = document.getElementById('sidebarNav');
    if (!nav) return;
    nav.addEventListener('click', function (e) {
      const chev = e.target.closest('[data-toggle-group]');
      if (!chev) return;
      e.preventDefault();
      const g = chev.closest('.nav-group');
      if (g) g.classList.toggle('open');
    });
  })();

  /* ---------- 数字键 1-7 切换模块（对应侧栏链接顺序） ---------- */
  (function shortcuts() {
    const links = document.querySelectorAll('.sidebar-nav a');
    if (!links.length) return;
    document.addEventListener('keydown', function (e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const tag = (e.target && e.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      const idx = parseInt(e.key, 10);
      if (!(idx >= 1 && idx <= links.length)) return;
      const href = links[idx - 1].getAttribute('href');
      if (href && href !== location.pathname) { e.preventDefault(); location.href = href; }
    });
  })();
})();
