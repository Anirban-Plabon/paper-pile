// paper-pile editor: CodeMirror 6 + markdown (GFM + inline math) + Live Preview.
// JS is a thin layer: it renders and captures events. All logic lives in Python.
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { HighlightStyle, syntaxHighlighting, syntaxTree } from "@codemirror/language";
import { highlightSelectionMatches, searchKeymap } from "@codemirror/search";
import { Compartment, EditorState } from "@codemirror/state";
import { EditorView, drawSelection, dropCursor, keymap } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import { blocks, themeFacet } from "./blocks.js";
import { livePreview } from "./livepreview.js";
import { refreshEffect } from "./reveal.js";
import { editorContext } from "./context.js";
import { editorExtensions } from "./grammar.js";

const CHANGE_DEBOUNCE_MS = 300;
const RAW_PASTE_WINDOW_MS = 600;
const NO_SLASH_NODES = new Set(["FencedCode", "CodeBlock", "InlineCode", "URL", "CodeText"]);

const sourceStyle = HighlightStyle.define([
  { tag: t.heading, color: "var(--pp-heading, inherit)", fontWeight: "bold" },
  { tag: t.link, color: "var(--pp-accent, #3b82f6)" },
  { tag: t.url, color: "var(--pp-accent, #3b82f6)" },
  { tag: t.monospace, fontFamily: "monospace" },
]);

