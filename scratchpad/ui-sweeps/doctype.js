// PLAN P4: typing latency in the documents editor on a ~20k-word document.
//
// Loads the big document through the surface adapter (DOCUMENTS_PLAN Phase 2:
// with CodeMirror mounted, `#doc-content` is a hidden fallback holding stale
// text, so writing to it directly would measure nothing at all), then types
// forty characters in each of the two modes people write in and reports the
// keydown/input event durations PerformanceObserver saw, plus the number of
// markdown renders the preview did.
//
// The gate is DOCUMENTS_PLAN Phase 2's: keydown to paint under 30 ms in Live
// on this document.
//
//   BASE=http://127.0.0.1:8786 node scratchpad/ui-sweeps/doctype.js
const { boot } = require("./lib.js");

const PHRASE = " the quick brown fox jumps over the lazy dog";

(async () => {
  const { browser, page } = await boot();

  // Its own document, made through the API: the sweep must not depend on the
  // notebook it happens to run against having one.
  // NOCM=1 forces the fallback textarea, so the two engines can be compared
  // on the same document without a second checkout.
  if (process.env.NOCM) await page.evaluate(() => { docCmBroken = true; });
  await page.evaluate(async () => {
    const r = await api("/documents", {
      method: "POST",
      body: JSON.stringify({ title: "Typing latency", content: "" }),
    });
    const doc = await r.json();
    switchTab("documents");
    await openDocument(doc.id);
  });
  await page.waitForTimeout(2000);

  await page.evaluate(() => {
    const words = [];
    for (let i = 0; i < 20000; i += 1) words.push(i % 17 === 0 ? "\n\n## Section " + i : "word" + i);
    docSurface().text = "# Big document\n\n" + words.join(" ");
    docSurfaceInput();
  });
  await page.waitForTimeout(1200);

  const arm = () =>
    page.evaluate(() => {
      window.__evt = [];
      window.__renders = 0;
      if (!window.__wrapped) {
        const orig = window.renderMarkdown;
        window.renderMarkdown = function (...a) {
          window.__renders += 1;
          return orig.apply(this, a);
        };
        window.__wrapped = true;
      }
      if (window.__po) window.__po.disconnect();
      window.__po = new PerformanceObserver((l) => {
        for (const e of l.getEntries()) {
          if (e.name === "keydown" || e.name === "input") window.__evt.push(e.duration);
        }
      });
      window.__po.observe({ type: "event", durationThreshold: 16, buffered: false });
    });

  const read = () =>
    page.evaluate(() => {
      const ds = window.__evt.slice().sort((a, b) => a - b);
      const p = (q) => (ds.length ? ds[Math.min(ds.length - 1, Math.floor(q * ds.length))] : 0);
      return {
        slowEvents: ds.length,
        p50: Math.round(p(0.5)),
        p95: Math.round(p(0.95)),
        max: Math.round(ds[ds.length - 1] || 0),
        renders: window.__renders,
      };
    });

  // --- Live, the default view and the one the gate is about ----------------
  await page.evaluate(() => setDocView("live"));
  await page.waitForTimeout(1000);
  await page.click((await page.$("#doc-editor .cm-content")) ? "#doc-editor .cm-content" : "#doc-content");
  await page.keyboard.press("Control+End");
  await page.waitForTimeout(500);
  await arm();
  await page.keyboard.type(PHRASE, { delay: 40 });
  await page.waitForTimeout(1200);
  console.log("live", JSON.stringify(await read()));

  // --- Split, where the preview is repainted as well -----------------------
  await page.evaluate(() => setDocView("split"));
  await page.waitForTimeout(1000);
  await page.click((await page.$("#doc-editor .cm-content")) ? "#doc-editor .cm-content" : "#doc-content");
  await page.keyboard.press("Control+End");
  await arm();
  await page.keyboard.type(PHRASE, { delay: 40 });
  await page.waitForTimeout(1200);
  console.log(
    "split",
    JSON.stringify({
      ...(await read()),
      preview: await page.evaluate(() => Boolean(document.querySelector("#doc-preview:not(.hidden)"))),
    })
  );

  await browser.close();
})();
