// === EDITOR LAYER ===========================================================
// The "/" menu, the block frames it inserts, and the caret-anchored popup both
// it and the document's own [[ autocomplete are drawn with.
//
// Why this is a separate file rather than more of app.js: app.js is ~27k lines
// and ROADMAP Tier 4 makes the case, correctly, that a big-bang split must
// not share a diff with live edits to the same code. New code in a new file
// moves the line the right way without that risk, the same way graph.js and
// whiteboard.js already did. Loaded after app.js (see index.html), so every
// global it leans on, $, apiJson, allEntries, MD_ACTIONS, markDocDirty,
// renderDocPreview, BUILTIN_TEMPLATES, prefsCache, noteLabel, toast, is
// already defined.
//
// Two design decisions worth stating up front, because both were the cheap
// option *and* the correct one:
//
// 1. **One delegated listener, not one per textarea.** Every handler here is
//    bound once on `document` and dispatches on `event.target`. Binding
//    per-element would have meant a third `input` listener on `entry-content`
//    (it already legitimately has two, see ALLOWED_DOUBLES in
//    tests/test_frontend_handlers.py) and a fresh entry in that allow-list for
//    every surface added later. Delegation is how "one behaviour across many
//    inputs" is supposed to be written, and it means a new editor surface is
//    one line in EDITOR_SURFACES rather than a wiring change.
//
// 2. **Callouts are `> [!kind] Title`, not a custom fence.** That syntax
//    degrades to an ordinary blockquote in any other markdown reader, 
//    GitHub, Obsidian and Typora all already understand it. A custom fence
//    would render as literal junk the moment a note left this app, and
//    "your notes stay portable" is the whole premise of a local-first
//    notebook that stores plain markdown.

// Which textareas get the "/" menu, and what each one is allowed to do. The
// value is the context: an AI command that acts on a document has nowhere to
// run inside the capture box, so commands declare which contexts they suit
// and the menu filters rather than offering something that would no-op.
const EDITOR_SURFACES = {
  "entry-content": "note",
  //: The note *edit* form (app.js's `renderEditForm`), which had none of this
  //: until now: the one editing surface in the app with no "/" menu, no
  //: toolbar and no selection bar. One id, because `editingId` allows exactly
  //: one open edit form at a time.
  "entry-edit-content": "note",
  "doc-content": "document",
  //: The chat composer. Asked for as part of "the chat interface needs
  //: bugfixing and more utility and features" -- "/" did nothing there, the
  //: one text box in the app where a slash menu is the *expected* affordance
  //: (every chat product the user compared this to has one). Its commands are
  //: chat's own: attach, web, plan, skills, mode. See `chatCommands`.
  "chat-input": "chat",
};

//: **What context an editing surface is.**
//:
//: `EDITOR_SURFACES` is an id-to-context table by construction, and for most
//: of this file's life the hard case was the document's Live view, which was
//: one textarea per paragraph with a generated id: gating on
//: `textarea.id in EDITOR_SURFACES` gave those blocks no "/" menu at all and
//: told them the document AI commands did not apply. Neither failure logged
//: or threw, which is this repo's "a policy silently refusing the work"
//: shape. DOCUMENTS_PLAN Phase 2 made Live and Source one editor, so the
//: generated ids are gone; the surface reports `doc-content` in every view.
//:
//: Returns null, not "note", for anything that is not an editing surface, so
//: callers can tell "not a surface" from "a note".
function editorSurfaceKind(box) {
  //: A surface, an element, or a node inside CodeMirror. The last of those is
  //: why this can no longer be a `instanceof HTMLTextAreaElement` check:
  //: CodeMirror's editable is a `div`, and gating on the textarea would have
  //: silently taken the "/" menu, the selection bar and the inline AI away
  //: from the document editor the moment the engine landed under it. Same
  //: "policy silently refusing the work" shape this file's own comment
  //: records for the Live view.
  const surface = editorSurfaceFor(box);
  if (!surface) return null;
  return surface.id in EDITOR_SURFACES ? EDITOR_SURFACES[surface.id] : null;
}

//: Whatever this is, as a surface, or null. `asSurface` lives in
//: documents.js beside the adapter itself; the guard is for the moment
//: before that file has evaluated, which cannot happen in the browser (the
//: script order is fixed) but does in any test that loads this file alone.
function editorSurfaceFor(box) {
  if (!box) return null;
  if (box.kind === "textarea" || box.kind === "codemirror") return box;
  if (typeof asSurface !== "function") return null;
  return asSurface(box);
}

// The callout kinds, their icon and their accessible label. Kept as data
// because three things read it: the "/" menu builds a command per kind, the
// renderer maps a parsed kind onto an icon, and the CSS keys a colour off
// `.callout-{kind}`. A kind added here needs a matching CSS block and nothing
// else.
const CALLOUT_KINDS = {
  note: { icon: "\u{1F4DD}", label: "Note" },
  tip: { icon: "\u{1F4A1}", label: "Tip" },
  info: { icon: "\u{2139}\u{FE0F}", label: "Info" },
  warning: { icon: "\u{26A0}\u{FE0F}", label: "Warning" },
  danger: { icon: "\u{1F6D1}", label: "Danger" },
  question: { icon: "\u{2753}", label: "Question" },
  quote: { icon: "\u{201C}", label: "Quote" },
  todo: { icon: "\u{2705}", label: "To do" },
};

// ---------------------------------------------------------------------------
// Inserting text into an arbitrary textarea
//
// app.js's applyMarkdown() does exactly this job already, but it is hard-wired
// to $("doc-content"), it reads the box, and it calls markDocDirty() and
// renderDocPreview() unconditionally. Rather than duplicate its action table
// (MD_ACTIONS is reused verbatim below), this is the same four insertion
// shapes parameterised by which box to act on, plus a host-notification step
// that does the right thing for whichever surface it landed in.
// ---------------------------------------------------------------------------

// Tell the surrounding app that a textarea's value changed under it.
//
// This is the step that is easy to forget and silent when missed: the capture
// box's character count and localStorage draft both hang off its `input`
// event, and the document's autosave hangs off markDocDirty(). Writing
// `.value` from script fires neither, so a note inserted through this menu
// would look right, count wrong, and never be saved as a draft.
function editorNotifyHost(textarea) {
  if (textarea.isDocument) {
    markDocDirty();
    renderDocPreview();
    return;
  }
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  //: The capture box grows with its content; a scripted write has to ask.
  //: **`.el`, not the surface.** `autoGrow` is app.js's and works on a real
  //: element: it writes `style.height`, and a surface has no `style`. Passing
  //: the surface threw `Cannot set properties of undefined (setting
  //: 'height')` out of every "/" command in the note composer, which still
  //: *inserted* the text, so the menu looked like it worked and the box
  //: silently stopped growing. Found by driving the capture box
  //: (`scratchpad/ui-sweeps/cm-notes.js`), not by reading: the surface wears
  //: enough of a textarea's names that the call site reads as correct.
  if (typeof autoGrow === "function" && textarea.classList.contains("autogrow")) {
    autoGrow(textarea.el);
  }
}

// Replace [start, end) with `text`, then place the caret. `select` picks which
// slice of the inserted text ends up selected, so a placeholder can be typed
// straight over: the behaviour wrapDocSelection() already establishes for the
// formatting toolbar, kept identical here so the two feel like one editor.
function editorSplice(textarea, start, end, text, select) {
  //: CodeMirror gets a transaction rather than a whole-document rewrite: one
  //: keeps the editor's own undo history granular, the other collapses every
  //: insertion into "the document became this string".
  if (textarea.kind === "codemirror") {
    textarea.replaceRange(start, end, text);
  } else {
    const value = textarea.value;
    textarea.value = value.slice(0, start) + text + value.slice(end);
  }
  if (select) {
    textarea.setSelectionRange(start + select.from, start + select.to);
  } else {
    const caret = start + text.length;
    textarea.setSelectionRange(caret, caret);
  }
  textarea.focus();
  editorNotifyHost(textarea);
}

// Apply one MD_ACTIONS-shaped action to any textarea.
//
// The shapes (wrap / line / block / insert) are app.js's, deliberately: the
// formatting toolbar and this menu must not drift into two dialects of the
// same markdown. Anything the toolbar can insert, "/" can insert identically.
function editorApplyAction(textarea, action) {
  const { selectionStart: start, selectionEnd: end, value } = textarea;
  const selected = value.slice(start, end);

  if (action.wrap) {
    const body = selected || action.placeholder || "";
    const text = action.wrap + body + action.wrap;
    editorSplice(textarea, start, end, text, {
      from: action.wrap.length,
      to: action.wrap.length + body.length,
    });
    return;
  }
  if (action.line) {
    // Prefix the selected lines, or the current one when nothing is selected.
    const lineStart = value.lastIndexOf("\n", start - 1) + 1;
    const tail = value.slice(end).indexOf("\n");
    const lineEnd = tail === -1 ? value.length : end + tail;
    const target = value.slice(lineStart, Math.max(lineEnd, end));
    const prefixed = target
      .split("\n")
      .map((line) => (line.startsWith(action.line) ? line : action.line + line))
      .join("\n");
    editorSplice(textarea, lineStart, Math.max(lineEnd, end), prefixed, {
      from: 0,
      to: prefixed.length,
    });
    return;
  }
  if (action.block) {
    const body = selected || action.placeholder || "";
    const text = action.block + body + (action.suffix || "");
    editorSplice(textarea, start, end, text, {
      from: action.block.length,
      to: action.block.length + body.length,
    });
    return;
  }
  if (action.insert) {
    editorSplice(textarea, start, end, action.insert);
  }
}

//: **The shapes `editorApplyAction` does not implement.**
//:
//: MD_ACTIONS is bigger than the four shapes above: `custom` (image, footnote,
//: link, indent, undo…) and `pre`/`post` (the HTML-ish sup/sub/underline/
//: comment) are both handled by `applyMarkdown` in documents.js and by nothing
//: here. A "/" command wired straight to one of those through
//: `editorApplyAction` matches no branch and returns silently, this repo's
//: "a policy silently refusing the work" shape, and it would have shipped as
//: three menu rows that do nothing.
//:
//: `applyMarkdown` takes a box id and every editor surface has one, so this
//: is a call rather than a second implementation for the two to drift apart.
function editorApplyNamed(textarea, kind) {
  if (typeof applyMarkdown === "function" && textarea.id) {
    applyMarkdown(kind, textarea.id);
    return;
  }
  editorApplyAction(textarea, (typeof MD_ACTIONS === "object" && MD_ACTIONS[kind]) || {});
}

