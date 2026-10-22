// paper-pile editor: CodeMirror 6 + markdown (GFM + inline math) + Live Preview.
// JS is a thin layer: it renders and captures events. All logic lives in Python.
import { defaultKeymap, history, isolateHistory, historyKeymap, indentWithTab } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { HighlightStyle, indentUnit, syntaxHighlighting, syntaxTree } from "@codemirror/language";
import { SearchQuery, findNext, highlightSelectionMatches, openSearchPanel, searchKeymap, setSearchQuery } from "@codemirror/search";
import { Annotation, Compartment, EditorSelection, EditorState, Transaction } from "@codemirror/state";
import { EditorView, drawSelection, dropCursor, keymap, tooltips } from "@codemirror/view";
import { classHighlighter, tags as t } from "@lezer/highlight";
import { blocks, themeFacet } from "./blocks.js";
import { livePreview } from "./livepreview.js";
import { refreshEffect } from "./reveal.js";
import { codeLanguages } from "./codelang.js";
import { editorContext, runtimeFacet } from "./context.js";
import { editorExtensions } from "./grammar.js";
import { autoBrackets, autoClose } from "./autoclose.js";
import { headingFolding } from "./fold.js";
import { listEditing } from "./listedit.js";
import { pageView, printLayoutReady } from "./pageview.js";
import { selectionSync } from "./selectionsync.js";
import { closeSlash, setSlashResults, slashExtension } from "./slash.js";
import { focusTableCell, tableKeys } from "./tablewidget.js";
import { streamAppend, streamBegin, streamEnd, streamField } from "./stream.js";
import { typeset } from "./typeset.js";

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

// Chat replies are typeset by the same code as the editor's widgets (KaTeX, Mermaid).
if (typeof window !== "undefined") {
  window.ppTypeset = (el, theme) => typeset(el, theme || (window.ppIsDark ? "dark" : "light"));
}

// Marks a change mirrored from the other editor of a split (not the user's, not reported back).
const mirrored = Annotation.define();

