// The owner: "the border shadow on elements like these are too strong",
// three dark-mode screenshots of the top bar, a Peek/Close bar and two icon
// buttons. Measures what a tonal button actually paints in both themes.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const r=await page.evaluate(() => {
    const seen = {};
    const root = getComputedStyle(document.documentElement);
    document.querySelectorAll('button.ghost').forEach(b => {
      if (!b.checkVisibility || !b.checkVisibility()) return;
      const rect = b.getBoundingClientRect();
      if (rect.width < 6) return;
      const c = getComputedStyle(b);
      const key = `${c.boxShadow} | bd=${c.borderTopColor}`;
      if (!seen[key]) seen[key] = { n: 0, ex: [] };
      seen[key].n += 1;
      if (seen[key].ex.length < 3) seen[key].ex.push(b.id || b.className.slice(0, 26));
    });
    return {
      theme: document.documentElement.dataset.mode || 'light',
      shadowSm: root.getPropertyValue('--shadow-sm').trim(),
      intensity: root.getPropertyValue('--shadow-intensity').trim(),
      recipes: seen,
    };
  });
  console.log(JSON.stringify(r, null, 1));
  await browser.close();
})();
