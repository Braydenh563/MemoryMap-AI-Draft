const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  page.on('response', async (r) => {
    if (r.status() === 422) console.log('422 ON', r.url(), '->', (await r.text()).slice(0,300));
  });
  const out=await page.evaluate(async()=>{
    // Make a map with one node through the app's own helpers.
    await switchTab('library');
    await new Promise(r=>setTimeout(r,600));
    const h={'X-Auth-Token':localStorage.getItem('token')||'','Content-Type':'application/json'};
    const b=await (await fetch('/whiteboard/boards',{method:'POST',headers:h,
      body:JSON.stringify({title:'Shape probe',type:'map'})})).json();
    const n=await (await fetch(`/whiteboard/boards/${b.id}/nodes`,{method:'POST',headers:h,
      body:JSON.stringify({label:'Root'})})).json().catch(()=>null);
    const results={};
    for (const shape of ['pill','rect','none',null]) {
      const body={...n, data:{...(n.data||{}), shape}};
      const r=await fetch(`/whiteboard/boards/${b.id}/objects/${n.id}`,{method:'PUT',headers:h,
        body:JSON.stringify(body)});
      results[String(shape)]={status:r.status, detail:r.ok?null:(await r.text()).slice(0,240)};
    }
    return {node:n, results};
  });
  console.log(JSON.stringify(out,null,1).slice(0,2000));
  await browser.close();
})();
