"""The backend address is the one setting that can send notes off this machine.

Everything else about MemoryMap is local by construction: the server binds to
localhost, the database is a file, nothing phones home. §6 made the *chat
backend* an address the user types, and the server posts their notes to
whatever it names on every turn. That is a new outbound surface and it needs a
rule: but the opposite rule from the web reader's.

`websearch._assert_external` refuses anything that ISN'T public, because it
follows untrusted links and must never probe this machine. This is the mirror
image: a model backend is *supposed* to be on localhost or the LAN, so private
addresses are the normal case and refusing them would break the product.

What is left to refuse is narrow, and the interesting member is link-local:
169.254.169.254 is the cloud instance-metadata service, the classic
credential-theft target, and nobody has ever served a language model from it.

The other half is honesty rather than enforcement. Someone who deliberately
points this at a hosted API is entitled to. What they are not entitled to is
for it to happen quietly.
"""

from __future__ import annotations

import pytest

from memorymap.core import security
from memorymap.core.security import check_backend_url


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch):
    """Answer hostname lookups from a table instead of the network.

    These tests were resolving `api.openai.com` and `*.invalid` for real. That
    made them depend on the machine's resolver: fast here, unbounded on a CI
    runner whose DNS is slow or absent, and `getaddrinfo` takes no timeout. A
    test suite that is "fully offline" (the project's own rule, and the reason
    CI needs no network beyond pip) should not have been asking DNS anything.

    Literal addresses never reach this: `_backend_addresses` parses those
    directly, which is the common case anyway.
    """
    table = {
        "api.openai.com": ["104.18.7.192"],
        "ollama.com": ["34.36.133.15"],
    }
    monkeypatch.setattr(security, "_resolve", lambda host: table.get(host, []))


def allowed(url):
    return check_backend_url(url)[0]


# --- refused ----------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://localhost/v1",
        "gopher://localhost:1234/v1",
        "",
        "not a url at all",
    ],
)
def test_only_http_addresses_can_be_a_backend(url):
    """`file://` is the one that matters: some HTTP libraries support it, and
    a backend URL is read back by the app rather than only written to."""
    assert not allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/v1",          # AWS/GCP/Azure metadata
        "http://169.254.169.254:80/latest/",
        "http://[fe80::1]/v1",                # IPv6 link-local
        "http://[::ffff:169.254.169.254]/v1", # the same address wearing a hat
    ],
)
def test_the_cloud_metadata_address_is_refused(url):
    assert not allowed(url)


def test_the_overlapping_categories_are_ordered_correctly():
    """Python's address categories overlap in two places, and each overlap
    flips an answer if the checks run in the wrong order. This is the test
    that catches a well-meaning reordering of `_refuses`.

    169.254.0.0/16 is link-local *and* `is_private`, so an allow-private rule
    running first waves through the cloud metadata address. `::1` is loopback
    *and* `is_reserved`, so a refuse-reserved rule running first rejects the
    most ordinary backend there is.
    """
    import ipaddress

    assert ipaddress.ip_address("169.254.169.254").is_private
    assert ipaddress.ip_address("::1").is_reserved
    assert not allowed("http://169.254.169.254/v1")
    assert allowed("http://[::1]:1234/v1")


def test_a_refusal_explains_itself():
    """A blocked setting with no reason reads as a broken app."""
    ok, reason, _ = check_backend_url("http://169.254.169.254/v1")
    assert not ok
    assert "link-local" in reason and "metadata" in reason


@pytest.mark.parametrize("url", ["http://0.0.0.0/v1", "http://224.0.0.1/v1"])
def test_addresses_nothing_can_listen_on_are_refused(url):
    assert not allowed(url)


# --- allowed, because they are the whole point ------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "http://127.0.0.1:1234/v1",
        "http://[::1]:1234/v1",
        "http://192.168.1.20:8080/v1",   # a server on the home network
        "http://10.0.0.5:8000/v1",
        "http://172.16.3.4:8000/v1",
    ],
)
def test_local_and_lan_backends_are_normal(url):
    """This is the product. A guard that blocked these would be a guard that
    broke the only thing the setting is for."""
    ok, reason, is_local = check_backend_url(url)
    assert ok and is_local
    assert reason == ""


def test_a_name_that_does_not_resolve_yet_is_not_an_error():
    """"Set the address, then start the server" is the normal order, and a
    docker-compose service name resolves only once its container is up."""
    assert allowed("http://not-started-yet.invalid:1234/v1")


# --- allowed, and said out loud ---------------------------------------------


def test_a_backend_on_the_internet_is_allowed_but_flagged():
    """Someone who wants a hosted API is entitled to one. The app's headline
    promise is that notes stay on the machine, so this cannot be quiet."""
    ok, reason, is_local = check_backend_url("https://api.openai.com/v1")
    assert ok
    assert not is_local
    assert "sent to it over the internet" in reason


def test_the_default_backends_are_local():
    """Whatever else changes, the out-of-the-box configuration must not send
    anything anywhere."""
    from memorymap.core import deps

    for url in deps.DEFAULT_BASE_URLS.values():
        ok, _, is_local = check_backend_url(url)
        assert ok and is_local, url


# --- through the endpoint ----------------------------------------------------


def test_the_endpoint_refuses_a_metadata_address(ai_client):
    response = ai_client.post(
        "/models/provider",
        json={"provider": "openai", "base_url": "http://169.254.169.254/v1"},
    )
    assert response.status_code == 400
    assert "link-local" in response.json()["detail"]


