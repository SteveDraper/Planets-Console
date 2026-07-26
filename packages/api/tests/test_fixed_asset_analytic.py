"""Tests for fixed analytic asset path conventions."""

from api.analytics.assets import repo_root
from api.analytics.homeworld_locator.layout_distributions_asset import (
    LAYOUT_DISTRIBUTIONS_FILENAME,
)
from api.analytics.homeworld_locator_assets import HomeworldLocator
from api.analytics.scores_assets import Scores


def test_scores_assets_dir_matches_catalog_analytic_id():
    expected = repo_root() / "assets" / "analytics" / Scores.ANALYTIC_ID
    assert Scores.assets_dir() == expected
    assert Scores.assets_dir().is_dir()
    assert (Scores.assets_dir() / "tier_policy.yaml").is_file()


def test_homeworld_locator_assets_dir_matches_catalog_analytic_id():
    expected = repo_root() / "assets" / "analytics" / HomeworldLocator.ANALYTIC_ID
    assert HomeworldLocator.assets_dir() == expected
    assert HomeworldLocator.assets_dir().is_dir()
    assert (HomeworldLocator.assets_dir() / LAYOUT_DISTRIBUTIONS_FILENAME).is_file()
