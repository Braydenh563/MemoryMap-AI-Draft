"""Settings, measured: ROADMAP.md item 7 ("Settings has never been measured").

The first measurement of every Settings section, at 1440x900. Words and
paragraphs are what REDESIGN.md item 48 ("spacing and excessive paragraph
text in Settings") asks about; distinct left edges is DESIGN.md's own
alignment test, which wants 2-4.

| section     | edges | paras | words  |
| ----------- | ----: | ----: | -----: |
| **about**   | **141** | **510** | **21,557** |
| help        |     5 |    21 |    580 |
| extras      |     5 |    27 |    572 |
| models      |     9 |    19 |    437 |
| appearance  |    28 |     6 |    135 |
| shortcuts   |    22 |     3 |     73 |

About dwarfed everything, and the cause was not what it looked like: the
whole changelog was rendered into `#changelog-body` on **every** open of
Settings, while the `<details>` around it showed 47 pixels. It never looked
wrong, the fold clips it, which is exactly why it survived. It was DOM
weight and layout work for content nobody had asked to see.

After deferring the render to the moment the fold opens: 45 words, 6 edges.
"""

from __future__ import annotations

from pathlib import Path

SETTINGS_JS = Path(__file__).resolve().parent.parent / "frontend" / "settings.js"


def _load_changelog_source() -> str:
    text = SETTINGS_JS.read_text(encoding="utf-8")
    start = text.index("async function loadChangelog(")
    return text[start : text.index("\n}\n", start)]


def test_the_changelog_renders_when_opened_not_when_settings_opens():
    body = _load_changelog_source()
    assert 'addEventListener("toggle"' in body, (
        "the changelog must render on the fold's toggle, not on every Settings open"
    )
    # The render call must be inside the deferred painter, not at top level.
    paint_at = body.index("const paint")
    assert body.index("renderMarkdown(") > paint_at, (
        "renderMarkdown still runs eagerly, that is the 21,452 words this guards"
    )


def test_the_fetch_stays_eager_because_it_decides_visibility():
    """A packaged build may not ship the changelog file, and a disclosure that
    opens onto nothing is worse than none. Only the render is deferred."""
    body = _load_changelog_source()
    assert 'apiJson("/changelog"' in body
    assert 'fold.classList.add("hidden")' in body


def test_rendering_happens_once():
    body = _load_changelog_source()
    assert "dataset.rendered" in body, (
        "opening and closing the fold repeatedly must not re-render 21k words"
    )
