const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot({viewport:{width:390,height:844}});
  await page.click('[data-tab="library"]').catch(()=>{}); await page.waitForTimeout(1500);
  const r=await page.evaluate(()=>{
    const dock=document.querySelector('#tab-library .dock');
    if(!dock) return {noDock:true};
    const db=dock.getBoundingClientRect();
    const zones=[...dock.children].map(z=>{const b=z.getBoundingClientRect();
      return {cls:(z.className||z.id).slice(0,30), top:Math.round(b.top), h:Math.round(b.height), w:Math.round(b.width),
              kids:z.children.length};});
    const rowsAt=[...new Set(zones.map(z=>z.top))];
    return {dockH:Math.round(db.height), wrap:getComputedStyle(dock).flexWrap, zones, rowCount:rowsAt.length,
      chips:(()=>{const c=document.querySelector('.library-chips, #library-filters');return c?Math.round(c.getBoundingClientRect().height):null;})()};
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
