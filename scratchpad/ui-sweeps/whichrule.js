// "Which rule actually wins?" asked of the browser rather than of grep.
// The stylesheets are same-origin, so `cssRules` is readable and every rule
// that matches an element and declares a property can be listed in cascade
// order. Grep cannot do this: it cannot see specificity, and it cannot see
// that a selector matches nothing at all.
//
//   SEL='.library-image-caption' PROP=font-size node whichrule.js
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const tab=process.env.TAB||'library';
  await page.click(`[data-tab="${tab}"]`).catch(()=>{}); await page.waitForTimeout(900);
  if(process.env.SUBTAB) { await page.click(process.env.SUBTAB,{timeout:4000}).catch(()=>{}); await page.waitForTimeout(1500); }
  // OPEN=<details id> plus CLICK=<selector> so a rule that only applies to a
  // control inside an open menu, in a state it has to be put into, can be
  // asked about at all.
  if(process.env.OPEN){ await page.evaluate((i)=>{const d=document.getElementById(i); if(d) d.open=true;}, process.env.OPEN); await page.waitForTimeout(300); }
  if(process.env.CLICK){ await page.click(process.env.CLICK,{timeout:4000}).catch(()=>{}); await page.waitForTimeout(600);
    if(process.env.OPEN) await page.evaluate((i)=>{const d=document.getElementById(i); if(d) d.open=true;}, process.env.OPEN);
    await page.waitForTimeout(300); }
  const r=await page.evaluate(({sel,prop})=>{
    const el=document.querySelector(sel); if(!el) return {error:'no element for '+sel};
    const out=[];
    for(const sheet of document.styleSheets){
      let rules; try{ rules=sheet.cssRules; }catch(e){ continue; }
      const walk=(list, media)=>{
        for(const rule of list){
          if(rule.cssRules && !rule.selectorText){ walk(rule.cssRules, rule.conditionText||media); continue; }
          if(!rule.selectorText) continue;
          const v=rule.style && rule.style.getPropertyValue(prop);
          if(!v) continue;
          let hit=false; try{ hit=el.matches(rule.selectorText); }catch(e){}
          if(hit) out.push({sel:rule.selectorText.slice(0,90), value:v, media:media||'', href:(sheet.href||'').split('/').pop()});
        }
      };
      walk(rules,'');
    }
    return {computed:getComputedStyle(el)[prop], matched:out};
  }, {sel:process.env.SEL||'.library-image-caption', prop:process.env.PROP||'font-size'});
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
