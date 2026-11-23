# MCP servers

Grandpa can use tools from other programs that speak MCP (Model Context
Protocol) over stdio. You list the servers in one file; each tool you allow
becomes a Grandpa action called `mcp__<server>__<tool>`, usable from
`grandpa mcp call` and from workflow steps.

## The rules

- **Nothing is allowed until you say so.** A server's `allow` list names the
  tools Grandpa may use (`["*"]` means all of them). Tools not on it are shown
  as `blocked` and cannot run.
- **Every MCP tool asks first**, every time. They are high risk: the server is
  someone else's code, and its tool descriptions are its own claims. With
  nobody to ask (voice, a background trigger), the tool does not run.
- **Timeout.** Each request has a deadline (`timeout`, default 30 s, at most
  600). A server that misses it is stopped, and started again on the next call.
- **Kill switch.** Any of these turns every MCP tool off at once:
  `grandpa mcp off` (undo with `grandpa mcp on`), `enabled = false` at the top
  of the file, or the environment variable `GRANDPA_MCP_OFF=1`.
- Results from MCP tools are marked untrusted.

## The file

`%USERPROFILE%\.grandpa\mcp.toml` (or the path in `GRANDPA_MCP_CONFIG`):

```toml
# enabled = false      # switches every MCP server off

[servers.files]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "D:/Notes"]
allow = ["list_directory", "read_text_file"]
timeout = 30
# enabled = false      # switches just this server off
# cwd = "D:/Notes"     # folder the server starts in
```

Server names use letters, digits, `-` and single `_`. Keep API keys out of
this file: a server inherits Grandpa's environment, so set keys as
environment variables.

The older `[tools.mcp] servers` setting in `config.toml` is not used by this.

## Commands

```powershell
uv run python -m grandpa mcp list            # servers, tools, allowed or blocked
uv run python -m grandpa mcp list --no-start # without starting servers
uv run python -m grandpa mcp test files      # start, handshake, list tools, stop
uv run python -m grandpa mcp call mcp__files__list_directory --arg path=D:/Notes
uv run python -m grandpa mcp off             # kill switch
uv run python -m grandpa mcp on
```

`--arg` values are read as JSON when they parse (`--arg count=3`,
`--arg flags=[1,2]`), otherwise as text.

## In a workflow

```yaml
name: notes-folder
steps:
  - id: look
    action: mcp__files__list_directory
    params:
      path: D:/Notes
```

`grandpa workflow run notes-folder --yes` still asks before the MCP step.
