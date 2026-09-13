// Phase 1 (mass and layout) measurements: the shell's gutters and heights, the
// gap between a sub-tab strip and its content, grid gaps, card padding by
// width, hero height, sidebar widths and head-row heights. One table per tab.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const px=v=>Math.round(v*10)/10;
  for(const t of ['dashboard','notes','library','chat','graph','timeline','reminders']){
    await page.click(`[data-tab="${t}"]`).catch(()=>{});await page.waitForTimeout(700);
    const r=await page.evaluate(()=>{
      const vis=e=>e&&e.checkVisibility&&e.checkVisibility();
      const rect=e=>e?e.getBoundingClientRect():null;
      const cs=e=>e?getComputedStyle(e):null;
      const out={};
      const top=document.querySelector('header, .top-bar, #top-bar, .topbar')||document.querySelector('nav')?.parentElement;
      const status=document.querySelector('.status-bar, #status-bar, footer');
      const page=document.querySelector('.tab-page:not(.hidden)');
      const logo=document.querySelector('.brand, .brand-mark, #brand, .app-brand, header img, header svg');
      const firstTab=document.querySelector('[data-tab]');
      const cards=[...document.querySelectorAll('.tab-page:not(.hidden) .card')].filter(vis);
      const firstCard=cards[0];
      const sidebar=document.querySelector('.tab-page:not(.hidden) .sidebar-panel, .tab-page:not(.hidden) aside.card');
      out.topBar=top?`h=${Math.round(rect(top).height)} padL=${cs(top).paddingLeft}`:null;
      out.statusBar=status?`h=${Math.round(rect(status).height)} padL=${cs(status).paddingLeft}`:null;
      out.pagePad=page?`${cs(page).paddingTop}/${cs(page).paddingRight}/${cs(page).paddingBottom}/${cs(page).paddingLeft} gap=${cs(page).gap}`:null;
      out.leftEdges={logo:logo?Math.round(rect(logo).left):null, firstTab:firstTab?Math.round(rect(firstTab).left):null, sidebar:sidebar?Math.round(rect(sidebar).left):null, firstCard:firstCard?Math.round(rect(firstCard).left):null, statusFirst:status?Math.round(rect(status.firstElementChild).left):null};
      // sub-tab strip → content gap
      const strip=document.querySelector('.tab-page:not(.hidden) .notes-subtabs, .tab-page:not(.hidden) .library-subtabs, .tab-page:not(.hidden) [role="tablist"].seg');
      if(strip&&vis(strip)){let n=strip.parentElement.nextElementSibling||strip.nextElementSibling; while(n&&!vis(n))n=n.nextElementSibling; if(n) out.stripToContent=Math.round(rect(n).top-rect(strip).bottom);}
      // grids
      const grid=document.querySelector('#dash-grid, .library-grid, .dash-widgets');
      if(grid&&vis(grid)) out.gridGap=`${grid.id||grid.className} gap=${cs(grid).gap} colGap=${cs(grid).columnGap} rowGap=${cs(grid).rowGap}`;
      // cards: padding by width
      const pads={};
      cards.forEach(c=>{const w=Math.round(rect(c).width);const s=cs(c);const k=`${s.paddingTop}/${s.paddingLeft}`;const b=w>=1100?'wide':w>=600?'mid':'narrow';pads[b+':'+k]=(pads[b+':'+k]||0)+1;});
      out.cardPads=pads;
      const nested=cards.filter(c=>c.parentElement.closest('.card')).map(c=>`${c.className.split(' ').slice(0,2).join('.')} bd=${cs(c).borderTopWidth} ${cs(c).borderTopColor} bg=${cs(c).backgroundColor}`);
      out.cardInCard=nested.slice(0,6);
      const hero=document.querySelector('#dash-hero'); if(hero&&vis(hero)) out.hero=`h=${Math.round(rect(hero).height)} pad=${cs(hero).paddingTop}/${cs(hero).paddingLeft}`;
      if(sidebar) out.sidebar=`w=${Math.round(rect(sidebar).width)} pad=${cs(sidebar).paddingTop}/${cs(sidebar).paddingLeft}`;
      const heads=[...document.querySelectorAll('.tab-page:not(.hidden) .sidebar-head, .tab-page:not(.hidden) .library-head, .tab-page:not(.hidden) .reminders-head, .tab-page:not(.hidden) .card > .row.space-between, .tab-page:not(.hidden) .dash-widget > .row, .tab-page:not(.hidden) .widget-head')].filter(vis);
      out.headRows=heads.map(h=>`${[...h.classList].slice(0,3).join('.')} h=${Math.round(rect(h).height)} mb=${cs(h).marginBottom}`);
      const lists=[...document.querySelectorAll('.tab-page:not(.hidden) .sidebar-panel li, .tab-page:not(.hidden) aside li')].filter(vis).slice(0,3);
      out.sidebarRows=lists.map(l=>`h=${Math.round(rect(l).height)} bd=${cs(l).borderTopWidth} ${cs(l).borderTopColor}`);
      return out;
    });
    console.log('== '+t); for(const [k,v] of Object.entries(r)) console.log('  '+k+': '+(typeof v==='string'?v:JSON.stringify(v)));
  }
  await browser.close();
})();
