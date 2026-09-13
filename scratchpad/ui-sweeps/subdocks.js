// Phase 8, second sitting: the surfaces the first one did not reach, namely every
// Library sub-tab head, the Chat head + toolbar, the Dashboard hero, and the
// Settings section heads. docks.js walks the *tab* panels and so never sees a
// sub-tab that is `hidden` when its tab first paints; this one clicks each
// sub-tab and measures the head row it actually renders.
//
//   BASE=http://127.0.0.1:8799 SCRATCH=/tmp/mm-docks \
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node subdocks.js
const { boot } = require('./lib.js');
const ROWSEL = '.dock, .row.space-between, .library-toolbar, .library-head, .chat-toolbar, .hero-actions, [role="toolbar"]';
async function inv(page, label, sel) {
  const r = await page.evaluate(({ sel, ROWSEL }) => {
    const root = document.querySelector(sel);
    if (!root) return null;
    const vis = (e) => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0; };
    return [...root.querySelectorAll(ROWSEL)].filter(vis).slice(0, 8).map((e) => {
      const ctrls = [...e.querySelectorAll('button, select, input:not([type=hidden]), .seg, .select-shell, summary')]
        .filter((c) => vis(c) && !c.closest('.doc-dock-menu-list') && c.closest(ROWSEL) === e);
      const hs = [...new Set(ctrls.map((c) => Math.round(c.getBoundingClientRect().height)))].sort((a, b) => a - b);
      const filled = ctrls.filter((c) => c.tagName === 'BUTTON'
        && !c.classList.contains('ghost') && !c.classList.contains('icon-only')
        && !c.classList.contains('select-opener'));
      return {
        sel: (e.id ? '#' + e.id : '.' + [...e.classList].slice(0, 2).join('.')),
        y: Math.round(e.getBoundingClientRect().top),
        controls: ctrls.length,
        heights: hs.join('/'),
        filled: filled.map((b) => b.id || b.textContent.trim().slice(0, 14)),
        ids: ctrls.map((c) => c.id || ('.' + [...c.classList].slice(0, 1).join(''))).join(' '),
      };
    });
  }, { sel, ROWSEL });
  console.log(label.padEnd(22), JSON.stringify(r));
}
(async () => {
  const { browser, page } = await boot();
  await page.click('[data-tab="dashboard"]'); await page.waitForTimeout(600);
  await inv(page, 'dashboard', '#tab-dashboard');
  await page.click('[data-tab="chat"]'); await page.waitForTimeout(700);
  await inv(page, 'chat', '#tab-chat');
  await page.click('[data-tab="library"]'); await page.waitForTimeout(600);
  const subs = [['all', 'library-view-documents'], ['docs', 'library-view-docs'],
    ['boards', 'library-view-whiteboard'], ['images', 'library-view-media'],
    ['skills', 'library-view-skills'], ['links', 'library-view-links'],
    ['contents', 'library-view-contents']];
  for (const [name, target] of subs) {
    await page.click(`[data-target="${target}"]`); await page.waitForTimeout(700);
    await inv(page, 'library:' + name, '#' + target);
  }
  await page.click('[data-target="library-view-media"][data-media-kind="files"]'); await page.waitForTimeout(700);
  await inv(page, 'library:files', '#library-view-media');
  await page.click('[data-tab="settings"]').catch(() => {}); await page.waitForTimeout(800);
  await inv(page, 'settings', '#tab-settings');
  await browser.close();
})();
