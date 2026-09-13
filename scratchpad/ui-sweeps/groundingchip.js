// chat-b.md items 2/3: measure a grounding chip's natural width with a long
// note opening, so `.result-reason-chip`'s max-width is a real number, not a
// guess, and confirm the ordinal ("1.") and the label truncate independently.
const {boot}=require('./lib.js');
(async()=>{const {browser,page}=await boot();
await page.click('[data-tab="chat"]');await page.waitForTimeout(700);
const r = await page.evaluate(() => {
  // A synthetic answer bubble, the shape renderAnswerGrounding expects: a
  // target row, an answer element for the inline-citation markers, one long
  // note opening (long enough that it would have hit setNoteLabel's old
  // "fall back to flattened text" branch at budget 30) and a short one.
  const wrap = document.createElement("div");
  wrap.className = "bubble bubble-answer";
  wrap.style.maxWidth = "38rem"; // .chat-thread's own bubble cap, read from CSS
  const answer = document.createElement("div");
  answer.className = "answer-body";
  answer.innerHTML = "<p>One. Two.</p>";
  const grounding = document.createElement("div");
  grounding.className = "answer-grounding";
  wrap.append(answer, grounding);
  document.body.appendChild(wrap);
  const sentences = [
    { note_id: 1, sentence: "One." },
    { note_id: 2, sentence: "Two." },
  ];
  const rawResults = [
    // Plain length ~64 chars: over the grounding chip's old 30-char budget
    // (where this used to fall back to flattened `**bold**` text) but well
    // under the new generous margin (length*4 = 120), so this is the case
    // INBOX 40/chat-b.md item 2 names: "renders Markdown only for short
    // note openings" -- this one is not short, and should still render.
    { id: 1, content: "**Ice Breakers:** a much longer note opening than the old budget allowed" },
    // Plain length ~230 chars: past even the generous margin, the one case
    // that is still expected to fall back to a plain character cut.
    { id: 2, content: "**A very long note title** that goes on for quite a while and would have been flattened before, with even more text after this point to push well past any reasonable chip width and past the generous margin as well, on purpose, for this probe." },
  ];
  renderAnswerGrounding(grounding, sentences, rawResults, answer);
  const chips = [...grounding.querySelectorAll(".result-reason-chip")];
  const out = chips.map(chip => {
    const rect = chip.getBoundingClientRect();
    const prefixEl = chip.querySelector(".note-label-prefix");
    const labelEl = chip.querySelector(".ph-text");
    const cs = labelEl ? getComputedStyle(labelEl) : null;
    return {
      chipW: Math.round(rect.width),
      hasBold: !!labelEl?.querySelector("strong"),
      prefixText: prefixEl?.textContent,
      prefixClipped: prefixEl ? prefixEl.scrollWidth > prefixEl.clientWidth + 1 : null,
      labelOverflow: cs?.overflow,
      labelTextOverflow: cs?.textOverflow,
      labelWhiteSpace: cs?.whiteSpace,
      labelClipped: labelEl ? labelEl.scrollWidth > labelEl.clientWidth + 1 : null,
    };
  });
  wrap.remove();
  return out;
});
console.log(JSON.stringify(r, null, 1));
await browser.close();})();
