"""The declared dependency must admit only versions whose API the server uses.

`pyproject.toml` asked for `mcp>=1.0`. The server imports

    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

and `mcp.server.mcpserver` exists only from **mcp 2.0.0**, where the class the
MCP SDK had called `FastMCP` was renamed `MCPServer`. No release in the 1.x line
ships that module at all: the subpackages under `mcp/server/` there are
`fastmcp`, `lowlevel`, `auth` and, late in the line, `experimental`.

So a resolver was free to satisfy the declaration with any 1.x, and in an
environment that already held one it did nothing whatsoever. What that produces
is not a degraded server, it is no server:

    $ pip install -e ".[dev]"   # mcp 1.28.1 already present, `mcp>=1.0` satisfied
    $ nano-mcp
    ModuleNotFoundError: No module named 'mcp.server.mcpserver'

The suite could not see it either, and that is the part worth a law. Seven of
the twenty-one test files import the server, so they failed at *collection*:
pytest reported `125 tests collected, 7 errors` where the real suite is 189, and
the 54 tests covering the payment tools, the pricing, the facilitator and the
scorecard were never run. Nothing went red. They were absent, and a count of
passing tests cannot tell the difference.

The two halves are checked separately below: that the declaration excludes the
versions that cannot work, and that every `mcp` module the production code
actually imports resolves in the installed environment. The second reads the
import statements rather than a list of names, so the next rename in this SDK is
caught by the same law.
"""

from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The release that introduced `mcp.server.mcpserver`. Read off the published
# wheels: 1.0.0 through 1.30.0 carry no such directory, 2.0.0 onwards all do.
MCPSERVER_INTRODUCED_IN = "2.0.0"

# Sampled across the whole 1.x line, including its last release, so the law does
# not pass merely because the floor moved a little way up inside 1.x.
VERSIONS_THAT_CANNOT_WORK = ("1.0.0", "1.2.0", "1.9.0", "1.15.0", "1.28.1", "1.30.0")

# The hook the installer calls, run the way tests/test_packaging.py runs it: in a
# subprocess, so reading the declaration cannot leave setuptools state behind.
_PROBE = (
    "import json;"
    "from setuptools.config.pyprojecttoml import apply_configuration;"
    "from setuptools.dist import Distribution;"
    "dist = apply_configuration(Distribution(), 'pyproject.toml');"
    "print(json.dumps(list(dist.install_requires or [])))"
)

# Production packages. Tests may import whatever they like; what ships may not.
SHIPPED = ("nano_mcp", "nano_sdk")


def _declared_requirements() -> list[str]:
    pytest.importorskip("setuptools", reason="the build backend is not installed here")
    done = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, (
        "could not read the declared dependencies from pyproject.toml:\n" + done.stderr
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


def _mcp_imports() -> list[tuple[str, str, tuple[str, ...]]]:
    """(file, module, names) for every `mcp` import in the shipped packages."""
    found: list[tuple[str, str, tuple[str, ...]]] = []
    for package in SHIPPED:
        for source in sorted((ROOT / package).rglob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    # A relative import has no module path of ours to resolve.
                    if node.level or not node.module:
                        continue
                    if node.module == "mcp" or node.module.startswith("mcp."):
                        names = tuple(alias.name for alias in node.names)
                        found.append((source.name, node.module, names))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "mcp" or alias.name.startswith("mcp."):
                            found.append((source.name, alias.name, ()))
    return found


def test_the_declared_mcp_floor_excludes_every_version_without_mcpserver():
    specifiers = pytest.importorskip(
        "packaging.specifiers", reason="packaging is not installed here"
    )
    requirements = pytest.importorskip(
        "packaging.requirements", reason="packaging is not installed here"
    )

    declared = [
        requirements.Requirement(text)
        for text in _declared_requirements()
    ]
    mcp = [req for req in declared if req.name == "mcp"]
    assert mcp, "pyproject.toml declares no dependency on mcp, but the server imports it"
    spec = specifiers.SpecifierSet(str(mcp[0].specifier))

    admitted = [v for v in VERSIONS_THAT_CANNOT_WORK if spec.contains(v)]
    assert not admitted, (
        f"`mcp{spec}` admits {admitted}, and no 1.x release ships "
        "`mcp.server.mcpserver`. An install that resolves to one of those cannot "
        f"import nano_mcp.server at all. The floor belongs at {MCPSERVER_INTRODUCED_IN}."
    )

    assert spec.contains(MCPSERVER_INTRODUCED_IN), (
        f"`mcp{spec}` excludes {MCPSERVER_INTRODUCED_IN}, the release that "
        "introduced `mcp.server.mcpserver`. That is narrower than the code needs."
    )


def test_the_shipped_code_imports_mcp_somewhere():
    """Guards the law below: it proves nothing if it finds no imports to check."""
    assert _mcp_imports(), (
        "no `mcp` import found in "
        + ", ".join(SHIPPED)
        + " - this law and the floor above are both checking nothing"
    )


@pytest.mark.parametrize("source,module,names", _mcp_imports(), ids=lambda v: str(v))
def test_every_mcp_module_the_shipped_code_imports_resolves(source, module, names):
    try:
        resolved = importlib.import_module(module)
    except ImportError as exc:  # pragma: no cover - the failure this law exists for
        pytest.fail(
            f"{source} imports `{module}`, which does not resolve against the "
            f"installed mcp: {exc}. Either the dependency floor in pyproject.toml "
            "admits a version without it, or this SDK renamed it again."
        )

    missing = [
        name
        for name in names
        if name != "*"
        and not hasattr(resolved, name)
        and not _is_importable_submodule(module, name)
    ]
    assert not missing, (
        f"{source} imports {missing} from `{module}`, which the installed mcp "
        "does not provide under those names"
    )


def _is_importable_submodule(parent: str, name: str) -> bool:
    """`from a.b import c` is legal when `c` is a submodule rather than an attribute."""
    try:
        importlib.import_module(f"{parent}.{name}")
    except ImportError:
        return False
    return True
