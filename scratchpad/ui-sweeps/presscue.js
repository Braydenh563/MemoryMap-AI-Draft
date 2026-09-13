// The press cue must not move a button that positions itself with transform.
// Reported: the chat jump-to-latest pill "jumped to the right for a second".
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.click('[data-tab="chat"]').catch(()=>{}); await page.waitForTimeout(1200);
  const r=await page.evaluate(()=>{
    const pill=document.getElementById('chat-jump-latest');
    if(!pill) return {error:'no pill'};
    pill.classList.remove('hidden');
    const before=pill.getBoundingClientRect();
    const cs=getComputedStyle(pill);
    return {
      transform:cs.transform,
      translate:cs.translate,
      scale:cs.scale,
      left:Math.round(before.left), width:Math.round(before.width),
      // Where the centring puts it: the pill's middle should sit on the
      // transcript's middle.
      parentMid:Math.round(pill.parentElement.getBoundingClientRect().left+pill.parentElement.getBoundingClientRect().width/2),
      pillMid:Math.round(before.left+before.width/2),
    };
  });
  // Press it and measure while held.
  const held=await page.evaluate(async()=>{
    const pill=document.getElementById('chat-jump-latest');
    const b=pill.getBoundingClientRect();
    pill.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
    await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    return {left:Math.round(b.left)};
  });
  const active=await page.evaluate(()=>{
    // :active needs a real press; emulate by forcing the same declarations.
    const pill=document.getElementById('chat-jump-latest');
    pill.style.translate='0 1px'; pill.style.scale='0.985';
    const b=pill.getBoundingClientRect();
    const cs=getComputedStyle(pill);
    return {left:Math.round(b.left), mid:Math.round(b.left+b.width/2), transform:cs.transform};
  });
  console.log(JSON.stringify({rest:r, pressed:active, drift:active.mid-r.pillMid}, null, 1));
  await browser.close();
})();
