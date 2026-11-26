// Markdown marks written in pairs (user 2026-11-26), the same in the note editor, the chat boxes
// (chat, Ask box) and table cells:
//   * _ ~ `   typed where a word can start: the closing mark is written too (`*|*`); typing the
//             same mark again in the empty pair makes it double (`**|**`, not for `); a space in
//             an empty pair drops the closer (`* ` starts a list); a third mark in an empty
//             double pair drops the closers (`***` is a rule)
//   ==        a second = after a lone one: `==|==` (highlight)
//   ( [ {     written in pairs before a space, the end of the line or a closing bracket
//   closing   a typed closer that is already next to the caret is stepped over
//   selected  typing a mark or bracket over selected words wraps them (they stay selected)
//   Backspace between an empty pair removes both marks.
// Inside code (a fence, inline code; the editor also knows math) only brackets pair.
//
// `typed` / `back` only decide; the editor (tools/editor_src/autoclose.js) and the text fields
// below apply what they return: replace [selStart - back, selEnd + fwd] with `text`, then select
// [start + a, start + b] where start = selStart - back.
(function () {
  const BRACKETS = { "(": ")", "[": "]", "{": "}" };
  const CLOSERS = new Set([")", "]", "}"]);
  const MARKS = new Set(["*", "_", "~", "`"]);
  const WRAP = new Set(["*", "_", "~", "`", "=", "$", "(", "[", "{"]);
  const SYMMETRIC = new Set(["*", "_", "~", "`", "=", "$"]);

  const isWord = (c) => !!c && /[\p{L}\p{N}]/u.test(c);
  const isSpace = (c) => !c || /\s/.test(c);
  // after the caret: a pair may open (nothing, a space, punctuation that ends a phrase)
  const free = (c) => isSpace(c) || CLOSERS.has(c) || /[.,;:!?'"]/.test(c);
  const lead = (s, ch) => {
    let n = 0;
    while (n < s.length && s[n] === ch) n++;
    return n;
  };
  const trail = (s, ch) => {
    let n = 0;
    while (n < s.length && s[s.length - 1 - n] === ch) n++;
    return n;
  };
  const unmatched = (before, open, close) => {
    let depth = 0;
    for (const c of before) {
      if (c === open) depth++;
      else if (c === close && depth > 0) depth--;
    }
    return depth;
  };
  const put = (text, a, b = a, back = 0, fwd = 0) => ({ back, fwd, text, a, b });

  // `before` / `after`: the line's text before the selection and after it; `sel`: the selected
  // text; `ch`: the typed character; `code`: the caret is in code (marks are plain there).
  function typed(before, after, sel, ch, code = false) {
    if (typeof ch !== "string" || ch.length !== 1) return null;
    const next = after[0] || "";
    const prev = before[before.length - 1] || "";
    if (sel) {
      if (!WRAP.has(ch) || (code && !BRACKETS[ch])) return null;
      if (SYMMETRIC.has(ch) && sel.includes("\n")) return null; // marks do not span lines
      if (ch === "=") return put(`==${sel}==`, 2, 2 + sel.length);
      return put(ch + sel + (BRACKETS[ch] || ch), 1, 1 + sel.length);
    }
    if (BRACKETS[ch]) return free(next) ? put(ch + BRACKETS[ch], 1) : null;
    if (CLOSERS.has(ch)) {
      const open = Object.keys(BRACKETS).find((k) => BRACKETS[k] === ch);
      return next === ch && unmatched(before, open, ch) > 0 ? put(ch, 1, 1, 0, 1) : null;
    }
    if (ch === " ") {
      // an empty pair of marks: a mark followed by a space is no emphasis (`* item`, `a == b`)
      const m = prev;
      if (!(MARKS.has(m) || m === "=")) return null;
      const p = trail(before, m);
      return lead(after, m) === p ? put(" ", 1, 1, 0, p) : null;
    }
    if (!SYMMETRIC.has(ch) || code) return null;
    const p = trail(before, ch);
    const n = lead(after, ch);
    const opener = isSpace(before[before.length - 1 - p] || "") || !isWord(before[before.length - 1 - p]);
    if (p > 0 && n === p && opener && ch !== "`" && ch !== "$" && ch !== "=") {
      // an empty pair: `*|*` -> `**|**`; `**|**` + * -> `***` (a rule, or bold italic by hand)
      return p === 1 ? put(ch + ch, 1) : put(ch, 1, 1, 0, n);
    }
    if (next === ch && (ch === "`" || ch === "$" || !isSpace(prev))) return put(ch, 1, 1, 0, 1); // the closer
    if (ch === "=") {
      // `=` + `=` where a word can start: the highlight pair
      const lone = p === 1 && !isWord(before[before.length - 2] || "") && before[before.length - 2] !== "=";
      return lone && n === 0 && free(next) ? put("===", 1) : null;
    }
    if (ch === "$" || p > 0) return null; // $ is money as often as maths: only wrapped / stepped over
    return free(next) && !isWord(prev) ? put(ch + ch, 1) : null;
  }

  // Backspace with the caret between an empty pair: both marks go.
  function back(before, after) {
    const c = before[before.length - 1];
    if (!c) return null;
    if (BRACKETS[c]) return after[0] === BRACKETS[c] ? put("", 0, 0, 1, 1) : null;
    if (!SYMMETRIC.has(c) || after[0] !== c) return null;
    return trail(before, c) === lead(after, c) ? put("", 0, 0, 1, 1) : null;
  }

  // is `before` (all the text before the caret) inside code: an open ``` fence, or an open `
  // on its line?
  function inCode(before) {
    const lines = before.split("\n");
    const fences = lines.slice(0, -1).filter((l) => /^\s*(```|~~~)/.test(l)).length;
    if (fences % 2 === 1) return true;
    return (lines[lines.length - 1].match(/`/g) || []).length % 2 === 1;
  }

  const api = { typed, back, inCode };
  if (typeof module !== "undefined" && module.exports) module.exports = api; // tests (node)
  if (typeof window === "undefined") return;
  window.ppPairs = api;

  // ---- text fields: the chat box, the Ask box, a table cell being typed in ----------------------
  const FIELDS = ".pp-chat-input textarea, input.pp-table-input";
  document.addEventListener(
    "keydown",
    (e) => {
      const t = e.target;
      if (!t || !t.matches || !t.matches(FIELDS)) return;
      if (e.defaultPrevented || e.isComposing || e.ctrlKey || e.metaKey || e.altKey) return;
      const v = t.value;
      const s = t.selectionStart;
      const end = t.selectionEnd;
      if (s === null || end === null) return;
      const from = v.lastIndexOf("\n", s - 1) + 1;
      let to = v.indexOf("\n", end);
      if (to < 0) to = v.length;
      const before = v.slice(from, s);
      const after = v.slice(end, to);
      let r = null;
      if (e.key === "Backspace") r = s === end ? back(before, after) : null;
      else if (e.key.length === 1) r = typed(before, after, v.slice(s, end), e.key, e.key !== "`" && inCode(v.slice(0, s)));
      if (!r) return;
      e.preventDefault();
      const start = s - r.back;
      t.setSelectionRange(start, end + r.fwd);
      // the browser's own edit: one undo step, and an input event for the field's owner
      if (r.text) document.execCommand("insertText", false, r.text);
      else document.execCommand("delete");
      t.setSelectionRange(start + r.a, start + r.b);
      // Vue writes the field's value back after the input event, which puts the caret at the
      // end: place it again once that is done (only if nothing else changed the text)
      const value = t.value;
      setTimeout(() => {
        if (t.value === value) t.setSelectionRange(start + r.a, start + r.b);
      }, 0);
    },
    true,
  );
})();
