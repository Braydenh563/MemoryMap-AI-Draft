// One skill run against the stand-in model server, instrumented: every
// `addInlineCitations` call records how many prose blocks it was handed and
// which of them ended up with markers. Written while chasing why the
// end-to-end sweep saw markers on the first two blocks of an eleven-block run
// (INBOX 40); the answer is in the `calls` list this prints.
//
//   BASE=http://127.0.0.1:8872 SCRATCH=/tmp/mm-chat-b2 FAKE=http://127.0.0.1:8879/v1 \
//     PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/citeskill.js
const { boot } = require('./lib.js');
const FAKE = process.env.FAKE || 'http://127.0.0.1:8879/v1';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const { browser, page } = await boot();
  await page.evaluate(async (base) => {
    await api('/models/provider', {
      method: 'POST',
      body: JSON.stringify({ provider: 'openai', base_url: base }),
    });
    await api('/models/chat-model', {
      method: 'POST',
      body: JSON.stringify({ name: 'fake-local-tools' }),
    });
  }, FAKE);
  await page.evaluate(() => switchTab('chat'));
  await page.waitForTimeout(600);
  await page.evaluate(() => {
    window.__calls = [];
    const real = window.addInlineCitations;
    window.addInlineCitations = function wrapped(target, sentences, raw) {
      const list = target && !target.nodeType ? [...target] : target ? [target] : [];
      const out = real.apply(this, arguments);
      window.__calls.push({
        handed: list.length,
        sentences: (sentences || []).map((s) => s.sentence || ''),
        blockText: list.map((el) => el.textContent),
        marked: list.map((el) => el.querySelectorAll('.answer-citation').length),
      });
      return out;
    };
  });
  await page.evaluate(() => newChat && newChat());
  await page.waitForTimeout(500);
  await page.evaluate(async () => {
    const list = await apiJson('/skills').catch(() => null);
    const skills = (list && (list.skills || list)) || [];
    const pick = skills.find((s) => s.name === 'Summarise my week') || skills[0];
    if (pick) runSkill(pick);
  });
  const until = Date.now() + 180000;
  while (Date.now() < until) {
    const busy = await page.evaluate(() => {
      const stop = document.getElementById('chat-stop');
      return Boolean(stop && !stop.classList.contains('hidden'));
    });
    if (!busy) break;
    await sleep(400);
  }
  // When the markers disappear, if they do: the post-`finalise()` pass puts
  // them in, and anything that re-renders the prose afterwards takes them out
  // again. A sampled trace is the only way to see which.
  const trace = [];
  for (let i = 0; i < 12; i += 1) {
    trace.push(
      await page.evaluate(() =>
        document.querySelectorAll('#chat-messages .answer-citation').length
      )
    );
    await sleep(250);
  }
  console.log('marker count over 3s after the turn:', JSON.stringify(trace));
  const report = await page.evaluate(() => ({
    calls: window.__calls,
    blocksNow: document.querySelectorAll('#chat-messages .bubble-answer').length,
    markersNow: [...document.querySelectorAll('#chat-messages .bubble-answer')].map(
      (b) => b.querySelectorAll('.answer-citation').length
    ),
  }));
  console.log(JSON.stringify(report, null, 1));
  await browser.close();
})();
