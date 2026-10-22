// One tooltip for the whole app (paper_pile/gui/tips.py): any element with data-tip gets it on
// hover after a short delay, below the element (above it if there is no room), always 8 px
// inside the window. It goes away on leave, click, key press, scroll or when the window blurs.
(function () {
  const MARGIN = 8, GAP = 6, DELAY = 450;
  let box = null, timer = null, current = null;
  function el() {
    if (!box) { box = document.createElement('div'); box.className = 'pp-tip'; document.body.appendChild(box); }
    return box;
  }
  function show(target) {
    const text = target.dataset.tip;
    if (!text || !target.isConnected) return;
    const t = el();
    t.textContent = text;
    t.classList.add('pp-tip-on');
    const r = target.getBoundingClientRect();
    const w = t.offsetWidth, h = t.offsetHeight;
    let x = r.left + r.width / 2 - w / 2;
    let y = r.bottom + GAP;
    if (y + h > innerHeight - MARGIN) y = r.top - GAP - h;
    x = Math.max(MARGIN, Math.min(x, innerWidth - MARGIN - w));
    y = Math.max(MARGIN, Math.min(y, innerHeight - MARGIN - h));
    t.style.left = x + 'px';
    t.style.top = y + 'px';
  }
  function hide() {
    clearTimeout(timer);
    timer = null;
    current = null;
    if (box) box.classList.remove('pp-tip-on');
  }
  document.addEventListener('mouseover', function (e) {
    const target = e.target && e.target.closest ? e.target.closest('[data-tip]') : null;
    if (target === current) return;
    hide();
    if (!target || !target.dataset.tip) return;
    current = target;
    timer = setTimeout(function () { show(target); }, DELAY);
  }, true);
  ['mousedown', 'keydown', 'scroll', 'wheel'].forEach(function (type) { document.addEventListener(type, hide, true); });
  window.addEventListener('blur', hide);
})();
