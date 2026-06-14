"""Test-only hand-seeded inference prior weights (not used in production)."""

from pathlib import Path

HAND_SEEDED_PRIOR_WEIGHTS_DIR = Path(__file__).resolve().parent / "hand_seeded_prior_weights"

HAND_SEEDED_STANDARD_PRIOR_PATH = HAND_SEEDED_PRIOR_WEIGHTS_DIR / "prior_weights_standard.yaml"
