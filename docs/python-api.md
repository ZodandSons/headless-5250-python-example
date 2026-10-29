# Python API

```python
from headless5250 import Session, KeyboardLocked
```

Everything a script can do maps to a `Session` method, plus you get loops, real error handling and your own data structures. Rows and columns are **1-based** throughout.

## Session

```python
Session(host, port=None, tls=False, verify=True, devname=None, wide=False,
        codepage="cp037", timeout=30.0, settle=0.3, trace=False)
```

| Argument | Meaning |
|---|---|
| `host`, `port` | Port defaults to 23, or 992 when `tls=True`. |
| `tls`, `verify` | TLS on/off; `verify=False` skips certificate checks. |
| `devname` | Workstation device name to request. |
| `wide` | 27x132 (IBM-3477-FC) instead of 24x80 (IBM-3179-2). |
| `codepage` | Any Python EBCDIC codec: `cp037`, `cp273`, `cp277`, `cp278`, `cp280`, `cp284`, `cp285`, `cp297`, `cp500`... |
| `timeout` | Default seconds to wait for the host. |
| `settle` | After the keyboard unlocks, how long the line must be quiet before a screen counts as complete. Raise it for slow links that send a screen in several records. |
| `trace` | Hex-dump traffic to stderr. |

Use it as a context manager, or call `connect()` and `close()` yourself:

```python
with Session("myibmi", tls=True) as s:
    ...

s = Session("myibmi").connect()
try:
    ...
finally:
    s.close()
```

`connect()` returns once the first screen is complete.

## Reading the screen

| Method / attribute | Returns |
|---|---|
| `text()` | The whole screen as one string, lines joined with `\n`, trailing spaces trimmed. |
| `lines(show_hidden=False)` | List of full-width lines. Non-display fields are blanked unless `show_hidden=True`. |
| `get_text(row, col, length)` | A slice of the screen. |
| `find(text)` | `(row, col)` of the first match, or `None`. |
| `contains(text)` | `True` / `False`. |
| `input_fields()` | `[(n, row, col, length, value), ...]` for typeable fields. Hidden fields show as `*`. |
| `dump()` | Bordered screen with cursor and keyboard state, for logs. |
| `error_message` | Text of the error line if the host sent one, else `None`. |
| `locked` | `True` while waiting for the host. |
| `rows`, `cols`, `cursor` | Screen size; cursor as a 0-based offset. |

## Entering data

| Method | Does |
|---|---|
| `fill_after(label, text)` | Fill the first input field after `label`. |
| `fill_field(n, text)` | Replace the Nth input field (1-based). |
| `put(row, col, text)` | Write into the field at row/col, clearing the rest of that field. |
| `type(text)` | Type at the cursor, auto-advancing between fields. |
| `move_cursor(row, col)` | Move the cursor. |
| `tab(back=False)` | Next / previous input field. |

They raise `ValueError` if the target isn't an input field or the text is too long, and `KeyboardLocked` if the host hasn't unlocked the keyboard.

## Keys and waiting

| Method | Does |
|---|---|
| `send_key(name, wait=True, timeout=None)` | Send an AID key (`"ENTER"`, `"F3"`, `"PAGEDOWN"`, ...) and, by default, wait for the reply. Also `press(...)`. |
| `attn()`, `sysreq()` | Attention / System Request. |
| `reset()` | Clear the error line. |
| `wait_unlocked(timeout=None, settle=None)` | Wait until the keyboard unlocks and data stops arriving. |
| `wait_for_text(text, timeout=None, gone=False)` | Wait for text to appear (or disappear). |

Waits raise `TimeoutError`; a dropped connection raises `ConnectionError`.

## Examples

### Sign on with checks

```python
def sign_on(s, user, password):
    s.wait_for_text("Sign On")
    s.fill_after("User", user)
    s.fill_after("Password", password)
    s.send_key("ENTER")
    if s.error_message:
        raise RuntimeError("sign-on failed: " + s.error_message)
    for skip in ("Display Program Messages", "Password expires"):
        if s.contains(skip):
            s.send_key("ENTER")
    if not s.contains("Main Menu"):
        raise RuntimeError("unexpected screen after sign-on:\n" + s.text())
```

### Collect every page of a list

```python
def all_pages(s, max_pages=200):
    pages = [s.text()]
    while "Bottom" not in pages[-1] and len(pages) < max_pages:
        s.send_key("PAGEDOWN")
        pages.append(s.text())
    return pages
```

### Pick a list entry by option

```python
row, col = s.find("QPADEV0001")
s.put(row, 2, "5")            # option 5=Work with, typed into the Opt column
s.send_key("ENTER")
```

### Testing with unittest/pytest

```python
class OrderEntryTest(unittest.TestCase):
    def setUp(self):
        self.s = Session("devibmi", tls=True).connect()
        sign_on(self.s, "TESTUSR", os.environ["H5250_PASSWORD"])

    def tearDown(self):
        self.s.close()

    def test_rejects_bad_customer(self):
        self.s.fill_after("===>", "CALL ORDENT")
        self.s.send_key("ENTER")
        self.s.fill_after("Customer", "99999")
        self.s.send_key("ENTER")
        self.assertIn("Customer not found", self.s.error_message or "")
```

## Running scripts from Python

```python
from headless5250 import ScriptRunner
r = ScriptRunner({"USER": "BOB"})
r.run(open("signon.5250").read().splitlines())
print(r.vars)      # includes anything captured
r.s.close()
```
