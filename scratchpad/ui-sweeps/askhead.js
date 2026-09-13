// The Ask sub-tab's AI answer head: does it wrap, and are its controls on the
// app's control height? #chat-results is hidden until an answer exists, so the
// sweep unhides it and gives the badge a real model id: the question is what
// the layout does with a long one, which needs no model run.
const {boot} = require('/home/user/MemoryMap-AI/scratchpad/ui-sweeps/lib.js');
const NAMES = [
  // What renderChatMeta now writes: the model id, with the phrase on the
  // tooltip. Both the name from the report and a real long Ollama id.
  ['reported', 'granite4.1:3b'],
  ['long', 'hf.co/unsloth/Qwen2.5-14B-Instruct-GGUF:Q4_K_M'],
];
(async () => {
  const {browser, page} = await boot();
  const errs = [];
  page.on('pageerror', e => errs.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0,120)); });
  await page.click('[data-tab="notes"]'); await page.waitForTimeout(500);
  await page.evaluate(() => window.showNotesSection && showNotesSection('ask'));
  await page.waitForTimeout(900);
  for (const w of [1440, 1024, 820]) {
    await page.setViewportSize({width: w, height: 900});
    for (const [tag, name] of NAMES) {
      const r = await page.evaluate((n) => {
        document.getElementById('chat-results').classList.remove('hidden');
        document.getElementById('ask-idle')?.classList.add('hidden');
        const by = document.getElementById('answered-by');
        by.textContent = n;
        by.title = 'Answered by ' + n;
        for (const id of ['retry-btn','copy-btn','speak-btn']) document.getElementById(id).classList.remove('hidden');
        const ans = document.getElementById('ai-answer');
        if (!ans.textContent.trim()) ans.textContent = 'You asked: Summarise my hobbies';
        const head = document.querySelector('#chat-results .chat-half .panel-head');
        const title = head.querySelector('.answer-title');
        const acts = head.querySelector('.answer-actions');
        const box = (e) => { const b = e.getBoundingClientRect(); return {x: +b.left.toFixed(1), y: +b.top.toFixed(1), w: +b.width.toFixed(1), h: +b.height.toFixed(1)}; };
        const ctrls = [...head.querySelectorAll('button')].filter(b => b.getBoundingClientRect().height > 0);
        return {
          headH: +head.getBoundingClientRect().height.toFixed(1),
          headW: +head.getBoundingClientRect().width.toFixed(1),
          titleTop: title.offsetTop, actsTop: acts.offsetTop,
          sameLine: title.offsetTop === acts.offsetTop,
          centres: [ +(title.getBoundingClientRect().top + title.getBoundingClientRect().height/2).toFixed(1),
                     +(by.getBoundingClientRect().top + by.getBoundingClientRect().height/2).toFixed(1),
                     +(acts.getBoundingClientRect().top + acts.getBoundingClientRect().height/2).toFixed(1) ],
          badgeClipped: by.scrollWidth > by.clientWidth + 1,
          badgeTitle: by.title,
          badge: box(by), title: box(title), acts: box(acts),
          controlH: getComputedStyle(document.documentElement).getPropertyValue('--control-h').trim(),
          btnHeights: ctrls.map(b => +b.getBoundingClientRect().height.toFixed(1)),
          btnFonts: [...new Set(ctrls.map(b => getComputedStyle(b).fontSize))],
          overflowX: head.scrollWidth > head.clientWidth + 1 ? head.scrollWidth - head.clientWidth : 0,
          pageScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          halfW: +document.querySelector('#chat-results .chat-half').getBoundingClientRect().width.toFixed(1),
        };
      }, name);
      console.log(`${w} ${tag}`, JSON.stringify(r));
    }
    await page.screenshot({path: `/tmp/claude-0/ocrwork/askhead-${w}.png`, clip: {x:0, y:120, width: w, height: 460}});
  }
  console.log('ERRORS', errs.length, JSON.stringify(errs.slice(0,5)));
  await browser.close();
})();
