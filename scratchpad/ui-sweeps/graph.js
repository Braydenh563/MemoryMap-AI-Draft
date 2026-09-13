// The Graph tab's Phase 1 gate (GRAPH_PLAN.md §5), measured in a real
// Chromium against the 2,000-note fixture.
//
//   scratchpad/ui-sweeps/serve.sh 8812 /tmp/mm-graph-a97
//   BASE=http://127.0.0.1:8812 node scratchpad/graph-fixture.js 2000 4000
//   BASE=http://127.0.0.1:8812 node scratchpad/ui-sweeps/graph.js            # canvas
//   BASE=http://127.0.0.1:8812 RENDERER=svg node scratchpad/ui-sweeps/graph.js
//
// What it measures, and why each one is measured this way rather than looked
// at:
//
//  1. **First frame after data arrives.** `window.fetch` is wrapped so the
//     moment the `/graph` response resolves is recorded in the page, and the
//     clock stops at the first frame that actually has content in it — a
//     canvas draw, or the first `.graph-node` in the SVG. Measuring from the
//     click instead would be measuring SQLite, not the renderer.
//  2. **Frames per second during a two-second drag.** A `requestAnimationFrame`
//     counter, exactly as the plan asks, while a synthetic pointer drags a
//     node in a circle. Both renderers are driven through the same gesture.
//  3. **The longest frame on a 200-note board.** Nine of the ten fixture
//     categories are switched off in the legend, which leaves 200 notes. The
//     canvas renderer reports its own draw cost per frame
//     (`__graphDebug.lastFrameMs`); for both renderers the gap between
//     consecutive `requestAnimationFrame` callbacks is recorded too, and both
//     numbers are printed, because they answer different questions and only
//     one of them is available on the old renderer.
//  4. **Hover within one frame.** The pointer is moved onto a node and the
//     next single frame is asked whether the highlight is on.
//  5. **Every control still changes what is drawn.** Each control is driven
//     and the *drawing* is compared, not the control: a hash of the canvas
//     pixels plus the renderer's own read-only `window.__graphDebug` state.
//     "The checkbox ticked" is not evidence that anything was redrawn, which
//     is the whole reason the debug surface exists.
const { boot } = require("./lib.js");

const RENDERER = process.env.RENDERER === "svg" ? "svg" : "canvas";
const ok = (pass) => (pass ? "PASS" : "FAIL");

