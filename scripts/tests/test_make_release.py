"""Console package version bump, release PR, and tag push."""

from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import make_release as release
import pytest
from server.package_identity import version_from_pyproject


def test_parse_semver_requires_major_minor_revision():
    assert release.parse_semver("0.1.0") == release.SemVer(0, 1, 0)
    assert release.parse_semver("1.2.3") == release.SemVer(1, 2, 3)
    with pytest.raises(ValueError, match="major.minor.revision"):
        release.parse_semver("0.1")
    with pytest.raises(ValueError, match="major.minor.revision"):
        release.parse_semver("v0.1.0")
    with pytest.raises(ValueError, match="major.minor.revision"):
        release.parse_semver("0.1.0-rc1")


def test_bump_revision_by_default():
    assert release.bump_semver(release.SemVer(0, 1, 0)) == release.SemVer(0, 1, 1)
    assert release.bump_semver(release.SemVer(2, 3, 9)) == release.SemVer(2, 3, 10)


def test_bump_minor_resets_revision():
    assert release.bump_semver(release.SemVer(0, 1, 7), minor=True) == release.SemVer(0, 2, 0)


def test_bump_major_resets_minor_and_revision():
    assert release.bump_semver(release.SemVer(0, 9, 4), major=True) == release.SemVer(1, 0, 0)


def test_bump_rejects_major_and_minor_together():
    with pytest.raises(ValueError, match="at most one"):
        release.bump_semver(release.SemVer(0, 1, 0), major=True, minor=True)


def test_release_branch_and_tag_names():
    version = release.SemVer(0, 1, 1)
    assert release.release_branch_name(version) == "release_0.1.1"
    assert release.release_git_tag(version) == "v0.1.1"


def test_replace_pyproject_version_rewrites_the_single_project_version():
    text = '[project]\nname = "planets-console"\nversion = "0.1.0"\n'
    updated = release.replace_pyproject_version(text, "0.1.1")
    assert 'version = "0.1.1"' in updated
    assert 'version = "0.1.0"' not in updated


def test_replace_pyproject_version_rejects_missing_or_multiple_lines():
    with pytest.raises(ValueError, match="version"):
        release.replace_pyproject_version('[project]\nname = "x"\n', "0.1.1")
    with pytest.raises(ValueError, match="version"):
        release.replace_pyproject_version('version = "0.1.0"\nversion = "0.2.0"\n', "0.1.1")