// A callout block, ready to type into.
//
// Every line of the body needs its own "> ", a blockquote ends at the first
// line that does not start with one, so a two-line callout written without the
// prefix on line two silently becomes a one-line callout followed by a
// paragraph. Getting that wrong is invisible until it renders.
function calloutTemplate(kind, fold = "") {
  const meta = CALLOUT_KINDS[kind] || CALLOUT_KINDS.note;
  return {
    block: `\n> [!${kind}]${fold} ${meta.label}\n> `,
    suffix: "\n",
    placeholder: "What matters about this?",
  };
}

// ---------------------------------------------------------------------------
// The command table
// ---------------------------------------------------------------------------

// `contexts` omitted means "everywhere". `keywords` exists so that typing
// "warn", "box" or "frame" finds the warning callout, the user asked for
// "specialised boxes and frames", which is nobody's idea of the word
// "callout", and a menu you can only search by its internal vocabulary is a
// menu you have to already know.
//: **What "/" offers in the chat box.** Not the note commands: a callout box
//: or a template pasted into a question is nobody's intent, and the document
//: AI actions have nowhere to run here. Each of these presses a control the
//: dock already has, so the menu is a second door to the same rooms and can
//: never drift from what the buttons do. The slash token is removed by
//: `editorRunItem` before `run` is called, so the question is left clean.
function chatCommands() {
  const press = (id) => () => document.getElementById(id)?.click();
  const pick = (source) => () => {
    if (typeof openNotePicker === "function") openNotePicker();
    document.querySelector(`#note-picker-sources [data-picker-source="${source}"]`)?.click();
  };
  const mode = (name) => () =>
    document.querySelector(`#chat-mode-seg button[data-chat-mode="${name}"]`)?.click();
  return [
    { id: "chat-attach-note", primary: true, group: "Attach", label: "\u{1F4DD} A note", hint: "as context", keywords: ["attach", "note", "reference", "context"], run: pick("notes") },
    { id: "chat-attach-document", primary: true, group: "Attach", label: "\u{1F4C4} A document", hint: "from Documents", keywords: ["attach", "document", "doc"], run: pick("documents") },
    { id: "chat-attach-file", primary: true, group: "Attach", label: "\u{1F4CE} A file", hint: "from the Library", keywords: ["attach", "file", "pdf", "spreadsheet"], run: pick("files") },
    { id: "chat-attach-image", group: "Attach", label: "\u{1F5BC}\u{FE0F} An image", hint: "from the Library", keywords: ["attach", "image", "picture", "photo", "sketch"], run: pick("images") },
    { id: "chat-upload", primary: true, group: "Attach", label: "\u{2B06}\u{FE0F} Upload something new", hint: "any file", keywords: ["upload", "new", "file", "attach"], run: press("attach-image") },
    { id: "chat-web", primary: true, group: "This message", label: "\u{1F310} Web search", hint: "toggle", keywords: ["web", "search", "online", "internet"], run: press("web-search-toggle") },
    { id: "chat-plan", primary: true, group: "This message", label: "\u{1F9ED} Plan first", hint: "toggle", keywords: ["plan", "steps", "think"], run: press("chat-plan") },
    { id: "chat-skills", primary: true, group: "This message", label: "\u{26A1} Skills", hint: "run a saved skill", keywords: ["skill", "skills", "run", "workflow"], run: press("chat-skills-btn") },
    { id: "chat-mode-agent", group: "Mode", label: "\u{1F916} Agent mode", hint: "let it act on the notebook", keywords: ["agent", "mode", "tools", "act"], run: mode("agent") },
    { id: "chat-mode-chat", group: "Mode", label: "\u{1F4AC} Ask mode", hint: "answer only", keywords: ["ask", "chat", "mode", "answer"], run: mode("chat") },
  ];
}

