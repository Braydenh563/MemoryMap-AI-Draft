// The graph node panel (GRAPH_PLAN Phase 6, INBOX 59): counts the buttons in
// the action toolbar per row, the panel's own scroll state, and every control
// shorter than the hit-target floor. Run at three widths; the 390 pass is the
// sheet.
const {boot}=require('./lib.js');
const W=Number(process.env.W||1440), H=Number(process.env.H||900);
(async()=>{
  const {browser,page}=await boot({viewport:{width:W,height:H}});
  const errs=[]; page.on('pageerror',e=>errs.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errs.push(m.text().slice(0,140));});
  await page.evaluate(()=>switchTab('graph'));
  await page.waitForTimeout(2500);
  const opened=await page.evaluate(async()=>{
    const list=(typeof allEntries!=='undefined'?allEntries:[]).filter(e=>!e.binned);
    const e=list[0]; if(!e) return 'no notes';
    await openGraphPopup({clientX:300,clientY:200,stopPropagation(){}},{id:e.id,category:e.category});
    return e.id;
  });
  await page.waitForTimeout(1200);
  const m=await page.evaluate(()=>{
    const p=document.getElementById('graph-popup');
    const r=p.getBoundingClientRect();
    const acts=[...p.querySelectorAll('.graph-popup-actions button, .graph-popup-toolbar button')];
    // buttons per row: group by rounded top edge
    const rows={};
    for(const b of acts){const t=Math.round(b.getBoundingClientRect().top); rows[t]=(rows[t]||0)+1;}
    const controls=[...p.querySelectorAll('button, input, textarea, summary')];
    const short=controls.filter(c=>c.offsetParent!==null && c.getBoundingClientRect().height<36)
      .map(c=>[c.id||c.className||c.tagName, +c.getBoundingClientRect().height.toFixed(1)]);
    const ta=document.getElementById('graph-popup-content');
    const clipped=controls.filter(c=>c.scrollHeight>c.clientHeight+1 && c!==ta && c.tagName!=='TEXTAREA')
      .map(c=>[c.id||c.className, c.scrollHeight, c.clientHeight]);
    const sizes=new Set([...p.querySelectorAll('*')].filter(el=>el.offsetParent!==null)
      .map(el=>getComputedStyle(el).fontSize));
    return {
      width:+r.width.toFixed(1), height:+r.height.toFixed(1),
      scrollHeight:p.scrollHeight, clientHeight:p.clientHeight,
      panelScrolls:p.scrollHeight>p.clientHeight,
      pageScrolls:document.scrollingElement.scrollHeight>document.scrollingElement.clientHeight+1,
      actionCount:acts.length, perRow:Object.values(rows), rowCount:Object.keys(rows).length,
      // The PAINT, not the class list: a late rule paints every
      // .icon-only:not(.ghost) button tonal, so "not ghost" is not "filled".
      filled:acts.filter(b=>{const bg=getComputedStyle(b).backgroundColor;
        return bg!=='rgba(0, 0, 0, 0)' && bg!==getComputedStyle(acts[acts.length-1]).backgroundColor;})
        .map(b=>[b.title||b.textContent.trim(), getComputedStyle(b).backgroundColor]),
      textareaH:ta?+ta.getBoundingClientRect().height.toFixed(1):null,
      saveVisible:(()=>{const s=document.getElementById('graph-popup-save');return s?s.offsetParent!==null:null;})(),
      chips:p.querySelectorAll('.chip').length,
      sheet:p.classList.contains('graph-popup-sheet'),
      taMinHeight:ta?getComputedStyle(ta).minHeight:null,
      dividers:p.querySelectorAll('.graph-popup-tool-group').length,
      fontSizes:[...sizes].sort(), shortControls:short, clipped,
    };
  });
  // The Save gate: typing shows it, undoing the change puts it away.
  await page.fill('#graph-popup-content', 'edited by the probe');
  await page.waitForTimeout(200);
  const dirty=await page.evaluate(()=>!document.getElementById('graph-popup-save').classList.contains('hidden'));
  await page.evaluate(()=>{const t=document.getElementById('graph-popup-content'); t.value=graphPopupClean.content; t.dispatchEvent(new Event('input'));});
  await page.waitForTimeout(200);
  const cleanAgain=await page.evaluate(()=>document.getElementById('graph-popup-save').classList.contains('hidden'));
  console.log(JSON.stringify({w:W, opened, ...m, saveOnEdit:dirty, saveHidesOnUndo:cleanAgain, errors:errs}, null, 1));
  const box=await page.evaluate(()=>{const r=document.getElementById('graph-popup').getBoundingClientRect();return {x:Math.max(0,r.x-8),y:Math.max(0,r.y-8),width:r.width+16,height:r.height+16};});
  await page.screenshot({path:`${process.env.SCRATCH||'.'}/shots/graphnode-${W}.png`, clip:box});
  await browser.close();
})();
