"""Block references parse and write the way the plan's decision says.

DOCUMENTS_PLAN Phase 4 item 2. The model lives between `DOC-BLOCKREF-BEGIN`
and `DOC-BLOCKREF-END` in documents.js and is pure string work with no DOM and
no app globals in it, so python can run it in node. That is a property this
test enforces by existing, the same way the table, frontmatter and columns
models are tested.

What matters here is not the happy case. It is that the shapes around it do
not silently become block ids: a `^` in prose ("2^31") is arithmetic, a `^id`
inside a code fence is an example of the syntax rather than a use of it, and a
link written yesterday has to keep resolving, which means an id is never
regenerated for a block that has one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_JS = ROOT / "frontend" / "documents.js"

BEGIN = "// DOC-BLOCKREF-BEGIN"
END = "// DOC-BLOCKREF-END"


def blockref_source() -> str:
    text = DOCUMENTS_JS.read_text(encoding="utf-8")
    start = text.find(BEGIN)
    stop = text.find(END)
    assert start != -1, f"{BEGIN} marker is missing from documents.js"
    assert stop > start, f"{END} marker is missing or before {BEGIN}"
    return text[start + len(BEGIN) : stop]


DRIVER = r"""
const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail === undefined ? null : detail });
}
// A generator with no randomness in it, so every assertion below is exact.
let counter = 0;
const fixedIds = ['aaaaaa', 'bbbbbb', 'cccccc'];
const fixed = () => {
  const id = fixedIds[Math.min(counter, fixedIds.length - 1)];
  counter++;
  return parseInt(id, 36) / 36 ** 6;
};

// --- splitting a reference -------------------------------------------------
{
  const cases = [
    ['Design notes', { name: 'Design notes', blockId: null }],
    ['Design notes#^abc123', { name: 'Design notes', blockId: 'abc123' }],
    ['  Design notes  #^abc123 ', { name: 'Design notes', blockId: 'abc123' }],
    ['Design notes#^', { name: 'Design notes', blockId: null }],
    ['Design notes#^not an id', { name: 'Design notes', blockId: null }],
    ['#^abc123', { name: '', blockId: 'abc123' }],
    ['', { name: '', blockId: null }],
  ];
  for (const [spec, want] of cases) {
    const got = docBlockRefSplit(spec);
    check(`split/${spec}/name`, got.name === want.name, got.name);
    check(`split/${spec}/id`, got.blockId === want.blockId, String(got.blockId));
  }
}

// --- what a block is -------------------------------------------------------
{
  const text = [
    '# A heading',            // 0
    '',
    'One paragraph line.',    // 2
    'Its second line.',       // 3
    '',
    '- first item',           // 5
    '- second item',          // 6
    '',
    '```',                    // 8
    'code ^notanid',          // 9
    '```',                    // 10
  ].join('\n');
  const at = (line, col) => {
    const lines = text.split('\n');
    let pos = 0;
    for (let i = 0; i < line; i++) pos += lines[i].length + 1;
    return pos + (col || 0);
  };
  const para = docBlockBounds(text, at(2, 3));
  check('bounds/paragraph joins its lines', text.slice(para.from, para.to) === 'One paragraph line.\nIts second line.', text.slice(para.from, para.to));
  check('bounds/the last line is the id line', text.slice(para.lastFrom, para.lastTo) === 'Its second line.', text.slice(para.lastFrom, para.lastTo));
  const item = docBlockBounds(text, at(6, 3));
  check('bounds/a list item is its own block', text.slice(item.from, item.to) === '- second item', text.slice(item.from, item.to));
  check('bounds/a blank line has no block', docBlockBounds(text, at(1, 0)) === null, '');
  check('bounds/inside a fence has no block', docBlockBounds(text, at(9, 2)) === null, '');
  const heading = docBlockBounds(text, at(0, 2));
  check('bounds/a heading is a block of its own', text.slice(heading.from, heading.to) === '# A heading', text.slice(heading.from, heading.to));
}

