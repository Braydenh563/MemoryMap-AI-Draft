// The two controls that moved into an overflow menu for the seven-control
// ceiling, driven rather than inspected. A control that moved and stopped
// working is CLAUDE.md's failure shape 2 ("a feature that never ran once"),
// and the only thing that rules it out is clicking it.
//
//   Select  -> #notes-more-menu : must open the batch bar, mark itself active,
//              and be returned to its resting state by #batch-cancel.
//   Trace   -> #graph-view-menu : must set aria-expanded and .is-on.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const openMenu=async(id)=>{ await page.evaluate((i)=>{const d=document.getElementById(i); if(d&&d.tagName==='DETAILS') d.open=true;}, id); await page.waitForTimeout(300); };

  await page.click('[data-tab="notes"]'); await page.waitForTimeout(1000);
  const before=await page.evaluate(()=>({
    dockControls: [...document.querySelector('[data-dock-name="notes"]').querySelectorAll('button, input, select, .seg, .select-shell > .select-opener, summary')].filter(e=>e.checkVisibility&&e.checkVisibility()&&!e.closest('.action-menu, .doc-dock-menu-list')&&!(e.parentElement&&e.parentElement.classList.contains('seg'))&&!e.classList.contains('select-native-hidden')&&!e.classList.contains('dock-native-hidden')).length,
    selectInMenu: !!document.querySelector('#notes-more-menu #select-btn'),
    batchVisible: !document.getElementById('batch-bar').classList.contains('hidden'),
  }));
  console.log('notes dock controls:', before.dockControls, '| Select lives in the menu:', before.selectInMenu, '| batch bar shown:', before.batchVisible);

  await openMenu('notes-more-menu');
  await page.click('#select-btn'); await page.waitForTimeout(600);
  const after=await page.evaluate(()=>({
    batchVisible: !document.getElementById('batch-bar').classList.contains('hidden'),
    active: document.getElementById('select-btn').classList.contains('active'),
    bg: (()=>{const d=document.getElementById('notes-more-menu'); if(d) d.open=true; return getComputedStyle(document.getElementById('select-btn')).backgroundColor;})(),
    menuClosed: !document.getElementById('notes-more-menu').open,
  }));
  console.log('after clicking Select: batch bar shown =', after.batchVisible, '| .active =', after.active, '| its fill while active =', after.bg);

  await page.evaluate(()=>{const d=document.getElementById('notes-more-menu'); if(d) d.open=false;});
  await page.click('#batch-cancel'); await page.waitForTimeout(600);
  const done=await page.evaluate(()=>({
    batchVisible: !document.getElementById('batch-bar').classList.contains('hidden'),
    active: document.getElementById('select-btn').classList.contains('active'),
  }));
  console.log('after Done: batch bar shown =', done.batchVisible, '| .active =', done.active);

  await page.click('[data-tab="graph"]'); await page.waitForTimeout(1400);
  const g0=await page.evaluate(()=>({
    dockControls: [...document.querySelector('[data-dock-name="graph"]').querySelectorAll('button, input, select, .seg, .select-shell > .select-opener, summary')].filter(e=>e.checkVisibility&&e.checkVisibility()&&!e.closest('.action-menu, .doc-dock-menu-list')&&!(e.parentElement&&e.parentElement.classList.contains('seg'))&&!e.classList.contains('select-native-hidden')&&!e.classList.contains('dock-native-hidden')).length,
    traceInMenu: !!document.querySelector('#graph-view-menu #graph-trace-toggle'),
  }));
  console.log('graph dock controls:', g0.dockControls, '(including #graph-concept-maps, the identity-zone link) | Trace lives in the menu:', g0.traceInMenu);
  await openMenu('graph-view-menu');
  await page.click('#graph-trace-toggle'); await page.waitForTimeout(700);
  const g1=await page.evaluate(()=>{
    const d=document.getElementById('graph-view-menu'); if(d) d.open=true;
    const t=document.getElementById('graph-trace-toggle');
    return {expanded:t.getAttribute('aria-expanded'), isOn:t.classList.contains('is-on'), bg:getComputedStyle(t).backgroundColor};
  });
  console.log('after clicking Trace: aria-expanded =', g1.expanded, '| .is-on =', g1.isOn, '| its fill while on =', g1.bg);
  await browser.close();
})();
