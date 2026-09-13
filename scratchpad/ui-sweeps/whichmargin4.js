const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const r=await page.evaluate(()=>{
    const tab=document.getElementById('tab-documents');
    tab.classList.remove('hidden'); tab.style.display='flex';
    const d=document.createElement('dialog');
    d.className='card space-dialog'; d.textContent='probe';
    tab.appendChild(d); d.showModal();
    const cs=getComputedStyle(d);
    const before={position:cs.position, width:cs.width, inset:cs.inset, display:cs.display,
                  flexBasis:cs.flexBasis, alignSelf:cs.alignSelf, margin:cs.margin};
    d.style.position='fixed'; d.style.inset='0';
    const cs2=getComputedStyle(d); const b=d.getBoundingClientRect();
    const after={position:cs2.position, margin:cs2.margin, left:Math.round(b.left),
      w:Math.round(b.width), centred:Math.abs((b.left+b.width/2)-window.innerWidth/2)<=2};
    d.close(); d.remove();
    return {before, after, tabDisplay:getComputedStyle(tab).display};
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
