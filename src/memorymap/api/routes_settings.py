"""Preferences, audit-log viewer, data export, and recycle-bin
maintenance.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import importlib
import os
import platform
import re
import sys
import tempfile
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap import __version__
from memorymap.ai import budget as run_budget
from memorymap.ai import presets, skills
from memorymap.core import deps, embedmodels, events, extras, logbuffer
from memorymap.core.database import AuditLog, Category, Entry, EntryLink, utcnow
from memorymap.core.deps import get_session
from memorymap.entry import importer, manager
from memorymap.search import searxng_manager, websearch

router = APIRouter(tags=["settings"])

#: Routes in this module that must work **before** the notebook is unlocked.
#: Included in `app.py` without the `locked` dependency, deliberately and
#: only for the client-error sink below, see its docstring.
open_router = APIRouter(tags=["settings"])

# Preferences the user may change from the UI, a deliberate allowlist
# so a stray request can't scribble on model settings (those have their
# own validated endpoints in routes_models).
class TemplateItem(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    content: str = Field(max_length=2000)
    # Optional one-liner shown in the Settings list and as the entry-template
    # option's tooltip: same shape as SkillItem.description below.
    description: str = Field(default="", max_length=200)


# Kept in sync by hand with BUILTIN_TEMPLATES in app.js. The templates
# themselves (their markdown bodies) only ever lived in the frontend, Wave
# B never gave the server a reason to know their content, but the NAMES
# have to be known here too, or a custom template called "Journal" would
# save fine and only collide with the shipped one client-side, in whichever
# session happens to render the <select> next.
BUILTIN_TEMPLATE_NAMES = {"Journal", "Recipe", "Contact", "Meeting"}


class PersonaItem(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    prompt: str = Field(min_length=1, max_length=2000)


class CustomThemeItem(BaseModel):
    """One saved look: the appearance settings the browser would have applied.

    `values` is deliberately a free-form string map rather than a model with a
    field per setting. The appearance controls live entirely in the frontend
    and are the only thing that knows what a key means, pinning the list here
    would mean a saved theme could not carry a setting added later without a
    matching server change, for a value the server never reads.

    It is *bounded* rather than trusted: a cap on how many keys, and on how
    long each is, so a stored theme cannot become an arbitrary blob in the
    preferences file.
    """

    name: str = Field(min_length=1, max_length=30)
    values: dict[str, str] = Field(default_factory=dict)
    preset: str = Field(default="", max_length=40)

    @field_validator("values")
    @classmethod
    def _bounded(cls, values: dict) -> dict:
        if len(values) > 40:
            raise ValueError("a theme carries at most 40 settings")
        for key, value in values.items():
            if len(str(key)) > 40 or len(str(value)) > 200:
                raise ValueError("theme settings must be short strings")
        return values


class SkillInput(BaseModel):
    """One value a skill asks for before it runs (§21)."""

    name: str = Field(min_length=1, max_length=24)
    label: str = Field(default="", max_length=60)
    required: bool = True
    default: str = Field(default="", max_length=skills.MAX_INPUT_VALUE)


class SkillItem(BaseModel):
    """A named, repeatable job over the notebook (§21).

    `prompt` alone is the whole of a pre-rebuild skill, and still valid, the
    steps, tools and inputs are what make it a job rather than a saved
    sentence. The real rules live in `ai/skills.normalise`, which the route
    applies as well, so the tool path and the settings path can't drift.
    """

    name: str = Field(min_length=1, max_length=skills.MAX_NAME)
    prompt: str = Field(min_length=1, max_length=skills.MAX_PROMPT)
    description: str = Field(default="", max_length=skills.MAX_DESCRIPTION)
    # When this skill applies. What makes it findable by the model rather than
    # only by the person who remembered writing it (§33).
    when_to_use: str = Field(default="", max_length=skills.MAX_WHEN)
    steps: list[str] = Field(default_factory=list, max_length=skills.MAX_STEPS)
    tools: list[str] = Field(default_factory=list, max_length=skills.MAX_TOOLS)
    inputs: list[SkillInput] = Field(default_factory=list, max_length=skills.MAX_INPUTS)
    # Pre-rebuild flag the UI still reads; derived on save from steps/tools.
    useTools: bool = False  # noqa: N815  # the stored key, kept for old skills


class PreferencesBody(BaseModel):
    recycle_bin_days: int | None = Field(default=None, ge=1, le=365)
    # 0 means "keep everything", which is the default, see
    # `autonomous.purge_old_conversations` for why this is opt-in rather than
    # on with a sensible number. `ge=0`, not `ge=1`, so switching it back off
    # is expressible.
    conversation_retention_days: int | None = Field(default=None, ge=0, le=3650)
    # Empty string resets to the default (data_dir/exports). Validated in
    # update_preferences (_validated_export_dir): must be an absolute,
    # existing, writable directory, checked at save time rather than at
    # export time when a bad path means a lost file.
    export_save_dir: str | None = Field(default=None, max_length=500)
    search_min_similarity: float | None = Field(default=None, ge=0, le=1)
    search_relative_z_margin: float | None = Field(default=None, ge=0, le=3)
    communication_style: Literal["friendly", "concise", "detailed"] | None = None
    #: **The writing checker's own two settings.** Both belong on the server
    #: rather than in `localStorage`, and the reason is the same for each: a
    #: dictionary you have to rebuild when you clear your browser data is a
    #: dictionary nobody adds to, and a spelling variant that differs between
    #: the desktop shell and a browser tab is a checker that contradicts
    #: itself. Asked for directly: *"adding to dictionary (a way to manage that
    #: dictionary), auto correct spelling (us, uk spelling etc)"*.
    #:
    #: Bounded, because this is a list a client writes to freely: 2,000 words
    #: is far more than anyone adds by hand and small enough that the whole
    #: list can be sent to the editor on load, which is what lets the check run
    #: on every keystroke without a request.
    writing_dictionary: list[str] | None = Field(default=None, max_length=2000)
    #: `off` means "do not have an opinion about which side of the Atlantic
    #: this document is on", the honest default for a notebook that does not
    #: know who is writing in it.
    spelling_variant: Literal["off", "uk", "us"] | None = None
    # Display name for the dashboard greeting (empty string clears it).
    display_name: str | None = Field(default=None, max_length=60)
    # Optional context about the user for the librarian.
    # profile_enabled is the opt-out switch; the delete button in the UI
    # simply saves an empty string.
    user_profile: str | None = Field(default=None, max_length=2000)
    profile_enabled: bool | None = None
    # Capture templates: user-defined prefills for the note box.
    custom_templates: list[TemplateItem] | None = Field(default=None, max_length=20)
    # Personas: custom system prompts + which one is active.
    personas: list[PersonaItem] | None = Field(default=None, max_length=20)
    active_persona: str | None = Field(default=None, max_length=40)
    # Independent override for just the dashboard greeting, empty clears it
    # back to "same as active_persona", the same clear-with-empty-string
    # convention display_name above already uses.
    dashboard_persona: str | None = Field(default=None, max_length=40)
    # Saved appearance looks. Server-side rather than in the browser because a
    # theme someone built by hand is a thing they would be upset to lose to a
    # cleared cache: and here it rides along in the daily backup too.
    custom_themes: list[CustomThemeItem] | None = Field(default=None, max_length=20)
    # Dashboard layout: widget order + hidden widgets.
    dashboard_layout: "DashboardLayout | None" = None
    # User-defined skills, and whether the chat AI may use tools.
    skills: list[SkillItem] | None = Field(default=None, max_length=30)
    tools_enabled: bool | None = None
    # The local-AI lock (§33). On by default; see core.config.
    local_only_ai: bool | None = None
    # Which tools each turn is offered: "auto" reads the question and sends
    # what it plausibly needs (§11a: the schemas are most of the per-round
    # cost); "all" sends the whole registry, as it always did.
    tool_focus: Literal["auto", "all"] | None = None
    #: Small-model mode for skill runs: each step is offered only the tools its
    #: own contract names, plus a worked example of the call. "auto" decides
    #: from the chat model's name (see `model_manager.parameter_count`, which
    #: answers "no idea" for a name with no size in it, and no idea means
    #: off). Declared here for the reason the comments above give: a field
    #: Pydantic does not know about is silently dropped, so a setting that is
    #: never declared is a switch that never saves.
    small_model_mode: Literal["auto", "on", "off"] | None = None
    #: **What one skill run may spend** (Brief 13). A run is many turns and
    #: every one of them starts its own fresh round allowance, so the only
    #: bound on a run that goes wrong used to be how long the person was
    #: willing to watch it. Zero in either field means "no limit on this one",
    #: which is a real answer for a ten-step audit over four thousand notes on
    #: hardware somebody is happy to give an hour to.
    run_budget_tokens: int | None = Field(default=None, ge=0)
    run_budget_seconds: int | None = Field(default=None, ge=0)
    # The ONE feature that goes online, off unless the user opts in.
    web_search_enabled: bool | None = None
    # The other opt-in network call (Settings -> About): see core.config.
    update_check_enabled: bool | None = None
    # Separate switch: "notify me" vs. "download and run the installer
    # without asking each time", see core.config's own comment.
    auto_update_enabled: bool | None = None
    update_channel: Literal["stable", "main"] | None = None
    searxng_autostart: bool | None = None
    session_idle_ttl_minutes: int | None = Field(default=None, ge=1)
    # The desktop launcher's console window: see core.config's own comment.
    show_console_on_startup: bool | None = None
    # Whether the first-run Dev-view/User-view prompt has already been
    # shown. Missing from this model entirely was its own bug: a PUT for a
    # field Pydantic doesn't know about is silently dropped rather than
    # rejected, so the prompt would have recorded nothing and reappeared on
    # every single launch: caught live, before this ever shipped, by the
    # same round of testing that found show_console_on_startup missing from
    # GET /preferences.
    console_view_intro_seen: bool | None = None
    #: Whether the desktop window's X button hides to the tray (default) or
    #: quits. Declared here for the reason the comment above gives: a field
    #: Pydantic does not know about is silently dropped, so a setting that is
    #: never declared is a switch that never saves.
    close_to_tray: bool | None = None
    #: Which status-bar slots the user has switched off. **The list of what is
    #: hidden, not what is shown**, see `STATUS_SLOTS` in app.js: a slot added
    #: in a later version then appears by default for everyone, instead of
    #: being invisible to every user who ever opened that settings screen.
    status_bar_hidden: list[str] | None = None
    #: Opt-in, unlike status_bar_hidden above: a clock is not one of the
    #: permanent landmarks STATUS_SLOTS lists, so it defaults to off rather
    #: than appearing for everyone the moment this shipped. Asked for
    #: directly ("show the current time in the status bar").
    status_bar_clock: bool | None = None
    #: One-shot: the tray balloon explaining where the window went has been
    #: shown. Written by the launcher, not the browser, but declared so the
    #: value round-trips rather than being dropped by a later PUT.
    tray_hide_explained: bool | None = None

    # Optional self-hosted SearXNG instance; empty string = use DuckDuckGo.
    searxng_url: str | None = Field(default=None, max_length=200)
    # Which engine answers: "auto" | "searxng" | "duckduckgo". Validated
    # rather than free text, so a bad value is rejected at the door instead of
    # sitting in preferences quietly meaning "auto" forever.
    search_provider: str | None = None
    # "Remember what I chose" for the Quick/Normal/Detailed response-mode
    # picker (setResponseMode in app.js): was never declared here at all,
    # so the PUT it fires on every change returned 200 while silently
    # dropping the value; the dropdown looked like it saved (it updates its
    # own <select> client-side regardless) but reverted to presets.DEFAULT_MODE
    # on the very next reload.
    response_mode: str | None = None
    # Autonomous Tasks settings. These were declared twice, once here with
    # bare types and once above with the validated ones, and Pydantic silently
    # keeps the last definition, so the bounds below were the only ones that
    # ever applied. One copy, the validated one.
    autonomous_tasks_enabled: bool | None = None
    auto_tag_enabled: bool | None = None
    auto_link_enabled: bool | None = None
    auto_dedupe_enabled: bool | None = None
    # ROADMAP.md item 31's stale/orphaned-note review. Missing from here was
    # the same shape of bug Tier 1 item 4a already found and fixed for eight
    # other preferences: the Settings checkbox (#pref-auto-stale-review)
    # calls setPreference exactly like its tag/link/dedupe siblings, but
    # Pydantic silently drops any key this model doesn't declare: so every
    # PUT that turned the toggle on was a no-op the whole time, and the
    # autonomous pass could never actually pick up any candidates no matter
    # what the checkbox showed.
    auto_stale_review_enabled: bool | None = None
    #: ANALYSIS.md §60 item 2. Declared here as well as in the response and
    #: `_AUTONOMOUS_PREFS` below: the comment above this block records what
    #: happens when it is not: Pydantic drops the key, every PUT that turns it
    #: on is a silent no-op, and the checkbox shows a state the backend never
    #: had.
    auto_capture_enabled: bool | None = None
    autonomous_tasks_interval_hours: int | None = Field(default=None, ge=1, le=168)
    autonomous_tasks_model: str | None = Field(default=None, max_length=100)
    battery_efficient_mode: bool | None = None
    smart_model_routing_enabled: bool | None = None
    # Asked directly: a way to quiet toasts and the notifications panel for
    # background jobs, agent runs and general activity while a due reminder
    # still gets through either way.
    notifications_muted_except_reminders: bool | None = None
    #: Where the AI's own activity is announced: "toasts" (a passing notice
    #: *and* a row in the notifications centre, the behaviour this app has
    #: always had) or "centre" (the row only).
    #:
    #: Asked for directly: *"make an option for agent activity notifications to
    #: be hidden and not show up as toast notifications but somewhere else."*
    #: Distinct from `notifications_muted_except_reminders`, which is a
    #: blanket mute that also stops the row being recorded, this is about
    #: *where* an activity notice lands, not whether it happens.
    agent_activity_notices: str | None = Field(default=None, pattern="^(toasts|centre)$")
    # Agent tools the user has switched off (by tool name).
    disabled_tools: list[str] | None = Field(default=None, max_length=50)
    # Which faster-whisper model size the dictation buttons load. Read by
    # `routes_voice.py` since the feature shipped; nothing ever let a user set
    # it, so every install has silently run "base" regardless of the box's
    # speed or the length of what's being dictated.
    voice_model: Literal["tiny", "base", "small", "medium"] | None = None
    # The user's IANA timezone, reported by the browser at startup. Anything
    # the AI reasons about in time ("in 10 minutes", "tomorrow at 9") is
    # resolved against this, because the server may be running in UTC while
    # the person is not. Validated on the way in, an unknown zone name would
    # otherwise sit in preferences and silently fall back forever.
    timezone: str | None = Field(default=None, max_length=64)
    # The interface's own local state, theme, palette, corner rounding,
    # whether onboarding has been seen (§35E). A flat map of short strings,
    # deliberately: this is the browser's `localStorage` mirrored so that a
    # shell which does not persist it still remembers. Validated for *shape*
    # rather than for meaning, the keys are the frontend's business and it
    # would be worse to have the server reject a setting the UI has just added
    # than to store a key nobody reads.
    ui_state: dict[str, str] | None = None

    @field_validator("ui_state")
    @classmethod
    def _small_ui_state(cls, value: dict | None) -> dict | None:
        """A bounded map. Nothing here should ever be large, and a preference
        file that can be grown without limit from the browser is a way to fill
        a disk."""
        if value is None:
            return value
        if len(value) > 60:
            raise ValueError("Too many interface settings")
        for key, item in value.items():
            if len(str(key)) > 40 or len(str(item)) > 400:
                raise ValueError(f"Interface setting {key!r} is too long")
        return value

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        if not value:
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone {value!r}") from exc
        return value

    @field_validator("search_provider")
    @classmethod
    def _known_provider(cls, value: str | None) -> str | None:
        """Rejected at the door rather than normalised away, so a UI sending
        the wrong name finds out instead of silently getting "auto"."""
        if value is None:
            return value
        if value not in websearch.PROVIDERS:
            raise ValueError(
                f"Unknown search provider {value!r}: expected one of "
                + ", ".join(sorted(websearch.PROVIDERS))
            )
        return value

    @field_validator("response_mode")
    @classmethod
    def _known_response_mode(cls, value: str | None) -> str | None:
        """Same reasoning as `_known_provider` above: `_resolve_mode` would
        happily fall back to the default for a bad value at read time, which
        is right for a value already sitting in storage, but rejecting a
        bad one at the door means the picker finds out immediately rather
        than saving a typo that silently never takes effect."""
        if value is None:
            return value
        if value not in presets.MODES:
            raise ValueError(
                f"Unknown response mode {value!r}: expected one of "
                + ", ".join(sorted(presets.MODES))
            )
        return value

    # Named filters the user has saved from the Notes tab.
    saved_searches: list["SavedSearch"] | None = Field(default=None, max_length=30)


class SavedSearch(BaseModel):
    """A named filter, e.g. {"name": "This week's work", "query": "tag:work"}."""

    name: str = Field(min_length=1, max_length=40)
    query: str = Field(min_length=1, max_length=200)


#: **The cap has to be bigger than the catalogue, and it was not.**
#:
#: Found by measuring, not by reading: reordering a widget on the dashboard
#: produced `PUT /preferences 422` and nothing moved. `order` carries *every*
#: widget, visible and hidden, and the dashboard has grown past twenty of
#: them, so every save of a full layout was rejected outright. Nothing in the
#: UI said so (`saveDashLayout` swallows the failure to keep a dead preference
#: from breaking the page), which is why "a better way to manage and rearrange
#: widgets" was reported as a design problem: rearranging did not persist at
#: all.
#:
#: 64 rather than "the current number of widgets": a bound exists here to stop
#: a malformed request storing an unbounded list, not to enforce the
#: catalogue's size: and a limit that has to be raised every time a widget is
#: added is a limit that will be forgotten again. `tests/test_dashboard_layout_cap.py`
#: fails the build if the catalogue ever approaches it.
DASHBOARD_LAYOUT_MAX = 64


class DashboardLayout(BaseModel):
    order: list[str] = Field(default_factory=list, max_length=DASHBOARD_LAYOUT_MAX)
    hidden: list[str] = Field(default_factory=list, max_length=DASHBOARD_LAYOUT_MAX)
    # Widgets the user has set to span two grid columns.
    wide: list[str] = Field(default_factory=list, max_length=DASHBOARD_LAYOUT_MAX)
    # Older layouts stored the same thing as {"stats": "wide"}. Kept so a
    # layout saved before the switch still loads; the frontend folds it into
    # `wide` and writes the list form back on the next save.
    sizes: dict[str, str] = Field(default_factory=dict)


@router.get("/preferences")
def get_preferences() -> dict:
    config = deps.get_config()
    return {
        "recycle_bin_days": config.get_preference("recycle_bin_days", 30),
        "conversation_retention_days": config.get_preference("conversation_retention_days", 0),
        "export_save_dir": config.get_preference("export_save_dir", ""),
        "search_min_similarity": config.get_preference("search_min_similarity", 0.25),
        "search_relative_z_margin": config.get_preference("search_relative_z_margin", 0.5),
        "communication_style": config.get_preference("communication_style", "friendly"),
        "writing_dictionary": config.get_preference("writing_dictionary", []),
        "spelling_variant": config.get_preference("spelling_variant", "off"),
        "display_name": config.get_preference("display_name", ""),
        # Saved correctly and honoured correctly (routes_auth.py's three
        # idle-timeout checks all read it) but never once echoed back here, 
        # the same shape of bug Tier 1 item 4a already fixed for eight other
        # preferences. Settings → Account's timeout field showed its HTML
        # default on every reload no matter what had actually been saved and
        # was actually in effect, which reads as "my setting didn't save."
        "session_idle_ttl_minutes": config.get_preference("session_idle_ttl_minutes", 720),
        "user_profile": config.get_preference("user_profile", ""),
        "profile_enabled": config.get_preference("profile_enabled", False),
        "custom_templates": config.get_preference("custom_templates", []),
        "personas": config.get_preference("personas", []),
        "custom_themes": config.get_preference("custom_themes", []),
        "active_persona": config.get_preference("active_persona", "Librarian"),
        "dashboard_persona": config.get_preference("dashboard_persona", ""),
        "dashboard_layout": config.get_preference(
            "dashboard_layout", {"order": [], "hidden": []}
        ),
        "skills": config.get_preference("skills", []),
        "tools_enabled": config.get_preference("tools_enabled", True),
        "local_only_ai": config.get_preference("local_only_ai", True),
        "tool_focus": config.get_preference("tool_focus", "auto"),
        "small_model_mode": config.get_preference("small_model_mode", "auto"),
        "run_budget_tokens": config.get_preference(
            "run_budget_tokens", run_budget.DEFAULT_TOKENS
        ),
        "run_budget_seconds": config.get_preference(
            "run_budget_seconds", run_budget.DEFAULT_SECONDS
        ),
        "web_search_enabled": config.get_preference("web_search_enabled", False),
        "update_check_enabled": config.get_preference("update_check_enabled", False),
        "auto_update_enabled": config.get_preference("auto_update_enabled", False),
        "update_channel": config.get_preference("update_channel", "stable"),
        "searxng_url": config.get_preference("searxng_url", ""),
        "searxng_autostart": config.get_preference("searxng_autostart", False),
        "search_provider": websearch.normalise_provider(
            config.get_preference("search_provider", websearch.DEFAULT_PROVIDER)
        ),
        "response_mode": config.get_preference("response_mode", presets.DEFAULT_MODE),
        "disabled_tools": config.get_preference("disabled_tools", []),
        "voice_model": config.get_preference("voice_model", "base"),
        "saved_searches": config.get_preference("saved_searches", []),
        # Echoed back so the browser can tell whether the zone it just
        # detected is already the stored one, and skip a pointless write on
        # every startup.
        "timezone": config.get_preference("timezone", ""),
        # Everything the interface keeps in localStorage, the theme, the
        # palette, corner rounding, whether onboarding has been seen (§35E).
        #
        # **Reported as two bugs and it is one:** *"the theme resets to default
        # on every start"* and *"onboarding shows every time"*. Both were kept
        # in localStorage and nowhere else, and the desktop shell does not
        # reliably persist it: pywebview is a different browser with its own
        # profile, and if that profile is not stable across launches then every
        # setting stored there is a setting the app forgets.
        #
        # The browser still writes localStorage first: it is synchronous, it
        # works with the server unreachable, and it is what every existing
        # `appearancePref` read already goes through. This is the copy that
        # survives, seeded back on first load when the local one is empty.
        "ui_state": config.get_preference("ui_state", {}),
        # Reported (indirectly, this session): a preference that saves
        # correctly and is honoured correctly, `autonomous.py` and
        # `model_manager.py` both read these straight from storage, but
        # this response never echoed any of them back, so every Settings
        # checkbox bound to one of these showed unchecked again the moment
        # the page reloaded or the panel reopened, regardless of what was
        # actually saved. Defaults match the ones each reader already uses,
        # so a profile that never touched these sees the same value the
        # backend would have assumed anyway.
        "autonomous_tasks_enabled": config.get_preference("autonomous_tasks_enabled", False),
        "auto_tag_enabled": config.get_preference("auto_tag_enabled", True),
        "auto_link_enabled": config.get_preference("auto_link_enabled", True),
        "auto_dedupe_enabled": config.get_preference("auto_dedupe_enabled", True),
        "auto_stale_review_enabled": config.get_preference("auto_stale_review_enabled", False),
        "auto_capture_enabled": config.get_preference("auto_capture_enabled", False),
        "autonomous_tasks_interval_hours": config.get_preference(
            "autonomous_tasks_interval_hours", 6
        ),
        "autonomous_tasks_model": config.get_preference("autonomous_tasks_model", ""),
        "battery_efficient_mode": config.get_preference("battery_efficient_mode", False),
        "smart_model_routing_enabled": config.get_preference(
            "smart_model_routing_enabled", True
        ),
        "notifications_muted_except_reminders": config.get_preference(
            "notifications_muted_except_reminders", False
        ),
        "agent_activity_notices": config.get_preference("agent_activity_notices", "toasts"),
        # Same shape of bug as the autonomous-prefs block above, on the same
        # checkbox this session already restyled: PUT /preferences has always
        # accepted show_console_on_startup (PreferencesBody's own field), but
        # this response never echoed it back, so prefsCache.show_console_
        # on_startup was always undefined, the Settings checkbox always
        # rendered unchecked regardless of what was actually saved, and the
        # first-run Dev-view/User-view intro (console_view_intro_seen, gated
        # on this same response) would have shown on every single launch.
        "show_console_on_startup": config.get_preference("show_console_on_startup", True),
        "console_view_intro_seen": config.get_preference("console_view_intro_seen", False),
        # Default True, matching `_on_closing` in __main__.py: the two must
        # agree or the checkbox shows the opposite of what the window does.
        "close_to_tray": config.get_preference("close_to_tray", True),
        "status_bar_hidden": config.get_preference("status_bar_hidden", []),
        "status_bar_clock": config.get_preference("status_bar_clock", False),
    }


#: Preferences the autonomous loop reads at the top of each pass. Changing
#: any of these should take effect on the loop's next tick, not its next
#: *scheduled* tick, which could be hours away, so writing one of these
#: wakes the loop early instead of leaving it asleep on a stale value.
_AUTONOMOUS_PREFS = frozenset(
    {
        "autonomous_tasks_enabled",
        "battery_efficient_mode",
        "autonomous_tasks_interval_hours",
        "auto_tag_enabled",
        "auto_link_enabled",
        "auto_dedupe_enabled",
        "auto_stale_review_enabled",
        "auto_capture_enabled",
    }
)


#: Preference keys that never reach the audit log (Library → Activity).
#: Reported directly: "idk what the go is with all the 'Edited your
#: settings' stuff", a click that toggles a status-bar icon or drags a
#: corner-rounding slider produced the exact same "Edited your settings"
#: row as changing the model backend or the auto-lock timeout, so the one
#: feed meant to answer "what did I actually do" was mostly cosmetic noise
#: with the real changes buried in it. `ui_state` alone is most of that
#: noise: it is the interface's *entire* look (theme, palette, corners,
#: zoom, shadow, glass, motion, see its own docstring above) behind one
#: key, so every appearance tweak wrote a row. The rest here are one-shot
#: internal bookkeeping (`*_intro_seen`, `tray_hide_explained`) or the two
#: status-bar toggles (§ this session): never a change a person would
#: describe as "something I did", only as "how it looks/behaves".
#: `set_preference` still runs for all of them; only the audit row is
#: skipped, so nothing about what is saved or restored changes.
_QUIET_PREFERENCE_KEYS = frozenset(
    {
        "ui_state",
        "status_bar_hidden",
        "status_bar_clock",
        "console_view_intro_seen",
        "tray_hide_explained",
    }
)


@router.put("/preferences")
def update_preferences(
    body: PreferencesBody, session: Session = Depends(get_session)
) -> dict:
    config = deps.get_config()
    changed_keys = set()
    for key, value in body.model_dump(exclude_none=True).items():
        if key == "skills":
            # One validator for both ways in. A skill saved from the editor
            # goes through exactly what `save_skill` goes through, so a skill
            # the AI can write is a skill the UI can write, and neither can
            # store one that won't run.
            value = _validated_skills(value)
        if key == "custom_templates":
            value = _validated_templates(value)
        if key == "export_save_dir":
            value = _validated_export_dir(value)
        config.set_preference(key, value)
        changed_keys.add(key)
        if key in _QUIET_PREFERENCE_KEYS:
            continue
        # Don't copy profile text into the audit log, it's personal.
        detail = f"{key}=…" if key == "user_profile" else f"{key}={value}"
        manager.log_action(session, "edited", "preferences", detail=detail)
    session.commit()
    if changed_keys & _AUTONOMOUS_PREFS:
        from memorymap.ai import autonomous

        #: **Switching it off stops the pass that is running, not only the next
        #: one.** Reported: "autonomous background agent tasks need to be fixed
        #: as I have accidentally turned them on multiple times and then I cant
        #: quit them, and then I turn battery saver mode on to try and stop
        #: them". Both are true of the code as it was: `wake()` only shortens
        #: the *sleep* between passes, and the enabled/battery checks run at the
        #: top of a pass, so a pass already walking the notebook read neither
        #: until it finished, which for a large notebook is many minutes of an
        #: agent the user has just told to stop.
        #:
        #: `request_stop()` sets the same flag the Quit button in the tasks
        #: panel sets, and `_run_optimization` checks it between every step, so
        #: the pass ends at its next checkpoint. Only on the way *off*: turning
        #: the librarian on, or changing its interval, should not kill a pass
        #: that is midway through being useful.
        turned_off = "autonomous_tasks_enabled" in changed_keys and not config.get_preference(
            "autonomous_tasks_enabled", False
        )
        battery_on = "battery_efficient_mode" in changed_keys and config.get_preference(
            "battery_efficient_mode", False
        )
        if turned_off or battery_on:
            autonomous.request_stop()
        autonomous.wake()
    return get_preferences()


@router.post("/system/console-mode")
def set_console_mode(
    body: dict, background_tasks: BackgroundTasks, session: Session = Depends(get_session)
) -> dict:
    """Switch Dev view / User view *live*, not just for the next launch, 
    asked for directly: togglable from Settings as well as the tray. Saves
    the preference the same way PUT /preferences would, then (desktop app,
    Windows only) restarts the whole process into the new console mode via
    __main__.restart_in_console_mode.

    The restart itself runs as a FastAPI background task, which the ASGI
    server only invokes *after* this response has actually gone out, doing
    it inline would mean `os._exit(0)` races the response itself off the
    wire, and the frontend's toast would never show ("did it even work?").
    A relaunch this can't reach (not the desktop app, not Windows, no
    pythonw.exe next to this interpreter) still saves the preference; the
    caller just won't see it take effect until the next launch, same as any
    other preference.

    Only restarts when the value actually changes, the first-run intro
    prompt calls this unconditionally with whatever was picked, and picking
    the option that already matches the current mode (the default, most of
    the time) must not restart the app the user just opened.
    """
    show_console = bool(body.get("show_console_on_startup"))
    config = deps.get_config()
    already = bool(config.get_preference("show_console_on_startup", True))
    config.set_preference("show_console_on_startup", show_console)
    manager.log_action(
        session, "edited", "preferences", detail=f"show_console_on_startup={show_console}"
    )
    session.commit()

    restarting = False
    if (
        show_console != already
        and os.getenv("MEMORYMAP_DESKTOP") == "1"
        and sys.platform == "win32"
    ):
        # `importlib`, not an `import` statement: `memorymap.__main__` imports
        # `api.app`, which imports this module, so a statement here closes a
        # CodeQL py/cyclic-import loop: and deferring it into the function
        # body does not clear that, only dropping the statement does. The
        # desktop entry point is the caller here, not a dependency.
        restart_in_console_mode = importlib.import_module(
            "memorymap.__main__"
        ).restart_in_console_mode

        restarting = True
        background_tasks.add_task(restart_in_console_mode, not show_console)
    return {"show_console_on_startup": show_console, "restarting": restarting}


@router.post("/system/restart")
def restart_app(background_tasks: BackgroundTasks) -> dict:
    """A plain restart, on request rather than tied to any one preference
    changing: ROADMAP item C, asked for directly. Several extras only take
    effect after a restart and the app said so without ever offering one;
    `restart_in_console_mode` already IS a generic "spawn a replacement
    process and exit this one," console-mode switching is just its first
    caller. This is the second: same mechanism, current console visibility
    preserved rather than flipped.

    Same platform gate as /system/console-mode, for the same reason, this
    can only ever work in the packaged desktop app on Windows (the one
    platform `_spawn_desktop` knows how to relaunch). Everywhere else,
    "restart" means the user's own means of doing that (Ctrl+C and rerun,
    close and reopen the browser tab), which this app cannot do for them.
    """
    if os.getenv("MEMORYMAP_DESKTOP") != "1" or sys.platform != "win32":
        return {"restarting": False}
    restart_in_console_mode = importlib.import_module(
        "memorymap.__main__"
    ).restart_in_console_mode  # same cycle break as above

    show_console = bool(deps.get_config().get_preference("show_console_on_startup", True))
    background_tasks.add_task(restart_in_console_mode, not show_console)
    return {"restarting": True}


def _validated_skills(raw: list[dict]) -> list[dict]:
    """Every skill, normalised: or a 422 naming the one that's wrong."""
    from memorymap.ai import tools

    known = set(tools.TOOLS)
    shipped = {skill["name"] for skill in skills.builtins()}
    out = []
    for item in raw:
        try:
            skill = skills.normalise(item, known)
        except skills.SkillError as exc:
            raise HTTPException(
                status_code=422, detail=f"“{item.get('name', '?')}”: {exc}"
            ) from exc
        if skill["name"] in shipped:
            raise HTTPException(
                status_code=422,
                detail=f"“{skill['name']}” is a built-in skill, pick another name",
            )
        out.append(skill)
    return out


