// State shared between the editor API (index.js) and widgets: which note is on screen.
// One editor per page, so a module-level holder is enough. Widgets read `notePath` to build
// image URLs (`/_pp/asset?note=...`); Python sets it on every note/tab switch and rename.
// `known`: normalised names of the notes wikilinks can point at (Python's `link_keys`), or null
// while unknown; used only to style links to missing notes.
export const editorContext = { notePath: "", known: null };

// Same rule as Python's `links.norm_name`, minus slashes at the ends.
export const normNote = (name) => name.trim().toLowerCase().replace(/\.(md|txt)$/, "").replace(/^\/+|\/+$/g, "");
