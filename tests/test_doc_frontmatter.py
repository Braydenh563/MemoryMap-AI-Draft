"""The properties panel's round trip through Source is byte-exact.

DOCUMENTS_PLAN Phase 3 item 4, in one sentence: **a document whose properties
were edited in the panel has to be the file its author wrote, minus the one
value they changed.** Not "equivalent YAML", not "the same keys re-printed":
the same bytes, because a frontmatter block that comes back with its quoting,
its spacing and its key order rebuilt every time somebody edits a tag is a
block whose diffs are noise and whose author no longer wrote it. This is the
table model's promise (`tests/test_doc_tables.py`) applied to the second place
in this editor where a widget writes into the markdown underneath it.

The way it is kept is the same: the model never prints YAML. Every operation
returns the smallest `{from, to, insert}` edits that can express it, so every
byte the operation did not have to touch is still the byte the author typed.
This test measures that claim the only honest way, by applying an operation
*and its inverse* and comparing the result to the original string, character
for character.

Python cannot run the editor, so the marked regions of documents.js
(`DOC-TABLE-BEGIN`/`-END` for `docTableApplyEdits`, which is the one way this
file applies a list of edits to a string, and `DOC-FRONTMATTER-BEGIN`/`-END`
for the model itself) are executed in node. Both regions are pure string work
with no DOM and no app globals in them, which is a property worth keeping and
which this file enforces by construction: the day somebody reaches for
`document` in there, this test stops running.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_JS = ROOT / "frontend" / "documents.js"


def region(begin: str, end: str) -> str:
    """The bracketed region of documents.js, on its own.

    The marker *lines* rather than the bare names: documents.js's own comment
    above each region says what its markers are for, so each name appears twice
    in the file and a `find` on the bare name extracts the comment instead of
    the code.
    """
    text = DOCUMENTS_JS.read_text(encoding="utf-8")
    start = text.find(f"// {begin}")
    stop = text.find(f"// {end}")
    assert start != -1, f"{begin} marker is missing from documents.js"
    assert stop > start, f"{end} marker is missing or before {begin}"
    return text[start + len(begin) + 3 : stop]


def model_source() -> str:
    return region("DOC-TABLE-BEGIN", "DOC-TABLE-END") + region(
        "DOC-FRONTMATTER-BEGIN", "DOC-FRONTMATTER-END"
    )


#: The shapes a real notebook has in it. Each one is here because it is a way a
#: re-serialising implementation quietly changes a file: hand-padded values get
#: rebuilt, a quoted scalar loses its quotes (or gains different ones), an
#: inline list is turned into a block list or the other way about, a key with no
#: value is dropped, and a key whose name has a space in it stops parsing.
#:
#: `vault_import` is the exact shape this app's own Obsidian import writes
#: (routes_settings.py `_parse_frontmatter`), which is the frontmatter most
#: likely to be in a real document here.
SHAPES = {
    "vault_import": "---\ncategory: Work\ntags: [one, two]\n---",
    "obsidian_block": "---\ntags:\n  - one\n  - two\naliases:\n  - A short name\n---",
    "quoted": "---\ntitle: \"A: a subtitle\"\nstatus: 'draft'\n---",
    "padded": "---\nstatus:    draft   \ntags: [ one,two ,three ]\n---",
    "empty_values": "---\nstatus:\ntags: []\n---",
    "awkward_keys": "---\ndue date: 2026-09-12\nsome.key: 7\n---",
    "comma_in_quotes": '---\ntags: ["one, two", three]\n---',
    "one_property": "---\nstatus: draft\n---",
}

#: The prose under each block, so every offset in the assertions is a real
#: document offset rather than a block-local one.
BODY = "\n\n# A document\n\nSome words, a [[link]] and a table:\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"


DRIVER = r"""
const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail === undefined ? null : detail });
}

const SHAPES = JSON.parse(process.argv[2]);
const BODY = JSON.parse(process.argv[3]);