// Only these may be opened from a note (mirrors paper_pile/core/links.py `external_url`).
function externalUrl(href) {
  href = (href || "").trim();
  if (/[\s\x00-\x1f\x7f]/.test(href)) return null;
  if (/^www\./i.test(href)) href = "https://" + href;
  return /^(https?:\/\/[^/?#\s]+|mailto:\S+)/i.test(href) ? href : null;
}

function inNoSlashContext(state, pos) {
  for (let n = syntaxTree(state).resolveInner(pos, -1); n; n = n.parent) {
    if (NO_SLASH_NODES.has(n.name)) return true;
  }
  return false;
}

export function createEditor(
  parent,
  { doc = "", mode = "live", theme = "light", emit = () => {}, imageUploadUrl = null, linkTarget = "python" } = {},
) {
  const modeSlot = new Compartment();
  const themeSlot = new Compartment();
  const modeExt = (m) => (m === "live" ? [livePreview, blocks] : []);
  parent.classList.toggle("pp-dark", theme === "dark");
  let timer = null;
  let rawUntil = 0;
  let currentMode = mode;
  let currentTheme = theme;
  // Which document the editor currently shows. Python bumps it on every note switch and ignores
  // events carrying an older id, so a late "change" can never land in the wrong note.
  let docId = 0;

  const flush = () => {
    if (timer === null) return;
    clearTimeout(timer);
    timer = null;
    emit("change", { text: view.state.doc.toString(), docId });
  };
  const snapshot = () => ({ text: view.state.doc.toString(), docId });
  // Editor state of every open tab that is not on screen: its own undo history, cursor and
  // scroll anchor. A tab only ever gets its own state back, so Ctrl+Z cannot cross tabs.
  const parked = new Map();
  const park = () => {
    flush(); // report the outgoing tab's pending edit while docId still names it
    if (docId !== -1) parked.set(docId, view.state);
  };

  const handlePaste = (event, v) => {
    if (performance.now() < rawUntil) return false; // Ctrl+Shift+V: raw paste
    const cd = event.clipboardData;
    if (!cd) return false;
    const image = [...cd.items].find((i) => i.kind === "file" && i.type.startsWith("image/"));
    if (image && imageUploadUrl) {
      const file = image.getAsFile();
      event.preventDefault();
      fetch(imageUploadUrl, { method: "POST", headers: { "Content-Type": file.type }, body: file })
        .then((r) => r.json())
        .then((info) => emit("paste", { kind: "image", mime: file.type, ...info }))
        .catch((err) => emit("paste", { kind: "error", message: String(err) }));
      return true;
    }
    const html = cd.getData("text/html");
    const text = cd.getData("text/plain");
    if (!html && !text) return false;
    event.preventDefault();
    emit("paste", { kind: html ? "html" : "text", html, text });
    return true;
  };

  // A note switch builds a fresh state, which also drops the undo history: Ctrl+Z must never
  // pull the previous note's text into this one.
  const makeState = (text) =>
    EditorState.create({
      doc: text,
      extensions: [
        history(),
        drawSelection(),
        dropCursor(),
        highlightSelectionMatches(),
        EditorState.allowMultipleSelections.of(true),
        EditorView.lineWrapping,
        markdown({ base: markdownLanguage, extensions: editorExtensions }),
        syntaxHighlighting(sourceStyle),
        keymap.of([
          {
            key: "Mod-s",
            run: () => {
              flush();
              emit("save", snapshot());
              return true;
            },
          },
          ...defaultKeymap,
          ...historyKeymap,
          ...searchKeymap,
          indentWithTab,
        ]),
        themeSlot.of(themeFacet.of(currentTheme)),
        modeSlot.of(modeExt(currentMode)),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) {
            clearTimeout(timer);
            timer = setTimeout(flush, CHANGE_DEBOUNCE_MS);
          }
        }),
        EditorView.inputHandler.of((v, from, _to, text) => {
          if (text !== "/") return false;
          const line = v.state.doc.lineAt(from);
          const before = v.state.sliceDoc(line.from, from);
          if ((before !== "" && !/\s$/.test(before)) || inNoSlashContext(v.state, from)) return false;
          queueMicrotask(() =>
            emit("slash", { line: line.number, ch: from - line.from, coords: v.coordsAtPos(from) }),
          );
          return false; // let CodeMirror insert the "/"
        }),
        EditorView.domEventHandlers({
          paste: handlePaste,
          // Ctrl/Cmd+click on a link opens it; a plain click only places the caret (to edit it).
          // This must be `mousedown`, not `click`: CodeMirror's own Ctrl+click handling adds a
          // selection, which un-hides the link's syntax and rebuilds its DOM before `click` fires.
          mousedown: (e) => {
            if (!(e.ctrlKey || e.metaKey)) return false;
            const el = e.target.closest ? e.target.closest("[data-href]") : null;
            if (!el) return false;
            e.preventDefault();
            const href = el.getAttribute("data-href");
            const url = externalUrl(href);
            // Web mode: open here, inside the click, so the browser's popup blocker allows it.
            // Native window: Python opens the system browser. Notes/relative links: Python decides.
            if (url && linkTarget === "window") window.open(url, "_blank", "noopener,noreferrer");
            else emit("link", { href });
            return true;
          },
          keydown: (e) => {
            if (e.key === "Control" || e.key === "Meta") parent.classList.add("pp-ctrl");
            if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "v") rawUntil = performance.now() + RAW_PASTE_WINDOW_MS;
            return false;
          },
          keyup: (e) => {
            if (e.key === "Control" || e.key === "Meta") parent.classList.remove("pp-ctrl");
            return false;
          },
          blur: () => {
            parent.classList.remove("pp-ctrl");
            flush();
            emit("blur", snapshot());
            return false;
          },
        }),
      ],
    });

  const view = new EditorView({ parent, state: makeState(doc) });

  return {
    getText: () => view.state.doc.toString(),
    // Show tab `id`: its parked state if it has one, else a fresh state made from `text`.
    showDoc(id, text, path = "") {
      editorContext.notePath = path; // before the state swap: widgets built next read it
      if (id === docId) return;
      park();
      clearTimeout(timer);
      timer = null;
      let state = parked.get(id);
      if (state) {
        parked.delete(id);
        // mode/theme may have changed while this tab was parked
        state = state.update({
          effects: [
            modeSlot.reconfigure(modeExt(currentMode)),
            themeSlot.reconfigure(themeFacet.of(currentTheme)),
          ],
        }).state;
      } else {
        state = makeState(text);
      }
      docId = id;
      view.setState(state);
    },
    // Replace tab `id`'s content outright (restored text): fresh state, history dropped.
    // The note on screen was renamed/moved: relative image URLs must be recomputed.
    setPath(path) {
      editorContext.notePath = path;
      view.dispatch({ effects: refreshEffect.of(null) });
    },
    setText(text, id = docId, path = editorContext.notePath) {
      editorContext.notePath = path;
      if (id !== docId) park();
      else flush();
      clearTimeout(timer);
      timer = null;
      parked.delete(id);
      docId = id;
      view.setState(makeState(text));
    },
    // The tab was closed: forget its parked state.
    closeDoc(id) {
      parked.delete(id);
      if (id === docId) {
        // the tab on screen was closed: show an empty, unowned document so nothing is parked for it
        clearTimeout(timer);
        timer = null;
        docId = -1;
        view.setState(makeState(""));
      }
    },
    insertAtCursor(text) {
      view.dispatch(view.state.replaceSelection(text), { userEvent: "input.paste", scrollIntoView: true });
      flush();
    },
    setMode(m) {
      currentMode = m;
      view.dispatch({ effects: modeSlot.reconfigure(modeExt(m)) });
    },
    setTheme(name) {
      currentTheme = name;
      parent.classList.toggle("pp-dark", name === "dark");
      view.dispatch({ effects: themeSlot.reconfigure(themeFacet.of(name)) });
    },
    focus: () => view.focus(),
    flush,
    destroy() {
      flush();
      view.destroy();
    },
  };
}
