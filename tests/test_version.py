#!/usr/bin/env python3
"""The running version must match the bundle it came from."""

import app_runtime
import re
import os


def test_version_matches_pyproject_when_running_from_source():
    root = os.path.dirname(os.path.abspath(app_runtime.__file__))
    with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as fh:
        expected = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.MULTILINE).group(1)

    assert app_runtime.resolve_version() == expected
