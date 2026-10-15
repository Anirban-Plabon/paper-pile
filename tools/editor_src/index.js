// paper-pile editor: CodeMirror 6 + markdown (GFM + inline math) + Live Preview.
// JS is a thin layer: it renders and captures events. All logic lives in Python.
import { defaultKeymap, history, isolateHistory, historyKeymap, indentWithTab } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { highlightSelectionMatches, searchKeymap } from "@codemirror/search";
import { Compartment, EditorSelection, EditorState } from "@codemirror/state";
import { EditorView, drawSelection, dropCursor, keymap } from "@codemirror/view";
import { classHighlighter, tags as t } from "@lezer/highlight";
import { blocks, themeFacet } from "./blocks.js";
import { livePreview } from "./livepreview.js";
import { refreshEffect } from "./reveal.js";
import { codeLanguages } from "./codelang.js";
import { editorContext } from "./context.js";
import { editorExtensions } from "./grammar.js";
import { listEditing } from "./listedit.js";
import { closeSlash, setSlashResults, slashExtension } from "./slash.js";
import { focusTableCell, tableKeys, tablesRuntime } from "./tablewidget.js";

const CHANGE_DEBOUNCE_MS = 300;
const RAW_PASTE_WINDOW_MS = 600;
// Where the caret starts in a freshly opened note: just below YAML front matter, so the
// properties block opens rendered instead of revealed (a caret at position 0 would touch it).
// Same shape as the grammar's rule (frontmatter.js): `---` line, then the next `---` line.
function initialCaret(text) {
  const m = /^---[ \t]*\r?\n(?:[^\n]*\n)*?---[ \t]*(?:\r?\n|$)/.exec(text);
  return m ? Math.min(m[0].length, text.length) : 0;
}

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

