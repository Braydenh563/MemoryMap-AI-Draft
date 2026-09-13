"""Turning an uploaded document into markdown, via markitdown (§37G).

Optional, like `ai/voice.py`'s Whisper: without the package installed, the
route this backs reports "not available" with the install hint rather than
failing in a way that looks broken. `core/extras.py`'s `documents` extra is
what makes it installable from inside the app.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

INSTALL_HINT = (
    "Importing documents needs the optional markitdown package. In your "
    "MemoryMap folder run:  pip install markitdown: then restart the app, "
    "or use Settings → Optional extras."
)

#: Splits on a top-level markdown heading, the shape a converted PDF/slide
#: deck comes back in when it has real structure (chapters, one heading per
#: slide). `re.MULTILINE` so `^` matches the start of each line, not just the
#: start of the whole document.
_H1 = re.compile(r"^# .+$", re.MULTILINE)


def markitdown_available() -> bool:
    return importlib.util.find_spec("markitdown") is not None


def convert_to_markdown(path: Path) -> str:
    """The file's text, as markdown. Raises RuntimeError with the install
    hint when markitdown isn't available."""
    if not markitdown_available():
        raise RuntimeError(INSTALL_HINT)
    from markitdown import MarkItDown  # imported only when present

    result = MarkItDown().convert(str(path))
    return (result.text_content or "").strip()


def split_into_sections(text: str) -> list[str]:
    """One note per top-level heading, when there is more than one, a slide
    deck or a document with real chapters is more useful as several notes
    than one long one. A single heading, or none, stays as one note: a
    converter that emits "# Page 1", "# Page 2" for a plain letter would
    otherwise turn one page into several near-empty notes.
    """
    text = text.strip()
    if not text:
        return []
    matches = list(_H1.finditer(text))
    if len(matches) < 2:
        return [text]
    sections = [text[: matches[0].start()].strip()]  # anything before the first heading
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append(text[match.start() : end].strip())
    return [section for section in sections if section]
