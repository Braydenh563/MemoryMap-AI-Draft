// The re-probe for the agent activity panel fixes: an empty run row does not
// fold, the log does not scroll sideways, Clear empties both.
const { boot } = require('./lib.js');
(async () => {
  const { browser, page } = await boot();
  const before = await page.evaluate(() => {
    const panel = document.getElementById('agent-monitor');
    const runs = document.getElementById('agent-monitor-runs');
    const logs = document.getElementById('agent-monitor-logs');
    panel.classList.remove('hidden');
    const mk = (hasSteps) => {
      const row = document.createElement('details');
      row.className = 'agent-step step-plan agent-run-row' + (hasSteps ? ' has-steps' : '');
      const sum = document.createElement('summary');
      sum.className = 'agent-run-summary';
      const name = document.createElement('span');
      name.className = 'agent-run-name';
      name.textContent = hasSteps ? 'Summarise my week' : 'Loading the embedding model';
      const meta = document.createElement('span');
      meta.className = 'agent-run-meta';
      meta.textContent = "The first run downloads it (~90 MB) from sentence-transformers/all-MiniLM-L6-v2.";
      sum.append(name, meta);
      const body = document.createElement('div');
      body.className = 'agent-run-body';
      row.append(sum, body);
      // The app's own guard, copied: this probe builds the DOM, not the app.
      sum.addEventListener('click', (e) => { if (!row.classList.contains('has-steps')) e.preventDefault(); });
      runs.append(row);
      return row;
    };
    const empty = mk(false);
    mk(true);
    const line = document.createElement('div');
    line.className = 'monitor-log-item info';
    line.textContent = '12:01:04 memorymap.ai.embeddings Loading sentence-transformers/all-MiniLM-L6-v2 from /home/user/.local/share/memorymap/models';
    logs.append(line);
    logs.classList.remove('hidden');
    return {
      runsScrollW: runs.scrollWidth, runsClientW: runs.clientWidth,
      logsScrollW: logs.scrollWidth, logsClientW: logs.clientWidth,
      markerHidden: getComputedStyle(empty.querySelector('summary'), '::before').visibility,
      hasClear: !!document.getElementById('agent-monitor-clear'),
      headerFits: document.querySelector('.monitor-header').scrollWidth <= document.querySelector('.monitor-header').clientWidth,
    };
  });
  await page.click('#agent-monitor-runs .agent-run-row:not(.has-steps) > summary');
  await page.waitForTimeout(200);
  const emptyOpen = await page.evaluate(() => document.querySelector('.agent-run-row:not(.has-steps)').open);
  await page.click('#agent-monitor-runs .agent-run-row.has-steps > summary');
  await page.waitForTimeout(200);
  const fullOpen = await page.evaluate(() => document.querySelector('.agent-run-row.has-steps').open);
  await page.click('#agent-monitor-clear');
  await page.waitForTimeout(200);
  const cleared = await page.evaluate(() => ({
    logLines: document.querySelectorAll('#agent-monitor-logs .monitor-log-item').length,
  }));
  console.log(JSON.stringify({ before, emptyRowOpens: emptyOpen, realRowOpens: fullOpen, cleared }, null, 1));
  await browser.close();
})();
