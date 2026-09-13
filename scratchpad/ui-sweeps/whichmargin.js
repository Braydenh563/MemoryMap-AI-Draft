const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const r=await page.evaluate(()=>{
    const d=document.getElementById('doc-ai-history-dialog');
    const hits=[];
    for(const sheet of document.styleSheets){
      let rules; try{ rules=sheet.cssRules; }catch(e){ continue; }
      const walk=(list,media)=>{
        for(const rule of list){
          if(rule.cssRules){ walk(rule.cssRules, rule.conditionText||media); continue; }
          if(!rule.selectorText) continue;
          if(!/margin/.test(rule.style.cssText||'')) continue;
          let m=false; try{ m=d.matches(rule.selectorText); }catch(e){}
          if(m) hits.push({sel:rule.selectorText, css:rule.style.cssText.slice(0,90),
            file:(sheet.href||'').split('/').pop(), media:media||''});
        }
      };
      walk(rules);
    }
    return hits;
  });
  for(const h of r) console.log(h.file,'|',h.media,'|',h.sel,'=>',h.css);
  await browser.close();
})();
