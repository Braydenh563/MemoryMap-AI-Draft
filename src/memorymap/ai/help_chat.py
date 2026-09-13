"""In-app guidance chat: "how do I..." answers about MemoryMap itself.

ROADMAP.md item 40's "mini AI chat half", deliberately its own path,
separate from `librarian.converse`/`librarian.answer`, because those two
answer from the user's notes or hold a general conversation, and this one
must do neither: it only explains the app. Uses the utility model (not the
main chat model), its own system prompt, and the existing `"quick"` preset
(low temperature, no extended thinking, a 256-token cap) rather than a new
one, since that preset already is the "speed and accuracy over creativity,
tight budget" the spec asked for.

**Grounded, not just instructed.** A first version of this module told the
model "don't invent a feature you're not sure exists" and gave it nothing
else to go on, for a small local model that has never heard of MemoryMap,
that is an instruction with no way to follow it: refusing to guess and
guessing wrong look identical from inside the prompt. `HELP_TOPICS` below is
the fix: a short, factual reference entry per feature area, the same
material the Help accordion already shows in `frontend/index.html`. The
question is matched against it by keyword, and whichever entries match get
attached to the prompt as the only material the model is allowed to answer
from. Keeping `HELP_TOPICS` in step with the accordion (and the accordion in
step with the app) is what "the chatbot's information is up to date" means
in practice, and it is why this module, not the docs alone, is the thing
future sessions should re-check first when a feature's behaviour changes.

No persistence: nothing here writes to the database. The caller (the
frontend) is the one holding the running transcript, in memory only, for
exactly as long as the spec allows, this module only ever sees what it's
handed on each call.
"""

from __future__ import annotations

import re

from memorymap.ai.model_manager import ModelManager
from memorymap.ai.provider import Provider

SYSTEM_PROMPT = (
    "You are MemoryMap's in-app help assistant. You answer ONLY questions "
    "about how to use the MemoryMap app itself: its features, tabs, and "
    "settings. You have no access to the user's notes or documents, so if "
    "asked a question about their notebook's own content, say plainly that "
    "this chat is for app guidance only and point them to the Chat or Ask "
    "tab instead of guessing. Base your answer only on the reference notes "
    "given to you below the question, if any are given, never invent a "
    "button, setting, or feature that isn't in them. If no reference notes "
    "are given, or they don't cover the question, say plainly that you're "
    "not sure and suggest checking the Help topics above this chat instead "
    "of guessing. Keep answers short: a few sentences or a short numbered "
    "list of steps: and name the exact tab or settings section involved."
)

OFFLINE_MESSAGE = (
    "The AI guide isn't available right now (the local model doesn't seem "
    "to be running): the Help topics above still work without it."
)

