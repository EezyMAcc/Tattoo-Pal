# RECONCILIATION.md — Phase 2 SDK capability findings

Captured by Chunk 0 (2026-06-15). Subsequent chunks should treat this as ground
truth for the installed `mcp==1.27.2` API surface — no re-derivation needed.

---

## 1. mcp version and bump decision

`mcp==1.27.2` (as pinned in `pyproject.toml`) exposes **all** APIs that chunks
1–5 require. **No version bump is needed.**

Verified with:

```python
import importlib.metadata
importlib.metadata.version("mcp")  # → "1.27.2"
```

---

## 2. Auth API — present in 1.27.2

All three symbols that Chunk 2 will use are importable and correct:

```python
from mcp.server.auth.settings import AuthSettings
from mcp.server.auth.provider import TokenVerifier, AccessToken
from mcp.server.fastmcp import FastMCP
```

**`AuthSettings` fields** (`AuthSettings.model_fields.keys()`):

| Field | Purpose |
|---|---|
| `issuer_url` | External IdP issuer (must match token `iss`) |
| `resource_server_url` | Canonical server URI (audience binding, RFC 8707) |
| `required_scopes` | List of scope strings the verifier must enforce |
| `service_documentation_url` | Optional docs URL |
| `client_registration_options` | Optional DCR config |
| `revocation_options` | Optional revocation config |

Construction confirmed green:

```python
AuthSettings(
    issuer_url=AnyHttpUrl("https://example.auth0.com/"),
    resource_server_url=AnyHttpUrl("https://mcp.example.com/"),
    required_scopes=["mcp:read"],
)
```

**`TokenVerifier`** — one method:

```python
async def verify_token(self, token: str) -> AccessToken | None: ...
```

**`AccessToken` fields**: `token`, `client_id`, `scopes`, `expires_at`, `resource`,
`subject`, `claims`.

**`FastMCP.__init__` accepts `auth=` and `token_verifier=`** — confirmed from
`inspect.signature(FastMCP.__init__).parameters`.

---

## 3. Resource registration for widget — present in 1.27.2

- `FastMCP.resource` decorator: **present** (`hasattr(FastMCP, 'resource') → True`).
- `mcp.types.Resource` has a `mimeType` field.
- `mimeType="text/html;profile=mcp-app"` is accepted without validation error.
- `uri="ui://widget/inspiration.html"` accepted.

Confirmed:

```python
from mcp.types import Resource
Resource(uri="ui://widget/test.html", name="test", mimeType="text/html;profile=mcp-app")
# → Resource(..., mimeType="text/html;profile=mcp-app")
```

---

## 4. Baseline gate

Full gate run immediately before Chunk 0 commit:

- `ruff format --check .` — 28 files already formatted ✓
- `ruff check .` — All checks passed ✓
- `mypy --strict src` — Success: no issues found in 17 source files ✓
- `pytest -q --cov=src/tattoo_feed --cov-fail-under=90` — 102 passed, 100% coverage ✓

No source behaviour was changed in Chunk 0.

---

## 5. Existing server notes (for later chunks)

- `server/app.py` `main()` already branches on `MCP_TRANSPORT=http` (set during
  setup). Chunk 1 formalises this with tests.
- `_services` singleton holds a single sync `httpx.Client`. Shared across HTTP
  requests — acceptable for the single-account demo (noted in `PLAN.md`).
- `next_inspiration` currently returns `[ImageContent, TextContent]`. Chunk 3
  replaces this with the widget pattern; the tests that assert
  `blocks[0].type == "image"` are the ones to update then.
- **Scope enforcement is automatic**: the SDK's `RequireAuthMiddleware` iterates
  over `required_scopes` and returns `403 insufficient_scope` if any required
  scope is absent from `auth_credentials.scopes` (populated from
  `AccessToken.scopes`). The `TokenVerifier.verify_token` implementation in
  Chunk 2 only needs to validate the JWT (signature, `iss`, `aud`, `exp`) and
  return an `AccessToken` with `scopes` populated from the JWT `scope` claim.
  The SDK middleware handles the 403 path.