function editorCommands(context) {
  if (context === "chat") return chatCommands();
  const commands = [];

  for (const [kind, meta] of Object.entries(CALLOUT_KINDS)) {
    commands.push({
      id: `callout-${kind}`,
      group: "Blocks & frames",
      // Eight callout kinds would fill the whole menu on their own and push
      // Links, AI and Templates below the fold, which is exactly what a live
      // browser check caught. Four show by default; typing finds the rest.
      primary: ["note", "tip", "warning", "danger"].includes(kind),
      label: `${meta.icon} ${meta.label} box`,
      hint: `> [!${kind}]`,
      keywords: ["callout", "box", "frame", "admonition", kind, meta.label],
      run: (textarea) => editorApplyAction(textarea, calloutTemplate(kind)),
    });
  }

  // **Typed collapsible blocks**: REDESIGN.md §R7.3 item 3, and the last
  // piece of it. Asked for directly: "I want the structured note features and
  // elements from kortex with the slash commands to be rendered and easier
  // for the user to use."
  //
  // One command rather than eight more (a foldable variant of every callout
  // kind would double this menu, which a live browser check already caught
  // once as pushing Links and Templates below the fold). The kind is easy to
  // change afterwards, it is one word in the text, and "fold this away" is
  // the thing being asked for, not "fold this away, in orange".
  commands.push({
    id: "callout-fold",
    primary: true,
    group: "Blocks & frames",
    label: "\u{1F4C1} Collapsible section",
    hint: "> [!note]-: folded until clicked",
    keywords: ["fold", "collapse", "collapsible", "toggle", "details", "section", "hide"],
    run: (textarea) => editorApplyAction(textarea, calloutTemplate("note", "-")),
  });

  commands.push(
    {
      id: "table",
      primary: true,
      group: "Blocks & frames",
      label: "\u{1F4CA} Table",
      hint: "3 columns",
      keywords: ["table", "grid", "columns"],
      //: `editorApplyNamed`, not `editorApplyAction`: the table is a `custom`
      //: action now (it places the caret in the first header cell), and
      //: `editorApplyAction` knows only the four insertion shapes, so it would
      //: have matched nothing and inserted nothing, silently. Its own comment
      //: says so.
      run: (textarea) => editorApplyNamed(textarea, "table"),
    },
    {
      id: "codeblock",
      primary: true,
      group: "Blocks & frames",
      label: "\u{1F4BB} Code block",
      hint: "```",
      keywords: ["code", "fence", "snippet"],
      run: (textarea) => editorApplyAction(textarea, MD_ACTIONS.codeblock),
    },
    {
      id: "checklist",
      primary: true,
      group: "Blocks & frames",
      label: "\u{2611}\u{FE0F} Checklist",
      hint: "- [ ]",
      keywords: ["task", "todo", "check", "list"],
      run: (textarea) => editorApplyAction(textarea, MD_ACTIONS.task),
    },
    {
      id: "bullets",
      group: "Blocks & frames",
      label: "\u{2022} Bullet list",
      hint: "-",
      keywords: ["list", "bullet", "ul"],
      run: (textarea) => editorApplyAction(textarea, MD_ACTIONS.ul),
    },
    {
      id: "math",
      group: "Blocks & frames",
      label: "\u{1F9EE} Math",
      hint: "$\u2026$, rendered where you write it",
      keywords: ["math", "formula", "equation", "latex", "tex", "mathml"],
      run: (textarea) => editorApplyAction(textarea, MD_ACTIONS.math),
    },
    {
      id: "divider",
      primary: true,
      group: "Blocks & frames",
      label: "\u{2014} Divider",
      hint: "---",
      keywords: ["divider", "rule", "hr", "separator", "break"],
      run: (textarea) => editorApplyAction(textarea, MD_ACTIONS.hr),
    },
    {
      id: "heading",
      primary: true,
      group: "Blocks & frames",
      label: "\u{1F516} Section heading",
      hint: "##, becomes a jump target",
      keywords: ["heading", "section", "anchor", "title", "h2"],
      run: (textarea) => editorApplyAction(textarea, MD_ACTIONS.h2),
    },
    //: **The rest of the block vocabulary.** The toolbar has had these since
    //: the Obsidian-toolbar pass; the "/" menu had a subset, which makes the
    //: two disagree about what the editor can do, and "/" is the one people
    //: reach for once they stop reading the toolbar. Every one of them runs
    //: the same MD_ACTIONS entry the toolbar button runs, so there is no
    //: second dialect of the markdown to keep in step.
    {
      id: "h1",
      group: "Blocks & frames",
      label: "\u{1F5DE}\u{FE0F} Title heading",
      hint: "#",
      keywords: ["h1", "title", "heading", "big"],
      run: (textarea) => editorApplyAction(textarea, MD_ACTIONS.h1),
    },
    {
      id: "h3",
      group: "Blocks & frames",
      label: "\u{1F4D1} Sub-heading",
      hint: "###",
      keywords: ["h3", "sub", "heading", "small"],
      run: (textarea) => editorApplyAction(textarea, MD_ACTIONS.h3),
    },
    {
      id: "numbered",
      group: "Blocks & frames",
      label: "\u{1F522} Numbered list",
      hint: "1.",
      keywords: ["ordered", "numbered", "list", "ol", "steps"],
      run: (textarea) => editorApplyAction(textarea, MD_ACTIONS.ol),
    },
    {
      id: "quote",
      group: "Blocks & frames",
      label: "\u{201C} Quote",
      hint: ">",
      keywords: ["quote", "blockquote", "cite"],
      run: (textarea) => editorApplyAction(textarea, MD_ACTIONS.quote),
    }
  );

  // --- links & references ---
  commands.push(
    {
      id: "wikilink",
      primary: true,
      group: "Links & references",
      label: "\u{1F517} Link to a note",
      hint: "[[…]]",
      keywords: ["link", "note", "wiki", "reference", "connect"],
      // Insert the opening brackets and hand straight over to the [[ menu,
      // so "/" and "[[" are one continuous gesture rather than two lookups.
      run: (textarea) => {
        editorApplyAction(textarea, { insert: "[[" });
        editorOpenMenu(textarea, "[[");
      },
    },
    {
      id: "embed",
      primary: true,
      group: "Links & references",
      label: "\u{1F4CE} Embed a note inline",
      hint: "![[…]], shows its text here",
      keywords: ["embed", "transclude", "include", "inline", "note"],
      run: (textarea) => {
        editorApplyAction(textarea, { insert: "![[" });
        editorOpenMenu(textarea, "[[");
      },
    },
    {
      id: "image",
      group: "Links & references",
      label: "\u{1F5BC}\u{FE0F} Image",
      hint: "![alt](url): or paste a file into the editor",
      keywords: ["image", "picture", "photo", "figure", "screenshot"],
      run: (textarea) => editorApplyNamed(textarea, "image"),
    },
    {
      id: "footnote",
      group: "Links & references",
      label: "\u{1F4CC} Footnote",
      hint: "[^1]: with its text at the foot",
      keywords: ["footnote", "reference", "cite", "aside"],
      run: (textarea) => editorApplyNamed(textarea, "footnote"),
    },
    {
      id: "comment",
      group: "Links & references",
      label: "\u{1F576}\u{FE0F} Private comment",
      hint: "%%…%%, kept in the file, never rendered",
      keywords: ["comment", "private", "hidden", "todo", "note to self"],
      run: (textarea) => editorApplyNamed(textarea, "comment"),
    },
    {
      id: "weblink",
      primary: true,
      group: "Links & references",
      label: "\u{1F310} Web link",
      hint: "[text](url)",
      keywords: ["url", "web", "href", "external"],
      run: (textarea) => {
        const { selectionStart: s, selectionEnd: e, value } = textarea;
        const label = value.slice(s, e) || "link text";
        editorSplice(textarea, s, e, `[${label}](https://)`, {
          from: label.length + 3,
          to: label.length + 11,
        });
      },
    }
  );

  //: **Properties**, the one block whose position is not the caret's:
  //: `docInsertProperties` puts it at the top of the document, or puts the
  //: caret in the block that is already there. Documents only, and pushed here
  //: rather than declared with a `contexts` field, because the filter the
  //: comment above describes is this `if`: nothing reads `contexts`.
  if (context === "document") {
    commands.push({
      id: "properties",
      primary: true,
      group: "Blocks & frames",
      label: "\u{1F3F7}\u{FE0F} Properties",
      hint: "tags, status, dates",
      keywords: ["properties", "frontmatter", "metadata", "tags", "yaml", "status", "aliases"],
      run: (textarea) => editorApplyNamed(textarea, "properties"),
    });
    //: Columns, for the same reason: the `:::columns` fence renders as columns
    //: in this editor and as three lines of literal text anywhere else, so
    //: offering it in the capture box would be offering a block that only
    //: looks like one somewhere the writer cannot see.
    //: **Link to this block**, the copy half of a block reference. It inserts
    //: nothing where the caret is: it gives the caret's own paragraph an id
    //: (if it has none yet) and puts `[[Title#^id]]` on the clipboard, which
    //: is the form you paste into a note, a map node or a chat. Documents
    //: only, because the id has to be written into a document's text and the
    //: capture box has no document to write it into.
    commands.push({
      id: "blockref",
      group: "Links & references",
      label: "\u{1F517} Link to this block",
      hint: "copies [[Title#^id]]",
      keywords: ["block", "reference", "anchor", "paragraph", "permalink", "copy link", "^"],
      run: (textarea) => editorApplyNamed(textarea, "blockref"),
    });
    commands.push({
      id: "columns",
      primary: true,
      group: "Blocks & frames",
      label: "\u{1F4D1} Two columns",
      hint: ":::columns",
      keywords: ["columns", "column", "two", "side", "split", "grid", "layout"],
      run: (textarea) => editorApplyNamed(textarea, "columns"),
    });
  }

  // --- AI actions ---
  // Document-only, because these route to the document editor's own AI panel
  // and extract-notes preview. Offering them in the capture box would open a
  // panel pointed at whatever document happened to be loaded, acting on text
  // the user cannot see is worse than not offering the command.
  if (context === "document") {
    commands.push(
      {
        //: **The one AI command that does not open a panel.** First in the
        //: group and `primary`, because it is the one that answers the ask
        //: ("the agent or ai needs to be more directly integrated into the
        //: documents"), the other two below are doors to the side pane, which
        //: is the right place for "review the whole document" and the wrong
        //: place for "make this shorter".
        id: "ai-inline",
        primary: true,
        group: "AI",
        label: "\u{2728} Ask the AI to write here",
        hint: "at the cursor \u{2014} Ctrl+J",
        keywords: ["ai", "write", "inline", "here", "cursor", "ask", "generate", "continue"],
        run: (textarea) => inlineAiOpen(textarea),
      },
      {
        id: "ai-edit",
      primary: true,
        group: "AI",
        label: "\u{2728} AI edit this selection",
        hint: "rewrite, expand, tighten",
        keywords: ["ai", "rewrite", "improve", "expand", "edit"],
        run: () => $("doc-ai")?.click(),
      },
      {
        id: "ai-extract",
      primary: true,
        group: "AI",
        label: "\u{2702}\u{FE0F} Extract notes from here",
        hint: "split into linked notes",
        keywords: ["ai", "extract", "split", "notes"],
        run: () => $("doc-extract")?.click(),
      }
    );
  }

  // --- templates & stamps ---
  const now = new Date();
  commands.push(
    {
      id: "stamp-date",
      primary: true,
      group: "Templates",
      label: "\u{1F4C5} Today's date",
      hint: now.toLocaleDateString(),
      keywords: ["date", "today", "stamp"],
      run: (textarea) => editorApplyAction(textarea, { insert: now.toLocaleDateString() }),
    },
    {
      id: "stamp-time",
      group: "Templates",
      label: "\u{1F551} Time now",
      hint: now.toLocaleTimeString(),
      keywords: ["time", "now", "stamp", "clock"],
      run: (textarea) =>
        editorApplyAction(textarea, {
          insert: now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        }),
    }
  );

  // The user's own templates first, then the built-ins, the same "yours
  // before ours" ordering loadTemplates() already uses for the dropdown.
  const custom = (typeof prefsCache !== "undefined" && prefsCache?.custom_templates) || [];
  const builtin = typeof BUILTIN_TEMPLATES !== "undefined" ? BUILTIN_TEMPLATES : [];
  for (const template of [...custom, ...builtin]) {
    if (!template?.name || !template?.content) continue;
    commands.push({
      id: `template-${template.name}`,
      group: "Templates",
      label: `\u{1F4C4} ${template.name}`,
      hint: "template",
      keywords: ["template", template.name],
      run: (textarea) =>
        editorApplyAction(textarea, {
          // Same {date} substitution applyTemplate() does, so a template
          // behaves identically whichever way it was reached.
          insert: template.content.replace("{date}", now.toLocaleDateString()),
        }),
    });
  }

  return commands;
}

// ---------------------------------------------------------------------------
// The popup itself
// ---------------------------------------------------------------------------

const editorMenuState = {
  open: false,
  textarea: null,
  trigger: null, // "/" or "[["
  items: [],
  index: 0,
  start: 0, // index in textarea.value where the trigger token begins
};

// Where the caret is, in page coordinates.
//
// **One answer for the whole app, asked of the surface itself.** This used to
// be a second mirror implementation: an invisible div with the same text
// metrics, a marker span where the caret is, measured and thrown away, which
// is the only thing a `<textarea>` can do because it exposes no caret
// geometry at all. documents.js has the same technique in `docMirrorPoint`,
// and two copies of a measurement this fiddly is two things to keep in step.
//
// The adapter already has to answer this question for CodeMirror (which does
// have a real API for it, `coordsAtPos`), so it answers it for a textarea too
// and this becomes the one line it always wanted to be. `lineHeight` comes
// back with the point because every caller here places its popup *under* the
// caret's line and needs to know how tall the line is.
function editorCaretPoint(textarea) {
  const at = textarea.coordsAt(textarea.selectionStart);
  return { top: at.top, left: at.left, lineHeight: at.lineHeight };
}

// Put the menu at the caret, then pull it back on screen if it would hang off
// the bottom or the right, a menu you have to scroll the page to read is the
// same as no menu.
function editorPositionMenu(textarea) {
  const menu = $("editor-menu");
  const { top, left, lineHeight } = editorCaretPoint(textarea);
  menu.style.top = "0px";
  menu.style.left = "0px";
  const size = menu.getBoundingClientRect();
  const margin = 8;

  let y = top + lineHeight + 4;
  // Not enough room below: flip above the caret line instead of overflowing.
  if (y + size.height > window.innerHeight - margin) {
    const above = top - size.height - 4;
    y = above > margin ? above : Math.max(margin, window.innerHeight - size.height - margin);
  }
  const x = Math.max(margin, Math.min(left, window.innerWidth - size.width - margin));
  menu.style.top = `${Math.round(y)}px`;
  menu.style.left = `${Math.round(x)}px`;
}

function editorCloseMenu() {
  editorMenuState.open = false;
  editorMenuState.textarea = null;
  editorMenuState.items = [];
  $("editor-menu")?.classList.add("hidden");
}

// The half-typed token immediately before the caret, or null.
//
// "/" only counts at the start of a line or after whitespace, so "and/or",
// "24/7" and a URL never open the menu. "[[" can appear anywhere, because
// there is nothing else it could plausibly mean.
function editorTokenAt(textarea, trigger) {
  const upto = textarea.value.slice(0, textarea.selectionStart);
  const open = upto.lastIndexOf(trigger);
  if (open === -1) return null;
  const fragment = upto.slice(open + trigger.length);
  // A newline means they moved on and left the token behind.
  if (fragment.includes("\n")) return null;
  if (trigger === "[[" && upto.slice(open).includes("]]")) return null;
  if (trigger === "/") {
    const before = open === 0 ? "\n" : upto[open - 1];
    if (!/\s/.test(before)) return null;
    // A slash command is one word. Once a space is typed it is prose.
    if (/\s/.test(fragment)) return null;
  }
  return { start: open, fragment };
}

// Rank matches: a label that starts with what was typed beats one that merely
// contains it, which beats a keyword hit. Without the ordering, typing "no"
// offers "Bullet list" (it contains no "no"… but "Note box" and "Today's
// date" both match on keywords) in an order that looks arbitrary.
function editorRankCommands(commands, needle) {
  if (!needle) return commands;
  const query = needle.toLowerCase();
  const scored = [];
  for (const command of commands) {
    const label = command.label.toLowerCase();
    const keywords = (command.keywords || []).map((k) => String(k).toLowerCase());
    let score = -1;
    if (label.startsWith(query)) score = 0;
    else if (keywords.some((k) => k.startsWith(query))) score = 1;
    else if (label.includes(query)) score = 2;
    else if (keywords.some((k) => k.includes(query))) score = 3;
    if (score >= 0) scored.push({ command, score });
  }
  scored.sort((a, b) => a.score - b.score);
  return scored.map((s) => s.command);
}

