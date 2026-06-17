# Built for ChatGPT — the design that makes this a GPT app

A reference for *how* this MCP server is shaped specifically around ChatGPT, and
which concrete design decisions let it work as a **ChatGPT app** (via a custom
connector + Apps SDK widget) rather than a generic MCP server.

This is descriptive, not aspirational — every claim is tied to a line in the
code as it stands on `feat/remote-app`, and to the verified contracts in
`RESEARCH.md`. If you want the *general* MCP/auth mechanics, those live in
`RESEARCH.md` §§2–4 and `scratchpads/auth-wiring-seam.md`; this doc is only about
the ChatGPT-facing seams.

---

## 0. The premise — why this build exists at all

Phase 1 returned the inspiration image as a **native MCP image content block**
(`type: image`, base64). The hard, manually-confirmed finding is that **no tested
chat client displays that block to the user inline:**

- **ChatGPT** ignores image content blocks in a tool result and shows nothing
  visual at all.
- **Claude** *receives* the image (the model can reason about it) but **does not
  render it in the conversation** — a Claude client limitation found during
  manual testing. The user never sees the picture.

> ⚠️ Correction (2026-06-16): earlier drafts of this doc and `RESEARCH.md` §1
> claimed Claude renders MCP image blocks inline. That is **false** — manual
> testing showed Claude does not display them to the user. The image-block
> approach surfaces the picture to *neither* client's UI.

ChatGPT's only supported path for *visible* output from an MCP tool is the **Apps
SDK UI component** — an HTML/JS widget rendered in a sandboxed iframe. So the
entire phase-2 redesign of `next_inspiration` exists to satisfy one constraint:
**to actually show the user a picture, you must ship a widget, and ChatGPT is the
host that renders it.** Everything below follows from that.

---

## 1. The three-channel output model — and what ChatGPT does with each

ChatGPT's Apps SDK splits a tool result into three independent channels
(`RESEARCH.md` §1.1). `next_inspiration` deliberately fills all three, each for a
different consumer (`app.py:206-221`):

| Channel | Who consumes it | What we put there |
|---|---|---|
| `content` | shown as the reply text; also the **fallback** for non-Apps-SDK clients | `TextContent` with `@handle — date / caption / permalink` (`_format_post`) |
| `structuredContent` | the **model** reads & narrates this — must stay small, never base64 | `{handle, permalink, caption}` |
| widget (via `_meta`) | the **iframe**, rendered visually by the ChatGPT host | the image data URL + handle/caption/permalink |

The key design rule, straight from the Apps SDK guidance: **the image never goes
in `content` or `structuredContent`.** If the base64 blob reached the model it
would burn tokens and the model would try to "read" it. So the picture travels
only through `_meta`, which the host forwards to the iframe *without* exposing it
to the model (`RESEARCH.md` §1.4). This separation — narration for the model,
pixels for the iframe — is the heart of the GPT-app design.

---

## 2. Registering the widget as an MCP resource

The widget HTML is served as an MCP **resource** at a `ui://` URI, with a mimeType
ChatGPT recognises as an app component (`app.py:80-87`):

```python
_WIDGET_URI = "ui://widget/inspiration.html"

@mcp.resource(_WIDGET_URI, mime_type="text/html;profile=mcp-app")
def _widget_inspiration() -> str:
    return _WIDGET_PATH.read_text(encoding="utf-8")
```

Two specifics that are load-bearing for ChatGPT:

- **`ui://` scheme** — marks this resource as a UI template the host can mount in
  an iframe, distinct from ordinary data resources.
- **`mimeType` must be exactly `text/html;profile=mcp-app`** (`RESEARCH.md` §1.3).
  The `;profile=mcp-app` parameter is what tells the host "this HTML is an app
  widget," not a plain document. Drop the profile and the host won't treat it as
  a renderable component.

The resource body is the full self-contained HTML (markup + inline CSS + inline
JS) from `server/widgets/inspiration.html` — no external bundler, no asset fetch.

---

## 3. The `_meta` contract — how a tool result points at its widget

The link from the tool call to its widget is carried in the result's `_meta`
(`app.py:213-221`):

```python
_meta={
    "openai/outputTemplate": _WIDGET_URI,     # the OpenAI/ChatGPT field
    "ui": {"resourceUri": _WIDGET_URI},        # broader MCP-Apps field
    "imageDataUrl": data_url,                  # the picture (iframe-only)
    "handle": post.artist_handle,
    "caption": post.caption or "",
    "permalink": post.permalink,
}
```

What each piece does:

- **`openai/outputTemplate`** — *the* ChatGPT-specific field. It tells the ChatGPT
  host "render this tool's output using the widget at this `ui://` URI." This
  exact dotted string is a wire identifier; it cannot be renamed
  (`RESEARCH.md` §1.2).
