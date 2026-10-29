# Troubleshooting

## First step: look at the screen

Add `print` and `fields` to a script, or call `s.dump()` / `s.input_fields()` in Python. On failure, `h5250` already prints the screen to stderr.

For protocol-level problems add `--trace` (scripts), `trace=True` (Python) or `H5250_TRACE=1` (MCP). Every byte sent (`>>`) and received (`<<`) is hex-dumped to stderr. **Traces contain everything typed, including passwords**; scrub them before sharing.

## Connecting

| Symptom | Likely cause |
|---|---|
| `ConnectionRefusedError` | Telnet server not started (`STRTCPSVR *TELNET`), wrong port, or a firewall. Plain telnet is 23, TLS is 992. |
| `ssl.SSLCertVerificationError` | The system's certificate isn't trusted by your machine. Install the CA, or use `insecure` for test systems only. |
| `TimeoutError` right after connect | No sign-on screen arrived. Check the device: with `devname=`, the name may be in use or the user may lack authority to it. Check `QAUTOVRT` if devices aren't being created. |
| `connection closed by host` | The system ended the session: device already in use, sign-on attempts exceeded (`QMAXSIGN`), or the job ended. |

## Waiting and timing

| Symptom | Fix |
|---|---|
| A step times out on a slow program | Add a timeout: `wait-text "Done" 120`, `connect ... timeout=120`, or `Session(timeout=120)`. |
| Script reads a half-drawn screen | Raise `settle` (`Session(settle=1.0)`), or use `wait-text` for something that appears last. |
| `keyboard is locked` | The host hasn't finished. Use `wait` / `wait-text`, or `key RESET` if there's an error message. |
| Script works interactively but not in cron | Environment variables (password) not set in cron's environment; a different code page; a different library list for the user. |

## Typing

| Symptom | Fix |
|---|---|
| `row R col C is not in an input field` | Run `fields` to see where the fields really are. Coordinates are 1-based and point at the data, not the attribute byte before it. |
| `text is longer than the N-char field` | The field is shorter than you thought; check `fields`. |
| `label 'X' not on screen` | Labels are matched exactly, including case and spacing. Use a shorter, unique piece of the label. |
| Wrong field filled by `fill-after` | It takes the first input field after the label text in screen order (left to right, top to bottom). Use `field N` or `put` instead. |

## Characters look wrong

The default code page is `cp037` (US/Canada). Pick the one matching the system's `QCCSID` / job CCSID:

| CCSID | Codec |
|---|---|
| 37 | `cp037` |
| 273 (Germany/Austria) | `cp273` |
| 277 (Denmark/Norway) | `cp277` |
| 278 (Finland/Sweden) | `cp278` |
| 280 (Italy) | `cp280` |
| 284 (Spain) | `cp284` |
| 285 (UK) | `cp285` |
| 297 (France) | `cp297` |
| 500 (International) | `cp500` |

## Sign-on problems

- **Password expired / must change.** The script lands on "Change Password". Handle it with `if "Change Password" fail ...` or change it interactively first.
- **"Display Program Messages" after sign-on.** Press Enter: `if "Display Program Messages" key ENTER`.
- **Initial program or menu.** Users with an initial program don't see the main menu. Assert on whatever their first screen shows.
- **Sign-on screen labels differ.** Customised `QDSIGNON` displays may use other labels. Use `field 1` / `field 2` instead of `fill-after`.

## MCP server

- **Server not listed or not connected in Bob.** Run the configured command yourself (`h5250-mcp`) in a terminal: it should wait silently for input. If it's "command not found", use the full path or the `python -m` form from [mcp-server.md](mcp-server.md).
- **`host ... is not in H5250_ALLOWED_HOSTS`.** The host name must match exactly as the assistant passes it (name vs IP).
- **`environment variable H5250_X is not set`.** Add it to the server's `env` block and restart the client; servers don't see variables added later.
