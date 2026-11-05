# Install the CI diagnosis plugin

## Package

From this repository:

```bash
pip install -e ".[dev]"
ci-orchestrator-mcp --timeout 5
```

The process speaks MCP over stdin and stdout. It does not read a workspace directory. Add `--audit-log path.jsonl` only when you want a local activation count. Leave it off to write nothing.

`ci-orchestrator` and `actions-doctor` are unchanged.

## Cursor plugin

The plugin manifest is `plugins/kozphy-ci-diagnosis/.cursor-plugin/plugin.json`. The MCP entry is `plugins/kozphy-ci-diagnosis/mcp.json`. It runs the `ci-orchestrator-mcp` command, so the install above has to be on `PATH` before the host starts the server.

Copy or symlink `plugins/kozphy-ci-diagnosis` to your local Cursor plugins directory if you want the skill listed without opening this repo. This repository does not publish the plugin to a marketplace.

## Demo

```bash
python scripts/demo_ci_diagnosis.py
```

Exit 0 means the fixture log was diagnosed, the printed JSON has no `ghp_` token, a `merge` call was refused, and the temporary audit file has one `tool_completed` line that does not contain the log text.

The demo log is a fixture. It is not a GitHub Actions download.

## Sample report

[sample-diagnosis.json](sample-diagnosis.json) is the success payload for that same fixture. `evidence_class` is `saved_log`.
