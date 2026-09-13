const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.evaluate(()=>{
    const tab=document.getElementById('tab-documents');
    tab.classList.remove('hidden'); tab.style.display='flex';
    const d=document.getElementById('doc-ai-history-dialog');
    d.showModal();
  });
  const cdp=await page.context().newCDPSession(page);
  await cdp.send('DOM.enable'); await cdp.send('CSS.enable');
  const {root}=await cdp.send('DOM.getDocument',{depth:-1});
  const {nodeId}=await cdp.send('DOM.querySelector',{nodeId:root.nodeId, selector:'#doc-ai-history-dialog'});
  const m=await cdp.send('CSS.getMatchedStylesForNode',{nodeId});
  for(const e of (m.matchedCSSRules||[])){
    const txt=e.rule.style.cssText||'';
    if(!/margin|width|position|inset/.test(txt)) continue;
    console.log((e.rule.origin||'')+' | '+e.rule.selectorList.text+' => '+txt.replace(/\s+/g,' ').slice(0,140));
  }
  await browser.close();
})();
