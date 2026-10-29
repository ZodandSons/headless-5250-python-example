# Contributing

Thanks for helping. Bug reports with a trace are the most useful thing you can send.

## Reporting a screen that misbehaves

1. Reproduce it with the smallest script you can, run with `--trace`.
2. **Remove passwords and confidential data** from the trace: everything typed appears in it in EBCDIC hex.
3. Open an issue with the script, the trace, what you expected and what `print` showed. Include the IBM i release and terminal settings (`wide`, `codepage`).

## Development setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v
```

There are no runtime or test dependencies beyond the Python standard library, and the project aims to keep it that way so it installs anywhere, including PASE on IBM i.

## Code layout

| Path | What |
|---|---|
| `src/headless5250/session.py` | Telnet, GDS and 5250 data stream; the `Session` API |
| `src/headless5250/script.py` | Script language |
| `src/headless5250/cli.py` | `h5250` command |
| `src/headless5250/mcp_server.py` | `h5250-mcp` MCP server |
| `tests/fake_host.py` | Fake IBM i host and 5250 stream builders |
| `docs/` | User documentation |

## Adding protocol support

- Build the host's side of the exchange in a test using the helpers in `tests/fake_host.py` (`wtd`, `sba`, `sf`, `input_field`, ...), and assert on what the client sends back with `Reply.fields()`, `.aid` and `.data`.
- Cite the section of the 5250 Functions Reference or RFC you implemented in the commit message.
- Update `docs/protocol.md` when you add or change what's supported.

## Style

- Python 3.8 compatible, standard library only.
- Public API rows and columns are 1-based; internal buffer offsets are 0-based.
- Keep every user-visible error message actionable: say what was expected and where.
