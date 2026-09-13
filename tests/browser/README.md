# Driving the real app

Not part of `pytest`. These are the harness the Python suite cannot be: the
suite cannot see the DOM, and **every UI bug reported in this project so far
turned out to be different from what reading the code suggested.**

```bash
# 1. run the app (PYTHONPATH is required and is easy to forget)
PYTHONPATH=src MEMORYMAP_DATA_DIR=/tmp/appdata \
  .venv/bin/python -m uvicorn memorymap.api.app:create_app --factory --port 8781 &

# 2. drive it
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node tests/browser/audit.js
```

**Restart the server after any Python change.** A stale uvicorn is why a
correct fix appeared not to work twice in one session.

## `drive.js`

Launches Chromium, does first-run setup, unlocks, and dismisses the onboarding
overlay: then hands you a page. Every probe is ten lines on top of it:

```js
const { open } = require("./drive");
const { browser, page } = await open({ width: 1440, height: 900 });
```

## `audit.js`

Walks every `fixed`/`sticky` element on all seven tabs and reports anything
whose bottom passes the status bar. Worth re-running after any layout change, 
it is what found the chat sidebar sitting 17px underneath it, on a screen where
nothing looked wrong.

## Two things worth knowing before you write a probe

- **`elementFromPoint` is how you prove a stacking bug.** "Is the menu on top?"
  is not answerable from a screenshot. Ask the browser what is actually at
  three points inside the menu, that is how a menu whose items clicked the
  *wrong note's buttons* was found, which a screenshot showed as merely untidy.
- **A module-scope `let` is not a property of `window`.** Inside
  `page.evaluate`, `graphNodesRef` works as a bare identifier;
  `window.graphNodesRef` is `undefined` and will quietly tell you the graph is
  empty.
