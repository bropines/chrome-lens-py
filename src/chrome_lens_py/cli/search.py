"""``lens_scan search``: search the web with an image and open the results.

Imported only when the command runs: ``manage.py`` stays free of heavy imports,
and a search is network-bound anyway.
"""

import asyncio
import json
import os
import webbrowser
from typing import Optional, Tuple

from ..api import LensAPI
from ..constants import DEFAULT_CONFIG_FILENAME
from ..exceptions import LensConfigError, LensException
from ..utils.config_manager import get_default_config_dir, resolve_settings
from ..utils.general import is_url
from .main import (
    EXIT_FAILED,
    EXIT_OK,
    _api_kwargs,
    fail,
    note,
    real_path,
    setup_logging,
    write_stdout,
)


def _open(url: str) -> bool:
    """Hand the link to the user's default browser.

    It has to be that browser: the results page shows a headless or fresh one
    Google's "unusual traffic" check instead of results.
    """
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def run_search(
    image: str,
    region: Optional[Tuple[float, float, float, float]] = None,
    query: Optional[str] = None,
    ai_question: Optional[str] = None,
    ui_language: Optional[str] = None,
    open_browser: bool = True,
    as_json: bool = False,
    config_file: Optional[str] = None,
) -> int:
    path = (
        real_path(config_file)
        if config_file
        else os.path.join(get_default_config_dir(), DEFAULT_CONFIG_FILENAME)
    )
    try:
        settings = resolve_settings(None, path)
    except LensConfigError as e:
        fail(str(e), "Configuration Error")
        return EXIT_FAILED
    setup_logging(settings.logging_level)

    source = image if is_url(image) else real_path(image)
    if not is_url(image) and not os.path.isfile(source):
        fail(f"no such image: {image}")
        return EXIT_FAILED

    async def search() -> dict:
        api = LensAPI(**_api_kwargs(settings))
        try:
            return await api.search_image(
                source,
                region=region,
                mode="ai" if ai_question else "visual",
                query=ai_question or query,
                ui_language=ui_language,
            )
        finally:
            await api.aclose()

    try:
        result = asyncio.run(search())
    except LensException as e:
        fail(str(e))
        return EXIT_FAILED

    if as_json:
        write_stdout(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return EXIT_OK

    # The link on stdout, so `lens_scan search x.png --no-open` can feed
    # something else; everything about it on stderr.
    write_stdout(result["url"] + "\n")
    if open_browser:
        if _open(result["url"]):
            note("Opened in your browser. The link stays good for about half an hour.")
        else:
            note("Could not open a browser; open the link above yourself.")
    return EXIT_OK
