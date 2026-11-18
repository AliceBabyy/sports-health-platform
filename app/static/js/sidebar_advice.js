/* 侧栏「今日训练建议」：正文在「今天」卡内、周期标签上方；只处理刷新点击与生成中态 */
(function () {
  const textEl = document.getElementById('adviceCard');
  const btn = document.getElementById('adviceRefresh');
  if (!textEl || !btn) return;

  let loading = false;

  function setText(text) {
    textEl.textContent = text || '';
  }

  function render(data) {
    textEl.dataset.status = data.status || 'none';
    if (data.status === 'ready' && data.text) setText(data.text);
    else if (data.status === 'generating') setText('今日建议生成中');
    else setText('今日建议未生成');
    btn.disabled = data.status === 'generating';
  }

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
})();
