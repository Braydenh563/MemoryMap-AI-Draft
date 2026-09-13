// dashboard.js: widgets, masonry, the generative art (split out of app.js).
//
// Loaded after app.js (see index.html's <script> ordering comment): every
// reference here into app.js globals ($, apiJson, toast, switchTab,
// smallButton, chip, renderMarkdown, renderInlineMarkdown, safeMdSlice,
// notePreviewText, renderEmblem, resolvedTheme, currentAccentHex,
// appearancePref, allEntries, prefsCache, modelStatus, and more) is a
// runtime call inside a function body or an event-listener closure, never a
// parse-time reference, so load order only matters for the reverse
// direction: anything in app.js that calls into dashboard.js
// (refreshActiveTab's "dashboard" branch, switchTab's dashboard branch,
// renderDashboardGreeting()/refreshArtForTheme() called from the appearance
// code, etc.) does so from inside its own functions too, which by the time
// they run have always already had this script loaded (same
// DOMContentLoaded pass, no user interaction possible in between).
//
// Two hazards found doing this split, both the same shape as
// documents.js's `initDocSidebarTabs()` one: a bare top-level reference in
// app.js resolving before this file has loaded:
//
// 1. Two `addEventListener` registrations at the bottom of this file
//    (`$("features-close")`, and the plain-reference form generally) used
//    to live in app.js's own top-level wiring, passing `closeFeatures` as a
//    bare function reference. That reference resolves the moment the
//    registering line executes: app.js's own top-level pass, before this
//    file has loaded. Fixed by moving the whole wiring group here, after
//    its own functions, instead of splitting definition from call site. See
//    the "wiring" section near the end of this file for the full
//    explanation.
// 2. `applyPalette()` (app.js) calls `refreshArtForTheme()` (this file), and
//    `applyPalette` is itself reachable from a bare top-level call, 
//    `applyAppearance()`, run once at parse time to paint the saved theme
//    before first render. Caught live in Chromium, not by reading the code:
//    a `ReferenceError` there aborted the rest of app.js's synchronous
//    top-level wiring. Fixed with a `typeof` guard at that one call site
//    (app.js's `applyPalette`) rather than moving `applyPalette` itself,
//    since it does real app.js-only work (the whole-app palette/background)
//    that has nothing to do with the dashboard.
//
// --- boundaries deliberately NOT crossed doing this split ---
//
// - `tickClocks()` (the `.live-clock` ticker `app.js` still owns) stays in
//   app.js: it drives the Reminders tab's clock too, not just the
//   dashboard's, so it is genuinely shared rather than dashboard-only.
// - The tab-bar overflow-fade machinery (`syncTabOverflowFade`,
//   `tabRowSpace`, `tabContentWidth`, `revealActiveTab`) physically sat
//   inside app.js's "masonry packing for the dashboard" comment block with
//   no header of its own, but has nothing to do with the dashboard, it
//   sizes the top tab strip for every tab. Left in app.js.
// - `safeMdSlice`/`notePreviewText`/`renderEmblem` stayed in app.js: all
//   three are called from outside the dashboard too (note-card previews,
//   the writing room, whiteboard.js's node labels, the chat avatar), see
//   the comments left at their definitions in app.js.
// - "Wave J: accent themes + generative background" (app.js, curated
//   themes, saved themes, the ambient/second p5 background instance) is
//   Settings → Appearance's own territory, not a dashboard widget, despite
//   `refreshArtForTheme()` (this file) being called from inside it whenever
//   the theme/accent/palette changes. Left for the settings.js split.
// - "SKILLS DASHBOARD TAB" (app.js, `renderSkillsDashboard`,
//   `#skills-dashboard-list`) is the AI Skills library page, an unrelated
//   feature that happens to share the word "dashboard" in its own internal
//   naming. Left in app.js.
// - `renderDashboardPersonaSelect` and its Settings wiring
//   (`#dashboard-persona-select`) configure which persona voices the
//   dashboard greeting, but the control itself lives inside Settings →
//   Personas' own render function (`renderPersonas`), a Settings concern,
//   like documents.js leaving `voice-model-select` behind. Left in app.js.

// --- dashboard (Wave D) -----------------------------------------------------------

let dashEditMode = false;
let dragWidget = null; // widget name being dragged

// Widget registry: name → title + async renderer that fills a body div.
// `description` is a one-line, plain-text (no ph: marker) summary shown only
// in the widget picker modal, the on-dashboard header just uses `title`.
const DASH_WIDGETS = {
  stats: { title: "ph:chart-bar Stats", description: "Note count, tags, categories and other totals at a glance.", render: renderStatsWidget },
  streak: { title: "ph:flame Streak", description: "How many days in a row you've added or edited a note.", render: renderStreakWidget },
  art: { title: "ph:palette Notebook constellation", description: "A generative starfield: one cluster per category, sized by note count.", render: renderArtWidget },
  //: The key stays `pinned`, it is a stored widget id, and renaming it would
  //: silently drop the widget off every dashboard that has it turned on. Only
  //: what a person reads changes, which is the half that was inconsistent:
  //: the sidebar and the note cards call this Favourites.
  pinned: { title: "ph:star Favourites", description: "Notes you've starred, so they're always one click away.", render: renderPinnedWidget },
  "recent-notes": { title: "ph:clock Recently added", description: "The last few notes you created, newest first.", render: renderRecentNotesWidget },
  "most-used": { title: "ph:flame Most used", description: "The categories and tags you reach for most often.", render: renderMostUsedWidget },
  "most-linked": { title: "ph:link Most-linked notes", description: "The notes with the most connections, the hubs of your notebook.", render: renderMostLinkedWidget },
  "top-tags": { title: "ph:tag Top tags", description: "Your most-used tags, ranked by how many notes carry them.", render: renderTopTagsWidget },
  questions: { title: "ph:chat-circle Recent questions", description: "The questions you've recently asked the notebook's chat.", render: renderQuestionsWidget },
  "on-this-day": { title: "ph:calendar-blank On this day", description: "What you wrote on this date in earlier months and years.", render: renderOnThisDayWidget },
  digest: { title: "ph:newspaper Weekly digest", description: "A short roundup of what you wrote and did this week.", render: renderDigestWidget },
  capture: { title: "ph:pencil-simple Quick capture", description: "A one-line box to jot a note without leaving the dashboard.", render: renderQuickCaptureWidget },
  reminders: { title: "ph:alarm Reminders", description: "Upcoming and overdue reminders, soonest first.", render: renderRemindersWidget },
  focus: { title: "ph:timer Focus timer", description: "A start/stop timer for focused writing sessions.", render: renderFocusTimerWidget },
  heatmap: { title: "ph:calendar-check Activity heatmap", description: "A calendar-style heatmap of note activity over the past months.", render: renderHeatmapWidget },
  "tag-cloud": { title: "ph:cloud Tag cloud", description: "All your tags sized by how often they're used.", render: renderTagCloudWidget },
  categories: { title: "ph:folders Categories", description: "Every category with its note count, click to filter.", render: renderCategoriesWidget },
  //: The key stays `random`, it is a stored widget id and renaming it would
  //: drop the widget off every dashboard that has it turned on. What it does
  //: changed (WORLD_CLASS_PLAN 15, I4): over ten notes it shows the three
  //: notes furthest out of reach, ranked by age, links and opens, with the
  //: reason on each card; under ten it still shuffles, because "the three
  //: most faded" out of five notes is the same three for ever.
  random: { title: "ph:dice-five Rediscover", description: "The notes slipping out of reach: old, unlinked and unopened, with the reason for each.", render: renderRandomNoteWidget },
  //: **Four surfaces the dashboard could not see at all.**
  //:
  //: Every widget above this line reads notes. But a notebook here is also
  //: boards, documents, and the state a note is *in*, and the dashboard is
  //: the one screen meant to answer "what is going on in here", so a feature
  //: with no widget is a feature the dashboard is blind to. Audited against
  //: the tab bar rather than brainstormed: Boards & maps, Documents, and the
  //: two things about notes that nothing surfaced (which ones still have work
  //: left in them, and which ones are stranded).
  boards: { title: "ph:squares-four Boards & maps", description: "Your most recent whiteboards and concept maps, with a miniature of each.", render: renderBoardsWidget },
  documents: { title: "ph:file-text Recent documents", description: "The documents you last edited, newest first.", render: renderDocumentsWidget },
  unfinished: { title: "ph:check-square-offset Unfinished", description: "Notes with checklist items you haven't ticked off yet.", render: renderUnfinishedWidget },
  orphans: { title: "ph:link-break Loose ends", description: "How much of your notebook is connected to anything, and the oldest notes that aren't.", render: renderOrphanNotesWidget },
  //: Deliberately a doorway rather than a live reading. Every other widget
  //: here answers from data already loaded; this one's answer costs a model
  //: pass over pairs of notes, so rendering the dashboard must not start one.
  tensions: { title: "ph:scales Tensions", description: "Find where your notes contradict each other, a decision reversed, a date that moved, a view you changed.", render: renderTensionsWidget },
  //: **What a notebook can tell you that a to-do list cannot:** whether you
  //: are actually writing. Answered entirely from `allEntries`, which is
  //: already loaded, no request, no model. (Its sibling idea, what you
  //: were thinking about on this date in earlier years, turned out to
  //: already exist as `on-this-day` above under a different key; reported
  //: directly as two identical widgets in the picker, "on-this-day" kept
  //: since it was the original and removing `onthisday` here needed no
  //: layout migration: `dashLayout()` already drops any saved id that
  //: isn't in this object.)
  pace: { title: "ph:chart-line-up Writing pace", description: "How many words you have written each day this fortnight.", render: renderPaceWidget },
};

//: Widgets that are the wrong shape in one column, so they start in two.
//:
//: The owner: "the heatmap on the dashboard is a little small." Measured at
//: 1440x900, and it is arithmetic rather than taste: the widget column is
//: 306px, a year is 53 columns of squares, and at a 3px gap the gaps alone
//: eat 156px of the 306, leaving **2.8px per cell**. A year of activity is
//: supposed to be a shape you read at a glance and that is a texture. In a
//: full-width section the same grid gets 1408px and its cells hit the 12px
//: cap, which is the size GitHub's own is drawn at.
//:
//: Applied only when the saved layout widens *nothing*, so it is a default
//: rather than an override: the moment anyone presses "Wide" or "Narrow" on
//: any widget, their list wins and this is never consulted again.
const DASH_DEFAULT_WIDE = ["heatmap"];

function dashLayout() {
  const saved = (prefsCache && prefsCache.dashboard_layout) || {};
  const order = [...(saved.order || [])];
  for (const name of Object.keys(DASH_WIDGETS)) {
    if (!order.includes(name)) order.push(name); // new widgets append
  }
  // Older layouts stored this as {name: "wide"}, fold those in so a saved
  // layout still works.
  const legacyWide = Object.keys(saved.sizes || {}).filter((n) => saved.sizes[n] === "wide");
  return {
    order: order.filter((n) => DASH_WIDGETS[n]),
    hidden: saved.hidden || [],
    wide: saved.wide?.length
      ? saved.wide
      : (legacyWide.length ? legacyWide : DASH_DEFAULT_WIDE.filter((n) => DASH_WIDGETS[n])),
  };
}

async function saveDashLayout(layout) {
  prefsCache = await apiJson("/preferences", {
    method: "PUT",
    body: JSON.stringify({ dashboard_layout: layout }),
  }).catch(() => prefsCache);
}

// Add/remove and wide/narrow, factored out of the inline "Edit layout" grid
// so the widget-picker modal (dash-widgets-dialog) can flip the same
// `dashboard_layout` preference instead of growing a second copy of this
// logic. Both surfaces call these, then re-render themselves.
async function toggleDashWidgetHidden(name) {
  const next = dashLayout();
  next.hidden = next.hidden.includes(name)
    ? next.hidden.filter((n) => n !== name)
    : [...next.hidden, name];
  await saveDashLayout(next);
}

async function toggleDashWidgetWide(name) {
  const next = dashLayout();
  next.wide = next.wide.includes(name)
    ? next.wide.filter((n) => n !== name)
    : [...next.wide, name];
  await saveDashLayout(next);
}
// --- dashboard welcome banner ------------------------------------------------
// A few phrasings per time of day so the greeting feels alive. The choice is
// keyed to the day + time-block, so it changes occasionally rather than
// flickering on every re-render.
const GREETINGS = {
  morning: ["Good morning", "Morning", "Rise and shine", "A fresh start"],
  afternoon: ["Good afternoon", "Afternoon", "Hope today's going well"],
  evening: ["Good evening", "Evening", "Winding down"],
  night: ["Still up", "Working late", "Burning the midnight oil"],
};

function greetingBlock(hour) {
  if (hour < 5) return "night";
  if (hour < 12) return "morning";
  if (hour < 18) return "afternoon";
  if (hour < 23) return "evening";
  return "night";
}

// The local fallback phrase, used until (or instead of) an AI-written one.
function fallbackGreetingPhrase(now = new Date()) {
  const options = GREETINGS[greetingBlock(now.getHours())];
  // Same greeting for a whole block on a given day, then it moves on.
  const daySlot = Math.floor(now.getTime() / 86400000) + now.getHours();
  return options[daySlot % options.length];
}

// The name always comes from preferences, never from the model, so it can't
// be mangled or hallucinated, and editing it takes effect immediately. The
// terminal mark goes on last so the result reads as a proper sentence:
// "Rise and shine" + ", Sam" + "!" → "Rise and shine, Sam!"
function withDisplayName(phrase, punctuation = ".", appendName = true) {
  const name = ((prefsCache && prefsCache.display_name) || "").trim();
  const mark = ".!?".includes(punctuation) ? punctuation : ".";
  // Also sentence-cased here, so an older cached greeting written by the model
  // in lowercase corrects itself on the next render.
  const opener = phrase ? phrase.charAt(0).toUpperCase() + phrase.slice(1) : phrase;
  // Don't append when the server says the greeting already handles the name, 
  // either the model wove it in, or this one is deliberately nameless. The
  // text check is a belt-and-braces guard against a stale cache.
  const already =
    !appendName ||
    (name && new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(opener));
  if (!name || already) return `${opener}${mark}`;
  return `${opener}, ${name}${mark}`;
}

function dashboardGreetingText(now = new Date()) {
  return withDisplayName(fallbackGreetingPhrase(now), ".");
}

// A cached AI greeting, refreshed once per time-block per day so it changes
// occasionally rather than on every render (and doesn't hammer the model).
function greetingCacheSlot(now = new Date()) {
  // Refreshed hourly, so the banner keeps changing through the day instead of
  // repeating the same line for a whole morning. The name is part of the slot
  // too: renaming yourself in Settings invalidates the cached greeting so the
  // AI writes a fresh one addressed to the new name.
  const name = ((prefsCache && prefsCache.display_name) || "").trim();
  return `${now.toDateString()}|${now.getHours()}|${name}`;
}

function cachedGreetingPhrase(now = new Date()) {
  try {
    const cached = JSON.parse(localStorage.getItem("greetingCache") || "null");
    if (cached && cached.slot === greetingCacheSlot(now) && cached.phrase) {
      return {
        phrase: cached.phrase,
        punctuation: cached.punctuation || ".",
        appendName: cached.appendName !== false,
      };
    }
  } catch {
    /* a corrupt cache just means we fetch a fresh one */
  }
  return null;
}

// Ask the AI for this block's greeting. Silent by design: any failure simply
// leaves the handwritten fallback on screen. `forced` skips the cache check, 
// used by the Settings "Regenerate" button (asked for directly) so a click
// gets a genuinely new line instead of the one already cached for this hour.
async function refreshAiGreeting(forced = false) {
  const now = new Date();
  if (!forced && cachedGreetingPhrase(now)) return; // still fresh for this block
  const block = greetingBlock(now.getHours());
  const body = await apiJson(`/insights/greeting?block=${block}`, { silent: true }).catch(
    () => null
  );
  const phrase = body && body.greeting;
  if (!phrase) return false;
  const punctuation = (body && body.punctuation) || ".";
  const appendName = !(body && body.append_name === false);
  localStorage.setItem(
    "greetingCache",
    JSON.stringify({ slot: greetingCacheSlot(now), phrase, punctuation, appendName })
  );
  const el = $("dash-greeting");
  if (el) el.textContent = withDisplayName(phrase, punctuation, appendName);
  return true;
}

let dashClockTimer = null;

function startDashClock() {
  if (dashClockTimer) clearInterval(dashClockTimer);
  // Nothing to tick for while nobody can see it. The repaint on return is
  // what makes stopping safe: resuming on the next tick would leave the time
  // it stopped at on screen for up to a second, which on a clock is the one
  // place a person notices.
  if (document.hidden) return;
  dashClockTimer = setInterval(paintDashClock, 1000);
}

document.addEventListener("visibilitychange", () => {
  // Only while the dashboard is actually drawn: `paintDashClock` returns at
  // once when its two elements are not in the page, but an interval started
  // on every tab would still be an interval.
  if (!$("dash-clock-time")) return;
  if (document.hidden) {
    if (dashClockTimer) clearInterval(dashClockTimer);
    dashClockTimer = null;
    return;
  }
  paintDashClock();
  startDashClock();
});