def test_write_release_version_files_updates_pyproject_and_app_version(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    app_version = tmp_path / "packages" / "frontend" / "src" / "assets" / "appVersion.json"
    pyproject.write_text(_PYPROJECT_010, encoding="utf-8")
    app_version.parent.mkdir(parents=True)
    app_version.write_text('{\n  "version": "0.1.0"\n}\n', encoding="utf-8")
    release.write_release_version_files(tmp_path, "0.1.1")
    assert version_from_pyproject(tmp_path) == "0.1.1"
    assert json.loads(app_version.read_text(encoding="utf-8")) == {"version": "0.1.1"}


def test_main_rejects_major_and_minor_together(capsys):
    assert release.main(["--major", "--minor"]) == 2
    err = capsys.readouterr().err
    assert "--major" in err
    assert "--minor" in err


class _MatchingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._handlers: list[tuple[object, object]] = []

    def when(self, predicate, result) -> None:
        self._handlers.append((predicate, result))

    def __call__(self, args: list[str], **_kwargs) -> CompletedProcess[str]:
        self.calls.append(list(args))
        for predicate, result in self._handlers:
            if predicate(args):
                proc = result(args) if callable(result) else result
                return proc
        return CompletedProcess(args, 0, stdout="", stderr="")


def _ok(stdout: str = "", returncode: int = 0) -> CompletedProcess[str]:
    return CompletedProcess(["ignored"], returncode, stdout=stdout, stderr="")


def _merged_pr_json(*, merged: bool) -> CompletedProcess[str]:
    state = "MERGED" if merged else "OPEN"
    return _ok(json.dumps({"merged": merged, "state": state}))


_PYPROJECT_010 = '[project]\nname = "planets-console"\nversion = "0.1.0"\n'


def _cmd_starts(*parts: str):
    def predicate(args: list[str]) -> bool:
        return args[: len(parts)] == list(parts)

    return predicate


def _seed_version_repo(tmp_path: Path, version: str = "0.1.0") -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "planets-console"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    app_version = tmp_path / "packages" / "frontend" / "src" / "assets" / "appVersion.json"
    app_version.parent.mkdir(parents=True, exist_ok=True)
    app_version.write_text(f'{{\n  "version": "{version}"\n}}\n', encoding="utf-8")


def test_cut_release_bumps_revision_opens_pr_waits_then_tags(tmp_path):
    _seed_version_repo(tmp_path)
    runner = _MatchingRunner()
    runner.when(_cmd_starts("git", "status"), _ok(""))
    runner.when(_cmd_starts("git", "tag", "--list"), _ok(""))
    runner.when(
        _cmd_starts("gh", "pr", "create"),
        _ok("https://github.com/SteveDraper/Planets-Console/pull/99\n"),
    )
    pr_checks = {"n": 0}

    def pr_view(_args: list[str]) -> CompletedProcess[str]:
        pr_checks["n"] += 1
        merged = pr_checks["n"] >= 2
        body = json.dumps({"merged": merged, "state": "MERGED" if merged else "OPEN"})
        return _ok(body)

    runner.when(_cmd_starts("gh", "pr", "view"), pr_view)
    prompts: list[str] = []

    def prompt(message: str) -> str:
        prompts.append(message)
        return ""

    release.cut_release(tmp_path, runner=runner, prompt=prompt)
    assert version_from_pyproject(tmp_path) == "0.1.1"
    app_path = tmp_path / "packages" / "frontend" / "src" / "assets" / "appVersion.json"
    assert json.loads(app_path.read_text(encoding="utf-8"))["version"] == "0.1.1"
    commands = [" ".join(c) for c in runner.calls]
    assert "git checkout -b release_0.1.1" in commands
    assert any(c.startswith("gh pr create") for c in commands)
    assert "git tag v0.1.1" in commands
    assert "git push origin v0.1.1" in commands
    assert pr_checks["n"] == 2
    assert len(prompts) == 2
    assert "https://github.com/SteveDraper/Planets-Console/pull/99" in prompts[0]


def test_cut_release_minor_and_major_branch_names(tmp_path):
    _seed_version_repo(tmp_path, "1.4.8")
    runner = _MatchingRunner()
    runner.when(_cmd_starts("git", "status"), _ok(""))
    runner.when(_cmd_starts("git", "tag", "--list"), _ok(""))
    runner.when(_cmd_starts("gh", "pr", "create"), _ok("https://example.test/pull/1\n"))
    runner.when(_cmd_starts("gh", "pr", "view"), _merged_pr_json(merged=True))
    release.cut_release(tmp_path, minor=True, runner=runner, prompt=lambda _m: "")
    assert "git checkout -b release_1.5.0" in {" ".join(c) for c in runner.calls}
    assert "git tag v1.5.0" in {" ".join(c) for c in runner.calls}

    _seed_version_repo(tmp_path, "1.4.8")
    runner = _MatchingRunner()
    runner.when(_cmd_starts("git", "status"), _ok(""))
    runner.when(_cmd_starts("git", "tag", "--list"), _ok(""))
    runner.when(_cmd_starts("gh", "pr", "create"), _ok("https://example.test/pull/2\n"))
    runner.when(_cmd_starts("gh", "pr", "view"), _merged_pr_json(merged=True))
    release.cut_release(tmp_path, major=True, runner=runner, prompt=lambda _m: "")
    assert "git checkout -b release_2.0.0" in {" ".join(c) for c in runner.calls}
    assert "git tag v2.0.0" in {" ".join(c) for c in runner.calls}


def test_cut_release_refuses_dirty_tree(tmp_path):
    _seed_version_repo(tmp_path)
    runner = _MatchingRunner()
    runner.when(_cmd_starts("git", "status"), _ok(" M pyproject.toml\n"))
    with pytest.raises(release.ReleaseError, match="working tree"):
        release.cut_release(tmp_path, runner=runner, prompt=lambda _m: "")


def test_cut_release_refuses_existing_tag(tmp_path):
    _seed_version_repo(tmp_path)
    runner = _MatchingRunner()
    runner.when(_cmd_starts("git", "status"), _ok(""))
    runner.when(_cmd_starts("git", "tag", "--list"), _ok("v0.1.1\n"))
    with pytest.raises(release.ReleaseError, match="already exists"):
        release.cut_release(tmp_path, runner=runner, prompt=lambda _m: "")
