"""A tiny fake IBM i telnet server for tests and offline demos.

It speaks just enough TN5250 to exercise a client: telnet negotiation, GDS
records, and hand-built 5250 data streams. A test supplies a `script`
function that receives a :class:`HostConn` and drives the conversation.

Run this file directly to get an interactive demo host on port 2323 with a
sign-on screen and a main menu, so you can try h5250 without an IBM i:

    python tests/fake_host.py            # then, in another terminal:
    h5250 examples/demo_fake_host.5250
"""

import socket
import struct
import threading
import time

IAC, DO, WILL, SB, SE, EOR = 255, 253, 251, 250, 240, 239
CP = "cp037"


# ------------------------------------------------------------ stream builders
def e(text):
    return text.encode(CP)


def clear():
    return b"\x04\x40"


def wtd(body, cc1=0x00, cc2=0x08):
    """Write To Display. cc2 bit 0x08 unlocks the keyboard."""
    return bytes([0x04, 0x11, cc1, cc2]) + body


def sba(row, col):
    return bytes([0x11, row, col])


def ic(row, col):
    return bytes([0x13, row, col])


def sf(length, ffw=0x4000, attr=0x24, fcws=()):
    """Start Field. The attribute byte goes in the cell before the field."""
    out = bytes([0x1D, ffw >> 8, ffw & 0xFF])
    for fcw in fcws:
        out += bytes([fcw >> 8, fcw & 0xFF])
    return out + bytes([attr, length >> 8, length & 0xFF])


def end_attr():
    return b"\x20"


def soh(ca_mask=0):
    """Start Of Header; ca_mask bit n-1 set = F<n> is a command-attention key."""
    hdr = bytes([0, 0, 0, 0, (ca_mask >> 16) & 0xFF, (ca_mask >> 8) & 0xFF, ca_mask & 0xFF])
    return bytes([0x01, len(hdr)]) + hdr


def read_mdt():
    return b"\x04\x52\x00\x00"


def write_error(msg):
    return b"\x04\x21" + e(msg)


def text_at(row, col, text):
    return sba(row, col) + e(text)


def input_field(row, col, length, ffw=0x4000, attr=0x24):
    """An input field whose first data cell is at row/col (attribute at col-1)."""
    return sba(row, col - 1) + sf(length, ffw, attr) + sba(row, col + length) + end_attr()


MONOCASE = 0x4020          # FFW: input field, monocase
HIDDEN = 0x27              # attribute: non-display


def signon_screen():
    return clear() + wtd(
        text_at(1, 36, "Sign On")
        + text_at(6, 17, "User  . . . . . . . . . . . . . .")
        + input_field(6, 53, 10, MONOCASE)
        + text_at(7, 17, "Password  . . . . . . . . . . . .")
        + input_field(7, 53, 10, 0x4000, HIDDEN)
        + ic(6, 53)) + read_mdt()


def menu_screen(user="BOB"):
    return clear() + wtd(
        soh(ca_mask=1 << 2)  # F3 is CA: no field data
        + text_at(1, 2, "MAIN")
        + text_at(1, 33, "IBM i Main Menu")
        + text_at(3, 2, "Select one of the following:")
        + text_at(5, 6, "1. User tasks")
        + text_at(6, 6, "90. Sign off")
        + text_at(18, 2, "Signed on as " + user)
        + text_at(20, 2, "Selection or command")
        + text_at(21, 2, "===>")
        + input_field(21, 7, 60, MONOCASE)
        + text_at(23, 2, "F3=Exit")) + read_mdt()


# ------------------------------------------------------------ server
def record(datastream, opcode=0x03):
    rec = struct.pack(">HHHBHB", 10 + len(datastream), 0x12A0, 0, 4, 0, opcode) + datastream
    return rec.replace(b"\xff", b"\xff\xff") + bytes([IAC, EOR])