// The notes a "[[" token could mean. Private notes are excluded for the same
// reason app.js's own [[ suggest excludes them: they cannot be link targets,
// so offering one is a dead end that also reveals it exists.
function editorLinkMatches(needle) {
  const query = (needle || "").trim().toLowerCase();
  const notes = (typeof allEntries !== "undefined" ? allEntries : [])
    .filter((e) => !e.is_private && (!query || (e.content || "").toLowerCase().includes(query)))
    .slice(0, 6)
    .map((entry) => ({
      id: `note-${entry.id}`,
      group: "Notes",
      label: noteLabel(entry, 60),
      hint: "note",
      // Link by the note's opening words: that is what resolution matches
      // on. Brackets are stripped first: a note that itself contains a
      // [[link]] would otherwise be inserted verbatim, and the parser would
      // then find the INNER brackets and resolve to the wrong note.
      value: (entry.content || "")
        .split("\n")[0]
        .replace(/\[\[|\]\]/g, "")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 60),
    }))
    .filter((item) => item.value);

  // Documents are link targets too, that is Phase B's whole point, and it is
  // why this list is built here rather than reusing app.js's note-only one.
  const documents = (editorDocumentCache || [])
    .filter((doc) => !query || (doc.title || "").toLowerCase().includes(query))
    .slice(0, 4)
    .map((doc) => ({
      id: `doc-${doc.id}`,
      group: "Documents",
      label: doc.title || "Untitled",
      hint: "document",
      value: (doc.title || "").replace(/\[\[|\]\]/g, "").trim().slice(0, 60),
    }))
    .filter((item) => item.value);

  //: **Files and images**, the third and fourth kinds. They are not wiki-link
  //: targets, there is no name to resolve, only a url, so each carries the
  //: markdown it wants inserted (`item.markdown`, handled in `editorRunItem`):
  //: an embed for a picture, a plain link for anything else.
  const files = (editorFileCache || [])
    .filter((file) => !query || (file.original_name || "").toLowerCase().includes(query))
    .slice(0, 4)
    .map((file) => ({
      id: `file-${file._isAttachment ? "a" : "m"}-${file.id}`,
      group: file._isImage ? "Images" : "Files",
      label: file.original_name || "File",
      hint: file._isImage ? "image" : "file",
      markdown: `${file._isImage ? "!" : ""}[${(file.original_name || "file").replace(/[[\]]/g, "")}](${file.url})`,
    }));

  //: **Boards.** A board *is* an Entry (`is_board`) and used to be found in
  //: `allEntries`, but `GET /entries` is the notes list and no longer
  //: returns boards at all (reported: a mind map called "test" appeared in
  //: the Notes list as a note), so the source is now `/whiteboard/boards`
  //: through the same index the map chips read. A notebook with boards still
  //: has to be able to link to one.
  //: Not awaited, and only when the index is empty: this function is
  //: synchronous (it runs on every keystroke of a `[[` token), so the most it
  //: can do is ask for the list and let the *next* keystroke show it. The
  //: request itself is cached for 8s inside `loadMapBoardIndex`, so a burst
  //: of typing costs one call.
  if (typeof mapBoardRows === "function" && !mapBoardRows().length
      && typeof loadMapBoardIndex === "function") {
    loadMapBoardIndex();
  }
  const boards = (typeof mapBoardRows === "function" ? mapBoardRows() : [])
    .filter((b) => b.id != null)
    .filter((b) => !query || String(b.title || "").toLowerCase().includes(query))
    .slice(0, 3)
    .map((board) => ({
      id: `board-${board.id}`,
      group: "Boards",
      label: String(board.title || "Untitled board").slice(0, 60),
      hint: board.type === "map" ? "mind map" : "board",
      //: **The board's title, not its first raw line.** A board's content is
      //: `# My map`, so this used to insert `[[# My map]]`, which resolved
      //: (the resolver matched by prefix) and read as a stray heading marker
      //: inside a sentence. `resolveWikiTarget` matches a board title with or
      //: without the `#`, so links written the old way still resolve. The
      //: board row's own `title` arrives with the `# ` already stripped, so
      //: the cleaning below is only about brackets and runs of whitespace.
      value: String(board.title || "")
        .replace(/\[\[|\]\]/g, "")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 60),
    }))
    .filter((item) => item.value);

  return [...notes, ...documents, ...boards, ...files];
}

//: The Library's own gallery payload, fetched once per menu session the same
//: way documents are: `/media` and `/files/gallery` are two calls, and doing
//: them per keystroke would put a request behind every letter typed.
let editorFileCache = null;

async function editorLoadFiles() {
  if (editorFileCache && editorFileCache.length) return;
  const [media, attachments] = await Promise.all([
    //: Read to the end (`apiPagedList`, documents.js): `GET /media` returns
    //: a page now (INBOX 117), and this cache is what the `/` and `[[` menus
    //: offer. A picker missing a file is a file you cannot insert, with
    //: nothing on screen to say it exists.
    apiPagedList("/media", MEDIA_PAGE_SIZE, { silent: true }).catch(() => []),
    apiJson("/files/gallery", { silent: true }).catch(() => []),
  ]);
  const rows = [
    ...(Array.isArray(media) ? media : []).map((row) => ({ ...row, _isAttachment: false })),
    ...(Array.isArray(attachments) ? attachments : []).map((row) => ({
      ...row,
      _isAttachment: true,
      url: `/files/${row.id}`,
    })),
  ];
  //: `_isImage` decides embed-or-link, and it is decided here once rather
  //: than by each caller re-sniffing the extension, the same split
  //: `library.js` makes for the gallery.
  editorFileCache = rows.map((row) => ({
    ...row,
    _isImage: /\.(png|jpe?g|gif|webp|bmp|svg|avif|heic|heif|tiff?)$/i.test(row.original_name || ""),
  }));
}

// Documents are fetched once per menu session rather than per keystroke.
let editorDocumentCache = null;

function editorRenderMenu() {
  const menu = $("editor-menu");
  const { items, index } = editorMenuState;
  if (!items.length) return editorCloseMenu();

  menu.replaceChildren();
  let lastGroup = null;
  items.forEach((item, position) => {
    if (item.group && item.group !== lastGroup) {
      const heading = document.createElement("li");
      heading.className = "editor-menu-group";
      heading.setAttribute("role", "presentation");
      heading.textContent = item.group;
      menu.appendChild(heading);
      lastGroup = item.group;
    }
    const row = document.createElement("li");
    row.setAttribute("role", "option");
    row.setAttribute("aria-selected", String(position === index));
    row.className = "editor-menu-item";
    if (position === index) row.classList.add("active");

    const label = document.createElement("span");
    label.className = "editor-menu-label";
    label.textContent = item.label;
    row.appendChild(label);
    if (item.hint) {
      const hint = document.createElement("span");
      hint.className = "editor-menu-hint";
      hint.textContent = item.hint;
      row.appendChild(hint);
    }
    // mousedown, not click: the textarea must not lose focus first, or the
    // caret position the insertion depends on is already gone.
    row.addEventListener("mousedown", (event) => {
      event.preventDefault();
      editorRunItem(position);
    });
    menu.appendChild(row);
  });

  menu.classList.remove("hidden");
  editorPositionMenu(editorMenuState.textarea);
}

// Apply the highlighted item: drop the trigger token that summoned the menu,
// then let the item do its work at that spot.
function editorRunItem(position) {
  const { textarea, trigger, items } = editorMenuState;
  const item = items[position];
  if (!item || !textarea) return editorCloseMenu();

  const token = editorTokenAt(textarea, trigger);
  if (token) {
    // Remove "/table" (or "[[part") so the command's own text replaces it.
    const keep = trigger === "[[" ? token.start + trigger.length : token.start;
    textarea.value =
      textarea.value.slice(0, keep) + textarea.value.slice(textarea.selectionStart);
    textarea.setSelectionRange(keep, keep);
  }
  editorCloseMenu();

  if (item.markdown !== undefined) {
    //: **A file is not a `[[wiki link]]`.** Wiki links resolve by *name*
    //: against notes and documents; an image or an attachment has a url and
    //: no name to resolve, so an item like that carries the markdown it wants
    //: inserted and the opening `[[` the trigger left behind is removed
    //: first. Asked for as "cross-link everything: notes, documents, files,
    //: maps from anywhere", the picker covered two of the four.
    const at = textarea.selectionStart;
    const open = trigger === "[[" ? at - trigger.length : at;
    editorSplice(textarea, open, at, item.markdown, null);
  } else if (item.value !== undefined) {
    // A link target: close the brackets and step past them.
    const at = textarea.selectionStart;
    editorSplice(textarea, at, at, `${item.value}]]`, null);
  } else if (typeof item.run === "function") {
    item.run(textarea);
  }
}

function editorOpenMenu(textarea, trigger) {
  editorMenuState.open = true;
  editorMenuState.textarea = textarea;
  editorMenuState.trigger = trigger;
  editorMenuState.index = 0;
  editorRefreshMenu();
}

// Recompute what the menu should show for whatever is currently before the
// caret. Called on every keystroke while open.
function editorRefreshMenu() {
  const { textarea, trigger } = editorMenuState;
  if (!textarea || !trigger) return editorCloseMenu();
  const token = editorTokenAt(textarea, trigger);
  if (!token) return editorCloseMenu();

  editorMenuState.start = token.start;
  const context = editorSurfaceKind(textarea) || "note";
  let items;
  if (trigger === "/") {
    const all = editorCommands(context);
    // With nothing typed, show a curated shortlist so that every group is
    // represented and reachable; once there is a query, search the full set.
    // Found the hard way: a flat cap over an alphabetically-grouped list meant
    // Links, AI and Templates were unreachable without already knowing to type
    // for them, which defeats the point of a discovery menu.
    const pool = token.fragment ? all : all.filter((c) => c.primary);
    items = editorRankCommands(pool, token.fragment);
  } else {
    items = editorLinkMatches(token.fragment);
  }

  // The menu scrolls (max-height in CSS), so the cap only exists to stop a
  // pathological list, not to fit the viewport.
  editorMenuState.items = items.slice(0, 20);
  editorMenuState.index = Math.min(editorMenuState.index, Math.max(0, editorMenuState.items.length - 1));
  editorRenderMenu();
}