# One factual entry per feature area, the model's *only* source of facts
# about the app, and the same ground truth the Help accordion shows in
# `frontend/index.html`'s `#settings-help` (kept in sync by hand: there is
# no shared data file behind both, since the accordion is static HTML and
# a build step to generate it from Python would be more machinery than a
# help page has earned). `keywords` decide which entries a question pulls
# in; `badge` is the quick-access chip attached to the reply when this
# entry gets used, so "how do I set a reminder" both answers correctly and
# offers one tap into the Reminders tab.
HELP_TOPICS: list[dict] = [
    {
        "id": "capture",
        "keywords": ("capture", "note", "template", "dictate", "sketch", "improve", "proofread", "draft"),
        "body": (
            "Notes tab: type into \"Capture a thought\" and Save. A local AI files "
            "it into a category and suggests tags; you can re-file or edit anytime. "
            "Use a template, dictate with the microphone icon, sketch with the "
            "palette icon, or run \"Improve\" to proofread first. \"Extract notes\" "
            "turns a block of pasted text into several AI-drafted, auto-linked notes."
        ),
        "badge": {"label": "Notes", "tab": "notes"},
    },
    {
        "id": "ask-chat",
        "keywords": ("ask", "chat", "agent", "conversation", "tool", "question", "popup agent", "everywhere"),
        "body": (
            "\"Ask your notebook\" (Notes tab) and the Chat tab both answer from "
            "saved notes, with the raw notes shown beside the answer. Agent mode "
            "(a toggle in Chat) lets the assistant use its tools to search, link, "
            "tag, organise and create, destructive actions always ask first. "
            "Conversations save and rename in the sidebar. The same agent also "
            "pops open over any tab with Ctrl/Cmd+Shift+A, so you don't have to "
            "switch to Chat first."
        ),
        "badge": {"label": "Chat", "tab": "chat"},
    },
    {
        "id": "skills",
        "keywords": ("skill",),
        "body": (
            "Skills are one-click requests shown above the chat box (e.g. "
            "\"Summarise my week\"). Built-in skills ship with the app; add your "
            "own in Settings -> Skills. A skill can use the AI's tools, so it "
            "does the work rather than just describing it."
        ),
        "badge": {"label": "Skills", "section": "skills"},
    },
    {
        "id": "graph",
        "keywords": ("graph", "concept map", "mind map", "mindmap", "network"),
        "body": (
            "The Graph tab shows notes as a force-directed map, links and threads "
            "drawn between them, plus optional AI similarity lines. Search "
            "highlights matches, dragging rearranges, and the legend toggles "
            "categories on and off. Concept maps (an authored mindmap, not the "
            "automatic graph) are made and managed from the Library."
        ),
        "badge": {"label": "Graph", "tab": "graph"},
    },
    {
        "id": "reminders",
        "keywords": ("reminder", "due date", "snooze", "recur"),
        "body": (
            "The Reminders tab groups items into Overdue / Today / Upcoming / "
            "Done. Set a priority, snooze, edit inline, or make one recurring. "
            "You can also just say \"call mum tomorrow evening\" in a note and "
            "let the AI schedule it. Notifications fire while the app is open."
        ),
        "badge": {"label": "Reminders", "tab": "reminders"},
    },
    {
        "id": "dashboard",
        "keywords": ("dashboard", "widget", "streak", "digest"),
        "body": (
            "The Dashboard is the at-a-glance home: capture streak, stats, a "
            "weekly AI digest, pinned notes, reminders, and more. Click \"Edit "
            "layout\" to show, hide and rearrange widgets; the layout is "
            "remembered per user."
        ),
        "badge": {"label": "Dashboard", "tab": "dashboard"},
    },
    {
        "id": "library",
        "keywords": ("library", "bookmark", "link shelf", "contents", "outline"),
        "body": (
            "The Library is everything already made, in one searchable, "
            "filterable place: notes, documents, chats, files and tags, plus "
            "Links (a bookmark shelf for websites), Contents (a hyperlinked "
            "outline of the whole notebook) and AI Skills. Sub-tabs also hold "
            "Documents, Whiteboards, and the Files & Images gallery."
        ),
        "badge": {"label": "Library", "tab": "library"},
    },
    {
        "id": "documents",
        "keywords": ("document", "editor", "markdown", "code file", "live view", "source view"),
        "body": (
            "The document editor (opened from Library -> Documents) has four "
            "views: Live (renders as you write), Source, Split and Read. Code "
            "files get line numbers, Tab/Shift+Tab indenting and Ctrl+/ "
            "commenting. \"Check with AI\" reviews a document for wording issues "
            "a spellchecker can't catch."
        ),
        "badge": {"label": "Library", "tab": "library"},
    },
    {
        "id": "whiteboard",
        "keywords": ("whiteboard", "sketch pad", "canvas", "freehand"),
        "body": (
            "The whiteboard (Library -> Whiteboards) is a pannable canvas for "
            "freehand sketches and note cards together. Freehand sketches also "
            "appear in the Library's Images sub-tab."
        ),
        "badge": {"label": "Library", "tab": "library"},
    },
    {
        "id": "files-images",
        "keywords": ("image", "photo", "caption", "ocr", "vision", "scan", "pdf", "file upload"),
        "body": (
            "Every image is read automatically, up to three ways: an AI caption "
            "of what it shows, a vision-model transcription of any text in it, "
            "and Tesseract OCR if that's installed: all editable and searchable. "
            "A scanned PDF is rasterised page-by-page and read by an OCR model "
            "(no Tesseract needed); you can pick the model or leave it automatic."
        ),
        "badge": {"label": "Library", "tab": "library"},
    },
    {
        "id": "timeline",
        "keywords": ("timeline",),
        "body": (
            "The Timeline tab lays notes out chronologically in day/week/month "
            "buckets, grid or line view, with an optional band (category, tag "
            "or space) to see how things cluster over time."
        ),
        "badge": {"label": "Timeline", "tab": "timeline"},
    },
    {
        "id": "memory",
        "keywords": ("remember", "passive capture", "auto capture", "learn about me"),
        "body": (
            "MemoryMap can pick up small facts and preferences as you write and "
            "chat, always asking first, never assumed. Accept or decline each "
            "suggestion right in the chat, and review or forget anything it has "
            "learned in Settings -> What it remembers."
        ),
        "badge": {"label": "What it remembers", "section": "memory"},
    },
    {
        "id": "spaces",
        "keywords": ("space", "workspace", "separate notebook"),
        "body": (
            "A space is a separate notebook inside the same app: notes, "
            "documents, chats and tags kept apart from other spaces. Switch or "
            "create one from the picker at the top of the sidebar; \"All "
            "spaces\" shows everything together."
        ),
        "badge": {"label": "Spaces", "section": "account"},
    },
    {
        "id": "appearance",
        "keywords": ("theme", "dark mode", "light mode", "accent colour", "accent color", "font", "density", "glass"),
        "body": (
            "Settings -> Appearance controls theme (light/dark/system), accent "
            "colour, fonts, density, glass effects and the animated background. "
            "High-contrast and reduce-motion options are there for comfort and "
            "accessibility."
        ),
        "badge": {"label": "Appearance", "section": "appearance"},
    },
    {
        "id": "shortcuts",
        "keywords": ("shortcut", "keyboard", "hotkey", "command palette"),
        "body": (
            "Press ? for the full shortcut list, or Ctrl/Cmd+K for the command "
            "palette (jump anywhere, search notes). Press g then a letter to "
            "jump straight to a tab; Settings -> Shortcuts lists which letter "
            "goes where. There are no \"/\" chat commands to learn."
        ),
        "badge": {"label": "Shortcuts", "section": "shortcuts"},
    },
    {
        "id": "models",
        "keywords": ("model", "ollama", "lm studio", "vllm", "llama.cpp", "utility model", "chat model", "sampling", "temperature"),
        "body": (
            "Settings -> Models picks the chat model and an optional smaller "
            "utility model for background jobs. Any OpenAI-compatible server "
            "works, not just Ollama, LM Studio, llama-server, Jan, vLLM. "
            "Sampling parameters (temperature, top-p, top-k, min-p, repeat "
            "penalty) are exposed there too, starting at what the model itself "
            "recommends."
        ),
        "badge": {"label": "Models", "section": "models"},
    },
    {
        "id": "storage",
        "keywords": ("backup", "storage", "data dir", "where is my", "export", "data folder"),
        "body": (
            "Everything lives in a data folder you control: the notebook "
            "database, uploads, and daily local backups. Settings -> Data shows "
            "exactly where it is on disk, and lets you export as JSON, CSV or "
            "Markdown, and manage or restore backups."
        ),
        "badge": {"label": "Data", "section": "data"},
    },
    {
        "id": "websearch",
        "keywords": ("web search", "websearch", "internet search", "searxng"),
        "body": (
            "Web search is opt-in and off by default. When turned on in "
            "Settings -> Web search, only your search words are sent out, "
            "never your notes: so the assistant can look something up online "
            "when asked."
        ),
        "badge": {"label": "Web search", "section": "websearch"},
    },
    {
        "id": "privacy",
        "keywords": ("private note", "encrypt", "password", "lock", "security"),
        "body": (
            "Private notes are encrypted at rest with a key derived from your "
            "unlock password. The app binds to localhost, has no account or "
            "telemetry, and nothing leaves your machine unless you explicitly "
            "turn on web search."
        ),
        "badge": {"label": "Account & security", "section": "account"},
    },
    {
        "id": "archive",
        "keywords": ("archive", "archived", "shelved", "out of the way"),
        "body": (
            "Archiving keeps a note, chat or document but gets it out of your "
            "everyday lists: different from the bin, since nothing archived "
            "is ever auto-cleared or at risk of being deleted. The action is "
            "in each item's own menu (next to Delete, not grouped with it); "
            "everything archived is still reachable from the Library's "
            "Archived filter, where Unarchive brings it straight back."
        ),
        "badge": {"label": "Library", "tab": "library"},
    },
    {
        "id": "undo-bin",
        "keywords": ("undo", "redo", "recycle bin", "restore", "deleted", "trash"),
        "body": (
            "Deleting a note goes to the recycle bin, not gone for good, "
            "restore it from the Library's Bin filter, or use the Undo toast "
            "that appears right after deleting. Ctrl/Cmd+Z undoes the last "
            "change generally; the status bar's own Undo/Redo buttons do the "
            "same thing by click."
        ),
        "badge": {"label": "Library", "tab": "library"},
    },
    {
        "id": "voice",
        "keywords": ("dictate", "dictation", "voice", "microphone", "meeting", "transcribe", "recording", "read aloud"),
        "body": (
            "The microphone icon on the note composer dictates a note using "
            "local Whisper: nothing sent anywhere. \"Record a meeting or "
            "lecture\" (reachable from the Dashboard or the command palette) "
            "transcribes a longer recording and can pull out decisions and "
            "action items. Read-aloud plays a note or answer back to you."
        ),
        "badge": {"label": "Notes", "tab": "notes"},
    },
    {
        "id": "autonomous",
        "keywords": ("background librarian", "auto tag", "auto-tag", "auto link", "auto-link", "dedupe", "duplicate", "autonomous"),
        "body": (
            "Turned on in Settings -> Preferences, the background librarian "
            "tags, links and flags duplicate notes on an interval you choose "
            ", off by default, since it writes to your notebook without "
            "being asked each time. It never deletes anything and skips "
            "itself on battery power."
        ),
        "badge": {"label": "Preferences", "section": "preferences"},
    },
    {
        "id": "command-palette",
        "keywords": ("command palette", "jump anywhere", "quick actions", "jump to"),
        "body": (
            "Ctrl/Cmd+K opens the command palette: jump to any tab or "
            "setting, search notes, or run a quick action (new note, new "
            "chat, back up now, toggle the theme, and more) without leaving "
            "the keyboard. It's a different box from the popup agent "
            "(Ctrl/Cmd+Shift+A): this one runs fixed commands, that one "
            "answers and acts on an open-ended request."
        ),
        "badge": {"label": "Shortcuts", "section": "shortcuts"},
    },
    {
        "id": "extract-notes",
        "keywords": ("extract notes", "rough thoughts", "writing room", "draft"),
        "body": (
            "\"Extract notes\" (Notes tab) turns a block of pasted free text "
            "into several AI-drafted, auto-linked notes instead of one long "
            "one. The Writing Room sub-tab is for turning rough, unstructured "
            "thoughts into a proper note before it's saved."
        ),
        "badge": {"label": "Notes", "tab": "notes"},
    },
    {
        "id": "favourites",
        "keywords": ("favourite", "favorite", "star", "starred", "pin", "pinned"),
        "body": (
            "Starring a note makes it a favourite, a parallel way to keep "
            "important notes close, separate from categories or tags. "
            "Favourites show in the sidebar, filter in the Library, and can "
            "sit in their own Dashboard widget."
        ),
        "badge": {"label": "Notes", "tab": "notes"},
    },
    #: **Five topics added after an audit against what the app can actually
    #: do.** Asked for directly: "did you make sure full usage guides exist in
    #: the docs for the help ai to use??" The answer was mostly yes, every tab
    #: had an entry: but the checker found five features the help AI could not
    #: describe at all, which means it would have guessed. A help assistant that
    #: guesses is worse than one that says it does not know, so anything it can
    #: be asked about needs an entry here.
    {
        "id": "ocr-workspace",
        "keywords": (
            "ocr", "read text", "scan", "scanned", "extract text", "transcribe",
            "tesseract", "vision model", "page read", "pdf text",
        ),
        "body": (
            "OCR workspace: open any image or PDF from the Library or a note and "
            "choose \"Read text\". Pick the reader at the top, the AI document "
            "reader (a model built to transcribe a page), the general vision "
            "model where you have a different one installed, or Tesseract, which "
            "needs no model, is about ten times faster and is the only reader "
            "that tells you where on the page each block sits. Read one page, a "
            "range like 1-5, or the whole document. A read keeps running if you "
            "close the window: it shows in Settings -> Background tasks and can "
            "be stopped from there or from the workspace, and every page that "
            "has been read is remembered, so reopening the document shows the "
            "text again rather than starting over."
        ),
        "badge": {"label": "Library", "tab": "library"},
    },
    {
        "id": "document-history",
        "keywords": (
            "history", "version", "revision", "restore", "undo edit", "previous version",
            "git log", "rollback", "ai edit log", "old version", "earlier version",
            "what it used to say", "roll back",
        ),
        "body": (
            "Documents keep a history. The ... menu -> History lists every "
            "version the document has had, newest first, with who changed it "
            "(you, an AI edit, or a restore), how many words it gained or lost, "
            "and the opening of that version. \"View\" reads an old version "
            "without changing anything; \"Restore\" puts it back and keeps the "
            "version it replaced, so a restore is itself undoable. A stretch of "
            "editing counts as one entry rather than one per autosave. The AI "
            "panel has a separate \"AI edits\" log for reverting one specific "
            "suggestion the model made."
        ),
        "badge": {"label": "Documents", "tab": "documents"},
    },
    {
        "id": "writing-checks",
        "keywords": (
            "spelling", "spellcheck", "suggestion", "proofread", "grammar",
            "dictionary", "rephrase", "wording", "autocorrect", "flagged",
        ),
        "body": (
            "The document editor checks spelling, spacing and sentence length as "
            "you write. In Live view a flagged word is underlined: click or "
            "right-click it for corrections, \"Add to dictionary\" or \"Ignore "
            "this for now\". The Suggestions panel lists every finding; clicking "
            "one scrolls to it and highlights it briefly. Where there is no "
            "mechanical fix, an awkward sentence, \"Ask the AI for wordings\" "
            "has the local model offer two or three alternatives to pick from. "
            "Nothing is changed until you choose it. Manage the dictionary and "
            "the British/American spelling preference from the editor's own "
            "dictionary dialog."
        ),
        "badge": {"label": "Documents", "tab": "documents"},
    },
    {
        "id": "notebook-questions",
        "keywords": (
            "how many", "most common", "statistics", "stats", "count", "top tags",
            "busiest", "untagged", "orphan", "most linked",
        ),
        "body": (
            "You can ask about the notebook itself, not just what is in it: "
            "\"what are my most common tags\", \"which categories have the most "
            "notes\", \"how many notes do I have\", \"how many notes have no "
            "tags\", \"which are my most linked notes\", \"when do I write "
            "most\". These are counted from your data rather than generated, so "
            "the numbers are exact, the answer is instant, and it works even "
            "with no AI model running at all. Private and binned notes are never "
            "counted."
        ),
        "badge": {"label": "Chat", "tab": "chat"},
    },
    {
        "id": "contradictions",
        "keywords": (
            "contradict", "contradiction", "tension", "disagree", "conflict",
            "inconsistent", "changed my mind", "out of date",
        ),
        "body": (
            "MemoryMap can look for places where two of your notes disagree, a "
            "decision you reversed, a fact you later corrected, and show them "
            "side by side with the dates, so you can see which is current. It "
            "runs on demand rather than constantly, because it is a real pass "
            "over the notebook with the local model. It never edits anything: "
            "the point is to show you the pair and let you decide."
        ),
        "badge": {"label": "Dashboard", "tab": "dashboard"},
    },
]

