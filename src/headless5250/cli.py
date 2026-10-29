"""Command-line entry point: ``h5250 SCRIPT [-D VAR=VALUE] [--trace]``."""

import argparse
import sys

from . import __version__
from .script import SCRIPT_HELP, ScriptError, ScriptExit, ScriptRunner


def main(argv=None):
    ap = argparse.ArgumentParser(prog="h5250", description="Headless scriptable TN5250 client.")
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    ap.add_argument("script", nargs="?", help="script file, or - for stdin")
    ap.add_argument("-D", dest="defs", action="append", default=[], metavar="VAR=VALUE",
                    help="define a script variable (repeatable)")
    ap.add_argument("--trace", action="store_true", help="hex-dump traffic to stderr")
    ap.add_argument("--help-script", action="store_true", help="show the script language")
    args = ap.parse_args(argv)
    if args.help_script or not args.script:
        print(SCRIPT_HELP)
        return 0
    variables = dict(d.split("=", 1) for d in args.defs)
    fh = sys.stdin if args.script == "-" else open(args.script, encoding="utf-8")
    with fh:
        lines = fh.read().splitlines()
    runner = ScriptRunner(variables, trace=args.trace)
    code = 0
    try:
        runner.run(lines)
    except ScriptExit as e:
        code = e.code
    except ScriptError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        if runner.s:
            print(runner.s.dump(), file=sys.stderr)
        code = 2 if isinstance(e.__cause__, (ConnectionError, OSError)) else 1
    finally:
        if runner.s:
            runner.s.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
