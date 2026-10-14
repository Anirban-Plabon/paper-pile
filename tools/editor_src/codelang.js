// Syntax highlighting inside fenced code blocks. A curated set of languages, each loaded lazily
// (esbuild splits every `import()` into its own chunk), so the main bundle stays small and a
// language is only fetched when a note actually contains a block in it.
import { LanguageDescription, StreamLanguage } from "@codemirror/language";

const lang = (name, alias, load) => LanguageDescription.of({ name, alias, load });
const legacy = (name, alias, loadMode) =>
  lang(name, alias, async () => StreamLanguage.define(await loadMode()));

export const codeLanguages = [
  lang("JavaScript", ["js", "mjs", "cjs", "jsx", "javascript"], () =>
    import("@codemirror/lang-javascript").then((m) => m.javascript({ jsx: true })),
  ),
  lang("TypeScript", ["ts", "tsx", "typescript"], () =>
    import("@codemirror/lang-javascript").then((m) => m.javascript({ typescript: true, jsx: true })),
  ),
  lang("Python", ["py", "python", "python3"], () => import("@codemirror/lang-python").then((m) => m.python())),
  lang("JSON", ["json", "jsonc"], () => import("@codemirror/lang-json").then((m) => m.json())),
  lang("HTML", ["html", "htm", "xhtml"], () => import("@codemirror/lang-html").then((m) => m.html())),
  lang("CSS", ["css"], () => import("@codemirror/lang-css").then((m) => m.css())),
  lang("SQL", ["sql"], () => import("@codemirror/lang-sql").then((m) => m.sql())),
  lang("Rust", ["rs", "rust"], () => import("@codemirror/lang-rust").then((m) => m.rust())),
  lang("C++", ["c", "cpp", "c++", "cc", "cxx", "h", "hpp"], () => import("@codemirror/lang-cpp").then((m) => m.cpp())),
  lang("Java", ["java"], () => import("@codemirror/lang-java").then((m) => m.java())),
  lang("Go", ["go", "golang"], () => import("@codemirror/lang-go").then((m) => m.go())),
  lang("YAML", ["yaml", "yml"], () => import("@codemirror/lang-yaml").then((m) => m.yaml())),
  legacy("Shell", ["sh", "bash", "zsh", "shell", "console"], () =>
    import("@codemirror/legacy-modes/mode/shell").then((m) => m.shell),
  ),
  legacy("TOML", ["toml"], () => import("@codemirror/legacy-modes/mode/toml").then((m) => m.toml)),
  legacy("Diff", ["diff", "patch"], () => import("@codemirror/legacy-modes/mode/diff").then((m) => m.diff)),
];
