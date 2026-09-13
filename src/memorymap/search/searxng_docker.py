"""Run SearXNG as a Docker container.

Split out of `searxng_manager.py` (see that module for the two backends and
why Docker is only the tidier one). Everything here is the docker-cli side of
it: is Docker there and its daemon up, create/start/stop the
`memorymap-searxng` container, and the loopback-only publishing rule (and the
guard that re-creates a container an earlier version published to every
interface, since publishing is fixed at container creation and `docker start`
can't change it).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from memorymap.search import searxng_manager, websearch
from memorymap.search.searxng_manager import (
    START_TIMEOUT,
    SearxngError,
    _reason,
    base_url,
    host_port,
)
from memorymap.search.searxng_settings import ensure_settings

# `_run`, `_wait_until_ready` and `docker_installed` (the last one, called
# from `docker_available` just below, is defined in this very file) are
# deliberately not used as bare names anywhere below: the test suite
# monkeypatches all three as `searxng_manager.<name>`, which only rebinds
# that attribute on the `searxng_manager` module object. Going through
# `searxng_manager.<name>` looks each one up fresh, so a patched or a real
# implementation is picked up exactly as it was when this was one file.

CONTAINER_NAME = "memorymap-searxng"
IMAGE = "searxng/searxng:latest"

# `docker info` against a stopped daemon is quick to fail, but give it room on
# a cold Docker Desktop rather than calling a slow start "not running".
DAEMON_PROBE_TIMEOUT = 8


def docker_installed() -> bool:
    """Is the docker command on PATH? Says nothing about the daemon."""
    return shutil.which("docker") is not None


def docker_available() -> bool:
    """Can we actually run a container right now?

    Checking only that the binary exists was wrong, and produced exactly the
    failure it should have prevented: with Docker Desktop installed but not
    started, the app picked the Docker backend, tried to create a container,
    and reported "failed to connect to the docker API at npipe:...", while
    the from-source backend that would have worked was never considered.

    `docker info` is the cheapest question that means "is the daemon up".
    """
    if not searxng_manager.docker_installed():
        return False
    try:
        result = subprocess.run(  # noqa: S603  # fixed args, no shell
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=DAEMON_PROBE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _docker_state() -> str:
    """'running', 'stopped', or 'absent' for our container."""
    result = searxng_manager._run(
        ["docker", "ps", "-a", "--filter", f"name=^{CONTAINER_NAME}$", "--format", "{{.State}}"]
    )
    state = (result.stdout or "").strip().splitlines()
    if not state:
        return "absent"
    return "running" if state[0].strip() == "running" else "stopped"


def _publish_spec() -> str:
    """The -p argument, pinned to the loopback interface.

    `-p 8888:8080` publishes on EVERY interface, which is not what the plain
    reading suggests and is the one place the docker path disagreed with the
    source path: that one sets SEARXNG_BIND_ADDRESS=127.0.0.1 and is reachable
    only from this machine. Docker also writes its own iptables rules, so a
    published port is reachable from the LAN even behind a host firewall that
    is set to refuse it, the firewall never sees the packet. Naming the
    interface is the whole fix.

    It matters here more than the port number suggests. SearXNG is an open
    proxy to the wider internet with no auth in front of it, and its /search
    endpoint takes the query as a GET parameter, so an exposed instance is
    both something a stranger on the café wifi can run searches through and a
    log of everything the owner has searched for.
    """
    return f"127.0.0.1:{host_port()}:8080"


def _docker_publishes_beyond_localhost() -> bool:
    """Does the existing container publish to the world rather than loopback?

    Port publishing is fixed when a container is CREATED, so changing the
    `docker run` above only protects people who have never started SearXNG.
    Anyone who ran an earlier version already has a container published on
    0.0.0.0, and `docker start` would keep it that way forever. This is what
    tells `_start_docker` to replace it instead.
    """
    result = searxng_manager._run(
        [
            "docker", "inspect", CONTAINER_NAME,
            "--format", "{{range $p, $conf := .HostConfig.PortBindings}}" +
                        "{{range $conf}}{{.HostIp}}\n{{end}}{{end}}",
        ]
    )
    if result.returncode != 0:
        return False  # can't tell: don't destroy a container on a guess
    bindings = [line.strip() for line in (result.stdout or "").splitlines()]
    bindings = [line for line in bindings if line]
    if not bindings:
        # No host IP recorded at all means "all interfaces", the same default
        # the bare `-p 8888:8080` form produces.
        return True
    return any(
        host_ip in ("", "0.0.0.0", "::") or not host_ip.startswith(("127.", "::1"))
        for host_ip in bindings
    )


def _remove_container() -> None:
    """Drop the container so the next start recreates it. Data is not lost:
    SearXNG keeps nothing we care about inside it, the settings file lives on
    the host and is mounted in."""
    searxng_manager._run(["docker", "rm", "-f", CONTAINER_NAME], timeout=40)


def _start_docker(data_dir: Path) -> dict:
    """Start (or create) the container and wait until it answers JSON."""
    # Refreshed for every path, not only creation: the container mounts this
    # host file, so a stopped container restarted with stale settings would
    # keep old engine defaults forever, the exact staleness rewrite-on-start
    # exists to end.
    settings = ensure_settings(data_dir)
    state = _docker_state()
    # A container an earlier version created is published on every interface,
    # and no amount of starting it changes that, publishing is set at create
    # time. Replace it rather than hand back a LAN-visible search proxy.
    if state != "absent" and _docker_publishes_beyond_localhost():
        logging.getLogger("memorymap.searxng").info(
            "Recreating the SearXNG container: it was published on all "
            "interfaces, and it should only be reachable from this machine."
        )
        _remove_container()
        state = "absent"
    if state == "running":
        if websearch.probe_searxng(base_url()):
            return {"url": base_url(), "started": False}
    elif state == "stopped":
        result = searxng_manager._run(["docker", "start", CONTAINER_NAME])
        if result.returncode != 0:
            raise SearxngError(_reason(result, "Couldn't start the existing container"))
    else:
        result = searxng_manager._run(
            [
                "docker", "run", "-d",
                "--name", CONTAINER_NAME,
                "--restart", "unless-stopped",
                "-p", _publish_spec(),
                "-v", f"{settings}:/etc/searxng/settings.yml:ro",
                "-e", f"SEARXNG_BASE_URL={base_url()}/",
                IMAGE,
            ],
            timeout=START_TIMEOUT,
        )
        if result.returncode != 0:
            raise SearxngError(_reason(result, "Couldn't create the container"))

    if not searxng_manager._wait_until_ready():
        raise SearxngError(
            "SearXNG started but isn't answering yet. Give it a moment and press "
            "Auto-detect, or check `docker logs memorymap-searxng`."
        )
    return {"url": base_url(), "started": True}
