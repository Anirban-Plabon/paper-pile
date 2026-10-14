// paper-pile editor: CodeMirror 6 + markdown (GFM + inline math) + Live Preview.
// JS is a thin layer: it renders and captures events. All logic lives in Python.
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { HighlightStyle, syntaxHighlighting, syntaxTree } from "@codemirror/language";
import { highlightSelectionMatches, searchKeymap } from "@codemirror/search";
import { Annotation, Compartment, EditorState } from "@codemirror/state";
import { EditorView, drawSelection, dropCursor, keymap } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import { livePreview } from "./livepreview.js";
import { MathExt } from "./math.js";

const External = Annotation.define(); // changes made via the API are not echoed back
const CHANGE_DEBOUNCE_MS = 300;
const RAW_PASTE_WINDOW_MS = 600;
const NO_SLASH_NODES = new Set(["FencedCode", "CodeBlock", "InlineCode", "URL", "CodeText"]);

const sourceStyle = HighlightStyle.define([
  { tag: t.heading, color: "var(--pp-heading, inherit)", fontWeight: "bold" },
  { tag: t.link, color: "var(--pp-accent, #3b82f6)" },
  { tag: t.url, color: "var(--pp-accent, #3b82f6)" },
  { tag: t.monospace, fontFamily: "monospace" },
]);

function inNoSlashContext(state, pos) {
  for (let n = syntaxTree(state).resolveInner(pos, -1); n; n = n.parent) {
    if (NO_SLASH_NODES.has(n.name)) return true;
  }
  return false;
}

export function createEditor(parent, { doc = "", mode = "live", emit = () => {}, imageUploadUrl = null } = {}) {
  const modeSlot = new Compartment();
  const modeExt = (m) => (m === "live" ? livePreview : []);
  let timer = null;
  let rawUntil = 0;

  const flush = () => {
    if (timer === null) return;
    clearTimeout(timer);
    timer = null;
    emit("change", { text: view.state.doc.toString() });
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

  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc,
      extensions: [
        history(),
        drawSelection(),
        dropCursor(),
        highlightSelectionMatches(),
        EditorState.allowMultipleSelections.of(true),
        EditorView.lineWrapping,
        markdown({ base: markdownLanguage, extensions: [MathExt] }),
        syntaxHighlighting(sourceStyle),
        keymap.of([...defaultKeymap, ...historyKeymap, ...searchKeymap, indentWithTab]),
        modeSlot.of(modeExt(mode)),
        EditorView.updateListener.of((u) => {
          if (u.docChanged && !u.transactions.every((tr) => tr.annotation(External))) {
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
          keydown: (e) => {
            if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "v") rawUntil = performance.now() + RAW_PASTE_WINDOW_MS;
            return false;
          },
          blur: () => {
            flush();
            return false;
          },
        }),
      ],
    }),
  });

  return {
    getText: () => view.state.doc.toString(),
    setText(text) {
      clearTimeout(timer);
      timer = null;
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: text },
        annotations: External.of(true),
      });
    },
    insertAtCursor(text) {
      view.dispatch(view.state.replaceSelection(text), { userEvent: "input.paste", scrollIntoView: true });
      flush();
    },
    setMode(m) {
      view.dispatch({ effects: modeSlot.reconfigure(modeExt(m)) });
    },
    focus: () => view.focus(),
    flush,
    destroy() {
      flush();
      view.destroy();
    },
  };
}
