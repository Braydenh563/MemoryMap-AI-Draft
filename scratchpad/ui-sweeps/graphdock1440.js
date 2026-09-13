const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot({viewport:{width:1440,height:900}});
  await page.click('[data-tab="graph"]').catch(()=>{}); await page.waitForTimeout(1400);
  const r=await page.evaluate(()=>{
    const dock=document.querySelector('#tab-graph .dock');
    const vis=[...dock.children].filter(c=>c.getBoundingClientRect().width);
    const label=document.querySelector('#graph-concept-maps .dock-link-label');
    return {rows:[...new Set(vis.map(c=>Math.round(c.getBoundingClientRect().top)))].length,
      labelShown:label?getComputedStyle(label).display:null,
      btnW:Math.round(document.getElementById('graph-concept-maps').getBoundingClientRect().width)};
  });
  console.log(JSON.stringify(r));
  await browser.close();
})();
