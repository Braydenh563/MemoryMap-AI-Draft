<#
  MemoryMap AI - launch splash.

  WHY THIS EXISTS
  ---------------
  Reported directly: the pre-launch work (git pull, building .venv, pip
  installing several hundred megabytes of dependencies) "takes a while to
  actually open the window so the user doesn't think the application didn't
  start properly because they didn't have access to the terminal logs".

  That gap is real and it is the worst one in the whole product. `__main__.py`
  already shows a loading window with a progress bar - but that window is
  created by Python, and everything above happens in start.bat *before* Python
  can run at all. On a first run, or any run where requirements.txt changed,
  that is minutes of a machine doing nothing visible. In console-less mode
  (show_console_on_startup = False, and the packaged build) there is not even a
  terminal to watch, so the only feedback is that double-clicking the icon
  appeared to do nothing.

  So: an Adobe-style splash, up within a second of the double-click, showing
  what is happening, handed off to the Python loading window when that appears.

  HOW IT TALKS TO THE LAUNCHER
  ----------------------------
  One status file, polled. The launcher appends a line per phase transition:

      step|total|title|detail|state          state in active, done, failed

  and this reads the whole file, not just the last line, so the window can draw
  every step that has happened with a tick beside it rather than one sentence
  with no context. `src/memorymap/core/launch_status.py` is the same grammar in
  Python, for the loading window that takes over from this one; the two are
  kept in step by tests/test_launcher_scripts.py.

  Deliberately a file rather than a pipe or a named event: start.bat is
  cmd.exe, which can write a file with `echo >` and essentially nothing else,
  and a file also gives us the shutdown signal for free - when the file
  disappears, the launcher is done and this exits.

  Three independent ways to die, because a splash that outlives its launcher is
  worse than no splash at all: the status file says __done__, the status file is
  deleted, or MaxMinutes elapses. The last one is the backstop for a launcher
  killed with Ctrl+C or Task Manager, which deletes nothing on its way out.

  Cancel writes "__cancel__" into "<status file>.cancel", which the launcher
  polls between phases and honours. Between phases and not during one, because
  killing a pip mid-install leaves a half-written venv.

  Everything here is best-effort. It is wrapped in a try/catch that exits
  quietly, and start.bat launches it detached and never checks whether it
  worked: a cosmetic window failing to appear must not stop the app starting.
