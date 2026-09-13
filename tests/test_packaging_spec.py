"""The Windows PyInstaller spec's `hiddenimports` list, kept honest against
the source it's meant to cover.

Nothing here can run PyInstaller itself, that only happens in CI, on
windows-latest (packaging/windows/memorymap.spec's own header comment says
so). What this guards against is cheaper and just as real: a module reached
only through `importlib.import_module` (searxng_manager.py's `__getattr__`
facade, the same "picked by name at runtime" shape as the uvicorn/sqlalchemy/
pywebview/pystray entries already in the spec) going missing from a frozen
build because nobody remembered to list it. That exact bug shipped once,
confirmed by a real user's support bundle: "ModuleNotFoundError: No module
named 'memorymap.search.searxng_docker'" on a packaged Windows install.
"""

from __future__ import annotations

from pathlib import Path

from memorymap.search import searxng_manager

SPEC_PATH = (
    Path(__file__).resolve().parents[1] / "packaging" / "windows" / "memorymap.spec"
)


def test_every_searxng_facade_module_is_a_hidden_import():
    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    for module_name in searxng_manager._FACADE_NAMES:
        needle = f"memorymap.search.{module_name}"
        assert needle in spec_text, (
            f"{needle} is reached only via searxng_manager's dynamic "
            "__getattr__ and must be listed in the spec's hiddenimports, "
            "or a frozen build can't import it"
        )
