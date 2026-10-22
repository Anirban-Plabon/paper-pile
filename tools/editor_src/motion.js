// Motion in the editor (PLAN §4.19): render-only cues for "where did it go".
//   * a jump (outline, wikilink heading, backlink, search: `gotoLine`) glides there and flashes
//     the target line;
//   * lines moved with Alt+↑/↓ slide in from where they were and flash;
//   * page view marks lines that crossed onto another page (pageview.js calls `markLines`).
// Only opacity, background and transform change (CSS in app.css), never a measured height, so
// clicks and the caret are right during an animation. The speed is `window.ppMotion` (theme.js,
// Settings → Animation speed): 0 = off, then a jump target keeps a still highlight until the
// next key or click. Marks live in a state field per editor (two can share a page).
import { StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin } from "@codemirror/view";

const FLASH_MS = 900;
const SCROLL_MS = 260;
const SLIDE_MS = 160;

export const motionFactor = () => {
  const m = Number(window.ppMotion);
  return Number.isFinite(m) && m >= 0 ? m : 1;
};

// { from, to, cls, style? } adds line marks on every line from..to; { clear: id } removes a batch.
const addMarks = StateEffect.define();
const clearMarks = StateEffect.define();
let seq = 0; // batch ids only (no editor state here)

const marksField = StateField.define({
  create: () => ({ set: Decoration.none, statics: [] }),
  update(value, tr) {
    let { set, statics } = value;
    set = set.map(tr.changes);
    for (const e of tr.effects) {
      if (e.is(addMarks)) {
        const { from, to, cls, style, id } = e.value;
        const doc = tr.state.doc;
        const ranges = [];
        const first = doc.lineAt(Math.min(from, doc.length)).number;
        const last = doc.lineAt(Math.min(to, doc.length)).number;
        for (let n = first; n <= last; n++) {
          const attributes = { class: cls, "data-pp-mark": String(id) };
          if (style) attributes.style = style;
          ranges.push(Decoration.line({ attributes, id }).range(doc.line(n).from));
        }
        set = set.update({ add: ranges, sort: true });
        if (e.value.still) statics = [...statics, id];
      } else if (e.is(clearMarks)) {
        const id = e.value;
        set = set.update({ filter: (_f, _t, d) => d.spec.id !== id });
        statics = statics.filter((s) => s !== id);
      }
    }
    // a still highlight (motion off) goes on the next edit or caret move by the user
    if (statics.length && (tr.docChanged || tr.isUserEvent("select")) && !tr.effects.some((e) => e.is(addMarks))) {
      const gone = new Set(statics);
      set = set.update({ filter: (_f, _t, d) => !gone.has(d.spec.id) });
      statics = [];
    }
    return { set, statics };
  },
  provide: (f) => EditorView.decorations.from(f, (v) => v.set),
});

// Mark lines from..to with `cls` for `ms` (× the speed). With motion off: `stillCls` instead,
// kept until the user's next edit or click/caret move; without `stillCls` nothing is marked.
export function markLines(view, from, to, { cls, ms = FLASH_MS, style = "", stillCls = "" }) {
  const factor = motionFactor();
  const id = ++seq;
  if (factor === 0) {
    if (stillCls) view.dispatch({ effects: addMarks.of({ from, to, cls: stillCls, id, still: true }) });
    return;
  }
  view.dispatch({ effects: addMarks.of({ from, to, cls, style, id }) });
  setTimeout(() => {
    if (view.dom.isConnected) view.dispatch({ effects: clearMarks.of(id) });
  }, ms * factor + 50);
}

// Scroll so that `pos` is near the top, gliding when it is within three screens (farther: jump to
// one screen away first). CodeMirror's heights below the fold are estimates, so the end is
// corrected with a normal scrollIntoView. Wheel or touch cancels the glide.
export function glideTo(view, pos, yMargin = 24) {
  const factor = motionFactor();
  const exact = () => view.dispatch({ effects: EditorView.scrollIntoView(pos, { y: "start", yMargin }) });
  const dom = view.scrollDOM;
  const target = () => {
    const box = dom.getBoundingClientRect();
    return Math.max(0, dom.scrollTop + view.documentTop - box.top + view.lineBlockAt(pos).top - yMargin);
  };
  let goal = target();
  const screen = dom.clientHeight || 1;
  const distance = goal - dom.scrollTop;
  if (factor === 0 || Math.abs(distance) < 4) return exact();
  if (Math.abs(distance) > 3 * screen) {
    dom.scrollTop = goal - Math.sign(distance) * screen;
    goal = target(); // the estimate improves once CodeMirror draws the lines near it
  }
  const start = dom.scrollTop;
  const ms = SCROLL_MS * factor;
  const t0 = performance.now();
  let stopped = false;
  const stop = () => { stopped = true; };
  dom.addEventListener("wheel", stop, { once: true, passive: true });
  dom.addEventListener("touchstart", stop, { once: true, passive: true });
  const ease = (x) => 1 - Math.pow(1 - x, 3);
  const step = (now) => {
    if (stopped || !view.dom.isConnected) return;
    const k = Math.min(1, (now - t0) / ms);
    dom.scrollTop = start + (goal - start) * ease(k);
    if (k < 1) requestAnimationFrame(step);
    else {
      dom.removeEventListener("wheel", stop);
      dom.removeEventListener("touchstart", stop);
      exact();
    }
  };
  requestAnimationFrame(step);
}

// Jump: caret on `pos`, glide there, flash the line.
export function jumpTo(view, pos) {
  view.dispatch({ selection: { anchor: pos } });
  glideTo(view, pos);
  markLines(view, pos, pos, { cls: "pp-jump-flash", stillCls: "pp-jump-static" });
}

// Alt+↑/↓ (CodeMirror's "move.line"): the moved lines slide in from where they were and flash.
const movedLines = ViewPlugin.fromClass(
  class {
    update(u) {
      if (!motionFactor()) return;
      for (const tr of u.transactions) {
        if (!tr.isUserEvent("move.line")) continue;
        const before = tr.startState.doc.lineAt(tr.startState.selection.main.head).number;
        const sel = tr.state.selection.main;
        const after = tr.state.doc.lineAt(sel.head).number;
        if (before === after) continue;
        // the line they jumped over: its height is how far they moved
        const over = after < before ? tr.state.doc.lineAt(sel.to).number + 1 : tr.state.doc.lineAt(sel.from).number - 1;
        const view = u.view;
        const height = over >= 1 && over <= tr.state.doc.lines ? view.lineBlockAt(tr.state.doc.line(over).from).height : view.defaultLineHeight;
        const from = (after < before ? 1 : -1) * Math.round(height);
        queueMicrotask(() =>
          markLines(view, sel.from, sel.to, { cls: "pp-moved", ms: Math.max(SLIDE_MS, FLASH_MS), style: `--pp-from: ${from}px` }),
        );
      }
    }
  },
);

export const motion = [marksField, movedLines];
