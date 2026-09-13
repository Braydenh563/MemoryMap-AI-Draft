// library.js: the Library tab, split out of app.js and whiteboard.js
// (§88.3 of the app.js split plan; documents.js was the first file, this
// is the second).
//
// Loaded after app.js and after whiteboard.js, see index.html's <script>
// ordering comment for why the whiteboard-relative order is load-bearing
// here in a way documents.js's own split never had to care about: this
// file's own bottom section (the sub-tab switcher) calls
// wbShowBoardsLanding() when the Whiteboard sub-tab is chosen, and
// whiteboard.js's own boards-gallery code (openWhiteboardBoard) clicks the
// Library's #library-subtabs whiteboard button to jump back, both calls
// are made from inside event-listener closures, never at parse time, so
// neither direction is actually load-bearing; loading after whiteboard.js
// simply keeps this file, like documents.js before it, as one of the later,
// smaller scripts rather than forcing whiteboard.js to move.
//
// Checked for the exact hazard documents.js found (a function definition
// moved out from under a bare top-level call site left behind) before
// trusting this split was safe: grepped every Library-owned function/const
// name (loadLibrary, renderLibrary*, flashLibraryItem, openBinnedNote,
// closeBinnedReader, openLibraryItem, refreshLibrarySemantic) for a bare
// top-level call anywhere left in app.js. None exists: every call site is
// inside a function or an event-listener body, which resolves the
// identifier at *call* time, long after every <script> tag (this one
// included) has parsed. So unlike documents.js's initDocSidebarTabs(),
// there was no call site to move here.
//
// What moved, and from where:
//
//  - app.js:19272-20114: the Library's core module (§4, §36F): the item
//    list, filters, sort, selection, cards, bulk actions' helpers, and
//    "reading a binned note in full" (§36G, openBinnedNote/closeBinnedReader
//    and the #binned-overlay reader). The binned-note reader is included
//    deliberately, resolving this split's own open question: it is called
//    from nowhere but this file's own openLibraryItem(), and its overlay
//    exists only to serve the Library's Bin filter chip, it is Library's
//    own code that happened to get its own §-number and its own "---"
//    comment banner, not a separate feature.
//  - app.js:4866-4904: flashLibraryItem(), the "View in bin" deep link a
//    skill's undo-row uses (BACKLOG §22). It lived far from the rest of the
//    Library's code (next to changeRow(), an agent-result renderer) because
//    its *caller* is a Notes/agent feature, but its *body* is nothing but
//    Library internals (libraryKind, renderLibraryFilters, renderLibrary,
//    #library-grid), the same shape documents.js's own split judged by:
//    what a function's body touches, not where its caller happens to sit.
//  - app.js:24022-24031 and 24391-24533: the Library's own wiring: the
//    "+ New Skill" button on the AI Skills sub-tab, and the main view's
//    search/sort/view-toggle/bulk-action/bin-empty/refresh controls.
//  - app.js:26717-26899: the AI Skills sub-tab's dashboard
//    (renderSkillsDashboard, renderSkillLogs) and the `switchTab` override
//    that calls them whenever the Library tab is opened. That override is
//    moved **verbatim, not folded into switchTab's own `if (name ===
//    "library")` branch** in app.js (which already exists, and already
//    calls loadLibrary()), merging the two would be a real behaviour
//    change (one code path instead of two) riding along with a split, which
//    the split's own rules forbid. Logged to ROADMAP.md instead as a
//    worthwhile follow-up, not built here.
//  - whiteboard.js:82-91: two `Set()`s (the image gallery's expanded-caption
//    set, since folded into `openRowReadings`, and libraryDocsSelection) that
//    whiteboard.js declared alongside its own
//    per-card state purely because nothing else existed yet; both are read
//    and written only inside code that moved here too.
//  - whiteboard.js:5515-5706: the Library's Documents sub-tab
//    (renderLibraryDocuments, its selection bar, its bulk-delete).
//  - whiteboard.js:5874-6191: the Library's Image Gallery sub-tab
//    (renderLibraryImagesGallery, filterLibraryImagesGallery).
//  - whiteboard.js:5710-5813 (of the original file), **the fix ROADMAP.md
//    §88.3 called "an accident worth fixing while splitting"**: the
//    `#library-subtabs` button switcher (deciding which library-view-*
//    section is visible) and the library-docs-*/library-images-* refresh,
//    search and upload listeners. These were never whiteboard's own code: 
//    they switch between the Library's Documents/Skills/Whiteboard/Media
//    sub-tabs and wire the Documents/Media sub-tabs' own controls: they
//    just landed in whiteboard.js's DOMContentLoaded listener because the
//    Whiteboard sub-tab's own two listeners (wb-boards-new,
//    wb-back-to-boards) were written in the same block right after them.
//    Those two *are* whiteboard's own code and stayed in whiteboard.js, in
//    a DOMContentLoaded listener of their own, see that file's comment.
//    This file's own copy of the switcher still calls wbShowBoardsLanding()
//    (whiteboard.js) and renderLibraryImagesGallery()/renderLibraryDocuments()
//    (this file) exactly as before; only the listener's *location* changed.


// --- the Library (§4, §36F) ---------------------------------------------------
//
// The one surface for finding something you made before. It **replaces** the
// Documents tab's list and the chat sidebar's list rather than joining them, 
// a library that duplicates two lists that already exist is a third place to
// look, which is worse than no library. The tab bar is the same length it was.
//
// A library is for *finding*, which is a different job from the Notes tab's
// "work with what I have", so it is built differently: bigger units, more
// metadata per unit, and sort and filter at the top as controls rather than at
// the side as an afterthought.
//
// The list itself is assembled by the server (GET /library): see
// routes_library.py for why. Filtering and sorting are **not**: they have to
// feel instant as you type, so the client owns them and holds the whole list.

//: The last payload from GET /library, so typing in the search box re-filters
//: what is already here instead of asking the server on every keystroke.
let libraryItems = [];
let libraryCounts = {};
let libraryOverview = {};
let libraryKind = "all";

//: Same pattern as Notes' and the Library Documents sub-tab's own paging: 
//: "all" (the default) leaves renderIncrementally's chunked scroll untouched;
//: a number slices the already-filtered/sorted list to one flat page instead.
let libraryPageSize = localStorage.getItem("library-page-size") || "all";
let libraryCurrentPage = 1;

//: Order matters: it is the order of the chips. "All" first because it is the
//: default and the one you come back to, then by how often you would reach for
//: the kind: a document is something you sat down to write, a binned note is
//: something you threw away.
const LIBRARY_KINDS = [
  { key: "all", icon: "ph:books", label: "Everything" },
  { key: "note", icon: "ph:note-pencil", label: "Notes" },
  { key: "document", icon: "ph:file-text", label: "Documents" },
  { key: "chat", icon: "ph:chat-circle", label: "Chats" },
  { key: "file", icon: "ph:paperclip", label: "Files" },
  { key: "tag", icon: "ph:tag", label: "Tags" },
  //: A board and a mind map are `Entry` rows carrying `is_board`
  //: (MINDMAP_PLAN §4 chose option B), so "Everything" listed them with a
  //: note's pencil and the Notes chip counted them. Reported on 2026-09-09:
  //: "in the all library subtab, the mindmap I made called bubble tea shows
  //: as a note". The server tells them apart now (`_entry_kind`); these two
  //: rows are what let this view draw and count them as what they are. Same
  //: icons the Boards and maps sub-tab uses, so one thing has one glyph
  //: wherever it appears.
  { key: "board", icon: "ph:pencil-circle", label: "Boards" },
  { key: "map", icon: "ph:tree-structure", label: "Mind maps" },
  // Drafts used to be a Library sub-tab of its own. It is a *filter over
  // notes*, not a separate kind of thing, and it only sat up there because
  // this chip row did not exist when it was added, so it moved here, which
  // is also where someone looking for "notes I have not finished" would
  // reasonably expect to find it.
  { key: "draft", icon: "ph:pencil-simple-line", label: "Drafts" },
  // Not a real kind, item.kind is still "note" for these, same as every
  // other tagged note. A meeting note is finished, unlike a draft, so it
  // stays reachable from "Everything" too; this chip is a client-side tag
  // filter (renderLibrary()'s own special case for libraryKind === "meeting"),
  // and its count below is computed the same way rather than read from the
  // server's per-kind counts, which only exist for real kinds.
  { key: "meeting", icon: "ph:video-camera", label: "Meetings" },
  // "archived" is the bin's own internal kind (see routes_library.py's
  // _archive()), this app's real archive uses "shelved" specifically so
  // the two are never confused at the code level, even though the words
  // read almost the same to a user.
  { key: "shelved", icon: "ph:archive", label: "Archived" },
  { key: "archived", icon: "ph:trash", label: "Bin" },
  { key: "activity", icon: "ph:scroll", label: "Activity" },
];

//: The overview strip. Each tile is a *state worth knowing*, and each one goes
//: somewhere: the same test the status bar had to pass, for the same reason:
//: a number you cannot act on is decoration, and a management screen made of
//: decoration is a dashboard nobody opens twice.
//: What is ticked. Ids alone would collide, a tag's id 3 and a note's id 3 are
//: different things: so the key is kind + id, and it survives a re-render
//: because it is not read off the DOM.
let librarySelection = new Set();

const LIBRARY_VIEW_KEY = "libraryView";

function libraryView() {
  return localStorage.getItem(LIBRARY_VIEW_KEY) === "list" ? "list" : "grid";
}

function libraryKeyOf(item) {
  return `${item.kind}:${item.id}`;
}

function renderLibraryView() {
  const current = libraryView();
  //: Both switches, because they share one stored preference: a Rows chosen
  //: on the Boards sub-tab has to come back pressed on the All sub-tab, or
  //: the two read as unrelated controls that happen to look the same.
  for (const button of document.querySelectorAll("#library-view button, #library-boards-view button")) {
    const active = button.dataset.libraryView === current;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

async function loadLibrary() {
  const body = await apiJson("/library").catch(() => null);
  libraryItems = (body && body.items) || [];
  libraryCounts = (body && body.counts) || {};
  libraryOverview = (body && body.overview) || {};
  // A selection that survives a reload is a selection that can act on
  // something already deleted. Cleared here rather than merged, because the
  // safe half of "delete nine things" is knowing exactly which nine.
  librarySelection = new Set();
  renderLibraryOverview();
  renderLibraryFilters();
  renderLibraryView();
  renderLibrary();
}

/** The one line of the old overview strip that was not already on screen.
 *
 *  The strip used to be six stat tiles above the filter chips, 
 *  notes / documents / chats / tags / archived / in the bin, each showing a
 *  count and, on click, setting `libraryKind`. Six of the chips directly
 *  below it are the same six filters, with the same counts, doing the same
 *  thing. Measured: 61px of duplicate control, in a screen that already put
 *  344px of chrome above its first item, and reported as "half the screen
 *  is taken up by poor ui choices or structuring."
 *
 *  Removing the tiles loses nothing: every filter they offered is still one
 *  click away in the row underneath, still labelled, still counted. What the
 *  chips never carried is the prose, how much disk the attachments take and
 *  how much writing is in the documents, so that stays, as one quiet line.
 */
function renderLibraryOverview() {
  const box = $("library-overview");
  if (!box) return;
  box.replaceChildren();
  // One line of plain prose about the things that are not counts: how much
  // disk the attachments take, and how much writing is in the documents.
  const note = document.createElement("p");
  note.className = "muted library-overview-note";
  const parts = [];
  if (libraryOverview.attachment_bytes) {
    parts.push(`${libraryOverview.attachment_size} of attachments`);
  }
  if (libraryOverview.words) parts.push(`${libraryOverview.words.toLocaleString()} words written`);
  if (libraryOverview.private_notes) {
    parts.push(`${libraryOverview.private_notes} private (locked, never previewed here)`);
  }
  note.textContent = parts.length
    ? parts.join(" · ")
    : "Everything you make, notes, documents, chats, files, is managed from here.";
  box.appendChild(note);
}

function renderLibraryFilters() {
  const box = $("library-filters");
  if (!box) return;
  box.replaceChildren();
  for (const kind of LIBRARY_KINDS) {
    // Not `libraryItems.length`: activity is unconditionally excluded from
    // the "Everything" view itself (see renderLibrary()'s own comment on
    // why: it would be 93%+ log on a real notebook), so a count that
    // included it disagreed with what pressing the chip actually shows.
    const count =
      kind.key === "all"
        ? libraryItems.length - (libraryCounts.activity || 0) - (libraryCounts.draft || 0)
        : kind.key === "meeting"
          ? libraryItems.filter((i) => i.kind === "note" && (i.tags || []).includes("meeting")).length
          : libraryCounts[kind.key] || 0;
    const button = document.createElement("button");
    button.type = "button";
    button.className =
      "library-chip" + (libraryKind === kind.key ? " active" : "");
    button.setAttribute("aria-pressed", String(libraryKind === kind.key));
    // Reported live: "can the activity button be moved somewhere better", 
    // it isn't a *kind of thing you made* the way the ten chips before it
    // are (it is excluded from "Everything"'s own count above for exactly
    // that reason), so it read as just one more chip in a row it doesn't
    // really belong to. `library-chip-activity` pushes it to the row's own
    // far end with a divider ahead of it, the same "different question,
    // visually apart" treatment the reminder view-toggle already gets next
    // to the reminder filter (05-sidebars-themes.css). Still one click away
    // in the same toolbar, a second surface for one chip would be a second
    // place to remember, not a better one.
    if (kind.key === "activity") {
      button.classList.add("library-chip-activity");
      button.title = "What you did: a record, not a kind of thing you made";
    }
    const icon = document.createElement("span");
    setLabel(icon, kind.icon);
    icon.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    setLabel(label, kind.label);
    // The count is on the chip, not discovered by pressing it. A filter you
    // have to try before you learn it is empty is a filter that wastes a click
    // every time: and with five of them that is most of the toolbar.
    const badge = document.createElement("span");
    badge.className = "library-chip-count";
    badge.textContent = count;
    button.append(icon, label, badge);
    button.addEventListener("click", () => {
      libraryKind = kind.key;
      libraryCurrentPage = 1;
      renderLibraryFilters();
      renderLibrary();
      updateLibraryCreateButton();
    });
    box.appendChild(button);
  }
}

function librarySorted(items) {
  const sort = $("library-sort")?.value || "recent";
  const copy = [...items];
  if (sort === "az") {
    copy.sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
  } else if (sort === "biggest") {
    // Within a kind this is words, turns or bytes; across a mixed list it is
    // whichever of those each card is showing. Deliberately not normalised: 
    // a number that made a document's words comparable with an image's bytes
    // would sort cleanly and mean nothing.
    copy.sort((a, b) => (b.size || 0) - (a.size || 0));
  } else {
    copy.sort((a, b) => {
      const cmp = String(a.updated_at).localeCompare(String(b.updated_at));
      return sort === "oldest" ? cmp : -cmp;
    });
  }
  return copy;
}

// Meaning-matched note ids for the Library's current query, or null when the
// Semantic toggle is off (or the query is empty, or the search failed).
//
// **The design question this answers, which is why it was not built sooner.**
// The Library mixes notes, documents, chats, images and skills, and only
// *notes* have embeddings: nothing in this app has ever embedded a PDF, a
// conversation or an image. So "semantic search over the Library" has no
// single honest meaning, and the two tempting answers are both wrong: pretend
// everything is searched by meaning (it is not, and the results would quietly
// be keyword results for four of the five kinds), or refuse to offer it at all
// (which is what happened, and left the Library the one search box in the app
// with no meaning option).
//
// The answer taken: **meaning where there is meaning to search, words
// everywhere else, and say so on the control.** A note matches if the semantic
// search returned it *or* its words match; every other kind matches on words,
// exactly as before. Turning the toggle on can therefore only ever *add*
// results, never remove one, which is the property that makes it safe to
// leave on, and the reason the two filters are OR-ed rather than swapped.
//
// Reuses `GET /entries?semantic=true`, the same endpoint and the same
// server-side bound (`SEMANTIC_LIST_LIMIT`) the Notes tab's own toggle uses.
let librarySemanticIds = null;
let librarySemanticQuery = "";

async function refreshLibrarySemantic() {
  const query = ($("library-search")?.value || "").trim();
  const on = $("library-semantic-toggle")?.checked;
  if (!on || !query) {
    librarySemanticIds = null;
    librarySemanticQuery = "";
    return;
  }
  if (query === librarySemanticQuery) return; // already have this one
  try {
    const results = await apiJson(`/entries?q=${encodeURIComponent(query)}&semantic=true`);
    librarySemanticIds = new Set(results.map((entry) => entry.id));
    librarySemanticQuery = query;
  } catch {
    // No embedding backend, or the search failed. Falling back to keyword-only
    // is the same graceful degradation the rest of the app uses when the AI is
    // unavailable: never a failed search, just a less clever one.
    librarySemanticIds = null;
    librarySemanticQuery = "";
  }
}

function renderLibrary() {
  const grid = $("library-grid");
  if (!grid) return;
  const query = ($("library-search")?.value || "").trim().toLowerCase();
  let items = libraryItems;
  // "meeting" isn't a real kind (item.kind is still "note"), a meeting note
  // is a real, finished note, unlike a draft, so it stays reachable from
  // "Everything" too and doesn't get its own excluded bucket there. The chip
  // is a client-side tag filter over the same notes the Notes chip shows,
  // not a second list the server computes.
  if (libraryKind === "meeting") {
    items = items.filter((i) => i.kind === "note" && (i.tags || []).includes("meeting"));
  } else if (libraryKind !== "all") items = items.filter((i) => i.kind === libraryKind);
  else {
    // Two kinds stay out of the mixed list. Deleted things are not part of
    // "everything you have made", they are things you decided you had not , 
    // and the Include-bin toggle is how you ask for them anyway.
    //
    // **Activity is out unconditionally, and that is not a toggle worth
    // offering.** Measured on a small notebook: 164 activity rows against 13
    // things, so "Everything" was 93% log. A log is a record *about* the
    // notebook rather than a thing in it, and burying twelve documents under
    // it would make the default view useless in exactly the way a management
    // screen must not be. Its own chip shows it in full.
    // Drafts join activity in being excluded from "Everything": they are
    // unfinished by definition, and a draft appearing as a first-class card
    // here was reported and fixed once already (see _notes() in
    // routes_library.py). The Drafts chip is how you ask for them.
    items = items.filter((i) => i.kind !== "activity" && i.kind !== "draft");
    if (!$("library-show-binned")?.checked) {
      items = items.filter((i) => i.kind !== "archived");
    }
    // Shelved notes get the same "kept, out of the way" treatment as
    // activity: no extra checkbox, since the "Archived" chip already
    // gives full access, and this is the one place "kept out of the way"
    // actually matters: the mixed view is exactly where an archived note
    // would otherwise clutter the notebook it was archived to get out of.
    items = items.filter((i) => i.kind !== "shelved");
  }
  if (query) {
    // Title *and* preview, for the same reason the conversation search reads
    // message text: you remember what a thing was about far more often than
    // what it ended up being called.
    const wordMatch = (i) =>
      (i.title || "").toLowerCase().includes(query) ||
      (i.preview || "").toLowerCase().includes(query);
    // With Semantic on, a note also matches if the meaning search returned it,
    // even when it shares no words with the query. Everything else is
    // unchanged: see `librarySemanticIds`.
    items = librarySemanticIds
      ? items.filter((i) => (i.kind === "note" && librarySemanticIds.has(i.id)) || wordMatch(i))
      : items.filter(wordMatch);
  }
  items = librarySorted(items);

  // Sliced after filtering/sorting and before the render loop below, same
  // point renderLibraryDocuments() slices at.
  const pageBar = $("library-pagination");
  if (libraryPageSize === "all" || !items.length) {
    pageBar?.classList.add("hidden");
  } else {
    const pageSize = Number(libraryPageSize);
    const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
    libraryCurrentPage = Math.min(Math.max(1, libraryCurrentPage), totalPages);
    const start = (libraryCurrentPage - 1) * pageSize;
    items = items.slice(start, start + pageSize);
    pageBar?.classList.remove("hidden");
    $("library-page-status").textContent = `Page ${libraryCurrentPage} of ${totalPages}`;
    $("library-page-prev").disabled = libraryCurrentPage <= 1;
    $("library-page-next").disabled = libraryCurrentPage >= totalPages;
  }

  const updateDOM = () => {
    grid.replaceChildren();
    grid.classList.toggle("library-list", libraryView() === "list");
    // Same incremental renderer the Notes list uses. The Library holds notes,
    // documents, images, chats and skills together, so it is the one list that
    // can be larger than any single collection in the app.
    renderIncrementally(grid, items, (item) => libraryCard(item), {
      afterChunk: () => {
        renderLibraryContextBars();
        //: **The thumbnail column is only reserved when a thumbnail exists.**
        //: Reported: "fix the wierd gap at the start of all the cards in the
        //: library line view in the all subtab." List view reserves a 3rem
        //: slot on every row *without* a picture so the rows that have one
        //: still line up -- correct when some rows have pictures, and on a
        //: notebook where none do it indents the entire list by 48px of
        //: nothing. CSS cannot ask whether any sibling has one; this can, so
        //: the class says so and the rule keys off it.
        grid.classList.toggle("has-thumbs", Boolean(grid.querySelector(".library-card-thumb")));
      },
    });

    const empty = $("library-empty");
    empty.classList.toggle("hidden", items.length > 0);
    if (!items.length) {
      $("library-empty-title").textContent = !libraryItems.length
        ? "Nothing here yet. Write a document, start a chat, or attach a file to a note."
        : query
          ? `Nothing matching “${$("library-search").value.trim()}”.`
          : "Nothing of this kind yet.";
    }
  };

  // Premium UI: Use native View Transitions for buttery smooth layout animations
  if (!document.startViewTransition) {
    updateDOM();
  } else {
    document.startViewTransition(() => updateDOM());
  }
}

// What you can do to a thing without leaving the surface you found it on. A
// library that could only *show* you a document would send you to the Documents
// page to rename it and to the bin panel to restore a note, which is the
// scatter it was built to end.
//
// One ⋯ per card rather than a row of icons, the same choice the note cards
// and the chat list already make: three buttons on a card this size is most of
// the card, and the actions are things you do occasionally to a thing you are
// mostly here to open.
function libraryActions(item) {
  const reload = () => loadLibrary();
  if (item.kind === "chat") {
    return [
      makeMenuItem(
        item.pinned ? "ph:push-pin-slash Unpin" : "ph:push-pin Pin",
        item.pinned ? "Let this chat sort by date again" : "Keep this chat at the top",
        async () => {
          await apiJson(`/conversations/${item.id}/pin`, {
            method: "PUT",
            body: JSON.stringify({ pinned: !item.pinned }),
          }).catch((e) => toast(e.message, true));
          reload();
        }
      ),
      makeMenuItem("ph:pencil-simple Rename", "Rename this chat", async () => {
        const next = await promptDialog("Rename this chat:", item.title);
        if (!next) return;
        await apiJson(`/conversations/${item.id}`, {
          method: "PUT",
          body: JSON.stringify({ title: next }),
        }).catch((e) => toast(e.message, true));
        reload();
        loadConversationList();
      }),
      makeMenuItem("ph:archive Archive", "Keep it, but out of the way, not deleted", async () => {
        await apiJson(`/conversations/${item.id}/archive`, { method: "PUT" }).catch((e) =>
          toast(e.message, true)
        );
        if (chatConv && chatConv.id === item.id) newChatConversation();
        toast("Archived.");
        reload();
        loadConversationList();
      }),
      makeMenuItem("ph:trash Delete", "Delete this chat", async () => {
        if (!(await confirmDialog("Delete this saved chat?"))) return;
        await apiJson(`/conversations/${item.id}`, { method: "DELETE" }).catch((e) =>
          toast(e.message, true)
        );
        if (chatConv && chatConv.id === item.id) newChatConversation();
        reload();
        loadConversationList();
      }),
    ];
  }
  if (item.kind === "document") {
    return [
      makeMenuItem("ph:pencil-simple Rename", "Rename this document", async () => {
        const next = await promptDialog("Rename this document:", item.title);
        if (!next) return;
        await apiJson(`/documents/${item.id}`, {
          method: "PUT",
          body: JSON.stringify({ title: next }),
        }).catch((e) => toast(e.message, true));
        reload();
      }),
      makeMenuItem("⬇ Download .md", "Save a copy as a markdown file", () => {
        window.open(`/documents/${item.id}/export.md`, "_blank");
      }),
      makeMenuItem("ph:archive Archive", "Keep it, but out of the way, not deleted", async () => {
        await apiJson(`/documents/${item.id}/archive`, { method: "PUT" }).catch((e) =>
          toast(e.message, true)
        );
        toast("Archived.");
        reload();
      }),
      makeMenuItem("ph:trash Delete", "Delete this document", async () => {
        if (
          !(await confirmDialog(`Delete “${item.title}”? You can undo this straight after.`))
        ) {
          return;
        }
        //: The same helper the Documents tab's own two delete buttons use
        //: (`documents.js`), so all three doors offer the same Undo rather
        //: than one of them being permanent because it was written later.
        await deleteDocumentWithUndo(item).catch((e) => toast(e.message, true));
        reload();
      }),
    ];
  }
  if (item.kind === "archived") {
    return [
      makeMenuItem("ph:arrow-u-up-left Restore", "Put this note back in your notebook", async () => {
        await apiJson(`/entries/${item.id}/restore`, { method: "POST" }).catch((e) =>
          toast(e.message, true)
        );
        toast("Restored.");
        reload();
        loadEntries();
      }),
      // The bin's other half. Without it the Library can show you a binned
      // note and take you back to the old panel to get rid of it, which is the
      // two-places problem the move was for.
      makeMenuItem("ph:trash Delete for good", "Permanently delete this note", async () => {
        if (!(await confirmDialog("Delete this note permanently?\n\nThis cannot be undone."))) return;
        await apiJson(`/entries/${item.id}/purge`, { method: "DELETE" }).catch((e) =>
          toast(e.message, true)
        );
        reload();
      }),
    ];
  }
  if (item.kind === "shelved") {
    // Notes, chats and documents all land in "shelved" (routes_library.
    // _shelved), each with its own unarchive route/method and its own
    // "bring it back to..." wording: `subtype` is what tells them apart.
    const UNARCHIVE = {
      note: { url: `/entries/${item.id}/unarchive`, method: "POST", noun: "note", reload: () => loadEntries() },
      chat: { url: `/conversations/${item.id}/unarchive`, method: "PUT", noun: "chat", reload: () => loadConversationList() },
      document: { url: `/documents/${item.id}/unarchive`, method: "PUT", noun: "document", reload: () => {} },
    };
    const target = UNARCHIVE[item.subtype] || UNARCHIVE.note;
    return [
      makeMenuItem(
        "ph:arrow-u-up-left Unarchive",
        `Bring this ${target.noun} back into your notebook`,
        async () => {
          await apiJson(target.url, { method: target.method }).catch((e) => toast(e.message, true));
          toast("Unarchived.");
          reload();
          target.reload();
        }
      ),
      // No delete-for-good here: an archived item was never at risk of
      // being lost, that's the whole difference from the bin above, so
      // the only way out of this list is back to the notebook.
    ];
  }
  if (item.kind === "note") {
    return [
      makeMenuItem("ph:arrow-square-out Open in Notes", "Show this note in the list", () => flashEntry(item.id)),
      // BACKLOG.md §95 item D.14: "Full export exists. There is no way to
      // hand one note to someone." Same route shape and menu placement as
      // the Document kind's own "Download .md" a few lines up.
      makeMenuItem("⬇ Download .md", "Save a copy of this note as a markdown file", () => {
        window.open(`/entries/${item.id}/export.md`, "_blank");
      }),
      makeMenuItem("ph:archive Archive", "Keep it, but out of the way, not the bin", async () => {
        await apiJson(`/entries/${item.id}/archive`, { method: "POST" }).catch((e) =>
          toast(e.message, true)
        );
        toast("Archived.");
        reload();
        loadEntries();
      }),
      makeMenuItem("ph:trash Move to bin", "Bin this note: recoverable", async () => {
        try {
          await apiJson(`/entries/${item.id}`, { method: "DELETE" });
        } catch (e) {
          toast(e.message, true);
          return;
        }
        reload();
        loadEntries();
        //: The one bin action in the app without Undo on its toast: the
        //: Notes tab's had it (pushUndo, the undo bar and the toast agree),
        //: the Library's card menu did not. Same recipe, same words.
        const restoreIt = async () => {
          await apiJson(`/entries/${item.id}/restore`, { method: "POST" });
          reload();
          loadEntries();
        };
        const binIt = async () => {
          await apiJson(`/entries/${item.id}`, { method: "DELETE" });
          reload();
          loadEntries();
        };
        const action = pushUndo("Moved a note to the bin", restoreIt, binIt);
        toastAction("Moved to the recycle bin.", "Undo", async () => {
          settleUndoFromToast(action);
          await restoreIt();
          toast("Note restored.");
        });
      }),
    ];
  }
  if (item.kind === "tag") {
    return [
      makeMenuItem("ph:pencil-simple Rename", "Rename this tag everywhere (merge if it exists)", async () => {
        const next = await promptDialog(`Rename tag “${item.title}” to:`, item.title);
        if (!next || next === item.title) return;
        const result = await apiJson("/tags/rename", {
          method: "POST",
          body: JSON.stringify({ old: item.title, new: next }),
        }).catch((e) => {
          toast(e.message, true);
          return null;
        });
        if (result) toast(`Renamed on ${result.changed} note${result.changed === 1 ? "" : "s"}.`);
        reload();
        loadEntries();
      }),
      makeMenuItem("ph:trash Remove everywhere", "Take this tag off every note", async () => {
        if (!(await confirmDialog(`Remove the tag “${item.title}” from every note?\n\nThe notes are untouched.`))) return;
        await apiJson("/tags/delete", {
          method: "POST",
          body: JSON.stringify({ name: item.title }),
        }).catch((e) => toast(e.message, true));
        reload();
        loadEntries();
      }),
    ];
  }
  // An activity row is a record of something that already happened. There is
  // nothing to do to it, so it gets no menu at all rather than an empty one.
  if (item.kind === "activity") return [];
  if (item.kind === "file") {
    return [
      // `window.open` never attaches the `X-Auth-Token` header a plain
      // navigation can't carry: the same gap `mediaSrc` already exists to
      // close for `<img src>`, just missed here. Every notebook with a
      // password set (the normal case) 401'd on Download until this.
      makeMenuItem("⬇ Download", "Save this file", () => {
        window.open(mediaSrc(`/files/${item.id}`), "_blank");
      }),
      // Live-reported: an uploaded file "can't be deleted", true for its
      // own ⋯ menu specifically; bulk-select delete already worked
      // (`library-bulk-delete` already has a `file` branch), but nothing
      // offered it from the one place someone looks first.
      makeMenuItem("ph:trash Delete", "Remove this file permanently", async () => {
        if (!(await confirmDialog(`Delete "${item.title}"?\n\nThis cannot be undone.`))) return;
        await apiJson(`/files/${item.id}`, { method: "DELETE" }).catch((e) => toast(e.message, true));
        toast("Deleted.");
        reload();
      }),
    ];
  }
  return [];
}

// The two strips that only appear when they have something to say.
function renderLibraryContextBars() {
  // The bin's own controls, where the bin now is. "Empty now" used to live in
  // a panel behind a sidebar button; a Bin filter you can look at but not
  // empty is half a move, and half a move leaves the user with two places.
  const binBar = $("library-binbar");
  const showingBin = libraryKind === "archived";
  binBar.classList.toggle("hidden", !showingBin);
  if (showingBin) {
    const count = libraryCounts.archived || 0;
    // "Kept for N days" came down from the deleted #bin-panel, which is the
    // one thing it said that this bar did not. It is the difference between a
    // bin you can trust to clear itself and one you assume you have to empty.
    const days = prefsCache ? prefsCache.recycle_bin_days : 30;
    $("library-bin-note").textContent = count
      ? `${count} note${count === 1 ? "" : "s"} in the bin, kept for ${days} days ` +
        "then cleared automatically. Open one to read it, or use its ⋯ menu."
      : `The bin is empty. Deleted notes are kept here for ${days} days ` +
        "(change that in Preferences) before they clear.";
    $("library-bin-empty").disabled = !count;
  }

  const bar = $("library-selectbar");
  const chosen = [...librarySelection];
  bar.classList.toggle("hidden", chosen.length === 0);
  if (!chosen.length) return;
  $("library-selected-count").textContent =
    `${chosen.length} selected`;
  // Restore only makes sense for binned notes, and offering it for a document
  // is offering a button that cannot work.
  const allBinned = chosen.every((key) => key.startsWith("archived:"));
  $("library-bulk-restore").classList.toggle("hidden", !allBinned);
}

function librarySelectedItems() {
  return libraryItems.filter((item) => librarySelection.has(libraryKeyOf(item)));
}

function toggleLibrarySelection(item, on) {
  const key = libraryKeyOf(item);
  if (on) librarySelection.add(key);
  else librarySelection.delete(key);
  renderLibraryContextBars();
}

function libraryCard(item) {
  // An `<article>` rather than a `<button>`: the card carries its own ⋯ menu,
  // and a button inside a button is invalid markup that browsers resolve by
  // dropping one of them. The click, the keyboard and the role are all here
  // explicitly instead, which is what the button element was giving us.
  const card = document.createElement("article");
  card.className =
    `library-card library-${item.kind}` + (item.private ? " library-private" : "");
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  // Lets a caller (flashLibraryItem) find one specific card to scroll to and
  // highlight, the same way #entry-list li[data-id] already works for notes.
  card.dataset.id = item.id;
  const meta = LIBRARY_KINDS.find((k) => k.key === item.kind);

  // A thumbnail where there is one to show. A grid of picture files that shows
  // the word "PNG" seven times is a list pretending to be a gallery, and this
  // is the one kind whose content *is* what it looks like.
  if (item.kind === "file" && (item.mime || "").startsWith("image/")) {
    const thumb = document.createElement("img");
    thumb.className = "library-card-thumb";
    thumb.src = mediaSrc(`/files/${item.id}`);
    thumb.alt = "";
    thumb.loading = "lazy";
    // A file whose bytes have gone leaves a broken-image glyph, which reads as
    // a bug in the Library rather than as a missing file.
    thumb.addEventListener("error", () => thumb.remove());
    card.appendChild(thumb);
  } else if (
    (item.kind === "note" || item.kind === "shelved" || item.kind === "archived") &&
    (item.thumb_attachment_id || item.thumb_url)
  ) {
    // A sketch is a note whose actual content is a file attachment, not
    // text: without this a sketch card in the Library was a bare title
    // with nothing under it, indistinguishable from any empty note.
    //
    // `thumb_url` is the other half of the same fix: a pasted or dropped
    // image lives as inline markdown in the note's own content, never as an
    // Attachment, so it needed its own source, a sketch's card showed its
    // drawing and a pasted-image note's card showed nothing at all, which
    // is the inconsistency this closes. Already an absolute URL
    // (`/media/...` or `https://...`, whatever the note itself renders it
    // as), so it goes to mediaSrc() as-is rather than through `/files/{id}`.
    const thumb = document.createElement("img");
    thumb.className = "library-card-thumb";
    thumb.src = item.thumb_attachment_id
      ? mediaSrc(`/files/${item.thumb_attachment_id}`)
      : mediaSrc(item.thumb_url);
    thumb.alt = "";
    thumb.loading = "lazy";
    thumb.addEventListener("error", () => thumb.remove());
    card.appendChild(thumb);
  }

  const top = document.createElement("div");
  top.className = "library-card-top";
  // Tick to select. Only for the kinds a bulk action can actually do something
  // to: an activity row is a record of the past and a tag is not a file, so
  // offering either a checkbox would be offering a Delete that does nothing.
  if (item.kind !== "activity" && item.kind !== "tag") {
    const tick = document.createElement("input");
    tick.type = "checkbox";
    tick.className = "library-card-tick";
    tick.checked = librarySelection.has(libraryKeyOf(item));
    tick.setAttribute("aria-label", `Select ${item.title}`);
    tick.addEventListener("click", (event) => event.stopPropagation());
    tick.addEventListener("change", () => toggleLibrarySelection(item, tick.checked));
    top.appendChild(tick);
  }
  const icon = document.createElement("span");
  icon.className = "library-card-icon";
  setLabel(icon, meta ? meta.icon : "•");
  if (meta && meta.label) {
    icon.setAttribute("role", "img");
    icon.setAttribute("aria-label", meta.label);
  } else {
    icon.setAttribute("aria-hidden", "true");
  }
  const title = document.createElement("strong");
  title.className = "library-card-title";
  // A note's title is its first line, so it carries the note's own markup too.
  // Everything else has a real title and renders as plain text through the
  // same call, which is harmless.
  // Strip block markdown (like headings) from the title before inline rendering,
  // so a note starting with `# Title` doesn't show the raw `# `.
  const cleanTitle = item.title.replace(/^#{1,6}\s+/gm, "").replace(/^>\s?/gm, "");
  renderInlineMarkdown(title, cleanTitle, []);
  // The 2-line clamp above cuts a long title off mid-word with no way to read
  // the rest short of opening the card, a native tooltip costs nothing.
  title.title = cleanTitle;
  top.append(icon, title);
  if (item.pinned) {
    //: **The same flag means two different things here**, and this card is
    //: the one place both kinds land side by side. A pinned *chat* is kept at
    //: the top of the list, that is a pin. A pinned *note* is a Favourite:
    //: one flag that both floats it and collects it into the sidebar's
    //: Favourites row, renamed everywhere else and missed here.
    const isChat = item.kind === "chat";
    const pin = document.createElement("span");
    setLabel(pin, isChat ? "ph:push-pin" : "ph:star");
    pin.title = isChat ? "Pinned" : "Favourite";
    top.appendChild(pin);
  }
  card.appendChild(top);

  // A chat's title *is* its first question, so its preview would be the same
  // sentence again one line down and one shade greyer, a card that looks like
  // a bug rather than one with more metadata on it.
  //
  // **But "starts with the title" was the wrong test**, and it is what was
  // behind "I can't see a lot of the response in the cards": a *note's* title
  // is the first 60 characters of the note, so every note card matched and
  // every note card lost its preview entirely, leaving 60 characters of a
  // 420-character card. The question is not whether the preview begins with
  // the title, it is whether it goes on to say anything more.
  const bare = cleanTitle.replace(/…$/, "").trim();
  const sameAsTitle =
    item.preview &&
    bare &&
    item.preview.startsWith(bare) &&
    item.preview.trim().length <= bare.length + 1;
  if (item.preview && !sameAsTitle) {
    const preview = document.createElement("p");
    preview.className = "library-card-preview";
    // Inline markdown, the same renderer the note list uses (§22): a note
    // written with **bold** and `code` in it was showing its asterisks and
    // backticks here, which is the Library rendering the *source* of a note
    // while every other surface renders the note. Inline only: block elements
    // would turn a card into a document, which is what the clamp is for.
    const cleanPreview = item.preview.replace(/^#{1,6}\s+/gm, "").replace(/^>\s?/gm, "");
    renderInlineMarkdown(preview, cleanPreview, []);
    card.appendChild(preview);
  }

  const foot = document.createElement("div");
  foot.className = "library-card-meta";
  const detail = document.createElement("span");
  setLabel(detail, item.detail);
  const when = document.createElement("span");
  when.textContent = relativeTime(item.updated_at);
  when.title = new Date(item.updated_at).toLocaleString();
  foot.append(detail, when);
  card.appendChild(foot);

  const kindWord = meta ? meta.label.replace(/s$/, "") : item.kind;
  card.title = `${kindWord} · ${item.title}`;
  card.setAttribute("aria-label", `${kindWord}: ${item.title}. ${item.detail}.`);

  const actions = libraryActions(item);
  if (actions.length) {
    const menu = kebabMenu(actions, `Actions for ${item.title}`);
    menu.classList.add("library-card-menu");
  // The menu is inside the card and the card is a click target, so every click
  // in the menu would also open the thing. Stopped here rather than on each
  // item: the opener, the popup's padding and its backdrop are all inside this
  // element, and only one of the three is a button.
    menu.addEventListener("click", (event) => event.stopPropagation());
    card.appendChild(menu);
  }

  card.addEventListener("click", () => openLibraryItem(item));
  // An <article role="button"> gets neither of these for free, this is the
  // half of the button element we gave up to be allowed a menu inside.
  card.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    if (event.target !== card) return; // a key pressed inside the menu is the menu's
    event.preventDefault();
    openLibraryItem(item);
  });
  return card;
}

// Each kind opens where it is actually worked on. The Library finds things; it
// is not a fifth editor.
function openLibraryItem(item) {
  if (item.kind === "document") {
    openDocumentFromNote(item.id); // the Documents page, on this document
  } else if (item.kind === "chat") {
    switchTab("chat");
    openConversation(item.id);
  } else if (item.kind === "file") {
    // The note, not the raw file: a download is one click further and the note
    // is the thing that says why the file was kept.
    flashEntry(item.entry_id);
  } else if (item.kind === "board" || item.kind === "map") {
    //: The board, not the entry behind it. Opening the note would show the
    //: row a board happens to be stored in, which is an empty note, and is
    //: the same class of mistake as drawing it with a pencil icon.
    if (typeof openWhiteboardBoard === "function") openWhiteboardBoard(item.id);
    else flashEntry(item.id);
  } else if (item.kind === "note" || item.kind === "draft") {
    // Drafts open exactly like notes. flashEntry already knows how, it turns
    // the Drafts filter on when its target is one, because drafts are excluded
    // from every other view. What was missing was this branch: the "draft"
    // kind arrived with the Library's new Drafts chip and nothing routed it,
    // so selecting a draft and pressing Open did nothing at all.
    flashEntry(item.id);
  } else if (item.kind === "tag") {
    // A tag's job is finding the notes that carry it, so opening one does
    // exactly that rather than opening a tag editor nobody asked for.
    switchTab("notes");
    showNotesSection("browse");
    const box = $("note-search");
    if (box) {
      box.value = `tag:${item.title}`;
      box.dispatchEvent(new Event("input", { bubbles: true }));
    }
  } else if (item.kind === "activity" && item.entry_id) {
    // The note the entry in the log is about, when it still exists.
    flashEntry(item.entry_id);
  } else if (item.kind === "activity") {
    // No related note to jump to (a preference change, a tag merge, a
    // password change): the click's only useful job left is showing the
    // whole record. `item.preview` is what the card already shows, clipped
    // to ACTIVITY_DETAIL_CHARS server-side; re-fetching by id gets the
    // record's real, un-clipped `detail` for anything long enough to have
    // lost the end of it.
    apiJson(`/audit?id=${item.id}&limit=1`)
      .then((rows) => showDetailDialog(item.title, rows[0]?.detail || item.preview || "(no detail recorded)"))
      .catch(() => showDetailDialog(item.title, item.preview || "(no detail recorded)"));
  } else if (item.kind === "archived") {
    // Restore and permanent delete are both on this card's own ⋯ menu, and
    // reading the note in full is the one thing a card cannot do, so that is
    // all this opens. It used to send the user to #bin-panel, which is the
    // only reason that panel outlived the Library's Bin chip.
    openBinnedNote(item.id);
  }
}

// --- reading a binned note in full (§36G) ----------------------------------
//
// **This is what let #bin-panel be deleted.** The Library card shows a
// preview, which is right for a grid of mixed things and wrong as the only
// way to see a note you are about to destroy, "restore or delete for good?"
// is a question you answer by reading the note, and the panel was the last
// place in the app that could still show one.
//
// Read-only. Editing a binned note would mean deciding whether the edit
// un-deletes it, and the honest answer is that you restore it first.
let binnedNoteId = null;

async function openBinnedNote(entryId) {
  binnedNoteId = entryId;
  const overlay = $("binned-overlay");
  const body = $("binned-body");
  body.replaceChildren();
  $("binned-meta").textContent = "Loading…";
  overlay.classList.remove("hidden");
  $("binned-close").focus();
  let entry;
  try {
    // `?deleted=true`, an ordinary read still 404s on a binned note, so
    // reaching into the bin is something the caller says it means to do.
    entry = await apiJson(`/entries/${entryId}?deleted=true`);
  } catch (error) {
    $("binned-meta").textContent = `Couldn't open that note: ${error.message}`;
    return;
  }
  if (binnedNoteId !== entryId) return; // a second open overtook this one
  const days = prefsCache ? prefsCache.recycle_bin_days : 30;
  const binned = entry.deleted_at ? relativeTime(entry.deleted_at) : "recently";
  $("binned-meta").textContent =
    `Deleted ${binned} · written ${relativeTime(entry.created_at)} · ` +
    `kept for ${days} days from deletion, then cleared automatically.`;
  // The note's own markdown, as the notebook renders it everywhere else. A
  // binned note is still a note, and showing it as flat text here would make
  // it look like a different, lesser thing than the one you deleted.
  renderMarkdown(body, entry.content || "");
}

function closeBinnedReader() {
  binnedNoteId = null;
  $("binned-overlay").classList.add("hidden");
}

$("binned-close").addEventListener("click", closeBinnedReader);
$("binned-restore").addEventListener("click", async () => {
  const id = binnedNoteId;
  if (!id) return;
  try {
    await apiJson(`/entries/${id}/restore`, { method: "POST" });
    toast("Restored.");
  } catch (error) {
    toast(`Couldn't restore that note: ${error.message}`, true);
    return;
  }
  closeBinnedReader();
  loadLibrary();
  loadEntries();
});
$("binned-purge").addEventListener("click", async () => {
  const id = binnedNoteId;
  if (!id) return;
  // The note is on screen and has just been read, so the dialog does not have
  // to quote it back the way the old bin row's did: "this cannot be undone"
  // is the whole of what is left to say.
  if (!(await confirmDialog("Permanently delete this note?\n\nThis cannot be undone."))) return;
  try {
    await apiJson(`/entries/${id}/purge`, { method: "DELETE" });
    toast("Deleted for good.");
  } catch (error) {
    toast(`Couldn't delete that note: ${error.message}`, true);
    return;
  }
  closeBinnedReader();
  loadLibrary();
});

// BACKLOG §22's still-open half of "take me to the thing the agent just
// changed": a destructive result (delete_note) used to reuse flashEntry,
// which only ever looks in the ordinary browse list, a note the agent just
// binned is never there, so the "View" button silently found nothing. This
// looks in the Library's own Bin filter instead, the one place a binned note
// actually lives (routes_library.py's _archive(), kind "archived").
async function flashLibraryItem(kind, id) {
  switchTab("library"); // already kicks off its own loadLibrary() in the background
  libraryKind = kind;
  const showBinned = $("library-show-binned");
  if (kind === "archived" && showBinned) showBinned.checked = true;
  renderLibraryFilters();
  renderLibrary(); // in case libraryItems is already fresh (tab was already open)
  // switchTab's own loadLibrary() fetch may still be in flight, starting a
  // second one here to await would race it, and whichever finishes last wins
  // the final render, silently dropping the flash the other one applied.
  // Polling for the card sidesteps the race: it waits for whichever render
  // actually lands instead of assuming which one that is.
  const card = await (async () => {
    for (let i = 0; i < 20; i++) {
      const found = document.querySelector(`#library-grid [data-id="${id}"]`);
      if (found) return found;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    return null;
  })();
  if (!card) return;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  card.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
  // "flash" alone only draws on a note-list <li> or something already
  // carrying "flash-target" (01-forms-settings.css): a library card is
  // neither, so both classes are needed here for the highlight to render.
  card.classList.remove("flash");
  void card.offsetWidth;
  card.classList.add("flash-target", "flash");
  announce("Showing item in the Library.");
  clearTimeout(flashLibraryItem.timer);
  flashLibraryItem.timer = setTimeout(() => card.classList.remove("flash"), 2700);
}

// "+ New Skill" on the Library's AI Skills page. Reported as doing nothing,
// and it did nothing: the button was in the markup and no handler was ever
// attached to it. The skill editor lives in Settings → Skills, so this opens
// that with a blank form rather than growing a second editor that would then
// have to be kept in step with the first.
$("skills-add-new")?.addEventListener("click", async () => {
  await openSettingsModal("skills");
  stopEditingSkill();           // clears the form and resets the button label
  $("skill-name")?.focus();
});

// The Library (§4, §36F). Filter and sort are first-class here rather than an
// afterthought, so they are wired like controls: every change re-renders from
// the list already in memory, with no round trip.
let librarySearchDebounceTimeout;
async function runLibrarySearch() {
  await refreshLibrarySemantic();
  libraryCurrentPage = 1; // a new search can move an item off whatever page it was on
  renderLibrary();
}
$("library-semantic-toggle").addEventListener("change", () => {
  syncLibraryFilterButton();
  runLibrarySearch();
});
$("library-search").addEventListener("input", () => {
  clearTimeout(librarySearchDebounceTimeout);
  librarySearchDebounceTimeout = setTimeout(runLibrarySearch, 150);
});
$("library-sort").addEventListener("change", () => {
  libraryCurrentPage = 1;
  renderLibrary();
});
//: The Filter menu's button says when a filter is on (Phase 8): a menu that
//: hides "Include bin" must not also hide that the bin is being shown.
function syncLibraryFilterButton() {
  const on = Boolean($("library-semantic-toggle")?.checked || $("library-show-binned")?.checked);
  const summary = document.querySelector("#library-filter-menu > summary");
  summary?.classList.toggle("is-on", on);
  summary?.setAttribute("aria-pressed", String(on));
}
$("library-show-binned").addEventListener("change", () => {
  libraryCurrentPage = 1;
  syncLibraryFilterButton();
  renderLibrary();
});
for (const button of document.querySelectorAll("#library-view button, #library-boards-view button")) {
  button.addEventListener("click", () => {
    localStorage.setItem(LIBRARY_VIEW_KEY, button.dataset.libraryView);
    renderLibraryView();
    renderLibrary();
    //: The boards gallery lives in whiteboard.js and renders from its own
    //: fetch; re-rendering it here is what makes the switch take effect on
    //: the sub-tab you pressed it on rather than on your next visit.
    window.renderLibraryBoardsGallery?.();
  });
}
// The bin's own control, on the bin's own screen.
$("library-bin-empty").addEventListener("click", async () => {
  const count = libraryCounts.archived || 0;
  const ok = await confirmDialog(
    `Permanently delete ${count} note${count === 1 ? "" : "s"} in the bin?\n\n` +
      "This cannot be undone."
  );
  if (!ok) return;
  try {
    await apiJson("/recycle-bin/empty", { method: "POST" });
  } catch (e) {
    // Was unconditional before: a failed request still showed "The bin is
    // empty." right under its own error toast, one saying it worked and one
    // saying it didn't, for the same click.
    toast(e.message, true);
    return;
  }
  toast("The bin is empty.");
  loadLibrary();
  loadEntries();
});

// --- bulk actions -------------------------------------------------------------
// The reason the Library is a management screen rather than a nicer list:
// doing one thing to nine things. Every one of these confirms with a *count*,
// because "delete 9 items" is the sentence that stops a mistake and "are you
// sure?" is the one that doesn't.
$("library-clear-selection").addEventListener("click", () => {
  librarySelection = new Set();
  renderLibrary();
});
$("library-bulk-open").addEventListener("click", () => {
  const chosen = librarySelectedItems();
  if (!chosen.length) return;
  // One thing opens; several would be several tab switches ending wherever the
  // last one landed, so the honest answer is to open the first and say so.
  if (chosen.length > 1) toast(`Opening the first of ${chosen.length}.`);
  openLibraryItem(chosen[0]);
});
$("library-bulk-restore").addEventListener("click", async () => {
  const chosen = librarySelectedItems().filter((i) => i.kind === "archived");
  if (!chosen.length) return;
  // Was `.catch(() => {})` then an unconditional "Restored N notes." for
  // every item *attempted*: a per-item 404/500 was silently swallowed and
  // still counted as a success. Track real outcomes instead.
  let restored = 0;
  for (const item of chosen) {
    try {
      await apiJson(`/entries/${item.id}/restore`, { method: "POST" });
      restored++;
    } catch {
      // counted below
    }
  }
  if (restored) toast(`Restored ${restored} note${restored === 1 ? "" : "s"}.`);
  const failed = chosen.length - restored;
  if (failed) toast(`${failed} note${failed === 1 ? "" : "s"} couldn't be restored.`, true);
  loadLibrary();
  loadEntries();
});
$("library-bulk-delete").addEventListener("click", async () => {
  const chosen = librarySelectedItems();
  if (!chosen.length) return;
  // Binned notes are destroyed; everything else is deleted the way its own
  // menu deletes it. Saying which is which in the confirmation matters, 
  // "delete" means recoverable for a note and permanent for one already binned.
  const permanent = chosen.filter((i) => i.kind === "archived").length;
  const ok = await confirmDialog(
    `Delete ${chosen.length} item${chosen.length === 1 ? "" : "s"}?\n\n` +
      (permanent
        ? `${permanent} of them ${permanent === 1 ? "is" : "are"} already in the bin and will be destroyed permanently.`
        : "Notes go to the bin; documents and chats are deleted for good.")
  );
  if (!ok) return;
  // Same fix as library-bulk-restore just above: a per-item failure used to
  // be swallowed by `.catch(() => {})` and still counted toward the
  // unconditional "Deleted N items." toast. Track what actually succeeded.
  let deleted = 0;
  for (const item of chosen) {
    const route =
      item.kind === "archived"
        ? [`/entries/${item.id}/purge`, "DELETE"]
        : item.kind === "note"
          ? [`/entries/${item.id}`, "DELETE"]
          : item.kind === "document"
            ? [`/documents/${item.id}`, "DELETE"]
            : item.kind === "chat"
              ? [`/conversations/${item.id}`, "DELETE"]
              : item.kind === "file"
                ? [`/files/${item.id}`, "DELETE"]
                : null;
    if (!route) continue;
    try {
      await apiJson(route[0], { method: route[1] });
      deleted++;
    } catch {
      // counted below
    }
  }
  if (deleted) toast(`Deleted ${deleted} item${deleted === 1 ? "" : "s"}.`);
  const failed = chosen.length - deleted;
  if (failed) toast(`${failed} item${failed === 1 ? "" : "s"} couldn't be deleted.`, true);
  loadLibrary();
  loadEntries();
});
$("library-refresh").addEventListener("click", loadLibrary);

// **The "All" tab's create button, matched to whichever filter chip is
// active.** Reported directly: it always said "+ New document" and made a
// document regardless of whether you were looking at Notes, Chats or
// Meetings: the one obviously-wrong thing to create in three of those
// four views. `renderLibraryFilters()` (above) calls this every time the
// chip changes; the four kinds with one unambiguous thing to create get a
// matching button, everything else (Everything, Files, Tags, Drafts,
// Activity, the bin) falls back to "+ New note", the fastest capture path
// in the app, and a reasonable default when there's no single obvious
// answer. A real "choose what to create" picker for the Everything view
// specifically was asked for too but not built this pass, logged rather
// than rushed; see BACKLOG.md.
const LIBRARY_CREATE_BY_KIND = {
  note: {
    label: "＋ New note",
    run: () => {
      switchTab("notes");
      showNotesSection("capture", { focus: true });
    },
  },
  document: {
    label: "＋ New document",
    run: () => {
      switchTab("documents");
      // The Documents page's own loader opens the last document otherwise,
      // and a new one would be replaced a moment after it appeared.
      setTimeout(() => $("doc-new").click(), 160);
    },
  },
  chat: {
    label: "＋ New chat",
    run: () => {
      switchTab("chat");
      newChatConversation();
    },
  },
  meeting: {
    label: "⏺ Transcribe audio",
    run: () => openMeetingRecorder(),
  },
  // Asked for directly: "I want ways to make custom knowledge graphs that are
  // like mindmaps where I can add and remove nodes, move them around, change
  // how they connect and reasons, and just make my own thought process map"
  //, and, on where it should live, "I should be able to make and manage map
  // graphs (maybe in library??)".
  //
  // **This is a board, not a third canvas**, and that is the whole design
  // decision. The whiteboard already has every part of a concept map:
  // freely-placed cards whose positions persist, a link tool, Tab for a new
  // branch and Enter for a new sibling off the selected card, "Arrange as
  // mind map" to re-tidy, pan/zoom, undo, spaces, and export. What it did
  // not have was a *name*, nothing in the app said "concept map", so the
  // one feature the user was asking for was sitting behind a button called
  // "New board" on a tab called Whiteboards, which is why they reported it
  // missing. See `createConceptMap` for what the entry point adds on top.
  //
  // It also answers the deferred half of the ask, "maybe with a way to
  // export that into a visual diagram on the whiteboard", by construction:
  // the map *is* a whiteboard, so it exports through the export button that
  // is already there.
  map: {
    label: "ph:graph New concept map",
    run: () => createConceptMap(),
  },
  // Reported directly: "in the library 'all' subtab, the files section has
  // the general create button and not an upload button." It did: `file` had
  // no entry here, so it fell through to the "＋ Create" picker, which asks
  // you what you want to make when the answer for a file is never "make".
  //
  // It opens the Files sub-tab first and then the picker, so the upload
  // lands somewhere you are already looking rather than on a screen you
  // then have to go and find. That click also sets the file input's own
  // `accept` (see `setLibraryMediaKind`).
  file: {
    label: "ph:upload-simple Upload a file",
    run: () => {
      document
        .querySelector('#library-subtabs button[data-media-kind="files"]')
        ?.click();
      $("library-images-upload-input")?.click();
    },
  },
};

// **BACKLOG §105 item 1, built**: "Everything" and every kind with no
// single obvious answer (Files, Tags, Drafts, Activity, the bin) now open
// a real picker instead of silently defaulting to "+ New note", asked for
// again directly ("the buttons for creating and uploading the specific
// things"). A modal overlay, not a `kebabMenu()` dropdown: the button
// isn't wrapped in `.menu-wrap` the way every other kebab opener is, and
// `.library-view-section`'s own `overflow-y: auto` is exactly the clipping
// trap `wireEscapedActionMenu` exists to work around elsewhere, a full
// overlay sidesteps both instead of fighting them.
function openLibraryCreatePicker() {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay confirm-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "Choose what to create");

  const card = document.createElement("div");
  card.className = "card modal-card confirm-card";
  const text = document.createElement("p");
  text.className = "confirm-text";
  text.textContent = "What would you like to create?";
  const row = document.createElement("div");
  row.className = "row confirm-actions library-create-picker-actions";

  const returnFocus = document.activeElement;
  const close = () => {
    document.removeEventListener("keydown", onKey, true);
    overlay.remove();
    returnFocus?.focus?.();
  };
  const onKey = (event) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      close();
    }
  };

  for (const kind of ["note", "document", "map", "chat", "meeting"]) {
    const entry = LIBRARY_CREATE_BY_KIND[kind];
    const button = smallButton(entry.label, entry.label, () => {
      close();
      entry.run();
    }, false);
    row.appendChild(button);
  }
  const cancel = smallButton("Cancel", "Cancel", close);
  row.appendChild(cancel);

  card.append(text, row);
  overlay.appendChild(card);
  wireBackdropClose(overlay, () => close());
  document.addEventListener("keydown", onKey, true);
  document.body.appendChild(overlay);
  row.querySelector("button")?.focus();
}

function updateLibraryCreateButton() {
  const btn = $("library-new-doc");
  if (!btn) return;
  const entry = LIBRARY_CREATE_BY_KIND[libraryKind];
  if (entry) {
    setLabel(btn, entry.label);
    btn.title = entry.label.replace(/^\S+\s*/, "");
    btn.onclick = entry.run;
  } else {
    setLabel(btn, "＋ Create");
    btn.title = "Choose what to create";
    btn.onclick = openLibraryCreatePicker;
  }
}
updateLibraryCreateButton();

// ======================= SKILLS DASHBOARD TAB =======================

// --- the AI Skills page ---------------------------------------------------------
//
// Asked for: "can you redesign the AI Skills tab in the library??", and an
// audit of what was here first found five separate faults, four of which the
// redesign removes rather than restyles:
//
// 1. **The grid was never used.** A `div.skills-grid` was created, appended,
//    and then every card was appended to `container` instead: so the grid
//    layout applied to an empty box and the cards stacked full-width below
//    it. The "No skills found" message went *into* that empty box, which is
//    why an empty library looked like nothing at all.
// 2. **A dead control.** "Schedule" toasted "Scheduler functionality coming
//    soon!". A button that does nothing is worse than a missing feature: it
//    teaches people the app is unreliable. Gone; it is on the roadmap.
// 3. **`innerHTML` templates**, against this file's own rule, including a
//    `.switch`/`.slider` toggle that exists nowhere else in this app, so the
//    one toggle on this page looked unlike every other toggle in it.
// 4. **Nothing said what a skill would do.** A name and a description, with
//    no indication of how many steps it runs, which tools it may use, or
//    whether it has ever been run, which is exactly what you want to know
//    before letting something edit your notebook.
// 5. `window.switchTab` was monkey-patched to notice the Library opening.
//
// The shape now: one settings card for the background workers, then a search
// box, then a real grid of cards that each say what the skill is, what it
// costs to run, and when it last ran.

//: The skill cards currently on screen, so the search box can filter without
//: another round trip. Rebuilt by `renderSkillsDashboard`.
let skillCardsCache = [];

function skillLastRunIndex(rows) {
  //: name → the most recent audit row for it. The rows arrive newest-first,
  //: so the first one wins and later ones are skipped.
  const index = new Map();
  for (const row of rows || []) {
    const name = (row.detail || "").split(", ")[0];
    if (name && !index.has(name)) index.set(name, row);
  }
  return index;
}

function skillCard(skill, lastRun) {
  const card = document.createElement("article");
  card.className = "skill-card";

  const header = document.createElement("div");
  header.className = "skill-card-header";
  const title = document.createElement("h3");
  title.className = "skill-card-title";
  title.textContent = skill.name;
  const badge = document.createElement("span");
  badge.className = `chip skill-badge ${skill.builtin ? "" : "skill-badge-custom"}`.trim();
  badge.textContent = skill.builtin ? "Built-in" : "Yours";
  header.append(title, badge);

  const desc = document.createElement("p");
  desc.className = "skill-card-desc muted";
  desc.textContent = skill.description || "No description.";

  // **What running this will actually do.** The missing half of the old card:
  // a skill is a thing you are about to let edit your notebook, and "how many
  // steps" and "which tools" are the two facts that decide whether you want
  // to. Only shown when there is something to say, a one-shot prompt skill
  // has neither, and a row of zeroes is noise.
  const facts = document.createElement("div");
  facts.className = "skill-card-facts";
  const steps = (skill.steps || []).length;
  const tools = (skill.tools || []).length;
  const inputs = (skill.inputs || []).length;
  // Steps and tools expand in place, reported directly: "allow dropdown
  // expansions for the steps and tools in each." A hover title said the same
  // thing before, which is both unreachable on touch and one line, hidden
  // until you happened to rest a cursor on a chip that never looked
  // hoverable. `<details>` opens on click and on Enter/Space and needs no
  // JS to track its own state, the same choice the gallery kebab menu
  // already made for the same reason.
  const expandableFact = (icon, count, noun, items, ordered) => {
    const wrap = document.createElement("details");
    wrap.className = "skill-fact-expand";
    const summary = document.createElement("summary");
    summary.className = "chip skill-fact";
    setLabel(summary, `${icon} ${count} ${noun}${count === 1 ? "" : "s"}`);
    // Steps run in order, so they're numbered; tools are just a set the
    // model may reach for, in no particular order.
    const list = document.createElement(ordered ? "ol" : "ul");
    // Steps and tools are different kinds of thing and now look it. A step is
    // a sentence and reads as numbered prose; a tool is an identifier, so it
    // gets the monospace chip treatment the rest of the app already gives
    // code-ish tokens instead of sitting as a bare bullet. Reported twice as
    // these lists being "still not properly designed UI wise".
    list.className = ordered
      ? "skill-fact-list skill-fact-list-steps"
      : "skill-fact-list skill-fact-list-tools";
    for (const item of items) {
      const li = document.createElement("li");
      if (ordered) {
        // The number is a real element, not `::marker`. Three rounds of
        // padding tweaks failed to stop the generated markers from sitting
        // on (and being clipped by) the panel's left border, because an
        // `outside` marker is positioned relative to the item's content box
        // and hangs into the padding by an amount the page does not control.
        // A two-column grid with the number in its own gutter is
        // deterministic: it cannot overhang anything, and multi-line steps
        // align under their own text rather than under the number.
        const n = document.createElement("span");
        n.className = "skill-step-n";
        n.textContent = `${list.childElementCount + 1}.`;
        const body = document.createElement("span");
        body.textContent = item;
        li.append(n, body);
      } else {
        const token = document.createElement("code");
        token.className = "skill-tool-token";
        token.textContent = item;
        li.appendChild(token);
      }
      list.appendChild(li);
    }
    wrap.append(summary, list);
    return wrap;
  };
  if (steps) facts.appendChild(expandableFact("ph:list-numbers", steps, "step", skill.steps, true));
  if (tools) facts.appendChild(expandableFact("ph:wrench", tools, "tool", skill.tools, false));
  if (inputs) {
    const chip_ = document.createElement("span");
    chip_.className = "chip skill-fact";
    chip_.title = "Asks you for these before it runs";
    setLabel(chip_, `ph:textbox ${inputs} input${inputs === 1 ? "" : "s"}`);
    facts.appendChild(chip_);
  }

  const when = document.createElement("p");
  when.className = "skill-card-when muted text-xs";
  if (lastRun) {
    const outcome = (lastRun.detail || "").split(", ")[1] || "";
    when.textContent = `Last run ${new Date(lastRun.created_at).toLocaleString()}, ${outcome}`;
  } else {
    when.textContent = "Never run.";
  }

  const footer = document.createElement("div");
  footer.className = "skill-card-footer";
  const run = document.createElement("button");
  run.className = "small";
  setLabel(run, "ph:play Run");
  run.title = `Run “${skill.name}” in the chat`;
  // runSkill, not startSkill: it prompts for the skill's inputs when it has
  // any, then calls startSkill with a real values object, and switches to the
  // chat itself. (startSkill(skill.name) was the earlier bug here, a name
  // string where a skill object was expected, and no `values` at all.)
  run.addEventListener("click", () => runSkill(skill));
  footer.appendChild(run);

  // A built-in has nothing to edit, it is defined in the app, not in your
  // preferences: so offering Edit on one would open a form that cannot save.
  if (!skill.builtin) {
    const edit = document.createElement("button");
    edit.className = "ghost small";
    setLabel(edit, "ph:pencil-simple Edit");
    edit.addEventListener("click", async () => {
      await openSettingsModal("skills");
      startEditingSkill(skill);
    });
    footer.appendChild(edit);
  }

  card.append(header, desc);
  if (facts.children.length) card.appendChild(facts);
  card.append(when, footer);
  return card;
}

function renderSkillCards(query = "") {
  const grid = document.getElementById("skills-grid");
  const empty = document.getElementById("skills-empty");
  if (!grid) return;
  const term = query.trim().toLowerCase();
  const matches = term
    ? skillCardsCache.filter(
        ({ skill }) =>
          skill.name.toLowerCase().includes(term) ||
          (skill.description || "").toLowerCase().includes(term)
      )
    : skillCardsCache;
  grid.replaceChildren(...matches.map(({ skill, lastRun }) => skillCard(skill, lastRun)));
  if (empty) {
    empty.classList.toggle("hidden", matches.length > 0);
    empty.textContent = skillCardsCache.length
      ? "No skills match that."
      : "No skills yet. “New skill” writes one, a name, what it should do, and the steps to take.";
  }
}

async function renderSkillsDashboard() {
  const container = document.getElementById("skills-dashboard-list");
  if (!container) return;

  const [skills, prefs, runs] = await Promise.all([
    loadSkills(),
    apiJson("/preferences").catch(() => ({})),
    apiJson("/audit?limit=100&entity_type=skill", { silent: true }).catch(() => []),
  ]);
  const lastRuns = skillLastRunIndex(runs);
  container.replaceChildren();

  // --- background workers, in this app's own controls ------------------------
  //
  // The same three preferences as Settings → Background tasks, and written
  // through `setPreference` for the reason that fix already documents: these
  // used to write straight to the server and update nothing locally, so
  // `savePrefs`, which rebuilds the whole object from the *other* screen's
  // DOM: silently switched them back off again. Reported as "the automated
  // tasks option keeps automatically disabling itself even when turned on".
  const workers = document.createElement("section");
  workers.className = "card skills-workers";
  const workersHead = document.createElement("div");
  workersHead.className = "row space-between";
  const workersTitle = document.createElement("h3");
  workersTitle.textContent = "Background workers";
  workersHead.append(workersTitle);
  const workersHint = document.createElement("p");
  workersHint.className = "muted text-sm";
  workersHint.textContent =
    "Lets the AI work through your notebook on its own, on a schedule you set in Settings. Everything it changes is listed there afterwards and can be undone one item at a time.";
  const workerToggle = (id, key, label, on) => {
    const wrap = document.createElement("label");
    // The app's own pill toggle, not the `.switch`/`.slider` markup that used
    // to be here and exists nowhere else in this codebase.
    wrap.className = "checkbox-label";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.id = id;
    box.checked = on;
    box.addEventListener("change", (event) => setPreference(key, event.target.checked));
    const text = document.createElement("span");
    text.textContent = label;
    wrap.append(box, text);
    return wrap;
  };
  // The master switch, on its own, reported directly: it "should be
  // separate from the other two as they are like what the agent is running
  // in the background." Tag notes / Link related notes are jobs the agent
  // does *while* it's running, not independent switches of their own kind;
  // grouping all three as identical pills said otherwise.
  const masterRow = document.createElement("div");
  masterRow.className = "skills-worker-master";
  masterRow.appendChild(
    workerToggle(
      "skills-auto-toggle",
      "autonomous_tasks_enabled",
      "Run in the background",
      Boolean(prefs.autonomous_tasks_enabled)
    )
  );
  const jobsHint = document.createElement("p");
  jobsHint.className = "muted text-xs skills-worker-jobs-hint";
  jobsHint.textContent = "What it does while running:";
  const workersRow = document.createElement("div");
  workersRow.className = "skills-worker-toggles";
  workersRow.append(
    workerToggle("skills-auto-tag", "auto_tag_enabled", "Tag notes", prefs.auto_tag_enabled !== false),
    workerToggle(
      "skills-auto-link",
      "auto_link_enabled",
      "Link related notes",
      prefs.auto_link_enabled !== false
    )
  );
  workers.append(workersHead, workersHint, masterRow, jobsHint, workersRow);
  container.appendChild(workers);

  // --- the skills themselves --------------------------------------------------
  //: The search box is markup now, in this sub-tab's dock, because a Library
  //: sub-tab's search belongs in its head row beside the title like the other
  //: six. It used to be built here and appended below the background-workers
  //: card, which is where it rendered: a card and a half beneath the heading.
  //:
  //: `oninput` rather than `addEventListener`: this function runs again every
  //: time the sub-tab is opened, and on an element that now outlives the
  //: render a listener added per visit would re-render the cards once for
  //: every visit ever made. Assigning the handler replaces it instead.
  const search = $("skills-search");
  if (search) search.oninput = () => renderSkillCards(search.value);

  const grid = document.createElement("div");
  grid.id = "skills-grid";
  grid.className = "skills-grid";
  const empty = document.createElement("p");
  empty.id = "skills-empty";
  empty.className = "muted hidden";
  // Appended *outside* the grid: the previous version put its empty state
  // inside a grid whose cards went somewhere else entirely, so an empty
  // library rendered as a blank page.
  container.append(grid, empty);

  skillCardsCache = skills.map((skill) => ({ skill, lastRun: lastRuns.get(skill.name) }));
  renderSkillCards(search ? search.value : "");
}

// The AI Skills page is rendered when its sub-tab is opened, by the sub-tab
// handler below: not by monkey-patching `switchTab`, which is what this used
// to do (`window.switchTab = function(name) { originalSwitchTab(name); … }`).
// That wrapper ran two network-backed renders every time *any* Library
// sub-tab was opened, and it depended on load order: whichever script
// happened to run last owned the global. See `librarySubtabs` below.

$("skills-logs-clear")?.addEventListener("click", async () => {
  const ok = await confirmDialog("Clear the skill run log? This can't be undone.");
  if (!ok) return;
  await apiJson("/audit?entity_type=skill", { method: "DELETE" }).catch((e) => toast(e.message, true));
  renderSkillLogs();
});

async function renderSkillLogs() {
  const logList = document.getElementById("skills-logs-list");
  if (!logList) return;
  logList.innerHTML = "<p class='muted'>Loading logs…</p>";
  
  // **Filtered in SQL, not here, and asking for 20 of *everything* was half
  // the reason this panel looked broken.** Reported as "I dont think the
  // skill logs work in the ai skills section in the library??", and it had
  // two independent causes, either of which alone was enough:
  //
  // 1. Nothing in the app ever wrote a `skill` audit row. The filter below
  //    looked for `entity_type === "skill"`; a grep for a `log_action` call
  //    with that entity type found none. `skill_runner._record_run` writes
  //    one now.
  // 2. Even once they exist, `/audit?limit=20` returns the last twenty
  //    things that happened *of any kind*, and this then filtered those in
  //    the browser: so on any notebook where the last twenty events were
  //    note edits, a real history of skill runs rendered as "none found".
  const skillLogs =
    (await apiJson("/audit?limit=50&entity_type=skill").catch(() => null)) || [];
  logList.innerHTML = "";

  if (!skillLogs.length) {
    logList.innerHTML =
      "<p class='muted'>No skill runs yet. Run a skill from the chat and it will be listed here.</p>";
    return;
  }
  
  // createElement rather than an `innerHTML` template per row, per this file's
  // own rule. Worth noting what the old template actually contained: a
  // trailing `</div>` with nothing open to close, which the HTML parser
  // silently discarded on every single row. That is the argument for the rule
  // in one line: a structural mistake in a string is invisible, and the same
  // mistake in `append()` calls does not compile.
  for (const log of skillLogs) {
    const div = document.createElement("div");
    div.className = "entry-item";

    const head = document.createElement("div");
    head.className = "row space-between";
    const action = document.createElement("strong");
    // The detail carries the skill's name and outcome; `log.action` is just
    // "ran", which as a heading told the reader nothing they did not already
    // know from the panel they were looking at.
    action.textContent = (log.detail || "").split(", ")[0] || log.action;
    const when = document.createElement("span");
    when.className = "muted text-sm";
    when.textContent = new Date(log.created_at).toLocaleString();
    head.append(action, when);

    const detail = document.createElement("div");
    detail.className = "muted text-sm log-detail";
    detail.textContent = (log.detail || "").split(", ").slice(1).join(", ")
      || log.detail || "";

    div.append(head, detail);
    logList.appendChild(div);
  }
}

//: The image gallery's own expanded-caption set used to sit here, next to
//: these two. It is gone, not moved: a card's description is unclamped by
//: opening the card's one fold now (`openRowReadings`, and `captionClamped`
//: in renderLibraryImagesGallery), because four affordances under one picture
//: is what INBOX 115 was reporting. The capability the original ask wanted
//: ("the image caption can't be expanded or collapsed") is unchanged; the
//: button that carried it is one fewer thing on the card.
// The two OCR fields below the caption. Asked for directly:
// "make the ocr extracted text in the image gallery collapsible and
// expandable like the image captions as well", captionText got the clamp
// fix above; these two never did, so a long transcription still grew the
// tile unboundedly.
const libraryExpandedOcr = new Set();
const libraryExpandedVisionOcr = new Set();
//: All three are keyed by `mediaRowKey(image)` rather than `image.id`. An
//: `Attachment` and a `MediaUpload` have separate id sequences and this one
//: grid renders both kinds, so `id` alone names two rows at once: expanding
//: attachment 1's reading also expanded upload 1's, on whichever sub-tab
//: they happened to share.
// Which documents are ticked in the Library's Documents sub-tab: this
// view's own selection, separate from `librarySelection` (the "All" view's),
// because this section never populates `libraryItems` and mixing the two
// would let a checkbox here report "selected" while the "All" view's own
// bulk-delete silently found nothing to act on.
const libraryDocsSelection = new Set();

// BACKLOG §77's page-size pattern, extended to the Library's Documents
// sub-tab (§89 item 1): a plain newest-first list with no due/overdue
// framing to protect, unlike Reminders, so a straight full-list page slice
// is safe here.
let libraryDocsPageSize = localStorage.getItem("library-docs-page-size") || "all";
let libraryDocsCurrentPage = 1;

// The Library sub-tab drafts were supposed to live in from the start, a
// stray comment already claimed "the sidebar/Library Drafts filter... is
// what makes them findable" and HISTORY.md said the same, but no
// library-view-drafts section ever existed to check off. Reported live:
// "there is no drafts section in the library." Fetches its own list rather
// than trusting Notes-tab state (`allEntries`) to already be loaded, the
// Library can be opened first, before Notes ever has been.
// Documents, on their own Library sub-tab.
//
// Reuses GET /documents, the same call the editor's sidebar makes, rather
// than adding an endpoint, and openDocument() to open one, so there is exactly
// one code path from "a document in a list" to "the editor showing it".
//
// This replaces the Drafts list that used to live here. Drafts are now a chip
// in the All view's filter row (LIBRARY_KINDS in app.js, _drafts() in
// routes_library.py) because a draft is a state a note is in, not a separate
// kind of object.
//: Sorting for the Documents sub-tab. Same local, no-round-trip approach as
//: the media gallery and the links list: the page of documents is already in
//: memory by the time this runs.
//:
//: Sorted **before** paging, which is the only order that makes a page mean
//: anything: sorting a slice would reorder ten rows within a page and leave
//: the pages themselves in the server's order, so "longest first" would show
//: the longest of page two rather than the longest there is.
const LIBRARY_DOC_SORTS = {
  newest: (a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")),
  oldest: (a, b) => String(a.updated_at || "").localeCompare(String(b.updated_at || "")),
  az: (a, b) => String(a.title || "").localeCompare(String(b.title || ""), undefined, { sensitivity: "base" }),
  za: (a, b) => String(b.title || "").localeCompare(String(a.title || ""), undefined, { sensitivity: "base" }),
  //: A document list has no file size, but it does have a word count, which
  //: is what "how big is this one" actually means here. The field is `words`
  //: (routes_documents.py's `_summary`), not `word_count`: reading the wrong
  //: name would have made every document sort as zero and the order look
  //: arbitrary rather than broken, which is the failure that hides longest.
  longest: (a, b) => (Number(b.words) || 0) - (Number(a.words) || 0),
};

const LIBRARY_DOC_SORT_KEY = "library-docs-sort";

function libraryDocSort() {
  const stored = localStorage.getItem(LIBRARY_DOC_SORT_KEY);
  return LIBRARY_DOC_SORTS[stored] ? stored : "newest";
}

document.addEventListener("DOMContentLoaded", () => {
  const select = document.getElementById("library-docs-sort");
  if (!select) return;
  select.value = libraryDocSort();
  select.addEventListener("change", () => {
    localStorage.setItem(LIBRARY_DOC_SORT_KEY, select.value);
    //: Back to page one: staying on page four of a list that has just been
    //: reordered shows a slice of rows nobody asked to look at.
    libraryDocsCurrentPage = 1;
    renderLibraryDocuments();
  });
});

async function renderLibraryDocuments() {
  const list = document.getElementById("library-docs-list");
  const empty = document.getElementById("library-docs-empty");
  const noMatch = document.getElementById("library-docs-no-match");
  if (!list) return;
  const needle = (document.getElementById("library-docs-search")?.value || "")
    .trim()
    .toLowerCase();

  let docs = [];
  try {
    // `q` searches title *and* content server-side (routes_documents.py): 
    // client-side filtering alone could only ever match a title, since a
    // document's body is never sent to the browser in the list view.
    //
    //: Read to the end rather than one page (`apiPagedList`, documents.js).
    //: `GET /documents` returns a page now (INBOX 117), and this list sorts
    //: and pages *client-side* below: on one page of the server's rows,
    //: sorting oldest-first would show the oldest of the newest two hundred
    //: and call it the oldest, and the pager would offer pages that do not
    //: exist. With `q` given the server counts the matches, not the table,
    //: so the loop ends on the size of the search.
    docs = await apiPagedList(
      needle ? `/documents?q=${encodeURIComponent(needle)}` : "/documents",
      DOCUMENTS_PAGE_SIZE
    );
  } catch (error) {
    toast(error.message || "Could not load documents.", true);
    return;
  }

  // A reload can drop a document that was ticked (deleted, or filtered out
  // by a new search) - drop it from the selection too, or the bar's count
  // would go on including a row that no longer exists.
  const liveIds = new Set(docs.map((d) => d.id));
  for (const id of [...libraryDocsSelection]) {
    if (!liveIds.has(id)) libraryDocsSelection.delete(id);
  }

  list.replaceChildren();
  const isFilteredEmpty = Boolean(needle) && !docs.length;
  empty?.classList.toggle("hidden", docs.length > 0 || isFilteredEmpty);
  noMatch?.classList.toggle("hidden", !isFilteredEmpty);
  if (noMatch && isFilteredEmpty) {
    noMatch.textContent = `No documents match \u201C${needle}\u201D.`;
  }

  // Sliced after the selection-cleanup above (which has to see every live
  // id, not just the current page) and before the render loop below.
  const pageBar = document.getElementById("library-docs-pagination");
  //: Before paging: see `LIBRARY_DOC_SORTS`. On a copy, because `docs` may be
  //: an array another reader holds.
  docs = [...docs].sort(LIBRARY_DOC_SORTS[libraryDocSort()]);
  if (libraryDocsPageSize === "all" || !docs.length) {
    pageBar?.classList.add("hidden");
  } else {
    const pageSize = Number(libraryDocsPageSize);
    const totalPages = Math.max(1, Math.ceil(docs.length / pageSize));
    libraryDocsCurrentPage = Math.min(Math.max(1, libraryDocsCurrentPage), totalPages);
    const start = (libraryDocsCurrentPage - 1) * pageSize;
    docs = docs.slice(start, start + pageSize);
    pageBar?.classList.remove("hidden");
    document.getElementById("library-docs-page-status").textContent =
      `Page ${libraryDocsCurrentPage} of ${totalPages}`;
    document.getElementById("library-docs-page-prev").disabled = libraryDocsCurrentPage <= 1;
    document.getElementById("library-docs-page-next").disabled = libraryDocsCurrentPage >= totalPages;
  }

  for (const doc of docs) {
    const item = document.createElement("li");

    // Reported: "can't rename, multi select, or delete documents in the
    // library subtab" - this row used to be nothing but the Open button
    // below. The tick and the ⋯ menu give it the same three actions a
    // document's card already has in the "All" library view: and,
    // reported again after the first pass, the same *placement*:
    // `libraryCard()`'s article-not-button shape (a button cannot contain
    // another button, which the tick and the kebab both are), the tick
    // sitting inline in the header row, the kebab absolutely positioned
    // and hover/focus-revealed rather than two more permanent controls
    // squeezed in as flex siblings.
    const open = document.createElement("article");
    open.className = "doc-list-item";
    open.tabIndex = 0;
    open.setAttribute("role", "button");
    const openDoc = () => {
      // switchTab first, then open. Reported as "the documents subtab document
      // cards don't even do anything": openDocument() loaded the document
      // correctly, but the Documents *page* stayed hidden behind the Library
      // tab, so from the outside the click did nothing at all.
      switchTab("documents");
      openDocument(doc.id);
    };
    open.addEventListener("click", openDoc);
    open.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      if (event.target !== open) return; // a key pressed inside the tick/menu is theirs
      event.preventDefault();
      openDoc();
    });

    const top = document.createElement("div");
    top.className = "doc-list-top";
    const tick = document.createElement("input");
    tick.type = "checkbox";
    tick.className = "doc-list-tick";
    tick.checked = libraryDocsSelection.has(doc.id);
    tick.setAttribute("aria-label", `Select "${doc.title || "Untitled"}"`);
    tick.addEventListener("click", (event) => event.stopPropagation());
    tick.addEventListener("change", () => {
      if (tick.checked) libraryDocsSelection.add(doc.id);
      else libraryDocsSelection.delete(doc.id);
      syncLibraryDocsSelectbar();
    });
    const icon = document.createElement("span");
    icon.className = "doc-list-icon";
    setLabel(icon, "ph:file-text");
    icon.setAttribute("aria-hidden", "true");
    top.append(tick, icon);

    const body = document.createElement("span");
    body.className = "doc-list-body";
    const title = document.createElement("span");
    title.className = "doc-list-title";
    title.textContent = doc.title || "Untitled";
    const meta = document.createElement("span");
    meta.className = "muted doc-list-meta";
    // Words and when it was last touched, the two facts that tell you which
    // of five similarly-named drafts is the one you meant.
    const words = typeof doc.words === "number" ? `${doc.words} words` : "";
    const when = doc.updated_at ? relativeTime(doc.updated_at) : "";
    meta.textContent = [words, when].filter(Boolean).join(" · ");
    body.append(title, meta);

    // The document's own opening, which is the thing that actually tells four
    // similarly-named drafts apart: a title, a word count and a date do not.
    // Asked for directly: the Documents sub-tab is "boring and should probably
    // have previews". Served by the list endpoint as a flattened 240-character
    // snippet (`routes_documents._preview`) rather than by shipping every
    // document's full text to draw a list.
    if (doc.preview) {
      const preview = document.createElement("span");
      preview.className = "doc-list-preview";
      preview.textContent = doc.preview;
      body.append(preview);
    }

    // Same three actions `libraryActions()` gives a document's card in the
    // "All" view: kept as its own copy rather than calling that function
    // directly, because its `reload` is hard-coded to `loadLibrary()` (the
    // "All" view's own data), which would leave this list showing a document
    // that was just renamed or deleted until something else refreshed it.
    const menu = kebabMenu(
      [
        // **A read-only showcase, not the editor.** Asked for directly:
        // "make a way to view documents in the documents tab in the
        // lightbox." The row's own click already opens the full editor, 
        // this is the quick-look alternative, matching what the lightbox
        // already does for an uploaded PDF or a note attachment. A native
        // document needs no extraction (`GET /documents/{id}` already
        // returns the whole body), so `item.kind`/`item.text` are set
        // straight from the response and `showDocument` (app.js) skips
        // its own fetch entirely when it sees them already filled in.
        makeMenuItem("ph:eye Preview", "View this document without opening the editor", async () => {
          let full;
          try {
            full = await apiJson(`/documents/${doc.id}`);
          } catch (error) {
            toast(error.message || "Couldn't open that document.", true);
            return;
          }
          openLightbox(
            [
              {
                filename: full.title || "Untitled",
                id: full.id,
                //: What tells the lightbox this preview has an editor to open
                //:, see `openDocBtn` there. Separate from `id`, which the
                //: lightbox also uses for attachments and uploads.
                documentId: full.id,
                kind: full.file_type === "md" ? "markdown" : "code",
                text: full.content || "",
                addedAt: full.updated_at || "",
                // No file on /media to fetch a URL from, Save reads this
                // directly, the same route the kebab's own "Download .md"
                // item already uses.
                getUrl: () => `/documents/${full.id}/export.md`,
              },
            ],
            0
          );
        }),
        makeMenuItem("ph:pencil-simple Rename", "Rename this document", async () => {
          const next = await promptDialog("Rename this document:", doc.title || "");
          if (!next) return;
          await apiJson(`/documents/${doc.id}`, {
            method: "PUT",
            body: JSON.stringify({ title: next }),
          }).catch((e) => toast(e.message, true));
          renderLibraryDocuments();
        }),
        makeMenuItem("⬇ Download .md", "Save a copy as a markdown file", () => {
          window.open(`/documents/${doc.id}/export.md`, "_blank");
        }),
        makeMenuItem("ph:trash Delete", "Delete this document", async () => {
          if (
            !(await confirmDialog(
              `Delete "${doc.title || "Untitled"}"? You can undo this straight after.`
            ))
          ) {
            return;
          }
          //: The fourth and last door onto the same delete. All four now go
          //: through `deleteDocumentWithUndo`, a delete that is recoverable
          //: from one menu and permanent from another is worse than one that
          //: is permanent everywhere, because it teaches a rule that is false.
          await deleteDocumentWithUndo(doc).catch((e) => toast(e.message, true));
          libraryDocsSelection.delete(doc.id);
          renderLibraryDocuments();
        }),
      ],
      `Actions for "${doc.title || "Untitled"}"`
    );
    menu.classList.add("doc-list-menu");
    menu.addEventListener("click", (event) => event.stopPropagation());
    // **Reported: "the documents popup menu in the library subtab gets cut
    // off."** `.library-view-section` (07-whiteboard-misc.css) is
    // `overflow-y: auto`, and `.action-menu`, the shared kebab menu
    // `kebabMenu()` builds: is `position: absolute`, so it is clipped by
    // The escape-to-<body> fix this list needed (it is clipped by
    // `#library-view-media`/`#tab-library` the same way
    // `.library-image-menu-list` was) now lives inside `kebabMenu()` itself,
    // so there is no call here: wiring it twice installs two
    // MutationObservers on one menu, which do the same reparent twice.

    open.append(top, body, menu);
    item.appendChild(open);
    list.appendChild(item);
  }
  syncLibraryDocsSelectbar();
}

function syncLibraryDocsSelectbar() {
  const bar = document.getElementById("library-docs-selectbar");
  const count = document.getElementById("library-docs-selected-count");
  if (!bar || !count) return;
  const n = libraryDocsSelection.size;
  bar.classList.toggle("hidden", n === 0);
  count.textContent = `${n} selected`;
}

$("library-docs-clear-selection")?.addEventListener("click", () => {
  libraryDocsSelection.clear();
  renderLibraryDocuments();
});

$("library-docs-bulk-delete")?.addEventListener("click", async () => {
  const ids = [...libraryDocsSelection];
  if (!ids.length) return;
  const ok = await confirmDialog(
    `Delete ${ids.length} document${ids.length === 1 ? "" : "s"}? This cannot be undone.`
  );
  if (!ok) return;
  let deleted = 0;
  for (const id of ids) {
    try {
      await apiJson(`/documents/${id}`, { method: "DELETE" });
      deleted++;
    } catch {
      // counted below, same as the "All" view's own bulk delete
    }
  }
  libraryDocsSelection.clear();
  if (deleted) toast(`Deleted ${deleted} document${deleted === 1 ? "" : "s"}.`);
  const failed = ids.length - deleted;
  if (failed) toast(`${failed} document${failed === 1 ? "" : "s"} couldn't be deleted.`, true);
  renderLibraryDocuments();
});

// Every `/media/upload` has ever produced: note-inline images, document
// images, and whiteboard image objects alike, since all three funnel
// through the same upload endpoint and (asked for directly) "images can be
// managed (delete, rename etc) in the gallery as well." A file whose bytes
// are gone (deleted from here, or off-disk by hand) leaves a broken-image
// glyph, same guard `libraryCard`'s own thumbnail already uses, but a
// note or whiteboard still referencing a *deleted* url gets its own
// placeholder instead of a broken glyph; see `renderInlineMarkdown`'s own
// image `error` handler and `wbRenderObjects`'s image-object one.
//: The last `GET /media` fetch, so the search box (below) can filter and
//: re-render without a round-trip on every keystroke, the same reasoning
//: the main Library search already uses against `libraryItems`.
let libraryImagesCache = [];

//: **What the gallery last drew**, so a poll that finds nothing new draws
//: nothing new. Reported on 2026-09-09, against both media sub-tabs: "when I
//: expand the ocr text in this image on the image cards in the images library
//: sub tab, it keeps auto closing and scrolling me back to the top", and "the
//: same happens on the text extracted from this file dropdown in the files
//: subtab". The six-second caption poll rebuilt every tile from scratch
//: whether or not anything had changed, so an open `<details>` was replaced
//: by a closed one and the grid's scroll offset went with it: a reader had
//: about six seconds to read a transcription before the app shut it.
//:
//: The signature is the fields a tile actually draws, not the whole payload:
//: `/media` carries timestamps and sizes that move without changing a pixel,
//: and comparing those would make this test always fail, which is the bug
//: again with extra steps.
let libraryImagesSignature = "";
function libraryImagesFingerprint(rows) {
  return JSON.stringify(
    (rows || []).map((row) => [
      row.url,
      row.name,
      row.caption || "",
      row.ocr_text || "",
      row.vision_ocr_text || "",
      row.usage_count ?? null,
    ]),
  );
}

// Captioning runs on a background thread after upload (routes_files.py): 
// the gallery only ever showed the caption once something re-fetched
// `/media`, and nothing did that on its own. Reported directly: a caption
// "doesn't work" at the time, then is there after reopening the app later, 
// it worked all along, the UI just never looked again. Runs only while the
// Image Gallery is the visible sub-tab (started/stopped by the sub-tab
// click handler below); skips a poll while a caption or rename field is
// mid-edit so a silent re-render can't wipe out unsaved typing.
let libraryImagesPollTimer = null;
function startLibraryImagesPoll() {
  stopLibraryImagesPoll();
  libraryImagesPollTimer = setInterval(() => {
    if (document.querySelector(".library-image-caption-input, .library-image-rename-input")) {
      return;
    }
    renderLibraryImagesGallery({ ifUnchanged: "skip" });
  }, 6000);
}
function stopLibraryImagesPoll() {
  if (libraryImagesPollTimer) clearInterval(libraryImagesPollTimer);
  libraryImagesPollTimer = null;
}

//: Icon and type label for a non-image upload's tile. Deliberately reads
//: the *url* rather than a stored mime: `MediaUpload` has never carried one
//: (it stores a filename and nothing about content type), and the extension
//: is what the allowlist that let the file in already validated.
//: **What counts as an image**, in one place. The gallery tile code already
//: had this test inline (a PDF rendered as an `<img>` decodes to nothing and
//: the tile deletes itself, see `filterLibraryImagesGallery`), and the
//: Images/Files split needs exactly the same answer. Two copies of it would
//: be two chances for a `.heic` to be an image in one and a file in the other.
function isImageUrl(url) {
  //: Asked for directly: "make sure all image file types are sorted into the
  //: image gallery". The list was the eight this app's own upload input
  //: happened to accept, so anything arriving by another route, dragged from
  //: a phone export, attached to a note, restored from a backup, was an
  //: image the Files tab held. `.heic`/`.heif` are what a phone actually
  //: writes, `.tif`/`.tiff` what a scanner does, and `.jfif` is what some
  //: Windows tools still save a JPEG as. Widening the test is safe in the
  //: direction that matters: the gallery already deletes a tile whose `<img>`
  //: decodes to nothing (`filterLibraryImagesGallery`), so a browser that
  //: cannot render a HEIC drops it rather than showing a broken frame, while
  //: one that can shows it where it belongs.
  //:
  //: The extension is read up to a `?` or `#` rather than to the end of the
  //: string, because an Attachment's url can carry a cache-busting query and
  //: an anchored test called that a non-image. Written as a fixed alternation
  //: with a single optional group, not a `[…]+$` run, which is the
  //: polynomial-backtracking shape CodeQL has already caught in this repo.
  return /\.(png|jpe?g|jfif|gif|webp|avif|bmp|ico|svg|heic|heif|tiff?|apng)(?:[?#]|$)/i.test(
    url || "",
  );
}

//: **Preview art or type icon, the viewer's choice.** Asked for: "make it
//: togglable to change between filetype and previews".
//:
//: Persisted in `localStorage` rather than in preferences: it is a way of
//: looking at one list, like the notes rows/cards toggle beside it in the same
//: kind of control, not a setting about the notebook. It also costs no
//: round-trip, so the grid does not flicker into the wrong mode on load.
//:
//: Applied as a class on the grid and resolved entirely in CSS. The tiles
//: already contain both the page render and the glyph, the render simply
//: covers the glyph: so switching modes is a matter of whether the cover is
//: painted, and nothing has to be rebuilt, refetched or re-laid-out.
const LIBRARY_MEDIA_VIEW_KEY = "library-media-view";
let libraryMediaView = localStorage.getItem(LIBRARY_MEDIA_VIEW_KEY) === "type" ? "type" : "preview";

function applyLibraryMediaView() {
  const grid = document.getElementById("library-images-grid");
  if (grid) grid.classList.toggle("show-file-types", libraryMediaView === "type");
  //: **Files are rows, images are tiles.** Asked for directly: "the card
  //: format is difficult with files as they can be quite long and large, a
  //: single image or ocr caption doesnt fit them." A tile is the right shape
  //: for a picture, whose content *is* the thumbnail; it is the wrong shape
  //: for a document, whose content is a name, a description, a size, a page
  //: count and a list of the notes it is used in, a card either truncates
  //: all of that or grows to a different height than its neighbours. The
  //: grid keeps one class and the CSS does the rest, so both sub-tabs keep
  //: rendering through the one builder.
  if (grid) grid.classList.toggle("library-file-rows", libraryMediaKind === "files");
  //: **Hidden on Images, where it would do nothing.** Reported: "the one in
  //: the image subtab doesnt do anything", correct, and it never could. The
  //: toggle chooses between a file's rendered first page and its type glyph,
  //: and an image tile is an `<img>` of the picture itself: it has no
  //: `.library-file-page` to hide and no glyph underneath to reveal. A control
  //: that is present and inert is worse than one that is absent, because it
  //: invites the click that teaches you it is broken.
  const viewToggle = document.querySelector(".library-media-view");
  viewToggle?.classList.toggle("hidden", libraryMediaKind !== "files");
  const preview = document.getElementById("library-media-view-preview");
  const type = document.getElementById("library-media-view-type");
  preview?.classList.toggle("active", libraryMediaView === "preview");
  preview?.setAttribute("aria-pressed", String(libraryMediaView === "preview"));
  type?.classList.toggle("active", libraryMediaView === "type");
  type?.setAttribute("aria-pressed", String(libraryMediaView === "type"));
}

function setLibraryMediaView(mode) {
  libraryMediaView = mode === "type" ? "type" : "preview";
  localStorage.setItem(LIBRARY_MEDIA_VIEW_KEY, libraryMediaView);
  applyLibraryMediaView();
}

document.addEventListener("DOMContentLoaded", () => {
  document
    .getElementById("library-media-view-preview")
    ?.addEventListener("click", () => setLibraryMediaView("preview"));
  document
    .getElementById("library-media-view-type")
    ?.addEventListener("click", () => setLibraryMediaView("type"));
  applyLibraryMediaView();
});

//: Which of the two media sub-tabs is showing. Not persisted: it is a place
//: in the Library, and the sub-tab strip already says which one you are on.
let libraryMediaKind = "images";

const LIBRARY_MEDIA_COPY = {
  images: {
    title: "Images",
    icon: "ph ph-images-square ph-lead",
    emptyTitle: "No images yet",
    emptyBody: "Paste, drop, or attach one to a note and it shows up here.",
    search: "Search filenames, captions and text found in images…",
    noMatch: "No images match your search.",
  },
  files: {
    title: "Files",
    icon: "ph ph-file-text ph-lead",
    emptyTitle: "No files yet",
    emptyBody:
      "Drop a PDF or a document into a note, or use Upload above, and it shows up here.",
    search: "Search filenames and text found in files…",
    noMatch: "No files match your search.",
  },
};

function setLibraryMediaKind(kind) {
  libraryMediaKind = kind === "files" ? "files" : "images";
  //: The view toggle only means something on Files, so it appears and
  //: disappears with the sub-tab, see `applyLibraryMediaView`.
  applyLibraryMediaView();
  const copy = LIBRARY_MEDIA_COPY[libraryMediaKind];
  const title = $("library-media-title");
  if (title) title.textContent = copy.title;
  const icon = $("library-media-empty-icon");
  if (icon) icon.className = copy.icon;
  const emptyTitle = $("library-media-empty-title");
  if (emptyTitle) emptyTitle.textContent = copy.emptyTitle;
  const emptyBody = $("library-media-empty-body");
  if (emptyBody) emptyBody.textContent = copy.emptyBody;
  const search = $("library-images-search");
  if (search) search.placeholder = copy.search;
  const noMatch = $("library-images-no-match");
  if (noMatch) noMatch.textContent = copy.noMatch;
  // The upload button offers what this sub-tab is *for*. It still accepts
  // both: a person who picks a PDF on the Images tab gets the PDF, it just
  // appears under Files: because refusing a file the app can store would be
  // worse than filing it somewhere they then have to look.
  //: The read filter is a Files idea. An image is not "unread" in any sense a
  //: person means: dividing pictures by whether OCR happened to have run on
  //: them would be a control that answers a question nobody asked.
  const readFilter = $("library-media-read");
  if (readFilter) {
    readFilter.classList.toggle("hidden", libraryMediaKind !== "files");
    if (libraryMediaKind !== "files") readFilter.value = "all";
  }
  const input = $("library-images-upload-input");
  if (input) {
    input.accept =
      libraryMediaKind === "files"
        ? "application/pdf,text/plain,text/markdown,text/csv,application/json"
        : "image/png,image/jpeg,image/gif,image/webp,image/avif,image/bmp,image/x-icon,image/heic,image/heif,image/tiff,image/apng";
  }
}

//: **One way to jump to a stored file**, used by the palette, the graph and
//: the Connections dialog. It exists because the media view became *two*
//: sub-tabs: `querySelector('[data-target="library-view-media"]')` now
//: matches both and returns Images, so every one of those jumps would have
//: landed a PDF on the Images tab and shown "no match".
//:
//: The sub-tab is clicked rather than switched by hand for the same reason
//: those call sites already clicked it: the strip's own handler owns the
//: active class, the aria-selected state and the lazy render, and this app
//: has already learned once that re-implementing three of those is how they
//: drift.
function focusLibraryFile(name, url) {
  switchTab("library");
  const kind = isImageUrl(url) ? "images" : "files";
  document
    .querySelector(`#library-subtabs button[data-media-kind="${kind}"]`)
    ?.click();
  const search = $("library-images-search");
  if (search) {
    search.value = name || "";
    search.dispatchEvent(new Event("input", { bubbles: true }));
  }
}
window.focusLibraryFile = focusLibraryFile;

function mediaFileIcon(url) {
  const ext = url.split(".").pop().split(/[?#]/)[0].toLowerCase();
  const map = {
    pdf: "ph-file-pdf", doc: "ph-file-doc", docx: "ph-file-doc",
    xls: "ph-file-xls", xlsx: "ph-file-xls", csv: "ph-file-csv",
    ppt: "ph-file-ppt", pptx: "ph-file-ppt",
    txt: "ph-file-text", md: "ph-file-md", json: "ph-file-code",
    zip: "ph-file-archive",
  };
  return map[ext] || "ph-file";
}

//: **The facts about a file, as facts.** Asked for directly with the Files
//: sub-tab redesign: "the card format is difficult with files as they can be
//: quite long and large, a single image or ocr caption doesnt fit them. there
//: should be details on the name, a generated description that cna happen,
//: file details such as the type, size, topic/category, linked notes and
//: other features."
//:
//: A tile could show a thumbnail, a name and a caption; everything else a
//: person actually brings to a file list, how big is it, how many pages,
//: when did it arrive, has it been read, was either absent or buried. These
//: are the ones the row can state in one line.
function formatFileSize(bytes) {
  const size = Number(bytes) || 0;
  if (size <= 0) return ""; // unknown, or the file is gone, say nothing
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB"];
  let value = size / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  // One decimal below 10 (2.4 MB reads better than 2 MB), none above it.
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

//: The muted "TYPE · SIZE · pages · added" strip under a file's name. Every
//: part is omitted when it is not known rather than shown empty or as a zero,
//: since "0 B" and ", " are both claims this list cannot make honestly.
//: **One line of facts, dot separated, built once.** The Files rows had this
//: shape inline; the Links rows now want the same one (the owner, 2026-09-13:
//: "redesign the links cards/rows ... to make them look nicer and more
//: modern"), and a second copy of a loop that inserts separators is how two
//: lists end up disagreeing about what a separator is. `extraClass` because
//: the two lines sit in different layouts and the row needs a handle of its
//: own for the column it lives in.
function metaLine(parts, extraClass = "") {
  const line = document.createElement("div");
  line.className = extraClass ? `library-file-meta ${extraClass}` : "library-file-meta";
  for (const [index, part] of parts.filter(Boolean).entries()) {
    if (index) {
      const dot = document.createElement("span");
      dot.className = "library-file-meta-sep";
      dot.textContent = "·";
      line.appendChild(dot);
    }
    const span = document.createElement("span");
    span.textContent = part;
    line.appendChild(span);
  }
  return line;
}

function fileMetaLine(image) {
  const parts = [];
  parts.push(mediaFileKind(image.original_name || image.url || ""));
  const size = formatFileSize(image.size_bytes);
  if (size) parts.push(size);
  if (image.page_count) parts.push(`${image.page_count} page${image.page_count === 1 ? "" : "s"}`);
  if (image.created_at) {
    const when = new Date(image.created_at);
    if (!Number.isNaN(when.getTime())) parts.push(`added ${when.toLocaleDateString()}`);
  }
  return metaLine(parts);
}

//: What a person calls a link: the site it is on. A bookmark row showed the
//: whole address under its title, which on a real bookmark
//: ("…/a/very/long/path?with=a&query=string") is a line of machine text under
//: a line of human text, at the same rank. The host is what identifies a link
//: in every browser's own bookmark list, the rest of the address is still on
//: the row's tooltip and is what the title opens.
function bookmarkAddress(url) {
  const raw = String(url || "").trim();
  try {
    //: A bookmark may have been saved without a scheme ("example.com"), which
    //: `new URL` rejects rather than guesses at, so the guess is made here and
    //: the raw string is the answer if even that fails.
    const parsed = new URL(/^[a-z][a-z0-9+.-]*:/i.test(raw) ? raw : `https://${raw}`);
    const rest = `${parsed.pathname}${parsed.search}`;
    return {
      host: parsed.host.replace(/^www\./, "") || raw,
      //: "/" is not a fact about a link, it is what every address ends up with
      //: when it names a site rather than a page.
      rest: rest === "/" ? "" : rest,
    };
  } catch {
    return { host: raw, rest: "" };
  }
}

function mediaFileKind(url) {
  const ext = url.split(".").pop().split(/[?#]/)[0].toLowerCase();
  return (ext || "file").toUpperCase();
}

//: One call for "read this file with the models", whichever table the row
//: came from. A `MediaUpload` has three endpoints (`/media/{id}/caption`,
//: `/ocr`, `/vision-ocr`); an `Attachment` has one that takes the kind
//: (`/files/{id}/analyse`), because that side was built after it was clear
//: the three differ only in which column they write. The tile does not care:
//: it asks for a kind and gets the updated row back either way.
//:
//: Asked for directly: "the files tab needs vision model and ocr model
//: caption and text extraction… the text and analysis needs to be accessible
//: to the ai models and modifyable by the user."
// --- The OCR workspace (three panes) -------------------------------------
//
// Asked for with three screenshots of Baidu's Unlimited-OCR: "for the
// document ocr I want smth like this". The reading this app already did was
// a paragraph under a thumbnail, you could read it, but not *check* it:
// nothing said which part of the page a line came from, and a wrong line was
// a wall of text to re-type rather than a row to fix.
//
// The two halves that make it checkable are the overlay and the list, and
// they are one selection: clicking a box scrolls to its text, clicking a row
// highlights its box. Boxes are fractions of the image (core/ocr.py), so the
// overlay is a percentage-positioned layer over the `<img>` and stays right
// at any panel width, which is why nothing here reads `naturalWidth`.
let ocrWorkspaceImages = [];
let ocrWorkspaceCurrent = null;
let ocrWorkspaceRegions = [];
//: Which page of a multi-page document is on the stage, and how many there
//: are. 0/1 for an image, which is a one-page document with no rail.
let ocrWorkspacePage = 0;
let ocrWorkspacePages = 1;
//: page index -> `{caption, caption_model}` for the document on the stage.
//: Filled from the `page-reads` response (which carries a page's description
//: on the same row as its reading), cleared and refilled on every page load so
//: it can never describe the previous document's page 3.
const ocrPageCaptions = new Map();

function ocrIsPdf(image) {
  return Boolean(image) && /\.pdf$/i.test(image.original_name || image.filename || "");
}

function ocrRegionsUrl(image, page = 0) {
  const base = image._isAttachment
    ? `/files/${image.id}/ocr-regions`
    : `/media/${image.id}/ocr-regions`;
  return `${base}?page=${page}`;
}

//: The rendered picture of one page, an image is itself the page, a PDF has
//: to be rasterised, and the endpoints for that already exist for the file
//: viewer and the Files tile.
function ocrPageImageUrl(image, page = 0) {
  if (!ocrIsPdf(image)) return image._src || mediaSrc(image.url);
  return mediaSrc(
    image._isAttachment
      ? `/files/${image.id}/pdf-page/${page}`
      : `/media/pdf-page/${encodeURIComponent((image.url || "").split("/").pop())}/${page}`
  );
}

//: **A reading outlives the window that started it.**
//:
//: Reported: *"I begin generating ocr for a document, I close the lightbox,
//: the ocr workspace is gone and its back to what it was, it should have
//: stayed open and should be openable if an active ocr reading is going on."*
//:
//: The request itself never stopped, a POST keeps going and writes its result
//: whatever the browser does next, but the only evidence it existed lived
//: inside the window that started it. This is the piece that outlives that
//: window: a map of file key → the read in flight, which the workspace reads
//: on open (so reopening mid-read shows the read, not an empty page) and which
//: any surface can consult to offer a way back in.
const ocrActiveReads = new Map();

function trackOcrRead(image, label, promise, controller = null) {
  const key = ocrRailKey(image);
  //: `controller` is what makes the read stoppable. Asked for directly:
  //: "also let the user be able to stop the readings." A page read is a
  //: blocking model call with nothing to interrupt server-side between
  //: tokens, so Stop abandons the *request*, the person pressing it wants
  //: their workspace back, not a guarantee about the model's own thread.
  const record = { label, started: Date.now(), promise, controller };
  ocrActiveReads.set(key, record);
  ocrSyncStopButton();
  const settle = () => {
    if (ocrActiveReads.get(key) === record) ocrActiveReads.delete(key);
    ocrSyncStopButton();
    //: Re-render only if this file is still the one on the stage. The
    //: workspace may have been closed, reopened on another page, or never
    //: opened at all: none of which should make a finished read throw.
    if (ocrWorkspaceCurrent && ocrRailKey(ocrWorkspaceCurrent) === key) {
      const overlay = $("ocr-workspace");
      if (overlay && !overlay.classList.contains("hidden")) {
        ocrLoadPage(ocrWorkspaceCurrent, ocrWorkspacePage);
      }
    }
  };
  Promise.resolve(promise).then(settle, settle);
  return promise;
}

function ocrReadInFlight(image) {
  return image ? ocrActiveReads.get(ocrRailKey(image)) || null : null;
}

//: Abandon the read on the file currently on the stage, and say so.
//: Returns whether there was one to stop, so the caller can stay quiet when
//: the read finished between the button appearing and the click landing.
function ocrStopRead() {
  const record = ocrReadInFlight(ocrWorkspaceCurrent);
  if (!record || !record.controller) return false;
  record.controller.abort();
  return true;
}

//: The Stop button exists only while something is running. A control that is
//: always there but does nothing most of the time is the affordance problem
//: this app keeps fixing elsewhere.
function ocrSyncStopButton() {
  const button = document.getElementById("ocr-stop-read");
  if (!button) return;
  const record = ocrReadInFlight(ocrWorkspaceCurrent);
  button.classList.toggle("hidden", !record || !record.controller);
}

function ocrSelectRegion(index) {
  for (const box of document.querySelectorAll("#ocr-boxes .ocr-box")) {
    box.classList.toggle("is-active", Number(box.dataset.index) === index);
  }
  for (const row of document.querySelectorAll("#ocr-region-list .ocr-region")) {
    const active = Number(row.dataset.index) === index;
    row.classList.toggle("is-active", active);
    //: `nearest`, not `start`: a row already fully on screen should not jerk
    //: the list when you click its box.
    if (active) row.scrollIntoView({ block: "nearest" });
  }
}

function ocrRenderRegions(body) {
  const boxes = $("ocr-boxes");
  const list = $("ocr-region-list");
  const message = $("ocr-message");
  const source = $("ocr-source");
  boxes.replaceChildren();
  list.replaceChildren();
  ocrWorkspaceRegions = body.regions || [];
  //: **A control that cannot act must not sit there looking live**, the same
  //: rule the Stop-reading button and the box-overlay toggle already follow.
  //: Shown only once there is something on screen to remove.
  //: Reported: "the delete this reading button doesnt work". It was gated on
  //: *regions*, which only Tesseract produces, a vision-model reading (the
  //: only kind this project actually uses) has text and no boxes, so the
  //: button never appeared for it. Gated on there being a reading at all.
  //: `body.pages` is a page *count* on the regions response and a list of
  //: readings on a stored-range response, `.some` on the number threw and
  //: took the whole page load down with it ("(body.pages || []).some is not
  //: a function" in the reader's status line, found by measurement).
  const hasReading = body.source !== "text-file" && (ocrWorkspaceRegions.length > 0
    || Boolean((body.text || "").trim())
    || (Array.isArray(body.pages) && body.pages.some((page) => (page?.text || "").trim())));
  $("ocr-delete-reading")?.classList.toggle("hidden", !hasReading);
  //: **Redo, made discoverable rather than merely possible.** Reported
  //: directly: "there's also no way to delete or redo ocr text extractions."
  //: Clicking "Read this page"/"Read this image" always re-reads and replaces
  //: the stored answer: `PageRead`'s own docstring: "re-reading a page
  //: replaces its row rather than appending", but nothing on the button said
  //: so, and a control that behaves differently from what it looks like it
  //: does is not discoverable just because it technically works. The label
  //: stays put (tests and habit both key off it); only the tooltip changes,
  //: once there is something on screen for it to describe replacing. Set
  //: here rather than in `ocrLoadPage` because that function calls this one
  //: to actually paint the page, reading `ocrWorkspaceRegions` before this
  //: line runs would still hold the *previous* page's count.
  const readBtn = $("ocr-read-page");
  if (readBtn) {
    readBtn.title = ocrWorkspaceRegions.length
      ? "Read again: replaces the reading shown here"
      : "Transcribe what you are looking at";
  }

  //: The badge is not decoration: a single whole-page region drawn from
  //: stored text is a *fallback*, and letting it look like something the
  //: reader found there would be a lie about where the text is.
  const labels = {
    tesseract: "ph:scan Read on the page",
    //: **"reading" is not a fallback badge any more, and it must not read as
    //: one.** It used to be "stored-text": one region covering the whole page,
    //: which really was a stand-in. Now the reading is split into its own
    //: typed blocks in order (`ocr.regions_from_reading`), real sections,
    //: real structure, just no rectangles, so the badge says what is true of
    //: it rather than apologising for what it lacks. The missing half is in
    //: the message underneath, where the offer to install Tesseract lives.
    reading: "ph:list-bullets Sections from the reading",
    //: Kept only so an older cached response does not render as "Nothing read
    //: yet", which would be wrong in the most alarming direction. Nothing
    //: emits it.
    "stored-text": "ph:text-align-left Stored text, no page positions",
    "text-file": "ph:file-text The file's own text",
    none: "ph:warning Nothing read yet",
  };
  setLabel(source, labels[body.source] || labels.none);
  //: Which model did it, the one Settings chose, named on the result so a
  //: wrong or missing model is visible here rather than only in Settings
  //: (asked for: readings "need to use the right models that are set in
  //: settings… properly manageable").
  if (body.source === "reading" || body.source === "vision") {
    source.appendChild(document.createTextNode(` · ${ocrReaderName()}`));
    source.title = `Read with ${ocrReaderName()}, change the reader above, or the model in Settings`;
  }
  source.hidden = false;
  source.classList.toggle("ocr-source-weak", body.source !== "tesseract");
  message.textContent = body.message || "";
  message.classList.toggle("hidden", !body.message);

  const positioned = body.source === "tesseract";
  //: **"I dont think that the regions works."** It did: there was simply
  //: nothing for it to show. Boxes are the positions the reader returned, and
  //: only Tesseract returns any: a vision model gives back the words on the
  //: page and nothing about where they sit (`ocr-page-read` renders its answer
  //: as one whole-page region on purpose, and says so in its own message). So
  //: on every vision or stored-text reading the toggle flipped a layer that
  //: was empty, which from the outside is indistinguishable from broken.
  //:
  //: A control that cannot do anything must say so rather than sit there
  //: looking live. Disabled, with the reason in its tooltip and the reader
  //: that *would* produce them named, which is also the honest argument for
  //: Tesseract still existing here.
  const boxToggle = $("ocr-show-boxes");
  const boxLabel = boxToggle?.closest("label");
  if (boxToggle) {
    boxToggle.disabled = !positioned;
    if (boxLabel) {
      boxLabel.classList.toggle("is-disabled", !positioned);
      boxLabel.title = positioned
        ? "Draw a box around each block the reader found"
        : "This reading has no page positions. Only Tesseract returns where each "
          + "block sits: a vision model gives back the words and not the places.";
    }
    //: The layer follows the checkbox even after a re-read, or a page read
    //: with boxes turned off would come back with them on.
    $("ocr-boxes").classList.toggle("is-hidden", positioned && !boxToggle.checked);
  }
  for (const region of ocrWorkspaceRegions) {
    //: `positioned` says the *reading* has boxes; `region.box` says this block
    //: does. They are the same thing today and were not always, a payload
    //: from before `box` became nullable, or a future reader that boxes some
    //: blocks and not others, would crash on `region.box.x` here. One extra
    //: check, and the list rows below still render for every block either way.
    if (positioned && region.box) {
      const box = document.createElement("button");
      box.type = "button";
      box.className = `ocr-box ocr-box-${region.kind}`;
      box.dataset.index = String(region.index);
      box.style.left = `${region.box.x * 100}%`;
      box.style.top = `${region.box.y * 100}%`;
      box.style.width = `${region.box.w * 100}%`;
      box.style.height = `${region.box.h * 100}%`;
      box.title = region.text.slice(0, 120);
      box.setAttribute("aria-label", `Region ${region.index + 1}: ${region.text.slice(0, 60)}`);
      box.addEventListener("click", () => ocrSelectRegion(region.index));
      boxes.appendChild(box);
    }

    const row = document.createElement("li");
    row.className = "ocr-region";
    row.dataset.index = String(region.index);
    //: **The two panes are one document, read from either side.** Asked for
    //: directly: "each page I am on it aoto scrolls to the extracted text in
    //: the pannel for extracted text on the right, and if I click on a
    //: specific text section of extracted text in the right panel it should
    //: auto scroll me to that page on the file."
    //:
    //: This half is the click: the row records which page it came from, and
    //: `ocrWireRegionJump` (below) turns that into a page change. The other
    //: half is `ocrRevealRegionsForPage`, called wherever the page changes.
    row.dataset.page = String(ocrRegionPage(region, body));
    const head = document.createElement("div");
    head.className = "row ocr-region-head";
    //: **Where this block came from, on the row itself.** Asked for: "make it
    //: so extracted text is visually linked to the page or section it was
    //: extracted from". Two halves: *which section* is the number, and
    //: *which page* is the badge, and both are true whether or not anything
    //: measured a rectangle, which is the whole reason the reading-derived
    //: regions are worth having.
    const where = document.createElement("span");
    where.className = "chip ocr-region-where";
    //: A stored page reading carries its own page; a live region belongs to
    //: the page on screen. Reported: every stored panel said "p1" because
    //: this only ever read `body.page`.
    const ownPage = Number.isInteger(region.page) ? region.page : Number(body.page) || 0;
    const pageNumber = ownPage + 1;
    const pageCount = Number(body.pages) || 1;
    if (Number.isInteger(region.page)) {
      // A stored reading is one panel per page: say the page, not "§1".
      where.textContent = `Page ${pageNumber}`;
      where.title = `The reading of page ${pageNumber}`;
    } else {
      where.textContent =
        pageCount > 1
          ? `p${pageNumber} \u00b7 \u00a7${region.index + 1}`
          : `\u00a7${region.index + 1}`;
      where.title =
        pageCount > 1
          ? `Section ${region.index + 1} of page ${pageNumber}`
          : `Section ${region.index + 1} of this page`;
    }
    head.appendChild(where);

    const kind = document.createElement("span");
    kind.className = `chip ocr-region-kind ocr-region-kind-${region.kind}`;
    //: Five kinds now, not two. Tesseract still only ever says heading/text;
    //: a reading also distinguishes lists, tables and code from prose, read
    //: off the block's own shape. An unknown kind falls back to "Text" rather
    //: than rendering `undefined`, which is the shape this repo keeps paying
    //: for elsewhere.
    kind.textContent =
      { heading: "Heading", list: "List", table: "Table", code: "Code", text: "Text" }[
        region.kind
      ] || "Text";
    head.appendChild(kind);
    if (region.confidence) {
      //: Confidence is the one number that tells you whether to trust a row,
      //: so it sits on the row rather than in a tooltip. Rounded to a whole
      //: percent: a reading is not 87.3% right.
      const conf = document.createElement("span");
      conf.className = "muted text-sm ocr-region-conf";
      conf.textContent = `${Math.round(region.confidence)}%`;
      conf.title = "How sure the reader was of this block";
      head.appendChild(conf);
    }
    const copy = document.createElement("button");
    copy.type = "button";
    //: **Top right, always.** Asked for: "move the copy text button to the top
    //: right in the text box". It looked like it already was, but the thing
    //: pushing it right was `.ocr-region-conf`'s own `margin-left: auto`, and
    //: only Tesseract returns a confidence. Every vision and stored-text
    //: reading therefore had no confidence row, nothing claimed the free
    //: space, and the copy button sat jammed against the "Text" chip on the
    //: left. The margin belongs on the thing that must be at the right.
    copy.className = "ghost small icon-button ocr-region-copy";
    setLabel(copy, "ph:copy");
    copy.title = "Copy this region's text";
    copy.setAttribute("aria-label", copy.title);
    copy.addEventListener("click", (event) => {
      event.stopPropagation();
      copyToClipboard(region.text, event.currentTarget);
    });
    head.appendChild(copy);
    //: **Delete this panel.** Asked for: "select on what was read and delete
    //: each extracted text panel as the delete this reading button doesn't
    //: do anything." That button deletes the reading of the page on
    //: *screen*, and with the panels for every stored page listed together
    //: the one you are looking at is usually not that page, so the delete
    //: landed on a page with nothing to delete and nothing changed. Each
    //: stored panel now removes its own page's reading.
    //: An image's reading is one panel; its delete is the header's delete.
    if (!Number.isInteger(region.page) && ocrWorkspaceCurrent && !ocrIsPdf(ocrWorkspaceCurrent)
        && body.source !== "text-file" && (region.text || "").trim()) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "ghost small icon-button danger ocr-region-delete";
      setLabel(remove, "ph:trash");
      remove.title = "Delete this reading";
      remove.setAttribute("aria-label", remove.title);
      remove.addEventListener("click", (event) => {
        event.stopPropagation();
        $("ocr-delete-reading")?.click();
      });
      head.appendChild(remove);
    }
    if (Number.isInteger(region.page) && body.source === "stored-text") {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "ghost small icon-button danger ocr-region-delete";
      setLabel(remove, "ph:trash");
      remove.title = `Delete the reading of page ${region.page + 1}`;
      remove.setAttribute("aria-label", remove.title);
      remove.addEventListener("click", async (event) => {
        event.stopPropagation();
        const image = ocrWorkspaceCurrent;
        if (!image) return;
        if (!(await confirmDialog(`Delete the reading for page ${region.page + 1}? You can read it again any time.`))) {
          return;
        }
        remove.disabled = true;
        try {
          const base = image._isAttachment ? `/files/${image.id}` : `/media/${image.id}`;
          await apiJson(`${base}/page-reads/${region.page}`, { method: "DELETE" });
          toast(`Reading of page ${region.page + 1} deleted.`);
          await ocrLoadPage(image, ocrWorkspacePage);
        } catch (error) {
          remove.disabled = false;
          toast(error.message || "Could not delete that reading.", true);
        }
      });
      head.appendChild(remove);
    }
    const text = document.createElement("p");
    text.className = "ocr-region-text";
    //: **A page can now have a description and no reading** (Phase 7.3), which
    //: is a state this paragraph had never had to render: an empty
    //: `contenteditable` box under a filled description reads as a reading that
    //: was lost rather than one that was never asked for. Said plainly, and not
    //: editable: typing into it would file invented text as a transcription,
    //: which is the failure `VisionOcrBody.text` exists to let people *undo*.
    const hasText = Boolean((region.text || "").trim());
    text.textContent = hasText ? region.text : "Not transcribed yet.";
    text.classList.toggle("ocr-region-text-empty", !hasText);
    //: **A misread line is fixable where you can see it.** Every reader gets
    //: words wrong: Tesseract on a bad scan, a vision model inventing a line
    //: that was not there (the failure `VisionOcrBody.text` already exists to
    //: let you correct on a *whole* image). Until now the workspace's answer
    //: to a wrong line was "copy it all out and fix it somewhere else".
    //:
    //: `contenteditable` on the one element holding that region's words, and
    //: the edit is written back into `ocrWorkspaceRegions`, which is what
    //: "Copy all", "Save as note" and "Ask about this" all read from, so a
    //: correction reaches every one of them without any of them knowing.
    //: Not persisted to the file's stored reading, and it must not silently
    //: be: this is a working copy of one page, and quietly overwriting the
    //: file's own transcription from a click in a preview would be the app
    //: deciding something it was not asked to decide.
    text.contentEditable = hasText ? "plaintext-only" : "false";
    text.spellcheck = false;
    text.title = hasText
      ? "Click to correct what was read"
      : "Nothing has been transcribed from this page yet, use Read this page";
    text.addEventListener("input", () => {
      const found = ocrWorkspaceRegions.find((item) => item.index === region.index);
      if (found) found.text = text.textContent;
    });
    //: A click in the text is a caret, not a region selection, without this
    //: the row's own handler steals the click and the caret never lands.
    text.addEventListener("click", (event) => event.stopPropagation());
    row.append(head, text);
    //: **The page's description, under the page's reading** (Phase 7.3, "a
    //: place to show it… per page, not one line under a thumbnail"). What the
    //: figures on this page *show* is a different claim from what the page
    //: *says*, so it is a separate, labelled block rather than more text
    //: appended to the transcription, the exact confusion the Library tile's
    //: own labelled fields were built to fix ("I feel the image captions and
    //: ocr extractions should be separated and labeled").
    //:
    //: Not editable, unlike the reading above it: a transcription can be
    //: *wrong* about what the page says and a person can fix it, while a
    //: description is one model's reading of a figure, re-describing it is
    //: the correction, and `Describe this page` is one click away.
    if ((region.caption || "").trim()) {
      const figures = document.createElement("p");
      figures.className = "ocr-region-caption";
      const label = document.createElement("span");
      label.className = "chip ocr-region-caption-label";
      const who = shortModelName(region.caption_model || "");
      label.textContent = who ? `Figures · ${who}` : "Figures";
      label.title = region.caption_model
        ? `Described by ${region.caption_model}`
        : "What this page's figures, charts and diagrams show";
      //: `sentence`, not `body`, `body` is this function's own parameter, and
      //: shadowing it here would silently rebind it for everything below.
      const sentence = document.createElement("span");
      sentence.textContent = region.caption;
      figures.append(label, sentence);
      row.appendChild(figures);
    }
    row.addEventListener("click", () => ocrSelectRegion(region.index));
    ocrWireRegionJump(row);
    list.appendChild(row);
  }
  if (!ocrWorkspaceRegions.length && !body.message) {
    message.textContent = "No text was found on this page.";
    message.classList.remove("hidden");
  }
  //: A find that survives a re-read: the rows were just rebuilt, so the filter
  //: has to be re-applied or a typed query silently stops filtering the moment
  //: a page is re-read, which is precisely when a reader is looking for it.
  ocrApplyFind();
}

// --- outline a region, read just that (UI_MODERNISATION_PLAN Phase 7.4) -----
//
// Asked as a question, and it is a good one: *"can there be a way for the user
// to manually outline and single out regions on a pdf or similar document and
// then the ai will read what is in those regions?? like maybe the user can
// outline a graph or diagram on a pdf slide and then the user cna get the
// image or ocr model to analyse and caption that thing."*
//
// The pieces were all already here, a page raster on screen, a percentage-
// positioned overlay measured against it, two readers and a describe prompt.
// What was missing is the gesture: drag on the page, and the rectangle you
// drew becomes the thing that gets read.
//
// **The rectangle is kept in fractions of the stage, not in pixels**, exactly
// as `.ocr-box` positions are (core/ocr.py returns fractions for the same
// reason): the pane resizes, the zoom changes, and a pixel rectangle would
// drift off the thing it was drawn around. Fractions also convert to *source*
// pixels for the crop with one multiplication by `naturalWidth`.

//: The rectangle currently drawn, in fractions of the page, or null.
let ocrRegionRect = null;
//: The pointer drag in progress: where it started (fractions) and which
//: element captured the pointer, so a drag that leaves the stage still ends.
let ocrRegionDrag = null;

//: **How small is a mis-click.** Measured against the running app: a plain
//: click on the page reports a 0-2px "drag", and treating that as a region
//: would pop the offer open every time somebody clicked the page to focus it.
//: In fractions rather than pixels so it means the same thing at every zoom.
const OCR_REGION_MIN = 0.01;

//: The stage the select layer is currently inside, the single stage in
//: one-page mode, or the current page's own stage in continuous mode. The page
//: picture is its `<img>`, which is what the crop is taken from.
function ocrSelectStage() {
  return $("ocr-select")?.parentElement || null;
}

function ocrSelectImage() {
  return ocrSelectStage()?.querySelector("img") || null;
}

//: Keep the two overlays together. `#ocr-boxes` is moved into the current
//: page's stage in continuous mode (see `ocrLoadPage`); the select layer has
//: to follow it or a drag would be measured against a stage that is not on
//: screen: and `ocrTearDownScroll` has to bring both home again.
function ocrMoveOverlays(target) {
  if (!target) return;
  const boxes = $("ocr-boxes");
  const select = $("ocr-select");
  if (select && select.parentElement !== target) target.appendChild(select);
  if (boxes && boxes.parentElement !== target) target.appendChild(boxes);
}

function ocrClearRegionSelection() {
  ocrRegionRect = null;
  ocrRegionDrag = null;
  $("ocr-select")?.replaceChildren();
  $("ocr-region-popover")?.classList.add("hidden");
}

//: Draw (or redraw) the marquee for `ocrRegionRect`. Percentages against the
//: select layer, which is `inset: 0` on the stage: the same geometry every
//: region box already uses, so the two cannot disagree about where the page is.
function ocrPaintRegionRect() {
  const layer = $("ocr-select");
  if (!layer) return;
  layer.replaceChildren();
  if (!ocrRegionRect) return;
  const marquee = document.createElement("div");
  marquee.className = "ocr-marquee";
  marquee.style.left = `${ocrRegionRect.x * 100}%`;
  marquee.style.top = `${ocrRegionRect.y * 100}%`;
  marquee.style.width = `${ocrRegionRect.w * 100}%`;
  marquee.style.height = `${ocrRegionRect.h * 100}%`;
  layer.appendChild(marquee);
}

//: Where the offer sits: under the rectangle when there is room below it,
//: above it when there is not. Measured against `#ocr-page-pane`, which is the
//: popover's positioned parent, so this stays right as the pane scrolls.
function ocrPlaceRegionPopover() {
  const popover = $("ocr-region-popover");
  const pane = $("ocr-page-pane");
  const layer = $("ocr-select");
  if (!popover || !pane || !layer || !ocrRegionRect) return;
  popover.classList.remove("hidden");
  const stage = layer.getBoundingClientRect();
  const box = pane.getBoundingClientRect();
  const size = popover.getBoundingClientRect();
  const bottom = stage.top + (ocrRegionRect.y + ocrRegionRect.h) * stage.height;
  const top = stage.top + ocrRegionRect.y * stage.height;
  //: `+ 8` is one gap between the rectangle and the offer; `--space-*` cannot
  //: be read from here, and a bare number in a *measurement* is not a token
  //: the design lint is about (it lints declarations in CSS, and this is a
  //: computed pixel offset, not a style rule).
  const gap = 8;
  const wantBelow = bottom + gap + size.height <= box.bottom;
  const y = wantBelow ? bottom + gap : Math.max(box.top + gap, top - gap - size.height);
  const centre = stage.left + (ocrRegionRect.x + ocrRegionRect.w / 2) * stage.width;
  //: Clamped the "pin to the margin" way round rather than the "hang off the
  //: edge" way: the same fix the selection kebab's own comment in app.js
  //: records, and for the same reason: when the panel is wider than the pane,
  //: `Math.min(Math.max(...))` puts it at a negative offset.
  const x = Math.max(
    box.left + gap,
    Math.min(centre - size.width / 2, box.right - size.width - gap)
  );
  //: `+ scrollLeft/scrollTop` because the offer is absolutely positioned inside
  //: `#ocr-page-pane`, which is itself a scroll container: `x`/`y` are viewport
  //: coordinates, and an absolute offset is measured from the pane's padding
  //: box *before* scrolling. Without these two terms the offer lands correctly
  //: only while the pane happens to be scrolled to the top.
  popover.style.left = `${Math.round(x - box.left + pane.scrollLeft)}px`;
  popover.style.top = `${Math.round(y - box.top + pane.scrollTop)}px`;
  const label = $("ocr-region-size");
  if (label) {
    //: What was outlined, in the page's own terms. A rectangle with no size
    //: on it is the same offer whether you grabbed one chart or the whole
    //: page, and the answer that comes back would not say which.
    label.textContent = `${Math.round(ocrRegionRect.w * 100)}% × ${Math.round(
      ocrRegionRect.h * 100
    )}% of page ${ocrWorkspacePage + 1}`;
  }
}

//: Pointer position as a fraction of the stage, clamped to it: a drag that
//: leaves the page still ends on the page's edge rather than describing a
//: rectangle that is partly off it.
function ocrRegionPoint(event) {
  const layer = $("ocr-select");
  if (!layer) return null;
  const box = layer.getBoundingClientRect();
  if (!box.width || !box.height) return null;
  return {
    x: Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)),
    y: Math.min(1, Math.max(0, (event.clientY - box.top) / box.height)),
  };
}

//: The crop, as a PNG blob, taken from the page raster at its own resolution.
//: `naturalWidth`, not the rendered width: the page is rasterised at 2x
//: (`pdfpages.RENDER_SCALE`) precisely so small type is legible to a model,
//: and cropping from the displayed size would throw that away before the model
//: ever saw it. Same-origin image, so the canvas is not tainted.
async function ocrRegionCrop() {
  const img = ocrSelectImage();
  if (!img || !ocrRegionRect || !img.naturalWidth) return null;
  const sx = Math.round(ocrRegionRect.x * img.naturalWidth);
  const sy = Math.round(ocrRegionRect.y * img.naturalHeight);
  const sw = Math.max(1, Math.round(ocrRegionRect.w * img.naturalWidth));
  const sh = Math.max(1, Math.round(ocrRegionRect.h * img.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = sw;
  canvas.height = sh;
  const context = canvas.getContext("2d");
  if (!context) return null;
  context.drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

//: One answer about one rectangle, in the pane where the reading already is.
//: Focused as it arrives, the request takes seconds and the reader has
//: usually looked away, so an answer that appears silently below the fold is
//: an answer nobody reads. `tabIndex = -1` rather than 0: it is a destination
//: for focus, not another stop on the way through the pane.
function ocrShowRegionResult({ mode, page, rect, text, model, message }) {
  const holder = $("ocr-region-results");
  if (!holder) return;
  holder.classList.remove("hidden");
  const card = document.createElement("article");
  card.className = "ocr-region-result";
  card.tabIndex = -1;
  const head = document.createElement("div");
  head.className = "row ocr-region-head";
  const where = document.createElement("span");
  where.className = "chip ocr-region-where";
  where.textContent = `Page ${page + 1} · region`;
  where.title = `A ${Math.round(rect.w * 100)}% × ${Math.round(
    rect.h * 100
  )}% rectangle you outlined on page ${page + 1}`;
  const kind = document.createElement("span");
  kind.className = "chip ocr-region-kind";
  kind.textContent = mode === "describe" ? "Description" : "Text";
  head.append(where, kind);
  if (model) {
    const who = document.createElement("span");
    who.className = "muted text-sm";
    who.textContent = shortModelName(model);
    who.title = model;
    head.appendChild(who);
  }
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "ghost small icon-button ocr-region-copy";
  setLabel(copy, "ph:copy");
  copy.title = "Copy this answer";
  copy.setAttribute("aria-label", copy.title);
  copy.addEventListener("click", (event) => {
    event.stopPropagation();
    copyToClipboard(text || message || "", event.currentTarget);
  });
  head.appendChild(copy);
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "ghost small icon-button danger ocr-region-delete";
  setLabel(remove, "ph:x");
  remove.title = "Dismiss this answer";
  remove.setAttribute("aria-label", remove.title);
  remove.addEventListener("click", (event) => {
    event.stopPropagation();
    card.remove();
    holder.classList.toggle("hidden", !holder.childElementCount);
  });
  head.appendChild(remove);
  const body = document.createElement("p");
  body.className = "ocr-region-text";
  //: Nothing found is a real answer and is said as one, an empty card would
  //: read as a request that silently failed.
  body.textContent = text || message || "Nothing came back for that region.";
  body.classList.toggle("ocr-region-text-empty", !text);
  card.append(head, body);
  //: Newest first: the previous answers are still worth keeping (that is the
  //: point of outlining several things), but the one just asked for is the one
  //: being waited on.
  holder.prepend(card);
  card.focus();
}

//: Read or describe whatever is outlined. Everything about *what* to run lives
//: server-side (`_read_region`, routes_files.py); this decides which file, and
//: hands over exactly the pixels that were outlined.
async function ocrRunRegion(mode) {
  const image = ocrWorkspaceCurrent;
  if (!image || !ocrRegionRect) return;
  const rect = { ...ocrRegionRect };
  const page = ocrWorkspacePage;
  const buttons = [$("ocr-region-read"), $("ocr-region-describe")];
  buttons.forEach((b) => b && (b.disabled = true));
  const blob = await ocrRegionCrop();
  if (!blob) {
    buttons.forEach((b) => b && (b.disabled = false));
    toast("That region couldn't be cut out of the page.", true);
    return;
  }
  const form = new FormData();
  form.append("crop", blob, "region.png");
  form.append("page", String(page));
  form.append("mode", mode);
  form.append("reader", ocrReader());
  const base = image._isAttachment ? `/files/${image.id}` : `/media/${image.id}`;
  const label = mode === "describe" ? "Describing that region…" : "Reading that region…";
  $("ocr-message").textContent = label;
  $("ocr-message").classList.remove("hidden");
  //: The rectangle goes as soon as the request is away. Asked for: "the
  //: rectangle is cleared after", and it is also what makes a second region
  //: drawable while the first is still being read.
  ocrClearRegionSelection();
  try {
    //: **The headers are replaced, not merged, and that is deliberate.**
    //: `api()` sends `Content-Type: application/json` by default, and a
    //: FormData body with that header has no multipart boundary, measured
    //: against the running app, the server answered 405 before any of this
    //: request's fields were ever looked at. Overriding `headers` drops that
    //: default so the browser writes its own boundary; the two headers the
    //: server actually needs are put back by hand. Same handling as every
    //: other FormData post in this app (`attachImageFiles` in app.js says so
    //: in its own comment).
    const answer = await apiJson(`${base}/region-read`, {
      method: "POST",
      headers: { "X-Auth-Token": authToken(), "X-Workspace-ID": activeSpaceId() },
      body: form,
    });
    ocrShowRegionResult({
      mode: answer.mode || mode,
      page: Number.isInteger(answer.page) ? answer.page : page,
      rect,
      text: (answer.text || "").trim(),
      model: answer.model || "",
      message: answer.message || "",
    });
    $("ocr-message").classList.add("hidden");
  } catch (error) {
    $("ocr-message").textContent = error.message || "That region couldn't be read.";
    $("ocr-message").classList.remove("hidden");
    toast(error.message || "That region couldn't be read.", true);
  } finally {
    buttons.forEach((b) => b && (b.disabled = false));
  }
}

//: Everything this document has already had read off it, from the store the
//: read endpoints write to. Never throws: a document with no readings and a
//: backend that cannot answer are the same thing here, nothing to show.
async function ocrStoredPageReads(image) {
  if (!image) return null;
  const base = image._isAttachment ? `/files/${image.id}` : `/media/${image.id}`;
  return apiJson(`${base}/page-reads`).catch(() => null);
}

async function ocrLoadPage(image, page = 0, opts = {}) {
  ocrWorkspaceCurrent = image;
  ocrWorkspacePage = Math.max(0, page);
  //: Whatever page descriptions are on screen belong to the *previous* load.
  //: Cleared here rather than where they are filled, because the two early
  //: returns below (a text file, a failed request) never reach that point and
  //: would leave another document's figures described under this one's page.
  ocrPageCaptions.clear();
  //: A rectangle is drawn on *a page*, so changing page has to take it with
  //: it: the fractions would otherwise be reinterpreted against a different
  //: picture and the offer would read a part of the wrong page.
  ocrClearRegionSelection();
  //: What to reopen, if this window is closed while a read is still running.
  ocrLastOpened = { image, page: ocrWorkspacePage };
  //: Which file this is. Four surfaces can open this dialog, and a header
  //: reading only "Text on the page" made you close it to find out what was
  //: in it.
  const fileLabel = $("ocr-file");
  if (fileLabel) {
    fileLabel.textContent = image.original_name || image.filename || "";
    fileLabel.hidden = !fileLabel.textContent;
    fileLabel.title = fileLabel.textContent;
  }
  const img = $("ocr-image");
  //: `_src` is an already-tokened url from a caller that has one (the
  //: lightbox); `url` is the raw path every gallery row carries. Running an
  //: already-tokened url back through `mediaSrc` appends a second token.
  //: `ocrPageImageUrl` keeps that rule and adds the PDF case, where the
  //: picture of the page is rendered rather than stored.
  const continuous =
    ocrViewMode === "scroll" && !$("ocr-scroll")?.classList.contains("hidden");
  if (continuous) {
    //: The pictures are all already on screen in this mode, so the only thing
    //: a page change moves is the region overlay, which must live inside the
    //: stage it is measured against, or every box lands on the wrong page.
    const target = document.querySelector(
      `#ocr-scroll .ocr-stage[data-page="${ocrWorkspacePage}"]`
    );
    //: Both overlays, not just the boxes: the region-select layer is measured
    //: against the stage it sits in, so leaving it behind would have a drag on
    //: page 6 outlining part of page 1.
    ocrMoveOverlays(target);
    if (!opts.fromScroll) ocrScrollToPage(ocrWorkspacePage);
  } else if (!ocrIsTextFile(image)) {
    //: **A text file has no picture of a page, so none is asked for.** The
    //: branch further down renders a .md, a .txt or a .docx as text and hides
    //: this `<img>`, but the `src` was set first, to the file's own url, and a
    //: browser handed markdown to decode as an image raises `error`: which is
    //: how a text file used to delete `#ocr-image` from the document (see
    //: `replaceMissingMedia` in app.js, which no longer lets it). Skipping the
    //: assignment removes the request as well as the error.
    img.src = ocrPageImageUrl(image, ocrWorkspacePage);
    img.alt = ocrIsPdf(image)
      ? `Page ${ocrWorkspacePage + 1} of ${image.original_name}`
      : `Page: ${image.original_name}`;
  }
  const activeKey = ocrIsPdf(image) ? `page:${ocrWorkspacePage}` : ocrRailKey(image);
  for (const thumb of document.querySelectorAll("#ocr-rail .ocr-rail-item")) {
    const active = thumb.dataset.key === activeKey;
    thumb.classList.toggle("is-active", active);
    thumb.setAttribute("aria-current", active ? "true" : "false");
  }
  //: A read started elsewhere and still running is the *first* thing this
  //: window has to say, otherwise reopening mid-read shows an empty page and
  //: reads as "it stopped when I closed the window", which is exactly what
  //: was reported.
  const running = ocrReadInFlight(image);
  $("ocr-message").textContent = running
    ? `${running.label}: this keeps running if you close this window.`
    : "Reading the page…";
  $("ocr-message").classList.remove("hidden");
  $("ocr-boxes").replaceChildren();
  $("ocr-region-list").replaceChildren();
  //: **The read button is not a PDF button.** Asked for directly: *"make it not
  //: just reading text on the page but truly ... an all encompassing text and
  //: image ocr workspace, dont limit the feature."* It was hidden outright for
  //: an image, so the one surface in the app built for reading a picture had no
  //: way to read the picture, you had to close it, find the tile in the
  //: gallery and use that row's own menu.
  $("ocr-read-page")?.classList.remove("hidden");
  const readLabel = $("ocr-read-page-label");
  if (readLabel) readLabel.textContent = ocrIsPdf(image) ? "Read this page" : "Read this image";
  //: The range box lives or dies with the per-page button, both are PDF-only,
  //: and a "read pages 1-5" control beside a photograph would be a lie.
  $("ocr-read-range-group")?.classList.toggle("hidden", !ocrIsPdf(image));

  //: **A text file needs no model at all.** Its words are already words, so
  //: the reader shows them straight away, same panes, same Copy / Ask /
  //: Save as note, and the read controls hidden because there is nothing to
  //: transcribe. This is what makes the workspace a reader for *every* file
  //: rather than only the two kinds a vision model is needed for.
  if (ocrIsTextFile(image)) {
    $("ocr-read-page")?.classList.add("hidden");
    $("ocr-describe")?.classList.add("hidden");
    $("ocr-boxes")?.replaceChildren();
    $("ocr-stage")?.classList.add("ocr-stage-text");
    try {
      const file = await ocrFetchFileText(image);
      const paragraphs = (file.text || "").split(/\n{2,}/).map((t) => t.trim()).filter(Boolean);
      ocrRenderRegions({
        regions: (paragraphs.length ? paragraphs : ["(This file is empty.)"]).map((text, index) => ({
          index, kind: "text", text, confidence: 0, box: { x: 0, y: 0, w: 1, h: 1 },
        })),
        source: "text-file",
        message: file.source === "converted"
          ? "Converted to text: no model was needed."
          : "Read straight from the file, no model was needed.",
        pages: 1,
        page: 0,
      });
      const stage = $("ocr-stage");
      if (stage) {
        //: The page picture belongs to a scan, not to a text file, hidden
        //: by class on the stage so it stays hidden through a re-render.
        stage.querySelector("img")?.classList.add("hidden");
        let pre = stage.querySelector(".ocr-text-view");
        if (!pre) {
          pre = document.createElement("pre");
          pre.className = "ocr-text-view";
          stage.appendChild(pre);
        }
        pre.textContent = file.text || "";
        $("ocr-image")?.classList.add("hidden");
      }
    } catch (error) {
      $("ocr-message").textContent = error.message || "That file could not be read.";
      $("ocr-message").classList.remove("hidden");
    }
    ocrSyncPager(image);
    return;
  }
  $("ocr-read-page")?.classList.remove("hidden");
  $("ocr-stage")?.classList.remove("ocr-stage-text");
  $("ocr-image")?.classList.remove("hidden");
  $("ocr-stage")?.querySelector(".ocr-text-view")?.remove();
  try {
    const body = await apiJson(ocrRegionsUrl(image, ocrWorkspacePage));
    //: **What was already read wins over "nothing read yet".** Reported
    //: twice: "ai read the pages 1-3 in my pdf as I put it, but no text
    //: appeared in any of the extracted text areas?? notifications appeared
    //: saying the pages were read but nothing happened after that."
    //:
    //: The second sentence was the diagnosis. A page read is announced as a
    //: background task precisely so this window can be closed while it runs, 
    //: and the result only ever existed in the response and in the DOM that
    //: response painted. Reopening the document re-ran the *regions* request,
    //: which knows nothing about page reads, and painted an empty pane over a
    //: reading that had genuinely happened.
    //:
    //: `GET …/page-reads` returns every page of this document the app has
    //: stored (see the `PageRead` model), in the same envelope a range read
    //: returns, so it goes straight through the same renderer. Asked for
    //: after the regions call and preferred over it only when it has
    //: something: a Tesseract reading with real box positions is a better
    //: answer than stored text, and this must not overwrite it.
    const stored = ocrIsPdf(image) ? await ocrStoredPageReads(image) : null;
    //: **Per-page descriptions, from the same response** (Phase 7.3). A page's
    //: reading and its description live on one `PageRead` row, so one request
    //: carries both; keeping them in a map keyed by page is what lets the
    //: caption line above name the page on screen while the panels below name
    //: their own. (Cleared at the top of `ocrLoadPage`, not here: an image
    //: never reaches this branch and would otherwise keep showing the last
    //: document's page 3.)
    for (const entry of stored?.pages || []) {
      if ((entry.caption || "").trim()) {
        ocrPageCaptions.set(Number(entry.page) || 0, {
          caption: entry.caption.trim(),
          caption_model: entry.caption_model || "",
        });
      }
    }
    const storedPages = (stored?.pages || []).filter(
      //: A page that has only been *described* still belongs in this list, 
      //: it is something the app knows about that page, and leaving it out
      //: meant a described-but-unread page rendered as "nothing read yet"
      //: with its description nowhere on screen.
      (p) => (p.text || "").trim() || (p.caption || "").trim()
    );
    if (storedPages.length && body.source !== "tesseract") {
      ocrRenderRegions({
        regions: storedPages.map((entry, index) => ({
          index,
          kind: "text",
          text: (entry.text || "").trim(),
          confidence: 0,
          box: { x: 0, y: 0, w: 1, h: 1 },
          caption: (entry.caption || "").trim(),
          caption_model: entry.caption_model || "",
          //: Which page this reading is *of*, the row's own badge and its
          //: delete button both need it, and `body.page` is only the page
          //: currently on screen.
          page: entry.page,
        })),
        source: "stored-text",
        message: stored.message || `${storedPages.length} page(s) already read.`,
        pages: body.pages || ocrWorkspacePages,
        page: ocrWorkspacePage,
      });
    } else {
      ocrRenderRegions(body);
    }
    //: An image's description lives here too, so caption and reading are
    //: managed side by side (reported: "a lot of disconnect between files and
    //: images regarding ocr and image captioning").
    const isImage = !ocrIsPdf(image);
    //: **Describe works for a document too now** (Phase 7.3). It used to be
    //: images-only, which is why a slide deck full of charts had no way to be
    //: described at all: the file-level caption route refuses a PDF, and the
    //: one surface built for reading documents hid the button.
    $("ocr-describe")?.classList.remove("hidden");
    const describeLabel = $("ocr-describe-label");
    if (describeLabel) {
      describeLabel.textContent = isImage ? "Describe" : "Describe this page";
    }
    const describeBtn = $("ocr-describe");
    if (describeBtn) {
      describeBtn.title = isImage
        ? "Describe this image with the vision model (writes its caption)"
        : "Describe the figures, charts and diagrams on this page";
    }
    const captionEl = $("ocr-caption");
    if (captionEl) {
      //: A page's own description, not the file's: `image.caption` is one
      //: sentence about a whole document, which describes none of its pages.
      //: `ocrPageCaptions` is filled from the same `page-reads` response the
      //: stored panels below are built from.
      const cap = isImage
        ? (image.caption || "").trim()
        : (ocrPageCaptions.get(ocrWorkspacePage)?.caption || "").trim();
      const who = isImage
        ? ""
        : shortModelName(ocrPageCaptions.get(ocrWorkspacePage)?.caption_model || "");
      captionEl.textContent = cap
        ? (who ? `Figures on this page (${who}): ${cap}` : `Description: ${cap}`)
        : "";
      captionEl.classList.toggle("hidden", !cap);
    }
    if (ocrIsPdf(image)) ocrBuildPageRail(image, body.pages || 1);
    ocrSyncPager(image);
    //: The mode can only be honoured once the page count is known, a
    //: continuous view of a document whose length is still unknown would
    //: build one page and call it the document.
    if (ocrIsPdf(image) && ocrViewMode === "scroll" && !continuous) {
      ocrSetViewMode("scroll", image);
    }
    //: The in-flight line wins over the "nothing read yet" message the
    //: backend sends: both are true, and only one of them is about to change.
    if (ocrReadInFlight(image)) {
      $("ocr-message").textContent = `${ocrReadInFlight(image).label}: this keeps running if you close this window.`;
      $("ocr-message").classList.remove("hidden");
    }
  } catch (error) {
    $("ocr-message").textContent = error.message || "That page could not be read.";
  }
}

//: One rail item per page of a document, built from the page count the region
//: response carries rather than from a second request. Thumbnails are the same
//: rendered-page endpoint at rail size, `loading="lazy"` so a 200-page scan
//: does not render 200 pages to show three.
function ocrBuildPageRail(image, pages) {
  ocrWorkspacePages = Math.max(1, pages || 1);
  const rail = $("ocr-rail");
  if (!rail) return;
  //: The switch above the rail gains its "Pages" segment only once the page
  //: count is known, which is here, the region response is the one thing that
  //: carries it. Redrawn on every page load so the count is right.
  ocrRenderRailSwitch(image);
  //: **The rail belongs to whichever list is selected.** Without this, opening
  //: a page of a PDF while the switch says "Images" would silently replace the
  //: sibling list with pages and leave the switch claiming otherwise, the
  //: state and the control disagreeing, which is the shape that makes a
  //: feature feel broken rather than merely limited.
  if (ocrRailMode !== "pages") return;
  if (rail.dataset.pagesFor === `${ocrRailKey(image)}:${ocrWorkspacePages}`) {
    for (const thumb of rail.querySelectorAll(".ocr-rail-item")) {
      const active = thumb.dataset.key === `page:${ocrWorkspacePage}`;
      thumb.classList.toggle("is-active", active);
      thumb.setAttribute("aria-current", active ? "true" : "false");
    }
    return;
  }
  rail.dataset.pagesFor = `${ocrRailKey(image)}:${ocrWorkspacePages}`;
  rail.replaceChildren();
  for (let index = 0; index < ocrWorkspacePages; index += 1) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "ocr-rail-item";
    item.dataset.key = `page:${index}`;
    const thumb = document.createElement("img");
    thumb.src = ocrPageImageUrl(image, index);
    thumb.alt = "";
    thumb.loading = "lazy";
    const name = document.createElement("span");
    name.className = "ocr-rail-name";
    name.textContent = `Page ${index + 1}`;
    item.append(thumb, name);
    item.title = `Page ${index + 1} of ${ocrWorkspacePages}`;
    item.classList.toggle("is-active", index === ocrWorkspacePage);
    item.addEventListener("click", () => ocrLoadPage(image, index));
    rail.appendChild(item);
  }
  rail.classList.toggle("hidden", ocrWorkspacePages < 2);
}

//: Two tables share one rail, and their ids collide, see `_touched_items`
//: in ai/agent.py for the same hazard on the same two id spaces.
function ocrRailKey(image) {
  return `${image._isAttachment ? "file" : "media"}:${image.id}`;
}

//: **Closing the window must not lose the reading.**
//:
//: Reported twice: *"I start document ocr, but then I close the workspace and
//: the ocr workspace goes as well so I cant access it again."* The read itself
//: has survived since `trackOcrRead` shipped: a POST keeps going and writes
//: its result whatever the browser does, but there was no door back in, which
//: from the outside is the same thing as losing it.
//:
//: So the close is a function rather than a class toggle: it remembers what
//: was open, and when a read is still running it leaves a notice on screen
//: with the way back. `toastAction` rather than a plain toast for exactly that
//: reason: a notice with no button is the thing that was already there.
let ocrLastOpened = null;

function closeOcrWorkspace() {
  const overlay = $("ocr-workspace");
  if (!overlay) return;
  overlay.classList.add("hidden");
  const running = ocrReadInFlight(ocrWorkspaceCurrent);
  if (!running || !ocrLastOpened) return;
  const { image, page } = ocrLastOpened;
  toastAction(`${running.label}: it keeps going.`, "Reopen", () => {
    openOcrWorkspace(image, []);
    if (page) setTimeout(() => ocrLoadPage(image, page), 150);
  });
}

//: Also reachable without closing anything: any surface that knows a read is
//: in flight can offer the way back through this.
function reopenOcrWorkspace() {
  if (!ocrLastOpened) return false;
  openOcrWorkspace(ocrLastOpened.image, []);
  if (ocrLastOpened.page) {
    setTimeout(() => ocrLoadPage(ocrLastOpened.image, ocrLastOpened.page), 150);
  }
  return true;
}
window.reopenOcrWorkspace = reopenOcrWorkspace;

//: **The way in that does not start from a file.**
//:
//: Reported: *"I want an easier and more accessible way to access the ocr
//: workspace as a proper and more central feature."* Every door the reader had
//: (the Files row's own button, the image card's kebab, the lightbox's "Read
//: text with AI" and its kebab) starts from a file you have already found, so
//: there was no answer at all to "I want to read something". The decision, in
//: UI_MODERNISATION_PLAN.md ("how the page reader is reached"), is the one the
//: meeting recorder's identically worded report already produced: the command
//: palette and the Tools & features browser, which are this app's two answers
//: to "reachable from anywhere", and no fifth per-file door.
//:
//: It opens on a file rather than on a picker because the reader's own rail is
//: already a list of every image and file in the notebook (`ocrLoadSiblings`),
//: so a chooser in front of it would be a second copy of the list behind it.
//: The order is the one that is right most often: what you were last reading,
//: then the newest thing you could read, then an honest empty state.
async function openPageReader() {
  //: The file you last had open in the reader, if this session has had one.
  //: `reopenOcrWorkspace` also restores the page you were on, which is the
  //: whole reason to prefer it over re-picking the same file from the cache.
  if (reopenOcrWorkspace()) return true;
  const rows = await ocrLoadSiblings().catch(() => []);
  //: The same extension test the lightbox's own menu row uses to decide
  //: whether the reader can open a thing at all. A `.docx` in the notebook is
  //: a file the reader has no raster for, and offering it here would be a door
  //: onto an empty stage.
  const readable = (rows || []).filter((row) =>
    /\.(png|jpe?g|gif|webp|bmp|pdf)$/i.test(row.original_name || row.filename || "")
  );
  if (!readable.length) {
    //: Not a dead end: the Files sub-tab is where a file gets into the
    //: notebook, so the empty case ends where the next step is.
    toast("Nothing to read yet. Add a PDF or a picture and it opens here.");
    switchTab("library");
    document.querySelector('#library-subtabs button[data-media-kind="files"]')?.click();
    return false;
  }
  //: `ocrSiblingCache` keeps `/media` then `/files/gallery` in the order each
  //: route returns them, which is the order the Library's own lists show:
  //: newest first. So this is the newest document you have, and a picture only
  //: if you have no documents at all: "read this for me" is asked about a scan
  //: far more often than about a photograph, and whichever this picks, every
  //: other file is one click away on the rail beside it.
  const target = readable.find((row) => ocrIsPdf(row)) || readable[0];
  openOcrWorkspace(target, readable);
  return true;
}

window.openPageReader = openPageReader;

//: **Which list the rail is showing.** "pages" is only reachable while a PDF
//: is open; the other two are always available, which is the point.
let ocrRailMode = "images";

//: Every image and every readable file in the notebook, loaded by the
//: workspace itself.
//:
//: **Why this exists.** Reported: *"I cant always switch between viewing
//: files or images, and if I open it from the lightbox when viewing an image,
//: no other files or images show."* The rail was built from an `images`
//: argument, and three of `openOcrWorkspace`'s four call sites passed `[]`, 
//: the lightbox, the reopen toast, and `reopenOcrWorkspace`. So the workspace
//: was navigable only when it happened to be opened from the gallery grid,
//: and everywhere else it was a dead end with no error and nothing to click.
//: A view that can only be navigated when a particular caller remembers to
//: hand it a list is a view whose navigation does not exist.
//:
//: Reuses `/media` and `/files/gallery`, the same two the Library's own
//: gallery loads, with the same `_isImage`/`_isAttachment` flags set the same
//: way, because a second shape for the same rows is how the two ended up
//: disagreeing about what an attachment is once already.
let ocrSiblingCache = null;

async function ocrLoadSiblings({ force = false } = {}) {
  if (ocrSiblingCache && !force) return ocrSiblingCache;
  const [images, attachments] = await Promise.all([
    //: Every upload, not the first page of them: the rail this builds is
    //: the workspace's only navigation, and a file missing from it is a
    //: file the reader cannot reach at all. `GET /media` is paged (INBOX
    //: 117), so this asks until `X-Total-Count` is satisfied.
    apiPagedList("/media", MEDIA_PAGE_SIZE, { silent: true }).catch(() => []),
    apiJson("/files/gallery", { silent: true }).catch(() => []),
  ]);
  for (const item of images || []) item._isImage = isImageUrl(item.url);
  for (const item of attachments || []) {
    item._isImage = (item.mime || "").startsWith("image/");
    item._isAttachment = true;
    item.ocr_text = item.ocr_text || "";
    item.caption = item.caption || "";
    item.vision_ocr_text = item.vision_ocr_text || "";
  }
  ocrSiblingCache = [...(images || []), ...(attachments || [])];
  return ocrSiblingCache;
}

//: A file the workspace can actually open. Images always; otherwise only what
//: `ocrIsPdf` recognises: the rail is a list of things to read, and a row
//: that opens to an empty stage is worse than a shorter rail.
//: Files whose text the app can read without a model: everything
//: `GET /files/{id}/text` already handles (plain text, markdown, code, CSV,
//: and a converted .docx), plus any text-ish upload. Asked for: "make sure
//: all files are handled and viewable". A spreadsheet workbook (.xlsx) and
//: other binary formats still cannot be shown, there is no parser for them
//: in this app, and inventing one is not a UI change.
const OCR_TEXT_SUFFIXES = /\.(txt|md|markdown|csv|tsv|json|ya?ml|log|py|js|ts|html?|css|sql|sh|ini|toml|docx|rtf)$/i;

function ocrIsTextFile(row) {
  if (!row || row._isImage || ocrIsPdf(row)) return false;
  const name = row.original_name || row.filename || "";
  if (OCR_TEXT_SUFFIXES.test(name)) return true;
  return (row.mime || "").startsWith("text/");
}

function ocrCanOpen(row) {
  return Boolean(row && (row._isImage || ocrIsPdf(row) || ocrIsTextFile(row)));
}

//: Fetch a readable file's text. Attachments go through the endpoint that
//: already converts (`/files/{id}/text`); an upload is fetched raw, which
//: is right for the plain-text kinds `ocrIsTextFile` lets through.
async function ocrFetchFileText(row) {
  if (row._isAttachment) {
    const body = await apiJson(`/files/${row.id}/text`);
    return { text: body.text || "", kind: body.kind || "plain", source: body.source || "file" };
  }
  const res = await fetch(mediaSrc(row.url), { headers: { "X-Auth-Token": localStorage.getItem("token") || "" } });
  if (!res.ok) throw new Error("That file could not be read.");
  return { text: await res.text(), kind: "plain", source: "file" };
}

//: Build the switch above the rail. Rebuilt on every rail render because the
//: counts change with the notebook and the "Pages" segment only exists while
//: a paged document is open.
function ocrRenderRailSwitch(current) {
  const host = $("ocr-rail-switch");
  if (!host) return;
  const siblings = ocrSiblingCache || [];
  const segments = [
    {
      id: "images",
      label: "Images",
      count: siblings.filter((row) => row._isImage).length,
      title: "Every picture in the notebook",
    },
    {
      id: "files",
      label: "Files",
      count: siblings.filter((row) => !row._isImage && ocrCanOpen(row)).length,
      title: "Every document the reader can open",
    },
  ];
  if (ocrIsPdf(current) && ocrWorkspacePages > 1) {
    segments.push({
      id: "pages",
      label: "Pages",
      count: ocrWorkspacePages,
      title: "The pages of the document you are reading",
    });
  }
  host.replaceChildren();
  //: One segment is not a choice. Hidden rather than rendered inert, for the
  //: same reason the box-overlay toggle is disabled when there is nothing to
  //: show: a control that cannot do anything teaches that the feature is
  //: broken.
  //: Always shown: the switch is how the reader moves between everything
  //: in the space, so an empty side reads as "no files yet" (disabled, 0)
  //: rather than as a control that comes and goes.
  //: A one-page document offers no Pages segment, so "pages" mode would
  //: leave the rail empty and no tab lit (measured): fall back to Files.
  if (ocrRailMode === "pages" && !segments.some((segment) => segment.id === "pages")) ocrRailMode = "files";
  const usable = segments;
  host.classList.remove("hidden");
  for (const segment of usable) {
    const button = document.createElement("button");
    button.disabled = segment.count === 0;
    button.type = "button";
    button.className = "ocr-rail-tab";
    button.dataset.mode = segment.id;
    button.setAttribute("role", "tab");
    const active = segment.id === ocrRailMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.title = segment.title;
    const name = document.createElement("span");
    name.textContent = segment.label;
    const count = document.createElement("span");
    count.className = "ocr-rail-tab-count";
    count.textContent = String(segment.count);
    button.append(name, count);
    button.addEventListener("click", () => {
      ocrRailMode = segment.id;
      ocrRenderRail(ocrWorkspaceCurrent || current);
    });
    host.appendChild(button);
  }
}

//: Fill the rail for whichever mode is selected. "pages" is left to
//: `ocrLoadPage`, which is the only thing that knows the page count.
function ocrRenderRail(current) {
  const rail = $("ocr-rail");
  if (!rail) return;
  ocrRenderRailSwitch(current);
  if (ocrRailMode === "pages") return; // the page rail is built elsewhere
  const siblings = (ocrSiblingCache || []).filter(
    (row) => ocrCanOpen(row) && (ocrRailMode === "images" ? row._isImage : !row._isImage)
  );
  ocrWorkspaceImages = siblings;
  rail.dataset.pagesFor = "";
  rail.replaceChildren();
  const currentKey = current ? ocrRailKey(current) : "";
  for (const row of siblings) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "ocr-rail-item";
    item.dataset.key = ocrRailKey(row);
    item.classList.toggle("is-active", item.dataset.key === currentKey);
    if (row._isImage) {
      const thumb = document.createElement("img");
      thumb.src = mediaSrc(row.url);
      thumb.alt = "";
      thumb.loading = "lazy";
      item.appendChild(thumb);
    } else {
      //: A PDF has no thumbnail to fetch without rasterising it, and a broken
      //: `<img>` in a rail reads as a missing file rather than as a document.
      const glyph = document.createElement("span");
      glyph.className = "ocr-rail-glyph";
      //: The icon says what the file is, every non-image was a PDF glyph,
      //: so a .csv and a .docx both claimed to be PDFs in the rail.
      setLabel(glyph, ocrIsPdf(row) ? "ph:file-pdf" : ocrIsTextFile(row) ? "ph:file-text" : "ph:file");
      item.appendChild(glyph);
    }
    const name = document.createElement("span");
    name.className = "ocr-rail-name";
    name.textContent = row.original_name;
    item.appendChild(name);
    item.title = row.original_name;
    item.addEventListener("click", () => ocrOpenSibling(row));
    rail.appendChild(item);
  }
  rail.classList.toggle("hidden", !siblings.length);
}

//: Opening a *different* thing from the rail, as opposed to a different page
//: of the same thing. A PDF resets the paging state and takes the page rail;
//: an image keeps the sibling rail it was picked from.
function ocrOpenSibling(row) {
  if (ocrIsPdf(row)) {
    ocrWorkspacePage = 0;
    ocrWorkspacePages = 1;
    ocrRailMode = "pages";
    ocrTearDownScroll();
    ocrLoadPage(row, 0);
    return;
  }
  //: Reported: "when clicking on images, it doesn't even go onto them and
  //: just stays on the file I was on." Opening an image from a document that
  //: was in continuous mode hit `ocrLoadPage`'s continuous branch: which
  //: only moves the region overlay between the pages already on screen and
  //: never sets the image, so the PDF's pages stayed put. An image is one
  //: page: leave the document's scroll stages and paging behind first.
  ocrTearDownScroll();
  ocrWorkspacePage = 0;
  ocrWorkspacePages = 1;
  ocrLoadPage(row);
  ocrRenderRail(row);
}

//: `page` is the page to open *at*, zero-based, Phase 7.1's "a way into the
//: OCR Workspace at that page". It defaults to 0, which is what every caller
//: that has no page in mind (a gallery row, the reopen toast) still passes by
//: omitting it; the lightbox passes the page you were looking at, because
//: opening a fifteen-page scan at page 1 from page 9 is navigation the reader
//: then has to redo by hand.
function openOcrWorkspace(image, images, page = 0) {
  const overlay = $("ocr-workspace");
  if (!overlay) return;
  //: Clamped at 0 here rather than trusted: a caller with a stale page number
  //: (a document re-read since, a negative from an off-by-one) must land on a
  //: real page, and `ocrLoadPage` clamps the upper end against the count it
  //: learns from the region response.
  const startPage = Math.max(0, Number(page) || 0);
  ocrWorkspacePage = startPage;
  ocrWorkspacePages = 1;
  //: Answers about regions belong to the file they were asked about. They are
  //: not stored anywhere, so opening another document has to take them away
  //: rather than leave them looking like something known about the new one.
  const answers = $("ocr-region-results");
  if (answers) {
    answers.replaceChildren();
    answers.classList.add("hidden");
  }
  ocrClearRegionSelection();
  //: The remembered mode is *wanted*, not yet applied: whether it can be
  //: honoured depends on the page count, which only the region response
  //: knows. `ocrLoadPage` turns it on once that comes back. The teardown here
  //: deliberately does **not** go through `ocrSetViewMode("page")`, that
  //: writes the preference, and opening a document would quietly forget that
  //: you read in continuous mode.
  ocrTearDownScroll();
  ocrViewMode = ocrStoredViewMode();
  ocrSyncViewButtons();
  ocrWatchPane();
  //: Both answers change while the app runs, a model gets loaded, an extra
  //: gets installed: so the picker is rebuilt on every open, not at boot.
  ocrLoadReaders();
  const find = $("ocr-find");
  if (find) find.value = "";
  const rail = $("ocr-rail");
  //: A document's rail is its *pages*; a gallery image's rail is the other
  //: images beside it. Two different lists in one strip, so the page rail is
  //: built from the region response (which knows the page count) and this
  //: sibling rail is built here.
  //: **The rail no longer depends on the caller.** Whatever list was passed
  //: seeds the cache so a gallery open still paints instantly, but the
  //: workspace then loads the rest itself, which is what makes it navigable
  //: when opened from the lightbox, from the reopen toast, or from a
  //: still-running read, all three of which passed nothing.
  //: Reported: "the images/pages selector disappears when on the images
  //: and only shows on files." The gallery seeded this cache with *its*
  //: list, images only, and the loader below then treated the cache as
  //: complete, so the Files count was 0 and the switch hid itself. The
  //: seed still paints the rail instantly; the full list always follows.
  const seeded = Array.isArray(images) && images.length && !ocrSiblingCache;
  if (seeded) ocrSiblingCache = images;
  ocrRailMode = ocrIsPdf(image) ? "pages" : image._isImage ? "images" : "files";
  rail.dataset.pagesFor = "";
  rail.replaceChildren();
  rail.classList.add("hidden");
  overlay.classList.remove("hidden");
  if (ocrIsPdf(image)) {
    ocrWorkspaceImages = [];
    ocrLoadPage(image, startPage);
  } else {
    //: An image is one page; a `startPage` for it would be a number with
    //: nothing to point at.
    ocrLoadPage(image);
  }
  //: Fetched after the overlay is up and the first page is loading, so the
  //: rail filling in never delays the thing you actually opened. A failure
  //: leaves the rail empty, which is exactly where it started.
  ocrLoadSiblings({ force: Boolean(seeded) })
    .then(() => ocrRenderRail(image))
    .catch(() => {});
}

//: **The whole page, in a pane that is the wrong shape for it.** See the
//: matching CSS comment for why this is not `max-height: 100%`: the stage's
//: height is `auto`, so a percentage cap against it computes to none, and
//: `object-fit` would letterbox the picture inside the box the region overlay
//: is measured against. Setting the stage's *width* keeps the stage exactly
//: as big as the picture, which is what makes a percentage-positioned box
//: land on the words it names.
function ocrFitStage() {
  for (const [stage, img] of ocrVisibleStages()) ocrSizeStage(stage, img);
}

//: Every stage currently on screen, paired with its picture. One in one-page
//: mode; one per page in continuous mode, which is why sizing had to stop
//: being a function that knew there was exactly one `#ocr-stage`.
function ocrVisibleStages() {
  if (ocrViewMode === "scroll" && !$("ocr-scroll")?.classList.contains("hidden")) {
    return [...document.querySelectorAll("#ocr-scroll .ocr-stage")].map((stage) => [
      stage,
      stage.querySelector("img"),
    ]);
  }
  return [[$("ocr-stage"), $("ocr-image")]];
}

function ocrSizeStage(stage, img) {
  const pane = $("ocr-page-pane");
  if (!pane || !stage || !img) return;
  const naturalWidth = img.naturalWidth || 0;
  const naturalHeight = img.naturalHeight || 0;
  if (!naturalWidth || !naturalHeight) return;
  if (!pane.classList.contains("is-fit")) {
    //: Actual size means the page's own pixels. Left to CSS the stage
    //: shrink-to-fits the pane instead, measured: an 800px-wide scan came
    //: back 757px wide, which is neither fit nor actual.
    stage.style.width = `${naturalWidth}px`;
    return;
  }
  //: The pane's *content* box: its padding is not room the picture can use.
  const style = getComputedStyle(pane);
  const availableWidth =
    pane.clientWidth - Number.parseFloat(style.paddingLeft) - Number.parseFloat(style.paddingRight);
  const availableHeight =
    pane.clientHeight - Number.parseFloat(style.paddingTop) - Number.parseFloat(style.paddingBottom);
  if (availableWidth <= 0 || availableHeight <= 0) return;
  //: Never upscale: a small screenshot blown up to fill the pane is blurry
  //: and says nothing more than it did at its own size.
  const scale = Math.min(availableWidth / naturalWidth, availableHeight / naturalHeight, 1);
  stage.style.width = `${Math.floor(naturalWidth * scale)}px`;
}

//: **The page rendered at a tenth of its size, and nothing in the source was
//: wrong.** Reported: *"fix ... the view of individual pages"*, with a
//: screenshot of a slide the size of a postage stamp in a pane ten times
//: bigger.
//:
//: Measured rather than reasoned about, because reading the code proved
//: nothing: every line of `ocrSizeStage` is right. At the moment the `<img>`
//: fires `load`, `#ocr-page-pane` measures **142px** wide; a beat later it
//: measures **769px**, and re-running the very same sizing code then produces
//: the correct 757px stage every time. The grid had not settled, and the fit
//: was computed against a pane that was about to stop existing at that size.
//: It was intermittent, four runs in a row wrong, two right, which is
//: exactly why "it looks fine here" kept closing it.
//:
//: A ResizeObserver is the fix that does not depend on winning the race: fit
//: is already a *mode* rather than a number in this file, so the honest
//: implementation is to re-fit whenever the box being fitted into changes
//: size. It covers the three other cases that had the same bug and were never
//: reported: the rail appearing when a second page is found (which narrows
//: this pane), the window resizing, and the dialog opening on a page whose
//: picture was already in cache.
let ocrPaneObserver = null;

function ocrWatchPane() {
  if (ocrPaneObserver || typeof ResizeObserver === "undefined") return;
  const pane = $("ocr-page-pane");
  if (!pane) return;
  ocrPaneObserver = new ResizeObserver(() => {
    if ($("ocr-workspace")?.classList.contains("hidden")) return;
    //: Only Fit depends on the pane's size. At a fixed zoom the stage is the
    //: page's own pixels and re-running this would fight the user's scroll.
    if (ocrZoom === null) ocrFitStage();
  });
  ocrPaneObserver.observe(pane);
}

//: **What "100%" means for a page that was rendered rather than photographed.**
//:
//: Reported: *"the document at 100% zoom is still zoomed in and I cant zoom
//: out."* Both halves were true. A PDF page is rasterised at
//: `pdfpages.RENDER_SCALE` (2.0: ~144 DPI, picked so a vision model can read
//: small type), so the PNG's own pixels are twice the page's nominal size and
//: "Actual size" was a 200% view wearing a 100% label. And the control was a
//: two-state segment, so there was no way down from it.
//:
//: An image is its own pixels and needs no correction; only a rendered page
//: does, which is why this is keyed on the file being a PDF rather than on a
//: number carried in the response.
const OCR_PDF_RENDER_SCALE = 2;
//: The steps the ± buttons walk. Wide at the bottom because reading a scan at
//: 50% is a real thing to want, and fine at the top because the point of
//: zooming into an OCR page is to check one word.
const OCR_ZOOM_STEPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3];
//: `null` means Fit: the mode, not a number, so resizing the window keeps
//: fitting rather than freezing at whatever fit happened to be.
let ocrZoom = null;

function ocrNaturalScale() {
  return ocrIsPdf(ocrWorkspaceCurrent) ? OCR_PDF_RENDER_SCALE : 1;
}

function ocrApplyZoom() {
  const pane = $("ocr-page-pane");
  const stage = $("ocr-stage");
  const img = $("ocr-image");
  const label = $("ocr-zoom-level");
  if (!pane || !stage || !img) return;
  if (ocrZoom === null) {
    pane.classList.add("is-fit");
    ocrFitStage();
    // The Fit button beside it is already lit; a second "Fit" as the level
    // read as a duplicate control (screenshot). Shown only as a percentage.
    if (label) { label.textContent = "Fit"; label.hidden = true; }
    return;
  }
  pane.classList.remove("is-fit");
  if (label) label.hidden = false;
  //: The page's own size on paper is the rendered width divided by the scale
  //: it was rendered at; the zoom multiplies *that*, so 100% is 100%. Applied
  //: to every stage on screen, which in continuous mode is every page.
  for (const [pageStage, pageImg] of ocrVisibleStages()) {
    const natural = pageImg?.naturalWidth || 0;
    if (!pageStage || !natural) continue;
    pageStage.style.width = `${Math.round((natural / ocrNaturalScale()) * ocrZoom)}px`;
  }
  if (label) label.textContent = `${Math.round(ocrZoom * 100)}%`;
}

function ocrStepZoom(direction) {
  //: Stepping from Fit starts at whatever Fit currently *is*, so the first
  //: press changes the picture by one step rather than jumping to 100%.
  if (ocrZoom === null) {
    const [stage, img] = ocrVisibleStages()[0] || [];
    const shown = stage ? stage.getBoundingClientRect().width : 0;
    const paper = (img?.naturalWidth || 0) / ocrNaturalScale();
    ocrZoom = paper ? Math.min(3, Math.max(0.25, shown / paper)) : 1;
  }
  const steps = OCR_ZOOM_STEPS;
  const next =
    direction > 0
      ? steps.find((step) => step > ocrZoom + 0.001)
      : [...steps].reverse().find((step) => step < ocrZoom - 0.001);
  ocrZoom = next ?? ocrZoom;
  ocrApplyZoom();
  ocrSyncZoomButtons();
}

//: The segment and the ± row describe one state, so they are painted from it
//: rather than each tracking their own idea of what is showing.
function ocrSyncZoomButtons() {
  for (const button of document.querySelectorAll("#ocr-zoom button")) {
    const isFit = button.dataset.ocrZoom === "fit";
    const on = isFit ? ocrZoom === null : ocrZoom === 1;
    button.classList.toggle("active", on);
    button.setAttribute("aria-pressed", String(on));
  }
  const out = $("ocr-zoom-out");
  const zin = $("ocr-zoom-in");
  if (out) out.disabled = ocrZoom !== null && ocrZoom <= OCR_ZOOM_STEPS[0];
  if (zin) zin.disabled = ocrZoom !== null && ocrZoom >= OCR_ZOOM_STEPS.at(-1);
}

//: **One page at a time, or the whole document under your thumb.**
//:
//: Asked for directly: *"allow scrolling in documents between pages as well"*.
//: The rail has always been able to *jump* to a page; what it could not do is
//: let you move *through* a document, which is how anyone looks for the page
//: with the diagram on it. Both modes exist because both are right for
//: different work: one page is what you want while checking a transcription
//: line by line against the picture it came from, and a scroll is what you
//: want while looking for the page worth transcribing at all.
//:
//: The mode is remembered, because it is a preference about how you read
//: rather than a property of this document.
const OCR_VIEW_KEY = "memorymap.ocr.view";
let ocrViewMode = "page";
//: Set while the code is doing the scrolling, so the observer that watches
//: which page is on screen does not answer its own scroll by scrolling again.
let ocrScrollSyncing = false;
let ocrScrollObserver = null;

function ocrStoredViewMode() {
  try {
    return localStorage.getItem(OCR_VIEW_KEY) === "scroll" ? "scroll" : "page";
  } catch {
    //: A private window throws on localStorage. A remembered preference is
    //: worth nothing next to the dialog opening at all.
    return "page";
  }
}

function ocrSyncViewButtons() {
  for (const button of document.querySelectorAll("#ocr-view button")) {
    const on = button.dataset.ocrView === ocrViewMode;
    button.classList.toggle("active", on);
    button.setAttribute("aria-pressed", String(on));
  }
}

function ocrSetViewMode(mode, image) {
  ocrViewMode = mode === "scroll" ? "scroll" : "page";
  try {
    localStorage.setItem(OCR_VIEW_KEY, ocrViewMode);
  } catch {
    //: See ocrStoredViewMode: not remembering is not a failure worth showing.
  }
  ocrSyncViewButtons();
  const continuous = ocrViewMode === "scroll" && ocrIsPdf(image) && ocrWorkspacePages > 1;
  if (!continuous) {
    ocrTearDownScroll();
    ocrApplyZoom();
    return;
  }
  $("ocr-page-pane")?.classList.add("is-scroll");
  $("ocr-stage")?.classList.add("hidden");
  $("ocr-scroll")?.classList.remove("hidden");
  ocrBuildScrollPages(image);
}

//: Back to one page on the stage, touching no preference. Giving the boxes
//: layer back to the single stage is the part that matters: it is the element
//: every region is percentage-positioned against, so a `#ocr-boxes` left
//: inside a discarded scroll page would put every box on nothing at all.
function ocrTearDownScroll() {
  const stage = $("ocr-stage");
  const scroll = $("ocr-scroll");
  $("ocr-page-pane")?.classList.remove("is-scroll");
  stage?.classList.remove("hidden");
  scroll?.classList.add("hidden");
  ocrMoveOverlays(stage);
  if (scroll) {
    scroll.replaceChildren();
    scroll.dataset.pagesFor = "";
  }
  ocrScrollObserver?.disconnect();
  ocrScrollObserver = null;
}

//: One stage per page, built once per document. `loading="lazy"` is what keeps
//: this honest for a long scan: the pages below the fold are markup, not
//: requests, until you scroll to them.
function ocrBuildScrollPages(image) {
  const scroll = $("ocr-scroll");
  if (!scroll) return;
  const key = `${ocrRailKey(image)}:${ocrWorkspacePages}`;
  if (scroll.dataset.pagesFor !== key) {
    scroll.dataset.pagesFor = key;
    scroll.replaceChildren();
    for (let index = 0; index < ocrWorkspacePages; index += 1) {
      const stage = document.createElement("div");
      stage.className = "ocr-stage ocr-scroll-stage";
      stage.dataset.page = String(index);
      const img = document.createElement("img");
      img.src = ocrPageImageUrl(image, index);
      img.alt = `Page ${index + 1} of ${image.original_name}`;
      img.loading = index < 2 ? "eager" : "lazy";
      //: Each page sizes itself as it arrives: pages in one PDF are not
      //: required to be the same shape, and a fit computed from page 1 would
      //: be wrong for a landscape page 7.
      img.addEventListener("load", () => ocrSizeStage(stage, img));
      const tag = document.createElement("span");
      tag.className = "ocr-scroll-tag";
      tag.textContent = `Page ${index + 1}`;
      stage.append(img, tag);
      scroll.appendChild(stage);
    }
  }
  ocrWatchScroll(image);
  ocrApplyZoom();
  ocrScrollToPage(ocrWorkspacePage);
}

//: Which page you are looking at, decided by what is actually on screen rather
//: than by what was last clicked, the rail, the page counter and the regions
//: pane all follow the scroll.
function ocrWatchScroll(image) {
  ocrScrollObserver?.disconnect();
  const scroll = $("ocr-scroll");
  const pane = $("ocr-page-pane");
  if (!scroll || !pane || typeof IntersectionObserver === "undefined") return;
  ocrScrollObserver = new IntersectionObserver(
    (entries) => {
      if (ocrScrollSyncing) return;
      //: The most-visible page wins. A threshold alone flickers between two
      //: pages at a boundary; picking the largest intersection does not.
      let best = null;
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        if (!best || entry.intersectionRatio > best.intersectionRatio) best = entry;
      }
      if (!best) return;
      const page = Number(best.target.dataset.page);
      if (!Number.isInteger(page) || page === ocrWorkspacePage) return;
      ocrLoadPage(image, page, { fromScroll: true });
    },
    { root: pane, threshold: [0.25, 0.5, 0.75] }
  );
  for (const stage of scroll.querySelectorAll(".ocr-stage")) ocrScrollObserver.observe(stage);
}

function ocrScrollToPage(page) {
  const target = document.querySelector(`#ocr-scroll .ocr-stage[data-page="${page}"]`);
  if (!target) return;
  ocrScrollSyncing = true;
  target.scrollIntoView({ block: "start", behavior: "auto" });
  //: Long enough for the scroll to land and the observer to fire once on it.
  setTimeout(() => {
    ocrScrollSyncing = false;
  }, 300);
}

//: Where you are, in words, beside the two controls that change it. A page
//: counter is not decoration in a document reader, without it "next page"
//: is a button with no idea how many times it can be pressed.
function ocrSyncPager(image) {
  //: Every path that changes the page ends here -- the pager buttons, the
  //: rail, and continuous scrolling -- which makes it the one place the
  //: reading panel has to be told to follow. See `ocrRevealRegionsForPage`.
  ocrRevealRegionsForPage(ocrWorkspacePage);
  const pager = $("ocr-pager");
  const label = $("ocr-page-label");
  const multi = ocrIsPdf(image) && ocrWorkspacePages > 1;
  if (pager) pager.hidden = !multi;
  if (label) label.textContent = `Page ${ocrWorkspacePage + 1} of ${ocrWorkspacePages}`;
  const previous = $("ocr-prev-page");
  const next = $("ocr-next-page");
  if (previous) previous.disabled = ocrWorkspacePage <= 0;
  if (next) next.disabled = ocrWorkspacePage >= ocrWorkspacePages - 1;
  $("ocr-view")?.classList.toggle("hidden", !multi);
}

function ocrStepPage(delta) {
  const image = ocrWorkspaceCurrent;
  if (!image || ocrWorkspacePages < 2) return;
  const next = ocrWorkspacePage + delta;
  if (next < 0 || next >= ocrWorkspacePages) return;
  ocrLoadPage(image, next);
}

//: **Which readers this machine actually has.** A picker whose second entry
//: always fails is worse than no picker, so the option is disabled and says
//: why rather than being offered and erroring. Refreshed on open because both
//: answers change while the app is running, a model gets loaded, an extra
//: gets installed.
let ocrReaders = {
  vision: false,
  tesseract: false,
  vision_model: "",
  vision_reason: "",
  ocr: false,
  ocr_model: "",
  ocr_reason: "",
};

async function ocrLoadReaders() {
  const select = $("ocr-reader");
  if (!select) return;
  try {
    ocrReaders = await apiJson("/ocr-readers");
  } catch {
    //: An unreachable status endpoint must not disable reading: leave both
    //: options enabled and let the read itself report what went wrong.
    ocrReaders = {
      vision: true,
      tesseract: true,
      vision_model: "",
      vision_reason: "",
      ocr: false,
      ocr_model: "",
      ocr_reason: "",
    };
  }
  const vision = select.querySelector('option[value="vision"]');
  const second = select.querySelector('option[value="ocr"]');
  const tess = select.querySelector('option[value="tesseract"]');
  if (vision) {
    //: "document reader", not "vision model": this option is
    //: `resolve_ocr_model`, which prefers a model built to transcribe a page
    //: (GLM-OCR, DeepSeek-OCR, PaddleOCR-VL) and only falls back to a general
    //: vision model. Calling it "vision model" is what produced the report, 
    //: "my ocr model shows as a vision model", because the label named the
    //: wrong one of the two things it could be.
    vision.textContent = ocrReaders.vision_model
      ? `AI document reader (${ocrReaders.vision_model})`
      : "AI document reader";
    vision.disabled = ocrReaders.vision === false;
    vision.title = ocrReaders.vision_reason || "";
  }
  if (second) {
    //: **Hidden unless there is a genuine second choice.** The backend only
    //: fills `ocr_model` when `resolve_vision_model` returns something
    //: *different* from the default reader, on the common machine with one
    //: vision model installed, both resolvers return it, and offering the same
    //: model twice under two names is a worse picker than offering it once.
    const has = Boolean(ocrReaders.ocr && ocrReaders.ocr_model);
    second.hidden = !has;
    second.disabled = !has;
    second.textContent = has
      ? `AI vision model (${shortModelName(ocrReaders.ocr_model)})`
      : "AI vision model";
    second.title = has ? ocrReaders.ocr_model : "";
    second.title = has
      ? "The general vision model, rather than the dedicated page reader. Worth "
        + "trying when a page is a photograph or a diagram more than a document."
      : ocrReaders.ocr_reason || "";
  }
  if (tess) {
    tess.disabled = ocrReaders.tesseract === false;
    tess.textContent = ocrReaders.tesseract
      ? "Tesseract (fast, on-page positions)"
      : "Tesseract (not installed)";
    tess.title = ocrReaders.tesseract
      ? "No model needed: about a tenth of a second a page, and it says where each block sits."
      : "Install the “OCR” extra in Settings → Optional extras.";
  }
  //: Fall to whichever one works rather than leaving a disabled option
  //: selected, which reads as "this is what will happen" and is not.
  if (select.selectedOptions[0]?.disabled || select.selectedOptions[0]?.hidden) {
    select.value = ocrReaders.tesseract && !ocrReaders.vision ? "tesseract" : "vision";
  }
  //: No repaint call is needed: `enhanceSelect` (app.js) watches each select
  //: with `MutationObserver(rebuild, {childList: true, subtree: true})`, and
  //: assigning `option.textContent` replaces the option's text node: a
  //: childList mutation: so the app's own dropdown rebuilds itself. Written
  //: down because `disabled` alone would *not* have been seen (no
  //: `attributes: true`), which is why every branch above sets the label too.
}

function ocrReader() {
  const value = $("ocr-reader")?.value;
  return value === "tesseract" || value === "ocr" ? value : "vision";
}

function ocrReaderName() {
  const reader = ocrReader();
  if (reader === "tesseract") return "Tesseract";
  if (reader === "ocr") return ocrReaders.ocr_model || "the vision model";
  return ocrReaders.vision_model || "AI";
}

//: **Find, over the reading.** The point of transcribing a page is that its
//: words become searchable; until now the result was a list you scrolled with
//: your eyes. Filters the region rows and says how many matched, so an empty
//: result is a statement rather than a blank pane.
//: Which page a region belongs to. A whole-page reading carries `region.page`;
//: a Tesseract box carries none and belongs to whichever page was read, which
//: the response records as `body.page`.
function ocrRegionPage(region, body) {
  if (Number.isInteger(region.page)) return region.page;
  return Number(body && body.page) || 0;
}

//: Panel -> page. Click anywhere in a section that is not already a control
//: (its Copy and Delete buttons stop propagation of their own) and the page
//: pane goes to the page that section was read from.
function ocrWireRegionJump(row) {
  row.addEventListener("click", (event) => {
    if (event.target.closest("button, a, input, textarea")) return;
    const page = Number(row.dataset.page);
    const image = ocrWorkspaceCurrent;
    if (!image || !Number.isInteger(page) || page === ocrWorkspacePage) return;
    if (page < 0 || page >= ocrWorkspacePages) return;
    ocrLoadPage(image, page);
  });
}

//: Page -> panel. Marks every section belonging to the page on screen and
//: brings the first of them into view, so changing page never leaves the
//: reading panel showing a different part of the document.
//:
//: `ocrRegionScrollLock` is the same guard `ocrScrollToPage` needs and for the
//: same reason: in continuous mode a programmatic scroll of one pane fires the
//: scroll listener of the other, and without it the two chase each other.
let ocrRegionScrollLock = false;

function ocrRevealRegionsForPage(page) {
  const list = $("ocr-region-list");
  if (!list || ocrRegionScrollLock) return;
  const rows = [...list.querySelectorAll(".ocr-region")];
  if (!rows.length) return;
  let first = null;
  for (const row of rows) {
    const mine = Number(row.dataset.page) === page;
    row.classList.toggle("is-current-page", mine);
    if (mine && !first && !row.classList.contains("hidden")) first = row;
  }
  if (!first) return;
  ocrRegionScrollLock = true;
  first.scrollIntoView({ block: "nearest", behavior: "auto" });
  setTimeout(() => {
    ocrRegionScrollLock = false;
  }, 300);
}

function ocrApplyFind() {
  const query = ($("ocr-find")?.value || "").trim().toLowerCase();
  const rows = [...document.querySelectorAll("#ocr-region-list .ocr-region")];
  let hits = 0;
  for (const row of rows) {
    const text = (row.textContent || "").toLowerCase();
    const match = !query || text.includes(query);
    row.classList.toggle("hidden", !match);
    row.classList.toggle("is-found", Boolean(query) && match);
    if (query && match) hits += 1;
  }
  const count = $("ocr-find-count");
  if (count) count.textContent = query ? `${hits} of ${rows.length}` : "";
  //: The boxes on the picture follow the filter, so "find" answers *where* as
  //: well as *what*: the one thing this workspace can do that a text search
  //: over a transcription cannot.
  for (const box of document.querySelectorAll("#ocr-boxes .ocr-box")) {
    const row = document.querySelector(
      `#ocr-region-list .ocr-region[data-index="${box.dataset.index}"]`
    );
    box.classList.toggle("is-dimmed", Boolean(query) && row?.classList.contains("hidden"));
  }
}

//: Reading a *picture*, as opposed to a page of a document. Deliberately the
//: same two endpoints the Images gallery's own row menu uses
//: (`analyseMediaRow`) rather than a third path: one place decides what a
//: vision read and a Tesseract read of an image mean, and a reading started
//: here has to appear on the gallery tile afterwards, which it does, because
//: it is written to the same column.
async function ocrReadImage(image, button) {
  const reader = ocrReader();
  const label = `Reading ${image.original_name || "this image"} with ${ocrReaderName()}…`;
  button.disabled = true;
  $("ocr-message").textContent = label;
  $("ocr-message").classList.remove("hidden");
  const progress = typeof toastProgress === "function" ? toastProgress(label) : null;
  try {
    await trackOcrRead(
      image,
      label,
      analyseMediaRow(image, reader === "tesseract" ? "ocr" : "vision-ocr", { force: true })
    );
    //: Re-read rather than render the response: the regions endpoint is the
    //: one thing that knows how to turn either reader's answer into boxes, and
    //: a second renderer here would drift from it.
    await ocrLoadPage(image, 0);
    progress?.done(`Read ${image.original_name || "the image"}.`);
    //: The gallery behind this dialog is now stale, the tile it was opened
    //: from has a reading it is not showing. This is the same repaint the
    //: gallery's own row menu triggers after an analyse.
    renderLibraryImagesGallery();
  } catch (error) {
    $("ocr-message").textContent = error.message || "That image could not be read.";
    $("ocr-message").classList.remove("hidden");
    progress?.done(error.message || "That image could not be read.", { isError: true });
  } finally {
    button.disabled = false;
  }
}

function ocrAllText() {
  return ocrWorkspaceRegions.map((region) => region.text).join("\n\n").trim();
}

document.addEventListener("DOMContentLoaded", () => {
  $("ocr-close")?.addEventListener("click", () => closeOcrWorkspace());
  $("ocr-workspace")?.addEventListener("click", (event) => {
    //: Click the backdrop to close, the card to keep working, the same rule
    //: every other overlay in this app follows.
    if (event.target === event.currentTarget) closeOcrWorkspace();
  });
  $("ocr-page-pane")?.classList.add("is-fit");
  for (const button of document.querySelectorAll("#ocr-zoom button")) {
    button.addEventListener("click", () => {
      //: Fit is a *mode* (null) and 100% is a number, so both go through the
      //: one state `ocrApplyZoom` paints from: the old handler toggled a
      //: class and called the fitter, which is why "Actual size" had no way
      //: back and no idea what percentage it was showing.
      ocrZoom = button.dataset.ocrZoom === "fit" ? null : 1;
      ocrApplyZoom();
      ocrSyncZoomButtons();
    });
  }
  for (const button of document.querySelectorAll("#ocr-view button")) {
    button.addEventListener("click", () => {
      ocrSetViewMode(button.dataset.ocrView, ocrWorkspaceCurrent);
    });
  }
  $("ocr-prev-page")?.addEventListener("click", () => ocrStepPage(-1));
  $("ocr-next-page")?.addEventListener("click", () => ocrStepPage(1));
  $("ocr-find")?.addEventListener("input", () => ocrApplyFind());
  //: A reader is a claim about *who read this*, so switching it clears the
  //: reading rather than leaving one reader's words under the other's name.
  $("ocr-reader")?.addEventListener("change", () => {
    const message = $("ocr-message");
    if (!message) return;
    message.textContent =
      ocrReader() === "tesseract"
        ? "Tesseract will read the page, no model needed, and it marks where each block sits."
        : "The AI vision model will read the page.";
    message.classList.remove("hidden");
  });
  //: **The reading has to be able to leave this window.** A transcription you
  //: can only re-read inside the dialog that produced it is a dead end; the
  //: two things anyone does with one are ask about it and keep it.
  $("ocr-to-chat")?.addEventListener("click", () => {
    const text = ocrAllText();
    if (!text) return toast("There is nothing to ask about yet.", true);
    const name = ocrWorkspaceCurrent?.original_name || "this page";
    const page = ocrIsPdf(ocrWorkspaceCurrent) ? `, page ${ocrWorkspacePage + 1}` : "";
    const quoted = text.length > 4000 ? `${text.slice(0, 4000)}…` : text;
    const prompt = `Here is the text read from ${name}${page}:\n\n${quoted}\n\n`;
    //: The composer, not a sent message: the question is the user's to write,
    //: and asking one on their behalf is what the selection popup's own
    //: "Ask the AI about this" was told not to do. Same two lines it uses, 
    //: `switchTab("chat")` then fill `#chat-input`, rather than a second way
    //: of starting a chat that can drift from the first.
    const box = document.getElementById("chat-input");
    if (!box) return toast("The chat isn't available right now.", true);
    closeOcrWorkspace();
    switchTab("chat");
    box.value = prompt;
    box.focus();
    //: The composer grows with its content (`.autogrow`), and that is driven
    //: by `input`, a value set in script fires nothing, so without this the
    //: box stays one line tall over four paragraphs of text.
    box.dispatchEvent(new Event("input", { bubbles: true }));
  });
  //: Arrow keys and Page Up/Down move between pages, which is what every
  //: document reader on the machine already does, a page rail you can only
  //: click is a reader you have to use with a mouse.
  document.addEventListener("keydown", (event) => {
    const overlay = $("ocr-workspace");
    if (!overlay || overlay.classList.contains("hidden")) return;
    //: Never while typing: the range box and the find box are both text
    //: fields inside this dialog, and Left/Right belong to the caret there.
    const tag = document.activeElement?.tagName;
    //: Escape closes the reader (measured: it did not): unless a confirm
    //: is up, which owns Escape, or a text field has focus, where Escape
    //: first drops out of the field. Ctrl+F goes to "Find in what was read"
    //: rather than the browser's own find, which cannot see this dialog's
    //: text any better than the page's.
    if (event.key === "Escape") {
      if (document.querySelector(".confirm-overlay")) return;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") { document.activeElement.blur(); return; }
      //: **Escape cancels the rectangle before it closes the window.** Asked
      //: for by name in Phase 7.4 ("Escape cancels"), and it is also the only
      //: sane order: having outlined something by mistake, the key you reach
      //: for must undo the mistake rather than throw away the whole reading
      //: session it happened in.
      if (ocrRegionRect) {
        event.preventDefault();
        ocrClearRegionSelection();
        return;
      }
      event.preventDefault();
      closeOcrWorkspace();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") {
      event.preventDefault();
      $("ocr-find")?.focus();
      return;
    }
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (event.key === "ArrowLeft" || event.key === "PageUp") {
      event.preventDefault();
      ocrStepPage(-1);
    } else if (event.key === "ArrowRight" || event.key === "PageDown") {
      event.preventDefault();
      ocrStepPage(1);
    } else if (event.key === "Home") {
      event.preventDefault();
      if (ocrWorkspaceCurrent) ocrLoadPage(ocrWorkspaceCurrent, 0);
    } else if (event.key === "End") {
      event.preventDefault();
      if (ocrWorkspaceCurrent) ocrLoadPage(ocrWorkspaceCurrent, ocrWorkspacePages - 1);
    }
  });
  //: **Drag on the page to outline a region** (Phase 7.4). Pointer events, not
  //: mouse events: the same gesture then works with a stylus on a tablet,
  //: which is the device somebody reading a scanned page is most likely to be
  //: circling a chart on.
  //:
  //: `setPointerCapture` is what makes a drag that leaves the stage still end
  //:, without it, releasing the button over the reading pane leaves the app
  //: convinced a drag is still in progress.
  $("ocr-select")?.addEventListener("pointerdown", (event) => {
    //: Left button only, and never while a text file is showing, there is no
    //: page raster to crop from, so the offer would lead nowhere.
    if (event.button !== 0) return;
    if (ocrWorkspaceCurrent && ocrIsTextFile(ocrWorkspaceCurrent)) return;
    const start = ocrRegionPoint(event);
    if (!start) return;
    event.preventDefault();
    ocrClearRegionSelection();
    ocrRegionDrag = start;
    event.currentTarget.setPointerCapture(event.pointerId);
  });
  $("ocr-select")?.addEventListener("pointermove", (event) => {
    if (!ocrRegionDrag) return;
    const now = ocrRegionPoint(event);
    if (!now) return;
    ocrRegionRect = {
      x: Math.min(ocrRegionDrag.x, now.x),
      y: Math.min(ocrRegionDrag.y, now.y),
      w: Math.abs(now.x - ocrRegionDrag.x),
      h: Math.abs(now.y - ocrRegionDrag.y),
    };
    ocrPaintRegionRect();
  });
  $("ocr-select")?.addEventListener("pointerup", (event) => {
    if (!ocrRegionDrag) return;
    ocrRegionDrag = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    //: A click is a drag of nearly nothing, and offering to read a 2px
    //: rectangle would make clicking the page feel broken.
    if (!ocrRegionRect || ocrRegionRect.w < OCR_REGION_MIN || ocrRegionRect.h < OCR_REGION_MIN) {
      ocrClearRegionSelection();
      return;
    }
    ocrPlaceRegionPopover();
  });
  //: A cancelled pointer (the browser taking over for a scroll gesture, the
  //: window losing focus) has to leave no half-drawn rectangle behind.
  $("ocr-select")?.addEventListener("pointercancel", () => ocrClearRegionSelection());
  $("ocr-region-read")?.addEventListener("click", () => ocrRunRegion("read"));
  $("ocr-region-describe")?.addEventListener("click", () => ocrRunRegion("describe"));
  $("ocr-region-cancel")?.addEventListener("click", () => ocrClearRegionSelection());
  $("ocr-zoom-in")?.addEventListener("click", () => ocrStepZoom(1));
  $("ocr-zoom-out")?.addEventListener("click", () => ocrStepZoom(-1));
  $("ocr-image")?.addEventListener("load", () => {
    ocrApplyZoom();
    ocrSyncZoomButtons();
  });
  window.addEventListener("resize", () => {
    if (!$("ocr-workspace")?.classList.contains("hidden")) ocrApplyZoom();
  });
  $("ocr-show-boxes")?.addEventListener("change", (event) => {
    $("ocr-boxes").classList.toggle("is-hidden", !event.currentTarget.checked);
  });
  $("ocr-copy-all")?.addEventListener("click", (event) => {
    const text = ocrAllText();
    if (!text) return toast("There is nothing to copy yet.", true);
    copyToClipboard(text, event.currentTarget);
  });
  //: **Delete, the half of "delete or redo" that redo did not already have.**
  //: Redo is just clicking "Read this page"/"Read this image" again: the
  //: backend replaces the stored reading rather than appending to it, but
  //: there was no way to remove a wrong reading without covering it with a
  //: better one. This removes it outright: the current PDF page's own stored
  //: reading (`PageRead`, via the new DELETE route), or a plain image's
  //: `ocr_text`/`vision_ocr_text` field, cleared through the same `analyse`
  //: endpoint the reader already uses to write it, sending `""` is the
  //: documented way to clear either field, not a new code path.
  $("ocr-describe")?.addEventListener("click", async (event) => {
    const image = ocrWorkspaceCurrent;
    if (!image) return;
    const button = event.currentTarget;
    button.disabled = true;
    $("ocr-message").textContent = ocrIsPdf(image)
      ? `Describing page ${ocrWorkspacePage + 1} with ${ocrReaders.vision_model || "the vision model"}…`
      : `Describing with ${ocrReaders.vision_model || "the vision model"}…`;
    $("ocr-message").classList.remove("hidden");
    try {
      //: **A document is described a page at a time** (Phase 7.3). Reported:
      //: "image captioning, how it is done and displayed needs to be refined
      //: for pdf documents and other similar documents. with graphs, images
      //: and diagrams in them." One caption on the file is the right shape for
      //: a photograph and describes none of a slide deck's twenty pages; the
      //: page-caption route writes `PageRead.caption` for the page on screen,
      //: with a prompt that asks about *figures* rather than "what does this
      //: image show" (ai/captioning.py's `PAGE_CAPTION_PROMPT`).
      if (ocrIsPdf(image)) {
        const base = image._isAttachment ? `/files/${image.id}` : `/media/${image.id}`;
        const described = await apiJson(
          `${base}/page-caption?page=${ocrWorkspacePage}`,
          { method: "POST" }
        );
        await ocrLoadPage(image, ocrWorkspacePage);
        //: The model can be reached, run, and still have nothing to say, 
        //: `message` carries that, and a "Description written." toast over it
        //: would be the app claiming work it did not do.
        toast(described?.caption ? `Page ${ocrWorkspacePage + 1} described.` : described?.message
          || "Nothing was written for that page.", !described?.caption);
        return;
      }
      const updated = await analyseMediaRow(image, "caption", { force: true });
      if (updated && typeof updated.caption === "string") image.caption = updated.caption;
      renderLibraryImagesGallery();
      await ocrLoadPage(image, ocrWorkspacePage);
      toast("Description written.");
    } catch (error) {
      //: **The status line has to stop claiming work that failed.** Measured
      //: against the running app with no vision model installed: the toast said
      //: "The AI model isn't running" while the pane underneath still read
      //: "Describing page 1 with the vision model…", which is the app saying
      //: two different things about the same click. (The image path had the
      //: same gap; one `catch` now covers both.)
      $("ocr-message").textContent = error.message || "Couldn't describe that.";
      $("ocr-message").classList.remove("hidden");
      toast(error.message || "Couldn't describe that.", true);
    } finally {
      button.disabled = false;
    }
  });
  $("ocr-delete-reading")?.addEventListener("click", async (event) => {
    const image = ocrWorkspaceCurrent;
    if (!image) return;
    const isPdf = ocrIsPdf(image);
    const what = isPdf ? `page ${ocrWorkspacePage + 1}` : "this image";
    if (!(await confirmDialog(`Delete the reading for ${what}? You can read it again any time.`))) {
      return;
    }
    const button = event.currentTarget;
    button.disabled = true;
    try {
      if (isPdf) {
        const base = image._isAttachment ? `/files/${image.id}` : `/media/${image.id}`;
        await apiJson(`${base}/page-reads/${ocrWorkspacePage}`, { method: "DELETE" });
      } else {
        //: Same reader-to-field mapping `ocrReadImage` uses for the read
        //: itself, so delete clears the field the *current* reader would
        //: have written rather than guessing at the other one.
        const kind = ocrReader() === "tesseract" ? "ocr" : "vision-ocr";
        await analyseMediaRow(image, kind, { text: "" });
        //: The gallery tile behind this dialog now claims a reading that is
        //: gone: same repaint `ocrReadImage` triggers after writing one.
        renderLibraryImagesGallery();
      }
      toast("Reading deleted.");
      await ocrLoadPage(image, ocrWorkspacePage);
    } catch (error) {
      toast(error.message || "Could not delete that reading.", true);
    } finally {
      button.disabled = false;
    }
  });
  //: **The document reader.** Tesseract cannot open a PDF at all
  //: (`core/ocr.py`'s OCR_SUFFIXES), and this project was told directly not to
  //: depend on it: *"I basically dont want to download tesseract and only
  //: want to use an ai vision learning and ocr model for images and scanned
  //: documents."* So the page you are looking at is rasterised server-side and
  //: handed to the local vision model, one page at a time: a reader who wants
  //: page 6 should not wait through five pages they have already checked.
  $("ocr-stop-read")?.addEventListener("click", () => {
    if (!ocrStopRead()) return;
    $("ocr-message").textContent = "Stopped. Nothing was written.";
    $("ocr-message").classList.remove("hidden");
  });

  $("ocr-read-page")?.addEventListener("click", async (event) => {
    const image = ocrWorkspaceCurrent;
    if (!image) return;
    if (!ocrIsPdf(image)) return ocrReadImage(image, event.currentTarget);
    const button = event.currentTarget;
    const page = ocrWorkspacePage;
    button.disabled = true;
    const label = `Reading page ${page + 1} with ${ocrReaderName()}…`;
    $("ocr-message").textContent = label;
    $("ocr-message").classList.remove("hidden");
    //: Announced outside this window as well as in it, because the window can
    //: be closed while the model works and the read must still be findable.
    const progress = typeof toastProgress === "function" ? toastProgress(label) : null;
    const base = image._isAttachment ? `/files/${image.id}` : `/media/${image.id}`;
    try {
      const controller = new AbortController();
      const body = await trackOcrRead(
        image,
        label,
        apiJson(`${base}/ocr-page-read?page=${page}&reader=${ocrReader()}`, {
          method: "POST",
          signal: controller.signal,
        }),
        controller
      );
      const text = (body.text || "").trim();
      if (text) {
        //: Rendered like a `stored-text` reading, one region, no boxes , 
        //: because that is honestly what it is: a vision model returns the
        //: words on the page, not where they sit on it.
        ocrRenderRegions({
          regions: [
            { index: 0, kind: "text", text, confidence: 0, box: { x: 0, y: 0, w: 1, h: 1 } },
          ],
          source: "stored-text",
          message: `Read by ${shortModelName(body.model || ocrReaderName())}, text only, no page positions.`,
          pages: ocrWorkspacePages,
          page,
        });
      } else {
        $("ocr-message").textContent = body.message || "Nothing was read on this page.";
        $("ocr-message").classList.remove("hidden");
      }
      progress?.done(text ? `Read page ${page + 1} of ${image.original_name}.` : body.message || "Nothing was read.");
    } catch (error) {
      //: A read the user stopped is not a failure and must not be reported
      //: as one: `ocrStopRead` has already written the "Stopped." line, and
      //: a red toast on top of it says the app broke when it obeyed.
      if (error?.name === "AbortError") {
        progress?.done("Reading stopped.");
        return;
      }
      $("ocr-message").textContent = error.message || "That page could not be read.";
      progress?.done(error.message || "That page could not be read.", { isError: true });
    } finally {
      button.disabled = false;
    }
  });
  //: **Read a range, or the whole document.** Reported: the workspace could
  //: read the page you were looking at and nothing else, so a ten-page scan
  //: took ten clicks and ten waits.
  //:
  //: Renders one region per page rather than a single blob, so the reading
  //: keeps the shape of the document: each page's text is separately
  //: copyable, and "Save as note" writes them in order with their page
  //: numbers instead of a wall of text nobody can navigate.
  $("ocr-read-range")?.addEventListener("click", async (event) => {
    const image = ocrWorkspaceCurrent;
    if (!image) return;
    const button = event.currentTarget;
    const spec = ($("ocr-read-pages")?.value || "all").trim() || "all";
    button.disabled = true;
    const label =
      spec === "all"
        ? `Reading every page with ${ocrReaderName()}…`
        : `Reading pages ${spec} with ${ocrReaderName()}…`;
    $("ocr-message").textContent = label;
    $("ocr-message").classList.remove("hidden");
    const progress = typeof toastProgress === "function" ? toastProgress(label) : null;
    const base = image._isAttachment ? `/files/${image.id}` : `/media/${image.id}`;
    try {
      const controller = new AbortController();
      const body = await trackOcrRead(
        image,
        label,
        apiJson(
          `${base}/ocr-range-read?pages=${encodeURIComponent(spec)}&reader=${ocrReader()}`,
          { method: "POST", signal: controller.signal }
        ),
        controller
      );
      const withText = (body.pages || []).filter((page) => (page.text || "").trim());
      if (withText.length) {
        ocrRenderRegions({
          //: `kind: "heading"` on nothing here: these are pages, not layout
          //: blocks, and the label carries the page number because a reader
          //: scrolling twelve transcriptions needs to know which is which.
          regions: withText.map((page, index) => ({
            index,
            kind: "text",
            text: `Page ${page.page + 1}\n\n${page.text.trim()}`,
            confidence: 0,
            box: { x: 0, y: 0, w: 1, h: 1 },
          })),
          source: "stored-text",
          message: body.message || `Read ${withText.length} page(s): text only, no page positions.`,
          pages: ocrWorkspacePages,
          page: ocrWorkspacePage,
        });
      } else {
        $("ocr-message").textContent =
          body.message || "Nothing was read on those pages.";
        $("ocr-message").classList.remove("hidden");
      }
      progress?.done(
        withText.length
          ? `Read ${withText.length} page(s) of ${image.original_name}.`
          : body.message || "Nothing was read."
      );
    } catch (error) {
      //: A read the user stopped is not a failure and must not be reported
      //: as one: `ocrStopRead` has already written the "Stopped." line, and
      //: a red toast on top of it says the app broke when it obeyed.
      if (error?.name === "AbortError") {
        progress?.done("Reading stopped.");
        return;
      }
      $("ocr-message").textContent = error.message || "Those pages could not be read.";
      progress?.done(error.message || "Those pages could not be read.", { isError: true });
    } finally {
      button.disabled = false;
    }
  });

  $("ocr-to-note")?.addEventListener("click", async () => {
    const text = ocrAllText();
    if (!text) return toast("There is nothing to save yet.", true);
    try {
      //: The image goes with the text. A note holding a transcription with no
      //: picture of what was transcribed cannot be checked later, which is
      //: the same failure this whole workspace exists to fix.
      const name = ocrWorkspaceCurrent?.original_name || "image";
      //: **The token must not go in the note.** A caller that opened the
      //: workspace from the lightbox hands over an already-tokened `_src`
      //: (see `ocrLoadPage`), and writing that into a note's markdown would
      //: store this session's auth token in the notebook, and hand it to
      //: anyone the note is later exported or shared with. The query string
      //: is dropped; `mediaSrc` re-adds a live token whenever the note is
      //: rendered.
      //: A PDF page has no stored url of its own, the picture is rendered on
      //: request: so the note points at the page endpoint instead, which
      //: renders the same page again whenever the note is opened.
      const raw = ocrIsPdf(ocrWorkspaceCurrent)
        ? (ocrWorkspaceCurrent._isAttachment
            ? `/files/${ocrWorkspaceCurrent.id}/pdf-page/${ocrWorkspacePage}`
            : `/media/pdf-page/${encodeURIComponent((ocrWorkspaceCurrent.url || "").split("/").pop())}/${ocrWorkspacePage}`)
        : ocrWorkspaceCurrent?.url || (ocrWorkspaceCurrent?._src || "").split("?")[0];
      const picture = raw ? `![${name}](${raw})\n\n` : "";
      const heading = ocrIsPdf(ocrWorkspaceCurrent)
        ? `# Text from ${name}, page ${ocrWorkspacePage + 1}`
        : `# Text from ${name}`;
      const body = `${heading}\n\n${picture}${text}`;
      const created = await apiJson("/entries", {
        method: "POST",
        body: JSON.stringify({ content: body }),
      });
      toast("Saved as a note.");
      $("ocr-workspace").classList.add("hidden");
      flashEntry(created.id);
    } catch (error) {
      toast(error.message || "Couldn't save that note.", true);
    }
  });
});

async function analyseMediaRow(image, kind, payload = {}) {
  if (image._isAttachment) {
    return apiJson(`/files/${image.id}/analyse`, {
      method: "POST",
      body: JSON.stringify({ kind: kind === "vision-ocr" ? "vision" : kind, ...payload }),
    });
  }
  return apiJson(`/media/${image.id}/${kind}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

//: Which gallery tiles are ticked. Media, attachments and sketches live in
//: three different tables, so a selection is keyed by the row's own kind as
//: well as its id, `media:12` and `attachment:12` are different files.
const libraryMediaSelection = new Map();

//: **What the workspace has already read out of a file.**
//:
//: A vision model's reading wins over Tesseract's when both exist: the
//: workspace prefers it everywhere else too (`ocrStoredPageReads`), and a
//: reading list that disagreed with the reader about which text is current
//: would be worse than no list.
function mediaReading(row) {
  return (row?.vision_ocr_text || row?.ocr_text || "").trim();
}

function mediaHasBeenRead(row) {
  return mediaReading(row).length > 0;
}

//: The badge on a file tile. Two states, and the read one carries a number:
//: "Read" alone says a job finished, while "Read · 1,240 words" says what came
//: out of it: which is the thing you are deciding on when you are looking for
//: the scan that actually had the text in it.
function mediaReadingBadge(row) {
  const badge = document.createElement("span");
  const reading = mediaReading(row);
  if (!reading) {
    badge.className = "chip library-read-badge is-unread";
    badge.textContent = "Not read";
    badge.title = "Nothing has been transcribed from this yet";
    return badge;
  }
  const words = reading.split(/\s+/).length;
  badge.className = "chip library-read-badge is-read";
  badge.textContent = `Read · ${words.toLocaleString()} words`;
  badge.title = "Open the reader to see it beside the page";
  return badge;
}

//: **A document's reading, said in one line** (UI_MODERNISATION_PLAN Phase
//: 7.5). Asked for directly, twice: "the card format is difficult with files as
//: they can be quite long and large, a single image or ocr caption doesnt fit
//: them", and then "the files sub-tab has to show more than a row can hold."
//:
//: The row used to render the whole transcription and clamp it, measured on a
//: three-page reading at 1440, the paragraph was cut mid-glyph two lines in,
//: with a "Show more" that turned one row into a wall. A clamped paragraph is
//: the worst of both: too little to read, too much to skim.
//:
//: So: the first sentence, and then the two numbers a person is actually
//: deciding on when they scan this list, how much of the document has been
//: read, and how much text came out of it.
function mediaReadingSummary(row) {
  const reading = mediaReading(row);
  if (!reading) return null;
  const words = reading.split(/\s+/).filter(Boolean).length;
  //: First sentence, or the first line if the reading has no sentence in it, 
  //: a table of figures, a slide title, a scan of a form. Capped, because a
  //: "sentence" in a bad transcription can run for a paragraph, and the cap is
  //: what keeps this to one line at every width.
  const firstLine = reading.split("\n").map((line) => line.trim()).find(Boolean) || reading;
  //: Deliberately not a `[…]+` run anchored at the end, that is the
  //: polynomial-backtracking shape CodeQL has already caught in this repo. A
  //: plain search for the first sentence end, then a slice.
  const stop = firstLine.search(/[.!?](\s|$)/);
  let sentence = stop > 0 ? firstLine.slice(0, stop + 1) : firstLine;
  if (sentence.length > 120) sentence = `${sentence.slice(0, 119).trimEnd()}…`;
  const facts = [];
  //: `pages_read` comes from the server (`_page_read_count_map`), so a
  //: document read page by page can say so. 0 for an image and for a file
  //: whose reading is one whole-file blob, where "pages read" would be a
  //: number about nothing.
  const pages = Number(row?.pages_read) || 0;
  if (pages) facts.push(`${pages} page${pages === 1 ? "" : "s"} read`);
  facts.push(`${words.toLocaleString()} word${words === 1 ? "" : "s"}`);
  return { sentence, facts, words, pages };
}

//: The gallery's rows in the shape `openLightbox` wants.
//:
//: Extracted from the tile's own click handler when Phase 7.5 gave the Files
//: row a second way in ("Open reading"). Two copies of this mapping would be
//: two chances for the two doors to open subtly different dialogs, and the
//: comments below are precisely the kind of hard-won detail that gets copied
//: once and then diverges.
function libraryLightboxItems(images) {
  return images.map((i) => ({
    filename: i.original_name,
    getUrl: () => mediaSrc(i.url),
    // The one caller with a real *MediaUpload* row, so the lightbox's
    // id-gated actions (rename/describe/OCR/delete) only ever appear
    // here: every other caller has a url and nothing else, and a
    // button guaranteed to 404 is worse than no button. `i._isAttachment`
    // (Attachment rows this gallery also lists now, see
    // renderLibraryImagesGallery) is the same case: `i.id` is real,
    // but it names a row in a different table with none of those
    // actions, so it must stay unset here for exactly the reason this
    // comment already gives.
    id: i._isAttachment ? undefined : i.id,
    // Asked for directly: "if clicking on an image to view expand it in
    // the lightbox…can the captions and ocr accompany it somehow??"
    // The tile is the one place these are too small to read.
    caption: i.caption || "",
    text: (i.vision_ocr_text || i.ocr_text || "").trim(),
    byline: i.vision_ocr_text
      ? `Text read by ${shortModelName(i.vision_ocr_model) || "a model"}`
      : i.ocr_text
        ? "Text read with Tesseract OCR"
        : "",
    addedAt: i.created_at || "",
  }));
}

//: The Files row's reading block: one line of it, and the way to the rest.
//: See `mediaReadingSummary` for why a clamped paragraph was the wrong answer.
//: Rows whose whole reading is open; survives the gallery poll re-render.
const openReadings = new Set();

//: **And the fold above it, which had no such memory.** Reported again on
//: 2026-09-09, against both media sub-tabs, after the poll's own signature
//: check had already landed: "the text extracted from this file disclosure
//: closes itself when the reader scrolls to the bottom of the text", and the
//: same for "text in this image" on the Images tab.
//:
//: Measured rather than reasoned. With the disclosure and the reading inside
//: it both open and the list scrolled to 240, a caption written in the
//: background (which is what the six-second poll exists to notice) rebuilt
//: every tile: 9 rebuilds, the inner <details> still open because
//: `openReadings` above remembers it, and the outer one *closed*, because
//: nothing remembered that one at all. The signature check only ever covered
//: the case where nothing changed; a poll that finds a real change still
//: rebuilds, and then the fold a reader is holding open is gone. Six seconds
//: is also about how long it takes to reach the bottom of a page of text,
//: which is why the report reads as "when I scroll to the bottom".
//:
//: Keyed by `mediaRowKey`, not by `image.id`: an `Attachment` and a
//: `MediaUpload` have separate id sequences and both kinds are rendered into
//: this one grid, so `id` alone names two different rows.
const openRowReadings = new Set();

//: How far down its own text each open reading was scrolled. Restoring the
//: fold without this puts the reader back at line 1 of sixty, which is the
//: same complaint one step further in ("it keeps ... scrolling me back to the
//: top"). Written on the reading's own scroll, read back on the next build.
const readingScrollTops = new Map();

function buildFileReadingSummary(image, summary, images) {
  const holder = document.createElement("div");
  holder.className = "library-file-reading";
  if (!summary) {
    //: Not read yet is a state, not an absence, and the offer that goes with
    //: it is "read it", which the row's own strip already carries, so this
    //: says the state and stops.
    const empty = document.createElement("p");
    empty.className = "library-file-summary muted text-sm library-image-ocr-empty";
    empty.textContent = "Nothing has been read from this file yet";
    holder.appendChild(empty);
    return holder;
  }
  const line = document.createElement("p");
  line.className = "library-file-summary";
  line.textContent = summary.sentence;
  //: The whole first line in the tooltip: the summary is clipped to one line
  //: by CSS, and a title is the cheapest way to see the rest without turning
  //: the row into a paragraph again.
  line.title = summary.sentence;
  const meta = document.createElement("p");
  meta.className = "muted text-sm library-file-summary-meta";
  meta.textContent = summary.facts.join("  ·  ");
  const open = document.createElement("button");
  open.type = "button";
  open.className = "ghost small library-file-open-reading";
  setLabel(open, "ph:book-open-text Open reading");
  //: Distinct from the strip's "Open reader" beside it, and the titles have to
  //: say how: this opens the *document* with its reading under it (the
  //: lightbox), that opens the workspace where a page is read, corrected and
  //: re-read. Both were asked for; neither replaces the other.
  open.title = "Open the file with its reading, page by page";
  open.addEventListener("click", (event) => {
    event.stopPropagation();
    //: The same items the tile's own click builds, so both doors open the same
    //: dialog: and `focusReading`, which scrolls the panel under the page
    //: into view and starts on the first page that has a reading. Without it
    //: the reading is below the fold on a tall document, which is the whole
    //: complaint this item is answering.
    openLightbox(libraryLightboxItems(images), images.indexOf(image), { focusReading: true });
  });
  //: The whole reading, in place. Reported directly: "the text extracted
  //: from this file area and dropdown in the library files subtab is
  //: broken, it only shows the first line on the first page extracted". It
  //: was the Phase 7.5 one-line summary working as designed, and the design
  //: was wrong: a person who opens a "Text extracted from this file" field
  //: expects to read the text there, not to be sent to a dialog. The line
  //: stays as the collapsed state; opening it shows every page's reading in
  //: a scrolling box, and "Open reading" still opens the page-by-page view.
  const full = document.createElement("details");
  full.className = "library-file-reading-full";
  // The gallery re-renders on a poll (libraryImagesPollTimer), which rebuilt
  // this element closed while a person was reading it (reported: "it keeps
  // on randomly collapsing, maybe when I scroll to the bottom"). The open
  // state lives outside the element, keyed by the row, so a re-render puts
  // it back exactly as it was.
  full.open = openReadings.has(mediaRowKey(image));
  const fullSummary = document.createElement("summary");
  fullSummary.className = "library-file-reading-more";
  setLabel(fullSummary, "ph:caret-down Show the whole reading");
  const fullText = document.createElement("pre");
  fullText.className = "library-file-reading-text";
  fullText.textContent = mediaReading(image);
  full.append(fullSummary, fullText);
  const syncReadingLabel = () =>
    setLabel(fullSummary, full.open ? "ph:caret-up Hide the reading" : "ph:caret-down Show the whole reading");
  syncReadingLabel();
  full.addEventListener("toggle", () => {
    if (full.open) openReadings.add(mediaRowKey(image));
    else openReadings.delete(mediaRowKey(image));
    syncReadingLabel();
  });
  fullText.addEventListener("scroll", () => {
    readingScrollTops.set(mediaRowKey(image), fullText.scrollTop);
  });
  //: After layout, not now: this element is built before it is in the
  //: document, so it has no scroll height yet and `scrollTop` would be
  //: dropped on the floor. One frame is enough, the tile is appended
  //: synchronously in the same task.
  const savedScroll = readingScrollTops.get(mediaRowKey(image)) || 0;
  if (savedScroll > 0) requestAnimationFrame(() => { fullText.scrollTop = savedScroll; });
  full.addEventListener("click", (event) => event.stopPropagation());
  holder.append(line, meta, full, open);
  return holder;
}

function mediaRowKey(image) {
  const kind = image._isAttachment ? "attachment" : "media";
  return `${kind}:${image.id}`;
}

//: The one place that knows where each kind of row is deleted, so the tile's
//: own Delete and the bulk bar cannot drift apart.
function mediaRowDeleteEndpoint(image) {
  if (image._isAttachment) return `/files/${image.id}`;
  return `/media/${image.id}`;
}

function syncLibraryMediaSelectbar() {
  const bar = document.getElementById("library-media-selectbar");
  const count = document.getElementById("library-media-selected-count");
  if (!bar || !count) return;
  const n = libraryMediaSelection.size;
  bar.classList.toggle("hidden", n === 0);
  count.textContent = `${n} selected`;
}

function clearLibraryMediaSelection() {
  libraryMediaSelection.clear();
  for (const tick of document.querySelectorAll(".library-tile-tick")) tick.checked = false;
  syncLibraryMediaSelectbar();
}

async function bulkDeleteLibraryMedia() {
  const rows = [...libraryMediaSelection.values()];
  if (!rows.length) return;
  const answer = await confirmDialog(
    `Delete ${rows.length} selected item${rows.length === 1 ? "" : "s"}?\n\n` +
      'Any note or board still showing one will show a "deleted" placeholder instead.',
    {
      checkbox: {
        label: "Also remove them from the notes that show them",
        title: "Takes the ![image](…) out of every note that embeds these files. Links to them are left alone.",
        checked: true,
      },
    },
  );
  if (!answer.ok) return;
  for (const image of rows) {
    const endpoint = `${mediaRowDeleteEndpoint(image)}${answer.checked ? "?strip_references=true" : ""}`;
    await apiJson(endpoint, { method: "DELETE" }).catch((err) =>
      toast(err.message, true)
    );
    const idx = libraryImagesCache.indexOf(image);
    if (idx !== -1) libraryImagesCache.splice(idx, 1);
  }
  libraryMediaSelection.clear();
  syncLibraryMediaSelectbar();
  filterLibraryImagesGallery();
  if (answer.checked) loadEntries().catch(() => {});
}

//: `ifUnchanged: "skip"` is the poll's call. Every other caller (a sub-tab
//: click, an upload, a delete, the search box) means "draw this now" and must
//: not be silently skipped: a delete that leaves the tile on screen because
//: the fingerprint had not been refreshed yet would be a far worse bug than
//: the one this fixes.
async function renderLibraryImagesGallery({ ifUnchanged = "render" } = {}) {
  const grid = $("library-images-grid");
  const empty = $("library-images-empty");
  if (!grid) return;
  //: The grid is rebuilt from scratch on every render, so the view class has
  //: to be re-applied with it, the toggle is a property of the list, not of
  //: the tiles that happen to be in it right now.
  applyLibraryMediaView();
  //: The whole gallery, paged out of the server a page at a time (INBOX
  //: 117): the grid's own search filters `libraryImagesCache` in the
  //: browser, so a picture missing from that cache is a picture the search
  //: box can never find, and the tile count would quietly stop at one page.
  const images = await apiPagedList("/media", MEDIA_PAGE_SIZE, { silent: true }).catch(() => null);
  // A note's own attached file (`Attachment`, not `MediaUpload`) never came
  // from `/media` at all: reported directly, twice: "a pdf I uplaoded to a
  // note doesnt show in the libary" and "my uploaded pdf file isnt shown in
  // the library files subtab". `GET /files/gallery` (routes_files.py) is the
  // same rows the note editor's own attachment list already shows, reshaped
  // for this gallery: see its own docstring for why it's a separate,
  // smaller shape rather than pretending an attachment has OCR/captions.
  //
  // `_isImage`/`_isAttachment` are set here, once, rather than making every
  // later call site re-derive them: an attachment's `.url` is `/files/{id}`
  // with no extension (served by id, not by stored filename), so the
  // extension-sniffing `isImageUrl()` below: which is exactly right for a
  // `/media/{name}.ext` row: would silently call every attachment a "file"
  // regardless of its real mime.
  const attachments = await apiJson("/files/gallery", { silent: true }).catch(() => []);
  // **These two loops are load-bearing and were once silently lost.**
  // Reported: "none of the images and sketches are in the images library
  // subtab at all and all the files are in the files subtab", and that is
  // exactly what an unset `_isImage` produces, because the kind filter below
  // reads `!i._isImage` for Files: `undefined` is falsy, so every single row
  // in the notebook satisfied "is a file" and none satisfied "is an image".
  // Nothing threw and nothing logged; the Images tab just rendered its empty
  // state on a notebook full of pictures. The comment above survived the edit
  // that dropped the code it describes, which is the only reason this was
  // findable by reading: so if this ever needs changing again, change both.
  for (const item of images || []) item._isImage = isImageUrl(item.url);
  for (const item of attachments || []) {
    item._isImage = (item.mime || "").startsWith("image/");
    item._isAttachment = true;
    // Never OCR'd, captioned or read by a vision model unless the analyse
    // step has run: explicit empty strings, the same never-null convention
    // `MediaUploadOut` uses, so the search filter and the lightbox can read
    // these without a branch for which kind of row they have.
    item.ocr_text = item.ocr_text || "";
    item.caption = item.caption || "";
    item.vision_ocr_text = item.vision_ocr_text || "";
  }
  libraryImagesCache = [...(images || []), ...(attachments || [])];
  const fingerprint = libraryImagesFingerprint(libraryImagesCache);
  const unchanged = fingerprint === libraryImagesSignature;
  libraryImagesSignature = fingerprint;
  if (unchanged && ifUnchanged === "skip") return;
  if (!images && !attachments?.length) {
    grid.replaceChildren();
    empty?.classList.remove("hidden");
    return;
  }
  filterLibraryImagesGallery();
}

// Filters `libraryImagesCache` against the search box's own value: the
// filename *and* any OCR text found on the image (ROADMAP.md item 30d), so
// "what was on that whiteboard photo from March" is answerable by typing
// a word that was written on it, not just what it happened to be named.
//: **How the media sub-tabs are ordered.** Reported: "the library subtabs are
//: missing sorting and filtering options", and measured, none of the six had
//: a sort control; only the Library's own "All" view did.
//:
//: The comparators live here rather than on the server because the gallery is
//: already fully in memory (`libraryImagesCache`), so sorting is a local
//: reorder with no round-trip and no new endpoint. `created_at` is the field
//: both row shapes carry, a `MediaUpload` and an `Attachment` agree on it
//: even though they agree on very little else, which is why "newest" is the
//: default here as it is everywhere else in the app.
const LIBRARY_MEDIA_SORTS = {
  newest: (a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")),
  oldest: (a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")),
  az: (a, b) =>
    String(a.original_name || "").localeCompare(String(b.original_name || ""), undefined, {
      sensitivity: "base",
    }),
  za: (a, b) =>
    String(b.original_name || "").localeCompare(String(a.original_name || ""), undefined, {
      sensitivity: "base",
    }),
  largest: (a, b) => (Number(b.size_bytes) || 0) - (Number(a.size_bytes) || 0),
};

const LIBRARY_MEDIA_SORT_KEY = "library-media-sort";

function libraryMediaSort() {
  const stored = localStorage.getItem(LIBRARY_MEDIA_SORT_KEY);
  return LIBRARY_MEDIA_SORTS[stored] ? stored : "newest";
}

//: The read filter is *not* stored, unlike the sort. A sort is a preference, 
//: how you like lists arranged, but "show me only what I have not read" is a
//: task you are in the middle of, and a filter that silently persisted across
//: sessions is how a Library comes back next week apparently missing half its
//: files. Same reasoning the notes list uses for its own transient filters.
document.addEventListener("DOMContentLoaded", () => {
  const select = document.getElementById("library-media-sort");
  if (select) {
    select.value = libraryMediaSort();
    select.addEventListener("change", () => {
      localStorage.setItem(LIBRARY_MEDIA_SORT_KEY, select.value);
      filterLibraryImagesGallery();
    });
  }
  document
    .getElementById("library-media-read")
    ?.addEventListener("change", () => filterLibraryImagesGallery());
});

function filterLibraryImagesGallery() {
  const grid = $("library-images-grid");
  const empty = $("library-images-empty");
  const noMatch = $("library-images-no-match");
  if (!grid) return;
  const query = ($("library-images-search")?.value || "").trim().toLowerCase();
  // Kind first, then the search box. Both the "nothing here" and the "nothing
  // matches" states below are about *this* sub-tab, so the count they test
  // has to be the kind-filtered one, otherwise a notebook holding only PDFs
  // would show the Images tab as "no match for your search" with an empty
  // search box.
  const readState = libraryMediaKind === "files" ? $("library-media-read")?.value || "all" : "all";
  const ofKind = libraryImagesCache
    .filter((i) => (libraryMediaKind === "files" ? !i._isImage : i._isImage))
    //: Applied with the kind rather than with the search box, deliberately:
    //: the empty-state copy below distinguishes "nothing in this sub-tab" from
    //: "nothing matches your search", and a read filter is part of *which
    //: files this sub-tab is showing*, not part of the query.
    .filter((i) => {
      if (readState === "read") return mediaHasBeenRead(i);
      if (readState === "unread") return !mediaHasBeenRead(i);
      return true;
    });
  const matched = query
    ? ofKind.filter(
        (i) =>
          (i.original_name || "").toLowerCase().includes(query) ||
          (i.ocr_text || "").toLowerCase().includes(query) ||
          (i.caption || "").toLowerCase().includes(query)
      )
    : ofKind;
  //: Sorted last, on a copy. A copy because `ofKind` can *be*
  //: `libraryImagesCache` when nothing is filtered, and sorting in place would
  //: silently reorder the cache every other reader shares, including the
  //: lightbox's own "N of M" and its prev/next, which index into the array
  //: this function hands them.
  const images = [...matched].sort(LIBRARY_MEDIA_SORTS[libraryMediaSort()]);
  grid.replaceChildren();
  if (!ofKind.length) {
    empty?.classList.remove("hidden");
    noMatch?.classList.add("hidden");
    return;
  }
  empty?.classList.add("hidden");
  noMatch?.classList.toggle("hidden", images.length > 0);
  for (const image of images) {
    const fig = document.createElement("figure");
    fig.className = "library-image-tile";
    // **A PDF is not an image, and rendering one as an <img> is why files
    // "dont appear anywhere".** Reported directly, and this is the whole
    // mechanism: every `/media/upload` row was rendered into an `<img
    // src="/media/…">` regardless of type, so a PDF failed to decode, the
    // `error` handler below fired, and the tile *deleted itself*, silently,
    // with no message, from the only screen that lists uploads at all. The
    // file was on disk and in the database the entire time.
    //
    // The gallery already knew how to open one: the lightbox sniffs a
    // non-image `/media/…` url and hands it to the document viewer. Only the
    // tile was missing, so this gives a non-image its own tile instead of an
    // image that cannot exist.
    // `image._isImage` (set in renderLibraryImagesGallery), not
    // `isImageUrl(image.url)`: an Attachment row's url is `/files/{id}`, 
    // served by id, no file extension at all, so the url-sniffing test
    // that works for a `/media/{name}.ext` row would call every attached
    // PDF a "file" with no icon or label. `mediaFileIcon`/`mediaFileKind`
    // below read `original_name` for the same reason: it carries the real
    // extension on both kinds of row, where the url only does for one.
    const isImage = image._isImage;
    const img = document.createElement(isImage ? "img" : "div");
    if (isImage) {
      img.src = mediaSrc(image.url);
      img.alt = image.original_name;
      img.loading = "lazy";
    } else {
      img.className = "library-file-thumb";
      // **A PDF shows its first page.** Reported: "in the files tab, there
      // is no preview", every non-image tile was a glyph and an extension,
      // which tells you nothing you could not read from the filename. The
      // page renderer already exists for the viewer (`/files/{id}/pdf-page`,
      // `/media/pdf-page/{name}`); this is the same call at thumbnail size.
      // The glyph stays underneath as the fallback for everything without
      // pages, and for a PDF whose render fails.
      if (image.has_pages || /\.pdf$/i.test(image.original_name || "")) {
        const page = document.createElement("img");
        page.className = "library-file-page";
        page.loading = "lazy";
        page.alt = "";
        page.src = mediaSrc(
          image._isAttachment
            ? `/files/${image.id}/pdf-page/0`
            : `/media/pdf-page/${encodeURIComponent((image.url || "").split("/").pop())}/0`
        );
        page.addEventListener("error", () => page.remove());
        img.appendChild(page);
      }
      const glyph = document.createElement("i");
      glyph.className = `ph ${mediaFileIcon(image.original_name)}`;
      glyph.setAttribute("aria-hidden", "true");
      const kind = document.createElement("span");
      kind.className = "library-file-thumb-kind";
      kind.textContent = mediaFileKind(image.original_name);
      img.append(glyph, kind);
      img.setAttribute("role", "img");
      img.setAttribute("aria-label", `${mediaFileKind(image.original_name)}: ${image.original_name}`);
    }
    img.addEventListener("error", () => {
      fig.remove();
      // Every tile's click handler closes over this same `images` array by
      // reference and re-reads it at click time, not a snapshot taken here
      //, so removing the broken entry from it is what every *other* tile's
      // "N of M" and prev/next actually see. Without this, a gallery whose
      // underlying file was deleted from disk (but not from the DB) would
      // hide the broken tile yet still count it: reported live as "it says
      // 1 of 2 when I only have one image" on a gallery with exactly one
      // real tile and one 404ing one.
      const idx = images.indexOf(image);
      if (idx !== -1) images.splice(idx, 1);
    });
    //: **What a click on a row opens**, asked for on 2026-09-09: "I want the
    //: file to be opened in the ocr workspace if I click on the main top part
    //: of the panel and not an element and when I click the file title".
    //:
    //: A picture opens in the lightbox, which is the view that answers "what
    //: is this": a document opens in the OCR workspace, which is the view
    //: that answers the same question about a document, page beside text. A
    //: PDF in a lightbox was always the compromise, and the workspace
    //: rasterises its pages server-side (`_pdf_regions_for`), so there is no
    //: longer a reason to send a document to the image viewer.
    const openThisRow = () => {
      if (image._isImage) openLightbox(libraryLightboxItems(images), images.indexOf(image));
      else openOcrWorkspace(image, images);
    };
    img.addEventListener("click", openThisRow);
    // The tick. Same control the Documents list already uses, so selecting
    // works the same way wherever you are in the Library.
    const tick = document.createElement("input");
    tick.type = "checkbox";
    tick.className = "library-tile-tick";
    tick.checked = libraryMediaSelection.has(mediaRowKey(image));
    tick.setAttribute("aria-label", `Select ${image.original_name}`);
    tick.addEventListener("click", (event) => event.stopPropagation());
    tick.addEventListener("change", () => {
      if (tick.checked) libraryMediaSelection.set(mediaRowKey(image), image);
      else libraryMediaSelection.delete(mediaRowKey(image));
      syncLibraryMediaSelectbar();
    });
    fig.appendChild(tick);

    const del = document.createElement("button");
    del.type = "button";
    del.className = "ghost small icon-button library-image-delete";
    del.title = `Delete “${image.original_name}”`;
    setLabel(del, "ph:trash");
    del.addEventListener("click", async (e) => {
      e.stopPropagation();
      //: **The second question, asked once, in the same dialog.** Reported:
      //: "notes still mention removed images", deleting the file left every
      //: `![](…)` behind, so those notes rendered a "this image was removed"
      //: placeholder for the rest of their lives. Ticked by default because
      //: a reference to a file that no longer exists is not something anyone
      //: keeps on purpose; unticking it keeps the old behaviour exactly.
      const answer = await confirmDialog(
        `Delete "${image.original_name}"?\n\nAny note or board still showing it will show a "deleted" placeholder instead.`,
        {
          checkbox: {
            label: "Also remove it from the notes that show it",
            title: "Takes the ![image](…) out of every note that embeds this file. Links to it are left alone.",
            checked: true,
          },
        },
      );
      if (!answer.ok) return;
      // An Attachment row (image._isAttachment) lives at a completely
      // different id space from MediaUpload, `DELETE /media/{id}` here
      // would either 404 or, worse, delete an unrelated MediaUpload row
      // that happened to share the same numeric id.
      const endpoint = `${mediaRowDeleteEndpoint(image)}${answer.checked ? "?strip_references=true" : ""}`;
      await apiJson(endpoint, { method: "DELETE" }).catch((err) =>
        toast(err.message, true)
      );
      //: The notes on screen are now out of date by exactly the edit the
      //: server just made, so they are refetched rather than left showing a
      //: picture that is gone from both the disk and the note.
      if (answer.checked) loadEntries().catch(() => {});
      libraryMediaSelection.delete(mediaRowKey(image));
      syncLibraryMediaSelectbar();
      const idx = libraryImagesCache.indexOf(image);
      if (idx !== -1) libraryImagesCache.splice(idx, 1);
      filterLibraryImagesGallery();
    });
    // Rename. Reported as simply missing: there was no way to rename an image
    // in the Library at all. The stylesheet already had `.library-image-edit`
    // from an earlier attempt, the CSS shipped and the button that would have
    // used it never did, so the rule sat there styling nothing.
    //
    // Renamed in place rather than through a dialog: a gallery is a wall of
    // captions and the one you are changing should stay where it is, next to
    // the picture it names.
    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "ghost small icon-button library-image-edit";
    rename.title = `Rename “${image.original_name}”`;
    rename.setAttribute("aria-label", `Rename ${image.original_name}`);
    setLabel(rename, "ph:pencil-simple");

    const cap = document.createElement("figcaption");
    cap.textContent = image.original_name;
    cap.title = image._isImage
      ? image.original_name
      : `${image.original_name}\n\nClick to open it page by page, beside the text.`;
    //: The title is the row's name, so it opens the row, the same click the
    //: thumbnail takes. Not while it is being renamed: `rename` replaces the
    //: caption's contents with an `<input>`, and a click into a text field
    //: you are typing in must never navigate away from it.
    cap.addEventListener("click", (event) => {
      if (cap.querySelector("input")) return;
      event.stopPropagation();
      openThisRow();
    });

    rename.addEventListener("click", (event) => {
      event.stopPropagation();
      if (cap.querySelector("input")) return; // already editing
      const box = document.createElement("input");
      box.type = "text";
      box.className = "library-image-rename-input";
      box.value = image.original_name;
      box.setAttribute("aria-label", "New name for this image");
      box.maxLength = 255;
      cap.replaceChildren(box);
      box.focus();
      box.select();

      let settled = false;
      const finish = (text) => {
        if (settled) return;
        settled = true;
        cap.replaceChildren(document.createTextNode(text));
      };
      const cancel = () => finish(image.original_name);
      const save = async () => {
        const next = box.value.trim();
        if (!next || next === image.original_name) return cancel();
        // Optimistic, then corrected: the server is the authority on what a
        // name may contain, and it rejects with a reason worth showing.
        finish(next);
        try {
          //: **An attachment renames too, through its own route.** Reported:
          //: "i cant rename or delete files via a kebab button in the files
          //: subtab." The kebab was there and Delete worked; Rename was
          //: withheld from `Attachment` rows on the reasoning that "an
          //: attachment's name is the note's own file list's business". That
          //: was a judgement about where the name belongs, and the report
          //: overrules it: a file shown in the Library is a file you expect to
          //: manage in the Library.
          //:
          //: Two tables, two routes, and they take different field names, 
          //: `PUT /files/{id}` wants `filename`, `PUT /media/{id}` wants
          //: `original_name`. Both already existed and both already enforce
          //: the workspace and private-note checks; nothing new was needed on
          //: the server.
          const saved = await apiJson(
            image._isAttachment ? `/files/${image.id}` : `/media/${image.id}`,
            {
              method: "PUT",
              body: JSON.stringify(
                image._isAttachment ? { filename: next } : { original_name: next }
              ),
            }
          );
          //: `PUT /files/{id}` answers with the whole note (`EntryOut`), not
          //: the attachment, so the new name is read back from the row rather
          //: than from a field the response does not have.
          const savedName = image._isAttachment
            ? (saved.attachments || []).find((a) => a.id === image.id)?.filename || next
            : saved.original_name;
          image.original_name = savedName;
          cap.replaceChildren(document.createTextNode(savedName));
          img.alt = savedName;
          rename.title = `Rename “${savedName}”`;
          del.title = `Delete “${savedName}”`;
        } catch (error) {
          cap.replaceChildren(document.createTextNode(image.original_name));
          toast(error.message, true);
        }
      };
      box.addEventListener("keydown", (keyEvent) => {
        if (keyEvent.key === "Enter") {
          keyEvent.preventDefault();
          save();
        } else if (keyEvent.key === "Escape") {
          keyEvent.preventDefault();
          cancel();
        }
      });
      // Clicking away commits, which is what every other inline rename in this
      // app does; Escape is the way out.
      box.addEventListener("blur", save);
    });

    // A vision model's own description of the image, distinct from `cap`
    // above (that's the filename: HTML's own <figcaption> naming just
    // collides with what this app calls a "caption"). Asked for directly:
    // written automatically in the background when a vision model is
    // available (routes_files.py's upload trigger), regenerated here only
    // on an explicit click, never silently overwritten.
    const captionBtn = document.createElement("button");
    captionBtn.type = "button";
    captionBtn.className = "ghost small icon-button library-image-caption-btn";
    setLabel(captionBtn, "ph:sparkle");
    // Always visible, even empty, asked for directly ("allow for manual
    // input of image captions"): a click-to-edit field, the same pattern
    // `cap`'s inline rename above already uses, rather than a caption only
    // ever being reachable through the AI-generate button.
    const captionText = document.createElement("p");
    //: No `text-sm`: the size is in `.library-image-caption` now, one rank
    //: rather than three (see that rule). The class was the only thing setting
    //: it, and a utility on the element would beat the rule that has to hold
    //: the card's two sizes together.
    captionText.className = "library-image-caption muted";
    captionText.tabIndex = 0;
    captionText.setAttribute("role", "button");
    // Roughly three lines' worth of this tile's narrow column at text-sm,
    // approximate on purpose, the same way LONG_NOTE_CHARS is: the tile is
    // still `display: none` inside a hidden sub-tab at render time for most
    // gallery loads, so a measured height would read 0 (the trap the Notes
    // list's own long-note comment already names).
    //: Two lines became three when the "Description" heading above it went
    //: (INBOX 56): the label was one of the six ranks of information the card
    //: stacked at one weight, and the paragraph it labelled is the only prose
    //: on the card, so it does not need naming.
    //: **The description has no More button of its own** (INBOX 115: "the
    //: bottom of the image cards ... needs a desperate redesign"). Under one
    //: picture the card stacked four controls at one rank: a More, a "Text in
    //: this image" fold, a chip row and a byline, and a reader cannot tell
    //: which of four affordances holds the thing they are after.
    //:
    //: **And the clamp is unconditional now** (INBOX 118: "still poorly
    //: designed and look unprofessional"). It used to apply past a character
    //: count, 140, which is a guess at a line count and was wrong at every
    //: width: measured on six seeded cards at 1440, the descriptions ran
    //: 1.44, 2.44, 3, 3, 3.44 and 0 lines, and only two of the six were
    //: clamped at all, so no two cards had their text ending in the same
    //: place. A clamp that only sometimes applies is not a clamp; two lines,
    //: always, is a caption. The whole description is one hover away in the
    //: element's own title, one click away in the editor it opens, and in the
    //: lightbox, which has shown the full caption all along.
    const syncCaptionClamp = () => {
      //: Never while it is being edited: the clamp treats its child as flowed
      //: text cut to two lines, and a <textarea> squashed into that box is
      //: what "the caption collapses when I click it" was.
      captionText.classList.toggle(
        "library-image-caption-clamped",
        !captionText.querySelector("textarea"),
      );
    };
    //: **Provenance is one muted line at the foot of the card, not chips.**
    //: Reported (INBOX 56): "chips for provenance that read as actions". Who
    //: described the picture and who read the text out of it were two pills
    //: in the middle of the card, at the same weight and with the same
    //: bordered shape as the "Used in" chips beside them, which *are*
    //: buttons. They are a byline: the smallest type on the card, plain
    //: text, last, where a byline goes. (The ask they came from is still
    //: met: "AI generated image captions should be tagged on the ui and list
    //: what model generated it and if it has been manually modified.")
    //:
    //: Built from `image.*` rather than from arguments, because both setters
    //: write the row first and then call this, and the tile's two readings
    //: change independently.
    const provenance = document.createElement("p");
    provenance.className = "library-image-provenance muted";
    const syncProvenance = () => {
      const parts = [];
      if (image.caption_model) {
        parts.push(
          `Described by ${shortModelName(image.caption_model)}${image.caption_edited ? ", edited by hand" : ""}`
        );
      } else if (image.caption && image.caption_edited) {
        parts.push("Described by hand");
      }
      if (image.vision_ocr_model) parts.push(`read by ${shortModelName(image.vision_ocr_model)}`);
      provenance.textContent = parts.join(" · ");
      provenance.title = [image.caption_model, image.vision_ocr_model].filter(Boolean).join(" · ");
      provenance.classList.toggle("hidden", parts.length === 0);
    };
    //: The section the description lives in, declared here and built further
    //: down with the rest of the card's blocks. `let`, not `const` at the
    //: build site: `setCaptionState` runs long before that point and has to
    //: be able to ask whether there is a section to hide yet, and reading a
    //: `const` before its own line throws rather than answering `undefined`.
    let captionField = null;
    function syncCaptionVisibility() {
      if (!captionField) return;
      captionField.classList.toggle(
        "hidden",
        !(image.caption || "") && !captionText.querySelector("textarea"),
      );
    }
    const setCaptionState = (text, meta = {}) => {
      image.caption = text || "";
      if ("caption_model" in meta) image.caption_model = meta.caption_model || "";
      if ("caption_edited" in meta) image.caption_edited = Boolean(meta.caption_edited);
      captionText.textContent = text || "Add a description";
      captionText.classList.toggle("library-image-caption-empty", !text);
      //: **An empty description is not a row of the card.** Measured before
      //: this (INBOX 115): a card with nothing filled in carried "Not used
      //: yet", an italic "Add a description" and a grey "Text in this image"
      //: fold, three rows that all say nothing is here, inside a tile the
      //: grid stretched to 371.8px whatever it held. The placeholder is not
      //: lost with the row: "Write a description" is a row of the card's
      //: menu, and it opens this field and puts the caret in it.
      syncCaptionVisibility();
      //: The clamp cuts at two lines, so the title is where the rest of it
      //: is, and it is the cheapest place: no control, no row, no height.
      captionText.title = text
        ? `${text}\n\nClick to edit this description`
        : "Click to add a description";
      captionBtn.title = image._isImage
        ? `Describe “${image.original_name}” ${text ? "again " : ""}with AI`
        : `Summarise “${image.original_name}” ${text ? "again " : ""}from its text`;
      captionBtn.setAttribute("aria-label", captionBtn.title);
      syncCaptionClamp();
      syncProvenance();
    };
    setCaptionState(image.caption);
    const startEditingCaption = () => {
      if (captionText.querySelector("textarea")) return; // already editing
      //: Reached from the menu on a card whose description is empty, where
      //: the field is not rendered at all: showing it has to come before
      //: focusing it, or the caret lands in a `display: none` box.
      captionField?.classList.remove("hidden");
      // Reported: the caption visibly collapsed the moment you clicked to
      // edit it. The clamp (-webkit-line-clamp, still on captionText from
      // whatever it was displaying a moment ago) treats its child as flowed
      // text truncated to two lines - a <textarea> squashed into that same
      // ~2-line box is what "collapsed" looked like. Editing shows the
      // whole thing either way, so the clamp has nothing left to do here.
      captionText.classList.remove("library-image-caption-clamped");
      const box = document.createElement("textarea");
      box.className = "library-image-caption-input";
      box.value = image.caption || "";
      box.setAttribute("aria-label", `Caption for "${image.original_name}"`);
      box.maxLength = 2000;
      captionText.replaceChildren(box);
      box.focus();
      box.select();
      // A plain textarea doesn't grow with its content, min-height:3rem
      // is a floor, not the whole box, so anything past ~2 lines scrolled
      // inside a tiny window instead of showing (reported: "collapses when
      // I try to edit it"). autoGrow (app.js) is the app's existing fix for
      // exactly this on every other textarea; it just was never wired here.
      autoGrow(box);
      box.addEventListener("input", () => autoGrow(box));

      let settled = false;
      const finish = (text) => {
        if (settled) return;
        settled = true;
        setCaptionState(text);
      };
      const cancel = () => finish(image.caption);
      const save = async () => {
        const next = box.value.trim();
        if (next === (image.caption || "")) return cancel();
        finish(next); // optimistic, corrected below if the server refuses it
        try {
          const updated = await analyseMediaRow(image, "caption", { text: next });
          setCaptionState(updated.caption, {
            caption_model: updated.caption_model,
            caption_edited: updated.caption_edited,
          });
        } catch (error) {
          setCaptionState(image.caption);
          toast(error.message || "Couldn't save that caption.", true);
        }
      };
      box.addEventListener("keydown", (keyEvent) => {
        if (keyEvent.key === "Enter" && !keyEvent.shiftKey) {
          keyEvent.preventDefault();
          save();
        } else if (keyEvent.key === "Escape") {
          keyEvent.preventDefault();
          cancel();
        }
      });
      box.addEventListener("blur", save);
    };
    captionText.addEventListener("click", startEditingCaption);
    captionText.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        startEditingCaption();
      }
    });

    captionBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      captionBtn.disabled = true;
      // A synchronous route (caption_media runs the model call inline, not
      // in the background), so with nothing shown here the caption text
      // just sat unchanged for however long the model took, asked for
      // directly, a visible "generating" state while one is in flight.
      const previousCaptionText = captionText.textContent;
      captionText.replaceChildren(typingDots("Generating a description…"));
      try {
        // force: true: a manual click is exactly "the user pressed the
        // button to rewrite it", the one case the write-once default
        // (caption_and_store) is meant to defer to.
        const updated = await analyseMediaRow(image, "caption", { force: true });
        setCaptionState(updated.caption, {
          caption_model: updated.caption_model,
          caption_edited: updated.caption_edited,
        });
        //: Reported: "image captioning just straight up didn't work with no
        //: notification, log or anything". The route answers 200 with an
        //: empty caption when no vision model answers, and silence here read
        //: as a dead button. Say so, once, with the likely cause.
        if (!updated.caption) {
          //: Two different missing models, so two different sentences: a
          //: picture is described by the vision model, a document by the
          //: utility model reading its extracted text, and sending someone to
          //: install a vision model for a .docx would be a wrong answer
          //: delivered confidently.
          toast(
            updated.message ||
              (image._isImage
                ? "No description was written. Is a vision model running in Settings > Models?"
                : "No description was written. Check a model is running in Settings > Models."),
            true,
          );
        }
      } catch (error) {
        captionText.textContent = previousCaptionText;
        syncProvenance();
        toast(error.message || "Couldn't generate a caption.", true);
      } finally {
        captionBtn.disabled = false;
      }
    });

    // Tesseract's own reading of any text in the image (core/ocr.py): 
    // local, exact, and (unlike the caption above) not AI-generated, so no
    // model badge. Asked for directly: "allow for manual OCR extraction or
    // retries. allow the user to access, view, and edit OCR extracted
    // text." Same always-visible, click-to-edit shape as captionText above
    //, `POST /media/{id}/ocr` has no write-once guard, so the retry
    // button always re-reads rather than needing a force flag.
    const ocrBtn = document.createElement("button");
    ocrBtn.type = "button";
    ocrBtn.className = "ghost small icon-button library-image-ocr-btn";
    setLabel(ocrBtn, "ph:scan");

    const ocrText = document.createElement("p");
    ocrText.className = "library-image-ocr muted text-sm";
    ocrText.tabIndex = 0;
    ocrText.setAttribute("role", "button");

    // Same clamp/toggle shape as captionText's above.
    const OCR_CLAMP_CHARS = 90;
    const ocrToggle = document.createElement("button");
    ocrToggle.type = "button";
    ocrToggle.className = "entry-more library-image-ocr-more hidden";
    const ocrClamped = () =>
      !libraryExpandedOcr.has(mediaRowKey(image)) && (image.ocr_text || "").length > OCR_CLAMP_CHARS;
    const syncOcrClamp = () => {
      ocrText.classList.toggle("library-image-ocr-clamped", ocrClamped());
      const needsToggle = (image.ocr_text || "").length > OCR_CLAMP_CHARS;
      ocrToggle.classList.toggle("hidden", !needsToggle);
      ocrToggle.textContent = libraryExpandedOcr.has(mediaRowKey(image)) ? "Show less" : "Show more";
    };
    ocrToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      if (libraryExpandedOcr.has(mediaRowKey(image))) libraryExpandedOcr.delete(mediaRowKey(image));
      else libraryExpandedOcr.add(mediaRowKey(image));
      syncOcrClamp();
    });

    const setOcrState = (text) => {
      image.ocr_text = text || "";
      ocrText.textContent = text || "No text found: click to add";
      ocrText.classList.toggle("library-image-ocr-empty", !text);
      ocrText.title = text ? "Click to edit this text" : "Click to add text";
      ocrBtn.title = `Re-read the text in “${image.original_name}” without AI`;
      ocrBtn.setAttribute("aria-label", ocrBtn.title);
      syncOcrClamp();
      // The section around this paragraph decides whether to show itself from
      // the same value. Announced rather than called directly because the
      // wrapper is built further down, after every handler here is closed
      // over: a plain call would be a forward reference to a `const`.
      ocrText.dispatchEvent(new CustomEvent("mm:changed"));
    };
    setOcrState(image.ocr_text);

    const startEditingOcr = () => {
      if (ocrText.querySelector("textarea")) return; // already editing
      // Same reasoning as captionText's own clamp removal above: a <textarea>
      // squashed into a 2-line clamped box reads as "collapsed" while editing.
      ocrText.classList.remove("library-image-ocr-clamped");
      const box = document.createElement("textarea");
      box.className = "library-image-ocr-input";
      box.value = image.ocr_text || "";
      box.setAttribute("aria-label", `Extracted text for "${image.original_name}"`);
      box.maxLength = 10000;
      ocrText.replaceChildren(box);
      box.focus();
      box.select();
      autoGrow(box);
      box.addEventListener("input", () => autoGrow(box));

      let settled = false;
      const finish = (text) => {
        if (settled) return;
        settled = true;
        setOcrState(text);
      };
      const cancel = () => finish(image.ocr_text);
      const save = async () => {
        const next = box.value.trim();
        if (next === (image.ocr_text || "")) return cancel();
        finish(next); // optimistic, corrected below if the server refuses it
        try {
          const updated = await analyseMediaRow(image, "ocr", { text: next });
          setOcrState(updated.ocr_text);
        } catch (error) {
          setOcrState(image.ocr_text);
          toast(error.message || "Couldn't save that text.", true);
        }
      };
      box.addEventListener("keydown", (keyEvent) => {
        if (keyEvent.key === "Enter" && !keyEvent.shiftKey) {
          keyEvent.preventDefault();
          save();
        } else if (keyEvent.key === "Escape") {
          keyEvent.preventDefault();
          cancel();
        }
      });
      box.addEventListener("blur", save);
    };
    ocrText.addEventListener("click", startEditingOcr);
    ocrText.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        startEditingOcr();
      }
    });

    // Reported directly: this button was always enabled, even on a machine
    // without the `tesseract` binary: the one dependency this app never
    // installs on its own (INSTALL.md): so pressing it just silently found
    // nothing, indistinguishable from "read the image and there was no
    // text". `/models/status`'s `tesseract_available` (routes_models.py, a
    // plain `shutil.which` check) is what makes that distinguishable.
    if (modelStatus && modelStatus.tesseract_available === false) {
      ocrBtn.disabled = true;
      ocrBtn.title = "Unavailable: the Tesseract OCR program isn't installed. See INSTALL.md.";
      ocrBtn.setAttribute("aria-label", ocrBtn.title);
    }
    ocrBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      ocrBtn.disabled = true;
      const previousOcrText = ocrText.textContent;
      ocrText.replaceChildren(typingDots("Reading text…"));
      try {
        const updated = await analyseMediaRow(image, "ocr");
        setOcrState(updated.ocr_text);
      } catch (error) {
        ocrText.textContent = previousOcrText;
        toast(error.message || "Couldn't read the text in that image.", true);
      } finally {
        ocrBtn.disabled = modelStatus && modelStatus.tesseract_available === false;
      }
    });

    //: The workspace, beside the re-read button. Two different acts: `ph:scan`
    //: *re-reads* the image and replaces the paragraph below; this *opens*
    //: what was read, region by region, over the page it came from. Offered
    //: for images and for PDFs: a PDF page is rasterised server-side first
    //: (`_pdf_regions_for`), so the one window built for reading documents is
    //: no longer the one window a document cannot be opened in.
    const ocrOpenBtn = document.createElement("button");
    ocrOpenBtn.type = "button";
    ocrOpenBtn.className = "ghost small library-image-menu-item library-image-ocr-open";
    setLabel(ocrOpenBtn, "ph:selection-all See text on the page");
    ocrOpenBtn.title = ocrIsPdf(image)
      ? `Read “${image.original_name}” page by page, beside the page itself`
      : `See where each line sits on “${image.original_name}”`;
    ocrOpenBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      openOcrWorkspace(image, images);
    });

    // A vision model's verbatim transcription of any text in the image, 
    // the "extractor mode" asked for directly, distinct from `ocr_text`
    // (Tesseract, automatic on upload, shown just above) and from
    // `captionText` above (a description, not a transcription). Runs
    // automatically on upload too (ai/vision_ocr.py, same as captioning), 
    // this button is the manual re-read. Unlike the caption there is
    // nothing to prompt someone to type by hand here, so it stays hidden
    // until a read has actually happened (automatic or manual).
    const visionOcrBtn = document.createElement("button");
    visionOcrBtn.type = "button";
    visionOcrBtn.className = "ghost small icon-button library-image-vision-ocr-btn";
    setLabel(visionOcrBtn, "ph:text-aa");

    const visionOcrText = document.createElement("p");
    // Not `hidden` any more, and it is the class that had to go rather than
    // the toggle: `setVisionOcrState` stopped hiding this paragraph when the
    // field became always-editable, but the element was still *born* hidden,
    // so a tile for an image nothing had read rendered the label with nothing
    // under it. Measured, not reasoned about, the field came back 17px tall.
    visionOcrText.className = "library-image-vision-ocr muted text-sm";
    // Editable for the same reason `ocrText` is, and it took a user report to
    // notice this one was not: a vision model transcribing a picture with no
    // text in it does not return nothing, it returns its best guess, the
    // report was four hallucinated Pokémon names under a picture of one, with
    // "no text in it and I cant remove or edit the text??". A *reading* the
    // app cannot correct is worse than no reading, because it is then filed
    // and searched as if it were what the page said.
    visionOcrText.tabIndex = 0;
    visionOcrText.setAttribute("role", "button");


    // Same clamp/toggle shape as captionText's/ocrText's above.
    const VISION_OCR_CLAMP_CHARS = 90;
    const visionOcrToggle = document.createElement("button");
    visionOcrToggle.type = "button";
    visionOcrToggle.className = "entry-more library-image-vision-ocr-more hidden";
    const visionOcrClamped = () =>
      !libraryExpandedVisionOcr.has(mediaRowKey(image)) &&
      (image.vision_ocr_text || "").length > VISION_OCR_CLAMP_CHARS;
    const syncVisionOcrClamp = () => {
      visionOcrText.classList.toggle("library-image-vision-ocr-clamped", visionOcrClamped());
      const needsToggle = (image.vision_ocr_text || "").length > VISION_OCR_CLAMP_CHARS;
      visionOcrToggle.classList.toggle("hidden", !needsToggle);
      visionOcrToggle.textContent = libraryExpandedVisionOcr.has(mediaRowKey(image))
        ? "Show less"
        : "Show more";
    };
    visionOcrToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      if (libraryExpandedVisionOcr.has(mediaRowKey(image))) libraryExpandedVisionOcr.delete(mediaRowKey(image));
      else libraryExpandedVisionOcr.add(mediaRowKey(image));
      syncVisionOcrClamp();
    });

    const setVisionOcrState = (text, model) => {
      image.vision_ocr_text = text || "";
      image.vision_ocr_model = model || "";
      const hasRun = Boolean(model);
      // Always visible, never hidden-until-run: it is the one field on this
      // tile that can be typed into for an image no model has read, and a
      // field you cannot see is a field you cannot use. (It used to hide
      // itself until a read had happened, which left the *offline* OCR
      // empty-state as the only visible "text" box: the mix-up above.)
      visionOcrText.textContent =
        text || (hasRun ? "No legible text found, click to edit" : "No text yet, click to add");
      visionOcrText.classList.toggle("library-image-ocr-empty", !text);
      visionOcrText.title = text ? "Click to edit or clear this reading" : "Click to add text";
      visionOcrBtn.title = hasRun
        ? `Read the text in “${image.original_name}” again`
        : `Read any text in “${image.original_name}” with AI`;
      visionOcrBtn.setAttribute("aria-label", visionOcrBtn.title);
      syncVisionOcrClamp();
      //: "Read by X" used to be a pill of its own here; it is half of the
      //: card's one provenance line now.
      syncProvenance();
      //: The fold's summary line says whether this picture has any text in
      //: it at all, and that line is built further down, after every handler
      //: here has closed over its own state. Announced rather than called,
      //: for the reason `setOcrState`'s own `mm:changed` records.
      visionOcrText.dispatchEvent(new CustomEvent("mm:changed"));
    };
    setVisionOcrState(image.vision_ocr_text, image.vision_ocr_model);

    // Click-to-edit, mirroring `startEditingOcr` above. Clearing the box is
    // the case that matters most and is why the empty string is sent rather
    // than skipped: an empty save clears the model badge too, server-side, so
    // a wrong reading can be deleted outright instead of only overwritten.
    const startEditingVisionOcr = () => {
      if (visionOcrText.querySelector("textarea")) return; // already editing
      visionOcrText.classList.remove("library-image-vision-ocr-clamped");
      const box = document.createElement("textarea");
      box.className = "library-image-ocr-input";
      box.value = image.vision_ocr_text || "";
      box.setAttribute("aria-label", `Text read from “${image.original_name}”`);
      box.maxLength = 10000;
      visionOcrText.replaceChildren(box);
      box.focus();
      box.select();
      autoGrow(box);
      box.addEventListener("input", () => autoGrow(box));

      let settled = false;
      const finish = (text, model) => {
        if (settled) return;
        settled = true;
        setVisionOcrState(text, model);
      };
      const cancel = () => finish(image.vision_ocr_text, image.vision_ocr_model);
      const save = async () => {
        const next = box.value.trim();
        if (next === (image.vision_ocr_text || "")) return cancel();
        const previousText = image.vision_ocr_text;
        const previousModel = image.vision_ocr_model;
        // Emptying it drops the badge with it: "read by <model>" is a claim
        // about text that no longer exists.
        finish(next, next ? previousModel : "");
        try {
          const updated = await analyseMediaRow(image, "vision-ocr", { text: next });
          setVisionOcrState(updated.vision_ocr_text, updated.vision_ocr_model);
        } catch (error) {
          setVisionOcrState(previousText, previousModel);
          toast(error.message || "Couldn't save that text.", true);
        }
      };
      box.addEventListener("keydown", (keyEvent) => {
        if (keyEvent.key === "Enter" && !keyEvent.shiftKey) {
          keyEvent.preventDefault();
          save();
        } else if (keyEvent.key === "Escape") {
          keyEvent.preventDefault();
          cancel();
        }
      });
      box.addEventListener("blur", save);
    };
    visionOcrText.addEventListener("click", startEditingVisionOcr);
    visionOcrText.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        startEditingVisionOcr();
      }
    });

    visionOcrBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      //: Same reason as `ocrBtn`'s: the spinner has to be somewhere visible.
      revealReading();
      visionOcrBtn.disabled = true;
      visionOcrText.replaceChildren(typingDots("Reading text…"));
      try {
        // force: true: a manual click always re-reads, the same "the user
        // pressed the button" reasoning captionBtn's own force:true uses.
        const updated = await analyseMediaRow(image, "vision-ocr", { force: true });
        setVisionOcrState(updated.vision_ocr_text, updated.vision_ocr_model);
      } catch (error) {
        // Restores whatever was there before this click, including
        // re-hiding the box if this was the first-ever attempt and it
        // failed, rather than leaving an empty line visible forever.
        setVisionOcrState(image.vision_ocr_text, image.vision_ocr_model);
        toast(error.message || "Couldn't read the text in that image.", true);
      } finally {
        visionOcrBtn.disabled = false;
      }
    });

    // **One kebab, not five icons.** Reported directly: "it also seems like
    // there are two popup buttons on the images in the image library which do
    // the same thing??", and they nearly did. `ocrBtn` (ph:scan) and
    // `visionOcrBtn` (ph:text-aa) are both "read the text in this image",
    // differing only in *which* reader, which an icon cannot say and a
    // tooltip only says once you have hovered both. A menu row has room for
    // words, so the two readers are told apart by name rather than by glyph.
    //
    //: **And it is the app's own kebab now, not a second implementation of
    //: one.** Reported three times, most recently with two screenshots side
    //: by side: "the images subtab dropdown menus are still different from the
    //: ones in the documents and all subtabs". They were: this menu was a
    //: `<details>` with its own list class, its own outside-click listener,
    //: its own reparent-to-body escape and its own 40-line placement
    //: function, while every other menu in the app is `kebabMenu()`. Two
    //: implementations of one control is exactly how two controls end up
    //: looking different, and no amount of matching the CSS by hand fixes the
    //: next difference. All of that is deleted; the five buttons keep their
    //: handlers and are driven from the shared menu's rows.
    //: **A copy of the file itself.** Asked for as "better function" on the
    //: Files rows (INBOX 115), and it was the one verb a file list has to
    //: have that this one did not: nothing in the Library could get a file
    //: back out of the notebook. The row already knows how to *read* a
    //: document and where it is *used*; it could not hand you the bytes.
    //:
    //: An `<a download>` clicked from script rather than a fetch: the two
    //: routes that serve these bytes already exist and already carry the
    //: right filename (`/files/{id}` answers with
    //: `Content-Disposition: attachment`), and `mediaSrc` puts the token on
    //: the url, which is how every other direct link to media in this app is
    //: authorised. `download` is what makes a `/media/{name}` row (served
    //: `inline`) save rather than open, and it is same-origin, so it is
    //: honoured.
    const save = document.createElement("button");
    save.type = "button";
    save.className = "ghost small icon-button library-image-download";
    save.title = `Save a copy of “${image.original_name}”`;
    save.setAttribute("aria-label", save.title);
    setLabel(save, "ph:download-simple");
    save.addEventListener("click", (event) => {
      event.stopPropagation();
      const link = document.createElement("a");
      link.href = mediaSrc(image._isAttachment ? `/files/${image.id}` : image.url);
      link.download = image.original_name || "file";
      document.body.appendChild(link);
      link.click();
      link.remove();
    });

    //: **The card's own way into the picture at full size.** Reported as the
    //: function half of INBOX 115: the tile opened the lightbox only by a
    //: click on the thumbnail itself, which is a target nobody is told about
    //: and the one target a card full of controls teaches you not to trust.
    //: `openThisRow` is the same call that click makes, so there is still one
    //: decision about what opening this row means.
    //: Where a use goes, and what it looks like, said once. The card's menu
    //: rows and the Files row's chips are two shapes for the same navigation
    //: and they were two copies of this switch.
    const useIcon = (use) =>
      ({ note: "ph:note", document: "ph:file-text", board: "ph:squares-four" })[use.kind] ||
      "ph:link";
    const openUse = (use) => {
      if (use.kind === "note") {
        switchTab("notes");
        flashEntry(use.id);
      } else if (use.kind === "document") {
        switchTab("documents");
        openDocument(use.id);
      } else if (use.kind === "board") {
        openWhiteboardBoard(use.id ?? null);
      }
    };

    const openBtn = document.createElement("button");
    openBtn.type = "button";
    openBtn.className = "ghost small library-image-open";
    openBtn.title = image._isImage
      ? `Open “${image.original_name}” at full size`
      : `Open “${image.original_name}” page by page, beside the text`;
    openBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      openThisRow();
    });

    //: **The reference, not the file.** The other half of "reuse a picture
    //: you already have": the Library could hand you the bytes (Save a copy)
    //: but not the one string that puts the picture into a note, which is
    //: what the notebook actually runs on. Exactly the markdown the editor's
    //: own upload writes (`![name](url)`, app.js), so a pasted reference and
    //: an uploaded one are the same line.
    //:
    //: `MediaUpload` rows only. An `Attachment` is served at `/files/{id}`
    //: and belongs to the note that holds it; handing out a reference to it
    //: would be handing out a link that reads as an embed and is not one.
    const copyRef = document.createElement("button");
    copyRef.type = "button";
    copyRef.className = "ghost small library-image-copy-ref";
    copyRef.title = `Copy the markdown that puts “${image.original_name}” in a note`;
    copyRef.addEventListener("click", async (event) => {
      event.stopPropagation();
      const markdown = `![${image.original_name}](${image.url})`;
      if (await copyToClipboard(markdown)) toast("Markdown reference copied.");
    });

    //: The description's own placeholder used to be a permanent row of every
    //: card (see `syncCaptionVisibility`). This is where that row went: the
    //: capability is the same click-to-edit field, reached by naming it.
    //: **The reading is a row of the card only when there is a reading.** It
    //: used to be a permanent grey "Text in this image" fold on every tile
    //: including the ones nothing had ever read, which is the third of the
    //: three rows INBOX 118 counted as saying nothing. This puts it back when
    //: something is about to land in it, which is the one moment it is
    //: needed. A function declaration, so the click handlers registered above
    //: `fields` can call it once the card is built.
    function revealReading() {
      if (!visionField.isConnected) fields.append(visionField);
      visionField.open = true;
    }

    //: Typing a reading by hand on a picture no reader has touched. The
    //: always-visible empty box this replaces was itself the answer to a
    //: report ("no text in it and I cant remove or edit the text??"), so the
    //: capability is kept exactly and only its permanent row is spent.
    const writeReading = document.createElement("button");
    writeReading.type = "button";
    writeReading.className = "ghost small library-image-write-reading";
    writeReading.title = `Type the text that is in “${image.original_name}” yourself`;
    writeReading.addEventListener("click", (event) => {
      event.stopPropagation();
      revealReading();
      startEditingVisionOcr();
    });

    const writeCaption = document.createElement("button");
    writeCaption.type = "button";
    writeCaption.className = "ghost small library-image-write-caption";
    writeCaption.title = `Type a description of “${image.original_name}” yourself`;
    writeCaption.addEventListener("click", (event) => {
      event.stopPropagation();
      startEditingCaption();
    });

    const menuActions = [
      {
        button: openBtn,
        label: image._isImage ? "ph:arrows-out Open full size" : "ph:book-open-text Open reader",
      },
      ...(image._isAttachment
        ? []
        : [{ button: copyRef, label: "ph:code Copy markdown reference" }]),
      { button: writeCaption, label: "ph:pencil-line Write a description" },
      ...(image._isImage
        ? [{ button: writeReading, label: "ph:keyboard Type the text in this picture" }]
        : []),
      { button: rename, label: "ph:pencil-simple Rename" },
      { button: save, label: "ph:download-simple Save a copy" },
      { button: captionBtn, label: "ph:sparkle Describe with AI" },
      { button: visionOcrBtn, label: "ph:text-aa Read text with AI" },
      //: Left out entirely, not greyed, when the binary is missing, the
      //: lightbox menu (app.js) does the same, for the same report: "make
      //: sure all the fila and document ocr worfs with ai ocr models, I dont
      //: use tesseract." This app never installs that binary (by
      //: instruction), so a disabled row here can never become enabled.
      ...(modelStatus && modelStatus.tesseract_available === false
        ? []
        : [{ button: ocrBtn, label: "ph:scan Read text (Tesseract OCR)" }]),
      //: Images and PDFs. Tesseract cannot open a PDF, but the workspace no
      //: longer needs it to: `_pdf_regions_for` (routes_files.py) rasterises
      //: the page first and the workspace reads it with the vision model,
      //: which is what *"is the document ocr even working??"* was about.
      ...(image._isImage || ocrIsPdf(image)
        ? [{ button: ocrOpenBtn, label: "ph:selection-all See text on the page" }]
        : []),
      //: **Every place this picture is used, by name.** Reported as the gap
      //: in INBOX 115 ("no way to see which notes use it beyond one chip")
      //: and sharpened by 118: where a file is used is a count you read at a
      //: glance, not a row of chips the card pays for. The count stays on the
      //: card as one line of plain text; the places themselves are rows of
      //: the menu the card already has, which costs the card nothing at rest
      //: and lifts the old four-chip cap at the same time.
      ...(Array.isArray(image.used_by) ? image.used_by : []).slice(0, 6).map((use) => {
        const go = document.createElement("button");
        go.type = "button";
        go.className = "ghost small library-image-goto";
        go.title = `Open the ${use.kind} this file is used in`;
        go.addEventListener("click", (event) => {
          event.stopPropagation();
          openUse(use);
        });
        return { button: go, label: `${useIcon(use)} Go to “${use.label}”` };
      }),
      { button: del, label: "ph:trash Delete", danger: true },
    ];
    //: The row of controls the kebab lives in. Declared here because the
    //: `<details>` version this replaced created it a few lines further down,
    //: and taking that block out took the declaration with it.
    const actions = document.createElement("div");
    actions.className = "library-image-actions";
    const menu = kebabMenu(
      menuActions.map(({ button, label, danger }) => ({
        label,
        title: button.title,
        //: The button's own disabled state carries through as the menu row's
        //: muted state: `ocrBtn` is disabled when Tesseract is missing, and a
        //: row that looks live and does nothing is worse than one that says so.
        disabled: button.disabled,
        danger,
        //: `run` clicks the original button, so its handler, rename's inline
        //: field, the two readers' spinners, delete's confirm: is still the
        //: one thing that decides what happens.
        run: () => button.click(),
      })),
      `More actions for “${image.original_name}”`,
    );
    actions.append(menu);

    // **Labelled, and separated.** Reported directly: "I feel the image
    // captions and ocr extractions should be separated and labeled, for the
    // ocr, it says 'No text found - click to add' but the extracted text is
    // below that selectable box and not editable??", which is exactly what
    // an unlabelled stack of three paragraphs produces. What the reader saw
    // was one field's empty-state sitting directly above another field's
    // filled value, with nothing to say they were different fields at all.
    //
    // A description and a transcription are different claims about a picture
    // and are now named as such. `library-image-field` is one block per
    // claim: a small label, the (editable) value, and the byline saying who
    // produced it.
    const field = (labelText, ...children) => {
      const section = document.createElement("section");
      section.className = "library-image-field";
      const label = document.createElement("h4");
      label.className = "library-image-field-label";
      label.textContent = labelText;
      section.append(label, ...children);
      return section;
    };

    //: **The description is the card's paragraph, not a labelled field.**
    //: It keeps the section box (the click-to-edit paragraph and its More
    //: toggle belong together) and loses the "Description" heading: with the
    //: filename now on the picture and the readings folded away, this is the
    //: only prose left on the card and nothing else could be mistaken for it.
    captionField = document.createElement("section");
    captionField.className = "library-image-field library-image-describe";
    captionField.append(captionText);
    syncCaptionVisibility();
    //: A PDF is not an image, and the heading said so anyway. Reported: "in
    //: the files tab, the ocr heading still says 'text in this image' when it
    //: should probably say something like 'extracted text from file'".
    //: `_isImage` is already set for every row by the gallery loader.
    //: **A file's reading is a summary and a way in, not a clamped
    //: paragraph** (UI_MODERNISATION_PLAN Phase 7.5). Asked for directly: "the
    //: card format is difficult with files as they can be quite long and
    //: large, a single image or ocr caption doesnt fit them."
    //:
    //: An image keeps the editable, always-visible box: a photo's reading is a
    //: line or two, correcting it in place is the whole point, and there is no
    //: "page 3" to open. A document gets the one-line summary
    //: (`mediaReadingSummary`) and an action that opens it where the reading
    //: can actually be read, the lightbox, page beside text. Correcting a
    //: document's reading was never really possible in a two-line clamp
    //: anyway; the workspace edits it per page, which is where it belongs.
    const summary = image._isImage ? null : mediaReadingSummary(image);
    //: **Folded away, under one disclosure.** A transcription is the thing
    //: you go looking for, not the thing you are shown: two clamped
    //: paragraphs of it, each with its own label and its own Show more,
    //: were four of the card's six ranks of information (INBOX 56). Closed
    //: by default, and the app's own <details> recipe (details.tool-chip,
    //: 02-chat-graph.css) so the marker and the caret read the same here as
    //: in the chat transcript.
    const visionField = document.createElement("details");
    visionField.className = "library-image-reading";
    //: Open across a rebuild, for the reason at `openRowReadings`.
    visionField.open = openRowReadings.has(mediaRowKey(image));
    visionField.addEventListener("toggle", () => {
      if (visionField.open) openRowReadings.add(mediaRowKey(image));
      else openRowReadings.delete(mediaRowKey(image));
    });
    const readingSummary = document.createElement("summary");
    //: **One control, one question** (INBOX 118: the fold "puts two unrelated
    //: facts in one control ... one of them is not a disclosure at all"). It
    //: said "Used in 1 place · text found" for one revision, which is where
    //: the file is *and* what is in it under a single caret. Where it is used
    //: is a count, and a count is a line of text; this is the fold, and a
    //: fold says what is folded.
    //: **On a card the label is one word, because it has to fit beside the
    //: count.** The two facts share a line now (`.library-image-meta`), and a
    //: 180px tile leaves 161px for it: "Used in 2 places" is 85px of that and
    //: "Text in this image" is a 128.8px chip, so the pair wrapped onto two
    //: lines and the cards with a reading stood 38px taller inside than the
    //: cards without, which is the unevenness the report is about. "Text" and
    //: its caret are 58px, the pair is 149px, and every card in the gallery
    //: then has the same two ranks whatever is in it. The full phrase is on the
    //: control's own tooltip and is still the heading inside the fold, where
    //: the reading it names is.
    readingSummary.textContent = image._isImage ? "Text" : "Text extracted from this file";
    if (image._isImage) {
      visionField.classList.add("library-image-card-fold");
      readingSummary.title = "Text found in this image";
    }
    const readingBody = document.createElement("div");
    readingBody.className = "library-image-reading-body";
    //: **The label moves inside the fold with the paragraph it names.** On an
    //: image card the summary line above is now a line of facts about the
    //: picture rather than the word "Text in this image", so the reading
    //: needs its own name again once the fold is open, next to Tesseract's,
    //: which has always had one. At rest neither label is on the card.
    if (image._isImage) readingBody.append(field("Text in this image", visionOcrText, visionOcrToggle));
    else readingBody.append(buildFileReadingSummary(image, summary, images));
    visionField.append(readingSummary, readingBody);
    // The Tesseract reading is shown only when it actually found something.
    // Tesseract is a system binary this app never installs on its own (by
    // instruction, and `tesseract_available` in /models/status now says so
    // up front rather than after a click), so on most machines it is
    // permanently empty, and an empty second "no text found" box under a
    // filled one is the confusion this whole block exists to remove.
    // Reachable regardless from the kebab menu.
    //: Tesseract's reading goes inside the same disclosure, under the vision
    //: one: it is the same question ("what does this say"), answered by the
    //: other reader, and a second top-level box asking it again is what made
    //: the card read as a form.
    const ocrField = field("Also read with Tesseract OCR", ocrText, ocrToggle);
    const syncOcrFieldVisibility = () =>
      ocrField.classList.toggle("hidden", !(image.ocr_text || "").trim());
    syncOcrFieldVisibility();
    ocrText.addEventListener("mm:changed", syncOcrFieldVisibility);
    // Running it from the menu reveals the field, so the result has somewhere
    // to appear even when the run finds nothing and says so.
    ocrBtn.addEventListener("click", () => {
      ocrField.classList.remove("hidden");
      //: The field lives inside the fold now, so revealing it is not enough:
      //: a result that lands in a closed <details> is a button that looks
      //: like it did nothing. And on an image card the fold itself is only on
      //: the card once there is a reading, so it has to be put back first.
      revealReading();
    });

    readingBody.appendChild(ocrField);
    const fields = document.createElement("div");
    fields.className = "library-image-fields";
    fields.append(captionField, visionField);

    // **Where this file is actually used.** Asked for as the Files tab being
    // "properly integrated" rather than just redesigned, and it was the one
    // question the gallery could not answer. A card showed a thumbnail, a
    // filename and two empty prompts, so a wall of sixty uploads told you
    // nothing about what any of them were for, and getting from a file to the
    // note it belongs to meant searching for it by name.
    //
    // Each chip opens the thing that references the file, so the gallery is a
    // way *into* the notebook rather than a dead end. Server-side
    // (`media_gc.usage_map`), built from the same `referenced_names` the
    // orphan collector uses: if the two disagreed, a file this called "used"
    // could be one the collector deletes.
    const usage = document.createElement("div");
    usage.className = "library-image-usage";
    const links = Array.isArray(image.used_by) ? image.used_by : [];
    //: **The same fact, said once per layout.** A Files row reads left to
    //: right and says "Used in" before its chips. An image card says the
    //: count in its fold's own summary line and keeps the chips inside the
    //: fold, so repeating the lead-in there would be the card saying the same
    //: thing twice, which is the shape INBOX 115 is about.
    //:
    //: The cap goes with it: four chips is what one line of a Files row can
    //: hold, and an image card's chips are behind a disclosure, where the
    //: length costs nothing at rest. Reported as the gap: "no way to see
    //: which notes use it beyond one chip".
    const usageShown = image._isImage ? links : links.slice(0, 4);
    const usageFact = links.length
      ? (links.length === 1 ? "Used in 1 place" : `Used in ${links.length} places`)
      : image.usage_incomplete
        ? "Usage unknown"
        : "Not used yet";
    if (links.length) {
      if (!image._isImage) {
        const lead = document.createElement("span");
        lead.className = "muted text-sm library-image-usage-lead";
        lead.textContent = links.length === 1 ? "Used in" : `Used in ${links.length} places`;
        usage.appendChild(lead);
      }
      for (const use of usageShown) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip chip-interactive library-image-usage-chip";
        const icon = { note: "ph:note", document: "ph:file-text", board: "ph:squares-four" }[use.kind] || "ph:link";
        setLabel(chip, `${icon} ${use.label}`);
        chip.title = `Open the ${use.kind} this file is used in`;
        chip.addEventListener("click", (event) => {
          event.stopPropagation();
          if (use.kind === "note") {
            switchTab("notes");
            flashEntry(use.id);
          } else if (use.kind === "document") {
            switchTab("documents");
            openDocument(use.id);
          } else if (use.kind === "board") {
            openWhiteboardBoard(use.id ?? null);
          }
        });
        usage.appendChild(chip);
      }
      if (links.length > usageShown.length) {
        const more = document.createElement("span");
        more.className = "muted text-sm";
        more.textContent = `+${links.length - usageShown.length} more`;
        usage.appendChild(more);
      }
    } else if (image.usage_incomplete) {
      // Not the same claim as "unused", and the difference matters: a locked
      // private note could not be read, so this file may well be in use.
      // Saying "not used anywhere" here would invite deleting something live.
      //: The image card says "Usage unknown" in its summary line and spells
      //: out why here, where there is room for the sentence.
      const note = document.createElement("span");
      note.className = "muted text-sm";
      note.textContent = "Usage unknown: a locked private note could not be checked";
      usage.appendChild(note);
    } else if (!image._isImage) {
      const note = document.createElement("span");
      note.className = "muted text-sm";
      //: One line, and the shortest true one: the card says where the file is
      //: used or that it is not, and "in any note, document or board" spent a
      //: whole line of a 180px card restating the three places it looked.
      note.textContent = "Not used yet";
      usage.appendChild(note);
    }

    // `fields` (caption/vision-OCR/Tesseract-OCR boxes) is skipped entirely
    // for an attachment tile, not just emptied, each of those is a
    // click-to-edit control that saves through `/media/{id}/...` (see the
    // menuList comment above for why that id doesn't belong to this row),
    // and a caption box that looks editable but silently 404s on save is
    // worse than a tile with no caption box at all.
    //: **The reading strip: the Files sub-tab's whole reason to look
    //: different from the Images one.** Asked for directly: "because the ocr
    //: worspace exists, redesign the files library subtab and its
    //: capabilities." The workspace is where a document gets read; this list
    //: could not say which ones already had been, so every scan looked the
    //: same as every other and the only way to find out was to open each one.
    //:
    //: Files only. An image "read" or "not read" is a statement about whether
    //: OCR happened to have run, which is not a thing anybody is looking for
    //: when they are browsing pictures.
    if (!image._isImage) {
      const strip = document.createElement("div");
      strip.className = "row library-read-strip";
      strip.appendChild(mediaReadingBadge(image));
      const read = document.createElement("button");
      read.type = "button";
      read.className = "ghost small library-read-open";
      //: The label follows the state, because "Read" on something already read
      //: reads as a claim about the file rather than as an invitation.
      setLabel(
        read,
        mediaHasBeenRead(image) ? "ph:book-open-text Open reader" : "ph:scan Read this"
      );
      read.title = mediaHasBeenRead(image)
        ? "Open it in the reader, beside what was found"
        : "Open the reader and transcribe it";
      //: A *primary* control on the tile rather than a row in the kebab. The
      //: workspace only became worth putting a front door on once it could
      //: find its own siblings, before that, opening it from here was a dead
      //: end you had to close to get anywhere.
      read.addEventListener("click", (event) => {
        event.stopPropagation();
        openOcrWorkspace(image, libraryImagesCache);
      });
      strip.appendChild(read);
      //: **One line of facts, not three stacked blocks** (INBOX 115: "the
      //: files rows in files still needs some ui improvement and redesign").
      //: Measured at 1440 before this: the text column is 1218px wide and
      //: held five full-width blocks each carrying one short string, so a
      //: single row stood 257px tall and four files filled the window. The
      //: three muted ones, what the file is, whether it has been read, and
      //: where it is used, are all short statements of fact about the same
      //: file and read as one line; only the name above them and the
      //: description below are their own rank. Wrapping, so a narrow window
      //: gets the old stack back rather than a clipped row.
      const facts = document.createElement("div");
      facts.className = "library-file-facts";
      facts.append(fileMetaLine(image), strip, usage);
      fig.append(img, actions, cap, facts, fields, provenance);
      grid.appendChild(fig);
      continue;
    }
    //: **The filename sits on the picture, not under it.** An image card is
    //: a picture and what is known about it; the name is what the picture is
    //: called, so it belongs to the picture (INBOX 56). A scrim behind it
    //: keeps it legible over a light photograph without a second surface.
    //: Files (the rows layout above) keep the name as a sibling: that layout
    //: puts the thumbnail out of flow and lays the text out beside it.
    const frame = document.createElement("div");
    frame.className = "library-image-frame";
    frame.append(img, cap);

    //: **The bottom of an image card is a caption, not a form** (INBOX 115:
    //: "the bottom of the image cards in the library images subsaection needs
    //: a desperate redesign and funection").
    //:
    //: Measured before this at 1440x900, three cards seeded full, half and
    //: empty: every card was 371.8px tall whatever it held, the picture was
    //: 144px of that (38.7%) and 226.8px sat under it in four stacked blocks,
    //: three of which said nothing at all on the empty card ("Not used yet",
    //: "Add a description", "Text in this image"). A gallery of twenty cards
    //: carried around two hundred controls.
    //:
    //: What the card says at rest is now what the card is: the picture, its
    //: name on the picture, and the description of what is in it. Everything
    //: else, where the file is used, what text is in it, and who wrote both,
    //: is behind the one disclosure whose summary line is itself the answer
    //: to "should I care about this one": how many places use it, and whether
    //: there is any text in it.
    //: **The count, as a line of text, only where there is a count.** Not a
    //: control: nothing opens, nothing toggles, so nothing invites a click
    //: that would do nothing. Where the places themselves are is in the
    //: card's menu, a row each. A picture nothing uses says nothing, which is
    //: the difference between a short card and a padded one: "Not used yet"
    //: was a permanent row on the emptiest card in the gallery.
    const uses = document.createElement("p");
    //: `text-xs`, because a fact about a picture is not the picture's words:
    //: unstyled, this paragraph rendered at 16px with 16px of user-agent
    //: margin either side of it, over a 12px description. It is the smallest
    //: type on the card now, which is the rank it holds.
    uses.className = "library-image-uses muted text-xs";
    uses.textContent = usageFact;
    uses.title =
      links.length
        ? "Open the card's menu to go to any of them"
        : "This picture is not in any note, document or board";

    //: The byline goes with the reading, inside the fold. "Described by X,
    //: read by Y" is a claim about where the card's words came from, not one
    //: of the card's words, and it was two lines of model names on the
    //: outside of every tile (INBOX 56, and again in the second design batch,
    //: both times called noise). When there is no reading there is no fold,
    //: and then the card does not carry it at all: the lightbox has shown
    //: both bylines under the picture since long before this.
    readingBody.append(provenance);

    //: **What the bottom of the card is: the prose, then one line of facts.**
    //: Reported a third time, 2026-09-13: "redesign the bottom text area of the
    //: image cards in the library images subtab again", with the block reading
    //: as "four unrelated rows of different weights". It was four: the filename
    //: on the picture, the description, the count on its own row, and the fold
    //: on a third. Measured at 1440 dark on the six seeded cards, the three
    //: rows under the picture stood 38.4px, 16.8px and 31.6px tall at three
    //: type sizes two pixels apart (13.6 / 12 / 11.2), and the number of rows
    //: differed from card to card, so the foot ran 9.6px to 115.5px across one
    //: gallery row.
    //:
    //: Two ranks now, and the decision the plan records ("a fact is a line of
    //: text, a disclosure is a control, and neither is the other") is kept:
    //: they are still two objects, one you read and one you press, they simply
    //: share a line, the way the Files rows' own facts line already puts the
    //: kind, the reading and the usage on one (`.library-file-meta`). One
    //: control holding both facts is what INBOX 118 called unprofessional, and
    //: that is not what this is.
    //:
    //: `fields` was built above for the Files rows, which stack the same two
    //: blocks unconditionally; an image card composes its own.
    fields.replaceChildren(captionField);
    const metaRow = document.createElement("div");
    //: The shared class plus a handle of its own, which is how all three of
    //: the Library's facts lines are built (`metaLine` above does the same for
    //: the Files rows and the saved links): the rank comes from the one rule,
    //: the handle carries only what this layout needs.
    metaRow.className = "library-file-meta library-image-meta";
    if (links.length || image.usage_incomplete) metaRow.append(uses);
    if ((image.vision_ocr_text || "").trim() || (image.ocr_text || "").trim()) {
      metaRow.append(visionField);
    }
    //: Nothing to say, no line: a picture nobody has used and nothing has read
    //: keeps the short foot it has now rather than an empty row holding the
    //: rhythm open.
    if (metaRow.children.length) fields.append(metaRow);

    fig.append(frame, actions, fields);
    grid.appendChild(fig);
  }
}

// The Library's own sub-tab switcher, plus the Documents/Media sub-tabs'
// refresh, search and upload controls, moved here from whiteboard.js's
// DOMContentLoaded listener (see this file's header). Still wrapped in its
// own DOMContentLoaded, matching where it came from; every other file in
// this split registers its top-level listeners as bare statements instead
// (safe because every <script> here loads after body content), but there
// was no reason to change that shape while moving it.
document.addEventListener("DOMContentLoaded", () => {
  const librarySubtabs = document.getElementById("library-subtabs");
  if (librarySubtabs) {
    const buttons = librarySubtabs.querySelectorAll("button");
    // "library-view-documents" is the *All* view, it kept its id when it was
    // renamed, because the id is referenced from several places and a rename
    // buys nothing. "library-view-docs" is the new documents-only section.
    // "library-view-drafts" is gone: drafts became a chip in the All view's
    // filter row (see LIBRARY_KINDS in app.js and _drafts() in
    // routes_library.py).
    const sections = [
      "library-view-documents", "library-view-docs", "library-view-skills",
      "library-view-whiteboard", "library-view-media", "library-view-links",
      "library-view-contents",
    ];

    buttons.forEach(btn => {
      btn.addEventListener("click", () => {
        buttons.forEach(b => {
          b.classList.remove("active");
          b.setAttribute("aria-selected", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-selected", "true");

        const targetId = btn.getAttribute("data-target");
        // Same {tab, section} shape showNotesSection already records, 
        // ROADMAP.md §88.1 item 7 / live-list item 13: Library's own
        // sub-tabs were the one gap in "back/forward handles sub-tabs too"
        // that was already scoped and located, not newly discovered here.
        if (typeof recordTabVisit === "function") recordTabVisit("library", targetId);
        sections.forEach(id => {
          const el = document.getElementById(id);
          if (el) {
            if (id === targetId) {
              el.classList.remove("hidden");
            } else {
              el.classList.add("hidden");
            }
          }
        });

        if (targetId === "library-view-media") {
          setLibraryMediaKind(btn.dataset.mediaKind);
          renderLibraryImagesGallery();
          startLibraryImagesPoll();
        } else {
          stopLibraryImagesPoll();
          if (targetId === "library-view-whiteboard") {
            // Lands on the boards gallery, not straight onto a canvas, one
            // door onto the whiteboard, asked for directly, replacing the
            // old always-opens-the-last-board behaviour.
            wbShowBoardsLanding();
          } else if (targetId === "library-view-docs") {
            renderLibraryDocuments();
          } else if (targetId === "library-view-skills") {
            // Here rather than in a `switchTab` wrapper: these are two
            // network-backed renders and they belong to *this* sub-tab, not
            // to every visit to the Library.
            renderSkillsDashboard();
            renderSkillLogs();
          } else if (targetId === "library-view-links") {
            renderBookmarks();
          } else if (targetId === "library-view-contents") {
            renderContents();
          }
        }
      });
    });
  }
  $("library-images-refresh")?.addEventListener("click", renderLibraryImagesGallery);
  $("library-media-bulk-delete")?.addEventListener("click", bulkDeleteLibraryMedia);
  $("library-media-clear-selection")?.addEventListener("click", clearLibraryMediaSelection);
  $("library-images-search")?.addEventListener("input", filterLibraryImagesGallery);
  $("library-docs-refresh")?.addEventListener("click", renderLibraryDocuments);
  $("library-docs-new")?.addEventListener("click", async () => {
    const doc = await createDocumentNamed();
    // switchTab first, then open, the same fix openDoc() above needed
    // ("the documents subtab document cards don't even do anything"): the
    // document was created and loaded into the editor correctly, but the
    // Documents page stayed hidden behind the Library tab, so nothing
    // seemed to happen.
    if (doc) {
      switchTab("documents");
      openDocument(doc.id);
    }
  });
  // Filter as you type. No debounce: the list is already in memory after the
  // first fetch and re-rendering it is cheap, unlike the semantic searches
  // elsewhere that a debounce exists to protect.
  $("library-docs-search")?.addEventListener("input", () => {
    libraryDocsCurrentPage = 1; // a new search can move a document off whatever page it was on
    renderLibraryDocuments();
  });
  const docsPageSizeSelect = $("library-docs-page-size");
  if (docsPageSizeSelect) {
    docsPageSizeSelect.value = libraryDocsPageSize;
    docsPageSizeSelect.addEventListener("change", (e) => {
      libraryDocsPageSize = e.target.value;
      localStorage.setItem("library-docs-page-size", libraryDocsPageSize);
      libraryDocsCurrentPage = 1;
      renderLibraryDocuments();
    });
  }
  $("library-docs-page-prev")?.addEventListener("click", () => {
    if (libraryDocsCurrentPage <= 1) return;
    libraryDocsCurrentPage -= 1;
    renderLibraryDocuments();
  });
  $("library-docs-page-next")?.addEventListener("click", () => {
    libraryDocsCurrentPage += 1; // clamped back down inside renderLibraryDocuments if this overshoots
    renderLibraryDocuments();
  });
  const libraryPageSizeSelect = $("library-page-size");
  if (libraryPageSizeSelect) {
    libraryPageSizeSelect.value = libraryPageSize;
    libraryPageSizeSelect.addEventListener("change", (e) => {
      libraryPageSize = e.target.value;
      localStorage.setItem("library-page-size", libraryPageSize);
      libraryCurrentPage = 1;
      renderLibrary();
    });
  }
  $("library-page-prev")?.addEventListener("click", () => {
    if (libraryCurrentPage <= 1) return;
    libraryCurrentPage -= 1;
    renderLibrary();
  });
  $("library-page-next")?.addEventListener("click", () => {
    libraryCurrentPage += 1; // clamped back down inside renderLibrary if this overshoots
    renderLibrary();
  });
  $("library-images-upload")?.addEventListener("click", () => $("library-images-upload-input").click());
  $("library-images-upload-input")?.addEventListener("change", async (event) => {
    const input = event.target;
    const files = [...input.files];
    input.value = ""; // so picking the same file twice still fires "change"
    if (!files.length) return;
    let uploaded = 0;
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      // Asked for directly: OCR/captioning/vision-OCR must not run on a
      // staged upload that never gets saved into a note, document or sent
      // chat message: but the Library's own "Upload images" button has no
      // separate staging step at all, so this upload IS the commit
      // (routes_files.py's upload_media, and core/media_process.py's own
      // docstring, name this exact case).
      form.append("direct", "true");
      try {
        // A bare headers override, not apiJson's default: a FormData body
        // needs the browser to set its own multipart boundary in
        // Content-Type; apiJson's own "application/json" default would
        // fight it (the same fix handleFileUpload's upload already needed).
        //: **X-Workspace-ID alongside the token, and it is not decoration.**
        //: A new row takes its space from `session.info["workspace_id"]`
        //: (core/database.py's before-flush hook), which is set from this
        //: header, so an upload sent without it is written with the model
        //: default, "default". Measured: the same upload lands in `space-b`
        //: with the header and in `default` without it, which means a picture
        //: added while working in a space vanished from that space's Library
        //: the moment it was uploaded. `apiJson` adds this header to every
        //: call it makes; a hand-rolled fetch has to add it itself, and the
        //: lint that was supposed to catch that only read app.js.
        const response = await fetch("/media/upload", {
          method: "POST",
          headers: { "X-Auth-Token": authToken(), "X-Workspace-ID": activeSpaceId() },
          body: form,
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || `Upload failed (${response.status})`);
        uploaded++;
      } catch (error) {
        toast(`${file.name}: ${error.message}`, true);
      }
    }
    if (uploaded > 0) {
      toast(uploaded === 1 ? "Uploaded." : `Uploaded ${uploaded} files.`);
      renderLibraryImagesGallery();
    }
  });
  $("bookmark-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const urlInput = $("bookmark-url-input");
    const titleInput = $("bookmark-title-input");
    const groupInput = $("bookmark-group-input");
    const url = urlInput.value.trim();
    if (!url) return;
    try {
      const created = await apiJson("/bookmarks", {
        method: "POST",
        body: JSON.stringify({
          url, title: titleInput.value.trim(), group_name: groupInput.value.trim(),
        }),
      });
      urlInput.value = "";
      titleInput.value = "";
      groupInput.value = "";
      urlInput.focus();
      if (created.duplicate_of) {
        toast(`Saved: you already had this link (${created.title || created.url}).`);
      }
      renderBookmarks();
    } catch (error) {
      toast(error.message, true);
    }
  });
  $("bookmark-search")?.addEventListener("input", filterBookmarks);
  $("bookmark-group-new")?.addEventListener("click", newBookmarkGroup);
  $("bookmark-group-manage")?.addEventListener("click", manageBookmarkGroups);
  $("contents-refresh")?.addEventListener("click", renderContents);
  $("contents-mode")?.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("contents-mode").querySelectorAll("button").forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      contentsMode = btn.getAttribute("data-mode");
      renderContents();
    });
  });
  //: Debounced like every other search box in this file: the index rebuilds
  //: from `allEntries` in memory, but a 400-note rebuild on each keystroke is
  //: still work the typist can feel.
  let contentsFilterTimer = null;
  $("contents-filter")?.addEventListener("input", () => {
    clearTimeout(contentsFilterTimer);
    contentsFilterTimer = setTimeout(renderContents, 150);
  });
  $("contents-collapse")?.addEventListener("click", (event) => {
    const outline = $("contents-outline");
    if (!outline) return;
    //: Reads the sections rather than a flag of its own: the button's job is
    //: "make them all the same", and whether that means folding or unfolding
    //: depends on what is on screen right now, which the user may have
    //: changed one section at a time since the last press.
    const anyOpen = [...outline.querySelectorAll(".contents-heading")].some(
      (h) => h.getAttribute("aria-expanded") === "true",
    );
    for (const heading of outline.querySelectorAll(".contents-heading")) {
      if ((heading.getAttribute("aria-expanded") === "true") === anyOpen) heading.click();
    }
    //: The words only, not the whole button. This control now lives in the
    //: dock's `...` menu, where it carries an icon beside its label, and
    //: writing `textContent` on the button replaced that icon with a bare
    //: string on the first press. The span is the label; the button is the
    //: fallback for anywhere this markup is simpler.
    const label = event.currentTarget.querySelector("[data-collapse-label]") || event.currentTarget;
    label.textContent = anyOpen ? "Expand all" : "Collapse all";
  });
});

// --- Multi-select for Boards, Links and Contents (asked for directly: "in
// many of the library subtabs… there is no way to multi select") ----------
//
// The Documents and Files/Images sub-tabs already had this, a tick per
// item, a count, a bulk Delete, because it shipped with them, bar and all,
// in index.html. These three sub-tabs did not, so the bar itself (same
// markup, same `.library-contextbar` class those two already use) is built
// here at runtime instead of pasting three more near-identical copies into
// index.html.
//
// One shared count/visibility sync, reused by all three selections below, 
// syncLibraryMediaSelectbar/syncLibraryDocsSelectbar above are this same
// six-line shape typed out twice already; a third and fourth copy is what
// this generalises instead of repeating again.
function syncSelectbarCount(idPrefix, n) {
  const bar = document.getElementById(`${idPrefix}-selectbar`);
  const count = document.getElementById(`${idPrefix}-selected-count`);
  if (!bar || !count) return;
  bar.classList.toggle("hidden", n === 0);
  count.textContent = `${n} selected`;
}

//: Builds one `.library-contextbar`, the same element `#library-docs-selectbar`
//: and `#library-media-selectbar` already are in index.html, so a sub-tab
//: that never had one gets the identical bar rather than a fourth visual
//: treatment for "items are selected".
function createLibrarySelectbar(idPrefix, ariaLabel) {
  const bar = document.createElement("div");
  bar.id = `${idPrefix}-selectbar`;
  bar.className = "library-contextbar hidden";
  bar.setAttribute("role", "group");
  bar.setAttribute("aria-label", ariaLabel);
  const count = document.createElement("span");
  count.id = `${idPrefix}-selected-count`;
  count.className = "library-selected-count";
  const end = document.createElement("span");
  end.className = "library-contextbar-end";
  const del = document.createElement("button");
  del.id = `${idPrefix}-bulk-delete`;
  del.className = "ghost small";
  del.type = "button";
  setLabel(del, "ph:trash Delete");
  const clear = document.createElement("button");
  clear.id = `${idPrefix}-clear-selection`;
  clear.className = "ghost small";
  clear.type = "button";
  clear.textContent = "Done";
  end.append(del, clear);
  bar.append(count, end);
  return bar;
}

// --- Boards & maps: the one sub-tab of the three whose gallery is built by
// whiteboard.js (renderLibraryBoardsGallery), which this file does not own
// and does not edit. Its cards carry no id in the DOM, nothing needed one
// until now: so the tick is grafted on from here via a MutationObserver on
// the grid whiteboard.js already tears down and rebuilds on every render,
// rather than by changing what that function builds. -----------------------

//: Keyed by board id (never `null`, the default scratch board is not a real
//: Entry and cannot be deleted; see attachBoardTick).
const libraryBoardsSelection = new Map();

//: Re-fetches the exact list `renderLibraryBoardsGallery` just rendered, with
//: the exact same filter (the search box's current value, the same
//: `wbLastCreatedBoard` patch-in that function does) so the *n*th tick lines
//: up with the *n*th card the observer below just saw appended. If the
//: counts don't match: the grid mutated again while this fetch was in
//: flight: this bails rather than tick the wrong board; the next mutation
//: (the very next render) retries it.
async function syncLibraryBoardsTicks() {
  const grid = document.getElementById("library-boards-grid");
  if (!grid) return;
  const cards = [...grid.querySelectorAll(".library-board-card")];
  if (!cards.length) {
    syncSelectbarCount("library-boards", libraryBoardsSelection.size);
    return;
  }
  let boards;
  try {
    // The same full read the gallery itself does (`wbRenderBoardGallery`):
    // this matches rows against the cards already on screen, so a first page
    // would leave every card past it unmatched.
    boards = await apiPagedList("/whiteboard/boards", 200, { silent: true });
  } catch {
    return;
  }
  if (!Array.isArray(boards)) return;
  const created = window.wbLastCreatedBoard;
  if (created && !boards.some((b) => b.id === created.id)) boards.push({ ...created });
  const needle = (document.getElementById("library-boards-search")?.value || "").trim().toLowerCase();
  //: The gallery's own filter *and* sort, not a second copy of the filter, 
  //: see `wbVisibleBoards` (whiteboard.js). Ordering is part of "the exact
  //: same filter" this function's comment above requires: the counts still
  //: match under a reorder, so a private copy would silently tick the wrong
  //: boards rather than bail.
  const shown = window.wbVisibleBoards(boards, needle);
  if (shown.length !== cards.length) return;
  // A board ticked in an earlier render that no longer exists (deleted from
  // its own ⋯ menu, or from elsewhere) shouldn't go on counting toward the bar.
  const liveIds = new Set(shown.filter((b) => b.id !== null).map((b) => b.id));
  for (const id of [...libraryBoardsSelection.keys()]) {
    if (!liveIds.has(id)) libraryBoardsSelection.delete(id);
  }
  cards.forEach((card, i) => attachBoardTick(card, shown[i]));
  syncSelectbarCount("library-boards", libraryBoardsSelection.size);
}

function attachBoardTick(card, board) {
  const top = card.querySelector(".library-card-top");
  if (!top) return;
  const existing = top.querySelector(".library-card-tick");
  // The default board (id === null) isn't a note and can't be renamed or
  // deleted: renderLibraryBoardsGallery's own comment says so, right where
  // it skips giving it a ⋯ menu at all. No tick for the same reason an
  // activity row gets no tick in the "All" library view: a Delete that can
  // never do anything is worse than no checkbox.
  if (board.id === null) {
    existing?.remove();
    return;
  }
  if (existing) {
    existing.checked = libraryBoardsSelection.has(board.id);
    return;
  }
  const tick = document.createElement("input");
  tick.type = "checkbox";
  tick.className = "library-card-tick";
  tick.checked = libraryBoardsSelection.has(board.id);
  tick.setAttribute("aria-label", `Select "${board.title}"`);
  tick.addEventListener("click", (event) => event.stopPropagation());
  tick.addEventListener("change", () => {
    if (tick.checked) libraryBoardsSelection.set(board.id, board);
    else libraryBoardsSelection.delete(board.id);
    syncSelectbarCount("library-boards", libraryBoardsSelection.size);
  });
  top.insertBefore(tick, top.firstChild);
}

function clearLibraryBoardsSelection() {
  libraryBoardsSelection.clear();
  for (const tick of document.querySelectorAll("#library-boards-grid .library-card-tick")) {
    tick.checked = false;
  }
  syncSelectbarCount("library-boards", 0);
}

async function bulkDeleteLibraryBoards() {
  const boards = [...libraryBoardsSelection.values()];
  if (!boards.length) return;
  // Same wording renderLibraryBoardsGallery's own per-board Delete already
  // uses (whiteboard.js): a board goes through `DELETE /entries/{id}` same
  // as that single-item menu action, so the two must not promise different
  // things about whether it comes back.
  if (
    !(await confirmDialog(
      `Delete ${boards.length} board${boards.length === 1 ? "" : "s"}? This cannot be undone.`
    ))
  ) {
    return;
  }
  let deleted = 0;
  for (const board of boards) {
    try {
      await apiJson(`/entries/${board.id}`, { method: "DELETE" });
      deleted++;
    } catch (err) {
      toast(err.message, true);
    }
  }
  libraryBoardsSelection.clear();
  if (deleted) toast(`Deleted ${deleted} board${deleted === 1 ? "" : "s"}.`);
  const failed = boards.length - deleted;
  if (failed) toast(`${failed} board${failed === 1 ? "" : "s"} couldn't be deleted.`, true);
  if (typeof renderLibraryBoardsGallery === "function") renderLibraryBoardsGallery();
}

document.addEventListener("DOMContentLoaded", () => {
  // The bar goes right above the grid it governs, same placement the
  // Documents/Files sub-tabs' own bars have in index.html.
  const boardsGrid = document.getElementById("library-boards-grid");
  if (boardsGrid && !document.getElementById("library-boards-selectbar")) {
    const bar = createLibrarySelectbar("library-boards", "Actions for the selected boards");
    boardsGrid.parentNode.insertBefore(bar, boardsGrid);
    document.getElementById("library-boards-bulk-delete").addEventListener("click", bulkDeleteLibraryBoards);
    document.getElementById("library-boards-clear-selection").addEventListener("click", clearLibraryBoardsSelection);
    // whiteboard.js calls `grid.replaceChildren()` then re-appends every
    // card on each render (a fresh board, a rename, the search box, "+ New
    // board"), this is the one hook available from outside that file that
    // fires exactly then, without this file calling into or duplicating
    // renderLibraryBoardsGallery's own logic.
    new MutationObserver(() => { syncLibraryBoardsTicks(); }).observe(boardsGrid, { childList: true });
  }

  const linksList = document.getElementById("bookmark-list");
  if (linksList && !document.getElementById("library-links-selectbar")) {
    const bar = createLibrarySelectbar("library-links", "Actions for the selected links");
    linksList.parentNode.insertBefore(bar, linksList);
    document.getElementById("library-links-bulk-delete").addEventListener("click", bulkDeleteLibraryLinks);
    document.getElementById("library-links-clear-selection").addEventListener("click", clearLibraryLinksSelection);
  }

  //: The Contents outline had a selection bar here. It went with its ticks, 
  //: see the note in the outline builder: a table of contents is for finding
  //: your place, not for bulk-editing. Nothing could reach the bar any more,
  //: and a set of actions for a selection that can never be made is worse
  //: than none.
});

// --- Links (§30): a bookmark shelf for websites, alongside the notes and
// documents already linkable to each other via [[wiki links]] ------------

let bookmarksCache = [];
let bookmarkGroupFilter = null; // null = all groups

//: Which links are ticked, keyed by bookmark id, its own Map so a selection
//: here can never leak into another sub-tab's bulk delete, the same reasoning
//: mediaRowKey's own comment gives for libraryMediaSelection.
const libraryLinksSelection = new Map();

async function renderBookmarks() {
  const list = $("bookmark-list");
  const empty = $("bookmark-empty");
  if (!list) return;
  try {
    bookmarksCache = await apiJson("/bookmarks");
  } catch (error) {
    toast(error.message, true);
    return;
  }
  // A reload can drop a link that was ticked (deleted from its own ⋯, or by
  // the bulk action just below), same prune renderLibraryDocuments does for
  // libraryDocsSelection, and for the same reason: otherwise the bar's count
  // goes on including a row that no longer exists.
  const liveLinkIds = new Set(bookmarksCache.map((b) => b.id));
  for (const id of [...libraryLinksSelection.keys()]) {
    if (!liveLinkIds.has(id)) libraryLinksSelection.delete(id);
  }
  empty.classList.toggle("hidden", bookmarksCache.length > 0);
  renderBookmarkGroupChips();
  filterBookmarks();
  syncSelectbarCount("library-links", libraryLinksSelection.size);
}

function clearLibraryLinksSelection() {
  libraryLinksSelection.clear();
  renderBookmarks();
}

async function bulkDeleteLibraryLinks() {
  const links = [...libraryLinksSelection.values()];
  if (!links.length) return;
  if (
    !(await confirmDialog(`Delete ${links.length} selected link${links.length === 1 ? "" : "s"}?`))
  ) {
    return;
  }
  let deleted = 0;
  for (const bookmark of links) {
    try {
      await apiJson(`/bookmarks/${bookmark.id}`, { method: "DELETE" });
      deleted++;
    } catch (err) {
      toast(err.message, true);
    }
  }
  libraryLinksSelection.clear();
  if (deleted) toast(`Deleted ${deleted} link${deleted === 1 ? "" : "s"}.`);
  const failed = links.length - deleted;
  if (failed) toast(`${failed} link${failed === 1 ? "" : "s"} couldn't be deleted.`, true);
  renderBookmarks();
}

//: **A group is a name on a bookmark, not a row in a table.** There is no
//: group entity anywhere in the backend, `routes_bookmarks.py` stores
//: `group_name` as a plain string field on each link, and the chips are
//: derived from whatever names the current links happen to carry. That is a
//: good model (nothing to garbage-collect, no join to keep honest), but it
//: has one hole: a group with no links in it cannot exist server-side, so
//: "New group" would create something that vanishes the moment you look away.
//:
//: This is that hole, filled client-side rather than by adding a table: a
//: freshly made, still-empty group is remembered here until a link lands in
//: it, at which point the derived name takes over and the placeholder is
//: dropped. Kept per-profile in localStorage alongside the sort preference,
//: for the same reason that one is: it is a view preference, not notebook
//: content, and it must not travel into an export as if it were data.
const BOOKMARK_EMPTY_GROUPS_KEY = "library-links-empty-groups";

function emptyBookmarkGroups() {
  try {
    const parsed = JSON.parse(localStorage.getItem(BOOKMARK_EMPTY_GROUPS_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.filter((g) => typeof g === "string" && g) : [];
  } catch {
    // A hand-edited or half-written value must not take the whole sub-tab
    // down with it: an unreadable preference is the same as none.
    return [];
  }
}

function setEmptyBookmarkGroups(groups) {
  try {
    localStorage.setItem(BOOKMARK_EMPTY_GROUPS_KEY, JSON.stringify([...new Set(groups)].sort()));
  } catch {
    /* storage full or blocked: the group just won't survive a reload. */
  }
}

//: Every group name the Links sub-tab knows about: the ones links actually
//: carry, plus the placeholders above that nothing has been filed into yet.
//: Also the one place that prunes a placeholder whose name is now real, so
//: the two sources can never both claim the same name.
function allBookmarkGroups() {
  const used = new Set(bookmarksCache.map((b) => b.group_name).filter(Boolean));
  const empties = emptyBookmarkGroups().filter((g) => !used.has(g));
  if (empties.length !== emptyBookmarkGroups().length) setEmptyBookmarkGroups(empties);
  return [...new Set([...used, ...empties])].sort();
}

//: Rename a group across every link carrying it. One PUT per link, because
//: that is the only endpoint there is, there is no bulk update and no group
//: row to rename instead. Sequential rather than Promise.all so a notebook
//: with a hundred links in one group does not open a hundred sockets at once;
//: a rename is rare and a moment of latency is cheaper than a thundering herd.
async function renameBookmarkGroup(from, to) {
  let moved = 0;
  for (const bookmark of bookmarksCache.filter((b) => b.group_name === from)) {
    try {
      await apiJson(`/bookmarks/${bookmark.id}`, {
        method: "PUT",
        body: JSON.stringify({ group_name: to }),
      });
      moved++;
    } catch (error) {
      toast(error.message || "Couldn't move that link.", true);
    }
  }
  const empties = emptyBookmarkGroups().filter((g) => g !== from);
  if (to) empties.push(to);
  setEmptyBookmarkGroups(empties);
  if (bookmarkGroupFilter === from) bookmarkGroupFilter = to || null;
  return moved;
}

//: Deleting a group deletes the *grouping*, never the links, clearing the
//: name on each one drops them back into the ungrouped pile. Deleting the
//: links themselves is what the row ticks and the bulk bar are for, and
//: conflating the two here would make a tidy-up destructive by surprise.
async function deleteBookmarkGroup(group) {
  return renameBookmarkGroup(group, "");
}

async function newBookmarkGroup() {
  const name = (await promptDialog("Name for the new group (e.g. Work/Reading):", "")).trim();
  if (!name) return;
  if (allBookmarkGroups().includes(name)) {
    toast(`"${name}" already exists.`);
    bookmarkGroupFilter = name;
    renderBookmarks();
    return;
  }
  setEmptyBookmarkGroups([...emptyBookmarkGroups(), name]);
  // Pre-fill the Add form so the obvious next move, saving a link into the
  // group you just made, needs no second trip to the group field.
  const groupInput = $("bookmark-group-input");
  if (groupInput) groupInput.value = name;
  bookmarkGroupFilter = name;
  renderBookmarks();
  toast(`Group "${name}" created. Add a link to it, or it'll be forgotten on the next device.`);
}

//: The manage dialog. Built by hand rather than reusing confirmDialog because
//: it is a list with two actions per row, and it re-renders itself in place
//: after each one: reopening it after every rename would lose your place.
function manageBookmarkGroups() {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay confirm-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "Manage link groups");

  const card = document.createElement("div");
  card.className = "card modal-card confirm-card bookmark-groups-card";
  const heading = document.createElement("h3");
  heading.textContent = "Manage groups";
  const blurb = document.createElement("p");
  blurb.className = "muted text-sm";
  blurb.textContent =
    "Renaming a group moves every link in it. Deleting one keeps the links and just ungroups them.";
  const list = document.createElement("div");
  list.className = "bookmark-groups-list";

  const returnFocus = document.activeElement;
  let settled = false;
  const close = () => {
    if (settled) return;
    settled = true;
    document.removeEventListener("keydown", onKey, true);
    overlay.remove();
    returnFocus?.focus?.();
  };
  const onKey = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    }
  };

  const paint = () => {
    list.replaceChildren();
    const groups = allBookmarkGroups();
    if (!groups.length) {
      const none = document.createElement("p");
      none.className = "muted";
      none.textContent = "No groups yet. Use “New group”, or type a group name when you add a link.";
      list.appendChild(none);
      return;
    }
    for (const group of groups) {
      const count = bookmarksCache.filter((b) => b.group_name === group).length;
      const row = document.createElement("div");
      row.className = "row space-between bookmark-group-row";

      const label = document.createElement("div");
      label.className = "bookmark-group-row-main";
      const name = document.createElement("strong");
      name.textContent = group.split("/").join(" / ");
      const meta = document.createElement("span");
      meta.className = "muted text-sm";
      meta.textContent = count === 0 ? "Empty" : `${count} link${count === 1 ? "" : "s"}`;
      label.append(name, meta);

      const actions = document.createElement("div");
      actions.className = "row bookmark-group-row-actions";
      actions.append(
        smallButton("ph:pencil-simple", `Rename "${group}"`, async () => {
          const next = (await promptDialog(`Rename "${group}" to:`, group)).trim();
          if (!next || next === group) return;
          const moved = await renameBookmarkGroup(group, next);
          await renderBookmarks();
          paint();
          toast(moved ? `Moved ${moved} link${moved === 1 ? "" : "s"} to "${next}".` : `Renamed to "${next}".`);
        }),
        smallButton("ph:trash", `Delete "${group}"`, async () => {
          const ok = await confirmDialog(
            count === 0
              ? `Delete the empty group "${group}"?`
              : `Delete the group "${group}"? Its ${count} link${count === 1 ? "" : "s"} stay: they just stop being grouped.`
          );
          if (!ok) return;
          await deleteBookmarkGroup(group);
          await renderBookmarks();
          paint();
        })
      );
      row.append(label, actions);
      list.appendChild(row);
    }
  };
  paint();

  const footer = document.createElement("div");
  footer.className = "row confirm-actions";
  footer.append(
    smallButton("New group", "Create a new group", async () => {
      close();
      await newBookmarkGroup();
    }),
    smallButton("Done", "Close", close, false)
  );

  card.append(heading, blurb, list, footer);
  overlay.appendChild(card);
  wireBackdropClose(overlay, close);
  document.addEventListener("keydown", onKey, true);
  document.body.appendChild(overlay);
  card.querySelector("button")?.focus();
}

function renderBookmarkGroupChips() {
  const box = $("bookmark-group-chips");
  const datalist = $("bookmark-group-options");
  if (!box) return;
  const groups = allBookmarkGroups();
  datalist?.replaceChildren(
    ...groups.map((g) => { const opt = document.createElement("option"); opt.value = g; return opt; })
  );
  box.replaceChildren();
  if (groups.length === 0) {
    bookmarkGroupFilter = null;
    return;
  }
  const allChip = document.createElement("button");
  allChip.type = "button";
  allChip.className = `library-chip${bookmarkGroupFilter === null ? " active" : ""}`;
  allChip.textContent = "All";
  allChip.addEventListener("click", () => { bookmarkGroupFilter = null; renderBookmarkGroupChips(); filterBookmarks(); });
  box.appendChild(allChip);
  for (const group of groups) {
    const chipEl = document.createElement("button");
    chipEl.type = "button";
    chipEl.className = `library-chip${bookmarkGroupFilter === group ? " active" : ""}`;
    // "Work/Reading" renders as "Work / Reading", the "/" is a grouping
    // convention for the user to type, not meant to display as a raw slash.
    chipEl.textContent = group.split("/").join(" / ");
    chipEl.addEventListener("click", () => { bookmarkGroupFilter = group; renderBookmarkGroupChips(); filterBookmarks(); });
    box.appendChild(chipEl);
  }
}

//: Sorting for the Links sub-tab, the Library's sub-tabs were reported as
//: "missing sorting and filtering options", and this is the same local,
//: no-round-trip approach the media gallery uses: the list is already in
//: memory, so ordering it is a reorder rather than a request.
//:
//: "By site" is the one order here that is not a copy of the media set, and it
//: is the one a list of links actually wants: hostname first, then title
//: within a host, so everything from one place reads as a block.
const BOOKMARK_SORTS = {
  newest: (a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")),
  oldest: (a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")),
  az: (a, b) => String(a.title || "").localeCompare(String(b.title || ""), undefined, { sensitivity: "base" }),
  za: (a, b) => String(b.title || "").localeCompare(String(a.title || ""), undefined, { sensitivity: "base" }),
  site: (a, b) => {
    const host = (url) => {
      //: A stored link can be anything somebody pasted, so a URL that will not
      //: parse sorts by its own raw text rather than throwing the whole list
      //: into an exception.
      try {
        return new URL(url).hostname.replace(/^www\./, "");
      } catch {
        return String(url || "");
      }
    };
    return (
      host(a.url).localeCompare(host(b.url), undefined, { sensitivity: "base" }) ||
      String(a.title || "").localeCompare(String(b.title || ""), undefined, { sensitivity: "base" })
    );
  },
};

const BOOKMARK_SORT_KEY = "library-links-sort";

function bookmarkSort() {
  const stored = localStorage.getItem(BOOKMARK_SORT_KEY);
  return BOOKMARK_SORTS[stored] ? stored : "newest";
}

document.addEventListener("DOMContentLoaded", () => {
  const select = document.getElementById("bookmark-sort");
  if (!select) return;
  select.value = bookmarkSort();
  select.addEventListener("change", () => {
    localStorage.setItem(BOOKMARK_SORT_KEY, select.value);
    filterBookmarks();
  });
});

function filterBookmarks() {
  const list = $("bookmark-list");
  const noMatch = $("bookmark-no-match");
  if (!list) return;
  const query = ($("bookmark-search")?.value || "").trim().toLowerCase();
  const visible = bookmarksCache.filter((b) => {
    if (bookmarkGroupFilter !== null && b.group_name !== bookmarkGroupFilter) return false;
    if (!query) return true;
    return (
      b.title.toLowerCase().includes(query) ||
      b.url.toLowerCase().includes(query) ||
      b.note.toLowerCase().includes(query)
    );
  });
  list.replaceChildren();
  //: On a copy, for the reason the media gallery's own sort records: `visible`
  //: can be the cache itself when nothing is filtered, and sorting in place
  //: would reorder the array every other reader shares.
  for (const bookmark of [...visible].sort(BOOKMARK_SORTS[bookmarkSort()])) {
    list.appendChild(bookmarkRow(bookmark));
  }
  noMatch?.classList.toggle("hidden", !(bookmarksCache.length > 0 && visible.length === 0));
}

function bookmarkRow(bookmark) {
  const row = document.createElement("div");
  row.className = "bookmark-row";

  // The tick. Same control (and the same `.doc-list-tick` sizing) the
  // Documents sub-tab's own rows already use, so selecting a link works the
  // same way selecting a document does.
  const tick = document.createElement("input");
  tick.type = "checkbox";
  tick.className = "doc-list-tick";
  tick.checked = libraryLinksSelection.has(bookmark.id);
  tick.setAttribute("aria-label", `Select "${bookmark.title || bookmark.url}"`);
  tick.addEventListener("click", (event) => event.stopPropagation());
  tick.addEventListener("change", () => {
    if (tick.checked) libraryLinksSelection.set(bookmark.id, bookmark);
    else libraryLinksSelection.delete(bookmark.id);
    syncSelectbarCount("library-links", libraryLinksSelection.size);
  });
  row.appendChild(tick);

  //: **A mark, so a list of links reads as a list of links.** The Timeline's
  //: rows carry one for the same reason: a column of rows with nothing at
  //: their left edge but a tick box is a table, and the owner's ask here was
  //: for these to look less like one. A glyph rather than a favicon, because
  //: this app fetches nothing from the internet: a favicon is a request to
  //: every site you have ever saved, which is the one thing an offline
  //: notebook must not do.
  const mark = document.createElement("span");
  mark.className = "bookmark-mark";
  mark.setAttribute("aria-hidden", "true");
  setLabel(mark, bookmark.pinned ? "ph:push-pin" : "ph:link-simple");
  row.appendChild(mark);

  const main = document.createElement("div");
  main.className = "bookmark-main";
  //: **Two ranks, not four lines.** Before this the row stacked the title, the
  //: whole address, the group and the note, each its own full-width line at
  //: its own weight: measured at 1440, a row with a group stood 89.2px against
  //: 67.2px for one without, so no two rows in the list were the same height,
  //: and five type sizes met inside one of them (16px title over 12px address
  //: over two more 12px lines with an icon at 13.8px). The title is the row;
  //: the site, the group and the note are facts about it and share one line at
  //: one size, the same `.library-file-meta` the Files rows use.
  const address = bookmarkAddress(bookmark.url);
  const link = document.createElement("a");
  link.className = "bookmark-title";
  link.href = bookmark.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = bookmark.title || address.host;
  link.title = bookmark.url;
  main.append(
    link,
    metaLine(
      [
        //: A link saved without a title is named by its site, and then the
        //: facts line saying the site again is the row saying one thing twice:
        //: it says which page on it instead, which is the part the title is
        //: not carrying.
        bookmark.title ? address.host : address.rest,
        bookmark.group_name ? bookmark.group_name.split("/").join(" / ") : "",
        bookmark.note,
      ],
      "bookmark-meta",
    ),
  );

  const actions = document.createElement("div");
  actions.className = "row bookmark-actions";

  const pin = document.createElement("button");
  pin.type = "button";
  pin.className = "ghost small icon-only";
  pin.title = bookmark.pinned ? "Unpin" : "Pin to the top";
  pin.setAttribute("aria-label", pin.title);
  // No "-fill" pin glyph in this app's bundled Phosphor set (checked: the
  // font only has push-pin/-slash/-simple/-simple-slash), reported live as
  // a blank icon before this went out. `-slash` for "already pinned, click
  // to undo" is the same pairing the pinned-chat button already uses.
  setLabel(pin, `ph:${bookmark.pinned ? "push-pin-slash" : "push-pin"}`);
  pin.classList.toggle("bookmark-pinned", Boolean(bookmark.pinned));
  pin.addEventListener("click", async () => {
    await apiJson(`/bookmarks/${bookmark.id}`, {
      method: "PUT",
      body: JSON.stringify({ pinned: !bookmark.pinned }),
    });
    renderBookmarks();
  });

  // **An inline form, not a chain of prompts.** This was two sequential
  // `promptDialog` calls (title, then URL) and was reported as "I still
  // can't edit the link URLs" five separate times. The flow was driven
  // end-to-end in a clean browser each time it was checked and worked
  // every time - including persistence through a reload - so the fault was
  // never in the handler. But a fix nobody can reach is not a fix, and a
  // second modal that only appears *after* you commit the first one is a
  // genuinely poor way to expose a second field: if anything at all
  // interrupts between them (a stale script, an Escape, a mis-click on
  // Cancel) the URL silently never gets asked for, and it looks exactly
  // like "editing the URL is broken".
  //
  // Editing the row in place removes the whole class of problem: all three
  // fields are visible at once, nothing is sequenced, nothing depends on
  // focus returning correctly between modals, and what you are editing
  // stays on screen next to the form.
  //
  //: A named function rather than a listener on a button of its own: the four
  //: verbs this row carried are a kebab now (see below), and a menu row runs a
  //: function.
  const startEditing = () => {
    if (row.querySelector(".bookmark-edit-form")) return; // already editing
    const form = document.createElement("form");
    form.className = "bookmark-edit-form";

    const field = (labelText, value, placeholder) => {
      const wrap = document.createElement("label");
      wrap.className = "bookmark-edit-field";
      const span = document.createElement("span");
      span.className = "muted text-xs";
      span.textContent = labelText;
      const input = document.createElement("input");
      input.type = "text";
      input.value = value || "";
      input.placeholder = placeholder;
      wrap.append(span, input);
      form.appendChild(wrap);
      return input;
    };

    const titleInput = field("Title", bookmark.title, "Title");
    const urlInput = field("URL", bookmark.url, "https://example.com");
    // Blank is meaningful here and always was: it means "no group".
    const groupInput = field("Group", bookmark.group_name, "e.g. Work/Reading");

    const buttons = document.createElement("div");
    buttons.className = "row bookmark-edit-actions";
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "small";
    save.textContent = "Save";
    const cancel = document.createElement("button");
    cancel.type = "button";
    // Owner: "the links edit save and cancel buttons arent consistent."
    // `icon-only` forces a square button (aspect-ratio: 1, see
    // 00-tokens-shell.css), which is right for a button whose only content
    // is a glyph and wrong here: this button's content is the word
    // "Cancel". Measured before this fix: Save 62.6x28 against Cancel
    // 56.2x56.2, a pill beside a near-square, not the "same radius, height
    // and padding, only the fill differs" pair DESIGN.md's button ramp
    // describes (filled `button` for the one action a surface is for, tonal
    // `.ghost` beside it for everything else). Plain `.ghost.small` matches
    // `.small` on both, the same pairing `.small`/`.ghost.small` already
    // uses everywhere else an edit row offers Save next to Cancel.
    cancel.className = "ghost small";
    cancel.textContent = "Cancel";
    buttons.append(save, cancel);
    form.appendChild(buttons);

    const close = () => {
      form.remove();
      main.classList.remove("hidden");
      actions.classList.remove("hidden");
    };
    cancel.addEventListener("click", close);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const url = urlInput.value.trim();
      if (!url) {
        toast("A link needs a URL.", true);
        urlInput.focus();
        return;
      }
      save.disabled = true;
      try {
        await apiJson(`/bookmarks/${bookmark.id}`, {
          method: "PUT",
          body: JSON.stringify({
            title: titleInput.value.trim(),
            url,
            group_name: groupInput.value.trim(),
          }),
        });
        renderBookmarks();
      } catch (error) {
        save.disabled = false;
        toast(error.message || "Couldn't save that link.", true);
      }
    });

    main.classList.add("hidden");
    actions.classList.add("hidden");
    row.appendChild(form);
    urlInput.focus();
    urlInput.select();
  };

  const moveToGroup = async () => {
    const value = await promptDialog(
      "Group (e.g. Work/Reading: blank clears it):", bookmark.group_name
    );
    // Unlike the title prompt above, an intentionally blank group is a real,
    // useful answer ("ungroup this link"), so only an actual Cancel/Escape
    // is ignored here, not an emptied field. promptDialog resolves "" for
    // both, so there's genuinely no way to tell them apart from its return
    // value alone; this trades "can't ungroup via Escape" for "can ungroup
    // by clearing the field", the more useful of the two to get right.
    if (value === "" && bookmark.group_name === "") return;
    await apiJson(`/bookmarks/${bookmark.id}`, {
      method: "PUT",
      body: JSON.stringify({ group_name: value }),
    });
    renderBookmarks();
  };

  const removeBookmark = async () => {
    const ok = await confirmDialog(`Delete "${bookmark.title || bookmark.url}"?`);
    if (!ok) return;
    await apiJson(`/bookmarks/${bookmark.id}`, { method: "DELETE" });
    renderBookmarks();
  };

  //: **Two controls on a row at rest, not four** (the owner, 2026-09-13:
  //: "redesign the links cards/rows ... to make them look nicer and more
  //: modern??"). Four icon buttons at the far end of every row is 32 buttons
  //: in a list of eight, and it is the shape UI_MODERNISATION_PLAN settled for
  //: the Files rows a pass ago ("the last three live in the kebab, which is
  //: where every other list in this app puts them"). Pin stays out, because it
  //: is a state you can see rather than a verb you go looking for: the row's
  //: mark shows it too. Copy link is new and was the gap: nothing in the
  //: Library could get a URL back out of the notebook.
  const menu = kebabMenu(
    [
      makeMenuItem("ph:pencil-simple Edit this link", "Change the title, address or group", startEditing),
      makeMenuItem("ph:folder-simple Move to group", "Move this link to a group", moveToGroup),
      makeMenuItem("ph:copy Copy link", "Copy the address to the clipboard", async () => {
        //: `copyToClipboard` flashes the button it is given, and a menu row is
        //: gone by the time it would: it says so in a toast instead, the same
        //: way every other copy in a menu does.
        if (await copyToClipboard(bookmark.url)) toast("Link copied.");
      }),
      { ...makeMenuItem("ph:trash Delete", "Delete this link", removeBookmark), danger: true },
    ],
    `Actions for ${bookmark.title || bookmark.url}`,
  );

  actions.append(pin, menu);
  row.append(main, actions);
  return row;
}

// --- Contents (§30): a hyperlinked outline of the notebook's own
// structure: categories and tags, each with what's filed under it. The
// force-directed, spatial visualisation already lives in the Graph tab;
// this is the fast, scannable list half of the same ask. Built entirely
// from `allEntries` (already loaded for the Notes tab) rather than a new
// endpoint: the same data, grouped differently client-side. -----------

let contentsMode = "category";
//: Which sections are folded, by their heading. Kept per grouping mode,
//: because "Uncategorised" collapsed under By category says nothing about a
//: month of the same name under By month.
const contentsCollapsed = {
  category: new Set(),
  tag: new Set(),
  date: new Set(),
  folder: new Set(),
};
// A big notebook can have a group with hundreds of notes; nobody scans
// past this many in one section, and rendering them all would be the one
// part of this view that isn't cheap.
const CONTENTS_GROUP_CAP = 200;

//: **This is an index, not a set of cards.** It used to be a masonry of
//: bordered boxes, each with its own 14rem scroller, asked for directly:
//: "I think cards are overly used and used too much… i want to redesign the
//: contents subtab".
//:
//: Three things were wrong with the boxes, and they are the reasons for the
//: shape below rather than a restyle of the old one:
//:
//: 1. **A card is a claim that its contents are one object you can act on.**
//:    A category is not, it is a heading. Boxes made twenty headings look
//:    like twenty things to click.
//: 2. **Each box scrolled on its own.** A category of 25 notes showed five
//:    rows and hid twenty behind a nested scrollbar inside an already
//:    scrolling page, which is the one interaction nobody finds by accident.
//:    Sections are now open to their full height and the *page* scrolls, the
//:    way an index in a book works.
//: 3. **There was no way to find anything.** An index of 400 rows without a
//:    filter or a jump bar is a wall, so both are here now, plus grouping by
//:    month: half of "where is that note" is *when* you wrote it.
function contentsGroups(entries) {
  const groups = new Map();
  const addTo = (key, entry) => {
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  };
  if (contentsMode === "tag") {
    for (const entry of entries) {
      if (entry.tags && entry.tags.length) for (const tag of entry.tags) addTo(tag, entry);
      else addTo("(untagged)", entry);
    }
  } else if (contentsMode === "folder") {
    //: The vault's own shape. Asked for directly: "kortex and obsidian files
    //: and md file trees … is I think the largest gap that is missing right
    //: now." An imported note carries the path it came from
    //: (`Entry.source_path`); everything written in this app has none, and
    //: those group under one heading rather than being hidden, a mode that
    //: silently drops most of the notebook reads as broken.
    for (const entry of entries) {
      const path = entry.source_path || "";
      const folder = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
      //: **"(written here)" said nothing to the person reading it.** Reported:
      //: *"idk what (written here) is. are there even folders?? how do I make
      //: them??"*, three fair questions, and the label answered none of
      //: them. It is not a folder you can make: folders in this app are the
      //: directories of an imported Obsidian vault, and a note typed into
      //: MemoryMap has no path at all. The heading now says that.
      addTo(path ? folder || CONTENTS_VAULT_ROOT : CONTENTS_NO_FOLDER, entry);
    }
  } else if (contentsMode === "date") {
    for (const entry of entries) {
      const when = new Date(entry.created_at || entry.updated_at || Date.now());
      //: A sortable key ("2026-03") with a readable label built from it, so
      //: months order by time rather than alphabetically, "April" before
      //: "January" is the classic version of this bug.
      const key = Number.isNaN(when.valueOf())
        ? "Undated"
        : `${when.getFullYear()}-${String(when.getMonth() + 1).padStart(2, "0")}`;
      addTo(key, entry);
    }
  } else {
    for (const entry of entries) addTo(entry.category || "Uncategorised", entry);
  }
  return groups;
}

//: The two synthetic folder headings. Named constants because three places
//: need to agree on them, the grouper, the ordering (they sort last) and the
//: explanation shown when they are all there is.
const CONTENTS_NO_FOLDER = "Written in MemoryMap (no folder)";
const CONTENTS_VAULT_ROOT = "Top level of the vault";

function contentsSectionLabel(key) {
  if (contentsMode !== "date" || key === "Undated") return key;
  const [year, month] = key.split("-");
  const when = new Date(Number(year), Number(month) - 1, 1);
  return when.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function contentsOrderedKeys(groups) {
  const keys = [...groups.keys()];
  //: Newest month first: an index by time is read from now backwards.
  if (contentsMode === "date") return keys.sort((a, b) => b.localeCompare(a));
  //: Folders in path order, with the two synthetic groups last: they are
  //: where things *aren't* filed, and a tree reads better without them at
  //: the top.
  if (contentsMode === "folder") {
    //: Compared against the constants, not `startsWith("(")`. The headings
    //: used to be "(written here)" and "(vault root)", so a leading bracket
    //: was a fair proxy, renaming them for legibility would have quietly
    //: sorted them in among the real folders instead of after them, which is
    //: precisely the kind of coupling a literal-matching helper hides.
    const synthetic = (key) =>
      key === CONTENTS_NO_FOLDER || key === CONTENTS_VAULT_ROOT ? 1 : 0;
    return keys.sort(
      (a, b) => synthetic(a) - synthetic(b) || a.localeCompare(b),
    );
  }
  return keys.sort((a, b) => a.localeCompare(b));
}

async function renderContents() {
  const outline = $("contents-outline");
  const empty = $("contents-empty");
  const jump = $("contents-jump");
  const noMatch = $("contents-no-match");
  if (!outline) return;
  // Refetched on every visit, not gated behind `entriesEverLoaded`, every
  // sibling Library subtab (Documents, Image Gallery, AI Skills) re-fetches
  // its own data on each visit too, and this outline is exactly the kind of
  // view where showing a note that was just deleted, or missing one just
  // added, would be a wrong answer, not just a stale one.
  await loadEntries();

  const active = allEntries.filter((e) => !e.deleted_at && !e.archived_at);
  outline.replaceChildren();
  jump?.replaceChildren();
  empty.classList.toggle("hidden", active.length > 0);
  noMatch?.classList.add("hidden");
  if (active.length === 0) return;

  const needle = ($("contents-filter")?.value || "").trim().toLowerCase();
  //: The filter reads the same text the row shows. Matching the raw markdown
  //: instead would hit a note on an image path or a link target the reader
  //: cannot see in this view, which reads as the filter being broken.
  const shown = needle
    ? active.filter((entry) => noteLabel(entry, 200).toLowerCase().includes(needle))
    : active;
  if (!shown.length) {
    if (noMatch) {
      noMatch.textContent = `Nothing in the index matches “${needle}”.`;
      noMatch.classList.remove("hidden");
    }
    return;
  }

  const groups = contentsGroups(shown);
  const folded = contentsCollapsed[contentsMode];

  //: **A mode that groups everything under one heading has to say why.**
  //: Reported: *"idk what (written here) is. are there even folders?? how do I
  //: make them??"* Folders here are not something you create, they are the
  //: directories of an imported Obsidian vault, and a note typed into this app
  //: has no path at all. Until something is imported, By folder therefore has
  //: exactly one group, which reads as a broken mode rather than an empty one.
  //: Shown only in that case: once a vault is imported there are real folders
  //: and the note would be clutter.
  if (contentsMode === "folder" && groups.size === 1 && groups.has(CONTENTS_NO_FOLDER)) {
    const hint = document.createElement("p");
    hint.className = "muted contents-folder-hint";
    hint.textContent =
      "Folders come from an imported Obsidian vault, they are not created in "
      + "MemoryMap. Nothing has been imported yet, so every note is grouped "
      + "here. Import a vault from Settings → Import to see its folder tree.";
    outline.appendChild(hint);
  }

  for (const key of contentsOrderedKeys(groups)) {
    const members = groups.get(key);
    const label = contentsSectionLabel(key);
    const section = document.createElement("section");
    section.className = "contents-section";
    section.id = `contents-sec-${encodeURIComponent(key)}`;

    //: A `<button>` heading, not an `<h3>` with a click handler: folding a
    //: section is an action, and the thing that performs it has to be
    //: reachable by keyboard and announce its state. `aria-expanded` is what
    //: a screen reader reads out; the caret is what everyone else sees.
    const heading = document.createElement("button");
    heading.type = "button";
    heading.className = "contents-heading";
    heading.setAttribute("aria-expanded", folded.has(key) ? "false" : "true");
    const caret = document.createElement("i");
    caret.className = "ph ph-caret-down contents-caret";
    caret.setAttribute("aria-hidden", "true");
    const name = document.createElement("span");
    name.className = "contents-heading-name";
    name.textContent = label;
    const count = document.createElement("span");
    count.className = "contents-count";
    count.textContent = members.length;
    heading.append(caret, name, count);

    const list = document.createElement("ul");
    list.className = "contents-list";
    list.hidden = folded.has(key);
    heading.addEventListener("click", () => {
      const nowFolded = !folded.has(key);
      if (nowFolded) folded.add(key);
      else folded.delete(key);
      list.hidden = nowFolded;
      heading.setAttribute("aria-expanded", nowFolded ? "false" : "true");
      section.classList.toggle("is-folded", nowFolded);
    });
    section.classList.toggle("is-folded", folded.has(key));

    for (const entry of members.slice(0, CONTENTS_GROUP_CAP)) {
      const li = document.createElement("li");
      //: **No tick here.** Asked for directly: "the contents page shouldnt have
      //: radio buttons, it is purely a table of contents." It is right, and it
      //: is a point about what this page *is* rather than about how the
      //: control looked: a table of contents is a way to find your place, and
      //: every row offering to select itself for a bulk delete makes an index
      //: into a management screen you did not ask to be in.
      const link = document.createElement("a");
      link.href = "#";
      //: **A picture note shows its picture.** Reported: "the contents tab
      //: doesnt render images". Every row was `noteLabel`, which strips
      //: markdown down to text, so a note that *is* a photo appeared as its
      //: filename, or as the bare word "image" when the alt text was empty.
      //: In an index whose whole job is helping you recognise a note, that is
      //: the one row shape that cannot do it.
      const shot = noteAnyImage(entry);
      if (shot) {
        const thumb = document.createElement("img");
        thumb.className = "contents-thumb";
        thumb.src = mediaSrc(shot.url);
        thumb.alt = "";
        thumb.loading = "lazy";
        link.appendChild(thumb);
      }
      const text = document.createElement("span");
      text.className = "contents-label";
      //: In folder mode a row is a *file*, so it is named the way the vault
      //: names it: that is also the name its `[[wiki links]]` use, so the
      //: index and the links agree about what a note is called.
      const fileName =
        contentsMode === "folder" && entry.source_path
          ? entry.source_path.split("/").pop()
          : "";
      text.textContent = fileName || noteLabel(entry, 80);
      link.appendChild(text);
      //: The right-hand column of an index: what a row is filed under, or
      //: when it was written when the grouping already answers "under what".
      //: One value, muted, at a fixed edge, so the eye can run down it.
      const meta = document.createElement("span");
      meta.className = "contents-meta";
      meta.textContent =
        contentsMode === "category" || contentsMode === "folder"
          ? relativeTime(entry.updated_at || entry.created_at)
          : entry.category || "Uncategorised";
      link.appendChild(meta);
      link.addEventListener("click", (e) => {
        e.preventDefault();
        flashEntry(entry.id);
      });
      li.appendChild(link);
      list.appendChild(li);
    }
    if (members.length > CONTENTS_GROUP_CAP) {
      const more = document.createElement("li");
      more.className = "muted text-sm contents-more";
      more.textContent = `…and ${members.length - CONTENTS_GROUP_CAP} more`;
      list.appendChild(more);
    }
    section.append(heading, list);
    outline.appendChild(section);

    //: The jump bar. An index long enough to need one is exactly the index
    //: that had nothing but a scrollbar before.
    if (jump) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip contents-jump-chip";
      chip.textContent = `${label} ${members.length}`;
      chip.title = `Jump to ${label}`;
      chip.addEventListener("click", () => {
        //: Unfold before scrolling: jumping to a section that is folded lands
        //: on a heading with nothing under it, which reads as the jump having
        //: failed.
        if (folded.has(key)) heading.click();
        section.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      jump.appendChild(chip);
    }
  }
}
