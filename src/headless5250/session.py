"""TN5250 protocol engine and the :class:`Session` API.

A headless 5250 display: it negotiates TN5250 over telnet (optionally TLS),
interprets the 5250 data stream into an in-memory screen and format table,
and sends AID keys with modified field data back to the host.
"""

import socket
import ssl
import struct
import sys
import time


# ---------------------------------------------------------------- telnet
IAC, DONT, DO, WONT, WILL, SB, SE, EOR = 255, 254, 253, 252, 251, 250, 240, 239
T_BINARY, T_TTYPE, T_EOR, T_NEWENV = 0, 24, 25, 39

# ---------------------------------------------------------- 5250 stream
ESC = 0x04
C_CLEAR_UNIT, C_CLEAR_UNIT_ALT, C_CLEAR_FMT = 0x40, 0x20, 0x50
C_WTD, C_WEC, C_WEC_WIN = 0x11, 0x21, 0x22
C_READ_INPUT, C_READ_MDT, C_READ_MDT_ALT = 0x42, 0x52, 0x82
C_READ_SCREEN, C_READ_IMMED, C_READ_IMMED_ALT = 0x62, 0x72, 0x83
C_SAVE, C_SAVE_PARTIAL, C_RESTORE, C_RESTORE_PARTIAL = 0x02, 0x03, 0x12, 0x13
C_ROLL, C_WSF = 0x23, 0xF3

O_SOH, O_RA, O_EA, O_TD, O_SBA = 0x01, 0x02, 0x03, 0x10, 0x11
O_WEA, O_IC, O_MC, O_WDSF, O_SF = 0x12, 0x13, 0x14, 0x15, 0x1D

OP_NOOP, OP_PUTGET, OP_SAVE = 0x00, 0x03, 0x04
FLAG_ATN, FLAG_SRQ = 0x4000, 0x0400

AIDS = {"ENTER": 0xF1, "CLEAR": 0xBD, "HELP": 0xF3, "PAGEUP": 0xF4,
        "ROLLDOWN": 0xF4, "PAGEDOWN": 0xF5, "ROLLUP": 0xF5, "PRINT": 0xF6,
        "RECBACK": 0xF8}
for _n in range(1, 13):
    AIDS["F%d" % _n] = 0x30 + _n
    AIDS["F%d" % (_n + 12)] = 0xB0 + _n
NO_DATA_AIDS = {0xBD, 0xF3, 0xF6, 0xF8}


class KeyboardLocked(Exception):
    pass


class Field:
    """An input field from the 5250 format table. start is a 0-based offset."""
    __slots__ = ("start", "length", "ffw", "fcws", "attr")

    def __init__(self, start, length, ffw, fcws, attr):
        self.start, self.length, self.ffw, self.fcws, self.attr = start, length, ffw, fcws, attr

    end = property(lambda s: s.start + s.length)
    bypass = property(lambda s: bool(s.ffw & 0x2000))
    monocase = property(lambda s: bool(s.ffw & 0x0020))
    hidden = property(lambda s: (s.attr & 0x07) == 0x07)   # non-display (passwords)

    @property
    def mdt(self):
        return bool(self.ffw & 0x0800)

    @mdt.setter
    def mdt(self, on):
        self.ffw = (self.ffw | 0x0800) if on else (self.ffw & ~0x0800)

    def copy(self):
        return Field(self.start, self.length, self.ffw, list(self.fcws), self.attr)


