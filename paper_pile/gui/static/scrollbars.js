// The note's and the chat's scrollbar is half the pane's height, centred (user 2026-11-09): CSS
// cannot size a scrollbar part from its scroller's height, so each scroller gets
// `--pp-sb-end` = a quarter of its height, the length of the limit bar at each end of the track
// (app.css). Kept up to date with a ResizeObserver; new scrollers (a split's second editor, the
// chat) are picked up by a light periodic scan.
(() => {
  const SELECTOR = ".pp-editor .cm-scroller, .pp-chat-log";
  const seen = new WeakSet();
  const size = new ResizeObserver((entries) => {
    for (const e of entries) {
      const end = Math.max(8, Math.round(e.target.clientHeight / 4));
      e.target.style.setProperty("--pp-sb-end", `${end}px`);
    }
  });
  const scan = () => {
    document.querySelectorAll(SELECTOR).forEach((el) => {
      if (seen.has(el)) return;
      seen.add(el);
      size.observe(el);
    });
  };
  scan();
  setInterval(scan, 1000);
})();
