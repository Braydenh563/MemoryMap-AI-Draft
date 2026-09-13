// The "new from a template" dialog against the app's other dialogs (INBOX 114,
// "the new from a template popup buttons need a look consistent with the rest
// of the application"). Measures the six choice rows and the Cancel beside the
// same numbers taken from a confirm dialog and the document history dialog.
//
//   BASE=http://127.0.0.1:8853 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
//   node scratchpad/ui-sweeps/tpldialog.js
const { boot } = require("./lib.js");

const sig = (el) => {
  const c = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  return {
    bg: c.backgroundColor, border: `${c.borderTopWidth} ${c.borderTopColor}`,
    radius: c.borderTopLeftRadius, shadow: c.boxShadow === "none" ? "none" : c.boxShadow.slice(0, 40),
    pad: c.padding, h: Math.round(r.height), font: c.fontSize, weight: c.fontWeight,
  };
};

(async () => {
  const { browser, page } = await boot({ viewport: { width: 1440, height: 900 } });
  await page.waitForTimeout(1200);
  await page.evaluate(() => switchTab("documents"));
  await page.waitForTimeout(2000);
  await page.click("#doc-new-template");
  await page.waitForTimeout(600);
  const shot = process.env.SHOT || "/tmp/tpl.png";
  await page.screenshot({ path: shot });
  const out = await page.evaluate((sigSrc) => {
    const sig = eval(`(${sigSrc})`);
    const dialog = document.getElementById("doc-template-dialog");
    const rows = [...dialog.querySelectorAll(".doc-template-choice")];
    const cancel = dialog.querySelector(".space-dialog-actions button");
    const list = document.getElementById("doc-template-list");
    return {
      rows: rows.length,
      row: sig(rows[0]),
      gap: getComputedStyle(list).gap,
      listMargin: getComputedStyle(list).margin,
      cancel: sig(cancel),
      dialogW: Math.round(dialog.getBoundingClientRect().width),
      dialogH: Math.round(dialog.getBoundingClientRect().height),
      outlined: rows.filter((b) => parseFloat(getComputedStyle(b).borderTopWidth) > 0).length,
    };
  }, sig.toString());
  console.log("template dialog " + JSON.stringify(out, null, 1));
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
  // A confirm dialog, for the app's own dialog-action look.
  const confirm = await page.evaluate((sigSrc) => {
    const sig = eval(`(${sigSrc})`);
    confirmDialog({ title: "A question", message: "Numbers, not a screenshot.", confirmLabel: "Do it" });
    const buttons = [...document.querySelectorAll(".confirm-overlay .confirm-actions button")];
    return buttons.map((b) => ({ label: b.textContent.trim(), cls: b.className, ...sig(b) }));
  }, sig.toString());
  console.log("confirm actions " + JSON.stringify(confirm, null, 1));
  // Every dialog in the family, not only this one: the `right` in their markup
  // matched no rule at all until now.
  console.log("action rows " + JSON.stringify(await page.evaluate(() => {
    const rows = [...document.querySelectorAll(".space-dialog-actions")];
    const kinds = {};
    for (const r of rows) {
      const k = getComputedStyle(r).justifyContent;
      kinds[k] = (kinds[k] || 0) + 1;
    }
    return { rows: rows.length, kinds };
  })));
  await browser.close();
})();
