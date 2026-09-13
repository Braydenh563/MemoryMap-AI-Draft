const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  for(const t of ['library','timeline','reminders','chat','notes']){
    await page.click(`[data-tab="${t}"]`).catch(()=>{});await page.waitForTimeout(1000);
    const rows=await page.evaluate((tab)=>{
      const out=[];
      document.querySelectorAll('.seg').forEach(seg=>{
        if(!seg.checkVisibility||!seg.checkVisibility())return;
        if(seg.getBoundingClientRect().width<6)return;
        const btns=[...seg.querySelectorAll('button')].filter(b=>b.getBoundingClientRect().width);
        if(!btns.length)return;
        out.push({tab, id:seg.id||seg.className.slice(0,24), role:seg.getAttribute('role'),
          fs:getComputedStyle(btns[0]).fontSize,
          kinds:btns.map(b=>({iconOnly:b.classList.contains('icon-only'),
            text:(b.textContent||'').trim().slice(0,10),
            icons:b.querySelectorAll('i').length,
            iconFs:b.querySelector('i')?getComputedStyle(b.querySelector('i')).fontSize:null}))});
      });
      return out;
    }, t);
    for(const r of rows) console.log(JSON.stringify(r));
  }
  await browser.close();
})();
