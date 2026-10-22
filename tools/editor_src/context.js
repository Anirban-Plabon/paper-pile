import { Facet } from "@codemirror/state";

// Per editor (a page can hold two, side by side): which note it shows, how it talks to Python and
// which doc id it is on. Every state an editor builds carries its runtime object through this
// facet, so widgets and plugins reach their own editor's runtime with `rtOf(view.state)`.
// Widgets read `notePath` to build image URLs (`/_pp/asset?note=...`); Python sets it on every
// note/tab switch and rename.
const NO_RUNTIME = { notePath: "", emit: () => {}, getDocId: () => 0 };
export const runtimeFacet = Facet.define({ combine: (values) => values[0] ?? NO_RUNTIME });
export const rtOf = (state) => state.facet(runtimeFacet);

// Shared by every editor on the page. `known`: normalised names of the notes wikilinks can point
// at (Python's `link_keys`), or null while unknown; used only to style links to missing notes.
export const editorContext = { known: null };

// Same rule as Python's `links.norm_name`, minus slashes at the ends.
export const normNote = (name) => name.trim().toLowerCase().replace(/\.(md|txt)$/, "").replace(/^\/+|\/+$/g, "");

// A widget grew or shrank after it was drawn (an embed's text, an image, a diagram arrived): make
// CodeMirror measure the content again. `requestMeasure()` alone is not enough when the content
// already fills the pane (its size does not change, so nothing tells CM a block got taller), and
// the editor then maps clicks and the caret with the old height. `mustMeasureContent` is internal
// to @codemirror/view (pinned in package.json); without it this still asks for a measure.
export function measureAgain(view) {
  if (view.viewState && "mustMeasureContent" in view.viewState) view.viewState.mustMeasureContent = true;
  view.requestMeasure();
}
