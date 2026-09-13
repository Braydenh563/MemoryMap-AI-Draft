// Typed tool cards (PLAN.md §4, A1), measured in a real Chromium against the
// real app — not reasoned about from the source, which is the rule CLAUDE.md
// exists to enforce.
//
// Two halves, because they answer different questions:
//
//  1. **The live path.** Point the app at `scratchpad/fake_openai_server.py`
//     with FAKE_TOOLS set so it calls `search_files`, `read_whiteboard` and
//     `list_reminders` — the three kinds that had no cards at all before —
//     and count what renders under the tool chip in the chat transcript.
//  2. **The renderer, per kind.** Call `toolChip()` in the page with a
//     synthetic event carrying one card of every kind, then open each chip
//     and read back the actions on the card it produces. This is the only way
//     to see all five kinds in one place, and it measures the real DOM with
//     the real CSS rather than a description of it.
//
//   BASE=http://127.0.0.1:8796 SCRATCH=/tmp/mm-agent FAKE=http://127.0.0.1:8798/v1 \
//     PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/cards.js
const { boot } = require('./lib.js');
const FAKE = process.env.FAKE || 'http://127.0.0.1:8798/v1';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const turnBusy = (page) =>
  page.evaluate(() => {
    const stop = document.getElementById('chat-stop');
    return Boolean(stop && !stop.classList.contains('hidden'));
  });

async function waitForTurn(page, ms = 90000) {
  const until = Date.now() + ms;
  await page.waitForTimeout(1200);
  while (Date.now() < until) {
    if (!(await turnBusy(page))) return true;
    await sleep(250);
  }
  return false;
}

