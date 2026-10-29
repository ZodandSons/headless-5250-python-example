#!/usr/bin/env python3
"""
h5250-mcp - MCP (Model Context Protocol) server that lets an AI assistant such
as IBM Bob drive IBM i 5250 green screens through headless5250.

Pure Python standard library, stdio transport. Run it as ``h5250-mcp`` or
``python -m headless5250.mcp_server``.

Environment variables (set them in the MCP client's config, not in chat):
  H5250_ALLOWED_HOSTS  optional comma-separated list of hosts the assistant may
                       connect to (empty = any host)
  H5250_<anything>     secrets the assistant may type into fields by NAME via
                       `value_env`, without ever seeing the value
                       (e.g. H5250_PASSWORD)
  H5250_ALLOW_SAVE=1   let run_script use `save` to write files (off by default)
  H5250_TRACE=1        hex-dump 5250 traffic to stderr
"""

import io
import json
import os
import re
import sys
import traceback
import uuid

from . import __version__
from .script import ScriptError, ScriptExit, ScriptRunner
from .session import KeyboardLocked, Session

_PROTO_OUT = sys.stdout

SERVER_INFO = {"name": "h5250", "version": __version__}
PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
SECRET_PREFIX = "H5250_"
ALLOWED_HOSTS = {h.strip().lower() for h in os.environ.get("H5250_ALLOWED_HOSTS", "").split(",") if h.strip()}
TRACE = os.environ.get("H5250_TRACE") == "1"
ALLOW_SAVE = os.environ.get("H5250_ALLOW_SAVE") == "1"

INSTRUCTIONS = (
    "Drives IBM i (AS/400) 5250 green-screen sessions. Typical flow: connect -> read the "
    "returned screen and input-field list -> fill fields -> press_key ENTER -> read the new "
    "screen. Every action returns the current screen. Rows/columns are 1-based. For "
    "passwords use value_env (e.g. H5250_PASSWORD) instead of value, so the secret never "
    "appears in the conversation. Disconnect when finished."
)


class ToolError(Exception):
    pass


sessions = {}

# ------------------------------------------------------------------ helpers
SID = {"session_id": {"type": "string", "description": "Session id returned by connect"}}
TARGET = {
    "label": {"type": "string", "description": "Fill the first input field after this on-screen label text"},
    "field": {"type": "integer", "description": "1-based input field number (see the field list)"},
    "row": {"type": "integer"}, "col": {"type": "integer"},
    "value": {"type": "string", "description": "Text to enter"},
    "value_env": {"type": "string",
                  "description": "Name of an H5250_* environment variable whose value is entered instead of `value` (use for passwords)"},
}


