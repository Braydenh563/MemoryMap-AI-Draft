// INBOX 81: a `<https://...>` autolink must render as a link, not as text
// with angle brackets. Driven end to end through a real note, because
// renderInlineMarkdown is module-scope and cannot be called from here.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const made = await page.evaluate(async () => {
    const h = { 'X-Auth-Token': localStorage.getItem('token') || '', 'Content-Type': 'application/json' };
    const body = 'Autolink probe: see <https://example.com/page> and Array<T> and <b>bold</b> '
      + 'and [named](https://example.org) and <javascript:alert(1)>.';
    const r = await fetch('/entries', { method: 'POST', headers: h, body: JSON.stringify({ content: body }) });
    return r.status;
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await page.click('[data-tab="notes"]').catch(() => {});
  await page.waitForTimeout(2500);
  const r = await page.evaluate(() => {
    const card = [...document.querySelectorAll('#entry-list li, .note-card, article')]
      .find((el) => /Autolink probe/.test(el.textContent || ''));
    if (!card) return { found: false };
    const links = [...card.querySelectorAll('a')].map((a) => a.getAttribute('href'));
    const text = card.textContent;
    return {
      found: true,
      links,
      stillShowsAngleBrackets: /<https?:\/\//.test(text),
      genericIntact: /Array<T>/.test(text),
      scriptSchemeNotLinked: !links.some((h) => (h || '').startsWith('javascript:')),
    };
  });
  console.log(JSON.stringify({ create: made, ...r }, null, 1));
  await browser.close();
})();
