"""Managing the embedding models on disk (Settings → Optional extras).

The question that prompted this is worth keeping, because the answer is not
obvious from the logs: *"the embedding model doesn't redownload every time I
load up the app right?"*, no. `SentenceTransformer(repo)` resolves through the
HuggingFace cache directory; the requests visible on every start are metadata
checks against a copy that is already there.

What there was no way to do was see it or undo it, which is what these cover.
The security property is `test_extras.py`'s and matters more here: a repo id
from a request is a path that gets written to *and deleted from* disk, so the
request names an allowlist entry and never a path.
"""

from __future__ import annotations

import pytest

from memorymap.core import embedmodels, taskhistory


@pytest.fixture(autouse=True)
def _clean():
    embedmodels.reset_for_tests()
    yield
    embedmodels.reset_for_tests()


def test_the_catalogue_says_what_each_model_costs(client):
    models = client.get("/embedding-models").json()["models"]
    assert models
    for model in models:
        assert model["about"] and model["size"] and model["repo"]
    assert sum(1 for m in models if m["default"]) == 1, "exactly one default"


def test_the_cache_location_is_reported(client):
    """"Somewhere in your home directory" is the answer every other tool
    gives, and it is the reason this screen exists."""
    assert client.get("/embedding-models").json()["cache"]


def test_an_unknown_model_is_refused_rather_than_fetched(client):
    body = client.post("/embedding-models/not-a-model/download").json()
    assert body["started"] is False
    assert "No such" in body["message"]


def test_a_repo_id_in_the_url_is_not_a_repo_id(client):
    """The whole security property. A path in the URL must be read as an
    allowlist key that does not match, never as somewhere to fetch from or, 
    far worse, since remove deletes a directory, somewhere to delete."""
    for attempt in ["BAAI/bge-small-en-v1.5", "..%2F..%2Fetc", "../../etc", "%2Fetc%2Fpasswd"]:
        got = client.post(f"/embedding-models/{attempt}/download")
        # 404/405 is the router refusing to read a path as one segment; 200
        # with started=False is the allowlist refusing it. Never a download.
        assert got.status_code in (404, 405, 200)
        if got.status_code == 200:
            assert got.json()["started"] is False


def test_removing_something_that_is_not_there_says_so(client):
    body = client.request("DELETE", "/embedding-models/bge-base").json()
    assert body["removed"] is False


def test_a_download_needs_the_hub_library_and_says_when_it_is_missing(client, monkeypatch):
    monkeypatch.setattr(embedmodels, "can_download", lambda: False)
    body = client.post("/embedding-models/bge-small/download").json()
    assert body["started"] is False
    assert "huggingface_hub" in body["message"]


def test_only_one_download_runs_at_a_time(client, monkeypatch):
    monkeypatch.setattr(embedmodels, "can_download", lambda: True)
    monkeypatch.setattr(
        embedmodels.threading,
        "Thread",
        lambda **kw: type("T", (), {"start": lambda self: None})(),
    )
    assert client.post("/embedding-models/bge-small/download").json()["started"] is True
    second = client.post("/embedding-models/minilm/download").json()
    assert second["started"] is False
    assert "already downloading" in second["message"]


# --- visible outside this one screen (Tier 1 §6) -------------------------------
#
# `DownloadState`'s own docstring says "for /tasks and the panel", the panel
# half (this file's own screen) was built, /tasks never was. A multi-hundred-MB
# download with its own dropped-connection retry logic was invisible the
# instant you clicked away from Settings → Optional extras.


def test_a_running_download_appears_in_the_shared_task_list(client, monkeypatch):
    monkeypatch.setattr(embedmodels, "can_download", lambda: True)
    monkeypatch.setattr(
        embedmodels.threading,
        "Thread",
        lambda **kw: type("T", (), {"start": lambda self: None})(),
    )
    assert client.post("/embedding-models/bge-small/download").json()["started"] is True

    tasks = client.get("/tasks").json()["tasks"]
    job = next((t for t in tasks if t["kind"] == "embedding-model"), None)
    assert job is not None, "the download is running but /tasks doesn't know"
    assert "bge-small" in job["name"] or job["name"] == "bge-small"
    assert "Downloading" in job["label"]
    # Quittable, with an honest promise: `snapshot_download` cannot be
    # interrupted mid-file, so the stop takes effect between attempts and the
    # message says the downloaded bytes are kept rather than thrown away.
    assert job["cancellable"] is True


