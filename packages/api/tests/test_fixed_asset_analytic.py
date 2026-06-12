"""Tests for fixed analytic asset path conventions."""

from api.analytics.assets import repo_root
from api.analytics.scores_assets import Scores


def test_scores_assets_dir_matches_catalog_analytic_id():
    expected = repo_root() / "assets" / "analytics" / Scores.ANALYTIC_ID
    assert Scores.assets_dir() == expected
    assert Scores.assets_dir().is_dir()
    assert (Scores.assets_dir() / "tier_policy.yaml").is_file()
