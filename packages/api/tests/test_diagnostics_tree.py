"""Diagnostic tree model."""

from api.diagnostics import DiagnosticNode, JSONValue, request_root_node, timed_section


def test_diagnostic_node_round_trip_dict():
    n = DiagnosticNode(name="f")
    n.values["k"] = 1
    n.timings["t"] = 0.5
    c = n.child("g")
    c.values["x"] = "y"
    d = n.to_dict()
    assert d["name"] == "f"
    assert d["values"]["k"] == 1
    assert d["timings"]["t"] == 0.5
    assert len(d["children"]) == 1
    assert d["children"][0]["name"] == "g"


def test_request_root_node():
    r = request_root_node("GET", "/x/a", gameId=1, flag=True)
    assert r.name == "GET /x/a"
    assert r.values["gameId"] == 1
    assert r.values["flag"] is True


def test_timed_section_sets_timing():
    n = DiagnosticNode(name="n")
    with timed_section(n, "block"):
        pass
    assert "block" in n.timings
    assert n.timings["block"] >= 0.0


def test_values_allow_nested_json_structures():
    """``values`` are JSONValue (e.g. list of small dicts), not only scalars."""
    n = DiagnosticNode(name="with_detail")
    nested: JSONValue = [
        {"a": 1, "b": 2.0},
        {"a": 2, "b": 3.0, "c": True},
    ]
    n.values["latticeBuilds"] = nested
    d = n.to_dict()
    assert d["values"]["latticeBuilds"] == nested
