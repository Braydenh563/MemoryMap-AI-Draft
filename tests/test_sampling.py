"""Advanced response parameters, and detecting the right ones per model.

Asked for directly: expose top-k, top-p, repeat penalty and the rest, "because
different models require different parameters to get the same result", and
detect them per model if that is possible.

It is, and without a hand-maintained table: a GGUF ships its author's
recommended parameters, Ollama reports them in `/api/show`, and this app was
already fetching and caching that payload while dropping that one field.
"""

from __future__ import annotations

import pytest

from memorymap.ai import sampling
from memorymap.ai.ollama_client import OllamaClient


@pytest.fixture()
def ollama():
    client = OllamaClient(base_url="http://127.0.0.1:1")
    client._context_lengths = {"m": 8192}
    return client

QWEN_SHOW = {
    "parameters": (
        'stop                           "<|im_end|>"\n'
        "temperature                    0.6\n"
        "top_p                          0.95\n"
        "top_k                          20\n"
        "repeat_penalty                 1.05\n"
        "mirostat                       2\n"
    )
}


# --- reading what the model actually recommends --------------------------------


def test_a_models_own_parameters_are_read_rather_than_guessed():
    assert sampling.parse_model_parameters(QWEN_SHOW) == {
        "temperature": 0.6, "top_p": 0.95, "top_k": 20, "repeat_penalty": 1.05,
    }


def test_string_parameters_never_reach_an_options_block():
    """`stop` is a list of sequences, not a sampling knob. Letting it through
    would put a quoted string where a number belongs."""
    assert "stop" not in sampling.parse_model_parameters(QWEN_SHOW)


def test_knobs_this_app_does_not_offer_are_ignored():
    """mirostat is real and is deliberately not offered, fourteen sliders is
    not help for someone whose model is repeating itself."""
    assert "mirostat" not in sampling.parse_model_parameters(QWEN_SHOW)


def test_an_integer_knob_stays_an_integer():
    parsed = sampling.parse_model_parameters(QWEN_SHOW)
    assert isinstance(parsed["top_k"], int)


def test_a_recommendation_outside_the_offered_range_is_clamped_not_dropped():
    """Still better information than the backend default, and the slider must
    not disagree with what is actually sent."""
    parsed = sampling.parse_model_parameters({"parameters": "temperature 9.0"})
    assert parsed["temperature"] == sampling.KNOBS_BY_NAME["temperature"].maximum


def test_a_backend_that_reports_nothing_is_not_an_error():
    """A model with no recommendations, a backend that does not report them,
    and a malformed payload all mean "use the defaults"."""
    for payload in ({}, {"parameters": None}, {"parameters": ""}, {"parameters": "@@@"}):
        assert sampling.parse_model_parameters(payload) == {}


# --- the order between the four sources ----------------------------------------


def test_nothing_set_anywhere_sends_nothing():
    """Absent means "the backend's own default". A key set to null would be an
    instruction to use nothing, which some backends reject and others read as
    zero."""
    assert sampling.resolve() == {}


def test_the_user_beats_the_task_which_beats_the_model():
    model = sampling.parse_model_parameters(QWEN_SHOW)
    got = sampling.resolve(model, {"temperature": 0.2}, {"top_k": 40})
    assert got["temperature"] == 0.2   # the task preset
    assert got["top_k"] == 40          # the user
    assert got["top_p"] == 0.95        # untouched: still the model's own
    assert got["repeat_penalty"] == 1.05


def test_an_override_for_one_knob_leaves_the_others_to_the_model():
    """The reason overrides are stored sparsely: a full set written on first
    open would pin one model's recommendations onto every other model."""
    model = sampling.parse_model_parameters(QWEN_SHOW)
    got = sampling.resolve(model, None, {"temperature": 1.4})
    assert got == {**model, "temperature": 1.4}


def test_where_each_value_came_from_is_reportable():
    model = sampling.parse_model_parameters(QWEN_SHOW)
    assert sampling.explain(model, {"temperature": 0.2}, {"top_k": 40}) == {
        "temperature": "task", "top_p": "model", "top_k": "you", "repeat_penalty": "model",
    }


def test_a_hand_edited_preference_file_cannot_break_a_request():
    assert sampling.resolve(None, None, {"temperature": "hot", "top_k": None}) == {}
    assert sampling.resolve(None, None, {"nonsense": 5}) == {}


# --- the two dialects ----------------------------------------------------------


def test_the_ollama_dialect_sends_the_models_own_parameters(ollama):
    ollama._shown = {"m": QWEN_SHOW}
    options = ollama.runtime_options("m")
    assert options["top_p"] == 0.95
    assert options["repeat_penalty"] == 1.05


def test_a_user_override_reaches_the_request(ollama, app_state):
    ollama._shown = {"m": QWEN_SHOW}
    app_state.set_preference("sampling_overrides", {"top_k": 7})
    assert ollama.runtime_options("m")["top_k"] == 7


def test_the_openai_dialect_only_sends_what_that_schema_defines(openai_client, app_state):
    """top_k, min_p and repeat_penalty are llama.cpp/Ollama names. A server
    that validates strictly rejects the whole request for one unknown field, so
    sending them would break every turn against the backends this dialect
    exists for."""
    openai_client._context_lengths = {"m": 8192}
    app_state.set_preference(
        "sampling_overrides", {"top_p": 0.8, "top_k": 20, "repeat_penalty": 1.2}
    )
    options = openai_client.runtime_options("m")
    assert options["top_p"] == 0.8
    assert "top_k" not in options
    assert "repeat_penalty" not in options


# --- the settings surface ------------------------------------------------------


def test_the_knob_catalogue_is_served_so_the_ui_has_one_source(client):
    body = client.get("/models/sampling").json()
    names = [k["name"] for k in body["knobs"]]
    assert "repeat_penalty" in names
    for knob in body["knobs"]:
        assert knob["min"] < knob["max"]
        assert knob["help"]


def test_saving_and_clearing_overrides(client):
    client.put("/models/sampling", json={"overrides": {"top_k": 33}})
    assert client.get("/models/sampling").json()["overrides"] == {"top_k": 33}
    # Clearing is expressed as having no override, not as a separate reset.
    client.put("/models/sampling", json={"overrides": {}})
    assert client.get("/models/sampling").json()["overrides"] == {}


def test_an_unknown_knob_is_refused_at_the_boundary(client):
    client.put("/models/sampling", json={"overrides": {"rm_rf": 1, "top_p": 0.5}})
    assert client.get("/models/sampling").json()["overrides"] == {"top_p": 0.5}
