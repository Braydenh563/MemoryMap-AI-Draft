const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot({viewport:{width:1024,height:900}});
  await page.click('[data-tab="graph"]').catch(()=>{}); await page.waitForTimeout(1500);
  const r=await page.evaluate(()=>{
    const dock=document.querySelector('#tab-graph .dock');
    const info=[...dock.children].filter(c=>c.getBoundingClientRect().width).map(z=>{
      const cs=getComputedStyle(z);
      return {cls:(z.className||'').slice(0,30), flex:cs.flex, minW:cs.minWidth, w:Math.round(z.getBoundingClientRect().width),
              marginLeft:cs.marginLeft};
    });
    // What happens if the find zone stops growing?
    const find=dock.querySelector('.dock-find');
    const before=[...new Set([...dock.children].filter(c=>c.getBoundingClientRect().width).map(c=>Math.round(c.getBoundingClientRect().top)))].length;
    find.style.flex='0 1 auto';
    const afterFind=[...new Set([...dock.children].filter(c=>c.getBoundingClientRect().width).map(c=>Math.round(c.getBoundingClientRect().top)))].length;
    const widths=[...dock.children].filter(c=>c.getBoundingClientRect().width).map(c=>Math.round(c.getBoundingClientRect().width));
    find.style.flex='';
    return {info, rowsBefore:before, rowsWithFindNotGrowing:afterFind, widthsThen:widths,
      dockW:Math.round(dock.getBoundingClientRect().width)};
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
