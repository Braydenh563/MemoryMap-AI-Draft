// Every menu's rows: one height, no fill at rest, and nothing clipped.
// The clip check is the one CLAUDE.md says cost six rounds on the nav-history
// popup: `scrollHeight > clientHeight` on a row is the number that settles
// "the text looks garbled", so it runs on every row of every menu here.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const rows=async(label,sel)=>{
    await page.mouse.move(1430,890); await page.waitForTimeout(150);
    const r=await page.evaluate((s)=>{
      const el=document.querySelector(s); if(!el) return null;
      const items=[...el.querySelectorAll('button,a,[role="menuitem"],[role="option"]')].filter(e=>e.checkVisibility&&e.checkVisibility());
      const filled=items.filter(e=>{const m=getComputedStyle(e).backgroundColor.match(/rgba?\(([^)]+)\)/);if(!m)return false;const p=m[1].split(/[\s,\/]+/).map(Number);return (p.length<4?1:p[3])>0.01;});
      const clipped=items.filter(e=>e.scrollHeight>e.clientHeight+1).map(e=>`${e.textContent.trim().slice(0,18)} ${e.scrollHeight}>${e.clientHeight}`);
      return {n:items.length, h:[...new Set(items.map(e=>+e.getBoundingClientRect().height.toFixed(2)))], filled:filled.length, clipped};
    }, sel);
    console.log(`  ${label}: ${r? `rows=${r.n} h=${JSON.stringify(r.h)} filled=${r.filled} clipped=${r.clipped.length?JSON.stringify(r.clipped):0}` : 'not open'}`);
  };
  console.log('== theme', process.env.THEME||'light');
  await page.click('#status-nav-history').catch(()=>{}); await page.waitForTimeout(500);
  await rows('nav-history','#status-nav-history-menu');
  await page.keyboard.press('Escape'); await page.waitForTimeout(200);
  await page.click('[data-tab="notes"]'); await page.waitForTimeout(900);
  const kebab=await page.$('.entry-list .menu-wrap > button');
  if(kebab){ await kebab.click(); await page.waitForTimeout(400); await rows('note kebab','.action-menu:not(.hidden)'); await page.keyboard.press('Escape'); await page.waitForTimeout(200); }
  await page.click('#notes-more-menu > summary, #notes-more-menu').catch(()=>{}); await page.waitForTimeout(400);
  await rows('notes more','#notes-more-menu .doc-dock-menu-list, #notes-more-menu .action-menu');
  await page.keyboard.press('Escape'); await page.waitForTimeout(200);
  await page.click('[data-tab="graph"]'); await page.waitForTimeout(900);
  await page.click('#graph-more-menu > summary, #graph-more-menu').catch(()=>{}); await page.waitForTimeout(400);
  await rows('graph more','#graph-more-menu .doc-dock-menu-list, #graph-more-menu .action-menu');
  await page.keyboard.press('Escape'); await page.waitForTimeout(200);
  const opener=await page.$('.select-shell .select-opener:visible');
  if(opener){ await opener.click({timeout:4000}).catch(()=>{}); await page.waitForTimeout(400); await rows('a select list','.select-menu:not(.hidden)'); await page.keyboard.press('Escape'); }
  else console.log('  a select list: none visible');
  await browser.close();
})();