def _validated_templates(raw: list[dict]) -> list[dict]:
    """Every custom template, name-checked, or a 422 naming the collision.

    Mirrors `_validated_skills` immediately above: a name that shadows a
    built-in is refused rather than silently allowed to win wherever the
    merged list is drawn next, and two customs can't collide with each other
    either. Rejecting (rather than de-duping, the way `addSkill` on the
    frontend quietly does for skills) was the deliberate choice here, 
    silently dropping a *different* saved template because its name was
    reused would be a surprise deletion of someone's own text, which a
    skill's shorter prompt doesn't risk in the same way.
    """
    seen: set[str] = set()
    out = []
    for item in raw:
        name = (item.get("name") or "").strip()
        if name in BUILTIN_TEMPLATE_NAMES:
            raise HTTPException(
                status_code=422,
                detail=f"“{name}” is a built-in template, pick another name",
            )
        if name in seen:
            raise HTTPException(
                status_code=422,
                detail=f"“{name}” is already used by another template",
            )
        seen.add(name)
        out.append(item)
    return out


def _validated_export_dir(raw: str) -> str:
    """An absolute, existing, writable directory, or a 422 saying which
    check failed. Empty string always passes (resets to the default,
    `data_dir/exports`). Checked here, at save time, rather than at export
    time: a bad path caught now is a rejected preference; caught later it's
    a lost file, discovered only when the next export silently goes nowhere
    the user can find.
    """
    value = raw.strip()
    if not value:
        return ""
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise HTTPException(status_code=422, detail="Use a full path, not a relative one.")
    if not path.is_dir():
        raise HTTPException(status_code=422, detail=f"{path} isn't a folder that exists.")
    if not os.access(path, os.W_OK):
        raise HTTPException(status_code=422, detail=f"{path} isn't writable.")
    return str(path)


