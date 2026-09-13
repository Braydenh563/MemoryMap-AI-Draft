// DOCUMENTS_PLAN Phase 4 item 1: backlinks with context, and unlinked
// mentions, measured in a browser rather than reasoned about.
//
//   BASE=http://127.0.0.1:8931 node scratchpad/ui-sweeps/docbacklinks.js
//
// What this has to prove, and why each one is here:
//
//  - a backlink carries the *sentence* it was written in, with the match
//    marked, and the mark is on the occurrence that matched (the offsets come
//    from the server; a sweep that only checked "there is a mark" would pass
//    on a panel marking the wrong word);
//  - a document backlink is found at all, which a client-side scan could not
//    do (the browser never receives another document's content);
//  - unlinked mentions are their own section, under the links, and "Link"
//    moves a row from that section into the other one for real;
//  - "Link back" writes `[[Source]]` into this document at the caret, and the
//    row then says the connection is two-way;
//  - the panel fits the sidebar it lives in: no row wider than its column at
//    1440 or at 390.
const { boot } = require('./lib.js');
const { openDoc } = require('./docopen.js');

const out = [];
const check = (name, ok, detail) => out.push({ name, ok: !!ok, detail });

async function panel(page) {
  return page.evaluate(() => {
    const read = (li) => {
      const context = li.querySelector('.doc-backlink-context');
      const mark = li.querySelector('.doc-backlink-context mark');
      const action = li.querySelector('.doc-backlink-action');
      return {
        title: li.querySelector('.doc-backlink-title')?.textContent.trim() || '',
        context: context ? context.textContent : '',
        mark: mark ? mark.textContent : null,
        action: action ? action.textContent.trim() : null,
        actionDisabled: action ? !!action.disabled : null,
        clamped: context ? context.scrollHeight > context.clientHeight + 1 : false,
        width: li.getBoundingClientRect().width,
        scrollWidth: li.scrollWidth,
        clientWidth: li.clientWidth,
      };
    };
    const links = [...document.querySelectorAll('#doc-backlinks > li')].map(read);
    const mentions = [...document.querySelectorAll('.doc-mentions > li')].map(read);
    const wrap = document.getElementById('doc-backlinks-wrap');
    const host = document.querySelector('.doc-mentions-wrap');
    return {
      links,
      mentions,
      linksCount: wrap?.querySelector('.doc-backlinks-count')?.textContent || '',
      mentionsCount: host?.querySelector('.doc-mentions-count')?.textContent || '',
      mentionsBelowLinks:
        wrap && host
          ? wrap.getBoundingClientRect().top < host.getBoundingClientRect().top
          : null,
      sidebarWidth: document.getElementById('doc-sidebar')?.getBoundingClientRect().width || 0,
    };
  });
}

async function openOutline(page) {
  await page.evaluate(() => {
    document
      .querySelector('#doc-sidebar-tabs button[aria-controls="doc-sidebar-outline"]')
      ?.click();
  });
  await page.waitForTimeout(400);
}

