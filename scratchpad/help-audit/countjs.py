"""Descriptive helper prose over 120 chars built in the frontend JS.

The JS builds its DOM with createElement, so there is no markup to parse.
This pairs an element whose className reads as helper text
(muted/hint/blurb/explain/caption/lead/note/desc/intro) with the string
assigned to its textContent or innerHTML within the following few lines, and
reports the ones over 120 characters.

Deliberately narrow. It will not see prose assembled through a helper, so
treat the number as a floor, not a census.

Run: python3 scratchpad/help-audit/countjs.py frontend/app.js ...
"""
import re
import sys

CLASSNAME = re.compile(
    r'(\w+)\.className\s*=\s*["\'`]([^"\'`]*(?:muted|hint|blurb|explain|caption|lead|desc|intro|note)[^"\'`]*)["\'`]'
)
STRING = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|`((?:[^`\\]|\\.)*)`', re.S)

SKIP_CLASS = re.compile(r"help-popover|help-body|graph-help|setting-hint|empty-state")


def visible(raw):
    text = re.sub(r"\$\{[^{}]*\}", "X", raw)
    text = text.replace("\\n", " ").replace('\\"', '"').replace("\\'", "'")
    return " ".join(text.split())


def main(paths):
    total = 0
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        for i, line in enumerate(lines):
            m = CLASSNAME.search(line)
            if not m:
                continue
            var, cls = m.group(1), m.group(2)
            if SKIP_CLASS.search(cls):
                continue
            window = "\n".join(lines[i : i + 14])
            assign = re.search(
                re.escape(var) + r"\.(?:textContent|innerHTML)\s*=\s*(.*?);\s*$",
                window,
                re.S | re.M,
            )
            if not assign:
                continue
            best = ""
            for s in STRING.finditer(assign.group(1)):
                raw = next(g for g in s.groups() if g is not None)
                v = visible(raw)
                if len(v) > len(best):
                    best = v
            if len(best) <= 120:
                continue
            print(f'{path}:{i + 1} class="{cls}" ({len(best)})')
            print(f"\t{best[:300]}")
            total += 1
    print("TOTAL", total)


if __name__ == "__main__":
    main(sys.argv[1:])
