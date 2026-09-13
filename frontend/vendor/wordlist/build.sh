#!/usr/bin/env bash
# Rebuilds en.txt, the English word list the documents editor's spelling check
# reads. Run by hand with network access; the result is committed, because the
# app is offline and nothing here may be fetched at run time. Nothing in the
# app or the tests depends on this script.
#
# The source is the English Speller Database (SCOWL's successor), whose licence
# is the LICENSE file beside this one: permissive, and it asks only that the
# copyright notice travels with any list built from it. That notice is why the
# LICENSE file exists rather than a line in a comment.
#
# The parameters, and why each one:
#   max_size=60      the default tier. 93k words after the normalisation below.
#                    Tier 50 drops words a writer does use; tier 70 starts
#                    admitting spellings that let a real typo through.
#   spelling=US,GBs  both spellings are *words*. This app has a separate UK/US
#                    preference (DOC_SPELLING_PAIRS) that says which one this
#                    notebook prefers; a checker that called "colour" a
#                    misspelling would be answering a different question.
#   special=hacker   "http", "email", "wiki" and the rest of the vocabulary
#                    every note in this app is written in.
#   diacritic=strip  the checker lowercases and compares ASCII.
#
# The normalisation, and why: everything is lowercased (the checker's lookup
# is case-insensitive, and folding saves 18k near-duplicate entries), and the
# 18,579 "word's" possessive forms are dropped because the checker strips a
# trailing "'s" itself. Contractions with an apostrophe anywhere else ("I'll",
# "O'Brien") are kept, because nothing else produces them.
set -euo pipefail
cd "$(dirname "$0")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
url="https://app.aspell.net/create?max_size=60&spelling=US&spelling=GBs"
url="$url&max_variant=1&diacritic=strip&special=hacker&special=roman-numerals"
url="$url&download=wordlist&encoding=utf-8&format=inline"
curl -fsS "$url" -o "$work/raw.txt"
grep -q '^---$' "$work/raw.txt" || { echo "no header separator: the service changed" >&2; exit 1; }
# The header above the "---" is the licence; keep it as LICENSE, verbatim.
sed -n '1,/^---$/p' "$work/raw.txt" | sed '$d' > LICENSE
sed -n '/^---$/,$p' "$work/raw.txt" | tail -n +2 > "$work/words.txt"
python3 - "$work/words.txt" <<'PY' > en.txt
import sys
words = [w.strip() for w in open(sys.argv[1], encoding="utf-8") if w.strip()]
keep = {w.lower() for w in words if not w.endswith("'s")}
print("\n".join(sorted(keep)))
PY
echo "wrote $(wc -l < en.txt) words, $(du -h en.txt | cut -f1)"
