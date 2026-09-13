"""`paths.find_many`, the best route between two notes, then the others.

Asked for directly: "allow for multiple paths to be displayed if they exist."
These pin the three properties that make several routes worth showing at all:
they are genuinely different, they are ordered cheapest-first, and none of them
walks through the same note twice.
"""

from __future__ import annotations

from memorymap.entry import paths
from memorymap.entry.paths import Connections, Step


class FakeIndex(Connections):
    """A `Connections` built from edges directly, with no database behind it.

    `paths.build` needs Entry rows, a session and the tag/thread scan; every
    property under test here is a property of the *search*, so the graph is
    written down literally instead. Anything the search reads, `entries` for
    the membership check, `edges` for the walk: is populated.
    """

    def __init__(self, edges: list[tuple[int, int, float]]) -> None:
        nodes = {node for a, b, _ in edges for node in (a, b)}
        # The search only asks `id in entries`, never what the entry holds.
        super().__init__([])
        self.entries = dict.fromkeys(sorted(nodes), None)
        for a, b, weight in edges:
            self._add(a, b, "link", f"{a}->{b}", f"{b}->{a}", weight)


def _route(source: int, chain: list[Step]) -> list[int]:
    return [source] + [step.target for step in chain]


def test_one_route_when_that_is_all_there_is() -> None:
    index = FakeIndex([(1, 2, 1), (2, 3, 1)])
    routes = paths.find_many(index, 1, 3)
    assert [_route(1, r) for r in routes] == [[1, 2, 3]]


def test_no_route_returns_an_empty_list_not_none() -> None:
    # Callers treat "no path" and "one path" through the same branch, so this
    # must not be a None that needs its own check at every call site.
    index = FakeIndex([(1, 2, 1), (3, 4, 1)])
    assert paths.find_many(index, 1, 4) == []


def test_the_alternatives_are_ordered_cheapest_first() -> None:
    # Three ways from 1 to 5, deliberately priced apart so the ordering cannot
    # come out right by accident.
    index = FakeIndex(
        [
            (1, 2, 1), (2, 5, 1),      # cost 2, the best
            (1, 3, 2), (3, 5, 2),      # cost 4
            (1, 4, 5), (4, 5, 5),      # cost 10
        ]
    )
    routes = paths.find_many(index, 1, 5)
    assert [_route(1, r) for r in routes] == [[1, 2, 5], [1, 3, 5], [1, 4, 5]]
    costs = [sum(step.weight for step in route) for route in routes]
    assert costs == sorted(costs)


def test_it_stops_at_the_limit() -> None:
    index = FakeIndex(
        [(1, 2, 1), (2, 5, 1), (1, 3, 2), (3, 5, 2), (1, 4, 5), (4, 5, 5)]
    )
    assert len(paths.find_many(index, 1, 5, limit=2)) == 2
    assert len(paths.find_many(index, 1, 5, limit=1)) == 1


def test_every_route_is_different() -> None:
    index = FakeIndex(
        [(1, 2, 1), (2, 5, 1), (1, 3, 2), (3, 5, 2), (1, 4, 5), (4, 5, 5)]
    )
    routes = [tuple(_route(1, r)) for r in paths.find_many(index, 1, 5)]
    assert len(set(routes)) == len(routes)


def test_no_route_visits_the_same_note_twice() -> None:
    """Looplessness, which is what Yen's spur/root split buys.

    A route that walked back through a note it had already passed would read as
    nonsense in the trace readout, and a cheap-looking one is easy to build
    accidentally, because the graph is undirected and every edge can be walked
    both ways.
    """
    index = FakeIndex(
        [
            (1, 2, 1), (2, 3, 1), (3, 4, 1), (4, 5, 1),
            (2, 4, 3),   # a shortcut that a naive search could double back over
            (1, 3, 4),
        ]
    )
    for route in paths.find_many(index, 1, 5):
        visited = _route(1, route)
        assert len(visited) == len(set(visited)), visited


def test_alternatives_do_not_change_which_route_is_best() -> None:
    """`find` and `find_many`'s first entry must be the same route.

    They share `_dijkstra` precisely so they cannot disagree; if someone
    reimplements one of them, this is what says so. A UI that labels a route
    "1 of 3" while the single-path answer picks a different one is worse than
    offering no alternatives.
    """
    index = FakeIndex(
        [(1, 2, 1), (2, 5, 1), (1, 3, 2), (3, 5, 2), (1, 4, 5), (4, 5, 5)]
    )
    assert paths.find_many(index, 1, 5)[0] == paths.find(index, 1, 5)
