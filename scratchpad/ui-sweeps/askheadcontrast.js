// Contrast of the Ask answer head, both themes. #chat-results is hidden until
// an answer exists, so contrast.js never reaches it: this unhides the panel and
// measures the same way (computed colour, composited against the first
// non-transparent ground up the tree).
const {boot} = require('/home/user/MemoryMap-AI/scratchpad/ui-sweeps/lib.js');
(async () => {
  const {browser, page} = await boot();
  await page.click('[data-tab="notes"]'); await page.waitForTimeout(400);
  await page.evaluate(() => window.showNotesSection && showNotesSection('ask'));
  await page.waitForTimeout(900);
  const r = await page.evaluate(() => {
    document.getElementById('chat-results').classList.remove('hidden');
    document.getElementById('ask-idle')?.classList.add('hidden');
    const by = document.getElementById('answered-by');
    by.textContent = 'granite4.1:3b';
    for (const id of ['retry-btn','copy-btn','speak-btn']) document.getElementById(id).classList.remove('hidden');
    const cv = document.createElement('canvas'); cv.width = cv.height = 1;
    const cx = cv.getContext('2d', {willReadFrequently: true});
    const parse = (c) => { if (!c || c === 'transparent') return null;
      cx.clearRect(0,0,1,1); cx.fillStyle = '#000'; cx.fillStyle = c;
      cx.fillRect(0,0,1,1); const d = cx.getImageData(0,0,1,1).data;
      const m = c.match(/rgba?\(([^)]+)\)/); let a = 1;
      if (m) { const p = m[1].split(/[\s,\/]+/).map(Number); if (p.length > 3) a = p[3]; }
      return {r: d[0], g: d[1], b: d[2], a}; };
    const ground = (el) => { let n = el;
      while (n) { const b = parse(getComputedStyle(n).backgroundColor);
        if (b && b.a >= 0.95) return b; n = n.parentElement; }
      return {r: 255, g: 255, b: 255, a: 1}; };
    const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v/12.92 : ((v+0.055)/1.055)**2.4; };
      return 0.2126*f(c.r) + 0.7152*f(c.g) + 0.0722*f(c.b); };
    const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b);
      return +(((Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05))).toFixed(2); };
    const out = [];
    const probe = (label, el) => { const cs = getComputedStyle(el);
      const fg = parse(cs.color); const bg = ground(el);
      const size = parseFloat(cs.fontSize); const bold = parseInt(cs.fontWeight, 10) >= 700;
      const floor = (size >= 18.66 || (bold && size >= 14)) ? 3 : 4.5;
      out.push({label, size: +size.toFixed(1), weight: cs.fontWeight, ratio: ratio(fg, bg), floor,
        pass: ratio(fg, bg) >= floor, fg: cs.color, bg: `rgb(${bg.r},${bg.g},${bg.b})`}); };
    probe('AI answer label', document.querySelector('.answer-title'));
    probe('model badge', by);
    for (const id of ['retry-btn','copy-btn','speak-btn']) probe(id + ' glyph', document.querySelector('#' + id + ' i'));
    return out;
  });
  console.log((process.env.THEME || 'light').toUpperCase());
  for (const row of r) console.log(' ', row.pass ? 'pass' : 'FAIL', JSON.stringify(row));
  await browser.close();
})();
