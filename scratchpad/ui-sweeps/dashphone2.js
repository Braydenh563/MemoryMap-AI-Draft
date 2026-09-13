const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot({viewport:{width:390,height:844}});
  await page.waitForTimeout(1500);
  const r=await page.evaluate(()=>{
    const q=document.querySelector('.dash-quicklinks');
    const groups=[...q.children].map(g=>{
      const b=g.getBoundingClientRect();
      const label=g.querySelector('.launch-label');
      const row=g.querySelector('.launch-row');
      const rb=row?row.getBoundingClientRect():null;
      return {cls:g.className, h:Math.round(b.height),
        label:label?label.textContent.trim().slice(0,24):null,
        labelH:label?Math.round(label.getBoundingClientRect().height):null,
        rowH:rb?Math.round(rb.height):null,
        rowScrollW:row?row.scrollWidth:null, rowClientW:row?row.clientWidth:null,
        items:row?row.children.length:null,
        itemH:row&&row.firstElementChild?Math.round(row.firstElementChild.getBoundingClientRect().height):null,
        wrap:row?getComputedStyle(row).flexWrap:null};
    });
    return {qH:Math.round(q.getBoundingClientRect().height), gap:getComputedStyle(q).gap,
            margin:getComputedStyle(q).margin, groups};
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
