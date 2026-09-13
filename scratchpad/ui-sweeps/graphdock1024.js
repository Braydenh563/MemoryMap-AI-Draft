const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot({viewport:{width:1024,height:900}});
  await page.click('[data-tab="graph"]').catch(()=>{}); await page.waitForTimeout(1500);
  const r=await page.evaluate(()=>{
    const dock=document.querySelector('#tab-graph .dock');
    const db=dock.getBoundingClientRect();
    const zones=[...dock.children].map(z=>{const b=z.getBoundingClientRect();
      return {cls:(z.className||z.id||'').slice(0,34), top:Math.round(b.top), w:Math.round(b.width),
        kids:[...z.children].map(k=>({t:(k.id||k.className||k.tagName).slice(0,26), w:Math.round(k.getBoundingClientRect().width)}))};});
    return {dockW:Math.round(db.width), dockH:Math.round(db.height), rows:[...new Set(zones.map(z=>z.top))].length, zones,
      gap:getComputedStyle(dock).gap, pad:getComputedStyle(dock).padding};
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