function paintDashClock() {
  const timeEl = $("dash-clock-time");
  const dateEl = $("dash-clock-date");
  if (!timeEl || !dateEl) return;
  const now = new Date();
  timeEl.textContent = now.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  dateEl.textContent = now.toLocaleDateString([], {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

// A short line about the notebook, note count, plus whatever's most
// worth surfacing right now (due reminders, then a capture streak).
async function renderDashSubmessage() {
  const el = $("dash-submessage");
  if (!el) return;
  const [stats, reminders] = await Promise.all([
    apiJson("/insights/stats").catch(() => null),
    // To the end: `/reminders` is `due_at` ascending, so a first page of
    // old, ticked-off rows would hide everything upcoming from this count
    // (`agent-remaining/list-paging.md`).
    apiPagedList("/reminders", 200).catch(() => []),
  ]);
  const bits = [];
  if (stats) {
    const n = stats.total_entries;
    bits.push(n === 0 ? "Your notebook is empty, capture a thought to begin" : `You have ${n} note${n === 1 ? "" : "s"}`);
  }
  const due = (reminders || []).filter(
    (r) => !r.done && new Date(r.due_at) <= new Date()
  ).length;
  if (due) bits.push(`${due} reminder${due === 1 ? "" : "s"} due`);
  else {
    const open = (reminders || []).filter((r) => !r.done).length;
    if (open) bits.push(`${open} reminder${open === 1 ? "" : "s"} coming up`);
  }
  if (stats && stats.per_day) {
    // Current capture streak, counting back from today.
    let streak = 0;
    for (let i = stats.per_day.length - 1; i >= 0 && stats.per_day[i] > 0; i--) streak++;
    if (streak > 1) bits.push(`${streak}-day capture streak`);
  }
  el.textContent = bits.join(" · ");
}

function renderDashboardGreeting() {
  const el = $("dash-greeting");
  if (!el) return;
  // Paint instantly from the cache (or the handwritten fallback), then let an
  // AI-written phrase replace it in the background if one arrives.
  const cached = cachedGreetingPhrase();
  el.textContent = cached
    ? withDisplayName(cached.phrase, cached.punctuation, cached.appendName)
    : dashboardGreetingText();
  refreshAiGreeting().catch(() => {});
  renderNameNudge(el);
  // Drawn here rather than at startup: renderEmblem reads the current accent,
  // so it has to be redrawn when the dashboard repaints after a theme change.
  // It also can't be sized while the tab is display:none, p5 measures zero , 
  // which is why this sits in the dashboard's own render and not in init.
  renderEmblem($("dash-hero-emblem"), 46, { animate: true });
  paintDashClock();
  // One ticking clock, however many times the dashboard re-renders, and none
  // at all while the tab is hidden. It paints HH:MM, so a hidden tab was
  // waking the process once a second to write the string that was already
  // there, for as long as the app stayed open (WORLD_CLASS_PLAN section 10,
  // F6: "0 timers while hidden"). Measured with a wrapped `setInterval`: two
  // one-second intervals survived hiding, this one and app.js's `tickClocks`.
  startDashClock();
  renderDashSubmessage().catch(() => {});
}

// The greeting can address you by name, but the setting for it is one field
// among a dozen in Preferences, so for most people it is simply never found,
// and the greeting looks like it just doesn't do that (user-reported). One
// quiet offer beside the greeting, only while no name is set, and it stops
// asking the moment you either set one or dismiss it.
function renderNameNudge(greetingEl) {
  const existing = document.getElementById("dash-name-nudge");
  if (existing) existing.remove();
  const name = ((prefsCache && prefsCache.display_name) || "").trim();
  if (name || localStorage.getItem("nameNudgeDismissed") === "1") return;

  const wrap = document.createElement("span");
  wrap.id = "dash-name-nudge";
  wrap.className = "name-nudge";
  const add = document.createElement("button");
  add.type = "button";
  add.className = "ghost small";
  setLabel(add, "ph:hand-waving Add your name");
  add.title = "Let the greeting call you by name";
  add.addEventListener("click", async () => {
    await openSettingsModal("preferences");
    const field = $("pref-display-name");
    field.focus();
    field.select();
  });
  const dismiss = document.createElement("button");
  dismiss.type = "button";
  dismiss.className = "ghost small";
  dismiss.textContent = "✕";
  dismiss.title = "Don't ask again";
  dismiss.setAttribute("aria-label", "Dismiss the name suggestion");
  dismiss.addEventListener("click", () => {
    localStorage.setItem("nameNudgeDismissed", "1");
    wrap.remove();
  });
  wrap.append(add, dismiss);
  greetingEl.after(wrap);
}
// --- masonry packing for the dashboard ---------------------------------------
// CSS grid can't size rows to content per-column, so each card is given a row
// span matching its measured height. Short widgets then stack vertically
// inside a row instead of being stretched to match the tallest one.

let dashResizeObserver = null;

function sizeDashWidget(card, rowUnit, gap) {
  // Measure the card's natural height, not its current grid-constrained one.
  const previous = card.style.gridRowEnd;
  card.style.gridRowEnd = "span 1";
  const height = card.getBoundingClientRect().height;
  const span = Math.max(1, Math.ceil((height + gap) / (rowUnit + gap)));
  const next = `span ${span}`;
  if (next !== previous) card.style.gridRowEnd = next;
  else card.style.gridRowEnd = previous;
}

function sizeDashWidgets() {
  const grid = $("dash-grid");
  if (!grid) return;
  const styles = getComputedStyle(grid);
  const rowUnit = Number.parseFloat(styles.getPropertyValue("grid-auto-rows")) || 8;
  const gap = Number.parseFloat(styles.rowGap) || 16;
  for (const card of grid.querySelectorAll(".dash-widget")) {
    sizeDashWidget(card, rowUnit, gap);
  }
  grid.classList.add("spans-ready");
}

// Widget bodies fill in asynchronously, so re-measure whenever one changes
// size rather than only once at render time.
function watchDashWidgets() {
  const grid = $("dash-grid");
  if (!grid || typeof ResizeObserver === "undefined") {
    sizeDashWidgets();
    return;
  }
  dashResizeObserver?.disconnect();
  let queued = false;
  dashResizeObserver = new ResizeObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      sizeDashWidgets();
    });
  });
  for (const card of grid.querySelectorAll(".dash-widget")) {
    dashResizeObserver.observe(card);
  }
  sizeDashWidgets();
}
// --- at-a-glance strip (page furniture, not a hideable widget) ---------------

async function renderDashStats() {
  const box = $("dash-stats");
  if (!box) return;
  const [stats, reminders] = await Promise.all([
    apiJson("/insights/stats").catch(() => null),
    // To the end, same reason as the widget above.
    apiPagedList("/reminders", 200).catch(() => []),
  ]);

  const now = new Date();
  const perDay = (stats && stats.per_day) || [];
  let streak = 0;
  for (let i = perDay.length - 1; i >= 0 && perDay[i] > 0; i--) streak++;
  const thisWeek = perDay.slice(-7).reduce((sum, n) => sum + n, 0);
  const open = (reminders || []).filter((r) => !r.done);
  const due = open.filter((r) => new Date(r.due_at) <= now).length;

  const tiles = [
    // Both of these are counts of notes, so they belong on the list that
    // shows them: not on whichever Notes sub-tab happened to be open last.
    { icon: "ph:note-pencil", value: stats ? stats.total_entries : "–", label: "notes",
      go: () => { switchTab("notes"); showNotesSection("browse"); } },
    { icon: "ph:calendar", value: thisWeek, label: "this week",
      go: () => { switchTab("notes"); showNotesSection("browse"); } },
    { icon: "ph:flame", value: streak, label: streak === 1 ? "day streak" : "day streak", go: () => switchTab("dashboard") },
    {
      icon: due ? "ph:alarm" : "ph:check-circle",
      value: due || open.length,
      label: due ? "due now" : "reminders",
      go: () => switchTab("reminders"),
      alert: Boolean(due),
    },
  ];

  box.replaceChildren();
  for (const tile of tiles) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "stat-tile" + (tile.alert ? " stat-alert" : "");
    const icon = document.createElement("span");
    icon.className = "stat-icon";
    setLabel(icon, tile.icon);
    icon.setAttribute("aria-hidden", "true");
    const value = document.createElement("span");
    value.className = "stat-value";
    setLabel(value, tile.value);
    const label = document.createElement("span");
    label.className = "stat-label";
    setLabel(label, tile.label);
    button.append(icon, value, label);
    button.addEventListener("click", tile.go);
    box.appendChild(button);
  }
  //: **The four tiles and the sparkline are two independent things to
  //: render, and one throwing used to take the other down with it.**
  //: `renderDashStats` is one function with no `try` anywhere in it: an
  //: exception in the block below (a malformed `per_day` entry, a
  //: `days.join` on something unexpected) would abort the whole call
  //: after the tiles loop had already run, leaving exactly four tiles
  //: and a silently missing fifth chip -- a row that reads as "bland"
  //: with nothing in the console to say why, reported as "the section
  //: of the dashboard needs something more". The `try` below cannot make
  //: bad data good, but it stops one bar chart's problem from being the
  //: whole row's problem, and a caught failure is at least visible in
  //: the console rather than a wordless gap.
  try {

  // **The shape of the fortnight, where the empty half of the strip was.**
  // Measured before this (`scratchpad/ui-sweeps/dashstart.js`, 1440x900): the
  // four tiles used 573px of a 1408px strip and left 835px empty, which is
  // the "most of its width empty" half of INBOX 60. Four numbers cannot say
  // whether this week was one burst or seven steady days, and that is exactly
  // what the empty space had room for.
  //
  // A figure, not a control: a chip is a fact, and this is a fact. It carries
  // its own text alternative because fourteen unlabelled bars are nothing at
  // all to a screen reader.
  if (perDay.length) {
    const spark = document.createElement("div");
    spark.className = "stat-spark";
    const days = perDay.slice(-14);
    const peak = Math.max(1, ...days);
    const bars = document.createElement("div");
    bars.className = "stat-spark-bars";
    for (const count of days) {
      const bar = document.createElement("span");
      // A percentage, so the strip's own height decides how tall the chart
      // is and no number here has to know it. The floor is what keeps an
      // empty day a visible baseline rather than a gap in the row.
      bar.style.height = `${Math.max(12, Math.round((count / peak) * 100))}%`;
      bar.classList.toggle("empty", count === 0);
      bars.appendChild(bar);
    }
    const caption = document.createElement("span");
    caption.className = "stat-spark-label";
    caption.textContent = `${days.length} days`;
    spark.replaceChildren(bars, caption);
    spark.setAttribute("role", "img");
    spark.setAttribute(
      "aria-label",
      `Notes captured on each of the last ${days.length} days: ${days.join(", ")}`
    );
    box.appendChild(spark);
  }
  } catch (err) {
    console.error("dashboard sparkline failed to render", err);
  }
}

// --- dashboard quick links ---------------------------------------------------

// Anything targeting the Notes tab must name its sub-tab.
//
// The tab is split into capture / ask / browse and *remembers the last one
// used*, so "switchTab('notes') then focus" only works if you happened to
// leave it on the right section. "Search notes" was fixed after being
// reported; an audit of every button here, clicking each one from all three
// starting sections: found "New note" failing in exactly the same way from
// two of the three, with the capture box hidden and nothing focused. It is
// the most-used button on the dashboard.
// **Three groups, because there were three kinds of button pretending to be
// one.** Reported: *"can you just completely redo, improve on and expand that
// whole top section."*
//
// What was there was one grid of seven identical chips. "Graph" only changes
// which tab you are looking at; "New note" puts a cursor in an empty box;
// "Skill Clean up my tags" sends a message to a model and waits for it. Those are
// three different commitments and they were drawn the same, in one row, sorted
// by a use counter that mixed them together, so the row said nothing about
// what pressing anything in it would do, and the only way to find out was to
// press it.
//
// Now: **Start** something (an action, and the row that owns the accent),
// **Jump to** somewhere (navigation, quiet pills: nothing happens that you
// cannot undo by pressing the tab you came from), and **Run a skill** (the
// expensive one, marked Skill, and the only group that talks to the model).
//
// The use-ordering that was here stays, but it is applied *inside* Jump to
// only. That was the point of it, the middle of a navigation row is exactly
// where reordering helps and never surprises, and applying it across the
// whole strip is what let an action drift into the middle of the navigation.
const QUICK_START = [
  {
    icon: "ph:pencil-simple",
    label: "New note",
    hint: "Capture a thought: the AI files it",
    primary: true,
    run: () => {
      switchTab("notes");
      showNotesSection("capture"); // or the box you're about to focus is hidden
      $("entry-content").focus();
    },
  },
  {
    icon: "ph:chat-circle",
    label: "Ask AI",
    hint: "A question answered from your own notes",
    run: () => {
      switchTab("chat");
      $("chat-input").focus();
    },
  },
  { icon: "ph:palette", label: "Sketch", hint: "Draw something and save it as a note", run: () => openSketch() },
  {
    icon: "ph:alarm",
    label: "Remind me",
    hint: "Type it in plain English and the AI schedules it",
    run: () => {
      switchTab("reminders");
      $("reminder-magic").focus();
    },
  },
  {
    icon: "ph:microphone",
    label: "Meeting notes",
    hint: "Record something longer and file the transcript",
    run: () => openMeetingRecorder(),
  },
];

const QUICK_GO = [
  {
    icon: "ph:magnifying-glass",
    label: "Search notes",
    run: () => {
      switchTab("notes");
      // The search box lives in the "browse" sub-tab; focusing it while that
      // section is display:none silently does nothing (user-reported).
      showNotesSection("browse");
      $("note-search").focus();
    },
  },
  // **The six chips that named tabs are gone**, and the reason is the ask
  // they came from being wrong about what the row is for. It said: "a quick
  // access strip that skips three of the app's seven tabs is a strip that
  // has stopped being an index of the app", and completing the index is
  // exactly what made the Dashboard show its own navigation three times.
  // Measured on one 1440x900 screen: the tab bar, a "Start something" row of
  // five action cards, and a "Jump to" row of eight chips, six of which
  // named *the same tabs as the tab bar two inches above them*. Three ways
  // to reach the same seven places, none of them obviously the one to use, 
  // reported as "a lot of ui elements arent where they should be from a
  // learnability and ux point of view. it doesnt feel intuitive."
  //
  // What survives is what the tab bar cannot do: focus the search box,
  // open the features modal, and open the command palette (which was
  // findable only by already knowing Ctrl+K, a button is how you learn a
  // shortcut). Every tab is still one click away, in the one place that has
  // always been for tabs.
  { icon: "ph:toolbox", label: "Tools & features", run: () => openFeatures() },
  // The palette is the fastest route to anything at all, and it was findable
  // only by already knowing Ctrl+K. A button is how you learn a shortcut.
  { icon: "ph:command", label: "Commands", run: () => openPalette() },
];

// --- quick access that follows what you actually do (§36D) ------------------------
//
// These are the first thing on the first screen, and they were a fixed list
// chosen early. Someone who lives in the graph and someone who never opens it
// got the same row.
//
// The row is ordered by use now, with two fixed points: **New note stays
// first** and **Tools & features stays last**. That is deliberate: a row that
// reorders completely is a row you have to re-read every time, and the whole
// value of a fixed position is that your hand learns it. Only the middle
// moves, and only by how often you actually press it.
const QUICK_USE_KEY = "quickLinkUse";
//: How many recently-run skills get a button. Two, because they are competing
//: for the same row as the fixed actions and a skill you ran once last month
//: is not quick access to anything.
const QUICK_SKILL_SLOTS = 2;

function quickLinkUse() {
  try {
    return JSON.parse(localStorage.getItem(QUICK_USE_KEY) || "{}");
  } catch {
    return {};
  }
}

function noteQuickLinkUse(label) {
  const counts = quickLinkUse();
  counts[label] = (counts[label] || 0) + 1;
  localStorage.setItem(QUICK_USE_KEY, JSON.stringify(counts));
}

//: Skills that have actually been run, most recent first. Written by
//: `startSkill`, so it covers both the dropdown and a run the agent started
//: itself (§33): if the model keeps reaching for a skill, that is evidence it
//: belongs on the dashboard too.
const RECENT_SKILLS_KEY = "recentSkills";

//: When each of them was last run, name to ISO timestamp. A second key rather
//: than a richer `recentSkills`, and that is deliberate: the list is written
//: by three call sites and read by two, and a profile that has run a skill
//: already has an array of plain strings on disk. Changing that shape in
//: place means a migration, and the last time this list changed shape without
//: one it left a `null` in every affected profile that broke the whole
//: dashboard on load (see `noteSkillRun`). A separate map has no old shape to
//: be wrong about: a name that is missing from it simply has no time to show.
const SKILL_RUN_TIMES_KEY = "recentSkillTimes";

function skillRunTimes() {
  try {
    const stored = JSON.parse(localStorage.getItem(SKILL_RUN_TIMES_KEY) || "{}");
    return stored && typeof stored === "object" && !Array.isArray(stored) ? stored : {};
  } catch {
    return {};
  }
}

function noteSkillRun(name) {
  // **Refuse a nameless run rather than storing it.** This guard exists
  // because the absence of it cost the whole dashboard, and the failure is
  // worth recording in full because nothing about it is visible at this line.
  //
  // §88.0 fixed a call site that read `startSkill(skill.name)` where an object
  // was expected. While that bug was live, `skill` was a *string*, so
  // `skill.name` was `undefined`, and this function was called with it. That
  // alone would have been harmless, but `JSON.stringify` converts `undefined`
  // inside an array to **`null`**, so what landed in localStorage was a real
  // `null` element, not a missing one. Fixing the call site stopped new poison
  // and did nothing about the `null` already written, which persists across
  // every reload, forever, in any profile that ran a skill during that window.
  //
  // The damage then surfaced nowhere near here: `recentSkillLinks` below
  // reads that array on every dashboard render, and `withoutLeadingEmoji`
  // calls `.replace()` on the `null`. That throw propagated out of
  // `renderQuickLinks` -> `renderDashboard` -> `refreshActiveTab`, i.e. it
  // escaped *before* `grid.replaceChildren()` and the widget loop had run, so
  // the reported symptoms were "the dashboard widgets are completely broken"
  // and a toast reading "Couldn't load this tab: Cannot read properties of
  // null (reading 'replace')", two reports, one cause, neither of them
  // pointing at the skills feature that actually caused it.
  //
  // The shape CLAUDE.md names: a value that is invalid where it is *used*,
  // not where it is *set*, does its damage nowhere near the code at fault.
  if (typeof name !== "string" || !name) return;
  let recent = [];
  try {
    recent = JSON.parse(localStorage.getItem(RECENT_SKILLS_KEY) || "[]");
  } catch {
    recent = [];
  }
  recent = [name, ...recent.filter((n) => n !== name)].slice(0, 8);
  localStorage.setItem(RECENT_SKILLS_KEY, JSON.stringify(recent));
  // The time goes in beside it, pruned to the names still on the list so the
  // map cannot grow forever in a profile that tries a lot of skills.
  const times = skillRunTimes();
  times[name] = new Date().toISOString();
  for (const key of Object.keys(times)) {
    if (!recent.includes(key)) delete times[key];
  }
  localStorage.setItem(SKILL_RUN_TIMES_KEY, JSON.stringify(times));
}

//: A skill's name usually starts with its own emoji, "stethoscope Notebook health
//: check", "tag Clean up my tags", and the quick-link then put Skill in front of
//: it, so those two chips wore two icons each while every other chip in the
//: row wore one. Reported as clutter, and it was: measured at 224px and 216px
//: against 107–169px for the fixed chips, i.e. the two least important buttons
//: in the row were the two widest.
//:
//: The Skill is the one that stays, because it carries what the row does not
//: otherwise say: this chip *runs* something rather than opening a page. The
//: skill's own emoji is still on it everywhere skills are listed.
const LEADING_EMOJI = /^(\p{Extended_Pictographic}(?:️|‍\p{Extended_Pictographic})*)\s*/u;

function withoutLeadingEmoji(name) {
  // `String(...)` rather than a bare `.replace`: this is the line that threw
  // for every profile carrying the poisoned `recentSkills` entry described in
  // `noteSkillRun`, and it took the whole dashboard down with it. The write
  // guard and the read filter below both prevent that now, so this coercion is
  // the third of three, but it is the cheapest, and it is the one standing
  // between any future bad value and another blank dashboard.
  const text = String(name ?? "");
  const stripped = text.replace(LEADING_EMOJI, "");
  // A skill named with nothing but an emoji would otherwise become a blank
  // chip; keeping the original is the lesser of the two.
  return stripped.trim() || text;
}

