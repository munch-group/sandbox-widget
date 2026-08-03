"""Sanity-check that the embedded frontend is at least syntactically valid JS.

Doesn't (and can't, headlessly) exercise the actual rendered output -- that
needs a real browser DOM. See CLAUDE.md's "Testing approach" for what is and
isn't covered here.
"""
import shutil
import subprocess

import pytest

from sandbox_widget import widget as widget_module


def test_esm_is_syntactically_valid_js(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH")
    esm_file = tmp_path / "sandbox_widget_esm_check.mjs"
    esm_file.write_text(widget_module._ESM)
    subprocess.run([node, "--check", str(esm_file)], check=True)
