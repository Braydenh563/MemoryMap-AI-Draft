// `cmdPaletteLinkNotes` in the real page: the link carries the note's own
// opening words beside whatever the model called it (INBOX 112), so a citation
// that points somewhere else says so in the sentence.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const out = await page.evaluate(() => {
    const host = document.createElement('div');
    host.className = 'bubble-answer';
    host.textContent =
      "You only have one note (note #68) in your notebook, and its content is " +
      "simply '# bubble tea'. See also notes id 12, 43 and 900.";
    document.body.appendChild(host);
    // 68 is the Shakespeare note, which is exactly the reported turn: the model
    // named an id belonging to a different note than the one it described.
    cmdPaletteLinkNotes(host, [
      { id: 68, content: '# Act I, Scene I\n\nA sonnet parody.' },
      { id: 12, content: '# bubble tea' },
      { id: 43, content: '# Shopping list\n\nmilk, tapioca' },
    ]);
    const links = [...host.querySelectorAll('.cmd-note-link')].map((b) => ({
      said: b.firstChild.textContent,
      name: b.querySelector('.cmd-note-link-name')?.textContent || null,
      title: b.title,
      nameColour: b.querySelector('.cmd-note-link-name')
        ? getComputedStyle(b.querySelector('.cmd-note-link-name')).color : null,
      linkColour: getComputedStyle(b).color,
    }));
    const text = host.textContent;
    host.remove();
    return { links, text };
  });
  const fails = [];
  const say = (k, v) => console.log(k + ': ' + JSON.stringify(v));
  say('links', out.links.length);
  say('text', out.text);
  if (out.links.length !== 3) fails.push(`expected 3 links (68, 12, 43), got ${out.links.length}`);
  const first = out.links[0] || {};
  if (first.said !== 'note #68') fails.push(`the model's own wording was rewritten: ${first.said}`);
  if (first.name !== 'Act I, Scene I') fails.push(`the link does not name its target: ${first.name}`);
  if (!/68/.test(first.title || '')) fails.push('the tooltip does not name the id');
  if (first.nameColour === first.linkColour) fails.push('the name is not quieter than the reference');
  if ((out.links[1] || {}).name !== 'bubble tea') fails.push('a run member does not name its target');
  if (/900/.test((out.links[2] || {}).said || '')) fails.push('an unretrieved id was linked');
  console.log(fails.length ? 'FAIL:\n  ' + fails.join('\n  ') : 'citename: all checks pass');
  await browser.close();
  process.exit(fails.length ? 1 : 0);
})();
