// PLAN.md §2 D2 + D3 — the document editor's selection toolbar and its own
// undo stack, measured in a real Chromium against a running app.
//
//   BASE=http://127.0.0.1:8795 SCRATCH=/tmp/mm-editor \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/editor.js
//
// Every assertion here is a *number* read out of the page, not a screenshot
// looked at — CLAUDE.md's rule, and the reason the selection bar's "one frame"
// claim and the undo stack's "restores exactly the prior text and selection"
// claim are both checkable rather than asserted.
const { boot } = require("/home/user/MemoryMap-AI/scratchpad/ui-sweeps/lib.js");

const BODY = [
  "Alpha paragraph one.",
  "Beta paragraph two.",
  "Gamma paragraph three.",
  "Delta paragraph four.",
].join("\n\n");

let failures = 0;
let checks = 0;
function ok(name, condition, detail) {
  checks += 1;
  if (!condition) failures += 1;
  console.log(`${condition ? "PASS" : "FAIL"}  ${name}${detail === undefined ? "" : `  — ${detail}`}`);
}

(async () => {
  const { browser, page } = await boot();
  const consoleErrors = [];
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text().slice(0, 200)));
  page.on("pageerror", (e) => consoleErrors.push("PAGEERROR " + e.message));

  const doc = await page.evaluate(async (content) => {
    const r = await api("/documents", {
      method: "POST",
      body: JSON.stringify({ title: "Editor sweep", content }),
    });
    return await r.json();
  }, BODY);

  // Opened the way a person opens it: Library -> Documents -> the row.
  await page.evaluate(() => {
    switchTab("library");
    libraryKind = "document";
    renderLibraryOverview();
    renderLibraryFilters();
    renderLibrary();
  });
  await page.waitForTimeout(700);
  const rowOpened = await page.evaluate((id) => {
    const row = document.querySelector(`[data-library-id="${id}"], [data-doc-id="${id}"]`);
    if (row) {
      row.click();
      return true;
    }
    return false;
  }, doc.id);
  if (!rowOpened) {
    await page.evaluate(async (id) => {
      switchTab("documents");
      await openDocument(id);
    }, doc.id);
  }
  await page.waitForTimeout(1400);
  const loaded = await page.evaluate(() => ({
    tab: localStorage.getItem("activeTab"),
    id: currentDoc && currentDoc.id,
    len: document.getElementById("doc-content").value.length,
  }));
  ok("document open in the editor", loaded.id === doc.id && loaded.len === BODY.length,
    JSON.stringify(loaded));

  // Timing probe: a capture-phase listener stamps the moment the selection
  // changed, a bubble-phase one (registered after the app's own
  // `selectionBarSync`) stamps the moment the bar was visible. The gap is the
  // app's synchronous work, i.e. "within one frame" made into a number.
  await page.evaluate(() => {
    window.__t0 = null;
    window.__t1 = null;
    document.addEventListener("selectionchange", () => { window.__t0 = performance.now(); }, true);
    document.addEventListener("selectionchange", () => {
      const bar = document.getElementById("selection-bar");
      if (bar && !bar.classList.contains("hidden")) window.__t1 = performance.now();
    });
  });

  // ---------------------------------------------------------------- D2, Source
  await page.evaluate(() => setDocView("source"));
  await page.waitForTimeout(300);

  const at = BODY.indexOf("Gamma");
  const d2 = await page.evaluate((start) => {
    window.__t0 = null;
    window.__t1 = null;
    const box = document.getElementById("doc-content");
    box.focus();
    box.setSelectionRange(start, start + 5);
    document.dispatchEvent(new Event("selectionchange"));
    const bar = document.getElementById("selection-bar");
    const rect = bar.getBoundingClientRect();
    const caret = editorCaretPoint(box);
    const pane = document.getElementById("doc-panes").getBoundingClientRect();
    return {
      hidden: bar.classList.contains("hidden"),
      ms: window.__t1 === null || window.__t0 === null ? null : window.__t1 - window.__t0,
      barTop: rect.top,
      barLeft: rect.left,
      barRight: rect.right,
      barBottom: rect.bottom,
      selTop: caret.top,
      pane: { top: pane.top, left: pane.left, right: pane.right, bottom: pane.bottom },
      styleAttr: bar.getAttribute("style") || "",
      buttons: [...bar.querySelectorAll("button")]
        .filter((b) => !b.hidden)
        .map((b) => b.dataset.md || (b.dataset.inlineAi ? "ai:rewrite" : "ai:ask")),
    };
  }, at);
  ok("D2 bar visible on a selection", !d2.hidden);
  ok("D2 bar appears within 50ms of the selection", d2.ms !== null && d2.ms < 50,
    `${d2.ms === null ? "not measured" : d2.ms.toFixed(2)}ms`);
  ok("D2 bar top is above the selection top", d2.barTop < d2.selTop,
    `bar ${d2.barTop.toFixed(1)} < selection ${d2.selTop.toFixed(1)}`);
  ok("D2 bar is clamped inside the editor pane",
    d2.barLeft >= d2.pane.left - 1 && d2.barRight <= d2.pane.right + 1,
    `bar ${d2.barLeft.toFixed(0)}..${d2.barRight.toFixed(0)} in pane ${d2.pane.left.toFixed(0)}..${d2.pane.right.toFixed(0)}`);
  // CSP: the position has to be written through the CSSOM. An inline `style=`
  // string is what a `style` *attribute* in the markup would look like; these
  // are set with `el.style.top = …`, which produces the same attribute — so
  // what is checked is that only geometry lives there, never a whole rule set.
  ok("D2 positions with CSSOM geometry only",
    /^\s*(top|left)\s*:[^;]+;?\s*(top|left)?\s*:?[^;]*;?\s*$/.test(d2.styleAttr),
    JSON.stringify(d2.styleAttr));
  const WANT = ["bold", "italic", "link", "h2", "quote", "code"];
  ok("D2 has bold/italic/link/heading/quote/code",
    WANT.every((k) => d2.buttons.includes(k)), JSON.stringify(d2.buttons));
  ok("D2 has an AI action", d2.buttons.some((b) => b.startsWith("ai:")),
    JSON.stringify(d2.buttons.filter((b) => b.startsWith("ai:"))));

  // Every button changes the text the way the fixed strip does. The strip's
  // delegated click handler calls `applyMarkdown(md, boxId)`; the floating bar
  // is driven here by a real mousedown on the real element, and the two results
  // are compared character for character. One edit path, proved rather than
  // read.
  for (const md of [...WANT, "strike", "highlight"]) {
    const same = await page.evaluate(async (key) => {
      const box = document.getElementById("doc-content");
      const start = box.value.indexOf("Gamma");
      const reset = (v) => {
        box.value = v;
        box.focus();
        box.setSelectionRange(start, start + 5);
        document.dispatchEvent(new Event("selectionchange"));
      };
      const base = box.value;
      // The strip's path.
      reset(base);
      applyMarkdown(key, "doc-content");
      const viaStrip = box.value;
      // The floating bar's path — a real mousedown on the real button.
      reset(base);
      const button = document.querySelector(`#selection-bar button[data-md="${key}"]`);
      if (!button) return { missing: true };
      button.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
      const viaBar = box.value;
      box.value = base;
      return { viaStrip, viaBar, changed: viaBar !== base };
    }, md);
    ok(`D2 "${md}" edits exactly as the strip does`,
      !same.missing && same.changed && same.viaBar === same.viaStrip,
      same.missing ? "no button" : JSON.stringify(same.viaBar.slice(
        Math.max(0, same.viaBar.indexOf("Gamma") - 4), same.viaBar.indexOf("Gamma") + 14)));
  }
  // That loop drives `applyMarkdown` sixteen times and then puts the text back
  // with a bare `.value =`, which is not something any real interaction does —
  // so the undo stack now holds sixteen entries for a document that is back
  // where it started. Re-baseline it, or the D3 checks below would be
  // measuring the harness rather than the editor.
  await page.evaluate(() => docUndoReset(document.getElementById("doc-content").value));

  // Hide rules.
  const hide = await page.evaluate((start) => {
    const bar = document.getElementById("selection-bar");
    const box = document.getElementById("doc-content");
    const show = () => {
      box.focus();
      box.setSelectionRange(start, start + 5);
      document.dispatchEvent(new Event("selectionchange"));
    };
    show();
    const shown = !bar.classList.contains("hidden");
    // Collapse.
    box.setSelectionRange(start, start);
    document.dispatchEvent(new Event("selectionchange"));
    const onCollapse = bar.classList.contains("hidden");
    // Escape.
    show();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    const onEscape = bar.classList.contains("hidden");
    // Focus leaving the editor entirely.
    show();
    document.getElementById("doc-title").focus();
    document.dispatchEvent(new Event("selectionchange"));
    const onBlur = bar.classList.contains("hidden");
    return { shown, onCollapse, onEscape, onBlur };
  }, at);
  ok("D2 hides on selection collapse", hide.shown && hide.onCollapse);
  ok("D2 hides on Escape", hide.onEscape);
  ok("D2 hides when focus leaves the editor", hide.onBlur);

  // ------------------------------------------------------------------ D2, Live
  await page.evaluate(() => setDocView("live"));
  await page.waitForTimeout(500);
  await page.evaluate(() => focusDocLiveBlock(2, 0));
  await page.waitForTimeout(400);
  const liveBar = await page.evaluate(() => {
    const box = document.querySelector("#doc-live .lp-src");
    if (!box) return { noBox: true };
    box.focus();
    box.setSelectionRange(0, 5);
    document.dispatchEvent(new Event("selectionchange"));
    const bar = document.getElementById("selection-bar");
    const rect = bar.getBoundingClientRect();
    return {
      hidden: bar.classList.contains("hidden"),
      barTop: rect.top,
      selTop: editorCaretPoint(box).top,
      boxId: box.id,
    };
  });
  ok("D2 bar appears on a Live paragraph too", !liveBar.noBox && !liveBar.hidden,
    JSON.stringify(liveBar));
  ok("D2 Live bar sits above the selection", !liveBar.noBox && liveBar.barTop < liveBar.selTop,
    `${liveBar.barTop} < ${liveBar.selTop}`);

  // ---------------------------------------------------------------------- D3
  // The PLAN.md acceptance, driven with real keystrokes: type in Live, switch
  // to Source, Ctrl+Z undoes the Live edit.
  const before = await page.evaluate(() => document.getElementById("doc-content").value);
  await page.evaluate(() => focusDocLiveBlock(1, 0));
  await page.waitForTimeout(300);
  await page.keyboard.type("ZZZ");
  await page.waitForTimeout(200);
  const afterLiveType = await page.evaluate(() => document.getElementById("doc-content").value);
  ok("D3 typing in Live reached the document", afterLiveType.includes("ZZZBeta"),
    JSON.stringify(afterLiveType.slice(0, 60)));

  await page.click('#doc-view-seg button[data-doc-view="source"]');
  await page.waitForTimeout(400);
  await page.focus("#doc-content");
  await page.keyboard.press("Control+z");
  await page.waitForTimeout(300);
  const afterUndo = await page.evaluate(() => document.getElementById("doc-content").value);
  ok("D3 ACCEPTANCE: type in Live, switch to Source, Ctrl+Z undoes the Live edit",
    afterUndo === before,
    afterUndo === before ? `${before.length} chars restored` : JSON.stringify(afterUndo.slice(0, 60)));

  await page.keyboard.press("Control+Shift+z");
  await page.waitForTimeout(250);
  const afterRedo = await page.evaluate(() => document.getElementById("doc-content").value);
  ok("D3 Ctrl+Shift+Z redoes it", afterRedo === afterLiveType,
    JSON.stringify(afterRedo.slice(0, 40)));
  await page.keyboard.press("Control+z");
  await page.waitForTimeout(250);
  await page.keyboard.press("Control+y");
  await page.waitForTimeout(250);
  const afterCtrlY = await page.evaluate(() => document.getElementById("doc-content").value);
  ok("D3 Ctrl+Y redoes it too", afterCtrlY === afterLiveType);
  await page.keyboard.press("Control+z");
  await page.waitForTimeout(250);

  // Undo after a toolbar action restores exactly the prior text *and* selection.
  const boldCase = await page.evaluate(() => {
    const box = document.getElementById("doc-content");
    const start = box.value.indexOf("Delta");
    box.focus();
    box.setSelectionRange(start, start + 5);
    document.dispatchEvent(new Event("selectionchange"));
    return { text: box.value, start, end: start + 5 };
  });
  await page.waitForTimeout(60);
  await page.evaluate(() => {
    document
      .querySelector('#selection-bar button[data-md="bold"]')
      .dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
  });
  await page.waitForTimeout(250);
  const bolded = await page.evaluate(() => document.getElementById("doc-content").value);
  ok("D3 the Bold actually applied", bolded.includes("**Delta**"),
    JSON.stringify(bolded.slice(bolded.indexOf("Delta") - 6, bolded.indexOf("Delta") + 12)));
  await page.focus("#doc-content");
  await page.keyboard.press("Control+z");
  await page.waitForTimeout(300);
  const unbolded = await page.evaluate(() => {
    const box = document.getElementById("doc-content");
    return { text: box.value, start: box.selectionStart, end: box.selectionEnd };
  });
  ok("D3 undo after Bold restores exactly the prior text",
    unbolded.text === boldCase.text,
    unbolded.text === boldCase.text ? "byte-identical" : JSON.stringify(unbolded.text.slice(0, 60)));
  ok("D3 undo after Bold restores exactly the prior selection",
    unbolded.start === boldCase.start && unbolded.end === boldCase.end,
    `got ${unbolded.start}..${unbolded.end}, wanted ${boldCase.start}..${boldCase.end}`);

  // Coalescing: a burst of typing is one undo step, a pause starts another.
  const coalesce = await page.evaluate(() => {
    const box = document.getElementById("doc-content");
    box.focus();
    box.setSelectionRange(box.value.length, box.value.length);
    return { before: box.value, depth: docUndoStack.length, at: docUndoAt };
  });
  await page.keyboard.type("abcdef", { delay: 20 });
  await page.waitForTimeout(200);
  const burst = await page.evaluate(() => ({
    text: document.getElementById("doc-content").value,
    depth: docUndoStack.length,
    at: docUndoAt,
  }));
  await page.keyboard.press("Control+z");
  await page.waitForTimeout(250);
  const afterBurstUndo = await page.evaluate(() => document.getElementById("doc-content").value);
  ok("D3 a 6-character burst coalesces into one undo entry",
    burst.at - coalesce.at === 1 && afterBurstUndo === coalesce.before,
    `entries added ${burst.at - coalesce.at}, one Ctrl+Z restored ${afterBurstUndo === coalesce.before}`);
  await page.waitForTimeout(700);
  await page.keyboard.type("gh");
  await page.waitForTimeout(150);
  const afterPause = await page.evaluate(() => ({ at: docUndoAt }));
  ok("D3 typing after a >500ms pause starts a new entry", afterPause.at > coalesce.at,
    `at ${coalesce.at} -> ${afterPause.at}`);

  const cap = await page.evaluate(() => ({ limit: DOC_UNDO_LIMIT, window: DOC_UNDO_COALESCE_MS }));
  ok("D3 stack is capped at ~200 with a ~500ms coalesce window",
    cap.limit === 200 && cap.window === 500, JSON.stringify(cap));

  // Past the 500ms window, so the "gh" above cannot be swallowed into the
  // burst measured next — a shorter wait here made this check fail against a
  // perfectly correct stack, which is the harness's fault and not the app's.
  await page.waitForTimeout(700);

  // Ctrl+Z still undoes an edit made and undone inside one mode: the document
  // stack is the one that answers, and it gives back the same text.
  const native = await page.evaluate(() => {
    const box = document.getElementById("doc-content");
    box.focus();
    box.setSelectionRange(0, 0);
    return box.value;
  });
  await page.keyboard.type("QQ");
  await page.waitForTimeout(700);
  await page.keyboard.press("Control+z");
  await page.waitForTimeout(250);
  const afterNative = await page.evaluate(() => document.getElementById("doc-content").value);
  ok("D3 Ctrl+Z inside Source undoes a Source edit", afterNative === native);

  // Undo works from inside a Live block as well.
  await page.evaluate(() => setDocView("live"));
  await page.waitForTimeout(500);
  const liveBefore = await page.evaluate(() => document.getElementById("doc-content").value);
  await page.evaluate(() => focusDocLiveBlock(0, 0));
  await page.waitForTimeout(300);
  await page.keyboard.type("WW");
  await page.waitForTimeout(700);
  await page.keyboard.press("Control+z");
  await page.waitForTimeout(500);
  const liveAfterUndo = await page.evaluate(() => document.getElementById("doc-content").value);
  ok("D3 Ctrl+Z works from inside a Live paragraph", liveAfterUndo === liveBefore,
    JSON.stringify(liveAfterUndo.slice(0, 40)));

  // Scrolling. The brief said "hide on scroll"; the bar instead **re-anchors**
  // to the caret (editor.js registers `selectionBarSync` on a capture-phase
  // scroll listener). That is strictly better — the selection is still there,
  // so the bar should still be over it — but "better" is a claim, so it is
  // measured: after scrolling the textarea the bar must have moved by the same
  // amount the text did, not stayed where it was.
  await page.evaluate(() => setDocView("source"));
  await page.waitForTimeout(300);
  const scrolled = await page.evaluate(async () => {
    const box = document.getElementById("doc-content");
    box.value = Array.from({ length: 120 }, (_, i) => `Line ${i} of a long document.`).join("\n");
    box.focus();
    box.scrollTop = 0;
    const start = box.value.indexOf("Line 40");
    box.setSelectionRange(start, start + 7);
    document.dispatchEvent(new Event("selectionchange"));
    const bar = document.getElementById("selection-bar");
    const before = bar.getBoundingClientRect().top;
    const wasHidden = bar.classList.contains("hidden");
    box.scrollTop = 200;
    box.dispatchEvent(new Event("scroll", { bubbles: true }));
    await new Promise((r) => requestAnimationFrame(r));
    return {
      wasHidden,
      before,
      after: bar.getBoundingClientRect().top,
      hiddenNow: bar.classList.contains("hidden"),
    };
  });
  ok("D2 re-anchors to the caret on scroll rather than drifting",
    !scrolled.wasHidden && !scrolled.hiddenNow &&
      Math.abs(scrolled.before - scrolled.after - 200) < 3,
    `top ${scrolled.before.toFixed(0)} -> ${scrolled.after.toFixed(0)} for a 200px scroll`);

  // =========================================================================
  // DOCUMENTS_PLAN.md Phase 0: click an underline, see suggestions
  // =========================================================================
  //
  // Its own document, because the D2/D3 run above ends with 120 lines of
  // `Line N ...` written straight into `.value`, with no findings in it and none
  // of the offsets the checks below need.
  const P0 = [
    "Alpha teh beta gamma.",
    "Gamma the the delta.",
    "A line with  double spaces and a seperate word.",
  ].join("\n\n");
  const p0doc = await page.evaluate(async (content) => {
    const r = await api("/documents", {
      method: "POST",
      body: JSON.stringify({ title: "Phase 0 sweep", content }),
    });
    return await r.json();
  }, P0);
  await page.evaluate(async (id) => {
    await openDocument(id);
    setDocView("source");
  }, p0doc.id);
  await page.waitForTimeout(900);

  // --- 1. the backdrop -----------------------------------------------------
  const back = await page.evaluate(() => {
    const box = document.getElementById("doc-content");
    const el = document.querySelector(".doc-backdrop");
    if (!el) return { missing: true };
    const boxStyle = getComputedStyle(box);
    const marks = [...el.querySelectorAll("mark")].map((m) => {
      const style = getComputedStyle(m);
      return {
        text: m.textContent,
        cls: m.className,
        line: style.textDecorationLine,
        style: style.textDecorationStyle,
        colour: style.textDecorationColor,
      };
    });
    return {
      marks,
      // The ink moved: the textarea is transparent, the caret is not.
      ink: boxStyle.color,
      caret: boxStyle.caretColor,
      inked: box.classList.contains("has-backdrop"),
      // Built from text nodes, never innerHTML: a document containing
      // `<img onerror=…>` is an ordinary markdown document.
      elements: [...el.querySelectorAll("*")].every((n) => n.tagName === "MARK"),
      // Same scroll height, or the two layers drift apart down a long file.
      scrollH: [box.scrollHeight, el.scrollHeight],
      boxRect: box.getBoundingClientRect().left,
      backRect: el.getBoundingClientRect().left,
    };
  });
  ok("P0 backdrop exists in Source view", !back.missing);
  ok("P0 the textarea's own ink is transparent, its caret is not",
    back.ink === "rgba(0, 0, 0, 0)" && back.caret !== "rgba(0, 0, 0, 0)" && back.inked,
    `${back.ink} / caret ${back.caret}`);
  ok("P0 the backdrop is built from text nodes and <mark>s only", back.elements);
  ok("P0 backdrop and textarea have the same scroll height",
    back.scrollH[0] === back.scrollH[1], back.scrollH.join(" vs "));
  ok("P0 backdrop is placed on the textarea's exact sub-pixel left edge",
    Math.abs(back.boxRect - back.backRect) < 0.01,
    `${back.boxRect} vs ${back.backRect}`);
  const kinds = Object.fromEntries(back.marks.map((m) => [m.text, m]));
  // Chromium reports this as `color(srgb 0.72549 0.109804 0.109804 / 0.8)`,
  // which is --error at 80%. Red is asserted as "much more red than green or
  // blue" rather than as a string, so a theme change cannot make this a lie.
  const redness = (c) => {
    const [r, g, b] = (c.match(/[\d.]+/g) || []).map(Number);
    return r > 0.5 && r > g * 2 && r > b * 2;
  };
  ok("P0 a misspelling is a red wavy underline",
    kinds.teh && kinds.teh.style === "wavy" && redness(kinds.teh.colour),
    kinds.teh && `${kinds.teh.style} ${kinds.teh.colour}`);
  ok("P0 a repeated word is dotted",
    kinds["the the"] && kinds["the the"].style === "dotted",
    kinds["the the"] && kinds["the the"].style);
  ok("P0 a style note is a blue wavy underline",
    kinds["  "] && kinds["  "].style === "wavy" && kinds["  "].cls.includes("doc-finding-style"),
    kinds["  "] && `${kinds["  "].style} ${kinds["  "].colour}`);

  // **The measurement that makes the backdrop worth having.** A mark that
  // does not sit exactly over the glyph it is about points at the wrong word,
  // and every click on it is then wrong too. `docCaretPoint` is the app's own
  // mirror-div measurement of where a character sits inside the textarea, an
  // independent oracle, since the backdrop does not use it.
  const align = await page.evaluate(() => {
    const box = document.getElementById("doc-content");
    const el = document.querySelector(".doc-backdrop");
    const out = [];
    for (const mark of el.querySelectorAll("mark")) {
      const finding = docProseFound.find((f) => f.text === mark.textContent);
      if (!finding) continue;
      box.setSelectionRange(finding.start, finding.start);
      const point = docCaretPoint(box);
      const rect = mark.getBoundingClientRect();
      out.push({ text: finding.text, dx: rect.left - point.x, dy: rect.top - point.y });
    }
    return out;
  });
  ok("P0 every mark's box coincides with its glyph's box within 1px",
    align.length === 4 && align.every((a) => Math.abs(a.dx) <= 1 && Math.abs(a.dy) <= 1),
    align.map((a) => `${a.text}: dx ${a.dx.toFixed(2)} dy ${a.dy.toFixed(2)}`).join(", "));

  // Scrolled, because a backdrop that is right at the top of the file and a
  // line out at the bottom is the failure mode this technique actually has.
  const scrolledBack = await page.evaluate(async () => {
    const box = document.getElementById("doc-content");
    const el = document.querySelector(".doc-backdrop");
    box.value = `${Array.from({ length: 60 }, (_, i) => `Filler line ${i}.`).join("\n")}\nA seperate word down here.`;
    box.dispatchEvent(new Event("input", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 500));
    box.scrollTop = box.scrollHeight;
    box.dispatchEvent(new Event("scroll", { bubbles: true }));
    await new Promise((r) => requestAnimationFrame(r));
    const finding = docProseFound.find((f) => f.text === "seperate");
    if (!finding) return { noFinding: true };
    box.setSelectionRange(finding.start, finding.start);
    const point = docCaretPoint(box);
    const mark = [...el.querySelectorAll("mark")].find((m) => m.textContent === "seperate");
    if (!mark) return { noMark: true };
    const rect = mark.getBoundingClientRect();
    return {
      inStep: el.scrollTop === box.scrollTop,
      scrollTop: box.scrollTop,
      dx: rect.left - point.x,
      dy: rect.top - point.y,
    };
  });
  ok("P0 the backdrop follows the textarea's scroll",
    scrolledBack.inStep === true, `scrollTop ${scrolledBack.scrollTop}`);
  ok("P0 a mark 60 lines down is still within 1px of its glyph",
    !scrolledBack.noMark && Math.abs(scrolledBack.dx) <= 1 && Math.abs(scrolledBack.dy) <= 1,
    scrolledBack.noMark ? "no mark" : `dx ${scrolledBack.dx.toFixed(2)} dy ${scrolledBack.dy.toFixed(2)}`);

  // ACCEPTANCE: type a misspelt word in Source, an underline appears within
  // 300ms. Measured from the keystroke to the frame the mark exists in, by
  // polling, not by waiting a fixed time and then looking.
  await page.evaluate(async (content) => {
    document.getElementById("doc-content").value = content;
    document.getElementById("doc-content").dispatchEvent(new Event("input", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 400));
  }, "The quick brown fox. ");
  // The clock starts at the *last* keystroke of the word, stamped by a
  // listener inside the page. Starting it before `keyboard.type` would be
  // measuring Playwright's key dispatch as well as the app, and the claim
  // being made is about the pause after you finish a word.
  await page.evaluate(() => {
    const box = document.getElementById("doc-content");
    box.focus();
    box.setSelectionRange(box.value.length, box.value.length);
    window.__lastKey = null;
    box.addEventListener("input", () => { window.__lastKey = performance.now(); });
  });
  await page.keyboard.type("recieve");
  const underlineMs = await page.evaluate(async () => {
    const el = document.querySelector(".doc-backdrop");
    for (let i = 0; i < 120; i += 1) {
      const hit = [...el.querySelectorAll("mark")].some((m) => m.textContent === "recieve");
      if (hit) return performance.now() - window.__lastKey;
      await new Promise((r) => requestAnimationFrame(r));
    }
    return null;
  });
  ok("P0 ACCEPTANCE: a misspelt word is underlined within 300ms of typing it",
    underlineMs !== null && underlineMs < 300,
    underlineMs === null ? "never underlined" : `${underlineMs.toFixed(0)}ms`);

  // Off where it cannot be right: Live and Rendered have no textarea to sit
  // behind, and a code file has no prose findings to draw.
  const offWhenNotSource = await page.evaluate(async () => {
    const el = document.querySelector(".doc-backdrop");
    setDocView("live");
    await new Promise((r) => setTimeout(r, 300));
    const live = el.classList.contains("hidden");
    const inkedInLive = document.getElementById("doc-content").classList.contains("has-backdrop");
    setDocView("source");
    await new Promise((r) => setTimeout(r, 300));
    return { live, inkedInLive, backInSource: !el.classList.contains("hidden") };
  });
  ok("P0 the backdrop is off in Live view and back on in Source",
    offWhenNotSource.live && !offWhenNotSource.inkedInLive && offWhenNotSource.backInSource,
    JSON.stringify(offWhenNotSource));

  // A code file has no prose findings, so it has no backdrop either. The type
  // can change under an open document, and `syncDocFileType` never re-ran the
  // prose pass: before this, switching a markdown file to .py left squiggles
  // under words in code, over a textarea whose own ink is transparent.
  const typeSwitch = await page.evaluate(async () => {
    const read = () => {
      const box = document.getElementById("doc-content");
      const back = document.querySelector(".doc-backdrop");
      return {
        ext: docFileType().ext,
        hidden: back.classList.contains("hidden"),
        inked: box.classList.contains("has-backdrop"),
        findings: docProseFound.length,
        ink: getComputedStyle(box).color,
      };
    };
    const pick = async (ext) => {
      const select = document.getElementById("doc-file-type");
      const option = [...select.options].find((o) => o.value === ext);
      if (!option) return null;
      select.value = ext;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 900));
      return read();
    };
    const before = read();
    const code = await pick("py");
    const back = await pick("md");
    return { before, code, back };
  });
  ok("P0 switching to a code file takes the backdrop away and the ink back",
    typeSwitch.code && typeSwitch.code.hidden && !typeSwitch.code.inked &&
      typeSwitch.code.findings === 0 && typeSwitch.code.ink !== "rgba(0, 0, 0, 0)",
    JSON.stringify(typeSwitch.code));
  ok("P0 switching back to markdown restores it",
    typeSwitch.back && !typeSwitch.back.hidden && typeSwitch.back.inked &&
      typeSwitch.back.findings === typeSwitch.before.findings,
    JSON.stringify(typeSwitch.back));

  // --- 2. one click opens the suggestions ----------------------------------
  // Back to the small document, and typed rather than assigned, so the whole
  // path (input, debounce, findings, backdrop) is the one under test.
  await page.evaluate(async (content) => {
    const box = document.getElementById("doc-content");
    box.value = content;
    box.dispatchEvent(new Event("input", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 400));
  }, P0);

  // A real mouse click at the centre of the underline, not a synthesised
  // event on an element: the click has to land in the textarea and be turned
  // back into a finding, which is the whole mechanism.
  const markBox = await page.evaluate(() => {
    const mark = [...document.querySelectorAll(".doc-backdrop mark")]
      .find((m) => m.textContent === "teh");
    const r = mark.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  });
  await page.mouse.click(markBox.x, markBox.y);
  await page.waitForTimeout(250);
  const clicked = await page.evaluate(() => {
    const menu = document.getElementById("doc-suggest-menu");
    const first = menu.querySelector(".doc-suggest-item");
    return {
      open: !menu.classList.contains("hidden"),
      word: menu.querySelector(".doc-suggest-head strong")?.textContent,
      why: menu.querySelector(".doc-suggest-why")?.textContent,
      first: first?.textContent.trim(),
      // The caret stays in the text on a plain click, so typing carries on.
      focusIsMenu: menu.contains(document.activeElement),
      items: [...menu.querySelectorAll(".doc-suggest-item")].map((b) => b.textContent.trim()),
    };
  });
  ok("P0 ACCEPTANCE: one click on an underline opens the menu", clicked.open,
    JSON.stringify(clicked).slice(0, 160));
  ok("P0 the menu is about the word that was clicked", clicked.word === "teh", clicked.word);
  ok("P0 every finding carries a one-line why", !!clicked.why && clicked.why.length > 0,
    JSON.stringify(clicked.why));
  ok("P0 a plain click leaves the caret in the text", clicked.focusIsMenu === false);
  ok("P0 the menu offers 'Add to dictionary' and 'Ignore in this document'",
    clicked.items.some((t) => /Add .* to dictionary/.test(t)) &&
      clicked.items.some((t) => /Ignore in this document/.test(t)),
    JSON.stringify(clicked.items));

  // ACCEPTANCE: the first item replaces the word.
  const replaced = await page.evaluate(async () => {
    const before = document.getElementById("doc-content").value;
    document.querySelector("#doc-suggest-menu .doc-suggest-item").click();
    await new Promise((r) => setTimeout(r, 400));
    return { before, after: document.getElementById("doc-content").value };
  });
  ok("P0 ACCEPTANCE: the menu's first item replaces the word",
    replaced.before.includes("teh ") && replaced.after.includes("the beta") &&
      !replaced.after.includes("teh "),
    JSON.stringify(replaced.after.slice(0, 30)));

  // Ranked candidates: a word one edit from something the app knows gets that
  // word offered even though no rule has an answer for it.
  const ranked = await page.evaluate(() => {
    const near = docSuggestAlternatives({
      rule: "spelling", text: "enviroment", replacement: null, start: 0, end: 10,
    });
    const distances = [
      ["teh", "the", docEditDistance("teh", "the", 2)],
      ["recieve", "receive", docEditDistance("recieve", "receive", 2)],
      ["colour", "color", docEditDistance("colour", "color", 2)],
      ["alpha", "omega", docEditDistance("alpha", "omega", 2)],
    ];
    return { near, distances, cap: DOC_SUGGEST_MAX, pool: docKnownWords().length };
  });
  ok("P0 a transposition is one edit, a far word is over the cap",
    ranked.distances[0][2] === 1 && ranked.distances[1][2] === 1 &&
      ranked.distances[2][2] === 1 && ranked.distances[3][2] > 2,
    ranked.distances.map((d) => `${d[0]}/${d[1]}=${d[2]}`).join(" "));
  ok("P0 the nearest known word is offered even with no rule answer",
    ranked.near.includes("environment"), JSON.stringify(ranked.near));
  ok("P0 the candidate list is capped", ranked.near.length <= ranked.cap,
    `${ranked.near.length} of at most ${ranked.cap}, from a pool of ${ranked.pool}`);

  // ACCEPTANCE: F8 moves to the next finding.
  const stepped = await page.evaluate(async () => {
    const box = document.getElementById("doc-content");
    closeDocSuggest();
    box.focus();
    box.setSelectionRange(0, 0);
    return { count: docProseFound.length, first: docProseFound[0].text };
  });
  await page.keyboard.press("F8");
  await page.waitForTimeout(300);
  const f8 = await page.evaluate(() => ({
    open: !document.getElementById("doc-suggest-menu").classList.contains("hidden"),
    on: docSuggestOpenFor && docSuggestOpenFor.text,
  }));
  await page.keyboard.press("F8");
  await page.waitForTimeout(300);
  const f8next = await page.evaluate(() => docSuggestOpenFor && docSuggestOpenFor.text);
  await page.keyboard.press("Shift+F8");
  await page.waitForTimeout(300);
  const f8back = await page.evaluate(() => docSuggestOpenFor && docSuggestOpenFor.text);
  ok("P0 ACCEPTANCE: F8 opens the first finding and moves to the next",
    f8.open && f8.on === stepped.first && f8next !== null && f8next !== f8.on,
    `${stepped.count} findings: ${f8.on} -> ${f8next}`);
  ok("P0 Shift+F8 steps back", f8back === f8.on, `${f8next} -> ${f8back}`);

  // Alt+Enter on a finding opens the same menu.
  const altEnter = await page.evaluate(async () => {
    closeDocSuggest();
    const box = document.getElementById("doc-content");
    const finding = docProseFound[1];
    box.focus();
    box.setSelectionRange(finding.start + 1, finding.start + 1);
    return finding.text;
  });
  await page.keyboard.press("Alt+Enter");
  await page.waitForTimeout(250);
  const altOpen = await page.evaluate(() => ({
    open: !document.getElementById("doc-suggest-menu").classList.contains("hidden"),
    on: docSuggestOpenFor && docSuggestOpenFor.text,
    focusIsMenu: document.getElementById("doc-suggest-menu").contains(document.activeElement),
  }));
  ok("P0 Alt+Enter on a finding opens its menu and takes the focus",
    altOpen.open && altOpen.on === altEnter && altOpen.focusIsMenu,
    JSON.stringify(altOpen));

  // Double-click and right-click still work, and the right-click path is the
  // one that was silently wrong before: `caretPositionFromPoint` inside a
  // textarea returns a per-line offset, so on line 3 it looked up the wrong
  // place entirely. Driven on a finding that is NOT on the first line.
  const laterLine = await page.evaluate(() => {
    closeDocSuggest();
    const finding = docProseFound.find((f) => f.start > 40);
    const mark = [...document.querySelectorAll(".doc-backdrop mark")]
      .find((m) => m._docFinding === finding);
    const r = mark.getBoundingClientRect();
    return { text: finding.text, x: r.left + r.width / 2, y: r.top + r.height / 2 };
  });
  await page.mouse.click(laterLine.x, laterLine.y, { button: "right" });
  await page.waitForTimeout(250);
  const rightClicked = await page.evaluate(() => ({
    open: !document.getElementById("doc-suggest-menu").classList.contains("hidden"),
    on: docSuggestOpenFor && docSuggestOpenFor.text,
  }));
  ok("P0 right-click opens the right finding on a line that is not the first",
    rightClicked.open && rightClicked.on === laterLine.text,
    `wanted ${laterLine.text}, got ${rightClicked.on}`);
  await page.evaluate(() => closeDocSuggest());
  await page.mouse.dblclick(laterLine.x, laterLine.y);
  await page.waitForTimeout(250);
  const doubleClicked = await page.evaluate(() => ({
    open: !document.getElementById("doc-suggest-menu").classList.contains("hidden"),
    on: docSuggestOpenFor && docSuggestOpenFor.text,
  }));
  ok("P0 double-click still opens the same menu",
    doubleClicked.open && doubleClicked.on === laterLine.text,
    JSON.stringify(doubleClicked));

  // ACCEPTANCE: the same click-to-suggest in Live view, where the mark is a
  // real element rather than a backdrop.
  await page.evaluate(() => {
    closeDocSuggest();
    setDocView("live");
  });
  await page.waitForTimeout(700);
  const liveMark = await page.evaluate(() => {
    const mark = [...document.querySelectorAll("#doc-live .doc-flag")]
      .find((m) => m.textContent === "teh" || m.textContent === "the the");
    if (!mark) return { missing: true };
    const r = mark.getBoundingClientRect();
    return { text: mark.textContent, x: r.left + r.width / 2, y: r.top + r.height / 2 };
  });
  if (!liveMark.missing) {
    await page.mouse.click(liveMark.x, liveMark.y);
    await page.waitForTimeout(300);
  }
  const liveOpen = await page.evaluate(() => ({
    open: !document.getElementById("doc-suggest-menu").classList.contains("hidden"),
    on: docSuggestOpenFor && docSuggestOpenFor.text,
  }));
  ok("P0 ACCEPTANCE: one click on a Live-view underline opens the menu too",
    !liveMark.missing && liveOpen.open && liveOpen.on === liveMark.text,
    liveMark.missing ? "no mark in Live" : `${liveMark.text} -> ${liveOpen.on}`);
  await page.evaluate(() => {
    closeDocSuggest();
    setDocView("source");
  });
  await page.waitForTimeout(400);

  // --- 3. the status bar count is a control --------------------------------
  const chip = await page.evaluate(() => {
    const el = document.getElementById("doc-prose");
    const style = getComputedStyle(el);
    return {
      tag: el.tagName,
      label: document.getElementById("doc-prose-count").textContent,
      controls: el.getAttribute("aria-controls"),
      expanded: el.getAttribute("aria-expanded"),
      chip: el.classList.contains("has-findings"),
      // A count with something behind it takes an edge and a wash; the empty
      // state stays flat, so the chip reads as pressable only when it is.
      border: style.borderColor,
      background: style.backgroundColor,
      // The switches are out of the bar and into the kebab, ids intact.
      switchesInBar: document.querySelectorAll("#doc-statusbar input[type=checkbox]").length,
      switchesInMenu: document.querySelectorAll("#doc-dock-menu input[type=checkbox]").length,
      autocorrect: !!document.getElementById("doc-autocorrect"),
      complete: !!document.getElementById("doc-complete"),
    };
  });
  ok("P0 the findings count is a button with the panel as its target",
    chip.tag === "BUTTON" && chip.controls === "doc-prose-panel", JSON.stringify(chip.controls));
  ok("P0 a real count paints as a chip", chip.chip && chip.background !== "rgba(0, 0, 0, 0)",
    `${chip.label}: border ${chip.border}, background ${chip.background}`);
  ok("P0 the two switches left the status bar for the kebab, ids intact",
    chip.switchesInBar === 0 && chip.switchesInMenu === 2 && chip.autocorrect && chip.complete,
    `bar ${chip.switchesInBar}, menu ${chip.switchesInMenu}`);

  // The switch still drives its preference, from its new home.
  const switched = await page.evaluate(() => {
    const box = document.getElementById("doc-autocorrect");
    const before = docToolPref("autocorrect", false);
    box.click();
    const after = docToolPref("autocorrect", false);
    box.click();
    return { before, after, restored: docToolPref("autocorrect", false) };
  });
  ok("P0 a switch in the kebab still writes its preference",
    switched.before !== switched.after && switched.restored === switched.before,
    JSON.stringify(switched));

  // ACCEPTANCE: the chip opens the panel, and the panel groups by kind.
  await page.click("#doc-prose");
  await page.waitForTimeout(300);
  const panel = await page.evaluate(() => {
    const el = document.getElementById("doc-prose-panel");
    const groups = [...el.querySelectorAll(".doc-prose-group")].map((g) => ({
      label: g.firstChild.textContent,
      count: Number(g.querySelector(".doc-prose-group-count").textContent),
      rows: g.nextElementSibling ? g.nextElementSibling.querySelectorAll(".doc-prose-row").length : 0,
    }));
    return {
      open: !el.classList.contains("hidden"),
      expanded: document.getElementById("doc-prose").getAttribute("aria-expanded"),
      groups,
      total: docProseFound.length,
    };
  });
  ok("P0 ACCEPTANCE: the status chip opens the suggestions panel",
    panel.open && panel.expanded === "true", JSON.stringify({ open: panel.open, expanded: panel.expanded }));
  // The rows were centred: a `<button>` takes the app's global
  // `justify-content: center`, and the `text-align: left` beside it has
  // nothing to align on a flex container. Measured, a row starting at x=326
  // whose first word began at x=751.7.
  const rowAlign = await page.evaluate(() => {
    const jump = document.querySelector(".doc-prose-jump");
    return {
      rowLeft: jump.getBoundingClientRect().left,
      wordLeft: jump.querySelector(".doc-prose-what").getBoundingClientRect().left,
    };
  });
  ok("P0 panel rows start at the left of the list, not the middle",
    rowAlign.wordLeft - rowAlign.rowLeft < 16,
    `row ${rowAlign.rowLeft.toFixed(0)}, first word ${rowAlign.wordLeft.toFixed(0)}`);
  ok("P0 the panel groups findings by kind, with a count on each group",
    panel.groups.length >= 2 &&
      panel.groups.every((g) => g.count === g.rows && g.count > 0) &&
      panel.groups.reduce((n, g) => n + g.count, 0) === panel.total,
    panel.groups.map((g) => `${g.label} ${g.count}`).join(", "));
  await page.click("#doc-prose");
  await page.waitForTimeout(200);

  // =========================================================================
  // The line-number gutter, in all three editors
  // =========================================================================
  //
  // Reported with a screenshot: gutter rows 1..18 continuing below a textarea
  // that ended at row 11, and numbers out of step with the text. Measured
  // before the fix, in the documents editor: the column was 9.6px taller than
  // the box even untouched, 325.4px taller once the resize handle was dragged
  // shorter, every number sat 1.59px above its line (the stylesheet's static
  // `padding-top: 0.5rem` against the textarea's `--space-4`), and a 200px
  // scroll moved the column only 139px because a too-tall gutter has a
  // shorter scrollable range.
  //
  // The check is the one the report implies: put 30 lines in, compare the top
  // of gutter row N with where the textarea actually draws line N, scroll,
  // and compare again.
  const GUTTER_LINES = Array.from(
    { length: 30 }, (_, i) => `Line ${i + 1} of the document under test.`
  ).join("\n");

  //: Runs in the page. Row tops come from a Range over the numbers' own text
  //: node; line tops come from `docCaretPoint`, which is the app's independent
  //: measurement of where a character sits inside the textarea.
  const gutterMeasure = (boxId) => {
    const box = document.getElementById(boxId);
    const gutter = [...document.querySelectorAll(".doc-gutter")]
      .find((g) => (g.dataset.for ? g.dataset.for : "doc-content") === boxId);
    if (!gutter || gutter.classList.contains("hidden")) return { missing: true };
    const boxRect = box.getBoundingClientRect();
    const gutRect = gutter.getBoundingClientRect();
    const node = gutter.firstChild;
    const text = gutter.textContent;
    const rowTop = (n) => {
      const start = text.split("\n").slice(0, n - 1).join("\n").length + (n > 1 ? 1 : 0);
      const range = document.createRange();
      range.setStart(node, start);
      range.setEnd(node, start + String(n).length);
      return range.getBoundingClientRect().top;
    };
    const lineTop = (n) => {
      const at = box.value.split("\n").slice(0, n - 1).join("\n").length + (n > 1 ? 1 : 0);
      box.setSelectionRange(at, at);
      return docCaretPoint(box).y;
    };
    const rows = [1, 5, 11, 20, 30].map((n) => ({ n, delta: rowTop(n) - lineTop(n) }));
    const style = getComputedStyle(gutter);
    const boxStyle = getComputedStyle(box);
    return {
      overflow: gutRect.bottom - boxRect.bottom,
      heights: [boxRect.height, gutRect.height],
      scroll: [box.scrollTop, gutter.scrollTop],
      metrics: [boxStyle.paddingTop === style.paddingTop, boxStyle.lineHeight === style.lineHeight,
        boxStyle.fontSize === style.fontSize],
      worst: Math.max(...rows.map((r) => Math.abs(r.delta))),
      rows,
    };
  };

  const gutterOk = (where, m) => {
    ok(`gutter (${where}) is clipped to the textarea, not the row`,
      !m.missing && Math.abs(m.overflow) <= 1,
      m.missing ? "no gutter" : `${m.overflow.toFixed(1)}px past the box, heights ${m.heights.map((h) => h.toFixed(0)).join(" vs ")}`);
    ok(`gutter (${where}) takes the textarea's own padding, line-height and size`,
      !m.missing && m.metrics.every(Boolean), JSON.stringify(m.metrics));
    ok(`gutter (${where}) scrolls in lock-step`,
      !m.missing && m.scroll[0] === m.scroll[1], `box ${m.scroll[0]}, gutter ${m.scroll[1]}`);
    ok(`gutter (${where}) rows sit on their lines within 1px`,
      !m.missing && m.worst <= 1,
      m.missing ? "no gutter" : m.rows.map((r) => `${r.n}:${r.delta.toFixed(2)}`).join(" "));
  };

  // --- the documents editor, including a textarea dragged shorter
  await page.evaluate(async (content) => {
    localStorage.setItem("doc-gutter", "1");
    setDocView("source");
    const box = document.getElementById("doc-content");
    box.value = content;
    box.dispatchEvent(new Event("input", { bubbles: true }));
    applyDocGutter();
    // What the report's screenshot shows: the native resize handle dragged up.
    box.style.height = "260px";
    await new Promise((r) => setTimeout(r, 400));
  }, GUTTER_LINES);
  await page.waitForTimeout(300);
  gutterOk("documents", await page.evaluate(`(${gutterMeasure})("doc-content")`));
  // The reading measure centres the textarea in its row while the gutter sits
  // at the row's left edge, so turning numbers on used to put 178px of empty
  // card between the column and the code, each with a squared-off shared edge
  // facing nothing.
  const gutterGap = await page.evaluate(() => {
    const g = document.getElementById("doc-gutter").getBoundingClientRect();
    const b = document.getElementById("doc-content").getBoundingClientRect();
    return b.left - g.right;
  });
  ok("gutter (documents) touches the textarea it numbers", Math.abs(gutterGap) < 1,
    `${gutterGap.toFixed(1)}px between them`);
  await page.evaluate(async () => {
    const box = document.getElementById("doc-content");
    box.scrollTop = 200;
    box.dispatchEvent(new Event("scroll", { bubbles: true }));
    await new Promise((r) => requestAnimationFrame(r));
  });
  gutterOk("documents, scrolled", await page.evaluate(`(${gutterMeasure})("doc-content")`));

  // --- the capture form. `#capture` is a hidden card until the section is
  // shown, and a textarea inside `display: none` measures zero.
  await page.evaluate(async (content) => {
    switchTab("notes");
    showNotesSection("capture", { focus: true });
    await new Promise((r) => setTimeout(r, 400));
    const box = document.getElementById("entry-content");
    box.value = content;
    box.dispatchEvent(new Event("input", { bubbles: true }));
    applyDocGutter();
    await new Promise((r) => setTimeout(r, 400));
  }, GUTTER_LINES);
  await page.waitForTimeout(500);
  await page.evaluate(async () => {
    const box = document.getElementById("entry-content");
    box.scrollTop = 120;
    box.dispatchEvent(new Event("scroll", { bubbles: true }));
    await new Promise((r) => requestAnimationFrame(r));
  });
  gutterOk("capture form", await page.evaluate(`(${gutterMeasure})("entry-content")`));

  // --- the note edit form, whose gutter is built by `mountGutterFor` into a
  // detached <li> and whose line-height (24px) differs from the capture
  // form's (23.2px). One static CSS value could not have been right for both,
  // which is the argument for copying each box's own metrics.
  const editBox = await page.evaluate(async (content) => {
    const r = await api("/entries", { method: "POST", body: JSON.stringify({ content, tags: ["gutter"] }) });
    const made = await r.json();
    showNotesSection("browse");
    await loadEntries();
    editingId = made.id;
    renderEntries();
    await new Promise((wait) => setTimeout(wait, 600));
    applyDocGutter();
    const box = document.querySelector(".gutter-wrap > textarea:not(#entry-content)");
    if (!box) return { missing: true };
    box.scrollTop = 90;
    box.dispatchEvent(new Event("scroll", { bubbles: true }));
    return { id: box.id };
  }, GUTTER_LINES);
  await page.waitForTimeout(500);
  gutterOk("note edit form",
    editBox.missing ? { missing: true } : await page.evaluate(`(${gutterMeasure})("${editBox.id}")`));

  await page.waitForTimeout(400);
  ok("no console errors", consoleErrors.length === 0, JSON.stringify(consoleErrors.slice(0, 4)));

  console.log(`\n${checks - failures}/${checks} checks passed`);
  await browser.close();
  process.exit(failures ? 1 : 0);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
