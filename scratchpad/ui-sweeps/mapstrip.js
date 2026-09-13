// The map's own node controls: the edit strip, the node radial, the link
// radial, the edge handles, the text-size grip, transplant and sever
// (MINDMAP_PLAN.md §12.1 items 2 to 9).
//
// Drives a real Chromium against a running app and asserts numbers, not
// screenshots: what the strip writes on the node, where it sits, that the
// board's own selection bar stands down on a map node, and that every action
// the radial offers is reachable.
//
//   BASE=http://127.0.0.1:8803 SCRATCH=/tmp/mm-map9 \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/mapstrip.js
const { boot } = require("./lib.js");

// SHOW_ERRORS=1 prints the body of any 4xx the page receives. Off by default
// because a sweep that passes should say nothing, and on demand because the
// alternative is guessing: a failing check here reports what it measured, not
// which field the server refused, and that difference cost a debugging round.
const SHOW_ERRORS = process.env.SHOW_ERRORS === "1";

// VIEWPORT=390x844 drives the same checks at phone width: everything in this
// file was written at 1440x900 and nothing here had been seen narrow.
const VIEWPORT = (() => {
  const raw = process.env.VIEWPORT;
  if (!raw) return { width: 1440, height: 900 };
  const [w, h] = raw.split("x").map(Number);
  return { width: w || 1440, height: h || 900 };
})();

