const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const bodies=[];
  page.on('response', async (r) => {
    if (r.status() >= 400) { try { bodies.push({url:r.url(), status:r.status(), body:(await r.text()).slice(0,500)}); } catch(e){} }
  });
  const out = await page.evaluate(async () => {
    switchTab('library');
    await new Promise(r=>setTimeout(r,800));
    // Use the app's own map creation path rather than guessing endpoints.
    const made = await (typeof wbCreateBoard === 'function'
      ? wbCreateBoard({title:'Shape probe', type:'map'})
      : null);
    return { made: made ? (made.id || made) : 'no wbCreateBoard',
             fns: Object.keys(window).filter(k=>/^wbCreate|^wbNewMap|^wbAddTopic/.test(k)) };
  });
  console.log(JSON.stringify(out));
  console.log(JSON.stringify(bodies, null, 1).slice(0, 1500));
  await browser.close();
})();
