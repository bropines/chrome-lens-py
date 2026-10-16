"""The package must be cheap to import: the daemon client runs before anything else."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
HEAVY = ("PIL", "httpx", "google.protobuf", "rich", "filetype", "h2", "certifi")


def run_python(code: str) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.mark.parametrize("module", ["chrome_lens_py", "chrome_lens_py.client"])
def test_importing_does_not_pull_in_the_heavy_dependencies(module):
    out = run_python(
        f"import sys, {module}; " f"print([m for m in {HEAVY!r} if m in sys.modules])"
    )
    assert out == "[]"


def test_public_names_still_resolve_lazily():
    out = run_python(
        "import sys, chrome_lens_py as c; "
        "assert 'PIL' not in sys.modules; "
        "api = c.LensAPI; "
        "assert 'PIL' in sys.modules; "
        "print(api.__name__, c.LensAPIError.__name__, c.__version__)"
    )
    assert out.startswith("LensAPI LensAPIError ")


def test_from_import_and_dir_work_and_unknown_names_fail_cleanly():
    out = run_python(
        "import chrome_lens_py as c\n"
        "from chrome_lens_py import LensAPI, LensException\n"
        "assert 'LensAPI' in dir(c)\n"
        "try:\n"
        "    c.nope\n"
        "except AttributeError:\n"
        "    print('AttributeError')\n"
    )
    assert out == "AttributeError"