- **`ui.resourceUri`** — the same pointer in the more neutral MCP-Apps spelling.
  We set both so the result is understood by ChatGPT *and* any other Apps-aware
  host (`RESEARCH.md` §1.2 says "use both").
- **`imageDataUrl` + handle/caption/permalink** — the hydration payload. These sit
  in `_meta` precisely so the host forwards them to the iframe but keeps them out
  of the model's view.

---

## 4. The data bridge inside the widget (`window.openai`)

The widget HTML hydrates itself from the host through the Apps SDK bridge. It
tries two paths the docs describe (`inspiration.html:31-44`, `RESEARCH.md` §1.4):

```javascript
// Primary: the host sets window.openai.toolOutput before the iframe loads.
if (window.openai && window.openai.toolOutput) {
  render(window.openai.toolOutput._meta || window.openai.toolOutput);
}

// Fallback: a postMessage notification the host emits after the result arrives.
window.addEventListener("message", function (event) {
  var d = event.data;
  if (!d || d.method !== "ui/notifications/tool-result") return;
  render(d.params._meta || d.params.structuredContent);
});
```

Why both paths exist: the live Apps SDK reference showed *both* a direct
`window.openai.toolOutput` property and a `ui/notifications/tool-result`
postMessage, and it wasn't certain which one ChatGPT would deliver first
(`RESEARCH.md` §1.4 ⚠). Implementing both makes the widget robust to whichever
the host uses — the primary path covers "data already present at load," the
listener covers "data arrives after load."

`render(meta)` then just paints `<img src=meta.imageDataUrl>` plus the handle,
caption, and permalink link (`inspiration.html:21-29`). Note `window.openai` is
the **ChatGPT host's** injected object — this is the single most ChatGPT-specific
line in the codebase. A host that doesn't inject it leaves the widget unhydrated.

---

## 5. Why a data URL, not a hotlinked image

The image is base64-inlined into a `data:image/jpeg;base64,...` URL
(`app.py:201-205`) rather than passed as an Instagram CDN link. This is a ChatGPT
sandbox decision (`RESEARCH.md` §1.5):

- An Apps SDK iframe enforces a CSP. Loading an image from an external origin
  requires allowlisting that origin via `_meta.ui.csp.resourceDomains`.
- Instagram serves images from **rotating** CDN hostnames, so a static allowlist
  would be brittle.
- **A `data:` URL needs no `resourceDomains` entry** — it's self-contained. Since
  the preview is already downscaled to ≤640px (cheap to inline), the data URL is
  the simpler, sandbox-friendly choice and sidesteps CSP entirely.

So the imaging pipeline (fetch → downscale → strip EXIF → base64) feeds directly
into the widget hydration payload with no external image request from the iframe.

---

## 6. The OAuth layer is shaped to the ChatGPT connector specifically

ChatGPT connects to a remote MCP server as a **custom connector**, and for
anything beyond no-auth it supports exactly one auth style: **OAuth** — *not*
static API-key/bearer headers (`RESEARCH.md` §6). That single fact dictates the
whole auth design:

- We cannot ship a shared secret. We must be a full **OAuth 2.1 resource server**
  so ChatGPT's connector can run its discovery → login → token flow.
- The server therefore implements the resource-server MUSTs (`RESEARCH.md` §2),
  all driven by what the ChatGPT connector expects:
  - serve `/.well-known/oauth-protected-resource` (RFC 9728) so the connector can
    discover the authorization server,
  - answer unauthenticated calls with `401` + `WWW-Authenticate: Bearer
    resource_metadata=...` so the connector knows where to start,
  - validate **audience** (RFC 8707) so a token minted for some *other* service
    can't be replayed against ours.
- The discovery/login choreography (`RESEARCH.md` §2 end) is literally "the client
  (ChatGPT) drives discovery: 401 → fetch metadata → find AS → register/PKCE →
  browser login → retry with Bearer." The server is built to be the passive end
  of exactly that dance.

In the SDK, most of this is automatic once `mcp.settings.auth` and the verifier
are set — the 401 challenge and the RFC 9728 metadata document are emitted by
FastMCP itself (see `REVIEW.md` notes 2 & 5, and `scratchpads/auth-wiring-seam.md`
for how the verifier is attached).

### Why ngrok is *only* TLS ingress

ngrok has its own OAuth "action," but it's deliberately **not** used
(`RESEARCH.md` §6). That gate is a browser-cookie wall, which a programmatic MCP
client like the ChatGPT connector can't complete. So ngrok is reduced to plain
public TLS forwarding to `server:8000`, and *all* auth lives in the server where
the connector's OAuth flow can reach it. A **stable ngrok domain** is recommended
so the connector URL — and the RFC 8707 audience bound to it — don't churn on
restart (`REVIEW.md` note 4).