for (const [shape, block] of Object.entries(SHAPES)) {
  const text = block + BODY;
  const fm = docFrontmatterParse(text);
  check(`${shape}/parses`, !!fm, "no frontmatter found");
  if (!fm) continue;

  // 1. The block is exactly the block, and the prose is exactly the prose.
  check(`${shape}/span`, text.slice(fm.from, fm.to) === block, JSON.stringify(text.slice(fm.from, fm.to)));
  check(`${shape}/strip`, docFrontmatterStrip(text) === BODY.replace(/^\n+/, ""),
    JSON.stringify(docFrontmatterStrip(text).slice(0, 40)));

  // 2. Every entry's key and value read back out of the document at the spans
  //    the model says they are at.
  for (const entry of fm.entries) {
    check(`${shape}/key-span-${entry.key}`, text.slice(entry.keyFrom, entry.keyTo) === entry.key,
      JSON.stringify(text.slice(entry.keyFrom, entry.keyTo)));
    for (let i = 0; i < entry.items.length; i += 1) {
      const item = entry.items[i];
      const raw = text.slice(item.from, item.to);
      check(`${shape}/item-span-${entry.key}-${i}`, raw.includes(item.text), JSON.stringify(raw));
    }
  }

  // 3. Writing a value back as it already reads changes nothing at all.
  for (const entry of fm.entries) {
    if (entry.kind === "list") {
      const same = docFrontmatterSetListEdits(fm, entry.key, entry.items.map((i) => i.text));
      check(`${shape}/list-same-${entry.key}`, same.length === 0, JSON.stringify(same));
    } else {
      const same = docFrontmatterSetEdits(fm, entry.key, entry.value.text);
      check(`${shape}/set-same-${entry.key}`, same.length === 0, JSON.stringify(same));
    }
  }

  // 4. Edit a value and edit it back: the document is the original, byte for
  //    byte, including the padding around every other value.
  for (const entry of fm.entries) {
    if (entry.kind === "list") continue;
    const was = entry.value.text;
    const edited = docTableApplyEdits(text, docFrontmatterSetEdits(fm, entry.key, "edited value"));
    const again = docFrontmatterParse(edited);
    check(`${shape}/edit-reparse-${entry.key}`, !!again, "the edited block no longer parses");
    if (!again) continue;
    check(`${shape}/edit-reads-back-${entry.key}`,
      docFrontmatterEntry(again, entry.key).value.text === "edited value",
      docFrontmatterEntry(again, entry.key).value.text);
    const back = docTableApplyEdits(edited, docFrontmatterSetEdits(again, entry.key, was));
    check(`${shape}/edit-round-trip-${entry.key}`, back === text, JSON.stringify(back));
  }

  // 5. A list item edited and edited back, one item at a time: the original.
  for (const entry of fm.entries) {
    if (entry.kind !== "list" || !entry.items.length) continue;
    for (let i = 0; i < entry.items.length; i += 1) {
      const values = entry.items.map((item) => item.text);
      const was = values.slice();
      values[i] = "edited item";
      const edited = docTableApplyEdits(text, docFrontmatterSetListEdits(fm, entry.key, values));
      const again = docFrontmatterParse(edited);
      check(`${shape}/item-reparse-${entry.key}-${i}`, !!again, "the edited block no longer parses");
      if (!again) continue;
      const read = docFrontmatterEntry(again, entry.key).items.map((item) => item.text);
      check(`${shape}/item-reads-back-${entry.key}-${i}`, read[i] === "edited item", JSON.stringify(read));
      const back = docTableApplyEdits(edited, docFrontmatterSetListEdits(again, entry.key, was));
      check(`${shape}/item-round-trip-${entry.key}-${i}`, back === text, JSON.stringify(back));
    }
  }

  // 6. Add an item, remove it again: the original. Both list styles, and the
  //    empty list, which is where a naive implementation leaves a comma.
  for (const entry of fm.entries) {
    if (entry.kind !== "list") continue;
    const values = entry.items.map((item) => item.text);
    const added = docTableApplyEdits(text, docFrontmatterSetListEdits(fm, entry.key, [...values, "late"]));
    const again = docFrontmatterParse(added);
    check(`${shape}/item-added-${entry.key}`,
      !!again && docFrontmatterEntry(again, entry.key).items.length === values.length + 1,
      again ? String(docFrontmatterEntry(again, entry.key).items.length) : "no block");
    if (!again) continue;
    check(`${shape}/item-added-reads-${entry.key}`,
      docFrontmatterEntry(again, entry.key).items.slice(-1)[0].text === "late",
      docFrontmatterEntry(again, entry.key).items.slice(-1)[0].text);
    const back = docTableApplyEdits(added, docFrontmatterSetListEdits(again, entry.key, values));
    check(`${shape}/item-added-round-trip-${entry.key}`, back === text, JSON.stringify(back));
  }

  // 7. Add a property, remove it again: the original, with the other keys in
  //    the order they were written in.
  {
    const added = docTableApplyEdits(text, docFrontmatterAddEdits(fm, "reviewed", "2026-09-12"));
    const again = docFrontmatterParse(added);
    check(`${shape}/add`, !!again && !!docFrontmatterEntry(again, "reviewed"),
      JSON.stringify(added.slice(0, 120)));
    if (again) {
      check(`${shape}/add-value`, docFrontmatterEntry(again, "reviewed").value.text === "2026-09-12",
        docFrontmatterEntry(again, "reviewed").value.text);
      check(`${shape}/add-order`,
        again.entries.map((e) => e.key).join(",") === [...fm.entries.map((e) => e.key), "reviewed"].join(","),
        again.entries.map((e) => e.key).join(","));
      const back = docTableApplyEdits(added, docFrontmatterRemoveEdits(again, "reviewed"));
      check(`${shape}/add-round-trip`, back === text, JSON.stringify(back));
    }
  }

  // 8. Removing a property takes its line and nothing else, and the block is
  //    still a block afterwards.
  for (const entry of fm.entries) {
    const removed = docTableApplyEdits(text, docFrontmatterRemoveEdits(fm, entry.key));
    const again = docFrontmatterParse(removed);
    check(`${shape}/remove-${entry.key}`, !!again && !docFrontmatterEntry(again, entry.key),
      JSON.stringify(removed.slice(0, 120)));
    if (!again) continue;
    check(`${shape}/remove-keeps-others-${entry.key}`,
      again.entries.length === fm.entries.length - 1, String(again.entries.length));
    check(`${shape}/remove-keeps-body-${entry.key}`, removed.endsWith(BODY), "the prose moved");
  }

  // 9. A key is found however it is cased, because the panel shows it however
  //    it was written.
  for (const entry of fm.entries) {
    check(`${shape}/case-insensitive-${entry.key}`,
      docFrontmatterEntry(fm, entry.key.toUpperCase()) === entry, entry.key);
  }
}

