// INBOX 39: the chat mode segment now reads Ask / Agent, and running a skill
// from Ask mode switches the mode itself and says so.
//
// Measured, not looked at: the two button widths (the segment used to hold two
// labels of near-equal length and the rename could unbalance it), the labels at
// both widths the media query splits on, and the toggle plus the toast after a
// skill is launched from Ask mode.
//
//   BASE=http://127.0.0.1:8871 SCRATCH=/tmp/mm-chat-b \
//     PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/chatmode.js
const { boot } = require('./lib.js');

const segReport = (page) =>
  page.evaluate(() => {
    const seg = document.getElementById('chat-mode-seg');
    if (!seg) return null;
    return [...seg.querySelectorAll('button')].map((b) => ({
      mode: b.dataset.chatMode,
      text: b.textContent.replace(/\s+/g, ' ').trim(),
      aria: b.getAttribute('aria-label'),
      pressed: b.getAttribute('aria-pressed'),
      width: Math.round(b.getBoundingClientRect().width),
      // A label that is wider than the button it sits in is the failure this
      // measures for; a screenshot cannot tell the difference.
      overflow: b.scrollWidth - b.clientWidth,
    }));
  });

(async () => {
  const { browser, page, OUT } = await boot();
  await page.evaluate(() => switchTab('chat'));
  await page.waitForTimeout(800);

  console.log('=== 1440 (long labels hidden below 1500) ===');
  console.log(JSON.stringify(await segReport(page), null, 1));
  await page.setViewportSize({ width: 1700, height: 900 });
  await page.waitForTimeout(400);
  console.log('=== 1700 (long labels shown) ===');
  console.log(JSON.stringify(await segReport(page), null, 1));
  await page.screenshot({ path: `${OUT}/chatmode-seg.png` });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(400);

  // Ask mode, then run a skill: the mode should move to Agent on its own and
  // one line should say so.
  await page.evaluate(() => document.querySelector('[data-chat-mode="chat"]')?.click());
  await page.waitForTimeout(600);
  const before = await page.evaluate(() => document.getElementById('tools-toggle').checked);
  await page.evaluate(() => {
    window.__toasts = [];
    const box = document.getElementById('toast-box');
    if (box) {
      new MutationObserver((records) => {
        for (const record of records) {
          for (const node of record.addedNodes) {
            if (node.textContent) window.__toasts.push(node.textContent.trim().slice(0, 80));
          }
        }
      }).observe(box, { childList: true });
    }
  });
  const skill = await page.evaluate(async () => {
    const list = await apiJson('/skills').catch(() => null);
    const skills = (list && (list.skills || list)) || [];
    const pick = skills.find((s) => s.name === 'Summarise my week') || skills[0];
    if (!pick) return null;
    runSkill(pick);
    return pick.name;
  });
  await page.waitForTimeout(2500);
  const after = await page.evaluate(async () => ({
    toolsToggle: document.getElementById('tools-toggle').checked,
    seg: [...document.querySelectorAll('#chat-mode-seg button')]
      .filter((b) => b.classList.contains('active'))
      .map((b) => b.dataset.chatMode),
    toasts: window.__toasts,
    stored: (await apiJson('/preferences')).tools_enabled,
  }));
  console.log('=== skill from Ask mode ===');
  console.log(JSON.stringify({ skill, toolsBefore: before, after }, null, 1));
  await page.screenshot({ path: `${OUT}/chatmode-after-skill.png` });
  console.log('shots in', OUT);
  await browser.close();
})();
