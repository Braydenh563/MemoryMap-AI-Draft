"""The table editor's round trip through Source is byte-exact.

DOCUMENTS_PLAN Phase 3 item 1 and PLAN D4's gate, in one sentence: **a table
edited in Live and then read in Source has to be the markdown a person would
have typed.** Not "equivalent markdown", not "the same table re-printed": the
same bytes, because a markdown file that comes back with its padding rebuilt
every time somebody ticks a cell is a file whose diffs are noise and whose
author no longer wrote it.

The way that promise is kept is in `documents.js`'s own comment: the table
model never prints a table. Every operation returns the smallest
`{from, to, insert}` edits that can express it, so every byte the operation
did not have to touch is still the byte the author typed. This test is the
measurement of that claim rather than a restatement of it, and it measures it
the only honest way: by applying an operation *and its inverse* and comparing
the result to the original string, character for character.

Python cannot run the editor, so the marked region of documents.js
(`DOC-TABLE-BEGIN` to `DOC-TABLE-END`) is executed in node. That region is
pure string work with no DOM and no app globals in it, which is a property
worth keeping and which this test enforces by construction: the day somebody
reaches for `document` in there, this file stops running.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_JS = ROOT / "frontend" / "documents.js"

#: The marker *lines*, not the bare names: documents.js's own comment above
#: the region says what the markers are for, so the names appear twice in the
#: file and a `find` on the bare name extracts the comment instead of the code.
BEGIN = "// DOC-TABLE-BEGIN"
END = "// DOC-TABLE-END"


def table_model_source() -> str:
    """The bracketed region of documents.js, on its own."""
    text = DOCUMENTS_JS.read_text(encoding="utf-8")
    start = text.find(BEGIN)
    end = text.find(END)
    assert start != -1, f"{BEGIN} marker is missing from documents.js"
    assert end > start, f"{END} marker is missing or before {BEGIN}"
    return text[start + len(BEGIN) : end]


#: The shapes a real notebook has in it. Each one is here because it is a way
#: a re-serialising implementation quietly changes a file: an escaped pipe
#: becomes a column break or a double backslash, hand-padded columns get
#: rebuilt, a table written without outer pipes gets them, an indented table
#: is pulled to the margin, and trailing spaces after the last pipe vanish.
SHAPES = {
    "canonical": "| Name | Notes |\n| --- | --- |\n| One | Two |\n| Three | Four |",
    "escaped_pipe": (
        "| Command | What it does |\n"
        "| --- | --- |\n"
        "| `a \\| b` | pipes a into b |\n"
        "| plain | nothing \\| special |"
    ),
    "ragged_widths": "|Name|Notes|\n|---|------------|\n| a |  b |\n|   c|d|",
    "no_outer_pipes": "Name | Notes\n--- | ---\nOne | Two",
    "indented_and_trailing": "  | a | b |   \n  | --- | :---: |\n  | 1 | 2 |  ",
    "aligned": "| a | b | c |\n| :--- | :---: | ---: |\n| 1 | 2 | 3 |",
}

#: The same tables with prose around them, so every offset in the assertions
#: below is a real document offset rather than a table-local one.
PROSE_BEFORE = "# A document\n\nSome words before it.\n\n"
PROSE_AFTER = "\n\nAnd a paragraph after it.\n"


DRIVER = r"""
const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail === undefined ? null : detail });
}

const SHAPES = JSON.parse(process.argv[2]);
const BEFORE = JSON.parse(process.argv[3]);
const AFTER = JSON.parse(process.argv[4]);

