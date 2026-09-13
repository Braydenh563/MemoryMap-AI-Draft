// The five docks as surfaces: how many distinct fills, radii, borders and
// control heights each one draws. This is the table in
// docs/roadmap/agent-remaining/consistency.md section 3, which was light theme
// at 1440 only; `THEME=dark` on the same script is the check it asked for.
// W=1024 for the wrap check, which also reports whether a zone other than
// `.dock-actions` wrapped first (a stray leading hairline at the second row's
// left edge, the failure `shot-docks.js` calls strayHairline).
const {boot}=require('./lib.js');
const DOCKS=[['notes','notes'],['graph','graph'],['timeline','timeline'],['reminders','reminders'],['library','library']];
(async()=>{
  const W=Number(process.env.W||1440);
  const {browser,page}=await boot({viewport:{width:W,height:900}});
  console.log(`== theme ${process.env.THEME||'light'} at ${W}`);
  for(const [tab,name] of DOCKS){
    await page.click(`[data-tab="${tab}"]`).catch(()=>{}); await page.waitForTimeout(900);
    await page.mouse.move(W-10,890); await page.waitForTimeout(150);
    const r=await page.evaluate((n)=>{
      const dock=document.querySelector(`[data-dock-name="${n}"]`)||document.querySelector('.dock');
      if(!dock) return null;
      const cs=getComputedStyle(dock);
      // Counted the way the grammar counts (docks.md section 2): a segmented
      // control is ONE control, not its track plus its items, and the native
      // `<select>` an enhanced select hides behind its opener is not a control
      // on the bar at all. Counting the items instead reports every dock with
      // a segment as having two heights (36 and 28) and the Timeline as having
      // three (it adds the 2px visually-hidden native select), which is a fact
      // about the counter, not about the bar.
      const kids=[...dock.querySelectorAll('button, input, select, .seg, .select-shell > .select-opener, summary')].filter(e=>
        e.checkVisibility&&e.checkVisibility()
        &&!e.closest('.action-menu, .doc-dock-menu-list')
        &&!(e.parentElement&&e.parentElement.classList.contains('seg'))
        &&!e.classList.contains('select-native-hidden')
        &&!e.classList.contains('dock-native-hidden'));
      const val=(e,p)=>getComputedStyle(e)[p];
      const nonTransparent=(c)=>{const m=c.match(/rgba?\(([^)]+)\)/);if(!m)return true;const p=m[1].split(/[\s,\/]+/).map(Number);return (p.length<4?1:p[3])>0.01;};
      const b=dock.getBoundingClientRect();
      // A zone that wrapped: any direct child whose top is more than 4px below
      // the first child's top.
      const zones=[...dock.children].filter(e=>e.getBoundingClientRect().height>0);
      const firstTop=zones.length?zones[0].getBoundingClientRect().top:0;
      const wrapped=zones.filter(e=>e.getBoundingClientRect().top>firstTop+4);
      const strayHairline=wrapped.length? !wrapped[0].classList.contains('dock-actions') : false;
      return {
        bar:`bg=${cs.backgroundColor} border=${cs.borderTopWidth} ${cs.borderTopColor} radius=${cs.borderTopLeftRadius} pad=${cs.paddingTop}/${cs.paddingLeft} h=${b.height.toFixed(0)}`,
        controls: kids.length,
        fills: [...new Set(kids.map(e=>val(e,'backgroundColor')).filter(nonTransparent))].length + 1,
        radii: [...new Set(kids.map(e=>val(e,'borderTopLeftRadius')))].length,
        borders: [...new Set(kids.map(e=>val(e,'borderTopWidth')+' '+val(e,'borderTopStyle')))].length,
        heights: [...new Set(kids.map(e=>+e.getBoundingClientRect().height.toFixed(1)))].sort((a,b)=>a-b),
        overflow: dock.scrollWidth>dock.clientWidth+1 ? `${dock.scrollWidth}>${dock.clientWidth}` : 'none',
        wrappedZones: wrapped.map(e=>'.'+[...e.classList].slice(0,2).join('.')),
        strayHairline,
      };
    }, name);
    if(!r){ console.log(`  ${name}: dock not found`); continue; }
    console.log(`  ${name}: fills=${r.fills} radii=${r.radii} borders=${r.borders} heights=${JSON.stringify(r.heights)} controls=${r.controls} overflow=${r.overflow} wrapped=${JSON.stringify(r.wrappedZones)} stray=${r.strayHairline}`);
    console.log(`      bar ${r.bar}`);
  }
  await browser.close();
})();