---

## 7. End-to-end: what happens when ChatGPT calls `next_inspiration`

Putting the pieces together, one call flows like this:

1. ChatGPT (custom connector, OAuth) sends `Authorization: Bearer <jwt>` to
   `/mcp`. The SDK middleware runs `IdpTokenVerifier.verify_token`; bad/expired/
   wrong-audience → `401`/`403`, never reaches the tool.
2. The tool runs core logic: pick an unseen post, fetch + downscale the image.
3. It returns the three channels: `content` (text), `structuredContent`
   (handle/permalink/caption for the model), and `_meta` (the data URL +
   `openai/outputTemplate` pointing at the widget).
4. The ChatGPT host sees `openai/outputTemplate`, fetches the `ui://` resource
   (the `text/html;profile=mcp-app` HTML), and mounts it in a sandboxed iframe.
5. The host injects `window.openai.toolOutput` (and/or posts the
   `ui/notifications/tool-result` message). The widget's script reads `_meta` and
   paints the `<img>` + handle/caption/permalink.
6. The model, meanwhile, only ever saw the small `structuredContent` and the
   `content` text — never the base64 — so it narrates "@handle posted … see the
   image above" without choking on a megabyte of pixels.

The picture appears inline in ChatGPT; the model stays cheap and clean.

---

## 8. The complete list of ChatGPT-specific seams

If you ever port this to another host, these are the exact points coded to
ChatGPT/Apps-SDK conventions (everything else is plain MCP):

| Seam | Location | Why it's ChatGPT-specific |
|---|---|---|
| Widget-instead-of-image at all | `next_inspiration`, `app.py:180-221` | ChatGPT won't render image content blocks (§0) |
| `openai/outputTemplate` `_meta` key | `app.py:214` | OpenAI-defined wire field |
| `mimeType=text/html;profile=mcp-app` | `app.py:84` | Apps SDK component marker |
| `window.openai.toolOutput` bridge | `inspiration.html:34-35` | host object injected by ChatGPT |
| `ui/notifications/tool-result` listener | `inspiration.html:39-43` | Apps SDK notification name |
| data-URL image (CSP avoidance) | `app.py:201-205` | Apps SDK iframe CSP (§5) |
| OAuth-only (no API key), RFC 9728/8707 | `server/auth.py`, `main()` | ChatGPT connector supports only OAuth (§6) |
| ngrok as TLS-only ingress | `docker-compose.yml`, `RESEARCH.md` §6 | connector can't pass ngrok's cookie gate |

The genuinely portable layer is everything under `src/tattoo_feed/` *outside*
`server/` (the `core`), plus the auth verifier's JWT logic, plus the non-widget
tools — all of which any MCP host can use unchanged.

---

## 9. The honest limitation (ChatGPT is the only client that shows the image)

**Only an Apps-SDK host (ChatGPT) renders the picture to the user.** In any other
client, `next_inspiration` shows the text only (handle/caption/permalink): the
widget's `window.openai` bridge is never satisfied, so the image doesn't appear.
This is not a phase-2 regression — the image-block approach didn't show the
picture to the user in Claude *or* ChatGPT either (§0). Phase 2 is what made the
image visible at all, by adopting the one mechanism (the ChatGPT widget) that
renders it inline.

There is **no dual-render fallback worth adding.** Re-including a native
`ImageContent` block alongside the widget would not help: it doesn't render to
the user in Claude (the limitation that motivated this build) and ChatGPT ignores
it. So the single-channel-to-widget design is not a compromise — it's the only
thing that works. The product therefore commits to the ChatGPT/HTTP connector;
stdio and other clients are dev/test surfaces, not places the image renders.

---

## One-paragraph summary

This is a ChatGPT app, not just an MCP server, because ChatGPT can't render image
content blocks: `next_inspiration` returns a three-channel result — text in
`content`, small metadata in `structuredContent` for the model, and the actual
picture as a base64 data URL in `_meta` — and points ChatGPT at an HTML widget via
`_meta["openai/outputTemplate"]`. The widget is an MCP resource served as
`text/html;profile=mcp-app` at a `ui://` URI; inside the iframe it hydrates from
the ChatGPT-injected `window.openai.toolOutput` bridge (with a
`ui/notifications/tool-result` postMessage fallback) and paints the image, keeping
the base64 away from the model. The auth layer is a full OAuth 2.1 resource server
(RFC 9728 metadata + RFC 8707 audience binding) precisely because ChatGPT's
connector speaks only OAuth, and ngrok is reduced to plain TLS ingress so the
connector's OAuth flow lands on the server, not on ngrok's cookie gate.
