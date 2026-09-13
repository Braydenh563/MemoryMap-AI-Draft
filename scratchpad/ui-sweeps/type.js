// Phase 3 type: distinct font sizes on controls and labels per tab, and any
// muted text that also carries an opacity (two dimmings stacked).
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  for(const t of ['dashboard','notes','library','chat','graph','timeline','reminders']){
    await page.click(`[data-tab="${t}"]`).catch(()=>{});await page.waitForTimeout(700);
    const r=await page.evaluate(()=>{
      const vis=e=>e.checkVisibility&&e.checkVisibility();
      const sizes={};
      document.querySelectorAll('button, label, input, select, .chip, .setting-label, .library-chip').forEach(e=>{if(!vis(e))return;const fs=getComputedStyle(e).fontSize;const k=`${fs} ${e.tagName.toLowerCase()}`;(sizes[k]=sizes[k]||{n:0,ex:new Set()});sizes[k].n++;if(sizes[k].ex.size<3)sizes[k].ex.add((e.id?'#'+e.id:'')+'.'+[...e.classList].slice(0,2).join('.'));});
      const muted=getComputedStyle(document.documentElement).getPropertyValue('--muted').trim();
      const dim={};
      document.querySelectorAll('body *').forEach(e=>{if(!vis(e))return;const c=getComputedStyle(e);if(parseFloat(c.opacity)<1&&parseFloat(c.opacity)>0&&(e.classList.contains('muted')||c.color===muted)){const k=`${[...e.classList].slice(0,2).join('.')} op=${c.opacity}`;dim[k]=(dim[k]||0)+1;}});
      return {sizes:Object.fromEntries(Object.entries(sizes).map(([k,v])=>[k,{n:v.n,ex:[...v.ex]}])),dim};
    });
    console.log(`== ${t}: ${Object.keys(r.sizes).length} size×tag combos`);
    console.log('  '+Object.entries(r.sizes).sort((a,b)=>b[1].n-a[1].n).map(([k,v])=>`${v.n} ${k} ${v.ex.join(' ')}`).join('\n  '));
    if(Object.keys(r.dim).length) console.log('  muted+opacity: '+JSON.stringify(r.dim));
  }
  await browser.close();
})();
