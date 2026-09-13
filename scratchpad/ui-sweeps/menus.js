// Open every floating surface the popover shell covers and measure it:
// computed fill/edge/radius/shadow/filter, plus a screenshot of each.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page,OUT}=await boot();
  const sig=async(sel)=>page.evaluate((sel)=>{const e=document.querySelector(sel);if(!e)return null;const c=getComputedStyle(e);const r=e.getBoundingClientRect();return `${sel}: bg=${c.backgroundColor} bd=${c.borderTopWidth} ${c.borderTopColor} r=${c.borderTopLeftRadius} sh=${c.boxShadow==='none'?'none':'shadow'} filter=${c.backdropFilter} vis=${c.visibility} box=${Math.round(r.width)}x${Math.round(r.height)}`;},sel);
  await page.click('#notif-btn'); await page.waitForTimeout(400); console.log(await sig('.notif-panel')); await page.screenshot({path:OUT+'/menu-notif.png'}); await page.keyboard.press('Escape'); await page.waitForTimeout(200);
  await page.click('[data-tab="notes"]'); await page.waitForTimeout(600);
  await page.click('#search-help').catch(()=>{}); await page.waitForTimeout(400); console.log(await sig('.help-popover')); await page.screenshot({path:OUT+'/menu-help.png'}); await page.keyboard.press('Escape'); await page.waitForTimeout(200);
  const kebab=await page.$('.entry-list .menu-wrap > button, .entry-list .menu-wrap button'); if(kebab){await kebab.click(); await page.waitForTimeout(400); console.log(await sig('.action-menu:not(.hidden)')); await page.screenshot({path:OUT+'/menu-kebab.png'}); await page.keyboard.press('Escape'); await page.waitForTimeout(200);} else console.log('no kebab found');
  await page.click('#status-nav-history').catch(()=>{}); await page.waitForTimeout(400); console.log(await sig('#status-nav-history-menu')); await page.screenshot({path:OUT+'/menu-navhist.png'}); await page.keyboard.press('Escape'); await page.waitForTimeout(200);
  await page.click('[data-tab="chat"]'); await page.waitForTimeout(600);
  await page.click('#chat-active-model').catch(()=>{}); await page.waitForTimeout(400); console.log(await sig('.chat-model-panel')); await page.screenshot({path:OUT+'/menu-model.png'}); await page.keyboard.press('Escape');
  const sel=await page.$('.select-opener'); if(sel){await sel.click(); await page.waitForTimeout(400); console.log(await sig('.select-menu')); await page.screenshot({path:OUT+'/menu-select.png'}); await page.keyboard.press('Escape');}
  await browser.close();
})();