@router.get("/skills")
def list_skills() -> dict:
    """Everything runnable: the shipped skills and the user's own.

    The built-ins used to be a list in `app.js`, which meant the server could
    not resolve a skill the user had just clicked, and every field added to a
    skill had to be added in two places. Served from here for the same reason
    the web-search providers are: the interface cannot then offer something
    the API would reject.
    """
    from memorymap.ai import tools

    catalog = []
    for skill in skills.catalog(deps.get_config(), set(tools.TOOLS)):
        # "This one changes things" is a different question from "this one
        # uses tools", and the UI marks it as such. A skill with steps but no
        # declared tools could do anything, so it counts.
        catalog.append(
            {
                **skill,
                "changes": bool(set(skill["tools"]) & tools.WRITE_TOOLS)
                or (not skill["tools"] and bool(skill["steps"])),
            }
        )
    return {
        "skills": catalog,
        "limits": {
            "skills": skills.MAX_SKILLS,
            "steps": skills.MAX_STEPS,
            "tools": skills.MAX_TOOLS,
            "inputs": skills.MAX_INPUTS,
        },
    }


# --- the memory stream (ROADMAP §39B) ---------------------------------------------
#
# What the AI has been told to remember, and the ability to un-tell it.
#
# `save_user_preference` lets the model write standing instructions that it
# then receives in its own system prompt on every later turn. That is a useful
# feature and a slightly alarming one, because it shipped with no way to see
# the list: the assistant's behaviour could change permanently, for a reason
# the user could not inspect, edit or undo. A rule you cannot read is
# indistinguishable from the model simply behaving oddly.
#
# So: list them, switch one off, delete one. `active` is a toggle rather than
# only a delete because "stop doing this for now" and "you never should have
# saved that" are different intentions, and the agent already filters on it.


