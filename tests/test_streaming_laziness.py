"""Agent and skill events must reach the browser as they happen (§35H).

Reported: "when using agent steps in the chat, the steps don't stream visually
as they are written and are instead dumped once each section of the response is
finished."

The transport was never the problem, `chat_tools_stream` yields deltas, and
the client's timeline renders them live. The problem was one line in the skill
runner. Having taken the first event off the iterator to check whether the model
supports tools at all, it put it back with `[first, *events]`, and `*` runs a
generator to exhaustion *before the list exists*. So every event for a step was
produced, buffered, and only then handed on: the step arrived complete, which is
exactly what was described.

It is worth a test rather than a comment because the broken version is the
obvious way to write the line, produces identical output, and fails only in
timing: which nothing else here would notice.
"""

from __future__ import annotations

from memorymap.ai import skill_runner


class _Recorder:
    """Notes the order in which a generator is produced and consumed.

    Laziness is not visible in the output, both versions emit the same events
    in the same order. It is only visible in the interleaving, which is why the
    fake has to record both sides.
    """

    def __init__(self) -> None:
        self.log: list[str] = []

    def source(self, items):
        for item in items:
            self.log.append(f"made:{item['type']}")
            yield item


def test_collect_does_not_run_ahead_of_its_consumer():
    """The property the fix restores: nothing is produced until it is wanted."""
    recorder = _Recorder()
    events = [{"type": "answer", "delta": "a"}, {"type": "answer", "delta": "b"}]
    stream = skill_runner._collect(recorder.source(events), [], {})

    assert recorder.log == []  # nothing made yet: the generator is untouched
    next(stream)
    assert recorder.log == ["made:answer"]  # exactly one, not both
    next(stream)
    assert recorder.log == ["made:answer", "made:answer"]


def test_putting_the_first_event_back_stays_lazy():
    """The runner peeks at the first event to see whether the model can use
    tools, then has to put it back. That reassembly is the line that broke."""
    from itertools import chain

    recorder = _Recorder()
    events = [{"type": "answer", "delta": x} for x in "abc"]
    source = recorder.source(events)
    first = next(source)
    recorder.log.clear()

    stream = skill_runner._collect(chain([first], source), [], {})
    assert next(stream) is first
    assert recorder.log == []  # the first came from the peek, nothing new made
    next(stream)
    assert recorder.log == ["made:answer"]  # one more, not the rest


def test_the_broken_form_is_what_it_looks_like():
    """Nails down *why* the obvious line is wrong, so nobody restores it: the
    unpacking exhausts the generator before a single event is handed on."""
    recorder = _Recorder()
    events = [{"type": "answer", "delta": x} for x in "abc"]
    source = recorder.source(events)

    eager = [*source]  # the shape that was in skill_runner
    assert len(recorder.log) == len(eager) == 3  # everything made, nothing consumed


def test_a_skill_run_streams_its_events(ai_client, fake_ollama, app_state):
    """End to end: the run still produces the same events in the same order, 
    laziness must not change what the user sees, only when they see it."""
    from memorymap.ai import skills
    from memorymap.core import deps

    config = deps.get_config()
    config.set_preference(
        "skills",
        [
            *skills.stored(config),
            {
                "name": "Two steps",
                "prompt": "Do the thing.",
                "steps": ["First step", "Second step"],
                "tools": ["search_notes"],
            },
        ],
    )
    fake_ollama.librarian_reply = "Done that."
    import json

    with ai_client.stream(
        "POST",
        "/chat/stream",
        json={"question": "ph:lightning Two steps", "skill": "Two steps", "use_tools": True},
    ) as response:
        events = [json.loads(line) for line in response.iter_lines() if line.strip()]

    kinds = [e["type"] for e in events]
    assert "plan" in kinds
    assert kinds.count("step") >= 4  # running + done, twice
    assert "result" in kinds


# --- the transport itself: a plain POST, not a WebSocket -----------------------


def test_the_chat_stream_is_a_plain_post_not_a_websocket(ai_client):
    """`/chat/stream` was rewritten as a WebSocket and reverted.

    Worth a guard rather than a note: the rewrite needed the request's
    SQLAlchemy Session on a second thread, had to be mounted outside the
    `locked` dependency and hand-roll its auth, and a WS handshake is not
    subject to the same-origin policy that protects this POST, so any page
    the user had open could have driven the agent. It also took ~70 tests with
    it, all reporting 405.
    """
    with ai_client.stream("POST", "/chat/stream", json={"question": "hello"}) as r:
        assert r.status_code == 200
        assert "ndjson" in r.headers["content-type"]


def test_the_frontend_streams_chat_over_fetch(request):
    from memorymap.api.app import FRONTEND_DIR

    app_js = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
    assert 'fetch("/chat/stream"' in app_js
    assert "new WebSocket(" not in app_js
