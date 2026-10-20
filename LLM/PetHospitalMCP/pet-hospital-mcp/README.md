# Pet Hospital MCP

An independent MCP (Model Context Protocol) service that exposes the Go Pet
Hospital REST API to AI Agents. Built on the official Python SDK `mcp==2.0.0`
with a stateless Streamable HTTP transport — no sessions, no `initialize`
handshake, no `Mcp-Session-Id` header.

## Architecture

```
┌──────────────┐     MCP/Streamable HTTP     ┌─────────────────┐
│  AI Agent    │ ◄──────────────────────────► │  pet-hospital-mcp │
│  (MCP Client)│      POST /mcp (JSON-RPC)   │  (Python ASGI)    │
└──────────────┘                              └────────┬──────────┘
                                                       │ httpx
                                                       ▼
                                              ┌─────────────────┐
                                              │  Go REST API     │
                                              │  :8080/api/v1/*  │
                                              └─────────────────┘
```

### Key design decisions

| Concern | Choice |
|---|---|
| MCP spec version | `2026-07-28` |
| Python SDK | `mcp==2.0.0` (`MCPServer`, not FastMCP) |
| Transport | Streamable HTTP (`stateless_http=True`) |
| Session model | Stateless — each request is self-contained |
| Input validation | Pydantic v2 models inside the tool function |
| Backend HTTP client | `httpx.AsyncClient` with retry + timeout |
| Error handling | Unified `{"error": {"code","message","details"}}` envelope |
| Logging | `structlog` JSON lines with sensitive-field redaction |
| Tool result | `CallToolResult` with `structured_content` + `is_error` flag |

## Quick start

### Prerequisites

- Python 3.11+
- The Go pet hospital REST API running on `http://127.0.0.1:8080`

### Install

```bash
cd pet-hospital-mcp
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -e ".[dev]"
```

### Run the MCP server

```bash
python -m pet_hospital_mcp
```

The server listens on `http://127.0.0.1:8000` and exposes:

| Endpoint | Method | Purpose |
|---|---|---|
| `/mcp` | POST | MCP JSON-RPC over Streamable HTTP |
| `/health` | GET | Service health + upstream reachability |

### Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `MCP_HOST` | `127.0.0.1` | Bind address |
| `MCP_PORT` | `8000` | Listen port |
| `PET_HOSPITAL_BASE_URL` | `http://127.0.0.1:8080` | Go REST API base URL |
| `BACKEND_TIMEOUT_SECONDS` | `10.0` | Per-request timeout |
| `BACKEND_MAX_RETRIES` | `2` | Max retry attempts for transient failures |
| `BACKEND_RETRY_BACKOFF_SECONDS` | `0.5` | Base delay for exponential backoff |

Example:

```bash
PET_HOSPITAL_BASE_URL=http://10.0.0.5:8080 MCP_PORT=9000 python -m pet_hospital_mcp
```

## Available tools

### `list_pets`

Wraps `GET /api/v1/pets` — query the pet hospital database with filtering,
sorting, and pagination. Read-only and safe to call repeatedly.

#### Parameters

All parameters are optional. Field names are snake_case.

| Parameter | Type | Default | Constraints |
|---|---|---|---|
| `q` | string | — | Free-text full-search |
| `name` | string | — | Substring match on pet name |
| `owner_name` | string | — | Substring match on owner name |
| `owner_phone` | string | — | Substring match on owner phone |
| `species` | string | — | One of: `犬, 猫, 兔, 鸟, 仓鼠, 爬宠, 其他` |
| `doctor` | string | — | Substring match on doctor name |
| `disease` | string | — | Substring match on diagnosis |
| `status` | string | — | One of: `待就诊, 就诊中, 住院中, 已康复, 慢性病随访` |
| `min` | float | — | Min total cost (≥ 0, must be ≤ `max`) |
| `max` | float | — | Max total cost (≥ 0) |
| `sort_by` | string | — | One of: `id, name, ownerName, species, doctor, disease, status, totalCost, visitCount, createdAt, updatedAt` |
| `order` | string | — | `asc` or `desc` |
| `page` | int | `1` | 1-based page number (≥ 1) |
| `page_size` | int | `20` | Items per page (1–500) |

#### Successful response (`structured_content`)

```json
{
  "items": [
    {
      "id": "pet-001",
      "name": "旺财",
      "species": "犬",
      "ownerName": "张三",
      "doctor": "李医生",
      "status": "就诊中",
      "totalCost": 120.5,
      "visitCount": 3
    }
  ],
  "total": 1,
  "page": 1,
  "pageSize": 20,
  "totalPages": 1,
  "totalCost": 120.5
}
```

#### Error response (`structured_content` with `is_error: true`)

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Input validation failed: ...",
    "details": { "tool": "list_pets" }
  }
}
```

Error codes:

| Code | Meaning |
|---|---|
| `VALIDATION_ERROR` | Input failed Pydantic validation |
| `BACKEND_TIMEOUT` | Go API did not respond in time |
| `BACKEND_UNAVAILABLE` | Connection refused / network unreachable |
| `BACKEND_API_ERROR` | Go API returned 4xx/5xx |
| `BACKEND_INVALID_RESPONSE` | Response body did not match expected schema |
| `INTERNAL_ERROR` | Unexpected internal failure |

## Project structure

```
pet-hospital-mcp/
├── pyproject.toml
├── README.md
├── src/
│   └── pet_hospital_mcp/
│       ├── __init__.py
│       ├── __main__.py          # Entry point: python -m pet_hospital_mcp
│       ├── config.py            # Settings (env-var driven)
│       ├── errors.py             # ErrorEnvelope + error codes
│       ├── logging_config.py    # structlog JSON + sensitive-field redaction
│       ├── rest_client.py       # httpx async client for Go REST API
│       ├── server.py            # MCPServer + Streamable HTTP + /health
│       └── tools/
│           ├── __init__.py
│           └── list_pets.py     # list_pets tool implementation
└── tests/
    ├── conftest.py              # Fixtures + mock Go responses
    ├── test_input_validation.py # Pydantic model tests
    ├── test_logging.py          # Redaction + log entry tests
    ├── test_rest_client.py      # REST client error/retry tests
    └── test_mcp_server.py       # MCP server/tool/endpoint tests
```

## Testing

```bash
cd pet-hospital-mcp
python -m pytest -v
```

All tests use `httpx.MockTransport` — no live Go backend required.

## Connecting an MCP client

### Claude Desktop / Cline / Continue

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "pet-hospital": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Because the service runs in stateless mode, no `Mcp-Session-Id` header or
`initialize` handshake is required — each POST to `/mcp` is self-contained.

### Manual JSON-RPC example

```bash
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tools/call",
    "params": {
      "name": "list_pets",
      "arguments": {
        "species": "犬",
        "page": 1,
        "page_size": 10
      }
    }
  }'
```

## Health check

```bash
curl http://127.0.0.1:8000/health
```

```json
{
  "status": "ok",
  "service": "pet-hospital-mcp",
  "mcp_sdk_version": "2.0.0",
  "mcp_protocol_version": "2026-07-28",
  "transport": "streamable-http",
  "endpoint": "/mcp",
  "upstream": "ok",
  "upstream_base_url": "http://127.0.0.1:8080"
}
```

## Extending with new tools

See `UPGRADE_PROMPT.md` for a step-by-step guide on adding new MCP tools that
wrap additional Go REST API endpoints.
