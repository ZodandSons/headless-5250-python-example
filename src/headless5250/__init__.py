"""headless5250 - a headless, scriptable TN5250 client for IBM i (AS/400).

Pure Python standard library. Drive 5250 green screens from scripts, from
Python, or from an AI assistant over MCP.

    from headless5250 import Session

    with Session("myibmi", tls=True) as s:
        s.wait_for_text("Sign On")
        s.fill_after("User", "BOB")
        s.fill_after("Password", password)
        s.send_key("ENTER")
        print(s.text())
"""

__version__ = "1.0.0"

from .session import AIDS, Field, KeyboardLocked, Session  # noqa: E402
from .script import SCRIPT_HELP, ScriptError, ScriptExit, ScriptRunner  # noqa: E402

__all__ = ["Session", "Field", "KeyboardLocked", "AIDS", "ScriptRunner",
           "ScriptError", "ScriptExit", "SCRIPT_HELP", "__version__"]
