// The DOM path from a dock down to one control. A "quiet by default" rule in a
// bar is written as `.dock > * > button`, so a control one wrapper deeper than
// the rule expects keeps its fill and nothing says why. This prints the path.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.click(`[data-tab="${process.env.TAB||'chat'}"]`).catch(()=>{}); await page.waitForTimeout(1200);
  const r=await page.evaluate((sel)=>{
    const el=[...document.querySelectorAll(sel)].find(e=>e.checkVisibility&&e.checkVisibility());
    if(!el) return 'not found';
    const path=[]; for(let e=el; e && !e.classList.contains('dock') && e!==document.body; e=e.parentElement){
      path.unshift(`${e.tagName.toLowerCase()}${e.id?'#'+e.id:''}${e.className?'.'+String(e.className).trim().split(/\s+/).join('.'):''}`);
    }
    return {path:'.dock > '+path.join(' > '), bg:getComputedStyle(el).backgroundColor};
  }, process.env.SEL);
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
