// The whiteboard's tool rail and its keys (Phase 1), and its context bar
// (Phase 2). Phase 3's own gate is `whiteboard3.js` beside this: one sweep
// that ran both took more than the 110s a Bash call gets.
//
//   BASE=http://127.0.0.1:8903 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     timeout 110 node scratchpad/ui-sweeps/whiteboard.js
//
// WHITEBOARD_PLAN.md Phase 1's gate, in its own words: every tool has a
// tooltip naming a key; pressing each key selects that tool; the rail is one
// panel with one control height; no tool button has its own border.
//
// VIEWPORT=390x844 and THEME=dark both work (lib.js reads the theme).
const { boot, OUT } = require("./lib.js");
const { execSync } = require("child_process");

const [VW, VH] = (process.env.VIEWPORT || "1440x900").split("x").map(Number);
const VIEWPORT = { width: VW, height: VH };

let pass = 0;
let fail = 0;
function ok(name, good, detail) {
  if (good) {
    pass += 1;
    console.log(`OK   ${name}${detail ? `  ${detail}` : ""}`);
  } else {
    fail += 1;
    console.log(`FAIL ${name}${detail ? `  ${detail}` : ""}`);
  }
}

// Clicks through the real UI, the way mapstrip.js does: `openWhiteboardBoard`
// called from `page.evaluate` leaves the boards landing showing and the board
// never opens (agent-remaining/mindmap.md, "what the next run should not
// repeat").
async function newBoard(page, name, type) {
  await page.click('[data-tab="library"]');
  await page.waitForTimeout(500);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(700);
  await page.click("#wb-boards-new");
  await page.waitForTimeout(700);
  await page.fill(".confirm-overlay input[type=text]", name);
  if (type === "map") await page.click('.confirm-overlay .seg button[data-value="map"]');
  await page.click(".confirm-overlay .confirm-actions button:last-child");
  await page.waitForTimeout(2500);
  await page.keyboard.press("Escape");
}

// Gives the canvas the keyboard. Left of centre on purpose: the properties
// drawer is 13.5rem of the right-hand edge and at 390x844 that is more than
// half the board, so a click at the middle lands on the drawer's thickness
// slider and Playwright retries it for thirty seconds (Phase 2 removes the
// drawer; until then the sweep aims around it).
async function clickCanvas(page) {
  await page.click("#whiteboard-container", { position: { x: 40, y: 300 } });
  await page.waitForTimeout(150);
}

