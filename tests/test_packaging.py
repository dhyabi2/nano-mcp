"""The distribution must still be buildable.

`pip install .`, `pip install -e .` and `python -m build` all begin by asking the
build backend what it needs, and setuptools resolves the package list at that
point. Under flat-layout auto-discovery that step *fails* as soon as the
repository root holds more than one directory that looks like a package -- it
refuses rather than guessing which one is the distribution. Adding `audits/`
was enough to do it:

    error: Multiple top-level packages discovered in a flat-layout:
           ['audits', 'nano_sdk'].

Nothing in the SDK changed, and the whole test suite went on passing, because
the suite imports `nano_sdk` from the working tree. Only someone installing the
package saw it. This law runs the same backend hook the installer runs, from
the repository root, so a root directory added later cannot break installation
silently again.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The hook the installer calls first. It resolves the package list, which is the
# step that fails when discovery is ambiguous.
_PROBE = (
    "import setuptools.build_meta as backend;"
    "backend.get_requires_for_build_wheel()"
)


def test_build_backend_resolves_the_package_list():
    pytest.importorskip("setuptools", reason="the build backend is not installed here")
    done = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, (
        "the build backend refused this tree, so `pip install .` cannot work:\n"
        + done.stderr
    )


def test_the_sdk_is_the_package_that_ships():
    """Whatever the discovery settings say, they must still select nano_sdk."""
    pytest.importorskip("setuptools", reason="the build backend is not installed here")
    probe = (
        "import json;"
        "from setuptools.config.pyprojecttoml import apply_configuration;"
        "from setuptools.dist import Distribution;"
        "dist = apply_configuration(Distribution(), 'pyproject.toml');"
        "dist.set_defaults();"
        "print(json.dumps(sorted(dist.packages or [])))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    packages = set(__import__("json").loads(done.stdout))
    assert "nano_sdk" in packages, packages
    # The MCP server is the half of this distribution a directory or an agent host
    # actually starts, and the `include` list is spelled per-package: when
    # `nano_mcp/` arrived, `include = ["nano_sdk*"]` dropped it from the wheel
    # SILENTLY. Nothing went red -- the suite imports both from the working tree,
    # so only someone installing the package would find the server missing, which
    # is exactly the reader we cannot afford to lose. Named here so the next
    # package added to this repo has to be named too.
    assert "nano_mcp" in packages, packages
    assert not any(p == "audits" or p.startswith("audits.") for p in packages), packages
    assert not any(p == "tests" or p.startswith("tests.") for p in packages), packages


def test_the_server_has_a_command_an_mcp_host_can_start():
    """A registry entry names a command; `python -m nano_mcp.server` is not one.

    MCP hosts and directories are configured with an executable, so a server with
    no console script has nothing to put in that field.
    """
    pytest.importorskip("setuptools", reason="the build backend is not installed here")
    probe = (
        "import json;"
        "from setuptools.config.pyprojecttoml import apply_configuration;"
        "from setuptools.dist import Distribution;"
        "dist = apply_configuration(Distribution(), 'pyproject.toml');"
        "print(json.dumps((dist.entry_points or {}).get('console_scripts', [])))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    scripts = __import__("json").loads(done.stdout)
    assert any(line.startswith("nano-mcp =") for line in scripts), scripts