class PreferenceBody(BaseModel):
    content: str | None = Field(default=None, max_length=200)
    active: bool | None = None


class ProposalAnswer(BaseModel):
    """Yes or no to a preference the model suggested."""

    accept: bool


def _preference_out(row) -> dict:  # noqa: ANN001  # a UserPreference
    return {
        "id": row.id,
        "content": row.content,
        "active": bool(row.active),
        # Waiting for an answer, the model wrote it, the user has not said
        # yes. A third state, not "off": it is out of the prompt *and* the UI
        # shows it as a question rather than as a switch someone flipped.
        "proposed": bool(getattr(row, "proposed", False)),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/memory")
def list_memory(session: Session = Depends(get_session)) -> dict:
    """Everything the AI has been told to remember, newest first."""
    from memorymap.ai import memory
    from memorymap.core.database import UserPreference

    rows = list(
        session.scalars(select(UserPreference).order_by(UserPreference.created_at.desc()))
    )
    return {
        "preferences": [_preference_out(r) for r in rows],
        # The UI says which of these actually reach the model. Only the active
        # ones do, and only until the character budget runs out, newest first,
        # so a long-standing list quietly stops including its oldest entries.
        # Showing the budget beats letting someone wonder why rule 41 is ignored.
        "budget_chars": memory.MEMORY_STREAM_BUDGET_CHARS,
        "in_prompt": len(memory.persona_with_memory(session, "").strip()),
    }


@router.post("/memory", status_code=201)
def add_memory(body: PreferenceBody, session: Session = Depends(get_session)) -> dict:
    """Write a standing instruction by hand.

    `save_user_preference` lets the *model* add one when you tell it something
    in conversation. This is the other direction, and it is the one people
    reach for first: "I want it to always do X" is a thing you know before you
    have had the conversation that would teach it.

    Same limits as the tool, deliberately, the cap exists because every active
    preference is replayed into the system prompt on every round, and that is
    true whoever typed it.
    """
    from memorymap.ai.tools import MAX_ACTIVE_PREFERENCES
    from memorymap.core.database import UserPreference

    text_ = (body.content or "").strip()
    if not text_:
        raise HTTPException(status_code=422, detail="A preference can't be empty.")

    active = list(
        session.scalars(
            select(UserPreference).where(UserPreference.active == True)  # noqa: E712
        )
    )
    if any((row.content or "").strip().lower() == text_.lower() for row in active):
        raise HTTPException(status_code=409, detail="That one is already saved.")
    if len(active) >= MAX_ACTIVE_PREFERENCES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"There are already {len(active)} saved preferences, which is the "
                "limit. Turn one off before adding another."
            ),
        )

    row = UserPreference(content=text_)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _preference_out(row)