function recentSkillLinks() {
  let recent = [];
  try {
    recent = JSON.parse(localStorage.getItem(RECENT_SKILLS_KEY) || "[]");
  } catch {
    return [];
  }
  if (!Array.isArray(recent)) return [];
  // **This filter is the repair, not just a guard.** The write side is fixed,
  // but a profile that ran a skill while the §88.0 bug was live already has a
  // `null` on disk and would keep crashing its own dashboard on every load
  // forever: a fix that only prevents new bad data would leave exactly the
  // people who hit the bug still broken. Rewriting the cleaned list back means
  // one load repairs the profile permanently.
  const clean = recent.filter((n) => typeof n === "string" && n);
  if (clean.length !== recent.length) {
    localStorage.setItem(RECENT_SKILLS_KEY, JSON.stringify(clean));
  }
  const times = skillRunTimes();
  return clean.slice(0, QUICK_SKILL_SLOTS).map((name) => ({
    icon: "ph:lightning",
    label: withoutLeadingEmoji(name),
    // **What the row was missing**, INBOX 60: a skill pill said only its own
    // name, so the row could not answer "did I already run this today?",
    // which is the question you ask before spending a model call. The other
    // two groups carry a hint each and this one carried none.
    hint: times[name] ? `Last run ${relativeTime(times[name])}` : "Not run yet on this device",
    // The full name, unaltered, is what the button remembers itself by: the
    // use counter and `runSkill` both key off it, and stripping the emoji from
    // either would silently start a second tally or fail to find the skill.
    skillName: name,
    skill: true,
    run: () => {
      const known = allSkills().find((s) => s.name === name);
      // A skill can be deleted between runs. Sending the user to the picker is
      // more use than a button that fails.
      if (known) runSkill(known);
      else switchTab("chat");
    },
  }));
}

// Navigation only: see the note on QUICK_START. Search stays first because it
// is the one entry in the row that is a *destination for anything*, and a
// fixed first position is what lets a hand learn it.
function orderedGoLinks() {
  const counts = quickLinkUse();
  const [first, ...rest] = QUICK_GO;
  // Stable sort: equal counts keep the order they were declared in, so an
  // untouched dashboard looks exactly as it always did.
  rest.sort((a, b) => (counts[b.label] || 0) - (counts[a.label] || 0));
  return [first, ...rest];
}

function quickLinkButton(link, className) {
  const button = document.createElement("button");
  button.className = className + (link.primary ? " quick-link-primary" : "");
  button.type = "button";
  // Every chip gets a title, not only the skills: the labels truncate, so
  // hovering has to be able to finish the sentence. A chip whose label fits
  // shows a tooltip repeating it, which is harmless; a chip whose label does
  // not fit and has no tooltip is a button you cannot read at all.
  button.title = link.skill
    ? `Run the skill “${link.skillName}”: it answers in the chat`
    : link.hint || link.label;
  const icon = document.createElement("span");
  icon.className = "quick-link-icon";
  setLabel(icon, link.icon);
  icon.setAttribute("aria-hidden", "true");
  const text = document.createElement("span");
  text.className = "quick-link-text";
  const label = document.createElement("span");
  label.className = "quick-link-label";
  setLabel(label, link.label);
  text.appendChild(label);
  // The hint is what turns a row of verbs into a row you can choose from
  // without pressing anything. Only the Start group carries one, the
  // navigation pills say where they go by being named after the tab, and a
  // sentence under each would be six sentences saying "goes to the tab".
  if (link.hint) {
    const hint = document.createElement("span");
    hint.className = "quick-link-hint";
    setLabel(hint, link.hint);
    text.appendChild(hint);
  }
  button.append(icon, text);
  button.addEventListener("click", () => {
    noteQuickLinkUse(link.skillName || link.label);
    link.run();
  });
  return button;
}

function launchGroup(label, className) {
  const group = document.createElement("div");
  group.className = "launch-group";
  const heading = document.createElement("p");
  heading.className = "launch-label";
  heading.textContent = label;
  const row = document.createElement("div");
  row.className = className;
  group.append(heading, row);
  return { group, row };
}

function renderQuickLinks() {
  const box = $("dash-quicklinks");
  if (!box) return;
  box.replaceChildren();

  const start = launchGroup("Start something", "launch-row launch-row-start");
  for (const link of QUICK_START) {
    start.row.appendChild(quickLinkButton(link, "quick-link quick-action"));
  }
  box.appendChild(start.group);

  const go = launchGroup("Jump to", "launch-row launch-row-go");
  for (const link of orderedGoLinks()) {
    go.row.appendChild(quickLinkButton(link, "quick-link quick-pill"));
  }
  box.appendChild(go.group);
  // Filled in when the notes arrive; see `renderContinueLink`. The row is
  // built synchronously because everything else in it is a constant, and a
  // row that waits for a fetch before drawing anything is a row that flickers
  // on every dashboard load.
  renderContinueLink(go.row);

  // The skills group is only drawn when there is a skill to put in it. An
  // empty "Run a skill" heading over one "Choose a skill…" button is a section
  // that exists to advertise itself, and this strip is already the busiest
  // thing on the page.
  const skills = recentSkillLinks();
  const skillGroup = launchGroup("Run a skill", "launch-row launch-row-skills");
  for (const link of skills) {
    skillGroup.row.appendChild(quickLinkButton(link, "quick-link quick-pill quick-link-skill"));
  }
  if (skills.length) {
    skillGroup.row.appendChild(
      quickLinkButton(
        {
          icon: "ph:lightning",
          label: "All skills…",
          hint: "Every skill, in the chat's skill picker",
          run: () => switchTab("chat"),
        },
        "quick-link quick-pill quick-link-more"
      )
    );
    box.appendChild(skillGroup.group);
  }
}

// **Continue where you left off**, the fourth thing INBOX 60 asked for. The
// navigation row is three pills wide and the strip is not: measured at 1440,
// it used 476px of 1408 and left 932px empty. The answer is not more pills
// naming tabs, which is a decision this file already took and wrote down
// above; it is the one destination the tab bar cannot offer, because it
// depends on what you were doing rather than on what the app contains.
//
// Most recently *touched*, where touching is opening or editing, and not
// created. Reported: "the opens a note you opened or edited most recently
// button doesnt update and just shows my latest note". The pill said "opened
// or edited" and ranked on `updated_at` alone, which only moves when the text
// changes, so reading an old note left this pointing at whatever was newest
// and the one case it exists for, coming back to something you were reading,
// was the one case it could not serve. `last_opened_at` is stamped by
// `GET /entries/{id}` beside the access count it already kept (routes_entries),
// and the pill takes whichever of the two is later.
async function renderContinueLink(row) {
  if (!row || !row.isConnected) return;
  let entries = [];
  try {
    entries = allEntries.length ? allEntries : await apiJson("/entries", { cacheMs: 4000 });
  } catch {
    return; // a dashboard that cannot reach the notes still draws the rest
  }
  if (!Array.isArray(entries) || !entries.length || !row.isConnected) return;
  //: Null for every note nobody has opened since the column existed, which
  //: is why this is a max rather than a preference: an old notebook would
  //: otherwise rank every one of its notes at the epoch and the pill would go
  //: blank until something was opened.
  const touched = (entry) => {
    const times = [entry.last_opened_at, entry.updated_at, entry.created_at]
      .map((value) => (value ? new Date(value).getTime() : 0))
      .filter((value) => Number.isFinite(value));
    return Math.max(0, ...times);
  };
  const newest = [...entries]
    .filter((entry) => entry && !entry.is_draft)
    .sort((a, b) => touched(b) - touched(a))[0];
  if (!newest) return;
  // One line of the note, short enough to sit in a pill beside three others.
  const preview = notePreviewText(newest.content || "").trim().slice(0, 42) || "your last note";
  //: **The note's own line is the label, not the hint.** 10-responsive.css
  //: gives this pill `flex: 2 1 0` against its neighbours' `1 1 0` and says
  //: why: "Continue is the one pill whose text is a note's own first line, so
  //: it is the one that needs room". It was not: the line was passed as the
  //: hint, and `.quick-pill .quick-link-hint { display: none }` (a pill is one
  //: line by definition) hid every pill's hint, this one included. Measured on
  //: the dashboard: a 535.1px pill holding 68.7px of centred text reading
  //: "Continue", beside three 281.4px pills. Double the width was being held
  //: for a string nothing drew.
  //:
  //: So the line goes where the width was reserved for it, and the word the
  //: label used to be becomes the tooltip, which is what a pill's explanation
  //: is for everywhere else in this row. The u-turn icon and the "Jump to"
  //: heading are what say this is a place to go back to.
  const button = quickLinkButton(
    {
      icon: "ph:arrow-u-up-left",
      label: preview,
      //: **Says the rule, not an idiom.** Asked directly: "what does left off
      //: mean?? should it be something else??" It meant "the note you edited
      //: most recently", which is a fact this pill can simply state; "where
      //: you left off" is a phrase that assumes the reader already knows the
      //: app picked a note for them, and reads as a place rather than as a
      //: note. A tooltip is where a control explains itself, so it explains.
      hint: "Opens the note you opened or edited most recently",
      run: () => flashEntry(newest.id),
    },
    "quick-link quick-pill quick-link-continue"
  );
  // First in the row: it is the only entry whose usefulness decays, and the
  // three beside it are constants that can be learned by position.
  row.prepend(button);
}

