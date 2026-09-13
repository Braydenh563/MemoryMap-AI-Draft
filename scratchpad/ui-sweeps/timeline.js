// TIMELINE_PLAN.md Phase 1's gate, as numbers rather than a screenshot.
//
// The plan's gate, quoted: "sticky headers stick at 1440/1024/390; 0
// horizontal scroll; every row has a title readable without hover and a tab
// stop; arrows move focus in document order and Enter opens the split panel;
// search reduces the row count". Each of those is a measurement here, and the
// script exits non-zero if any of them fails, so it can gate a commit rather
// than be read.
//
// Run it from this directory:
//   BASE=http://127.0.0.1:8936 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//     SCRATCH=/tmp/claude-0 timeout 110 node timeline.js
//
// Seed first (`seed-timeline.js` then `seed-timeline.py`), or every count is
// zero and every check passes for the wrong reason: an empty feed has no rows
// to fail. The row count assertion below is what catches that.
const { boot } = require('./lib.js');

const WIDTHS = [
  { w: 1440, h: 900 },
  { w: 1024, h: 820 },
  { w: 390, h: 844 },
];

let failures = 0;
const check = (label, ok, detail) => {
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}  ${detail}`);
};

(async () => {
  const { browser, page, OUT } = await boot();
  for (const { w, h } of WIDTHS) {
    await page.setViewportSize({ width: w, height: h });
    await page.click('[data-tab="timeline"]');
    await page.waitForTimeout(900);
    // The scale select drives the density, and the gate is about the full
    // row: ask for the day scale explicitly rather than measuring whatever
    // "auto" chose for this seed at this width.
    await page.evaluate(() => {
      const sel = document.getElementById('timeline-scale');
      if (sel && sel.value !== 'day') {
        sel.value = 'day';
        sel.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
    await page.waitForTimeout(900);

    const shape = await page.evaluate(() => {
      const scroller = document.getElementById('timeline-scroll');
      const rows = [...document.querySelectorAll('.timeline-row')];
      const heads = [...document.querySelectorAll('.timeline-bucket-head')];
      const titled = rows.filter((r) => {
        const t = r.querySelector('.timeline-row-title');
        if (!t || !t.textContent.trim()) return false;
        // Readable without hover means the text is actually laid out: a
        // zero-height or zero-width title is text nobody can read, and an
        // ellipsis is fine but an empty box is not.
        const box = t.getBoundingClientRect();
        return box.width > 8 && box.height > 4;
      });
      // The plan's gate says "a tab stop" per row. The app's own recipe for a
      // list (`applyEntryListTabOrder`, the Notes list) is a ROVING tab stop:
      // every row focusable, exactly one of them in the page's Tab order, and
      // the arrows moving between them. Forty-eight Tab stops in one feed is
      // the other failure. So: every row carries a tabindex, and exactly one
      // of them is 0.
      const focusable = rows.filter((r) => r.hasAttribute('tabindex'));
      const stops = rows.filter((r) => Number(r.getAttribute('tabindex')) === 0);
      const page_ = document.getElementById('tab-timeline');
      return {
        rows: rows.length,
        titled: titled.length,
        stops: stops.length,
        focusable: focusable.length,
        heads: heads.length,
        headFont: heads[0] ? getComputedStyle(heads[0]).position : '',
        scrollerOverflowX: scroller ? scroller.scrollWidth - scroller.clientWidth : -1,
        pageOverflowX: page_ ? page_.scrollWidth - page_.clientWidth : -1,
        docOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        scrollable: scroller ? scroller.scrollHeight - scroller.clientHeight : -1,
        rowH: rows[0] ? Math.round(rows[0].getBoundingClientRect().height) : 0,
      };
    });
    check(`${w} rows rendered`, shape.rows > 0, `rows=${shape.rows} buckets=${shape.heads} rowH=${shape.rowH}px`);
    check(`${w} every row has a readable title`, shape.rows > 0 && shape.titled === shape.rows, `${shape.titled}/${shape.rows}`);
    check(`${w} every row is keyboard reachable, one Tab stop`,
      shape.rows > 0 && shape.focusable === shape.rows && shape.stops === 1,
      `${shape.focusable}/${shape.rows} focusable, ${shape.stops} Tab stop`);
    check(`${w} no horizontal scroll`, shape.scrollerOverflowX <= 0 && shape.pageOverflowX <= 0 && shape.docOverflowX <= 0,
      `scroller=${shape.scrollerOverflowX}px tab=${shape.pageOverflowX}px doc=${shape.docOverflowX}px`);
    check(`${w} headers are sticky`, shape.headFont === 'sticky', `position=${shape.headFont}`);

    // Sticky, measured: scroll the feed past its first bucket and ask whether
    // a bucket head is still pinned at the top of whichever box scrolls. The
    // one number that matters is the gap between the topmost visible head and
    // the scroll box's own top edge; a header that scrolled away leaves a gap
    // the size of everything above it.
    const stuck = await page.evaluate(() => {
      const scroller = document.getElementById('timeline-scroll');
      const box = scroller.scrollHeight - scroller.clientHeight > 40 ? scroller : document.scrollingElement;
      const before = box.scrollTop;
      box.scrollTop = before + 260;
      const top = box === document.scrollingElement
        ? (document.querySelector('header#top-bar')?.getBoundingClientRect().bottom ?? 0)
        : scroller.getBoundingClientRect().top;
      const heads = [...document.querySelectorAll('.timeline-bucket-head')]
        .map((hd) => ({ t: hd.getBoundingClientRect().top, text: hd.textContent.trim().slice(0, 18) }))
        .filter((hd) => hd.t >= top - 2 && hd.t < top + 160)
        .sort((a, b) => a.t - b.t);
      return {
        which: box === scroller ? '#timeline-scroll' : 'page',
        scrolled: box.scrollTop - before,
        gap: heads.length ? Math.round(heads[0].t - top) : 9999,
        text: heads.length ? heads[0].text : '(none)',
      };
    });
    check(`${w} a bucket head stays pinned after scrolling`, stuck.scrolled > 0 && stuck.gap <= 4,
      `${stuck.which} scrolled ${stuck.scrolled}px, head "${stuck.text}" sits ${stuck.gap}px below the top`);

    // Arrows walk the rows in document order, Enter opens the row in place.
    const keys = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.timeline-row')];
      if (rows.length < 3) return { ok: false, why: 'too few rows' };
      rows[0].focus();
      const order = [document.activeElement === rows[0] ? 0 : -1];
      for (const key of ['ArrowDown', 'ArrowDown', 'ArrowUp']) {
        document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
        order.push(rows.indexOf(document.activeElement));
      }
      return { ok: true, order };
    });
    check(`${w} arrows move focus in document order`, keys.ok && String(keys.order) === '0,1,2,1', `focus walked ${keys.order}`);

    const opened = await page.evaluate(() => {
      const row = document.querySelector('.timeline-row');
      if (!row) return { expanded: '(no row)' };
      row.focus();
      row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      return { expanded: row.getAttribute('aria-expanded') };
    });
    await page.waitForTimeout(700);
    const detail = await page.evaluate(() => {
      const row = document.querySelector('.timeline-row');
      const body = row ? row.querySelector('.timeline-row-detail') : null;
      return {
        present: Boolean(body),
        height: body ? Math.round(body.getBoundingClientRect().height) : 0,
        text: body ? body.textContent.trim().length : 0,
      };
    });
    check(`${w} Enter opens the row in place`, opened.expanded === 'true' && detail.height > 20 && detail.text > 10,
      `aria-expanded=${opened.expanded} detail ${detail.height}px, ${detail.text} chars`);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);

    // Search filters the array rather than dimming it, so the row count falls.
    const search = await page.evaluate(async () => {
      const before = document.querySelectorAll('.timeline-row').length;
      const box = document.getElementById('timeline-search');
      if (!box) return { before, after: -1, restored: -1 };
      box.value = 'kyoto';
      box.dispatchEvent(new Event('input', { bubbles: true }));
      await new Promise((r) => setTimeout(r, 500));
      const after = document.querySelectorAll('.timeline-row').length;
      box.value = '';
      box.dispatchEvent(new Event('input', { bubbles: true }));
      await new Promise((r) => setTimeout(r, 500));
      return { before, after, restored: document.querySelectorAll('.timeline-row').length };
    });
    check(`${w} search reduces the row count`, search.after > 0 && search.after < search.before && search.restored === search.before,
      `${search.before} -> ${search.after} -> ${search.restored}`);

    await page.screenshot({ path: `${OUT}/timeline-${w}.png`, fullPage: false });
  }
  await browser.close();
  console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
  process.exit(failures ? 1 : 0);
})();
