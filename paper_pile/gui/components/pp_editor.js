// Thin Vue wrapper around the vendored CM6 bundle (tools/editor_src -> static/vendor/pp-editor).
// Renders and captures only; Python decides what every event means.
import { createEditor } from "pp-editor";

export default {
  template: "<div class='pp-editor'></div>",
  props: {
    initialText: { type: String, default: "" },
    mode: { type: String, default: "live" },
    theme: { type: String, default: "light" },
    imageUploadUrl: { type: String, default: null },
    linkTarget: { type: String, default: "python" },
    options: { type: Object, default: () => ({}) },
  },
  data() {
    return {
      // Server calls can arrive before mounted() has built the editor.
      ready: new Promise((resolve) => {
        this.resolveReady = resolve;
      }),
    };
  },
  mounted() {
    this.api = createEditor(this.$el, {
      doc: this.initialText,
      mode: this.mode,
      theme: this.theme,
      imageUploadUrl: this.imageUploadUrl,
      linkTarget: this.linkTarget,
      options: this.options,
      emit: (name, payload) => this.$emit(name, payload),
    });
    this.resolveReady(this.api);
  },
  beforeUnmount() {
    this.api?.destroy();
  },
  methods: {
    async getText(expectedId) {
      return (await this.ready).getText(expectedId ?? null);
    },
    async setText(text, docId, path, keepCaret) {
      (await this.ready).setText(text, docId, path, keepCaret);
    },
    async showDoc(docId, text, path) {
      (await this.ready).showDoc(docId, text, path);
    },
    async setPath(path) {
      (await this.ready).setPath(path);
    },
    async closeDoc(docId) {
      (await this.ready).closeDoc(docId);
    },
    async applyChanges(docId, changes, expected, cursor) {
      return (await this.ready).applyChanges(docId, changes, expected, cursor ?? null);
    },
    async streamBegin(id, pos) {
      (await this.ready).streamBegin(id, pos);
      return true;
    },
    async streamAppend(id, text) {
      return (await this.ready).streamAppend(id, text);
    },
    async streamEnd(id) {
      (await this.ready).streamEnd(id);
    },
    async getSelection() {
      return (await this.ready).getSelection();
    },
    async focusTableCell(row, col, from) {
      (await this.ready).focusTableCell(row, col, from ?? null);
    },
    async setSlashResults(seq, groups) {
      (await this.ready).setSlashResults(seq, groups);
    },
    async setKnownNotes(names) {
      (await this.ready).setKnownNotes(names);
    },
    async gotoLine(line) {
      (await this.ready).gotoLine(line);
    },
    async insertAtCursor(text) {
      (await this.ready).insertAtCursor(text);
    },
    async setOptions(options) {
      (await this.ready).setOptions(options);
    },
    async setMode(mode) {
      (await this.ready).setMode(mode);
    },
    async setTheme(theme) {
      (await this.ready).setTheme(theme);
    },
    async pickImage() {
      (await this.ready).pickImage();
    },
    async focus() {
      (await this.ready).focus();
    },
    async syncText(docId, text) {
      (await this.ready).syncText(docId, text);
    },
    async openSearch(replace) {
      (await this.ready).openSearch(replace);
    },
    async printLayoutReady(seq, url) {
      (await this.ready).printLayoutReady(seq, url);
    },
  },
};