// --- the "everything this app does" browser ----------------------------------
// Grouped, searchable, and every entry either jumps you there or explains
// itself: the fastest way to discover features you didn't know existed.
function featureCatalog() {
  return [
    { group: "Capture & notes", items: [
      { name: "Capture a thought", desc: "Save anything; the AI files it into a category and suggests tags.", run: () => { switchTab("notes"); showNotesSection("capture"); $("entry-content").focus(); } },
      { name: "Templates", desc: "Start a note from a prefilled shape (journal, recipe, meeting…).", run: () => { switchTab("notes"); showNotesSection("capture"); } },
      { name: "Improve writing", desc: "Proofread, rewrite, or condense a note with AI before saving.", run: () => { switchTab("notes"); showNotesSection("capture"); } },
      // The writing room is a sub-tab of Notes and was in the palette but in
      // no catalogue row, which is the shape this audit was for: a surface
      // that shipped, got a command, and never got its line in the list of
      // what the app can do.
      { name: "Writing room", desc: "Turn rough thoughts into a drafted note, section by section.", run: () => { switchTab("notes"); showNotesSection("writing-room"); $("draft-thoughts")?.focus(); } },
      { name: "Sketch pad", desc: "Draw something and save it as a note with a caption.", run: () => openSketch() },
      { name: "Dictation", desc: "Speak a note; transcribed locally with Whisper.", run: () => { switchTab("notes"); showNotesSection("capture"); } },
      { name: "Record a meeting", desc: "Transcribe a meeting or lecture as it happens, then file the notes.", run: () => { closeFeatures(); openMeetingRecorder(); } },
      { name: "Attachments", desc: "Attach files and images to any note.", run: () => { switchTab("notes"); showNotesSection("browse"); } },
      // Beside Attachments, which is the entry a person who has files in the
      // notebook is already reading. Asked for directly: "I want an easier and
      // more accessible way to access the ocr workspace as a proper and more
      // central feature." This browser and the command palette are the app's
      // two answers to that, and the reader had been in neither.
      { name: "Page reader", desc: "Open a PDF or picture beside the text read from it, page by page.", run: () => { closeFeatures(); window.openPageReader?.(); } },
      { name: "Threads", desc: "Continue a thought to build a train of related notes.", run: () => { switchTab("notes"); showNotesSection("browse"); } },
      { name: "Note links", desc: "Type [[ to point one note at another; the link works both ways.", run: () => { switchTab("notes"); showNotesSection("capture"); } },
      { name: "Checklists", desc: "Tick items off inside a note; the dashboard tracks what is left.", run: () => { switchTab("notes"); showNotesSection("browse"); } },
      { name: "Private notes", desc: "Encrypt a note so it is readable only while the app is unlocked.", run: () => { switchTab("notes"); showNotesSection("browse"); } },
      { name: "Pins & tags", desc: "Pin important notes and organise with tags.", run: () => { switchTab("notes"); showNotesSection("browse"); } },
      { name: "Recycle bin", desc: "Deleted notes are recoverable until the bin is cleared.", run: () => { switchTab("notes"); showNotesSection("browse"); } },
    ]},
    { group: "Ask & chat", items: [
      { name: "Ask your notebook", desc: "Questions answered strictly from your own notes.", run: () => { switchTab("notes"); showNotesSection("ask"); $("question").focus(); } },
      { name: "Chat", desc: "A full conversation with your notebook, saved and resumable.", run: () => { switchTab("chat"); $("chat-input").focus(); } },
      { name: "Attach to a message", desc: "Point a message at notes, documents, files, images or a map you already have.", run: () => { switchTab("chat"); $("attach-note").click(); } },
      { name: "Saved conversations", desc: "Every chat is kept, searchable, and can be picked up later.", run: () => switchTab("chat") },
      { name: "Personas", desc: "Change the assistant's voice: Librarian, Coach, Analyst, or your own.", run: () => openSettingsModal("personas") },
      { name: "Skills", desc: "One-click requests like “Summarise my week”; can act on your notes.", run: () => openSettingsModal("skills") },
      { name: "Agent mode", desc: "Let the assistant use its tools, search your notes, open a page, create, tag, link and organise.", run: () => switchTab("chat") },
      // The popup agent has the same capability as Chat's agent mode and is
      // reachable from every tab, which is exactly why it needs a row: a chord
      // nobody has been told about is not a feature anyone has.
      { name: "Ask from anywhere", desc: "Ctrl+Shift+A opens the assistant over whatever you are working on.", run: () => { closeFeatures(); toggleAgentPalette(); } },
      { name: "What it remembers", desc: "See and edit the facts the assistant has kept about you.", run: () => openSettingsModal("memory") },
      { name: "Web search", desc: "Optional, opt-in: the one feature that goes online.", run: () => switchTab("chat") },
      { name: "Export chat", desc: "Download a conversation as Markdown.", run: () => switchTab("chat") },
      { name: "Search relevance", desc: "How strict semantic search is about what counts as a real match.", run: () => openSettingsModal("preferences", "search-relevance-group") },
    ]},
    // **Documents had no rows at all**, and the editor is one of the largest
    // surfaces in the app: blocks, an outline, breadcrumbs, a spelling and
    // style check with its own dictionary, tables, properties, block links and
    // embeds, version history. Every row below goes to the tab rather than
    // driving the editor from outside it, with two exceptions that are real
    // dialogs of their own (the dictionary and the template picker): a
    // document-scoped action with no document open is a row that does nothing.
    { group: "Documents", items: [
      { name: "New document", desc: "Long-form writing in Markdown, with live formatting as you type.", run: () => { switchTab("documents"); createDocument(); } },
      { name: "Document templates", desc: "Start from a prefilled document instead of a blank page.", run: () => { closeFeatures(); switchTab("documents"); openDocTemplateDialog(); } },
      { name: "Blocks and the “/” menu", desc: "Type / for headings, quotes, callouts, tables, columns and embeds.", run: () => switchTab("documents") },
      { name: "Outline", desc: "Every heading as a list you can jump around by, marking where you are.", run: () => { switchTab("documents"); showDocSidebarSection("outline"); } },
      { name: "Breadcrumbs", desc: "The heading trail above the text says where in the document the caret is.", run: () => switchTab("documents") },
      { name: "Find and replace", desc: "Search the document, step through matches, replace one or all.", run: () => switchTab("documents") },
      { name: "Focus mode", desc: "Hide everything but the text you are writing.", run: () => switchTab("documents") },
      { name: "Document properties", desc: "Title, tags and your own fields, stored as front matter at the top.", run: () => switchTab("documents") },
      { name: "Tables", desc: "Build and edit Markdown tables without counting pipes.", run: () => switchTab("documents") },
      { name: "Block links and embeds", desc: "Link or quote a single paragraph from anywhere, by its own short id.", run: () => switchTab("documents") },
      { name: "Backlinks", desc: "What points at this document, from notes, maps, chats and other documents.", run: () => switchTab("documents") },
      { name: "Spelling and style", desc: "Findings in the margin for spelling, repeated words and clumsy phrasing.", run: () => switchTab("documents") },
      { name: "Your dictionary", desc: "Words you have taught it, so they stop being flagged everywhere.", run: () => { closeFeatures(); openDocDictionary(); } },
      { name: "Word goal", desc: "Set a target and watch the count, reading time and structure as you write.", run: () => switchTab("documents") },
      { name: "Version history", desc: "Earlier saves of a document, with what changed, restorable.", run: () => switchTab("documents") },
      { name: "AI edit", desc: "Rewrite, shorten, translate or review a passage, with the change reviewable before it lands.", run: () => switchTab("documents") },
      { name: "Export a document", desc: "Download it as Markdown, or print it to PDF with its formatting kept.", run: () => switchTab("documents") },
    ]},
    // Boards and maps were in the same position as Documents: built, reached
    // from the Library's own sub-tab, and mentioned nowhere in the list of
    // what the app does. A map is a board (see `createConceptMap`), so the two
    // share a group rather than pretending to be separate canvases.
    { group: "Boards, maps & drawing", items: [
      { name: "New board", desc: "A whiteboard of cards, drawings, images and links you arrange yourself.", run: () => { closeFeatures(); switchTab("library"); document.querySelector('#library-subtabs button[data-target="library-view-whiteboard"]')?.click(); } },
      { name: "Concept maps", desc: "A mind map made of real notes: branches, links and a reason on each connection.", run: () => { closeFeatures(); createConceptMap(); } },
      { name: "Grow a map by keyboard", desc: "Tab adds a branch off the selected topic, Enter one beside it.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-target="library-view-whiteboard"]')?.click(); } },
      { name: "Map templates", desc: "Start a map from a shape: a decision, a project, a subject to revise.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-target="library-view-whiteboard"]')?.click(); } },
      { name: "Arrange as mind map", desc: "Re-tidy a sprawling board into a readable tree in one move.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-target="library-view-whiteboard"]')?.click(); } },
      { name: "Board overview", desc: "A miniature of the whole board, to see where you are and jump.", run: () => { closeFeatures(); if (typeof wbToggleNavigator === "function") wbToggleNavigator(true); } },
      { name: "Find a card", desc: "Search the board you are on and step through the matches.", run: () => { closeFeatures(); if (typeof wbOpenBoardSearch === "function") wbOpenBoardSearch(); } },
      { name: "The tool rail", desc: "Select, draw, shapes, text, links and images, grouped by what they do.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-target="library-view-whiteboard"]')?.click(); } },
      { name: "Context bar", desc: "The properties of whatever is selected, above the selection itself.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-target="library-view-whiteboard"]')?.click(); } },
      { name: "Export a board", desc: "Save the board, or just what you selected, as an image.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-target="library-view-whiteboard"]')?.click(); } },
    ]},
    // The Library is the app's filing cabinet and had no rows either, which
    // left six sub-tabs of real surfaces undiscoverable from here.
    { group: "Library", items: [
      { name: "Everything in one place", desc: "Notes, chats, documents, files and boards in one list you can filter.", run: () => switchTab("library") },
      { name: "Your documents", desc: "Every document, with its size, when you last touched it, and a preview.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-target="library-view-docs"]')?.click(); } },
      { name: "Images", desc: "Every picture in the notebook, with its caption and where it is used.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-media-kind="images"]')?.click(); } },
      { name: "Files", desc: "PDFs and other files, with a first-page preview and what has been read from them.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-media-kind="files"]')?.click(); } },
      { name: "Links", desc: "Bookmarks, grouped, with the page's own title and description.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-target="library-view-links"]')?.click(); } },
      { name: "AI skills", desc: "The skills you can run, what each one does, and how to add your own.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-target="library-view-skills"]')?.click(); } },
      { name: "Contents", desc: "A table of contents for the whole notebook, by category and tag.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-target="library-view-contents"]')?.click(); } },
      { name: "Where a file is used", desc: "Every file says which notes, documents and boards reference it.", run: () => { switchTab("library"); document.querySelector('#library-subtabs button[data-media-kind="files"]')?.click(); } },
    ]},
    { group: "Map & discovery", items: [
      { name: "Graph view", desc: "Your notes as a network of links, threads and similarity.", run: () => switchTab("graph") },
      { name: "Edit on the map", desc: "Click any node to edit its content and tags in place.", run: () => switchTab("graph") },
      { name: "Physics controls", desc: "Gravity and Spread sliders reshape the layout.", run: () => switchTab("graph") },
      { name: "Suggested links", desc: "The AI proposes connections between related notes.", run: () => switchTab("graph") },
      { name: "Timeline", desc: "Everything you have made, in order, as a grid or a branching line.", run: () => switchTab("timeline") },
      { name: "Zoom the timeline", desc: "By day, week, month or year, with a jump back to today.", run: () => switchTab("timeline") },
      { name: "Timeline bands", desc: "Group the timeline by category, tag or kind of thing.", run: () => switchTab("timeline") },
      { name: "On this day", desc: "Notes you captured on this date in past months resurface.", run: () => switchTab("dashboard") },
      { name: "Related notes", desc: "See notes that mean something similar to the one you're reading.", run: () => { switchTab("notes"); showNotesSection("browse"); } },
      { name: "Find on this screen", desc: "Ctrl+F searches whatever tab you are looking at.", run: () => { closeFeatures(); openGlobalFind(); } },
    ]},
    { group: "Plan & focus", items: [
      { name: "Reminders", desc: "Due dates with priority, repeats, snooze and notifications.", run: () => switchTab("reminders") },
      { name: "Magic add", desc: "Type “call mum tomorrow evening” and the AI schedules it.", run: () => { switchTab("reminders"); $("reminder-magic").focus(); } },
      { name: "Focus timer", desc: "Pomodoro-style timer with presets or your own minutes.", run: () => switchTab("dashboard") },
      { name: "Weekly digest", desc: "An AI recap of everything you saved this week.", run: () => switchTab("dashboard") },
      { name: "Tensions", desc: "Find where your notes contradict each other, a decision reversed, a date that moved.", run: () => openTensions() },
      // Resurfacing had shipped on two surfaces (the sort and the widget) and
      // was named on neither list.
      { name: "Forgotten first", desc: "Sort your notes by what is slipping out of reach: old, unlinked, unopened.", run: () => { switchTab("notes"); showNotesSection("browse"); $("note-sort").focus(); } },
      { name: "Rediscover", desc: "Three faded notes a day, with the reason each one surfaced.", run: () => switchTab("dashboard") },
      { name: "Loose ends", desc: "How much of the notebook is connected, and the oldest notes that are not.", run: () => switchTab("dashboard") },
      { name: "Unfinished", desc: "Notes with checklist items still waiting to be ticked.", run: () => switchTab("dashboard") },
      { name: "Writing pace", desc: "How many words you have written each day this fortnight.", run: () => switchTab("dashboard") },
      { name: "Activity heatmap", desc: "A year of capture activity at a glance.", run: () => switchTab("dashboard") },
      { name: "Streaks", desc: "How many days in a row you've captured something.", run: () => switchTab("dashboard") },
    ]},
    { group: "Make it yours", items: [
      { name: "Theme", desc: "Light, dark, or follow your system.", run: () => openSettingsModal("appearance") },
      { name: "Accent colour", desc: "Presets or any custom colour you like.", run: () => openSettingsModal("appearance") },
      { name: "Typography & density", desc: "Font, text size, and how roomy the layout feels.", run: () => openSettingsModal("appearance") },
      { name: "Corner rounding & glass", desc: "Tune the shape and blur of every surface.", run: () => openSettingsModal("appearance") },
      { name: "Animated background", desc: "Aurora, constellations, blobs or particles behind the app.", run: () => openSettingsModal("appearance") },
      { name: "Accessibility", desc: "High-contrast mode and reduce-motion.", run: () => openSettingsModal("appearance") },
      { name: "Custom CSS", desc: "For tinkerers: your own style overrides.", run: () => openSettingsModal("appearance") },
      { name: "Zoom the whole app", desc: "Ctrl with plus or minus scales every surface, and Ctrl+0 puts it back.", run: () => { closeFeatures(); nudgeZoom(1); } },
      { name: "Dashboard layout", desc: "Show, hide, reorder and widen widgets.", run: () => { switchTab("dashboard"); $("dash-edit").click(); } },
      // Workspaces are the top-left control every tab is filtered by, and
      // nothing in either list said they existed.
      { name: "Workspaces", desc: "Keep work, study and home in separate notebooks that share one app.", run: () => { closeFeatures(); openSpaceCreate(); } },
      { name: "Note templates", desc: "Edit the shapes a new note can start from, or write your own.", run: () => openSettingsModal("templates") },
    ]},
    { group: "Data & control", items: [
      { name: "Export", desc: "Download everything as JSON, Markdown or CSV.", run: () => openSettingsModal("data") },
      { name: "Import markdown", desc: "Bring in notes from an Obsidian-style vault.", run: () => openSettingsModal("data") },
      { name: "Backups", desc: "Snapshot your notebook and restore it later.", run: () => openSettingsModal("data") },
      { name: "Models", desc: "Choose the chat, utility and embedding models.", run: () => openSettingsModal("models") },
      { name: "AI tool permissions", desc: "Decide exactly what the assistant is allowed to do.", run: () => openSettingsModal("tools") },
      { name: "Background tasks", desc: "What the app is doing in the background, and what it has finished.", run: () => openSettingsModal("tasks") },
      { name: "Packages", desc: "The optional extras (OCR, speech, vision) and whether they are installed.", run: () => openSettingsModal("extras") },
      { name: "Account & security", desc: "Change your password, and what happens when the app locks.", run: () => openSettingsModal("account") },
      { name: "Logs", desc: "What the app and the models have been doing, in plain text.", run: () => openSettingsModal("logs") },
      { name: "Lock", desc: "Password-protect the app on shared devices.", run: () => lockNow() },
      { name: "Command palette", desc: "Ctrl/⌘-K to jump anywhere or search your notes.", run: () => { closeFeatures(); openPalette(); } },
      { name: "Keyboard shortcuts", desc: "Press ? any time for the full list.", run: () => { closeFeatures(); openShortcuts(); } },
      { name: "Help", desc: "How the parts of the app fit together, in the app itself.", run: () => openSettingsModal("help") },
      { name: "Updates", desc: "Which version you are on, and whether a newer one is out.", run: () => openSettingsModal("about") },
      { name: "Welcome tour", desc: "Replay the introduction to MemoryMap.", run: () => { closeFeatures(); openOnboarding(); } },
    ]},
  ];
}

let featureAiTools = null; // fetched once per session

async function openFeatures() {
  overlayReturnFocus = document.activeElement;
  $("features-overlay").classList.remove("hidden");
  $("features-search").value = "";
  renderFeatures("");
  $("features-search").focus();
  if (featureAiTools === null) {
    featureAiTools = await apiJson("/chat/tools").catch(() => []);
    if (!$("features-overlay").classList.contains("hidden")) {
      renderFeatures($("features-search").value);
    }
  }
}

function closeFeatures() {
  $("features-overlay").classList.add("hidden");
  overlayReturnFocus?.focus?.();
  overlayReturnFocus = null;
}

function renderFeatures(query) {
  const list = $("features-list");
  list.replaceChildren();
  const q = (query || "").trim().toLowerCase();
  const groups = featureCatalog();
  // The AI's own tools, straight from the backend registry.
  if (featureAiTools && featureAiTools.length) {
    groups.push({
      group: "What the AI can do for you",
      items: featureAiTools.map((tool) => ({
        name: tool.name.replace(/_/g, " "),
        desc: tool.description + (tool.destructive ? " (asks you to confirm first)" : ""),
        run: () => openSettingsModal("tools"),
      })),
    });
  }

  let shown = 0;
  for (const group of groups) {
    const matches = group.items.filter(
      (item) =>
        !q ||
        item.name.toLowerCase().includes(q) ||
        item.desc.toLowerCase().includes(q) ||
        group.group.toLowerCase().includes(q)
    );
    if (!matches.length) continue;
    shown += matches.length;

    const heading = document.createElement("h3");
    heading.className = "features-group";
    heading.textContent = group.group;
    list.appendChild(heading);

    for (const item of matches) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "feature-row";
      const name = document.createElement("span");
      name.className = "feature-name";
      setLabel(name, item.name);
      const desc = document.createElement("span");
      desc.className = "feature-desc muted";
      setLabel(desc, item.desc);
      row.append(name, desc);
      row.addEventListener("click", () => {
        closeFeatures();
        item.run();
      });
      list.appendChild(row);
    }
  }

  $("features-count").textContent = q
    ? `${shown} match${shown === 1 ? "" : "es"}`
    : `${shown} things MemoryMap can do`;
  if (!shown) {
    const none = document.createElement("p");
    none.className = "muted";
    none.textContent = "Nothing matches that: try another word.";
    list.appendChild(none);
  }
}

// The day-one dashboard. Deliberately a small number of real actions rather
// than a tour of everything: the widgets appear on their own as soon as there
// is something for them to hold, and that is a better demonstration than a
// description of them.
function gettingStartedCard() {
  const card = document.createElement("section");
  card.className = "card dash-widget dash-getting-started";

  const emblem = document.createElement("div");
  emblem.className = "emblem emblem-centred";
  emblem.setAttribute("aria-hidden", "true");

  const title = document.createElement("h2");
  title.textContent = "Your notebook is empty, here's the whole idea";

  const blurb = document.createElement("p");
  blurb.className = "muted";
  blurb.textContent =
    "Type a thought, and it gets filed for you. Later, ask a question in " +
    "plain English and get an answer plus the notes behind it. Everything " +
    "stays on this machine.";

  const steps = document.createElement("div");
  steps.className = "start-steps";
  const actions = [
    {
      icon: "ph:pencil-simple",
      label: "Write your first note",
      note: "Anything at all: a half sentence is fine.",
      run: () => {
        switchTab("notes");
        $("entry-content")?.focus();
      },
    },
    {
      icon: "ph:chat-circle",
      label: "Ask your notebook",
      note: "Works on keywords even with no AI running.",
      run: () => {
        switchTab("chat");
        $("chat-input")?.focus();
      },
    },
    {
      icon: "ph:backpack",
      label: "Bring notes in",
      note: "Import from a file in Settings → Import & export.",
      run: () => openSettingsModal("data"),
    },
    {
      icon: "ph:compass",
      label: "Take the tour",
      note: "Two minutes through what's here.",
      run: () => openOnboarding(),
    },
  ];
  for (const action of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "start-step";
    const icon = document.createElement("span");
    icon.className = "start-step-icon";
    setLabel(icon, action.icon);
    icon.setAttribute("aria-hidden", "true");
    const text = document.createElement("span");
    const label = document.createElement("strong");
    setLabel(label, action.label);
    const note = document.createElement("span");
    note.className = "muted";
    setLabel(note, action.note);
    text.append(label, note);
    button.append(icon, text);
    button.addEventListener("click", action.run);
    steps.appendChild(button);
  }

  const footer = document.createElement("p");
  footer.className = "muted start-footer";
  footer.textContent =
    "Your dashboard fills itself in as you go, streaks, tags, a map of your " +
    "notes and a dozen other panels appear once there's something to put in them.";

  card.append(emblem, title, blurb, steps, footer);
  return { card, mount: () => renderEmblem(emblem, 56) };
}

async function renderDashboard() {
  // The saved layout lives in preferences, after a page reload this can
  // run before startApp has fetched them, so fetch here if needed.
  if (!prefsCache) {
    prefsCache = await apiJson("/preferences").catch(() => null);
  }
  renderDashboardGreeting();
  renderDashStats().catch(() => {});
  renderQuickLinks();
  const grid = $("dash-grid");
  grid.replaceChildren();
  $("dash-hint").classList.toggle("hidden", !dashEditMode); // hint only in edit mode
  const layout = dashLayout();

  // A brand-new notebook filled this grid with a dozen cards each politely
  // saying it had nothing to show. Every message was fine on its own; together
  // they made a working app look broken on the day someone starts using it.
  // One card that says what to do instead, and only until there's anything
  // to show, which is the first note.
  // `entriesEverLoaded` and not just the length: before the first GET /entries
  // comes back these are indistinguishable, and guessing "empty" paints the
  // brand-new-notebook card over a notebook full of notes.
  if (entriesEverLoaded && !allEntries.length && !dashEditMode) {
    // The emblem draws into a canvas, which p5 can only size once the element
    // is actually in the document, rendering it while the card is still
    // detached leaves a blank gap where the mark should be.
    const { card, mount } = gettingStartedCard();
    grid.appendChild(card);
    mount();
    return;
  }

  for (const name of layout.order) {
    const hidden = layout.hidden.includes(name);
    if (hidden && !dashEditMode) continue;

    const widget = DASH_WIDGETS[name];
    const isWide = layout.wide.includes(name);
    const card = document.createElement("section");
    card.className =
      "card dash-widget" + (hidden ? " dash-hidden" : "") + (isWide ? " wide" : "");
    card.dataset.widget = name;

    const header = document.createElement("div");
    header.className = "row space-between";
    const title = document.createElement("h2");
    setLabel(title, widget.title);
    header.appendChild(title);
    if (dashEditMode) {
      const controls = document.createElement("span");
      controls.className = "entry-actions";
      // There used to be two width buttons here, side by side: this one and
      // the "▭ Wide" below, writing to `wide` and the legacy `sizes` map
      // respectively. dashLayout() only falls back to `sizes` when `wide` is
      // empty, so the legacy button appeared to work exactly once and then
      // silently stopped: and until then the row showed two controls doing
      // the same job. One control, one place it's stored.
      controls.appendChild(
        smallButton(hidden ? "ph:plus Add" : "ph:x Remove", hidden ? "Add this widget to the dashboard" : "Remove this widget from the dashboard", async () => {
          await toggleDashWidgetHidden(name);
          renderDashboard();
        })
      );
      if (!hidden) controls.appendChild(
        smallButton(
          isWide ? "ph:rows Narrow" : "ph:arrows-out-line-horizontal Wide",
          isWide ? "Show in one column" : "Span two columns",
          async () => {
            await toggleDashWidgetWide(name);
            renderDashboard();
          }
        )
      );
      //: **Reordering without a mouse.** Drag-to-reorder is the only way this
      //: grid could be arranged, and HTML5 drag-and-drop is unreachable by
      //: keyboard, unusable with a screen reader and awkward on a trackpad, 
      //: which is the whole of "a better way to manage and rearrange widgets"
      //: for anyone who does not want to drag a card across a page. Two
      //: buttons do the same job, exactly, and are also the faster way to move
      //: one widget three places up.
      if (!hidden) {
        const at = layout.order.indexOf(name);
        const move = (delta) => async () => {
          const order = [...layout.order];
          const to = at + delta;
          if (to < 0 || to >= order.length) return;
          order.splice(to, 0, ...order.splice(at, 1));
          await saveDashLayout({ ...dashLayout(), order });
          renderDashboard();
          //: Focus follows the widget, so a second press moves the same card
          //: again rather than whatever landed under the pointer.
          setTimeout(() => {
            document
              .querySelector(`[data-widget="${name}"] .dash-move-${delta < 0 ? "up" : "down"}`)
              ?.focus();
          }, 60);
        };
        const up = smallButton("ph:arrow-up", "Move this widget earlier", move(-1));
        up.classList.add("dash-move-up");
        up.disabled = at <= 0;
        const down = smallButton("ph:arrow-down", "Move this widget later", move(1));
        down.classList.add("dash-move-down");
        down.disabled = at >= layout.order.length - 1;
        controls.append(up, down);
      }
      const handle = document.createElement("span");
      handle.className = "drag-handle";
      handle.textContent = "≡ drag";
      controls.appendChild(handle);
      header.appendChild(controls);
    }
    card.appendChild(header);

    const body = document.createElement("div");
    body.className = "dash-body";
    card.appendChild(body);
    if (!hidden) {
      // Promise.resolve() so a synchronous renderer can't break the whole
      // dashboard loop, and a throwing one only spoils its own card.
      Promise.resolve()
        .then(() => widget.render(body))
        .catch(() => {
          body.textContent = "Couldn't load this widget.";
        });
    }

    // Drag to reorder (edit mode only).
    if (dashEditMode) {
      card.draggable = true;
      card.addEventListener("dragstart", () => {
        dragWidget = name;
        card.classList.add("dragging");
      });
      card.addEventListener("dragend", async () => {
        card.classList.remove("dragging");
        dragWidget = null;
        // Persist whatever order the DOM ended up in.
        const order = [...grid.querySelectorAll(".dash-widget")].map(
          (el) => el.dataset.widget
        );
        await saveDashLayout({ ...dashLayout(), order });
      });
      card.addEventListener("dragover", (e) => {
        e.preventDefault();
        if (!dragWidget || dragWidget === name) return;
        const dragged = grid.querySelector(`[data-widget="${dragWidget}"]`);
        if (!dragged) return;
        const after = [...grid.children].indexOf(card) > [...grid.children].indexOf(dragged);
        grid.insertBefore(dragged, after ? card.nextSibling : card);
      });
    }
    grid.appendChild(card);
  }
  // Pack them once the cards exist; the observer keeps it right as the
  // async widget bodies fill in.
  grid.classList.remove("spans-ready");
  watchDashWidgets();
}

// --- widget picker modal ------------------------------------------------------------
// A dedicated "Widgets" surface (roadmap §26) alongside the inline "Edit
// layout" mode: not a replacement for it. Both read/write the same
// `dashboard_layout` preference through dashLayout()/saveDashLayout() and the
// toggleDashWidget* helpers above; this modal just gives ~17 widgets a
// searchable, browsable list instead of only being reachable by scrolling
// the live grid in edit mode.

//: **A row here is a widget's *state*, not a pair of verbs.**
//:
//: Asked for: "the widgets menu and edit need a redesign". Three things were
//: wrong, and each is a semiotics problem rather than a styling one:
//:
//: 1. Wide was a **flip-label button**, it read "Wide" when narrow and
//:    "Narrow" when wide. A flip label says what pressing it will do and, at
//:    rest, says nothing about what the widget *is*; with nineteen rows you
//:    could not scan the list and see which ones span two columns. It is a
//:    two-state property, so it is now a toggle that stays pressed, with
//:    `aria-pressed` for anyone not looking at it.
//: 2. Remove sat at the same visual weight as Wide, so a destructive action
//:    and a reversible one looked identical. Remove keeps its own accent.
//: 3. **Order could only be changed by dragging the live grid**, unreachable
//:    by keyboard, and invisible from the one screen that lists every widget.
//:    Each row on the dashboard now carries move-up/move-down.
function dashWidgetToggle(label, title, pressed, onClick) {
  const button = smallButton(label, title, onClick);
  button.setAttribute("aria-pressed", String(pressed));
  button.classList.toggle("active", pressed);
  return button;
}

async function moveDashWidget(name, delta) {
  const layout = dashLayout();
  //: Reordered against the *visible* row order, not the full list: moving a
  //: widget "up" past three hidden ones looks like nothing happening.
  const visible = layout.order.filter((n) => !layout.hidden.includes(n));
  const from = visible.indexOf(name);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= visible.length) return;
  visible.splice(to, 0, ...visible.splice(from, 1));
  //: Hidden widgets keep their relative places by being appended after: they
  //: are not on the dashboard, so their order is not something the user is
  //: looking at, and preserving it means un-hiding one puts it back where it
  //: was rather than at the end.
  layout.order = [...visible, ...layout.order.filter((n) => layout.hidden.includes(n))];
  await saveDashLayout(layout);
  renderDashboard();
  renderDashWidgetsList($("dash-widgets-search").value);
}

function dashWidgetRow(name, layout, position = null) {
  const widget = DASH_WIDGETS[name];
  const hidden = layout.hidden.includes(name);
  const isWide = layout.wide.includes(name);

  const row = document.createElement("div");
  row.className = "dash-widget-row";
  row.dataset.widget = name;

  const main = document.createElement("div");
  main.className = "dash-widget-row-main";
  const title = document.createElement("div");
  title.className = "dash-widget-row-title";
  setLabel(title, widget.title);
  main.appendChild(title);
  if (widget.description) {
    const desc = document.createElement("p");
    desc.className = "dash-widget-row-desc muted";
    desc.textContent = widget.description;
    main.appendChild(desc);
  }
  row.appendChild(main);

  //: **One toggle and one icon cluster, not four boxes.** Reported as one of
  //: two dialogs that are off the modal recipe. Measured before this, on a
  //: dialog listing twenty-four widgets: four controls a row, every one of
  //: them drawing its own resting tint, so the picker rendered 96 tinted
  //: boxes and read as a wall of buttons rather than as a list of widgets.
  //: That is the "everything is a button" complaint in one surface.
  //:
  //: The shape now: "Wide" stays a labelled toggle, because it is a property
  //: of the widget and its state has to be readable without hovering, and the
  //: three verbs (up, down, add/remove) become one icon cluster at the row's
  //: end. Add/remove loses its word and keeps its name: `smallButton` puts the
  //: title on `aria-label`, so it is still announced, and the icon already
  //: carries the meaning (plus against x) that the word repeated.
  const controls = document.createElement("div");
  controls.className = "dash-widget-row-controls entry-actions";
  if (!hidden) {
    controls.appendChild(
      dashWidgetToggle(
        "ph:arrows-out-line-horizontal Wide",
        isWide ? "Spanning two columns: press to narrow" : "Span two columns",
        isWide,
        async () => {
          await toggleDashWidgetWide(name);
          renderDashboard();
          renderDashWidgetsList($("dash-widgets-search").value);
        },
      ),
    );
  }
  const cluster = document.createElement("div");
  cluster.className = "dash-widget-row-cluster";
  if (!hidden && position) {
    //: Only where they can do something: the first row's "up" and the last
    //: row's "down" are disabled rather than absent, so the control cluster
    //: keeps one width and the rows stay aligned down the list.
    const up = smallButton("ph:arrow-up", "Move up", () => moveDashWidget(name, -1));
    up.disabled = position.index === 0;
    const down = smallButton("ph:arrow-down", "Move down", () => moveDashWidget(name, 1));
    down.disabled = position.index === position.total - 1;
    for (const button of [up, down]) button.classList.add("icon-button");
    cluster.append(up, down);
  }
  const onOff = smallButton(
    hidden ? "ph:plus" : "ph:x",
    hidden ? "Add this widget to the dashboard" : "Remove this widget from the dashboard",
    async () => {
      await toggleDashWidgetHidden(name);
      renderDashboard();
      renderDashWidgetsList($("dash-widgets-search").value);
    },
  );
  onOff.classList.add("icon-button");
  //: The one row that takes something away says so in the app's own danger
  //: colour, rather than looking like the reversible toggle beside it.
  if (!hidden) onOff.classList.add("danger");
  cluster.appendChild(onOff);
  controls.appendChild(cluster);
  row.appendChild(controls);
  return row;
}

// Two groups, "On your dashboard" and "Available", rather than a single
// list with a per-row status chip: with ~17 widgets, seeing at a glance how
// many are already on the dashboard is more useful than reading each row.
//: Which shelf each widget belongs on. A map here rather than a `group:` field
//: on all twenty-five entries: the catalogue's rows are already long, and a
//: widget's *group* is a fact about this list rather than about the widget.
//: Anything unlisted falls into "other", so a widget added later still appears
//:, silently vanishing from the picker is the one failure this must not have.
const DASH_WIDGET_GROUPS = {
  stats: "overview", streak: "overview", heatmap: "overview", pace: "overview",
  digest: "overview", art: "overview",
  pinned: "notes", random: "notes", categories: "notes", "on-this-day": "notes",
  unfinished: "notes", orphans: "notes", tensions: "notes", boards: "notes",
  documents: "notes",
  capture: "doing", reminders: "doing", focus: "doing", questions: "doing",
};

const DASH_WIDGET_GROUP_LABELS = {
  overview: "How the notebook is going",
  notes: "Your notes and what is in them",
  doing: "Things to do here",
  other: "Everything else",
};

//: What the dashboard currently is, in one line, and the way back to the
//: default. A list of twenty-five toggles with no statement of the result is a
//: list you edit blind, and "reset" is the answer to the fear that stops
//: people trying any of them.
function dashWidgetsSummary(layout) {
  const row = document.createElement("div");
  row.className = "row space-between dash-widgets-summary";
  const count = layout.order.filter((name) => !layout.hidden.includes(name)).length;
  const total = Object.keys(DASH_WIDGETS).length;
  const line = document.createElement("span");
  line.className = "muted";
  line.textContent = `${count} of ${total} on your dashboard`;
  row.appendChild(line);
  const reset = smallButton(
    "ph:arrow-counter-clockwise Reset layout",
    "Put every widget back to the order and visibility it started with",
    async () => {
      const sure = await confirmDialog(
        "Reset the dashboard layout?\n\nEvery widget goes back to its original place, and the ones you removed come back. Nothing else changes.",
      );
      if (!sure) return;
      //: An empty layout is what `dashLayout()` reads as "no preference", so
      //: this is a reset rather than a second copy of the default order kept
      //: in a place that could drift from the real one.
      await saveDashLayout({ order: [], hidden: [], wide: [], sizes: {} });
      renderDashboard();
      renderDashWidgetsList($("dash-widgets-search")?.value || "");
    },
  );
  row.appendChild(reset);
  return row;
}

function renderDashWidgetsList(filterText = "") {
  const container = $("dash-widgets-list");
  container.replaceChildren();
  const layout = dashLayout();
  container.appendChild(dashWidgetsSummary(layout));
  const q = filterText.trim().toLowerCase();
  const names = Object.keys(DASH_WIDGETS).filter((name) => {
    if (!q) return true;
    //: **The description is searched too.** Reported: "I just want a better
    //: menu and way to manage the widgets." With twenty-five of them, a filter
    //: that only matches titles means you have to already know a widget is
    //: called "Rediscover" to find the one that shows you an old note, which
    //: is exactly backwards, because the reason you are in this list is that
    //: you do not know what is in it.
    const widget = DASH_WIDGETS[name];
    const haystack = `${widget.title.replace(PH_LABEL, "")} ${widget.description || ""}`;
    return haystack.toLowerCase().includes(q);
  });

  const addGroup = (label, list, ordered) => {
    if (!list.length) return;
    const heading = document.createElement("h4");
    heading.className = "dash-widgets-group-label";
    heading.textContent = `${label} (${list.length})`;
    container.appendChild(heading);
    list.forEach((name, index) => {
      //: Position is the *unfiltered* one: with a search term typed, "up"
      //: still means one place up the dashboard, not one place up the four
      //: rows that happen to match.
      const position = ordered
        ? { index: ordered.indexOf(name), total: ordered.length }
        : null;
      container.appendChild(dashWidgetRow(name, layout, position));
    });
  };
  //: The dashboard's own order, so the list reads top-to-bottom the way the
  //: page does: a picker that lists widgets in a different order from the
  //: thing it is editing makes "move up" unreadable.
  const onDashboard = layout.order.filter((n) => !layout.hidden.includes(n));
  addGroup(
    "On your dashboard",
    onDashboard.filter((n) => names.includes(n)),
    onDashboard,
  );
  //: **The rest, grouped by what they are for.** Thirteen hidden widgets in one
  //: flat list called "Available" is a wall: you scroll it once, take nothing
  //: in, and close the dialog. Four short groups are four decisions.
  const available = names.filter((n) => layout.hidden.includes(n));
  for (const [group, label] of Object.entries(DASH_WIDGET_GROUP_LABELS)) {
    addGroup(
      label,
      available.filter((n) => (DASH_WIDGET_GROUPS[n] || "other") === group),
      null,
    );
  }

  if (!names.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No widgets match that search.";
    container.appendChild(empty);
  }
}

// --- Wave J: generative art (p5.js, vendored locally) -------------------------------
// A living "constellation" of the notebook: each category becomes a
// cluster of drifting stars, more notes, more stars, connected by
// faint lines in the category's own colour. It's seeded from the real
// note counts, so the same notebook always grows the same sky (until
// you hit Regenerate). Purely decorative; nothing depends on it.

let artInstance = null; // the one live p5 instance, if any
let artNonce = 0; // bumped by "Regenerate" for a fresh arrangement
// Bumped on every startArt call. A run that finds it has changed while it was
// waiting knows it was superseded and must not mount its canvas, see the
// comment in startArt for the stacking bug this fixes (§35G).
let artRun = 0;
// Where the constellation is drawn, kept so a theme change can rebuild it.
//
// The sketch reads light-or-dark ONCE, when it is built, and paints its wash
// from that. Nothing rebuilt it when the mode changed, so toggling to dark left
// the one panel on the dashboard still wearing the light background until you
// pressed Regenerate: reported, and listed in IDEAS.md.
let artHolder = null;

// Stable 0–359 hue from a category name, so a category keeps its colour.
function hueFor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) % 360;
  }
  return hash;
}

// A deterministic seed from the category names + counts: the sky is
// stable for a given notebook, and shifts only as the notebook changes.
function artSeed(categories) {
  let seed = 1;
  for (const c of categories) {
    seed = (seed * 31 + hueFor(c.name) + c.count) % 1_000_000;
  }
  return seed;
}

function stopArt() {
  if (artInstance) {
    artInstance.remove(); // tears down the canvas + draw loop
    artInstance = null;
  }
}

// Rebuild the constellation for the mode now in force. Safe to call whenever
// the theme changes: it does nothing unless the widget is actually on screen,
// and it keeps `artNonce` so the sky stays the same arrangement, this is a
// recolour, not a reshuffle, and re-rolling someone's picture because they
// turned on dark mode would be its own bug.
function refreshArtForTheme() {
  if (!artHolder || !artHolder.isConnected) {
    artHolder = null;
    return;
  }
  startArt(artHolder);
}

function buildArtParticles(p, categories, total, width, height) {
  const groups = categories.length ? categories : [{ name: "Notes", count: 1 }];
  const particles = [];
  for (const group of groups) {
    const hue = hueFor(group.name);
    // 3 base stars, plus more for a bigger share of the notebook (capped).
    const count = Math.max(3, Math.min(16, Math.round((group.count / total) * 70) + 3));
    const cx = p.random(width * 0.15, width * 0.85);
    const cy = p.random(height * 0.2, height * 0.8);
    for (let i = 0; i < count; i++) {
      particles.push({
        baseX: cx + p.random(-46, 46),
        baseY: cy + p.random(-34, 34),
        x: 0,
        y: 0,
        phase: p.random(p.TWO_PI),
        amp: p.random(2, 9),
        size: p.random(2, 5),
        hue,
      });
    }
  }
  return particles;
}

async function renderArtWidget(body) {
  const holder = document.createElement("div");
  holder.className = "art-holder";
  body.appendChild(holder);

  // Say what the picture actually means, until now it was pretty but
  // unlabelled (user asked what the nodes represent).
  const caption = document.createElement("p");
  caption.className = "muted art-caption";
  caption.textContent =
    "Each cluster of stars is one category; the more notes it holds, the more " +
    "stars it gets. Lines link stars that drift close together.";
  body.appendChild(caption);

  const controls = document.createElement("div");
  controls.className = "row art-controls";
  controls.appendChild(
    smallButton("ph:dice-five Regenerate", "A fresh arrangement of the same notes", () => {
      artNonce += 1;
      startArt(holder);
    })
  );
  controls.appendChild(
    smallButton("ph:floppy-disk Save PNG", "Save this artwork as an image", () => {
      if (artInstance) artInstance.saveCanvas("memorymap-constellation", "png");
    })
  );
  body.appendChild(controls);

  // A colour key so each cluster is identifiable, matching the hue the
  // canvas paints each category with.
  const legend = document.createElement("div");
  legend.className = "art-legend";
  body.appendChild(legend);
  apiJson("/insights/stats")
    .then((stats) => {
      const cats = (stats.categories || []).slice(0, 8);
      legend.replaceChildren();
      for (const cat of cats) {
        const item = document.createElement("span");
        item.className = "art-legend-item";
        const dot = document.createElement("span");
        dot.className = "art-legend-dot";
        dot.style.background = `hsl(${hueFor(cat.name)}, 70%, 55%)`;
        item.append(dot, document.createTextNode(`${cat.name} · ${cat.count}`));
        legend.appendChild(item);
      }
    })
    .catch(() => {});

  return startArt(holder);
}

async function startArt(holder) {
  // Which run this is. `startArt` awaits /insights/stats before it mounts
  // anything, and `stopArt()` above that await can only remove an instance
  // that already exists: so two overlapping calls each found `artInstance`
  // null, each waited, and each mounted a canvas into the same holder. That
  // is the four-or-five stacked constellations that were screenshotted
  // (§35G), and the same bug is why Regenerate read as "broken and severely
  // glitchy": every click added a canvas and `artInstance` only ever tracked
  // the last one, so nothing could tear the others down.
  const run = ++artRun;
  stopArt();
  artHolder = holder;
  if (typeof p5 === "undefined") {
    holder.textContent = "The art library didn't load.";
    return;
  }
  const stats = await apiJson("/insights/stats").catch(() => ({
    categories: [],
    total_entries: 0,
  }));
  const categories = (stats.categories || []).slice(0, 8);
  const total = Math.max(1, stats.total_entries || 0);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // data-mode is always resolved to light or dark, including under "System",
  // so this no longer has to re-derive it from two sources.
  const dark = resolvedTheme() === "dark";
  // The wash used a hardcoded indigo hue, so on any palette that isn't
  // indigo, Sage, Ocean, Ember, the one generative panel on the dashboard
  // was the only thing on screen still wearing the old theme's colour.
  const accentHex = currentAccentHex();

  const sketch = (p) => {
    let particles = [];
    let width = 0;
    const height = 220;

    const scene = (t) => {
      // A soft vertical wash instead of a flat fill, more depth (Wave N).
      p.noStroke();
      const washHue = p.hue(p.color(accentHex));
      for (let y = 0; y < height; y += 4) {
        const shade = dark ? 14 + (y / height) * 10 : 250 - (y / height) * 10;
        p.fill(washHue, 30, shade, 1);
        p.rect(0, y, width, 4);
      }
      for (const dot of particles) {
        dot.x = dot.baseX + Math.cos(t + dot.phase) * dot.amp;
        dot.y = dot.baseY + Math.sin(t * 1.3 + dot.phase) * dot.amp;
      }
      // Faint connecting lines between nearby stars (O(n²), but n is
      // capped low enough that it stays cheap at 60fps).
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const a = particles[i];
          const b = particles[j];
          const d = p.dist(a.x, a.y, b.x, b.y);
          if (d < 70) {
            p.stroke(a.hue, 65, dark ? 72 : 55, p.map(d, 0, 70, 0.45, 0));
            p.strokeWeight(1);
            p.line(a.x, a.y, b.x, b.y);
          }
        }
      }
      // The stars themselves: a soft glow halo + a bright core, twinkling.
      p.noStroke();
      for (const dot of particles) {
        const twinkle = 0.6 + 0.4 * Math.sin(t * 2 + dot.phase);
        p.fill(dot.hue, 75, dark ? 65 : 55, 0.14 * twinkle);
        p.circle(dot.x, dot.y, dot.size * 4); // glow
        p.fill(dot.hue, 80, dark ? 78 : 48, twinkle);
        p.circle(dot.x, dot.y, dot.size); // core
      }
    };

    p.setup = () => {
      width = holder.clientWidth || 300;
      p.createCanvas(width, height);
      p.colorMode(p.HSL, 360, 100, 100, 1);
      p.randomSeed(artSeed(categories) + artNonce * 997);
      particles = buildArtParticles(p, categories, total, width, height);
      if (reduceMotion) {
        scene(0); // one still frame: no animation for reduced-motion users
        p.noLoop();
      }
    };
    p.draw = () => scene(p.frameCount * 0.005);
    // Was missing entirely: width was measured once at setup and never
    // re-synced, so this canvas was the one p5 sketch in the app with no
    // resize handling at all (the sibling in the whiteboard has its own).
    // Reported as the constellation "keeps disappearing": a second trigger
    // on top of the theme-change one ARCHITECTURE §10 already documents and
    // `refreshArtForTheme` already handles. A ResizeObserver on the holder
    // catches both a real window resize *and* the Edit-layout "Wide" toggle
    // (which changes the card's width with no window resize event at all), 
    // `p.windowResized` alone would have missed the second one entirely.
    const resync = () => {
      if (!holder.isConnected) return;
      const next = holder.clientWidth;
      // Guarded the same reason `holder.clientWidth || 300` is in setup: a
      // transient 0 mid-reflow must not shrink the canvas to nothing.
      if (!next || next === width) return;
      width = next;
      p.resizeCanvas(width, height);
      particles = buildArtParticles(p, categories, total, width, height);
    };
    const observer = new ResizeObserver(resync);
    observer.observe(holder);
    p.remove = ((original) => () => {
      observer.disconnect();
      original.call(p);
    })(p.remove);
  };

  // Superseded while we waited, or the widget was re-rendered out from under
  // us. Either way this run must not mount: it would be the second canvas.
  if (run !== artRun || !holder.isConnected) return;
  // Belt and braces. `stopArt` handles the instance we know about; clearing
  // the holder removes any canvas a previous version of this bug left behind,
  // so an already-stacked dashboard heals on the next render rather than
  // needing a reload.
  stopArt();
  holder.replaceChildren();
  artInstance = new p5(sketch, holder);
}

// Capture streak (Wave K): consecutive days up to today with at least
// one note, read from the same per-day series the stats strip uses.
async function renderStreakWidget(body) {
  const stats = await apiJson("/insights/stats");
  const perDay = stats.per_day || []; // oldest → newest, last = today

  let current = 0;
  for (let i = perDay.length - 1; i >= 0; i--) {
    if (perDay[i] > 0) current += 1;
    else break;
  }
  let longest = 0;
  let run = 0;
  for (const count of perDay) {
    run = count > 0 ? run + 1 : 0;
    longest = Math.max(longest, run);
  }

  const big = document.createElement("p");
  big.className = "dash-big";
  setLabel(big, current > 0 ? `ph:flame ${current}-day streak` : "No streak yet");
  body.appendChild(big);

  const sub = document.createElement("p");
  sub.className = "muted";
  if (current > 0) {
    sub.textContent =
      `You've captured ${current} day${current === 1 ? "" : "s"} running` +
      (longest > current ? ` · best in the last fortnight: ${longest}` : "");
  } else {
    sub.textContent = "Save a note today to start one.";
  }
  body.appendChild(sub);
}

async function renderStatsWidget(body) {
  const stats = await apiJson("/insights/stats");
  const total = document.createElement("p");
  total.className = "dash-big";
  total.textContent = `${stats.total_entries} note${stats.total_entries === 1 ? "" : "s"}`;
  body.appendChild(total);

  // Last-14-days activity strip (theme colours, height = volume).
  const strip = document.createElement("div");
  strip.className = "activity-strip";
  strip.title = "Notes captured per day, last 14 days";
  const peak = Math.max(1, ...stats.per_day);
  for (const count of stats.per_day) {
    const bar = document.createElement("span");
    bar.style.height = `${Math.max(8, (count / peak) * 34)}px`;
    bar.classList.toggle("empty", count === 0);
    bar.title = `${count} note${count === 1 ? "" : "s"}`;
    strip.appendChild(bar);
  }
  body.appendChild(strip);

  const cats = document.createElement("div");
  cats.className = "entry-meta";
  for (const category of stats.categories.slice(0, 5)) {
    cats.appendChild(chip(`${category.name} · ${category.count}`));
  }
  body.appendChild(cats);
}
// Shared by the Pinned/Most-used/Recent-notes dashboard widgets, reported
// directly for Most Used, but all three shared the same gap: `notePreviewText`
// *strips* markdown syntax down to plain readable text (no literal `**`), which
// isn't the same as *rendering* it, `**bold**` read as clean but unstyled
// "bold", not actual bold text, and an inline image showed nothing at all.
// `renderInlineMarkdown`'s own `compact` mode is exactly what a label-sized
// list row already uses everywhere else in this app for the same reason
// (link chips, the document sidebar), swap to it here too rather than the
// stripped-text path.
// First image in a note's raw markdown, if it has one and the URL is safe to
// load. `renderInlineMarkdown`'s `compact` mode (used below) deliberately
// swaps every image for its alt text, right for a label-sized chip, but a
// dashboard row has room for the real picture, so this widget-only path
// pulls the first one out for a thumbnail instead.
const FIRST_MD_IMAGE = /!\[([^\]\n]{0,200})\]\(([^)\n]{1,500})\)/;
function firstNoteImage(content) {
  const m = FIRST_MD_IMAGE.exec(content || "");
  if (!m) return null;
  const [, alt, url] = m;
  return isRenderableUrl(url) ? { alt, url } : null;
}

//: **An attached picture is a picture too.** Reported: "the widgets and other
//: things dont render attached files on notes like the recently added widget
//: and other areas in the application."
//:
//: The gap is in the model, not the markup: an image *embedded* in the note
//: text is `![](…)` and was found by `firstNoteImage` above, but an image
//: **attached** to the note (`entry.attachments`, its own table, `/files/{id}`)
//: appears nowhere in the note's markdown: so a note whose only picture was
//: attached rather than pasted rendered as a row of text with no picture at
//: all, in every widget, forever.
function noteRowImage(entry) {
  const embedded = firstNoteImage((entry.content || "").replace(/\[\[([^[\]]{1,120})\]\]/g, "$1"));
  if (embedded) return embedded;
  const attached = (entry.attachments || []).find((file) => file.is_image);
  return attached ? { alt: attached.filename || "", url: `/files/${attached.id}` } : null;
}

// The non-image half of `noteRowImage`, a note's attached PDF, spreadsheet
// or the like has nothing to thumbnail, and previously had nothing shown
// for it at all here: `miniEntryList` only ever asked `noteRowImage`, so a
// note whose only attachment was a document rendered as if it were bare
// text, indistinguishable from a note with nothing attached. Reported
// directly: "files dont render in the widgets and other areas notes are
// shown."
function noteRowFile(entry) {
  const attached = (entry.attachments || []).find((file) => !file.is_image);
  return attached ? { name: attached.filename || "", url: `/files/${attached.id}` } : null;
}

function miniEntryList(body, entries, emptyText) {
  if (!entries.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = emptyText;
    body.appendChild(p);
    return;
  }
  const ul = document.createElement("ul");
  ul.className = "dash-list";
  for (const entry of entries) {
    const li = document.createElement("li");
    // The wiki-link unwrap notePreviewText also did, renderInlineMarkdown
    // itself doesn't know `[[...]]`, only the full note-body renderer does.
    const raw = (entry.content || "").replace(/\[\[([^[\]]{1,120})\]\]/g, "$1");
    const image = noteRowImage(entry);
    if (image) {
      li.classList.add("dash-has-thumb");
      const thumb = document.createElement("img");
      thumb.src = mediaSrc(image.url);
      thumb.alt = image.alt || "";
      thumb.loading = "lazy";
      thumb.className = "dash-list-thumb";
      li.appendChild(thumb);
    }
    const file = !image && noteRowFile(entry);
    const textEl = document.createElement("span");
    textEl.className = "dash-list-text";
    // Block syntax first. renderInlineMarkdown is exactly that, INLINE, so a
    // note beginning "# Groceries" rendered the hash as literal text, which is
    // the reported "markdown still isn't rendering" on these widgets: the bold
    // and italics worked and the headings, bullets and quote marks did not, so
    // it looked like nothing was rendering at all.
    //
    // The first line becomes the row's title instead of being flattened into
    // the preview, the same shape the timeline card uses. It is what a person
    // calls the note, and without it every row in a widget starts with the
    // same three words of body text.
    const flat = raw.replace(/^\s*(?:#{1,6}\s+|>\s?|[-*+]\s+|\d+\.\s+)/gm, "").trim();
    const split = flat.indexOf("\n");
    const heading = (split === -1 ? flat : flat.slice(0, split)).trim();
    const rest = split === -1 ? "" : flat.slice(split + 1).replace(/\s+/g, " ").trim();

    if (heading) {
      const title = document.createElement("span");
      title.className = "dash-list-title";
      const cut = safeMdSlice(heading, 70);
      renderInlineMarkdown(title, cut.text, [], true);
      if (cut.truncated) title.appendChild(document.createTextNode("…"));
      textEl.appendChild(title);
    }
    if (rest) {
      const preview = document.createElement("span");
      preview.className = "dash-list-preview";
      const cut = safeMdSlice(rest, 110);
      renderInlineMarkdown(preview, cut.text, [], true);
      if (cut.truncated) preview.appendChild(document.createTextNode("…"));
      textEl.appendChild(preview);
    }
    if (file) {
      const chipEl = fileChip(file.name, file.url);
      chipEl.classList.add("dash-list-file-chip");
      textEl.appendChild(chipEl);
    }
    li.appendChild(textEl);
    li.title = "Open this note";
    li.addEventListener("click", () => flashEntry(entry.id));
    ul.appendChild(li);
  }
  body.appendChild(ul);
}

// GET /entries pages now (ENTRIES_PAGE_SIZE) rather than returning the whole
// notebook: these three widgets used to each fetch their own full copy of
// it independently, which silently would have started missing tags/notes
// past the first page on a large notebook. `allEntries` is the same data,
// already loaded by loadEntries() before any tab (including the dashboard)
// renders, and complete once its own background paging finishes, so
// preferring it is both a correctness fix and three fewer network calls.
// The fetch fallback only matters if a widget somehow renders before that
// first load, and mirrors the pattern renderRandomNoteWidget already uses.
async function renderPinnedWidget(body) {
  const entries = (
    allEntries.length ? allEntries : await apiJson("/entries", { cacheMs: 4000 })
  ).filter((e) => e.pinned);
  miniEntryList(body, entries.slice(0, 5), "Star a note and it shows up here.");
}

async function renderMostUsedWidget(body) {
  const entries = await apiJson("/entries/most-accessed");
  miniEntryList(body, entries, "Ask questions and your most-used notes appear here.");
}

// The graph tab already knows how connected every note is (edges from
// EntryLink rows plus reply threads), this just ranks by how many of those
// edges touch each note, rather than asking the user to eyeball the graph
// for its own densest cluster. Perplexity brainstorm doc review flagged the
// gap: a "most-linked notes / hub" widget was one of the few ideas the app
// didn't already have a version of.
async function renderMostLinkedWidget(body) {
  const [entries, data] = await Promise.all([
    allEntries.length ? Promise.resolve(allEntries) : apiJson("/entries", { cacheMs: 4000 }),
    apiJson("/graph").catch(() => null),
  ]);
  const degree = new Map();
  for (const edge of (data && data.edges) || []) {
    if (typeof edge.source === "number") degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
    if (typeof edge.target === "number") degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
  }
  const byId = new Map(entries.map((e) => [e.id, e]));
  const ranked = [...degree.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([id]) => byId.get(id))
    .filter(Boolean)
    .slice(0, 6);
  miniEntryList(body, ranked, "Link notes to each other and the most-connected ones show up here.");
}

async function renderRecentNotesWidget(body) {
  const entries = allEntries.length ? allEntries : await apiJson("/entries", { cacheMs: 4000 });
  const newest = [...entries].sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at)
  );
  miniEntryList(body, newest.slice(0, 6), "Your newest notes will appear here.");
}

async function renderTopTagsWidget(body) {
  const entries = allEntries.length ? allEntries : await apiJson("/entries", { cacheMs: 4000 });
  const counts = new Map();
  for (const entry of entries) {
    for (const tag of entry.tags || []) counts.set(tag, (counts.get(tag) || 0) + 1);
  }
  if (!counts.size) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "Tag some notes and your top tags show up here.";
    body.appendChild(p);
    return;
  }
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
  const cloud = document.createElement("div");
  cloud.className = "entry-meta";
  for (const [tag, count] of top) {
    const tagChip = chip(`${tag} · ${count}`, "tag", () => {
      $("note-search").value = tag;
      noteSearch = tag;
      switchTab("notes");
      renderEntries();
    });
    tagChip.title = `Show notes tagged “${tag}”`;
    cloud.appendChild(tagChip);
  }
  body.appendChild(cloud);
}

async function renderQuestionsWidget(body) {
  const questions = await apiJson("/chat/recent");
  if (!questions.length) {
    body.textContent = "Your recent questions will appear here.";
    body.classList.add("muted");
    return;
  }
  const box = document.createElement("div");
  box.className = "recent";
  for (const question of questions) {
    const chipEl = chip(question.length > 40 ? question.slice(0, 39) + "…" : question, "", () => {
      switchTab("chat");
      sendChatMessage(question);
    });
    chipEl.title = question;
    box.appendChild(chipEl);
  }
  body.appendChild(box);
}

async function renderOnThisDayWidget(body) {
  const matches = await apiJson("/insights/on-this-day");
  miniEntryList(
    body,
    matches,
    "Notes you captured on this date in past months will resurface here."
  );
}

// Weekly digest caching (Wave J follow-up). The AI digest is expensive,
// so once it's generated it STAYS until you regenerate, and it resets
// itself each day. Generation is a module-level promise, so switching
// away from the dashboard never cancels it, whenever it finishes, the
// result is cached and shown next time the widget is on screen.
const DIGEST_KEY = "digestCache";
let digestPromise = null; // the in-flight generation, shared across renders

function todayStamp() {
  return new Date().toISOString().slice(0, 10);
}

function loadDigestCache() {
  try {
    const cached = JSON.parse(localStorage.getItem(DIGEST_KEY) || "null");
    if (cached && cached.date === todayStamp()) return cached.text; // fresh today
  } catch {
    /* corrupt cache: ignore and regenerate */
  }
  return null;
}

// Kicks off (or reuses) one generation. Caches the result for today,
// unless the server says it isn't cacheable (e.g. Ollama was offline).
// Streams the digest, calling onDelta with each chunk so the widget can show
// words as they arrive rather than a spinner. Resolves with the full text.
function generateDigest(onDelta) {
  if (!digestPromise) {
    digestPromise = streamDigest(onDelta)
      .then((result) => {
        if (result.cacheable !== false) {
          localStorage.setItem(
            DIGEST_KEY,
            JSON.stringify({ text: result.text, date: todayStamp() })
          );
        }
        return result.text;
      })
      .finally(() => {
        digestPromise = null;
      });
  }
  return digestPromise;
}

async function streamDigest(onDelta) {
  const response = await api("/insights/digest/stream", { method: "POST" });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let text = "";
  let cacheable = true;
  // NDJSON: one JSON object per line, same shape as the chat stream.
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      let event;
      try {
        event = JSON.parse(line);
      } catch {
        continue; // a partial line: the next chunk completes it
      }
      if (event.type === "answer") {
        text += event.delta;
        if (onDelta) onDelta(text);
      } else if (event.type === "done") {
        cacheable = event.cacheable !== false;
      }
    }
  }
  return { text, cacheable };
}

