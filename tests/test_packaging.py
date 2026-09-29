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

import re
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
    assert not any(p == "audits" or p.startswith("audits.") for p in packages), packages
    assert not any(p == "tests" or p.startswith("tests.") for p in packages), packages


# --- what the distribution makes an installer fetch -------------------------
#
# `dependencies` is not documentation: every name in it is downloaded, resolved
# against everything else in the installing environment, and installed, on every
# `pip install nano-mcp`. A name nobody imports is therefore not harmless -- it
# is weight and a resolver constraint a user pays for and cannot see the reason
# for. This law reads the declared runtime dependencies and the imports the
# shipped package actually makes, and requires the first to be covered by the
# second.

import ast
import tomllib

# Distribution name -> the module name it installs, where the two differ.
_IMPORT_NAME = {"ed25519-blake2b-fork": "ed25519_blake2b"}


def _declared_runtime_dependencies() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    names = set()
    for spec in data["project"].get("dependencies", []):
        # "httpx>=0.24" / "mcp >= 1.0" / "foo[bar]==1" -> "httpx" / "mcp" / "foo"
        name = re.split(r"[<>=!~\[; ]", spec.strip(), maxsplit=1)[0]
        if name:
            names.add(name.lower())
    return names


def _modules_imported_by_the_shipped_package() -> set[str]:
    modules = set()
    for source in sorted((ROOT / "nano_sdk").rglob("*.py")):
        tree = ast.parse(source.read_text(), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return modules


def test_every_declared_runtime_dependency_is_imported_by_the_shipped_package():
    imported = _modules_imported_by_the_shipped_package()
    unused = {
        dep
        for dep in _declared_runtime_dependencies()
        if _IMPORT_NAME.get(dep, dep.replace("-", "_")) not in imported
    }
    assert not unused, (
        "pyproject.toml makes every installer fetch these, and nothing under "
        f"nano_sdk/ imports them: {sorted(unused)}. Either the code that needs "
        "them is not in this distribution yet -- in which case the dependency "
        "belongs with it, not here -- or the declaration is stale."
    )
