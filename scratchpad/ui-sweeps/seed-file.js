// One non-image upload, so the Files sub-tab's rows can be measured too: the
// image cards and the file rows share one tile builder, and a change to the
// cards has to be checked against both.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const out=await page.evaluate(async()=>{
    // A hand-written one-page PDF: the upload route takes images and PDFs
    // only, and the sweeps stay text rather than shipping a binary.
    const body='BT /F1 12 Tf 40 120 Td (Weekly review) Tj ET';
    const objs=[
      '<</Type/Catalog/Pages 2 0 R>>',
      '<</Type/Pages/Kids[3 0 R]/Count 1>>',
      '<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>',
      `<</Length ${body.length}>>\nstream\n${body}\nendstream`,
      '<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>',
    ];
    let pdf='%PDF-1.4\n'; const offsets=[];
    objs.forEach((o,i)=>{ offsets.push(pdf.length); pdf+=`${i+1} 0 obj\n${o}\nendobj\n`; });
    const xref=pdf.length;
    pdf+=`xref\n0 ${objs.length+1}\n0000000000 65535 f \n`;
    for(const off of offsets) pdf+=String(off).padStart(10,'0')+' 00000 n \n';
    pdf+=`trailer\n<</Size ${objs.length+1}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`;
    const fd=new FormData();
    fd.append('file', new File([pdf], 'sweep-notes.pdf', {type:'application/pdf'}));
    fd.append('direct','true');
    // Raw fetch, not `api()`: `api()` forces a JSON content type, which
    // strips the multipart boundary and makes the upload a 422.
    const r=await fetch('/media/upload',{method:'POST', body: fd, headers:{'X-Auth-Token':authToken(),'X-Workspace-ID':activeSpaceId()}});
    return await r.json();
  });
  console.log(JSON.stringify(out).slice(0,200));
  await browser.close();
})();
