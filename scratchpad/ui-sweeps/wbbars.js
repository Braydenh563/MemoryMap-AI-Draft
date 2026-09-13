// The whiteboard's floating panels (INBOX 52, 64, 65): how many elements
// inside each bar paint a background of their own, whether the bar and the
// zoom pill are the same height, and whether any two controls in the
// properties panel overlap each other.
const {boot}=require('./lib.js');
const W=Number(process.env.W||1440), H=Number(process.env.H||900);
(async()=>{
  const {browser,page}=await boot({viewport:{width:W,height:H}});
  const errs=[]; page.on('pageerror',e=>errs.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errs.push(m.text().slice(0,140));});
  const id=await page.evaluate(async()=>{
    const r=await api('/whiteboard/boards',{method:'POST',body:JSON.stringify({name:'Bars sweep'})});
    return (await r.json()).id;
  });
  await page.evaluate((b)=>openWhiteboardBoard(b), id);
  await page.waitForTimeout(2000);
  // The Arrange section only appears for a multi-selection, which is the
  // state INBOX 64's screenshots are of: two cards, then select all.
  await page.evaluate(async()=>{
    await wbCreateSticky(320, 300);
    await wbCreateSticky(560, 300);
    if (typeof wbBlurTextEdit==='function') wbBlurTextEdit();
    document.activeElement?.blur();
  });
  await page.waitForTimeout(1200);
  await page.evaluate(()=>{ wbSelectAllItems(); });
  await page.waitForTimeout(600);
  const out=await page.evaluate(() => {
    const painted=(el)=>{
      const c=getComputedStyle(el);
      const bg=c.backgroundColor;
      const has=bg && bg!=='rgba(0, 0, 0, 0)' && bg!=='transparent';
      const img=c.backgroundImage && c.backgroundImage!=='none';
      return has||img;
    };
    const survey=(sel)=>{
      const bar=document.querySelector(sel);
      if(!bar||bar.classList.contains('hidden')) return {found:false};
      const kids=[...bar.querySelectorAll('*')].filter(e=>e.checkVisibility&&e.checkVisibility());
      const backgrounds=kids.filter(painted).map(e=>[e.tagName.toLowerCase()+'.'+String(e.className).split(' ').filter(Boolean).slice(0,2).join('.'), getComputedStyle(e).backgroundColor]);
      const borders=kids.filter(e=>{
        const c=getComputedStyle(e);
        return ['Top','Right','Bottom','Left'].some(s=>parseFloat(c['border'+s+'Width'])>0 && c['border'+s+'Style']!=='none' && !/rgba\(0, 0, 0, 0\)|transparent/.test(c['border'+s+'Color']));
      }).map(e=>e.tagName.toLowerCase()+'.'+String(e.className).split(' ').filter(Boolean).slice(0,2).join('.'));
      const r=bar.getBoundingClientRect();
      return {found:true, h:+r.height.toFixed(1), w:+r.width.toFixed(1),
        barBg:getComputedStyle(bar).backgroundColor,
        backgrounds, borders, count:kids.length};
    };
    // Any two controls in a panel whose boxes intersect (INBOX 64's
    // "Group / Ungroup overlapping each other").
    const overlaps=(sel)=>{
      const panel=document.querySelector(sel);
      if(!panel) return [];
      const ctrls=[...panel.querySelectorAll('button, input, select, summary')]
        .filter(e=>e.checkVisibility&&e.checkVisibility());
      const out=[];
      for(let i=0;i<ctrls.length;i++) for(let j=i+1;j<ctrls.length;j++){
        const a=ctrls[i].getBoundingClientRect(), b=ctrls[j].getBoundingClientRect();
        if(a.right>b.left+0.5 && b.right>a.left+0.5 && a.bottom>b.top+0.5 && b.bottom>a.top+0.5){
          if(ctrls[i].contains(ctrls[j])||ctrls[j].contains(ctrls[i])) continue;
          out.push([ctrls[i].id||ctrls[i].title||ctrls[i].className, ctrls[j].id||ctrls[j].title||ctrls[j].className]);
        }
      }
      return out;
    };
    // A control whose box leaves its panel's own box: the clip that an
    // intersection test cannot see (a group that does not fit is cut by the
    // panel edge rather than overlapping a sibling).
    const outside=(sel)=>{
      const panel=document.querySelector(sel);
      if(!panel) return [];
      const p=panel.getBoundingClientRect();
      return [...panel.querySelectorAll('button, input, select, summary')]
        .filter(e=>e.checkVisibility&&e.checkVisibility())
        .filter(e=>{const r=e.getBoundingClientRect(); return r.right>p.right+0.5||r.left<p.left-0.5;})
        .map(e=>e.id||String(e.className));
    };
    const props=document.getElementById('wb-properties-panel');
    return {
      tools: survey('.whiteboard-floating-panel.bottom-center'),
      zoom: survey('.whiteboard-floating-panel.bottom-right'),
      properties: survey('#wb-properties-panel'),
      propsOverlaps: overlaps('#wb-properties-panel'),
      propsOutside: outside('#wb-properties-panel'),
      toolsOutside: outside('.whiteboard-floating-panel.bottom-center'),
      propsScroll: props?{sh:props.scrollHeight, ch:props.clientHeight, scrolls:props.scrollHeight>props.clientHeight}:null,
      headings: props?[...props.querySelectorAll('h3, h4, .wb-panel-group-label')].map(e=>e.textContent.trim()):[],
      pageScrolls: document.scrollingElement.scrollHeight>document.scrollingElement.clientHeight+1,
    };
  });
  // The fill has to come back under the pointer, or removing it at rest
  // takes the affordance with it.
  await page.hover('.whiteboard-floating-panel.bottom-center button[data-tool="pan"]');
  await page.waitForTimeout(250);
  const hover=await page.evaluate(()=>{
    const b=document.querySelector('.whiteboard-floating-panel.bottom-center button[data-tool="pan"]');
    return getComputedStyle(b).backgroundColor;
  });
  console.log(JSON.stringify({w:W, ...out, hoverFill:hover, errors:errs}, null, 1));
  const clip=await page.evaluate(()=>{
    const t=document.querySelector('.whiteboard-floating-panel.bottom-center').getBoundingClientRect();
    const z=document.querySelector('.whiteboard-floating-panel.bottom-right').getBoundingClientRect();
    const x=Math.max(0,t.x-10), y=Math.min(t.y,z.y)-10;
    return {x, y, width:Math.min(z.right-x+10, innerWidth-x), height:Math.max(t.bottom,z.bottom)-y+10};
  });
  await page.screenshot({path:`${process.env.SCRATCH||'.'}/shots/wbbars-${W}${process.env.THEME==='dark'?'-dark':''}.png`, clip});
  const pr=await page.evaluate(()=>{const p=document.getElementById('wb-properties-panel');
    if(!p||p.classList.contains('hidden')) return null; const r=p.getBoundingClientRect();
    return {x:Math.max(0,r.x-8),y:Math.max(0,r.y-8),width:r.width+16,height:Math.min(r.height+16, 1200)};});
  if(pr) await page.screenshot({path:`${process.env.SCRATCH||'.'}/shots/wbprops-${W}.png`, clip:pr});
  await browser.close();
})();
