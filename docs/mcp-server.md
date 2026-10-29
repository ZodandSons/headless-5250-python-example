# MCP server (IBM Bob and other AI assistants)

`h5250-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server over stdio. It gives an AI assistant tools to open 5250 sessions, read screens, fill fields and press keys, so it can work green screens one step at a time.

It works with any MCP client that runs local stdio servers, including IBM Bob (IDE and Shell), Claude Desktop, Claude Code and VS Code.

## Setup for IBM Bob

1. Install the package so `h5250-mcp` is on your PATH: `pip install .` from the repo. (Or point at the module, below.)
2. Edit Bob's MCP settings:
   - global: `~/.bob/settings/mcp.json` (Windows: `%APPDATA%\Bob\settings\mcp.json`)
   - one workspace: `.bob/mcp.json`
3. Add the server:

```json
{
  "mcpServers": {
    "h5250": {
      "command": "h5250-mcp",
      "env": {
        "H5250_ALLOWED_HOSTS": "myibmi.example.com,devibmi.example.com",
        "H5250_PASSWORD": "your-password"
      }
    }
  }
}
```

Without installing, run it as a module:

```json
"h5250": {
  "command": "python3",
  "args": ["-m", "headless5250.mcp_server"],
  "env": { "PYTHONPATH": "/path/to/headless5250/src", "H5250_PASSWORD": "..." }
}
```

On Windows use `python` and a Windows path such as `C:\\tools\\headless5250\\src`.

4. Restart Bob and check **Settings > MCP**: `h5250` should show as connected with 12 tools.

`examples/bob/` has a ready-made `mcp.json` and sample prompts.

### Bob Shell

Servers configured for the IDE may already be available in Bob Shell; check with `bob mcp list` (or `/mcp list` inside a session).

### Other clients

The same `mcpServers` block works for Claude Desktop (`claude_desktop_config.json`) and Claude Code (`claude mcp add h5250 -- h5250-mcp`).

## Environment variables

| Variable | Purpose |
|---|---|
| `H5250_ALLOWED_HOSTS` | Comma-separated hosts the assistant may connect to. Empty or unset = any host. **Set this.** |
| `H5250_<NAME>` | Secrets the assistant can type into fields by name, e.g. `H5250_PASSWORD`, `H5250_PROD_PASSWORD`. |
| `H5250_ALLOW_SAVE` | `1` lets `run_script` use `save` to write screen text to files. Off by default. |
| `H5250_TRACE` | `1` hex-dumps 5250 traffic to the server's stderr (Bob's MCP log). |

## Tools

Every tool that touches a session returns the current screen, the keyboard state, any error-line message and a numbered list of input fields, so the assistant always knows where it can type next.

| Tool | Arguments | Does |
|---|---|---|
| `connect` | `host`, `port`, `tls`, `insecure`, `wide`, `devname`, `codepage`, `timeout` | Opens a session; returns `session_id` and the first screen. |
| `get_screen` | `session_id` | Current screen. |
| `fill` | `session_id`, one of `label` / `field` / `row`+`col`, and `value` or `value_env` | Fills one field. Doesn't press Enter. |
| `fill_many` | `session_id`, `items` (list of the above) | Fills several fields. |
| `type_text` | `session_id`, `text` | Types at the cursor. |
| `move_cursor` | `session_id`, `row`, `col` | Moves the cursor. |
| `press_key` | `session_id`, `key`, `wait`, `timeout` | ENTER, F1-F24, PAGEUP, PAGEDOWN, CLEAR, HELP, PRINT, ATTN, SYSREQ, RESET, TAB, BACKTAB. Returns the new screen. |
| `wait_for_text` | `session_id`, `text`, `gone`, `timeout` | Waits for text to appear or disappear. |
| `read_text` | `session_id`, `row`, `col`, `length` | Returns just that piece of text. |
| `run_script` | `script`, optional `session_id`, `variables` | Runs a whole [script](script-language.md) in one call; faster for routine sequences. |
| `list_sessions` | | Open sessions. |
| `disconnect` | `session_id` | Closes a session. |

## Security model

An assistant with a 5250 session can do anything the user profile can do. Plan for that:

- **Use a limited user profile.** Give the assistant its own IBM i profile with only the authority it needs; for exploration, a profile with `LMTCPB(*YES)` and a restricted menu is a good start. The server can't be more careful than the profile.
- **Allowlist hosts.** `H5250_ALLOWED_HOSTS` stops the assistant from connecting anywhere else, including from inside `run_script`.
- **Secrets by name.** The assistant passes `value_env: "H5250_PASSWORD"`; the server types the value. The password never appears in the conversation, and non-display fields are masked in every screen it returns.
- **Only `H5250_` variables.** `value_env` and `${...}` in `run_script` can only read environment variables starting with `H5250_`, so the assistant can't read your other environment (API keys, `HOME`, `PATH`...).
- **No file writes by default.** The script `save` command is disabled in `run_script` unless you set `H5250_ALLOW_SAVE=1`, since it would write files with the server's permissions.
- **Review destructive steps.** Most MCP clients, Bob included, can ask for approval before each tool call. Keep approvals on for production systems.

## Sample prompts

- "Connect to devibmi, sign on as QAUSER using H5250_PASSWORD, and list the jobs in WRKACTJOB using more than 5% CPU."
- "On myibmi, go to WRKSPLF and tell me which spooled files are older than a week."
- "Walk through the ORDENT program on devibmi with customer 1001 and item ABC, and report every error message you hit."
- "Write a headless5250 script that reproduces what you just did, so I can run it in CI."

The last one is a good habit: let the assistant explore once, then keep the result as a script.
