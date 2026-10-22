#!/usr/bin/env bash
# Bundles the CodeMirror 6 editor (tools/editor_src) with esbuild into
# paper_pile/gui/static/vendor/. Dev-only: end users never need Node; the output is committed.
# Code splitting keeps mermaid (large) in a lazy chunk that loads on the first diagram.
set -euo pipefail
cd "$(dirname "$0")/editor_src"
npm ci --no-audit --no-fund
node check_sync.mjs  # the editor's grammar must agree with the Python parser
out=../../paper_pile/gui/static/vendor
rm -rf "$out/pp-editor"
mkdir -p "$out/pp-editor" "$out/katex"
# two entries: the editor, and the print page's layout (print.js); they share chunks
npx esbuild index.js print.js --bundle --splitting --format=esm --minify --target=es2022 \
  --entry-names=[name] --chunk-names=chunks/[name]-[hash] --outdir="$out/pp-editor"
cp node_modules/katex/dist/katex.min.css "$out/katex/"
rm -rf "$out/katex/fonts" && cp -r node_modules/katex/dist/fonts "$out/katex/fonts"
# Lucide line icons: one JSON file read by paper_pile/gui/icons.py (no CDN)
node build_icons.mjs
echo "built $out/pp-editor/"