(async () => {
  const { browser, page } = await boot({ viewport: VIEWPORT });
  await newBoard(page, "Rail sweep", "board");

  // --- 1. every tool button names a key in its tooltip ----------------------
  // The shape sub-tools live in a flyout, so the rail is read as "every
  // `[data-tool]` button anywhere under the tools panel", which is what a
  // person can reach with one click or one key.
  const tools = await page.evaluate(() => {
    const out = [];
    for (const b of document.querySelectorAll("#wb-tools-panel [data-tool], #wb-tools-panel [data-wb-key]")) {
      if (b.closest('[data-wb-surface="map"]')) continue;
      out.push({
        tool: b.dataset.tool || b.id,
        key: b.dataset.wbKey || null,
        title: b.getAttribute("title") || "",
        label: b.getAttribute("aria-label") || "",
        hidden: b.offsetParent === null,
      });
    }
    return out;
  });
  const keyless = tools.filter((t) => !/\(([^)]*\b[A-Z0-9]\b[^)]*)\)/.test(t.title));
  ok(
    "every tool's tooltip names a key",
    keyless.length === 0,
    `${tools.length} tools, ${keyless.length} without a key: ${keyless.map((t) => t.tool).join(", ") || "none"}`,
  );
  const labelless = tools.filter((t) => !t.label);
  ok("every tool has an aria-label", labelless.length === 0, `${labelless.length} without one`);

  // --- 2. pressing each key selects that tool -------------------------------
  // The key written in the tooltip is the one asserted, so the two can never
  // drift: a tooltip that lies fails here rather than being believed.
  await clickCanvas(page);
  await page.waitForTimeout(200);
  const keyResults = [];
  for (const t of tools) {
    // Action keys (the image upload) press a button rather than hold a mode,
    // so `window.currentTool` is the wrong question for them; check 5 asks the
    // right one.
    if (t.key) continue;
    const m = t.title.match(/\(([^)]+)\)/);
    if (!m) continue;
    const key = m[1].split(/[/,]/)[0].trim();
    if (key.length !== 1) continue; // chords (Ctrl+Z) are not tool keys
    await page.keyboard.press(key.toLowerCase());
    await page.waitForTimeout(80);
    const active = await page.evaluate(() => window.currentTool);
    keyResults.push({ key, want: t.tool, got: active });
  }
  const wrongKey = keyResults.filter((r) => r.got !== r.want);
  ok(
    "pressing each tool's key selects that tool",
    wrongKey.length === 0,
    `${keyResults.length} keys, ${wrongKey.length} wrong: ${wrongKey.map((r) => `${r.key}->${r.got} (want ${r.want})`).join(", ") || "none"}`,
  );

  // --- 3. the rail is one panel at one control height -----------------------
  const rail = await page.evaluate(() => {
    const panel = document.getElementById("wb-tools-panel");
    if (!panel) return null;
    const cs = getComputedStyle(panel);
    const opaque = [];
    const heights = [];
    const borders = [];
    for (const el of panel.querySelectorAll("*")) {
      if (el.offsetParent === null) continue;
      const s = getComputedStyle(el);
      const bg = s.backgroundColor;
      if (bg && bg !== "transparent" && !/rgba\(0, 0, 0, 0\)/.test(bg)) {
        opaque.push({ cls: el.className.toString().slice(0, 40), bg, active: el.classList.contains("active") });
      }
      if (el.matches("button")) {
        const r = el.getBoundingClientRect();
        heights.push(Math.round(r.height));
        // A *painted* border, not a reserved one. Every ghost button keeps a
        // 1px transparent edge so its box does not jump when the fill comes
        // back under the pointer; what the gate is about is whether the
        // button draws a rim of its own inside the bar, which is a colour
        // question, not a width one.
        const bw = [s.borderTopWidth, s.borderRightWidth, s.borderBottomWidth, s.borderLeftWidth]
          .map((v) => parseFloat(v) || 0);
        const bc = [s.borderTopColor, s.borderRightColor, s.borderBottomColor, s.borderLeftColor];
        const painted = bw.some((v, i) => v > 0 && !/rgba\([^)]*,\s*0\)$/.test(bc[i]));
        if (painted) borders.push({ cls: el.className.toString().slice(0, 40), bw, bc });
      }
    }
    return {
      rect: panel.getBoundingClientRect().toJSON(),
      panelBg: cs.backgroundColor,
      isRail: panel.classList.contains("wb-rail"),
      opaqueChildren: opaque,
      heights: [...new Set(heights)].sort((a, b) => a - b),
      borders,
      count: panel.querySelectorAll("button").length,
    };
  });
  ok("the tools panel carries the rail recipe", rail && rail.isRail, rail ? `classes ${rail.isRail}` : "no panel");
  // One panel: one painted surface, plus the one active tool. Anything else
  // with a background of its own is a second surface inside the first, which
  // is what INBOX 52 and 65 reported ("the buttons look separate from the
  // panels").
  const extraSurfaces = (rail?.opaqueChildren || []).filter((o) => !o.active);
  ok(
    "one painted surface in the rail, plus the active tool",
    extraSurfaces.length === 0,
    `${rail?.opaqueChildren.length} painted children, ${extraSurfaces.length} not the active tool`,
  );
  ok(
    "one control height across the rail",
    rail && rail.heights.length === 1,
    `heights ${JSON.stringify(rail?.heights)} across ${rail?.count} buttons`,
  );
  ok(
    "no tool button draws its own border",
    rail && rail.borders.length === 0,
    `${rail?.borders.length} bordered: ${(rail?.borders || []).map((b) => b.cls).join(", ") || "none"}`,
  );

  // --- 4. the ink swatch ----------------------------------------------------
  const ink = await page.evaluate(() => {
    const sw = document.getElementById("wb-rail-ink");
    if (!sw) return null;
    const r = sw.getBoundingClientRect();
    return {
      inRail: Boolean(sw.closest("#wb-tools-panel")),
      rect: r.toJSON(),
      title: sw.getAttribute("title") || "",
      label: sw.getAttribute("aria-label") || "",
      key: sw.dataset.wbKey || null,
    };
  });
  ok(
    "the ink swatch is on the rail",
    Boolean(ink && ink.inRail),
    ink ? `${Math.round(ink.rect.width)}x${Math.round(ink.rect.height)} at ${Math.round(ink.rect.x)},${Math.round(ink.rect.y)}` : "missing",
  );
  if (ink) {
    // The colour is read off the pixels, not off `value` or a computed
    // background: a native colour input paints its value through
    // `::-webkit-color-swatch`, and neither of those two properties would
    // notice if that stopped happening (CLAUDE.md: a screenshot you look at
    // is not a measurement, and neither is a property beside the paint).
    await page.evaluate(() => {
      const sw = document.getElementById("wb-rail-ink");
      sw.value = "#ff0000";
      sw.dispatchEvent(new Event("input", { bubbles: true }));
      sw.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.waitForTimeout(200);
    // At phone width the rail scrolls sideways inside itself (measured at
    // 390x844: scrollWidth 835 in a 358px client box), so the swatch's first
    // rect can be outside the viewport entirely. Scroll it in and re-read the
    // box before clipping, rather than reporting the app broken for it.
    await page.locator("#wb-rail-ink").scrollIntoViewIfNeeded();
    await page.waitForTimeout(150);
    const box = await page.evaluate(() => document.getElementById("wb-rail-ink").getBoundingClientRect().toJSON());
    const shot = `${OUT}/wb-rail-ink.png`;
    await page.screenshot({ path: shot, clip: { x: box.x, y: box.y, width: box.width, height: box.height } });
    const mid = Math.round(box.width / 2);
    const px = execSync(`python3 ${__dirname}/../pngpixel.py ${shot} ${mid} ${mid}`).toString().trim();
    ok("the ink swatch paints the drawing colour", /\(255, 0, 0\)/.test(px), `centre pixel ${px.split("\n").pop()} after the swatch went #ff0000`);
    // And the other way: the rail is a control, not a read-out.
    const back = await page.evaluate(() => {
      const sw = document.getElementById("wb-rail-ink");
      sw.value = "#00ff00";
      sw.dispatchEvent(new Event("input", { bubbles: true }));
      sw.dispatchEvent(new Event("change", { bubbles: true }));
      return { stroke: window.currentStrokeColor, stored: localStorage.getItem("wb-stroke-color") };
    });
    ok(
      "the rail's swatch sets the drawing colour",
      back.stroke === "#00ff00" && back.stored === "#00ff00",
      `currentStrokeColor ${back.stroke}, stored ${back.stored}`,
    );
  }

  // --- 5. the keys the tooltips spell as chords -----------------------------
  // Shift+C is the board's second connector (INBOX: decision 8 names one
  // connector key and the board has two connector tools).
  await clickCanvas(page);
  await page.keyboard.press("Shift+c");
  await page.waitForTimeout(120);
  const curved = await page.evaluate(() => window.currentTool);
  ok("Shift+C picks the curved connector", curved === "link-curved", `currentTool ${curved}`);
  // I is an action key: it presses the upload button rather than holding a
  // mode. The click is watched rather than the file dialog, which Playwright
  // cannot complete.
  const fired = await page.evaluate(async () => {
    const btn = document.getElementById("wb-add-image");
    let hit = 0;
    const stop = (e) => { hit += 1; e.stopPropagation(); e.preventDefault(); };
    btn.addEventListener("click", stop, true);
    await new Promise((r) => setTimeout(r, 50));
    return new Promise((resolve) => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "i", bubbles: true }));
      setTimeout(() => { btn.removeEventListener("click", stop, true); resolve(hit); }, 200);
    });
  });
  ok("I presses the image upload button", fired === 1, `${fired} click(s) on #wb-add-image`);
  // The binding N took from the sticky note moved rather than vanished: this
  // is the regression check for that move, not a new feature's check.
  await clickCanvas(page);
  await page.keyboard.press("n");
  await page.waitForTimeout(150);
  const afterN = await page.evaluate(() => ({
    tool: window.currentTool,
    overview: !document.getElementById("wb-navigator").classList.contains("hidden"),
  }));
  await page.keyboard.press("Shift+n");
  await page.waitForTimeout(200);
  const afterShiftN = await page.evaluate(() => !document.getElementById("wb-navigator").classList.contains("hidden"));
  ok(
    "N is the sticky and Shift+N is the overview",
    afterN.tool === "sticky" && afterN.overview === false && afterShiftN === true,
    `N: tool ${afterN.tool}, overview ${afterN.overview}; Shift+N: overview ${afterShiftN}`,
  );

  // --- 6. the eleven arrange actions ----------------------------------------
  // Three text objects of deliberately different widths, so distribute by
  // centres and distribute by gaps cannot give the same answer: 100, 300 and
  // 100 wide, which is exactly the case §2 item 4 of the plan is about.
  // Objects come from the app's own `api()` (a bare fetch is 401 while the app
  // holds the unlock token), then the board is reloaded through the UI.
  const boardObjects = async (page, boxes) => page.evaluate(async (defs) => {
    // `let` at the top of a classic script is a global lexical binding, not a
    // property of `window`: `wbState` reads, `window.wbState` is undefined.
    const board = window.currentBoardId;
    const made = [];
    for (const d of defs) {
      const res = await api("/whiteboard/objects", {
        method: "POST",
        body: JSON.stringify({ kind: "text", board_id: board, x: d.x, y: d.y, width: d.w, height: d.h, data: { content: d.t } }),
      });
      made.push((await res.json()).id);
    }
    return made;
  }, boxes);

  const boxesNow = (ids) => page.evaluate((wanted) => wanted.map((id) => {
    const o = wbState.objects.find((i) => i.id === id);
    return o ? { id, x: Math.round(o.x), y: Math.round(o.y), w: Math.round(o.width), h: Math.round(o.height) } : null;
  }), ids);

  const made = await boardObjects(page, [
    { x: 100, y: 900, w: 100, h: 80, t: "one" },
    { x: 400, y: 900, w: 300, h: 120, t: "two" },
    { x: 1000, y: 900, w: 100, h: 60, t: "three" },
  ]);
  if (made.length !== 3) {
    ok("three test objects created", false, `got ${JSON.stringify(made)}`);
  } else {
    // `fetchWhiteboardState` and not `renderWhiteboard`: objects posted
    // straight to the API are not in `wbState` until the board re-reads it,
    // and `wbSelectAllItems` walks `wbState` (measured: 3 objects created, 0
    // selected, until this line existed).
    await page.evaluate(async () => { await fetchWhiteboardState(); wbSelectAllItems(); });
    await page.waitForTimeout(500);
    const selected = await page.evaluate(() => wbMultiSelection.size);

    // Align horizontal centres: every centre lands on the selection box's own
    // centre, which for 100..1100 is 600.
    await page.click("#wb-align-hcenter");
    await page.waitForTimeout(900);
    const aligned = await boxesNow(made);
    const centres = aligned.map((b) => b.x + b.w / 2);
    ok(
      "align centres puts every centre on the selection's centre",
      selected === 3 && centres.every((c) => Math.abs(c - 600) <= 1),
      `${selected} selected, centres ${JSON.stringify(centres)} (want 600)`,
    );

    // Put them back on a row of known, uneven positions and distribute the
    // gaps: spans 100 to 1100, 500 of box, so each of the two gaps is 250 and
    // the middle box starts at 100 + 100 + 250 = 450.
    await page.evaluate(async (ids) => {
      const put = async (id, x, y) => {
        const o = wbState.objects.find((i) => i.id === id);
        o.x = x; o.y = y;
        await api(`/whiteboard/objects/${id}`, { method: "PUT", body: JSON.stringify({ kind: o.kind, data: o.data, board_id: o.board_id, x, y, z: o.z, width: o.width, height: o.height }) });
      };
      await put(ids[0], 100, 900);
      await put(ids[1], 300, 900);
      await put(ids[2], 1000, 900);
      await fetchWhiteboardState();
      wbSelectAllItems();
    }, made);
    await page.waitForTimeout(500);
    await page.click("#wb-distribute-h");
    await page.waitForTimeout(900);
    const spread = await boxesNow(made);
    const byX = [...spread].sort((a, b) => a.x - b.x);
    const gaps = [byX[1].x - (byX[0].x + byX[0].w), byX[2].x - (byX[1].x + byX[1].w)];
    ok(
      "distribute leaves equal gaps, not equal centres",
      Math.abs(gaps[0] - gaps[1]) <= 1 && Math.abs(gaps[0] - 250) <= 1,
      `gaps ${JSON.stringify(gaps)} (want 250 and 250), boxes ${JSON.stringify(byX.map((b) => [b.x, b.w]))}`,
    );

    // Same size: the widest is 300 and the tallest 120, and every item takes
    // it while keeping its own top-left corner.
    const leftsBefore = (await boxesNow(made)).map((b) => b.x);
    await page.evaluate(() => wbSelectAllItems());
    await page.click("#wb-same-width");
    await page.waitForTimeout(900);
    await page.evaluate(() => wbSelectAllItems());
    await page.click("#wb-same-height");
    await page.waitForTimeout(900);
    const sized = await boxesNow(made);
    ok(
      "same size gives every item the largest width and height, in place",
      sized.every((b) => b.w === 300 && b.h === 120)
        && sized.map((b) => b.x).every((x, i) => Math.abs(x - leftsBefore[i]) <= 1),
      `sizes ${JSON.stringify(sized.map((b) => [b.w, b.h]))}, lefts ${JSON.stringify(sized.map((b) => b.x))} (were ${JSON.stringify(leftsBefore)})`,
    );
  }

  // --- 7. the context bar shows only the selected kind's controls ----------
  // WHITEBOARD_PLAN Phase 2's gate, in its own words. One of each kind is made
  // through the API and selected through the app's own `selectWbItem`, then
  // the bar's visible groups are read back and compared with the table's row.
  const kinds = await page.evaluate(async () => {
    const board = window.currentBoardId;
    const post = async (path, body) => (await api(path, { method: "POST", body: JSON.stringify(body) })).json();
    const sketch = async (data) => post("/whiteboard/sketches", { board_id: board, data: JSON.stringify(data), x: 0, y: 0 });
    const made = {};
    // A plain line: one subpath, so `wbSketchIsArrow` says no and the caps
    // group stays away.
    made.line = (await sketch({ d: "M 60 60 L 260 60", color: "#112233", width: 4, shape: "line" })).id;
    // An arrow: a second subpath is the head, and this one has a head at the
    // END only, which is the case the plan's section 2 item 4 is about.
    made.arrow = (await sketch({ d: "M 60 160 L 260 160 M 250 152 L 260 160 L 250 168", color: "#112233", width: 4, shape: "line", startCap: "none", endCap: "arrow" })).id;
    made.shape = (await sketch({ d: "M 60 260 L 260 260 L 260 360 L 60 360 Z", color: "#112233", width: 4, shape: "rect", fill: "#ff8800" })).id;
    made.text = (await post("/whiteboard/objects", { kind: "text", board_id: board, x: 400, y: 60, width: 200, height: 90, data: { content: "hello" } })).id;
    made.image = (await post("/whiteboard/objects", { kind: "image", board_id: board, x: 400, y: 200, width: 160, height: 120, data: { url: "/media/none.png" } })).id;
    // A note card, which the handle gate names alongside the other three. It
    // needs a real note behind it: a `node` is a note placed on a board, not a
    // kind of drawing.
    const entry = await post("/entries", { content: "A note on a board", tags: ["wbsweep"] });
    made.note = (await post("/whiteboard/nodes", { entry_id: entry.id, board_id: board, x: 700, y: 60, z: 1 })).id;
    // Both: `fetchWhiteboardState` fills `wbState` and `renderWhiteboard` is
    // what puts elements on the canvas. Without the second, every item exists
    // and none of them is in the DOM, so a check that reads a box measures
    // nothing (found exactly that way).
    await fetchWhiteboardState();
    renderWhiteboard();
    return made;
  });
  await page.waitForTimeout(600);

  const barFor = async (kind, id) => {
    await page.evaluate(([k, i]) => { wbMultiSelection.clear(); selectWbItem(k, i); }, [kind, id]);
    await page.waitForTimeout(250);
    return page.evaluate(() => {
      const bar = document.getElementById("wb-context");
      const box = bar.getBoundingClientRect();
      return {
        hidden: bar.classList.contains("hidden"),
        size: `${Math.round(box.width)}x${Math.round(box.height)}`,
        controls: [...bar.querySelectorAll("button, input, select, .seg")].filter((c) => c.offsetParent !== null && !c.closest(".wb-board-menu")).length,
        groups: [...bar.querySelectorAll(":scope > [data-wb-ctx]")].filter((g) => !g.classList.contains("hidden")).map((g) => g.dataset.wbCtx),
        more: [...document.querySelectorAll("#wb-context-menu [data-wb-ctx]")].filter((g) => !g.classList.contains("hidden")).map((g) => g.dataset.wbCtx),
        startcap: document.getElementById("wb-prop-startcap").value,
        endcap: document.getElementById("wb-prop-endcap").value,
        colour: document.getElementById("wb-prop-color").value,
      };
    });
  };

  const want = {
    line: ["ink", "stroke", "order", "common"],
    arrow: ["ink", "caps", "stroke", "order", "common"],
    shape: ["ink", "stroke", "fill", "order", "common"],
    text: ["ink", "text", "order", "common"],
    image: ["order", "common"],
    note: ["order", "common"],
  };
  const seen = {};
  const kindOf = (name) => (name === "note" ? "node" : name === "text" || name === "image" ? "object" : "sketch");
  for (const [name, id] of Object.entries(kinds)) {
    seen[name] = await barFor(kindOf(name), id);
  }
  const wrongGroups = Object.keys(want).filter((k) => JSON.stringify(seen[k].groups) !== JSON.stringify(want[k]));
  ok(
    "the bar shows only the selected kind's controls",
    wrongGroups.length === 0,
    Object.entries(seen).map(([k, v]) => `${k}: ${v.groups.join("+")} (${v.controls} controls, ${v.size})`).join("; "),
  );
  ok(
    "a plain line offers no line ends, an arrow does",
    !seen.line.groups.includes("caps") && seen.arrow.groups.includes("caps"),
    `line ${seen.line.groups.join("+")}, arrow ${seen.arrow.groups.join("+")}`,
  );
  // The caps come off the object, never off the tool's default: the arrow was
  // made with a head at one end only, and that is what has to be reported.
  ok(
    "the caps read from the object, not from the tool",
    seen.arrow.startcap === "none" && seen.arrow.endcap === "arrow",
    `start ${seen.arrow.startcap}, end ${seen.arrow.endcap} (drawn with a head at the end only)`,
  );
  ok(
    "the colour reads from the object",
    seen.shape.colour === "#112233",
    `#wb-prop-color ${seen.shape.colour} for a shape drawn in #112233`,
  );
  // The bar sits above the selection, not over it, and inside the canvas.
  await page.evaluate((id) => { wbMultiSelection.clear(); selectWbItem("object", id); }, kinds.text);
  await page.waitForTimeout(400);
  const placed = await page.evaluate((id) => {
    const bar = document.getElementById("wb-context").getBoundingClientRect();
    const host = document.getElementById("library-view-whiteboard").getBoundingClientRect();
    const item = document.querySelector(`.wb-object[data-id="${id}"]`)?.getBoundingClientRect();
    return { bar: bar.toJSON(), host: host.toJSON(), item: item ? item.toJSON() : null };
  }, kinds.text);
  const inside = placed.bar.left >= placed.host.left - 1 && placed.bar.right <= placed.host.right + 1
    && placed.bar.top >= placed.host.top - 1 && placed.bar.bottom <= placed.host.bottom + 1;
  // One control height across the bar, the same property the rail is held to:
  // a row where a select stands taller than the buttons beside it is the
  // "assembled rather than designed" read DESIGN.md's control-height section
  // is about.
  const heights = await page.evaluate(() => {
    const out = {};
    for (const c of document.querySelectorAll("#wb-context button, #wb-context input, #wb-context select, #wb-context .select-shell, #wb-context .seg")) {
      if (c.offsetParent === null || c.closest(".wb-board-menu")) continue;
      const h = Math.round(c.getBoundingClientRect().height);
      const name = `${c.tagName.toLowerCase()}${c.type ? `[${c.type}]` : ""}${c.className ? `.${c.className.toString().split(" ")[0]}` : ""}`;
      (out[h] = out[h] || []).push(name);
    }
    return out;
  });
  ok(
    "one control height across the context bar",
    Object.keys(heights).length === 1,
    Object.entries(heights).map(([h, names]) => `${h}px: ${[...new Set(names)].join(", ")}`).join(" | "),
  );

  // Above the item where there is room and below it where there is not (the
  // placement's own rule, so a bar never covers the rotate handle or the top
  // bar), and never across it either way.
  const clear = placed.item
    && (placed.bar.bottom <= placed.item.top + 1 || placed.bar.top >= placed.item.bottom - 1);
  ok(
    "the bar is inside the canvas and clear of the item",
    inside && Boolean(clear),
    `bar ${Math.round(placed.bar.top)} to ${Math.round(placed.bar.bottom)} (${Math.round(placed.bar.width)}x${Math.round(placed.bar.height)}), item ${placed.item ? `${Math.round(placed.item.top)} to ${Math.round(placed.item.bottom)}` : "n/a"}, canvas ${Math.round(placed.host.width)}x${Math.round(placed.host.height)}`,
  );
  // The "..." menu is the board menus' own recipe, so it escapes the canvas's
  // clipping and caps itself to the window rather than being cut off the way
  // the export popover was (the plan's section 2 item 3).
  await page.click('#wb-context [data-wb-menu-toggle]');
  await page.waitForTimeout(400);
  const menu = await page.evaluate(() => {
    const m = document.getElementById("wb-context-menu");
    const r = m.getBoundingClientRect();
    return { hidden: m.classList.contains("hidden"), rect: r.toJSON(), w: window.innerWidth, h: window.innerHeight };
  });
  ok(
    "the more menu opens inside the window",
    !menu.hidden && menu.rect.width > 0 && menu.rect.left >= -1 && menu.rect.right <= menu.w + 1
      && menu.rect.top >= -1 && menu.rect.bottom <= menu.h + 1,
    `menu ${Math.round(menu.rect.left)},${Math.round(menu.rect.top)} ${Math.round(menu.rect.width)}x${Math.round(menu.rect.height)} in ${menu.w}x${menu.h}`,
  );
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);

  // The drawer and the pill it replaced are gone, not hidden.
  const gone = await page.evaluate(() => ({
    drawer: Boolean(document.getElementById("wb-properties-panel")),
    pill: Boolean(document.getElementById("wb-selection-bar")),
  }));
  ok("the properties drawer and the selection pill are gone", !gone.drawer && !gone.pill, JSON.stringify(gone));

  console.log(`\n${pass}/${pass + fail} checks pass at ${VW}x${VH} (${process.env.THEME || "light"})`);
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
