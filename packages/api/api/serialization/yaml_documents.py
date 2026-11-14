"""Read YAML asset documents whose root is a mapping."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml_mapping(path: Path, *, document_name: str) -> dict[str, Any]:
    """Parse ``path`` with libyaml's safe loader and return its root mapping.

    Some assets are many megabytes, and the pure-Python loader takes several
    times as long on them. ``document_name`` names the document in the error
    raised when the root is not a mapping.
    """
    with path.open(encoding="utf-8") as handle:
        document = yaml.load(handle, Loader=yaml.CSafeLoader)
    if not isinstance(document, dict):
        raise ValueError(f"{document_name} root must be a mapping: {path}")
    return document
