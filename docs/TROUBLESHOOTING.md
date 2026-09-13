# Troubleshooting

## Windows: "torch_xpu.dll ... WinError 127" and search falls back to keywords

You'll see a banner like *"The specified procedure could not be found.
Error loading ...\torch\lib\torch_xpu.dll"*. The app is fine: this is
torch's default Windows wheel shipping an Intel GPU library that can't
load on your machine. MemoryMap only needs the **CPU** build.

**Fresh installs are already handled.** `requirements.txt` installs the
CPU-only torch on Windows.

**Already installed the broken wheel?** Swap it:

```
pip uninstall -y torch
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Then restart the app.

**Or go torch-free.** In **Settings → Models**, download
`nomic-embed-text` and set it as the embedding backend. It runs entirely
through Ollama, needs no torch at all, and your notes re-index
automatically.

## Web search returns nothing, or says DuckDuckGo is rate-limiting

Scraping DuckDuckGo gets rate-limited, and the app now says so rather
than showing an empty panel. Waiting a few minutes usually clears it.

The real fix is your own SearXNG instance: **Settings → Web search →
Start SearXNG**. MemoryMap installs it (Docker if you have it, otherwise
a virtualenv of its own), configures the JSON API, and points search at
it.

## SearXNG won't start, or starts and never answers

Everything you need is on **Settings → Web search**:

- **The port line** says whether port 8888 is free, held by a working
  SearXNG (fine, MemoryMap will just use it), or held by something else
  (the only case you have to go and fix).
- **What SearXNG reported** is a fold with the instance's own output: the
  actual traceback, not a guess. It's kept in `data/searxng/searxng.log`
  too.
- **Reinstall** deletes the downloaded copy and its virtualenv and
  builds a fresh one. This is the fix when an install was interrupted, or
  the Python it was built against has since been upgraded: it *looks*
  installed and dies instantly on start. Your `settings.yml` is kept, it
  holds the instance's secret key and any edits you made, and it isn't
  what breaks.

## The header pill or dot says the AI is off

That's amber, not red, and it's a supported state: the app is built to
degrade. Capture and keyword search work exactly as normal; only
auto-filing and chat answers need Ollama. Red is reserved for a model
that failed to load or a server that can't be reached, rarer, since it
needs Ollama to be *reachable but failing* rather than simply not
running.

## Something looks wrong and I want to see what happened

**Settings → Logs** is a live view of what the app is doing, without
hunting for a terminal. It streams as things happen, follows the newest
records (and pauses the moment you scroll up to read something), filters
by level, source or text, and folds tracebacks open under the record
they belong to. Server and browser logs appear in one time-ordered list,
so an error in the page and the request behind it sit next to each
other. It's memory-only, nothing is written to disk, in keeping with the
rest of the privacy posture, and it says so when the buffer has had to
drop older records rather than leaving a silent gap.

**Got an error you want to send someone?** Every record has its own copy
button that takes the traceback with it, and an opened traceback has a
**Copy traceback** button too, so one error is one click, not a filter
plus a careful drag. The error count on the **Logs** menu item is
clickable and opens the screen already filtered to errors. **Copy all**
copies what's on screen and relabels itself ("Copy 12 shown") whenever a
filter is hiding something.

**Reporting a bug?** The **Support bundle** button on the same screen
saves a zip with the log, your settings, and app and model status: the
things a bug report needs. Nothing is sent anywhere, the file goes to
your disk and it's your choice whether to share it. Free-text settings
are listed by name and length only (your display name appears as `str,
31 chars`), and no note, document, chat or reminder content is included.
There's a README inside describing exactly what it holds.