def test_a_failed_download_is_recorded_in_task_history(monkeypatch):
    taskhistory.clear()

    def _boom(repo_id):
        raise ValueError("Repository Not Found for url")

    import sys
    import types

    fake = types.ModuleType("huggingface_hub")
    fake.snapshot_download = _boom
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)

    embedmodels._run_download(embedmodels.EMBED_MODELS_BY_ID["minilm"])

    # Not running any more, so a poll after this point must not still list it.
    assert embedmodels.current().running is False
    entry = next((h for h in taskhistory.recent() if h["kind"] == "embedding-model"), None)
    assert entry is not None, "a failed download vanished instead of being recorded"
    assert entry["outcome"] == "failed"
    assert entry["name"] == "minilm"


def test_a_repo_id_can_never_name_a_directory_outside_the_cache(tmp_path, monkeypatch):
    """The `/` → `--` substitution is not cosmetic, it is the defence.

    HuggingFace's own layout flattens `org/name` to `models--org--name`, which
    means a repo id full of `../` becomes one harmless directory name inside
    the cache rather than a climb out of it. Written down because it looks like
    formatting and is load-bearing.
    """
    monkeypatch.setattr(embedmodels, "cache_root", lambda: tmp_path / "hub")
    escaped = embedmodels.EmbedModel(
        id="escapee", repo="../../../etc/passwd", label="x", about="x", size="x"
    )
    path = embedmodels._model_dir(escaped)
    assert path.parent == tmp_path / "hub"
    assert path.name == "models--..--..--..--etc--passwd"


def test_a_directory_outside_the_cache_root_is_never_deleted(tmp_path, monkeypatch):
    """Belt and braces behind the two rules above. If a future change ever lets
    a path out of the cache, this is what stops `rmtree` following it."""
    monkeypatch.setattr(embedmodels, "cache_root", lambda: tmp_path / "hub")
    (tmp_path / "hub").mkdir()
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "notes.db").write_text("do not delete me")
    escaped = embedmodels.EmbedModel(
        id="escapee", repo="x", label="x", about="x", size="x"
    )
    monkeypatch.setitem(embedmodels.EMBED_MODELS_BY_ID, "escapee", escaped)
    monkeypatch.setattr(embedmodels, "_model_dir", lambda m: outside)
    removed, message = embedmodels.remove("escapee")
    assert removed is False
    assert "outside the model cache" in message
    assert (outside / "notes.db").exists()


def test_the_size_on_disk_ignores_the_cache_symlinks(tmp_path, monkeypatch):
    """The hub cache is made of symlinks, `snapshots/` links into `blobs/` , 
    so a walk that follows them reports twice the real size, and this screen
    exists to tell the truth about disk."""
    monkeypatch.setattr(embedmodels, "cache_root", lambda: tmp_path)
    blobs = tmp_path / "models--BAAI--bge-small-en-v1.5" / "blobs"
    blobs.mkdir(parents=True)
    real = blobs / "weights"
    real.write_bytes(b"x" * 2048)
    snap = tmp_path / "models--BAAI--bge-small-en-v1.5" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "weights").symlink_to(real)
    row = next(m for m in embedmodels.status() if m["id"] == "bge-small")
    assert row["installed"] is True
    assert row["on_disk"] == "2 KB"


def test_a_dropped_connection_is_retried_and_then_explained(monkeypatch):
    """Reported from a real download: `[WinError 10054] An existing connection
    was forcibly closed by the remote host`. That is one TCP connection dying
    part-way through several hundred megabytes, not a broken install, and
    `snapshot_download` resumes from the cache, so a retry costs the bytes
    since the last completed file rather than starting again."""
    calls = []

    def _boom(repo_id):
        calls.append(repo_id)
        raise OSError("[WinError 10054] An existing connection was forcibly closed")

    import sys
    import types

    fake = types.ModuleType("huggingface_hub")
    fake.snapshot_download = _boom
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    embedmodels._run_download(embedmodels.EMBED_MODELS_BY_ID["minilm"])
    assert len(calls) == embedmodels.DOWNLOAD_ATTEMPTS
    state = embedmodels.current()
    assert state.outcome == "failed"
    # The advice has to be actionable and true: resuming is what pressing the
    # button again actually does.
    assert "resumes rather than starting over" in state.step


def test_a_failure_that_is_not_the_network_is_not_retried(monkeypatch):
    """Retrying a wrong repo id three times wastes the user's time and buries
    the real reason under two identical attempts."""
    calls = []

    def _boom(repo_id):
        calls.append(repo_id)
        raise ValueError("Repository Not Found for url")

    import sys
    import types

    fake = types.ModuleType("huggingface_hub")
    fake.snapshot_download = _boom
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    embedmodels._run_download(embedmodels.EMBED_MODELS_BY_ID["minilm"])
    assert len(calls) == 1
    assert embedmodels.current().outcome == "failed"
