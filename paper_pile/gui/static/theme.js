// Theme: light / dark / system, accent colour, density and the editor's font. Python sends the
// settings (`ppTheme.apply`) and is told whether the result is dark (`pp_theme_resolved`) so the
// editor and its diagrams can follow. The first values are in `window.__pp_theme` (no flash).
(function () {
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let current = null;

  function isDark(cfg) {
    return cfg.theme === 'dark' || (cfg.theme === 'system' && media.matches);
  }

  // white text on a dark accent, near-black on a light one (WCAG relative luminance)
  function onAccent(hex) {
    const c = [1, 3, 5].map(function (i) {
      const v = parseInt(hex.slice(i, i + 2), 16) / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 0.5 ? '#1f2328' : '#fff';
  }

  function apply(cfg) {
    current = cfg;
    const dark = isDark(cfg);
    const root = document.documentElement;
    const body = document.body;
    body.classList.toggle('body--dark', dark);
    body.classList.toggle('body--light', !dark);
    body.classList.toggle('pp-compact', cfg.density === 'compact');
    root.style.setProperty('--pp-accent', dark ? cfg.accentDark : cfg.accentLight);
    root.style.setProperty('--pp-accent-rgb', dark ? cfg.accentDarkRgb : cfg.accentLightRgb);
    root.style.setProperty('--q-primary', dark ? cfg.accentDark : cfg.accentLight);
    root.style.setProperty('--pp-on-accent', onAccent(dark ? cfg.accentDark : cfg.accentLight));
    root.style.setProperty('--pp-editor-font', cfg.fontFamily);
    root.style.setProperty('--pp-editor-size', cfg.fontSize + 'px');
    root.style.setProperty('--pp-editor-lh', String(cfg.lineHeight));
    try {
      // Quasar's own widgets (buttons, switches, toggles) use the accent colour as "primary"
      if (window.Quasar && window.Quasar.colors) window.Quasar.colors.setBrand('primary', dark ? cfg.accentDark : cfg.accentLight);
      if (window.Quasar && window.Quasar.Dark) window.Quasar.Dark.set(dark);
    } catch (e) { /* the classes above are enough */ }
    window.ppIsDark = dark;
    tell(dark);
  }

  let told = null;
  function tell(dark) {
    if (told === dark) return;
    if (!window.emitEvent) { setTimeout(function () { tell(dark); }, 150); return; }
    told = dark;
    window.emitEvent('pp_theme_resolved', { dark: dark });
  }

  media.addEventListener('change', function () { if (current && current.theme === 'system') apply(current); });
  window.ppTheme = { apply: apply };
  function start() { if (window.__pp_theme) apply(window.__pp_theme); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
