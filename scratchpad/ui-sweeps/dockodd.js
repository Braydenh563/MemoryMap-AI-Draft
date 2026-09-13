// Name the outliers docksurface.js counts: which control in each dock is not
// on the row's height, and which fill the dark theme draws that the light one
// does not.
const {boot}=require('./lib.js');
const DOCKS=(process.env.DOCKS? JSON.parse(process.env.DOCKS) : [['notes','notes'],['graph','graph'],['timeline','timeline'],['reminders','reminders'],['library','library']]);
(async()=>{
  const {browser,page}=await boot();
  console.log('== theme', process.env.THEME||'light');
  for(const [tab,name] of DOCKS){
    await page.click(`[data-tab="${tab}"]`).catch(()=>{}); await page.waitForTimeout(900);
    await page.mouse.move(1430,890); await page.waitForTimeout(150);
    const r=await page.evaluate((n)=>{
      const dock=document.querySelector(`[data-dock-name="${n}"]`); if(!dock) return null;
      const kids=[...dock.querySelectorAll('button, input, select, .seg, .select-shell > .select-opener, summary')].filter(e=>e.checkVisibility&&e.checkVisibility()&&!e.closest('.action-menu, .doc-dock-menu-list'));
      const nonTransparent=(c)=>{const m=c.match(/rgba?\(([^)]+)\)/);if(!m)return true;const p=m[1].split(/[\s,\/]+/).map(Number);return (p.length<4?1:p[3])>0.01;};
      const sig=(e)=>`${e.tagName.toLowerCase()}${e.id?'#'+e.id:''}.${[...e.classList].slice(0,3).join('.')}${e.id?'':'["'+(e.getAttribute('aria-label')||e.title||e.textContent.trim().slice(0,16))+'"]'}`;
      const heights={}; const fills={};
      for(const e of kids){
        const h=+e.getBoundingClientRect().height.toFixed(1);
        (heights[h]=heights[h]||[]).push(sig(e));
        const bg=getComputedStyle(e).backgroundColor;
        if(nonTransparent(bg)) (fills[bg]=fills[bg]||[]).push(sig(e));
      }
      return {heights, fills};
    }, name);
    if(!r) continue;
    console.log(`  ${name}`);
    for(const [h,list] of Object.entries(r.heights)) console.log(`    h=${h}: ${list.join(' ')}`);
    for(const [f,list] of Object.entries(r.fills)) console.log(`    fill ${f}: ${list.join(' ')}`);
  }
  await browser.close();
})();
