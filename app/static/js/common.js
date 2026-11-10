/* 通用工具：fetch 封装、弹窗、分钟/秒换算、日期格式化、toast（FE 基础件） */
(function () {
  /* 详情弹窗 kv 网格行（值允许少量受控 HTML，用户文本须先 escapeHtml） */
  function kvRows(pairs) {
    return '<div class="dl-grid">' + pairs.map(function (p) {
      return '<div class="dl-item"><span class="dl-label">' + p[0] + '</span><span class="dl-value">' + p[1] + '</span></div>';
    }).join('') + '</div>';
  }

  const App = {
    /** 计划/记录状态标签：计划=绿色(tag-mint)、记录=灰色(tag-gray)，三模块唯一口径（2026-11-04 抽出）；text 可覆盖默认文案 */
    statusTag: function (status, text) {
      const planned = status === 'planned';
      return '<span class="tag ' + (planned ? 'tag-mint' : 'tag-gray') + ' no-dot">' + (text || (planned ? '计划' : '记录')) + '</span>';
    },
    /** 读 tokens.css 的设计令牌：ECharts 等读不到 CSS 变量的地方统一走这里，令牌仍是唯一来源（fallback 仅防样式未加载） */
    cssVar: function (name, fallback) {
      const v = getComputedStyle(document.documentElement).getPropertyValue(name);
      return v ? v.trim() : (fallback || '');
    },
    bindBatchDelete: function (bodyId, allId, buttonId, endpoint, reload) {
      const body = document.getElementById(bodyId);
      const all = document.getElementById(allId);
      const button = document.getElementById(buttonId);
      const selected = () => Array.from(body.querySelectorAll('.batch-row:checked')).map(el => Number(el.value));
      const update = () => {
        const rows = body.querySelectorAll('.batch-row');
        const count = selected().length;
        button.disabled = count === 0;
        button.textContent = count ? '删除所选 (' + count + ')' : '删除所选';
        all.checked = rows.length > 0 && count === rows.length;
        all.indeterminate = count > 0 && count < rows.length;
      };
      body.addEventListener('change', e => { if (e.target.matches('.batch-row')) update(); });
      all.addEventListener('change', () => {
        body.querySelectorAll('.batch-row').forEach(el => { el.checked = all.checked; });
        update();
      });
      button.addEventListener('click', () => {
        const ids = selected();
        if (!ids.length) return;
        this.confirmDialog({ title: '删除所选', message: '确定删除选中的 ' + ids.length + ' 条计划或记录？删除后不可恢复。' })
          .then(ok => {
            if (!ok) return;
            button.disabled = true;
            this.api(endpoint + '/batch-delete', { method: 'POST', body: { ids } })
              .then(result => {
                this.toast('已删除 ' + result.deleted.length + ' 条');
                reload();
              })
              .catch(err => { this.toast(err.message, true); update(); });
          });
      });
      return { reset: () => { all.checked = false; all.indeterminate = false; update(); } };
    },
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

    /* ---------- 统一「查看详情」弹窗（健身/游泳/舞蹈记录操作列共用，2026-11-04） ---------- */
    openDetail(kind, row) {
      if (!row) return;
      const title = document.getElementById('detailTitle');
      const sub = document.getElementById('detailSub');
      const body = document.getElementById('detailBody');
      const esc = this.escapeHtml.bind(this);
      // 心得区块：仅记录态且确实有内容才展示（空心得不占位）
      const hasNote = (n, keys) => !!n && keys.some(k => n[k] != null && String(n[k]).trim() !== '');
      if (kind === 'training') {
        const rec = row.status === 'recorded';
        title.textContent = rec ? '训练记录详情' : '训练计划详情';
        sub.innerHTML = '<span class="dl-sub">' + App.statusTag(row.status) + esc(row.date) + '</span>';
        let dur = '—';
        if (row.duration_s) {
          dur = this.fmtDuration(row.duration_s);
        } else if (row.start_time && row.end_time) {
          dur = this.fmtDuration(Math.max(0, Math.round((Date.parse(row.end_time) - Date.parse(row.start_time)) / 1000)));
        }
        const kv = [
          ['训练内容', row.body_parts_summary || '—'],
          ['起止时间', (row.start_time || row.end_time)
            ? ((row.start_time ? row.start_time.replace('T', ' ').slice(0, 16) : '—') + ' ~ ' + (row.end_time ? row.end_time.replace('T', ' ').slice(0, 16) : '—'))
            : '—'],
          ['时长', dur],
          ['平均心率', row.avg_heart_rate != null ? row.avg_heart_rate + ' bpm' : '—'],
          ['最大心率', row.max_heart_rate != null ? row.max_heart_rate + ' bpm' : '—'],
          ['热量', row.calories != null ? row.calories + ' kcal' : '—'],
        ];
        kv.push(
          ['容量', (row.total_volume != null ? row.total_volume : 0) + ' kg'],
          ['组数', (row.total_sets != null ? row.total_sets : 0) + ' 组'],
          ['动作数', row.item_count + ' 个'],
        );
        const items = (row.items || []).map(function (it) {
          const w = it.weight_kg != null ? it.weight_kg : '—';
          const s = it.sets != null ? it.sets : '—';
          const r = it.reps != null ? it.reps : '—';
          const t = it.target_weight_kg != null ? it.target_weight_kg : '—';
          return '<tr><td>' + esc(it.exercise_name) + '</td><td>' + esc(it.body_part || '—') + '</td>' +
            '<td class="num">' + esc(w) + '</td><td class="num">' + esc(s) + '</td><td class="num">' + esc(r) + '</td><td class="num">' + esc(t) + '</td></tr>';
        }).join('');
        let html = kvRows(kv);
        if (row.remark) html += '<div class="dl-remark">' + esc(row.remark) + '</div>';
        html += '<div class="dl-block"><div class="dl-block-title">动作明细（' + row.item_count + '）</div>' +
          '<div class="table-wrap"><table class="tbl dl-tbl"><thead><tr><th>动作</th><th>部位</th><th>重量 kg</th><th>组数</th><th>每组个数</th><th>目标重量</th></tr></thead><tbody>' + items + '</tbody></table></div></div>';
        if (rec && hasNote(row.note, ['rating', 'best_movement', 'notes', 'next_steps'])) {
          const n = row.note;
          html += '<div class="dl-block"><div class="dl-block-title">练后心得</div>' + kvRows([
            ['自我评估', n.rating ? '★'.repeat(n.rating) : '—'],
            ['最佳动作', n.best_movement ? esc(n.best_movement) : '—'],
            ['复盘反思', n.notes ? esc(n.notes) : '—'],
            ['下一步想法', n.next_steps ? esc(n.next_steps) : '—'],
          ]) + '</div>';
        }
        body.innerHTML = html;
      } else if (kind === 'swim') {
        const rec = row.status === 'recorded';
        title.textContent = rec ? '游泳记录详情' : '游泳计划详情';
        sub.innerHTML = '<span class="dl-sub">' + App.statusTag(row.status) + esc(row.date) + '</span>';
        body.innerHTML = kvRows([
          ['距离', row.distance_m != null ? row.distance_m + ' m' : '—'],
          ['时段', (row.start_time || row.end_time)
            ? ((row.start_time ? row.start_time.substring(11, 16) : '') + (row.start_time && row.end_time ? '–' : '') + (row.end_time ? row.end_time.substring(11, 16) : ''))
            : '—'],
          ['时长', this.fmtClock(row.duration_s)],
          ['配速', row.pace != null ? row.pace + ' min/100m' : '—'],
          ['主泳姿', row.main_stroke_label || '—'],
          ['平均心率', row.avg_heart_rate != null ? row.avg_heart_rate + ' bpm' : '—'],
          ['总划水', row.total_strokes != null ? row.total_strokes + ' 次' : '—'],
          ['趟数', row.laps != null ? row.laps + ' 趟' : '—'],
          ['平均划频', row.avg_stroke_rate != null ? row.avg_stroke_rate + ' 次/分' : '—'],
          ['活动卡路里', row.calories != null ? row.calories + ' kcal' : '—'],
          ['备注', esc(row.remark || '—')],
        ]);
        if (rec && hasNote(row.note, ['rating', 'stroke_insight', 'notes'])) {
          const n = row.note;
          body.innerHTML += '<div class="dl-block"><div class="dl-block-title">练后心得</div>' + kvRows([
            ['自我评估', n.rating ? '★'.repeat(n.rating) : '—'],
            ['泳姿感悟', n.stroke_insight ? esc(n.stroke_insight) : '—'],
            ['其他', n.notes ? esc(n.notes) : '—'],
          ]) + '</div>';
        }
      } else if (kind === 'dance') {
        const rec = row.status === 'recorded';
        title.textContent = rec ? '舞蹈记录详情' : '舞蹈计划详情';
        sub.innerHTML = '<span class="dl-sub">' + App.statusTag(row.status) + esc(row.date) + '</span>';
        body.innerHTML = kvRows([
          ['舞种', row.dance_type || '—'],
          ['星级', row.stars != null ? '★'.repeat(row.stars) : '—'],
          ['上课时间', row.start_time || row.end_time ? (row.start_time ? row.start_time.substring(11, 16) : '') + (row.start_time && row.end_time ? '–' : '') + (row.end_time ? row.end_time.substring(11, 16) : '') : '—'],
          ['舞蹈老师', row.teacher || '—'],
          ['风格', row.style || '—'],
          ['时长', this.fmtClock(row.duration_s)],
          ['平均心率', row.avg_heart_rate != null ? row.avg_heart_rate + ' bpm' : '—'],
          ['最大心率', row.max_heart_rate != null ? row.max_heart_rate + ' bpm' : '—'],
          ['总卡路里', row.calories != null ? row.calories + ' kcal' : '—'],
          ['备注', esc(row.remark || '—')],
        ]);
        if (rec && hasNote(row.note, ['rating', 'video_effect', 'notes'])) {
          const n = row.note;
          body.innerHTML += '<div class="dl-block"><div class="dl-block-title">练后心得</div>' + kvRows([
            ['自我评估', n.rating ? '★'.repeat(n.rating) : '—'],
            ['视频效果', n.video_effect ? '★'.repeat(n.video_effect) : '—'],
            ['感悟', n.notes ? esc(n.notes) : '—'],
          ]) + '</div>';
        }
      }
      this.openModal('modalDetail');
    },

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

    /* ---------- 练后庆祝弹窗（彩带特效；纯展示弹窗，点遮罩/👏 均可关闭） ----------
       opts: { showNote: 是否显示「记录心得」按钮, onNote: 点「记录心得」回调, onClose: 弹窗关闭回调 } */
    celebrate(opts = {}) {
      const showNote = opts.showNote !== false;
      let mask = document.getElementById('celebrateMask');
      if (!mask) {
        mask = document.createElement('div');
        mask.id = 'celebrateMask';
        mask.className = 'modal-mask celebrate-mask';
        mask.innerHTML =
          '<div class="celebrate-stage"></div>' +
          '<div class="modal celebrate-modal">' +
          '<div class="celebrate-emoji">🎉</div>' +
          '<div class="celebrate-title">恭喜完成训练，又是自律的一天！</div>' +
          '<div class="modal-actions celebrate-actions">' +
          '<button type="button" class="btn" id="celebrateNote">记录心得</button>' +
          '<button type="button" class="btn btn-primary" id="celebrateClap">完成👏</button>' +
          '</div></div>';
        document.body.appendChild(mask);
        const self = this;
        mask.addEventListener('click', function (e) {
          if (e.target === mask) { close(); return; }
          const b = e.target.closest('button');
          if (!b) return;
          if (b.id === 'celebrateClap') close();
          else if (b.id === 'celebrateNote') { const cb = mask._onNote; mask._noteOpened = true; close(); if (cb) cb(); }
        });
      }
      function close() {
        mask.classList.remove('open');
        // 彩带下次重画
        setTimeout(function () { const s = mask.querySelector('.celebrate-stage'); if (s) s.innerHTML = ''; }, 400);
        // 走了「记录心得」分支：等心得弹窗关闭后再由 onNote 链路触发收尾；否则直接 onClose
        if (!mask._noteOpened && mask._onClose) { const cb = mask._onClose; mask._onClose = null; cb(); }
      }
      mask._onNote = opts.onNote || null;
      mask._onClose = opts.onClose || null;
      mask._noteOpened = false;
      mask.querySelector('#celebrateNote').style.display = showNote ? '' : 'none';
      mask.classList.add('open');
      // 彩带：80 片，随机颜色/水平位置/下落时长/延迟
      const stage = mask.querySelector('.celebrate-stage');
      stage.innerHTML = '';
      const colors = ['#2dd4bf', '#f59e0b', '#f472b6', '#818cf8', '#38bdf8', '#a3e635'];
      for (let i = 0; i < 80; i++) {
        const p = document.createElement('i');
        p.className = 'confetti';
        p.style.left = Math.random() * 100 + '%';
        p.style.background = colors[i % colors.length];
        p.style.animationDuration = (2.2 + Math.random() * 1.8) + 's';
        p.style.animationDelay = (Math.random() * 0.6) + 's';
        p.style.transform = 'rotate(' + (Math.random() * 360) + 'deg)';
        stage.appendChild(p);
      }
    },

    /* 星级评分小部件 HTML（5 颗可点星星；用法：容器 innerHTML = App.starWidget(3)，监听 .star 的 click） */
    starWidgetHtml(value) {
      let html = '<span class="star-widget">';
      for (let i = 1; i <= 5; i++) {
        html += '<i class="sw-star' + (i <= (value || 0) ? ' on' : '') + '" data-v="' + i + '">★</i>';
      }
      return html + '</span>';
    },
    /* 给容器绑定星级点击：写入隐藏值并刷新高亮。返回当前分值 getter */
    bindStars(containerEl, initial, onSet) {
      function paint(v) {
        containerEl.querySelectorAll('.sw-star').forEach(function (s) {
          s.classList.toggle('on', parseInt(s.dataset.v, 10) <= v);
        });
      }
      let cur = initial || 0;
      paint(cur);
      containerEl.addEventListener('click', function (e) {
        const s = e.target.closest('.sw-star');
        if (!s) return;
        cur = parseInt(s.dataset.v, 10);
        paint(cur);
        if (onSet) onSet(cur);
      });
      return function () { return cur; };
    },

    /* 统一二次确认弹窗（删除等危险操作）→ Promise<boolean>（确认 true / 取消或遮罩点击 false） */
    confirmDialog(opts = {}) {      const o = {
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
