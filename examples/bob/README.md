# Using headless5250 from IBM Bob

1. `pip install .` from the repository root, so `h5250-mcp` is on your PATH.
2. Copy `mcp.json` to `~/.bob/settings/mcp.json` (Windows: `%APPDATA%\Bob\settings\mcp.json`), or to `.bob/mcp.json` in one workspace. If the file already exists, merge the `h5250` entry into its `mcpServers` object.
3. Set `H5250_ALLOWED_HOSTS` and the password. Use a dedicated IBM i profile with only the authority Bob needs.
4. Restart Bob and check that **h5250** is connected under Settings > MCP.

Full details: [docs/mcp-server.md](../../docs/mcp-server.md).

## Prompts to try

Exploring:

> Connect to devibmi.example.com with TLS, sign on as BOBUSER using H5250_PASSWORD, and tell me what's on the first screen after sign-on.

> In WRKACTJOB, list the five jobs using the most CPU and which subsystem each is in.

> Go to WRKSPLF and summarise the spooled files by output queue.

Testing:

> Run the order entry program (CALL ORDENT) with customer 1001, item ABC, quantity 0, and tell me exactly what error message the program shows.

Turning exploration into automation:

> Write a headless5250 script (see docs/script-language.md) that repeats the steps you just took, using ${H5250_PASSWORD} for the password and assert lines for each screen you expect. Save it as tests/ordent_qty_zero.5250.

Without a real system, start the fake host (`python tests/fake_host.py`) and allow `127.0.0.1` in `H5250_ALLOWED_HOSTS`:

> Connect to 127.0.0.1 port 2323, sign on as DEMO with any password, and describe the menu.
