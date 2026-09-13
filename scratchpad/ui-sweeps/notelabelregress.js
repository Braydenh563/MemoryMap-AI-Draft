// Regression check: setNoteLabel's `holder` keeps the `.ph-text` class name
// (not renamed) specifically so the app's other per-chip ellipsis rules
// keyed on `.answer-related-chip > .ph-text` (and siblings: `.map-chip
// .ph-text`, `.entry-pick-row > .ph-text`, `.library-image-usage-chip >
// .ph-text`) keep applying after chat-b.md's "the ordinal gets its own
// element" change. Calls renderRelatedElsewhere (a setNoteLabel caller with
// no numeric prefix) directly and checks the rendered shape.
const {boot}=require('./lib.js');
(async()=>{const {browser,page}=await boot();
const r = await page.evaluate(() => {
  const target = document.createElement("div");
  document.body.appendChild(target);
  renderRelatedElsewhere(target, [
    { kind: "document", id: 55, label: "**A related document**" },
  ]);
  const chip = target.querySelector(".answer-related-chip");
  const out = {
    hasChip: !!chip,
    hasPhText: !!chip?.querySelector(".ph-text"),
    hasBold: !!chip?.querySelector(".ph-text strong"),
    hasPrefixEl: !!chip?.querySelector(".note-label-prefix"), // none expected: no ordinal here
    text: chip?.querySelector(".ph-text")?.textContent,
  };
  target.remove();
  return out;
});
console.log(JSON.stringify(r, null, 1));
await browser.close();})();
