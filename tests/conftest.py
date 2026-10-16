import os
import shutil
import tempfile

import pytest


@pytest.fixture
def short_tmp():
    """A temporary directory with a short path.

    AF_UNIX socket paths are capped at 104 bytes on macOS (108 on Linux), and
    pytest's tmp_path on macOS lives under /private/var/folders/..., long
    enough on its own to overflow that. Tests that need a real unix socket use
    this instead.
    """
    base = "/tmp" if os.name == "posix" and os.path.isdir("/tmp") else None
    path = tempfile.mkdtemp(prefix="cl", dir=base)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
