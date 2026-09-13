// WHITEBOARD_PLAN.md Phase 3's gate: the export dialog, one handle recipe,
// and the highlighter's blend.
//
//   BASE=http://127.0.0.1:8903 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     timeout 110 node scratchpad/ui-sweeps/whiteboard3.js
//
// The plan's words: the export dialog is inside the viewport at 1440 and 390
// and every scope x format pair produces a file (PNG dimensions asserted);
// handles identical for note, shape, image and text (rect and handle count);
// the highlighter stroke composites (pixel sampled under overlap).
//
// Split from `whiteboard.js` (Phases 1 and 2) because one sweep that ran both
// took longer than the 110s a Bash call gets, not because they are unrelated.
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

(async () => {
  const { browser, page } = await boot({ viewport: VIEWPORT });
  await newBoard(page, "Phase 3 sweep", "board");

  // One of each kind, the same four the handle gate names, made through the
  // API and then rendered: `fetchWhiteboardState` fills `wbState` and
  // `renderWhiteboard` is what puts elements on the canvas.
  const kinds = await page.evaluate(async () => {
    const board = window.currentBoardId;
    const post = async (path, body) => (await api(path, { method: "POST", body: JSON.stringify(body) })).json();
    const sketch = async (data) => post("/whiteboard/sketches", { board_id: board, data: JSON.stringify(data), x: 0, y: 0 });
    const made = {};
    made.shape = (await sketch({ d: "M 60 260 L 260 260 L 260 360 L 60 360 Z", color: "#112233", width: 4, shape: "rect", fill: "#ff8800" })).id;
    made.text = (await post("/whiteboard/objects", { kind: "text", board_id: board, x: 400, y: 60, width: 200, height: 90, data: { content: "hello" } })).id;
    made.image = (await post("/whiteboard/objects", { kind: "image", board_id: board, x: 400, y: 200, width: 160, height: 120, data: { url: "/media/none.png" } })).id;
    const entry = await post("/entries", { content: "A note on a board", tags: ["wbsweep"] });
    made.note = (await post("/whiteboard/nodes", { entry_id: entry.id, board_id: board, x: 700, y: 60, z: 1 })).id;
    await fetchWhiteboardState();
    renderWhiteboard();
    return made;
  });
  await page.waitForTimeout(600);

  // --- 8. the export dialog (Phase 3) --------------------------------------
  // It opens inside the viewport, offers the matrix as two rows of segments,
  // and every scope by format pair that can produce a file does produce one.
  const openExport = async () => {
    await page.evaluate(() => { document.querySelector(".wb-export-overlay")?.remove(); wbExportBoard(); });
    await page.waitForTimeout(300);
  };
  await page.evaluate((id) => { wbMultiSelection.clear(); selectWbItem("object", id); }, kinds.text);
  await page.waitForTimeout(200);
  await openExport();
  const dialog = await page.evaluate(() => {
    const card = document.querySelector(".wb-export-card");
    if (!card) return null;
    const r = card.getBoundingClientRect();
    const segs = [...card.querySelectorAll(".wb-export-seg")].map((sg) => ({
      label: sg.getAttribute("aria-label"),
      options: [...sg.querySelectorAll("button")].map((b) => `${b.dataset.value}${b.disabled ? "(off)" : ""}`),
    }));
    return {
      rect: r.toJSON(), w: window.innerWidth, h: window.innerHeight, segs,
      // The app's filled tier is a `button.small` with no `.ghost`, which is
      // what DESIGN.md means by "one filled control per surface".
      primaries: [...card.querySelectorAll("button.small:not(.ghost)")].length,
      note: card.querySelector(".wb-export-note")?.textContent || "",
    };
  });
  ok(
    "the export dialog is inside the viewport",
    dialog && dialog.rect.left >= -1 && dialog.rect.top >= -1
      && dialog.rect.right <= dialog.w + 1 && dialog.rect.bottom <= dialog.h + 1,
    dialog ? `card ${Math.round(dialog.rect.left)},${Math.round(dialog.rect.top)} ${Math.round(dialog.rect.width)}x${Math.round(dialog.rect.height)} in ${dialog.w}x${dialog.h}` : "no dialog",
  );
  ok(
    "the choices are two segments, not a list",
    dialog && dialog.segs.length === 2 && dialog.segs[0].options.length === 4 && dialog.segs[1].options.length === 3,
    dialog ? dialog.segs.map((sg) => `${sg.label}: ${sg.options.join("/")}`).join(" | ") : "none",
  );
  ok(
    "one primary button, and a line saying what will happen",
    dialog && dialog.primaries === 1 && dialog.note.length > 10,
    dialog ? `${dialog.primaries} filled button, note "${dialog.note}"` : "none",
  );
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);

  // Every pair that writes a file, driven through the dialog's own buttons.
  // PDF is left out on purpose: it goes through the browser's print dialog,
  // which Playwright cannot complete (agent-remaining/mindmap.md says the same).
  const pairs = [];
  for (const format of ["png", "library", "svg"]) {
    for (const scope of ["selection", "visible", "whole"]) {
      if (format === "svg" && scope === "visible") continue;
      pairs.push([format, scope]);
    }
  }
  const results = [];
  for (const [format, scope] of pairs) {
    await page.evaluate((id) => { wbMultiSelection.clear(); selectWbItem("object", id); }, kinds.text);
    await page.waitForTimeout(150);
    await openExport();
    const picked = await page.evaluate(([f, sc]) => {
      const card = document.querySelector(".wb-export-card");
      const segs = card.querySelectorAll(".wb-export-seg");
      segs[0].querySelector(`button[data-value="${f}"]`).click();
      const scopeBtn = segs[1].querySelector(`button[data-value="${sc}"]`);
      if (scopeBtn.disabled) return false;
      scopeBtn.click();
      return true;
    }, [format, scope]);
    if (!picked) { results.push({ format, scope, note: "scope refused" }); await page.keyboard.press("Escape"); continue; }
    const wait = format === "library"
      ? page.waitForResponse((r) => r.url().includes("/media/upload"), { timeout: 15000 }).catch(() => null)
      : page.waitForEvent("download", { timeout: 15000 }).catch(() => null);
    await page.click("#wb-export-go");
    const got = await wait;
    if (!got) { results.push({ format, scope, note: "nothing" }); continue; }
    if (format === "library") {
      results.push({ format, scope, note: `upload ${got.status()}` });
      continue;
    }
    const file = `${OUT}/wb-export-${format}-${scope}`;
    await got.saveAs(file);
    if (format === "png") {
      const dims = execSync(`python3 ${__dirname}/../pngpixel.py ${file} 0 0`).toString().trim().split(/\s+/);
      results.push({ format, scope, note: dims[1] || "?" });
    } else {
      const bytes = require("fs").statSync(file).size;
      results.push({ format, scope, note: `${bytes}B` });
    }
  }
  const missing = results.filter((r) => r.note === "nothing" || r.note === "scope refused");
  const pngs = results.filter((r) => r.format === "png");
  ok(
    "every scope by format pair produces a file",
    missing.length === 0,
    results.map((r) => `${r.format}/${r.scope}=${r.note}`).join(" "),
  );
  ok(
    "the PNG exports have real pixel dimensions",
    pngs.length === 3 && pngs.every((r) => /^\d+x\d+$/.test(r.note) && Number(r.note.split("x")[0]) > 0),
    pngs.map((r) => `${r.scope} ${r.note}`).join(", "),
  );

  // --- 9. one handle recipe for every kind (Phase 3, decision 6) -----------
  // Eight handles, a rotate grip on a stem, and the selection box at
  // `--accent` 1px, the same for a note, a shape, an image and a text box.
  // Measured at zoom 1 so the SVG kinds' board-unit handles and the HTML
  // kinds' CSS-pixel ones are on one scale.
  await page.evaluate(() => d3.select("#whiteboard-container").call(wbZoom.transform, d3.zoomIdentity));
  await page.waitForTimeout(400);
  const handleFor = async (kind, id) => {
    await page.evaluate(([k, i]) => { wbMultiSelection.clear(); selectWbItem(k, i); renderWhiteboardNow(); }, [kind, id]);
    await page.waitForTimeout(350);
    return page.evaluate(([k, i]) => {
      const host = k === "sketch"
        ? document.querySelector(".wb-sketch-handle-group")
        : document.querySelector(`${k === "node" ? ".node-card" : ".wb-object"}[data-id="${i}"]`);
      if (!host) return null;
      const resize = [...host.querySelectorAll(".wb-resize-handle, .wb-sketch-resize-handle")];
      const rotate = host.querySelector(".wb-rotate-handle, .wb-sketch-rotate-handle");
      const stem = host.querySelector(".wb-rotate-handle-stem") || (rotate && getComputedStyle(rotate, "::before").height !== "0px" ? rotate : null);
      const box = (el) => { const r = el.getBoundingClientRect(); return `${Math.round(r.width)}x${Math.round(r.height)}`; };
      const item = k === "sketch"
        ? document.querySelector(`.sketch-group[data-id="${i}"]`)
        : host;
      const outline = k === "sketch"
        ? (() => { const r = document.querySelector(".wb-sketch-selection-box"); return r ? `${getComputedStyle(r).strokeWidth} ${getComputedStyle(r).stroke}` : "none"; })()
        : `${getComputedStyle(item).outlineWidth} ${getComputedStyle(item).outlineColor}`;
      return {
        count: resize.length,
        sizes: [...new Set(resize.map(box))],
        rotate: rotate ? box(rotate) : "none",
        stem: Boolean(stem),
        outline,
      };
    }, [kind, id]);
  };
  const hs = {
    note: await handleFor("node", kinds.note),
    shape: await handleFor("sketch", kinds.shape),
    text: await handleFor("object", kinds.text),
    image: await handleFor("object", kinds.image),
  };
  ok(
    "eight resize handles on every kind",
    Object.values(hs).every((h) => h && h.count === 8),
    Object.entries(hs).map(([k, h]) => `${k}: ${h ? h.count : "missing"}`).join(", "),
  );
  const sizes = Object.values(hs).flatMap((h) => (h ? h.sizes : ["?"]));
  ok(
    "the handles are the same rect on every kind",
    new Set(sizes).size === 1,
    Object.entries(hs).map(([k, h]) => `${k}: ${h ? h.sizes.join("/") : "?"}`).join(", "),
  );
  ok(
    "a rotate grip on a stem on every kind",
    Object.values(hs).every((h) => h && h.stem) && new Set(Object.values(hs).map((h) => h.rotate)).size === 1,
    Object.entries(hs).map(([k, h]) => `${k}: ${h ? `${h.rotate}${h.stem ? " on a stem" : " with no stem"}` : "?"}`).join(", "),
  );
  ok(
    "the selection box is one recipe on every kind",
    new Set(Object.values(hs).map((h) => (h ? h.outline : "?"))).size === 1,
    Object.entries(hs).map(([k, h]) => `${k}: ${h ? h.outline : "?"}`).join(" | "),
  );

  // --- 10. the highlighter composites (Phase 3, decision 7) ----------------
  // Two crossing strokes on a clean board, drawn with the real mouse (a
  // synthetic PointerEvent never reaches these handlers), then the crossing
  // sampled per pixel: a multiplying highlighter is strictly darker where the
  // two overlap than where either runs alone. Compared as a number, not looked
  // at.
  const board2 = await page.evaluate(async () => {
    const b = await (await api("/whiteboard/boards", { method: "POST", body: JSON.stringify({ name: "Highlighter" }) })).json();
    return b.id;
  });
  await page.evaluate((id) => openWhiteboardBoard(id), board2);
  await page.waitForTimeout(1200);
  // Through the real UI: `openWhiteboardBoard` from `evaluate` can leave the
  // landing showing, so this asserts the canvas is up before drawing on it.
  const onCanvas = await page.evaluate(() => !document.getElementById("wb-canvas-view")?.classList.contains("hidden"));
  if (!onCanvas) {
    ok("the highlighter stroke composites", false, "the board did not open");
  } else {
    // `selectWbTool` is closed over inside `initWhiteboard`, so a sweep reaches
    // the tool the way a person does: the rail's own button.
    await page.click('#wb-tool-group [data-tool="highlighter"]');
    await page.waitForTimeout(200);
    await page.evaluate(() => {
      const sw = document.getElementById("wb-rail-ink");
      sw.value = "#ffcc00";
      sw.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.waitForTimeout(300);
    const canvas = await page.evaluate(() => document.getElementById("whiteboard-container").getBoundingClientRect().toJSON());
    const cx = Math.round(canvas.x + canvas.width / 2);
    const cy = Math.round(canvas.y + canvas.height / 2);
    // A horizontal pass and a vertical one, crossing at the centre.
    await page.mouse.move(cx - 120, cy);
    await page.mouse.down();
    for (let i = -110; i <= 120; i += 10) { await page.mouse.move(cx + i, cy); }
    await page.mouse.up();
    await page.waitForTimeout(500);
    await page.mouse.move(cx, cy - 120);
    await page.mouse.down();
    for (let i = -110; i <= 120; i += 10) { await page.mouse.move(cx, cy + i); }
    await page.mouse.up();
    await page.waitForTimeout(900);

    const shot = `${OUT}/wb-highlighter.png`;
    await page.screenshot({ path: shot, clip: { x: cx - 100, y: cy - 100, width: 200, height: 200 } });
    // 100,100 is the crossing; 40,100 and 100,40 are one stroke each; 20,20 is
    // the bare board.
    const read = execSync(`python3 ${__dirname}/../pngpixel.py ${shot} 100 100 40 100 100 40 20 20`).toString().trim().split("\n").slice(1);
    const lum = (line) => {
      const m = line.match(/\((\d+), (\d+), (\d+)\)/);
      return m ? 0.299 * Number(m[1]) + 0.587 * Number(m[2]) + 0.114 * Number(m[3]) : null;
    };
    const [cross, hOnly, vOnly, bare] = read.map(lum);
    const strokes = await page.evaluate(() => ({
      count: wbState.sketches.length,
      blend: [...document.querySelectorAll(".sketch-path")].map((el) => el.style.mixBlendMode),
      width: (() => { try { return JSON.parse(wbState.sketches[0].data).width; } catch { return null; } })(),
      opacity: (() => { try { return JSON.parse(wbState.sketches[0].data).opacity; } catch { return null; } })(),
    }));
    ok(
      "two highlighter strokes were drawn and both multiply",
      strokes.count === 2 && strokes.blend.length === 2 && strokes.blend.every((b) => b === "multiply"),
      `${strokes.count} strokes, blend ${JSON.stringify(strokes.blend)}, width ${strokes.width}, opacity ${strokes.opacity}`,
    );
    ok(
      "the highlighter width is the plan's 12 to 24",
      strokes.width >= 12 && strokes.width <= 24,
      `width ${strokes.width}`,
    );
    ok(
      "the crossing is darker than either stroke alone",
      cross !== null && hOnly !== null && vOnly !== null && bare !== null
        && cross < hOnly - 1 && cross < vOnly - 1 && hOnly < bare - 1,
      `luminance: crossing ${cross === null ? "?" : cross.toFixed(1)}, across ${hOnly === null ? "?" : hOnly.toFixed(1)}, down ${vOnly === null ? "?" : vOnly.toFixed(1)}, bare board ${bare === null ? "?" : bare.toFixed(1)}`,
    );
  }


  console.log(`\n${pass}/${pass + fail} checks pass at ${VW}x${VH} (${process.env.THEME || "light"})`);
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
