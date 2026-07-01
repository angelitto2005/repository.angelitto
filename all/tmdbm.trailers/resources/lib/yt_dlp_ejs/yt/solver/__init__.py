import importlib.resources
import yt_dlp_ejs.yt.solver


def core() -> str:
    """
    Read the contents of the JavaScript core solver bundle as string.
    """
    try:
        return importlib.resources.read_text(
            yt_dlp_ejs.yt.solver, "core.min.js", encoding="utf-8"
        )
    except Exception:
        return None


def lib() -> str:
    """
    Read the contents of the JavaScript library solver bundle as string.
    """
    try:
        return importlib.resources.read_text(
            yt_dlp_ejs.yt.solver, "lib.min.js", encoding="utf-8"
        )
    except Exception:
        return None
