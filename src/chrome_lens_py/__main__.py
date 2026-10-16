"""Allow `python -m chrome_lens_py`, which is how the portable Windows build
runs: its python.exe is the signed one from python.org, so there is no
launcher executable of our own for antivirus heuristics to react to.

Goes through the client first, like the console script, so the portable build
gets the warm-daemon fast path too."""

from .client import entry

if __name__ == "__main__":
    entry()