// Does the note end with something other than a paragraph (a heading, list, quote, table, fenced
// block, math, an image or embed line, a rule)? Then there is no place after it for the caret.
function endsWithBlock(state) {
  const last = state.doc.line(state.doc.lines);
  if (/^\s*!\[/.test(last.text)) return true; // an image or embed on its own line is drawn as a block
  let node = syntaxTree(state).resolveInner(last.from, 1);
  while (node.parent && node.parent.name !== "Document") node = node.parent;
  return node.name !== "Paragraph" && node.name !== "Document";
}

// Open the search panel; with `replace`, put the caret in its replace field. With `query` (a
// vault-search hit), search for it and select the first match after the caret.
function openSearch(view, replace, query = "") {
  openSearchPanel(view);
  if (query) {
    view.dispatch({ effects: setSearchQuery.of(new SearchQuery({ search: query })) });
    findNext(view);
  }
  const name = replace ? "replace" : "search";
  const grab = () => {
    const field = view.dom.querySelector(`.cm-search input[name=${name}]`);
    if (field && document.activeElement !== field) {
      field.focus();
      field.select();
    }
  };
  grab();
  // opened from a menu: the menu hands focus back to its button as it closes, so take it again
  for (const ms of [120, 320]) setTimeout(grab, ms);
  return true;
}

export function createEditor(
  parent,
  { doc = "", mode = "live", theme = "light", emit = () => {}, imageUploadUrl = null, linkTarget = "python", options = {} } = {},
) {
  // this editor's own runtime (note path, events, doc id), reached by its widgets via the facet
  const rt = { notePath: "", emit, getDocId: () => docId };
  const modeSlot = new Compartment();
  const optionsSlot = new Compartment();
  // word wrap, tab size, spell check, page view (Settings): applied to every open note
  let currentOptions = { wordWrap: true, tabSize: 4, spellCheck: false, lang: "en", pageView: false, pageStyle: "lines", paper: "A4", textWidthMm: 170, paperHeightMm: 297, marginMm: 20, ...options };
  const optionsExt = (o) => [
    o.wordWrap ? EditorView.lineWrapping : [],
    EditorState.tabSize.of(o.tabSize),
    indentUnit.of(" ".repeat(o.tabSize)),
    EditorView.contentAttributes.of({ spellcheck: o.spellCheck ? "true" : "false", lang: o.lang || "en" }),
    o.pageView ? pageView({ style: o.pageStyle, paper: o.paper, textWidthMm: o.textWidthMm, paperHeightMm: o.paperHeightMm, marginMm: o.marginMm }) : [],
  ];
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

  // Ln / Col for the status bar, a moment after the caret stops moving
  let caretTimer = null;
  const reportCaret = (state) => {
    clearTimeout(caretTimer);
    caretTimer = setTimeout(() => {
      const head = state.selection.main.head;
      const line = state.doc.lineAt(head);
      emit("caret", { docId, line: line.number, col: head - line.from + 1 });
    }, 120);
  };

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
      const url = `${imageUploadUrl}?note=${encodeURIComponent(rt.notePath)}`;
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

  // Slash menu / autocomplete stay out of the strip a maximized WSL window has under the
  // Windows taskbar (--pp-inset-*, set by native_boot.py); CodeMirror only knows innerHeight.
  const tooltipSpace = (view) => {
    const css = getComputedStyle(document.documentElement);
    const inset = (name) => parseFloat(css.getPropertyValue(name)) || 0;
    const win = view.dom.ownerDocument.defaultView;
    return { top: inset("--pp-inset-top"), left: 0, right: win.innerWidth, bottom: win.innerHeight - inset("--pp-inset-bottom") };
  };

  // A note switch builds a fresh state, which also drops the undo history: Ctrl+Z must never
  // pull the previous note's text into this one.
  const makeState = (text, id) => {
    const plain = isPlainPath(rt.notePath);
    if (plain) plainDocs.add(id);
    else plainDocs.delete(id);
    const common = [
      // all the pieces of one AI answer belong to one undo step (the first one is isolated, see stream.js)
      history({ joinToEvent: (tr, adjacent) => (tr.isUserEvent("input.type.ai") && !tr.annotation(isolateHistory)) || adjacent }),
      streamField,
      drawSelection(),
      dropCursor(),
      tooltips({ tooltipSpace }),
      highlightSelectionMatches(),
      runtimeFacet.of(rt),
      // the user is in this editor now (Python makes its note the active one)
      EditorView.domEventHandlers({ focus: () => { emit("focus", { docId }); return false; } }),
      EditorState.allowMultipleSelections.of(true),
      optionsSlot.of(optionsExt(currentOptions)),
      keymap.of([
        {
          key: "Mod-s",
          run: () => {
            flush();
            emit("save", snapshot());
            return true;
          },
        },
        // Ctrl+Enter: a page break here (like Word); Python inserts it (the slash command's rules).
        // Before the default keymap, which uses Mod-Enter for "insert blank line".
        {
          key: "Mod-Enter",
          run: (v) => {
            if (isPlainDoc()) return false;
            const r = v.state.selection.main;
            flush();
            emit("page_break", { docId, from: r.from, to: r.to });
            return true;
          },
        },
        ...defaultKeymap,
        ...historyKeymap,
        ...searchKeymap,
        { key: "Mod-h", run: (v) => openSearch(v, true) },
        indentWithTab,
      ]),
      themeSlot.of(themeFacet.of(currentTheme)),
      EditorView.updateListener.of((u) => {
        if (u.docChanged && !u.transactions.some((tr) => tr.annotation(mirrored))) {
          clearTimeout(timer);
          timer = setTimeout(flush, CHANGE_DEBOUNCE_MS);
        }
        if ((u.selectionSet || u.docChanged) && u.view.hasFocus) reportCaret(u.state);
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
          autoClose,
          autoBrackets,
          headingFolding,
          syntaxHighlighting(sourceStyle),
          syntaxHighlighting(classHighlighter), // `tok-*` classes inside code blocks; colours live in CSS
          modeSlot.of(modeExt(currentMode)),
          slashExtension(),
          selectionSync({ emit, getDocId: () => docId }),
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
              const tagEl = e.target.closest ? e.target.closest("[data-tag]") : null;
              if (tagEl && e.button === 0 && (ctrl || tagEl.hasAttribute("data-tag-open"))) {
                e.preventDefault();
                emit("tag", { tag: tagEl.getAttribute("data-tag") });
                return true;
              }
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

  // A click below the end of a note that ends with a block (table, image, heading, list, …) would
  // put the caret inside that block: give the note an empty last line and put the caret there.
  view.scrollDOM.addEventListener(
    "mousedown",
    (e) => {
      if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || isPlainDoc()) return;
      const { doc: d } = view.state;
      const last = d.line(d.lines);
      if (!last.text.trim()) return; // there already is an empty line to go to
      if (e.clientY <= view.documentTop + view.lineBlockAt(last.to).bottom) return;
      if (!endsWithBlock(view.state)) return;
      e.preventDefault();
      view.dispatch({ changes: { from: last.to, insert: "\n" }, selection: { anchor: last.to + 1 }, scrollIntoView: true, userEvent: "input" });
      view.focus();
    },
    true,
  );

  // Put `text` on screen for doc `id` with a fresh state (history dropped).
  const replaceText = (text, id, path, keepCaret) => {
    const head = view.state.selection.main.head;
    rt.notePath = path;
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
    // The text on screen; with `expectedId`, only if that doc is the one on screen (else null), so
    // Python can never file one note's text under another.
    getText: (expectedId = null) => (expectedId === null || expectedId === docId ? view.state.doc.toString() : null),
    // Show tab `id`: its parked state if it has one, else a fresh state made from `text`.
    showDoc(id, text, path = "") {
      rt.notePath = path; // before the state swap: widgets built next read it
      if (id === docId) return;
      park();
      clearTimeout(timer);
      timer = null;
      let state = parked.get(id);
      if (state) {
        parked.delete(id);
        // mode/theme may have changed while this tab was parked (plain text has no mode)
        const effects = [
          themeSlot.reconfigure(themeFacet.of(currentTheme)),
          optionsSlot.reconfigure(optionsExt(currentOptions)),
        ];
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
      rt.notePath = path;
      if (docId !== -1 && isPlainPath(path) !== isPlainDoc()) {
        // renamed across .md <-> .txt: the note changes kind, so rebuild its state in place
        replaceText(view.state.doc.toString(), docId, path, true);
        return;
      }
      view.dispatch({ effects: refreshEffect.of(null) });
    },
    // `keepCaret`: an outside change was reloaded into the note on screen; stay where the user was.
    setText(text, id = docId, path = rt.notePath, keepCaret = false) {
      replaceText(text, id, path, keepCaret);
    },
    // The same note is open in the other editor of a split and changed there: take its text as a
    // minimal change that stays out of this side's undo history and is not reported back.
    syncText(id, text) {
      const spec = (state) => {
        const old = state.doc.toString();
        if (old === text) return null;
        const max = Math.min(old.length, text.length);
        let a = 0;
        while (a < max && old.charCodeAt(a) === text.charCodeAt(a)) a++;
        let b = 0;
        while (b < max - a && old.charCodeAt(old.length - 1 - b) === text.charCodeAt(text.length - 1 - b)) b++;
        return {
          changes: { from: a, to: old.length - b, insert: text.slice(a, text.length - b) },
          annotations: [Transaction.addToHistory.of(false), mirrored.of(true)],
        };
      };
      if (id === docId) {
        const s = spec(view.state);
        if (s) view.dispatch(s);
        return;
      }
      const state = parked.get(id);
      const s = state && spec(state);
      if (s) parked.set(id, state.update(s).state);
    },
    // Find (and replace) in the note on screen: CodeMirror's search panel.
    openSearch(replace = false, query = "") {
      openSearch(view, replace, query);
    },
    // The tab was closed: forget its parked state.
    closeDoc(id) {
      parked.delete(id);
      if (id === docId) {
        // the tab on screen was closed: report any typing not yet sent (Python drops it if the
        // tab is gone), then show an empty, unowned document so nothing is parked for it
        flush();
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
    // An AI answer typed into the note at `pos` as it arrives (see stream.js).
    streamBegin(id, pos) {
      streamBegin(view, id, pos, docId);
    },
    streamAppend(id, text) {
      return streamAppend(view, id, text, docId);
    },
    streamEnd(id) {
      streamEnd(view, id);
      flush();
    },
    // The selected text (for the AI): {from, to, text} in UTF-16 offsets, from == to when empty.
    getSelection() {
      const r = view.state.selection.main;
      return { from: r.from, to: r.to, text: view.state.sliceDoc(r.from, r.to), docId };
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
    // Put the caret on 1-based `line` and bring it to the top of the view. Focus first: the
    // caret position (status bar, outline) is only reported while the editor has focus.
    gotoLine(line) {
      const doc = view.state.doc;
      const pos = doc.line(Math.max(1, Math.min(line, doc.lines))).from;
      view.focus();
      view.dispatch({
        selection: { anchor: pos },
        effects: EditorView.scrollIntoView(pos, { y: "start", yMargin: 24 }),
      });
    },
    insertAtCursor(text) {
      view.dispatch(view.state.replaceSelection(text), { userEvent: "input.paste", scrollIntoView: true });
      flush();
    },
    setOptions(o) {
      currentOptions = { ...currentOptions, ...o };
      view.dispatch({ effects: optionsSlot.reconfigure(optionsExt(currentOptions)) });
      // page view just came on: a caret inside the (now hidden) properties moves below them
      view.dispatch({ selection: view.state.selection });
    },
    // Python's answer to a `print_layout` request: the print page to lay out (page view).
    printLayoutReady(seq, url) {
      printLayoutReady(view, seq, url);
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
