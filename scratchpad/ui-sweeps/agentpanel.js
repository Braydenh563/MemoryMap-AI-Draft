// The agent activity panel (#agent-monitor), against DESIGN.md (INBOX 114,
// "I dont think you have redesigned the popup agent yet"). Opens the panel with
// a few runs in it and measures the panel, its header, its rows and its
// buttons, then screenshots it light and dark.
//
//   BASE=http://127.0.0.1:8853 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//   node scratchpad/ui-sweeps/agentpanel.js
const { boot } = require("./lib.js");

const seed = () => {
  setAgentMonitorVisible(true);
  const a = addAgentRun({ kind: "skill", name: "Summarise my week", icon: "ph:sparkle",
    steps: ["Read the week's notes", "Group them by project", "Write the summary"] });
  agentRunStep(a, { index: 0, state: "done" });
  agentRunStep(a, { index: 1, state: "running" });
  const b = addAgentRun({ kind: "job", name: "Loading the embedding model", detail: "Background job" });
  endAgentRun(b, { state: "done" });
  addAgentRun({ kind: "agent", name: "What did I decide about the kitchen?", steps: ["Search the notes", "Answer"] });
  return true;
};

const measure = () => {
  const px = (v) => Math.round(parseFloat(v) * 10) / 10;
  const panel = document.getElementById("agent-monitor");
  const r = panel.getBoundingClientRect();
  const cs = getComputedStyle(panel);
  const head = document.querySelector(".monitor-header");
  const title = document.querySelector(".monitor-title");
  const buttons = [...document.querySelectorAll(".monitor-header-actions button")].map((b) => ({
    id: b.id.replace("agent-monitor-", ""), h: Math.round(b.getBoundingClientRect().height),
    font: getComputedStyle(b).fontSize, bg: getComputedStyle(b).backgroundColor,
    border: getComputedStyle(b).borderTopWidth, shadow: getComputedStyle(b).boxShadow === "none" ? "none" : "shadow",
  }));
  const runs = document.getElementById("agent-monitor-runs");
  const rows = [...runs.querySelectorAll(".agent-run-row")].map((el) => Math.round(el.getBoundingClientRect().height));
  const name = document.querySelector(".agent-run-name");
  const state = document.querySelector(".agent-run-state");
  const empty = document.getElementById("agent-monitor-empty");
  return {
    panel: { w: Math.round(r.width), h: Math.round(r.height), pad: cs.padding, radius: px(cs.borderTopLeftRadius),
      shadow: cs.boxShadow.slice(0, 34), left: Math.round(r.left), bottom: Math.round(window.innerHeight - r.bottom),
      gap: cs.gap, display: cs.display },
    header: { h: Math.round(head.getBoundingClientRect().height), padBottom: getComputedStyle(head).paddingBottom,
      border: getComputedStyle(head).borderBottomWidth,
      titleFont: getComputedStyle(title).fontSize, titleWeight: getComputedStyle(title).fontWeight,
      actionsGap: getComputedStyle(document.querySelector(".monitor-header-actions")).gap },
    buttons,
    runs: { h: Math.round(runs.getBoundingClientRect().height), padTop: getComputedStyle(runs).paddingTop,
      gap: getComputedStyle(runs).gap, maxH: getComputedStyle(runs).maxHeight,
      scrolls: runs.scrollHeight > runs.clientHeight + 1, rows },
    rowType: { name: getComputedStyle(name).fontSize, nameWeight: getComputedStyle(name).fontWeight,
      state: getComputedStyle(state).fontSize, stateColour: getComputedStyle(state).color },
    emptyShown: !empty.classList.contains("hidden"),
  };
};

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await page.waitForTimeout(1500);
  await page.evaluate(seed);
  await page.waitForTimeout(800);
  console.log(JSON.stringify(await page.evaluate(measure), null, 1));
  await (await page.$("#agent-monitor")).screenshot({ path: process.env.SHOT || "/tmp/agentpanel.png" });
  // The log half of the panel, and the contrast of everything in both halves
  // against the panel's own ground (it is opaque by rule, see the CSS).
  await page.evaluate(() => {
    const logs = document.getElementById("agent-monitor-logs");
    for (const line of ["Reading 12 notes", "sentence-transformers/all-MiniLM-L6-v2 loaded", "Skill: weekly summary"]) {
      const div = document.createElement("div");
      div.className = "monitor-log-item info";
      div.textContent = line;
      logs.appendChild(div);
    }
    setAgentMonitorLogVisible(true);
  });
  await page.waitForTimeout(500);
  console.log("contrast " + JSON.stringify(await page.evaluate(() => {
    const parse = (css) => { const m = css.match(/rgba?\(([^)]+)\)/); if (!m) return { r: 0, g: 0, b: 0, a: 0 };
      const p = m[1].split(/[ ,/]+/).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
    const over = (t, b) => ({ r: t.r * t.a + b.r * (1 - t.a), g: t.g * t.a + b.g * (1 - t.a), b: t.b * t.a + b.b * (1 - t.a), a: 1 });
    const lum = (c) => { const f = (v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
    const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return Math.round((x + 0.05) / (y + 0.05) * 100) / 100; };
    const page_ = parse(getComputedStyle(document.body).backgroundColor);
    const panel = document.getElementById("agent-monitor");
    const ground = over(parse(getComputedStyle(panel).backgroundColor), { ...page_, a: 1 });
    const on = (sel) => { const el = document.querySelector(sel); return el ? ratio(over(parse(getComputedStyle(el).color), ground), ground) : null; };
    return { title: on(".monitor-title"), meta: on(".agent-run-meta"), state: on(".agent-run-state"),
      log: on(".monitor-log-item"), clear: on("#agent-monitor-clear"), empty: on(".monitor-empty") };
  })));
  await (await page.$("#agent-monitor")).screenshot({ path: (process.env.SHOT || "/tmp/agentpanel.png").replace(".png", "-log.png") });
  await browser.close();
})();
