// Which stylesheet rules set PROP on the first visible element matching SEL?
//   node scratchpad/ui-sweeps/rules.js notes "#graph-search" font-size
const {boot}=require('./lib.js');
const [tab,sel,prop]=process.argv.slice(2);
(async()=>{
  const {browser,page}=await boot();
  if(tab&&tab!=='dashboard'){await page.click(`[data-tab="${tab}"]`).catch(()=>{});await page.waitForTimeout(700);}
  const r=await page.evaluate(([sel,prop])=>{
    const els=[...document.querySelectorAll(sel)].filter(e=>e.checkVisibility&&e.checkVisibility());
    const e=els[0]; if(!e) return 'no visible match';
    const out=[`computed ${prop}=${getComputedStyle(e)[prop]||getComputedStyle(e).getPropertyValue(prop)} on ${e.tagName.toLowerCase()}#${e.id}.${[...e.classList].join('.')}`];
    let node=e;
    while(node&&node!==document){
      for(const ss of document.styleSheets){let rules;try{rules=ss.cssRules;}catch(err){continue;}
        const walk=(list)=>{for(const rule of list){if(!rule.selectorText){if(rule.cssRules)walk(rule.cssRules);continue;}try{if(node.matches(rule.selectorText)&&rule.style.getPropertyValue(prop))out.push(`${node===e?'SELF':'ancestor '+node.tagName.toLowerCase()+'.'+[...node.classList].slice(0,2).join('.')}: ${(ss.href||'').split('/').pop().split('?')[0]} ${rule.selectorText} { ${prop}: ${rule.style.getPropertyValue(prop)} }`);}catch(err){}}};
        walk(rules);}
      node=node.parentElement;
    }
    return out.join('\n');
  },[sel,prop]);
  console.log(r); await browser.close();
})();
