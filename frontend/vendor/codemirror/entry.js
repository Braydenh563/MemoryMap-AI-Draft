// The CodeMirror 6 surface MemoryMap vendors: one IIFE, one global (`CM6`),
// every module the editor needs and nothing it does not. Rebuilt by
// frontend/vendor/codemirror/build.sh; versions pinned in package.json there.
export * as state from "@codemirror/state";
export * as view from "@codemirror/view";
export * as commands from "@codemirror/commands";
export * as search from "@codemirror/search";
export * as language from "@codemirror/language";
export * as autocomplete from "@codemirror/autocomplete";
export * as lint from "@codemirror/lint";
export * as markdown from "@codemirror/lang-markdown";
export * as javascript from "@codemirror/lang-javascript";
export * as python from "@codemirror/lang-python";
export * as css from "@codemirror/lang-css";
export * as html from "@codemirror/lang-html";
export * as json from "@codemirror/lang-json";
export * as yaml from "@codemirror/lang-yaml";
export * as highlight from "@lezer/highlight";
export { shell } from "@codemirror/legacy-modes/mode/shell";
export { sql, standardSQL } from "@codemirror/legacy-modes/mode/sql";
export { toml } from "@codemirror/legacy-modes/mode/toml";
export { go } from "@codemirror/legacy-modes/mode/go";
export { rust } from "@codemirror/legacy-modes/mode/rust";
export { c, cpp, csharp, java, kotlin } from "@codemirror/legacy-modes/mode/clike";
export { ruby } from "@codemirror/legacy-modes/mode/ruby";
export { xml } from "@codemirror/legacy-modes/mode/xml";
export { diff } from "@codemirror/legacy-modes/mode/diff";
export { dockerFile } from "@codemirror/legacy-modes/mode/dockerfile";
// Added 2026-09-09 for three of the file types `GET /documents/file-types`
// already offers and the editor could not highlight. Measured cost for the
// three together: +7,658 bytes raw, +2,476 gzipped, under 1% of the bundle.
// `properties` is the INI mode; CodeMirror has no mode called `ini`.
export { swift } from "@codemirror/legacy-modes/mode/swift";
export { r } from "@codemirror/legacy-modes/mode/r";
export { properties } from "@codemirror/legacy-modes/mode/properties";
// **PHP is deliberately absent**, and the number is the reason:
// `@codemirror/lang-php` is not a legacy mode but a full Lezer grammar that
// also pulls in lang-html (PHP is embedded in HTML), and it costs +98,144
// bytes raw and +28,563 gzipped on its own, 10.6% of this bundle for one
// language. DOCUMENTS_PLAN records the decision.
