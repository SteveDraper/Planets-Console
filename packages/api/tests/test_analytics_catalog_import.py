"""Import-isolation tests for turn analytic catalog metadata."""

import subprocess
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parent.parent


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


def test_bff_catalog_entry_import_does_not_load_compute_graph():
    """Descriptor modules can resolve catalog_entry without eager compute imports."""
    script = """
import sys
from api.analytics.catalog import catalog_entry
heavy = [name for name in sys.modules if "military_score_inference" in name]
if heavy:
    raise SystemExit(f"unexpected modules before registry: {heavy}")
import api.analytics.registry  # publishes catalog; compute graph loads here by design
catalog_entry("scores")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_API_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
