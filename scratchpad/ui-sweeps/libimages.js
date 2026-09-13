// The Library's image cards (INBOX 56). Gives the seeded images a long
// description, a vision reading and a Tesseract reading, then measures one
// card: its height, how many distinct font sizes are inside it, how many
// chips, and any text clipped by its own box.
const {boot}=require('./lib.js');
const W=Number(process.env.W||1440), H=Number(process.env.H||900);
const LONG='A wide shot of a desk at dusk with two monitors, a notebook open at a page of pencil diagrams, a cold cup of coffee and a cable running off the left edge of the frame towards a lamp that is not in shot. The light is coming from the window behind the desk.';
const OCR='Weekly review\nShipped the sweep tooling\nNext: component consistency by count\nThen the skills reform\nPage 1 of 2';
(async()=>{
  const {browser,page}=await boot({viewport:{width:W,height:H}});
  const errs=[]; page.on('pageerror',e=>errs.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errs.push(m.text().slice(0,140));});
  if(process.env.SEED){
    const seeded=await page.evaluate(async([long,ocr])=>{
      const rows=await apiJson('/media').catch(()=>[]);
      const list=Array.isArray(rows)?rows:(rows.items||[]);
      const out=[];
      for(const row of list.slice(0,2)){
        for(const [kind,body] of [['caption',{text:long}],['vision-ocr',{text:ocr}],['ocr',{text:ocr}]]){
          try{ await apiJson(`/media/${row.id}/${kind}`,{method:'POST',body:JSON.stringify(body)}); out.push(`${row.id}:${kind}`);}
          catch(e){ out.push(`${row.id}:${kind}:${String(e).slice(0,60)}`);}
        }
      }
      return out;
    },[LONG,OCR]);
    console.log('seeded', JSON.stringify(seeded));
  }
  await page.evaluate(()=>switchTab('library'));
  await page.waitForTimeout(1200);
  await page.evaluate(()=>{document.querySelector('#library-subtabs [data-media-kind="images"]')?.click();});
  await page.waitForTimeout(1500);
  const m=await page.evaluate(()=>{
    const tiles=[...document.querySelectorAll('.library-image-tile')].filter(t=>t.offsetParent!==null);
    if(!tiles.length) return {tiles:0};
    const measure=(t)=>{
      const r=t.getBoundingClientRect();
      const kids=[...t.querySelectorAll('*')].filter(el=>el.offsetParent!==null);
      // Only elements with text of their OWN: counting wrappers counts the
      // font size of everything they contain, which is not a rank.
      const own=(el)=>[...el.childNodes].some(n=>n.nodeType===3 && n.textContent.trim());
      const sizes=[...new Set(kids.filter(own).map(el=>getComputedStyle(el).fontSize))].sort();
      const clipped=kids.filter(el=>el.scrollWidth>el.clientWidth+1 && getComputedStyle(el).textOverflow!=='ellipsis' && el.tagName!=='TEXTAREA' && el.tagName!=='INPUT')
        .map(el=>[String(el.className)||el.tagName, el.scrollWidth, el.clientWidth]);
      const overflowY=kids.filter(el=>el.scrollHeight>el.clientHeight+1 && !String(el.className).includes('clamp') && el.tagName!=='TEXTAREA')
        .map(el=>[String(el.className)||el.tagName, el.scrollHeight, el.clientHeight]);
      return {
        h:+r.height.toFixed(1), w:+r.width.toFixed(1), fontSizes:sizes,
        chips:t.querySelectorAll('.chip').length,
        headings:[...t.querySelectorAll('h4, .library-image-field-label, summary')].map(e=>e.textContent.trim()),
        clipped, overflowY,
      };
    };
    const withText=tiles.find(t=>(t.querySelector('.library-image-caption')?.textContent||'').length>100)||tiles[0];
    return {tiles:tiles.length, first:measure(withText), heights:tiles.map(t=>+t.getBoundingClientRect().height.toFixed(1))};
  });
  console.log(JSON.stringify({w:W, ...m, errors:errs}, null, 1));
  const shot=await page.evaluate(()=>{const t=[...document.querySelectorAll('.library-image-tile')].filter(x=>x.offsetParent!==null);
    const el=t.find(x=>(x.querySelector('.library-image-caption')?.textContent||'').length>100)||t[0];
    if(!el) return null; const r=el.getBoundingClientRect(); return {x:Math.max(0,r.x-6),y:Math.max(0,r.y-6),width:r.width+12,height:Math.min(r.height+12, 2000)};});
  if(shot) await page.screenshot({path:`${process.env.SCRATCH||'.'}/shots/libimage-${W}.png`, clip:shot});
  await browser.close();
})();
