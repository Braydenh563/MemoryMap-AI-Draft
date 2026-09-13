"""The whole-notebook markdown export (a zip of files) and its import.

(Unrelated to test_document_import.py, which is markitdown converting an
uploaded PDF/DOCX/etc. into notes: this is the notebook's own round-trip
format: one `.md` file per note, with frontmatter for category/tags.)
"""

from __future__ import annotations

import io
import zipfile


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


def test_markdown_export_zip_layout(client):
    _save(client, "buy milk", category="Shopping", tags=["errand"])
    binned = _save(client, "old thought")
    client.delete(f"/entries/{binned['id']}")

    response = client.get("/export/markdown")
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = archive.namelist()
    assert any(name.startswith("Shopping/") for name in names)
    assert any(name.startswith("_recycle-bin/") for name in names)  # never dropped

    shopping = archive.read([n for n in names if n.startswith("Shopping/")][0]).decode()
    assert "category: Shopping" in shopping
    assert "tags: [errand]" in shopping
    assert shopping.rstrip().endswith("buy milk")


def _upload(client, files):
    return client.post(
        "/import/markdown",
        files=[("files", (name, body.encode(), "text/markdown")) for name, body in files],
    )


def test_markdown_import_with_frontmatter(client):
    body = "---\ncategory: Recipes\ntags: [dinner, easy]\n---\n\nPasta: boil, sauce, eat."
    response = _upload(client, [("pasta.md", body)])
    assert response.status_code == 201
    assert response.json() == {"imported": 1, "skipped": []}

    entry = client.get("/entries").json()[0]
    assert entry["content"] == "Pasta: boil, sauce, eat."
    assert entry["category"] == "Recipes"
    assert entry["tags"] == ["dinner", "easy"]
    assert entry["user_filed"] is True  # the file chose its home


def test_markdown_import_plain_file_and_skips(client):
    response = _upload(client, [("idea.md", "just a plain thought"), ("empty.md", "   ")])
    body = response.json()
    assert body["imported"] == 1
    assert body["skipped"] == ["empty.md: empty"]
    assert client.get("/entries").json()[0]["category"] == "Uncategorised"


def test_directory_import_walks_a_folder_and_files_notes(client, tmp_path):
    """The Settings -> Data "Bulk Directory Import" path (an Obsidian-vault-
    style import): a background task rather than an upload, so it has to
    open its own DB session rather than reuse the request's."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "recipe.md").write_text(
        "---\ncategory: Recipes\ntags: [dinner]\n---\n\nPasta night.", encoding="utf-8"
    )
    (vault / "plain.md").write_text("just a plain thought", encoding="utf-8")
    (vault / "empty.md").write_text("   ", encoding="utf-8")

    response = client.post("/import/directory", json={"path": str(vault)})
    assert response.status_code == 202
    assert response.json()["status"] == "started"

    entries = client.get("/entries").json()
    assert len(entries) == 2  # empty.md skipped
    by_content = {e["content"]: e for e in entries}
    assert by_content["Pasta night."]["category"] == "Recipes"
    assert by_content["Pasta night."]["tags"] == ["dinner"]
    assert by_content["Pasta night."]["user_filed"] is True
    assert by_content["just a plain thought"]["category"] == "Uncategorised"


def test_directory_import_refuses_a_path_that_is_not_a_directory(client, tmp_path):
    response = client.post("/import/directory", json={"path": str(tmp_path / "nope")})
    assert response.status_code == 400


def test_full_backup_export_is_a_zip_of_the_database(client):
    """Settings -> Data "Export Full Backup (.zip)"."""
    _save(client, "back this up")

    response = client.get("/export/backup")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert "memorymap.db" in archive.namelist()


def test_markdown_roundtrip(client):
    _save(client, "roundtrip me", category="Ideas", tags=["keep"])
    exported = client.get("/export/markdown").content
    archive = zipfile.ZipFile(io.BytesIO(exported))
    name = archive.namelist()[0]

    response = _upload(client, [(name.split("/")[-1], archive.read(name).decode())])
    assert response.json()["imported"] == 1
    contents = [e["content"] for e in client.get("/entries").json()]
    assert contents.count("roundtrip me") == 2  # original + reimport


def test_the_cli_export_writes_the_same_archive_as_the_route(client, tmp_path, monkeypatch):
    """`python -m memorymap --export PATH` and the Settings download are one
    function, not two implementations. uninstall.sh --export calls the first
    so someone removing the app can take their notes out with no browser and
    no running server, and it has to be the same zip.
    """
    _save(client, "buy milk", category="Shopping", tags=["errand"])
    binned = _save(client, "old thought")
    client.delete(f"/entries/{binned['id']}")

    from memorymap.__main__ import _export_markdown

    target = tmp_path / "out" / "notes.zip"
    assert _export_markdown(str(target)) == 0
    assert target.exists()

    from_route = zipfile.ZipFile(io.BytesIO(client.get("/export/markdown").content))
    from_cli = zipfile.ZipFile(target)
    assert sorted(from_cli.namelist()) == sorted(from_route.namelist())
    name = [n for n in from_cli.namelist() if n.startswith("Shopping/")][0]
    assert from_cli.read(name) == from_route.read(name)


def test_the_cli_export_puts_the_default_name_inside_a_directory(client, tmp_path):
    """`--export .` is what someone types, and it must not try to write a
    zip over the directory itself."""
    _save(client, "buy milk")
    from memorymap.__main__ import _export_markdown

    assert _export_markdown(str(tmp_path)) == 0
    assert (tmp_path / "memorymap-markdown.zip").exists()


def test_the_cli_export_reports_rather_than_raises_on_an_unwritable_path(client, tmp_path):
    """Someone exporting before an uninstall gets a sentence, not a
    traceback, and a non-zero code so the uninstaller stops."""
    _save(client, "buy milk")
    from memorymap.__main__ import _export_markdown

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    assert _export_markdown(str(blocker / "sub" / "notes.zip")) == 1
