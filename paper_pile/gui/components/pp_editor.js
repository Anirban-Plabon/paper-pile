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
      emit: (name, payload) => this.$emit(name, payload),
    });
    this.resolveReady(this.api);
  },
  beforeUnmount() {
    this.api?.destroy();
  },
  methods: {
    async getText() {
      return (await this.ready).getText();
    },
    async setText(text, docId) {
      (await this.ready).setText(text, docId);
    },
    async insertAtCursor(text) {
      (await this.ready).insertAtCursor(text);
    },
    async setMode(mode) {
      (await this.ready).setMode(mode);
    },
    async setTheme(theme) {
      (await this.ready).setTheme(theme);
    },
    async focus() {
      (await this.ready).focus();
    },
  },
};
