# UPGRADE_PROMPT — Phase 2 and beyond

This document captures the contract for extending the Pet Hospital MCP
service after phase 1. Future work should follow the same conventions
established here so new tools slot in without touching the transport or
error layer.

## Scope of phase 1 (already implemented)

- Single tool: `list_pets` wrapping `GET /api/v1/pets`.
- Stateless Streamable HTTP transport.
- Unified error envelope.
- Structured logging with sensitive-data redaction.

## Phase 2 — add read tools

When the next phase is green-lit, add one module per tool under
`src/pet_hospital_mcp/tools/` and register it in `server.py`. Each
module must:

1. Define Pydantic `Input`, `Success`, and (reusing) `ErrorEnvelope`
   models.
2. Expose a `register(mcp, rest_client)` function that decorates the
   tool with `@mcp.tool(name=..., description=...)`.
3. Use `PetHospitalRESTClient` for all upstream calls — never import
   `httpx` directly in tool code.
4. Emit a structured log entry via `build_tool_log_entry`.
5. Return `ErrorEnvelope.to_dict()` on any failure path.

Candidate tools for phase 2 (subject to Go API support):

- `get_pet` — `GET /api/v1/pets/{id}`
- `list_medical_records` — `GET /api/v1/pets/{id}/records`
- `list_charges` — `GET /api/v1/pets/{id}/charges`

## Phase 3 — write tools

Write tools (POST/PUT/DELETE) require an audit of:

- Idempotency strategy.
- Error rollback semantics.
- Whether the MCP client (AI agent) should be allowed to mutate data at
  all in a teaching scenario.

Do not begin phase 3 without explicit approval.

## What never changes

- The service is stateless: no `initialize`, no `Mcp-Session-Id`, no
  session storage.
- The service only listens on `127.0.0.1` by default.
- The service never modifies the Go backend's code.
