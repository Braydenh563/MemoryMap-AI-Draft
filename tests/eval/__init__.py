"""The in-repo eval harness (PLAN.md §4, item A6).

Thirty golden asks over a fixture notebook, scored on the two things a
notebook agent can be wrong about in a way a user notices:

- **tool choice**: was the tool that answers this ask even offered? and was
  a destructive one offered when it should not have been?
- **citation correctness**: when that tool runs, does it come back naming the
  note, document or file the ask was about?

`golden.py` is the set, `fixture.py` builds the notebook, `scoring.py` scores
one case, and `test_eval_harness.py` is the CI run against the fake transport.
`scripts/eval.py` (or `make eval`) is the same set against a real local model.
"""
