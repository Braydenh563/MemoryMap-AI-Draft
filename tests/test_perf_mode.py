"""Performance mode and the glass budget (INBOX 49).

The suite cannot see the DOM, so this pins the shape that
`scratchpad/ui-sweeps/weight.js` measured: blur only where something scrolls
under a surface or where it floats, never on a content panel, and a
Performance mode that takes the rest off on a small machine. Measured at
1366x768 before: 32% of the viewport blurred at rest on the dashboard and over
80% on notes, chat and graph. After: under 10% on every tab.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "frontend" / "css"
FRONTEND = ROOT / "frontend"


def _block(css: str, selector: str) -> str:
    """The body of the first top-level rule whose selector line is exactly
    `selector` (so `.card {` does not match `.card.glass {`)."""
    match = re.search(r"^" + re.escape(selector) + r" \{\n(.*?)^\}", css, re.M | re.S)
    assert match, f"{selector} rule not found"
    # Declarations only: the comments explain why a blur is absent by name.
    return re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.S)


def test_content_panels_are_not_blurred() -> None:
    shell = (CSS / "00-tokens-shell.css").read_text(encoding="utf-8")
    forms = (CSS / "01-forms-settings.css").read_text(encoding="utf-8")
    assert "backdrop-filter" not in _block(shell, ".card")
    assert "backdrop-filter" not in _block(shell, "#status-bar")
    assert "backdrop-filter" not in _block(forms, ".dash-hero")


def test_floating_surfaces_keep_the_blur() -> None:
    shell = (CSS / "00-tokens-shell.css").read_text(encoding="utf-8")
    widgets = (CSS / "03-dashboard-widgets.css").read_text(encoding="utf-8")
    assert "backdrop-filter" in _block(shell, "header#top-bar")
    assert "backdrop-filter: var(--glass-filter)" in _block(shell, ".card.modal-card,\n.card.space-dialog")
    assert "backdrop-filter: var(--glass-filter)" in _block(widgets, ".glass,\n.card.glass")


def test_performance_mode_is_wired_end_to_end() -> None:
    settings = (FRONTEND / "settings.js").read_text(encoding="utf-8")
    boot = (FRONTEND / "theme-boot.js").read_text(encoding="utf-8")
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    canvas = (FRONTEND / "graph-canvas.js").read_text(encoding="utf-8")
    worker = (FRONTEND / "graph-worker.js").read_text(encoding="utf-8")
    # The preference, its default, and its place on the reset list.
    assert 'perf: "auto"' in settings
    assert '"perf", "motion"' in settings
    # Resolved the same way before first paint and after: both read the two
    # machine signals and the OS transparency query.
    for src in (settings, boot):
        assert "deviceMemory" in src and "hardwareConcurrency" in src
        assert "prefers-reduced-transparency" in src
        assert "dataset.perf" in src
    # On, it overrides glass and motion without rewriting the preferences.
    assert 'root.dataset.glass = perf ? "off" : appearancePref("glass")' in settings
    assert 'root.dataset.motion = perf ? "reduced" : appearancePref("motion")' in settings
    # The setting itself: three states, a hint that says why it is on.
    assert 'id="perf-mode"' in html and 'id="perf-mode-hint"' in html
    assert html.count('<option value="auto">Auto</option>') >= 1
    # Said once, never when chosen by hand.
    assert 'localStorage.getItem("perf-noticed")' in settings
    # The graph's physics rest twice as long.
    assert 'perf: document.documentElement.dataset.perf === "on"' in canvas
    assert "message.perf === true" in worker and "const rest = perf ? 2 : 1" in worker