#: A tight window: this is guidance, not a conversation to reminisce in.
MAX_HISTORY_TURNS = 6
MAX_MESSAGE_CHARS = 1000
#: How many reference entries to hand the model for one question. Kept
#: small on purpose: item 40 asked for "a tight prompt/context budget",
#: and a guidance answer is about one or two features, not a syllabus.
MAX_TOPICS = 3


# Whole-word match, not a raw substring one, a plain `in` check let "ask"
# match inside "basket" and "task", and a wrongly-matched topic means the
# model gets handed reference notes about the wrong feature. Compiled once
# at import time rather than per call: this runs on every `/help/ask`
# request, and re-compiling ~100 small regexes (18 topics x ~6 keywords)
# on every one of them is wasted work an unbounded local model call already
# dwarfs, but costs nothing to avoid.
_KEYWORD_PATTERNS: dict[str, re.Pattern[str]] = {
    keyword: re.compile(rf"\b{re.escape(keyword)}\b")
    for topic in HELP_TOPICS
    for keyword in topic["keywords"]
}


def _matching_topics(question: str) -> list[dict]:
    """Which `HELP_TOPICS` entries this question is actually about, ranked
    by how many of a topic's keywords it mentions. Ties keep `HELP_TOPICS`
    order, so the more commonly-asked-about features (listed first) win a
    tie over a rarer one."""
    lowered = question.lower()
    scored = [
        (
            sum(1 for keyword in topic["keywords"] if _KEYWORD_PATTERNS[keyword].search(lowered)),
            topic,
        )
        for topic in HELP_TOPICS
    ]
    scored = [pair for pair in scored if pair[0] > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [topic for _, topic in scored[:MAX_TOPICS]]


def badges_for(topics: list[dict]) -> list[dict]:
    """The quick-access chips for a set of matched topics, de-duplicated by
    label and capped: same cap as `MAX_TOPICS`, since each matched topic
    contributes at most one badge."""
    seen: set[str] = set()
    out: list[dict] = []
    for topic in topics:
        badge = topic["badge"]
        if badge["label"] not in seen:
            out.append(badge)
            seen.add(badge["label"])
    return out


def answer(
    question: str,
    model_manager: ModelManager,
    ollama: Provider,
    history: list[dict] | None = None,
) -> dict:
    """One turn of the help chat.

    `history` is whatever the caller is holding client-side for the current
    session (see module docstring): never read from or written to the
    database. Returns `{"content": str, "badges": list[dict]}`."""
    question = question.strip()[:MAX_MESSAGE_CHARS]
    if not question:
        return {"content": "", "badges": []}
    if not ollama.is_running():
        return {"content": OFFLINE_MESSAGE, "badges": []}

    topics = _matching_topics(question)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if topics:
        reference = "\n".join(f"- {topic['body']}" for topic in topics)
        messages.append(
            {"role": "system", "content": f"Reference notes for this question:\n{reference}"}
        )
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    messages.append({"role": "user", "content": question})

    reply = ollama.chat(model_manager.utility_model(), messages, mode="quick")
    content = reply["content"].strip()
    return {"content": content, "badges": badges_for(topics)}
