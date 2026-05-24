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

All 10 tools implemented and live-tested against a real Paperless-ngx
instance. Resolvers verified end-to-end; bulk operations are wired through
the same `_bulk_edit` helper and share the same response shape.

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

**Diagnostics**

| Tool | Description |
|---|---|
| `health_check` | Confirms reachability and token validity. |

**Resolvers (name → ID)**

| Tool | Description |
|---|---|
| `find_tag_by_name(name, limit=5)` | Resolve a tag name to one or more IDs (case-insensitive substring). |
| `find_correspondent_by_name(name, limit=5)` | Resolve a correspondent name to IDs. |
| `find_document_type_by_name(name, limit=5)` | Resolve a document type name to IDs. |

**Bulk write operations**

| Tool | Description |
|---|---|
| `bulk_add_tag(document_ids, tag_id)` | Add a tag to N documents (idempotent). |
| `bulk_remove_tag(document_ids, tag_id)` | Remove a tag from N documents (idempotent). |
| `bulk_modify_tags(document_ids, add_tags?, remove_tags?)` | Add and/or remove multiple tags in one batch — typical inbox-processing call. |
| `bulk_set_correspondent(document_ids, correspondent_id)` | Assign correspondent (pass `None` to clear). |
| `bulk_set_document_type(document_ids, document_type_id)` | Assign document type (pass `None` to clear). |
| `bulk_set_storage_path(document_ids, storage_path_id)` | Assign storage path (pass `None` to clear). |
| `bulk_redo_ocr(document_ids)` | Queue OCR re-run on N documents (async on Paperless). |

### Deliberately not included

- **`bulk_delete`** — Paperless is a long-term archive ("once in, never out");
  bulk delete is the riskiest operation for an LLM-driven tool. Removed
  from v1. If ever added, must require an explicit user-provided
  `confirm_phrase` string parameter, not just a boolean.
- **`update_document_title`** — title edits aren't supported by `bulk_edit`
  and would require PUT/PATCH (the very thing this MCP exists to avoid).
  Use the Paperless UI for the rare case you need it.

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
