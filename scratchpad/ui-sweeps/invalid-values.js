// The invisible-bug class: a value that is invalid where it is used, not
// where it is set. Two missing appearance defaults once wrote `undefined`
// and `NaN` into two CSS custom properties and flattened every card in the
// app; nothing logged, nothing threw. This sweep reads every declared
// custom property (from the stylesheets and from the root's inline style,
// which is where Settings writes) and every element's inline style, on
// every tab and Settings section, in both themes, and prints any value
// that contains NaN, undefined, null or [object. Clean run: one line per
// theme.
const {chromium}=require('/opt/node22/lib/node_modules/playwright');
const PW='testpassword123'; const BASE=process.env.BASE||'http://127.0.0.1:8781';
const TABS=['dashboard','notes','library','chat','graph','timeline','reminders'];
const SECTIONS=['account','appearance','preferences','models','tools','skills','personas','templates','websearch','memory','tasks','data','logs','shortcuts','extras','help','about'];
const BAD=/NaN|undefined|null|\[object/;
async function scan(page){
  return page.evaluate((badSrc)=>{
    const bad=new RegExp(badSrc); const out=[];
    const root=document.documentElement; const names=new Set();
    for(const sheet of document.styleSheets){let rules=[];try{rules=sheet.cssRules;}catch(e){continue;}
      for(const r of rules){if(r.style)for(const p of r.style)if(p.startsWith('--'))names.add(p);}}
    for(const p of root.style)if(p.startsWith('--'))names.add(p);
    const cs=getComputedStyle(root);
    for(const n of names){const v=cs.getPropertyValue(n).trim(); if(bad.test(v))out.push(`root ${n}: "${v}"`);}
    for(const el of document.querySelectorAll('[style]')){const s=el.getAttribute('style')||''; if(bad.test(s))out.push(`${el.tagName.toLowerCase()}#${el.id||''}.${[...el.classList].slice(0,2).join('.')} style="${s.slice(0,80)}"`);}
    // Computed lengths that resolved to nothing where a token was expected.
    for(const el of document.querySelectorAll('.card,.chip,button,input,select,textarea,.modal')){const c=getComputedStyle(el); if(c.borderRadius==='' || c.padding==='') out.push(`empty computed on ${el.tagName} #${el.id||''}`);}
    return out;
  }, BAD.source);
}
(async()=>{
  const browser=await chromium.launch();
  for(const theme of ['light','dark']){
    const ctx=await browser.newContext({viewport:{width:1440,height:900}});
    await ctx.addInitScript((t)=>{try{localStorage.setItem('theme',t);}catch(e){}},theme);
    const page=await ctx.newPage();
    await page.goto(BASE+'/',{waitUntil:'domcontentloaded'});
    await page.waitForSelector('#lock-password',{state:'visible',timeout:20000});
    await page.fill('#lock-password',PW); await page.click('#lock-submit'); await page.waitForTimeout(2500);
    if(await page.$('#lock-password')&&await page.isVisible('#lock-password')){await page.fill('#lock-password',PW);await page.click('#lock-submit');await page.waitForTimeout(2500);}
    await page.evaluate(()=>document.getElementById('onboarding-overlay')?.remove());
    const found=new Set();
    for(const tab of TABS){await page.click(`[data-tab="${tab}"]`).catch(()=>{}); await page.waitForTimeout(700); for(const f of await scan(page))found.add(`[${tab}] ${f}`);}
    for(const sec of SECTIONS){await page.evaluate((s)=>{document.querySelector(`[data-settings-section="${s}"],[data-section="${s}"],#settings-nav [data-target="${s}"]`)?.click();},sec).catch(()=>{}); await page.waitForTimeout(300); for(const f of await scan(page))found.add(`[settings:${sec}] ${f}`);}
    console.log(`== ${theme}: ${found.size} invalid values`); for(const f of found)console.log('  '+f);
    await ctx.close();
  }
  await browser.close();
})();
