const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot({viewport:{width:390,height:844}});
  await page.waitForTimeout(1500);
  const r=await page.evaluate(()=>{
    const page_=document.getElementById('tab-dashboard');
    const kids=[...page_.children].map(c=>{
      const b=c.getBoundingClientRect(); const cs=getComputedStyle(c);
      return {cls:(c.className||c.id||c.tagName).slice(0,40), top:Math.round(b.top), h:Math.round(b.height),
              display:cs.display, minH:cs.minHeight, pad:cs.padding};
    });
    const hero=document.querySelector('.dash-hero, #dash-hero, .dashboard-hero, .dash-greeting');
    return {vh:window.innerHeight, kids, hero:hero?{cls:hero.className, h:Math.round(hero.getBoundingClientRect().height), minH:getComputedStyle(hero).minHeight}:null,
      scrollTop:page_.scrollTop, scrollH:page_.scrollHeight, clientH:page_.clientHeight};
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
