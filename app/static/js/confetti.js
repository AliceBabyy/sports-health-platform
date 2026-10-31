/* 轻量彩带特效（FE-15：轻量实现、弹窗关闭即停，无外部依赖） */
window.Confetti = (function () {
  const COLORS = ['#e05d38', '#c8452b', '#e0a72b', '#0e8f72', '#2f8f9f', '#c2335f', '#b97a1e', '#5a6472'];
  let rafId = null, canvas = null, particles = [];

  function ensureCanvas() {
    if (canvas) return;
    canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:400';
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    document.body.appendChild(canvas);
  }

  function tick() {
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    particles.forEach(function (p) {
      p.vy += 0.06; p.vx *= 0.99; p.y += p.vy; p.x += p.vx; p.rot += p.vr;
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
      ctx.restore();
    });
    particles = particles.filter(function (p) { return p.y < canvas.height + 20; });
    if (particles.length) rafId = requestAnimationFrame(tick);
    else stop();
  }

  function launch(opts) {
    stop();
    ensureCanvas();
    const n = (opts && opts.count) || 140;
    const x0 = window.innerWidth / 2;
    for (let i = 0; i < n; i++) {
      particles.push({
        x: x0 + (Math.random() - 0.5) * 180,
        y: (opts && opts.fromTop) ? -10 : window.innerHeight * 0.35,
        vx: (Math.random() - 0.5) * 9,
        vy: -(Math.random() * 10 + 4),
        size: 6 + Math.random() * 5,
        rot: Math.random() * Math.PI * 2,
        vr: (Math.random() - 0.5) * 0.25,
        color: COLORS[Math.floor(Math.random() * COLORS.length)]
      });
    }
    rafId = requestAnimationFrame(tick);
    setTimeout(stop, (opts && opts.duration) || 4000);
  }

  function stop() {
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    particles = [];
    if (canvas) { canvas.remove(); canvas = null; }
  }

  return { launch: launch, stop: stop };
})();
