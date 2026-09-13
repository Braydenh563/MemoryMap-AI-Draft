const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.click('[data-tab="library"]').catch(()=>{}); await page.waitForTimeout(1200);
  await page.click('#library-subtabs button[data-target="library-view-skills"]').catch(e=>console.log('click fail',e.message));
  await page.waitForTimeout(1400);
  const r=await page.evaluate(()=>{
    const sb=document.getElementById('skills-sidebar');
    const host=document.getElementById('library-view-skills');
    const s=sb.getBoundingClientRect(), h=host.getBoundingClientRect();
    const parent=sb.parentElement;
    const p=parent.getBoundingClientRect();
    const sibs=[...parent.children].map(c=>({cls:(c.className||'').slice(0,28), h:Math.round(c.getBoundingClientRect().height)}));
    const cs=getComputedStyle(sb);
    return {
      hostHidden:host.classList.contains('hidden'),
      sb:{h:Math.round(s.height), top:Math.round(s.top), bottom:Math.round(s.bottom)},
      host:{h:Math.round(h.height), top:Math.round(h.top), bottom:Math.round(h.bottom)},
      parent:{cls:parent.className.slice(0,40), h:Math.round(p.height), display:getComputedStyle(parent).display,
              align:getComputedStyle(parent).alignItems, rows:getComputedStyle(parent).gridTemplateRows},
      sibs, sbHeightCss:cs.height, sbMaxH:cs.maxHeight, sbAlign:cs.alignSelf,
      shortfall:Math.round(p.bottom-s.bottom),
      vh:window.innerHeight,
    };
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
