import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from fake_host import (FakeHost, HIDDEN, clear, e, ic, input_field, menu_screen,  # noqa: E402
                       read_mdt, signon_screen, text_at, write_error, wtd)
from headless5250 import KeyboardLocked, Session  # noqa: E402


def connect(host, **kw):
    return Session("127.0.0.1", host.port, timeout=5, settle=0.1, **kw).connect()


class NegotiationTests(unittest.TestCase):
    def test_terminal_type_devname_and_query_reply(self):
        def script(c):
            q = c.query()
            c.send(signon_screen())
            return c.negotiation, q

        h = FakeHost(script).start()
        with connect(h, devname="QPADEV9999") as s:
            s.wait_for_text("Sign On")
        neg, q = h.join()
        self.assertIn(b"IBM-3179-2", neg)
        self.assertIn(b"DEVNAME\x01QPADEV9999", neg)
        self.assertEqual(q.opcode, 0x00)
        self.assertEqual(q.data[2], 0x88)          # query reply AID
        self.assertIn("3179".encode("cp037"), q.data)

    def test_wide_terminal(self):
        h = FakeHost(lambda c: (c.send(b"\x04\x20\x00" + wtd(text_at(1, 2, "WIDE")) + read_mdt()),
                                c.negotiation)[1]).start()
        with connect(h, wide=True) as s:
            s.wait_for_text("WIDE")
            self.assertEqual((s.rows, s.cols), (27, 132))
        self.assertIn(b"IBM-3477-FC", h.join())


class ScreenTests(unittest.TestCase):
    def test_signon_fields_and_masking(self):
        h = FakeHost(lambda c: (c.send(signon_screen()), c.recv())[1]).start()
        with connect(h) as s:
            s.wait_for_text("Sign On")
            fields = s.input_fields()
            self.assertEqual([(f[1], f[2], f[3]) for f in fields], [(6, 53, 10), (7, 53, 10)])
            self.assertEqual(s.cursor, s._addr(6, 53))
            s.fill_after("User", "bob")
            s.fill_field(2, "secret")
            self.assertNotIn("secret", s.text())
            self.assertIn("secret", "".join(s.lines(show_hidden=True)))
            self.assertEqual(s.get_text(6, 53, 3), "BOB")      # monocase upper-cases
            s.send_key("ENTER", wait=False)
        r = h.join()
        self.assertEqual(r.aid, 0xF1)
        self.assertEqual(r.fields(), {(6, 53): "BOB", (7, 53): "secret"})

    def test_type_auto_advances_between_fields(self):
        h = FakeHost(lambda c: (c.send(signon_screen()), c.recv())[1]).start()
        with connect(h) as s:
            s.wait_for_text("Sign On")
            s.type("ABCDEFGHIJxy")
            s.send_key("ENTER", wait=False)
        self.assertEqual(h.join().fields(), {(6, 53): "ABCDEFGHIJ", (7, 53): "xy"})

    def test_put_and_errors_outside_fields(self):
        h = FakeHost(lambda c: c.send(signon_screen())).start()
        with connect(h) as s:
            s.wait_for_text("Sign On")
            s.put(6, 55, "Z")
            self.assertEqual(s.get_text(6, 53, 3), "\x00\x00Z".replace("\x00", " "))
            with self.assertRaises(ValueError):
                s.put(1, 1, "x")
            with self.assertRaises(ValueError):
                s.fill_field(9, "x")
            with self.assertRaises(ValueError):
                s.fill_after("User", "X" * 11)
        h.join()

    def test_menu_command_and_ca_key_sends_no_data(self):
        def script(c):
            c.send(menu_screen())
            first = c.recv()
            c.send(menu_screen())
            return first, c.recv()

        h = FakeHost(script).start()
        with connect(h) as s:
            s.wait_for_text("Main Menu")
            s.fill_after("===>", "wrkactjob")
            s.send_key("ENTER")
            s.fill_after("===>", "junk")
            s.send_key("F3", wait=False)
        enter, f3 = h.join()
        self.assertEqual(enter.fields(), {(21, 7): "WRKACTJOB"})
        self.assertEqual(f3.aid, 0x33)
        self.assertEqual(f3.data[3:], b"")

    def test_error_line_and_reset(self):
        h = FakeHost(lambda c: (c.send(signon_screen()), c.recv(),
                                c.send(write_error("CPF1120 User XYZ does not exist.")), c.recv())).start()
        with connect(h) as s:
            s.wait_for_text("Sign On")
            s.send_key("ENTER")
            self.assertIn("CPF1120", s.error_message)
            self.assertIn("CPF1120", s.lines()[-1])
            s.send_key("RESET")
            self.assertIsNone(s.error_message)
            self.assertNotIn("CPF1120", s.text())
            s.send_key("ENTER", wait=False)
        h.join()

    def test_read_screen_and_save_restore(self):
        def script(c):
            c.send(signon_screen())
            c.send(b"\x04\x62")
            scr = c.recv()
            c.send(b"\x04\x02")
            saved = c.recv()
            c.send(clear() + wtd(text_at(1, 2, "POPUP")) + read_mdt())
            c.recv()
            c.send(saved.data + read_mdt())  # host echoes the restore order back
            return scr, saved

        h = FakeHost(script).start()
        with connect(h) as s:
            s.wait_for_text("POPUP")
            s.send_key("ENTER")
            s.wait_for_text("Sign On")
            self.assertEqual(len(s.input_fields()), 2)
        scr, saved = h.join()
        self.assertEqual(len(scr.data), 24 * 80)
        self.assertIn(e("Sign On"), scr.data)
        self.assertEqual(saved.opcode, 0x04)

    def test_attn_and_sysreq_flags(self):
        def script(c):
            c.send(signon_screen())
            a = c.recv()
            c.send(signon_screen())
            return a, c.recv()

        h = FakeHost(script).start()
        with connect(h) as s:
            s.wait_for_text("Sign On")
            s.attn()
            s.sysreq(wait=False)
        attn, srq = h.join()
        self.assertTrue(attn.flags & 0x4000)
        self.assertTrue(srq.flags & 0x0400)

    def test_keyboard_locked_and_timeout(self):
        h = FakeHost(lambda c: (c.send(clear() + wtd(text_at(1, 2, "BUSY"), cc2=0)), c.recv())).start()
        s = Session("127.0.0.1", h.port, timeout=0.5, settle=0.1)
        with self.assertRaises(TimeoutError):
            s.connect()
        with self.assertRaises(KeyboardLocked):
            s.type("x")
        s.send_key("ATTN", wait=False)
        s.close()
        h.join()

    def test_iac_bytes_are_escaped(self):
        h = FakeHost(lambda c: (c.send(clear() + wtd(text_at(1, 2, "A") + input_field(2, 2, 5)
                                                      + ic(2, 2)) + read_mdt()), c.recv())[1]).start()
        with connect(h) as s:
            s.wait_for_text("A")
            s.fill_field(1, "\x9f")   # U+009F encodes to 0xFF in cp037
            s.send_key("ENTER", wait=False)
        self.assertEqual(h.join().data[6:7], b"\xff")

    def test_hidden_attribute_constant(self):
        self.assertEqual(HIDDEN & 0x07, 0x07)


if __name__ == "__main__":
    unittest.main()