// --- giving a block an id --------------------------------------------------
{
  counter = 0;
  const text = 'One paragraph line.\nIts second line.\n\nAnother.';
  const first = docBlockEnsureIdEdits(text, 3, fixed);
  check('ensure/an id is added', first.reason === 'added', first.reason);
  check('ensure/one edit only', first.edits.length === 1, String(first.edits.length));
  const applied = text.slice(0, first.edits[0].from) + first.edits[0].insert + text.slice(first.edits[0].to);
  check('ensure/it lands at the end of the last line', applied === 'One paragraph line.\nIts second line. ^aaaaaa\n\nAnother.', JSON.stringify(applied));
  check('ensure/and nothing else moved', applied.replace(' ^aaaaaa', '') === text, JSON.stringify(applied));

  const again = docBlockEnsureIdEdits(applied, 3, fixed);
  check('ensure/a block that has one keeps it', again.id === 'aaaaaa' && again.edits.length === 0, `${again.id}/${again.reason}`);

  const blank = docBlockEnsureIdEdits('para\n\n', 5, fixed);
  check('ensure/a blank line refuses', blank.reason === 'no-block' && blank.id === null, blank.reason);

  // Two trailing spaces are a markdown hard break: the id must not move it.
  counter = 1;
  const hard = 'A line with a break  \nnext line.';
  const edits = docBlockEnsureIdEdits(hard, 2, fixed).edits;
  const after = hard.slice(0, edits[0].from) + edits[0].insert + hard.slice(edits[0].to);
  check('ensure/a hard break is not padded around', after === 'A line with a break  \nnext line. ^bbbbbb', JSON.stringify(after));
}

// --- collisions ------------------------------------------------------------
{
  counter = 0;
  const text = 'first ^aaaaaa\n\nsecond';
  const made = docBlockEnsureIdEdits(text, text.length - 1, fixed);
  check('ids/a taken id is not handed out twice', made.id === 'bbbbbb', String(made.id));
  const ids = docBlockIds('one ^abc123\ntwo\nthree ^def456\n');
  check('ids/every id in the text is seen', ids.size === 2 && ids.has('abc123') && ids.has('def456'), String(ids.size));
}

// --- finding a block by its id ---------------------------------------------
{
  const text = [
    '# Doc',
    '',
    'The block we want.',
    'Its second line. ^abc123',
    '',
    'Another block.',
    '',
    '```',
    'not the block ^abc123',
    '```',
  ].join('\n');
  const found = docBlockFind(text, 'abc123');
  check('find/the whole block comes back', found.text === 'The block we want.\nIts second line.', JSON.stringify(found && found.text));
  check('find/the marker is not part of it', !found.text.includes('^abc123'), found.text);
  check('find/the span is the block in the document', text.slice(found.from, found.to).startsWith('The block we want.'), '');
  check('find/an id nobody carries is null', docBlockFind(text, 'zzzzzz') === null, '');
  check('find/an id that is not an id is null', docBlockFind(text, 'not an id') === null, '');
}

// --- the shapes that are not block ids -------------------------------------
{
  const cases = [
    ['2^31 is a big number.', 'arithmetic'],
    ['x ^ y is a caret.', 'a bare caret'],
    ['A line ending in ^ nothing else', 'a caret not at the end'],
    ['trailing ^UPPER-case-ok', null],
  ];
  for (const [line, why] of cases) {
    const bounds = docBlockBounds(line, 1);
    const id = docBlockIdOf(line, bounds);
    if (why === null) check(`notid/${line}`, id !== null && id.id === 'UPPER-case-ok', String(id && id.id));
    else check(`notid/${why}`, id === null, String(id && id.id));
  }
}

// --- the reader's copy has no markers in it --------------------------------
{
  const text = [
    'A paragraph. ^abc123',
    '',
    'Another one.',
    '',
    '```',
    'shell ^keepme',
    '```',
    '',
    'A link to [[Doc#^abc123]] keeps its reference.',
  ].join('\n');
  const stripped = docBlockStripIds(text);
  check('strip/the marker is gone', !stripped.includes('^abc123\n') && stripped.startsWith('A paragraph.\n'), JSON.stringify(stripped.split('\n')[0]));
  check('strip/a fence is left alone', stripped.includes('shell ^keepme'), '');
  check('strip/a reference in prose is not a marker', stripped.includes('[[Doc#^abc123]]'), '');
  check('strip/nothing else changed', stripped.replace(' ^abc123', '') === text.replace(' ^abc123', ''), '');
  check('strip/empty text is empty', docBlockStripIds(null) === '', JSON.stringify(docBlockStripIds(null)));
}

process.stdout.write(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def blockref_checks(tmp_path_factory) -> list[dict]:
    node = shutil.which("node")
    if not node:  # pragma: no cover - node is in the sandbox and in CI
        pytest.skip("node is not available")
    script = tmp_path_factory.mktemp("docblockrefs") / "run.js"
    script.write_text(blockref_source() + DRIVER, encoding="utf-8")
    out = subprocess.run(
        [node, str(script)], capture_output=True, text=True, timeout=60, check=False
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_model_runs_without_a_browser(blockref_checks: list[dict]) -> None:
    assert len(blockref_checks) > 30, "the driver did not reach the end"


def test_block_references_parse_and_write_as_decided(blockref_checks: list[dict]) -> None:
    failed = [c for c in blockref_checks if not c["ok"]]
    assert not failed, "\n".join(f"{c['name']}: {c['detail']}" for c in failed[:20])