(async () => {
  const { browser, page } = await boot();
  const findings = [];

  // The renderer switch is read from localStorage by graph.js's
  // `graphRenderer()`; it needs to be set before the tab first renders.
  await page.evaluate((r) => {
    try {
      localStorage.setItem("graph-renderer", r);
      localStorage.setItem("graph-layout", "force");
      localStorage.setItem("graph-colour", "category");
      localStorage.removeItem("graph-minimap-hidden");
    } catch (e) {
      /* private mode; the default is canvas anyway */
    }
  }, RENDERER);

  // Instrument before the tab is opened: the clock has to be running before
  // the request that starts it.
  await page.evaluate(() => {
    window.__gate = { dataAt: 0, firstFrame: 0, frames: [], counting: false };
    const realFetch = window.fetch;
    window.fetch = function (...args) {
      const url = String(args[0] || "");
      const promise = realFetch.apply(this, args);
      if (/^\/graph(\?|$)/.test(url)) {
        promise.then(() => {
          window.__gate.dataAt = performance.now();
          window.__gate.firstFrame = 0;
        });
      }
      return promise;
    };
    const painted = () => {
      const debug = window.__graphDebug;
      if (debug && debug.renderer === "canvas") return debug.frames > 0;
      return document.querySelectorAll("#graph-svg .graph-node").length > 0;
    };
    const tick = (now) => {
      const gate = window.__gate;
      if (gate.counting) gate.frames.push(now);
      if (gate.dataAt && !gate.firstFrame && painted()) {
        gate.firstFrame = performance.now() - gate.dataAt;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });

  await page.click('[data-tab="graph"]');
  await page.waitForTimeout(6000);

  const shape = await page.evaluate(() => ({
    firstFrame: window.__gate.firstFrame,
    debug: window.__graphDebug || null,
    svgNodes: document.querySelectorAll("#graph-svg .graph-node").length,
    canvasHidden: (document.getElementById("graph-canvas") || {}).className || "",
  }));
  const nodeCount = shape.debug && shape.debug.nodes ? shape.debug.nodes : shape.svgNodes;
  console.log(`renderer=${RENDERER} nodes=${nodeCount} edges=${(shape.debug || {}).edges || "n/a"}`);
  console.log(
    `1. first frame after data: ${shape.firstFrame.toFixed(1)} ms  ${ok(
      shape.firstFrame > 0 && shape.firstFrame < 300
    )} (< 300 ms)`
  );

  // --- 2. fps during a two-second drag -----------------------------------
  //
  //: **A node that is actually on screen.** The first draft grabbed
  //: `positions[0]`, which on a fitted 2,000-note map is as likely to be
  //: outside the card as inside it — the drag then started on empty canvas and
  //: panned, and the hover test moved the pointer over nothing and reported a
  //: renderer bug that did not exist. The screen rectangle is the test.
  const onScreenNode = () =>
    page.evaluate(() => {
      const box = document.getElementById("graph-box").getBoundingClientRect();
      const debug = window.__graphDebug;
      if (debug && debug.renderer === "canvas" && debug.positions.length) {
        const t = debug.transform;
        for (let i = 0; i < debug.positions.length; i++) {
          const [x, y] = debug.positions[i];
          const sx = box.left + t.x + x * t.k;
          const sy = box.top + t.y + y * t.k;
          if (sx > box.left + 70 && sx < box.right - 70 && sy > box.top + 70 && sy < box.bottom - 70) {
            return { x: sx, y: sy };
          }
        }
        return null;
      }
      const node = document.querySelector("#graph-svg .graph-node .graph-core");
      if (!node) return null;
      const rect = node.getBoundingClientRect();
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    });

  const dragOnce = async (seconds) => {
    const point = await onScreenNode();
    if (!point) return null;
    await page.evaluate(() => {
      window.__gate.frames = [];
      window.__gate.counting = true;
      window.__gate.draw = [];
      window.__gate.sample = setInterval(() => {
        const d = window.__graphDebug;
        if (d && d.lastFrameMs) window.__gate.draw.push(d.lastFrameMs);
      }, 8);
    });
    await page.mouse.move(point.x, point.y);
    await page.mouse.down();
    const steps = Math.round(seconds * 60);
    for (let i = 0; i < steps; i++) {
      const angle = (i / steps) * Math.PI * 4;
      await page.mouse.move(point.x + Math.cos(angle) * 90, point.y + Math.sin(angle) * 70);
      await page.waitForTimeout(1000 / 60);
    }
    await page.mouse.up();
    return page.evaluate((secs) => {
      window.__gate.counting = false;
      clearInterval(window.__gate.sample);
      const frames = window.__gate.frames;
      const gaps = [];
      for (let i = 1; i < frames.length; i++) gaps.push(frames[i] - frames[i - 1]);
      gaps.sort((a, b) => a - b);
      const span = frames.length > 1 ? frames[frames.length - 1] - frames[0] : secs * 1000;
      return {
        fps: ((frames.length - 1) * 1000) / span,
        worstGap: gaps.length ? gaps[gaps.length - 1] : 0,
        p95Gap: gaps.length ? gaps[Math.floor(gaps.length * 0.95)] : 0,
        worstDraw: window.__gate.draw.length ? Math.max(...window.__gate.draw) : null,
      };
    }, seconds);
  };

  const drag = await dragOnce(2);
  if (!drag) {
    findings.push("could not find a node to drag");
  } else {
    console.log(
      `2. drag fps (2 s, ${nodeCount} notes): ${drag.fps.toFixed(1)} fps  ${ok(drag.fps >= 55)} (>= 55)` +
        `   worst frame gap ${drag.worstGap.toFixed(1)} ms, p95 ${drag.p95Gap.toFixed(1)} ms` +
        (drag.worstDraw != null ? `, worst draw ${drag.worstDraw.toFixed(2)} ms` : "")
    );
  }

  // --- 2b. what the frame rate is actually limited by -----------------------
  //
  //: The drag number on a 2,000-note map is dominated by one thing, and
  //: guessing which one wasted a round. This measures it instead: the page's
  //: own frame rate with the simulation running, then with the worker stopped
  //: and *nothing else changed*, then running again. A large gap says the
  //: limit is the simulation's share of the CPU; no gap says it is the paint.
  const rafFps = () =>
    page.evaluate(
      () =>
        new Promise((resolve) => {
          const f = [];
          const done = () => {
            const gaps = [];
            for (let i = 1; i < f.length; i++) gaps.push(f[i] - f[i - 1]);
            gaps.sort((a, b) => a - b);
            const d = window.__graphDebug || {};
            resolve({
              fps: ((f.length - 1) * 1000) / (f[f.length - 1] - f[0]),
              p50: gaps[Math.floor(gaps.length / 2)] || 0,
              draw: d.lastFrameMs || 0,
              tick: d.tickMs || 0,
              alpha: d.alpha || 0,
            });
          };
          const step = (now) => {
            f.push(now);
            if (f.length < 300 && now - f[0] < 2500) requestAnimationFrame(step);
            else done();
          };
          requestAnimationFrame(step);
        })
    );
  if (RENDERER === "canvas") {
    await page.evaluate(() => gcPost({ type: "reheat", alpha: 0.5 }));
    await page.waitForTimeout(700);
    const hot = await rafFps();
    await page.evaluate(() => gcPost({ type: "stop" }));
    await page.waitForTimeout(700);
    const cold = await rafFps();
    console.log(
      `2b. frame rate with the layout hot: ${hot.fps.toFixed(1)} fps ` +
        `(p50 gap ${hot.p50.toFixed(0)} ms, draw ${hot.draw.toFixed(1)} ms, tick ${hot.tick.toFixed(0)} ms); ` +
        `with the worker stopped and nothing else changed: ${cold.fps.toFixed(1)} fps ` +
        `(p50 gap ${cold.p50.toFixed(0)} ms, draw ${cold.draw.toFixed(1)} ms)`
    );
    await page.evaluate(() => gcPost({ type: "reheat", alpha: 0.05 }));
    await page.waitForTimeout(500);
  }

  // --- 4. hover within one frame ------------------------------------------
  const hover = await page.evaluate(async () => {
    const box = document.getElementById("graph-box").getBoundingClientRect();
    const debug = window.__graphDebug;
    let target = null;
    if (debug && debug.renderer === "canvas" && debug.positions.length) {
      const t = debug.transform;
      for (let i = 0; i < debug.positions.length && !target; i++) {
        const [x, y] = debug.positions[i];
        const sx = box.left + t.x + x * t.k;
        const sy = box.top + t.y + y * t.k;
        if (sx > box.left + 70 && sx < box.right - 70 && sy > box.top + 70 && sy < box.bottom - 70) {
          target = { x: sx, y: sy };
        }
      }
    }
    if (!target) return null;
    const surface = document.getElementById("graph-canvas");
    //: Start from "nothing hovered". The drag above leaves the pointer on a
    //: node, so without this the test moves onto a node that is already lit and
    //: reads an unchanged value as a failure — which it did, and the renderer
    //: was fine.
    surface.dispatchEvent(new PointerEvent("pointerleave", { bubbles: true, pointerId: 1 }));
    await new Promise((resolve) => requestAnimationFrame(() => resolve()));
    const before = window.__graphDebug.hovered;
    surface.dispatchEvent(
      new PointerEvent("pointermove", {
        clientX: target.x,
        clientY: target.y,
        bubbles: true,
        pointerId: 1,
      })
    );
    const at = performance.now();
    await new Promise((resolve) => requestAnimationFrame(() => resolve()));
    return {
      before,
      after: window.__graphDebug.hovered,
      ms: performance.now() - at,
      frames: window.__graphDebug.frames,
    };
  });
  if (hover) {
    console.log(
      `4. hover highlight: ${hover.before} -> ${hover.after} in one frame ` +
        `(${hover.ms.toFixed(1)} ms)  ${ok(hover.after !== null && hover.after !== hover.before)}`
    );
  } else {
    console.log("4. hover highlight: not measurable on this renderer (no debug surface)");
  }

  // --- 3. the longest frame on a 200-note board ----------------------------
  // The fixture files notes round-robin into ten categories, so switching nine
  // off in the legend leaves 200. Done through the legend buttons themselves,
  // not by poking state, so this also exercises the legend filter.
  //: **One click, then wait, then look again.** Every legend click calls
  //: `renderGraph()`, which rebuilds the legend — so a loop over a list of
  //: buttons captured once clicks nine detached elements and hides exactly one
  //: category. That is what "200 notes (from 10 legend entries)" meant on the
  //: first run: the board never got smaller and the frame budget was measured
  //: against the full map.
  const names = await page.evaluate(() =>
    [...document.querySelectorAll("#graph-legend .legend-toggle")].map((b) => b.textContent.trim())
  );
  const smaller = names.length;
  for (const name of names.slice(1)) {
    await page.evaluate((wanted) => {
      const item = [...document.querySelectorAll("#graph-legend .legend-toggle")].find(
        (b) => b.textContent.trim() === wanted
      );
      if (item) item.click();
    }, name);
    await page.waitForTimeout(1800);
  }
  await page.waitForTimeout(4000);
  const small = await page.evaluate(() => {
    const d = window.__graphDebug;
    return {
      nodes: d && d.renderer === "canvas" ? d.nodes : document.querySelectorAll("#graph-svg .graph-node").length,
    };
  });
  const smallDrag = await dragOnce(2);
  console.log(
    `3. ${small.nodes} notes (from ${smaller} legend entries): ` +
      (smallDrag
        ? `worst draw ${smallDrag.worstDraw != null ? smallDrag.worstDraw.toFixed(2) + " ms" : "n/a"} ` +
          `${smallDrag.worstDraw != null ? ok(smallDrag.worstDraw < 16) : ""} (< 16 ms), ` +
          `${smallDrag.fps.toFixed(1)} fps, worst gap ${smallDrag.worstGap.toFixed(1)} ms`
        : "no node to drag")
  );

  // Put the legend back before the control sweep.
  await page.evaluate(() => {
    for (const button of document.querySelectorAll("#graph-legend .legend-off")) button.click();
  });
  await page.waitForTimeout(3500);

  // --- 5. every control still changes what is drawn ------------------------
  const snapshot = () =>
    page.evaluate(() => {
      const canvas = document.getElementById("graph-canvas");
      let pixels = 0;
      if (canvas && !canvas.classList.contains("hidden")) {
        const ctx = canvas.getContext("2d");
        const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        // A cheap content hash: every 401st byte, so a redraw that moved
        // anything at all changes it, and reading it costs a few hundred
        // thousand array lookups rather than four million.
        for (let i = 0; i < data.length; i += 401) pixels = (pixels * 31 + data[i]) >>> 0;
      }
      const svg = document.getElementById("graph-svg");
      const debug = window.__graphDebug || {};
      return {
        pixels,
        svg: svg ? svg.innerHTML.length : 0,
        state: JSON.stringify({
          nodes: debug.nodes,
          edges: debug.edges,
          layout: debug.layout,
          colourMode: debug.colourMode,
          k: debug.transform && Math.round(debug.transform.k * 1000),
          time: debug.timeCutoff,
          hidden: debug.hiddenCategories,
          highlight: debug.highlight,
          trace: debug.trace,
          focus: debug.focusModeId,
          colours: debug.colours,
          radii: debug.radii,
        }),
      };
    });

  const control = async (label, action, settle = 2500) => {
    const before = await snapshot();
    await action();
    await page.waitForTimeout(settle);
    const after = await snapshot();
    const changed =
      before.pixels !== after.pixels || before.state !== after.state || before.svg !== after.svg;
    console.log(`5. ${label}: ${changed ? "redrew" : "NO CHANGE"}  ${ok(changed)}`);
    if (!changed) findings.push(`${label} did not change the drawing`);
  };

  //: 5 s, not the default 2.5. Laying out a 2,000-note hierarchy and painting
  //: it is real work, and the first run read a change that had not finished as
  //: "the control did nothing".
  await control(
    "layout tree",
    () =>
      page.evaluate(() => {
        localStorage.setItem("graph-layout", "tree");
        document.querySelector('input[name="graph-layout"][value="tree"]').click();
      }),
    5000
  );
  await control(
    "layout radial",
    () =>
      page.evaluate(() => {
        localStorage.setItem("graph-layout", "radial");
        document.querySelector('input[name="graph-layout"][value="radial"]').click();
      }),
    5000
  );
  await control(
    "layout arc",
    () =>
      page.evaluate(() => {
        localStorage.setItem("graph-layout", "arc");
        document.querySelector('input[name="graph-layout"][value="arc"]').click();
      }),
    5000
  );
  await control(
    "layout force",
    () =>
      page.evaluate(() => {
        localStorage.setItem("graph-layout", "force");
        document.querySelector('input[name="graph-layout"][value="force"]').click();
      }),
    4000
  );
  // "Colour by" became a `<select>` when Phase 3 turned it into a rule picker
  // (category, tag, space, age, cluster, has a file). This sweep still drove
  // the radio group it used to be and threw on a null, which stopped it three
  // checks in: everything below here had not run since.
  // The native <select> is hidden behind the app's enhanced select, so
  // `selectOption` never sees a visible element: set the value and fire the
  // change the app listens for, which is what the enhanced control does too.
  const colourBy = (value) =>
    page.evaluate((v) => {
      const box = document.getElementById("graph-colour");
      if (!box) throw new Error("#graph-colour is gone");
      box.value = v;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    }, value);
  await control("colour by cluster", () => colourBy("cluster"), 5000);
  await control("colour by category", () => colourBy("category"));
  await control("search highlight", async () => {
    await page.fill("#graph-search", "Reading");
  });
  await control("search cleared", async () => {
    await page.fill("#graph-search", "");
  });
  await control("hide unlinked", () =>
    page.evaluate(() => {
      const box = document.getElementById("graph-hide-orphans");
      box.checked = true;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    })
  );
  await control("show unlinked", () =>
    page.evaluate(() => {
      const box = document.getElementById("graph-hide-orphans");
      box.checked = false;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    })
  );
  await control(
    "labels off",
    () =>
      page.evaluate(() => {
        const box = document.getElementById("graph-labels");
        box.checked = false;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }),
    900
  );
  await control(
    "labels on",
    () =>
      page.evaluate(() => {
        const box = document.getElementById("graph-labels");
        box.checked = true;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }),
    900
  );
  await control(
    "time slider back",
    () =>
      page.evaluate(() => {
        const slider = document.getElementById("graph-time-slider");
        slider.value = String(Number(slider.min) + (Number(slider.max) - Number(slider.min)) * 0.3);
        slider.dispatchEvent(new Event("input", { bubbles: true }));
      }),
    900
  );
  await control(
    "time slider to now",
    () =>
      page.evaluate(() => {
        const slider = document.getElementById("graph-time-slider");
        slider.value = slider.max;
        slider.dispatchEvent(new Event("input", { bubbles: true }));
      }),
    900
  );
  await control("legend filter", () =>
    page.evaluate(() => document.querySelector("#graph-legend .legend-toggle").click())
  );
  await control("legend filter off", () =>
    page.evaluate(() => document.querySelector("#graph-legend .legend-off").click())
  );
  await control("zoom in", () => page.click("#graph-zoom-in"), 1200);
  await control("zoom out", () => page.click("#graph-zoom-out"), 1200);
  await control("fit to view", () => page.click("#graph-zoom-fit"), 1500);
  await control(
    "similarity edges",
    () =>
      page.evaluate(() => {
        const box = document.getElementById("graph-similarity");
        box.checked = true;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }),
    // Deriving similarity edges for 2,000 notes is a real traversal on the
    // server; 6 s was not always enough on a loaded box and the step reported
    // "the control did nothing" when the answer had simply not arrived.
    14000
  );
  await control(
    "similarity off",
    () =>
      page.evaluate(() => {
        const box = document.getElementById("graph-similarity");
        box.checked = false;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }),
    5000
  );
  await control(
    "focus mode",
    () =>
      page.evaluate(async () => {
        const first = (await api("/entries?limit=1").then((r) => r.json()))[0];
        graphFocusModeId = first.id;
        document.getElementById("graph-focus-clear").classList.remove("hidden");
        return renderGraph();
      }),
    4000
  );
  await control("exit focus", () => page.click("#graph-focus-clear"), 5000);
  await control(
    "trace between two notes",
    () =>
      page.evaluate(async () => {
        // The two ends of a real edge, not the first two nodes in the list:
        // those are very often unconnected, and "no route between these two"
        // then reads as "the trace did not draw" for the rest of the run.
        const edge = (gcEdges || []).find(
          (e) => e.source && e.target && !e.source.isGroup && !e.target.isGroup
        );
        if (!edge) return null;
        setTraceEnd("from", edge.source.id);
        setTraceEnd("to", edge.target.id);
        return runTrace();
      }),
    4000
  );
  //: Only meaningful if a route was actually found — two notes picked from the
  //: top of the list may not be connected at all, in which case there is no
  //: path on screen and clearing it correctly changes nothing. Reported either
  //: way rather than failed, because "no route between these two" is a fact
  //: about the fixture and not about the renderer.
  const hadTrace = await page.evaluate(() => Boolean(window.__graphDebug.trace));
  await control(`clear trace (a route was drawn: ${hadTrace})`, () =>
    page.evaluate(() => clearTrace()), 2500);

  // The minimap, saved views and the PNG export are not "did the drawing
  // change" questions, so they are checked for their own result instead.
  const minimap = await page.evaluate(() => {
    graphMinimapPaint();
    const dots = document.getElementById("graph-minimap-dots");
    const frame = document.getElementById("graph-minimap-frame");
    return {
      dots: dots ? dots.childElementCount : 0,
      frame: frame ? Number(frame.getAttribute("width")) : 0,
      coloured: dots && dots.firstChild ? dots.firstChild.getAttribute("fill") : "",
    };
  });
  console.log(
    `5. minimap: ${minimap.dots} dots, viewport frame ${minimap.frame}px wide, ` +
      `first dot ${minimap.coloured}  ${ok(minimap.dots > 0 && minimap.frame > 0)}`
  );
  if (!minimap.dots) findings.push("minimap drew no dots");

  const views = await page.evaluate(() => {
    const captured = graphCaptureView();
    localStorage.setItem("graph-saved-views", JSON.stringify([{ name: "gate", ...captured }]));
    renderGraphViews();
    const picker = document.getElementById("graph-view-picker");
    picker.value = "gate";
    picker.dispatchEvent(new Event("change", { bubbles: true }));
    return { options: picker.options.length, transform: Boolean(captured.transform) };
  });
  console.log(
    `5. saved views: ${views.options} options, captured a transform: ${views.transform}  ` +
      ok(views.options > 1 && views.transform)
  );

  const exported = await page.evaluate(async () => {
    const canvas = document.getElementById("graph-canvas");
    const surface = canvas && !canvas.classList.contains("hidden") ? canvas : null;
    if (!surface) return { bytes: 0, note: "svg renderer" };
    const blob = await new Promise((resolve) => surface.toBlob(resolve, "image/png"));
    return { bytes: blob ? blob.size : 0 };
  });
  console.log(`5. export PNG from the canvas: ${exported.bytes} bytes  ${ok(exported.bytes > 5000)}`);
  if (exported.bytes !== undefined && exported.bytes <= 5000 && !exported.note) {
    findings.push("canvas PNG export produced almost nothing");
  }

  const errors = await page.evaluate(() => (window.__gate.errors || []).length);
  console.log(`findings: ${findings.length}${findings.length ? "\n  " + findings.join("\n  ") : ""}`);
  await browser.close();
  process.exit(findings.length ? 1 : 0);
})();
