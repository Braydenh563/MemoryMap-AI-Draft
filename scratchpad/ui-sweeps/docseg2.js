const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot({viewport:{width:1280,height:900}});
  await page.click('[data-tab="documents"]').catch(()=>{}); await page.waitForTimeout(1400);
  const r=await page.evaluate(()=>{
    const seg=document.getElementById('doc-view-seg');
    const dock=document.querySelector('.doc-dock');
    const other=[...dock.querySelectorAll('button.ghost.small, summary')].filter(e=>e.getBoundingClientRect().height)[0];
    const other2=document.getElementById('doc-ai');
    const b=(e)=>e?Math.round(e.getBoundingClientRect().height):null;
    // Other segs in the app, for comparison
    const segs=[...document.querySelectorAll('.seg')].filter(e=>e.getBoundingClientRect().height).map(e=>({
      id:e.id||e.className.slice(0,24), h:b(e), btn:b(e.querySelector('button')), pad:getComputedStyle(e).padding}));
    return {segH:b(seg), segBtn:b(seg?.querySelector('button')), segPad:getComputedStyle(seg).padding,
      ghostH:b(other), aiH:b(other2), dockH:b(dock), segs};
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
