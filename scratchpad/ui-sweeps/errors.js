// Bug scan: page errors and console errors per tab and Settings section,
// horizontal overflow and clipped cards at four widths. Prints only what is
// wrong; a clean run prints one line per width.
//
// `checkVisibility` is called with all three opt-in flags (Phase 9). The bare
// call only rules out `display: none` and `content-visibility`, so anything
// hidden with `visibility` or `opacity: 0` still counted as on screen: the
// sidebar sheets added in Phase 9 park off-canvas when closed, and the sweep
// reported "New chat" as an off-screen control every time. An element with
// `visibility: hidden` is not visible, so the stricter test is the correct
// one rather than an excuse made for the sheet.
const {chromium}=require('/opt/node22/lib/node_modules/playwright');
const PW='testpassword123'; const BASE=process.env.BASE||'http://127.0.0.1:8781';
// Every tab page, not the seven with a button in the tab bar. Documents and
// the whiteboard are reached from a dock or a Library row, so clicking
// `[data-tab]` never opened them and a console error on the documents editor
// could not fail this sweep. Same gap `contrast.js` had, found 2026-09-12.
const TABS=['dashboard','notes','library','chat','graph','timeline','reminders','documents','whiteboard'];
const SECTIONS=['account','appearance','preferences','models','tools','skills','personas','templates','websearch','memory','tasks','data','logs','shortcuts','extras','help','about'];
const SUBTABS={notes:['browse','capture','writing-room','ask'],library:['docs','boards','images','files','skills','links','contents']};
(async()=>{
  const browser=await chromium.launch();
  for(const width of (process.env.WIDTHS||'1440,1024,820,390').split(',').map(Number)){
    const ctx=await browser.newContext({viewport:{width,height:width<600?844:900},deviceScaleFactor:1,hasTouch:width<820,isMobile:width<600});
    await ctx.addInitScript(()=>{try{localStorage.setItem('theme','light');}catch(e){}});
    const page=await ctx.newPage(); const errs=[]; let where='boot';
    page.on('pageerror',e=>errs.push(`[${where}] ${e.message}`));
    page.on('response',r=>{if(r.status()>=500)errs.push(`[${where}] HTTP ${r.status()} ${r.request().method()} ${r.url().replace(BASE,'')}`);});
    page.on('console',m=>{if(m.type()==='error'&&!/401|Failed to load resource/.test(m.text()))errs.push(`[${where}] console: ${m.text().slice(0,140)}`);});
    await page.goto(BASE+'/',{waitUntil:'domcontentloaded'}); await page.waitForSelector('#lock-password',{state:'visible',timeout:20000});
    await page.fill('#lock-password',PW); await page.click('#lock-submit'); await page.waitForTimeout(2500);
    if(await page.$('#lock-password')&&await page.isVisible('#lock-password')){await page.fill('#lock-password',PW);await page.click('#lock-submit');await page.waitForTimeout(2500);}
    await page.evaluate(()=>{const o=document.getElementById('onboarding-overlay');if(o)o.classList.add('hidden');}); await page.waitForTimeout(500);
    const findings=[];
    const check=async(label)=>{const r=await page.evaluate(()=>{const vis=e=>e.checkVisibility&&e.checkVisibility({visibilityProperty:true,opacityProperty:true,contentVisibilityAuto:true});const over=document.documentElement.scrollWidth>window.innerWidth+1;const clipped=[...document.querySelectorAll('.card, .tab-page:not(.hidden) button, .tab-page:not(.hidden) h2, .tab-page:not(.hidden) h3')].filter(e=>vis(e)&&getComputedStyle(e).overflow!=='visible'&&e.scrollHeight>e.clientHeight+2&&!e.matches('textarea, .tab-page, [class*="scroll"], .entry-list, ul, ol')).slice(0,4).map(e=>`${e.tagName.toLowerCase()}#${e.id}.${[...e.classList].slice(0,2).join('.')} ${e.scrollHeight}>${e.clientHeight}`);const inStrip=e=>{for(let p=e.parentElement;p&&p!==document.body;p=p.parentElement){const o=getComputedStyle(p).overflowX;if((o==='auto'||o==='scroll')&&p.scrollWidth>p.clientWidth+1)return true;}return false;};const off=[...document.querySelectorAll('.tab-page:not(.hidden) button, .tab-page:not(.hidden) input')].filter(e=>vis(e)&&!inStrip(e)).filter(e=>{const r=e.getBoundingClientRect();return r.right>window.innerWidth+1||r.left<-1;}).slice(0,4).map(e=>`${e.tagName.toLowerCase()}#${e.id}.${[...e.classList].slice(0,2).join('.')}`);return {over,clipped,off};});
      if(r.over)findings.push(`[${label}] page scrolls horizontally`); if(r.clipped.length)findings.push(`[${label}] clipped: ${r.clipped.join(', ')}`); if(r.off.length)findings.push(`[${label}] off-screen: ${r.off.join(', ')}`);};
    for(const t of TABS){where=t; await page.evaluate((name)=>{try{switchTab(name);}catch(e){}},t); await page.waitForTimeout(700);
      const shown=await page.evaluate((name)=>{const el=document.getElementById('tab-'+name);return el?!el.classList.contains('hidden'):null;},t);
      if(shown===false){findings.push(`[${t}] the tab did not open, so nothing here was checked`); continue;}
      await check(t);
      for(const s of (SUBTABS[t]||[])){where=t+'/'+s; const ok=await page.click(`#tab-${t} [data-section="${s}"], #tab-${t} [data-view="${s}"]`,{timeout:1500}).then(()=>true).catch(()=>false); if(!ok)continue; await page.waitForTimeout(500); await check(where);}}
    where='settings'; await page.click('#settings-btn').catch(()=>{}); await page.waitForTimeout(500);
    for(const s of SECTIONS){where='settings/'+s; const ok=await page.click(`#settings-modal [data-section="${s}"]`,{timeout:1500}).then(()=>true).catch(()=>false); if(!ok)continue; await page.waitForTimeout(300);
      const r=await page.evaluate(()=>{const m=document.querySelector('#settings-modal .settings-section:not(.hidden), #settings-modal .settings-body');return m?(m.scrollWidth>m.clientWidth+2?`section scrolls sideways ${m.scrollWidth}>${m.clientWidth}`:''):'';}); if(r)findings.push(`[${where}] ${r}`);}
    console.log(`== ${width}px: ${errs.length} errors, ${findings.length} layout findings`); errs.forEach(e=>console.log('  '+e)); findings.forEach(f=>console.log('  '+f));
    await ctx.close();
  }
  await browser.close();
})();
