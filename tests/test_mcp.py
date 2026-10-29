import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
sys.path.insert(0, HERE)

from fake_host import FakeHost, demo_script  # noqa: E402


class McpClient:
    def __init__(self, env):
        full = dict(os.environ, PYTHONPATH=SRC, **env)
        self.p = subprocess.Popen([sys.executable, "-m", "headless5250.mcp_server"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=full)
        self.n = 0

    def request(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self.n += 1
            msg["id"] = self.n
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        return None if notify else json.loads(self.p.stdout.readline())

    def tool(self, name, **args):
        r = self.request("tools/call", {"name": name, "arguments": args})["result"]
        return r["isError"], r["content"][0]["text"]

    def close(self):
        self.p.stdin.close()
        self.p.wait(5)


class McpTests(unittest.TestCase):
    def setUp(self):
        self.c = McpClient({"H5250_PASSWORD": "s3cret", "H5250_ALLOWED_HOSTS": "127.0.0.1"})
        self.addCleanup(self.c.close)
        init = self.c.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                             "clientInfo": {"name": "test", "version": "1"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        self.c.request("notifications/initialized", notify=True)

    def test_tools_listed(self):
        names = {t["name"] for t in self.c.request("tools/list")["result"]["tools"]}
        self.assertTrue({"connect", "fill", "fill_many", "press_key", "get_screen", "run_script",
                         "disconnect"} <= names)

    def test_unknown_method(self):
        self.assertEqual(self.c.request("bogus/method")["error"]["code"], -32601)

    def test_allowlist_and_secret_rules(self):
        err, text = self.c.tool("connect", host="evil.example.com")
        self.assertTrue(err)
        self.assertIn("H5250_ALLOWED_HOSTS", text)
        err, text = self.c.tool("get_screen", session_id="nope")
        self.assertTrue(err)

    def test_full_signon_flow(self):
        h = FakeHost(demo_script).start()
        err, text = self.c.tool("connect", host="127.0.0.1", port=h.port, timeout=5)
        self.assertFalse(err, text)
        sid = text.split("session_id=")[1].split()[0]
        self.assertIn("#2 row 7 col 53 len 10", text)

        err, text = self.c.tool("fill", session_id=sid, label="Password", value_env="PATH")
        self.assertTrue(err)
        self.assertIn("must name a variable starting with H5250_", text)

        err, text = self.c.tool("fill_many", session_id=sid, items=[
            {"label": "User", "value": "bob"}, {"field": 2, "value_env": "H5250_PASSWORD"}])
        self.assertFalse(err, text)
        self.assertNotIn("s3cret", text)

        err, text = self.c.tool("press_key", session_id=sid, key="ENTER")
        self.assertIn("IBM i Main Menu", text)
        err, text = self.c.tool("read_text", session_id=sid, row=18, col=15, length=3)
        self.assertEqual(text, "BOB")

        err, text = self.c.tool("run_script", session_id=sid,
                                script='assert "Main Menu"\ncapture X 1 33 15\necho title=${X}\n')
        self.assertFalse(err, text)
        self.assertIn("title=IBM i Main Menu", text)

        err, text = self.c.tool("run_script", session_id=sid, script="echo ${HOME}\n")
        self.assertTrue(err)                           # non-H5250_ env vars are not exposed
        self.assertIn("undefined variable", text)

        err, text = self.c.tool("run_script", session_id=sid, script="save /tmp/x.txt\n")
        self.assertTrue(err)
        self.assertIn("H5250_ALLOW_SAVE", text)

        self.assertIn(sid, self.c.tool("list_sessions")[1])
        self.c.tool("press_key", session_id=sid, key="F3", wait=False)
        self.assertFalse(self.c.tool("disconnect", session_id=sid)[0])
        h.join()


if __name__ == "__main__":
    unittest.main()
