// Why is one Insert row filled at rest? Ask the browser which rules matched,
// rather than guessing from a grep.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const id=await page.evaluate(async()=>{const r=await api('/whiteboard/boards',{method:'POST',body:JSON.stringify({name:'Why board'})});return (await r.json()).id;});
  await page.evaluate((b)=>openWhiteboardBoard(b), id); await page.waitForTimeout(1500);
  await page.evaluate(()=>{document.querySelector('[aria-controls="wb-insert-menu"]')?.click();});
  await page.waitForTimeout(300);
  const r=await page.evaluate(()=>{
    const el=[...document.querySelectorAll('#wb-insert-menu .wb-menu-item')].find(e=>e.textContent.includes('Connector'));
    const act=document.activeElement;
    return {
      classes:[...el.classList], attrs:[...el.attributes].map(a=>a.name+'='+a.value),
      matchesHover: el.matches(':hover'), matchesFocus: el.matches(':focus-visible'), matchesFocusPlain: el.matches(':focus'),
      active: act ? (act.tagName+'#'+act.id+'.'+act.className+' "'+act.textContent.trim().slice(0,20)+'"') : 'none',
      bg: getComputedStyle(el).backgroundColor,
    };
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
