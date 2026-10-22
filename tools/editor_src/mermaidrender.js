// Mermaid diagrams as SVG strings: the editor's diagram widgets, chat replies and the print
// layout (print.js) all draw them here. Mermaid loads on the first diagram (a lazy chunk).
//
// The print layout runs in a frame of the editor's page and is laid out again after every pause
// in typing: it borrows the page's cache, so a diagram is drawn once, not on every layout.
function sharedCache() {
  try {
    if (window.parent !== window && window.parent.__ppSvgCache) return window.parent.__ppSvgCache;
  } catch {
    /* another origin: keep our own */
  }
  return (window.__ppSvgCache ??= new Map());
}

const CACHE_MAX = 100;
const svgCache = sharedCache(); // `${theme}\0${src}` -> svg string
let mermaidPromise = null;
let renderChain = Promise.resolve();
let renderCount = 0;

const loadMermaid = () => (mermaidPromise ??= import("mermaid").then((m) => m.default));

// A diagram already drawn (to show it at once, without waiting a tick), or undefined.
export const cachedSvg = (src, theme) => svgCache.get(`${theme}\0${src}`);

// Renders are serialized: mermaid keeps global state (initialize + temp DOM nodes).
// `parse` runs first and throws on invalid input, so mermaid never injects its error graphic.
export function renderMermaid(src, theme) {
  const key = `${theme}\0${src}`;
  if (svgCache.has(key)) return Promise.resolve(svgCache.get(key));
  const job = renderChain.then(async () => {
    const mermaid = await loadMermaid();
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: theme === "dark" ? "dark" : "default" });
    await mermaid.parse(src);
    const { svg } = await mermaid.render(`pp-mmd-${++renderCount}`, src);
    if (svgCache.size >= CACHE_MAX) svgCache.delete(svgCache.keys().next().value);
    svgCache.set(key, svg);
    return svg;
  });
  renderChain = job.catch(() => {});
  return job;
}

