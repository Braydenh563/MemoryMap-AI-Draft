// Dock inventory (UI_MODERNISATION_PLAN.md Phase 8): for every tab, the rows that
// hold controls near the top of the main panel: how many controls, how many
// distinct heights, what kinds, plus a 260px strip screenshot of each, and the
// documents editor at 1440/820/390. The Phase 8 baseline table came from this.
// Run from this directory: BASE=… SCRATCH=… PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node docks.js
//
// **A control is the thing you press, not its parts.** This used to count a
// segmented control three times: the `.seg` well and each of its buttons. The
// well is `--control-h` (36px) and its buttons are inset by the well's own
// padding to 28px *on purpose* (`08-consistency.css`: "its segments are inset
// by the well's own padding rather than each deciding its own height"), so
// every dock holding a segment reported `28/36` and read as two control
// heights in one bar. It was reported that way about the Library's boards
// dock, believed, and nearly fixed, which is the cost of a sweep that cries
// wolf: the second reading is what showed the bar was already consistent.
// A hidden native `<select>` behind an enhanced one was the same kind of
// phantom, arriving as a 2px control (the Timeline's `2/28/36`).
//
// So: a `.seg`, a `.segmented-control` and a `.select-shell` each count once,
// as themselves, and nothing inside them counts at all.
const {boot}=require('./lib.js');
(async()=>{const {browser,page,OUT}=await boot();
const inv=async(label,sel)=>{const r=await page.evaluate((sel)=>{const root=document.querySelector(sel);if(!root)return null;const rows=[...root.querySelectorAll('.row, .library-toolbar, .graph-toolbar, .chat-toolbar, .wb-topbar, .doc-dock-head, .doc-toolbar, .doc-statusbar, .notes-toolbar, .log-toolbar, [role="toolbar"]')].filter(e=>e.getBoundingClientRect().height>0&&e.getBoundingClientRect().top<420).slice(0,6).map(e=>{const b=e.getBoundingClientRect();const WRAP='.seg, .segmented-control, .select-shell';const ctrls=[...e.querySelectorAll('button, select, input, .seg, .segmented-control, .select-shell, label')].filter(c=>{const box=c.getBoundingClientRect();if(box.width<=0||box.height<=0)return false;if(c.closest('.doc-dock-menu-list'))return false;
// Three more phantoms, each a real element that is not a control you can
// see: the hidden native `<select>` the app keeps behind an enhanced one
// (`.dock-native-hidden`, 2px, which is the Timeline's old `2/28/36`), a
// label inside a dock menu, and anything visually hidden until its menu
// opens.
if(c.matches('.dock-native-hidden, .dock-menu-label, .visually-hidden'))return false;
// One control per wrapper: the well, the shell. Its buttons and its hidden
// native select are how it is built, not what the eye counts.
const wrap=c.closest(WRAP);if(wrap&&wrap!==c)return false;return c.closest('.row, .library-toolbar, .graph-toolbar, .chat-toolbar, .wb-topbar, .doc-dock-head, .doc-toolbar, .doc-statusbar, .notes-toolbar, .log-toolbar, [role="toolbar"]')===e;});const hs=[...new Set(ctrls.map(c=>Math.round(c.getBoundingClientRect().height)))];return {sel:(e.id?'#'+e.id:'.'+[...e.classList].slice(0,2).join('.')),y:Math.round(b.top),h:Math.round(b.height),controls:ctrls.length,heights:hs.sort((a,b)=>a-b).join('/'),kinds:[...new Set(ctrls.map(c=>c.tagName.toLowerCase()+(c.classList.contains('icon-only')||c.classList.contains('icon-button')?'.icon':c.classList.contains('ghost')?'.ghost':c.classList.contains('primary')||(c.tagName==='BUTTON'&&!c.className.includes('ghost')&&!c.className.includes('icon'))?'.filled':'')))].join(',')};});return rows;},sel);console.log(label, JSON.stringify(r));};
for (const t of ['dashboard','notes','chat','graph','library','timeline','reminders']){await page.click(`[data-tab="${t}"]`);await page.waitForTimeout(700);await page.screenshot({path:OUT+`/dock-${t}.png`,clip:{x:0,y:100,width:1440,height:260}});await inv(t,`#tab-${t}`);}
await page.click('[data-tab="library"]');await page.waitForTimeout(400);await page.click('[data-target="library-view-whiteboard"]');await page.waitForTimeout(700);
const card=await page.$('#library-boards-grid .library-card');if(card){await card.click();await page.waitForTimeout(900);await page.screenshot({path:OUT+'/dock-whiteboard.png',clip:{x:0,y:100,width:1440,height:260}});await inv('whiteboard','#library-view-whiteboard');}
await page.click('#wb-back-to-boards').catch(()=>{});await page.waitForTimeout(400);
await page.click('[data-target="library-view-docs"]');await page.waitForTimeout(600);const d=await page.$('.doc-list-item');if(d){await d.click();await page.waitForTimeout(1200);
await page.evaluate(()=>{document.getElementById('doc-format-toggle')?.click();});await page.waitForTimeout(300);
await page.screenshot({path:OUT+'/dock-documents.png',clip:{x:0,y:100,width:1440,height:700}});await inv('documents','#library-view-docs');
await page.setViewportSize({width:820,height:1180});await page.waitForTimeout(500);await page.screenshot({path:OUT+'/dock-documents-820.png',clip:{x:0,y:0,width:820,height:700}});
await page.setViewportSize({width:390,height:844});await page.waitForTimeout(500);await page.screenshot({path:OUT+'/dock-documents-390.png'});}
await browser.close();})();
