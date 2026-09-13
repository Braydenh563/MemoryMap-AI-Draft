// The rename-in-place flow, now that the filename is an overlay caption on
// the thumbnail (INBOX 56): the input has to be legible over the scrim and
// sit exactly where the name was.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot({viewport:{width:1440,height:900}});
  const errs=[]; page.on('pageerror',e=>errs.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errs.push(m.text().slice(0,140));});
  await page.evaluate(()=>switchTab('library'));
  await page.waitForTimeout(1200);
  await page.evaluate(()=>{document.querySelector('#library-subtabs [data-media-kind="images"]')?.click();});
  await page.waitForTimeout(1500);
  const before=await page.evaluate(()=>{
    const cap=document.querySelector('.library-image-frame figcaption');
    const r=cap.getBoundingClientRect();
    return {text:cap.textContent, x:+r.x.toFixed(1), y:+r.y.toFixed(1), w:+r.width.toFixed(1), h:+r.height.toFixed(1)};
  });
  // Rename lives in the tile's kebab (the buttons themselves are detached
  // objects the menu rows click), so the menu has to be opened first.
  await page.evaluate(()=>{document.querySelector('.library-image-actions button')?.click();});
  await page.waitForTimeout(400);
  const found=await page.evaluate(()=>{
    // The chat sidebar has a "Rename this chat" row of its own, so the
    // search is scoped to the menu the tile just opened.
    const menu=[...document.querySelectorAll('.action-menu')].find(m=>!m.classList.contains('hidden'));
    const row=[...(menu||document).querySelectorAll('button, [role="menuitem"]')]
      .find(e=>e.textContent.trim()==='Rename');
    if(!row) return 'rows: '+[...(menu||document).querySelectorAll('button')].map(b=>b.textContent.trim()).slice(0,8).join('|');
    if(!row) return 'no rename row';
    row.click();
    return {text:row.textContent.trim()};
  });
  console.log('rename row', JSON.stringify(found));
  await page.waitForTimeout(400);
  const editing=await page.evaluate(()=>{
    const box=document.querySelector('.library-image-rename-input');
    if(!box) return null;
    const c=getComputedStyle(box); const r=box.getBoundingClientRect();
    const cap=box.closest('figcaption').getBoundingClientRect();
    return {value:box.value, color:c.color, x:+r.x.toFixed(1), y:+r.y.toFixed(1),
      w:+r.width.toFixed(1), h:+r.height.toFixed(1),
      capMoved:{dx:+(cap.x-0).toFixed(1)}, visible:box.checkVisibility()};
  });
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  const after=await page.evaluate(()=>document.querySelector('.library-image-frame figcaption')?.textContent);
  console.log(JSON.stringify({before, editing, after, errors:errs}, null, 1));
  const clip=await page.evaluate(()=>{const f=document.querySelector('.library-image-frame').getBoundingClientRect();
    return {x:f.x-4,y:f.y-4,width:f.width+8,height:f.height+8};});
  await page.screenshot({path:`${process.env.SCRATCH||'.'}/shots/librename.png`, clip});
  await browser.close();
})();
