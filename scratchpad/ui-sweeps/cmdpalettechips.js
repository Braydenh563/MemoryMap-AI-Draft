// chat-b.md item 1: cmdPaletteResultRow/cmdPaletteTouchedRow now route
// through setNoteLabel (were noteLabel+setLabel, which only ever flattens).
// Confirms both still build valid, clickable chips with real Markdown
// rendered, calling them directly with synthetic data rather than driving a
// full agent turn to reach the popup palette.
const {boot}=require('./lib.js');
(async()=>{const {browser,page}=await boot();
const r = await page.evaluate(() => {
  const resultRow = cmdPaletteResultRow([
    { id: 101, content: "**Ice Breakers:** things to say at a party", category: "Social" },
  ]);
  const touchedRow = cmdPaletteTouchedRow([
    { id: 202, kind: "document", label: "# CAB432 project notes" },
  ]);
  const check = (block, name) => {
    const chip = block.querySelector(".cmd-source-row");
    const label = chip?.querySelector(".ph-text");
    return {
      name,
      hasChip: !!chip,
      hasBold: !!label?.querySelector("strong"),
      text: label?.textContent,
      hasIcon: !!chip?.querySelector("i.ph"),
    };
  };
  return [check(resultRow, "cmdPaletteResultRow"), check(touchedRow, "cmdPaletteTouchedRow")];
});
console.log(JSON.stringify(r, null, 1));
await browser.close();})();
