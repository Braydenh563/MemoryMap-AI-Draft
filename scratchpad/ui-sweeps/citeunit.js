// A unit measurement of `addInlineCitations` in the real page: three prose
// blocks all holding the same grounded sentence, and one grounded row. The
// marker must land in the LAST of them (the answer a run ends with), which is
// the ordering INBOX 40's fix turns on and which the end-to-end sweep cannot
// isolate.
//
//   BASE=http://127.0.0.1:8872 SCRATCH=/tmp/mm-chat-b2 \
//     PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/citeunit.js
const { boot } = require('./lib.js');

(async () => {
  const { browser, page } = await boot();
  const result = await page.evaluate(() => {
    const host = document.createElement('div');
    host.id = 'cite-unit-host';
    for (let i = 0; i < 3; i += 1) {
      const block = document.createElement('div');
      block.className = 'bubble-answer';
      block.textContent = `Step ${i}. The starter needs feeding before Snowdon.`;
      host.appendChild(block);
    }
    document.body.appendChild(host);
    const sentences = [
      { sentence: 'The starter needs feeding before Snowdon.', note_id: 7, label: 'sourdough' },
    ];
    addInlineCitations(host.querySelectorAll('.bubble-answer'), sentences, [
      { id: 7, content: 'Feed the starter before you take the boots up Snowdon.' },
    ]);
    const per = [...host.querySelectorAll('.bubble-answer')].map(
      (b) => b.querySelectorAll('.answer-citation').length
    );
    // …and the same call with a single element, the shape the Ask box uses,
    // so the fix cannot have broken the surface that already worked.
    const one = document.createElement('div');
    one.className = 'bubble-answer';
    one.textContent = 'The starter needs feeding before Snowdon.';
    document.body.appendChild(one);
    addInlineCitations(one, sentences, [{ id: 7, content: 'starter Snowdon' }]);
    const out = { markersPerBlock: per, singleElement: one.querySelectorAll('.answer-citation').length };
    host.remove();
    one.remove();
    return out;
  });
  // And the badge half of INBOX 40: a chip whose label carries Markdown must
  // render it and must not grow taller than a plain one. A <strong> inside a
  // flex chip is exactly the kind of thing that changes a line box, and a
  // screenshot cannot tell one pixel of drift from none.
  const badges = await page.evaluate(() => {
    const host = document.createElement('div');
    host.className = 'row tool-touched';
    const make = (md) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'chip result-reason-chip result-reason-connected tool-touched-chip';
      host.appendChild(chip);
      setNoteLabel(chip, 'ph:note', md, 120);
      return chip;
    };
    document.body.appendChild(host);
    const plain = make('Ice Breakers: the first session of the week');
    const rich = make('**Ice Breakers:** the first session of the week');
    const heading = make('# CAB432 assignment notes');
    const linked = make('See [the brief](https://example.com/brief) before Monday');
    const out = {
      plainHeight: Math.round(plain.getBoundingClientRect().height),
      richHeight: Math.round(rich.getBoundingClientRect().height),
      richText: rich.textContent.trim(),
      richStrong: rich.querySelectorAll('strong').length,
      headingText: heading.textContent.trim(),
      linkedText: linked.textContent.trim(),
      anchorsInChips: host.querySelectorAll('a').length,
    };
    host.remove();
    return out;
  });
  console.log(JSON.stringify({ ...result, badges }, null, 1));
  const ok =
    result.markersPerBlock.join(',') === '0,0,1' &&
    result.singleElement === 1 &&
    badges.richStrong === 1 &&
    !badges.richText.includes('*') &&
    !badges.headingText.startsWith('#') &&
    badges.anchorsInChips === 0 &&
    Math.abs(badges.richHeight - badges.plainHeight) <= 1;
  console.log('pass:', ok);
  await browser.close();
  process.exitCode = ok ? 0 : 1;
})();
