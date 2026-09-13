const {chromium}=require('/opt/node22/lib/node_modules/playwright');
const PW='testpassword123'; const BASE=process.env.BASE||'http://127.0.0.1:8781';
(async()=>{
  const browser=await chromium.launch(); const ctx=await browser.newContext({viewport:{width:1366,height:768}}); const page=await ctx.newPage();
  let bytes=0, reqs=0; page.on('response',async r=>{try{const b=await r.body();bytes+=b.length;}catch(e){}}); page.on('request',()=>reqs++);
  const t0=Date.now(); await page.goto(BASE+'/',{waitUntil:'domcontentloaded'});
  await page.waitForSelector('#lock-password',{state:'visible',timeout:20000});
  await page.fill('#lock-password',PW); await page.click('#lock-submit'); await page.waitForTimeout(3000);
  if(await page.$('#lock-password')&&await page.isVisible('#lock-password')){await page.fill('#lock-password',PW);await page.click('#lock-submit');await page.waitForTimeout(3000);}
  await page.evaluate(()=>document.getElementById('onboarding-overlay')?.remove());
  const loadBytes=bytes, loadReqs=reqs; const t1=Date.now();
  reqs=0; bytes=0; await page.waitForTimeout(60000); const idleReqs=reqs, idleBytes=bytes;
  const m=await page.evaluate(()=>{const els=[...document.querySelectorAll('*')]; const blur=els.filter(e=>{const c=getComputedStyle(e);return (c.backdropFilter&&c.backdropFilter!=='none')&&e.getBoundingClientRect().width>0;}); const area=blur.reduce((a,e)=>{const r=e.getBoundingClientRect();return a+r.width*r.height;},0); const nav=performance.getEntriesByType('navigation')[0]; return {elements:els.length, blurElements:blur.length, blurAreaPct:Math.round(100*area/(innerWidth*innerHeight)), heapMB:performance.memory?Math.round(performance.memory.usedJSHeapSize/1048576):null, domContentLoadedMs:Math.round(nav.domContentLoadedEventEnd), loadMs:Math.round(nav.loadEventEnd), timers:(window.__timers||null)};});
  // frame time while scrolling the notes list
  await page.click('[data-tab="notes"]'); await page.waitForTimeout(800);
  const frames=await page.evaluate(()=>new Promise(res=>{const ts=[];let last=performance.now();function f(t){ts.push(t-last);last=t;if(ts.length<120)requestAnimationFrame(f);else res(ts);}requestAnimationFrame(f);window.scrollBy(0,400);}));
  const sorted=[...frames].sort((a,b)=>a-b); const p95=sorted[Math.floor(sorted.length*0.95)];
  console.log(JSON.stringify({loadKB:Math.round(loadBytes/1024), loadRequests:loadReqs, unlockToReadyMs:t1-t0, idleRequestsPerMin:idleReqs, idleKBPerMin:Math.round(idleBytes/1024), ...m, frameP95Ms:Math.round(p95*10)/10}));
  await browser.close();
})();
