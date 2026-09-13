// INBOX 110: "square tab corners" and "the containers of all the ui in each
// tab page have hard corner rectangular edges ... the shadows make the cut off
// pretty obvious". Sweep every tab and sub-tab for a visible element whose
// border-radius is 0 while it carries a shadow or a border (a framed box with
// square corners), and for a 0px-radius element sitting among rounded
// siblings.
const { boot } = require('./lib.js');
const TABS = ['dashboard', 'notes', 'chat', 'graph', 'library', 'timeline', 'documents', 'reminders', 'whiteboard', 'settings'];

(async () => {
  const { browser, page } = await boot();
  await page.waitForTimeout(1500);
  const all = {};
  for (const tab of TABS) {
    const ok = await page.evaluate((t) => {
      try { if (typeof switchTab === 'function') { switchTab(t); return true; } } catch (e) { return String(e); }
      return false;
    }, tab);
    await page.waitForTimeout(1400);
    const found = await page.evaluate(() => {
      const out = { framedSquare: [], oddSibling: [], subtabs: [] };
      const path = (el) => {
        let s = el.tagName.toLowerCase();
        if (el.id) s += '#' + el.id;
        if (el.className && typeof el.className === 'string') s += '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.');
        return s;
      };
      const vis = [...document.querySelectorAll('*')].filter((el) => {
        const b = el.getBoundingClientRect();
        if (b.width < 40 || b.height < 24) return false;
        const cs = getComputedStyle(el);
        return cs.display !== 'none' && cs.visibility !== 'hidden' && Number(cs.opacity) > 0.05;
      });
      for (const el of vis) {
        const cs = getComputedStyle(el);
        const rad = cs.borderRadius;
        const flat = /^0px( 0px)*$/.test(rad);
        if (!flat) continue;
        const hasShadow = cs.boxShadow && cs.boxShadow !== 'none';
        const hasBorder = parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== 'none';
        const hasBg = cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'transparent';
        if (hasShadow || (hasBorder && hasBg)) {
          out.framedSquare.push({ sel: path(el), radius: rad, shadow: (cs.boxShadow || '').slice(0, 70), border: cs.borderTopWidth + ' ' + cs.borderTopStyle, bg: cs.backgroundColor, box: [Math.round(el.getBoundingClientRect().width), Math.round(el.getBoundingClientRect().height)] });
        }
        // A square among rounded siblings.
        const sibs = [...(el.parentElement ? el.parentElement.children : [])].filter((s) => s !== el);
        const rounded = sibs.filter((s) => { const r = getComputedStyle(s).borderRadius; return r && !/^0px( 0px)*$/.test(r) && s.getBoundingClientRect().width > 20; });
        if (rounded.length && rounded.length === sibs.filter((s) => s.getBoundingClientRect().width > 20).length) {
          out.oddSibling.push({ sel: path(el), parent: path(el.parentElement), roundedSibs: rounded.length, sibRadius: getComputedStyle(rounded[0]).borderRadius });
        }
      }
      // Every tab-like control, with its radius.
      const tabish = [...document.querySelectorAll('[role="tab"], .subtab, .seg > *, .segmented-control > *, [id^="tab-btn-"], .notes-subtabs *, .sub-tabs *, [class*="subtab"]')];
      for (const el of tabish) {
        const b = el.getBoundingClientRect();
        if (b.width < 12 || b.height < 8) continue;
        const cs = getComputedStyle(el);
        out.subtabs.push({ sel: path(el), radius: cs.borderRadius, w: Math.round(b.width), h: Math.round(b.height) });
      }
      return out;
    });
    all[tab] = found;
    console.log('== ' + tab + ' (switch:' + ok + ')');
    console.log(' framedSquare:', JSON.stringify(found.framedSquare.slice(0, 14)));
    console.log(' oddSibling:', JSON.stringify(found.oddSibling.slice(0, 10)));
    const flatTabs = found.subtabs.filter((s) => /^0px( 0px)*$/.test(s.radius));
    console.log(' flat tab-ish:', JSON.stringify(flatTabs.slice(0, 20)));
    console.log(' all tab-ish radii:', JSON.stringify([...new Set(found.subtabs.map((s) => s.radius))]));
  }
  await browser.close();
})();
