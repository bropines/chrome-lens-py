import logging
import platform

logger = logging.getLogger(__name__)


def copy_to_clipboard(text: str) -> bool:
    """Copies the provided text to the clipboard."""
    system = platform.system()
    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        logger.info("Text copied to clipboard.")
        return True
    except ImportError:
        logger.error(
            "Module 'pyperclip' not found. Please install it to use clipboard functionality (pip install 'chrome-lens-py[clipboard]')."
        )
        if system == "Linux":
            logger.info(
                "On Linux, you might also need to install xclip or xsel: sudo apt-get install xclip (or xsel)"
            )
        return False
    except Exception as e:
        logger.error(f"Failed to copy text to clipboard: {e}")
        return False
