// Measure the Boards & maps dashboard widget against its sibling widgets.
// INBOX 110: "the boards and maps dashboard widget is ugly and needs fixing".
const { boot } = require('./lib.js');

(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1500);
  // Make sure the widget is on: the widgets dialog lists them by id.
  const on = await page.evaluate(() => {
    try {
      const key = Object.keys(localStorage).filter((k) => /widget/i.test(k));
      return key.map((k) => k + '=' + localStorage.getItem(k).slice(0, 300));
    } catch (e) { return [String(e)]; }
  });
  console.log('widget prefs:', JSON.stringify(on, null, 1));
  await page.waitForTimeout(1200);
  const out = await page.evaluate(() => {
    const r = (el) => { const b = el.getBoundingClientRect(); return { w: +b.width.toFixed(1), h: +b.height.toFixed(1) }; };
    const widgets = [...document.querySelectorAll('.dash-widget')].map((w) => {
      const head = w.querySelector('h3, .dash-widget-head, header');
      const body = w.querySelector('.dash-body');
      const rows = [...w.querySelectorAll('.dash-list > li')];
      return {
        id: w.id || w.dataset.widget || '?',
        title: (head && head.textContent.trim().slice(0, 40)) || '',
        box: r(w),
        bodyScroll: body ? { sh: body.scrollHeight, ch: body.clientHeight } : null,
        rowCount: rows.length,
        rowHeights: rows.slice(0, 6).map((li) => +li.getBoundingClientRect().height.toFixed(1)),
        rowPad: rows[0] ? getComputedStyle(rows[0]).padding : null,
        rowGap: rows[0] ? getComputedStyle(rows[0].parentElement).gap : null,
      };
    });
    const bw = document.querySelector('.dash-widget .dash-board-thumb');
    const boardWidget = bw ? bw.closest('.dash-widget') : null;
    let thumbs = [];
    if (boardWidget) {
      thumbs = [...boardWidget.querySelectorAll('.dash-list-thumb')].map((t) => {
        const cs = getComputedStyle(t);
        const b = t.getBoundingClientRect();
        return {
          cls: t.getAttribute('class'),
          w: +b.width.toFixed(1), h: +b.height.toFixed(1),
          radius: cs.borderRadius, border: cs.border, bg: cs.backgroundColor,
          viewBox: t.getAttribute('viewBox'),
          kids: t.children.length,
        };
      });
    }
    let rows = [];
    if (boardWidget) {
      rows = [...boardWidget.querySelectorAll('.dash-list > li')].map((li) => {
        const cs = getComputedStyle(li);
        const b = li.getBoundingClientRect();
        const chip = li.querySelector('.map-chip, .chip');
        const title = li.querySelector('.dash-list-title');
        const meta = li.querySelector('.dash-list-preview');
        return {
          h: +b.height.toFixed(1), pad: cs.padding, align: cs.alignItems, gap: cs.gap,
          radius: cs.borderRadius,
          chip: chip ? { cls: chip.className, h: +chip.getBoundingClientRect().height.toFixed(1), txt: chip.textContent.trim().slice(0,40) } : null,
          title: title ? title.textContent.trim().slice(0, 40) : null,
          meta: meta ? meta.textContent.trim().slice(0, 60) : null,
        };
      });
    }
    return { widgets, thumbs, rows, hasBoardWidget: !!boardWidget };
  });
  console.log(JSON.stringify(out, null, 1));
  await page.screenshot({ path: (process.env.SCRATCH || '.') + '/shots/boardswidget.png', fullPage: true });
  await browser.close();
})();
