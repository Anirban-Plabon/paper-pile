// The copy button on code, math and diagram blocks. One click copies the block's source to the
// clipboard and tells Python to attach it to the chat (JS only captures; Python decides).
import { WidgetType } from "@codemirror/view";
import { editorContext } from "./context.js";

const ICON = {
  copy: '<svg viewBox="0 0 24 24" width="15" height="15"><path fill="currentColor" d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11v14z"/></svg>',
  done: '<svg viewBox="0 0 24 24" width="15" height="15"><path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>',
};

export function copyButton(kind, lang, text) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "pp-blockcopy";
  btn.title = "Copy, and add to the chat";
  btn.setAttribute("aria-label", btn.title);
  btn.innerHTML = ICON.copy;
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
    editorContext.emit("block_to_chat", { docId: editorContext.getDocId(), kind, lang, text });
    btn.innerHTML = ICON.done;
    btn.classList.add("pp-blockcopy-done");
    setTimeout(() => {
      btn.innerHTML = ICON.copy;
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
