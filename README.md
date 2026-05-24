# paperless-bulk-mcp

> Bulk write operations for [Paperless-ngx](https://docs.paperless-ngx.com/) via Model Context Protocol.

Companion to read-only search MCPs (such as PaperCortex). Where those let an
LLM **find** documents, this server lets it **change** them in bulk — set
correspondents, add/remove tags, change document types, etc. — using
Paperless' native `bulk_edit` endpoint.

## Why this exists

Paperless' direct PUT/PATCH endpoints require the full document body. For
OCR'd documents with embedded control characters, the JSON round-trip can
fail with cryptic parse errors. The `bulk_edit` endpoint sidesteps this by
taking only IDs + the operation:

```json
POST /api/documents/bulk_edit/
{
  "documents": [123, 456, 789],
  "method": "add_tag",
  "parameters": { "tag": 42 }
}
```

This MCP server wraps that endpoint behind tool calls.

## Status

Early — only `health_check` is implemented. Bulk operations are next.

## Install

Requires Python 3.11+ (tested on 3.14, Homebrew).

```bash
git clone git@github.com:McCavity/paperless-bulk-mcp.git
cd paperless-bulk-mcp

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and set PAPERLESS_URL + PAPERLESS_TOKEN
```

## Test it standalone

```bash
source .venv/bin/activate
python server.py
# (server now listens on stdin — feed it MCP JSON-RPC frames)
```

For a quick smoke test, see `tests/` (TBD).

## Register as a Claude Code MCP

Add to `~/.claude.json` under `mcpServers` (user scope):

```json
"paperless-bulk": {
  "command": "/Users/<you>/git/projects/own/paperless-bulk-mcp/.venv/bin/python",
  "args": ["/Users/<you>/git/projects/own/paperless-bulk-mcp/server.py"]
}
```

Token + URL come from `.env` next to `server.py` — no need to duplicate them
into the host config.

## Tool catalog

| Tool | Status | Description |
|---|---|---|
| `health_check` | ✅ | Confirms reachability and token validity. |
| `bulk_add_tag` | 🚧 | Add a tag to N documents. |
| `bulk_remove_tag` | 🚧 | Remove a tag from N documents. |
| `bulk_set_correspondent` | 🚧 | Assign a correspondent to N documents. |
| `bulk_set_document_type` | 🚧 | Assign a document type to N documents. |
| `bulk_set_storage_path` | 🚧 | Assign a storage path to N documents. |
| `bulk_delete` | 🚧 | Delete N documents (Paperless trash). |
| `bulk_redo_ocr` | 🚧 | Re-run OCR for N documents. |
| `find_tag_by_name` | 🚧 | Resolve a tag name to ID (uses `?name__icontains=`). |
| `find_correspondent_by_name` | 🚧 | Resolve a correspondent name to ID. |
| `find_document_type_by_name` | 🚧 | Resolve a document type name to ID. |

Naming-resolver tools exist because the `bulk_edit` endpoint takes IDs, but
humans (and LLMs) reason in names. They also enforce the
"server-side filter, never grep page 1"-discipline.

## Project layout

```
paperless-bulk-mcp/
├── .env.example       # Template for the secret file
├── .gitignore         # Ignores .env, venv, caches
├── CLAUDE.md          # Conventions for AI agents working on this repo
├── LICENSE            # MIT
├── README.md          # This file
├── requirements.txt   # fastmcp, httpx, python-dotenv
├── server.py          # FastMCP server, all tools
└── tests/             # (TBD)
```

## License

[MIT](LICENSE)
