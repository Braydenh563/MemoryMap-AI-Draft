// The head rows consistency.md section 3 listed as "named in the brief but NOT
// on the recipe", measured against `.dock`'s own surface so the gap is a number
// rather than an impression. The reference row is printed first.
const {boot}=require('./lib.js');
const SURFACES=[
  ['notes (the reference)','notes',null,'[data-dock-name="notes"]'],
  ['chat','chat',null,'[data-dock-name="chat"]'],
  ['graph','graph',null,'[data-dock-name="graph"]'],
  ['timeline','timeline',null,'[data-dock-name="timeline"]'],
  ['reminders','reminders',null,'[data-dock-name="reminders"]'],
  ['library','library',null,'[data-dock-name="library"]'],
  ['library-docs','library','[data-target="library-view-docs"]','[data-dock-name="library-docs"]'],
  ['library-boards','library','[data-target="library-view-whiteboard"]','[data-dock-name="library-boards"]'],
  ['library-media','library','[data-target="library-view-media"]','[data-dock-name="library-media"]'],
  ['library-links','library','[data-target="library-view-links"]','[data-dock-name="library-links"]'],
  ['library-contents','library','[data-target="library-view-contents"]','[data-dock-name="library-contents"]'],
  ['library-skills','library','[data-target="library-view-skills"]','[data-dock-name="library-skills"]'],
  ['dashboard toolbar','dashboard',null,'.dash-toolbar'],
];

(async()=>{
  const {browser,page}=await boot();
  console.log('== theme', process.env.THEME||'light');
  for(const [label,tab,sub,sel] of SURFACES){
    await page.click(`[data-tab="${tab}"]`).catch(()=>{}); await page.waitForTimeout(800);
    if(sub){ await page.click(sub,{timeout:4000}).catch(()=>{}); await page.waitForTimeout(1100); }
    await page.mouse.move(1430,890); await page.waitForTimeout(150);
    const r=await page.evaluate((s)=>{
      const el=[...document.querySelectorAll(s)].find(e=>e.checkVisibility&&e.checkVisibility()&&e.getBoundingClientRect().height>0);
      if(!el) return null;
      const c=getComputedStyle(el);
      const kids=[...el.querySelectorAll('button, input, select, .seg, .select-shell > .select-opener, summary')].filter(e=>
        e.checkVisibility&&e.checkVisibility()
        &&!e.closest('.action-menu, .doc-dock-menu-list')
        &&!(e.parentElement&&e.parentElement.classList.contains('seg'))
        &&!e.classList.contains('select-native-hidden')
        &&!e.classList.contains('dock-native-hidden'));
      const nonTransparent=(x)=>{const m=x.match(/rgba?\(([^)]+)\)/);if(!m)return true;const p=m[1].split(/[\s,\/]+/).map(Number);return (p.length<4?1:p[3])>0.01;};
      const filled=kids.filter(e=>{const b=getComputedStyle(e);return nonTransparent(b.backgroundColor)&&!e.matches('input,select,.select-opener,.seg');});
      return {
        surface:`bg=${nonTransparent(c.backgroundColor)?c.backgroundColor:'transparent'} border=${c.borderTopWidth} radius=${c.borderTopLeftRadius} pad=${c.paddingTop}/${c.paddingLeft} h=${el.getBoundingClientRect().height.toFixed(0)}`,
        controls:kids.length,
        heights:[...new Set(kids.map(e=>+e.getBoundingClientRect().height.toFixed(1)))].sort((a,b)=>a-b),
        radii:[...new Set(kids.map(e=>getComputedStyle(e).borderTopLeftRadius))].length,
        filledPrimaries:filled.map(e=>e.id||e.textContent.trim().slice(0,14)),
      };
    }, sel);
    if(!r){ console.log(`  ${label}: not found`); continue; }
    console.log(`  ${label}: controls=${r.controls} heights=${JSON.stringify(r.heights)} radii=${r.radii} primaries=${r.filledPrimaries.length}${r.filledPrimaries.length?' ['+r.filledPrimaries.join(',')+']':''}`);
    console.log(`      ${r.surface}`);
  }
  await browser.close();
})();
