"""Single source of truth for the version.

Kept in its own module with no imports so that setuptools can read it
statically (it parses the AST rather than importing), and so a frozen build
carries the version in code rather than depending on dist-info metadata
being bundled.
"""

__version__ = "3.5.2"
