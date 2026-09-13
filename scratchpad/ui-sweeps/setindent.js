// The Settings headings' left edges. docks.md section 6 measured two of them,
// 529px and 546px, and traced the 17px to `.settings-group`'s own padding: a
// heading that heads a group starts at the group's content edge, one that heads
// a section starts at the section's. This prints every heading with its edge
// and which of the two it is, so the fix can be aimed rather than guessed.
const {boot}=require('./lib.js');
const SECTIONS=['account','appearance','preferences','models','tools','skills','personas','templates','websearch','memory','tasks','data','logs','shortcuts','extras','help','about'];
(async()=>{
  const {browser,page}=await boot();
  await page.click('#settings-btn'); await page.waitForTimeout(700);
  const edges={};
  for(const s of SECTIONS){
    const ok=await page.click(`#settings-modal [data-section="${s}"]`,{timeout:2500}).then(()=>true).catch(()=>false);
    if(!ok) continue;
    await page.waitForTimeout(350);
    const r=await page.evaluate(()=>{
      const sec=document.querySelector('#settings-modal .settings-section:not(.hidden)');
      if(!sec) return [];
      return [...sec.querySelectorAll('h2, h3')].filter(e=>e.checkVisibility&&e.checkVisibility()).map(e=>({
        text:e.textContent.trim().slice(0,28),
        // The CONTENT edge, not the border-box edge. The first version of
        // this read `getBoundingClientRect().left`, which does not move when a
        // heading is indented with padding, so a fix that had landed measured
        // as no change at all. What the eye compares is where the glyphs
        // start.
        left:+(()=>{const c=getComputedStyle(e);return e.getBoundingClientRect().left+parseFloat(c.paddingLeft)+parseFloat(c.borderLeftWidth);})().toFixed(1),
        inGroup:!!e.closest('.settings-group'),
        inSummary:!!e.closest('summary'),
        directChild:e.parentElement&&e.parentElement.classList.contains('settings-section'),
        tag:e.tagName.toLowerCase(),
      }));
    });
    for(const h of r){ (edges[h.left]=edges[h.left]||[]).push(`${s}/${h.tag} "${h.text}"${h.inGroup?' [in .settings-group]':''}${h.inSummary?' [in <summary>]':''}${h.directChild?' [direct child of .settings-section]':' [nested]'}`); }
  }
  const keys=Object.keys(edges).map(Number).sort((a,b)=>a-b);
  console.log(`distinct heading left edges: ${keys.length}`);
  for(const k of keys){ console.log(`  ${k}px  x${edges[k].length}`); edges[k].slice(0,4).forEach(t=>console.log('      '+t)); }
  await browser.close();
})();
