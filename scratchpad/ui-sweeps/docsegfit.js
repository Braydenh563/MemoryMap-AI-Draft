// "the documents edit and read toggle options dont fit in the toggle and go
// out of it at the bottom": is the seg's content taller than its buttons, and
// does either button's box escape the well?
const {chromium}=require('/opt/node22/lib/node_modules/playwright');
const PW='testpassword123'; const BASE=process.env.BASE||'http://127.0.0.1:8781';
(async()=>{
  const browser=await chromium.launch();
  for (const width of [1440, 1280, 1024, 820, 390]) {
    const page=await browser.newPage({viewport:{width,height:800}});
    await page.goto(BASE+'/',{waitUntil:'domcontentloaded'});
    await page.waitForSelector('#lock-password',{state:'visible',timeout:20000});
    await page.fill('#lock-password',PW); await page.click('#lock-submit'); await page.waitForTimeout(2200);
    await page.evaluate(()=>document.getElementById('onboarding-overlay')?.remove());
    await page.evaluate(()=>switchTab('documents')); await page.waitForTimeout(800);
    await page.evaluate(()=>document.getElementById('doc-new')?.click()); await page.waitForTimeout(900);
    const r=await page.evaluate(()=>{
      const seg=document.getElementById('doc-view-seg');
      if(!seg) return {noSeg:true};
      const sb=seg.getBoundingClientRect();
      const cs=getComputedStyle(seg);
      const btns=[...seg.querySelectorAll('button')].map(b=>{
        const bb=b.getBoundingClientRect();
        const bs=getComputedStyle(b);
        return {t:b.textContent.trim(), h:Math.round(bb.height), w:Math.round(bb.width),
          scrollH:b.scrollHeight, clientH:b.clientHeight,
          overflowsOwnBox:b.scrollHeight>b.clientHeight+1,
          escapesTop:Math.round(sb.top-bb.top), escapesBottom:Math.round(bb.bottom-sb.bottom),
          lineH:bs.lineHeight, fs:bs.fontSize, pad:bs.padding, whiteSpace:bs.whiteSpace,
          clipped:bb.width+1<b.scrollWidth};
      });
      return {segH:Math.round(sb.height), segPad:cs.padding, segOverflow:cs.overflow,
        segScrollH:seg.scrollHeight, segClientH:seg.clientHeight, btns};
    });
    console.log(width+': '+JSON.stringify(r));
    await page.close();
  }
  await browser.close();
})();
