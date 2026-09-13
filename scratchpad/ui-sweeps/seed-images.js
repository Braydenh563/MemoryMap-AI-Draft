// Two real PNGs through `POST /media/upload?direct=true`, and one of them
// referenced from a note so the "Used in" chip has something to name.
// consistency.md item 7 could not measure the image-card chips because the
// seeded notebook had no images; this is what gives it some.
const {boot}=require('./lib.js');

// A 2x2 PNG, built here rather than shipped as a binary: the sweep scripts are
// text and stay text.
const PNG='iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8DAwMDAxMDAwAAADwEBAAyEAvUAAAAASUVORK5CYII=';

(async()=>{
  const {browser,page}=await boot();
  const out=await page.evaluate(async(b64)=>{
    const bytes=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));
    const names=['sweep-one.png','sweep-two.png'];
    const urls=[];
    for(const name of names){
      const fd=new FormData();
      fd.append('file', new File([bytes], name, {type:'image/png'}));
      fd.append('direct','true');
      // Raw fetch, not `api()`: `api()` forces `Content-Type: application/json`,
      // which strips the multipart boundary and makes the upload a 422.
      const r=await fetch('/media/upload',{method:'POST', body: fd, headers:{'X-Auth-Token':authToken(),'X-Workspace-ID':activeSpaceId()}});
      const j=await r.json();
      urls.push(j.url||j.path||JSON.stringify(j).slice(0,80));
    }
    // One reference, so a usage chip renders on at least one card.
    let noteStatus='skipped';
    if(urls[0] && typeof urls[0]==='string' && urls[0].startsWith('/')){
      const r=await api('/entries',{method:'POST',body:JSON.stringify({content:`# Sweep image note\n\n![sweep one](${urls[0]})`,tags:['sweep']})});
      noteStatus=r.status;
    }
    return {urls, noteStatus};
  }, PNG);
  console.log(JSON.stringify(out));
  await browser.close();
})();
