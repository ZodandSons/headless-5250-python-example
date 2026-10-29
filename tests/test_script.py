import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from fake_host import FakeHost, demo_script  # noqa: E402
from headless5250 import ScriptError, ScriptExit, ScriptRunner  # noqa: E402
from headless5250.cli import main  # noqa: E402

SIGNON = """
connect 127.0.0.1 {port} timeout=5
wait-text "Sign On"
fill-after "User" ${{USER}}
field 2 ${{PASS}}
key ENTER
assert "Main Menu"
"""


def run(script, variables=None):
    out = io.StringIO()
    r = ScriptRunner(variables or {}, out=out)
    try:
        r.run(script.splitlines())
    finally:
        if r.s:
            r.s.close()
    return r, out.getvalue()


class ScriptTests(unittest.TestCase):
    def test_signon_capture_and_conditionals(self):
        h = FakeHost(demo_script).start()
        r, out = run(SIGNON.format(port=h.port) + """
capture WHO 18 15 3
echo user=${WHO}
if "Main Menu" echo on-menu
ifnot "Main Menu" echo not-on-menu
assert-not "Sign On"
fields
key F3 nowait
""", {"USER": "bob", "PASS": "pw"})
        h.join()
        self.assertEqual(r.vars["WHO"], "BOB")
        self.assertIn("user=BOB", out)
        self.assertIn("on-menu", out)
        self.assertNotIn("not-on-menu", out)
        self.assertIn("row 21 col   7 len  60", out)

    def test_assert_failure_reports_line(self):
        h = FakeHost(demo_script).start()
        with self.assertRaises(ScriptError) as cm:
            run(SIGNON.format(port=h.port) + 'assert "Nope"\n', {"USER": "bob", "PASS": "x"})
        self.assertIn("line 8", str(cm.exception))
        self.assertIn("expected 'Nope'", str(cm.exception))

    def test_error_message_path(self):
        h = FakeHost(demo_script).start()
        _, out = run("""
connect 127.0.0.1 %d timeout=5
key ENTER
assert "CPF1120"
key RESET
assert-not "CPF1120"
echo ok
""" % h.port)
        self.assertIn("ok", out)

    def test_variables_and_exit(self):
        os.environ["H5250_TEST_ENV"] = "from-env"
        _, out = run('set A "hello world"\necho ${A} ${H5250_TEST_ENV}\n')
        self.assertEqual(out.strip(), "hello world from-env")
        with self.assertRaises(ScriptExit) as cm:
            run("exit 3\necho never\n")
        self.assertEqual(cm.exception.code, 3)
        with self.assertRaises(ScriptError):
            run("echo ${UNDEFINED_THING}\n")
        with self.assertRaises(ScriptError):
            run("frobnicate\n")
        with self.assertRaises(ScriptError):
            run("key ENTER\n")              # not connected

    def test_save_writes_file(self):
        h = FakeHost(demo_script).start()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "screen.txt")
            run(SIGNON.format(port=h.port) + 'save "%s"\nsave "%s" append\n' % (path, path),
                {"USER": "bob", "PASS": "x"})
            text = open(path).read()
        self.assertEqual(text.count("IBM i Main Menu"), 2)


class CliTests(unittest.TestCase):
    def _script(self, body):
        f = tempfile.NamedTemporaryFile("w", suffix=".5250", delete=False)
        f.write(body)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_exit_codes(self):
        h = FakeHost(demo_script).start()
        ok = self._script(SIGNON.format(port=h.port))
        self.assertEqual(main([ok, "-D", "USER=bob", "-D", "PASS=x"]), 0)
        h.join()

        h = FakeHost(demo_script).start()
        bad = self._script(SIGNON.format(port=h.port) + 'assert "Nope"\n')
        err = io.StringIO()
        old, sys.stderr = sys.stderr, err
        try:
            self.assertEqual(main([bad, "-D", "USER=bob", "-D", "PASS=x"]), 1)
        finally:
            sys.stderr = old
        self.assertIn("ERROR: line 8", err.getvalue())
        self.assertIn("IBM i Main Menu", err.getvalue())   # screen dumped on failure

        self.assertEqual(main([self._script("exit 4\n")]), 4)
        self.assertEqual(main([self._script("connect 127.0.0.1 1 timeout=1\n")]), 2)


if __name__ == "__main__":
    unittest.main()
