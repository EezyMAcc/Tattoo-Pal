# RESEARCH.md — verified external contracts (as of 2026-06-14)

The current-documentation ground truth this build depends on. Every external API
shape below was read from a live source on 2026-06-14 (links given). **These are
beta, fast-moving surfaces — re-verify against the live links before implementing
the chunk that uses them (`CLAUDE.md` §1.6). If a link contradicts this file,
update this file and note it in `BLOCKERS.md`.**

---

## 1. ChatGPT image rendering — you need an Apps SDK widget, not an image block

**The key finding that motivates this whole build:** ChatGPT does **not** render
a native MCP image content block (`type: image`, base64, `mimeType`) inline in
chat. Visual output goes through an **Apps SDK UI component** (an HTML/JS widget
rendered in a sandboxed iframe). A developer returning an image from an MCP tool
result confirmed it did not render, while the same markdown rendered when ChatGPT
itself produced it.

> Claude *does* understand native MCP image blocks (that is why phase-1's
> `to_image_content()` worked there). ChatGPT is different — hence the widget.

Sources:
- Apps SDK — build a custom UX: <https://developers.openai.com/apps-sdk/build/custom-ux>
- Apps SDK — set up your server: <https://developers.openai.com/apps-sdk/build/mcp-server>
- Connectors & MCP (auth surface): <https://developers.openai.com/api/docs/guides/tools-connectors-mcp>
- Community report (image not rendering from MCP result): <https://community.openai.com/t/output-markdown-with-image/1380737>

### 1.1 How tool output surfaces

Three channels, from the build docs:
- **`structuredContent`** — JSON the *model* reads and narrates. Keep it small;
  never put base64 here (the model would try to read it).
- **`content`** — markdown/text narration shown in the reply.
- **UI widget** — an HTML resource referenced from the tool's `_meta`, rendered
  in an iframe. This is the visual surface.

### 1.2 Linking a tool to its widget (`_meta`)

```json
"_meta": {
  "openai/outputTemplate": "ui://widget/inspiration.html",
  "ui": { "resourceUri": "ui://widget/inspiration.html" }
}
```

`openai/outputTemplate` is the OpenAI field; `ui.resourceUri` is for broader MCP
Apps compatibility. Use both.

### 1.3 Registering the widget resource

Register an MCP **resource** at the `ui://` URI whose mimeType is **exactly**:

```
text/html;profile=mcp-app
```

The resource body is the widget HTML (with inline/bundled JS). In the Python SDK
this is a resource handler returning that mimeType + the HTML text.

### 1.4 Getting data into the widget (and keeping it from the model)

> "The host forwards `_meta` to the component so you can hydrate UI without
> exposing the data to the model."

So the **image data URL goes in `_meta`**, not `structuredContent`. The widget
reads tool data via the `window.openai` bridge:

```javascript
const data = window.openai?.toolOutput;
// or, via notification:
window.addEventListener("message", (event) => {
  if (event.data?.method !== "ui/notifications/tool-result") return;
  const sc = event.data.params?.structuredContent;
});
```

Image display inside the widget — either a data URL (self-contained, preferred
for our ≤640px JPEG) or a fetched file URL:

```javascript
imageElement.src = "data:image/jpeg;base64,<...>";        // self-contained
// or
const { downloadUrl } = await window.openai.getFileDownloadUrl({ fileId });
```

> ⚠️ The exact field the widget reads (`window.openai.toolOutput` vs the `_meta`
> forwarding path) is the one detail to re-confirm against the live custom-ux
> reference before finalising the HTML — the docs show both a direct property and
> a postMessage notification.

### 1.5 CSP for external image domains

If the widget loads images from an external origin, allowlist it:

```json
"_meta": { "ui": { "csp": { "resourceDomains": ["https://example.com"] } } }
```

A **data URL needs no `resourceDomains` entry**, which is another reason to inline
the ≤640px preview rather than hotlink Instagram's rotating CDN hosts.

---

## 2. MCP authorization — the server is an OAuth 2.1 *resource server*

Source: MCP spec, Authorization —
<https://modelcontextprotocol.io/specification/draft/basic/authorization>

Hard requirements that fall on **our** server (the resource server):

- **MUST** implement OAuth 2.0 Protected Resource Metadata (**RFC 9728**) — i.e.
  serve `/.well-known/oauth-protected-resource` naming the authorization server.
- **MUST** answer an unauthenticated request with `401` and a `WWW-Authenticate`
  header pointing at that metadata, e.g.:

  ```http
  HTTP/1.1 401 Unauthorized
  WWW-Authenticate: Bearer resource_metadata="https://<host>/.well-known/oauth-protected-resource",
                           scope="..."
  ```

- **MUST** validate that the access token was issued **specifically for this
  server** (audience binding, **RFC 8707**). Reject wrong-audience tokens.
- **MUST** accept the token only in the `Authorization: Bearer <token>` header
  (never the query string), on **every** request. Invalid/expired → `401`;
  insufficient scope → `403` with `error="insufficient_scope"`.

