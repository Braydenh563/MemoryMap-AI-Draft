const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const r=await page.evaluate(()=>{
    const tab=document.getElementById('tab-documents');
    tab.classList.remove('hidden'); tab.style.display='flex';
    const mk=(host,label)=>{
      const d=document.createElement('dialog');
      d.className='card space-dialog';
      d.textContent='probe';
      host.appendChild(d);
      d.showModal();
      const cs=getComputedStyle(d); const b=d.getBoundingClientRect();
      const out={label, margin:cs.margin, left:Math.round(b.left), w:Math.round(b.width),
        centred:Math.abs((b.left+b.width/2)-window.innerWidth/2)<=2};
      d.close(); d.remove();
      return out;
    };
    const real=document.getElementById('doc-ai-history-dialog');
    const parent=real.parentElement;
    const res=[mk(document.body,'body'), mk(tab,'#tab-documents'), mk(parent,'real parent: '+(parent.id||parent.className))];
    // and the real one, with its extra class removed
    real.classList.remove('doc-ai-history-dialog');
    real.showModal();
    const b=real.getBoundingClientRect();
    res.push({label:'real minus .doc-ai-history-dialog', margin:getComputedStyle(real).margin,
      left:Math.round(b.left), w:Math.round(b.width), centred:Math.abs((b.left+b.width/2)-window.innerWidth/2)<=2});
    real.close(); real.classList.add('doc-ai-history-dialog');
    return res;
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