class Reply:
    """A record the client sent: opcode, flags, and the 5250 payload."""

    def __init__(self, raw):
        self.raw = raw
        self.flags = raw[7] << 8 | raw[8]
        self.opcode = raw[9]
        self.data = raw[10:]

    @property
    def cursor(self):
        return self.data[0], self.data[1]

    @property
    def aid(self):
        return self.data[2]

    def fields(self):
        """{(row, col): text} for SBA-tagged field data (Read MDT replies)."""
        out, d, i = {}, self.data[3:], 0
        while i < len(d):
            if d[i] != 0x11:
                break
            row, col, i = d[i + 1], d[i + 2], i + 3
            j = i
            while j < len(d) and d[j] != 0x11:
                j += 1
            out[(row, col)] = d[i:j].decode(CP)
            i = j
        return out


class HostConn:
    def __init__(self, sock):
        self.sock, self.buf, self.negotiation = sock, b"", b""

    def send(self, datastream, opcode=0x03):
        self.sock.sendall(record(datastream, opcode))

    def recv(self, timeout=5):
        self.sock.settimeout(timeout)
        while bytes([IAC, EOR]) not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("client closed")
            self.buf += chunk
        raw, self.buf = self.buf.split(bytes([IAC, EOR]), 1)
        return Reply(raw.replace(b"\xff\xff", b"\xff"))

    def negotiate(self):
        self.sock.sendall(bytes([IAC, DO, 24, IAC, DO, 25, IAC, WILL, 25, IAC, DO, 0, IAC, WILL, 0,
                                 IAC, DO, 39, IAC, SB, 24, 1, IAC, SE, IAC, SB, 39, 1, IAC, SE]))
        deadline = time.time() + 2
        self.sock.settimeout(0.2)
        while time.time() < deadline and b"IBM-" not in self.negotiation:
            try:
                self.negotiation += self.sock.recv(4096)
            except socket.timeout:
                pass
        time.sleep(0.05)
        self.sock.settimeout(0.1)
        try:
            self.negotiation += self.sock.recv(4096)
        except socket.timeout:
            pass

    def query(self):
        self.send(b"\x04\xf3\x00\x05\xd9\x70\x00", opcode=0x00)
        return self.recv()


class FakeHost:
    """Serve one client connection with `script(conn)` in a background thread."""

    def __init__(self, script, port=0):
        self.script, self.error, self.result = script, None, None
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", port))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        try:
            c, _ = self.srv.accept()
            with c:
                conn = HostConn(c)
                conn.negotiate()
                self.result = self.script(conn)
                time.sleep(0.2)
        except Exception as ex:  # surfaced to the test via .join()
            self.error = ex
        finally:
            self.srv.close()

    def start(self):
        self.thread.start()
        return self

    def join(self, timeout=10):
        self.thread.join(timeout)
        if self.error:
            raise self.error
        return self.result


def demo_script(conn):
    """Sign-on -> menu loop, used by the standalone demo host and tests.
    A client hanging up is a normal end of session."""
    try:
        _demo(conn)
    except ConnectionError:
        pass


def _demo(conn):
    conn.send(signon_screen())
    while True:
        r = conn.recv(timeout=600)
        user = r.fields().get((6, 53), "").strip() or "?"
        if r.aid == 0xF1 and user != "?":
            break
        conn.send(write_error("CPF1120 User required."))
    conn.send(menu_screen(user))
    while True:
        r = conn.recv(timeout=600)
        cmd = r.fields().get((21, 7), "").strip().upper()
        if r.aid == 0x33 or cmd in ("90", "SIGNOFF"):
            return
        conn.send(write_error("Command %s not available on the demo host." % (cmd or "(blank)")))


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 2323
    print("Fake IBM i on 127.0.0.1:%d (one session at a time, Ctrl+C to stop)" % port)
    try:
        while True:
            try:
                FakeHost(demo_script, port).start().join(timeout=None)
                print("session ended")
            except (ConnectionError, OSError) as ex:
                print("session ended:", ex)
    except KeyboardInterrupt:
        pass
