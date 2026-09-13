const {chromium}=require('/opt/node22/lib/node_modules/playwright');
const PW='testpassword123'; const BASE=process.env.BASE||'http://127.0.0.1:8784';
(async()=>{
  const browser=await chromium.launch(); const page=await browser.newPage({viewport:{width:1440,height:900}});
  const errs=[]; page.on('pageerror',e=>errs.push(e.message)); page.on('console',m=>{if(m.type()==='error')errs.push(m.text().slice(0,120));});
  await page.goto(BASE+'/',{waitUntil:'domcontentloaded'});
  await page.waitForSelector('#lock-password',{state:'visible',timeout:20000});
  await page.fill('#lock-password',PW); await page.click('#lock-submit'); await page.waitForTimeout(2500);
  if(await page.$('#lock-password')&&await page.isVisible('#lock-password')){await page.fill('#lock-password',PW);await page.click('#lock-submit');await page.waitForTimeout(2500);}
  await page.evaluate(()=>document.getElementById('onboarding-overlay')?.remove());
  await page.evaluate(async()=>{const seed=[["tea shop opening hours",["food"]],["bubble tea order",["food"]],["thesis outline",["uni"]],["thesis chapter two",["uni"]],["gym on tuesday",[]],["holiday plans",["travel"]]]; for(const [c,t] of seed){await api('/entries',{method:'POST',body:JSON.stringify({content:c,tags:t})});}});
  await page.evaluate(()=>switchTab('graph')); await page.waitForTimeout(2500);
  const out={errors:errs.slice(0,3)};
  for (const rule of ['category','kind','age','space','tag','file']) {
    await page.evaluate((r)=>{const s=document.getElementById('graph-colour'); s.value=r; s.dispatchEvent(new Event('change',{bubbles:true}));}, rule);
    await page.waitForTimeout(900);
    out[rule]=await page.evaluate(()=>({legend:[...document.querySelectorAll('#graph-legend .legend-toggle')].map(b=>b.textContent.trim()).slice(0,6), colours:new Set(gcNodes.filter(n=>!n.isGroup).map(n=>gcColourOf(n))).size, nodes:gcNodes.length}));
  }
  // hide one tag via the legend
  await page.evaluate(()=>{const s=document.getElementById('graph-colour'); s.value='tag'; s.dispatchEvent(new Event('change',{bubbles:true}));}); await page.waitForTimeout(800);
  const before=await page.evaluate(()=>gcNodes.length);
  await page.evaluate(()=>[...document.querySelectorAll('#graph-legend .legend-toggle')].find(b=>b.textContent.trim()==='uni')?.click()); await page.waitForTimeout(800);
  const after=await page.evaluate(()=>gcNodes.length);
  out.hideTag={before, after, off:await page.evaluate(()=>document.querySelectorAll('#graph-legend .legend-off').length)};
  // a group
  await page.evaluate(()=>{document.getElementById('graph-options-toggle')?.click();}); await page.waitForTimeout(300);
  await page.evaluate(()=>{const i=document.getElementById('graph-group-query'); i.value='thesis'; document.getElementById('graph-group-add').click();}); await page.waitForTimeout(1200);
  out.group=await page.evaluate(()=>({rows:document.querySelectorAll('#graph-groups .graph-group-row').length, legend:[...document.querySelectorAll('#graph-legend .legend-group')].map(b=>b.textContent.trim()), painted:gcNodes.filter(n=>graphGroupOf.has(n.id)).length, colour:gcNodes.filter(n=>graphGroupOf.has(n.id)).map(n=>gcColourOf(n))[0]}));
  // saved view carries the group and the rule
  out.view=await page.evaluate(()=>{const v=graphCaptureView(); return {colour:localStorage.getItem('graph-colour'), groups:v.groups.length, hiddenKeys:v.hiddenKeys};});
  console.log(JSON.stringify(out));
  await browser.close();
})();
