# Privacy and security

The whole app is built around one rule: **nothing leaves your machine
unless you explicitly ask it to.** The server binds to localhost, every
route except `/health` sits behind the unlock gate, and no asset is ever
loaded from a CDN.

For how to report a vulnerability, see [`SECURITY.md`](../SECURITY.md).
This page is about what the app does and why, not how to disclose a bug
in it.

## Is the AI itself local?

**Yes, and it is now enforced, not just intended.** Every chat and agent
request goes to a model server on your own machine, and **Settings →
Models → "Keep the AI on this machine"** is on by default: an address
that isn't on this computer or your own network is *refused*, not
warned about. That check runs both when you set the address and when
the app builds its client at startup, so a hand-edited
`preferences.json` or a restored backup can't quietly route your notes
somewhere else. Turning the lock off is a deliberate click, for people
who genuinely want a hosted API.

## What actually touches the network

Being precise about what "local" means here, since it's the whole
promise. Three things do touch the network, and none of them is your
notes:

| What | When | What goes out |
| --- | --- | --- |
| `ollama pull` | You download a model | The model name, to Ollama's registry |
| The embedding model | Once, on first use | A one-off download of `bge-small-en-v1.5` |
| Web search | Only if you turn it on | Your search words, never your notes |

Your notes, your questions, and everything the AI writes about them
stay on your machine in all three cases. Ollama's own hosted service
(`ollama.com`) would not be local, and the lock refuses it like any
other remote address.

## Web search: the one exception

Off until you turn it on in **Settings → Web search**. When it is on:

- only your search words leave the computer, never your notes;
- requests send an ordinary browser User-Agent rather than one naming
  this app, keep no cookies between searches, send no `Referer`, and set
  DNT and Sec-GPC;
- queries go by POST, so they stay out of request lines and access
  logs;
- tracking parameters (`utm_*`, `fbclid`, `gclid`, and the like) are
  stripped from result URLs before you ever see them;
- **your own [SearXNG](https://searxng.org) is the recommended engine**,
  and MemoryMap installs and runs it for you in one click: no Docker
  required, no account, no setup. The query then never leaves your own
  network at all. The default setting, *Automatic*, uses it whenever it
  is running and falls back to DuckDuckGo until you have one, so search
  works out of the box either way;
- the results panel says **which engine actually answered** each
  search, and what that meant for the query, so the choice you made in
  Settings is visible at the moment it applies rather than only where
  you set it.

**Opening a page** (the reader view, and the agent's `read_url` tool) is
address-checked on *every* redirect hop and then pinned to the address
that passed, so a page that answers "302 to 127.0.0.1" cannot turn
"open this link" into a probe of your own services. Only text comes
back: scripts, styles and page chrome are stripped server-side, so
nothing from a third-party page can execute anywhere in the app.

## Private notes

Encrypted at rest with a key wrapped by your password, and excluded
from search, the graph and every AI tool: the model cannot reach around
the front door. The key is derived with **scrypt** (n=2^15), a
deliberately slow, memory-hard function, so a copy of the database file
taken off the machine is not worth guessing at.

## The browser on your own machine is treated as untrusted too

Binding to localhost keeps the *network* out; it does nothing about a
page open in another tab, which can ask your browser to send requests
to `http://localhost:8000` on your behalf. This is how local dev servers
and Ollama itself have actually been attacked. So:

- requests that state an origin other than MemoryMap's own are
  **refused**, including before you have set a password, when there is
  otherwise nothing standing between a stray page and your new
  notebook;
- a strict **Content-Security-Policy** on every response allows scripts
  and styles only from the app itself, no inline code, and **no remote
  host at all**, which the "no asset from a CDN" rule above makes
  possible;
- **sessions expire**, after 12 hours unused, and 7 days regardless, and
  expiring forgets the private-note key, not just the token;
- **wrong passwords earn a growing wait**, so a four-character PIN
  cannot be guessed at speed;
- the SearXNG instance the app runs for you is published to
  `127.0.0.1` only, never the wider network.

`.github/workflows/codeql.yml` runs static security analysis on every
push and weekly.

## One notebook, one password

MemoryMap is single-user by design: one `users` row, one password,
everything on this machine. To keep separate notebooks, point the app
at a different data folder with `MEMORYMAP_DATA_DIR` rather than
creating a second account.

### If you forget the password

There is no reset link inside the app: one there would just be a way in
for anyone at the keyboard. Instead:

```
python -m memorymap --reset-password
```

It asks you to confirm, then clears the password so you can set a new
one. Two very different things happen to your notes, and the command
tells you which before you commit:

- **Ordinary notes are not encrypted** by your password. They are plain
  rows in SQLite and come back untouched.
- **Private notes are.** Their key is derived from the password, so
  without it nobody can decrypt them, including this command. The reset
  loses them, and it tells you how many you have first.

No backdoor was added, on purpose.