for (const [shape, table] of Object.entries(SHAPES)) {
  const text = BEFORE + table + AFTER;
  const at = BEFORE.length;

  // 1. Every line puts itself back together exactly.
  for (const line of table.split("\n")) {
    const back = docTableJoinRow(docTableSplitRow(line));
    check(`${shape}/split-join`, back === line, JSON.stringify({ line, back }));
  }

  // 2. The parse finds the whole table and nothing but the table, from any
  //    offset inside it.
  let parsed = null;
  for (let offset = at; offset <= at + table.length; offset += 1) {
    const found = docTableParse(text, offset);
    if (!found) {
      check(`${shape}/parse-at-${offset - at}`, false, "no table at this offset");
      continue;
    }
    if (!parsed) parsed = found;
    check(
      `${shape}/parse-span-${offset - at}`,
      text.slice(found.from, found.to) === table,
      JSON.stringify(text.slice(found.from, found.to))
    );
  }
  if (!parsed) continue;

  // 3. Writing a cell back as it already reads changes nothing at all.
  for (let row = 0; row < parsed.rows.length; row += 1) {
    if (row === parsed.delim) continue;
    for (let col = 0; col < parsed.rows[row].cells.length; col += 1) {
      const same = docTableSetCellEdits(parsed, row, col, docTableCellText(parsed, row, col));
      check(`${shape}/set-same-${row}-${col}`, same.length === 0, JSON.stringify(same));
    }
  }

  // 4. Edit a cell and edit it back: the document is the original, byte for
  //    byte, including the padding around every other cell.
  for (let row = 0; row < parsed.rows.length; row += 1) {
    if (row === parsed.delim) continue;
    for (let col = 0; col < parsed.rows[row].cells.length; col += 1) {
      const was = docTableCellText(parsed, row, col);
      const edited = docTableApplyEdits(text, docTableSetCellEdits(parsed, row, col, "edited value"));
      const reparsed = docTableParse(edited, at);
      check(`${shape}/edit-reparse-${row}-${col}`, !!reparsed, "the edited table no longer parses");
      if (!reparsed) continue;
      check(
        `${shape}/edit-reads-back-${row}-${col}`,
        docTableCellText(reparsed, row, col) === "edited value",
        docTableCellText(reparsed, row, col)
      );
      const back = docTableApplyEdits(edited, docTableSetCellEdits(reparsed, row, col, was));
      check(`${shape}/edit-round-trip-${row}-${col}`, back === text, JSON.stringify(back));
    }
  }

  // 5. A pipe typed into a cell stays inside its cell, and reads back as the
  //    pipe that was typed.
  {
    const withPipe = docTableApplyEdits(text, docTableSetCellEdits(parsed, 0, 0, "a | b"));
    const reparsed = docTableParse(withPipe, at);
    check(`${shape}/pipe-columns`, reparsed && reparsed.columns === parsed.columns,
      reparsed ? String(reparsed.columns) : "no table");
    check(`${shape}/pipe-reads-back`, reparsed && docTableCellText(reparsed, 0, 0) === "a | b",
      reparsed ? docTableCellText(reparsed, 0, 0) : "no table");
  }

  // 6. Add a row, remove it again: the original.
  {
    const added = docTableApplyEdits(text, docTableAddRowEdits(parsed, parsed.rows.length - 1));
    const reparsed = docTableParse(added, at);
    check(`${shape}/row-added`, reparsed && reparsed.rows.length === parsed.rows.length + 1,
      reparsed ? String(reparsed.rows.length) : "no table");
    if (reparsed) {
      const back = docTableApplyEdits(added, docTableRemoveRowEdits(reparsed, reparsed.rows.length - 1));
      check(`${shape}/row-round-trip`, back === text, JSON.stringify(back));
    }
  }

  // 7. Add a column, remove it again: the original. Both ends, because the
  //    first column owns the pipe after it and every other column the pipe
  //    before it, and getting that backwards leaves a broken row.
  for (const afterCol of [0, parsed.columns - 1]) {
    const added = docTableApplyEdits(text, docTableAddColumnEdits(parsed, afterCol));
    const reparsed = docTableParse(added, at);
    check(`${shape}/col-added-${afterCol}`, reparsed && reparsed.columns === parsed.columns + 1,
      reparsed ? String(reparsed.columns) : "no table");
    if (!reparsed) continue;
    for (let row = 0; row < reparsed.rows.length; row += 1) {
      //: A body row with no trailing pipe cannot hold a blank final cell:
      //: GFM drops it, so the column is left for the renderer to pad and for
      //: the first write to materialise. Every other row grows by one.
      const ghost =
        row !== 0 && row !== parsed.delim && afterCol === parsed.columns - 1 && !parsed.rows[row].trail;
      check(
        `${shape}/col-added-cells-${afterCol}-${row}`,
        reparsed.rows[row].cells.length === parsed.rows[row].cells.length + (ghost ? 0 : 1),
        String(reparsed.rows[row].cells.length)
      );
      if (!ghost) continue;
      //: The ghost cell is writable, and writing it appends it for real.
      const written = docTableApplyEdits(added, docTableSetCellEdits(reparsed, row, parsed.columns, "late"));
      const again = docTableParse(written, at);
      check(`${shape}/ghost-cell-writable-${row}`, !!again && docTableCellText(again, row, parsed.columns) === "late",
        again ? docTableCellText(again, row, parsed.columns) : "no table");
    }
    const back = docTableApplyEdits(added, docTableRemoveColumnEdits(reparsed, afterCol + 1));
    check(`${shape}/col-round-trip-${afterCol}`, back === text, JSON.stringify(back));
  }

  // 7b. The same from the other side: a column inserted *before* one, then
  //     removed, is the original. The first column is the case that matters,
  //     because it owns the pipe on its right where every other column owns
  //     the one on its left.
  for (const col of [0, parsed.columns - 1]) {
    const added = docTableApplyEdits(text, docTableAddColumnEdits(parsed, col, true));
    const reparsed = docTableParse(added, at);
    check(`${shape}/col-before-added-${col}`, reparsed && reparsed.columns === parsed.columns + 1,
      reparsed ? String(reparsed.columns) : "no table");
    if (!reparsed) continue;
    check(`${shape}/col-before-named-${col}`, docTableCellText(reparsed, 0, col) === "Column",
      docTableCellText(reparsed, 0, col));
    const back = docTableApplyEdits(added, docTableRemoveColumnEdits(reparsed, col));
    //: The one documented exception, and it is markdown's rather than the
    //: editor's: a row with no outer pipes cannot hold a blank *first* cell,
    //: because GFM reads the leading spaces as indentation and strips the
    //: optional leading pipe. Such a table gains a leading pipe when a column
    //: goes in front of it and keeps that pipe when the column is removed
    //: again. Every other byte, including the padding of every other cell, is
    //: the author's.
    const gained = docTableApplyEdits(
      text,
      parsed.rows
        .filter((row) => !row.lead)
        .map((row) => ({ from: row.from + row.indent.length, to: row.from + row.indent.length, insert: "|" }))
    );
    const want = col === 0 ? gained : text;
    check(`${shape}/col-before-round-trip-${col}`, back === want, JSON.stringify(back));
  }

  // 8. Alignment is one delimiter cell, and setting it to what it already is
  //    is not an edit.
  for (let col = 0; col < parsed.columns; col += 1) {
    const already = docTableAlignEdits(parsed, col, parsed.aligns[col]);
    check(`${shape}/align-same-${col}`, already.length === 0, JSON.stringify(already));
    const right = docTableApplyEdits(text, docTableAlignEdits(parsed, col, "right"));
    const reparsed = docTableParse(right, at);
    check(`${shape}/align-right-${col}`, reparsed && reparsed.aligns[col] === "right",
      reparsed ? String(reparsed.aligns[col]) : "no table");
    if (!reparsed) continue;
    const back = docTableApplyEdits(right, docTableAlignEdits(reparsed, col, parsed.aligns[col]));
    check(`${shape}/align-round-trip-${col}`, back === text, JSON.stringify(back));
  }

  // 9. Tab walks the cells and steps over the delimiter row.
  {
    const last = parsed.rows.length - 1;
    const end = docTableStepCell(parsed, last, parsed.rows[last].cells.length - 1, 1);
    check(`${shape}/tab-past-the-end`, end === null, JSON.stringify(end));
    const fromHeader = docTableStepCell(parsed, 0, parsed.columns - 1, 1);
    check(`${shape}/tab-skips-the-delimiter`, fromHeader && fromHeader.row === 2,
      JSON.stringify(fromHeader));
  }
}

