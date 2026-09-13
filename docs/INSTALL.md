# Installing and running MemoryMap AI

Three ways in, pick whichever fits: the **Windows installer** (no terminal),
the **launcher script** (any OS, one command), or **manual setup** (if you'd
rather manage the virtual environment yourself).

- [Windows installer](#windows-installer)
- [Launcher script (Windows / macOS / Linux)](#launcher-script)
- [Manual setup](#manual-setup)
- [Running it](#running-it)
- [Updating](#updating)
- [Uninstalling](#uninstalling)

## Windows installer

The simplest way in on Windows, no terminal or Python install required:

1. Download the latest `MemoryMap-AI-Setup-*.exe` from
   [Releases](https://github.com/Braydenh563/MemoryMap-AI/releases).
2. Run it. **Windows will show a blue "Windows protected your PC" screen**:
   this build is not code-signed yet (a certificate costs money every year,
   and is not worth it before there is a real user base to justify it), so
   Windows flags it as from an unrecognised publisher. Click **More info**,
   then **Run anyway**. The installer only copies the app into your own
   user folder: nothing system-wide, no admin prompt.
3. It installs a Start Menu shortcut (and, optionally, a desktop one) and
   offers to launch the app when it finishes.

Your notes live in `%APPDATA%\MemoryMap AI`, untouched by an update or
reinstall, and left alone if you uninstall the app itself. Voice dictation,
search-by-meaning, and the desktop window are all still installed the same
way afterwards: **Settings → Packages**.

**The installer is a snapshot, not a subscription.** It does not phone home
or patch itself: a release built today is exactly what you will be running
a year from now, unless you download a newer one by hand. Turn on
**Settings → About → "Check GitHub for a newer version"** (off by default,
the same "100% offline unless you ask" rule as web search) and the app
tells you when a newer release exists. It only ever checks; it never
downloads or installs anything on its own.

**No terminal window.** The desktop app runs its server in the background
and puts an icon in the system tray. Closing the window minimises it there
rather than quitting, and the tray menu (Open / View Logs / Restart / Quit)
is how you get it back or shut it down for real. If Settings → Packages
shows the desktop extra as installed but no tray icon appears, the tray
piece (`pystray` + `Pillow`) did not come along with it: reinstall the
desktop extra from that same panel.

Prefer to build it yourself, or want it on macOS or Linux? See below:
`start.sh`/`start.bat` work on all three, today.

## Launcher script

**You need Python 3.11 or newer.** That is all it takes to get running. If
you have never used a terminal before, follow the numbered steps below
exactly: every grey box is a command to copy and paste, one line at a
time.

### 1. Open a terminal

- **Windows:** press `Win`, type `PowerShell`, press Enter.
- **macOS:** press `Cmd`+`Space`, type `Terminal`, press Enter.
- **Linux:** usually `Ctrl`+`Alt`+`T`, or find "Terminal" in your app menu.

### 2. Get the app onto your machine

Pick whichever of these two you find easier: both end up in the same
place, a folder called `MemoryMap-AI`.

**With git** (if you are not sure, you probably do not have it: skip to
the next option):

```
cd ~
git clone https://github.com/Braydenh563/MemoryMap-AI.git
cd MemoryMap-AI
```

**Without git**: download instead:

1. Open <https://github.com/Braydenh563/MemoryMap-AI> in your browser.
2. Click the green **Code** button, then **Download ZIP**.
3. Unzip it wherever you like (double-click the downloaded file on
   Windows/macOS).
4. Back in your terminal, `cd` into the folder you just unzipped. The
   easiest way: type `cd ` (with a trailing space), then **drag the unzipped
   folder from your file browser into the terminal window** (most terminals
   fill in the correct path for you), then press Enter.

Either way, you should now be sitting *inside* the `MemoryMap-AI` folder.
`ls` (macOS/Linux) or `dir` (Windows) should list `start.sh`,
`start-desktop.sh`, `start.bat`, `start-desktop.bat` and this repo's
`README.md` among the files.

### 3. Run the launcher

From inside that same folder:

- **Windows**: double-click **`start-desktop.bat`** in File Explorer, or
  type `start-desktop.bat` and press Enter in the terminal you are already
  in. This opens the app in its own window rather than a browser tab.
  Prefer it unless you specifically want a browser tab (`start.bat`, no
  arguments, does that instead).
- **macOS / Linux**: run **`./start-desktop.sh`** for the app's own window,
  or `./start.sh` for a browser tab.

The launcher builds the virtual environment, installs everything, starts the
app and opens <http://localhost:8000> (or <http://127.0.0.1:8000>). The
first run takes a few minutes; after that it goes straight to launching, and
only re-installs when `requirements.txt` changes.

**Losing track of the folder is the single most common stumbling block
here**, so every launch prints exactly where it is running from and the
command to get back, right above the browser opening:

```
Installed at: /home/you/MemoryMap-AI
Next time:    open a terminal there and run ./start.sh again
```

That line is your answer any time you cannot remember where you put it:
scroll up in that terminal window, or re-run the launcher from the same
place you ran it the first time.

Prefer a browser tab over the app's own window? `start.bat`/`./start.sh`
with no arguments does that instead.

### Launcher options

Both launchers take the same flags, in the same order, so an instruction
works whichever one you are on. `./start.sh --help` or `start.bat --help`
prints this list, and the path to your notes with it.

| Flag | What it does |
| --- | --- |
| `desktop` | Start in the app's own window instead of a browser tab |
| `--port N` | Serve on port N instead of 8000 |
| `--no-browser` | Start the server but do not open a browser |
| `--no-update` | Skip the update check and run the code that is here now |
| `--reinstall` | Rebuild the virtual environment from scratch, then start |
| `--doctor` | Check this machine, print a table and exit |
| `--logs` | Open the launcher log folder and exit |
| `--shortcut` | Create a desktop shortcut for this launcher and exit |
| `--version` | Print the version and exit |
| `--help` | Show the list and exit |

**If it does not start, run `--doctor` first.** It prints one row per thing
that can stop a launch, with a tick or a cross and, for a cross, one line
saying what to do: Python's version and path, whether the virtual
environment can import what the server needs, free disk where your notes
are, whether the port is free or already has MemoryMap on it, whether the
update remote answers, your model provider, where your notes are and how
big, and the last error from the previous run's log. It exits 0 when
everything checks out and 1 when something needs fixing, and it works on a
machine where the app itself will not start.

Every run also writes `<your notes folder>/logs/launcher-<date>.log`, ten
days of them, so "it did not start" can be answered by reading something.
`--logs` opens that folder.

## Manual setup

If you would rather not use the launcher:

```
# 1. A virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Dependencies, then the app itself
pip install -r requirements.txt
pip install -e .                 # the dot matters - it means "this folder"

# 3. Optional: relocate your data or point at a different Ollama
cp .env.example .env             # Windows: copy .env.example .env
```

Optional extras, installed only if you want them:

```
pip install pywebview        # the --desktop window
pip install pystray Pillow   # tray icon for the desktop window above
pip install faster-whisper   # local speech-to-text for the 🎙 buttons
pip install pytesseract Pillow   # OCR text on uploaded images (Library -> Image Gallery search)
```

The OCR extra also needs the `tesseract` **system binary** on your PATH:
`pip` cannot install that part for you, since it is not a Python package.

```
# Debian/Ubuntu
sudo apt install tesseract-ocr
# macOS
brew install tesseract
# Windows: https://github.com/UB-Mannheim/tesseract/wiki
```

Without it, uploaded images just do not get searchable text. Nothing else
about the app is affected, and no upload ever fails because of it.

## Running it

```
python -m memorymap             # a browser tab at http://localhost:8000
python -m memorymap --desktop   # the same app in its own window
```

Without `pywebview`, `--desktop` falls back to a browser tab rather than
failing.

On first run you choose a password (bcrypt-hashed, stays on your machine).
The interactive API explorer lives at <http://localhost:8000/docs>.

## Updating

Same command: `start.sh`/`start.bat` pull the latest code and reinstall
dependencies automatically every time you run them, before the app starts.

**Schema upgrades happen automatically at startup**: new columns are added
in place, your notes are never touched. You do not need to delete
`data/memorymap.db` when updating.

## Uninstalling

Run `./uninstall.sh` (or `uninstall.bat`). It removes the virtual
environment the launcher built, and the caches that came with it, and leaves
your notes untouched unless you explicitly pass `--delete-data`. Start with
`--dry-run`: it lists everything that would go, with a size against each,
and changes nothing.

| Flag | What it does |
| --- | --- |
| `--dry-run` | List what would be removed, with sizes, and change nothing |
| `--export PATH` | Write your notes to PATH as a Markdown zip first |
| `--delete-data` | Also delete your notes and `.env`, asked for separately |
| `--shortcuts` | Also remove the desktop shortcut `--shortcut` created |
| `--yes` | Skip the "remove the virtual environment?" prompts |
| `--help` | Show the list and exit |

Two things it will not do. It stops rather than deleting under a MemoryMap
that is still running, so close the app first. And `--delete-data` asks you
to type DELETE at its own prompt, which `--yes` does not skip.

`--export` writes the same Markdown zip the Settings download does, one
`.md` file per note with its metadata in the frontmatter, so you can take
your notes with you before removing anything. The same export is available
without the uninstaller: `python -m memorymap --export ~/my-notes.zip`.

Optional extras (dictation, the desktop window, search-by-meaning) can be
installed, reinstalled or removed individually and without touching a
terminal at all, from **Settings → Packages**.
