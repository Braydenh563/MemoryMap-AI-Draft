// The two dialogs the owner flagged as off-recipe, against the modal recipe:
// a title row, a body, a footer whose last child is the one primary.
//
// The reference is the Settings modal, the app's own biggest dialog.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const probe=async(label,cardSel)=>{
    await page.mouse.move(1430,890); await page.waitForTimeout(200);
    const r=await page.evaluate((s)=>{
      const card=[...document.querySelectorAll(s)].find(e=>e.checkVisibility&&e.checkVisibility());
      if(!card) return null;
      const c=getComputedStyle(card);
      const kids=[...card.children].filter(e=>e.checkVisibility&&e.checkVisibility());
      const nonTransparent=(x)=>{const m=x.match(/rgba?\(([^)]+)\)/);if(!m)return true;const p=m[1].split(/[\s,\/]+/).map(Number);return (p.length<4?1:p[3])>0.01;};
      const buttons=[...card.querySelectorAll('button')].filter(e=>e.checkVisibility&&e.checkVisibility());
      const filled=buttons.filter(e=>nonTransparent(getComputedStyle(e).backgroundColor)&&!e.closest('.seg'));
      const foot=kids[kids.length-1];
      return {
        card:`w=${card.getBoundingClientRect().width.toFixed(0)} pad=${c.padding} gap=${c.gap} radius=${c.borderTopLeftRadius}`,
        heading: !!card.querySelector('h1,h2,h3,.modal-title'),
        children: kids.map(e=>`${e.tagName.toLowerCase()}${e.className?'.'+String(e.className).trim().split(/\s+/).slice(0,2).join('.'):''}`),
        buttons: buttons.length,
        filled: filled.map(e=>e.textContent.trim().slice(0,16)),
        footIsRow: foot? /row|actions|foot/.test(String(foot.className)) : false,
        footLast: foot? (()=>{const b=[...foot.querySelectorAll('button')].filter(e=>e.checkVisibility&&e.checkVisibility());return b.length?b[b.length-1].textContent.trim().slice(0,16):'(no buttons)';})() : '(no footer)',
        footLastIsFilled: foot? (()=>{const b=[...foot.querySelectorAll('button')].filter(e=>e.checkVisibility&&e.checkVisibility());return b.length? nonTransparent(getComputedStyle(b[b.length-1]).backgroundColor):false;})() : false,
        heights:[...new Set(buttons.map(e=>+e.getBoundingClientRect().height.toFixed(1)))].sort((a,b)=>a-b),
        offHeight: buttons.filter(e=>Math.abs(e.getBoundingClientRect().height-36)>1).slice(0,6).map(e=>`"${(e.getAttribute('aria-label')||e.textContent.trim()).slice(0,16)}" ${e.getBoundingClientRect().height.toFixed(1)} cls=${e.className}`),
      };
    }, cardSel);
    if(!r){ console.log(`  ${label}: not open`); return; }
    console.log(`  ${label}`);
    console.log(`      ${r.card}`);
    console.log(`      heading=${r.heading} children=${JSON.stringify(r.children)}`);
    console.log(`      buttons=${r.buttons} heights=${JSON.stringify(r.heights)} filled=${JSON.stringify(r.filled)}`);
    console.log(`      footer is a row=${r.footIsRow} last button="${r.footLast}" last is the primary=${r.footLastIsFilled}`);
    if(r.offHeight&&r.offHeight.length) { console.log('      not on 36px:'); r.offHeight.forEach(x=>console.log('        '+x)); }
  };

  // Reference
  await page.click('#settings-btn'); await page.waitForTimeout(700);
  await probe('settings modal (the reference)','#settings-modal .modal-card');
  await page.keyboard.press('Escape'); await page.waitForTimeout(400);

  // New board dialog
  await page.click('[data-tab="library"]'); await page.waitForTimeout(800);
  await page.click('[data-target="library-view-whiteboard"]',{timeout:4000}).catch(()=>{}); await page.waitForTimeout(1200);
  await page.click('#wb-boards-new',{timeout:4000}).catch(()=>{}); await page.waitForTimeout(700);
  await probe('new board dialog','.confirm-card');
  await page.keyboard.press('Escape'); await page.waitForTimeout(400);

  // Widgets editor
  await page.click('[data-tab="dashboard"]'); await page.waitForTimeout(900);
  await page.click('#dash-widgets-open',{timeout:4000}).catch(()=>{}); await page.waitForTimeout(800);
  // A native `<dialog>`, not a `.modal-overlay` + `.modal-card`: the first
  // version of this probe looked for the overlay shape every other dialog in
  // the app uses and reported "not open" while the dialog was open on screen.
  // That difference is itself part of what "off the modal recipe" means here.
  await probe('widgets editor','#dash-widgets-dialog[open]');
  const rows=await page.evaluate(()=>{
    const card=document.querySelector('#dash-widgets-dialog[open]');
    if(!card) return null;
    const rowEls=[...card.querySelectorAll('.dash-widget-row')].filter(e=>e.checkVisibility&&e.checkVisibility());
    return rowEls.slice(0,2).map(e=>{
      const b=[...e.querySelectorAll('button')].filter(x=>x.checkVisibility&&x.checkVisibility());
      return b.map(x=>`  "${(x.getAttribute('aria-label')||x.title||x.textContent.trim()).slice(0,12)}" ${x.getBoundingClientRect().width.toFixed(0)}x${x.getBoundingClientRect().height.toFixed(0)} bg=${getComputedStyle(x).backgroundColor} cls=${x.className}`).join('\n      ');
    });
  });
  if(rows) { console.log('      per-row buttons:'); rows.forEach(x=>console.log('        '+x)); }
  await browser.close();
})();
