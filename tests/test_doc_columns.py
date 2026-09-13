"""Columns and image options parse the way the plan's decision says they do.

DOCUMENTS_PLAN Phase 3 item 5. Two parsers, both in the marked region
`DOC-BLOCKS-BEGIN` / `DOC-BLOCKS-END` of documents.js, both pure string work
with no DOM and no app globals in them, so python can run them in node.

What matters here is not that the happy case works: it is that the shapes
around it do not silently become blocks. A `:::` inside a code fence is an
example of the syntax rather than a use of it; an unclosed block is somebody
halfway through typing one and must not turn the rest of the document into a
column; and an image option that is neither a number nor an alignment is a
caption, wherever in the list it appears, because `![[photo|A river|400]]` is
what people type once they know both exist.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_JS = ROOT / "frontend" / "documents.js"

BEGIN = "// DOC-BLOCKS-BEGIN"
END = "// DOC-BLOCKS-END"


def blocks_source() -> str:
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

// --- the shape the plan decided on -----------------------------------------
{
  const text = [
    '# A page',
    '',
    ':::columns',
    'Left hand side.',
    '',
    'Still the left.',
    ':::column',
    'Right hand side.',
    ':::',
    '',
    'After the block.',
  ].join('\n');
  const blocks = docColumnsBlocks(text);
  check('one block', blocks.length === 1, String(blocks.length));
  const block = blocks[0];
  check('the block starts at its opener', text.slice(block.from, block.from + 10) === ':::columns',
    text.slice(block.from, block.from + 10));
  check('and ends at its closer', text.slice(block.to - 3, block.to) === ':::', text.slice(block.to - 3, block.to));
  check('two columns', block.columns.length === 2, String(block.columns.length));
  check('the first column is its own text',
    block.columns[0].text === 'Left hand side.\n\nStill the left.', JSON.stringify(block.columns[0].text));
  check('the second column is its own text',
    block.columns[1].text === 'Right hand side.', JSON.stringify(block.columns[1].text));
  check('every column span reads back out of the document',
    block.columns.every((c) => text.slice(c.from, c.to) === c.text), 'a span disagrees with its text');
  check('the caret in the block finds it', docColumnsAt(text, block.from + 12) === null ? false : true, 'not found');
  check('the caret outside it does not', docColumnsAt(text, 0) === null, 'found a block at the title');
}

// --- three columns, and the count in the opener is ignored ------------------
{
  const text = '::: columns 3\na\n:::column\nb\n:::column\nc\n:::\n';
  const blocks = docColumnsBlocks(text);
  check('three columns', blocks.length === 1 && blocks[0].columns.length === 3,
    blocks.length ? String(blocks[0].columns.length) : 'no block');
  check('and each holds its own letter',
    blocks.length && blocks[0].columns.map((c) => c.text).join('') === 'abc',
    blocks.length ? blocks[0].columns.map((c) => c.text).join('|') : 'none');
}

// --- an empty column is still a column --------------------------------------
{
  const text = ':::columns\n:::column\nb\n:::\n';
  const blocks = docColumnsBlocks(text);
  check('an empty first column', blocks.length === 1 && blocks[0].columns.length === 2,
    blocks.length ? String(blocks[0].columns.length) : 'no block');
  check('and it is empty', blocks.length && blocks[0].columns[0].text === '',
    blocks.length ? JSON.stringify(blocks[0].columns[0].text) : 'none');
}

// --- the shapes that must NOT become blocks ---------------------------------
{
  check('an unclosed block is not a block',
    docColumnsBlocks(':::columns\nhalf typed\n').length === 0, 'an unclosed block parsed');
  check('a fence with no columns word is not a block',
    docColumnsBlocks(':::\nwhat is this\n:::\n').length === 0, 'a bare fence parsed');
  const fenced = ['```markdown', ':::columns', 'a', ':::column', 'b', ':::', '```'].join('\n');
  check('a block inside a code fence is an example, not a block',
    docColumnsBlocks(fenced).length === 0, 'a fenced example parsed');
  const after = ['```', 'code', '```', ':::columns', 'a', ':::column', 'b', ':::'].join('\n');
  check('and a real block after a code fence still parses',
    docColumnsBlocks(after).length === 1, String(docColumnsBlocks(after).length));
  const reopened = [':::columns', 'a', ':::columns', 'b', ':::column', 'c', ':::'].join('\n');
  const blocks = docColumnsBlocks(reopened);
  check('a second opener restarts the block', blocks.length === 1 && blocks[0].columns.length === 2,
    blocks.length ? String(blocks[0].columns.length) : 'no block');
  check('and the block is the second opener onwards',
    blocks.length && reopened.slice(blocks[0].from).startsWith(':::columns\nb'),
    blocks.length ? JSON.stringify(reopened.slice(blocks[0].from, blocks[0].from + 14)) : 'none');
}

// --- two blocks in one document ---------------------------------------------
{
  const text = ':::columns\na\n:::column\nb\n:::\n\nbetween\n\n:::columns\nc\n:::column\nd\n:::\n';
  const blocks = docColumnsBlocks(text);
  check('two blocks', blocks.length === 2, String(blocks.length));
  check('and they do not overlap', blocks.length === 2 && blocks[0].to < blocks[1].from, 'they overlap');
  check('the text between them is outside both',
    blocks.length === 2 && text.slice(blocks[0].to, blocks[1].from).includes('between'),
    JSON.stringify(text.slice(blocks[0].to, blocks[1].from)));
}

// --- the template the "/" menu inserts parses as one empty two-column block --
{
  const blocks = docColumnsBlocks(docColumnsTemplate());
  check('the template is a block', blocks.length === 1 && blocks[0].columns.length === 2,
    blocks.length ? String(blocks[0].columns.length) : 'no block');
}

// --- image options, by shape rather than by position ------------------------
{
  const cases = [
    ['photo.png', { name: 'photo.png', width: null, align: null, caption: '' }],
    ['photo.png|300', { name: 'photo.png', width: 300, align: null, caption: '' }],
    ['photo.png|300|center', { name: 'photo.png', width: 300, align: 'center', caption: '' }],
    ['photo.png|centre', { name: 'photo.png', width: null, align: 'center', caption: '' }],
    ['photo.png|A river at dusk|400', { name: 'photo.png', width: 400, align: null, caption: 'A river at dusk' }],
    ['photo.png|300x200', { name: 'photo.png', width: 300, align: null, caption: '' }],
    ['A river|400|center', { name: 'A river', width: 400, align: 'center', caption: '' }],
    ['photo.png|RIGHT', { name: 'photo.png', width: null, align: 'right', caption: '' }],
    ['photo.png|12345', { name: 'photo.png', width: null, align: null, caption: '12345' }],
    ['  photo.png  |  300  ', { name: 'photo.png', width: 300, align: null, caption: '' }],
  ];
  for (const [spec, want] of cases) {
    const got = docImageOptions(spec);
    for (const key of Object.keys(want)) {
      check(`options/${spec}/${key}`, got[key] === want[key], `${key}=${JSON.stringify(got[key])}`);
    }
  }
  check('options/empty', docImageOptions('').name === '', docImageOptions('').name);
}

process.stdout.write(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def block_checks(tmp_path_factory) -> list[dict]:
    node = shutil.which("node")
    if not node:  # pragma: no cover - node is in the sandbox and in CI
        pytest.skip("node is not available")
    script = tmp_path_factory.mktemp("doccols") / "run.js"
    script.write_text(blocks_source() + DRIVER, encoding="utf-8")
    out = subprocess.run(
        [node, str(script)], capture_output=True, text=True, timeout=60, check=False
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_parsers_run_without_a_browser(block_checks: list[dict]) -> None:
    assert len(block_checks) > 50, "the driver did not reach the end"


def test_columns_and_image_options_parse_as_decided(block_checks: list[dict]) -> None:
    failed = [c for c in block_checks if not c["ok"]]
    assert not failed, "\n".join(f"{c['name']}: {c['detail']}" for c in failed[:20])
