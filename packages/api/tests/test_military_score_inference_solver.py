"""Smoke tests for OR-Tools CP-SAT availability (military score inference dependency)."""


def test_cp_model_imports():
    from ortools.sat.python import cp_model

    assert cp_model.CpModel is not None
