// The five capture-row buttons, before and after they lose their words: they
// must still be a real hit target and still carry an accessible name. A row
// that fits because its controls became unclickable is not a fix.
const {boot}=require('./lib.js');
(async()=>{
  const W=Number(process.env.W||1024);
  const {browser,page}=await boot({viewport:{width:W,height:900}});
  await page.click('[data-tab="notes"]'); await page.waitForTimeout(700);
  await page.click('#tab-notes [data-section="capture"], #tab-notes [data-view="capture"]',{timeout:4000}).catch(()=>{});
  await page.waitForTimeout(900);
  const r=await page.evaluate(()=>[...document.querySelectorAll('.capture-field-row > button')].filter(e=>e.checkVisibility&&e.checkVisibility()).map(e=>{
    const b=e.getBoundingClientRect(); const c=getComputedStyle(e);
    const icon=e.querySelector('.ph');
    return `${e.id} ${b.width.toFixed(0)}x${b.height.toFixed(0)} fs=${c.fontSize} icon=${icon?getComputedStyle(icon).fontSize:'none'} name="${e.getAttribute('aria-label')||e.textContent.trim()}" title=${!!e.title}`;
  }));
  console.log(`== ${W}px`); r.forEach(x=>console.log('  '+x));
  await browser.close();
})();
