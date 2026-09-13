// The suggestion menu's candidate rows read as words, not as five identical
// commands: no icon on a candidate, the check mark kept for the apply action,
// the first candidate carrying the weight.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.click('[data-tab="documents"]').catch(()=>{});
  await page.waitForTimeout(1200);
  const r=await page.evaluate(async()=>{
    const mk=await fetch('/documents',{method:'POST',
      headers:{'X-Auth-Token':localStorage.getItem('token')||'','Content-Type':'application/json'},
      body:JSON.stringify({title:'Spelling probe',content:'This is a tets of the suggestion menu.'})});
    const doc=await mk.json();
    await openDocument(doc.id);
    await new Promise(r=>setTimeout(r,2500));
    const findings=docProseFindings(docText());
    const spelling=findings.find(f=>/tets/.test(f.text||''));
    if(!spelling) return {error:'no finding', findings:findings.length};
    openDocSuggest(spelling, {left:100,top:100,right:200,bottom:120,width:100,height:20});
    await new Promise(r=>setTimeout(r,500));
    const menu=document.querySelector('.doc-suggest-menu, #doc-suggest');
    const items=[...document.querySelectorAll('.doc-suggest-item')].map(b=>({
      text:b.textContent.trim(), icons:b.querySelectorAll('i.ph, i[class*=ph-]').length,
      weight:getComputedStyle(b).fontWeight, best:b.classList.contains('doc-suggest-best')}));
    return {items, menuFound:!!menu};
  });
  const fails=[];
  console.log(JSON.stringify(r,null,1));
  const items=r.items||[];
  const candidates=items.filter(i=>!/Ask the AI|dictionary|Ignore|Translate/.test(i.text));
  if(candidates.length<2) fails.push('fewer than two candidate rows to compare');
  if(candidates.some(i=>i.icons>0)) fails.push('a candidate row still draws an icon');
  if(!candidates.some(i=>i.best)) fails.push('no candidate is marked as the best one');
  const best=candidates.find(i=>i.best), rest=candidates.find(i=>!i.best);
  if(best&&rest&&Number(best.weight)<=Number(rest.weight)) fails.push(`the first candidate is not heavier: ${best.weight} vs ${rest.weight}`);
  const actions=items.filter(i=>/Ask the AI|dictionary|Ignore|Translate/.test(i.text));
  if(actions.length&&actions.every(i=>i.icons===0)) fails.push('the action rows lost their icons too');
  console.log(fails.length?'FAIL:\n  '+fails.join('\n  '):'suggestrows: all checks pass');
  await browser.close();
  process.exit(fails.length?1:0);
})();