@router.post("/memory/{preference_id}/answer")
def answer_memory_proposal(
    preference_id: int, body: ProposalAnswer, session: Session = Depends(get_session)
) -> dict:
    """Accept or decline a preference the model suggested.

    Asked for directly: "can the ai pick up things and suggest the user adds it
    as a preference in that section with an accept or deny or similar popup??"
    - and the shape of the old behaviour is why that is the right question.
    `save_user_preference` used to write a standing instruction into every
    future system prompt with no confirmation at all, so a model that misread
    one sentence gave itself a permanent rule its user never agreed to.

    **Declining does not delete the row**, and that is deliberate: the
    duplicate check in `_save_user_preference` looks at *every* preference, so
    a kept row is what stops the model proposing the same thing again an hour
    later. It reads as an ordinary switched-off preference afterwards, which
    it is: and can be switched on if the user changes their mind.

    Answering something that is not a proposal is a no-op rather than an
    error: two windows, two clicks, one of them second.
    """
    from memorymap.core.database import UserPreference

    row = deps.get_or_404(session, UserPreference, preference_id, "No such preference")
    if not getattr(row, "proposed", False):
        return _preference_out(row)
    row.proposed = False
    row.active = bool(body.accept)
    session.commit()
    session.refresh(row)
    return _preference_out(row)


@router.patch("/memory/{preference_id}")
def update_memory(
    preference_id: int, body: PreferenceBody, session: Session = Depends(get_session)
) -> dict:
    from memorymap.core.database import UserPreference

    row = deps.get_or_404(session, UserPreference, preference_id, "No such preference")
    if body.content is not None:
        text_ = body.content.strip()
        if not text_:
            raise HTTPException(status_code=422, detail="A preference can't be empty.")
        row.content = text_
    if body.active is not None:
        row.active = body.active
    session.commit()
    session.refresh(row)
    return _preference_out(row)


@router.delete("/memory/{preference_id}")
def forget_memory(preference_id: int, session: Session = Depends(get_session)) -> dict:
    from memorymap.core.database import UserPreference

    row = deps.get_or_404(session, UserPreference, preference_id, "No such preference")
    session.delete(row)
    session.commit()
    return {"status": "ok"}


