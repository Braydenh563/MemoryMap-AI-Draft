const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  // A: AI skills sidebar height inside Library
  await page.click('[data-tab="library"]').catch(()=>{}); await page.waitForTimeout(1200);
  const skills=await page.evaluate(async()=>{
    const btn=document.querySelector('[data-library-view="skills"], #library-subtab-skills, [data-subtab="skills"]');
    if(btn) btn.click();
    await new Promise(r=>setTimeout(r,900));
    const sb=document.getElementById('skills-sidebar');
    const host=document.getElementById('library-view-skills');
    if(!sb||!host) return {found:false, sb:!!sb, host:!!host};
    const s=sb.getBoundingClientRect(), h=host.getBoundingClientRect();
    const cs=getComputedStyle(sb);
    return {found:true, sbH:Math.round(s.height), hostH:Math.round(h.height),
      gapBottom:Math.round(h.bottom-s.bottom), gapTop:Math.round(s.top-h.top),
      height:cs.height, alignSelf:cs.alignSelf, parentDisplay:getComputedStyle(sb.parentElement).display,
      parentAlign:getComputedStyle(sb.parentElement).alignItems};
  });
  // B: tab corners
  const tabs=await page.evaluate(()=>{
    const out={};
    for(const id of ['tab-btn-dashboard','tab-btn-notes','tab-btn-library']){
      const e=document.getElementById(id); if(!e) continue;
      const c=getComputedStyle(e);
      out[id]={radius:c.borderRadius, h:Math.round(e.getBoundingClientRect().height)};
    }
    const bar=document.getElementById('tab-bar');
    out.bar=bar?{radius:getComputedStyle(bar).borderRadius, pad:getComputedStyle(bar).padding}:null;
    const subs=document.querySelector('.library-subtabs, .notes-subtabs');
    out.subtabs=subs?{cls:subs.className, radius:getComputedStyle(subs).borderRadius,
      child:(()=>{const b=subs.querySelector('button');return b?getComputedStyle(b).borderRadius:null;})()}:null;
    return out;
  });
  // C: chat panel shadow
  await page.click('[data-tab="chat"]').catch(()=>{}); await page.waitForTimeout(1000);
  const chat=await page.evaluate(()=>{
    const out={};
    for(const sel of ['.chat-panel','#chat-messages','.chat-transcript','.chat-dock','.conv-sidebar','#tab-chat .card']){
      const e=document.querySelector(sel); if(!e) continue;
      const c=getComputedStyle(e);
      out[sel]={shadow:c.boxShadow==='none'?'none':c.boxShadow.slice(0,60), radius:c.borderRadius};
    }
    return out;
  });
  console.log(JSON.stringify({skills, tabs, chat},null,1));
  await browser.close();
})();
