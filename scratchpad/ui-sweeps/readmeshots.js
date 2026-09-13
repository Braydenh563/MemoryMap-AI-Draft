// The README's eight screenshots, recaptured. HANDOVER done-when item 5b, and
// the owner's own note: "I think the screen shots on the readme need an
// update from all the ui changes."
//
// Light theme at 1440x900, which is what the existing set is and what the
// README's 850px-wide <img> tags are sized for. One file per tab, written
// straight over docs/screenshots/.
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const fs = require('fs');
const PW = 'testpassword123';
const BASE = process.env.BASE || 'http://127.0.0.1:8800';
const OUT = process.env.OUT || 'docs/screenshots';

// Documents is a Library sub-tab, so it is reached differently from the rest,
// and so are the five surfaces added below it. A `sub` is a second step taken
// after the tab click, named here and handled in the loop.
//
// **Why five more.** Reported: the README's shots "need to show more parts of
// the application than what is there". The eight above are the seven tab
// buttons plus the document editor, which leaves out the surfaces built since:
// boards, concept maps, the page reader, the file gallery, and the command
// palette that reaches all of them. A tour that stops at the tab bar describes
// a smaller app than the one that ships.
const SHOTS = [
  { file: 'dashboard', tab: 'dashboard' },
  { file: 'notes', tab: 'notes' },
  { file: 'chat', tab: 'chat' },
  { file: 'graph', tab: 'graph' },
  { file: 'library', tab: 'library' },
  { file: 'timeline', tab: 'timeline' },
  { file: 'reminders', tab: 'reminders' },
  { file: 'documents', tab: 'library', sub: 'documents' },
  { file: 'whiteboard', tab: 'library', sub: 'board', board: 'Website relaunch' },
  { file: 'map', tab: 'library', sub: 'board', board: 'Bubble tea' },
  { file: 'features', tab: 'dashboard', sub: 'features' },
  { file: 'palette', tab: 'dashboard', sub: 'palette' },
  { file: 'appearance', tab: 'dashboard', sub: 'appearance' },
];

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  await ctx.addInitScript(() => {
    try {
      localStorage.setItem('theme', 'light');
      localStorage.setItem('onboardingDone', '1');
      //: The graph's own defaults spread 59 notes into a field of dots with
      //: no readable structure, which is not what the README's caption
      //: describes ("a map of notes coloured by category, with links between
      //: related notes"). Gravity at 85 pulls the map into something a
      //: reader can see the shape of. Both are ordinary settings a person can
      //: reach from the graph's own controls, not a state only a script can
      //: produce.
      localStorage.setItem('graph-gravity', '85');
      localStorage.setItem('graph-spread', '35');
    } catch (e) {}
  });
  const page = await ctx.newPage();
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#lock-password', { state: 'visible', timeout: 20000 });
  await page.fill('#lock-password', PW);
  await page.click('#lock-submit');
  await page.waitForTimeout(3500);
  await page.evaluate(() => { const o = document.getElementById('onboarding-overlay'); if (o) o.classList.add('hidden'); });
  //: **One thing is hidden, and only this one.** `#ai-status` shows a red
  //: badge here reading "Search AI didn't load, ModuleNotFound", because this
  //: sandbox deliberately never installs `sentence-transformers` (CLAUDE.md
  //: section 7 forbids it). That is an artefact of the machine the shots are
  //: taken on, not a state a person who installed the app would see, so
  //: leaving it in would misrepresent the app rather than document it.
  //: Nothing else in these captures is altered: no state is faked, no empty
  //: panel is filled, and the data is whatever `seed.js` and its companions
  //: put there.
  //: `el.style` rather than `addStyleTag`: this app's CSP is `style-src
  //: 'self'` with no nonce, so an injected stylesheet is refused outright
  //: (CLAUDE.md section 6 item 4, and it refused this one on the first try).
  //: Re-applied after every tab switch, since a tab that re-renders its own
  //: status bar would put the chip back.
  const hideSandboxBadge = () => page.evaluate(() => {
    for (const el of document.querySelectorAll('.ai-status-wrap')) el.style.visibility = 'hidden';
    //: Two more artefacts of a *first* run on a fresh data directory, not of
    //: the app: the agent monitor opens itself to report "Loading the
    //: embedding model" (a one-time ~90 MB download that a person who has
    //: used the app once has already done), and its toast lands on top of the
    //: widgets. Both were sitting over the dashboard hero in the set this
    //: replaced. Closed the way a person closes them, rather than hidden:
    //: the monitor has a close button and a toast expires.
    document.getElementById('agent-monitor')?.classList.add('hidden');
    document.getElementById('toast-box')?.replaceChildren();
  });
  await hideSandboxBadge();

  //: **The theme is set through the app, not through localStorage.** The
  //: block above sets `theme` in storage and the previous set came out dark
  //: anyway: the choice is an appearance preference stored on the server
  //: (`applyThemeChoice`, settings.js), and the stored one wins over anything
  //: a script puts in storage before the app boots. So it is chosen here, the
  //: same call the Appearance panel's own buttons make, and every shot in the
  //: set is the same theme rather than whichever one the data dir happened to
  //: hold.
  await page.evaluate(() => applyThemeChoice('dark', true));
  await page.waitForTimeout(900);

  const done = [];
  for (const shot of SHOTS) {
    await page.click(`[data-tab="${shot.tab}"]`).catch(() => {});
    await page.waitForTimeout(2500);
    if (shot.sub === 'board') {
      //: A board is opened the way a person opens one: the Boards & maps
      //: sub-tab, then the card. Opening it by id through the API would skip
      //: exactly the gallery step that decides which board is on screen.
      await page.click('[data-target="library-view-whiteboard"]').catch(() => {});
      await page.waitForTimeout(1200);
      const card = page.locator('.library-board-card', { hasText: shot.board }).first();
      await card.click({ timeout: 8000 }).catch(() => {});
      //: The canvas draws after the board's objects land, and a screenshot of
      //: a board mid-load is a screenshot of an empty grid.
      await page.waitForTimeout(3500);
      //: "Fit to screen", the board's own View action (`wbZoomToFit`): a board
      //: opens at the position it was last left at, which for a freshly seeded
      //: one clipped the banner card along the top edge of the first capture.
      //: Fitting is what a person does on opening a board they have not seen.
      await page.evaluate(() => wbZoomToFit({ animate: false }));
      await page.waitForTimeout(1200);
    }
    if (shot.sub === 'features') {
      //: The catalogue of what the app can do, which is both a feature worth
      //: showing and the honest answer to "what else is in here" that a
      //: screenshot tour can only gesture at. Its AI-tool group is fetched on
      //: open, hence the wait.
      await page.evaluate(() => openFeatures());
      await page.waitForTimeout(2500);
    }
    if (shot.sub === 'appearance') {
      //: Themes, accent, typography, density, glass and the animated
      //: background in one panel: the part of the app a person changes on
      //: their first evening with it, and nothing in the old set showed that
      //: any of it existed.
      await page.evaluate(() => openSettingsModal('appearance'));
      await page.waitForTimeout(2500);
    }
    if (shot.sub === 'palette') {
      await page.evaluate(() => openPalette());
      await page.waitForTimeout(700);
      //: Typed rather than left empty: the palette's point is that one string
      //: reaches a command, a note, a document, a file and a board at once,
      //: and an empty box shows only the commands.
      await page.fill('#palette-input', 'map').catch(() => {});
      await page.waitForTimeout(1200);
    }
    if (shot.sub === 'documents') {
      // The app's own route in, the same one `docopen.js` uses: a click on a
      // list row did not open the editor, and the README's caption describes
      // the editor rather than a list of one row.
      const opened = await page.evaluate(async () => {
        const r = await api('/documents');
        const list = await r.json();
        if (!list.length) return 'no documents';
        switchTab('documents');
        await openDocument(list[0].id);
        return 'opened ' + list[0].id;
      });
      await page
        .waitForSelector('#doc-editor .cm-content', { state: 'visible', timeout: 15000 })
        .catch(() => {});
      await page.waitForTimeout(2000);
      if (!String(opened).startsWith('opened')) console.log('NOTE:', opened);
    }
    // Nothing hovered, nothing focused: a focus ring in a marketing shot
    // reads as a rendering fault. The palette is the one exception: it is a
    // typed-into box, and blurring it closes the overlay the shot is of.
    await hideSandboxBadge();
    await page.mouse.move(1439, 899);
    if (shot.sub !== 'palette') {
      await page.evaluate(() => document.activeElement && document.activeElement.blur());
    }
    await page.waitForTimeout(600);
    const path = `${OUT}/${shot.file}.png`;
    await page.screenshot({ path });
    done.push({ file: shot.file, bytes: fs.statSync(path).size });
    //: Whatever this shot opened is closed before the next one: an overlay
    //: left up (the reader, the palette) would be in every picture after it.
    await page.keyboard.press('Escape').catch(() => {});
    await page.waitForTimeout(500);
  }
  console.log(JSON.stringify(done, null, 1));
  await browser.close();
})();
