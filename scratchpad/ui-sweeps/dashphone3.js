const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot({viewport:{width:390,height:844}});
  await page.waitForTimeout(1500);
  const r=await page.evaluate(()=>{
    const rows=[...document.querySelectorAll('.dash-quicklinks .launch-row')];
    return rows.map(row=>{
      const cs=getComputedStyle(row);
      return {cls:row.className, display:cs.display, dir:cs.flexDirection, wrap:cs.flexWrap,
        cols:cs.gridTemplateColumns, gap:cs.gap,
        kids:[...row.children].slice(0,3).map(k=>({cls:k.className,
          w:Math.round(k.getBoundingClientRect().width), h:Math.round(k.getBoundingClientRect().height),
          flex:getComputedStyle(k).flex, minW:getComputedStyle(k).minWidth}))};
    });
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