#>
param(
  [Parameter(Mandatory = $true)][string]$StatusFile,
  [int]$MaxMinutes = 20,
  # Where the app's own icon is. Reported directly: the splash window and its
  # taskbar button showed the PowerShell icon, because a WinForms form with no
  # `Icon` set inherits the icon of the process hosting it - and the process
  # hosting this is powershell.exe. Defaulted rather than required so the
  # script still runs standalone; resolved below, relative to this file, so it
  # works from a checkout without start.bat passing anything.
  [string]$IconPath = "",
  # The launcher log for this run, so Details can show its tail and the error
  # card can offer to open it. Empty is fine: those two just say so.
  [string]$LogPath = "",
  # The launcher itself, for the error card's "Try again". Empty disables it.
  [string]$LauncherPath = "",
  # Printed in the tips, because "where are my notes" is the most-asked
  # question this app has.
  [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"
try {
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing

  # Reported: the marquee bar below "doesn't actually progress" - it isn't a
  # regression of the ForeColor/BackColor fix already documented on $bar
  # further down, it's a second, independent cause of the same symptom.
  # WinForms renders every control with the classic (pre-XP, unthemed)
  # renderer unless the process opts into visual styles explicitly, and the
  # *classic* renderer does not animate a Marquee-style ProgressBar at all -
  # it just sits there, themed colours or not. Hosted here inside
  # powershell.exe, which carries no manifest asking for visual styles on its
  # own behalf, so nothing turns them on unless this script does. Must run
  # before any control is created - set after the fact, it does nothing.
  [System.Windows.Forms.Application]::EnableVisualStyles()
  [System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)

  # Same palette as _LOADING_HTML in __main__.py, so the handoff from this
  # window to that one does not read as two different applications.
  $bg     = [System.Drawing.Color]::FromArgb(18, 20, 28)
  $ink    = [System.Drawing.Color]::FromArgb(231, 233, 238)
  $muted  = [System.Drawing.Color]::FromArgb(154, 161, 173)
  $dim    = [System.Drawing.Color]::FromArgb(93, 100, 114)
  $accent = [System.Drawing.Color]::FromArgb(79, 109, 245)
  $good   = [System.Drawing.Color]::FromArgb(74, 157, 122)
  $warn   = [System.Drawing.Color]::FromArgb(229, 161, 58)
  $bad    = [System.Drawing.Color]::FromArgb(229, 143, 143)
  $panel  = [System.Drawing.Color]::FromArgb(28, 31, 42)

  $COLLAPSED_HEIGHT = 372
  $EXPANDED_HEIGHT  = 476

  $form                 = New-Object System.Windows.Forms.Form
  $form.FormBorderStyle = "None"
  $form.StartPosition   = "CenterScreen"
  $form.Size            = New-Object System.Drawing.Size(520, $COLLAPSED_HEIGHT)
  $form.BackColor       = $bg
  $form.TopMost         = $true
  $form.ShowInTaskbar   = $true
  $form.Text            = "Starting MemoryMap AI"

  # The window's icon, and therefore the taskbar button's. Best-effort in
  # every direction: the icon file may genuinely not be there yet - this
  # script runs during the phase where the checkout is still being updated,
  # which is the whole reason the logo below is *drawn* rather than loaded -
  # and a missing icon is a cosmetic detail, never a reason for the loading
  # window to fail to appear.
  if (-not $IconPath) {
    $IconPath = Join-Path (Split-Path -Parent $PSScriptRoot) "frontend\icon.ico"
  }
  try {
    if (Test-Path -LiteralPath $IconPath) {
      $form.Icon = New-Object System.Drawing.Icon($IconPath)
    }
  } catch {
    # Keep the default icon rather than no window.
  }

  # The mark, drawn rather than loaded. Same geometry as frontend/favicon.svg
  # (a hub with notes orbiting it on spokes). Drawing it avoids depending on a
  # file path that differs between a git checkout and the packaged build - and
  # this script may be running before the checkout has even finished updating.
  $logo = New-Object System.Windows.Forms.Panel
  $logo.Size     = New-Object System.Drawing.Size(64, 64)
  $logo.Location = New-Object System.Drawing.Point(28, 26)
  $logo.BackColor = $bg
  $logo.Add_Paint({
    param($src, $e)
    $g = $e.Graphics
    $g.SmoothingMode = "AntiAlias"
    $rect = New-Object System.Drawing.Rectangle(0, 0, 63, 63)
    $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush -ArgumentList `
      $rect, `
      ([System.Drawing.Color]::FromArgb(91, 124, 255)), `
      ([System.Drawing.Color]::FromArgb(169, 39, 216)), `
      ([float]45.0)
    # A rounded tile, matching the favicon's rx=23 at a 100-unit viewBox.
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $r = 15
    $path.AddArc(0, 0, $r * 2, $r * 2, 180, 90)
    $path.AddArc(63 - $r * 2, 0, $r * 2, $r * 2, 270, 90)
    $path.AddArc(63 - $r * 2, 63 - $r * 2, $r * 2, $r * 2, 0, 90)
    $path.AddArc(0, 63 - $r * 2, $r * 2, $r * 2, 90, 90)
    $path.CloseFigure()
    $g.FillPath($brush, $path)

    # Five spokes and five notes, at the favicon's own coordinates scaled
    # from its 100-unit viewBox down to 64px.
    $s = 64.0 / 100.0
    $penColour = [System.Drawing.Color]::FromArgb(235, 255, 255, 255)
    $pen = New-Object System.Drawing.Pen -ArgumentList $penColour, ([float](5.5 * $s))
    $pen.StartCap = "Round"; $pen.EndCap = "Round"
    $white = New-Object System.Drawing.SolidBrush -ArgumentList ([System.Drawing.Color]::White)
    $nodes = @(@(50, 20), @(78.5, 40.7), @(67.6, 74.3), @(32.4, 74.3), @(21.5, 40.7))
    foreach ($n in $nodes) {
      $g.DrawLine($pen, (50 * $s), (50 * $s), ($n[0] * $s), ($n[1] * $s))
    }
    foreach ($n in $nodes) {
      $g.FillEllipse($white, (($n[0] - 7.5) * $s), (($n[1] - 7.5) * $s), (15 * $s), (15 * $s))
    }
    $hub = New-Object System.Drawing.SolidBrush -ArgumentList $accent
    $g.FillEllipse($hub, ((50 - 13) * $s), ((50 - 13) * $s), (26 * $s), (26 * $s))
    $g.FillEllipse($white, ((50 - 9.5) * $s), ((50 - 9.5) * $s), (19 * $s), (19 * $s))

    $pen.Dispose(); $white.Dispose(); $hub.Dispose(); $brush.Dispose(); $path.Dispose()
  })

  $title           = New-Object System.Windows.Forms.Label
  $title.Text      = "MemoryMap AI"
  $title.ForeColor = $ink
  $title.Font      = New-Object System.Drawing.Font -ArgumentList "Segoe UI", ([float]17), ([System.Drawing.FontStyle]::Bold)
  $title.Location  = New-Object System.Drawing.Point(108, 34)
  $title.Size      = New-Object System.Drawing.Size(380, 32)

  $tag             = New-Object System.Windows.Forms.Label
  $tag.Text        = "Your notebook, on your own machine"
  $tag.ForeColor   = $muted
  $tag.Font        = New-Object System.Drawing.Font -ArgumentList "Segoe UI", ([float]9)
  $tag.Location    = New-Object System.Drawing.Point(110, 66)
  $tag.Size        = New-Object System.Drawing.Size(380, 20)

  # --- The step list ---------------------------------------------------
  # Eight rows created once and reused, rather than rebuilt each tick: a
  # WinForms control added and removed four times a second flickers, and the
  # launcher never writes more steps than this.
  $MAX_ROWS  = 6
  $ROW_TOP   = 104
  $ROW_STEP  = 22
  # The marquee's place in a row: under the detail text, never across it.
  # Reported with a screenshot: the bar at +6 ran straight through
  # "Checking for updates on GitHub, 1s". The detail label is 16px tall
  # from +2, so the bar starts at +18 and is 3px, leaving the next row's
  # top edge at +22 untouched.
  $BAR_DROP   = 18
  $BAR_HEIGHT = 3
  $rowMark   = @()
  $rowName   = @()
  $rowDetail = @()
  for ($i = 0; $i -lt $MAX_ROWS; $i++) {
    $mark            = New-Object System.Windows.Forms.Label
    $mark.Font       = New-Object System.Drawing.Font -ArgumentList "Segoe UI", ([float]10)
    $mark.ForeColor  = $dim
    $mark.Location   = New-Object System.Drawing.Point(30, ($ROW_TOP + $i * $ROW_STEP))
    $mark.Size       = New-Object System.Drawing.Size(18, 20)
    $mark.Text       = ""

    $name            = New-Object System.Windows.Forms.Label
    $name.Font       = New-Object System.Drawing.Font -ArgumentList "Segoe UI", ([float]10)
    $name.ForeColor  = $dim
    $name.Location   = New-Object System.Drawing.Point(50, ($ROW_TOP + $i * $ROW_STEP))
    $name.Size       = New-Object System.Drawing.Size(118, 20)
    $name.Text       = ""

    $detail           = New-Object System.Windows.Forms.Label
    $detail.Font      = New-Object System.Drawing.Font -ArgumentList "Segoe UI", ([float]9)
    $detail.ForeColor = $dim
    $detail.Location  = New-Object System.Drawing.Point(170, ($ROW_TOP + 2 + $i * $ROW_STEP))
    $detail.Size      = New-Object System.Drawing.Size(320, 16)
    $detail.Text      = ""

    $rowMark   += $mark
    $rowName   += $name
    $rowDetail += $detail
  }

  # Marquee, and only ever inside the active step: the launcher genuinely does
  # not know how far through a pip install it is, so the *step* bar below shows
  # real progress (steps finished over total) and this shows "still working" on
  # the one step that is running. Before the protocol carried step and total
  # there was nothing but this, and a marquee alone cannot tell a launcher that
  # is working from one that is wedged.
  $bar          = New-Object System.Windows.Forms.ProgressBar
  $bar.Style    = "Marquee"
  # Milliseconds per step. 30 is brisk; 0 would stop it dead, which is the
  # other way to get the reported "empty bar".
  $bar.MarqueeAnimationSpeed = 30
  $bar.Location = New-Object System.Drawing.Point(170, ($ROW_TOP + $BAR_DROP))
  $bar.Size     = New-Object System.Drawing.Size(320, $BAR_HEIGHT)
  $bar.Visible  = $false
  # **No ForeColor/BackColor.** Reported: the bar "just stays empty".
  #
  # Setting either on a WinForms ProgressBar switches the control off the
  # themed (visual-styles) renderer and onto the plain one - and the plain
  # renderer does not draw a Marquee at all. So the two colour lines that were
  # here made the animation invisible while leaving the control present, which
  # is exactly "an empty bar". The theme's own accent is close enough to this
  # app's that losing the custom colour costs nothing next to losing the
  # animation.

  # The real one: steps finished over total. The active step counts as not yet
  # done, so this cannot reach 100% while the last and longest phase is still
  # running. Continuous, and it deliberately carries no ForeColor either, for
  # the same themed-renderer reason as the marquee above.
  $progress          = New-Object System.Windows.Forms.ProgressBar
  $progress.Style    = "Continuous"
  $progress.Minimum  = 0
  $progress.Maximum  = 100
  $progress.Value    = 0
  $progress.Location = New-Object System.Drawing.Point(30, 286)
  $progress.Size     = New-Object System.Drawing.Size(460, 8)

  $status           = New-Object System.Windows.Forms.Label
  $status.Text      = "Starting…"
  $status.ForeColor = $muted
  $status.Font      = New-Object System.Drawing.Font -ArgumentList "Segoe UI", ([float]9)
  $status.Location  = New-Object System.Drawing.Point(30, 300)
  $status.Size      = New-Object System.Drawing.Size(460, 26)

  # The slow-step hint. Empty almost always: it appears only when a step has
  # outlasted the time that step normally takes, which is the moment someone
  # starts wondering whether anything is happening at all.
  $hint             = New-Object System.Windows.Forms.Label
  $hint.Text        = ""
  $hint.ForeColor   = $warn
  $hint.Font        = New-Object System.Drawing.Font -ArgumentList "Segoe UI", ([float]8)
  $hint.Location    = New-Object System.Drawing.Point(30, 240)
  $hint.Size        = New-Object System.Drawing.Size(460, 18)

  # One tip at a time, changed every six seconds. The same five the desktop
  # loading window and the browser boot splash draw from, so a first run reads
  # as one piece of software across all three.
  $tips = @(
    "Your notes never leave this machine.",
    "Ctrl+K opens the command palette.",
    "The capture box files a thought for you, in the right place.",
    "The first run installs about 300 MB once. Later starts take seconds."
  )
  if ($DataDir) {
    $tips += "Your notes live in $DataDir, as plain files you can copy."
  } else {
    $tips += "Your notes live in your own data folder, as plain files you can copy."
  }

  $tip             = New-Object System.Windows.Forms.Label
  $tip.ForeColor   = $dim
  $tip.Font        = New-Object System.Drawing.Font -ArgumentList "Segoe UI", ([float]8)
  $tip.Location    = New-Object System.Drawing.Point(30, 260)
  $tip.Size        = New-Object System.Drawing.Size(460, 18)
  $tip.Text        = $tips[0]

  # --- The footer -------------------------------------------------------
  # A splash with no way out is a window someone force-quits. Three things,
  # all of which answer a question the reader is actually asking: what is it
  # doing (Details), how do I report this (Copy diagnostics), and how do I
  # stop (Cancel).
  function New-FooterButton([string]$text, [int]$x, [int]$width) {
    $b               = New-Object System.Windows.Forms.Button
    $b.Text          = $text
    $b.Location      = New-Object System.Drawing.Point($x, 334)
    $b.Size          = New-Object System.Drawing.Size($width, 26)
    $b.FlatStyle     = "Flat"
    $b.BackColor     = $panel
    $b.ForeColor     = $muted
    $b.Font          = New-Object System.Drawing.Font -ArgumentList "Segoe UI", ([float]8.5)
    $b.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(48, 53, 68)
    $b.TabStop       = $false
    return $b
  }

  $btnDetails = New-FooterButton "Details" 30 78
  $btnCopy    = New-FooterButton "Copy diagnostics" 116 122
  $btnCancel  = New-FooterButton "Cancel" 412 78

  $details              = New-Object System.Windows.Forms.TextBox
  $details.Multiline    = $true
  $details.ReadOnly     = $true
  $details.ScrollBars   = "Vertical"
  $details.BackColor    = $panel
  $details.ForeColor    = $muted
  $details.BorderStyle  = "None"
  $details.Font         = New-Object System.Drawing.Font -ArgumentList "Consolas", ([float]8)
  $details.Location     = New-Object System.Drawing.Point(30, 372)
  $details.Size         = New-Object System.Drawing.Size(460, 88)
  $details.Visible      = $false

  $form.Controls.AddRange(@($logo, $title, $tag, $bar, $progress, $status, $hint, $tip,
                            $btnDetails, $btnCopy, $btnCancel, $details))
  foreach ($i in 0..($MAX_ROWS - 1)) {
    $form.Controls.AddRange(@($rowMark[$i], $rowName[$i], $rowDetail[$i]))
  }

  # --- Mutable state ----------------------------------------------------
  # A hashtable, not plain variables: assigning to a variable inside a
  # WinForms event script block creates a local that vanishes when the block
  # returns, which is why $drag below has always been one too.
  $st = @{
    rows        = @()      # one entry per step, last state each reached
    activeTitle = ""
    activeSince = (Get-Date)
    tipAt       = 0
    tipSince    = (Get-Date)
    started     = (Get-Date)
    cancelled   = $false
    failed      = $false
    lastRaw     = ""
  }

  function Read-Steps {
    # Every parseable line in the file, collapsed to one row per step with the
    # last state it reached. Unparseable lines are skipped rather than
    # complained about: the file is appended to by a batch script four times a
    # second away, so a half-written line is ordinary, not an error.
    $rows = @{}
    $order = @()
    $lines = Get-Content -LiteralPath $StatusFile -ErrorAction SilentlyContinue
    foreach ($line in $lines) {
      if ($null -eq $line) { continue }
      $parts = $line -split '\|'
      if ($parts.Count -lt 5) { continue }
      $state = $parts[$parts.Count - 1].Trim()
      if ($state -ne "active" -and $state -ne "done" -and $state -ne "failed") { continue }
      $step = 0
      $total = 0
      if (-not [int]::TryParse($parts[0].Trim(), [ref]$step)) { continue }
      if (-not [int]::TryParse($parts[1].Trim(), [ref]$total)) { continue }
      if ($total -lt 1 -or $total -gt 20) { continue }
      if ($step -lt 1 -or $step -gt $total) { continue }
      $rowTitle = $parts[2].Trim()
      if (-not $rowTitle) { continue }
      # Anything past the fourth bar belongs to the detail: it is free text
      # and the launcher does not escape it.
      $rowDetailText = ($parts[3..($parts.Count - 2)] -join '|').Trim()
      if (-not $rows.ContainsKey($step)) { $order += $step }
      $rows[$step] = [pscustomobject]@{
        Step = $step; Total = $total; Title = $rowTitle
        Detail = $rowDetailText; State = $state
      }
    }
    return ($order | Sort-Object | ForEach-Object { $rows[$_] })
  }

  function Update-Rows($steps) {
    $count = @($steps).Count
    # Off unless a row below turns it on: with every step done there is
    # nothing running, and a marquee still animating beside a finished list
    # is the same lie as a bar that reaches 100% early.
    $bar.Visible = $false
    for ($i = 0; $i -lt $MAX_ROWS; $i++) {
      if ($i -ge $count) {
        $rowMark[$i].Text = ""; $rowName[$i].Text = ""; $rowDetail[$i].Text = ""
        continue
      }
      $s = @($steps)[$i]
      $rowName[$i].Text = $s.Title
      if ($s.State -eq "done") {
        $rowMark[$i].Text = [char]0x2713
        $rowMark[$i].ForeColor = $good
        $rowName[$i].ForeColor = $muted
        $rowDetail[$i].ForeColor = $dim
        $rowDetail[$i].Text = $s.Detail
      } elseif ($s.State -eq "failed") {
        $rowMark[$i].Text = [char]0x00D7
        $rowMark[$i].ForeColor = $bad
        $rowName[$i].ForeColor = $bad
        $rowDetail[$i].ForeColor = $bad
        $rowDetail[$i].Text = $s.Detail
      } else {
        $rowMark[$i].Text = [char]0x25CF
        $rowMark[$i].ForeColor = $accent
        $rowName[$i].ForeColor = $ink
        $rowDetail[$i].ForeColor = $muted
        # The elapsed seconds are the point: "still on Dependencies" says
        # nothing, "still on Dependencies, 214s" says whether to worry.
        $secs = [int]((Get-Date) - $st.activeSince).TotalSeconds
        $rowDetail[$i].Text = "$($s.Detail)  $($secs)s"
        # The marquee moves to whichever row is active, and is the only thing
        # in this window that animates while a step is running.
        $bar.Location = New-Object System.Drawing.Point(170, ($ROW_TOP + $BAR_DROP + $i * $ROW_STEP))
        $bar.Visible = $true
      }
    }
  }

  function Update-Hint($steps) {
    # A step that has outlasted its usual time, named with the time it usually
    # takes, so "slow" becomes "slower than it should be" or "normal".
    $hint.Text = ""
    foreach ($s in @($steps)) {
      if ($s.State -ne "active") { continue }
      $secs = ((Get-Date) - $st.activeSince).TotalSeconds
      if ($s.Title -eq "Dependencies" -and $secs -gt 300) {
        $hint.Text = "Dependencies usually finish inside five minutes. A slow connection can take longer; Details shows what pip is doing."
      } elseif ($s.Title -eq "Update" -and $secs -gt 30) {
        $hint.Text = "The update check usually answers in a few seconds. It gives up on its own, and the app starts either way."
      }
    }
  }

  function Read-LogTail([int]$count) {
    if (-not $LogPath) { return "No launcher log for this run yet." }
    if (-not (Test-Path -LiteralPath $LogPath)) { return "No launcher log at $LogPath yet." }
    try {
      $tail = Get-Content -LiteralPath $LogPath -Tail $count -ErrorAction Stop
      if (-not $tail) { return "The launcher log is empty so far." }
      return ($tail -join "`r`n")
    } catch {
      return "Could not read $LogPath."
    }
  }

  # One handler per button, branching on $st.failed, rather than two handlers
  # added at different points: WinForms runs every handler on a button, so a
  # second one added later would fire alongside the first and "Open log" would
  # also toggle the details panel.
  $btnDetails.Add_Click({
    if ($st.failed) {
      if ($LogPath -and (Test-Path -LiteralPath $LogPath)) {
        try { Start-Process -FilePath $LogPath } catch { }
      }
      return
    }
    # Toggles the last eight log lines inline, growing the window rather than
    # scrolling it: a splash that changes size on click is less surprising
    # than one that hides its own footer.
    if ($details.Visible) {
      $details.Visible = $false
      $form.Height = $COLLAPSED_HEIGHT
      $btnDetails.Text = "Details"
    } else {
      $details.Text = Read-LogTail 8
      $details.Visible = $true
      $form.Height = $EXPANDED_HEIGHT
      $btnDetails.Text = "Hide details"
    }
  })

  $btnCopy.Add_Click({
    # What a person is asked for when they report "it will not start": the
    # steps that ran, how long the current one has been going, and the tail of
    # the log. Deliberately NOT a live `start.bat --doctor` run: the doctor
    # probes the port the app is about to bind and talks to the git remote,
    # and running it in the middle of an install is a good way to make the
    # thing being diagnosed worse. The doctor is one command away in a
    # terminal; this is what only the splash knows.
    try {
      $lines = @("MemoryMap AI launch diagnostics", (Get-Date).ToString("u"), "")
      foreach ($s in @($st.rows)) {
        $lines += ("[{0}] {1}/{2} {3}: {4}" -f $s.State, $s.Step, $s.Total, $s.Title, $s.Detail)
      }
      $lines += ""
      $lines += ("Windows: " + [System.Environment]::OSVersion.VersionString)
      $lines += ("PowerShell: " + $PSVersionTable.PSVersion.ToString())
      if ($LogPath) { $lines += ("Log: " + $LogPath) }
      $lines += ""
      $lines += "Last log lines:"
      $lines += (Read-LogTail 20)
      [System.Windows.Forms.Clipboard]::SetText(($lines -join "`r`n"))
      $btnCopy.Text = "Copied"
    } catch {
      $btnCopy.Text = "Could not copy"
    }
  })

  $btnCancel.Add_Click({
    if ($st.failed) { $form.Close(); return }
    # The launcher polls this between phases and stops there. Writing it is
    # all this window does: killing a pip mid-install from here would leave a
    # half-written venv, which is a worse outcome than one more minute.
    try {
      Set-Content -LiteralPath ($StatusFile + ".cancel") -Value "__cancel__" -ErrorAction Stop
      $st.cancelled = $true
      $btnCancel.Enabled = $false
      $status.Text = "Cancelling after this step finishes."
    } catch {
      $status.Text = "Could not cancel. Close the launcher window instead."
    }
  })

  # Borderless windows cannot be moved, and this one sits on top of everything.
  # Dragging it out of the way is the one interaction it needs.
  $drag = @{ on = $false; x = 0; y = 0 }
  $down = { param($s, $e) $drag.on = $true; $drag.x = $e.X; $drag.y = $e.Y }
  $move = {
    param($s, $e)
    if ($drag.on) {
      $form.Location = New-Object System.Drawing.Point(
        ($form.Location.X + $e.X - $drag.x), ($form.Location.Y + $e.Y - $drag.y))
    }
  }
  $up = { param($s, $e) $drag.on = $false }
  foreach ($c in @($form, $title, $tag, $hint, $tip)) {
    $c.Add_MouseDown($down); $c.Add_MouseMove($move); $c.Add_MouseUp($up)
  }

  function Show-ErrorCard($step) {
    # The window stops being a progress indicator and becomes the report. The
    # step list stays: which step failed is half the answer, and it is already
    # on screen with a cross beside it.
    $st.failed = $true
    # Hidden, not slowed to zero: MarqueeAnimationSpeed = 0 is one of the two
    # documented ways to get the reported "empty bar", and leaving that value
    # anywhere in this file invites the next reader to copy it upward.
    $bar.Visible = $false
    $progress.Visible = $false
    $status.ForeColor = $bad
    $status.Text = "$($step.Title) failed: $($step.Detail)"
    if ($LogPath) {
      $hint.ForeColor = $muted
      $hint.Text = "Log: $LogPath"
    }
    $tip.Text = "Nothing was lost. Your notes are untouched."
    $btnCancel.Text = "Close"
    $btnCopy.Text = "Copy diagnostics"
    $btnDetails.Text = "Open log"
  }

  $deadline = (Get-Date).AddMinutes($MaxMinutes)

  $timer          = New-Object System.Windows.Forms.Timer
  $timer.Interval = 250
  $timer.Add_Tick({
    try {
      if ((Get-Date) -gt $deadline) { $form.Close(); return }
      # Gone means the launcher finished (or died). Either way this window's
      # job is over - leaving it on top of the app would be the worst outcome.
      # Not while the error card is up: that one is the reader's to close.
      if (-not (Test-Path -LiteralPath $StatusFile)) {
        if (-not $st.failed) { $form.Close() }
        return
      }

      # The tip rotates on its own clock, so it keeps moving even while the
      # launcher is silent for minutes at a time inside one step.
      if (((Get-Date) - $st.tipSince).TotalSeconds -ge 6) {
        $st.tipAt = ($st.tipAt + 1) % $tips.Count
        $st.tipSince = (Get-Date)
        if (-not $st.failed) { $tip.Text = $tips[$st.tipAt] }
      }

      if ($st.failed) { return }

      $raw = (Get-Content -LiteralPath $StatusFile -Raw -ErrorAction SilentlyContinue)
      if ($null -eq $raw) { return }
      if ($raw -match "__done__") { $form.Close(); return }

      $steps = @(Read-Steps)
      if ($steps.Count -eq 0) { return }
      $st.rows = $steps

      $current = $steps[$steps.Count - 1]
      if ($current.Title -ne $st.activeTitle) {
        $st.activeTitle = $current.Title
        $st.activeSince = (Get-Date)
      }

      # Steps finished over total, never the step number: see $progress.
      $done = @($steps | Where-Object { $_.State -eq "done" }).Count
      $total = $current.Total
      if ($total -lt 1) { $total = 1 }
      $pct = [int](($done * 100) / $total)
      if ($pct -lt 0) { $pct = 0 }
      if ($pct -gt 100) { $pct = 100 }
      $progress.Value = $pct

      Update-Rows $steps
      Update-Hint $steps

      # Not the current step's detail: the active row already shows that,
      # and the same sentence twice, one above the other, reads as a
      # rendering fault rather than as two pieces of information. The total
      # elapsed time is the thing neither the list nor the bar can say, and
      # it is what someone watching a slow first run actually wants.
      $elapsed = [int]((Get-Date) - $st.started).TotalSeconds
      if ($elapsed -lt 60) {
        $detailText = "$done of $total steps done, running for $($elapsed)s."
      } else {
        $mins = [int]($elapsed / 60)
        $detailText = "$done of $total steps done, running for $($mins)m $($elapsed % 60)s."
      }
      if ($st.cancelled) { $detailText = "Cancelling after this step finishes." }
      if ($status.Text -ne $detailText) { $status.Text = $detailText }

      $failedStep = @($steps | Where-Object { $_.State -eq "failed" })
      if ($failedStep.Count -gt 0) { Show-ErrorCard $failedStep[0] }
    } catch {
      # A half-written file, or one locked mid-write by cmd's `echo >`. Both
      # are normal at 250ms polling and both resolve on the next tick.
    }
  })
  $timer.Start()

  # Try again, offered only once something has actually failed: re-running the
  # launcher while it is still working would put two of them on one checkout.
  $btnRetry              = New-Object System.Windows.Forms.Button
  $btnRetry.Text         = "Try again"
  $btnRetry.Location     = New-Object System.Drawing.Point(244, 334)
  $btnRetry.Size         = New-Object System.Drawing.Size(78, 26)
  $btnRetry.FlatStyle    = "Flat"
  $btnRetry.BackColor    = $panel
  $btnRetry.ForeColor    = $muted
  $btnRetry.Font         = New-Object System.Drawing.Font -ArgumentList "Segoe UI", ([float]8.5)
  $btnRetry.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(48, 53, 68)
  $btnRetry.TabStop      = $false
  $btnRetry.Visible      = $false
  $btnRetry.Add_Click({
    if ($LauncherPath -and (Test-Path -LiteralPath $LauncherPath)) {
      try { Start-Process -FilePath $LauncherPath } catch { }
    }
    $form.Close()
  })
  $form.Controls.Add($btnRetry)

  # One more timer job, kept separate so the main tick stays readable: show
  # Try again the moment the card appears, and only if there is something to
  # re-run.
  $retryTimer          = New-Object System.Windows.Forms.Timer
  $retryTimer.Interval = 400
  $retryTimer.Add_Tick({
    if ($st.failed -and $LauncherPath -and -not $btnRetry.Visible) {
      $btnRetry.Visible = $true
    }
  })
  $retryTimer.Start()

  [void]$form.ShowDialog()
  $timer.Stop()
  $retryTimer.Stop()
  $form.Dispose()
} catch {
  # No PowerShell assemblies (Server Core), a blocked execution policy, a
  # remote session with no display. None of those are reasons to stop the app
  # from starting, and the launcher never checks our exit code.
  exit 0
}
