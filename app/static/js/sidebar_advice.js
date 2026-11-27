/* 侧栏「今日训练建议」：正文在「今天」卡内、周期标签上方；默认收起 5 行，可展开/收起 */
(function () {
  const textEl = document.getElementById('adviceCard');
  const btn = document.getElementById('adviceRefresh');
  const wrap = document.getElementById('adviceWrap');
  const toggle = document.getElementById('adviceToggle');
  if (!textEl || !btn || !wrap || !toggle) return;

  let loading = false;
  let expanded = false;
  let measureTimer = 0;

  function renderToggleState() {
    toggle.hidden = false;
    toggle.textContent = expanded ? '收起' : '展开';
    toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  }

  function applyExpandedHeight() {
    if (!expanded) {
      textEl.style.maxHeight = '';
      return;
    }
    const limit = Math.min(Math.round(window.innerHeight * 0.46), 420);
    textEl.style.maxHeight = Math.min(textEl.scrollHeight, limit) + 'px';
  }

  function measure() {
    measureTimer = 0;
    if (expanded) {
      applyExpandedHeight();
      renderToggleState();
      return;
    }
    textEl.classList.remove('is-expanded');
    textEl.style.maxHeight = '';
    wrap.classList.remove('is-clamped');
    const overflow = textEl.scrollHeight > textEl.clientHeight + 2;
    toggle.hidden = !overflow;
    wrap.classList.toggle('is-clamped', overflow);
    toggle.textContent = '展开';
    toggle.setAttribute('aria-expanded', 'false');
  }

  function scheduleMeasure(delay) {
    if (measureTimer) clearTimeout(measureTimer);
    measureTimer = setTimeout(measure, delay || 40);
  }

  function setText(text) {
    textEl.textContent = text || '';
    expanded = false;
    textEl.classList.remove('is-expanded');
    textEl.style.maxHeight = '';
    scheduleMeasure(260);
  }

  function render(data) {
    textEl.dataset.status = data.status || 'none';
    if (data.status === 'ready' && data.text) setText(data.text);
    else if (data.status === 'generating') setText('今日建议生成中');
    else setText('今日建议未生成');
    btn.disabled = data.status === 'generating';
  }

  toggle.addEventListener('click', function () {
    expanded = !expanded;
    textEl.classList.toggle('is-expanded', expanded);
    wrap.classList.remove('is-clamped');
    applyExpandedHeight();
    renderToggleState();
    if (!expanded) scheduleMeasure(260);
  });

  btn.addEventListener('click', function () {
    if (loading) return;
    loading = true;
    btn.disabled = true;
    setText('今日建议生成中');
    App.api('/api/daily-advice/regenerate', { method: 'POST', body: { force: true } })
      .then(function (data) { render(data); })
      .catch(function (err) {
        App.toast(err.message || '重新生成失败', true);
        setText('今日建议未生成');
      })
      .then(function () {
        loading = false;
        btn.disabled = false;
      });
  });

  window.addEventListener('resize', function () {
    if (expanded) applyExpandedHeight();
    else scheduleMeasure(180);
  });
  scheduleMeasure(40);
})();
