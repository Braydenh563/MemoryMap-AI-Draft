// Seed the sandbox notebook so sweeps and screenshots measure populated
// screens rather than empty states: notes with tags, a document, reminders
// and bookmarks. Idempotent enough — run it once per data dir.
const {boot}=require('./lib.js');
(async()=>{
  const {browser,page}=await boot();
  const r=await page.evaluate(async()=>{
    const post=async(url,body)=>{try{const r=await api(url,{method:'POST',body:JSON.stringify(body)});return r.status;}catch(e){return String(e).slice(0,60);}};
    const out=[];
    const notes=[
      ["# Weekly review\n\nShipped the sweep tooling. Next: component consistency by count, then the skills reform.",["work","planning"]],
      ["Call the dentist about the appointment on Thursday; ask about the retainer.",["personal","health"]],
      ["# Reading list\n\n- Designing Data-Intensive Applications\n- The Design of Everyday Things\n- Thinking in Systems",["reading"]],
      ["Idea: a mindmap mode on the whiteboard where a node can be a real note. Tab adds a child, Enter a sibling.",["ideas","memorymap"]],
      ["Meeting with Sam: agreed the Q4 plan, three workstreams, review on the 20th.",["work","meetings"]],
      ["Recipe: tomato soup — roast the tomatoes first, add a little smoked paprika.",["cooking"]],
      ["# Sprint retro\n\nWhat went well: measuring before changing. What didn't: reading the source instead of running it.",["work","retro"]],
      ["Remember to renew the passport before March.",["personal","admin"]],
    ];
    for(const [content,tags] of notes) out.push(await post('/entries',{content,tags}));
    out.push(await post('/documents',{title:'Design system notes',content:'# Design system notes\n\nSurface tiers, the button ramp, one eyebrow recipe.\n\n## Rows\n\nTwo gaps: inside a group and between groups.'}));
    out.push(await post('/reminders',{text:'Send the weekly summary',due_at:new Date(Date.now()+3600e3).toISOString()}));
    out.push(await post('/reminders',{text:'Water the plants',due_at:new Date(Date.now()+86400e3*2).toISOString()}));
    out.push(await post('/bookmarks',{url:'https://kumu.io/',title:'Kumu — relationship mapping',group_name:'Research'}));
    out.push(await post('/bookmarks',{url:'https://coggle.it/',title:'Coggle — mind maps',group_name:'Research'}));
    return out;
  });
  console.log('statuses', JSON.stringify(r));
  await browser.close();
})();
