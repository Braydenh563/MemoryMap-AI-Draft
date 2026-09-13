const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const r=await page.evaluate(()=>{
    const d=document.getElementById('doc-ai-history-dialog');
    let sheets=0, rules=0, marginRules=0, matched=[];
    const walk=(list)=>{ for(const rule of list){ if(rule.cssRules){walk(rule.cssRules);continue;}
      if(!rule.selectorText) continue; rules++;
      const txt=rule.style.cssText||''; if(!txt.includes('margin')) continue; marginRules++;
      try{ if(d.matches(rule.selectorText)) matched.push(rule.selectorText+' => '+txt.slice(0,80)); }catch(e){}
    }};
    for(const s of document.styleSheets){ sheets++; try{ walk(s.cssRules); }catch(e){} }
    return {hasEl:!!d, sheets, rules, marginRules, matched};
  });
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
