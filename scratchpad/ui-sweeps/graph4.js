const {chromium}=require('/opt/node22/lib/node_modules/playwright');
const PW='testpassword123'; const BASE=process.env.BASE||'http://127.0.0.1:8784';
(async()=>{
  const browser=await chromium.launch(); const page=await browser.newPage({viewport:{width:1440,height:900}});
  const errs=[]; page.on('pageerror',e=>errs.push(e.message)); page.on('console',m=>{if(m.type()==='error')errs.push(m.text().slice(0,140));});
  await page.goto(BASE+'/',{waitUntil:'domcontentloaded'});
  await page.waitForSelector('#lock-password',{state:'visible',timeout:20000});
  await page.fill('#lock-password',PW); await page.click('#lock-submit'); await page.waitForTimeout(2500);
  if(await page.$('#lock-password')&&await page.isVisible('#lock-password')){await page.fill('#lock-password',PW);await page.click('#lock-submit');await page.waitForTimeout(2500);}
  await page.evaluate(()=>document.getElementById('onboarding-overlay')?.remove());
  await page.evaluate(()=>switchTab('graph')); await page.waitForTimeout(3000);
  const out={errors:[]};
  // lasso around everything: drag with shift over the whole canvas
  const box=await page.evaluate(()=>{const c=document.getElementById('graph-canvas'); const r=c.getBoundingClientRect(); return {x:r.left,y:r.top,w:r.width,h:r.height};});
  await page.keyboard.down('Shift');
  const L=box.x+box.w*0.3, T=box.y+150, R=box.x+box.w*0.88, B=box.y+box.h-150;
  out.underStart=await page.evaluate(([x,y])=>{const el=document.elementFromPoint(x,y); return el?`${el.tagName}#${el.id}.${el.className}`.slice(0,60):null;},[L,T]);
  await page.mouse.move(L, T); await page.mouse.down();
  await page.mouse.move(R, T, {steps:6});
  out.midDrag=await page.evaluate(()=>gcLasso?gcLasso.points.length:null);
  for (const [px,py] of [[R,B],[L,B],[L,T]]) { await page.mouse.move(px,py,{steps:6}); }
  await page.mouse.up(); await page.keyboard.up('Shift'); await page.waitForTimeout(400);
  out.nodesInRect=await page.evaluate(([L,T,R,B])=>{const c=document.getElementById('graph-canvas').getBoundingClientRect(); const t=gcTransform; return gcNodes.filter(n=>{const sx=c.left+t.applyX(n.x), sy=c.top+t.applyY(n.y); return sx>L&&sx<R&&sy>T&&sy<B;}).length;},[L,T,R,B]);
  out.lasso=await page.evaluate(()=>({selected:gcSelected.size, nodes:gcNodes.length, dockShown:!document.getElementById('graph-selection-dock').classList.contains('hidden'), count:document.getElementById('graph-selection-count').textContent, panned:!!(gcTransform&&(Math.abs(gcTransform.x)>0||Math.abs(gcTransform.y)>0))}));
  // link together
  const linksBefore=await page.evaluate(()=>gcEdges.length);
  await page.evaluate(()=>document.getElementById('graph-selection-link').click()); await page.waitForTimeout(2500);
  out.link={before:linksBefore, after:await page.evaluate(()=>gcEdges.length)};
  // tag: stub promptDialog
  await page.evaluate(()=>{window.promptDialog=async()=>'lassoed';}); await page.evaluate(()=>document.getElementById('graph-selection-tag').click()); await page.waitForTimeout(2500);
  out.tag=await page.evaluate(()=>gcNodes.filter(n=>(n.tags||[]).includes('lassoed')).length);
  // right-click menu on the first node
  const pt=await page.evaluate(()=>{const n=gcNodes[0]; const t=gcTransform; const c=document.getElementById('graph-canvas').getBoundingClientRect(); return {x:c.left+t.applyX(n.x), y:c.top+t.applyY(n.y)};});
  await page.mouse.click(pt.x, pt.y, {button:'right'}); await page.waitForTimeout(300);
  out.menu=await page.evaluate(()=>{const m=document.querySelector('.graph-node-menu'); if(!m)return null; const r=m.getBoundingClientRect(); return {items:[...m.querySelectorAll('button')].map(b=>b.textContent.trim()), inViewport:r.right<=innerWidth&&r.bottom<=innerHeight};});
  await page.evaluate(()=>[...document.querySelectorAll('.graph-node-menu button')].find(b=>b.textContent.includes('Hide'))?.click()); await page.waitForTimeout(1200);
  out.hide=await page.evaluate(()=>({hidden:graphHiddenIds.size, nodes:gcNodes.length, legend:[...document.querySelectorAll('#graph-legend .legend-toggle')].map(b=>b.textContent.trim()).filter(t=>t.includes('hidden'))}));
  // mind map from selection
  await page.evaluate(()=>{window.promptDialog=async()=>'From the map';}); await page.evaluate(()=>document.getElementById('graph-selection-map').click()); await page.waitForTimeout(3000);
  out.map=await page.evaluate(async()=>{const boards=await api('/whiteboard/boards'); const b=(Array.isArray(boards)?boards:boards.items||[]).find(x=>(x.name||x.title)==='From the map'); if(!b)return null; const tree=await api(`/whiteboard/boards/${b.id}/tree`).catch(()=>null); return {type:b.type||b.board_type, nodes: tree? JSON.stringify(tree).match(/"kind":"note"/g)?.length : null};});
  out.errors=errs.slice(0,4);
  console.log(JSON.stringify(out));
  await browser.close();
})();
