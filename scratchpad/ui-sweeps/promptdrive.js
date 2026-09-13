// `promptDialog` gained a title row, which means its first child changed and
// its append order changed. Twenty-odd callers depend on it, so it is driven
// rather than read: type a name, press Enter, and check the board really
// exists on the server.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const count=async()=>page.evaluate(async()=>{const r=await api('/whiteboard/boards');return (await r.json()).length;});
  await page.click('[data-tab="library"]'); await page.waitForTimeout(900);
  await page.click('[data-target="library-view-whiteboard"]',{timeout:5000}).catch(()=>{});
  await page.waitForTimeout(1300);
  const before=await count();
  await page.click('#wb-boards-new',{timeout:5000});
  await page.waitForTimeout(700);
  const shape=await page.evaluate(()=>{
    const card=document.querySelector('.confirm-card');
    if(!card) return 'no dialog';
    const h=card.querySelector('.confirm-title');
    const input=card.querySelector('input');
    return {
      title: h? h.textContent.trim() : '(none)',
      titleTag: h? h.tagName : '-',
      inputFocused: document.activeElement===input,
      inputAriaLabel: input? input.getAttribute('aria-label') : '-',
      children: [...card.children].map(e=>e.tagName.toLowerCase()+'.'+String(e.className).trim().split(/\s+/)[0]),
    };
  });
  console.log('dialog shape:', JSON.stringify(shape));
  await page.fill('.confirm-card input','Prompt drive board');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(1500);
  const after=await count();
  const named=await page.evaluate(async()=>{const r=await api('/whiteboard/boards');const j=await r.json();// BoardOut's field is \`title\`, not \`name\`: the create body takes \`name\`
    // and the read model returns \`title\`, which is worth naming because a
    // check written against the wrong one reads as a broken feature.
    return j.some(b=>(b.title||'').includes('Prompt drive board'));});
  console.log(`boards ${before} -> ${after}; a board named "Prompt drive board" exists = ${named}`);
  const stillOpen=await page.evaluate(()=>!!document.querySelector('.confirm-card'));
  console.log('dialog closed after Enter =', !stillOpen);
  await browser.close();
})();
