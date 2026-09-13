// The two catalogues, driven rather than read.
//
// `tests/test_feature_catalog.py` proves statically that no row names an id or
// a function that does not exist. What it cannot see is what happens when a
// row is actually run: a function that exists can still throw on the first
// line, and a row that throws is a row that does nothing when a person clicks
// it, which is the failure this pair of lists must not have.
//
// So this calls every `run` in both tables, in the browser, inside a try/catch,
// and reports the ones that throw along with the heading count the features
// dialog puts in front of the reader against the number of rows it drew.
//
// It is deliberately not a click-through: clicking would navigate, and every
// row after the first would be measured on a different screen. Calling the
// closures is the same code path the click handler takes.
const {boot}=require('./lib.js');

(async()=>{
  const {browser,page}=await boot();

  // The dialog first, because the count in its heading is the thing the report
  // was about ("105 things MemoryMap can do") and it is computed from the rows
  // that were just rendered.
  await page.evaluate(()=>switchTab('dashboard'));
  await page.waitForTimeout(900);
  await page.evaluate(()=>openFeatures());
  await page.waitForTimeout(1800); // the AI tool list is fetched on open
  const dialog=await page.evaluate(()=>({
    heading: document.getElementById('features-count').textContent,
    rows: document.querySelectorAll('#features-list .feature-row').length,
    groups: document.querySelectorAll('#features-list .features-group').length,
    staticRows: featureCatalog().reduce((n,g)=>n+g.items.length,0),
    staticGroups: featureCatalog().length,
  }));

  // Every row's own closure. `closeFeatures` inside some of them is what a
  // click would have done anyway.
  //
  // One row is deliberately not run: Lock. It works, which is the problem, it
  // locks the session, and every request after it comes back 401 "Locked", so
  // the run reports a hundred failures whose only cause is the one row that
  // did exactly what it promised. Its palette twin is skipped for the same
  // reason.
  //
  // A `run` is raced against a short timer rather than awaited outright: some
  // of them open a dialog and await the answer (`createConceptMap` asks for a
  // name), so awaiting the closure means waiting for a person who is not
  // there. What is being checked is whether the row throws on the way in, and
  // that has happened by the time the timer is up.
  const ran=await page.evaluate(async()=>{
    const out={features:[], palette:[], skipped:[]};
    const skip=(text)=>/^Lock$|Lock MemoryMap/.test(text);
    const tick=()=>new Promise((r)=>setTimeout(r,40));
    //: **Hidden, never removed.** The first version of this took every open
    //: `.modal-overlay` out of the DOM between rows, and most of the overlays
    //: in this app are static elements in index.html (the settings modal, the
    //: palette, the features browser, the page reader). Removing them meant
    //: every later row that opened one threw on a null, and the run reported
    //: 38 broken rows that were the sweep's own doing. Only a node that was
    //: built at runtime is removed, and it is recognised by not having an id
    //: the markup declares.
    const clear=()=>{
      for(const el of document.querySelectorAll('.modal-overlay, dialog[open]')){
        if(el.close){ el.close(); continue; }
        if(el.id) el.classList.add('hidden'); else el.remove();
      }
      document.getElementById('settings-modal')?.classList.add('hidden');
    };
    const race=(fn)=>Promise.race([
      Promise.resolve().then(fn),
      new Promise((r)=>setTimeout(r,300)),
    ]);
    for(const group of featureCatalog()){
      for(const item of group.items){
        if(skip(item.name)){ out.skipped.push(item.name); continue; }
        try{ await race(()=>item.run()); }
        catch(e){ out.features.push(`${group.group} / ${item.name}: ${String(e).slice(0,120)}`); }
        await tick();
        clear();
      }
    }
    for(const command of paletteCommands()){
      if(skip(command.label.replace(/^ph:[\w-]+\s*/,''))){ out.skipped.push(command.label); continue; }
      try{ await race(()=>command.run()); }
      catch(e){ out.palette.push(`${command.label}: ${String(e).slice(0,120)}`); }
      await tick();
      clear();
    }
    out.paletteCount=paletteCommands().length;
    return out;
  });

  console.log('DIALOG', JSON.stringify(dialog));
  console.log('PALETTE COMMANDS', ran.paletteCount);
  console.log('THREW (features):', ran.features.length, ran.features.join(' | '));
  console.log('THREW (palette):', ran.palette.length, ran.palette.join(' | '));
  console.log('SKIPPED (would lock the session):', JSON.stringify(ran.skipped));
  await browser.close();
})();
