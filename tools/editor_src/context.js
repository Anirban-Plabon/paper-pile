// State shared between the editor API (index.js) and widgets: which note is on screen.
// One editor per page, so a module-level holder is enough. Widgets read `notePath` to build
// image URLs (`/_pp/asset?note=...`); Python sets it on every note/tab switch and rename.
export const editorContext = { notePath: "" };
