// How many lines does a control row actually occupy? consistency.md item 5
// left three rows open at 1024: both `.draft-controls` rows in the Writing
// Room, `.capture-field-row` in Capture, and `.ask-query-row`, which it
// suspected was one tall child rather than a wrap.
//
// "Lines" is counted from the distinct y of the row's children, not from the
// row's height, precisely so a tall child and a wrapped row cannot be
// confused: that is the reading item 5 asked to be confirmed before anything
// was changed.
const {boot}=require('./lib.js');
const ROWS=[
  ['notes','writing-room','.draft-controls'],
  ['notes','capture','.capture-field-row'],
  ['notes','ask','.ask-query-row'],
];
(async()=>{
  const W=Number(process.env.W||1024);
  const {browser,page}=await boot({viewport:{width:W,height:900}});
  console.log(`== ${W}px`);
  for(const [tab,sub,sel] of ROWS){
    await page.click(`[data-tab="${tab}"]`).catch(()=>{}); await page.waitForTimeout(700);
    await page.click(`#tab-${tab} [data-section="${sub}"], #tab-${tab} [data-view="${sub}"]`,{timeout:4000}).catch(()=>{});
    await page.waitForTimeout(900);
    const r=await page.evaluate((s)=>{
      return [...document.querySelectorAll(s)].filter(e=>e.checkVisibility&&e.checkVisibility()).map(e=>{
        const kids=[...e.children].filter(c=>c.checkVisibility&&c.checkVisibility());
        // Bucketed, not distinct: children on one line do not share a top to
        // the pixel (a label centred against a 40px button sits a few px
        // lower), so counting raw tops reported the Capture row as three
        // lines while it was 40px tall, which is one. A new line starts only
        // when a child's top is more than half a control height below the
        // line it is being compared against.
        const tops=kids.map(c=>c.getBoundingClientRect().top).sort((a,b)=>a-b);
        const ys=[]; for(const t of tops){ if(!ys.length||t>ys[ys.length-1]+20) ys.push(t); }
        const tallest=Math.max(0,...kids.map(c=>c.getBoundingClientRect().height));
        return {h:+e.getBoundingClientRect().height.toFixed(0), lines:ys.length, kids:kids.length, tallest:+tallest.toFixed(0),
          wrap:getComputedStyle(e).flexWrap,
          last:kids.length?`${kids[kids.length-1].tagName.toLowerCase()}#${kids[kids.length-1].id}`:'-'};
      });
    }, sel);
    r.forEach((x,i)=>console.log(`  ${sel}[${i}] h=${x.h} lines=${x.lines} children=${x.kids} tallestChild=${x.tallest} flex-wrap=${x.wrap} last=${x.last}`));
    if(!r.length) console.log(`  ${sel}: none visible`);
  }
  await browser.close();
})();
