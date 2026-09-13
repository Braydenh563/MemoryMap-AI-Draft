// batch-a.md "Left open": loadChatSuggestions() null-derefs on #chat-suggest.
// The actual sequence (no artificial race needed): #chat-suggest is "on
// loan" to `.chat-empty` (see the long comment on `openConversation`)
// whenever suggestions have already loaded for the current empty chat.
// `newChatConversation`'s `$("chat-messages").replaceChildren()` used to
// wipe `.chat-empty` -- and the loaned `#chat-suggest` inside it -- without
// sending it home first, so its own `loadChatSuggestions()` call right
// after found no `#chat-suggest` anywhere in the document.
//
// lib.js's page.on('pageerror', ...) already prints any uncaught exception,
// so a clean run here with no PAGEERROR line is the assertion.
const {boot}=require('./lib.js');
(async()=>{const {browser,page}=await boot();
await page.click('[data-tab="chat"]');
// Real suggestions need a live model; whether or not the backend returns
// any, loadChatSuggestions() itself must not throw, and #chat-suggest must
// still exist afterwards either way. Wait for the fetch to have settled.
await page.waitForTimeout(1500);

const before = await page.evaluate(() => {
  const box = document.getElementById('chat-suggest');
  return {
    exists: !!box,
    onLoan: !!box && !!box.closest('.chat-empty'),
    hidden: box?.classList.contains('hidden'),
    childCount: box?.children.length,
  };
});
console.log('before "+ New":', JSON.stringify(before));

await page.click('#chat-new');
await page.waitForTimeout(800); // loadChatSuggestions()'s own await

const after = await page.evaluate(() => {
  const box = document.getElementById('chat-suggest');
  return { exists: !!box, inDock: !!box && !!box.closest('.chat-dock, .chat-empty') };
});
console.log('after "+ New":', JSON.stringify(after));
console.log(after.exists ? 'PASS: #chat-suggest survived "+ New"' : 'FAIL: #chat-suggest is gone');
await browser.close();
process.exit(after.exists ? 0 : 1);
})();