async function renderDigestWidget(body) {
  const showDigest = (text) => {
    const out = document.createElement("div");
    renderMarkdown(out, text);
    const controls = document.createElement("div");
    controls.className = "row";
    controls.appendChild(
      smallButton("ph:arrows-clockwise Regenerate", "Rebuild this week's digest now", () => {
        localStorage.removeItem(DIGEST_KEY);
        runGeneration();
      })
    );
    body.replaceChildren(out, controls);
  };

  const runGeneration = () => {
    const thinking = document.createElement("p");
    thinking.className = "muted";
    // One indicator, one sentence, in both motion modes.
    thinking.append(typingLine("Thinking about your week…"));
    body.replaceChildren(thinking);
    // Live-render the text as it streams in; the dots stay until the first
    // token arrives, then the words take over.
    const live = document.createElement("div");
    let started = false;
    generateDigest((soFar) => {
      if (!body.isConnected) return;
      if (!started) {
        started = true;
        body.replaceChildren(live);
      }
      renderMarkdown(live, soFar);
      body.scrollTop = body.scrollHeight;
    })
      .then((text) => {
        // The widget may have been left/re-rendered while we waited, 
        // only paint if this exact body is still on screen.
        if (body.isConnected) showDigest(text);
      })
      .catch((error) => {
        if (!body.isConnected) return;
        const retry = smallButton(
          "Generate this week's digest",
          "",
          runGeneration,
          false
        );
        body.replaceChildren(retry);
        toast(error.message, true);
      });
  };

  const cached = loadDigestCache();
  if (cached !== null) {
    showDigest(cached); // today's digest, kept until you regenerate
  } else if (digestPromise) {
    runGeneration(); // one is already running (from before a tab switch)
  } else {
    const generate = smallButton("Generate this week's digest", "", runGeneration, false);
    // Built dynamically, so it can't live in AI_ONLY_CONTROLS, mark it here
    // instead. A dashboard button that only fails once you press it is exactly
    // the thing that makes the app feel broken when the AI simply isn't on.
    if (modelStatus && modelStatus.ollama_running === false) {
      generate.disabled = true;
      generate.classList.add("ai-unavailable");
      generate.title = "The weekly digest is written by the local AI, start Ollama to generate one.";
    }
    body.appendChild(generate);
  }
}

