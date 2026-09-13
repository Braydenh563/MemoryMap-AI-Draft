// Phase C's verification run: do tool calls actually render in the chat
// transcript on all three paths (plain chat with tools, Agent mode, a skill
// run); does the activity panel read as a run list; does a retrying step say
// so; and does the small-model toggle round-trip?
//
// It also carries INBOX 40's measurement: an agent answer and a skill run
// must end up with numbered citation markers *inside* the answer, not only a
// chip row under it. That needs the model's prose to actually overlap a note,
// which `seedGroundableNote` below arranges by writing the stand-in server's
// one fixed sentence into a note before anything is asked. Without it the
// grounding is correctly empty and the sweep would measure nothing.
//
// It drives the real app against `scratchpad/fake_openai_server.py` — a real
// socket speaking the OpenAI `/v1` dialect, including streamed tool-call
// fragments — so this is a measurement, not a reading of the source. See the
// fake server's own docstring for why that matters (CLAUDE.md's standing
// caveat about `chat_tools_stream`).
//
//   BASE=http://127.0.0.1:8792 SCRATCH=/tmp/phasec FAKE=http://127.0.0.1:8799/v1 \
//     PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node scratchpad/ui-sweeps/phasec.js
const { boot } = require('./lib.js');
const FAKE = process.env.FAKE || 'http://127.0.0.1:8799/v1';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The sentence `scratchpad/fake_openai_server.py` answers with once it has a
// tool result. A note containing it is a note every word of that sentence is
// found in, which is what `ground_answer_sentences` scores on (shared
// meaningful words, MIN_OVERLAP_RATIO 0.4), so the turn gets a real
// `grounding` event rather than an empty one.
const FAKE_SENTENCE =
  'I checked your notebook with the tool above and there is nothing surprising in it.';

// The note opens with a bold run on purpose: it is INBOX 40's other half.
// A badge built from this note's first words has to show *Tool audit:* in
// bold, never the four asterisks, which is the defect the owner screenshotted.
const SEED_NOTE = `**Tool audit:** ${FAKE_SENTENCE} The tags looked tidy.`;

async function seedGroundableNote(page) {
  return page.evaluate(async (content) => {
    // `/entries` answers with a bare list, but a failed call and a future
    // envelope both answer with something that has no `.find`, and a
    // TypeError here would take the whole sweep down before its first turn.
    const existing = await apiJson('/entries?limit=200').catch(() => null);
    const rows = Array.isArray(existing) ? existing : (existing && existing.entries) || [];
    const already = rows.find((e) => (e.content || '').trim() === content);
    if (already) return { id: already.id, created: false };
    const made = await apiJson('/entries', {
      method: 'POST',
      body: JSON.stringify({ content, category: 'notes' }),
    });
    return { id: made.id, created: true };
  }, SEED_NOTE);
}

