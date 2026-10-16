"""Entry point for the frozen binaries.

Nuitka was pointed at `src/chrome_lens_py/cli/main.py` directly, which builds
that file as a top-level script. Its relative imports then have no package to
resolve against, and every binary produced died on startup with
"attempted relative import with no known parent package".

A module outside the package, importing it absolutely, gives Nuitka something it
can build. Not used when running from source, where the console script entry
point in pyproject.toml does the same job.

Goes through the thin client first (stdlib only), which hands the command to a
warm daemon when there is one and otherwise imports the real CLI.
"""

from chrome_lens_py.client import entry

if __name__ == "__main__":
    entry()
