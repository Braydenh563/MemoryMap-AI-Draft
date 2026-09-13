// Both media sub-tabs in one pass: the Images grid (INBOX 56's cards) and the
// Files rows, which share the same tile builder and must not have been broken
// by the card redesign. Screenshots the grid and reports each tile's height,
// the usage line it drew and any text clipped by its own box.
const {boot}=require('./lib.js');
const W=Number(process.env.W||1440), H=Number(process.env.H||900);
(async()=>{
  const {browser,page}=await boot({viewport:{width:W,height:H}});
  const errs=[]; page.on('pageerror',e=>errs.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errs.push(m.text().slice(0,140));});
  const look=async(kind)=>{
    await page.evaluate((k)=>{document.querySelector(`#library-subtabs [data-media-kind="${k}"]`)?.click();}, kind);
    await page.waitForTimeout(1600);
    const m=await page.evaluate(()=>{
      const tiles=[...document.querySelectorAll('.library-image-tile')].filter(t=>t.offsetParent!==null);
      return tiles.map(t=>{
        const kids=[...t.querySelectorAll('*')].filter(el=>el.offsetParent!==null);
        const clipped=kids.filter(el=>el.scrollWidth>el.clientWidth+1 && getComputedStyle(el).textOverflow!=='ellipsis' && el.tagName!=='TEXTAREA' && el.tagName!=='INPUT')
          .map(el=>[String(el.className), el.scrollWidth, el.clientWidth]);
        return {
          h:+t.getBoundingClientRect().height.toFixed(1),
          name:t.querySelector('figcaption')?.textContent,
          usage:t.querySelector('.library-image-usage')?.textContent.trim().slice(0,60),
          provenance:t.querySelector('.library-image-provenance')?.textContent,
          reading:t.querySelector('.library-image-reading > summary')?.textContent,
          clipped,
        };
      });
    });
    return m;
  };
  await page.evaluate(()=>switchTab('library'));
  await page.waitForTimeout(1200);
  const images=await look('images');
  const grid=await page.evaluate(()=>{const g=document.getElementById('library-images-grid'); const r=g.getBoundingClientRect();
    return {x:r.x-6,y:r.y-6,width:Math.min(r.width+12, 1400),height:Math.min(r.height+12, 1400)};});
  await page.screenshot({path:`${process.env.SCRATCH||'.'}/shots/libgrid-${W}${process.env.THEME==='dark'?'-dark':''}.png`, clip:grid});
  const files=await look('files');
  await page.screenshot({path:`${process.env.SCRATCH||'.'}/shots/libfiles-${W}.png`, clip:{x:0,y:120,width:Math.min(W,1400),height:600}});
  console.log(JSON.stringify({w:W, images, files, errors:errs}, null, 1));
  await browser.close();
})();
