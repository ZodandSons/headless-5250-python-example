# headless5250

A headless, scriptable **TN5250 client for IBM i** (AS/400, iSeries), written in pure Python with no dependencies.

It keeps the 5250 green screen in memory instead of drawing it, so you can drive it from:

- **scripts**: a small line-oriented language for sign-ons, menu navigation, data entry and screen checks
- **Python**: a `Session` class for anything a script can't express
- **AI assistants**: an MCP server, so tools such as **IBM Bob** can sign on and work green screens themselves

```text
$ h5250 examples/demo_fake_host.5250
#1   row  6 col  53 len  10  ''
#2   row  7 col  53 len  10  '**********'
Host said: CPF1120 (user required) - pressing Reset
Signed on as DEMO
24x80  cursor=21,7  ready
+--------------------------------------------------------------------------------+
| MAIN                           IBM i Main Menu                                 |  1
|                                                                                |  2
| Select one of the following:                                                   |  3
...
```

## Why

Plenty of IBM i work still only exists as a 5250 screen: vendor packages, menu-driven admin tasks, interactive programs with no API. `headless5250` lets you automate and test those screens from cron, CI or an AI assistant without a desktop emulator or screen-scraping a GUI.

## Install

Requires Python 3.8 or later. No other packages.

```bash
git clone <this repo> headless5250
cd headless5250
pip install .
```

That gives you two commands: `h5250` (run scripts) and `h5250-mcp` (the MCP server). Without installing, use `python -m headless5250` and `python -m headless5250.mcp_server` with `src` on `PYTHONPATH`.

It also runs **on the IBM i itself** in PASE with the open-source `python3` package (`yum install python3`), pointing at `localhost`.

## Quick start

### 1. Try it without an IBM i

The repo includes a small fake host with a sign-on screen and a main menu:

```bash
python tests/fake_host.py            # terminal 1: listens on 127.0.0.1:2323
PYTHONPATH=src python -m headless5250 examples/demo_fake_host.5250    # terminal 2
```

### 2. A script against a real system

```text
# signon.5250
connect ${HOST} 992 tls
wait-text "Sign On"
fill-after "User" ${USER}
fill-after "Password" ${H5250_PASSWORD}
key ENTER
if "Display Program Messages" key ENTER
assert "Main Menu"

type "WRKACTJOB"
key ENTER
wait-text "Work with Active Jobs"
save activejobs.txt
```

```bash
export H5250_PASSWORD='...'
PYTHONPATH=src py -m headless5250 examples/signon.5250 -D HOST=your.real.hostname -D USER=BOB
```

The exit code is `0` on success, `1` if a check fails (the screen at the point of failure is printed to stderr), and `2` for connection errors, so scripts drop straight into cron, Jenkins or GitHub Actions.

### 3. From Python

```python
import os
from headless5250 import Session

with Session("myibmi.example.com", tls=True) as s:
    s.wait_for_text("Sign On")
    s.fill_after("User", "BOB")
    s.fill_after("Password", os.environ["H5250_PASSWORD"])
    s.send_key("ENTER")
    s.fill_after("===>", "WRKSPLF")
    s.send_key("ENTER")
    print(s.text())
```

### 4. From IBM Bob (or any MCP client)

Add the server to Bob's `mcp.json` (`~/.bob/settings/mcp.json`, `%APPDATA%\Bob\settings\mcp.json` on Windows, or `.bob/mcp.json` in a workspace):

```json
{
  "mcpServers": {
    "h5250": {
      "command": "h5250-mcp",
      "env": {
        "H5250_ALLOWED_HOSTS": "myibmi.example.com",
        "H5250_PASSWORD": "your-password"
      }
    }
  }
}
```

Then ask Bob something like: *"Sign on to myibmi as BOB and tell me which jobs are using the most CPU in WRKACTJOB."* Bob fills the password from `H5250_PASSWORD` without ever seeing it.

## Documentation

| Guide | What's in it |
|---|---|
| [Script language](docs/script-language.md) | Every script command, variables, exit codes, patterns |
| [Python API](docs/python-api.md) | `Session` reference and examples |
| [MCP server](docs/mcp-server.md) | Setup for IBM Bob and other MCP clients, tools, security model |
| [Protocol notes](docs/protocol.md) | What parts of TN5250 are implemented, and what isn't |
| [Troubleshooting](docs/troubleshooting.md) | Tracing, timeouts, code pages, common sign-on problems |

## Examples

| File | Shows |
|---|---|
| [`examples/signon.5250`](examples/signon.5250) | Sign on, run WRKACTJOB, save the screen, sign off |
| [`examples/demo_fake_host.5250`](examples/demo_fake_host.5250) | Runs against the bundled fake host; good first try |
| [`examples/paged_report.5250`](examples/paged_report.5250) | Page through a list with PAGEDOWN until "Bottom", saving every page |
| [`examples/smoke_test.5250`](examples/smoke_test.5250) | A regression check for CI: each screen must show what it should |
| [`examples/python_api.py`](examples/python_api.py) | Python sign-on helper with error handling |
| [`examples/multi_system_check.py`](examples/multi_system_check.py) | Check several systems in parallel and print a summary |
| [`examples/bob/`](examples/bob/) | `mcp.json` for IBM Bob and sample prompts |

## Features

- TN5250 over telnet or TLS (port 992), with certificate verification on by default
- Terminal types IBM-3179-2 (24x80) and IBM-3477-FC (27x132); optional device name (`DEVNAME`)
- Write To Display and its orders, Clear Unit, Read Input / Read MDT / Read Immediate / Read Screen, Save and Restore Screen, error line messages, the 5250 Query reply
- All AID keys: Enter, F1 to F24, PageUp/PageDown, Clear, Help, Print, plus Attn, SysReq and Reset
- Field-aware typing: monocase fields, auto-advance, bypass fields, command-attention (CA) keys send no data
- Password (non-display) fields are masked in every screen dump
- Any EBCDIC code page that Python has a codec for (default `cp037`, US English)

## Limitations

- No DBCS (double-byte) code pages, and no special handling for signed-numeric or right-adjust fields
- No printer sessions (3812) and no telnet auto sign-on (`USER`/`IBMRSEED` environment variables); scripts sign on through the screen
- Tested against a simulated host and the 5250 data stream reference, not yet certified against every IBM i release. Please open an issue with a `--trace` capture if a screen misbehaves.

See [docs/protocol.md](docs/protocol.md) for details.

## Development

```bash
python -m unittest discover -s tests -v
```

The tests run against `tests/fake_host.py`, so no IBM i is needed. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
