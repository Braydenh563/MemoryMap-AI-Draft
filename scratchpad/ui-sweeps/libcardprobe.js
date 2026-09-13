// One measurement of the image card's disclosure and its clamped
// description: what the summary is actually painting, and whether the clamp
// cuts between lines or through one.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot({viewport:{width:1440,height:900}});
  await page.evaluate(()=>switchTab('library'));
  await page.waitForTimeout(1000);
  await page.evaluate(()=>{document.querySelector('#library-subtabs [data-media-kind="images"]')?.click();});
  await page.waitForTimeout(1500);
  const out=await page.evaluate(()=>{
    const s=document.querySelector('.library-image-reading > summary');
    const cs=s?getComputedStyle(s):null;
    const cap=document.querySelector('.library-image-caption');
    const cc=getComputedStyle(cap);
    return {
      summary:s?{bg:cs.backgroundColor, border:cs.borderTopWidth+' '+cs.borderTopColor,
        radius:cs.borderRadius, fs:cs.fontSize, h:+s.getBoundingClientRect().height.toFixed(1)}:null,
      caption:{h:+cap.getBoundingClientRect().height.toFixed(1), sh:cap.scrollHeight,
        lh:cc.lineHeight, pb:cc.paddingBottom, clamp:cc.getPropertyValue('-webkit-line-clamp'),
        clamped:cap.className},
    };
  });
  console.log(JSON.stringify(out,null,1));
  await browser.close();
})();