// Documents that have no frontmatter, and shapes that only look like it. Each
// of these is a way a greedy parser eats someone's prose.
{
  const rule = "Some words\n\n---\n\nmore words\n";
  check("none/mid-document-rule", docFrontmatterParse(rule) === null, "a horizontal rule parsed as properties");
  check("none/strip-is-identity", docFrontmatterStrip(rule) === rule, "strip changed a document with no properties");
  const unclosed = "---\nstatus: draft\n\n# A document\n";
  check("none/unclosed", docFrontmatterParse(unclosed) === null, "an unclosed block parsed");
  const setext = "A heading\n---\n\nbody\n";
  check("none/setext", docFrontmatterParse(setext) === null, "a setext heading parsed as properties");
}

// A document with no properties gets a block, and the block it gets parses.
{
  const plain = "# A document\n\nSome words.\n";
  const made = docTableApplyEdits(plain, docFrontmatterCreateEdits(plain, "tags", "[one]"));
  const fm = docFrontmatterParse(made);
  check("create/parses", !!fm, JSON.stringify(made));
  check("create/keeps-the-prose", made.endsWith(plain), JSON.stringify(made));
  check("create/blank-line", made.includes("---\n\n# A document"), JSON.stringify(made));
  if (fm) {
    check("create/value", docFrontmatterEntry(fm, "tags").items.map((i) => i.text).join(",") === "one",
      JSON.stringify(made));
    check("create/round-trip", docFrontmatterStrip(made) === plain, JSON.stringify(docFrontmatterStrip(made)));
  }
  check("create/never-twice", docFrontmatterCreateEdits(made, "tags", "[one]").length === 0, "a second block");
}

// A value that cannot be written bare is quoted, and reads back as itself.
{
  const text = "---\ntitle: A document\n---\n\nbody\n";
  for (const value of ["A: a subtitle", "  padded  ", "#hash", "- dashed", "a, b"]) {
    const fm = docFrontmatterParse(text);
    const edited = docTableApplyEdits(text, docFrontmatterSetEdits(fm, "title", value));
    const again = docFrontmatterParse(edited);
    check(`quote/${value}/parses`, !!again, JSON.stringify(edited));
    if (!again) continue;
    check(`quote/${value}/reads-back`, docFrontmatterEntry(again, "title").value.text === value.trim() || docFrontmatterEntry(again, "title").value.text === value,
      JSON.stringify(docFrontmatterEntry(again, "title").value.text));
    check(`quote/${value}/one-line`, again.entries.length === 1, JSON.stringify(edited));
  }
}

// The fields the panel and the Library filter both read.
{
  const fields = docFrontmatterFields("---\nstatus: draft\ntags: [a, b]\n---\n\nbody");
  check("fields/kinds", fields.map((f) => `${f.key}:${f.kind}`).join(",") === "status:scalar,tags:list",
    JSON.stringify(fields));
  check("fields/values", fields[0].value === "draft" && fields[1].items.join("|") === "a|b",
    JSON.stringify(fields));
  check("fields/none", docFrontmatterFields("# no properties here").length === 0, "fields from nothing");
}

process.stdout.write(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def frontmatter_checks(tmp_path_factory) -> list[dict]:
    node = shutil.which("node")
    if not node:  # pragma: no cover - node is in the sandbox and in CI
        pytest.skip("node is not available")
    script = tmp_path_factory.mktemp("docfm") / "run.js"
    script.write_text(model_source() + DRIVER, encoding="utf-8")
    out = subprocess.run(
        [node, str(script), json.dumps(SHAPES), json.dumps(BODY)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_model_runs_without_a_browser(frontmatter_checks: list[dict]) -> None:
    """No DOM, no app globals: the region is pure string work."""
    assert len(frontmatter_checks) > 150, "the driver did not reach the end of the shapes"


def test_every_property_operation_round_trips_byte_for_byte(
    frontmatter_checks: list[dict],
) -> None:
    failed = [c for c in frontmatter_checks if not c["ok"]]
    assert not failed, "\n".join(f"{c['name']}: {c['detail']}" for c in failed[:20])
