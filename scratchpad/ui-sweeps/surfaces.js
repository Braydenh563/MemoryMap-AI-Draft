// Phase 5.7: the whiteboard and the documents editor — the two surfaces no
// sweep had covered. Opens a fresh board and the first document, then counts
// button recipes, blurred layers, nested hairlines and panel shells, and
// measures the chrome above the first line of document text (PLAN D1).
const {boot}=require('./lib.js');
const sig=(scope)=>`(()=>{const vis=e=>e.checkVisibility&&e.checkVisibility();const root=document.querySelector('${scope}')||document;
 const btn={};root.querySelectorAll('button, summary').forEach(b=>{if(!vis(b))return;const r=b.getBoundingClientRect();if(r.width<6||r.height<6)return;if(b.closest('.seg,[role=tablist]'))return;const c=getComputedStyle(b);const icon=b.classList.contains('icon-only')||b.classList.contains('icon-button')?'ICON':'text';const k=icon+' bg='+c.backgroundColor+' bd='+c.borderTopWidth+' '+c.borderTopColor+' sh='+(c.boxShadow==='none'?'none':'shadow')+' r='+c.borderTopLeftRadius+' h='+Math.round(r.height);btn[k]=btn[k]||{n:0,ex:[]};btn[k].n++;if(btn[k].ex.length<3)btn[k].ex.push((b.id?'#'+b.id:'')+'.'+[...b.classList].slice(0,2).join('.'));});
 const blurred=[...root.querySelectorAll('*')].filter(e=>vis(e)&&getComputedStyle(e).backdropFilter!=='none');let nested=0;for(const e of blurred){let p=e.parentElement;while(p){if(blurred.includes(p)){nested++;break;}p=p.parentElement;}}
 const bordered=[...root.querySelectorAll('*')].filter(e=>vis(e)&&getComputedStyle(e).borderTopWidth!=='0px'&&getComputedStyle(e).borderTopStyle!=='none'&&getComputedStyle(e).borderTopColor!=='rgba(0, 0, 0, 0)'&&!e.matches('input,select,textarea,button,summary,hr,kbd'));const nestedB=bordered.filter(e=>{let p=e.parentElement;while(p&&p!==root){if(bordered.includes(p))return true;p=p.parentElement;}return false;}).map(e=>e.tagName.toLowerCase()+'.'+[...e.classList].slice(0,2).join('.'));
 const panels={};root.querySelectorAll('[class*="panel"],[class*="toolbar"],[class*="bar"],[class*="dock"],[class*="navigator"],[id*="toolbar"]').forEach(e=>{if(!vis(e))return;const c=getComputedStyle(e);if(c.backgroundColor==='rgba(0, 0, 0, 0)'&&c.borderTopWidth==='0px')return;const k='bg='+c.backgroundColor+' bd='+c.borderTopWidth+' '+c.borderTopColor+' r='+c.borderTopLeftRadius+' sh='+(c.boxShadow==='none'?'none':'shadow')+' blur='+(c.backdropFilter!=='none');panels[k]=panels[k]||[];if(panels[k].length<3)panels[k].push((e.id?'#'+e.id:'')+'.'+[...e.classList].slice(0,2).join('.'));});
 return {buttons:btn,blurred:blurred.length,nested,nestedBorders:nestedB.slice(0,12),panels};})()`;
const print=(label,r)=>{const rows=Object.entries(r.buttons).sort((a,b)=>b[1].n-a[1].n);console.log(`== ${label}: ${rows.length} button signatures, blurred=${r.blurred} nested=${r.nested}, nested hairlines=${r.nestedBorders.length}`);console.log('  '+rows.map(([k,v])=>v.n+' '+k+' '+v.ex.join(' ')).join('\n  '));console.log('  nested hairlines: '+r.nestedBorders.join(', '));console.log('  panel shells ('+Object.keys(r.panels).length+'):\n  '+Object.entries(r.panels).map(([k,v])=>k+' '+v.join(' ')).join('\n  '));};
(async()=>{
  const {browser,page,OUT}=await boot();
  await page.click('[data-tab="library"]');await page.waitForTimeout(600);
  await page.click('[data-target="library-view-whiteboard"]');await page.waitForTimeout(700);
  const nb=await page.$('#wb-boards-new'); if(nb&&await nb.isVisible()){await nb.click();await page.waitForTimeout(800);
    // A name prompt opens as a confirm dialog; accept it with whatever it offers.
    const ok=await page.$('.confirm-overlay button:not(.ghost), .confirm-overlay .confirm-ok, .confirm-overlay button'); if(ok){await ok.click();await page.waitForTimeout(1200);}}
  await page.screenshot({path:OUT+'/surf-whiteboard.png'});
  print('whiteboard', await page.evaluate(sig('.tab-page:not(.hidden)')));
  await page.keyboard.press('Escape');await page.waitForTimeout(300);
  await page.evaluate(()=>document.querySelectorAll('.confirm-overlay').forEach(o=>o.remove()));
  await page.click('[data-tab="library"]');await page.waitForTimeout(400);
  await page.click('[data-target="library-view-docs"]');await page.waitForTimeout(700);
  const row=await page.$('.doc-list-item'); const opened=row?(await row.click(),'clicked row'):'no row';
  await page.waitForTimeout(1500); console.log(opened);
  await page.screenshot({path:OUT+'/surf-documents.png'});
  const chrome=await page.evaluate(()=>{const panes=document.querySelector('#doc-panes');const page_=document.querySelector('.tab-page:not(.hidden)');if(!panes||!page_)return null;const text=document.querySelector('#doc-live .doc-live-body, #doc-live, #doc-editor, .doc-live');return {panesTop:Math.round(panes.getBoundingClientRect().top-page_.getBoundingClientRect().top),textTop:text?Math.round(text.getBoundingClientRect().top):null,windowTopOfText:text?Math.round(text.getBoundingClientRect().top):null};});
  console.log('documents chrome above panes (px from page top):', JSON.stringify(chrome));
  print('documents', await page.evaluate(sig('.tab-page:not(.hidden)')));
  await browser.close();
})();
