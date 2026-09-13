// The keyboard pass docks.md section 1 asks for, and the baseline the decision
// about roving tabindex has to be made against.
//
// For each dock: focus the element before it, press Tab, and record which
// element takes focus and how many Tab presses it takes to leave the dock.
// Also reports whether the dock contains a text input, because that is the
// fact that decides the question: arrow keys inside a text field mean "move
// the caret", and a roving toolbar steals them.
const {boot}=require('./lib.js');
const DOCKS=[['notes','notes'],['graph','graph'],['timeline','timeline'],['reminders','reminders'],['library','library'],['chat','chat']];
(async()=>{
  const {browser,page}=await boot();
  console.log('dock            role        stops  first stop                       has a text field  arrow keys move focus');
  for(const [tab,name] of DOCKS){
    await page.click(`[data-tab="${tab}"]`).catch(()=>{}); await page.waitForTimeout(900);
    const info=await page.evaluate((n)=>{
      const dock=document.querySelector(`[data-dock-name="${n}"]`); if(!dock) return null;
      const focusables=[...dock.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),summary,[tabindex]:not([tabindex="-1"])')]
        .filter(e=>e.checkVisibility&&e.checkVisibility());
      return {
        role: dock.getAttribute('role')||'(none)',
        focusables: focusables.length,
        roving: focusables.filter(e=>e.getAttribute('tabindex')==='-1').length,
        textField: focusables.some(e=>e.tagName==='INPUT'&&!['checkbox','radio','button'].includes(e.type)),
      };
    }, name);
    if(!info){ console.log(`  ${name}: not found`); continue; }

    // Put focus just before the dock, then walk in with Tab.
    await page.evaluate((n)=>{
      const dock=document.querySelector(`[data-dock-name="${n}"]`);
      const before=document.createElement('button');
      before.id='__keys_anchor'; before.textContent='anchor';
      before.style.position='fixed'; before.style.left='-9999px';
      dock.parentElement.insertBefore(before, dock);
      before.focus();
    }, name);
    let stops=0, firstStop='(none)';
    for(let i=0;i<40;i++){
      await page.keyboard.press('Tab');
      const where=await page.evaluate((n)=>{
        const dock=document.querySelector(`[data-dock-name="${n}"]`);
        const a=document.activeElement;
        return {inside: !!(a&&dock.contains(a)), id:(a&&(a.id||a.getAttribute('aria-label')||a.textContent.trim().slice(0,22)))||'body'};
      }, name);
      if(where.inside){ if(!stops) firstStop=where.id; stops++; }
      else if(stops) break;
      else if(i>6) break;
    }
    // Do the arrow keys do anything, from the first control in the dock?
    const arrows=await page.evaluate((n)=>{
      const dock=document.querySelector(`[data-dock-name="${n}"]`);
      const first=[...dock.querySelectorAll('button:not([disabled]),summary')].find(e=>e.checkVisibility&&e.checkVisibility());
      if(!first) return 'no control';
      first.focus(); const was=document.activeElement;
      first.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
      return document.activeElement===was ? 'no' : 'yes';
    }, name);
    await page.evaluate(()=>document.getElementById('__keys_anchor')?.remove());
    console.log(`  ${name.padEnd(14)}${String(info.role).padEnd(12)}${String(stops).padEnd(7)}${String(firstStop).slice(0,32).padEnd(33)}${String(info.textField).padEnd(18)}${arrows}`);
  }
  await browser.close();
})();