// A paragraph that merely contains a pipe is not a table, and a table sitting
// under one is still found: the run of pipe-bearing lines around the caret is
// wider than the table in both of these.
{
  const text = "one | two is a choice\n\n| a | b |\n| --- | --- |\n| 1 | 2 |";
  check("prose/not-a-table", docTableParse(text, 3) === null, "a paragraph parsed as a table");
  const found = docTableParse(text, text.indexOf("| 1"));
  check("prose/table-under-prose", !!found && found.columns === 2, found ? String(found.columns) : "none");
}
{
  const text = "run | of | prose\n| a | b |\n| --- | --- |\n| 1 | 2 |";
  const found = docTableParse(text, text.indexOf("| 1"));
  check("prose/header-not-the-run-start", !!found && text.slice(found.from, found.to) ===
    "| a | b |\n| --- | --- |\n| 1 | 2 |", found ? text.slice(found.from, found.to) : "none");
}

process.stdout.write(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def table_checks(tmp_path_factory) -> list[dict]:
    node = shutil.which("node")
    if not node:  # pragma: no cover - node is in the sandbox and in CI
        pytest.skip("node is not available")
    script = tmp_path_factory.mktemp("doctable") / "run.js"
    script.write_text(table_model_source() + DRIVER, encoding="utf-8")
    out = subprocess.run(
        [node, str(script), json.dumps(SHAPES), json.dumps(PROSE_BEFORE), json.dumps(PROSE_AFTER)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_model_runs_without_a_browser(table_checks: list[dict]) -> None:
    """No DOM, no app globals: the region is pure string work."""
    assert len(table_checks) > 400, "the driver did not reach the end of the shapes"


def test_every_table_operation_round_trips_byte_for_byte(table_checks: list[dict]) -> None:
    failed = [c for c in table_checks if not c["ok"]]
    assert not failed, "\n".join(f"{c['name']}: {c['detail']}" for c in failed[:20])
