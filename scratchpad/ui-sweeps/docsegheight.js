const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot({viewport:{width:1280,height:900}});
  await page.click('[data-tab="documents"]').catch(()=>{}); await page.waitForTimeout(1400);
  const r=await page.evaluate(()=>{
    const dock=document.querySelector('#tab-documents .dock, .doc-dock');
    if(!dock) return {noDock:true};
    const rows=[...dock.querySelectorAll('button, summary, input, select')].filter(e=>e.getBoundingClientRect().height)
      .map(e=>({t:(e.id||e.textContent.trim()||e.tagName).slice(0,22), tag:e.tagName.toLowerCase(),
        cls:(e.className||'').slice(0,40), h:Math.round(e.getBoundingClientRect().height),
        minH:getComputedStyle(e).minHeight, pad:getComputedStyle(e).padding,
        parentCls:(e.parentElement.className||'').slice(0,36)}));
    return {dockH:Math.round(dock.getBoundingClientRect().height), controlH:getComputedStyle(dock).getPropertyValue('--control-h'), rows};
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
