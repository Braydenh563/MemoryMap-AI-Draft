// The 10.4px icon-to-label gap consistency.md item 4 left open. Its container
// gap is 6.4px and its icon margin is 0, so the extra 4px is coming from
// something between them. This dumps the children, including text nodes, which
// is the one thing a computed-style dump cannot show.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.waitForTimeout(800);
  const r=await page.evaluate(()=>{
    const out=[];
    for(const el of document.querySelectorAll('#space-switcher-btn, .space-sw, .chip.when, .chip.map-chip')){
      if(!(el.checkVisibility&&el.checkVisibility())) continue;
      const c=getComputedStyle(el);
      const nodes=[...el.childNodes].map(n=>{
        if(n.nodeType===3) return `TEXT ${JSON.stringify(n.textContent)}`;
        const cs=getComputedStyle(n);
        const b=n.getBoundingClientRect();
        return `<${n.tagName.toLowerCase()}.${String(n.className).trim().split(/\s+/).join('.')||'-'}> x=${b.left.toFixed(1)} w=${b.width.toFixed(1)} mr=${cs.marginRight} ml=${cs.marginLeft} pad=${cs.padding} display=${cs.display}`;
      });
      out.push({sel:`${el.tagName.toLowerCase()}${el.id?'#'+el.id:''}.${[...el.classList].join('.')}`, gap:c.gap, display:c.display, pad:c.padding, nodes});
    }
    return out;
  });
  for(const x of r){ console.log(`== ${x.sel} gap=${x.gap} display=${x.display} pad=${x.pad}`); x.nodes.forEach(n=>console.log('   '+n)); }
  await browser.close();
})();
