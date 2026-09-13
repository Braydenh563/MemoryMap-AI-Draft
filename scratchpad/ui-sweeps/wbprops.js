// The properties panel with a single shape selected, which is the state that
// shows the most rows at once: does the panel scroll inside itself rather
// than spilling past its own box (INBOX 64), and does anything overlap.
const {boot}=require('./lib.js');
const W=Number(process.env.W||1440), H=Number(process.env.H||900);
(async()=>{
  const {browser,page}=await boot({viewport:{width:W,height:H}});
  const errs=[]; page.on('pageerror',e=>errs.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errs.push(m.text().slice(0,140));});
  const id=await page.evaluate(async()=>{
    const r=await api('/whiteboard/boards',{method:'POST',body:JSON.stringify({name:'Props sweep'})});
    return (await r.json()).id;
  });
  await page.evaluate((b)=>openWhiteboardBoard(b), id);
  await page.waitForTimeout(2000);
  // A drawing tool active AND a text card selected: every group the panel has
  // is on screen at once, which is the tallest it ever gets.
  const state=await page.evaluate(async()=>{
    await wbCreateSticky(320, 300);
    document.activeElement?.blur();
    return {objects:(wbState.objects||[]).length};
  });
  await page.waitForTimeout(1000);
  await page.evaluate(()=>{
    const first=(wbState.objects||[])[0];
    if(first){ wbSelectedItem={kind:'object', id:first.id}; }
    if (typeof wbSelectToolRef==='function') wbSelectToolRef('draw');
    wbUpdatePropertiesPanel();
  });
  await page.waitForTimeout(600);
  const m=await page.evaluate(()=>{
    const p=document.getElementById('wb-properties-panel');
    const r=p.getBoundingClientRect();
    const c=getComputedStyle(p);
    // The native <select> an enhanced select parks behind its own opener is
    // not a second control on the panel: counted, it reports every enhanced
    // select as overlapping something forever (the trap wbtopbar.js records).
    const ctrls=[...p.querySelectorAll('button, input, select, summary')]
      .filter(e=>e.checkVisibility&&e.checkVisibility())
      .filter(e=>!(e.tagName==='SELECT' && e.parentElement?.querySelector('.select-opener')));
    // Horizontal only: the panel scrolls on purpose, so a control below the
    // fold is the design, and a control past the left or right edge is the
    // clip INBOX 64 is about.
    const outside=ctrls.filter(e=>{const b=e.getBoundingClientRect(); return b.right>r.right+0.5||b.left<r.left-0.5;}).map(e=>e.id||String(e.className));
    const overlaps=[];
    for(let i=0;i<ctrls.length;i++) for(let j=i+1;j<ctrls.length;j++){
      const a=ctrls[i].getBoundingClientRect(), b=ctrls[j].getBoundingClientRect();
      if(ctrls[i].contains(ctrls[j])||ctrls[j].contains(ctrls[i])) continue;
      if(a.right>b.left+0.5 && b.right>a.left+0.5 && a.bottom>b.top+0.5 && b.bottom>a.top+0.5)
        overlaps.push([ctrls[i].id||String(ctrls[i].className), ctrls[j].id||String(ctrls[j].className)]);
    }
    return {hidden:p.classList.contains('hidden'), h:+r.height.toFixed(1), w:+r.width.toFixed(1),
      overflowY:c.overflowY, sh:p.scrollHeight, ch:p.clientHeight, scrolls:p.scrollHeight>p.clientHeight,
      controls:ctrls.length, outside, overlaps,
      headings:[...p.querySelectorAll('.wb-properties-group-label, .wb-properties-title')].map(e=>e.textContent.trim())};
  });
  console.log(JSON.stringify({w:W, ...state, ...m, errors:errs}, null, 1));
  const clip=await page.evaluate(()=>{const p=document.getElementById('wb-properties-panel').getBoundingClientRect();
    return {x:Math.max(0,p.x-8),y:Math.max(0,p.y-8),width:p.width+16,height:Math.min(p.height+16,1200)};});
  await page.screenshot({path:`${process.env.SCRATCH||'.'}/shots/wbpropsfull-${W}.png`, clip});
  await browser.close();
})();
