// INBOX 69 and the owner's report of 2026-09-09: the agent activity panel's
// rows "don't expand", the text overflows sideways, and the log cannot be
// cleared. The runs are built in app.js (`agentRunAddStep`), so this builds
// the same DOM inside the real panel and measures it against the real CSS and
// the app's real global click handlers, which are the two suspects.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const r = await page.evaluate(() => {
    const panel = document.getElementById('agent-monitor');
    const runs = document.getElementById('agent-monitor-runs');
    panel.classList.remove('hidden');
    const row = document.createElement('details');
    row.className = 'agent-step step-plan agent-run-row';
    const sum = document.createElement('summary');
    sum.className = 'agent-run-summary';
    const name = document.createElement('span');
    name.className = 'agent-run-name';
    name.textContent = 'Loading the embedding model';
    const state = document.createElement('span');
    state.className = 'agent-run-state';
    state.textContent = 'Done';
    const prog = document.createElement('span');
    prog.className = 'agent-run-progress';
    const meta = document.createElement('span');
    meta.className = 'agent-run-meta';
    meta.textContent = 'Step 1 of 3';
    const bar = document.createElement('progress');
    bar.className = 'task-progress'; bar.max = 1; bar.value = 0.4;
    prog.append(meta, bar);
    sum.append(name, state, prog);
    const body = document.createElement('div');
    body.className = 'agent-run-body';
    const step = document.createElement('details');
    step.className = 'agent-step step-thinking agent-run-step has-tools';
    const ssum = document.createElement('summary');
    ssum.className = 'plan-step';
    ssum.textContent = "The first run downloads it (~90 MB). Search falls back to keywords until it's ready.";
    const tools = document.createElement('div');
    tools.className = 'agent-run-tools';
    const chip = document.createElement('div');
    chip.className = 'tool-chip';
    chip.textContent = 'search_notes({"query":"sentence-transformers/all-MiniLM-L6-v2"})';
    tools.append(chip);
    step.append(ssum, tools);
    if (!location.hash.includes('nosteps')) { body.append(step); row.classList.add('has-steps'); }
    row.append(sum, body);
    runs.append(row);
    return {
      panelW: panel.clientWidth,
      runsClientW: runs.clientWidth,
      runsScrollW: runs.scrollWidth,
      overflowsX: runs.scrollWidth > runs.clientWidth,
      rowW: row.getBoundingClientRect().width,
      overflowX: getComputedStyle(runs).overflowX,
      hasClearButton: !!document.querySelector('#agent-monitor-clear'),
      openBefore: row.open,
      progW: prog.getBoundingClientRect().width,
      barW: bar.getBoundingClientRect().width,
    };
  });
  await page.click('#agent-monitor-runs .agent-run-summary');
  await page.waitForTimeout(300);
  const after = await page.evaluate(() => {
    const row = document.querySelector('#agent-monitor-runs .agent-run-row');
    const step = document.querySelector('#agent-monitor-runs .agent-run-step');
    return { runOpen: row.open, bodyH: row.querySelector('.agent-run-body').getBoundingClientRect().height, stepOpen: step.open };
  });
  await page.click('#agent-monitor-runs .agent-run-step > summary');
  await page.waitForTimeout(300);
  const after2 = await page.evaluate(() => {
    const step = document.querySelector('#agent-monitor-runs .agent-run-step');
    const runs = document.getElementById('agent-monitor-runs');
    return { stepOpen: step.open, toolsH: step.querySelector('.agent-run-tools').getBoundingClientRect().height,
             scrollW: runs.scrollWidth, clientW: runs.clientWidth };
  });
  // The log view: fifty lines of raw logger output, which is what the owner
  // was looking at when the panel scrolled sideways.
  await page.click('#agent-monitor-log-toggle');
  await page.waitForTimeout(200);
  const logs = await page.evaluate(() => {
    const box = document.getElementById('agent-monitor-logs');
    const d = document.createElement('div');
    d.className = 'monitor-log-item info';
    d.textContent = '12:01:04 memorymap.ai.embeddings Loading sentence-transformers/all-MiniLM-L6-v2 from /home/user/.local/share/memorymap/models';
    box.append(d);
    return { clientW: box.clientWidth, scrollW: box.scrollWidth, overflowsX: box.scrollWidth > box.clientWidth,
             overflowX: getComputedStyle(box).overflowX, itemW: d.getBoundingClientRect().width };
  });
  console.log(JSON.stringify({ before: r, afterRunClick: after, afterStepClick: after2, logs }, null, 1));
  await browser.close();
})();
