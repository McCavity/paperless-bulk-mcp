# paperless-bulk-mcp — Conventions for AI agents

> Last update: 2026-05-24

This file orients AI coding agents (Claude Code, Codex, etc.) when working
on this repository. Humans should read [README.md](README.md) first.

## What this project is

A Model Context Protocol server that wraps Paperless-ngx' `bulk_edit`
endpoint. Designed as the **write-side companion** to read-only search
MCPs like PaperCortex.

Transport: stdio. Framework: [FastMCP](https://github.com/jlowin/fastmcp).

## Key design choices

- **Single `server.py`, no package split.** Stays under ~300 lines for the
  full tool set. If it ever grows past that, split per-domain (tags /
  correspondents / etc.) — but not preemptively.
- **`.env` next to `server.py`, not in CWD.** The MCP host launches us
  from arbitrary directories; we load `.env` relative to the file path.
- **No mutating call without explicit IDs.** Every bulk operation takes
  `document_ids: list[int]` plus the target ID. The caller is responsible
  for having resolved names to IDs (via `find_*_by_name` helpers).
- **`bulk_edit` endpoint over PUT/PATCH.** PUT requires the full document
  body; OCR'd documents with control characters break JSON parsing
  (KI-OS Lerneintrag 2026-05-14). `bulk_edit` only takes IDs.

## Paperless API gotchas (carry-over from the KI-OS Lernprotokoll)

- **List endpoints paginate.** Never grep page 1 — use server-side filters:
  - Correspondents/Tags/DocTypes: `?name__icontains=stadtwerke`
  - Documents: `?correspondent__id=X&query=STICHWORT&ordering=-created`
- **PUT on a document returns empty body even on success.** Use `bulk_edit`
  instead for any tag/correspondent/type change.
- **The Paperless URL for Henning's homelab is `http://192.168.178.168:8001`.**
  Token lookup priority:
  1. `.env` next to `server.py` (this repo)
  2. `~/.mcp.json` under `mcpServers.papercortex.env.PAPERLESS_TOKEN`
     (Henning's existing PaperCortex token, same Paperless instance)

## Coding conventions

- Python 3.11+ (developed on Homebrew Python 3.14).
- Type hints everywhere (`from __future__ import annotations` at top).
- `httpx.Client` for sync calls; reuse via context manager per tool call —
  no global client (MCP host may spawn / kill us at will).
- Tool docstrings are the user-facing contract — write them as if the
  next user is an LLM that has nothing else to go on.
- No retry logic in v1. Paperless is on the LAN; if it's unreachable that's
  a real problem, not a transient one. Add retries only when proven needed.

## Testing

TBD — start with manual `stdio-test.sh` (echo MCP JSON-RPC frames into
`server.py`, assert against expected output). Move to pytest if the matrix
grows.

## Future "to-do"-flagged items

- [ ] Implement the seven bulk tools listed in README.
- [ ] Implement the three find_*_by_name helpers.
- [ ] Add a `stdio-test.sh` smoke test runner.
- [ ] Decide: should `bulk_delete` require an explicit `confirm=True`
      parameter to prevent accidental bulk deletion from an LLM call?

## Pattern hints for sibling MCPs

If you find yourself wanting to copy this server.py wholesale for another
MCP project (e.g. `nanobanana-render-mcp`), pause and note what's truly
shared (the `.env`-loading dance, the FastMCP scaffolding, the headers
helper). After the second copy, extract into a real template repo — see
the open loop "MCP-Server Template" in the KI-OS vault.
