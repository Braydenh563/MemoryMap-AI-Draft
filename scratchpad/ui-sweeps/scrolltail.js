// "the panels and sidebars in windows actually go quite far down below where
// the scroll should stop": how much empty room is under the last real content
// in each tab's scroll container, once scrolled to the end.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.waitForTimeout(1500);
  const out=[];
  for (const tab of ['dashboard','notes','library','timeline','reminders','documents']){
    const r=await page.evaluate(async(t)=>{
      switchTab(t);
      await new Promise(r=>setTimeout(r,1100));
      const el=(typeof scrollTopTargetEl==='function')?scrollTopTargetEl():document.getElementById('tab-'+t);
      if(!el) return {tab:t, none:true};
      el.scrollTop=el.scrollHeight;
      await new Promise(r=>setTimeout(r,400));
      const box=el.getBoundingClientRect();
      // The lowest painted bottom among the container's visible descendants.
      let lowest=-Infinity, who='';
      el.querySelectorAll('*').forEach(n=>{
        if(!n.checkVisibility||!n.checkVisibility())return;
        const b=n.getBoundingClientRect();
        if(b.width<4||b.height<4)return;
        if(getComputedStyle(n).position==='fixed')return;
        if(b.bottom>lowest){lowest=b.bottom;who=(n.id||n.className||n.tagName).toString().slice(0,30);}
      });
      return {tab:t, id:el.id||el.className.slice(0,24),
        scrollH:Math.round(el.scrollHeight), clientH:Math.round(el.clientHeight),
        atEnd:Math.round(el.scrollTop+el.clientHeight)>=Math.round(el.scrollHeight)-2,
        tailGap:Math.round(box.bottom-lowest), lowest:who};
    }, tab);
    out.push(r);
  }
  console.log(JSON.stringify(out,null,1));
  await browser.close();
})();