const results = [];
function check(label, ok, detail) {
  results.push({ label, ok: Boolean(ok) });
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? "  " + detail : ""}`);
}

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
  if (SHOW_ERRORS) {
    page.on("response", async (r) => {
      if (r.status() >= 400) {
        let body = "";
        try { body = (await r.text()).slice(0, 400); } catch (e) { body = "(unreadable)"; }
        console.log(`HTTP ${r.status()} ${r.request().method()} ${r.url()}\n   ${body}`);
      }
    });
  }

  // At phone width the canvas is 364px and a trunk with one child is 440px of
  // tree, so a tidy leaves the trunk's own centre off the left edge and a
  // click on it lands on the shell behind the canvas (measured at 390x844:
  // the root's box at x=-95, `elementFromPoint` at its centre returning
  // `#tab-library`). A person would reach for Fit; this does the same, with
  // the app's own function, before each gesture that has to land on a node.
  // A no-op at 1440, where nothing is ever off the canvas.
  const frame = async () => {
    if (VIEWPORT.width >= 900) return;
    await page.evaluate(() => wbZoomToFit({ animate: false }));
    await page.waitForTimeout(400);
  };

  await newBoard(page, "Strip map", "map");
  // A root plus one child, so there is a branch as well as a trunk.
  await page.evaluate(async () => {
    const root = wbMapIndex().roots[0];
    await wbMapAddChild(root.id);
  });
  await page.waitForTimeout(1700);
  await page.keyboard.press("Escape");

  const kidId = await page.evaluate(() => {
    const i = wbMapIndex();
    return i.childrenOf.get(i.roots[0].id)[0].id;
  });

  // --- the strip stands in the board bar's place ----------------------------
  await page.evaluate((id) => selectWbItem("object", id), kidId);
  await page.waitForTimeout(400);
  const placed = await page.evaluate((id) => {
    const strip = document.getElementById("wb-map-strip");
    const bar = document.getElementById("wb-selection-bar");
    const node = document.querySelector(`.wb-object[data-id="${id}"]`);
    const s = strip.getBoundingClientRect();
    const n = node.getBoundingClientRect();
    return {
      stripShown: !strip.classList.contains("hidden") && s.width > 0,
      barHidden: bar.classList.contains("hidden"),
      above: Math.round(n.top - s.bottom),
      below: Math.round(s.top - n.bottom),
      dx: Math.round((s.left + s.width / 2) - (n.left + n.width / 2)),
      w: Math.round(s.width),
      h: Math.round(s.height),
      hostW: Math.round(document.getElementById("library-view-whiteboard").getBoundingClientRect().width),
      right: Math.round(s.right),
      view: window.innerWidth,
      pageScroll: document.documentElement.scrollWidth,
    };
  }, kidId);
  check("a map node gets the strip and the board's bar stands down",
    placed.stripShown && placed.barHidden, JSON.stringify(placed));
  check("the strip sits clear of the node and centred on it",
    // Above the node, or below it when it no longer fits above: that is
    // `wbUpdateSelectionBar`'s own documented fallback, and at 390 the strip
    // is two rows tall and takes it. Centred on the node unless the canvas is
    // too narrow to centre it there, where the 8px clamp pins it inside.
    ((placed.above > 20 && placed.above < 90) || (placed.below >= 10 && placed.below < 40))
      && (Math.abs(placed.dx) <= 2 || placed.w >= placed.hostW - 16),
    JSON.stringify(placed));
  // At 1440 this is the same single row it always was; at 390 it wraps to two
  // instead of standing 392px wide in a 364px canvas and out of the window.
  // `pageScroll` is reported, not asserted: at 390 the whole shell overflows
  // by 7px (43 elements, `.header-controls` among them), which is nothing to
  // do with the map and is written down in agent-remaining/mindmap.md.
  check("the strip stays inside the canvas",
    placed.w <= placed.hostW && placed.right <= placed.view,
    JSON.stringify({ w: placed.w, hostW: placed.hostW, right: placed.right,
      view: placed.view, pageScroll: placed.pageScroll, h: placed.h }));

  const boardBar = await page.evaluate(() => {
    // A board's own object still gets the board's bar: the split is the map's,
    // not a replacement of the bar everywhere.
    const strip = document.getElementById("wb-map-strip");
    clearWbSelection();
    return strip.classList.contains("hidden");
  });
  check("clearing the selection puts the strip away", boardBar === true);

  // --- what the strip writes -----------------------------------------------
  await page.evaluate((id) => selectWbItem("object", id), kidId);
  await page.waitForTimeout(300);
  await page.click("#wb-map-bold");
  await page.waitForTimeout(700);
  await page.click("#wb-map-italic");
  await page.waitForTimeout(700);
  const marks = await page.evaluate((id) => {
    const node = document.querySelector(`.wb-object[data-id="${id}"]`);
    const text = node.querySelector(".wb-map-text");
    const obj = wbMapIndex().byId.get(id);
    return {
      bold: obj.data?.bold, italic: obj.data?.italic,
      weight: getComputedStyle(text).fontWeight,
      style: getComputedStyle(text).fontStyle,
      pressed: document.getElementById("wb-map-bold").getAttribute("aria-pressed"),
    };
  }, kidId);
  check("bold and italic are stored and drawn",
    marks.bold === true && marks.italic === true
      && Number(marks.weight) >= 600 && marks.style === "italic"
      && marks.pressed === "true",
    JSON.stringify(marks));

  const sized = await page.evaluate(async (id) => {
    const before = getComputedStyle(
      document.querySelector(`.wb-object[data-id="${id}"] .wb-map-text`)).fontSize;
    const select = document.getElementById("wb-map-text-size");
    select.value = "25";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 900));
    const after = getComputedStyle(
      document.querySelector(`.wb-object[data-id="${id}"] .wb-map-text`)).fontSize;
    return { before, after, stored: wbMapIndex().byId.get(id).data?.font_size };
  }, kidId);
  check("the size select changes the node's own text size",
    sized.stored === 25 && parseFloat(sized.after) > parseFloat(sized.before),
    JSON.stringify(sized));

  const aligned = await page.evaluate(async (id) => {
    const select = document.getElementById("wb-map-align");
    select.value = "center";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 900));
    const node = document.querySelector(`.wb-object[data-id="${id}"]`);
    return {
      stored: wbMapIndex().byId.get(id).data?.align,
      align: getComputedStyle(node.querySelector(".wb-map-text")).textAlign,
    };
  }, kidId);
  check("alignment is stored and drawn", aligned.stored === "center" && aligned.align === "center",
    JSON.stringify(aligned));

  const iconed = await page.evaluate(async (id) => {
    const select = document.getElementById("wb-map-strip-icon");
    select.value = "star";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 900));
    const icon = document.querySelector(`.wb-object[data-id="${id}"] .wb-map-node-icon`);
    return {
      stored: wbMapIndex().byId.get(id).data?.icon,
      cls: icon ? icon.className : "",
      shown: icon ? !icon.hidden : false,
      w: icon ? Math.round(icon.getBoundingClientRect().width) : 0,
    };
  }, kidId);
  check("an icon is stored, shown and drawn from Phosphor",
    iconed.stored === "star" && iconed.cls.includes("ph-star") && iconed.shown && iconed.w > 6,
    JSON.stringify(iconed));

  // The four shapes (§12.1 item 3). Measured on the node, not on the select:
  // the radius and the surface are what a shape *is*, and a select that
  // stores a value nothing draws is the failure worth catching.
  const shaped = await page.evaluate(async (id) => {
    const node = document.querySelector(`.wb-object[data-id="${id}"]`);
    const select = document.getElementById("wb-map-shape");
    const read = () => {
      const cs = getComputedStyle(node);
      return {
        radius: Math.round(parseFloat(cs.borderTopLeftRadius)),
        fill: cs.backgroundColor,
        spine: cs.borderLeftColor,
        w: Math.round(node.getBoundingClientRect().width),
        h: Math.round(node.getBoundingClientRect().height),
      };
    };
    const rounded = read();
    const out = { rounded };
    for (const value of ["pill", "rect", "none"]) {
      select.value = value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 900));
      out[value] = { ...read(), stored: wbMapIndex().byId.get(id).data?.shape,
        shown: node.dataset.shape };
    }
    select.value = "";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 900));
    out.back = { ...read(), stored: wbMapIndex().byId.get(id).data?.shape ?? null,
      shown: node.dataset.shape ?? null };
    return out;
  }, kidId);
  check("each of the four shapes is stored and drawn",
    shaped.pill.stored === "pill" && shaped.pill.radius > shaped.rounded.radius
      && shaped.rect.stored === "rect" && shaped.rect.radius === 0
      && shaped.none.stored === "none" && shaped.none.fill === "rgba(0, 0, 0, 0)"
      && shaped.none.spine === "rgba(0, 0, 0, 0)"
      && shaped.back.stored === null && shaped.back.shown === null
      && shaped.back.radius === shaped.rounded.radius,
    JSON.stringify(shaped));
  // A shape may not resize the node: the layout, the edge anchors and both
  // rings all measure this box, so a plain topic that lost its 5.5px of
  // border would move under everything already drawn against it.
  check("and no shape changes the size of the node",
    [shaped.pill, shaped.rect, shaped.none, shaped.back]
      .every((s) => s.w === shaped.rounded.w && s.h === shaped.rounded.h),
    JSON.stringify({ rounded: [shaped.rounded.w, shaped.rounded.h],
      none: [shaped.none.w, shaped.none.h] }));

  // Read back from the server, which is the only proof the schema kept them:
  // a field Pydantic does not name is dropped silently on the way in, and the
  // browser's own copy would still be showing the value it sent.
  const persisted = await page.evaluate(async (id) => {
    await fetchWhiteboardState();
    const obj = (wbState.objects || []).find((o) => o.id === id);
    return obj ? { bold: obj.data?.bold, italic: obj.data?.italic,
      size: obj.data?.font_size, align: obj.data?.align, icon: obj.data?.icon } : null;
  }, kidId);
  check("and every one of them comes back from the server",
    persisted && persisted.bold === true && persisted.italic === true
      && persisted.size === 25 && persisted.align === "center" && persisted.icon === "star",
    JSON.stringify(persisted));

  // --- the link ------------------------------------------------------------
  const linked = await page.evaluate(async (id) => {
    const obj = (wbState.objects || []).find((o) => o.id === id);
    await wbMapSetNodeStyle(obj, { link: "https://example.org/notes" });
    await new Promise((r) => setTimeout(r, 600));
    const marker = document.querySelector(`.wb-object[data-id="${id}"] .wb-map-link`);
    return { stored: obj.data?.link, shown: marker ? !marker.hidden : false };
  }, kidId);
  check("a topic's link is stored and marked on the node",
    linked.stored === "https://example.org/notes" && linked.shown, JSON.stringify(linked));

  const refused = await page.evaluate(async (id) => {
    const obj = (wbState.objects || []).find((o) => o.id === id);
    try {
      await window.apiJson(`/whiteboard/objects/${id}`, {
        method: "PUT",
        body: JSON.stringify({
          kind: obj.kind, x: obj.x, y: obj.y, width: obj.width, height: obj.height,
          data: { ...obj.data, link: "javascript:alert(1)" },
        }),
      });
      return "accepted";
    } catch (e) {
      return "refused";
    }
  }, kidId);
  check("and a javascript: link is refused by the schema", refused === "refused", refused);

  // --- the node radial (§12.1 item 3) ---------------------------------------
  // Opened by the gesture, not by calling the function: the point of the ring
  // is that right-click reaches it.
  await page.evaluate((id) => selectWbItem("object", id), kidId);
  await page.waitForTimeout(300);
  await frame();
  await page.click(`.wb-object[data-id="${kidId}"]`, { button: "right" });
  await page.waitForTimeout(500);
  const ring = await page.evaluate((id) => {
    const el = document.getElementById("wb-map-radial");
    const node = document.querySelector(`.wb-object[data-id="${id}"]`);
    const n = node.getBoundingClientRect();
    const slots = [...el.querySelectorAll(".wb-map-radial-slot")].map((b) => {
      const r = b.getBoundingClientRect();
      return { id: b.id, cx: r.left + r.width / 2, cy: r.top + r.height / 2 };
    });
    const cx = n.left + n.width / 2, cy = n.top + n.height / 2;
    // About the ring's own centre, not the node's: a node near an edge slides
    // its ring inside the window (`wbPlaceMapRadial`), and a radius measured
    // from the node would then read as a broken ring rather than a moved one.
    // How far it has moved is its own number below, bounded by the ring's
    // reach so that it still lands on the topic it belongs to.
    const rx = slots.reduce((a, sl) => a + sl.cx, 0) / slots.length;
    const ry = slots.reduce((a, sl) => a + sl.cy, 0) / slots.length;
    const radii = slots.map((sl) => Math.round(Math.hypot(sl.cx - rx, sl.cy - ry)));
    return {
      open: !el.classList.contains("hidden"),
      role: el.getAttribute("role"),
      flat: document.querySelector(".wb-ctx-menu:not(.hidden)") === null,
      n: slots.length,
      radii,
      spread: Math.max(...radii) - Math.min(...radii),
      offset: Math.round(Math.hypot(rx - cx, ry - cy)),
    };
  }, kidId);
  check("right-click on a topic opens the ring, not the board's flat menu",
    ring.open && ring.flat && ring.n === 8 && ring.role === "toolbar",
    JSON.stringify({ open: ring.open, flat: ring.flat, n: ring.n, role: ring.role }));
  check("its eight slots sit on one circle around the node",
    ring.spread <= 2 && Math.min(...ring.radii) > 40 && ring.offset <= 82,
    JSON.stringify({ radii: ring.radii, spread: ring.spread, offset: ring.offset }));

  // Alt re-labels the two add slots rather than keeping the swap a secret.
  await page.keyboard.down("Alt");
  await page.waitForTimeout(250);
  const alted = await page.evaluate(() => ({
    icon: document.querySelector("#wb-radial-child i").className,
    danger: document.getElementById("wb-radial-child").classList.contains("wb-map-radial-danger"),
    title: document.getElementById("wb-radial-sibling").title,
  }));
  await page.keyboard.up("Alt");
  await page.waitForTimeout(250);
  const unalted = await page.evaluate(() =>
    document.querySelector("#wb-radial-child i").className);
  check("Alt turns the add slots into the remove slots, and says so",
    alted.icon.includes("ph-trash") && alted.danger
      && /Remove this topic only/.test(alted.title)
      && unalted.includes("elbow"),
    JSON.stringify({ alted, unalted }));

  // A trunk cannot be severed, and the slot says so instead of doing nothing.
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  const rootId = await page.evaluate(() => wbMapIndex().roots[0].id);
  await page.evaluate((id) => selectWbItem("object", id), rootId);
  await frame();
  await page.click(`.wb-object[data-id="${rootId}"]`, { button: "right" });
  await page.waitForTimeout(400);
  const severState = await page.evaluate(() => {
    const b = document.getElementById("wb-radial-sever");
    return { disabled: b.disabled, title: b.title };
  });
  check("sever is refused on a trunk and says why",
    severState.disabled === true && /already a trunk/.test(severState.title),
    JSON.stringify(severState));
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);

  // Copy a branch: a grandchild first, so there is a shape to copy.
  await page.evaluate(async (id) => {
    await wbMapAddChild(id);
  }, kidId);
  await page.waitForTimeout(1700);
  await page.keyboard.press("Escape");
  const before = await page.evaluate(() => wbMapIndex().nodes.length);
  await page.evaluate((id) => selectWbItem("object", id), kidId);
  await frame();
  await page.click(`.wb-object[data-id="${kidId}"]`, { button: "right" });
  await page.waitForTimeout(400);
  await page.click("#wb-radial-copy");
  await page.waitForTimeout(3000);
  const copied = await page.evaluate((id) => {
    const i = wbMapIndex();
    const source = i.byId.get(id);
    const siblings = i.childrenOf.get(source.parent_id) || [];
    const twin = siblings.find((o) => o.id !== id && o.data?.icon === "star");
    return {
      n: i.nodes.length,
      twin: Boolean(twin),
      twinKids: twin ? (i.childrenOf.get(twin.id) || []).length : 0,
      style: twin ? { icon: twin.data?.icon, bold: twin.data?.bold, size: twin.data?.font_size } : null,
    };
  }, kidId);
  check("copy branch duplicates the whole branch beside it, styling and all",
    copied.n === before + 2 && copied.twin && copied.twinKids === 1
      && copied.style.bold === true && copied.style.size === 25,
    JSON.stringify(copied));

  // Label the line into a topic, and see it drawn.
  const labelled = await page.evaluate(async (id) => {
    const node = wbMapIndex().byId.get(id);
    await wbMapSetNodeStyle(node, { edge_label: "because" });
    renderWhiteboardNow();
    await new Promise((r) => setTimeout(r, 400));
    const text = document.querySelector(".wb-map-edges .wb-map-edge-label");
    const edge = document.querySelector(`.wb-map-edge[data-child="${id}"]`);
    if (!text || !edge) return { drawn: false };
    const t = text.getBoundingClientRect(), e = edge.getBoundingClientRect();
    return {
      drawn: true,
      words: text.textContent,
      onTheEdge: t.left > e.left - 40 && t.right < e.right + 40,
      size: getComputedStyle(text).fontSize,
    };
  }, kidId);
  check("a line's label is drawn on the line it belongs to",
    labelled.drawn && labelled.words === "because" && labelled.onTheEdge,
    JSON.stringify(labelled));

  // Sever, then put it back: the map keeps one more trunk and then loses it.
  const severed = await page.evaluate(async (id) => {
    const roots = wbMapIndex().roots.length;
    await wbMapSever(id);
    await new Promise((r) => setTimeout(r, 1200));
    const after = wbMapIndex();
    return {
      roots, now: after.roots.length,
      parent: after.byId.get(id).parent_id,
      colour: after.byId.get(id).data?.color,
    };
  }, kidId);
  check("sever makes a topic a trunk of its own, branch and all",
    severed.now === severed.roots + 1 && severed.parent === null, JSON.stringify(severed));

  // Back to the branch clears everything the strip and the ring can set.
  const reset = await page.evaluate(async (id) => {
    await wbMapResetToBranch(id);
    await new Promise((r) => setTimeout(r, 900));
    await fetchWhiteboardState();
    const obj = (wbState.objects || []).find((o) => o.id === id);
    return { bold: obj.data?.bold, icon: obj.data?.icon, size: obj.data?.font_size,
      align: obj.data?.align, link: obj.data?.link, label: obj.data?.edge_label };
  }, kidId);
  check("back to the branch drops every look the strip and the ring can set",
    reset && !reset.bold && !reset.icon && !reset.size && !reset.align
      && !reset.link && !reset.label,
    JSON.stringify(reset));

  // --- the link radial (§12.1 item 4) ---------------------------------------
  // Rebuild a parent/child pair: the sever above left `kidId` a trunk.
  await page.evaluate(async (id) => {
    const roots = wbMapIndex().roots;
    const other = roots.find((r) => r.id !== id);
    await window.apiJson(`/whiteboard/boards/${window.currentBoardId}/nodes/${id}/move`, {
      method: "PUT", body: JSON.stringify({ parent_id: other.id }),
    });
    await fetchWhiteboardState();
    renderWhiteboardNow();
  }, kidId);
  await page.waitForTimeout(900);

  const hit = await page.evaluate((id) => {
    const h = document.querySelector(`.wb-map-edge-hit[data-child="${id}"]`);
    const line = document.querySelector(`.wb-map-edge[data-child="${id}"]`);
    if (!h || !line) return null;
    return {
      width: getComputedStyle(h).strokeWidth,
      lineWidth: getComputedStyle(line).strokeWidth,
      events: getComputedStyle(h).pointerEvents,
      groupEvents: getComputedStyle(document.querySelector(".wb-map-edges")).pointerEvents,
      sameD: h.getAttribute("d") === line.getAttribute("d"),
    };
  }, kidId);
  check("a line has a target wide enough to hit, over an inert group",
    hit && hit.events === "stroke" && hit.groupEvents === "none"
      && parseFloat(hit.width) >= 12 && parseFloat(hit.lineWidth) <= 3 && hit.sameD,
    JSON.stringify(hit));

  const box = await page.evaluate((id) => {
    const h = document.querySelector(`.wb-map-edge-hit[data-child="${id}"]`);
    const r = h.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }, kidId);
  await page.mouse.click(box.x, box.y, { button: "right" });
  await page.waitForTimeout(500);
  const linkRing = await page.evaluate(() => {
    const el = document.getElementById("wb-map-link-radial");
    return {
      open: !el.classList.contains("hidden"),
      slots: el.querySelectorAll(".wb-map-radial-slot").length,
      curveActive: document.getElementById("wb-link-curve").classList.contains("active"),
      nodeRingClosed: document.getElementById("wb-map-radial").classList.contains("hidden"),
    };
  });
  check("right-click on a line opens the line's own ring",
    linkRing.open && linkRing.slots === 8 && linkRing.curveActive && linkRing.nodeRingClosed,
    JSON.stringify(linkRing));

  await page.click("#wb-link-elbow");
  await page.waitForTimeout(1100);
  const elbowed = await page.evaluate((id) => {
    const line = document.querySelector(`.wb-map-edge[data-child="${id}"]`);
    return { stored: wbMapIndex().byId.get(id).data?.edge_style, d: line.getAttribute("d") };
  }, kidId);
  check("the elbow is stored and the line is redrawn with corners",
    elbowed.stored === "elbow" && elbowed.d.includes("L") && !elbowed.d.includes("C"),
    JSON.stringify(elbowed));

  const dashed = await page.evaluate(async (id) => {
    const node = wbMapIndex().byId.get(id);
    await wbMapSetNodeStyle(node, { edge_dashed: true });
    renderWhiteboardNow();
    await new Promise((r) => setTimeout(r, 500));
    const line = document.querySelector(`.wb-map-edge[data-child="${id}"]`);
    return { dash: getComputedStyle(line).strokeDasharray, cls: line.getAttribute("class") };
  }, kidId);
  check("a dashed line is drawn dashed", /\d/.test(dashed.dash) && dashed.cls.includes("dashed"),
    JSON.stringify(dashed));

  const reversed = await page.evaluate(async (id) => {
    const i = wbMapIndex();
    const child = i.byId.get(id);
    const parentId = child.parent_id;
    await wbMapReverseEdge(id);
    await new Promise((r) => setTimeout(r, 2000));
    const after = wbMapIndex();
    return {
      parentId,
      childNowParentOf: (after.childrenOf.get(id) || []).map((o) => o.id).includes(parentId),
      childParent: after.byId.get(id).parent_id,
    };
  }, kidId);
  check("turning a line around swaps the two topics without a cycle",
    reversed.childNowParentOf && reversed.childParent !== reversed.parentId,
    JSON.stringify(reversed));

  // --- the mid-line plus (§12.1 item 5) -------------------------------------
  const plus = await page.evaluate(() => {
    const layer = document.querySelector(".wb-map-plus-layer");
    const buttons = [...document.querySelectorAll(".wb-map-edge-plus")];
    const edges = document.querySelectorAll(".wb-map-edges .wb-map-edge").length;
    if (!layer || !buttons.length) return null;
    const first = buttons[0];
    const child = first.nextElementSibling;
    return {
      n: buttons.length,
      edges,
      hiddenAtRest: getComputedStyle(first).opacity === "0",
      grabbable: getComputedStyle(first).pointerEvents === "auto",
      layerInert: getComputedStyle(layer).pointerEvents === "none",
      onALine: Boolean(child === null || true),
    };
  });
  check("every visible line carries a mid-point plus, invisible until pointed at",
    plus && plus.n === plus.edges && plus.hiddenAtRest && plus.grabbable && plus.layerInert,
    JSON.stringify(plus));

  // It lands on the line it belongs to: measured against the edge's own path.
  const onLine = await page.evaluate(() => {
    const button = document.querySelector(".wb-map-edge-plus");
    const b = button.getBoundingClientRect();
    const cx = b.left + b.width / 2, cy = b.top + b.height / 2;
    let best = Infinity;
    for (const edge of document.querySelectorAll(".wb-map-edges .wb-map-edge")) {
      const len = edge.getTotalLength();
      for (let i = 0; i <= 40; i += 1) {
        const p = edge.getPointAtLength((len * i) / 40);
        const svg = edge.ownerSVGElement;
        const pt = svg.createSVGPoint();
        pt.x = p.x; pt.y = p.y;
        const screen = pt.matrixTransform(edge.getScreenCTM());
        best = Math.min(best, Math.hypot(screen.x - cx, screen.y - cy));
      }
    }
    return Math.round(best);
  });
  check("and it sits on the line, not beside it", onLine <= 6, `${onLine}px from the nearest line`);

  const inserted = await page.evaluate(async () => {
    const before = wbMapIndex().nodes.length;
    const button = document.querySelector(".wb-map-edge-plus");
    const parentId = Number(document.querySelector(".wb-map-edges .wb-map-edge")
      .getAttribute("data-parent"));
    const childId = Number(document.querySelector(".wb-map-edges .wb-map-edge")
      .getAttribute("data-child"));
    button.click();
    await new Promise((r) => setTimeout(r, 2500));
    const i = wbMapIndex();
    const child = i.byId.get(childId);
    const middle = child ? i.byId.get(child.parent_id) : null;
    return {
      before, after: i.nodes.length,
      middleIsNew: Boolean(middle) && middle.id !== parentId,
      middleUnderParent: middle ? middle.parent_id === parentId : false,
    };
  });
  await page.keyboard.press("Escape");
  check("the plus puts a new topic between the two it was drawn on",
    inserted.after === inserted.before + 1 && inserted.middleIsNew
      && inserted.middleUnderParent,
    JSON.stringify(inserted));

  // --- the text-size grip (§12.1 item 6) ------------------------------------
  // The pointer goes somewhere else first: `:hover` is a real state, and the
  // last click in this sweep left the cursor on a node, so reading the grip's
  // resting opacity without this measured a hovered node twice.
  await page.mouse.move(4, 4);
  await page.waitForTimeout(250);
  const gripped = await page.evaluate(async (id) => {
    const node = document.querySelector(`.wb-object[data-id="${id}"]`);
    const grip = node.querySelector(".wb-map-size-grip");
    if (!grip) return null;
    // At rest means neither hovered nor selected: this node is still selected
    // from the checks above, so the class comes off to read the resting state
    // and goes straight back on. Reading it while selected is what the first
    // version of this check did, and it measured nothing.
    node.classList.remove("wb-selected");
    const atRest = getComputedStyle(grip).opacity;
    node.classList.add("wb-selected");
    const shown = getComputedStyle(grip).opacity;
    const r = grip.getBoundingClientRect();
    const before = getComputedStyle(node).fontSize;
    const send = (type, y, extra) => grip.dispatchEvent(new PointerEvent(type, {
      bubbles: true, cancelable: true, pointerId: 1, pointerType: "mouse",
      clientX: r.left + r.width / 2, clientY: y, ...extra,
    }));
    send("pointerdown", r.top + r.height / 2);
    send("pointermove", r.top + r.height / 2 + 80);
    const live = getComputedStyle(node).fontSize;
    send("pointerup", r.top + r.height / 2 + 80);
    await new Promise((res) => setTimeout(res, 1200));
    await fetchWhiteboardState();
    const obj = (wbState.objects || []).find((o) => o.id === id);
    return { atRest, shown, before, live, stored: obj?.data?.font_size,
      cursor: getComputedStyle(grip).cursor };
  }, kidId);
  check("the corner grip is quiet until the node is, and says it drags",
    gripped && gripped.atRest === "0" && gripped.shown === "1"
      && gripped.cursor === "ns-resize",
    JSON.stringify({ atRest: gripped?.atRest, shown: gripped?.shown, cursor: gripped?.cursor }));
  check("and dragging it down grows the text and stores the size",
    gripped && parseFloat(gripped.live) > parseFloat(gripped.before)
      && gripped.stored === Math.round(parseFloat(gripped.live)),
    JSON.stringify({ before: gripped?.before, live: gripped?.live, stored: gripped?.stored }));

  const clamped = await page.evaluate(async (id) => {
    const node = document.querySelector(`.wb-object[data-id="${id}"]`);
    const grip = node.querySelector(".wb-map-size-grip");
    const r = grip.getBoundingClientRect();
    const send = (type, y) => grip.dispatchEvent(new PointerEvent(type, {
      bubbles: true, cancelable: true, pointerId: 1, pointerType: "mouse",
      clientX: r.left + r.width / 2, clientY: y,
    }));
    send("pointerdown", r.top);
    send("pointermove", r.top + 4000);
    const high = getComputedStyle(node).fontSize;
    send("pointermove", r.top - 4000);
    const low = getComputedStyle(node).fontSize;
    send("pointerup", r.top - 4000);
    await new Promise((res) => setTimeout(res, 900));
    return { high, low };
  }, kidId);
  check("and it cannot be dragged past the sizes a node can read at",
    parseFloat(clamped.high) <= 44 && parseFloat(clamped.low) >= 10,
    JSON.stringify(clamped));

  // --- drag a branch onto a new parent (§12.1 item 8) -----------------------
  // A fresh map, so the shape under test is plain: root, two children, and a
  // grandchild under the first child.
  await newBoard(page, "Transplant map", "map");
  const ids = await page.evaluate(async () => {
    const root = wbMapIndex().roots[0];
    const a = await wbMapAddChild(root.id);
    const b = await wbMapAddChild(root.id);
    const kid = await wbMapAddChild(a.id);
    return { root: root.id, a: a.id, b: b.id, kid: kid.id };
  });
  await page.waitForTimeout(3600);
  await page.keyboard.press("Escape");

  // The branch follows the topic, and the topic under the pointer lights up.
  const dragging = await page.evaluate((ids) => {
    const container = document.getElementById("whiteboard-container");
    const rect = container.getBoundingClientRect();
    const t = d3.zoomTransform(container);
    const at = (node) => {
      const size = wbMapNodeSize(node);
      const [sx, sy] = t.apply([node.x + size.w / 2, node.y + size.h / 2]);
      return { x: rect.left + sx, y: rect.top + sy };
    };
    const i = wbMapIndex();
    const a = i.byId.get(ids.a), b = i.byId.get(ids.b);
    const kidBefore = { x: i.byId.get(ids.kid).x, y: i.byId.get(ids.kid).y };
    const from = at(a), to = at(b);
    const el = document.querySelector(`.wb-object[data-id="${ids.a}"]`);
    const mouse = (type, x, y, buttons) => new MouseEvent(type, {
      bubbles: true, cancelable: true, view: window, button: 0, buttons,
      clientX: x, clientY: y,
    });
    el.dispatchEvent(mouse("mousedown", from.x, from.y, 1));
    window.dispatchEvent(mouse("mousemove", from.x + 6, from.y + 4, 1));
    window.dispatchEvent(mouse("mousemove", to.x, to.y, 1));
    const lit = document.querySelectorAll(".wb-map-drop-target");
    const kidNow = wbMapIndex().byId.get(ids.kid);
    return {
      lit: lit.length,
      litId: lit.length ? Number(lit[0].getAttribute("data-id")) : null,
      kidMoved: Math.round(Math.hypot(kidNow.x - kidBefore.x, kidNow.y - kidBefore.y)),
      to,
    };
  }, ids);
  check("dragging a topic takes its branch and lights the topic under the pointer",
    dragging.lit === 1 && dragging.litId === ids.b && dragging.kidMoved > 10,
    JSON.stringify({ lit: dragging.lit, litId: dragging.litId, kidMoved: dragging.kidMoved }));

  const dropped = await page.evaluate(async (ids) => {
    const container = document.getElementById("whiteboard-container");
    const rect = container.getBoundingClientRect();
    const t = d3.zoomTransform(container);
    const i = wbMapIndex();
    const b = i.byId.get(ids.b);
    const size = wbMapNodeSize(b);
    const [sx, sy] = t.apply([b.x + size.w / 2, b.y + size.h / 2]);
    window.dispatchEvent(new MouseEvent("mouseup", {
      bubbles: true, cancelable: true, view: window, button: 0, buttons: 0,
      clientX: rect.left + sx, clientY: rect.top + sy,
    }));
    await new Promise((r) => setTimeout(r, 3000));
    await fetchWhiteboardState();
    const after = wbMapIndex();
    return {
      aParent: after.byId.get(ids.a).parent_id,
      kidParent: after.byId.get(ids.kid).parent_id,
      pinned: Boolean(after.byId.get(ids.a).data?.pinned),
      lit: document.querySelectorAll(".wb-map-drop-target").length,
    };
  }, ids);
  check("the drop re-parents the whole branch and clears the cue",
    dropped.aParent === ids.b && dropped.kidParent === ids.a
      && dropped.pinned === false && dropped.lit === 0,
    JSON.stringify(dropped));

  // Ctrl held: the topic goes alone and its children go up to its old parent.
  const alone = await page.evaluate(async (ids) => {
    const container = document.getElementById("whiteboard-container");
    const rect = container.getBoundingClientRect();
    const t = d3.zoomTransform(container);
    const at = (node) => {
      const size = wbMapNodeSize(node);
      const [sx, sy] = t.apply([node.x + size.w / 2, node.y + size.h / 2]);
      return { x: rect.left + sx, y: rect.top + sy };
    };
    const i = wbMapIndex();
    const from = at(i.byId.get(ids.a)), to = at(i.byId.get(ids.root));
    const el = document.querySelector(`.wb-object[data-id="${ids.a}"]`);
    const mouse = (type, x, y, buttons) => new MouseEvent(type, {
      bubbles: true, cancelable: true, view: window, button: 0, buttons,
      clientX: x, clientY: y, ctrlKey: true,
    });
    el.dispatchEvent(mouse("mousedown", from.x, from.y, 1));
    window.dispatchEvent(mouse("mousemove", from.x + 6, from.y + 4, 1));
    window.dispatchEvent(mouse("mousemove", to.x, to.y, 1));
    window.dispatchEvent(mouse("mouseup", to.x, to.y, 0));
    await new Promise((r) => setTimeout(r, 3000));
    await fetchWhiteboardState();
    const after = wbMapIndex();
    return {
      aParent: after.byId.get(ids.a).parent_id,
      kidParent: after.byId.get(ids.kid).parent_id,
      oldParent: ids.b,
    };
  }, ids);
  check("Ctrl held moves the topic alone and lets its branch up to its old parent",
    alone.aParent === ids.root && alone.kidParent === ids.b, JSON.stringify(alone));

  // A branch cannot be dropped inside itself: the offer is never made.
  const noCycle = await page.evaluate((ids) => {
    // A pair that really is ancestor and descendant *now*: the moves above
    // have rearranged the tree, and asking about a pair that used to be
    // related would have measured nothing (it did, once).
    const i = wbMapIndex();
    const a = i.byId.get(ids.root);
    const kid = wbMapSubtree(i, ids.root).find((o) => o.id !== ids.root);
    const container = document.getElementById("whiteboard-container");
    const rect = container.getBoundingClientRect();
    const t = d3.zoomTransform(container);
    const size = wbMapNodeSize(kid);
    const [sx, sy] = t.apply([kid.x + size.w / 2, kid.y + size.h / 2]);
    return wbMapDropTargetAt(a, rect.left + sx, rect.top + sy);
  }, ids);
  check("and a branch is never offered its own descendant as a parent",
    noCycle === null, JSON.stringify(noCycle && { id: noCycle.id, parent: noCycle.parent_id }));

  // --- both rings stay inside the window (§12.1 items 3 and 4) --------------
  // A map grows outward, so the topics nearest an edge are the newest ones,
  // and a ring that loses slots off-screen is least reachable exactly where
  // it is most wanted. Driven by panning the canvas until a real topic sits
  // in the corner, then opening the ring on it with the gesture.
  const cornered = await page.evaluate(() => {
    const container = document.getElementById("whiteboard-container");
    const host = document.getElementById("library-view-whiteboard");
    const hostRect = host.getBoundingClientRect();
    const rect = container.getBoundingClientRect();
    const index = wbMapIndex();
    const node = index.roots[0];
    const size = wbMapNodeSize(node);
    const t = d3.zoomTransform(container);
    // Just inside the left edge, and just under the top bar so the topic is
    // still clickable: the ring reaches 82px, so both edges are short of it
    // and both have to give. (The bar floats over the canvas, which is why
    // the ring's own bound is the canvas minus the bands across it.)
    const bar = document.getElementById("wb-topbar").getBoundingClientRect();
    const want = { x: hostRect.left + 40, y: bar.bottom + 20 };
    // Solve for the pan that puts this node's centre there:
    // screen = rect.left + k * world + tx.
    const tx = want.x - rect.left - t.k * (node.x + size.w / 2);
    const ty = want.y - rect.top - t.k * (node.y + size.h / 2);
    d3.select(container).call(wbZoom.transform, d3.zoomIdentity.translate(tx, ty).scale(t.k));
    return { id: node.id, want };
  });
  // The pan's own transforms are written in a `requestAnimationFrame`
  // (`handleWbZoom`, panlag.js), so the node's new rect is not there in the
  // same tick that asked for the pan: reading it there measured the position
  // it had *before* the pan, and the right-click then landed on bare canvas.
  await page.waitForTimeout(600);
  // Then correct the pan against where the node actually landed, and say by
  // how much: the arithmetic above goes through `wbMapNodeSize`, and a
  // node whose rendered box is not the size that function reports puts the
  // whole calculation out (measured 47px out at 390x844). One correction is
  // enough because the second pan is measured, not derived.
  const at = await page.evaluate(({ id, want }) => {
    const container = document.getElementById("whiteboard-container");
    const el = document.querySelector(`.wb-object[data-id="${id}"]`);
    const first = el.getBoundingClientRect();
    const t = d3.zoomTransform(container);
    const dx = want.x - (first.left + first.width / 2);
    const dy = want.y - (first.top + first.height / 2);
    if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
      d3.select(container).call(wbZoom.transform,
        d3.zoomIdentity.translate(t.x + dx, t.y + dy).scale(t.k));
    }
    return { drift: [Math.round(dx), Math.round(dy)] };
  }, cornered);
  await page.waitForTimeout(500);
  Object.assign(at, await page.evaluate((id) => {
    const box = document.querySelector(`.wb-object[data-id="${id}"]`).getBoundingClientRect();
    return { x: Math.round(box.left + box.width / 2), y: Math.round(box.top + box.height / 2) };
  }, cornered.id));
  await page.mouse.click(at.x, at.y, { button: "right" });
  await page.waitForTimeout(500);
  const ringed = await page.evaluate(() => {
    const el = document.getElementById("wb-map-radial");
    const host = document.getElementById("library-view-whiteboard");
    const hostRect = host.getBoundingClientRect();
    const slots = [...el.querySelectorAll(".wb-map-radial-slot")].map((b) => b.getBoundingClientRect());
    const centres = slots.map((r) => ({ x: r.left + r.width / 2, y: r.top + r.height / 2 }));
    const cx = centres.reduce((a, c) => a + c.x, 0) / centres.length;
    const cy = centres.reduce((a, c) => a + c.y, 0) / centres.length;
    const radii = centres.map((c) => Math.round(Math.hypot(c.x - cx, c.y - cy)));
    return {
      open: !el.classList.contains("hidden"),
      n: slots.length,
      minLeft: Math.round(Math.min(...slots.map((r) => r.left))),
      minTop: Math.round(Math.min(...slots.map((r) => r.top))),
      maxRight: Math.round(Math.max(...slots.map((r) => r.right))),
      maxBottom: Math.round(Math.max(...slots.map((r) => r.bottom))),
      hostLeft: Math.round(hostRect.left),
      barBottom: Math.round(document.getElementById("wb-topbar").getBoundingClientRect().bottom),
      w: window.innerWidth,
      h: window.innerHeight,
      spread: Math.max(...radii) - Math.min(...radii),
      radius: Math.min(...radii),
    };
  });
  check("a topic in the corner keeps all eight of its ring's slots reachable",
    ringed.open && ringed.n === 8
      && ringed.minLeft >= ringed.hostLeft && ringed.minTop >= ringed.barBottom
      && ringed.maxRight <= ringed.w && ringed.maxBottom <= ringed.h,
    JSON.stringify(ringed));
  check("and the slid ring is still a ring, not eight clamped buttons",
    ringed.spread <= 2 && ringed.radius > 60,
    JSON.stringify({ spread: ringed.spread, radius: ringed.radius }));

  // The line ring is placed from the pointer, so the pointer is what this
  // drives: `wbOpenMapLinkRadial`'s own two arguments, at the far corner of
  // the window. The hit target itself has its own check above.
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  const linkClamped = await page.evaluate(() => {
    const index = wbMapIndex();
    const child = [...index.byId.values()].find((o) => index.byId.has(o.parent_id));
    wbOpenMapLinkRadial(child.id, window.innerWidth - 6, window.innerHeight - 6);
    const el = document.getElementById("wb-map-link-radial");
    const slots = [...el.querySelectorAll(".wb-map-radial-slot")].map((b) => b.getBoundingClientRect());
    return {
      open: !el.classList.contains("hidden"),
      n: slots.length,
      maxRight: Math.round(Math.max(...slots.map((r) => r.right))),
      maxBottom: Math.round(Math.max(...slots.map((r) => r.bottom))),
      w: window.innerWidth,
      h: window.innerHeight,
    };
  });
  check("a line ring opened at the far corner stays inside the window too",
    linkClamped.open && linkClamped.n === 8
      && linkClamped.maxRight <= linkClamped.w && linkClamped.maxBottom <= linkClamped.h,
    JSON.stringify(linkClamped));

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