// ---------------------------------------------------------------------------
// Wiring: one delegated listener per event, for every surface at once
// ---------------------------------------------------------------------------

//: **Called, not only listened for.** A `<textarea>` raises `input` for every
//: character and this file has always hung the trigger check off that. The
//: engine does not: CodeMirror applies a typed character itself, through its
//: own transaction pipeline, and no bubbling `input` reaches this listener at
//: all. Measured, not reasoned: with the engine mounted the "/" menu and the
//: `[[` picker simply never opened, and nothing logged, which is this repo's
//: "a policy silently refusing the work" shape in the one place it is hardest
//: to notice, because both menus look like they are just not wanted yet.
//:
//: So the body is a function, and documents.js's update listener calls it for
//: the engine. One implementation, two ways in.
function editorHandleInput(textarea) {
  if (!textarea) return;
  if (!editorSurfaceKind(textarea)) return;

  if (editorMenuState.open && editorMenuState.textarea === textarea) {
    editorRefreshMenu();
    return;
  }
  // Not open yet: does what was just typed start a token?
  //
  // The capture box keeps its own [[ autocomplete (app.js's #wiki-suggest),
  // which predates this file and is wired, styled and tested. Two menus racing
  // for the same trigger in the same box would both open. So "[[" is claimed
  // here only for surfaces that had nothing before, today, the document
  // editor. Migrating capture onto this one mechanism is worth doing, but as
  // its own change, not folded into the diff that introduces the mechanism.
  const claimsWiki = textarea.id !== "entry-content";
  for (const trigger of claimsWiki ? ["/", "[["] : ["/"]) {
    if (editorTokenAt(textarea, trigger)) {
      if (trigger === "[[") {
        // Fetch documents once, then redraw, the list opens on notes alone
        // and gains documents a moment later rather than blocking on a fetch.
        if (editorDocumentCache === null) {
          editorDocumentCache = [];
          //: Paged to the end, same reason as the file cache above: a
          //: document missing from this list is a `[[link]]` the menu
          //: cannot offer, silently.
          apiPagedList("/documents", DOCUMENTS_PAGE_SIZE)
            .then((docs) => {
              editorDocumentCache = Array.isArray(docs) ? docs : [];
              if (editorMenuState.open) editorRefreshMenu();
            })
            .catch(() => {
              editorDocumentCache = [];
            });
        }
        //: Files and images the same way: the menu opens on what is already
        //: in memory and gains the rest a moment later, rather than making
        //: the first keystroke wait on two requests.
        if (editorFileCache === null) {
          editorFileCache = [];
          editorLoadFiles().then(() => {
            if (editorMenuState.open) editorRefreshMenu();
          });
        }
      }
      editorOpenMenu(textarea, trigger);
      return;
    }
  }
}

document.addEventListener("input", (event) => {
  //: The engine's own edits arrive through `editorHandleInput` above, called
  //: from documents.js's update listener. Anything from inside the view that
  //: *does* raise a DOM `input` (a paste, in some browsers) would otherwise
  //: run the check a second time and reopen a menu the first pass closed.
  if (typeof docEventFromCm === "function" && docEventFromCm(event.target)) return;
  editorHandleInput(editorSurfaceFor(event.target));
});

document.addEventListener(
  "keydown",
  (event) => {
    if (!editorMenuState.open) return;
    //: Compared as *surfaces*: the event target inside CodeMirror is whichever
    //: line element the caret is in, never the object the menu was opened on.
    if (editorSurfaceFor(event.target) !== editorMenuState.textarea) return;
    const { items } = editorMenuState;

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!items.length) return;
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      editorMenuState.index = (editorMenuState.index + step + items.length) % items.length;
      editorRenderMenu();
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      if (!items.length) return;
      event.preventDefault();
      // stopPropagation as well as preventDefault: the capture box submits on
      // Ctrl+Enter and the document editor has its own Enter handling, and
      // choosing from a menu must not also trigger the surface behind it.
      event.stopPropagation();
      editorRunItem(editorMenuState.index);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      editorCloseMenu();
    }
  },
  true // capture phase, so the menu answers before the surface's own handlers
);

// Clicking anywhere else, or moving the caret with the mouse, dismisses it.
document.addEventListener("mousedown", (event) => {
  if (!editorMenuState.open) return;
  if ($("editor-menu")?.contains(event.target)) return;
  editorCloseMenu();
});

// Scrolling the *page* moves the caret out from under a menu anchored to it,
// so the menu closes. Scrolling *inside the menu itself* must not, reported
// directly: "the popup options for commands aren't scrollable and disappear
// when I try to scroll them". This listener is on the capture phase, so it saw
// the menu's own wheel-scroll before it reached the menu and shut it every
// time, which is exactly the shape of bug that makes a list look un-scrollable
// rather than merely short.
document.addEventListener(
  "scroll",
  (event) => {
    if (!editorMenuState.open) return;
    const menu = $("editor-menu");
    if (menu && (event.target === menu || menu.contains(event.target))) return;
    editorCloseMenu();
  },
  true
);

window.addEventListener("resize", () => editorMenuState.open && editorCloseMenu());

// ---------------------------------------------------------------------------
// The selection toolbar
// ---------------------------------------------------------------------------
//
// Asked for with a link to Obsidian's editing-toolbar plugin: *"pease upgrade
// the way the toolbar works in everything to be like this obsidian toolbar
// plugin. Ive used it and it is great."*
//
// The thing that plugin actually changes is **where the buttons are**, not
// which ones exist: this app's fixed toolbar already has more of them. A bar
// that follows the text you selected puts formatting where you are looking,
// instead of at the top of a panel you may have scrolled a screen away from.
//
// Built on the two pieces that were already here: `editorCaretPoint` (a
// textarea has no Range, so the caret is measured with a mirror element) and
// `applyMarkdown` (documents.js), so this adds a *place*, not a second opinion
// about what `**` means. Nothing here knows any markdown.
const SELECTION_BAR_ACTIONS = [
  { md: "bold", label: "ph:text-b", title: "Bold (Ctrl+B)" },
  { md: "italic", label: "ph:text-italic", title: "Italic (Ctrl+I)" },
  { md: "strike", label: "ph:text-strikethrough", title: "Strikethrough" },
  { md: "highlight", label: "ph:highlighter", title: "Highlight" },
  { md: "code", label: "ph:code", title: "Inline code" },
  { md: "link", label: "ph:link", title: "Link" },
  { md: "h2", label: "ph:text-h", title: "Heading" },
  { md: "quote", label: "ph:quotes", title: "Quote" },
  //: **Not a formatting action, and it says so with a rule beside it.**
  //: REDESIGN.md §R7.1 item 1, quoted from the request: *"able to highlight
  //: text and say something in the chat and the agent gets the context of
  //: what is highlighted and cursor position."* It is the highest ratio of
  //: "feels capable" to work in that whole section, and this bar is already
  //: the thing on screen the moment a selection exists, a second control
  //: somewhere else would be a second thing to find.
  { ask: true, label: "ph:chat-teardrop-text", title: "Ask the AI about this selection" },
  //: **The second half of that pair: change it here, rather than talk about
  //: it there.** Asking sends the selection to the chat and leaves the text
  //: alone; this rewrites the selection in place. They belong next to each
  //: other because the choice between them is the whole decision, and a
  //: selection is the moment it gets made. Document surfaces only: see
  //: `inlineAiAvailable`, so the button is skipped where it could not work.
  { inlineAi: true, label: "ph:magic-wand", title: "Rewrite this with AI (Ctrl+J)" },
];

const selectionBarState = { textarea: null };

function selectionBarElement() {
  let bar = $("selection-bar");
  if (bar) return bar;
  //: Built once, lazily, rather than sitting in index.html: it belongs to this
  //: file's behaviour, and a hidden bar in the markup would be one more thing
  //: for the id/duplicate-listener lints to police for no gain.
  bar = document.createElement("div");
  bar.id = "selection-bar";
  bar.className = "selection-bar hidden";
  bar.setAttribute("role", "toolbar");
  bar.setAttribute("aria-label", "Format the selection");
  for (const action of SELECTION_BAR_ACTIONS) {
    if (action.ask) {
      //: A hairline, so "ask about this" does not read as a ninth way to
      //: change the text. Same separator the chat dock's control strip uses
      //: between its own groups.
      const rule = document.createElement("span");
      rule.className = "selection-bar-rule";
      rule.setAttribute("aria-hidden", "true");
      bar.appendChild(rule);
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost small icon-button";
    if (action.inlineAi) button.dataset.inlineAi = "1";
    if (action.md) button.dataset.md = action.md;
    button.title = action.title;
    button.setAttribute("aria-label", action.title);
    setLabel(button, action.label);
    //: `mousedown`, not `click`, and prevented: a click would first move focus
    //: out of the textarea, and the browser drops the selection on the way, 
    //: so by the time the handler ran there would be nothing selected to wrap.
    button.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const textarea = selectionBarState.textarea;
      if (!textarea) return;
      if (action.ask) {
        askAboutSelection(textarea);
        selectionBarHide();
        return;
      }
      if (action.inlineAi) {
        //: The selection is read from the textarea *before* the bar takes
        //: focus, which `inlineAiOpen` does on its first two lines, the same
        //: reason this whole handler is on `mousedown`.
        inlineAiOpen(textarea);
        return;
      }
      applyMarkdown(action.md, textarea.id);
      //: Deliberately *not* hidden here. `applyMarkdown` leaves the text it
      //: wrapped selected, so the bar re-anchors to it on the next
      //: `selectionchange`, which is what lets bold-then-italic be two
      //: presses rather than a re-selection between them. Hiding it made the
      //: bar blink out and straight back in.
    });
    bar.appendChild(button);
  }
  document.body.appendChild(bar);
  return bar;
}

function selectionBarHide() {
  selectionBarState.textarea = null;
  $("selection-bar")?.classList.add("hidden");
}

