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
import { MathExt } from "./math.js";

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

export function createEditor(
  parent,
  { doc = "", mode = "live", theme = "light", emit = () => {}, imageUploadUrl = null } = {},
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
        markdown({ base: markdownLanguage, extensions: [MathExt] }),
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
          keydown: (e) => {
            if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "v") rawUntil = performance.now() + RAW_PASTE_WINDOW_MS;
            return false;
          },
          blur: () => {
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
    setText(text, id = docId) {
      clearTimeout(timer);
      timer = null;
      docId = id;
      view.setState(makeState(text));
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
