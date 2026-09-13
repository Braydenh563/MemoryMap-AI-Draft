// Phase 5.1 Settings pass: per section — nav labels that wrap, distinct
// heading→content gaps, distinct setting-row gaps/heights, label column
// widths, and the section's own padding. Numbers, so the pass is by count.
const {boot}=require('./lib.js');
const SECTIONS=['account','appearance','preferences','models','tools','skills','personas','templates','websearch','memory','tasks','data','logs','shortcuts','extras','help','about'];
(async()=>{
  const {browser,page}=await boot();
  await page.click('#settings-btn'); await page.waitForTimeout(600);
  const nav=await page.evaluate(()=>{const out=[];document.querySelectorAll('#settings-modal .modal-nav button, #settings-modal [data-section]').forEach(b=>{if(!b.checkVisibility())return;const r=b.getBoundingClientRect();const lh=parseFloat(getComputedStyle(b).lineHeight)||18;if(r.height>lh*1.6)out.push(`"${b.textContent.trim()}" h=${Math.round(r.height)}`);});const col=document.querySelector('#settings-modal .modal-nav, #settings-modal nav');return {wrapping:out,navW:col?Math.round(col.getBoundingClientRect().width):null};});
  console.log('nav width',nav.navW,'wrapping labels:',nav.wrapping.join(' | ')||'none');
  const all={h3gap:{},rowgap:{},rowh:{},labelw:{},pad:{}};
  for(const s of SECTIONS){
    const ok=await page.click(`#settings-modal [data-section="${s}"]`,{timeout:1500}).then(()=>true).catch(()=>false); if(!ok)continue; await page.waitForTimeout(300);
    const r=await page.evaluate(()=>{
      const vis=e=>e.checkVisibility&&e.checkVisibility();
      const sec=document.querySelector('#settings-modal .settings-section:not(.hidden)')||document.querySelector('#settings-modal .settings-body');
      const out={h3gap:{},rowgap:{},rowh:{},labelw:{},pad:{}};
      if(!sec)return out;
      const cs=getComputedStyle(sec); out.pad[`${cs.paddingTop}/${cs.paddingLeft}`]=1;
      sec.querySelectorAll('h3').forEach(h=>{if(!vis(h))return;let n=h.nextElementSibling;while(n&&!vis(n))n=n.nextElementSibling;if(!n)return;const g=Math.round(n.getBoundingClientRect().top-h.getBoundingClientRect().bottom);out.h3gap[g]=(out.h3gap[g]||0)+1;});
      sec.querySelectorAll('.setting-row').forEach(r=>{if(!vis(r))return;const c=getComputedStyle(r);const k=`gap=${c.gap} mb=${c.marginBottom} pad=${c.paddingTop}`;out.rowgap[k]=(out.rowgap[k]||0)+1;const lbl=r.querySelector('.setting-label');if(lbl){const w=Math.round(lbl.getBoundingClientRect().width);out.labelw[w]=(out.labelw[w]||0)+1;}});
      return out;
    });
    for(const k of Object.keys(all))for(const [v,n] of Object.entries(r[k]||{}))all[k][v]=(all[k][v]||0)+n;
    console.log(`== ${s}: h3→content gaps ${JSON.stringify(r.h3gap)} rows ${JSON.stringify(r.rowgap)} labelW ${JSON.stringify(r.labelw)} pad ${Object.keys(r.pad)}`);
  }
  console.log('TOTAL', JSON.stringify(all));
  await browser.close();
})();
