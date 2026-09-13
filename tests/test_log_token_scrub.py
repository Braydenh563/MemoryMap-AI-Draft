"""The session token never reaches the access log (WORLD_CLASS_PLAN 12, S1)."""
import logging

from memorymap.core import logbuffer


def _uvicorn_record(path: str) -> logging.LogRecord:
    # The shape uvicorn.access emits: the path arrives in args, not in msg.
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:1", "GET", path, "1.1", 200), None,
    )


def test_token_query_is_redacted_in_args_and_message():
    flt = logbuffer.TokenScrubFilter()
    record = _uvicorn_record("/media/pic.png?token=abc.def-123&x=1")
    assert flt.filter(record) is True
    line = record.getMessage()
    assert "abc.def-123" not in line
    assert "token=[redacted]&x=1" in line
    plain = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                              "GET /files/1?TOKEN=zzz done", (), None)
    flt.filter(plain)
    assert "zzz" not in plain.getMessage()


def test_install_attaches_the_scrubber_once():
    logbuffer.install()
    logbuffer.install()
    access = logging.getLogger("uvicorn.access")
    assert sum(isinstance(f, logbuffer.TokenScrubFilter) for f in access.filters) == 1
