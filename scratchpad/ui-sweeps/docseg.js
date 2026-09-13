// The Documents Edit / Read segment: do the pills fit inside their control?
//
// The owner, with a screenshot: "the documents edit and read toggle options
// dont fit in the toggle and go out of it at the bottom".
//
// This file used to be the probe that could not answer that. It clicked its
// way to the tab through `[data-tab="library"]` and a text-matched sub-tab,
// never reached `#tab-documents`, and the entry in DOCUMENTS_PLAN had to be
// written as a reading of the CSS rules rather than as a measurement. It now
// opens a document through `docopen.js`, which is the path the other seven
// cm-* sweeps already take, and asserts two independent numbers rather than
// looking at a screenshot:
//
//   - the segment's own `scrollHeight` equals its `clientHeight` (nothing
//     inside it is taller than it is), and
//   - every button's `getBoundingClientRect()` is inside the segment's, top
//     and bottom.
//
// Before the fix, at both 1440 and 1280: scrollHeight 40 / clientHeight 36,
// and each button's bottom 4px below the segment's. After: 36 / 36, and each
// button 4px inside at both ends.
//
//   BASE=http://127.0.0.1:8830 node scratchpad/ui-sweeps/docseg.js
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

(async () => {
  const { browser, page } = await boot();
  const say = (k, v) => console.log(`${k}: ${JSON.stringify(v)}`);
  let bad = 0;

  await openDoc(page, { title: 'Segment fit', content: '# Heading\n\nSome body text.' });
  const mounted = await page.evaluate(() => Boolean(document.querySelector('#doc-editor .cm-editor')));
  say('cm_mounted', mounted);
  if (!mounted) { console.log('FAIL: the editor never mounted, nothing below is measured'); bad++; }

  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(400);
    const seg = await page.evaluate(() => {
      const s = document.querySelector('.doc-dock .seg');
      if (!s) return null;
      const sr = s.getBoundingClientRect();
      return {
        scrollH: s.scrollHeight,
        clientH: s.clientHeight,
        h: +sr.height.toFixed(2),
        buttons: [...s.querySelectorAll('button')].map((b) => {
          const br = b.getBoundingClientRect();
          return {
            txt: b.textContent.trim().slice(0, 12),
            h: +br.height.toFixed(2),
            // Positive means the button is inside the segment on that edge.
            insetTop: +(br.top - sr.top).toFixed(2),
            insetBottom: +(sr.bottom - br.bottom).toFixed(2),
            // A label sliced by its own box shows up here and nowhere else.
            clipped: b.scrollHeight > b.clientHeight,
          };
        }),
      };
    });
    say(`seg_${width}`, seg);
    if (!seg) { console.log(`FAIL ${width}: no .doc-dock .seg in the page`); bad++; continue; }
    if (seg.scrollH > seg.clientH) {
      console.log(`FAIL ${width}: seg scrollHeight ${seg.scrollH} > clientHeight ${seg.clientH}`);
      bad++;
    }
    for (const b of seg.buttons) {
      if (b.insetTop < 0 || b.insetBottom < 0) {
        console.log(`FAIL ${width}: "${b.txt}" out of the segment (top ${b.insetTop}, bottom ${b.insetBottom})`);
        bad++;
      }
      if (b.clipped) { console.log(`FAIL ${width}: "${b.txt}" clips its own label`); bad++; }
    }
  }

  console.log(bad ? `docseg: ${bad} failures` : 'docseg: all checks pass');
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