// INBOX 40: the markers themselves, counted where they are supposed to be.
// `.bubble-answer` is one node per prose step, so this also says *which* step
// got them — the point of the fix is that they land on the final answer and
// not on step one's narration.
async function citationReport(page, label, sentence) {
  const found = await page.evaluate((needle) => {
    // Scoped to the last assistant bubble, not to the whole pane: `newChat()`
    // does not always clear the transcript before the next run starts, and a
    // count over every bubble reported the previous path's markers as this
    // one's (measured: an eleven-block "skill run" that was really the agent
    // turn's two blocks plus the run's nine).
    const bubble = [...document.querySelectorAll('#chat-messages .msg.assistant')].at(-1);
    const scope = bubble || document.getElementById('chat-messages') || document;
    const blocks = [...scope.querySelectorAll('.bubble-answer')];
    const markersPerBlock = blocks.map((b) => b.querySelectorAll('.answer-citation').length);
    // Which blocks the grounded sentence is actually in, and which one the
    // markers landed in. The bug was that those two were different: the
    // walker was handed the *first* prose block and the sentence was in a
    // later one, so nothing was marked at all.
    const holds = blocks
      .map((b, i) => (b.textContent.includes(needle) ? i : -1))
      .filter((i) => i >= 0);
    return {
      proseBlocks: blocks.length,
      blocksHoldingTheSentence: holds,
      markedBlocks: markersPerBlock.map((n, i) => (n ? i : -1)).filter((i) => i >= 0),
      lastBlockHoldingIt: holds.length ? holds[holds.length - 1] : null,
      markersPerBlock,
      markers: scope.querySelectorAll('.answer-citation').length,
      markerText: [...scope.querySelectorAll('.answer-citation')].map((m) => m.textContent.trim()),
      groundingChips: scope.querySelectorAll('.answer-grounding-chip').length,
      // The badge halves of INBOX 40: a chip that still shows raw markers is
      // the defect, so both the text and any rendered <strong> are reported.
      badges: [...scope.querySelectorAll('.tool-touched-chip, .answer-grounding-chip')]
        .slice(0, 6)
        .map((c) => ({
          text: c.textContent.replace(/\s+/g, ' ').trim().slice(0, 60),
          rendered: c.querySelectorAll('strong, em, code, mark').length,
        })),
      rawMarkerBadges: [...scope.querySelectorAll('.tool-touched-chip, .answer-grounding-chip')]
        .map((c) => c.textContent)
        .filter((t) => /\*\*|^#{1,6}\s|~~|`/.test(t)).length,
      renderedBadges: [...scope.querySelectorAll('.tool-touched-chip, .answer-grounding-chip')]
        .filter((c) => c.querySelector('strong, em, code, mark')).length,
    };
  }, sentence);
  console.log(`\n=== citations: ${label} ===`);
  console.log(JSON.stringify(found, null, 1));
  return found;
}

async function pointAtFake(page) {
  return page.evaluate(async (base) => {
    const provider = await api('/models/provider', {
      method: 'POST',
      body: JSON.stringify({ provider: 'openai', base_url: base }),
    }).then((r) => r.json());
    const model = await api('/models/chat-model', {
      method: 'POST',
      body: JSON.stringify({ name: 'fake-local-tools' }),
    }).then((r) => r.json());
    return { provider: provider.provider, reachable: provider.reachable, model };
  }, FAKE);
}

const waitForTurnInPage = (page) => waitForTurn(page, 180000);

const turnBusy = (page) =>
  page.evaluate(() => {
    // The class, not `offsetParent`: on any tab but Chat the whole panel is
    // hidden, so an offsetParent test reports every running turn as finished —
    // which is exactly the case the off-tab check below is measuring.
    const stop = document.getElementById('chat-stop');
    return Boolean(stop && !stop.classList.contains('hidden'));
  });

// Every turn ends by taking the Stop button away again, so that is the signal
// a turn is over — not a fixed wait, which on a slow round either cuts the
// turn off or wastes a minute. While it waits it watches for the states that
// only exist mid-run (`retrying`), which is the only chance to see them.
async function waitForTurn(page, ms = 90000, watch = null) {
  const until = Date.now() + ms;
  await page.waitForTimeout(1200);
  while (Date.now() < until) {
    if (watch) await watch();
    if (!(await turnBusy(page))) return true;
    await sleep(250);
  }
  return false;
}

async function send(page, text, ms) {
  await page.fill('#chat-input', text);
  await page.click('#chat-send');
  return waitForTurn(page, ms);
}

async function toolReport(page, label) {
  const found = await page.evaluate(() => {
    const chips = [...document.querySelectorAll('#chat-messages .tool-chip, #chat-messages .tool-chip-wrap')];
    return {
      chipsInTranscript: chips.length,
      chipLabels: chips.map((c) => (c.querySelector('summary') || c).textContent.trim().slice(0, 48)),
      stepGroups: [...document.querySelectorAll('#chat-messages .agent-step-group summary')].map((s) => s.textContent.trim()),
      plans: [...document.querySelectorAll('#chat-messages .step-plan')].map((p) => ({
        summary: p.querySelector('summary')?.textContent.trim(),
        steps: [...p.querySelectorAll('.plan-steps li')].map((li) => `[${li.dataset.state || '-'}] ${li.textContent.trim().slice(0, 90)}`),
      })),
      answer: (document.querySelector('#chat-messages .step-answer')?.textContent || '').slice(0, 60),
    };
  });
  console.log(`\n=== ${label} ===`);
  console.log(JSON.stringify(found, null, 1));
  return found;
}

// The panel, as numbers rather than as a look: how many rows, what each says,
// and whether anything in it is clipped (scrollHeight vs clientHeight — the
// measurement CLAUDE.md asks for before any claim about text being cut off).
async function panelReport(page, label) {
  const found = await page.evaluate(() => {
    const el = document.getElementById('agent-monitor');
    if (!el) return null;
    const rows = [...el.querySelectorAll('.agent-run-row')];
    return {
      panelHidden: el.classList.contains('hidden'),
      rows: rows.map((row) => ({
        summary: row.querySelector('summary').textContent.replace(/\s+/g, ' ').trim(),
        open: row.open,
        steps: [...row.querySelectorAll('.agent-run-step summary')].map((s) => s.textContent.replace(/\s+/g, ' ').trim().slice(0, 110)),
        tools: row.querySelectorAll('.agent-run-tools .tool-chip, .agent-run-tools .tool-chip-wrap').length,
        bar: (() => {
          const bar = row.querySelector('progress');
          return bar && !bar.classList.contains('hidden') ? Number(bar.value.toFixed(2)) : null;
        })(),
      })),
      clipped: rows
        .map((row) => {
          const s = row.querySelector('summary');
          return { text: s.textContent.trim().slice(0, 30), over: s.scrollHeight - s.clientHeight };
        })
        .filter((r) => r.over > 1),
      logLines: el.querySelectorAll('.monitor-log-item').length,
      logHidden: document.getElementById('agent-monitor-logs').classList.contains('hidden'),
      statusItem: (() => {
        const b = document.getElementById('status-activity');
        return b && !b.classList.contains('hidden') ? b.textContent.trim() : null;
      })(),
    };
  });
  console.log(`\n=== panel: ${label} ===`);
  console.log(JSON.stringify(found, null, 1));
  return found;
}

(async () => {
  const { browser, page, OUT } = await boot();
  console.log('provider:', JSON.stringify(await pointAtFake(page)));
  // Start from a known place: Phase B's mode is a stored preference, so a
  // previous run of this script would otherwise decide what this one measures.
  await page.evaluate(async () => {
    await apiJson('/preferences', { method: 'PUT', body: JSON.stringify({ small_model_mode: 'off' }) });
  });
  console.log('groundable note:', JSON.stringify(await seedGroundableNote(page)));
  await page.evaluate(() => switchTab('chat'));
  await page.waitForTimeout(800);

  // --- path 1: plain chat (Ask) with tools enabled --------------------------
  await page.evaluate(() => {
    document.querySelector('[data-chat-mode="chat"]')?.click();
    const t = document.getElementById('tools-toggle');
    if (t) t.checked = true;
  });
  await page.waitForTimeout(300);
  await send(page, 'What tags do I use in my notes?');
  await toolReport(page, 'PATH 1 — plain chat (Ask) with tools');
  await page.screenshot({ path: `${OUT}/phasec-1-plain-chat.png` });

  // --- path 2: Agent mode ---------------------------------------------------
  await page.evaluate(() => newChat && newChat());
  await page.waitForTimeout(600);
  await page.evaluate(() => document.querySelector('[data-chat-mode="agent"]')?.click());
  await page.waitForTimeout(400);
  // A question rather than an instruction: grounding is skipped for a turn
  // whose intent needs no retrieval, so "tidy up my tags" would correctly
  // produce no citations at all.
  await send(page, 'What did I write in my tool audit note?');
  await toolReport(page, 'PATH 2 — Agent mode');
  const agentCites = await citationReport(page, 'PATH 2 — Agent mode', FAKE_SENTENCE);
  await page.screenshot({ path: `${OUT}/phasec-2-agent-mode.png` });

  // --- path 3: a built-in skill run ----------------------------------------
  // The panel is forced open first: a chat run does not open it by itself any
  // more (the reader is already watching the transcript), and the point here
  // is to watch both renderings of the same run at once.
  await page.evaluate(() => newChat && newChat());
  await page.waitForTimeout(600);
  await page.evaluate(() => {
    setAgentMonitorVisible(true);
    agentMonitorPinned = true;
  });
  const skillName = await page.evaluate(async () => {
    const list = await apiJson('/skills').catch(() => null);
    const skills = (list && (list.skills || list)) || [];
    const pick = skills.find((s) => s.name === 'Summarise my week') || skills[0];
    if (!pick) return null;
    runSkill(pick);
    return pick.name;
  });
  console.log('skill:', skillName);

  // The `retrying` state exists only between two model rounds — on a stand-in
  // server that answers in milliseconds that window is far too short to poll
  // for, so the page itself records every one it paints.
  await page.evaluate(() => {
    // Phase C point 2: toasts announce start, finished and failed — never a
    // step. Every toast that appears during the run below is recorded, so
    // "no per-step chatter" is a count rather than a claim.
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
    window.__retrySeen = [];
    new MutationObserver(() => {
      for (const node of document.querySelectorAll('.plan-step-retrying')) {
        const where = node.closest('#agent-monitor') ? 'panel' : 'chat';
        const text = `${where}: ${node.textContent.replace(/\s+/g, ' ').trim().slice(0, 160)}`;
        if (!window.__retrySeen.includes(text)) window.__retrySeen.push(text);
      }
    }).observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
  });
  const retrying = { chat: null, panel: null, shot: false };
  await waitForTurn(page, 180000, async () => {
    const seen = await page.evaluate(() => ({
      chat: [...document.querySelectorAll('#chat-messages .plan-step-retrying')].map((n) => n.textContent.replace(/\s+/g, ' ').trim().slice(0, 140))[0] || null,
      panel: [...document.querySelectorAll('#agent-monitor .plan-step-retrying')].map((n) => n.textContent.replace(/\s+/g, ' ').trim().slice(0, 140))[0] || null,
    }));
    if (seen.chat && !retrying.chat) retrying.chat = seen.chat;
    if (seen.panel && !retrying.panel) retrying.panel = seen.panel;
    if ((seen.chat || seen.panel) && !retrying.shot) {
      retrying.shot = true;
      // Both renderings of the same state, in one frame: the panel row opened
      // to the step, and the chat scrolled to the plan card.
      await page.evaluate(() => {
        const row = document.querySelector('#agent-monitor .agent-run-row:last-child');
        if (row) {
          row.open = true;
          for (const step of row.querySelectorAll('.agent-run-step')) step.open = true;
        }
        const messages = document.getElementById('chat-messages');
        if (messages) messages.scrollTop = messages.scrollHeight;
      });
      await page.screenshot({ path: `${OUT}/phasec-5-retrying.png` });
    }
  });
  await toolReport(page, `PATH 3 — skill run (${skillName})`);
  const skillCites = await citationReport(page, `PATH 3 — skill run (${skillName})`, FAKE_SENTENCE);
  console.log('\n=== retrying, caught mid-run ===');
  console.log(JSON.stringify({ polled: retrying, observed: await page.evaluate(() => window.__retrySeen) }, null, 1));
  console.log('\n=== toasts raised during the skill run ===');
  console.log(JSON.stringify(await page.evaluate(() => window.__toasts), null, 1));
  await panelReport(page, 'after three runs');
  await page.screenshot({ path: `${OUT}/phasec-3-skill-run.png` });

  // The three levels, opened: run → steps → tool calls.
  await page.evaluate(() => {
    const row = document.querySelector('#agent-monitor .agent-run-row:last-child');
    if (!row) return;
    row.open = true;
    for (const step of row.querySelectorAll('.agent-run-step')) step.open = true;
    for (const chip of row.querySelectorAll('.agent-run-tools .tool-chip')) chip.open = true;
  });
  await page.waitForTimeout(400);
  await panelReport(page, 'run row opened');
  await page.screenshot({ path: `${OUT}/phasec-6-panel-open.png` });

  // The log is still one click away, with the same content.
  await page.click('#agent-monitor-log-toggle');
  await page.waitForTimeout(300);
  await panelReport(page, 'Show log');
  await page.screenshot({ path: `${OUT}/phasec-7-panel-log.png` });
  await page.click('#agent-monitor-log-toggle');

  // --- the small-model toggle ----------------------------------------------
  await page.evaluate(() => openSettingsModal('tools'));
  await page.waitForTimeout(1800);
  const before = await page.evaluate(() => document.getElementById('small-model-mode')?.value);
  await page.selectOption('#small-model-mode', 'on');
  await page.waitForTimeout(900);
  const saved = await page.evaluate(async () => {
    const prefs = await apiJson('/preferences');
    return { stored: prefs.small_model_mode, status: document.getElementById('small-model-mode-status')?.textContent };
  });
  await page.screenshot({ path: `${OUT}/phasec-8-small-model-toggle.png` });
  // …and it survives a reload of the settings screen, which is the half a
  // control that only *looks* saved always fails.
  await page.evaluate(() => showSettingsSection('appearance'));
  await page.waitForTimeout(400);
  await page.evaluate(() => showSettingsSection('tools'));
  await page.waitForTimeout(1200);
  const after = await page.evaluate(() => document.getElementById('small-model-mode')?.value);
  console.log('\n=== small model mode ===');
  console.log(JSON.stringify({ before, saved, afterReRender: after }, null, 1));
  await page.evaluate(() => closeSettingsModal());
  await page.waitForTimeout(400);

  // --- the same skill again, in small-model mode ---------------------------
  // Phase B narrows a step to the tool its contract names, and the stand-in
  // server always calls the first tool it is offered — so this run is the one
  // where every contract is met, and the run list should say so.
  await page.evaluate(() => newChat && newChat());
  await page.waitForTimeout(600);
  await page.evaluate(async () => {
    const list = await apiJson('/skills').catch(() => null);
    const skills = (list && (list.skills || list)) || [];
    const pick = skills.find((s) => s.name === 'Summarise my week');
    if (pick) runSkill(pick);
  });
  await waitForTurn(page, 180000);
  await toolReport(page, 'PATH 3b — same skill, small-model mode on');
  await panelReport(page, 'small-model run');
  await page.screenshot({ path: `${OUT}/phasec-9-small-model-run.png` });

  // --- a run that ends while the reader is on another tab -------------------
  // The one toast a chat run is allowed: its end, when the transcript that
  // would otherwise have shown it is not on screen. Muting must still win.
  await page.evaluate(() => { window.__toasts = []; });
  await page.evaluate(async () => {
    // Back to `off`, so the run takes long enough (two nudged rounds) to still
    // be going when the tab changes underneath it.
    await apiJson('/preferences', { method: 'PUT', body: JSON.stringify({ small_model_mode: 'off' }) });
    const list = await apiJson('/skills').catch(() => null);
    const pick = ((list && list.skills) || []).find((s) => s.name === 'Summarise my week');
    if (pick) runSkill(pick);
  });
  await page.waitForTimeout(400);
  await page.evaluate(() => switchTab('notes'));
  await waitForTurnInPage(page);
  const offTab = await page.evaluate(() => ({
    toasts: window.__toasts,
    toastsInBox: [...document.querySelectorAll('#toast-box .toast')].map((t) => t.textContent.trim()),
    activeTab: localStorage.getItem('activeTab'),
    lastRow: (() => {
      const row = document.querySelector('#agent-monitor .agent-run-row:last-child');
      return row ? row.querySelector('summary').textContent.replace(/\s+/g, ' ').trim() : null;
    })(),
    panelOpened: !document.getElementById('agent-monitor').classList.contains('hidden'),
  }));
  console.log('\n=== run finishing while on another tab ===');
  console.log(JSON.stringify(offTab, null, 1));
  await page.screenshot({ path: `${OUT}/phasec-10-off-tab.png` });

  // INBOX 40, as a pass/fail rather than as a screenshot to squint at.
  // The marker has to be in the *last* prose block that holds the sentence:
  // that is the answer the run ends with, and citing an intermediate step's
  // repeat of it would put the number where nobody reads.
  const onTheRightBlock = (r) =>
    r.markedBlocks.length > 0 && r.markedBlocks.every((i) => i === r.lastBlockHoldingIt);
  const cites = {
    agentMarkers: agentCites.markers,
    agentMarkedBlocks: agentCites.markedBlocks,
    agentLastBlockHoldingIt: agentCites.lastBlockHoldingIt,
    skillMarkers: skillCites.markers,
    skillProseBlocks: skillCites.proseBlocks,
    skillMarkedBlocks: skillCites.markedBlocks,
    skillLastBlockHoldingIt: skillCites.lastBlockHoldingIt,
    badgesShowingRawMarkers: agentCites.rawMarkerBadges + skillCites.rawMarkerBadges,
    badgesRenderingMarkdown: agentCites.renderedBadges + skillCites.renderedBadges,
  };
  const ok =
    cites.agentMarkers >= 1 &&
    cites.skillMarkers >= 1 &&
    onTheRightBlock(agentCites) &&
    onTheRightBlock(skillCites) &&
    cites.badgesShowingRawMarkers === 0 &&
    cites.badgesRenderingMarkdown >= 1;
  console.log('\n=== INBOX 40 ===');
  console.log(JSON.stringify({ ...cites, pass: ok }, null, 1));
  console.log('\nshots in', OUT);
  await browser.close();
  process.exitCode = ok ? 0 : 1;
})();
