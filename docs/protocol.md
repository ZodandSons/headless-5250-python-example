# Protocol notes

How `headless5250` implements TN5250, for anyone debugging a screen or extending the code. References: RFC 1205 (5250 Telnet Interface), RFC 2877 (5250 Telnet Enhancements), RFC 4777 (IBM iSeries Telnet Enhancements) and IBM's *5250 Information Display System Functions Reference*.

## Layers

```text
TCP / TLS
  └─ Telnet        IAC negotiation, IAC IAC escaping, records ended by IAC EOR
       └─ GDS      10-byte header: length, 0x12A0, flags, opcode
            └─ 5250 data stream   ESC (0x04) + command + orders/data
```

Everything is in `src/headless5250/session.py`:

| Function | Layer |
|---|---|
| `_feed`, `_negotiate`, `_subneg` | Telnet state machine |
| `_record`, `_send_record` | GDS records |
| `_datastream`, `_wtd`, `_sf`, `_write_error`, `_wsf` | 5250 commands and orders |
| `_field_data`, `send_key` | Building the reply for an AID key |

## Telnet negotiation

| Option | Client answer |
|---|---|
| BINARY (0), END-OF-RECORD (25) | WILL / DO |
| TERMINAL-TYPE (24) | WILL; sends `IBM-3179-2`, or `IBM-3477-FC` with `wide` |
| NEW-ENVIRON (39) | WILL; sends `DEVNAME` when a device name is set, otherwise an empty list |
| anything else | WONT / DONT |

## Commands handled

| Command | Code | Notes |
|---|---|---|
| Clear Unit | `40` | Resets to 24x80 |
| Clear Unit Alternate | `20` | `00` = 27x132 |
| Clear Format Table | `50` | |
| Write To Display | `11` | Control characters CC1 (field reset / MDT handling) and CC2 (unlock keyboard) |
| Write Error Code | `21`, `22` | Shown on the last line; exposed as `error_message`; Reset restores the line |
| Read Input Fields | `42` | All fields, no addresses |
| Read MDT Fields | `52`, `82` | Changed fields, each prefixed with SBA row/col; trailing nulls trimmed |
| Read Immediate | `72`, `83` | Answered at once without an AID |
| Read Screen | `62` | Raw screen buffer |
| Save Screen / Restore Screen | `02`, `12` | Save replies with a restore order the host sends back later |
| Roll | `23` | Accepted and ignored |
| Write Structured Field | `F3` | 5250 Query (`D9 70`) gets a query reply; others ignored |

## Orders handled in Write To Display

SBA (set buffer address), SF (start field, with FFW and FCWs), IC (insert cursor), MC (move cursor), RA (repeat to address), EA (erase to address), SOH (start of header, including the command-attention key mask), TD (transparent data). WEA and WDSF are parsed and skipped, so windows and selection fields still draw their text but have no special behaviour.

## Fields

Each SF with a field format word becomes a `Field(start, length, ffw, fcws, attr)`. The client uses:

| Bit / value | Effect |
|---|---|
| FFW `0x2000` bypass | Not an input field |
| FFW `0x0800` MDT | Set when typed into; decides what Read MDT sends |
| FFW `0x0020` monocase | Input upper-cased |
| attribute low bits `111` | Non-display; masked in all output |
| SOH CA mask | F-keys marked command-attention send cursor + AID only |

Not implemented: signed-numeric and right-adjust/fill semantics (`FFW` shift edits), mandatory-enter and mandatory-fill checks, field exit, auto-enter, cursor progression FCWs, continued (word-wrap) fields. The host still validates these, so you'll see its error message rather than a client-side lock.

## Keys

AID codes: Enter `F1`, F1-F12 `31`-`3C`, F13-F24 `B1`-`BC`, PageUp `F4`, PageDown `F5`, Clear `BD`, Help `F3`, Print `F6`, Record Backspace `F8`. Clear, Help, Print and Record Backspace send no field data.

Attn and SysReq are not AIDs: they are empty GDS records with flag `0x4000` and `0x0400`.

## Screen completeness

The host signals "your turn" by unlocking the keyboard (CC2 bit or a Read command), but some screens arrive in several records. `wait_unlocked` therefore waits for the keyboard to unlock **and** for no data to arrive for `settle` seconds (default 0.3). Raise `settle` on slow or high-latency links.

## Not supported

- DBCS code pages (Japanese, Chinese, Korean) and SO/SI handling
- Printer sessions (3812 emulation)
- Telnet auto sign-on (`USER`, `IBMRSEED`, encrypted password substitution); sign on through the screen instead
- Graphical/GUI orders (scroll bars, push buttons drawn with WDSF), which still show their text
- Insert mode, field exit and Dup keys

Contributions for any of these are welcome; see `CONTRIBUTING.md`.