async function renderQuickCaptureWidget(body) {
  const textarea = document.createElement("textarea");
  textarea.rows = 2;
  // Don't promise AI filing when there's no AI to do it; the note still saves.
  textarea.placeholder =
    modelStatus && modelStatus.ollama_running === false
      ? "Type a thought and press Save."
      : "Type a thought and press Save, the AI files it.";
  const row = document.createElement("div");
  row.className = "row";
  const status = document.createElement("span");
  status.className = "status";
  row.appendChild(
    smallButton("Save", "", async () => {
      const content = textarea.value.trim();
      if (!content) return;
      status.textContent = "Filing…";
      try {
        const saved = await apiJson("/entries", {
          method: "POST",
          body: JSON.stringify({ content, tags: [] }),
        });
        status.textContent = `Filed under “${saved.category}”.`;
        textarea.value = "";
        loadEntries();
      } catch (error) {
        status.textContent = error.message;
      }
    }, false)
  );
  row.appendChild(status);
  body.append(textarea, row);
}

async function renderRemindersWidget(body) {
  // To the end before filtering: taking four open ones out of a first page
  // that happens to be all done would show "no open reminders" to someone who
  // has plenty.
  const reminders = (await apiPagedList("/reminders", 200)).filter((r) => !r.done).slice(0, 4);
  if (!reminders.length) {
    body.textContent = "No open reminders: add one in the Reminders tab.";
    body.classList.add("muted");
    return;
  }
  const ul = document.createElement("ul");
  ul.className = "dash-list";
  for (const reminder of reminders) {
    const li = document.createElement("li");
    const due = new Date(reminder.due_at);
    li.textContent = `${reminder.text}: ${due.toLocaleString()}`;
    if (due < new Date()) li.classList.add("overdue");
    li.addEventListener("click", () => switchTab("reminders"));
    ul.appendChild(li);
  }
  body.appendChild(ul);
}

// --- activity heatmap (a year of capture activity, GitHub-style) ------------

