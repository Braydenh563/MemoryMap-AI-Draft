const {chromium}=require('/opt/node22/lib/node_modules/playwright');
const PW='testpassword123'; const BASE=process.env.BASE||'http://127.0.0.1:8781';
(async()=>{
  const browser=await chromium.launch();
  for (const width of [1280, 820]) {
  const page=await browser.newPage({viewport:{width,height:800}});
  await page.goto(BASE+'/',{waitUntil:'domcontentloaded'});
  await page.waitForSelector('#lock-password',{state:'visible',timeout:20000});
  await page.fill('#lock-password',PW); await page.click('#lock-submit'); await page.waitForTimeout(2500);
  if(await page.$('#lock-password')&&await page.isVisible('#lock-password')){await page.fill('#lock-password',PW);await page.click('#lock-submit');await page.waitForTimeout(2500);}
  await page.evaluate(()=>document.getElementById('onboarding-overlay')?.remove());
  await page.evaluate(()=>switchTab('documents')); await page.waitForTimeout(900);
  await page.evaluate(()=>document.getElementById('doc-new')?.click()); await page.waitForTimeout(900);
  const r=(el)=>{const b=el.getBoundingClientRect();return {w:Math.round(b.width),h:Math.round(b.height),y:Math.round(b.top)};};
  const info=await page.evaluate(()=>{
    const r=(el)=>{const b=el.getBoundingClientRect();return {w:Math.round(b.width),h:Math.round(b.height),y:Math.round(b.top)};};
    const dock=document.querySelector('.doc-dock');
    const vis=(el)=>el.getBoundingClientRect().width>0&&!el.closest('details:not([open]) > :not(summary)');
    const ctrls=[...dock.querySelectorAll('button,select,input,summary')].filter(el=>vis(el)&&!el.closest('.doc-dock-menu-list')).map(el=>`${el.tagName.toLowerCase()}#${el.id||el.textContent.trim().slice(0,8)}:${Math.round(el.getBoundingClientRect().height)}`);
    const editor=document.querySelector('#doc-editor .cm-content')||document.getElementById('doc-content');
    const firstLine=editor?r(editor).y:null;
    const menu=document.getElementById('doc-dock-menu'); menu.open=true;
    const rows=[...menu.querySelectorAll('.doc-dock-menu-item')].filter(vis).map(el=>({t:el.textContent.trim().slice(0,22),h:Math.round(el.getBoundingClientRect().height),bg:getComputedStyle(el).backgroundColor}));
    const list=menu.querySelector('.doc-dock-menu-list'); const lr=list.getBoundingClientRect();
    menu.open=false;
    const sb=document.getElementById('doc-statusbar'); const sbItems=[...sb.children].filter(vis).map(el=>el.id||el.className.split(' ')[0]);
    const sidebarClipped=[...document.querySelectorAll('#doc-sidebar-tabs button, #doc-sidebar-list .doc-list-item, #doc-sidebar-list button')].filter(el=>el.scrollWidth>el.clientWidth+1).length;
    return {dock:r(dock), controls:ctrls, chromeAboveFirstLine:firstLine!==null?firstLine-r(dock).y:null, menuRows:rows, menuInViewport:lr.bottom<=innerHeight&&lr.right<=innerWidth, statusbar:sbItems, sidebarClipped};
  });
  // view switching through the group button and the menu
  await page.evaluate(()=>document.querySelector('#doc-view-seg [data-doc-view="rendered"]').click()); await page.waitForTimeout(200);
  const read=await page.evaluate(()=>({reading:document.getElementById('doc-panes').classList.contains('reading'), editOn:document.querySelector('[data-doc-view-group]').classList.contains('active')}));
  await page.evaluate(()=>{const m=document.getElementById('doc-view-menu'); m.open=true; m.querySelector('[data-doc-view="split"]').click();}); await page.waitForTimeout(200);
  const split=await page.evaluate(()=>({split:document.getElementById('doc-panes').classList.contains('split'), editOn:document.querySelector('[data-doc-view-group]').classList.contains('active'), menuOpen:document.getElementById('doc-view-menu').open}));
  await page.evaluate(()=>document.querySelector('#doc-view-seg [data-doc-view="rendered"]').click()); await page.evaluate(()=>document.querySelector('[data-doc-view-group]').click()); await page.waitForTimeout(200);
  const back=await page.evaluate(()=>({split:document.getElementById('doc-panes').classList.contains('split')}));
  console.log(width, JSON.stringify({...info, read, split, backToLastEdit:back}));
  await page.close();
  }
  await browser.close();
})();
