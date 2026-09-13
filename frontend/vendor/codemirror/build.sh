#!/usr/bin/env bash
# Rebuilds codemirror.min.js from the versions pinned in package.json.
# Run from this directory with node and npm on PATH; the app has no build
# step, so this is run by hand when a CodeMirror upgrade is wanted, and the
# result is committed. Nothing in the app or the tests depends on it.
#
# One patch, and the reason for it. CodeMirror injects its stylesheets through
# style-mod, which uses a constructed stylesheet (`document.adoptedStyleSheets`)
# only for a ShadowRoot and a `<style>` tag for a Document. The app's CSP is
# `style-src 'self'` with no nonce and no 'unsafe-inline', so that tag is
# refused and the editor would render with no styling at all, silently
# (CLAUDE.md, section 6, shape 4). A constructed stylesheet is not subject to
# style-src, and it is exactly how Settings > Appearance applies custom CSS
# (tests/test_security_boundaries.py). The one-line patch below makes
# style-mod take the adopted-sheet branch for a Document too. It fails the
# build if the line it expects has moved, so an upgrade cannot lose it.
set -euo pipefail
cd "$(dirname "$0")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp package.json entry.js "$work"/
cd "$work"
npm install --no-audit --no-fund --silent
src=node_modules/style-mod/src/style-mod.js
grep -q 'if (!root.head && root.adoptedStyleSheets && win.CSSStyleSheet) {' "$src" \
  || { echo "style-mod changed: the adopted-stylesheet patch no longer applies" >&2; exit 1; }
sed -i 's/if (!root.head && root.adoptedStyleSheets && win.CSSStyleSheet) {/if (root.adoptedStyleSheets \&\& win.CSSStyleSheet) {/' "$src"
npx esbuild entry.js --bundle --format=iife --global-name=CM6 --minify \
  --target=es2020 --legal-comments=none --outfile=codemirror.min.js
{
  echo "/*! CodeMirror 6, MIT licence, see LICENSE beside this file. Built by build.sh from package.json. */"
  cat codemirror.min.js
} > "$OLDPWD/codemirror.min.js"
echo "wrote $(du -h "$OLDPWD/codemirror.min.js" | cut -f1) codemirror.min.js"