export function createEditor(
  parent,
  { doc = "", mode = "live", theme = "light", emit = () => {}, imageUploadUrl = null, linkTarget = "python" } = {},
) {
  tablesRuntime({ emit, getDocId: () => docId });
  editorContext.emit = emit;
  editorContext.getDocId = () => docId;
  const modeSlot = new Compartment();
  const themeSlot = new Compartment();
  const modeExt = (m) => (m === "live" ? [livePreview, blocks, tableKeys] : []);
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
    view.dispatch({ effects: closeSlash() }); // an open "/" menu does not travel between tabs
    flush(); // report the outgoing tab's pending edit while docId still names it
    if (docId !== -1) parked.set(docId, view.state);
  };

  // Send an image to Python's upload route (it stores it in the note's assets folder); Python then
  // inserts the markdown at the caret. The caret is where the paste/drop/pick happened.
  const uploadImage = async (file) => {
    const id = docId;
    try {
      const url = `${imageUploadUrl}?note=${encodeURIComponent(editorContext.notePath)}`;
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream", "X-PP-Upload": "1" },
        body: file,
      });
      const info = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(info.error || r.statusText);
      emit("image_saved", { docId: id, ref: info.ref, width: info.width ?? null });
    } catch (err) {
      emit("image_error", { docId: id, message: String(err && err.message ? err.message : err) });
    }
  };
  const uploadAll = async (files) => {
    for (const f of files) await uploadImage(f); // one after the other: each lands after the previous
  };
  const isImageFile = (f) => f.type.startsWith("image/") || /\.(png|jpe?g|gif|webp|bmp|avif|svg)$/i.test(f.name);

  const handlePaste = (event, v) => {
    if (performance.now() < rawUntil) return false; // Ctrl+Shift+V: raw paste
    const cd = event.clipboardData;
    if (!cd) return false;
    const image = [...cd.items].find((i) => i.kind === "file" && i.type.startsWith("image/"));
    if (image && imageUploadUrl) {
      event.preventDefault();
      uploadAll([image.getAsFile()]);
      return true;
    }
    const html = cd.getData("text/html");
    const text = cd.getData("text/plain");
    if (!html && !text) return false;
    event.preventDefault();
    emit("paste", { kind: html ? "html" : "text", html, text });
    return true;
  };

  // `.txt` notes are plain text: no markdown language, no rendering, no slash trigger, no link or
  // paste hooks. Which kind a note is follows its path; `plainDocs` remembers it per open doc.
  const plainDocs = new Set();
  const isPlainPath = (path) => /\.txt$/i.test(path || "");
  const isPlainDoc = () => plainDocs.has(docId);

  // A note switch builds a fresh state, which also drops the undo history: Ctrl+Z must never
  // pull the previous note's text into this one.
  const makeState = (text, id) => {
    const plain = isPlainPath(editorContext.notePath);
    if (plain) plainDocs.add(id);
    else plainDocs.delete(id);
    const common = [
      history(),
      drawSelection(),
      dropCursor(),
      highlightSelectionMatches(),
      EditorState.allowMultipleSelections.of(true),
      EditorView.lineWrapping,
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
      EditorView.updateListener.of((u) => {
        if (u.docChanged) {
          clearTimeout(timer);
          timer = setTimeout(flush, CHANGE_DEBOUNCE_MS);
        }
      }),
    ];
    const onBlur = () => {
      parent.classList.remove("pp-ctrl");
      flush();
      emit("blur", snapshot());
      return false;
    };
    const kind = plain
      ? [EditorView.domEventHandlers({ blur: onBlur })]
      : [
          markdown({ base: markdownLanguage, extensions: editorExtensions, codeLanguages, addKeymap: false }),
          listEditing,
          syntaxHighlighting(sourceStyle),
          syntaxHighlighting(classHighlighter), // `tok-*` classes inside code blocks; colours live in CSS
          modeSlot.of(modeExt(currentMode)),
          slashExtension({ emit, getDocId: () => docId }),
          EditorView.domEventHandlers({
            paste: handlePaste,
            // dropping image files puts them where they were dropped
            drop: (e, v) => {
              const dropped = e.dataTransfer ? [...e.dataTransfer.files] : [];
              if (!dropped.length) return false; // text and links: the editor's own handling
              e.preventDefault(); // never let the editor read a dropped file's bytes into the note
              const files = dropped.filter(isImageFile);
              if (!files.length || !imageUploadUrl) return true;
              const pos = v.posAtCoords({ x: e.clientX, y: e.clientY });
              if (pos !== null) v.dispatch({ selection: { anchor: pos } });
              uploadAll(files);
              return true;
            },
            // Ctrl/Cmd+click on any link opens it. A plain click opens a note link that is not being edited
            // (a web link's plain click only places the caret, to edit it).
            // This must be `mousedown`, not `click`: CodeMirror's own Ctrl+click handling adds a
            // selection, which un-hides the link's syntax and rebuilds its DOM before `click` fires.
            mousedown: (e) => {
              const ctrl = e.ctrlKey || e.metaKey;
              const wiki = e.target.closest ? e.target.closest("[data-wiki-note]") : null;
              if (wiki && !ctrl && (e.button !== 0 || !wiki.hasAttribute("data-wiki-open"))) return false;
              if (!ctrl && !wiki) return false;
              if (wiki) {
                e.preventDefault();
                emit("wikilink", {
                  note: wiki.getAttribute("data-wiki-note"),
                  heading: wiki.getAttribute("data-wiki-heading") || "",
                });
                return true;
              }
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
            blur: onBlur,
          }),
        ];
    return EditorState.create({
      doc: text,
      selection: EditorSelection.cursor(initialCaret(text)),
      extensions: [...common, ...kind],
    });
  };

  const view = new EditorView({ parent, state: makeState(doc, docId) });

  // Put `text` on screen for doc `id` with a fresh state (history dropped).
  const replaceText = (text, id, path, keepCaret) => {
    const head = view.state.selection.main.head;
    editorContext.notePath = path;
    if (id !== docId) park();
    else flush();
    clearTimeout(timer);
    timer = null;
    parked.delete(id);
    docId = id;
    view.setState(makeState(text, id));
    if (keepCaret) view.dispatch({ selection: { anchor: Math.min(head, view.state.doc.length) } });
  };

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
        // mode/theme may have changed while this tab was parked (plain text has no mode)
        const effects = [themeSlot.reconfigure(themeFacet.of(currentTheme))];
        if (!plainDocs.has(id)) effects.push(modeSlot.reconfigure(modeExt(currentMode)));
        state = state.update({ effects }).state;
      } else {
        state = makeState(text, id);
      }
      docId = id;
      view.setState(state);
    },
    // Replace tab `id`'s content outright (restored text): fresh state, history dropped.
    // The note on screen was renamed/moved: relative image URLs must be recomputed.
    setPath(path) {
      editorContext.notePath = path;
      if (docId !== -1 && isPlainPath(path) !== isPlainDoc()) {
        // renamed across .md <-> .txt: the note changes kind, so rebuild its state in place
        replaceText(view.state.doc.toString(), docId, path, true);
        return;
      }
      view.dispatch({ effects: refreshEffect.of(null) });
    },
    // `keepCaret`: an outside change was reloaded into the note on screen; stay where the user was.
    setText(text, id = docId, path = editorContext.notePath, keepCaret = false) {
      replaceText(text, id, path, keepCaret);
    },
    // The tab was closed: forget its parked state.
    closeDoc(id) {
      parked.delete(id);
      if (id === docId) {
        // the tab on screen was closed: show an empty, unowned document so nothing is parked for it
        clearTimeout(timer);
        timer = null;
        docId = -1;
        view.setState(makeState("", -1));
      }
    },
    // Apply edits made by Python (a link rewrite) to tab `id`, keeping its undo history. `changes`
    // are {from, to, insert} in UTF-16 offsets of `expected`, the text Python planned them on.
    // If the tab no longer holds exactly that text (a keystroke raced in) nothing is touched and
    // false is returned, so Python can leave that note alone instead of overwriting typing.
    applyChanges(id, changes, expected, cursor = null) {
      if (id === docId) {
        if (view.state.doc.toString() !== expected) return false;
        const spec = { changes, annotations: isolateHistory.of("full") }; // its own undo step
        if (cursor !== null) {
          spec.selection = { anchor: cursor }; // offset in the document after the changes
          spec.scrollIntoView = true;
        }
        view.dispatch(spec);
        return true;
      }
      const state = parked.get(id);
      if (!state) return true; // never shown yet: it will be built from Python's text
      if (state.doc.toString() !== expected) return false;
      parked.set(id, state.update({ changes }).state);
      return true;
    },
    // Put the cursor in a table cell (row 0 is the header). `from` is the table's start offset.
    focusTableCell(row, col, from = null) {
      focusTableCell(row, col, from, view.dom);
    },
    // Python's answer to a `slash_query` (the commands matching the typed text).
    setSlashResults(seq, groups) {
      setSlashResults(view, seq, groups);
    },
    // Wikilink targets that exist (normalised names), so links to missing notes can be styled.
    setKnownNotes(names) {
      editorContext.known = new Set(names);
      view.dispatch({ effects: refreshEffect.of(null) });
    },
    // Put the caret on 1-based `line` and bring it to the top of the view.
    gotoLine(line) {
      const doc = view.state.doc;
      const pos = doc.line(Math.max(1, Math.min(line, doc.lines))).from;
      view.dispatch({
        selection: { anchor: pos },
        effects: EditorView.scrollIntoView(pos, { y: "start", yMargin: 24 }),
      });
      view.focus();
    },
    insertAtCursor(text) {
      view.dispatch(view.state.replaceSelection(text), { userEvent: "input.paste", scrollIntoView: true });
      flush();
    },
    setMode(m) {
      currentMode = m;
      if (!isPlainDoc()) view.dispatch({ effects: modeSlot.reconfigure(modeExt(m)) });
    },
    setTheme(name) {
      currentTheme = name;
      parent.classList.toggle("pp-dark", name === "dark");
      view.dispatch({ effects: themeSlot.reconfigure(themeFacet.of(name)) });
    },
    // The `/image` command: let the user choose image files, which are then inserted at the caret.
    pickImage() {
      if (!imageUploadUrl) return;
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "image/*";
      input.multiple = true;
      input.addEventListener("change", () => uploadAll([...input.files].filter(isImageFile)));
      input.click();
    },
    focus: () => view.focus(),
    flush,
    destroy() {
      flush();
      view.destroy();
    },
  };
}
