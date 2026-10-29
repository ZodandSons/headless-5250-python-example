# Script language

A script is a plain text file, one command per line. Run it with:

```bash
h5250 SCRIPT [-D NAME=VALUE ...] [--trace]
h5250 -                    # read the script from stdin
h5250 --help-script        # print the command summary
```

## Syntax

- One command per line. Blank lines and lines starting with `#` are ignored.
- Arguments are split like a shell: use `"double"` or `'single'` quotes for text with spaces.
- `${NAME}` is replaced by a variable. Variables come from, in order: `set` / `capture` / `-D NAME=VALUE`, then the environment. An undefined variable stops the script with an error.
- Rows and columns are **1-based**, matching what you see on a 5250 display.
- Every key that talks to the host (`key ENTER`, `key F3`...) waits for the host to answer and unlock the keyboard before the next line runs, so you rarely need `wait` or `sleep`.

## Commands

### Connecting

| Command | Description |
|---|---|
| `connect HOST [PORT] [options]` | Open a session and wait for the first screen. `PORT` defaults to 23, or 992 with `tls`. |
| `disconnect` | Close the session (also happens automatically at the end). |

`connect` options, in any order after the host:

| Option | Meaning |
|---|---|
| `tls` | Use TLS (SSL). Usually with port 992. |
| `insecure` | Don't verify the TLS certificate (self-signed test systems). |
| `wide` | Request a 27x132 display (IBM-3477-FC) instead of 24x80. |
| `devname=NAME` | Ask for a specific workstation device name. |
| `codepage=cp037` | EBCDIC code page as a Python codec name, e.g. `cp273` (German), `cp500` (international), `cp285` (UK). |
| `timeout=30` | Seconds to wait for the host on each step. |

### Waiting

| Command | Description |
|---|---|
| `wait [TIMEOUT]` | Wait until the keyboard is unlocked. |
| `wait-text TEXT [TIMEOUT]` | Wait until `TEXT` is on screen and the keyboard is unlocked. |
| `wait-gone TEXT [TIMEOUT]` | Wait until `TEXT` has disappeared. |
| `sleep SECONDS` | Pause. Prefer `wait-text`. |

### Entering data

| Command | Description |
|---|---|
| `fill-after LABEL TEXT` | Fill the first input field after the on-screen text `LABEL`. The most robust choice. |
| `field N TEXT` | Replace the contents of the Nth input field (1-based, top-left to bottom-right). Use `fields` to see numbers. |
| `put ROW COL TEXT` | Write into the input field at ROW/COL, clearing the rest of that field. |
| `type TEXT` | Type at the cursor like a keyboard, moving to the next field when one fills. |
| `cursor ROW COL` | Move the cursor (matters for F4 prompting and option lists). |
| `tab` / `backtab` | Move to the next / previous input field. |

Text is upper-cased automatically in monocase fields, as a real terminal would. Typing into a protected area is an error.

### Keys

```text
key NAME [nowait]
```

`NAME` is one of: `ENTER`, `F1` to `F24`, `PAGEUP` (`ROLLDOWN`), `PAGEDOWN` (`ROLLUP`), `CLEAR`, `HELP`, `PRINT`, `ATTN`, `SYSREQ`, `RESET`.

- The key is sent and the script waits for the host's reply. Add `nowait` when no reply is expected, e.g. after `SIGNOFF`.
- `RESET` clears an error message from the bottom line, like the Reset key. Sending any other key also clears it.

### Checking the screen

| Command | Description |
|---|---|
| `assert TEXT` | Stop with an error unless `TEXT` is on screen. |
| `assert-not TEXT` | Stop with an error if `TEXT` is on screen. |
| `if TEXT COMMAND...` | Run `COMMAND` only if `TEXT` is on screen. |
| `ifnot TEXT COMMAND...` | Run `COMMAND` only if `TEXT` is not on screen. |
| `fail MESSAGE` | Stop with an error. Useful after `if`/`ifnot`. |
| `exit [CODE]` | Stop the script with an exit code (default 0). |

### Output

| Command | Description |
|---|---|
| `capture VAR ROW COL LENGTH` | Store screen text (trimmed) in `${VAR}`. |
| `set VAR VALUE...` | Set a variable. |
| `echo TEXT...` | Print a line to stdout. |
| `print` | Print the screen with a border, cursor position and keyboard state. |
| `fields` | List the input fields: number, row, column, length, current value. |
| `save FILE [append]` | Write the screen text to a file. `append` adds it with a separator line. |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Script finished (or `exit` with no code) |
| 1 | A command failed: `assert`, `fail`, a timeout, typing outside a field... |
| 2 | Connection error: host unreachable, TLS failure, connection dropped |
| N | `exit N` |

On failure the line number, the reason and the current screen go to stderr.

## Patterns

**Writing a new script.** Start with `connect`, `print` and `fields`, run it, then add one step at a time:

```text
connect myibmi
print
fields
```

**Optional screens.** Sign-on can be followed by "Display Program Messages" or a password-expiry warning:

```text
key ENTER
if "Display Program Messages" key ENTER
if "Password expires" key ENTER
ifnot "Main Menu" fail "did not reach the main menu"
```

**Command line.** Most screens have a `===>` command line:

```text
fill-after "===>" "DSPLIBL"
key ENTER
```

**Paging through a list.**

```text
save report.txt
ifnot "Bottom" key PAGEDOWN
ifnot "Bottom" save report.txt append
```

The script language has no loops; for long lists repeat the pair a fixed number of times (see `examples/paged_report.5250`) or use the Python API.

**Secrets.** Keep passwords in environment variables, not in scripts or command lines (which show up in `ps`). Password fields are masked in `print`, `save` and error dumps.

```bash
export H5250_PASSWORD='...'
h5250 signon.5250 -D USER=BOB
```

**Debugging.** `--trace` hex-dumps all traffic to stderr.
