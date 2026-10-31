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
  };
  window.App = App;
  document.addEventListener('click', function (e) {
    const mask = e.target.closest('.modal-mask');
    if (mask && e.target === mask) mask.classList.remove('open');
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
})();