def test_a_refused_address_is_not_saved(ai_client, app_state):
    before = app_state.get_preference("llm_base_url")
    ai_client.post(
        "/models/provider",
        json={"provider": "openai", "base_url": "file:///etc/passwd"},
    )
    assert app_state.get_preference("llm_base_url") == before


def test_the_endpoint_reports_locality(ai_client):
    body = ai_client.post(
        "/models/provider",
        json={"provider": "openai", "base_url": "http://127.0.0.1:1234/v1"},
    ).json()
    assert body["is_local"] is True
    assert body["privacy_note"] == ""


def test_an_empty_address_is_judged_by_the_default_it_will_use(ai_client):
    """Blank means "the usual one for that provider". The check has to run
    against the address that will actually be dialled, not against ""."""
    body = ai_client.post("/models/provider", json={"provider": "openai"}).json()
    assert body["is_local"] is True


def test_the_warning_persists_across_reloads(ai_client, app_state):
    """A warning that shows once when you press Connect and vanishes on the
    next reload is a warning about a condition that has not gone away. The
    status poll, which is what redraws the screen, has to carry it too.

    The lock is turned off first, and that is the point rather than test
    scaffolding: with it on this state cannot exist at all, because the remote
    address is refused before it can become the client. The warning is what
    remains for someone who deliberately unlocked.
    """
    app_state.set_preference("local_only_ai", False)
    app_state.set_preference("llm_provider", "openai")
    app_state.set_preference("llm_base_url", "https://api.openai.com/v1")
    from memorymap.core import deps

    deps.reload_llm_client()

    status = ai_client.get("/models/status").json()
    assert status["is_local"] is False
    assert "over the internet" in status["privacy_note"]


def test_a_local_backend_says_nothing_at_all(ai_client, app_state):
    """No warning fatigue: the ordinary case is silent."""
    app_state.set_preference("llm_provider", "ollama")
    app_state.set_preference("llm_base_url", "")
    from memorymap.core import deps

    deps.reload_llm_client()

    status = ai_client.get("/models/status").json()
    assert status["is_local"] is True
    assert status["privacy_note"] == ""


# --- the lock: local is enforced, not merely warned about --------------------


def test_the_lock_refuses_a_backend_on_the_internet():
    """"100% offline, on your machine" as a promise the app keeps, rather than
    one it reminds you that you are breaking."""
    ok, reason, _ = check_backend_url("https://api.openai.com/v1", local_only=True)
    assert not ok
    assert "Keep the AI on this machine" in reason


def test_the_lock_still_allows_everything_local():
    """The lock must not break the product it is protecting."""
    for url in ("http://localhost:11434", "http://192.168.1.20:1234/v1", "http://[::1]:1234/v1"):
        ok, _, is_local = check_backend_url(url, local_only=True)
        assert ok and is_local, url


def test_the_lock_refuses_a_name_it_cannot_verify():
    """Unresolvable is the safe direction under a lock: a name that does not
    resolve yet could be anything, and the whole point is not finding out the
    hard way."""
    assert not check_backend_url("http://unknown.invalid/v1", local_only=True)[0]
    # Without the lock it stays allowed, "set the address, then start the
    # server" is still the normal order.
    assert check_backend_url("http://unknown.invalid/v1", local_only=False)[0]


def test_the_lock_is_on_by_default(app_state):
    assert app_state.get_preference("local_only_ai") is True


def test_the_endpoint_refuses_a_remote_backend_while_locked(ai_client, app_state):
    app_state.set_preference("local_only_ai", True)
    response = ai_client.post(
        "/models/provider",
        json={"provider": "openai", "base_url": "https://api.openai.com/v1"},
    )
    assert response.status_code == 400
    assert "Keep the AI on this machine" in response.json()["detail"]
    # And nothing was saved.
    assert app_state.get_preference("llm_base_url") != "https://api.openai.com/v1"


def test_turning_the_lock_off_allows_it(ai_client, app_state):
    """A deliberate act with a visible switch. Someone who genuinely wants a
    hosted API is not blocked, they are asked to say so first."""
    app_state.set_preference("local_only_ai", False)
    response = ai_client.post(
        "/models/provider",
        json={"provider": "openai", "base_url": "https://api.openai.com/v1"},
    )
    assert response.status_code == 200
    assert response.json()["is_local"] is False


def test_a_hand_edited_preferences_file_cannot_bypass_the_lock(app_state):
    """`preferences.json` is a plain file, and it is what a restored backup or
    a copied config brings with it. Checking only at the endpoint would mean an
    address that never passed through it is used anyway, silently, every turn.
    """
    from memorymap.core import deps

    app_state.set_preference("local_only_ai", True)
    app_state.set_preference("llm_provider", "openai")
    app_state.set_preference("llm_base_url", "https://api.openai.com/v1")

    client = deps.build_llm_client(app_state)
    assert client.base_url == deps.DEFAULT_BASE_URLS["openai"]
    assert "api.openai.com" not in client.base_url


def test_the_app_still_starts_with_a_refused_address(app_state):
    """Falling back rather than refusing to start: the app has to open so the
    setting can be fixed from inside it."""
    from memorymap.core import deps

    app_state.set_preference("local_only_ai", True)
    app_state.set_preference("llm_base_url", "https://api.openai.com/v1")
    assert deps.build_llm_client(app_state) is not None
