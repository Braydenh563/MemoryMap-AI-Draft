const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.click('[data-tab="chat"]').catch(()=>{}); await page.waitForTimeout(1200);
  const r=await page.evaluate(()=>{
    const pill=document.getElementById('chat-jump-latest');
    pill.classList.remove('hidden');
    const rest=pill.getBoundingClientRect();
    pill.style.transform='translateY(1px) scale(0.985)';  // the old cue
    const old=pill.getBoundingClientRect();
    pill.style.transform='';
    pill.style.translate='0 1px'; pill.style.scale='0.985'; // the new cue
    const now=pill.getBoundingClientRect();
    const mid=(b)=>Math.round(b.left+b.width/2);
    return {restMid:mid(rest), oldCueMid:mid(old), newCueMid:mid(now)};
  });
  console.log(JSON.stringify({...r, oldDrift:r.oldCueMid-r.restMid, newDrift:r.newCueMid-r.restMid}));
  await browser.close();
})();
