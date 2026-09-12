#!/usr/bin/env python3
"""Cut a console-package GitHub Release: bump version, PR, tag, push tag.

Reads root ``pyproject.toml`` ``[project].version``, bumps it, opens a version PR,
waits until that PR is merged, then tags merged ``main`` and pushes the tag so
``console-package-release`` CI can build the unsigned GitHub Release assets.

Default bump is the revision (patch). ``--minor`` increments minor and resets
revision to 0. ``--major`` increments major and resets minor and revision to 0.
``--major`` and ``--minor`` together are illegal.

Also writes ``packages/frontend/src/assets/appVersion.json`` so About stays in
sync with root pyproject, then runs ``uv lock`` so ``uv.lock`` records the
same workspace root version.

Usage:
  uv run python scripts/make_release.py
  uv run python scripts/make_release.py --minor
  uv run python scripts/make_release.py --major
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVER_SRC = REPO_ROOT / "packages" / "server"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

from server.package_identity import version_from_pyproject  # noqa: E402

APP_VERSION_JSON_RELATIVE = Path("packages") / "frontend" / "src" / "assets" / "appVersion.json"
GH_PR_VIEW_JSON_FIELDS = "state,mergedAt"
PYPROJECT_RELATIVE = Path("pyproject.toml")
UV_LOCK_RELATIVE = Path("uv.lock")
RELEASE_VERSION_PATHS = (
    PYPROJECT_RELATIVE,
    APP_VERSION_JSON_RELATIVE,
    UV_LOCK_RELATIVE,
)
_VERSION_LINE = re.compile(r'^(version\s*=\s*")([^"]+)(")', re.MULTILINE)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
PromptFn = Callable[[str], str]
EchoFn = Callable[[str], None]


class ReleaseError(Exception):
    """User-facing failure while cutting a release."""


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    revision: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.revision}"


def parse_semver(raw: str) -> SemVer:
    """Parse ``major.minor.revision`` with non-negative integers and no suffix."""
    parts = raw.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(
            f"version {raw!r} must be major.minor.revision (non-negative integers, no suffix)"
        )
    return SemVer(int(parts[0]), int(parts[1]), int(parts[2]))


def bump_semver(current: SemVer, *, major: bool = False, minor: bool = False) -> SemVer:
    """Return the next version. ``major`` and ``minor`` together are illegal."""
    if major and minor:
        raise ValueError("specify at most one of --major and --minor")
    if major:
        return SemVer(current.major + 1, 0, 0)
    if minor:
        return SemVer(current.major, current.minor + 1, 0)
    return SemVer(current.major, current.minor, current.revision + 1)


def release_branch_name(version: SemVer) -> str:
    return f"release_{version}"


def release_git_tag(version: SemVer | str) -> str:
    return f"v{version}"


def replace_pyproject_version(text: str, new_version: str) -> str:
    """Replace the single ``version = "..."`` line in a pyproject document."""
    matches = list(_VERSION_LINE.finditer(text))
    if len(matches) != 1:
        raise ValueError(
            f'expected exactly one version = "..." line in pyproject.toml, found {len(matches)}'
        )
    match = matches[0]
    return text[: match.start(2)] + new_version + text[match.end(2) :]


def write_release_version_files(repo_root: Path, new_version: str) -> tuple[Path, Path]:
    """Write root pyproject and About ``appVersion.json``. Return the two paths."""
    pyproject = repo_root / PYPROJECT_RELATIVE
    app_version = repo_root / APP_VERSION_JSON_RELATIVE
    pyproject.write_text(
        replace_pyproject_version(pyproject.read_text(encoding="utf-8"), new_version),
        encoding="utf-8",
    )
    app_version.write_text(json.dumps({"version": new_version}, indent=2) + "\n", encoding="utf-8")
    return pyproject, app_version


def default_runner(
    args: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        raise ReleaseError(f"{' '.join(args)} failed: {detail}")
    return result


def _run(
    runner: CommandRunner,
    args: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return runner(list(args), cwd=cwd, check=check)


def _require_clean_tree(runner: CommandRunner, repo_root: Path) -> None:
    status = _run(runner, ["git", "status", "--porcelain"], cwd=repo_root)
    if status.stdout.strip():
        raise ReleaseError("working tree is not clean; commit or stash before cutting a release")


def _tag_exists(runner: CommandRunner, repo_root: Path, tag: str) -> bool:
    listed = _run(runner, ["git", "tag", "--list", tag], cwd=repo_root)
    return listed.stdout.strip() == tag


def _pr_is_merged(runner: CommandRunner, repo_root: Path, pr_url: str) -> bool:
    view = _run(
        runner,
        ["gh", "pr", "view", pr_url, "--json", GH_PR_VIEW_JSON_FIELDS],
        cwd=repo_root,
    )
    try:
        payload = json.loads(view.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"gh pr view did not return JSON: {view.stdout!r}") from exc
    return payload.get("state") == "MERGED" or payload.get("mergedAt") is not None


def _wait_for_merged_pr(
    runner: CommandRunner,
    repo_root: Path,
    pr_url: str,
    *,
    prompt: PromptFn,
    echo: EchoFn,
) -> None:
    echo(f"Opened {pr_url}")
    echo("Validate and merge that pull request on GitHub.")
    while True:
        prompt(f"Press Enter after {pr_url} is merged: ")
        if _pr_is_merged(runner, repo_root, pr_url):
            return
        echo("PR is not merged yet. Merge it, then press Enter.")


def cut_release(
    repo_root: Path,
    *,
    major: bool = False,
    minor: bool = False,
    runner: CommandRunner | None = None,
    prompt: PromptFn | None = None,
    echo: EchoFn | None = None,
) -> str:
    """Bump version, open a PR, wait for merge, tag ``main``, push the tag.

    Returns the new version string.
    """
    run = default_runner if runner is None else runner
    ask = input if prompt is None else prompt
    say = print if echo is None else echo
    root = repo_root.resolve()

    _require_clean_tree(run, root)
    _run(run, ["git", "fetch", "origin", "--tags"], cwd=root)
    _run(run, ["git", "checkout", "main"], cwd=root)
    _run(run, ["git", "pull", "--ff-only", "origin", "main"], cwd=root)

    current = parse_semver(version_from_pyproject(root))
    new = bump_semver(current, major=major, minor=minor)
    tag = release_git_tag(new)
    branch = release_branch_name(new)
    if _tag_exists(run, root, tag):
        raise ReleaseError(f"git tag {tag} already exists")

    _run(run, ["git", "checkout", "-b", branch], cwd=root)
    write_release_version_files(root, str(new))
    _run(run, ["uv", "lock"], cwd=root)
    _run(
        run,
        [
            "git",
            "add",
            *[path.as_posix() for path in RELEASE_VERSION_PATHS],
        ],
        cwd=root,
    )
    _run(
        run,
        ["git", "commit", "-m", f"Bump console package version to {new}."],
        cwd=root,
    )
    _run(run, ["git", "push", "-u", "origin", "HEAD"], cwd=root)
    created = _run(
        run,
        [
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--title",
            f"Bump console package version to {new}",
            "--body",
            (
                f"Bumps root `pyproject.toml`, About `appVersion.json`, and "
                f"`uv.lock` from `{current}` to `{new}`.\n\n"
                f"After this PR is merged, tag `{tag}` will be pushed so "
                f"`console-package-release` can publish GitHub Release assets.\n"
            ),
        ],
        cwd=root,
    )
    pr_url = created.stdout.strip().splitlines()[-1].strip()
    if not pr_url:
        raise ReleaseError("gh pr create did not print a pull request URL")
    _wait_for_merged_pr(run, root, pr_url, prompt=ask, echo=say)

    _run(run, ["git", "fetch", "origin", "--tags"], cwd=root)
    _run(run, ["git", "checkout", "main"], cwd=root)
    _run(run, ["git", "pull", "--ff-only", "origin", "main"], cwd=root)
    merged_version = version_from_pyproject(root)
    if merged_version != str(new):
        raise ReleaseError(
            f"main pyproject version is {merged_version!r}, expected {str(new)!r} after merge"
        )
    if _tag_exists(run, root, tag):
        raise ReleaseError(f"git tag {tag} already exists")
    _run(run, ["git", "tag", tag], cwd=root)
    _run(run, ["git", "push", "origin", tag], cwd=root)
    say(f"Pushed {tag}. Watch console-package-release for the GitHub Release assets.")
    return str(new)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bump console package version, open a release PR, then tag merged main."
    )
    parser.add_argument(
        "--major",
        action="store_true",
        help="Bump major version; reset minor and revision to 0.",
    )
    parser.add_argument(
        "--minor",
        action="store_true",
        help="Bump minor version; reset revision to 0.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Workspace root (default: parent of scripts/).",
    )
    args = parser.parse_args(argv)
    if args.major and args.minor:
        print("specify at most one of --major and --minor", file=sys.stderr)
        return 2
    try:
        cut_release(args.repo_root, major=args.major, minor=args.minor)
    except (ReleaseError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1 if isinstance(exc, ReleaseError) else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
