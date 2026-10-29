"""The headless5250 script language: a line-oriented runner over :class:`Session`."""

import os
import re
import shlex
import sys
import time

from .session import Session

SCRIPT_HELP = """\
SCRIPT LANGUAGE  (one command per line, # comments, shell-style quoting,
${NAME} expands a variable from set/-D/capture or the environment)

  connect HOST [PORT] [tls] [insecure] [wide] [devname=X] [codepage=cp037] [timeout=S]
  disconnect
  wait [TIMEOUT]                 wait for keyboard unlock
  wait-text TEXT [TIMEOUT]       wait for TEXT on screen
  wait-gone TEXT [TIMEOUT]       wait for TEXT to disappear
  type TEXT                      type at cursor (auto-advances fields)
  put ROW COL TEXT               write into the field at ROW/COL
  field N TEXT                   replace Nth input field (1-based)
  fill-after LABEL TEXT          fill the first input field after LABEL
  cursor ROW COL | tab | backtab
  key NAME [nowait]              ENTER F1..F24 PAGEUP PAGEDOWN CLEAR HELP
                                 PRINT ATTN SYSREQ RESET (waits for unlock)
  assert TEXT | assert-not TEXT  fail the script if the check fails
  if TEXT COMMAND...             run COMMAND only if TEXT is on screen
  ifnot TEXT COMMAND...          run COMMAND only if TEXT is not on screen
  capture VAR ROW COL LEN        store screen text in ${VAR}
  set VAR VALUE | echo TEXT...
  print | fields                 show the screen / list input fields
  save FILE [append]             write the screen text to FILE
  sleep SECONDS | exit [CODE] | fail MESSAGE
"""


class ScriptError(Exception):
    pass


class ScriptExit(Exception):
    def __init__(self, code):
        self.code = code


class ScriptRunner:
    def __init__(self, variables=None, trace=False, out=sys.stdout):
        self.vars = dict(variables or {})
        self.trace, self.out, self.s = trace, out, None

    def _expand(self, line):
        def sub(m):
            name = m.group(1)
            if name in self.vars:
                return self.vars[name]
            if name in os.environ:
                return os.environ[name]
            raise ScriptError("undefined variable ${%s}" % name)
        return re.sub(r"\$\{(\w+)\}", sub, line)

    def _need(self):
        if not self.s or not self.s.sock:
            raise ScriptError("not connected (use 'connect HOST' first)")
        return self.s

    def run(self, lines):
        for no, raw in enumerate(lines, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                self.exec(shlex.split(self._expand(line)))
            except ScriptExit:
                raise
            except Exception as e:
                raise ScriptError("line %d: %s: %s" % (no, line, e)) from e

    def exec(self, t):
        cmd, a = t[0].lower(), t[1:]
        num = lambda k, d=None: float(a[k]) if len(a) > k else d
        if cmd == "connect":
            opts = {"tls": False, "verify": True, "wide": False}
            pos = []
            for x in a:
                xl = x.lower()
                if xl in ("tls", "ssl"):
                    opts["tls"] = True
                elif xl == "insecure":
                    opts["verify"] = False
                elif xl == "wide":
                    opts["wide"] = True
                elif "=" in x:
                    k, v = x.split("=", 1)
                    opts[k.lower()] = float(v) if k.lower() == "timeout" else v
                else:
                    pos.append(x)
            self.s = Session(pos[0], int(pos[1]) if len(pos) > 1 else None, trace=self.trace, **opts)
            self.s.connect()
        elif cmd == "disconnect":
            if self.s:
                self.s.close()
        elif cmd == "wait":
            self._need().wait_unlocked(num(0))
        elif cmd == "wait-text":
            self._need().wait_for_text(a[0], num(1))
        elif cmd == "wait-gone":
            self._need().wait_for_text(a[0], num(1), gone=True)
        elif cmd == "type":
            self._need().type(a[0])
        elif cmd == "put":
            self._need().put(int(a[0]), int(a[1]), a[2])
        elif cmd == "field":
            self._need().fill_field(int(a[0]), a[1])
        elif cmd == "fill-after":
            self._need().fill_after(a[0], a[1])
        elif cmd == "cursor":
            self._need().move_cursor(int(a[0]), int(a[1]))
        elif cmd in ("tab", "backtab"):
            self._need().tab(back=cmd == "backtab")
        elif cmd == "key":
            self._need().send_key(a[0], wait=not (len(a) > 1 and a[1].lower() == "nowait"))
        elif cmd == "assert":
            if not self._need().contains(a[0]):
                raise ScriptError("expected %r on screen" % a[0])
        elif cmd == "assert-not":
            if self._need().contains(a[0]):
                raise ScriptError("did not expect %r on screen" % a[0])
        elif cmd in ("if", "ifnot"):
            if self._need().contains(a[0]) == (cmd == "if"):
                self.exec(a[1:])
        elif cmd == "capture":
            self.vars[a[0]] = self._need().get_text(int(a[1]), int(a[2]), int(a[3])).strip()
        elif cmd == "set":
            self.vars[a[0]] = " ".join(a[1:])
        elif cmd == "echo":
            print(" ".join(a), file=self.out)
        elif cmd == "print":
            print(self._need().dump(), file=self.out)
        elif cmd == "fields":
            for n, r, c, ln, txt in self._need().input_fields():
                print("#%-3d row %2d col %3d len %3d  %r" % (n, r, c, ln, txt), file=self.out)
        elif cmd == "save":
            mode = "a" if len(a) > 1 and a[1].lower() == "append" else "w"
            with open(a[0], mode, encoding="utf-8") as fh:
                fh.write(self._need().text() + "\n" + ("-" * 40 + "\n" if mode == "a" else ""))
        elif cmd == "sleep":
            time.sleep(num(0, 1.0))
        elif cmd == "exit":
            raise ScriptExit(int(a[0]) if a else 0)
        elif cmd == "fail":
            raise ScriptError(" ".join(a) or "fail")
        else:
            raise ScriptError("unknown command %r" % cmd)