async function renderHeatmapWidget(body) {
  const data = await apiJson("/insights/heatmap").catch(() => null);
  if (!data) {
    body.textContent = "Couldn't load your activity.";
    body.classList.add("muted");
    return;
  }
  if (!data.total) {
    body.textContent = "Save some notes and your activity shows up here.";
    body.classList.add("muted");
    return;
  }

  const grid = document.createElement("div");
  grid.className = "heatmap";
  body.appendChild(grid);

  //: **Full size, full year, scrolled rather than shrunk.** The first
  //: version of this widget shrank its cells to fit whatever width the
  //: widget had (reported "the heatmap on the dashboard is a little
  //: small" at 2.7px cells), and the fix after that kept the cells at
  //: their real size by showing fewer weeks instead, so nothing ever
  //: scrolled. Reported again, 2026-09-09: "the whole thing fits into the
  //: small not wide dashboard, it looked better bigger and scrolled to the
  //: right" -- a year read a glance at a time is still the point, but the
  //: owner's own preference is the wider, scrollable shape over the
  //: cropped one, so this reverses the second fix and keeps the first: the
  //: whole year at `--heat-cell-max` (03-dashboard-widgets.css sets the
  //: grid's own columns to that width now, rather than a `1fr` this
  //: function used to divide up), the grid scrolls horizontally
  //: (`.heatmap`'s `overflow-x: auto`), and it opens scrolled to today
  //: (below) rather than to the oldest day, so the crop this replaces is
  //: not missed on first paint.
  function paint() {
    grid.replaceChildren();
    const counts = data.counts;
    const start = new Date(`${data.start}T00:00:00`);
    // Pad so each column is a whole week starting on Sunday.
    const lead = start.getDay();
    for (let i = 0; i < lead; i++) {
      const blank = document.createElement("span");
      blank.className = "heat-cell heat-blank";
      grid.appendChild(blank);
    }
    counts.forEach((count, index) => {
      const cell = document.createElement("span");
      // Five buckets, scaled against the busiest day so quiet notebooks
      // still show contrast.
      const level = count === 0 ? 0 : Math.min(4, Math.ceil((count / data.busiest) * 4));
      cell.className = `heat-cell heat-${level}`;
      const day = new Date(start);
      day.setDate(day.getDate() + index);
      cell.title = `${day.toLocaleDateString()}, ${count} note${count === 1 ? "" : "s"}`;
      grid.appendChild(cell);
    });
    // The grid runs oldest → newest, so the interesting end is the right
    // one. Start scrolled there instead of making the user drag across
    // empty squares to find today.
    requestAnimationFrame(() => {
      grid.scrollLeft = grid.scrollWidth;
    });
  }

  //: No `ResizeObserver` any more: the grid's own width no longer decides
  //: how many weeks are drawn (the column width is fixed in CSS), so a
  //: widget resize has nothing left for a repaint to change.
  paint();

  const legend = document.createElement("div");
  legend.className = "heat-legend muted";
  const less = document.createElement("span");
  less.textContent = "Less";
  legend.appendChild(less);
  for (let level = 0; level <= 4; level++) {
    const swatch = document.createElement("span");
    swatch.className = `heat-cell heat-${level}`;
    legend.appendChild(swatch);
  }
  const more = document.createElement("span");
  more.textContent = "More";
  legend.appendChild(more);
  body.appendChild(legend);

  const summary = document.createElement("p");
  summary.className = "muted";
  summary.textContent = `${data.total} notes in the last year · busiest day ${data.busiest}`;
  body.appendChild(summary);
}

// --- category breakdown ------------------------------------------------------

async function renderCategoriesWidget(body) {
  const stats = await apiJson("/insights/stats").catch(() => null);
  const categories = (stats && stats.categories) || [];
  if (!categories.length) {
    body.textContent = "Save a few notes and your categories appear here.";
    body.classList.add("muted");
    return;
  }
  const max = categories[0].count || 1;
  const list = document.createElement("div");
  list.className = "cat-bars";
  for (const { name, count } of categories.slice(0, 8)) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "cat-row";
    row.title = `Show the ${name} notes`;
    const label = document.createElement("span");
    label.className = "cat-name";
    label.textContent = name;
    const track = document.createElement("span");
    track.className = "cat-track";
    const fill = document.createElement("span");
    fill.className = "cat-fill";
    fill.style.width = `${Math.max(6, (count / max) * 100)}%`;
    track.appendChild(fill);
    const num = document.createElement("span");
    num.className = "cat-count";
    num.textContent = count;
    row.append(label, track, num);
    row.addEventListener("click", () => {
      activeCategory = name;
      draftsOnly = false;
      switchTab("notes");
      renderEntries();
      renderSidebar();
    });
    list.appendChild(row);
  }
  body.appendChild(list);
}

// A plain char-count slice can land inside an unclosed `![alt](url` or
// `[text](url`, the truncated tail then has no closing `)`, so INLINE_MD
// never matches it and it prints as literal markdown source instead of
// rendering (or vanishing) as intended. Reported live as "the Rediscover
// widget doesn't render images or sketches", plausible root cause: a
// sketch note is a caption plus `![...](...)`, and the reference is exactly
// what a mid-string cut most often lands inside. Backs the cut up to just
// before the last unclosed `[`/`![` before the limit, if there is one.
function truncateMarkdownSafe(text, limit) {
  if (text.length <= limit + 1) return text;
  let cut = limit;
  const openBracket = text.lastIndexOf("[", cut);
  if (openBracket !== -1) {
    const closeParen = text.indexOf(")", openBracket);
    if (closeParen === -1 || closeParen >= cut) {
      cut = text[openBracket - 1] === "!" ? openBracket - 1 : openBracket;
    }
  }
  return text.slice(0, cut).trimEnd() + "…";
}

// --- rediscover a random note ------------------------------------------------

async function renderRandomNoteWidget(body) {
  // **Scored, not random, once there is enough notebook to score.**
  // WORLD_CLASS_PLAN 15, I4: a notebook that only ever shows you what you
  // just wrote is a diary, and the thing a notebook can do that a pile of
  // files cannot is bring back the note you would never have thought to look
  // for. The backend (`ai/resurface.py`) ranks by three facts a person can
  // check, age, links and opens, and this is the surface the plan asks for.
  //
  // The random pick below is kept, not replaced, and it is the right answer
  // for a small notebook: `MIN_NOTEBOOK` in resurface.py refuses to rank at
  // all under ten notes, because "the three most faded" out of five notes is
  // the same three for ever, which teaches people to ignore the panel. So
  // `/resurface` answers with nothing there and this falls through to the
  // shuffle, which is what that size actually wants.
  const cards = await apiJson("/resurface?limit=3", { silent: true, cacheMs: 30000 }).catch(() => null);
  const items = (cards && cards.items) || [];
  if (items.length) {
    paintFadedNotes(body, items);
    return;
  }
  await renderRandomShuffle(body);
}

// Three notes slipping out of reach, each with the reason it was chosen and
// a way to say "never again". The dismissal is a correction
// (`POST /learned/corrections`), the same store the filing and search
// corrections use, so sending a card away is a decision the notebook keeps
// rather than a thirty-second reprieve.
function paintFadedNotes(body, items) {
  body.replaceChildren();
  const list = document.createElement("div");
  list.className = "faded-list";
  for (const item of items) {
    const card = document.createElement("div");
    card.className = "faded-card";

    const title = document.createElement("button");
    title.type = "button";
    title.className = "linklike faded-title";
    title.textContent = item.title || "Untitled note";
    title.title = "Open this note in the Notes tab";
    title.addEventListener("click", () => flashEntry(item.id));
    card.appendChild(title);

    if (item.reason) {
      const why = document.createElement("p");
      why.className = "muted faded-why";
      // The facts, not the score: "120 days old, no links, never opened" is
      // checkable and "0.82" is not.
      why.textContent = item.reason;
      card.appendChild(why);
    }

    const dismiss = smallButton("ph:x Never again", "Stop showing this note here", async () => {
      dismiss.disabled = true;
      try {
        await apiJson("/learned/corrections", {
          method: "POST",
          body: JSON.stringify({ kind: "dismiss_resurface", subject: { entry_id: item.id } }),
        });
        card.remove();
        // Emptied by dismissals: ask again rather than leaving a blank panel,
        // the next three are already ranked.
        if (!list.querySelector(".faded-card")) renderRandomNoteWidget(body);
      } catch (error) {
        dismiss.disabled = false;
      }
    });
    dismiss.classList.add("faded-dismiss");
    card.appendChild(dismiss);
    list.appendChild(card);
  }
  body.appendChild(list);
}

async function renderRandomShuffle(body) {
  const entries = allEntries.length
    ? allEntries
    : await apiJson("/entries", { cacheMs: 4000 }).catch(() => []);
  if (!entries.length) {
    body.textContent = "Save some notes and one will resurface here.";
    body.classList.add("muted"); // not `className +=`, which stacks on re-render
    return;
  }

  // "Another" has to actually show another one.
  //
  // Reported as broken, and it was: the pick was uniform over every note
  // WITH REPLACEMENT, so it could hand back the note already on screen and
  // the click did nothing. That is not rare, it is 1 in N, so a tenth of
  // clicks on a ten-note notebook, half of them on two notes, and every
  // single one when there is only one note to show. Excluding the current
  // note makes the button keep its promise.
  let current = null;

  const paint = () => {
    body.replaceChildren();
    const pool = entries.filter((e) => e.id !== (current && current.id));
    const note = (pool.length ? pool : entries)[
      Math.floor(Math.random() * (pool.length || entries.length))
    ];
    current = note;
    // Rendered as markdown, like every other place a note's text is shown.
    // It was `textContent`, so a note written with a heading, a list or any
    // emphasis surfaced here as its raw source, `## Schedule` and `**bold**`
    // spelled out: which makes the one widget whose whole job is to make an
    // old note appealing show it at its least readable.
    //
    // A <div>, not a <p>: renderMarkdown appends block elements, and a <p>
    // containing a <ul> is invalid markup that browsers fix by closing the
    // paragraph early, which drops the styling this class carries.
    const text = document.createElement("div");
    text.className = "random-note";
    renderMarkdown(text, truncateMarkdownSafe(note.content, 239));
    body.appendChild(text);

    // A sketch's picture is never in `note.content` at all: the sketch pad
    // saves a caption as the note's text and the drawing as a real
    // Attachment (saveSketch), a completely different mechanism from a
    // pasted/dropped image's inline `![](...)`. Any renderer that only
    // reads content, this one included, showed nothing for a sketch note, 
    // "the widget doesn't render... sketches", reported directly. Same
    // .attachment-thumb treatment the note-card list already gives an
    // attached image, so a sketch resurfaced here looks the way it does
    // everywhere else.
    const images = (note.attachments || []).filter((a) => a.is_image);
    if (images.length) {
      const row = document.createElement("div");
      row.className = "entry-links";
      for (const attachment of images) {
        const wrap = document.createElement("span");
        wrap.className = "thumb-wrap";
        const img = document.createElement("img");
        img.className = "attachment-thumb";
        img.alt = attachment.filename;
        img.title = `${attachment.filename}: click to view full size`;
        attachmentObjectUrl(attachment)
          .then((url) => (img.src = url))
          .catch(() => wrap.remove());
        img.addEventListener("click", () => {
          openLightbox(
            images.map((a) => ({ filename: a.filename, getUrl: () => attachmentObjectUrl(a) })),
            images.indexOf(attachment)
          );
        });
        wrap.appendChild(img);
        row.appendChild(wrap);
      }
      body.appendChild(row);
    }

    const meta = document.createElement("div");
    meta.className = "entry-meta";
    meta.appendChild(chip(note.category || "Uncategorised", "tag"));
    const when = document.createElement("span");
    when.className = "entry-date";
    when.textContent = new Date(note.created_at).toLocaleDateString();
    meta.appendChild(when);
    body.appendChild(meta);

    const row = document.createElement("div");
    row.className = "row";
    const another = smallButton("ph:dice-five Another", "Show a different note", paint);
    if (entries.length < 2) {
      // There is no other note to show. A live-looking button that cannot do
      // anything is the exact shape of "this control is broken", say why
      // instead.
      another.disabled = true;
      another.title = "This is your only note so far, write another and it'll shuffle.";
    }
    row.appendChild(another);
    row.appendChild(
      smallButton("ph:note-pencil Open", "Open this note in the Notes tab", () => flashEntry(note.id))
    );
    body.appendChild(row);
  };
  paint();
}

// --- weighted tag cloud ------------------------------------------------------

async function renderTagCloudWidget(body) {
  const tags = await apiJson("/insights/tag-cloud").catch(() => []);
  if (!tags.length) {
    body.textContent = "Tag some notes and your cloud grows here.";
    body.classList.add("muted");
    return;
  }
  const max = tags[0].count || 1;
  const cloud = document.createElement("div");
  cloud.className = "tag-cloud";
  for (const { tag, count } of tags) {
    // Font size scales with frequency (0.8rem – 1.7rem).
    const weight = count / max;
    const item = chip(tag, "tag", () => {
      $("note-search").value = tag;
      noteSearch = tag;
      switchTab("notes");
      renderEntries();
    });
    item.style.fontSize = `${(0.8 + weight * 0.9).toFixed(2)}rem`;
    item.style.opacity = String(0.55 + weight * 0.45);
    item.title = `${count} note${count === 1 ? "" : "s"} tagged “${tag}”`;
    cloud.appendChild(item);
  }
  body.appendChild(cloud);
}

// --- focus timer (dashboard widget) -----------------------------------------
// State lives at module level so it keeps running while the widget re-renders
// (e.g. when you switch away and back to the dashboard).
let focusTimer = { remaining: 0, total: 25 * 60, running: false, handle: null };

function focusTimeLabel(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function paintFocusTimer() {
  const display = $("focus-timer-display");
  if (display) {
    const shown = focusTimer.remaining || focusTimer.total;
    display.textContent = focusTimeLabel(shown);
  }
  const toggle = $("focus-timer-toggle");
  if (toggle) toggle.textContent = focusTimer.running ? "Pause" : "Start";
}

function focusTimerTick() {
  if (focusTimer.remaining > 0) {
    focusTimer.remaining -= 1;
    paintFocusTimer();
    if (focusTimer.remaining === 0) {
      stopFocusTimer();
      toast("Focus session complete: nice work!");
      notify("MemoryMap", "Focus session complete: nice work!");
    }
  }
}

function startFocusTimer() {
  if (focusTimer.running) return;
  if (focusTimer.remaining <= 0) focusTimer.remaining = focusTimer.total;
  focusTimer.running = true;
  askNotificationPermission();
  focusTimer.handle = setInterval(focusTimerTick, 1000);
  paintFocusTimer();
}

function stopFocusTimer() {
  focusTimer.running = false;
  if (focusTimer.handle) clearInterval(focusTimer.handle);
  focusTimer.handle = null;
  paintFocusTimer();
}

function setFocusTimer(minutes) {
  stopFocusTimer();
  focusTimer.total = Math.max(1, Math.round(minutes)) * 60;
  focusTimer.remaining = 0;
  paintFocusTimer();
}

// async to match the widget contract in renderDashboard (render() must
// return a promise).
async function renderFocusTimerWidget(body) {
  const display = document.createElement("div");
  display.id = "focus-timer-display";
  display.className = "focus-timer-display";
  body.appendChild(display);

  const presets = document.createElement("div");
  presets.className = "row focus-presets";
  for (const mins of [5, 15, 25]) {
    presets.appendChild(smallButton(`${mins}m`, `${mins} minutes`, () => setFocusTimer(mins)));
  }
  const custom = document.createElement("input");
  custom.type = "number";
  custom.min = "1";
  custom.max = "180";
  custom.placeholder = "min";
  custom.className = "focus-custom";
  custom.setAttribute("aria-label", "Custom minutes");
  custom.addEventListener("change", () => {
    const value = Number(custom.value);
    if (value >= 1) setFocusTimer(value);
  });
  presets.appendChild(custom);
  body.appendChild(presets);

  const controls = document.createElement("div");
  controls.className = "row";
  const toggle = smallButton("Start", "Start or pause the timer", () => {
    if (focusTimer.running) stopFocusTimer();
    else startFocusTimer();
  }, false);
  toggle.id = "focus-timer-toggle";
  const reset = smallButton("Reset", "Reset the timer", () => {
    focusTimer.remaining = 0;
    stopFocusTimer();
  });
  controls.append(toggle, reset);
  body.appendChild(controls);

  paintFocusTimer();
}

// --- wiring (moved out of app.js's own wiring block, §88.3) -----------------------
//
// These two listener groups used to sit inside app.js's general wiring, far
// from the code they drive (the same "scattered, not one block" shape the
// roadmap warned about). Moving only the function *definitions* out and
// leaving these `addEventListener` calls behind in app.js would have been
// the exact hazard documents.js's split found: `$("features-close")
// .addEventListener("click", closeFeatures)` passes `closeFeatures` as a
// bare identifier, resolved the moment this line runs, and this line runs
// at app.js's own top-level, parse-time pass, before dashboard.js (loaded
// after app.js) has defined it. Left behind, that throws `ReferenceError`
// and aborts the rest of app.js's synchronous top-level code, same as
// `initDocSidebarTabs()` did. The other listeners here wrap their calls in
// arrow functions, which resolve the name lazily at click time rather than
// at registration time, so they were never actually at risk, but keeping
// the whole related group together here is clearer than splitting it by
// which handlers happen to be safe.
$("dash-edit").addEventListener("click", () => {
  dashEditMode = !dashEditMode;
  $("dash-edit").textContent = dashEditMode ? "Done" : "Edit layout";
  renderDashboard();
});
// Widget picker modal (roadmap §26): a dedicated surface alongside "Edit
// layout" above, not a replacement for it.
$("dash-widgets-open").addEventListener("click", () => {
  $("dash-widgets-search").value = "";
  renderDashWidgetsList();
  $("dash-widgets-dialog").showModal();
});
$("dash-widgets-search").addEventListener("input", (e) => renderDashWidgetsList(e.target.value));
// Tools & features browser (opened from the dashboard quick links).
$("features-close").addEventListener("click", closeFeatures);
$("features-search").addEventListener("input", (e) => renderFeatures(e.target.value));
wireBackdropClose($("features-overlay"), () => closeFeatures());

// --- The four widgets for what the dashboard could not previously see -------
//
// Registered in DASH_WIDGETS above, where the reasoning for the set lives.
// All four follow the shape every widget here already uses: an async function
// taking the widget's own `body` element, reading `allEntries` or one cached
// `apiJson`, and rendering an empty state that says what to do rather than
// "no data".

/** A row that opens something other than a note, styled like `.dash-list`. */
function dashActionRow(ul, { title, meta, onOpen, hint, thumb, chip = null }) {
  const li = document.createElement("li");
  if (thumb) {
    li.classList.add("dash-has-thumb");
    li.appendChild(thumb);
  }
  const text = document.createElement("span");
  text.className = "dash-list-text";
  //: `chip` stands in for the plain title when the row is a thing the app has
  //: a chip for: a mind map, so far. Not *beside* the title: the chip already
  //: carries the title, and drawing both would say the same words twice on one
  //: row. The chip passed here is the non-interactive form (`mapChip`'s own
  //: comment says why), because this `<li>` is already `role="button"`.
  const titleEl = chip || document.createElement("span");
  if (!chip) {
    titleEl.className = "dash-list-title";
    titleEl.textContent = title;
  }
  text.appendChild(titleEl);
  if (meta) {
    const metaEl = document.createElement("span");
    metaEl.className = "dash-list-preview";
    metaEl.textContent = meta;
    text.appendChild(metaEl);
  }
  li.appendChild(text);
  li.title = hint || "Open";
  // A row that does something is a control, so it answers to the keyboard and
  // announces itself as one, `li.addEventListener("click")` alone (the shape
  // `miniEntryList` uses) is invisible to a screen reader and unreachable by
  // Tab.
  li.tabIndex = 0;
  li.setAttribute("role", "button");
  const go = () => onOpen();
  li.addEventListener("click", go);
  li.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      go();
    }
  });
  ul.appendChild(li);
}