(async () => {
  const { browser, page } = await boot();

  // --- seed a notebook with one of everything -------------------------------
  const seeded = await page.evaluate(async () => {
    const j = (r) => r.json();
    const note = await api('/entries', {
      method: 'POST',
      body: JSON.stringify({ content: 'The schema change needs a backfill first.' }),
    }).then(j);
    const doc = await api('/documents', {
      method: 'POST',
      body: JSON.stringify({ title: 'Attention and recurrence', content: '# Attention\n\nA long document.' }),
    }).then(j);
    const due = new Date(Date.now() + 3 * 86400000).toISOString();
    const reminder = await api('/reminders', {
      method: 'POST',
      body: JSON.stringify({ text: 'Send the chapter two draft', due_at: due }),
    }).then(j);
    return { note: note.id, doc: doc.id, reminder: reminder.id };
  });
  console.log('seeded', JSON.stringify(seeded));

  // --- 1. the live path -----------------------------------------------------
  await page.evaluate(async (base) => {
    await api('/models/provider', {
      method: 'POST',
      body: JSON.stringify({ provider: 'openai', base_url: base }),
    });
    await api('/models/chat-model', { method: 'POST', body: JSON.stringify({ name: 'fake-local-tools' }) });
  }, FAKE);

  await page.click('[data-tab="chat"]');
  await page.waitForTimeout(600);
  for (const ask of ['what reminders have I got?', 'find the photo of the whiteboard']) {
    await page.fill('#chat-input', ask);
    await page.click('#chat-send');
    const finished = await waitForTurn(page);
    const seen = await page.evaluate(() => {
      const wraps = [...document.querySelectorAll('#chat-messages .tool-chip-wrap')];
      return wraps.map((w) => ({
        label: (w.querySelector('summary') || w).textContent.trim().slice(0, 44),
        chips: [...w.querySelectorAll('.tool-touched-chip')].map((c) => c.textContent.trim().slice(0, 40)),
      }));
    });
    console.log(`\n=== live: ${ask} (finished=${finished}) ===`);
    console.log(JSON.stringify(seen, null, 1));
  }

  // --- 2. the renderer, one card of every kind ------------------------------
  const perKind = await page.evaluate(async (ids) => {
    const event = {
      tool: 'demo',
      label: 'ph:wrench A synthetic call',
      ok: true,
      arguments: { demo: true },
      result_summary: '{"demo": true}',
      cards: [
        { kind: 'note', items: [{ id: ids.note, label: 'The schema change', snippet: 'needs a backfill' }] },
        { kind: 'document', items: [{ id: ids.doc, label: 'Attention and recurrence', snippet: 'A long document.' }] },
        {
          kind: 'file',
          items: [
            { id: 1, file_kind: 'upload', label: 'whiteboard-march.png', snippet: 'RETENTION PLAN', url: '/media/x.png' },
            { id: 2, file_kind: 'attachment', label: 'lecture.pdf', snippet: 'Week 3', url: '/files/2' },
          ],
        },
        { kind: 'board', items: [{ id: null, label: 'Default board', snippet: '' }] },
        {
          kind: 'reminder',
          items: [{ id: ids.reminder, label: 'Send the chapter two draft', snippet: '', due_at: new Date().toISOString(), done: false }],
        },
      ],
    };
    const holder = document.createElement('div');
    holder.id = 'cards-probe';
    document.getElementById('chat-messages').appendChild(holder);
    holder.appendChild(toolChip(event.label, true, event));

    const chips = [...holder.querySelectorAll('.tool-touched-chip')];
    for (const chip of chips) chip.click();
    await new Promise((r) => setTimeout(r, 900));

    const panels = [...holder.querySelectorAll('.tool-preview')];
    const styles = chips.map((c) => {
      const s = getComputedStyle(c);
      return { h: Math.round(c.getBoundingClientRect().height * 100) / 100, scroll: c.scrollHeight, client: c.clientHeight, overflow: s.overflow };
    });
    return {
      chipCount: chips.length,
      chipLabels: chips.map((c) => c.textContent.trim()),
      panelCount: panels.length,
      actionsPerPanel: panels.map((p) => [...p.querySelectorAll('.tool-preview-actions button')].map((b) => b.textContent.trim())),
      previewText: panels.map((p) => (p.querySelector('.tool-preview-content')?.textContent || '').trim().slice(0, 50)),
      // A clipped chip is the failure CLAUDE.md records twice: content taller
      // than the box, sliced by `overflow: hidden`, invisible in a screenshot.
      clipped: styles.filter((s) => s.scroll > s.client + 1).length,
      chipHeights: styles.map((s) => s.h),
      // Nothing may be written as markup — the transcript renders model text.
      innerHTMLFree: !holder.innerHTML.includes('<script'),
    };
  }, seeded);
  console.log('\n=== renderer, one card of every kind ===');
  console.log(JSON.stringify(perKind, null, 1));

  // --- 3. the reminder action actually writes -------------------------------
  const marked = await page.evaluate(async (id) => {
    const buttons = [...document.querySelectorAll('#cards-probe .tool-preview-actions button')];
    const done = buttons.find((b) => b.textContent.includes('Mark done'));
    if (!done) return { found: false };
    done.click();
    await new Promise((r) => setTimeout(r, 1200));
    const rows = await api('/reminders').then((r) => r.json());
    const row = (rows.reminders || rows).find((r) => r.id === id);
    return { found: true, done: Boolean(row && row.done) };
  }, seeded.reminder);
  console.log('\n=== reminder action ===');
  console.log(JSON.stringify(marked));

  // --- 4. a re-planned step, on the plan card (PLAN.md §4 A2) ---------------
  //
  // Driven through `agentTimeline` rather than through a run, because the
  // stand-in server always calls the tool it is told to and then answers —
  // there is no way to make it fail a step from outside. What is measured is
  // the half this change owns: does the checklist row *change its words* when
  // the runner rewrites the step, and does it read as recovery rather than as
  // an error?
  const replanned = await page.evaluate(async () => {
    const holder = document.createElement('div');
    holder.id = 'replan-probe';
    document.getElementById('chat-messages').appendChild(holder);
    const timeline = agentTimeline(holder);
    timeline.plan({ type: 'plan', kind: 'plan', skill: 'Tidy my notebook', steps: ['List my tags', 'Report'] });
    timeline.step({ type: 'step', index: 0, state: 'running', text: 'List my tags' });
    const before = holder.querySelector('.plan-steps li').textContent.trim();
    timeline.step({
      type: 'step',
      index: 0,
      state: 'replanned',
      text: 'List my tags. Call list_tags exactly once.',
      attempt: 1,
      of: 2,
      reason: 'the model said nothing and called no tool',
    });
    await new Promise((r) => setTimeout(r, 200));
    const li = holder.querySelector('.plan-steps li');
    const style = getComputedStyle(li);
    const warn = getComputedStyle(document.documentElement).getPropertyValue('--warn').trim();
    return {
      before,
      after: li.textContent.trim(),
      className: li.className,
      state: li.dataset.state,
      colour: style.color,
      warnToken: warn,
      // The clip test again: a row whose new text is taller than its box.
      clipped: li.scrollHeight > li.clientHeight + 1,
    };
  });
  console.log('\n=== a re-planned step on the plan card ===');
  console.log(JSON.stringify(replanned, null, 1));

  await browser.close();
})();
