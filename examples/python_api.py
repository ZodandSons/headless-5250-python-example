"""Sign on with the Python API, run a command, and print the result.

    export H5250_PASSWORD='...'
    python examples/python_api.py myibmi.example.com BOB "DSPLIBL"
"""

import os
import sys

from headless5250 import Session


def sign_on(s, user, password):
    s.wait_for_text("Sign On")
    s.fill_after("User", user)
    s.fill_after("Password", password)
    s.send_key("ENTER")
    if s.error_message:
        raise RuntimeError("sign-on failed: " + s.error_message)
    for optional in ("Display Program Messages", "Password expires"):
        if s.contains(optional):
            s.send_key("ENTER")
    if not s.contains("===>"):
        raise RuntimeError("no command line after sign-on:\n" + s.text())


def run_command(s, command):
    """Type a CL command on the command line and return every page of output."""
    s.fill_after("===>", command)
    s.send_key("ENTER")
    if s.error_message:
        raise RuntimeError("%s: %s" % (command, s.error_message))
    pages = [s.text()]
    while "More..." in pages[-1] and len(pages) < 100:
        s.send_key("PAGEDOWN")
        pages.append(s.text())
    s.send_key("F3")
    return pages


def main():
    host, user, command = sys.argv[1], sys.argv[2], sys.argv[3]
    with Session(host, tls=True, timeout=60) as s:
        sign_on(s, user, os.environ["H5250_PASSWORD"])
        for n, page in enumerate(run_command(s, command), 1):
            print("----- page %d -----" % n)
            print(page)
        s.fill_after("===>", "SIGNOFF")
        s.send_key("ENTER", wait=False)


if __name__ == "__main__":
    main()