class Session:
    """One TN5250 display session. Rows and columns in the public API are 1-based."""

    def __init__(self, host, port=None, tls=False, verify=True, devname=None,
                 wide=False, codepage="cp037", timeout=30.0, settle=0.3, trace=False):
        self.host, self.tls, self.verify = host, tls, verify
        self.port = port or (992 if tls else 23)
        self.devname, self.wide, self.codepage = devname, wide, codepage
        self.timeout, self.settle, self.trace = timeout, settle, trace
        self.terminal_type = "IBM-3477-FC" if wide else "IBM-3179-2"
        self.sock = None
        self._tbl = [" "] * 0x40 + [bytes([b]).decode(codepage, "replace") for b in range(0x40, 0x100)]
        self._tbl[0x41] = " "  # EBCDIC required space
        self._clear_unit(24, 80)
        self.locked = True
        self._tstate, self._rec, self._sb, self._verb = 0, bytearray(), bytearray(), 0
        self._saves, self._save_id = {}, 0
        self.last_rx = time.monotonic()

    # ------------------------------------------------------------ connection
    def connect(self):
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.tls:
            ctx = ssl.create_default_context()
            if not self.verify:
                ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=self.host)
        self.sock = sock
        self.last_rx = time.monotonic()
        self.wait_unlocked()
        return self

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self):
        return self if self.sock else self.connect()

    def __exit__(self, *exc):
        self.close()

    def _log(self, tag, data):
        if self.trace:
            sys.stderr.write("%s %s\n" % (tag, data.hex(" ")))

    def _send_raw(self, data):
        if not self.sock:
            raise ConnectionError("not connected")
        self._log(">>", data)
        self.sock.sendall(data)

    def _send_record(self, opcode, data=b"", flags=0):
        rec = struct.pack(">HHHBHB", 10 + len(data), 0x12A0, 0, 4, flags, opcode) + bytes(data)
        self._send_raw(rec.replace(b"\xff", b"\xff\xff") + bytes([IAC, EOR]))

    def _pump(self, timeout):
        """Read whatever arrives within timeout seconds and process it."""
        if not self.sock:
            raise ConnectionError("not connected")
        self.sock.settimeout(max(timeout, 0.01))
        try:
            chunk = self.sock.recv(65536)
        except (socket.timeout, ssl.SSLWantReadError):
            return False
        if not chunk:
            self.close()
            raise ConnectionError("connection closed by host")
        self._log("<<", chunk)
        self.last_rx = time.monotonic()
        self._feed(chunk)
        return True

    # ------------------------------------------------------------ telnet layer
    def _feed(self, data):
        for b in data:
            st = self._tstate
            if st == 0:                      # data
                if b == IAC:
                    self._tstate = 1
                else:
                    self._rec.append(b)
            elif st == 1:                    # after IAC
                self._tstate = 0
                if b == IAC:
                    self._rec.append(IAC)
                elif b == EOR:
                    rec, self._rec = bytes(self._rec), bytearray()
                    self._record(rec)
                elif b in (WILL, WONT, DO, DONT):
                    self._verb, self._tstate = b, 2
                elif b == SB:
                    self._sb, self._tstate = bytearray(), 3
            elif st == 2:                    # option negotiation
                self._tstate = 0
                self._negotiate(self._verb, b)
            elif st == 3:                    # subnegotiation
                if b == IAC:
                    self._tstate = 4
                else:
                    self._sb.append(b)
            elif st == 4:
                if b == SE:
                    self._tstate = 0
                    self._subneg(bytes(self._sb))
                else:
                    self._sb.append(b)
                    self._tstate = 3

    def _negotiate(self, verb, opt):
        if verb == DO:
            ok = opt in (T_TTYPE, T_EOR, T_BINARY, T_NEWENV)
            self._send_raw(bytes([IAC, WILL if ok else WONT, opt]))
        elif verb == WILL:
            ok = opt in (T_EOR, T_BINARY)
            self._send_raw(bytes([IAC, DO if ok else DONT, opt]))

    def _subneg(self, sb):
        if len(sb) < 2 or sb[1] != 1:        # only answer SEND
            return
        if sb[0] == T_TTYPE:
            self._send_raw(bytes([IAC, SB, T_TTYPE, 0]) + self.terminal_type.encode() + bytes([IAC, SE]))
        elif sb[0] == T_NEWENV:
            body = bytearray([IAC, SB, T_NEWENV, 0])
            if self.devname:
                body += b"\x03DEVNAME\x01" + self.devname.encode()
            self._send_raw(bytes(body) + bytes([IAC, SE]))

    # ------------------------------------------------------------ 5250 layer
    def _record(self, rec):
        if len(rec) < 10 or rec[2:4] != b"\x12\xa0":
            return
        self._datastream(rec[6 + rec[6]:])

    def _datastream(self, d):
        i, n = 0, len(d)
        while i < n - 1:
            if d[i] != ESC:
                i += 1
                continue
            cmd, i = d[i + 1], i + 2
            if cmd == C_CLEAR_UNIT:
                self._clear_unit(24, 80)
            elif cmd == C_CLEAR_UNIT_ALT:
                self._clear_unit(*((27, 132) if d[i] == 0 else (24, 80)))
                i += 1
            elif cmd == C_CLEAR_FMT:
                self.fields = []
            elif cmd == C_WTD:
                i = self._wtd(d, i)
            elif cmd in (C_WEC, C_WEC_WIN):
                i = self._write_error(d, i)
            elif cmd in (C_READ_INPUT, C_READ_MDT, C_READ_MDT_ALT):
                self.read_cmd, i = cmd, i + 2
                self._unlock()
            elif cmd in (C_READ_IMMED, C_READ_IMMED_ALT):
                self._send_record(OP_PUTGET, self._field_data(C_READ_INPUT))
            elif cmd == C_READ_SCREEN:
                self._send_record(OP_NOOP, bytes(self.screen))
            elif cmd == C_SAVE:
                self._save_id = self._save_id % 255 + 1
                self._saves[self._save_id] = (self.rows, self.cols, bytes(self.screen),
                                              [f.copy() for f in self.fields], self.cursor, self.read_cmd)
                self._send_record(OP_SAVE, bytes([ESC, C_RESTORE, self._save_id]))
            elif cmd == C_RESTORE:
                snap = self._saves.get(d[i]) if i < n else None
                i += 1
                if snap:
                    self.rows, self.cols, scr, flds, self.cursor, self.read_cmd = snap
                    self.screen, self.fields = bytearray(scr), [f.copy() for f in flds]
            elif cmd == C_ROLL:
                i += 3
            elif cmd == C_WSF:
                i = self._wsf(d, i)
            # anything else: skip forward to the next ESC

    def _clear_unit(self, rows, cols):
        self.rows, self.cols = rows, cols
        self.screen = bytearray(rows * cols)
        self.fields, self.cursor, self.read_cmd = [], 0, None
        self.ca_mask, self.error_message, self._err_row = 0, None, None

    def _addr(self, row, col):
        return max(row - 1, 0) * self.cols + max(col - 1, 0)

    def _put(self, addr, b):
        if 0 <= addr < len(self.screen):
            self.screen[addr] = b

    def _wtd(self, d, i):
        cc1, cc2 = d[i], d[i + 1]
        i += 2
        self._cc1(cc1)
        addr, ic, n = self.cursor, None, len(d)
        while i < n and d[i] != ESC:
            c = d[i]
            i += 1
            if c == O_SBA:
                addr, i = self._addr(d[i], d[i + 1]), i + 2
            elif c == O_SF:
                i, addr = self._sf(d, i, addr)
            elif c == O_IC:
                ic, i = self._addr(d[i], d[i + 1]), i + 2
            elif c == O_MC:
                self.cursor, i = self._addr(d[i], d[i + 1]), i + 2
            elif c == O_RA:
                end, ch = self._addr(d[i], d[i + 1]), d[i + 2]
                i += 3
                while addr <= end:
                    self._put(addr, ch)
                    addr += 1
            elif c == O_EA:
                end, ln = self._addr(d[i], d[i + 1]), d[i + 2]
                i += 2 + max(ln, 1)
                while addr <= end:
                    self._put(addr, 0)
                    addr += 1
            elif c == O_SOH:
                ln = d[i]
                hdr = d[i + 1:i + 1 + ln]
                i += 1 + ln
                self.ca_mask = (hdr[4] << 16 | hdr[5] << 8 | hdr[6]) if len(hdr) >= 7 else 0
            elif c == O_TD:
                ln = d[i] << 8 | d[i + 1]
                for b in d[i + 2:i + 2 + ln]:
                    self._put(addr, b)
                    addr += 1
                i += 2 + ln
            elif c == O_WEA:
                i += 2
            elif c == O_WDSF:
                i += max(d[i] << 8 | d[i + 1], 2)
            else:
                self._put(addr, c)
                addr += 1
        if ic is not None:
            self.cursor = ic
        elif self._field_at(self.cursor) is None:
            first = self._next_field(-1)
            if first:
                self.cursor = first.start
        if cc2 & 0x08:
            self._unlock()
        return i

    def _sf(self, d, i, addr):
        c, ffw, fcws = d[i], None, []
        i += 1
        if c & 0xC0 == 0x40:                 # field format word
            ffw, c, i = c << 8 | d[i], d[i + 1], i + 2
        while c & 0xE0 != 0x20:              # field control words
            fcws.append(c << 8 | d[i])
            c, i = d[i + 1], i + 2
        length = d[i] << 8 | d[i + 1]
        i += 2
        self._put(addr, c)                   # attribute occupies one cell
        start = addr + 1
        self.fields = [f for f in self.fields if f.start != start]
        if ffw is not None:
            self.fields.append(Field(start, length, ffw, fcws, c))
            self.fields.sort(key=lambda f: f.start)
        return i, start

    def _cc1(self, cc1):
        t, nb = cc1 & 0xE0, [f for f in self.fields if not f.bypass]
        for f in (self.fields if t == 0x60 else nb):
            null = (t == 0x80 and f.mdt) or t in (0xA0, 0xE0) or (t == 0xC0 and f.mdt)
            if null:
                self.screen[f.start:f.end] = bytes(f.length)
            if t in (0x40, 0x60, 0xA0, 0xC0, 0xE0):
                f.mdt = False

    def _write_error(self, d, i):
        start = i
        while i < len(d) and d[i] != ESC:
            i += 1
        raw, chars, j = d[start:i], bytearray(), 0
        while j < len(raw):
            if raw[j] in (O_IC, O_MC, O_SBA):
                j += 3
                continue
            chars.append(raw[j] if raw[j] >= 0x40 else 0x40)
            j += 1
        last = (self.rows - 1) * self.cols
        if self._err_row is None:
            self._err_row = bytes(self.screen[last:last + self.cols])
        self.screen[last:last + self.cols] = bytes(chars[:self.cols]).ljust(self.cols, b"\x40")
        self.error_message = "".join(self._tbl[b] for b in chars).strip()
        self._unlock()
        return i

    def _wsf(self, d, i):
        ln = d[i] << 8 | d[i + 1]
        if d[i + 2:i + 4] == b"\xd9\x70":
            self._query_reply()
        return i + max(ln, 2)

    def _query_reply(self):
        dev, model = ("3477", "FC ") if self.wide else ("3179", "002")
        q = bytearray([0x00, 0x00, 0x88, 0x00, 0x3A, 0xD9, 0x70, 0x80,
                       0x06, 0x00, 0x01, 0x01, 0x00]) + bytes(16)
        q += b"\x01" + dev.encode(self.codepage) + model.encode(self.codepage)
        q += bytes([0x02, 0x00, 0x00, 0x00, 0x61, 0x50, 0x00, 0x01, 0x00]) + bytes(15)
        self._send_record(OP_NOOP, q)

    def _unlock(self):
        self.locked = False

    # ------------------------------------------------------------ fields
    def _field_at(self, addr):
        for f in self.fields:
            if f.start <= addr < f.end:
                return f
        return None

    def _inputs(self):
        return [f for f in self.fields if not f.bypass]

    def _next_field(self, addr, back=False):
        ins = self._inputs()
        if not ins:
            return None
        if back:
            cur = self._field_at(addr)
            before = [f for f in ins if f.start < (cur.start if cur else addr)]
            return before[-1] if before else ins[-1]
        after = [f for f in ins if f.start > addr]
        return after[0] if after else ins[0]

    def _field_bytes(self, f, strip):
        b = bytes(self.screen[f.start:f.end])
        if strip:
            b = b.rstrip(b"\x00")
        return b.replace(b"\x00", b"\x40")

    def _field_data(self, mode):
        out, ins = bytearray(), [f for f in self.fields]
        if mode == C_READ_INPUT:
            if any(f.mdt for f in ins):
                for f in ins:
                    out += self._field_bytes(f, False)
        else:
            for f in ins:
                if f.mdt:
                    r, c = divmod(f.start, self.cols)
                    out += bytes([O_SBA, r + 1, c + 1]) + self._field_bytes(f, True)
        return bytes(out)

    def input_fields(self):
        """List of (index, row, col, length, text) for typeable fields."""
        res = []
        for n, f in enumerate(self._inputs(), 1):
            r, c = divmod(f.start, self.cols)
            txt = "*" * f.length if f.hidden else self._decode(self.screen[f.start:f.end])
            res.append((n, r + 1, c + 1, f.length, txt.rstrip()))
        return res

    # ------------------------------------------------------------ keyboard
    def _check_unlocked(self):
        if self.locked:
            raise KeyboardLocked("keyboard is locked (waiting for host)")

    def _encode(self, ch, f):
        if f.monocase:
            ch = ch.upper()
        b = ch.encode(self.codepage, "replace")
        return b[0] if b else 0x40

    def move_cursor(self, row, col):
        self.cursor = self._addr(row, col)

    def type(self, text):
        """Type at the cursor, auto-advancing to the next field like a real terminal."""
        self._check_unlocked()
        for ch in text:
            f = self._field_at(self.cursor)
            if f is None or f.bypass:
                r, c = divmod(self.cursor, self.cols)
                raise ValueError("cursor at row %d col %d is not in an input field" % (r + 1, c + 1))
            self.screen[self.cursor] = self._encode(ch, f)
            f.mdt = True
            self.cursor += 1
            if self.cursor >= f.end:
                nxt = self._next_field(f.start)
                self.cursor = nxt.start if nxt else f.end - 1

    def _write_field(self, f, text, offset=0):
        if offset + len(text) > f.length:
            raise ValueError("text %r is longer than the %d-char field" % (text, f.length - offset))
        self.screen[f.start + offset:f.end] = bytes(f.length - offset)   # erase to end of field
        for k, ch in enumerate(text):
            self.screen[f.start + offset + k] = self._encode(ch, f)
        f.mdt = True
        self.cursor = min(f.start + offset + len(text), f.end - 1)

    def put(self, row, col, text):
        """Write text at row/col (must be inside an input field); clears the rest of that field."""
        self._check_unlocked()
        addr = self._addr(row, col)
        f = self._field_at(addr)
        if f is None or f.bypass:
            raise ValueError("row %d col %d is not in an input field" % (row, col))
        self._write_field(f, text, addr - f.start)

    def fill_field(self, index, text):
        """Replace the contents of the Nth (1-based) input field on the screen."""
        self._check_unlocked()
        ins = self._inputs()
        if not 1 <= index <= len(ins):
            raise ValueError("no input field #%d (screen has %d)" % (index, len(ins)))
        self._write_field(ins[index - 1], text)

    def fill_after(self, label, text):
        """Fill the first input field that follows the given label text."""
        self._check_unlocked()
        pos = self.find(label)
        if not pos:
            raise ValueError("label %r not on screen" % label)
        at = self._addr(*pos) + len(label)
        for f in self._inputs():
            if f.start >= at:
                return self._write_field(f, text)
        raise ValueError("no input field after %r" % label)

    def tab(self, back=False):
        f = self._next_field(self.cursor, back)
        if f:
            self.cursor = f.start

    def reset(self):
        """The Reset key: clear an error line."""
        if self._err_row is not None:
            last = (self.rows - 1) * self.cols
            self.screen[last:last + self.cols] = self._err_row
        self._err_row, self.error_message = None, None

    def send_key(self, key, wait=True, timeout=None):
        """Press an AID key (ENTER, F1-F24, PAGEUP, PAGEDOWN, CLEAR, HELP, PRINT, ATTN, SYSREQ, RESET)."""
        k = key.upper().replace("_", "")
        if k == "RESET":
            return self.reset()
        if k in ("ATTN", "SYSREQ"):
            self.reset()
            self._send_record(OP_NOOP, b"", FLAG_ATN if k == "ATTN" else FLAG_SRQ)
        else:
            if k not in AIDS:
                raise ValueError("unknown key %r" % key)
            self._check_unlocked()
            self.reset()
            aid = AIDS[k]
            r, c = divmod(self.cursor, self.cols)
            data = bytearray([r + 1, c + 1, aid])
            fnum = (aid - 0x30) if 0x31 <= aid <= 0x3C else (aid - 0xA4) if 0xB1 <= aid <= 0xBC else 0
            is_ca = fnum and (self.ca_mask >> (fnum - 1)) & 1
            if aid not in NO_DATA_AIDS and not is_ca:
                data += self._field_data(self.read_cmd or C_READ_MDT)
            self._send_record(OP_PUTGET, data)
        self.locked = True
        if wait:
            self.wait_unlocked(timeout)
        return self

    press = send_key

    def attn(self, wait=True):
        return self.send_key("ATTN", wait)

    def sysreq(self, wait=True):
        return self.send_key("SYSREQ", wait)

    # ------------------------------------------------------------ waiting
    def wait_unlocked(self, timeout=None, settle=None):
        """Block until the host unlocks the keyboard and data stops arriving for `settle` s."""
        settle = self.settle if settle is None else settle
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            now = time.monotonic()
            quiet = now - self.last_rx
            if not self.locked and quiet >= settle:
                return self
            if now >= deadline:
                raise TimeoutError("host did not unlock the keyboard in time")
            wait = (settle - quiet) if not self.locked else 0.5
            self._pump(min(wait, deadline - now))

    def wait_for_text(self, text, timeout=None, gone=False):
        """Wait until text appears (or disappears, gone=True) and the keyboard is unlocked."""
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            if (self.contains(text) != gone) and not self.locked:
                return self.wait_unlocked(max(deadline - time.monotonic(), 0.1))
            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError("timed out waiting for %r to %s" % (text, "go" if gone else "appear"))
            self._pump(min(0.5, deadline - now))

    # ------------------------------------------------------------ reading
    def _decode(self, raw):
        return "".join(self._tbl[b] for b in raw)

    def lines(self, show_hidden=False):
        scr = bytearray(self.screen)
        if not show_hidden:
            for f in self.fields:
                if f.hidden:
                    scr[f.start:f.end] = bytes(f.length)
        return [self._decode(scr[r * self.cols:(r + 1) * self.cols]) for r in range(self.rows)]

    def text(self):
        return "\n".join(l.rstrip() for l in self.lines())

    def get_text(self, row, col, length):
        a = self._addr(row, col)
        return self._decode(self.screen[a:a + length])

    def find(self, text):
        """Return (row, col) of the first occurrence of text, or None."""
        for r, line in enumerate(self.lines()):
            c = line.find(text)
            if c >= 0:
                return (r + 1, c + 1)
        return None

    def contains(self, text):
        return self.find(text) is not None

    def dump(self):
        r, c = divmod(self.cursor, self.cols)
        bar = "+" + "-" * self.cols + "+"
        head = "%dx%d  cursor=%d,%d  %s" % (self.rows, self.cols, r + 1, c + 1,
                                            "LOCKED" if self.locked else "ready")
        body = ["|%s| %2d" % (l, n) for n, l in enumerate(self.lines(), 1)]
        return "\n".join([head, bar] + body + [bar])
