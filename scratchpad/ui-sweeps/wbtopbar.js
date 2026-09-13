// The whiteboard top bar's controls, and the OCR workspace head. Both are
// named in consistency.md section 3 as bars whose SURFACE is settled but whose
// controls are not quiet. The surface itself is deliberately not the dock's:
// it floats over the canvas, so DESIGN.md's floating-surface rule makes
// `--modal-bg` with `--glass-border` correct there. Only the controls are the
// question, so only the controls are measured.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const id=await page.evaluate(async()=>{const r=await api('/whiteboard/boards',{method:'POST',body:JSON.stringify({name:'Topbar sweep'})});return (await r.json()).id;});
  await page.evaluate((b)=>openWhiteboardBoard(b), id); await page.waitForTimeout(1600);
  await page.mouse.move(1430,890); await page.waitForTimeout(250);
  const probe=async(label,sel)=>{
    const r=await page.evaluate((s)=>{
      const bar=document.querySelector(s); if(!bar) return null;
      const c=getComputedStyle(bar);
      const btns=[...bar.querySelectorAll('button, summary, select, input')].filter(e=>e.checkVisibility&&e.checkVisibility()&&!e.closest('.wb-board-menu, .action-menu, .doc-dock-menu-list')
        // The visually hidden native `<select>` an enhanced select parks
        // behind its opener is not a control on the bar: counted, it reports
        // the strip as having two heights (36 and its own 32) forever.
        && !e.classList.contains('select-native-hidden') && !e.classList.contains('dock-native-hidden'));
      const nonTransparent=(x)=>{const m=x.match(/rgba?\(([^)]+)\)/);if(!m)return true;const p=m[1].split(/[\s,\/]+/).map(Number);return (p.length<4?1:p[3])>0.01;};
      const filled=btns.filter(e=>nonTransparent(getComputedStyle(e).backgroundColor));
      return {
        surface:`bg=${c.backgroundColor} border=${c.borderTopWidth} radius=${c.borderTopLeftRadius}`,
        controls:btns.length,
        filled:filled.length,
        filledNames:filled.slice(0,8).map(e=>`${e.id||e.getAttribute('aria-label')||e.textContent.trim().slice(0,12)}:${getComputedStyle(e).backgroundColor}`),
        heights:[...new Set(btns.map(e=>+e.getBoundingClientRect().height.toFixed(1)))].sort((a,b)=>a-b),
        radii:[...new Set(btns.map(e=>getComputedStyle(e).borderTopLeftRadius))],
        offHeight: btns.filter(e=>Math.abs(e.getBoundingClientRect().height-36)>1).map(e=>`${e.tagName.toLowerCase()}${e.id?'#'+e.id:''}.${[...e.classList].join('.')||'-'} h=${e.getBoundingClientRect().height.toFixed(1)}`),
      };
    }, sel);
    if(!r){ console.log(`  ${label}: not found`); return; }
    console.log(`  ${label}: controls=${r.controls} filled=${r.filled} heights=${JSON.stringify(r.heights)} radii=${JSON.stringify(r.radii)}`);
    console.log(`      surface ${r.surface}`);
    if(r.filledNames.length) console.log('      filled: '+r.filledNames.join('  '));
    if(r.offHeight&&r.offHeight.length) console.log('      not on 36px: '+r.offHeight.join(' , '));
  };
  console.log('== theme', process.env.THEME||'light');
  await probe('wb-topbar','#wb-topbar, .wb-topbar');
  await page.click('[data-tab="library"]').catch(()=>{}); await page.waitForTimeout(700);
  await page.click('[data-target="library-view-files"]',{timeout:4000}).catch(()=>{}); await page.waitForTimeout(1200);
  await probe('ocr head','.ocr-toolbar, .ocr-head');
  await browser.close();
})();
