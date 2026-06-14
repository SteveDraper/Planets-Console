"""Import-isolation tests for turn analytic catalog metadata."""

import subprocess
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parent.parent
_BFF_ROOT = _API_ROOT.parent / "bff"


def test_catalog_module_import_does_not_load_compute_graph():
    """BFF metadata imports should not pull Core compute modules."""
    script = """
import sys
from api.analytics.catalog import TurnAnalyticCatalogEntry, tuple_aligned_with_turn_analytic_catalog
heavy = [name for name in sys.modules if "military_score_inference" in name]
if heavy:
    raise SystemExit(f"unexpected modules: {heavy}")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_API_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_catalog_entry_resolves_without_registry_import():
    """Descriptor modules can resolve catalog_entry without eager compute imports."""
    script = """
import sys
from api.analytics.catalog import catalog_entry
heavy = [name for name in sys.modules if "military_score_inference" in name]
if heavy:
    raise SystemExit(f"unexpected modules before lookup: {heavy}")
entry = catalog_entry("scores")
if entry.id != "scores":
    raise SystemExit(f"unexpected entry: {entry!r}")
heavy = [name for name in sys.modules if "military_score_inference" in name]
if heavy:
    raise SystemExit(f"unexpected modules after lookup: {heavy}")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_API_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_bff_descriptor_import_does_not_load_compute_graph():
    """BFF analytic descriptor modules should not pull Core compute at import."""
    script = """
import sys
import bff.analytics.base_map
heavy = [name for name in sys.modules if "military_score_inference" in name]
if heavy:
    raise SystemExit(f"unexpected modules: {heavy}")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_BFF_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_bff_analytics_registry_import_does_not_load_compute_graph():
    """BFF registry alignment should use the catalog without Core compute."""
    script = """
import sys
import bff.analytics.registry
heavy = [name for name in sys.modules if "military_score_inference" in name]
if heavy:
    raise SystemExit(f"unexpected modules: {heavy}")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_BFF_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
