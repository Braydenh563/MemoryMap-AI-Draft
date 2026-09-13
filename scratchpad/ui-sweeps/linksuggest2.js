const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const made=await page.evaluate(async()=>{
    const h={'X-Auth-Token':localStorage.getItem('token')||'','Content-Type':'application/json'};
    const texts=[
      '# Bubble tea shops\n\nA list of bubble tea shops near campus worth trying, with notes on the brown sugar one.',
      '# Brown sugar milk tea\n\nRecipe notes for brown sugar milk tea, the bubble tea kind, with tapioca pearls.',
      '# Campus cafes\n\nCafes near campus, including the bubble tea place on the corner.',
    ];
    const ids=[];
    for(const t of texts){
      const r=await fetch('/entries',{method:'POST',headers:h,body:JSON.stringify({content:t})});
      if(r.ok) ids.push((await r.json()).id);
    }
    return ids;
  });
  await page.click('[data-tab="graph"]').catch(()=>{});
  await page.waitForTimeout(1500);
  const out=await page.evaluate(async()=>{
    await loadLinkSuggestions();
    await new Promise(r=>setTimeout(r,900));
    const box=document.getElementById('link-suggestions');
    const cs=getComputedStyle(box);
    const row=box.querySelector('.link-suggestion');
    const head=box.querySelector('.link-suggest-head');
    const px=(el,p)=>el?getComputedStyle(el)[p]:null;
    const rect=(el)=>el?{l:Math.round(el.getBoundingClientRect().left),r:Math.round(el.getBoundingClientRect().right),h:Math.round(el.getBoundingClientRect().height)}:null;
    return {
      text:(box.textContent||'').slice(0,90),
      rows:box.querySelectorAll('.link-suggestion').length,
      boxPadding:cs.padding, boxMargin:cs.margin, boxRadius:cs.borderRadius, boxBorder:cs.borderTopWidth+' '+cs.borderTopColor,
      boxRect:rect(box),
      headRect:rect(head), headMargin:px(head,'marginBottom'),
      rowPadding:px(row,'padding'), rowGap:px(row,'gap'), rowMargin:px(row,'marginBottom'),
      rowRect:rect(row),
      insetLeft: row&&box?Math.round(row.getBoundingClientRect().left-box.getBoundingClientRect().left):null,
      insetRight: row&&box?Math.round(box.getBoundingClientRect().right-row.getBoundingClientRect().right):null,
      reasonH: rect(box.querySelector('.link-suggestion-reason'))?.h,
      linkBtnH: rect(box.querySelector('.link-suggestion button'))?.h,
      tokens: (()=>{const s=getComputedStyle(document.documentElement);
        return {s2:s.getPropertyValue('--space-2').trim(),s3:s.getPropertyValue('--space-3').trim(),
                s4:s.getPropertyValue('--space-4').trim(),radiusLg:s.getPropertyValue('--radius-lg').trim()};})(),
    };
  });
  console.log(JSON.stringify(out,null,1));
  await browser.close();
})();
