// INBOX 46: every pill-toggle's *off* track fill, app-wide, both themes.
// The rule (06-timeline-dialogs.css) mixes `--ink` against `--page`, which is
// a gradient, not a colour, so `color-mix` is invalid where it's used and the
// whole `background` declaration is dropped -- an off switch renders
// transparent even though its border and knob (`--muted`) still paint.
// This walks every selector the rule targets, across every tab and the
// settings modal's sections, and reports the *off* ones' computed
// background-color plus whether it resolves to fully transparent.
const {boot}=require('./lib.js');
const TABS=['dashboard','notes','chat','graph','library','timeline','reminders','whiteboard','mindmap'];
const SECTIONS=['models','appearance','account','tools','skills','tasks','data','logs','extras','about'];
const SEL=[
  '.settings-section label>input[type="checkbox"]',
  '.setting-check input[type="checkbox"]',
  '.tools-toggle input[type="checkbox"]',
  '#tool-list input[type="checkbox"]',
  '.library-toolbar label>input[type="checkbox"]',
  '.check-row input[type="checkbox"]',
  '.semantic-toggle input[type="checkbox"]',
  '.library-sort-check input[type="checkbox"]',
  '.checkbox-label>input[type="checkbox"]:not(.sr-only)',
  '.wb-snap-label input[type="checkbox"]',
].join(',');
(async()=>{const {browser,page}=await boot({viewport:{width:1440,height:900}});
// Groups by (label, id-or-class), not by individual element: the tool list
// alone renders 50+ identical `.setting-check` rows, so a per-element report
// would be a screenful of the same line. Any group with a mix of transparent
// and painted rows still shows both, because that would be a different bug.
const run=async(label)=>{
  const r = await page.evaluate((SEL)=>{
    const groups=new Map();
    for(const el of document.querySelectorAll(SEL)){
      if(!el.checkVisibility || !el.checkVisibility()) continue;
      if(el.checked) continue; // only the OFF state is the bug
      const cs=getComputedStyle(el);
      const bg=cs.backgroundColor;
      const id=el.id?('#'+el.id):('.'+[...el.classList].slice(0,2).join('.')||'(bare input)');
      const key=id+'|'+bg;
      groups.set(key, (groups.get(key)||{id,bg,n:0}));
      groups.get(key).n++;
    }
    return [...groups.values()];
  }, SEL);
  for(const row of r){
    const transparent = row.bg==='rgba(0, 0, 0, 0)' || row.bg==='transparent';
    console.log(`${label}\t${row.id}\t${row.bg}\tx${row.n}\t${transparent ? 'FAIL transparent' : 'ok'}`);
  }
};
for(const t of TABS){await page.click(`[data-tab="${t}"]`).catch(()=>{});await page.waitForTimeout(500);await run(t);}
// Graph's options panel is folded away until the gear button opens it.
await page.click('[data-tab="graph"]').catch(()=>{});await page.waitForTimeout(400);
await page.click('#graph-options-toggle').catch(()=>{});await page.waitForTimeout(400);await run('graph/options');
// INBOX 46's own repro names "the Chat dock's Tools switch": the chat tab's
// #tools-toggle (the Agent-mode checkbox the mode segment now sits in front
// of -- see the long comment on it in index.html). It stays `.hidden`
// (display:none) per that comment, but INBOX 46's measurement did not filter
// on visibility, so check it directly and unhidden, both ways.
await page.click('[data-tab="chat"]').catch(()=>{});await page.waitForTimeout(400);
const toolsToggle = await page.evaluate(()=>{
  const el=document.getElementById('tools-toggle'); if(!el) return null;
  el.checked = false; // INBOX 46 is the OFF state only; default boots checked=true
  const hiddenBg=getComputedStyle(el).backgroundColor;
  el.closest('.agent-toggle')?.classList.remove('hidden');
  const shownBg=getComputedStyle(el).backgroundColor;
  el.closest('.agent-toggle')?.classList.add('hidden');
  return {hiddenBg, shownBg};
});
if (toolsToggle) console.log(`chat/tools-toggle\t#tools-toggle(as-shipped .hidden, off)\t${toolsToggle.hiddenBg}\tx1\t${toolsToggle.hiddenBg==='rgba(0, 0, 0, 0)'?'(display:none, expected)':'ok'}`);
if (toolsToggle) console.log(`chat/tools-toggle\t#tools-toggle(class unhidden, off)\t${toolsToggle.shownBg}\tx1\t${toolsToggle.shownBg==='rgba(0, 0, 0, 0)'?'FAIL transparent':'ok'}`);
await page.click('#settings-btn').catch(()=>{});await page.waitForTimeout(400);
for(const s of SECTIONS){const ok=await page.click(`#settings-modal [data-section="${s}"]`,{timeout:1500}).then(()=>true).catch(()=>false);if(!ok)continue;await page.waitForTimeout(300);await run('settings/'+s);}
await browser.close();})();
