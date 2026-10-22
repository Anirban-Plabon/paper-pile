// `![[note]]` / `![[note#heading]]` alone on a line: the other note's content shown inside this one.
// Python finds the note and renders it (`/_pp/embed`); a click anywhere on the block opens that
// note in a tab. The block is read-only: arrow into it to see (and edit) the `![[...]]` text.
import { WidgetType } from "@codemirror/view";
import { measureAgain, rtOf } from "./context.js";

export class EmbedWidget extends WidgetType {
  constructor(note, heading, source) {
    super();
    this.note = note;
    this.heading = heading;
    this.source = source;
  }
  eq(other) {
    return other.note === this.note && other.heading === this.heading && other.source === this.source;
  }
  toDOM(view) {
    const wrap = document.createElement("div");
    wrap.className = "pp-embed";
    const head = document.createElement("div");
    head.className = "pp-embed-title";
    head.textContent = this.heading ? `${this.note} › ${this.heading}` : this.note;
    const body = document.createElement("div");
    body.className = "pp-embed-body";
    wrap.append(head, body);
    const query = new URLSearchParams({ note: this.source, target: this.note, heading: this.heading });
    fetch(`/_pp/embed?${query}`)
      .then((r) => r.json())
      .then((j) => {
        head.textContent = j.title || head.textContent;
        if (j.message) {
          wrap.classList.add("pp-embed-missing");
          body.textContent = j.message;
        } else {
          body.innerHTML = j.html; // server-rendered, raw HTML in notes is escaped there
        }
        measureAgain(view);
      })
      .catch(() => {
        body.textContent = "Could not load the note";
      });
    wrap.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const link = e.target.closest ? e.target.closest("a.wikilink") : null;
      const note = link ? link.getAttribute("data-note") : this.note;
      const heading = link ? link.getAttribute("data-heading") || "" : this.heading;
      rtOf(view.state).emit("wikilink", { note, heading });
    });
    wrap.addEventListener("click", (e) => {
      if (e.target.closest && e.target.closest("a")) e.preventDefault(); // links inside are inert
    });
    return wrap;
  }
  ignoreEvent() {
    return true;
  }
}