function selectionBarShow(textarea) {
  const bar = selectionBarElement();
  selectionBarState.textarea = textarea;
  //: Shown only where it can run. A control that is present and refuses is
  //: worse than one that is absent: the first teaches that the feature is
  //: broken, the second that it belongs to documents.
  const magic = bar.querySelector("[data-inline-ai]");
  if (magic) magic.hidden = !inlineAiAvailable(textarea);
  bar.classList.remove("hidden");
  //: Anchored to the *start* of the selection, which is where the eye is when
  //: a selection is made left-to-right, and measured after the bar is visible
  //: so its size is real rather than zero.
  const { top, left, lineHeight } = editorCaretPoint(textarea);
  const size = bar.getBoundingClientRect();
  const margin = 8;
  //: **The boundary is the editing pane, and now that is the surface itself.**
  //: This used to need a special case: the Live view gave every paragraph its
  //: own box, so the caret's box was the top of *that paragraph*, and the rule
  //: below read every selection in Live as "on the first line, flip the bar
  //: below it". Measured at the time: selecting inside the third paragraph put
  //: the bar at y=358 against a selection at y=328, under the words instead of
  //: above them. With one editor in every view the surface's own rectangle is
  //: the pane's, and the special case goes.
  const boxTop = textarea.getBoundingClientRect().top;
  let y = top - size.height - 6;
  //: **Above the line, unless that means on top of the fixed toolbar.** Every
  //: editing surface in this app has its own formatting row immediately above
  //: the textarea, so a selection on the *first* line put this bar straight
  //: over it: measured, and it read as two toolbars stacked rather than as a
  //: bar belonging to the selection. Below the line in that case: it covers
  //: the next line of the note instead, which is text you can scroll to and
  //: not a control you might press by mistake.
  if (y < Math.max(margin, boxTop)) y = top + (lineHeight || 20) + 6;
  const x = Math.max(margin, Math.min(left, window.innerWidth - size.width - margin));
  bar.style.top = `${Math.round(y)}px`;
  bar.style.left = `${Math.round(x)}px`;
}

//: One predicate, so the selection bar and the "/" menu cannot disagree about
//: what an editing surface is. They did: this used to be its own class check
//: while the "/" menu gated on `EDITOR_SURFACES` alone, which is how the live
//: view ended up with a selection bar and no slash menu.
function isEditorSurface(node) {
  return editorSurfaceKind(node) !== null;
}

function selectionBarSync() {
  //: The inline AI bar anchors to the same caret and leaves its answer
  //: *selected* on purpose, so without this the two bars stack on top of each
  //: other the moment an answer lands, and the one underneath is the one with
  //: Keep and Undo on it.
  if (inlineAiState.phase !== "idle") return selectionBarHide();
  const active = editorSurfaceFor(document.activeElement);
  if (!isEditorSurface(active)) {
    return selectionBarHide();
  }
  //: A caret is not a selection. Nothing appears until there is text to act
  //: on, which is what keeps this from being a bar that hovers over the note
  //: while you type.
  if (active.selectionStart === active.selectionEnd) return selectionBarHide();
  selectionBarShow(active);
}

//: `selectionchange` is the one event that fires for *every* way a selection
//: can change, drag, shift+arrow, double-click, select-all, undo, where
//: mouseup/keyup each miss several. It fires on `document`, not the element.
document.addEventListener("selectionchange", selectionBarSync);
//: The bar is positioned in viewport coordinates against a caret that moves
//: when anything scrolls, so it re-anchors rather than drifting away from the
//: text it belongs to. Capture, because the scroller is usually a descendant.
document.addEventListener("scroll", () => selectionBarState.textarea && selectionBarSync(), true);
window.addEventListener("resize", () => selectionBarState.textarea && selectionBarSync());
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && selectionBarState.textarea) selectionBarHide();
});

//: How much text either side of the selection travels with it. Enough that a
//: pronoun in the selection ("why does *it* do that?") has an antecedent, and
//: small enough that a selection made in a 40,000-character document does not
//: quietly become the whole document, the harness budgets tool *results*
//: (§R5 item 4) but the question itself is not a tool result, so nothing else
//: would bound this.
const SELECTION_CONTEXT_MARGIN = 240;

//: Where the selection sits, in a form the model can be told about and the
//: app can re-check later. `line`/`column` are 1-based because that is what
//: every editor in the world shows the user, and the number is going into a
//: chip they read.
function selectionContextFrom(textarea) {
  //: **One set of coordinates.** This used to translate a live-view
  //: paragraph's own offsets into the document's, because Live gave every
  //: paragraph its own box and left alone this would have told the model
  //: "line 2" for the last paragraph of a long document. DOCUMENTS_PLAN
  //: Phase 2 made Live and Source one editor, so a selection is already in
  //: the document's coordinates wherever it was made.
  return selectionOffsets(textarea, textarea.selectionStart, textarea.selectionEnd);
}

function selectionOffsets(textarea, start, end) {
  const value = textarea.value;
  const text = value.slice(start, end);
  const upToCaret = value.slice(0, end);
  const line = upToCaret.split("\n").length;
  const column = end - (upToCaret.lastIndexOf("\n") + 1) + 1;
  return {
    surfaceId: textarea.id,
    kind: editorSurfaceKind(textarea) || "note",
    start,
    end,
    text,
    line,
    column,
    before: value.slice(Math.max(0, start - SELECTION_CONTEXT_MARGIN), start),
    after: value.slice(end, end + SELECTION_CONTEXT_MARGIN),
  };
}

//: The label on the chip, and the only place that knows which surface belongs
//: to which thing. `entry-content` deliberately has no id: it is a note being
//: written that does not exist yet, and a selection from it is still worth
//: asking about: the text is what matters, not a row in the database.
function selectionContextSource(surfaceId) {
  if (surfaceId === "doc-content") {
    const doc = typeof currentDoc !== "undefined" ? currentDoc : null;
    return { title: doc?.title || "this document", entityKind: "document", entityId: doc?.id ?? null };
  }
  if (surfaceId === "entry-edit-content") {
    const entry =
      typeof allEntries !== "undefined" && typeof editingId !== "undefined"
        ? allEntries.find((e) => e.id === editingId)
        : null;
    return {
      title: entry ? noteLabel(entry, 40) : "this note",
      entityKind: "note",
      entityId: entry?.id ?? null,
    };
  }
  return { title: "the note you're writing", entityKind: "note", entityId: null };
}

function askAboutSelection(textarea) {
  //: The *resolved* surface, not the textarea that was focused: a live-view
  //: block reports itself as `doc-content` (see `selectionContextFrom`), and
  //: looking the label up by the block's own id would call a document "the
  //: note you're writing".
  const where = selectionContextFrom(textarea);
  const context = { ...where, ...selectionContextSource(where.surfaceId) };
  if (!context.text.trim()) return;
  attachSelectionContext(context);
}

// ---------------------------------------------------------------------------
// Create-on-miss: a link to something that does not exist yet
// ---------------------------------------------------------------------------

// confirmDialog's three-way sibling. Built here rather than generalising
// confirmDialog because that function's contract is a boolean, and widening it
// to return a string would mean auditing all of its call sites for a truthy
// check that now passes on "cancel".
//
// The DOM shape, the captured Escape handler, the backdrop click and the
// "focus the safe option, not the committing one" rule are all copied from
// confirmDialog deliberately: a second dialog that behaves differently from
// the app's own is worse than no dialog.
function editorChoiceDialog(message, choices) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay confirm-overlay";
    overlay.setAttribute("role", "dialog");
    // aria-modal, because this one genuinely is: the page behind it is inert
    // until it is answered. (The focus trap keys off exactly this attribute, 
    // see HANDOVER.md on the 13 anchored popovers that must NOT carry it.)
    overlay.setAttribute("aria-modal", "true");

    const card = document.createElement("div");
    card.className = "card modal-card confirm-card";
    const text = document.createElement("p");
    text.className = "confirm-text";
    for (const part of String(message).split(/\n{2,}/)) {
      const line = document.createElement("span");
      line.textContent = part;
      text.append(line, document.createElement("br"));
    }
    const row = document.createElement("div");
    row.className = "row confirm-actions";

    let settled = false;
    const close = (answer) => {
      if (settled) return;
      settled = true;
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
      returnFocus?.focus?.();
      resolve(answer);
    };
    const onKey = (event) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close(null);
      }
    };

    const returnFocus = document.activeElement;
    const cancel = smallButton("Cancel", "Leave the link unresolved", () => close(null));
    row.appendChild(cancel);
    for (const choice of choices) {
      row.appendChild(
        smallButton(choice.label, choice.title || choice.label, () => close(choice.value), false)
      );
    }
    card.append(text, row);
    overlay.appendChild(card);
    wireBackdropClose(overlay, () => close(null));
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(overlay);
    // Cancel takes focus: a stray Enter must not be the thing that creates a
    // note, the same reasoning confirmDialog uses for its destructive button.
    cancel.focus();
  });
}

// Clicking a [[link]] whose target does not exist yet.
//
// A link you typed on purpose is the clearest possible statement that the
// thing ought to exist, so the dead end becomes an offer. Creation stays
// user-confirmed and never happens in the background: silently materialising
// notes from typos is precisely the failure mode this app's autonomous agent
// is deliberately conservative about, and a notebook that grows notes you did
// not ask for is worse than one that makes you click twice.
async function offerToCreateWikiTarget(name) {
  const wanted = String(name || "").trim();
  if (!wanted) return;

  const choice = await editorChoiceDialog(
    `Nothing called “${wanted}” exists yet.\n\nCreate it, and this link will resolve to it.`,
    [
      { value: "note", label: "Create note", title: `Start a note beginning "${wanted}"` },
      { value: "document", label: "Create document", title: `Start a document titled "${wanted}"` },
    ]
  );
  if (!choice) return;

  try {
    if (choice === "note") {
      // The note's content opens with the link text, because that is what
      // resolution matches on: a note created here that did not start with
      // the name would leave the very link that made it still unresolved.
      const entry = await apiJson("/entries", {
        method: "POST",
        body: JSON.stringify({ content: `${wanted}\n\n` }),
      });
      await loadEntries();
      toast(`Created “${wanted}”.`);
      if (entry?.id) flashEntry(entry.id);
      return;
    }

    const doc = await apiJson("/documents", {
      method: "POST",
      body: JSON.stringify({ title: wanted, content: `# ${wanted}\n\n` }),
    });
    // Keep the resolver's cache honest, or the link stays unresolved until
    // something else happens to refetch documents.
    if (doc) {
      editorDocumentCache = [...(editorDocumentCache || []), doc];
      toast(`Created “${wanted}”.`);
      openDocument(doc.id);
    }
  } catch (error) {
    toast(error.message || "Could not create that.", true);
  }
}

