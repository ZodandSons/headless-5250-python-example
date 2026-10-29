# Changelog

All notable changes are listed here. The project follows [Semantic Versioning](https://semver.org).

## [1.0.0] - 2026-10-29

### Added
- TN5250 client (`Session`): telnet and TLS, IBM-3179-2 and IBM-3477-FC terminal types, device names, EBCDIC code pages.
- 5250 data stream: Write To Display with SBA, SF, IC, MC, RA, EA, SOH and TD orders; Clear Unit; Read Input, Read MDT, Read Immediate and Read Screen; Save and Restore Screen; Write Error Code; 5250 Query reply.
- All AID keys plus Attn, SysReq and Reset; command-attention keys send no field data.
- Script language and `h5250` command with exit codes for CI.
- `h5250-mcp` MCP server for IBM Bob and other assistants, with a host allowlist, secrets passed by environment-variable name, masked password fields and opt-in file writes.
- Fake IBM i host for tests and offline demos; unit tests for the protocol, scripts, CLI and MCP server.
- Documentation and examples.

### Fixed (compared with the pre-release single-file version)
- `with Session(...).connect() as s:` no longer opens a second connection.
