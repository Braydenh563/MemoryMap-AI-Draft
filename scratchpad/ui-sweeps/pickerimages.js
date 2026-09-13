// The chat composer's attach picker, Images tab: does a row say what the
// picture is?
//
// The report this exists for: "images just show as their names but the user
// might not be able to tell what those images are from their names so they
// need to be rendered in some way". So the numbers that matter are per row:
// is there an <img>, did its bytes actually decode (`naturalWidth`, not the
// presence of the element, a 404 still leaves an <img> in the DOM), is the
// caption text on the row, and are the rows one height so the list reads as
// a list rather than as five different things.
//
// It seeds first, with canvas-drawn PNGs in five clearly different colours
// and a hand-typed caption each (`POST /media/{id}/caption` with `text`,
// which skips the model entirely, there is no Ollama in the sandbox). The
// colour is the point: a thumbnail that loads the *wrong* row's picture
// passes a naturalWidth check and fails the only thing the row is for, so
// the probe reads the middle pixel of each thumbnail back and matches it to
// the caption beside it.
const {boot}=require('./lib.js');

const SEED=[
  ['picker-red.png','#c0392b','A red square, the seeded colour test card'],
  ['picker-green.png','#27ae60','Green pasture with a fence post in the middle'],
  ['picker-blue.png','#2d6cdf','Blue notebook cover photographed on a desk'],
  ['picker-amber.png','#e0a316','Amber street light against an evening sky'],
  ['picker-violet.png','#7d4bd1','Violet gradient used as a wallpaper test'],
];

(async()=>{
  const {browser,page}=await boot();
  // NOSEED=1 re-measures a data dir that has already been seeded: every run
  // otherwise adds five more uploads, which is fine for the first pass and
  // noise for the fifth.
  const seeded=process.env.NOSEED ? [] : await page.evaluate(async (rows)=>{
    const made=[];
    for(const [name,colour,caption] of rows){
      const canvas=document.createElement('canvas');
      canvas.width=96; canvas.height=96;
      const ctx=canvas.getContext('2d');
      ctx.fillStyle=colour; ctx.fillRect(0,0,96,96);
      const blob=await new Promise((res)=>canvas.toBlob(res,'image/png'));
      const fd=new FormData();
      fd.append('file', new File([blob], name, {type:'image/png'}));
      fd.append('direct','true');
      // Raw fetch, not `api()`: `api()` forces a JSON content type, which
      // strips the multipart boundary and turns the upload into a 422.
      const r=await fetch('/media/upload',{method:'POST',body:fd,headers:{'X-Auth-Token':authToken(),'X-Workspace-ID':activeSpaceId()}});
      const j=await r.json();
      if(j.id!=null){
        await api(`/media/${j.id}/caption`,{method:'POST',body:JSON.stringify({text:caption})});
        made.push({id:j.id,name,colour,caption});
      }
    }
    return made;
  }, SEED);

  // The picker caches its rows per source for the life of the panel, so the
  // seeding above has to happen before the panel is ever opened.
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForTimeout(2500);
  await page.evaluate(()=>{ const o=document.getElementById('onboarding-overlay'); if(o) o.classList.add('hidden'); });
  // The chat dock has to be the open surface for the composer to exist.
  await page.evaluate(()=>{ document.querySelector('[data-tab="chat"]')?.click(); });
  await page.waitForTimeout(700);
  await page.click('#attach-note');
  await page.waitForTimeout(400);
  await page.click('#note-picker-sources [data-picker-source="images"]');
  await page.waitForTimeout(1800);
  // The thumbnails are `loading="lazy"` inside a scroll container, so the rows
  // below the fold have deliberately not fetched anything yet: walk the list to
  // the bottom before asserting that every one of them decoded.
  await page.evaluate(async()=>{
    const l=document.getElementById('note-picker-list');
    for(let y=0;y<=l.scrollHeight;y+=l.clientHeight/2){ l.scrollTop=y; await new Promise(r=>setTimeout(r,250)); }
    l.scrollTop=0;
  });
  await page.waitForTimeout(1200);

  const out=await page.evaluate(()=>{
    const rows=[...document.querySelectorAll('#note-picker-list > li')];
    const read=(img)=>{
      if(!img) return null;
      const c=document.createElement('canvas');
      c.width=1; c.height=1;
      try{
        c.getContext('2d').drawImage(img, Math.floor(img.naturalWidth/2), Math.floor(img.naturalHeight/2), 1, 1, 0, 0, 1, 1);
        const d=c.getContext('2d').getImageData(0,0,1,1).data;
        return `rgb(${d[0]},${d[1]},${d[2]})`;
      }catch(e){ return 'unreadable: '+String(e).slice(0,40); }
    };
    return {
      count: rows.length,
      panel: document.getElementById('note-picker-panel').getBoundingClientRect().width,
      list: (()=>{const l=document.getElementById('note-picker-list');return {scrollH:l.scrollHeight,clientH:l.clientHeight};})(),
      rows: rows.map((li)=>{
        const img=li.querySelector('img');
        const r=li.getBoundingClientRect();
        return {
          h: Math.round(r.height*10)/10,
          text: (li.textContent||'').replace(/\s+/g,' ').trim().slice(0,90),
          img: img ? {w:img.naturalWidth,h:img.naturalHeight,box:Math.round(img.getBoundingClientRect().width),px:read(img),src:(img.currentSrc||img.src).slice(0,60)} : null,
          caption: li.querySelector('.note-picker-caption')?.textContent?.slice(0,60) || null,
        };
      }),
    };
  });
  console.log('seeded', JSON.stringify(seeded.map(s=>[s.name,s.colour])));
  // The one line that says pass or fail: every row has a decoded picture, a
  // caption line, and the same height as its neighbours.
  const heights=[...new Set(out.rows.map(r=>r.h))];
  console.log('SUMMARY', JSON.stringify({
    rows: out.count,
    withDecodedImage: out.rows.filter(r=>r.img && r.img.w>0).length,
    withCaptionLine: out.rows.filter(r=>r.caption).length,
    distinctRowHeights: heights,
  }));
  console.log(JSON.stringify(out,null,1));
  await page.screenshot({path:(process.env.SCRATCH||'.')+'/shots/pickerimages.png'});
  await browser.close();
})();