What the **authorization server** (the external IdP, *not* us) handles: OAuth 2.1
with PKCE, metadata discovery (RFC 8414 / OIDC Discovery), client registration
(Client ID Metadata Documents preferred; Dynamic Client Registration supported
but deprecated), the `resource` indicator, and issuing tokens. "The
implementation details of the authorization server are beyond the scope of this
specification. It may be hosted with the resource server or a separate entity."

The client (ChatGPT) drives discovery: 401 → fetch protected-resource metadata →
find the AS → AS metadata discovery → register/PKCE → browser login → token →
retry with `Authorization: Bearer`.

---

## 3. MCP Python SDK — resource-server auth API

Source: modelcontextprotocol/python-sdk —
<https://github.com/modelcontextprotocol/python-sdk> (`examples/servers/simple-auth/`,
`src/mcp/server/auth/`).

The SDK provides the resource-server side so we don't hand-roll the metadata/401:

```python
from mcp.server.auth.settings import AuthSettings
from mcp.server.auth.provider import TokenVerifier, AccessToken
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl

class IdpTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        # validate signature (JWKS), iss, aud (RFC 8707), exp, scopes;
        # return AccessToken on success, None on failure.
        ...

mcp = FastMCP(
    "tattoo-feed",
    token_verifier=IdpTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("https://<your-idp-issuer>"),
        resource_server_url=AnyHttpUrl("https://<your-public-mcp-url>"),
        required_scopes=["..."],
    ),
)
```

- `verify_token` is **async** — fits the project's `asyncio_mode=auto`.
- `resource_server_url` is the canonical audience the verifier must enforce.
- **Verify in Chunk 0** that the pinned `mcp==1.27.2` exposes
  `token_verifier=`/`AuthSettings` and serves the RFC 9728 metadata + 401
  automatically. If it does not, either bump `mcp` (approved) or add an explicit
  `.well-known/oauth-protected-resource` route + 401 middleware per §2.
- JWT validation uses **PyJWT** (`pyjwt[crypto]`, already transitively present;
  promote to a direct pin) with the IdP's JWKS.

---

## 4. Token validation specifics (what `verify_token` must check)

From §2's MUSTs, the verifier validates, in order:
1. **Signature** — against the IdP JWKS (fetch + cache; key id from the JWT
   header). Network injected for tests.
2. **`iss`** — equals the configured issuer.
3. **`aud` / resource** — equals the canonical server URI (RFC 8707). **Reject if
   absent or mismatched** — this is the confused-deputy guard.
4. **`exp` / `nbf`** — not expired / not before now.
5. **scopes** — contains the required scope(s); else insufficient-scope.

Tests generate an RSA keypair in-process, sign test JWTs, and mock the JWKS
endpoint with `respx`. No live IdP in the test path (`CLAUDE.md` §1.3).

---

## 5. Identity provider (the external AS) — human choice

The verifier is IdP-agnostic (it only needs issuer + JWKS + audience), so the IdP
is a human decision, not loop work. It must support the ChatGPT connector flow:
OAuth 2.1, RFC 8414/OIDC discovery, PKCE, RFC 8707 `resource`, and CIMD or DCR.

- **Auth0** has a documented walkthrough for exactly this (securing an MCP server
  for ChatGPT): <https://auth0.com/blog/add-remote-mcp-server-chatgpt/>
- Alternatives with MCP-auth support: Stytch, WorkOS, Descope.

The loop consumes three values as env config: **issuer URL**, **JWKS URL**,
**audience/resource identifier** (plus required scopes).

---

## 6. ngrok ingress + ChatGPT connector

Source: ngrok MCP gateway docs —
<https://ngrok.com/docs/using-ngrok-with/using-mcp>

For phase 2, ngrok is **plain TLS ingress** — auth lives in the server (§2-4), so
we do *not* use ngrok's OAuth action (which is a browser cookie-gate a
programmatic MCP client can't complete). Run the agent (or compose `ngrok`
service) forwarding the public endpoint to `server:8000`; ideally on a stable
domain so the ChatGPT connector URL doesn't churn.

**ChatGPT connector** (from §1 connectors source): add a custom connector with
the ngrok URL and Authentication = **OAuth** (ChatGPT supports no-auth or OAuth;
**not** static API-key/bearer headers — which is exactly why §2's full OAuth path
is required rather than a shared token). ChatGPT then runs the discovery/login
flow from §2 against your IdP.

---

## Source index

| Topic | URL |
|---|---|
| Apps SDK custom UX / widget | https://developers.openai.com/apps-sdk/build/custom-ux |
| Apps SDK server setup | https://developers.openai.com/apps-sdk/build/mcp-server |
| ChatGPT connectors & MCP auth | https://developers.openai.com/api/docs/guides/tools-connectors-mcp |
| Image-not-rendering report | https://community.openai.com/t/output-markdown-with-image/1380737 |
| MCP authorization spec | https://modelcontextprotocol.io/specification/draft/basic/authorization |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk |
| Auth0 × ChatGPT MCP | https://auth0.com/blog/add-remote-mcp-server-chatgpt/ |
| ngrok MCP gateway | https://ngrok.com/docs/using-ngrok-with/using-mcp |
