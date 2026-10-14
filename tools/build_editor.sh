#!/usr/bin/env bash
# Bundles the CodeMirror 6 editor (tools/editor_src) with esbuild into
# paper_pile/gui/static/vendor/. Dev-only: end users never need Node; the output is committed.
set -euo pipefail
cd "$(dirname "$0")/editor_src"
npm ci --no-audit --no-fund
out=../../paper_pile/gui/static/vendor
mkdir -p "$out/pp-editor" "$out/katex"
npx esbuild index.js --bundle --format=esm --minify --target=es2022 \
  --outfile="$out/pp-editor/index.js"
cp node_modules/katex/dist/katex.min.css "$out/katex/"
rm -rf "$out/katex/fonts" && cp -r node_modules/katex/dist/fonts "$out/katex/fonts"
echo "built $out/pp-editor/index.js"
