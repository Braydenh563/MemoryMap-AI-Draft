// Does a selector match what I think it matches, in the running app? Cheaper
// than another round of guessing at a rule that had no effect.
//   SELS='["a","b"]' node selcheck.js
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.click('#settings-btn').catch(()=>{}); await page.waitForTimeout(700);
  await page.click('#settings-modal [data-section="skills"]',{timeout:3000}).catch(()=>{});
  await page.waitForTimeout(500);
  const sels=JSON.parse(process.env.SELS||'[]');
  const r=await page.evaluate((list)=>{
    const out={};
    for(const s of list){ try{ out[s]=document.querySelectorAll(s).length; }catch(e){ out[s]='invalid: '+e.message; } }
    const h=[...document.querySelectorAll('#settings-modal .settings-section:not(.hidden) h3')][0];
    out['__first h3 path']=h? (()=>{const p=[];for(let e=h;e&&e!==document.body;e=e.parentElement)p.unshift(`${e.tagName.toLowerCase()}${e.id?'#'+e.id:''}${e.className?'.'+String(e.className).trim().split(/\s+/).slice(0,3).join('.'):''}`);return p.join(' > ');})() : 'none';
    out['__first h3 padding-left']=h?getComputedStyle(h).paddingLeft:'-';
    return out;
  }, sels);
  console.log(JSON.stringify(r,null,1));
  await browser.close();
})();