def schema(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


TOOLS = [
    {"name": "connect",
     "description": "Open a 5250 session to an IBM i host and wait for the first screen (usually Sign On). Returns a session_id and the screen.",
     "inputSchema": schema({
         "host": {"type": "string"},
         "port": {"type": "integer", "description": "Default 23, or 992 with tls"},
         "tls": {"type": "boolean"},
         "insecure": {"type": "boolean", "description": "Skip TLS certificate verification"},
         "wide": {"type": "boolean", "description": "27x132 display instead of 24x80"},
         "devname": {"type": "string", "description": "Device (workstation) name to request"},
         "codepage": {"type": "string", "description": "Python EBCDIC codec, default cp037"},
         "timeout": {"type": "number", "description": "Seconds to wait for the host, default 30"}},
         ["host"])},
    {"name": "get_screen",
     "description": "Return the current screen text, cursor, keyboard state and input fields.",
     "inputSchema": schema(dict(SID), ["session_id"])},
    {"name": "fill",
     "description": "Enter text into one input field, chosen by label, field number, or row+col. Clears the rest of the field. Does not press Enter.",
     "inputSchema": schema(dict(SID, **TARGET), ["session_id"])},
    {"name": "fill_many",
     "description": "Fill several input fields at once. Each item takes the same targeting keys as `fill`. Does not press Enter.",
     "inputSchema": schema(dict(SID, items={"type": "array", "items": schema(TARGET)}), ["session_id", "items"])},
    {"name": "type_text",
     "description": "Type text at the current cursor position, auto-advancing between fields like a keyboard.",
     "inputSchema": schema(dict(SID, text={"type": "string"}), ["session_id", "text"])},
    {"name": "move_cursor",
     "description": "Move the cursor to row/col (some screens act on the cursor position, e.g. F4 prompt or option lists).",
     "inputSchema": schema(dict(SID, row={"type": "integer"}, col={"type": "integer"}), ["session_id", "row", "col"])},
    {"name": "press_key",
     "description": "Press a key and wait for the host's next screen: ENTER, F1-F24, PAGEUP, PAGEDOWN, CLEAR, HELP, PRINT, ATTN, SYSREQ, RESET (clears an error line), TAB, BACKTAB. Returns the new screen.",
     "inputSchema": schema(dict(SID, key={"type": "string"},
                                wait={"type": "boolean", "description": "Wait for the reply (default true)"},
                                timeout={"type": "number"}), ["session_id", "key"])},
    {"name": "wait_for_text",
     "description": "Wait until text appears on screen (or disappears, with gone=true) and the keyboard unlocks.",
     "inputSchema": schema(dict(SID, text={"type": "string"}, gone={"type": "boolean"},
                                timeout={"type": "number"}), ["session_id", "text"])},
    {"name": "read_text",
     "description": "Read `length` characters of screen text starting at row/col.",
     "inputSchema": schema(dict(SID, row={"type": "integer"}, col={"type": "integer"},
                                length={"type": "integer"}), ["session_id", "row", "col", "length"])},
    {"name": "run_script",
     "description": "Run a headless5250 script (one command per line: connect, wait-text, fill-after, field, put, type, key, assert, if, capture, echo, print...). If session_id is given the script runs on that open session and may omit `connect`. Returns script output and the final screen.",
     "inputSchema": schema(dict(SID, script={"type": "string"},
                                variables={"type": "object", "additionalProperties": {"type": "string"},
                                           "description": "Values for ${NAME} in the script"}), ["script"])},
    {"name": "list_sessions",
     "description": "List open sessions.",
     "inputSchema": schema({})},
    {"name": "disconnect",
     "description": "Close a session.",
     "inputSchema": schema(dict(SID), ["session_id"])},
]


def report(s, note=""):
    lines = [note] if note else []
    lines.append(s.dump())
    if s.error_message:
        lines.append("ERROR LINE: " + s.error_message)
    fields = s.input_fields()
    lines.append("Input fields:" if fields else "Input fields: (none)")
    for n, r, c, ln, txt in fields:
        lines.append("  #%d row %d col %d len %d value=%r" % (n, r, c, ln, txt))
    return "\n".join(lines)


def get_session(args):
    sid = args.get("session_id")
    s = sessions.get(sid)
    if s is None:
        raise ToolError("unknown session_id %r (open sessions: %s)" % (sid, ", ".join(sessions) or "none"))
    if s.sock is None:
        sessions.pop(sid, None)
        raise ToolError("session %s was closed by the host" % sid)
    return s


def check_host(host):
    if ALLOWED_HOSTS and host.lower() not in ALLOWED_HOSTS:
        raise ToolError("host %r is not in H5250_ALLOWED_HOSTS" % host)


def secret(name):
    if not name.startswith(SECRET_PREFIX):
        raise ToolError("value_env must name a variable starting with %s" % SECRET_PREFIX)
    if name not in os.environ:
        raise ToolError("environment variable %s is not set in the MCP server config" % name)
    return os.environ[name]


def fill_one(s, item):
    if item.get("value_env"):
        value = secret(item["value_env"])
    elif "value" in item:
        value = str(item["value"])
    else:
        raise ToolError("give `value` or `value_env`")
    if item.get("label"):
        s.fill_after(item["label"], value)
    elif item.get("field"):
        s.fill_field(int(item["field"]), value)
    elif item.get("row") and item.get("col"):
        s.put(int(item["row"]), int(item["col"]), value)
    else:
        raise ToolError("give `label`, `field`, or `row`+`col`")


class SafeRunner(ScriptRunner):
    """Script runner whose ${VARS} come only from `variables` or H5250_* env vars,
    and whose connect honours the host allow-list."""

    def _expand(self, line):
        def sub(m):
            name = m.group(1)
            if name in self.vars:
                return self.vars[name]
            if name.startswith(SECRET_PREFIX) and name in os.environ:
                return os.environ[name]
            raise ScriptError("undefined variable ${%s}" % name)
        return re.sub(r"\$\{(\w+)\}", sub, line)

    def exec(self, t):
        if t and t[0].lower() == "connect" and len(t) > 1:
            check_host(t[1])
        if t and t[0].lower() == "save" and not ALLOW_SAVE:
            raise ScriptError("`save` is disabled in the MCP server (set H5250_ALLOW_SAVE=1 to allow it)")
        return ScriptRunner.exec(self, t)


# ------------------------------------------------------------------ tools
def call_tool(name, a):
    if name == "connect":
        check_host(a["host"])
        s = Session(a["host"], a.get("port"), tls=a.get("tls", False), verify=not a.get("insecure", False),
                    devname=a.get("devname"), wide=a.get("wide", False), codepage=a.get("codepage", "cp037"),
                    timeout=a.get("timeout", 30), trace=TRACE)
        s.connect()
        sid = uuid.uuid4().hex[:8]
        sessions[sid] = s
        return report(s, "Connected. session_id=%s" % sid)

    if name == "list_sessions":
        if not sessions:
            return "No open sessions."
        return "\n".join("%s  %s:%s  %s" % (k, v.host, v.port, "open" if v.sock else "closed")
                         for k, v in sessions.items())

    if name == "run_script":
        own = a.get("session_id")
        out = io.StringIO()
        runner = SafeRunner(a.get("variables") or {}, trace=TRACE, out=out)
        if own:
            runner.s = get_session(a)
        status = "Script finished."
        try:
            runner.run(a["script"].splitlines())
        except ScriptExit as e:
            status = "Script exited with code %d." % e.code
        except ScriptError as e:
            status = "SCRIPT FAILED: %s" % e
        text = status + ("\n\nOutput:\n" + out.getvalue() if out.getvalue() else "")
        if runner.s and runner.s.sock:
            if own:
                text += "\n\n" + report(runner.s)
            else:  # keep the script's connection usable by later tool calls
                sid = uuid.uuid4().hex[:8]
                sessions[sid] = runner.s
                text += "\n\nThe script's session is still open: session_id=%s\n%s" % (sid, report(runner.s))
        if status.startswith("SCRIPT FAILED"):
            raise ToolError(text)
        return text

    s = get_session(a)
    if name == "disconnect":
        s.close()
        sessions.pop(a["session_id"], None)
        return "Disconnected %s." % a["session_id"]
    if name == "get_screen":
        return report(s)
    if name == "fill":
        fill_one(s, a)
        return report(s, "Filled (not submitted yet - press ENTER or another key).")
    if name == "fill_many":
        for item in a["items"]:
            fill_one(s, item)
        return report(s, "Filled %d fields (not submitted yet)." % len(a["items"]))
    if name == "type_text":
        s.type(a["text"])
        return report(s)
    if name == "move_cursor":
        s.move_cursor(int(a["row"]), int(a["col"]))
        return report(s)
    if name == "press_key":
        key = a["key"].upper()
        if key in ("TAB", "BACKTAB"):
            s.tab(back=key == "BACKTAB")
        else:
            s.send_key(key, wait=a.get("wait", True), timeout=a.get("timeout"))
        return report(s, "Pressed %s." % key)
    if name == "wait_for_text":
        s.wait_for_text(a["text"], a.get("timeout"), gone=a.get("gone", False))
        return report(s)
    if name == "read_text":
        return s.get_text(int(a["row"]), int(a["col"]), int(a["length"]))
    raise ToolError("unknown tool %r" % name)


def tools_call(params):
    name, args = params.get("name"), params.get("arguments") or {}
    try:
        text, err = call_tool(name, args), False
    except KeyboardLocked as e:
        text, err = "%s. Wait for the host (wait_for_text / get_screen) or press RESET if an error is shown." % e, True
    except (ToolError, ValueError, TimeoutError, ConnectionError, OSError, KeyError) as e:
        text, err = "%s: %s" % (type(e).__name__, e), True
    except Exception:
        traceback.print_exc()
        text, err = "Internal error:\n" + traceback.format_exc(limit=3), True
    if err:
        s = sessions.get(args.get("session_id"))
        if s is not None and s.sock and "Input fields" not in text:
            text += "\n\n" + report(s)
        if s is not None and s.sock is None:
            sessions.pop(args.get("session_id"), None)
    return {"content": [{"type": "text", "text": text}], "isError": err}


# ------------------------------------------------------------------ JSON-RPC
def handle(msg):
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:                       # notification
        return None
    if method == "initialize":
        want = params.get("protocolVersion")
        result = {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = tools_call(params)
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found: %s" % method}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def send(obj):
    _PROTO_OUT.write(json.dumps(obj) + "\n")
    _PROTO_OUT.flush()


def main():
    global _PROTO_OUT
    # stdout carries the protocol; anything else printed goes to stderr.
    _PROTO_OUT, sys.stdout = sys.stdout, sys.stderr
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        batch = msg if isinstance(msg, list) else [msg]
        replies = [r for r in (handle(m) for m in batch) if r is not None]
        for r in replies:
            send(r)
    for s in sessions.values():
        s.close()


if __name__ == "__main__":
    main()
