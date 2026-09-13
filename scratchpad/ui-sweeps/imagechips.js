// consistency.md item 7's unfinished half: the Library image cards' chips,
// measured on a notebook that actually has images (seed-images.js first).
// The reference is the persona the skill cards were brought onto: `--chip-bg`,
// no border, pill radius, 1.6/9.6 padding, 12px, `--muted`.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.click('[data-tab="library"]'); await page.waitForTimeout(900);
  const ok=await page.click('[role="tab"][data-target="library-view-media"], #library-subtabs [data-target="library-view-media"]',{timeout:4000}).then(()=>true).catch(()=>false);
  console.log('images sub-tab:', ok);
  await page.waitForTimeout(1600);
  await page.mouse.move(1430,890); await page.waitForTimeout(200);
  const r=await page.evaluate(()=>{
    const cards=[...document.querySelectorAll('.library-image-card, .library-image-tile')].filter(e=>e.checkVisibility&&e.checkVisibility());
    // Every piece of meta on the card, not only the ones already carrying a
    // chip class: the item's claim is that meta looks like meta, and a fact
    // drawn as a button is exactly what that rules out.
    const chips=[...document.querySelectorAll('.library-image-card *, .library-image-tile *')].filter(e=>{
      if(!(e.checkVisibility&&e.checkVisibility())) return false;
      if(e.querySelector('*')) return false;
      const t=e.textContent.trim(); if(!t) return false;
      return /chip|badge|tag|meta|usage|model|muted|status|count|size|name/i.test(e.className||'');
    });
    const sig=(e)=>{const c=getComputedStyle(e);return {
      cls:[...e.classList].join('.'),
      h:+e.getBoundingClientRect().height.toFixed(2),
      bg:c.backgroundColor, border:c.borderTopWidth+' '+c.borderTopStyle,
      radius:c.borderTopLeftRadius, pad:c.paddingTop+'/'+c.paddingLeft,
      fs:c.fontSize, color:c.color, weight:c.fontWeight, shadow:c.boxShadow==='none'?'none':'shadow',
      clipped:e.scrollHeight>e.clientHeight+1,
    };};
    return {cards:cards.length, chips:chips.map(sig)};
  });
  console.log('cards', r.cards, 'chips', r.chips.length);
  const key=(c)=>[c.bg,c.border,c.radius,c.pad,c.fs,c.color,c.weight,c.shadow].join(' | ');
  const groups=new Map();
  for(const c of r.chips){ const k=key(c); if(!groups.has(k)) groups.set(k,[]); groups.get(k).push(c); }
  console.log('distinct chip recipes:', groups.size);
  for(const [k,v] of groups) console.log(`  x${v.length} [${[...new Set(v.map(c=>c.cls))].join(' , ')}] h=${[...new Set(v.map(c=>c.h))].join(',')} clipped=${v.filter(c=>c.clipped).length}\n      ${k}`);
  await browser.close();
})();
