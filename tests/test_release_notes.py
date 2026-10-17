import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "release_notes", ROOT / "scripts" / "release_notes.py"
)
rn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rn)

CHANGELOG = """# Changelog

## [Unreleased]

## [2.0.0] - 2026-01-02

### Highlights

- Big thing.

### Features

- Small thing.

### Bug Fixes

- A fix.

## [1.0.0] - 2026-01-01

### Bug Fixes

- First fix.

[2.0.0]: https://example.com/compare
"""


def test_install_comes_first_and_the_version_is_filled_in():
    notes = rn.build("2.0.0", CHANGELOG)
    assert notes.index("## Install") < notes.index("## What's new in 2.0.0")
    assert notes.index("## What's new") < notes.index("## Which file do I need?")
    assert "@VERSION@" not in notes and "chrome-lens-py:2.0.0" in notes


def test_highlights_are_shown_and_the_rest_folded():
    notes = rn.build("2.0.0", CHANGELOG)
    new = notes[notes.index("## What's new") : notes.index("## Which file")]
    assert "- Big thing." in new.split("<details>")[0]
    assert "### Highlights" not in new  # the heading under "What's new" is noise
    folded = new.split("<summary>All changes</summary>")[1]
    assert "- Small thing." in folded and "- A fix." in folded


def test_a_short_section_without_highlights_is_shown_whole():
    notes = rn.build("1.0.0", CHANGELOG)
    assert "- First fix." in notes and "All changes" not in notes
    assert "[2.0.0]: https" not in notes  # link references are not part of it


def test_a_missing_version_is_reported_so_the_workflow_can_fall_back():
    assert rn.build("9.9.9", CHANGELOG) is None


def test_the_real_changelog_has_notes_for_the_current_version():
    from chrome_lens_py import __version__

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert rn.build(__version__, changelog) is not None
