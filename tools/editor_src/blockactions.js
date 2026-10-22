// The copy button on code, math and diagram blocks. One click copies the block's source to the
// clipboard and tells Python to attach it to the chat (JS only captures; Python decides).
import { WidgetType } from "@codemirror/view";
import { EditorView } from "@codemirror/view";
import { rtOf } from "./context.js";

// Line icons come from the page (window.ppIconSvg, static/icons.js): one style app-wide.
const ICON = {
  copy: () => window.ppIconSvg?.("copy", "s") ?? "",
  done: () => window.ppIconSvg?.("check", "s") ?? "",
};

export function copyButton(kind, lang, text) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "pp-blockcopy";
  btn.dataset.tip = "Copy, and add to the chat";
  btn.setAttribute("aria-label", btn.dataset.tip);
  btn.innerHTML = ICON.copy();
  // never let the editor see the press: it would move the caret into the block and reveal it
  for (const type of ["mousedown", "pointerdown"]) {
    btn.addEventListener(type, (e) => {
      e.preventDefault();
      e.stopPropagation();
    });
  }
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      navigator.clipboard?.writeText(text);
    } catch (_) {
      /* the chat attachment still happens */
    }
    const view = EditorView.findFromDOM(btn.closest(".cm-editor"));
    if (view) rtOf(view.state).emit("block_to_chat", { docId: rtOf(view.state).getDocId(), kind, lang, text });
    btn.innerHTML = ICON.done();
    btn.classList.add("pp-blockcopy-done");
    setTimeout(() => {
      btn.innerHTML = ICON.copy();
      btn.classList.remove("pp-blockcopy-done");
    }, 1200);
  });
  return btn;
}

// Sits at the start of a code block's first line, positioned in the block's top-right corner by CSS.
export class CodeCopyWidget extends WidgetType {
  constructor(kind, lang, text) {
    super();
    this.kind = kind;
    this.lang = lang;
    this.text = text;
  }
  eq(other) {
    return other.kind === this.kind && other.lang === this.lang && other.text === this.text;
  }
  toDOM() {
    const wrap = document.createElement("span");
    wrap.className = "pp-blockcopy-wrap";
    wrap.appendChild(copyButton(this.kind, this.lang, this.text));
    return wrap;
  }
  ignoreEvent() {
    return true;
  }
}
