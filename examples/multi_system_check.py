"""Check that several IBM i systems accept a sign-on, in parallel.

    export H5250_PASSWORD='...'
    python examples/multi_system_check.py MONITOR prod1.example.com prod2.example.com dev.example.com

Prints one line per system and exits 1 if any failed - handy for a cron job
or monitoring check.
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from headless5250 import Session


def check(host, user, password):
    started = time.monotonic()
    try:
        with Session(host, tls=True, timeout=30) as s:
            s.wait_for_text("Sign On")
            s.fill_after("User", user)
            s.fill_after("Password", password)
            s.send_key("ENTER")
            if s.error_message:
                return host, False, s.error_message
            if s.contains("Display Program Messages"):
                s.send_key("ENTER")
            ok = s.contains("===>")
            if ok:
                s.fill_after("===>", "SIGNOFF")
                s.send_key("ENTER", wait=False)
            return host, ok, "%.1fs" % (time.monotonic() - started) if ok else "unexpected screen"
    except Exception as e:
        return host, False, "%s: %s" % (type(e).__name__, e)


def main():
    user, hosts = sys.argv[1], sys.argv[2:]
    password = os.environ["H5250_PASSWORD"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda h: check(h, user, password), hosts))
    for host, ok, detail in results:
        print("%-4s %-30s %s" % ("OK" if ok else "FAIL", host, detail))
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)


if __name__ == "__main__":
    main()
