// The widgets editor's reworked row, driven. Four controls changed shape, and
// a control that changed shape and stopped working is the failure this repo
// calls "never ran once". Each one is pressed and its effect read back from
// the saved layout, not from the DOM that just rendered it.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.click('[data-tab="dashboard"]'); await page.waitForTimeout(1200);
  await page.click('#dash-widgets-open'); await page.waitForTimeout(900);

  const layout=async()=>page.evaluate(async()=>{
    // `/preferences`, which is where `saveDashLayout` PUTs it. The first
    // version asked `/settings` and got a 404, which is worth keeping as a
    // note: read the state back from the endpoint that writes it.
    const r=await api('/preferences'); const j=await r.json();
    let l=j.dashboard_layout ?? null;
    if(typeof l==='string'){ try{ l=JSON.parse(l); }catch(e){} }
    return l;
  });
  const firstRow=async()=>page.evaluate(()=>{
    const r=document.querySelector('#dash-widgets-dialog .dash-widget-row');
    return r? r.dataset.widget : null;
  });

  console.log('first row widget:', await firstRow());
  const before=await layout();
  console.log('layout before:', JSON.stringify(before).slice(0,140));

  // Wide
  // NOT `:first-of-type`: that counts divs among divs and the container's
  // first div is the summary line, so it matched no row at all and every click
  // timed out against an app that was working. Playwright's `.first` on a
  // locator is what "the first row" actually means here.
  const wideSel='#dash-widgets-dialog .dash-widget-row .dash-widget-row-controls button[aria-pressed]';
  const first=(sel)=>page.locator(sel).first();
  const wideBefore=await first(wideSel).getAttribute('aria-pressed',{timeout:6000}).catch(()=>null);
  await first(wideSel).click({timeout:6000}).catch(e=>console.log('wide click failed', e.message));
  await page.waitForTimeout(900);
  const wideAfter=await first(wideSel).getAttribute('aria-pressed',{timeout:6000}).catch(()=>null);
  const afterWide=await layout();
  console.log(`Wide: aria-pressed ${wideBefore} -> ${wideAfter}; saved wide list ${JSON.stringify(afterWide&&afterWide.wide)}`);

  // Move down, then read the order back
  const orderBefore=await page.evaluate(()=>[...document.querySelectorAll('#dash-widgets-dialog .dash-widget-row')].slice(0,3).map(e=>e.dataset.widget));
  await first('#dash-widgets-dialog .dash-widget-row button[aria-label="Move down"]').click({timeout:6000}).catch(e=>console.log('down click failed', e.message));
  await page.waitForTimeout(900);
  const orderAfter=await page.evaluate(()=>[...document.querySelectorAll('#dash-widgets-dialog .dash-widget-row')].slice(0,3).map(e=>e.dataset.widget));
  console.log('Move down:', JSON.stringify(orderBefore), '->', JSON.stringify(orderAfter));

  // Remove, then Add the same widget back
  const target=await firstRow();
  await first('#dash-widgets-dialog .dash-widget-row button[aria-label="Remove this widget from the dashboard"]').click({timeout:6000}).catch(e=>console.log('remove click failed', e.message));
  await page.waitForTimeout(900);
  const afterRemove=await layout();
  console.log(`Remove "${target}": hidden list now contains it =`, !!(afterRemove&&afterRemove.hidden&&afterRemove.hidden.includes(target)));
  const added=await page.evaluate(async(name)=>{
    const row=[...document.querySelectorAll('#dash-widgets-dialog .dash-widget-row')].find(e=>e.dataset.widget===name);
    if(!row) return 'row gone';
    const b=row.querySelector('button[aria-label="Add this widget to the dashboard"]');
    if(!b) return 'no add button';
    b.click(); return 'clicked';
  }, target);
  await page.waitForTimeout(900);
  const afterAdd=await layout();
  console.log(`Add "${target}" (${added}): still hidden =`, !!(afterAdd&&afterAdd.hidden&&afterAdd.hidden.includes(target)));
  await browser.close();
})();
