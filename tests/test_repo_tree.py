"""Build output must not be trackable.

`.gitignore` covered `__pycache__/`, `*.pyc`, `.venv/`, `.pytest_cache/` and
`*.egg-info/` but not `build/` or `dist/`. The repository's own documented setup
(`uv pip install -e ".[dev]"`, then `python -m build`) produces both, so a plain
`git add -A` staged a second, complete copy of the SDK:

    $ git add -A --dry-run
    add 'build/lib/nano_sdk/__init__.py'
    add 'build/lib/nano_sdk/block.py'
    add 'build/lib/nano_sdk/client.py'
    add 'build/lib/nano_sdk/crypto.py'
    add 'build/lib/nano_sdk/units.py'
    add 'build/lib/nano_sdk/wallet.py'
    add 'dist/nano_mcp-0.1.0-py3-none-any.whl'

That copy would include `wallet.py` -- the daily cap and the send path -- and it
would then age in place while `nano_sdk/` moved on. This is not hypothetical: the
sibling repository `openai-agents-nano-x402` committed exactly that, and by the
time it was found the tracked copy was missing the `is_finite()` guard that
refuses a model-supplied `"nan"` amount. A public repository carrying a second,
weaker copy of money code is worth a law rather than a habit.

These laws read git itself -- what it tracks and what it ignores -- rather than
the `.gitignore` text, because the property that matters is the behaviour, not
how the pattern is spelled.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Directories that only ever hold build output.
ARTIFACT_DIRS = ("build/", "dist/")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _require_git_checkout() -> None:
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout (installed from a distribution)")
    if _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip("git is not usable here")


def test_no_build_output_is_tracked():
    _require_git_checkout()
    tracked = _git("ls-files").stdout.split("\n")
    offenders = sorted(p for p in tracked if p.startswith(ARTIFACT_DIRS))
    assert offenders == [], (
        "these build artifacts are tracked: "
        + ", ".join(offenders)
        + ". They are a second, silently ageing copy of the SDK; remove them with "
        "`git rm --cached` and keep the directory ignored."
    )


@pytest.mark.parametrize(
    "probe",
    ["build/lib/nano_sdk/wallet.py", "dist/nano_mcp-0.1.0-py3-none-any.whl"],
)
def test_git_ignores_build_output(probe: str):
    _require_git_checkout()
    # check-ignore answers for an arbitrary path, so this holds whether or not a
    # build has run in this checkout.
    assert _git("check-ignore", probe).returncode == 0, (
        f"git does not ignore {probe!r}, so the repository's own documented "
        "install and build leave a copy of the package where `git add -A` will "
        "commit it. Add `build/` and `dist/` to .gitignore."
    )