(async () => {
  const { browser, page } = await boot();

  // The document everything points at, plus a document and a note that point
  // at it, and one of each that only mentions it.
  const targetId = await openDoc(page, { title: 'Design system notes', content: '# Design system notes\n\nOne radius everywhere.\n' });
  await page.evaluate(async () => {
    const post = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body) });
    await post('/documents', {
      title: 'Weekly review',
      content:
        'Monday was quiet. I finally read [[Design system notes]] end to end. Tuesday was not.',
    });
    await post('/documents', {
      title: 'Spacing audit',
      content: 'The design system notes are the reason every card agrees.',
    });
    await post('/entries', {
      content: '# Standup\n\nAgreed the design system notes need a diagram.',
    });
    await loadEntries();
  });
  await page.evaluate((id) => openDocument(id), targetId);
  await page.waitForTimeout(1200);
  await openOutline(page);

  let state = await panel(page);
  check('a document backlink is found', state.links.length === 1, JSON.stringify(state.links.map((l) => l.title)));
  check('and it is the document that linked', state.links[0]?.title.includes('Weekly review'), state.links[0]?.title);
  check(
    'the backlink carries its sentence, not its title',
    state.links[0]?.context === 'I finally read [[Design system notes]] end to end.',
    state.links[0]?.context
  );
  check(
    'the match is marked, and it is the link',
    state.links[0]?.mark === '[[Design system notes]]',
    state.links[0]?.mark
  );
  check('the links heading counts them', state.linksCount === '1', state.linksCount);

  check('unlinked mentions are their own section', state.mentions.length === 2, String(state.mentions.length));
  check('and it sits under the links', state.mentionsBelowLinks === true, String(state.mentionsBelowLinks));
  check('the mentions heading counts them', state.mentionsCount === '2', state.mentionsCount);
  const noteMention = state.mentions.find((m) => m.title.includes('Standup'));
  const docMention = state.mentions.find((m) => m.title.includes('Spacing audit'));
  check('a note mention is there', !!noteMention, JSON.stringify(state.mentions.map((m) => m.title)));
  check('a document mention is there', !!docMention, '');
  check(
    'a mention marks the words it matched on',
    noteMention?.mark === 'design system notes',
    noteMention?.mark
  );
  check(
    'a mention shows its own sentence',
    noteMention?.context === 'Agreed the design system notes need a diagram.',
    noteMention?.context
  );
  check('every mention offers Link', state.mentions.every((m) => m.action === 'Link'), JSON.stringify(state.mentions.map((m) => m.action)));
  check('a backlink offers Link back', state.links[0]?.action === 'Link back', state.links[0]?.action);

  // Nothing is wider than the column it is in.
  check(
    'no row overflows the sidebar at 1440',
    [...state.links, ...state.mentions].every((r) => r.scrollWidth <= r.clientWidth + 1),
    JSON.stringify([...state.links, ...state.mentions].map((r) => [r.scrollWidth, r.clientWidth]))
  );

  // Link: the mention becomes a link, in the source that wrote it.
  await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.doc-mentions > li')];
    const row = rows.find((li) => li.textContent.includes('Standup'));
    row.querySelector('.doc-backlink-action').click();
  });
  await page.waitForTimeout(2000);
  state = await panel(page);
  check(
    'Link moves the row from mentions to links',
    state.links.length === 2 && state.mentions.length === 1,
    `${state.links.length} links, ${state.mentions.length} mentions`
  );
  const linkedNote = state.links.find((l) => l.title.includes('Standup'));
  check(
    'and the source now holds the wiki link it wrote',
    linkedNote && linkedNote.mark === '[[Design system notes]]',
    linkedNote?.mark
  );
  const noteText = await page.evaluate(async () => {
    const rows = await (await api('/entries')).json();
    const items = Array.isArray(rows) ? rows : rows.items;
    return (items.find((e) => (e.content || '').includes('Standup')) || {}).content || '';
  });
  check(
    'the note itself was rewritten, not just the panel',
    noteText.includes('[[Design system notes]]'),
    noteText.slice(0, 80)
  );

  // Link back: the open document gains the link, and the row says so.
  await page.evaluate(() => {
    const surface = docSurface();
    surface.focus();
    surface.setSelectionRange(docText().length, docText().length);
    const rows = [...document.querySelectorAll('#doc-backlinks > li')];
    rows.find((li) => li.textContent.includes('Weekly review'))
      .querySelector('.doc-backlink-action')
      .click();
  });
  await page.waitForTimeout(1500);
  const docNow = await page.evaluate(() => docText());
  check('Link back writes the link into this document', docNow.includes('[[Weekly review]]'), docNow.slice(-40));
  state = await panel(page);
  const back = state.links.find((l) => l.title.includes('Weekly review'));
  check('and the row now says the connection is two-way', back?.action === 'Linked both ways', back?.action);
  check('with the button disabled rather than repeatable', back?.actionDisabled === true, String(back?.actionDisabled));

  // A phone.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(700);
  await openOutline(page);
  const phone = await panel(page);
  const rows = [...phone.links, ...phone.mentions];
  check('nothing scrolls sideways at 390', rows.every((r) => r.scrollWidth <= r.clientWidth + 1), JSON.stringify(rows.map((r) => [r.scrollWidth, r.clientWidth])));
  check('the panel still has rows at 390', rows.length > 0, String(rows.length));
  check(
    'the page itself does not scroll sideways at 390',
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    ''
  );

  await browser.close();
  let bad = 0;
  for (const row of out) {
    if (!row.ok) bad++;
    console.log(`${row.ok ? 'ok  ' : 'FAIL'} ${row.name}${row.ok ? '' : `  <- ${row.detail}`}`);
  }
  console.log(`${out.length - bad}/${out.length} checks passed`);
  process.exit(bad ? 1 : 0);
})();
