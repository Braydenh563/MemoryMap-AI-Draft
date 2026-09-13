// Icon/text vertical alignment, measured rather than eyeballed.
//
// For every visible button, anchor, summary, label or menu row that holds an
// icon (`<i class="ph …">` or an `<svg>`) *and* a text node, compare the
// icon's vertical centre with the text's. The text's centre comes from a
// Range around the element's own text nodes, not from the parent box, because
// a parent box that is taller than its text (a fixed control height, a
// wrapped label) reports a centre the reader never sees.
//
// Usage:  BASE=http://127.0.0.1:8815 node scratchpad/ui-sweeps/iconalign.js
//         THEME=dark  W=1024  to sweep the other theme or width.
const {boot}=require('./lib.js');
const TABS=['dashboard','notes','chat','graph','timeline','reminders','library'];
const TOL=parseFloat(process.env.TOL||"1");   // px of vertical centre difference we accept

const PROBE=(tol)=>{
  const out=[];
  let seen=0, maxd=0; const gaps=[]; const gapWho={};
  const sel='button, a, summary, label, .menu-item, .chip, .status-item, .linklike';
  for(const el of document.querySelectorAll(sel)){
    const r=el.getBoundingClientRect();
    if(r.width<1||r.height<1) continue;
    const cs=getComputedStyle(el);
    if(cs.visibility==='hidden'||cs.display==='none') continue;
    // Any depth, not just a direct child: a first pass looked only at
    // `:scope > i.ph` and reported a clean sweep while every icon wrapped in
    // a span went unexamined. A zero with the wrong denominator is not a
    // measurement.
    const icon=el.querySelector('i.ph, svg, i[class*="ph-"]');
    if(!icon) continue;
    // Only rows. An icon stacked *above* its text (a timeline card, a
    // multi-line grid row with a hint under the label) is not misaligned, and
    // a first pass that compared their vertical centres reported nine
    // "failures" that were all this shape.
    const flow=cs.display;
    if(!/flex|inline-flex/.test(flow)) continue;
    if(cs.flexDirection!=='row') continue;
    const ir=icon.getBoundingClientRect();
    if(ir.height<1) continue;
    // The element's own text, measured by a Range so the box does not lie.
    const range=document.createRange();
    let first=null,last=null;
    for(const n of el.childNodes){
      if(n.nodeType===3&&n.textContent.trim()){ if(!first) first=n; last=n; }
      else if(n.nodeType===1&&n!==icon&&!n.contains(icon)&&n.textContent.trim()&&!n.querySelector('i.ph, svg')){ if(!first) first=n; last=n; }
    }
    if(!first) continue;
    try{ range.setStartBefore(first); range.setEndAfter(last); }catch(e){ continue; }
    const tr=range.getBoundingClientRect();
    if(tr.height<1||tr.width<1) continue;
    const d=Math.abs((ir.top+ir.height/2)-(tr.top+tr.height/2));
    seen++; if(d>maxd) maxd=d;
    // The horizontal gap between the icon and the label it leads. One value
    // app-wide is the other half of "icons and text don't align".
    if(tr.left>ir.right){
      const g=Math.round((tr.left-ir.right)*10)/10;
      gaps.push(g);
      if(!gapWho[g]) gapWho[g]=[];
      if(gapWho[g].length<3) gapWho[g].push(
        ((el.id?'#'+el.id:'')+'.'+(el.className||el.tagName).toString().trim().replace(/\s+/g,'.')).slice(0,40)
        +` [container gap=${cs.gap} icon margin-end=${getComputedStyle(icon).marginInlineEnd}]`);
    }
    if(d>tol){
      const ic=getComputedStyle(icon);
      out.push({
        d:Math.round(d*100)/100,
        who:(el.id?'#'+el.id:'')+'.'+(el.className||el.tagName).toString().trim().replace(/\s+/g,'.').slice(0,44),
        txt:(el.textContent||'').trim().slice(0,22),
        disp:cs.display, ai:cs.alignItems,
        ifs:ic.fontSize, ilh:ic.lineHeight, iva:ic.verticalAlign,
      });
    }
  }
  const g={}; for(const v of gaps) g[v]=(g[v]||0)+1;
  return {bad:out, seen, maxd:Math.round(maxd*100)/100, gaps:g, gapWho};
};

(async()=>{
  const W=parseInt(process.env.W||'1440',10);
  const {browser,page}=await boot({viewport:{width:W,height:900}});
  let total=0, examined=0; const allGaps={}, allWho={};
  for(const t of TABS){
    await page.click(`[data-tab="${t}"]`).catch(()=>{});
    await page.waitForTimeout(1500);
    const {bad,seen,maxd,gaps,gapWho}=await page.evaluate(PROBE,TOL);
    total+=bad.length; examined+=seen; for(const k in gaps) allGaps[k]=(allGaps[k]||0)+gaps[k]; for(const k in gapWho){ allWho[k]=allWho[k]||[]; for(const v of gapWho[k]) if(allWho[k].length<3&&!allWho[k].includes(v)) allWho[k].push(v); }
    console.log(`[${t}] ${bad.length} of ${seen} icon+text controls off by more than ${TOL}px (worst ${maxd}px)`);
    for(const b of bad.sort((a,b)=>b.d-a.d).slice(0,14)){
      console.log(`    ${String(b.d).padStart(6)}px  ${b.who}  display=${b.disp} align=${b.ai} icon(fs=${b.ifs} lh=${b.ilh} va=${b.iva})  :: ${b.txt}`);

    }
  }
  // The settings modal holds most of the app's icon+text rows, so a sweep
  // that skips it is not a sweep of the app.
  await page.click('#settings-btn, [data-open-settings], #open-settings').catch(()=>{});
  await page.waitForTimeout(1200);
  for(const sec of ['preferences','appearance','models','tools','skills','about','help']){
    const b=await page.$(`#settings-modal [data-section="${sec}"]`); if(!b) continue;
    await b.click(); await page.waitForTimeout(700);
    const {bad,seen,maxd,gaps,gapWho}=await page.evaluate(PROBE,TOL);
    total+=bad.length; examined+=seen; for(const k in gaps) allGaps[k]=(allGaps[k]||0)+gaps[k]; for(const k in gapWho){ allWho[k]=allWho[k]||[]; for(const v of gapWho[k]) if(allWho[k].length<3&&!allWho[k].includes(v)) allWho[k].push(v); }
    console.log(`[settings/${sec}] ${bad.length} of ${seen} off by more than ${TOL}px (worst ${maxd}px)`);
    for(const x of bad.sort((a,b)=>b.d-a.d).slice(0,10))
      console.log(`    ${String(x.d).padStart(6)}px  ${x.who}  display=${x.disp} align=${x.ai} icon(fs=${x.ifs} lh=${x.ilh} va=${x.iva})  :: ${x.txt}`);
  }
  const gk=Object.keys(allGaps).map(Number).sort((a,b)=>a-b);
  const tiny=gk.filter(k=>k<3);
  if(tiny.length) console.log(`\nWARNING - ${tiny.length} gap value(s) under 3px, a row may have lost its gap entirely: ${tiny.join(', ')}`);
  console.log(`\nicon-to-label gaps: ${gk.length} distinct`);
  for(const k of gk) console.log(`   ${String(k).padStart(6)}px x${String(allGaps[k]).padEnd(4)} e.g. ${(allWho[k]||[]).join(' ; ')}`);
  console.log(`TOTAL: ${total} of ${examined} icon+text controls off by more than ${TOL}px at ${W}px, theme ${process.env.THEME||'light'}`);
  await browser.close();
})();