function dashEmpty(body, text) {
  const p = document.createElement("p");
  p.className = "muted";
  p.textContent = text;
  body.appendChild(p);
}

async function renderBoardsWidget(body) {
  // Every board, not the first page: the widget ranks them by how much is on
  // them, and the busiest board is not necessarily on page one. No `cacheMs`
  // with it: `apiPagedList` goes through `api`, which has no read cache, so
  // the option would have read as a cache that was never there. One widget
  // asks for this list, once per dashboard render, which is what the four
  // seconds were protecting `/entries` from and this list does not need.
  const boards = await apiPagedList("/whiteboard/boards", 200, { silent: true }).catch(() => null);
  const usable = (boards || []).filter((b) => (b.node_count + b.sketch_count + (b.object_count || 0)) > 0);
  if (!usable.length) {
    dashEmpty(body, "Draw a board or build a concept map and it will show up here.");
    return;
  }
  // Busiest first. `GET /whiteboard/boards` has no updated_at to sort on, and
  // "the board with the most on it" is a better answer than "whichever row
  // the database returned first", which is what an unsorted list would be.
  const ranked = [...usable]
    .sort(
      (a, b) =>
        b.node_count + b.sketch_count + (b.object_count || 0) -
        (a.node_count + a.sketch_count + (a.object_count || 0)),
    )
    .slice(0, 5);
  const ul = document.createElement("ul");
  ul.className = "dash-list";
  for (const board of ranked) {
    dashActionRow(ul, {
      title: board.title,
      // `mapCountLabel` (app.js) rather than three lines here. The three lines
      // it replaces called a map's objects "images", which is the wrong noun
      // for the only thing on a map, the Library card had already been fixed
      // and this copy had not, which is precisely what §5 item 12 is about.
      meta: mapCountLabel(board),
      hint: board.type === "map" ? "Open this map" : "Open this board",
      thumb: dashBoardThumb(board),
      // `openWhiteboardBoard` handles the tab and sub-tab switch itself.
      onOpen: () => openWhiteboardBoard(board.id),
      // **A map says it is one, in the row.** The row's title is a bare
      // string, so before this a map and a whiteboard were the same row with
      // different words in it. `mapChip` is the app's one map chip, so this
      // reads identically to a map in a note, on the timeline and in the chat.
      chip: board.type === "map" ? mapChip(board, { count: false, interactive: false }) : null,
    });
  }
  body.appendChild(ul);
}

/**
 * The same miniature the Library's board cards draw, at widget-row size.
 *
 * **One renderer, not two.** This used to be its own 20-line copy that drew
 * `preview_items` and nothing else, no `preview_edges`, so a map in the
 * dashboard previewed as a scatter of dots while the identical map in the
 * Library previewed as a tree. Structure is the entire difference between a
 * map and a board, so the one place it was missing was the one place it
 * mattered. `mapPreview` (app.js) is now the only place this picture exists;
 * MINDMAP_PLAN.md §5 item 12 asked for exactly that.
 */
function dashBoardThumb(board) {
  // Never null now: an empty board draws the designed empty state rather than
  // leaving the row without its left rail (see mapPreview). The guard stays
  // for a caller that hands this a board object it does not have yet.
  const svg = mapPreview(board, { size: "row" });
  if (!svg) return null;
  // The row's own thumbnail classes, on top of the shared `.board-minimap`
  // ones: sizing belongs to the row, the drawing belongs to the map.
  svg.classList.add("dash-list-thumb", "dash-board-thumb");
  return svg;
}

async function renderDocumentsWidget(body) {
  // `GET /documents` is already ordered by updated_at descending, so the
  // newest-edited are simply the first rows, no client-side sort needed.
  const docs = await apiJson("/documents", { cacheMs: 4000, silent: true }).catch(() => null);
  if (!docs || !docs.length) {
    dashEmpty(body, "Write or import a document and the ones you edited last show up here.");
    return;
  }
  const ul = document.createElement("ul");
  ul.className = "dash-list";
  for (const doc of docs.slice(0, 6)) {
    const words = doc.words ? `${doc.words.toLocaleString()} word${doc.words === 1 ? "" : "s"}` : "Empty";
    dashActionRow(ul, {
      title: doc.title || "Untitled document",
      meta: `${words} · ${dashRelativeTime(doc.updated_at)}`,
      hint: "Open this document",
      onOpen: () => {
        switchTab("documents");
        openDocument(doc.id);
      },
    });
  }
  body.appendChild(ul);
}

/** "3 days ago" from an ISO timestamp, with a plain date once it is old. */
function dashRelativeTime(iso) {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  const seconds = Math.max(0, (Date.now() - when.getTime()) / 1000);
  if (seconds < 90) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days <= 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  return when.toLocaleDateString();
}

//: A markdown task line: `- [ ]` / `* [x]` / `1. [ ]`, with the loose leading
//: whitespace real notes actually contain. Deliberately anchored per line
//: with `m` rather than scanning the whole body, so an indented sub-task
//: counts and a literal "[ ]" mid-sentence does not.
const DASH_OPEN_TASK = /^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[[ \t]\]/gm;
const DASH_DONE_TASK = /^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[[xX]\]/gm;

async function renderUnfinishedWidget(body) {
  const entries = allEntries.length ? allEntries : await apiJson("/entries", { cacheMs: 4000 });
  const withTasks = [];
  for (const entry of entries) {
    const content = entry.content || "";
    if (!content.includes("[")) continue; // cheap reject before two regexes
    // `lastIndex` is shared state on a `g` regex, so these must be reset per
    // note or every second note silently scores zero, the classic one.
    DASH_OPEN_TASK.lastIndex = 0;
    DASH_DONE_TASK.lastIndex = 0;
    const open = (content.match(DASH_OPEN_TASK) || []).length;
    if (!open) continue;
    const done = (content.match(DASH_DONE_TASK) || []).length;
    withTasks.push({ entry, open, done });
  }
  if (!withTasks.length) {
    dashEmpty(body, "Nothing outstanding. Checklists you write as “- [ ] something” appear here until they are ticked.");
    return;
  }
  // Closest to finished first: a list with one box left is the one worth
  // showing, not the one someone has barely started.
  withTasks.sort((a, b) => a.open - b.open || b.done - a.done);
  const ul = document.createElement("ul");
  ul.className = "dash-list";
  for (const row of withTasks.slice(0, 6)) {
    const first = (row.entry.content || "").split("\n").find((line) => line.trim())?.trim() || "Untitled note";
    const total = row.open + row.done;
    dashActionRow(ul, {
      title: first.replace(/^#{1,6}\s+/, "").slice(0, 70),
      meta: `${row.open} left of ${total}`,
      hint: "Open this note",
      onOpen: () => flashEntry(row.entry.id),
    });
  }
  body.appendChild(ul);
}

async function renderOrphanNotesWidget(body) {
  const [entries, graph] = await Promise.all([
    allEntries.length ? Promise.resolve(allEntries) : apiJson("/entries", { cacheMs: 4000 }),
    apiJson("/graph", { cacheMs: 4000, silent: true }).catch(() => null),
  ]);
  // The same degree map `renderMostLinkedWidget` builds, read for its zeroes
  // instead of its peaks.
  const linked = new Set();
  for (const edge of (graph && graph.edges) || []) {
    if (typeof edge.source === "number") linked.add(edge.source);
    if (typeof edge.target === "number") linked.add(edge.target);
  }
  // A board is a note by construction here, and an empty canvas is not a
  // stranded thought. Drafts have not been filed yet by definition.
  const real = entries.filter((e) => !e.is_board && !e.is_draft);
  // **Category is deliberately not part of this test, and that is a measured
  // decision rather than an oversight.** The first cut of this widget counted
  // a note as stranded only if it had no links, no tags *and* no category, 
  // and it could never fire, because this app files every note as it is
  // saved: on a real 116-note notebook, 116 had a category. A field the app
  // fills in for you says nothing about whether *you* connected anything.
  //
  // Tags and links are the two a person actually chooses, so those are the
  // test. On that same notebook 99 of 116 notes qualified, which is why this
  // is not the list of them it started as. A widget that lists 85% of your
  // notes has told you nothing and made you scroll; the number *is* the
  // finding, so the number leads, and only a handful of oldest offenders come
  // with it as somewhere to actually start.
  const loose = real.filter((entry) => !linked.has(entry.id) && !(entry.tags || []).length);
  if (!real.length) {
    dashEmpty(body, "Write a few notes and this will show how well connected they are.");
    return;
  }
  const connected = real.length - loose.length;
  const pct = Math.round((connected / real.length) * 100);

  const summary = document.createElement("p");
  summary.className = "dash-loose-summary";
  summary.textContent = loose.length
    ? `${loose.length} of ${real.length} notes have no link and no tag.`
    : `All ${real.length} notes have a link or a tag.`;
  body.appendChild(summary);

  // A meter, not a decorative bar: it carries its own value for a screen
  // reader, which a styled div cannot.
  const meter = document.createElement("div");
  meter.className = "dash-loose-meter";
  meter.setAttribute("role", "meter");
  meter.setAttribute("aria-valuemin", "0");
  meter.setAttribute("aria-valuemax", "100");
  meter.setAttribute("aria-valuenow", String(pct));
  meter.setAttribute("aria-label", `${pct}% of notes are connected`);
  const fill = document.createElement("div");
  fill.className = "dash-loose-fill";
  // A width has to be a real number here, and CSP forbids a `style`
  // attribute: a custom property set through the CSSOM is neither.
  fill.style.setProperty("--dash-loose-pct", `${pct}%`);
  meter.appendChild(fill);
  body.appendChild(meter);

  const caption = document.createElement("p");
  caption.className = "muted dash-loose-caption";
  caption.textContent = `${pct}% connected`;
  body.appendChild(caption);

  if (!loose.length) return;

  // **The widget that names the problem offers the thing that fixes it.**
  // The auto-linker lives as "Suggest links" in the Graph tab's toolbar,
  // among the graph's own display options, so the one screen that tells you
  // most of your notebook is unconnected had no way to act on it, and the
  // feature that would has to be found first. `loadLinkSuggestions` renders
  // into the Graph tab's own panel, so this switches there and runs it rather
  // than duplicating the list here.
  const connect = document.createElement("button");
  connect.type = "button";
  connect.className = "ghost small dash-loose-action";
  const connectIcon = document.createElement("i");
  connectIcon.className = "ph ph-link ph-lead";
  connectIcon.setAttribute("aria-hidden", "true");
  connect.append(connectIcon, "Find links to add");
  connect.title = "Look for notes worth connecting, and approve them one by one";
  connect.addEventListener("click", () => {
    switchTab("graph");
    // The tab switch renders asynchronously; the suggestions panel it draws
    // into has to exist before it is filled.
    setTimeout(() => loadLinkSuggestions(), 120);
  });
  body.appendChild(connect);
  // Oldest first: a note written this morning has not had a chance to be
  // filed yet, and nagging about it is how a hygiene widget becomes noise.
  const oldest = [...loose].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  miniEntryList(body, oldest.slice(0, 3), "");
}


/**
 * The Tensions doorway.
 *
 * Explains the idea and opens the review; it does **not** run one. Every
 * other widget renders from `allEntries` or one cached fetch, and a widget
 * that quietly started a model pass over the notebook every time the
 * dashboard drew would be the most expensive thing on the page.
 */
async function renderTensionsWidget(body) {
  const [entries, graph] = await Promise.all([
    allEntries.length ? Promise.resolve(allEntries) : apiJson("/entries", { cacheMs: 4000 }),
    apiJson("/graph", { cacheMs: 4000, silent: true }).catch(() => null),
  ]);
  // Already-accepted tensions are the one part that *is* cheap to show: they
  // are ordinary links with a type, so the graph already carries them.
  const accepted = ((graph && graph.edges) || []).filter((e) => e.link_type === "contradicts").length;

  const blurb = document.createElement("p");
  blurb.className = "muted";
  blurb.textContent = accepted
    ? `${accepted} place${accepted === 1 ? "" : "s"} where your notes contradict each other.`
    : "Nothing here can tell you where you changed your mind, until you look.";
  body.appendChild(blurb);

  const explain = document.createElement("p");
  explain.className = "muted dash-tension-explain";
  explain.textContent =
    "Similar-notes search finds what belongs together. This reads pairs with your local model and looks for the opposite: claims that can't both be right.";
  body.appendChild(explain);

  const open = document.createElement("button");
  open.type = "button";
  open.className = "ghost small";
  const icon = document.createElement("i");
  icon.className = "ph ph-scales ph-lead";
  icon.setAttribute("aria-hidden", "true");
  open.append(icon, entries.length < 2 ? "Nothing to compare yet" : "Review disagreements");
  open.disabled = entries.length < 2;
  open.addEventListener("click", () => openTensions());
  body.appendChild(open);
}

//: **On this day.** A notebook accumulates, and the thing that makes years of
//: it worth having is being handed a page from one of them without asking.
//: Same date, earlier years and earlier months, months as well as years,
//: because a notebook two months old would otherwise never show anything and
//: an empty widget teaches you to remove it.
function renderOnThisDayWidget(body) {
  const now = new Date();
  const day = now.getDate();
  const month = now.getMonth();
  const thisYear = now.getFullYear();
  const entries = (typeof allEntries !== "undefined" ? allEntries : []).filter((entry) => {
    const at = new Date(entry.created_at);
    if (Number.isNaN(at.getTime())) return false;
    if (at.getDate() !== day) return false;
    //: A different year on the same date, or an earlier month this year. Today
    //: itself is excluded: "on this day" that returns what you wrote an hour
    //: ago is a mirror, not a memory.
    if (at.getFullYear() !== thisYear) return true;
    return at.getMonth() !== month;
  });
  if (!entries.length) {
    return dashEmpty(
      body,
      "Nothing from this date yet. Come back when the notebook is a few months older."
    );
  }
  entries.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  //: Grouped by when, because "two years ago" is the fact that makes the row
  //: worth reading and a bare list of notes buries it.
  const seen = new Set();
  const shown = [];
  for (const entry of entries) {
    const at = new Date(entry.created_at);
    const years = thisYear - at.getFullYear();
    const key = years > 0 ? `${years}y` : `${month - at.getMonth()}m`;
    if (seen.has(key)) continue;
    seen.add(key);
    shown.push({ entry, when: years > 0
      ? `${years} year${years === 1 ? "" : "s"} ago`
      : `${month - at.getMonth()} month${month - at.getMonth() === 1 ? "" : "s"} ago` });
    if (shown.length >= 4) break;
  }
  const list = document.createElement("ul");
  list.className = "dash-list";
  for (const { entry, when } of shown) {
    const li = document.createElement("li");
    li.setAttribute("role", "button");
    li.tabIndex = 0;
    const stamp = document.createElement("span");
    stamp.className = "chip dash-onthisday-when";
    stamp.textContent = when;
    const text = document.createElement("span");
    text.className = "dash-list-text";
    renderInlineMarkdown(text, noteLabel(entry, 90), null, true);
    li.append(stamp, text);
    const open = () => flashEntry(entry.id);
    li.addEventListener("click", open);
    li.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
    list.appendChild(li);
  }
  body.appendChild(list);
}

//: **Writing pace.** The streak widget answers "did I show up"; this answers
//: "did I write anything when I did", which is a different and more honest
//: question: a one-word note keeps a streak alive.
//:
//: A fortnight rather than a week: seven bars cannot show a trend, and a month
//: of bars in a widget column is a picket fence.
const DASH_PACE_DAYS = 14;

function renderPaceWidget(body) {
  const entries = typeof allEntries !== "undefined" ? allEntries : [];
  const days = [];
  const now = new Date();
  for (let back = DASH_PACE_DAYS - 1; back >= 0; back -= 1) {
    const at = new Date(now);
    at.setDate(now.getDate() - back);
    at.setHours(0, 0, 0, 0);
    days.push({ at, words: 0 });
  }
  const first = days[0].at.getTime();
  for (const entry of entries) {
    const at = new Date(entry.created_at);
    if (Number.isNaN(at.getTime()) || at.getTime() < first) continue;
    const index = Math.floor((at.setHours(0, 0, 0, 0) - first) / 86400000);
    if (index < 0 || index >= days.length) continue;
    days[index].words += (String(entry.content || "").match(/\S+/g) || []).length;
  }
  const total = days.reduce((sum, day) => sum + day.words, 0);
  if (!total) {
    return dashEmpty(body, "No words yet this fortnight. Anything you write today shows up here.");
  }
  const peak = Math.max(...days.map((day) => day.words), 1);

  const headline = document.createElement("p");
  headline.className = "dash-pace-total";
  const strong = document.createElement("strong");
  strong.textContent = total.toLocaleString();
  headline.append(strong, ` words in ${DASH_PACE_DAYS} days · ${Math.round(total / DASH_PACE_DAYS).toLocaleString()} a day`);
  body.appendChild(headline);

  const chart = document.createElement("div");
  chart.className = "dash-pace-chart";
  chart.setAttribute("role", "img");
  chart.setAttribute(
    "aria-label",
    `Words written each day: ${days.map((d) => `${d.at.toLocaleDateString(undefined, { weekday: "short" })} ${d.words}`).join(", ")}`
  );
  for (const day of days) {
    const column = document.createElement("div");
    column.className = "dash-pace-bar";
    //: A custom property rather than an inline `style` attribute, which this
    //: app's CSP refuses: the same rule the Loose ends meter follows.
    column.style.setProperty("--dash-pace-height", `${Math.round((day.words / peak) * 100)}%`);
    column.title = `${day.at.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" })}: ${day.words.toLocaleString()} word${day.words === 1 ? "" : "s"}`;
    //: Today is marked, so the row reads as ending *now* rather than as an
    //: undated fortnight.
    if (day.at.toDateString() === new Date().toDateString()) column.classList.add("is-today");
    chart.appendChild(column);
  }
  body.appendChild(chart);

  const caption = document.createElement("p");
  caption.className = "muted dash-pace-caption";
  const best = days.reduce((a, b) => (b.words > a.words ? b : a));
  caption.textContent = `Best day: ${best.at.toLocaleDateString(undefined, { weekday: "long" })}, ${best.words.toLocaleString()} words`;
  body.appendChild(caption);
}
