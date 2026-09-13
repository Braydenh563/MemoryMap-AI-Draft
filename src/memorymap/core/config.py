"""Paths + user preferences for the whole app.

Why a single class: every part of the app must agree on where the
database lives and what the user has chosen (build plan §4). `deps.py`
creates exactly ONE instance of this at startup; nothing else should
construct it.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any

from dotenv import load_dotenv

from memorymap.core.atomic_io import atomic_write_json

# Defaults for every user-changeable preference. Stored as data in one
# place so the future Preferences screen has one list to show.
DEFAULT_PREFERENCES: dict[str, Any] = {
    "chat_model": "llama3.2",  # any installed Ollama model
    "embedding_backend": "sentence-transformers",  # or "ollama"
    "embedding_model": "nomic-embed-text",  # only used when backend == "ollama"
    "recycle_bin_days": 30,
    # Where a generated export (graph PNG, chat export, whiteboard PNG, see
    # routes_files.py's save_generated_file) is written. Empty means the
    # default, `data_dir/exports`; validated at save time (PUT /preferences),
    # not at export time, so a bad path is a rejected preference rather than
    # a lost file. Asked for directly, alongside the "Open exports folder"
    # button: "a configurable save location for exported images."
    "export_save_dir": "",
    # Semantic search relevance (search_manager.py). Defaults match that
    # module's own MIN_SIMILARITY/RELATIVE_Z_MARGIN constants, kept here
    # too, as plain values rather than an import, so Settings -> Preferences
    # can offer a real "reset to default" without importing search_manager
    # into config.py.
    "search_min_similarity": 0.25,
    "search_relative_z_margin": 0.5,
    # The user's IANA timezone, e.g. "Australia/Brisbane". Reported by the
    # browser on startup, because the browser is the only thing that knows
    # where the person actually is, the server may well be running in UTC
    # (a container, a NAS), and "remind me in ten minutes" resolved against
    # the wrong clock lands hours out. Empty means "fall back to the server's
    # own zone", which is correct for the ordinary case of both on one laptop.
    "timezone": "",
    # Web search is the one feature that leaves the machine, so it is off
    # until asked for, and which engine answers is the user's choice rather
    # than something inferred from whether a SearXNG address happens to be
    # filled in. See `search/websearch.PROVIDERS`.
    "web_search_enabled": False,
    # Asked for directly, alongside the Windows installer: since a release
    # only ships when someone remembers to tag one, nothing ever told a
    # person running an installed build that a newer version existed. The
    # only other opt-in network call in the app, off by default for the
    # same reason web_search_enabled is: "100% offline" (Settings -> About)
    # has to stay true until someone deliberately switches it off, not
    # something the app quietly does anyway for a good reason. Checks
    # GitHub's own releases API for the latest tag; nothing about the
    # notebook itself is ever sent.
    "update_check_enabled": False,
    # Separate from update_check_enabled on purpose: "tell me a new version
    # exists" and "download and run an installer without me clicking
    # anything in a browser" are different sizes of consequence, asked for
    # directly ("the option to turn auto update off entirely"), with its own
    # switch rather than folding it into the check preference, so someone
    # can want the notification without ever wanting the second part. Off by
    # default for the same reason the check itself is: this is opt-in, not
    # opt-out, the first time.
    "auto_update_enabled": False,
    # "stable" (tagged GitHub releases) or "main" (asked for directly: track
    # the main branch and update on every push to it). "main" is accepted as
    # a real, storable choice, the Settings toggle isn't fake, but
    # routes_update.py's own check honestly reports it as not yet available
    # for the GitHub-releases flow rather than pretending to find updates
    # that don't exist: that would need a second release pipeline (a rolling
    # nightly build published on every main-branch push) this repo does not
    # have yet, and building that blind, unreviewed, was judged a larger and
    # riskier undertaking than the rest of this feature, see HANDOVER.md.
    #
    # This literal value only ever applies to a packaged (frozen) Windows
    # install: ConfigManager._load_preferences overrides it to "main" for
    # every other install type before merging in whatever the user has
    # actually saved, since a source checkout already tracks main for real
    # via start.sh/start.bat's own `git pull` on every launch.
    "update_channel": "stable",
    # Bring the user's own SearXNG up with the app. Off by default: starting a
    # container is not something a local-first app does unasked.
    "searxng_autostart": False,
    "searxng_url": "",
    "search_provider": "auto",
    # Which dialect the chat backend speaks (§6). "ollama" is the native
    # `/api` shape; "openai" is `/v1/chat/completions`, which is what LM
    # Studio, llama.cpp, Jan and vLLM all serve, one setting covers all of
    # them, because the only thing that differs between them is the URL.
    "llm_provider": "ollama",
    # Empty means "the default for that provider", OLLAMA_URL for Ollama,
    # LM Studio's port for the OpenAI shape. Stored rather than derived so
    # switching provider and back doesn't forget a custom address.
    "llm_base_url": "",
    # Only ever needed by a hosted gateway; local servers ignore it. Kept out
    # of the support bundle by the same redaction that hides other secrets.
    "llm_api_key": "",
    # How much effort a chat turn is worth by default (§11): "quick", "normal"
    # or "detailed". One dial over the reply cap, the temperature, the thinking
    # toggle and a length hint, see `ai/presets.py`. "normal" reproduces the
    # behaviour that predates presets exactly, so upgrading changes nothing
    # until someone chooses otherwise.
    "response_mode": "normal",
    # Keep the AI on this machine. ON by default, and the default is the point:
    # "100% offline, on your machine" is a promise the app keeps rather than
    # one it reminds you that you are breaking. With this on, a backend address
    # that is not local or LAN is refused outright, see
    # `core.security.check_backend_url`. Turning it off is a deliberate act
    # with a visible switch, for someone who genuinely wants a hosted API.
    "local_only_ai": True,
    # --- the background librarian (§39) ---------------------------------------
    # Off by default and deliberately so: it runs the agent against the whole
    # notebook with nobody watching, which is a thing to opt into rather than
    # discover.
    "autonomous_tasks_enabled": False,
    "auto_tag_enabled": True,
    "auto_link_enabled": True,
    "auto_dedupe_enabled": True,
    # ROADMAP.md item 34. Off by default like the other three, and for the
    # same reason: but also because unlike tag/link/dedupe, this one adds a
    # whole new kind of thing to the notebook (an entity) rather than
    # changing an existing note, which deserves an even more deliberate opt-in.
    "auto_entities_enabled": False,
    # ROADMAP.md item 31. Off by default for the same reason as entities
    # above: this one makes a judgement call about which notes count as
    # "forgotten" rather than performing a request the user already made
    # (tag/link/dedupe are all reactions to a note's own content).
    "auto_stale_review_enabled": False,
    # ANALYSIS.md §60 item 2, the one real feature gap the odysseus read
    # found: nothing in this app turns an offhand mention in ordinary chat
    # into a filed note. Off by default, and this is the *most* deliberate
    # opt-in of the five: the other four react to notes the user wrote, and
    # this one decides on its own that something said in passing was worth
    # keeping. It writes drafts rather than notes for the same reason, see
    # `ai/passive_capture.py`.
    "auto_capture_enabled": False,
    "autonomous_tasks_interval_hours": 6,
    #: Skip the expensive extras, similarity edges on the graph, the
    #: background pass: on a laptop running off its battery.
    "battery_efficient_mode": False,
    #: Let background work use the (smaller, faster) utility model instead of
    #: tying up the chat model. Off means everything uses the chat model.
    "smart_model_routing_enabled": True,
    # How long a session can be idle before the user must log in again.
    "session_idle_ttl_minutes": 720,
    #: The desktop launcher's console window (start.bat/start-desktop.bat
    #: open one; the packaged installer's build has none to show at all).
    #: "Dev view" (console visible, True) is the default a fresh install
    #: starts on: asked for directly, reversing an earlier default in this
    #: same app: "dev view is the default on install and the user will be
    #: presented with a popup option to change it just after install."
    #: "User view" (False) is the one that hides it, genuinely never
    #: creates a console at all when the app supports that (see
    #: __main__.py's pythonw.exe relaunch), rather than trying to hide one
    #: that already exists. Read by __main__.py before the window opens,
    #: and kept in sync with the tray's own live toggle and Settings.
    "show_console_on_startup": True,
    #: Whether the first-run "Dev view or User view?" prompt has already
    #: been shown, so it asks exactly once per install rather than on every
    #: launch. Distinct from show_console_on_startup itself so a later
    #: change via Settings/tray doesn't make the intro reappear.
    "console_view_intro_seen": False,
}


def _default_data_dir() -> str:
    """Where notes live when nothing else says otherwise.

    `"data"` (relative to the current directory) is right for every way this
    app has run until now: cloned from git, `./start.sh`'d, or run from a
    source checkout in tests, the working directory is always the repo, and
    "data" next to it is obvious and easy to find.

    A PyInstaller-frozen, installed build breaks that assumption twice over.
    `sys.frozen` distinguishes it from every case above (never true running
    from source, so this can't change behaviour for the existing git-clone
    workflow or the test suite at all). And an installed app's own folder is
    Program Files, or wherever else it happens to run from, not writable by
    a standard Windows account, and not something a reinstall or an update
    should be trusted to leave alone. The OS-standard per-user data location
    is both writable and survives a reinstall; an explicit
    `MEMORYMAP_DATA_DIR` always overrides this regardless of how the app is
    running.
    """
    if not getattr(sys, "frozen", False):
        return "data"
    if sys.platform == "win32":
        base = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return str(Path(base) / "MemoryMap AI")


class ConfigManager:
    """Knows the app's folders, files, and saved preferences."""

    def __init__(self, data_dir: str | os.PathLike[str] | None = None) -> None:
        # .env lets a user relocate their data without touching code.
        load_dotenv()
        self.data_dir = Path(
            data_dir or os.getenv("MEMORYMAP_DATA_DIR") or _default_data_dir()
        ).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_dir / "memorymap.db"
        self.preferences_path = self.data_dir / "preferences.json"
        # Attached files live next to the data dir, so wiping
        # one without the other can't happen by accident.
        self.uploads_dir = self.data_dir / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

        self._preferences = self._load_preferences()

    def _load_preferences(self) -> dict[str, Any]:
        """Merge saved preferences over the defaults.

        A missing or corrupt preferences file must never stop the app
        from starting: we just fall back to defaults.
        """
        prefs = dict(DEFAULT_PREFERENCES)
        # A source checkout (git clone + start.sh/start.bat) already auto-
        # updates on every launch via `git pull` on whatever branch is
        # checked out: that IS tracking main, unconditionally, before this
        # preference is ever read. Defaulting such an install to "stable"
        # would point its *other* update path (routes_update.py's GitHub-
        # releases check) at a channel that install has no way to actually
        # apply anyway (can_auto_apply requires a frozen Windows build), so
        # it would just silently do nothing useful. A packaged Windows
        # install has the opposite situation, no git pull, no main branch
        # to track: so it keeps "stable", the one channel it can act on.
        # Overridden below by whatever the user has actually saved, the
        # moment they have ever touched the setting themselves.
        prefs["update_channel"] = "stable" if getattr(sys, "frozen", False) else "main"
        if self.preferences_path.exists():
            try:
                prefs.update(json.loads(self.preferences_path.read_text()))
            except (OSError, json.JSONDecodeError) as exc:
                # Starting on defaults is the right behaviour; doing it
                # silently is not. Every setting the user has ever chosen has
                # just reverted, and without this line the only clue is that
                # the app "forgot" everything.
                logging.getLogger("memorymap.config").warning(
                    "couldn't read %s (%s): starting from the default "
                    "preferences; your saved settings are not lost unless "
                    "something writes over the file",
                    self.preferences_path.name,
                    type(exc).__name__,
                )
        return prefs

    def get_preference(self, key: str, default: Any = None) -> Any:
        return self._preferences.get(key, default)

    def all_preferences(self) -> dict[str, Any]:
        """Every setting, as a copy, for the support bundle to redact.

        A copy rather than the live dict: a caller that only means to read
        should not be able to edit the app's settings by accident.
        """
        return dict(self._preferences)

    def set_preference(self, key: str, value: Any) -> None:
        """Change a preference and persist it to disk immediately,
        so a crash never loses a settings change.

        Written atomically (temp file + fsync + rename): `preferences.json`
        sits outside the database's own transaction boundary and holds
        `llm_api_key` plus every setting the user has ever changed, so a
        plain truncate-and-write here is the one place in the app where a
        `kill -9` or power loss mid-write could corrupt live state.
        """
        self._preferences[key] = value
        atomic_write_json(self.preferences_path, self._preferences)


def user_now(config: "ConfigManager") -> datetime:
    """Right now, on the user's own clock.

    Everything is *stored* in UTC, that part is not negotiable, since a
    notebook has to survive its owner changing timezone. But anything the AI
    reasons about ("in ten minutes", "tomorrow at 9", "what did I save today")
    has to be resolved against the wall clock the user is actually reading, or
    it silently lands hours out.

    Falls back to the server's local zone when no timezone has been reported,
    which is right for the ordinary case of app and browser on one machine.
    """
    name = str(config.get_preference("timezone", "") or "").strip()
    if name:
        try:
            return datetime.now(ZoneInfo(name))
        except (ZoneInfoNotFoundError, ValueError):
            # A stale or hand-edited zone name must never break the app.
            logging.getLogger("memorymap.config").warning(
                "unknown timezone %r in preferences; using the server's", name
            )
    return datetime.now(timezone.utc).astimezone()
