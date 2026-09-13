"""An icon followed by a label needs `ph-lead`, and a label should not be
prefixed with a raw Unicode glyph standing in for one.

Two lints, both from the same report: *"the widgets button text and icon arent
aligned either and dont have a gap between them"*, and the same complaint about
the popup agent's Stop button.

**The gap.** `.ph-lead` is `margin-inline-end: 0.35em`, the whole of the space
between an icon and the word after it. `#dash-widgets-open` was
`<i class="ph ph-squares-four">` with no `ph-lead`, so its glyph sat flush
against "Widgets": measured at 0px, against 5.5px on every button that had the
class. Eleven buttons in index.html were missing it.

**The stand-in glyphs.** The Stop button was not an icon at all, it was the
literal character `■` typed in front of the word, and so were `↩ Undo`,
`⧉ Copy`, `＋ Tag`, `⭳ Export`, `↗ Open` and a dozen more. A text glyph is
drawn by whichever font the label uses, at the label's own size and baseline,
and gets no `ph-lead` gap and none of the vertical centring the icon rules
apply: which is exactly "text and icon arent aligned". Nineteen were replaced
with real Phosphor icons.

Single-glyph controls with no words are left alone (the map's `＋`/`－`/`⤢`
zoom cluster, the whiteboard's alignment arrows): there is no label for them
to be misaligned against, and each is a coherent set of its own.
"""

from __future__ import annotations

import re
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "frontend" / "index.html"

# Glyphs that have been used as icon stand-ins in this file's history. A short
# list on purpose: it should catch a habit, not police every character.
STANDIN_GLYPHS = "■↩⧉＋⭳↗⬇•⤢"

# Labels where the character is genuinely part of the wording rather than an
# icon standing in front of it.
ALLOWED_LABELS = {
    "−15m",  # a time step: the minus is the value, not decoration
    "−1d",
}


def _buttons() -> list[tuple[int, str]]:
    src = INDEX.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"<button\b[^>]*>(.*?)</button>", src, re.S):
        out.append((src[: m.start()].count("\n") + 1, m.group(1)))
    return out


def test_an_icon_before_a_label_carries_ph_lead() -> None:
    offenders = []
    for line, inner in _buttons():
        for m in re.finditer(r'<i class="ph (ph-[a-z0-9-]+)([^"]*)"[^>]*>\s*</i>([^<]*)', inner):
            if "ph-lead" in m.group(2):
                continue
            if not m.group(3).strip():
                continue  # icon-only: the gap would be dead space on one side
            offenders.append(f"line {line}: {m.group(1)} before {m.group(3).strip()[:24]!r}")
    assert not offenders, (
        "These icons are followed by a label but lack `ph-lead`, so there is no "
        "gap between the glyph and the word (measured at 0px against 5.5px "
        "elsewhere):\n" + "\n".join(offenders)
    )


def test_no_unicode_glyph_stands_in_for_an_icon() -> None:
    offenders = []
    for line, inner in _buttons():
        text = re.sub(r"<[^>]+>", "", inner).strip()
        if not text or text in ALLOWED_LABELS:
            continue
        # Only a *leading* glyph followed by words is an icon stand-in.
        if text[0] in STANDIN_GLYPHS and len(text) > 1 and text[1:].strip():
            offenders.append(f"line {line}: {text[:32]!r}")
    assert not offenders, (
        "These button labels start with a Unicode glyph used as an icon. A text "
        "glyph is drawn by the label's own font at the label's own baseline, so "
        "it gets neither the `ph-lead` gap nor the icon centring rules, it "
        "reads as an icon that is not aligned with its text. Use "
        '`<i class="ph ph-NAME ph-lead" aria-hidden="true"></i>` instead:\n'
        + "\n".join(offenders)
    )