// ---------------------------------------------------------------------------
// Syntax highlighting for the file viewer (REDESIGN.md §R7.1 item 3)
// ---------------------------------------------------------------------------
//
// **Written here rather than pulled in.** This app is offline by construction
//, there is no CDN to load highlight.js from and no bundler to vendor it
// with, and a 900 KB library shipped for one panel would be the largest
// single asset in the project. Four token classes cover what makes code
// readable at a glance: comments recede, strings and numbers stand out from
// identifiers, keywords carry the structure. That is most of the value of a
// full grammar for none of the weight.
//
// **The colours are existing semantic tokens, not new ones.** `--muted` for
// comments, `--ok` for strings, `--warn` for numbers, `--accent` for
// keywords: each already has a light and a dark value, so this follows the
// theme for free and adds nothing for `tests/test_style_scale.py` to police.
//
// **Every pattern here is linear.** CI runs CodeQL, which has caught a real
// polynomial-ReDoS in this repo before; the string rules use the
// `[^"\\\n]|\\.` shape whose alternatives are disjoint on their first
// character, and nothing nests a quantifier inside a quantifier.

//: What a suffix is written in. The value is the profile name below; a suffix
//: that is missing gets `generic`, which still finds strings, numbers and
//: both comment styles: worth having for a `.conf` nobody thought about.
const CODE_LANGUAGES = {
  js: "c", mjs: "c", cjs: "c", ts: "c", tsx: "c", jsx: "c", java: "c",
  c: "c", h: "c", cpp: "c", hpp: "c", cs: "c", go: "c", rs: "c", swift: "c",
  kt: "c", php: "c", scss: "c", css: "css",
  py: "hash", rb: "hash", sh: "hash", bash: "hash", zsh: "hash",
  yaml: "hash", yml: "hash", toml: "hash", ini: "hash", cfg: "hash", r: "hash",
  sql: "sql", json: "json", html: "markup", htm: "markup", xml: "markup",
};

//: Keywords worth colouring, per family. Deliberately not exhaustive: a
//: keyword list that tries to be complete is a maintenance burden that buys
//: nothing: what the eye uses is the *shape* of the control flow, and these
//: are the words that carry it.
const CODE_KEYWORDS = {
  c: "abstract async await break case catch class const continue default delete do else enum export extends false final finally for from function goto if implements import in instanceof interface let new null package private protected public return static struct super switch this throw throws true try typeof var void while yield",
  hash: "and as assert async await break case class continue def del elif else end except false finally for from global if import in is lambda module nil none not or pass raise return self true try unless until while with yield",
  sql: "add all alter and as asc between by case create delete desc distinct drop else exists from group having in inner insert into is join left limit not null on or order outer right select set table then union update values where",
  json: "true false null",
  css: "important media import supports keyframes from to and not only",
  markup: "",
  generic: "false null true",
};

//: One scanner, built once per family. Order inside the alternation *is* the
//: precedence: comments and strings first, so a `#` inside a string or the
//: word `if` inside a comment is not re-coloured as something else.
const codeScanners = new Map();

function codeScanner(family) {
  if (codeScanners.has(family)) return codeScanners.get(family);
  const lineComment =
    family === "hash" ? "#[^\\n]*" : family === "sql" ? "--[^\\n]*" : "\\/\\/[^\\n]*";
  const parts = [];
  if (family === "markup") parts.push("(?<comment><!--[\\s\\S]*?-->)");
  else parts.push(`(?<comment>\\/\\*[\\s\\S]*?\\*\\/|${lineComment})`);
  parts.push('(?<string>"(?:[^"\\\\\\n]|\\\\.)*"|\'(?:[^\'\\\\\\n]|\\\\.)*\'|`(?:[^`\\\\]|\\\\.)*`)');
  parts.push("(?<number>\\b\\d[\\d_]*(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b)");
  const words = (CODE_KEYWORDS[family] || CODE_KEYWORDS.generic).trim().split(/\s+/);
  if (words.length && words[0]) parts.push(`(?<keyword>\\b(?:${words.join("|")})\\b)`);
  const scanner = new RegExp(parts.join("|"), "g");
  codeScanners.set(family, scanner);
  return scanner;
}

//: Which family a filename is in. Extension only: content sniffing guesses
//: wrong on short files and there is nothing to gain: a file this app can
//: view arrived with a suffix it recognised (`docview.CODE_SUFFIXES`).
function codeFamilyFor(filename) {
  const suffix = /\.([a-z0-9]+)$/i.exec(String(filename || ""));
  return CODE_LANGUAGES[(suffix?.[1] || "").toLowerCase()] || "generic";
}

//: Fills `target` with the highlighted source. Text nodes and `<span>`s
//: built with `textContent`, never `innerHTML`, a file's own text is exactly
//: the untrusted input a markup-assembling highlighter turns into an
//: injection, and this app's CSP would not save a same-origin one.
function highlightCodeInto(target, text, filename) {
  const scanner = codeScanner(codeFamilyFor(filename));
  scanner.lastIndex = 0;
  const source = String(text ?? "");
  let at = 0;
  let match;
  while ((match = scanner.exec(source)) !== null) {
    //: A zero-length match would loop forever. None of the patterns above can
    //: produce one, and this costs nothing to be certain of.
    if (match.index === scanner.lastIndex) {
      scanner.lastIndex++;
      continue;
    }
    if (match.index > at) target.appendChild(document.createTextNode(source.slice(at, match.index)));
    const kind = Object.keys(match.groups).find((name) => match.groups[name] !== undefined);
    const span = document.createElement("span");
    span.className = `tok-${kind}`;
    span.textContent = match[0];
    target.appendChild(span);
    at = match.index + match[0].length;
  }
  if (at < source.length) target.appendChild(document.createTextNode(source.slice(at)));
}

// ---------------------------------------------------------------------------
// Inline AI: the AI at the caret, not in a panel
// ---------------------------------------------------------------------------
//
// Asked for directly: *"the agent or ai needs to be more directly integrated
// into the documents."* Everything the document editor already had, AI edit,
// extract notes, rephrase, translate, check with AI, is a *panel*: you leave
// the text, open a side pane, ask, read, accept, come back. That is a fine
// place for "review this whole document" and the wrong place for "make this
// sentence shorter", which is the thing writers actually do fifty times an
// hour. Notion answers it with `/ai`, Cursor with Ctrl+K, Word with the
// rewrite popover; all three put the request *where the caret is* and put the
// result *into the text*, with one keystroke to keep it and one to undo it.
//
// Three deliberate constraints, each of which is why this is ~200 lines and
// not a second AI panel:
//
// 1. **No new endpoint.** `POST /documents/{id}/ai-edit` already takes an
//    instruction, an optional selection and a verb, already returns the
//    revised text without saving it, and already reports `ollama_running`
//    false with a message when the model is not there. A third code path to
//    the same model would be a third place for the offline message, the
//    thinking trace and the token budget to drift.
// 2. **Nothing is written until it is accepted, and "accepted" is the
//    default, not a modal.** The result goes straight into the text, selected,
//    with Keep / Try again / Undo underneath. Undo restores the exact prior
//    value and caret, because `before` is captured whole; a diff would be
//    prettier and would not survive the AI reflowing a paragraph.
// 3. **Document surfaces only.** The endpoint needs a document id, and the
//    capture box has none. The command and the shortcut both check, rather
//    than opening a bar that would fail on submit.

const inlineAiState = {
  textarea: null,
  //: The range the answer replaces, captured when the bar opens. Held rather
  //: than re-read on submit because clicking into the bar's own input moves
  //: focus out of the textarea, and several browsers drop the selection on the
  //: way: the same trap `selectionBarElement` documents for `mousedown`.
  start: 0,
  end: 0,
  //: The whole textarea value before anything was inserted. Undo restores this
  //: verbatim. Cheap: a document big enough for this to matter is already
  //: being held in `.value` twice by the live view.
  before: "",
  //: The instruction, kept so "Try again" does not make you retype it.
  instruction: "",
  phase: "idle", // idle | asking | working | review
  controller: null,
};

//: The bar is one element reused for every invocation, built lazily for the
//: same reason `selectionBarElement` is: it belongs to this file's behaviour,
//: and a hidden copy in index.html would be one more thing for the duplicate-id
//: and duplicate-listener lints to police for nothing.
function inlineAiElement() {
  let bar = $("inline-ai");
  if (bar) return bar;

  bar = document.createElement("div");
  bar.id = "inline-ai";
  bar.className = "inline-ai hidden";
  bar.setAttribute("role", "dialog");
  bar.setAttribute("aria-label", "Ask the AI to write here");

  const row = document.createElement("div");
  row.className = "inline-ai-row";

  const icon = document.createElement("span");
  icon.className = "inline-ai-icon";
  icon.setAttribute("aria-hidden", "true");
  setLabel(icon, "ph:magic-wand");
  row.appendChild(icon);

  const input = document.createElement("input");
  input.id = "inline-ai-input";
  input.className = "inline-ai-input";
  input.type = "text";
  input.autocomplete = "off";
  input.setAttribute("aria-label", "What should the AI do here?");
  row.appendChild(input);

  const run = document.createElement("button");
  run.id = "inline-ai-run";
  run.type = "button";
  run.className = "primary small";
  run.textContent = "Ask";
  run.addEventListener("click", () => inlineAiSubmit());
  row.appendChild(run);

  const close = document.createElement("button");
  close.id = "inline-ai-close";
  close.type = "button";
  close.className = "ghost small icon-button";
  close.title = "Close (Esc)";
  close.setAttribute("aria-label", "Close");
  setLabel(close, "ph:x");
  close.addEventListener("click", () => inlineAiClose());
  row.appendChild(close);

  bar.appendChild(row);

  //: The scope line. Without it the bar is a text field floating over a
  //: document with no statement of what it is about to change, which is the
  //: one thing a writer needs to know before pressing Enter.
  const scope = document.createElement("p");
  scope.id = "inline-ai-scope";
  scope.className = "inline-ai-scope";
  bar.appendChild(scope);

  const review = document.createElement("div");
  review.id = "inline-ai-review";
  review.className = "inline-ai-review hidden";
  for (const [act, label, cls] of [
    ["keep", "Keep", "primary small"],
    ["retry", "Try again", "ghost small"],
    ["undo", "Undo", "ghost small"],
  ]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = cls;
    button.dataset.act = act;
    button.textContent = label;
    button.addEventListener("click", () => {
      if (act === "keep") inlineAiClose();
      else if (act === "undo") inlineAiUndo();
      else inlineAiRetry();
    });
    review.appendChild(button);
  }
  bar.appendChild(review);

  document.body.appendChild(bar);
  return bar;
}