@router.get("/audit")
def audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    entity_type: str = Query(default="", max_length=40),
    id: int | None = Query(default=None),  # noqa: A002
    session: Session = Depends(get_session),
) -> list[dict]:
    """The activity log, newest first (viewer in the UI).

    `entity_type` filters *before* the limit, and that ordering is the whole
    reason it exists. The Library's AI Skills tab asked for 20 rows and then
    filtered them in the browser for skill runs, so on any notebook where the
    last twenty things that happened were note edits, a real history of skill
    runs rendered as "No skill execution logs found". Reported as the skill
    logs not working. Filtering in SQL means the limit counts the rows you
    asked for rather than the rows you are about to throw away.

    `id` is the Library Activity card's own "view the whole thing", its own
    list comes from `_activity()` (routes_library.py), which clips `detail`
    to `ACTIVITY_DETAIL_CHARS` so a long one doesn't blow out the card grid.
    This route never clips (`detail` below is the raw column), so re-fetching
    one row by id is what a click-to-expand needs, without a second endpoint.
    """
    query = select(AuditLog)
    if id is not None:
        query = query.where(AuditLog.id == id)
    elif entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    rows = session.scalars(query.order_by(AuditLog.id.desc()).limit(limit))
    return [
        {
            "id": row.id,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "actor": row.actor or events.ACTOR_USER,
            "detail": row.detail,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def _feed_item(row: AuditLog) -> dict:
    """One event as the feed reports it: what happened, not what it stored."""
    span = events.snapshot_span(row)
    return {
        "id": row.id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "actor": row.actor or events.ACTOR_USER,
        "detail": row.detail,
        # A snapshot's `after` is the whole state, not the fields this event
        # set, so naming them would be a lie about what changed.
        "changed": [] if span else sorted((row.payload or {}).get("after", {}) or {}),
        #: How many events this row stands for, absent on an ordinary one.
        "snapshot": span,
        #: Its values were dropped by the compactor; the row is still a fact.
        "compacted": events.is_compacted(row),
        "created_at": row.created_at.isoformat(),
    }


@router.get("/events")
def event_feed(
    since: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    entity_type: str = Query(default="", max_length=40),
    include_quiet: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> dict:
    """The event log forwards, for anything that follows what happens here.

    `/audit` reads backwards from now, which is what a viewer wants and what
    a feed cannot use: a poller has to ask "what has happened since the last
    thing I saw" and get it in the order it happened. So this is ascending
    from `since` (exclusive), with `cursor` to pass back next time, and it
    is what a Dashboard or Timeline activity strip should read instead of
    scanning the notes table for recency (WORLD_CLASS_PLAN B1).

    Payloads are not returned: they carry whole field values, which for a
    note is its entire text, and a feed that ships every version of every
    note is a different thing from a feed. `changed` names the fields each
    event set, which is what a strip renders, and `/entries/{id}/history`
    has the values when something actually needs them.

    **A compacted event says what it is instead of naming fields.** The
    compactor (`events.compact`) folds a run of old events into one
    snapshot whose `after` holds the entity's whole state at that point, so
    reading `after` off it named every field of the note and reported one
    change as having set all of them at once, which never happened. Such a
    row reports `changed: []` and a `snapshot` count of the events it
    stands for; the rows behind it, whose values were dropped, report
    `compacted: true`. Both are the honest answer to "what happened here",
    and both are what a strip needs to render a run of folded history as
    one line rather than as a burst of edits.
    """
    query = select(AuditLog).where(AuditLog.id > since)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if not include_quiet:
        query = query.where(AuditLog.action.notin_(sorted(events.QUIET_ACTIONS)))
    rows = list(session.scalars(query.order_by(AuditLog.id.asc()).limit(limit)))
    return {"items": [_feed_item(row) for row in rows], "cursor": rows[-1].id if rows else since}


@router.delete("/audit")
def clear_audit_log(
    entity_type: str = Query(..., max_length=40),
    session: Session = Depends(get_session),
) -> dict:
    """Asked for directly: a "Clear" button for the AI Skills sidebar's own
    log list. `entity_type` is required, not optional: this deliberately
    cannot clear the whole audit trail (note edits, deletes, private-note
    decryption events: real accountability history, not a scrollback
    buffer someone would want to blank), only one filtered slice of it at a
    time, the same scope `GET /audit?entity_type=` already reads."""
    deleted = session.query(AuditLog).filter(AuditLog.entity_type == entity_type).delete()
    session.commit()
    return {"deleted": deleted}


@router.post("/recycle-bin/empty")
def empty_recycle_bin(session: Session = Depends(get_session)) -> dict:
    removed = manager.empty_recycle_bin(
        session, uploads_dir=deps.get_config().uploads_dir
    )
    return {"removed": removed}


# --- optional extras ---------------------------------------------------------


@router.get("/extras")
def list_extras() -> dict:
    """What can be installed, and what already is.

    The install itself reports through /tasks like every other background job,
    so this is only the catalogue and the current state.
    """
    state = extras.current()
    return {
        "extras": extras.status(),
        "running": state.running,
        "installing": state.extra_id if state.running else "",
        "step": state.step,
        "outcome": state.outcome,
        "log": list(state.log),
    }


@router.post("/extras/{extra_id}/install")
def install_extra(extra_id: str, reinstall: bool = False) -> dict:
    """Start installing one extra **from the allowlist**.

    The path names an entry in `core/extras.py`; the package spec handed to pip
    is never anything the client sent. That is the whole security property here
    - `pip install <a name from a request body>` is arbitrary code execution by
    design, and validating the string afterwards does not fix it.
    """
    started, message = extras.start(extra_id, reinstall=reinstall)
    return {"started": started, "message": message}


@router.post("/extras/{extra_id}/uninstall")
def uninstall_extra(extra_id: str) -> dict:
    """Remove one extra, by the same allowlist id the install uses."""
    started, message = extras.remove(extra_id)
    return {"started": started, "message": message}


# --- embedding models ---------------------------------------------------------


@router.get("/embedding-models")
def list_embedding_models() -> dict:
    """Which embedding models are on this machine, and what they cost.

    `can_download` is here rather than left for the client to infer: without
    `huggingface_hub` (which arrives with the semantic-search extra) every
    button on this screen would start something that cannot finish, and a
    disabled button with a reason beats a download that fails on an ImportError.
    """
    state = embedmodels.current()
    return {
        "models": embedmodels.status(),
        "cache": str(embedmodels.cache_root()),
        "can_download": embedmodels.can_download(),
        "running": state.running,
        "downloading": state.model_id if state.running else "",
        "step": state.step,
        "outcome": state.outcome,
        "log": list(state.log),
    }


@router.post("/embedding-models/{model_id}/download")
def download_embedding_model(model_id: str, reinstall: bool = False) -> dict:
    """Fetch one model **from the allowlist** in `core/embedmodels.py`.

    Same property as the extras installer: the repo id handed to the hub is
    never anything the client sent. A repo id from a request is a path that
    gets fetched and written to disk.

    A reinstall removes first, because that is the state the button exists for
    - a half-finished download leaves a directory that looks installed and
    loads as a corrupt model, and fetching over the top of it resumes the same
    broken snapshot.
    """
    if reinstall:
        embedmodels.remove(model_id)
    started, message = embedmodels.start(model_id)
    return {"started": started, "message": message}


@router.delete("/embedding-models/{model_id}")
def remove_embedding_model(model_id: str) -> dict:
    """Delete one model from the cache, by the same allowlist id."""
    removed, message = embedmodels.remove(model_id)
    return {"removed": removed, "message": message}


@router.get("/logs")
def server_logs(limit: int = Query(default=200, ge=1, le=logbuffer.MAX_RECORDS)) -> list[dict]:
    """Recent server-side log records for the Settings → Logs viewer."""
    return logbuffer.recent(limit=limit)


class ClientError(BaseModel):
    """One thing that went wrong in the browser, on its way to the terminal."""

    message: str = Field(max_length=2000)
    #: Where it happened, when the browser knows: "app.js:6088:12". Free text
    #: because a stack frame's shape differs per engine and none of it is
    #: parsed: it is read by a person.
    source: str = Field(default="", max_length=500)
    #: "error" | "unhandledrejection" | "csp", what kind of failure this was,
    #: since the three need different first questions asked about them.
    kind: str = Field(default="error", max_length=40)


@open_router.post("/logs/client", status_code=204)
def record_client_error(body: ClientError, response: Response) -> None:
    """Put a browser-side failure into the same log everything else uses.

    Asked for directly: *"can you make any other erros like what aoppeared on
    the loading screen appear in the logs as well?? the terminal and logs need
    to capture everything."*

    The gap was real and had just cost a session. A JavaScript error aborts
    the rest of the file it is in, so the app can hang on its loading screen
    with **nothing** in the terminal, nothing in Settings → Logs, and the only
    record sitting in a browser console nobody opens, least of all in the
    desktop shell, which has no obvious way to open one. The crash that
    prompted this (`Cannot access 'captureStagedFiles' before initialization`)
    was invisible to every log this app keeps.

    Deliberately `logger.error`, not a new channel: `logbuffer`'s handler is
    already attached to the root logger, so this reaches the terminal, the
    Settings → Logs viewer and `/logs/stream` at once, with no new plumbing to
    keep in step. The `[browser]` prefix is what tells a reader the failure
    happened on the other side of the wire, which changes what they should
    look at next.

    **On `open_router`, outside the unlock gate, on purpose.** This has to
    work *before* unlock: the loading-screen hang it exists for happens with
    the lock overlay still up, and a crash report that needs a token cannot
    describe the failure that stopped the token from ever being used. Every
    other route in this module stays behind `locked`.

    What it accepts is bounded instead of authenticated: three short strings,
    length-capped by the schema, appended to a ring buffer that already caps
    itself at `MAX_RECORDS`, reachable only from an origin the CSP pins to
    `'self'` on a server that binds to localhost. The worst an abuser of it
    can do is push older lines out of a 500-record buffer on their own
    machine.
    """
    # **Through `safe_value`, not raw.** Everything in this payload is
    # attacker-shaped by construction: it is text the browser was handed by
    # whatever failed, and a message containing a newline would draw a forged
    # second row in the Settings → Logs viewer while control characters can
    # rewrite what a terminal shows. `logbuffer.sanitise` runs at the ring
    # buffer and so protects the viewer only; the terminal sees the raw
    # record, which is exactly why this module's own helper exists and says
    # to clean at the call site.
    logger = logging.getLogger("memorymap.browser")
    kind = logbuffer.safe_value(body.kind, limit=40)
    message = logbuffer.safe_value(body.message, limit=logbuffer.MAX_MESSAGE_CHARS)
    where = f" ({logbuffer.safe_value(body.source, limit=200)})" if body.source else ""
    logger.error("[browser/%s] %s%s", kind, message, where)
    response.status_code = 204


@router.get("/logs/stats")
def server_log_stats(
    limit: int = Query(default=200, ge=1, le=logbuffer.MAX_RECORDS),
) -> dict:
    """How complete the log above actually is.

    A separate call rather than a wrapper around the records, so the shape of
    /logs stays a plain list for everything already reading it.
    """
    return logbuffer.stats(limit=limit)


@router.delete("/logs")
def clear_server_logs() -> dict:
    logbuffer.clear()
    return {"cleared": True}


# How long a single stream lives before it hands over to the browser's own
# reconnect, and how often it looks for new records. The cap is not a
# limitation to work around, EventSource reconnects on its own and resends
# Last-Event-ID, so the handover is seamless, and a stream that lives forever
# is a resource nothing ever reclaims when a tab is left open for a week.
LOG_STREAM_SECONDS = 10 * 60
LOG_STREAM_POLL = 0.7
LOG_STREAM_HEARTBEAT = 15


@router.get("/logs/stream")
async def stream_server_logs(request: Request, after: int = 0) -> StreamingResponse:
    """A live log feed, so the Logs screen reads like a terminal.

    Asked for directly: the screen should behave "like the terminal running in
    the background", not a list you refresh by hand.

    **NDJSON over fetch rather than the EventSource the roadmap suggested.**
    EventSource cannot set request headers, and this app authenticates with
    `X-Auth-Token`, so an EventSource here would simply 401. The usual way
    round that is to put the token in the query string, which is a bad trade
    anywhere and a farcical one on the endpoint that serves the log: the token
    would be written into the very records it is protecting. `fetch` carries
    the header, and NDJSON matches the chat and digest streams the app already
    has, so the browser-side reader is the one that already exists.

    Polling the ring buffer rather than registering a subscriber on it. That
    sounds like the lazier choice and is the more robust one: a subscriber
    registry means the logging handler pushes into per-connection queues, so a
    slow or dead reader can block or grow unboundedly *inside logging itself*, 
    and a logging path that can stall is a far worse failure than a console
    running 700ms behind. One reader, one process, one deque.
    """

    async def lines() -> AsyncIterator[str]:
        cursor = after
        loop = asyncio.get_running_loop()
        started = loop.time()
        last_sent = started
        # An immediate first line, so the reader knows the stream is live
        # before anything has been logged, and learns where it is starting
        # from, which is what makes "dropped" meaningful on the client.
        yield json.dumps(
            {"type": "open", "cursor": cursor, "latest": logbuffer.latest_seq()}
        ) + "\n"
        while True:
            if await request.is_disconnected():
                return
            now = loop.time()
            # Drain BEFORE checking the deadline. The other order loses every
            # record that arrived in the last poll interval of the connection:
            # the client reconnects from its cursor and those records are
            # inside the buffer but behind it, so they are never sent at all.
            for record in logbuffer.since(cursor):
                cursor = record.get("seq", cursor)
                yield json.dumps({"type": "record", "record": record}) + "\n"
                last_sent = now
            if now - started > LOG_STREAM_SECONDS:
                # Hand back to the client's own reconnect rather than holding a
                # connection open forever for a tab left open all week.
                yield json.dumps({"type": "reconnect", "cursor": cursor}) + "\n"
                return
            if now - last_sent > LOG_STREAM_HEARTBEAT:
                # Keeps the connection from being reaped as idle, and doubles
                # as the client's proof that the server is still there rather
                # than merely quiet.
                yield json.dumps({"type": "ping", "cursor": cursor}) + "\n"
                last_sent = now
            await asyncio.sleep(LOG_STREAM_POLL)

    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={
            # Same reasoning as the chat stream: stop a reverse proxy buffering
            # a stream whose whole value is arriving promptly.
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


# Preferences safe to put in a file the user will send to a stranger.
#
# An allowlist, not a denylist, and that choice is the whole design. A denylist
# has to predict every sensitive key anyone will ever add; this one only has to
# name the ones that help diagnose a bug. Anything not here is reported by
# name, type and size, "persona_prompt: string, 412 chars", which is enough
# to tell whether a setting is involved without disclosing what it says.
DIAGNOSTIC_PREFERENCES = frozenset(
    {
        "ai_enabled",
        "tools_enabled",
        "chat_model",
        "utility_model",
        "embedding_backend",
        "embedding_model",
        "recycle_bin_days",
        "conversation_retention_days",
        "timezone",
        "web_search_enabled",
        "searxng_autostart",
        "search_provider",
        "thinking_enabled",
        "guided_mode",
        "auto_categorise",
        # Which backend answered is the first question any "the AI is broken"
        # report needs. `llm_api_key` is deliberately NOT here, it stays
        # described-not-disclosed like every other secret.
        "llm_provider",
        "llm_base_url",
        "local_only_ai",
        # How long answers were asked to be, which is the first thing to check
        # in a "the AI is slow" or "the AI is too terse" report (§11).
        "response_mode",
    }
)


def _redacted_preferences(preferences: dict) -> dict:
    """Diagnostic settings verbatim; everything else described, not disclosed."""
    kept: dict = {}
    withheld: dict = {}
    for key, value in sorted(preferences.items()):
        if key in DIAGNOSTIC_PREFERENCES:
            kept[key] = value
            continue
        shape = type(value).__name__
        if isinstance(value, str):
            withheld[key] = f"{shape}, {len(value)} chars"
        elif isinstance(value, (list, dict)):
            withheld[key] = f"{shape}, {len(value)} items"
        else:
            withheld[key] = shape
    return {"included": kept, "withheld": withheld}


BUNDLE_README = """MemoryMap AI: support bundle
=============================

What this is
------------
A snapshot of what the app can see about itself, collected so you can attach
it to a bug report. Everything in it was already on this machine and already
visible somewhere in the app; this file only gathers it into one place.

Nothing was sent anywhere. This file was written to your disk and it is
entirely your choice whether to share it.

What is in it
-------------
  logs.json         the recent server log, exactly as Settings -> Logs shows
  preferences.json  your settings, with free-text ones withheld (see below)
  status.json       app version, platform, and the state of Ollama, the
                    embedding model and SearXNG
  counts.json       how many notes, categories and documents exist, numbers
                    only, never their contents

What is NOT in it
-----------------
  · No note, document, chat or reminder content of any kind.
  · No password, and nothing derived from one.
  · No private-note data, encrypted or otherwise.
  · Free-text settings (display name, personas, custom prompts) are listed by
    name and length only, under "withheld" in preferences.json.

Worth a glance before you send it
---------------------------------
Log messages can quote things you typed, a chat question, or the title of a
page you opened. Open logs.json and skim it if that matters to you.
"""


@router.get("/support-bundle")
def support_bundle(session: Session = Depends(get_session)) -> Response:
    """Everything a bug report needs, in one file, collected locally.

    Asked for indirectly ("an interface for managing the application… errors
    etc") and echoed by an outside review. Deliberately *not* crash reporting:
    nothing is transmitted, the file lands on disk, and the user decides
    whether it ever goes anywhere. That distinction is why this was accepted
    and opt-in telemetry was not.
    """
    config = deps.get_config()
    buffer = io.BytesIO()

    def _safely(collect, fallback):
        """A bundle that half-collects is far better than one that 500s.

        The moment this is most needed is when something is already broken, so
        any single probe failing must not take the whole file with it.
        """
        try:
            return collect()
        except Exception as exc:  # noqa: BLE001  # the reason IS the diagnostic
            return {"error": f"{type(exc).__name__}: {exc}", **fallback}

    status_payload = {
        "app_version": __version__,
        "generated_at": utcnow().isoformat(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "data_dir": str(config.data_dir),
        "models": _safely(_models_status_snapshot, {"models": None}),
        "searxng": _safely(lambda: searxng_manager.status(config.data_dir), {}),
        "logs": logbuffer.stats(),
    }
    counts = _safely(
        lambda: {
            "entries": session.scalar(select(func.count(Entry.id))) or 0,
            "entries_deleted": session.scalar(
                select(func.count(Entry.id)).where(Entry.is_deleted == True)  # noqa: E712
            )
            or 0,
            "entries_private": session.scalar(
                select(func.count(Entry.id)).where(Entry.is_private == True)  # noqa: E712
            )
            or 0,
            "categories": session.scalar(select(func.count(Category.id))) or 0,
            "links": session.scalar(select(func.count(EntryLink.id))) or 0,
        },
        {},
    )

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", BUNDLE_README)
        archive.writestr(
            "logs.json", json.dumps(logbuffer.recent(logbuffer.MAX_RECORDS), indent=2)
        )
        archive.writestr(
            "preferences.json",
            json.dumps(_redacted_preferences(config.all_preferences()), indent=2),
        )
        archive.writestr("status.json", json.dumps(status_payload, indent=2, default=str))
        archive.writestr("counts.json", json.dumps(counts, indent=2))

    manager.log_action(session, "exported", "data", detail="support bundle")
    session.commit()
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=memorymap-support-bundle.zip"
        },
    )


def _models_status_snapshot() -> dict:
    """The model/AI state, without importing the models router's response."""
    ollama = deps.get_ollama()
    model_manager = deps.get_model_manager()
    embeddings = deps.get_embeddings()
    return {
        "ollama_running": ollama.is_running(),
        "chat_model": model_manager.chat_model(),
        "utility_model": model_manager._config.get_preference("utility_model", ""),
        "embedding_backend": model_manager.embedding_backend(),
        "active_embedding_model": embeddings.active_model(),
        "embedding_ready": embeddings.is_ready(),
        "embedding_error": embeddings.last_error,
    }


def _export_rows(session: Session) -> tuple[list[Category], list[Entry], list[EntryLink]]:
    """Everything the user owns, including binned entries, an export
    should never silently drop data."""
    categories = list(session.scalars(select(Category).order_by(Category.id)))
    entries = list(session.scalars(select(Entry).order_by(Entry.id)))
    links = list(session.scalars(select(EntryLink).order_by(EntryLink.id)))
    return categories, entries, links



@router.get("/export/backup")
def export_backup(background_tasks: BackgroundTasks):
    import os
    config = deps.get_config()
    db_path = config.data_dir / "memorymap.db"
    media_dir = config.data_dir / "media"
    
    fd, tmp_path = tempfile.mkstemp(suffix=".zip", prefix="memorymap_backup_")
    os.close(fd)
    
    def cleanup():
        try:
            os.remove(tmp_path)
        except OSError:
            pass  # already gone, or never got written, nothing left to clean up
            
    background_tasks.add_task(cleanup)
    
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if db_path.exists():
            zf.write(db_path, "memorymap.db")
        if media_dir.exists() and media_dir.is_dir():
            for root, _, files in os.walk(media_dir):
                for f in files:
                    file_path = Path(root) / f
                    arcname = file_path.relative_to(config.data_dir)
                    zf.write(file_path, str(arcname))
                    
    return FileResponse(tmp_path, media_type="application/zip", filename="memorymap_backup.zip", background=background_tasks)

@router.get("/export/json")

def export_json(session: Session = Depends(get_session)) -> Response:
    categories, entries, links = _export_rows(session)
    payload = {
        "app": "MemoryMap AI",
        "version": __version__,
        "exported_at": utcnow().isoformat(),
        "categories": [{"id": c.id, "name": c.name} for c in categories],
        "entries": [],
        "links": [],
    }

    category_names = manager.bulk_category_names(session, entries)

    for e in entries:
        payload["entries"].append({
            "id": e.id,
            # Exports decrypt while the app is unlocked. An export is for
            # taking your notes elsewhere, and ciphertext with no key is
            # not your notes. (The app's own backups keep the database
            # file as-is, so those stay encrypted.)
            "content": manager.readable_content(e),
            "category": category_names.get(e.category_id, manager.UNCATEGORISED),
            "tags": manager.entry_tags(e),
            "ai_confidence": e.ai_confidence,
            "created_at": e.created_at.isoformat(),
            "updated_at": e.updated_at.isoformat(),
            # `is_deleted` is not decoration and not derivable from
            # `deleted_at`: an export is what a re-import reads, and without
            # this flag every note in the recycle bin comes back as a live
            # note. It went missing when this block was rewritten as a loop.
            "is_deleted": e.is_deleted,
            "deleted_at": e.deleted_at.isoformat() if e.deleted_at else None,
        })

    payload["links"] = [
        {
            "id": link.id,
            "source_entry_id": link.source_entry_id,
            "target_entry_id": link.target_entry_id,
        }
        for link in links
    ]
    manager.log_action(session, "exported", "data", detail="json")
    session.commit()
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=memorymap-export.json"},
    )


def _slug(text: str, length: int = 30) -> str:
    """A filesystem-safe slice of a note's first words."""
    cleaned = re.sub(r"[^\w\s-]", "", text)[:length].strip()
    return re.sub(r"[\s]+", "-", cleaned) or "note"


def build_markdown_export(session: Session) -> bytes:
    """The zip itself, as bytes, with nothing HTTP about it.

    Lifted out of the route below so `python -m memorymap --export PATH`
    writes exactly the same archive the Settings button downloads, rather
    than a second implementation that drifts. uninstall.sh and
    uninstall.bat call that entry point for `--export`, which is the whole
    point: someone removing the app should be able to take their notes out
    first, from a terminal, with no browser and no running server.

    The audit line is written here rather than in the route so a CLI export
    is recorded too: "where did this zip come from" is the same question
    either way.
    """
    _categories, entries, _links = _export_rows(session)
    category_names = manager.bulk_category_names(session, entries)
    
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            cat_name = category_names.get(entry.category_id, manager.UNCATEGORISED)
            folder = (
                "_recycle-bin"
                if entry.is_deleted
                else _slug(cat_name, 40)
            )
            tags = manager.entry_tags(entry)
            front = [
                "---",
                f"category: {cat_name}",
                f"created: {entry.created_at.isoformat()}",
            ]
            if tags:
                front.append(f"tags: [{', '.join(tags)}]")
            if entry.pinned:
                front.append("pinned: true")
            front.append("---")
            readable = manager.readable_content(entry)
            body = "\n".join(front) + f"\n\n{readable}\n"
            archive.writestr(f"{folder}/{entry.id}-{_slug(readable)}.md", body)
    manager.log_action(session, "exported", "data", detail="markdown")
    session.commit()
    return buffer.getvalue()


@router.get("/export/markdown")
def export_markdown(session: Session = Depends(get_session)) -> Response:
    """A zip of Obsidian-friendly .md files: one file per note, one
    folder per category, YAML frontmatter carrying the metadata. Binned
    notes go under _recycle-bin/, exports never silently drop data."""
    return Response(
        content=build_markdown_export(session),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=memorymap-markdown.zip"},
    )


MAX_IMPORT_BYTES = 1024 * 1024  # a single markdown note, not a novel
#: `import_markdown` below had a per-file size cap but no cap on how many
#: files one request could carry, each one does its own `create_entry` +
#: `session.commit()`, so a request with an unbounded file count ran
#: unbounded work. Same instinct as `MAX_DOCUMENT_IMPORT_NOTES` just below:
#: a real "import my Obsidian vault" drag-and-drop is at most a few hundred
#: files, so this is generous headroom, not a real-world ceiling.
MAX_IMPORT_FILES = 500


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """(metadata, body). Understands the small subset this app writes:
    `category: X` and `tags: [a, b]`. Anything else is left in the body
    untouched: imports must never eat someone's text."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta: dict = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "category" and value:
            meta["category"] = value
        elif key == "tags":
            meta["tags"] = [t.strip() for t in value.strip("[]").split(",") if t.strip()]
    return meta, text[end + 5 :].lstrip("\n")



class ImportDirectoryRequest(BaseModel):
    path: str

def _validated_import_directory(path_value: str) -> Path:
    """The one place `import_directory`'s request path is turned into a
    real, checked filesystem path, both the route and the background job
    it schedules use this, and both pass its *return value* on, never the
    original string.

    CodeQL flags the raw `req.path` reaching file I/O as "uncontrolled
    data used in a path expression", correct about the data flow, but
    this route's whole job is letting the already-authenticated owner of
    this single-user, local-only notebook pick any folder on their own
    machine to import from (the Obsidian-vault-import feature). There is
    no narrower base directory to confine it to without breaking that.
    What this *can* do, and didn't before: reject a null byte outright
    (the one thing no legitimate path contains), confirm the path
    genuinely resolves to an existing directory before anything reads
    from it, and, the part a first pass at this missed, make sure the
    resolved, checked `Path` is what actually gets used downstream rather
    than the original unchecked string living on past this function.
    """
    if not path_value or "\x00" in path_value:
        raise ValueError("Invalid directory path")
    try:
        p = Path(path_value).resolve(strict=True)
    except OSError as exc:
        raise ValueError("Invalid directory path") from exc
    if not p.is_dir():
        raise ValueError("Invalid directory path")
    return p

def _run_directory_import(directory_path: str):
    try:
        p = _validated_import_directory(directory_path)
    except ValueError:
        return
    with deps.get_db().session() as session:
        imported = 0
        skipped = 0
        for f in p.rglob("*.md"):
            try:
                text = f.read_text(encoding="utf-8")
                meta, body = _parse_frontmatter(text)
                if not body.strip():
                    skipped += 1
                    continue
                #: **The file's own text, unchanged.** An earlier attempt at
                #: this prepended `# <filename>` so the note would carry its
                #: vault name: and three existing tests caught it, rightly:
                #: an importer that edits what it imports is a data-loss bug
                #: waiting to be reported, and this app's own rule is that a
                #: note has no separate title, its opening words *are* its
                #: name. The filename is preserved on `source_path` instead,
                #: where `find_by_wiki_name` reads it, so `[[wiki links]]`
                #: resolve without a single character of the note changing.
                entry = manager.create_entry(
                    session,
                    body.strip(),
                    category_name=meta.get("category") or manager.UNCATEGORISED,
                    tags=meta.get("tags") or [],
                    ai_confidence=100 if meta.get("category") else 0,
                )
                #: Relative to the vault root, never absolute, see
                #: `Entry.source_path`. `as_posix` so a vault imported on
                #: Windows and one imported on Linux group identically.
                try:
                    entry.source_path = f.relative_to(p).as_posix()[:500]
                except ValueError:
                    entry.source_path = f.name[:500]
                if meta.get("category"):
                    entry.user_filed = True
                deps.store_quietly(session, entry)
                imported += 1
                if imported % 50 == 0:
                    session.commit()
            except Exception:
                skipped += 1
        if imported > 0:
            manager.log_action(session, "imported", "data", detail=f"markdown dir x{imported}")
            session.commit()
            #: A whole vault arriving at once is exactly the "large change"
            #: the rebuild suggestion exists for, see `mark_index_stale`.
            deps.mark_index_stale(imported)

@router.post("/import/directory", status_code=202)
def import_directory(req: ImportDirectoryRequest, background_tasks: BackgroundTasks):
    try:
        p = _validated_import_directory(req.path)
    except ValueError:
        raise HTTPException(400, "Invalid directory path") from None
    # The validated, resolved path, not req.path, is what the background
    # job and the response both carry from here on.
    canonical_path = str(p)
    background_tasks.add_task(_run_directory_import, canonical_path)
    return {"status": "started", "path": canonical_path}

@router.post("/import/markdown", status_code=201)

def import_markdown(
    files: list[UploadFile], session: Session = Depends(get_session)
) -> dict:
    """Turn uploaded .md files into notes (Obsidian-friendly: the same
    frontmatter the export writes is understood on the way back in)."""
    if len(files) > MAX_IMPORT_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"{len(files)} files at once is more than one import handles "
            f"({MAX_IMPORT_FILES} max): split it into smaller batches.",
        )
    imported = 0
    skipped: list[str] = []
    for file in files:
        raw = file.file.read(MAX_IMPORT_BYTES + 1)
        name = file.filename or "note.md"
        if len(raw) > MAX_IMPORT_BYTES:
            skipped.append(f"{name}: larger than 1 MB")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append(f"{name}: not a text file")
            continue
        meta, body = _parse_frontmatter(text)
        if not body.strip():
            skipped.append(f"{name}: empty")
            continue
        #: The path, not the text, see the directory importer above for why
        #: nothing here rewrites the file's own content. A browser sends the
        #: relative path as the filename when the picker was a directory
        #: picker, and the bare name otherwise; both are relative, which is
        #: the only kind stored.
        entry = manager.create_entry(
            session,
            body.strip(),
            category_name=meta.get("category") or manager.UNCATEGORISED,
            tags=meta.get("tags") or [],
            ai_confidence=100 if meta.get("category") else 0,
        )
        entry.source_path = name.lstrip("/")[:500]
        if meta.get("category"):
            entry.user_filed = True  # the file said where it belongs
            session.commit()
        deps.store_quietly(session, entry)
        imported += 1
    manager.log_action(session, "imported", "data", detail=f"markdown x{imported}")
    session.commit()
    deps.mark_index_stale(imported)
    return {"imported": imported, "skipped": skipped}


#: A PDF or slide deck, not a video, well past what a document-conversion
#: library is for.
MAX_DOCUMENT_IMPORT_BYTES = 20 * 1024 * 1024
#: A very long deck splits into one note per slide; a sane ceiling on how
#: many notes one upload can create, the same instinct as `tools.py`'s
#: MAX_PLAN_STEPS: a huge number here is usually a converter emitting one
#: heading per page rather than someone wanting 200 new notes at once.
MAX_DOCUMENT_IMPORT_NOTES = 25


@router.post("/import/document", status_code=201)
def import_document(file: UploadFile, session: Session = Depends(get_session)) -> dict:
    """Turn an uploaded PDF/Word/slide file into one or more notes, via
    markitdown (§37G): the button `core/extras.py`'s `documents` extra
    installed for and had nothing behind, until this.

    One note per top-level heading when the converted markdown has more than
    one (a deck, a document with real chapters); the whole file as one note
    otherwise: `import_markdown`'s "each file becomes a note" for the common
    case, once markitdown has turned it into something with that shape.
    """
    if not importer.markitdown_available():
        raise HTTPException(status_code=503, detail=importer.INSTALL_HINT)

    data = file.file.read(MAX_DOCUMENT_IMPORT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 20 MB")
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty")

    suffix = Path(file.filename or "document").suffix[:12] or ".txt"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as saved:
        saved.write(data)
        saved.flush()
        try:
            text = importer.convert_to_markdown(Path(saved.name))
        except Exception as exc:  # a file markitdown can't parse must not 500
            raise HTTPException(
                status_code=422, detail=f"Couldn't read that file: {exc}"
            ) from exc

    all_sections = importer.split_into_sections(text)
    if not all_sections:
        raise HTTPException(
            status_code=422, detail="That file had no readable text in it"
        )
    sections = all_sections[:MAX_DOCUMENT_IMPORT_NOTES]

    imported = 0
    for section in sections:
        entry = manager.create_entry(
            session,
            section,
            category_name="Imports",
            tags=["imported"],
            ai_confidence=100,
        )
        entry.user_filed = True  # this file said where it came from, not the janitor
        session.commit()
        deps.store_quietly(session, entry)
        imported += 1
    manager.log_action(
        session, "imported", "data", detail=f"document x{imported} ({file.filename})"
    )
    session.commit()
    return {
        "imported": imported,
        "truncated": len(all_sections) > len(sections),
        "filename": file.filename,
    }



# web search (routes_websearch.py) and backups (routes_backups.py) moved out

@router.get("/export/csv")
def export_csv(session: Session = Depends(get_session)) -> Response:
    _categories, entries, _links = _export_rows(session)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["id", "content", "category", "tags", "ai_confidence", "created_at", "is_deleted"]
    )
    
    category_names = manager.bulk_category_names(session, entries)
    
    for e in entries:
        writer.writerow(
            [
                e.id,
                manager.readable_content(e),
                category_names.get(e.category_id, manager.UNCATEGORISED),
                "|".join(manager.entry_tags(e)),
                e.ai_confidence,
                e.created_at.isoformat(),
                e.is_deleted,
            ]
        )
    manager.log_action(session, "exported", "data", detail="csv")
    session.commit()
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=memorymap-export.csv"},
    )
