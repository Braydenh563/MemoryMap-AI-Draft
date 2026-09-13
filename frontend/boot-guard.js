// Runs before anything else, and is deliberately the only file that must
// never fail. See the comment on its <script> tag in index.html for why it
// is a file rather than an inline block.
//
// **What it is for.** Reported: "idk if it is just slow but the app is stuck
// on th eloading screen", with a screenshot of the progress bar stalled
// short of the end, and later "the loading issue is only on the pydesktop
// view".
//
// `initAuth()` in app.js already bounds its own `/auth/status` probe at 8s
// and hides the splash on every branch, so it cannot hang *if it runs*. The
// failures this covers are the ones where it never runs at all: a runtime
// error earlier in app.js, a script the CSP refused, or an asset that 404s.
// In every one of those the splash sits at ~90% with its dots animating from
// CSS, which looks exactly like "still loading" and is not.
(function () {
  // **Every failure also goes to the server log.** Asked for directly: "can
  // you make any other erros like what aoppeared on the loading screen appear
  // in the logs as well?? the terminal and logs need to capture everything."
  //
  // The gap was real and had just cost a session: a JavaScript error aborts
  // the rest of the file it is in, so the app can hang with nothing in the
  // terminal, nothing in Settings → Logs, and the only record in a browser
  // console nobody opens: least of all in the desktop shell, which has no
  // obvious way to open one.
  //
  // `keepalive` so a report still leaves even if the page is being torn down
  // as it fires. No token: `/logs/client` sits outside the unlock
  // gate precisely because these failures happen before unlock. Failures
  // here are swallowed: a logger that throws while reporting a crash would
  // replace the message on screen with its own.
  var reported = 0;
  function report(kind, message, source) {
    // A loop that throws on every frame would otherwise post thousands of
    // identical lines and push everything useful out of a 500-record buffer.
    if (reported >= 5) return;
    reported += 1;
    try {
      fetch("/logs/client", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        keepalive: true,
        body: JSON.stringify({
          kind: kind,
          message: String(message || "").slice(0, 2000),
          source: String(source || "").slice(0, 500),
        }),
      }).catch(function () {});
    } catch (ignored) {
      /* reporting must never be the thing that fails */
    }
  }

  function say(text) {
    var splash = document.getElementById("boot-splash");
    if (!splash || splash.classList.contains("hidden")) return;
    var line = document.getElementById("boot-splash-error");
    if (!line) {
      line = document.createElement("p");
      line.id = "boot-splash-error";
      line.className = "boot-splash-error";
      line.setAttribute("role", "alert");
      splash.appendChild(line);
    }
    line.textContent = text;
  }

  // A script error is the likeliest cause and the one worth naming exactly:
  // it is the difference between "my machine is slow" and "this build is
  // broken", and nobody can tell those apart from a progress bar.
  // **No "press Ctrl+Shift+R" here.** Reported immediately after the first
  // version said exactly that: "ctrl shift r hard reload doesnt work as it is
  // a hothey", in the desktop shell that chord is bound to something else,
  // so the one instruction on a dead screen was one the reader could not
  // follow. Restarting the app is the advice that works in every shell this
  // runs in, and it also fixes the stale-server case below.
  window.addEventListener("error", function (event) {
    report(
      "error",
      event.message,
      event.filename ? event.filename + ":" + event.lineno + ":" + event.colno : ""
    );
    say(
      "Something failed while starting: " +
        (event.message || "a script error") +
        ". Close MemoryMap and start it again. If it keeps happening this is " +
        "a bug \u2014 the message above is the useful part of the report."
    );
  });

  // A CSP refusal does not fire `error` with a useful message, and it is the
  // failure mode most likely to leave a completely blank app, so it is
  // reported specifically, with the one thing that actually fixes it.
  document.addEventListener("securitypolicyviolation", function (event) {
    report(
      "csp",
      "blocked " + (event.violatedDirective || "script-src") + ": " + (event.blockedURI || "inline"),
      event.sourceFile || ""
    );
    say(
      "The app blocked one of its own scripts (" +
        (event.violatedDirective || "script-src") +
        "). This usually means the MemoryMap server is still running from " +
        "before an update \u2014 close MemoryMap completely and start it again."
    );
  });

  // An unhandled promise rejection never fires `error`, and every network
  // call in this app is a promise, so the most likely runtime failure after
  // load was the one class going unreported. Not surfaced on the splash: by
  // the time these happen the app is usually up, and a rejected fetch is
  // often already handled by a toast. The log is the right place for it.
  window.addEventListener("unhandledrejection", function (event) {
    var reason = event.reason;
    report(
      "unhandledrejection",
      (reason && (reason.stack || reason.message)) || String(reason),
      ""
    );
  });

  // **A way out, not just a message.** The 12-second notice below has been
  // here a while and it names the one remedy that works in every shell, but
  // it is still an instruction on a dead screen, and the report that prompted
  // this ("it went back to the loading screen and got stuck there") is a case
  // where a plain reload is all that is needed. A button is one click; closing
  // and reopening the app is not.
  function offerReload(splash) {
    if (document.getElementById("boot-splash-reload")) return;
    var button = document.createElement("button");
    button.id = "boot-splash-reload";
    button.type = "button";
    button.className = "boot-splash-reload";
    button.textContent = "Try again";
    button.addEventListener("click", function () {
      // `true` is ignored by modern browsers and harmless; the plain reload is
      // what re-runs boot. Deliberately not `location.href = "/"`, that would
      // discard a deep link the reader may have arrived on.
      location.reload();
    });
    splash.appendChild(button);
  }

  // Eight seconds, then twelve. `initAuth()` bounds its own /auth/status
  // probe at 8s, so a boot still on screen at that point has already used
  // up the one wait the app plans for: the reader has been looking at a
  // crawling bar with nothing to do about it. This says so and gives them
  // the button, without yet claiming anything is broken, which at eight
  // seconds it may not be. The 12-second notice below still follows and
  // still names the remedy that works in every shell; the two are
  // deliberately different sentences.
  setTimeout(function () {
    var splash = document.getElementById("boot-splash");
    if (!splash || splash.classList.contains("hidden")) return;
    say("Still loading. Give it a moment, or reload.");
    offerReload(splash);
  }, 8000);

  setTimeout(function () {
    say(
      "This is taking longer than it should. Try again, and if it still " +
        "doesn't finish, close MemoryMap completely and start it again."
    );
    var splash = document.getElementById("boot-splash");
    if (splash && !splash.classList.contains("hidden")) offerReload(splash);
  }, 12000);
})();