//: Anchored the same way the "/" menu is, and for the same reason: a bar that
//: opens at the top of a full-height document editor reads as belonging to the
//: toolbar rather than to the sentence you were writing. Flips above the line
//: when there is no room below, and is clamped into the viewport on both axes.
function inlineAiPosition() {
  const bar = $("inline-ai");
  const textarea = inlineAiState.textarea;
  if (!bar || !textarea) return;
  const { top, left, lineHeight } = editorCaretPoint(textarea);
  const size = bar.getBoundingClientRect();
  const margin = 8;
  let y = top + (lineHeight || 20) + 6;
  if (y + size.height > window.innerHeight - margin) {
    const above = top - size.height - 6;
    y = above > margin ? above : Math.max(margin, window.innerHeight - size.height - margin);
  }
  const x = Math.max(margin, Math.min(left, window.innerWidth - size.width - margin));
  bar.style.top = `${Math.round(y)}px`;
  bar.style.left = `${Math.round(x)}px`;
}

//: What the bar says it is about to do. Two shapes, because "write something
//: here" and "change this" are different requests and a single placeholder
//: that covers both ("Ask the AI…") tells you nothing about which one you are
//: making.
function inlineAiDescribeScope() {
  const { before, start, end } = inlineAiState;
  const selected = before.slice(start, end);
  const scope = $("inline-ai-scope");
  const input = $("inline-ai-input");
  if (!scope || !input) return;
  if (selected.trim()) {
    const words = selected.trim().split(/\s+/).length;
    scope.textContent = `Rewrites the ${words === 1 ? "word" : `${words} words`} you selected. Enter to ask, Esc to cancel.`;
    input.placeholder = "Tighten this / fix the grammar / make it formal…";
  } else {
    scope.textContent = "Writes at the cursor. Enter to ask, Esc to cancel.";
    input.placeholder = "Write an intro paragraph / a table of the options…";
  }
}

//: True when this surface can reach `POST /documents/{id}/ai-edit`, a
//: document textarea *and* a document actually open. Checked by both doors
//: (the "/" command and the shortcut) rather than letting the bar open and
//: fail on submit, which is the shape that teaches people a feature is broken.
function inlineAiAvailable(textarea) {
  if (editorSurfaceKind(textarea) !== "document") return false;
  return Boolean(typeof currentDoc !== "undefined" && currentDoc && currentDoc.id);
}

function inlineAiOpen(textarea, instruction = "") {
  if (!inlineAiAvailable(textarea)) {
    toast("Open a document first, inline AI writes into the document you're editing.");
    return;
  }
  const bar = inlineAiElement();
  inlineAiState.textarea = textarea;
  inlineAiState.start = textarea.selectionStart;
  inlineAiState.end = textarea.selectionEnd;
  inlineAiState.before = textarea.value;
  inlineAiState.instruction = instruction;
  inlineAiState.phase = "asking";

  //: The selection bar and this bar both anchor to the caret, so they would
  //: sit on top of each other the moment this opens over a selection.
  selectionBarHide();

  bar.classList.remove("hidden");
  $("inline-ai-review").classList.add("hidden");
  const input = $("inline-ai-input");
  input.disabled = false;
  input.value = instruction;
  $("inline-ai-run").disabled = false;
  $("inline-ai-run").textContent = "Ask";
  inlineAiDescribeScope();
  inlineAiPosition();
  input.focus();
  input.select();
}

//: Closing keeps whatever is in the text. That is deliberate and it is the
//: same choice every editor with this feature makes: the result is already
//: visible in the document, so the surprising outcome would be it vanishing
//: when the bar goes away. Undo is a button, and the app's own Ctrl+Z still
//: works on the textarea afterwards.
function inlineAiClose() {
  const textarea = inlineAiState.textarea;
  inlineAiState.controller?.abort();
  inlineAiState.controller = null;
  inlineAiState.textarea = null;
  inlineAiState.phase = "idle";
  $("inline-ai")?.classList.add("hidden");
  //: Focus goes back to the text, not to whatever the browser picks. Without
  //: this, dismissing the bar leaves the caret nowhere and the next keystroke
  //: is lost.
  textarea?.focus();
}

function inlineAiUndo() {
  const { textarea, before, start, end } = inlineAiState;
  if (!textarea) return inlineAiClose();
  textarea.value = before;
  textarea.setSelectionRange(start, end);
  editorNotifyHost(textarea);
  inlineAiClose();
}

function inlineAiRetry() {
  const { textarea, before, start, end, instruction } = inlineAiState;
  if (!textarea) return;
  //: Put the text back *before* re-asking, or the second answer is written on
  //: top of the first and the third on top of that.
  textarea.value = before;
  textarea.setSelectionRange(start, end);
  editorNotifyHost(textarea);
  inlineAiOpen(textarea, instruction);
}

async function inlineAiSubmit() {
  if (inlineAiState.phase === "working") return;
  const { textarea, start, end, before } = inlineAiState;
  if (!textarea) return;
  const instruction = $("inline-ai-input").value.trim();
  const selection = before.slice(start, end);
  //: "Write" needs an instruction: there is nothing else to go on. "Edit"
  //: does too: a selection alone says *what*, never *what to do to it*.
  if (!instruction) {
    $("inline-ai-scope").textContent = "Say what you'd like: for example, “make this two sentences”.";
    $("inline-ai-input").focus();
    return;
  }
  inlineAiState.instruction = instruction;
  inlineAiState.phase = "working";
  const run = $("inline-ai-run");
  run.disabled = true;
  run.textContent = "Writing…";
  $("inline-ai-input").disabled = true;
  $("inline-ai-scope").textContent = "Thinking locally… Esc to cancel.";

  const controller = new AbortController();
  inlineAiState.controller = controller;
  try {
    const data = await apiJson(`/documents/${currentDoc.id}/ai-edit`, {
      method: "POST",
      signal: controller.signal,
      body: JSON.stringify({
        instruction,
        selection,
        verb: selection.trim() ? "edit" : "write",
      }),
    });
    //: The model is not running. Say so *in the bar* and leave it open with
    //: the instruction intact, rather than closing and firing a toast the
    //: user has to read somewhere else while their sentence is gone.
    if (data.ollama_running === false) {
      inlineAiState.phase = "asking";
      run.disabled = false;
      run.textContent = "Ask";
      $("inline-ai-input").disabled = false;
      $("inline-ai-scope").textContent = data.message || "The local model isn't running.";
      inlineAiPosition();
      return;
    }
    const revised = String(data.revised ?? "");
    if (!revised.trim()) {
      inlineAiState.phase = "asking";
      run.disabled = false;
      run.textContent = "Ask";
      $("inline-ai-input").disabled = false;
      $("inline-ai-scope").textContent = "The model returned nothing. Try asking differently.";
      return;
    }
    //: `replaced_selection` comes from the server rather than being inferred
    //: here, because the server is what decided whether the selection or the
    //: whole document was the target, inferring it a second time is how the
    //: two would drift.
    const to = data.replaced_selection ? end : start;
    editorSplice(textarea, start, to, revised, { from: 0, to: revised.length });
    //: The inserted text ends up *selected*. That is the highlight, a
    //: textarea cannot paint a range any other way, and it also means the
    //: next thing typed replaces it, which is what "try it and see" should
    //: feel like.
    inlineAiState.phase = "review";
    $("inline-ai-input").disabled = false;
    $("inline-ai-review").classList.remove("hidden");
    $("inline-ai-scope").textContent =
      data.thinking ? `Done. ${data.thinking}` : "Done: keep it, ask again, or undo.";
    run.disabled = false;
    run.textContent = "Ask";
    inlineAiPosition();
    //: Focus the primary action, so Enter keeps and Esc keeps-and-closes. The
    //: textarea keeps the selection either way.
    $("inline-ai-review").querySelector('[data-act="keep"]')?.focus();
  } catch (error) {
    if (controller.signal.aborted) return;
    inlineAiState.phase = "asking";
    run.disabled = false;
    run.textContent = "Ask";
    $("inline-ai-input").disabled = false;
    $("inline-ai-scope").textContent = error?.message || "That didn't work. Try again.";
  } finally {
    if (inlineAiState.controller === controller) inlineAiState.controller = null;
  }
}

//: Enter submits, Esc dismisses, handled on the bar rather than globally so
//: neither key is stolen from the document behind it.
document.addEventListener("keydown", (event) => {
  if (inlineAiState.phase === "idle") return;
  const bar = $("inline-ai");
  if (!bar || bar.classList.contains("hidden")) return;
  if (!bar.contains(event.target)) return;
  if (event.key === "Enter" && event.target.id === "inline-ai-input") {
    event.preventDefault();
    inlineAiSubmit();
    return;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    //: Esc while the model is still writing cancels the request and leaves the
    //: document untouched; Esc afterwards keeps the result, matching the
    //: "closing keeps" rule above.
    if (inlineAiState.phase === "working") {
      inlineAiState.controller?.abort();
      inlineAiClose();
      return;
    }
    inlineAiClose();
  }
});

//: Clicking away keeps the result and closes, the same as Esc. Not on
//: `mousedown` inside the bar, obviously, and not while the model is writing, 
//: a stray click should not throw away work that is seconds from arriving.
document.addEventListener("mousedown", (event) => {
  if (inlineAiState.phase === "idle" || inlineAiState.phase === "working") return;
  const bar = $("inline-ai");
  if (!bar || bar.contains(event.target)) return;
  inlineAiClose();
});

window.addEventListener("resize", () => inlineAiState.textarea && inlineAiPosition());
