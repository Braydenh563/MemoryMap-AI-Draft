// Phase 2's map nodes in the theme and at the width §10.4 never looked at.
//
// MINDMAP_PLAN.md §10.4, verbatim: *"One theme, one viewport, one scale.
// Everything was measured in light theme at 1440x900, DPR 1. Dark mode and a
// narrow viewport are reasoned, not observed — the node uses `--card`/
// `--border`/`--text`, which are theme-aware, but nothing has looked at it."*
//
// This looks at it, and it measures rather than looking: `getComputedStyle`
// for the declared colours, a real WCAG contrast ratio computed from them,
// and `scrollHeight` vs `clientHeight` for anything clipped. CLAUDE.md's rule
// — a screenshot you look at is not a measurement — is the reason every number
// below is a number.
//
//   THEME=dark BASE=http://127.0.0.1:8797 SCRATCH=/tmp/mm-map3 \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/mindmap-theme.js
//   VIEWPORT=390x844 … for the narrow one.
const { boot } = require("./lib.js");

const results = [];
function check(label, ok, detail) {
  results.push({ label, ok: Boolean(ok), detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? "  — " + detail : ""}`);
}

const THEME = process.env.THEME || "light";
const VIEWPORT = (() => {
  const raw = process.env.VIEWPORT;
  if (!raw) return { width: 1440, height: 900 };
  const [w, h] = raw.split("x").map(Number);
  return { width: w || 1440, height: h || 900 };
})();

(async () => {
  const { browser, page, OUT } = await boot({ viewport: VIEWPORT });
  const tag = `${THEME}-${VIEWPORT.width}${process.env.GLASS !== undefined ? "-glass" + process.env.GLASS : ""}`;

  //: GLASS=0 turns the appearance slider all the way down, which is the case
  //: `--card` collapses to nothing in. Set through the same preference key
  //: Settings writes (`applyAppearance` reads it on load), not by poking the
  //: custom property, so this measures what a user who moved that slider
  //: actually gets rather than a value invented by the test.
  if (process.env.GLASS !== undefined) {
    await page.evaluate((value) => {
      localStorage.setItem("glass-opacity", value);
      document.documentElement.style.setProperty("--glass-opacity", Number(value) / 100);
    }, process.env.GLASS);
    await page.waitForTimeout(400);
  }

  await page.click('[data-tab="library"]');
  await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]');
  await page.waitForTimeout(900);
  await page.click("#wb-boards-new");
  await page.waitForTimeout(700);
  await page.fill(".confirm-overlay input[type=text]", `Theme map ${tag}`);
  await page.click('.confirm-overlay .seg button[data-value="map"]');
  await page.waitForTimeout(150);
  await page.click(".confirm-overlay .confirm-actions button:last-child");
  await page.waitForTimeout(2600);

  // Three branches, so the branch palette is actually exercised — the root
  // takes `--accent` and only a first-level topic gets a palette entry, so a
  // one-node map would measure the default and call it the palette.
  const boardId = await page.evaluate(() => window.currentBoardId);
  // Through the API, and the root comes from `/tree` — `wbState` is a
  // module-level binding in whiteboard.js and is not on `window` (a top-level
  // `let` never is; only `var` is), which a first run of this script found the
  // hard way.
  await page.evaluate(async (id) => {
    const tree = await window.apiJson(`/whiteboard/boards/${id}/tree`);
    const root = (tree.roots || [])[0];
    for (const text of [
      "First branch",
      "Second branch",
      "A third branch with a much longer label than the others",
    ]) {
      await window.apiJson(`/whiteboard/boards/${id}/nodes`, {
        method: "POST",
        body: JSON.stringify({ kind: "topic", parent_id: root.id, text }),
      });
    }
  }, boardId);
  await page.evaluate(() => window.openWhiteboardBoard(window.currentBoardId));
  await page.waitForTimeout(2600);
  await page.evaluate(() => window.wbZoomToFit && window.wbZoomToFit({ animate: false }));
  await page.waitForTimeout(900);

  //: The measurement itself. `getComputedStyle` gives the *resolved* colour of
  //: every token involved, which is the thing that can be wrong in a theme
  //: without anything logging — CLAUDE.md's worst-bug shape is a value that is
  //: invalid where it is used rather than where it is set.
  const readings = await page.evaluate(() => {
    // Flatten a possibly-translucent colour over what is behind it, then
    // WCAG-contrast the two. A node's own background is the thing its text
    // has to be legible against, and this app's `--card` is deliberately
    // semi-transparent, so comparing the declared colours alone would be
    // comparing something no eye ever sees.
    //: **`color(srgb …)` is a colour too**, and missing it is how a real
    //: reading turns into a fake one. This app's `--card` is a `color-mix()`,
    //: and Chromium serialises a mixed colour as `color(srgb 1 1 1 / 0.549)`
    //: rather than as `rgba(…)` — so an rgb-only parser returns null for the
    //: one value this script exists to measure, and a `{0,0,0,0}` fallback
    //: then reports "transparent" for a node that is painted.
    const parse = (css) => {
      const modern = css.match(/color\(srgb\s+([^)]+)\)/);
      if (modern) {
        const parts = modern[1].split("/");
        const rgb = parts[0].trim().split(/\s+/).map(Number);
        return {
          r: rgb[0] * 255,
          g: rgb[1] * 255,
          b: rgb[2] * 255,
          a: parts.length > 1 ? parseFloat(parts[1]) : 1,
        };
      }
      const m = css.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const parts = m[1].split(/[,/]/).map((s) => parseFloat(s.trim()));
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
    };
    const over = (top, bottom) => ({
      r: top.r * top.a + bottom.r * (1 - top.a),
      g: top.g * top.a + bottom.g * (1 - top.a),
      b: top.b * top.a + bottom.b * (1 - top.a),
      a: 1,
    });
    const lum = (c) => {
      const f = (v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
    };
    const ratio = (a, b) => {
      const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
      return (x + 0.05) / (y + 0.05);
    };

    // What is behind a node: the board's own canvas.
    const canvas = document.getElementById("whiteboard-container");
    let behind = parse(getComputedStyle(canvas).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
    if (behind.a < 1) {
      const page_ = parse(getComputedStyle(document.body).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
      behind = over(behind, { ...page_, a: 1 });
    }

    const out = [];
    for (const el of document.querySelectorAll(".wb-object.wb-map-node")) {
      const cs = getComputedStyle(el);
      const textEl = el.querySelector(".wb-map-text");
      const ts = getComputedStyle(textEl);
      const fillRaw = parse(cs.backgroundColor) || { r: 0, g: 0, b: 0, a: 0 };
      const fill = over(fillRaw, behind);
      const ink = parse(ts.color) || { r: 0, g: 0, b: 0, a: 1 };
      // What actually draws the node's edge: the 1.5px branch-tinted border
      // and the 4px spine down the leading edge. A map node's *fill* is
      // near-identical to the board by design (both derive from `--card`), so
      // the border is the thing that has to be legible against the canvas —
      // measuring the fill alone would be measuring the wrong boundary.
      const borderRaw = parse(cs.borderTopColor) || { r: 0, g: 0, b: 0, a: 0 };
      const spineRaw = parse(cs.borderLeftColor) || { r: 0, g: 0, b: 0, a: 0 };
      const rect = el.getBoundingClientRect();
      out.push({
        text: (textEl.textContent || "").slice(0, 28),
        fillDeclared: cs.backgroundColor,
        fillEffective: `rgb(${Math.round(fill.r)}, ${Math.round(fill.g)}, ${Math.round(fill.b)})`,
        ink: ts.color,
        branch: cs.getPropertyValue("--wb-branch").trim(),
        // The number this whole script exists for.
        contrast: Math.round(ratio(over(ink, fill), fill) * 100) / 100,
        // And the node against the board it sits on. A map node's fill is
        // near-identical to the canvas on purpose, so what has to carry the
        // edge is the border and the branch spine.
        fillVsBoard: Math.round(ratio(fill, behind) * 100) / 100,
        fillAlpha: Math.round(fillRaw.a * 1000) / 1000,
        borderVsBoard: Math.round(ratio(over(borderRaw, behind), behind) * 100) / 100,
        spineVsBoard: Math.round(ratio(over(spineRaw, behind), behind) * 100) / 100,
        w: Math.round(rect.width),
        h: Math.round(rect.height),
        clipped: textEl.scrollHeight - textEl.clientHeight,
        offRight: Math.round(rect.right - window.innerWidth),
        offLeft: Math.round(-rect.left),
      });
    }
    return {
      board: getComputedStyle(canvas).backgroundColor,
      behind: `rgb(${Math.round(behind.r)}, ${Math.round(behind.g)}, ${Math.round(behind.b)})`,
      glassOpacity: getComputedStyle(document.documentElement).getPropertyValue("--glass-opacity").trim(),
      card: getComputedStyle(document.documentElement).getPropertyValue("--card").trim(),
      theme: document.documentElement.dataset.theme || "(system)",
      nodes: out,
      // Does the board scroll sideways at this width? A canvas is allowed to;
      // the page around it is not.
      bodyOverflow: document.body.scrollWidth - document.body.clientWidth,
    };
  });

  console.log(JSON.stringify(readings, null, 2));

  const worst = readings.nodes.reduce((m, n) => Math.min(m, n.contrast), Infinity);
  check(
    `[${tag}] every map node's label is at least 4.5:1 on its own fill`,
    worst >= 4.5,
    `worst ${worst}:1 over ${readings.nodes.length} nodes`
  );
  //: **3:1 against the canvas, on the thing that actually draws the edge.**
  //: WCAG 1.4.11 asks 3:1 of a non-text UI boundary, and a map node's fill is
  //: deliberately within a hair of the board it floats on (both come from
  //: `--card`), so measuring the fill would be measuring the wrong boundary
  //: and passing or failing for the wrong reason.
  const worstEdge = readings.nodes.reduce(
    (m, n) => Math.min(m, Math.max(n.borderVsBoard, n.spineVsBoard)),
    Infinity
  );
  check(
    `[${tag}] a node's edge reads against the board behind it`,
    worstEdge >= 3,
    `worst ${worstEdge}:1 (board ${readings.behind})`
  );
  //: **The fill must never vanish.** `--card` is a `color-mix` scaled by the
  //: user's glass-opacity setting, so a plain `var(--card)` falls to fully
  //: transparent when that slider goes to zero — which is exactly the failure
  //: `.wb-object-text` has a `max(…, 0.55)` floor for, recorded in its own
  //: comment ("a text box was hard to tell apart from the board behind it").
  const worstAlpha = readings.nodes.reduce((m, n) => Math.min(m, n.fillAlpha), Infinity);
  check(
    `[${tag}] a node keeps a fill at glass opacity ${readings.glassOpacity}`,
    worstAlpha >= 0.3,
    `lowest alpha ${worstAlpha}`
  );
  const clipped = readings.nodes.filter((n) => n.clipped > 0);
  check(
    `[${tag}] no map node clips its own label`,
    clipped.length === 0,
    clipped.length ? JSON.stringify(clipped) : `${readings.nodes.length} nodes, 0 clipped`
  );
  check(
    `[${tag}] the page itself does not scroll sideways`,
    readings.bodyOverflow <= 0,
    `${readings.bodyOverflow}px`
  );
  const widest = Math.max(...readings.nodes.map((n) => n.w));
  check(
    `[${tag}] a map node fits the viewport`,
    widest <= VIEWPORT.width,
    `widest node ${widest}px in a ${VIEWPORT.width}px viewport`
  );

  // The hover controls, at this width: two 28px buttons hanging off the node's
  // corner is the thing most likely to fall off a 390px screen.
  await page.hover(".wb-map-node");
  await page.waitForTimeout(400);
  const controls = await page.evaluate(() => {
    const row = document.querySelector(".wb-map-node .wb-map-actions");
    if (!row) return null;
    const r = row.getBoundingClientRect();
    const cs = getComputedStyle(row);
    return {
      opacity: cs.opacity,
      w: Math.round(r.width),
      h: Math.round(r.height),
      offRight: Math.round(r.right - window.innerWidth),
      buttons: row.querySelectorAll("button").length,
    };
  });
  check(
    `[${tag}] the node's add controls are visible on hover and on screen`,
    controls && controls.opacity === "1" && controls.buttons === 2 && controls.offRight <= 0,
    JSON.stringify(controls)
  );

  // --- the node edit strip and the node radial (§12.1 items 2 and 3) -------
  // Both landed in one run, measured at one width in one theme. These two
  // checks are the other theme and the other width: the strip's glyphs
  // against the tray they sit in, and a ring slot's own edge against the
  // canvas behind it, which is the 3:1 WCAG 1.4.11 asks of a control's
  // boundary. The colour maths is the same as the block above (a `color(srgb
  // …)`-aware parse, flatten, WCAG ratio), written again rather than shared
  // because a `page.evaluate` body cannot see the other one's locals.
  const firstNode = await page.evaluate(() => {
    const el = document.querySelector(".wb-object.wb-map-node");
    selectWbItem("object", Number(el.dataset.id));
    return Number(el.dataset.id);
  });
  await page.waitForTimeout(500);
  await page.evaluate((id) => {
    const el = document.querySelector(`.wb-object[data-id="${id}"]`);
    const r = el.getBoundingClientRect();
    el.dispatchEvent(new MouseEvent("contextmenu", {
      bubbles: true, cancelable: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
    }));
  }, firstNode);
  await page.waitForTimeout(500);
  const chrome = await page.evaluate(() => {
    const parse = (css) => {
      const modern = css.match(/color\(srgb\s+([^)]+)\)/);
      if (modern) {
        const parts = modern[1].split("/");
        const rgb = parts[0].trim().split(/\s+/).map(Number);
        return { r: rgb[0] * 255, g: rgb[1] * 255, b: rgb[2] * 255, a: parts.length > 1 ? parseFloat(parts[1]) : 1 };
      }
      const m = css.match(/rgba?\(([^)]+)\)/);
      if (!m) return { r: 0, g: 0, b: 0, a: 0 };
      const parts = m[1].split(/[,/]/).map((x) => parseFloat(x.trim()));
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
    };
    const over = (t, b) => ({ r: t.r * t.a + b.r * (1 - t.a), g: t.g * t.a + b.g * (1 - t.a), b: t.b * t.a + b.b * (1 - t.a), a: 1 });
    const lum = (c) => {
      const f = (v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
    };
    const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
    const page_ = parse(getComputedStyle(document.body).backgroundColor);
    const canvas = over(parse(getComputedStyle(document.getElementById("whiteboard-container")).backgroundColor), { ...page_, a: 1 });

    const strip = document.getElementById("wb-map-strip");
    const tray = over(parse(getComputedStyle(strip).backgroundColor), canvas);
    const glyph = strip.querySelector("button i");
    const stripInk = Math.round(ratio(over(parse(getComputedStyle(glyph).color), tray), tray) * 100) / 100;
    const sr = strip.getBoundingClientRect();

    const ring = document.getElementById("wb-map-radial");
    const slot = ring.querySelector(".wb-map-radial-slot");
    const cs = getComputedStyle(slot);
    const slotFill = over(parse(cs.backgroundColor), canvas);
    return {
      theme: document.documentElement.dataset.theme || "(system)",
      stripShown: !strip.classList.contains("hidden"),
      stripRows: Math.round(sr.height) > 60 ? 2 : 1,
      stripInk,
      stripInsideCanvas: Math.round(sr.right) <= window.innerWidth,
      ringOpen: !ring.classList.contains("hidden"),
      slotEdge: Math.round(ratio(over(parse(cs.borderTopColor), slotFill), canvas) * 100) / 100,
      slotInk: Math.round(ratio(over(parse(getComputedStyle(slot.querySelector("i")).color), slotFill), slotFill) * 100) / 100,
    };
  });
  check(
    `[${tag}] the edit strip's controls read against the tray they sit in`,
    chrome.stripShown && chrome.stripInk >= 4.5 && chrome.stripInsideCanvas,
    JSON.stringify(chrome)
  );
  check(
    `[${tag}] a ring slot's edge and glyph read against the canvas`,
    chrome.ringOpen && chrome.slotEdge >= 3 && chrome.slotInk >= 4.5,
    JSON.stringify({ slotEdge: chrome.slotEdge, slotInk: chrome.slotInk })
  );

  await page.screenshot({ path: `${OUT}/mindmap-theme-${tag}.png` });

  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${passed}/${results.length} checks passed. (${tag})`);
  console.log("shots in " + OUT);
  await browser.close();
  process.exit(passed === results.length ? 0 : 1);
})().catch((error) => {
  console.error("SWEEP CRASHED", error);
  process.exit(2);
});
