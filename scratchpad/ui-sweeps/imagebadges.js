// The image cards' model badges. They only render once a vision model has
// actually read a picture, which no offline sweep can arrange, so the sweep
// gives them text and unhides them instead: the question is what the CSS does
// to them, and that does not need a real model run.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  await page.click('[data-tab="library"]'); await page.waitForTimeout(900);
  await page.click('[data-target="library-view-media"]',{timeout:4000}).catch(()=>{});
  await page.waitForTimeout(1600);
  await page.mouse.move(1430,890); await page.waitForTimeout(200);
  const r=await page.evaluate(()=>{
    for(const e of document.querySelectorAll('.library-image-caption-badge, .library-image-vision-ocr-badge')){
      e.classList.remove('hidden'); if(!e.textContent.trim()) e.textContent='llava:7b';
    }
    const sig=(e)=>{const c=getComputedStyle(e);return `${[...e.classList].join('.')} h=${e.getBoundingClientRect().height.toFixed(2)} bg=${c.backgroundColor} border=${c.borderTopWidth} ${c.borderTopColor} radius=${c.borderTopLeftRadius} pad=${c.paddingTop}/${c.paddingLeft} fs=${c.fontSize} color=${c.color} weight=${c.fontWeight}`;};
    const badges=[...document.querySelectorAll('.library-image-caption-badge, .library-image-vision-ocr-badge')].filter(e=>e.checkVisibility&&e.checkVisibility());
    const usage=[...document.querySelectorAll('.library-image-usage-chip')].filter(e=>e.checkVisibility&&e.checkVisibility());
    return {
      phantom: document.querySelectorAll('.library-image-model-chip').length,
      badges: badges.map(sig),
      usage: usage.map(sig),
    };
  });
  console.log('elements carrying .library-image-model-chip anywhere in the DOM:', r.phantom);
  console.log('badges:'); r.badges.forEach(b=>console.log('  '+b));
  console.log('usage chip (the reference this family was brought onto):'); r.usage.forEach(b=>console.log('  '+b));
  await browser.close();
})();
