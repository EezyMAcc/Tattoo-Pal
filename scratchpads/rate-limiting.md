# Rate limiting in tattoo-feed — from first principles

A reference for how this repo deals with Instagram/Meta rate limits: what rate
limiting *is*, what the code actually does today, why that's a fair fit for a
single user, and where more deliberate request-tracking would buy real
reliability. Written to be read cold — no prior knowledge of rate limiting
assumed.

Grounded in the actual source as of this writing:
- `src/tattoo_feed/graph/client.py` — the only place that calls Meta.
- `src/tattoo_feed/errors.py` — the `RateLimitedError` type.
- `src/tattoo_feed/server/app.py` — how the client is built and shared.

> **Verified against Meta's live docs (2026-06-17).** Sources: the Graph API
> rate-limiting page (`developers.facebook.com/docs/graph-api/overview/
> rate-limiting`) for the framework, and Meta's **Instagram Platform** rate-limit
> section for the endpoint-specific rule. The decisive line:
> *"Business Discovery and Hashtag Search API are subject to **Platform Rate
> Limits**."* So `business_discovery` is governed by the app-level Platform limit
> (`200 × users` / hour, header `X-App-Usage`, error codes `4/17/32`) — **not** by
> the Instagram Business-Use-Case limit. **Our code's `{4, 17, 32}` is therefore
> correct; there is no `80002` gap.**
>
> > **Correction (2026-06-17).** An earlier revision of this doc wrongly inferred
> > that `business_discovery` was a BUC call and flagged a "missing `80002`" as a
> > live bug. Meta's Instagram-Platform note above explicitly contradicts that —
> > Business Discovery is Platform-limited. The inference has been retracted
> > throughout. Lesson: verify the *endpoint-specific* note, don't extrapolate
> > from the general framework (exactly what CLAUDE.md §1.6 warns about).

---

## Part 0 — background you need first

If you already know what a 429 is and how Meta's quota headers work, skip to
Part 1. Everything after only makes sense once these are clear.

### 0.1 What "rate limiting" actually is, and why APIs do it

A rate limit is a cap on **how many requests you may make in a window of time**.
Instagram's servers are shared by millions of apps; if any one app could call as
fast as it liked, a bug or a busy moment could swamp them. So Meta says, in
effect: *"you get N calls per hour; past that, I stop answering until the window
rolls forward."*

The key mental model: a rate limit is a **bucket that refills over time**. Every
call you make takes a token out of the bucket. Tokens drip back in as the window
advances. While there are tokens, you're served normally. When the bucket is
empty, further calls are **rejected** — not because anything is broken, but
because you've spent your allowance. Wait a bit, tokens refill, you're served
again.

This is why rate-limit errors are fundamentally different from other failures:
they are **temporary and self-healing**. A "not found" error means *retrying
won't help*. A rate-limit error means *retrying later is exactly the fix*. That
distinction is why the code gives rate limiting its own typed error and its own
retry path (Part 1).

### 0.2 The two ways an API tells you you're rate-limited

There are two signals, and Meta uses **both** — which is why the code checks for
both (this trips people up):

1. **The HTTP status code `429 Too Many Requests`.** This is the standard,
   protocol-level "slow down," and may carry a `Retry-After` header. **But note
   (verified 2026-06-17):** Meta's rate-limiting docs say errors are *"returned in
   JSON response bodies with the error codes"* and **do not specify a distinct
   HTTP status** — in practice Meta often returns `400` (or `200`) with the error
   in the body, *not* always a clean `429`. So signal 2 is at least as important.

2. **A normal-looking response (HTTP 200 or 400) whose JSON body contains a
   rate-limit *error code*.** Meta puts an error object in the body like
   `{"error": {"code": 4, ...}}`. Because `business_discovery` is governed by
   **Platform Rate Limits** (Part 0.3), the codes that matter for us are the
   Platform ones: `4` (app limit), `17` (user limit), `32` (Pages token), and
   `613` (custom limit). (The Business-Use-Case codes like `80002` are a separate
   range that does **not** apply to this endpoint — see the correction at the top.)

So "am I rate-limited?" is really two questions: *was the status 429?* **and**
*does the body carry one of `4/17/32`?* The client checks both — and `{4, 17, 32}`
is the right set for this Platform-limited endpoint.

### 0.3 What Meta's limits actually are (verified 2026-06-17)

Meta runs **two** rate-limit frameworks. The important fact for us is **which one
`business_discovery` falls under** — and Meta answers it explicitly.

**1. Platform rate limits** — apply to calls made with an app or user access
token. The app-level formula, quoted verbatim:

> `Calls within one hour = 200 * Number of Users`

…where "Number of Users" is the app's unique **daily active users**. *This is
your "200/hour"* — and for a single-user app it is almost exactly that: ~200
calls per rolling hour. Signalled by the **`X-App-Usage`** header.

**2. Business Use Case (BUC) rate limits** — apply to most Instagram Platform
endpoints, under the `instagram` BUC type, with a 24-hour window:
`Calls within 24 hours = 4800 * Number of Impressions`.

**Which one governs `business_discovery`?** Meta's Instagram Platform note settles
it verbatim:

> *"Business Discovery and Hashtag Search API are subject to **Platform Rate
> Limits**."*

So `business_discovery` is **explicitly carved out of the BUC `4800 × impressions`
formula** and governed by framework **1** — the app-level `200 × users` per
rolling hour. The header that matters is therefore **`X-App-Usage`**, and the
rate-limit error codes are the Platform ones (`4/17/32/613`), *not* the BUC code
`80002`. (This is the correction noted at the top: an earlier draft assumed the
BUC path. It does not apply here.)

**The header — your live fuel gauge.** On responses, Meta returns in `X-App-Usage`
(field names verbatim):

- `call_count` — *"percentage of calls made by your app over a rolling one hour
  period"*
- `total_time` — percentage of total time allotted for query processing
- `total_cputime` — percentage of CPU time allotted

Each is a **percentage (0–100)**; throttling kicks in when any reaches ~100.
Example: `{"call_count": 28, "total_time": 25, "total_cputime": 25}`. Note
`X-App-Usage` does **not** carry an `estimated_time_to_regain_access` field — that
exists only on the BUC header, which doesn't apply to us. So there's no
minutes-to-recovery hint here; recovery just happens as the rolling hour advances.

**The takeaway for Part 3:** Meta hands you a live fuel gauge — the three
`X-App-Usage` percentages — on every response, and this repo currently throws it
away. You don't have to *guess* whether you're near the limit; the API tells you.
Reacting only after a failure is choosing to fly without looking at the gauge.

---

## Part 1 — what this repo actually does today

All Meta traffic in the entire app flows through **one method**:
`BusinessDiscoveryClient._get()` (`graph/client.py:222`). Every artist
validation and every media fetch ultimately calls it. Because there is exactly
one choke point, rate-limit handling lives in exactly one place — which is the
right shape. Here's what that one place does.

### 1.1 The retry loop (`_get`, client.py:222-247)

`_get` wraps the HTTP call in a `while True` loop with an attempt counter:

```python
if response.status_code == httpx.codes.TOO_MANY_REQUESTS:   # the 429 case
    if attempt < self._max_retries:
        self._sleep(self._retry_after(response, attempt))    # wait, then…
        attempt += 1
        continue                                             # …try again
    raise RateLimitedError(                                  # gave up
        "Instagram rate limit hit; try again later",
        retry_after_seconds=self._retry_after(response, attempt),
    )
```

In plain terms: **on a 429, wait and retry, up to `max_retries` times; if it's
still 429 after that, give up with a typed `RateLimitedError`.** The default
`max_retries` is **2** (`__init__`, client.py:73).

### 1.2 How long it waits (`_retry_after`, client.py:259-268)

The wait time is computed two ways, in priority order:

1. **Honour the server.** If the 429 carried a `Retry-After` header, use that
   number of seconds — the server knows best when it'll serve you again.
2. **Otherwise, exponential backoff:** `2 ** attempt` seconds → **1s, then 2s,
   then 4s…**. "Exponential backoff" just means *each retry waits longer than
   the last*, so you back off harder the more the server pushes back, instead of
   hammering it at a fixed cadence.

With the default `max_retries = 2`, the worst case is: try → 429 → wait 1s → try
→ 429 → wait 2s → try → 429 → **give up** and raise, reporting `retry_after = 4s`
as a hint to the caller. So a fully rate-limited call blocks for **~3 seconds**
then fails cleanly.

> Note: this `_sleep` is a **blocking** sleep (injected `time.sleep` by default,
> client.py:75). For a single user that's harmless. It matters at concurrency —
> see 3.4.

### 1.3 The in-body error codes (`_raise_for_graph_error`, client.py:271-301)

If the response *wasn't* a clean 429 but failed some other way, `_get` hands the
body to `_raise_for_graph_error`, which maps Graph's error codes to typed
exceptions. The rate-limit branch:

```python
_RATE_LIMIT_CODES = frozenset({4, 17, 32})          # client.py:51
...
if code in _RATE_LIMIT_CODES or status_code == httpx.codes.TOO_MANY_REQUESTS:
    raise RateLimitedError(message)                  # client.py:293-294
```

This is the 0.2 point in code: it catches the "looks like 200/400 but the body
says rate-limited" case that the status-code check in 1.1 would miss. Note these
in-body rate-limit errors are **not retried** — they're raised immediately. Only
a true HTTP `429` goes through the retry loop in 1.1.

> **Confirmed correct (verified 2026-06-17 against live docs).**
> `_RATE_LIMIT_CODES = {4, 17, 32}` are **Platform** rate-limit codes, and
> `business_discovery` is governed by Platform Rate Limits (0.3, per Meta's
> explicit note) — so this set is right for this endpoint. The only arguable
> addition is `613` ("custom rate limit"), also a Platform code; a minor
> robustness call, not a bug fix.
>
> **Don't be fooled by the BUC error table.** Meta publishes a separate
> *Business-Use-Case* error-code table, and it lists **`80002` = "Instagram"** —
> which looks like it should be ours, and is exactly the trap an earlier draft
> fell into. It is **not** ours: those `80xxx` codes fire only for BUC-limited
> endpoints, and Business Discovery is carved out to Platform limits. The two code
> families are disjoint:
>
> | Family | Codes | Applies to us? |
> |---|---|---|
> | **Platform** | `4` (app), `17` (user), `32` (Pages token), `613` (custom) | **Yes** |
> | **Business Use Case** | `80000`–`80014` incl. `80002` (Instagram), `80004`, `80003`, … | No |
>
> One nuance the tables reveal: `32` is specifically a *Pages*-token limit, so for
> an Instagram call with an app/user token the codes that realistically fire are
> `4` and `17` (and maybe `613`). Keeping `32` in the set is harmless — it just
> won't trigger here — so there's no reason to remove it.

### 1.4 The typed error (`errors.py:35-47`)

```python
class RateLimitedError(TattooFeedError):
    def __init__(self, message, retry_after_seconds=None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
```

Why a dedicated type matters (the 0.1 distinction made concrete): callers can
tell "you're rate-limited, try later" apart from "that account doesn't exist,
don't bother retrying" **without string-matching error messages**. The optional
`retry_after_seconds` carries the wait hint up to whoever wants to act on it.
Every public service method documents that it may raise this (e.g.
`ArtistService.add_artist`, `services/artists.py:40`).

### 1.5 The cache — the real rate-limit defence (client.py:99, 146-157)

This is the part that does the most to keep you *under* the limit, and it's easy
to overlook because it isn't labelled "rate limiting."

`fetch_recent_media` caches its result per `(handle, limit)` for
`cache_ttl_seconds` (**default 300s = 5 minutes**, client.py:72):

```python
cached = self._cache.get(cache_key)
if cached is not None and self._clock() < cached[0]:
    return cached[1]                 # serve from memory — no network call at all
```

So calling `next_inspiration` or `get_feed` repeatedly within a 5-minute window
re-fetches an artist's media **zero times** after the first — the cache answers.
The cheapest API call is the one you never make, and the cache is what turns a
chatty usage pattern into a trickle of actual Meta traffic.

Two things to know about this cache:
- It's an **in-process dict** (client.py:99). It lives as long as the server
  process and vanishes on restart. It is not shared between processes.
- **`validate_account` is *not* cached** — only `fetch_recent_media` is. That's
  fine, because validation only runs on `add_artist`, which is rare.

### 1.6 One client, shared for the whole process (app.py:104-134)

`_build_services` creates **one** `BusinessDiscoveryClient` (and one underlying
`httpx.Client`), and `_get_services` memoises it as a lazy singleton:

```python
def _get_services() -> _Services:
    global _services
    if _services is None:
        _services = _build_services()   # built once, on first tool call
    return _services
```

The consequence that matters: because the client is a singleton, **its cache
(1.5) persists across every tool call** for the life of the server. Every
`get_feed` / `next_inspiration` / `add_artist` shares the same cache and the same
HTTP connection pool. If the client were rebuilt per request, the cache would be
useless and you'd hit Meta far harder.

---

## Part 2 — why this is a sound fit for a single user

The design is **reactive**: it does nothing about rate limits until Meta pushes
back, then it backs off politely and surfaces a clean error. For one user that's
proportionate, for concrete reasons:

- **The traffic is tiny.** One person browsing inspiration generates a handful of
  tool calls. Each tracked artist costs **one** `business_discovery` call per
  feed refresh — and the 5-minute cache (1.5) collapses repeated refreshes to
  zero calls. Realistically you'd track maybe tens of artists and refresh
  occasionally. That's nowhere near a ~200/hour ceiling.
- **There's no concurrency to coordinate.** A single user makes one request at a
  time. The blocking retry-sleep (1.2) just means *this* call pauses briefly —
  there's no second request waiting behind it, no event loop to stall, no other
  worker also hammering the same quota.
- **The failure mode is already graceful.** If you somehow do hit the limit, you
  get a typed `RateLimitedError` with a retry hint, not a crash or a confusing
  raw HTTP error. The user waits a moment and tries again — exactly the right
  response to a self-healing error (0.1).

So: **for one user, "react to 429 + cache aggressively" is the right amount of
engineering.** Building a quota-tracking subsystem for one person browsing
tattoos would be over-engineering. The honest summary is *not* "rate limiting is
unhandled" — it's "rate limiting is handled reactively, and reactive is enough at
this scale."

The rest of this doc is about what changes that calculus.

---

## Part 3 — where more intentional handling would improve reliability

Everything below is **optional for the current single-user goal**. It becomes
worth doing if usage grows: more tracked artists, more frequent refreshes,
multiple users, or background/scheduled fetching. Each item names the specific
reliability risk it removes.

### 3.1 Read the fuel gauge — track `X-App-Usage` (the biggest win)

**Risk today:** the code is *blind* until it's already been rejected. It only
learns about the limit at the moment it hits `429` — the worst possible time,
when a user is mid-action and now eats a 3-second stall and a failure.

**The fix:** Meta returns the **`X-App-Usage`** header on *every* response,
carrying the **percentage of quota already used** (0.3) — and since
`business_discovery` is Platform-limited, this is exactly the right gauge to read.
Parse its `call_count` / `total_time` / `total_cputime` (each 0–100) in `_get`
after each call and you get a live fuel gauge essentially for free. With it you
can:
- **Log a warning** as any of the three crosses, say, 80% — turning "we got
  mysteriously rate-limited" into "we saw it coming in the logs."
- **Pre-emptively slow down** (add a small delay, or refuse non-essential
  fetches) *before* hitting the wall, so you never serve a hard failure to the
  user at all.

Note the header value is a JSON string (e.g.
`{"call_count": 28, "total_time": 25, "total_cputime": 25}`), so parsing is a
`json.loads` on the header value, not a plain int.

This is the single highest-leverage change: it converts rate limiting from a
thing that *surprises* you into a thing you *observe*. Even just **logging** the
percentage (without acting on it) is a cheap, strictly-positive first step and
costs almost nothing.

### 3.2 Remember that you're limited — a shared cooldown

**Risk today:** rate-limit state is rediscovered per call. If artist A's fetch
hits `429`, the *very next* `get_feed` will still cheerfully try artist B, C, D…
against an API you already know is refusing you — each one burning the full
retry budget (3s of blocking sleep) before failing. A feed of 10 artists could
stall for 30 seconds, all of it pointless.

**The fix:** when a rate-limit is hit, record a single `rate_limited_until`
timestamp on the client. Since `business_discovery` is Platform-limited, there's
no `estimated_time_to_regain_access` hint to lean on (that's a BUC-only field,
0.3) — so derive the timestamp from the `Retry-After` header if present, otherwise
fall back to a fixed cooldown (the rolling-hour window means a conservative
default like a few minutes is reasonable). While that timestamp is in the future,
**fail fast** — raise `RateLimitedError` immediately without touching the network.
One stored timestamp turns a 30-second cascade of doomed retries into one instant,
honest "try again shortly." You could also drive this proactively off the
`X-App-Usage` percentages (3.1): if `call_count` is already ~100, set the cooldown
*before* the next call even fails.

### 3.3 Make the cache survive restarts (and maybe be shared)

**Risk today:** the cache is an in-process dict (1.5). Restart the server — a
deploy, a crash, the container bouncing — and it starts **cold**, re-fetching
every artist from Meta on the first feed load. Frequent restarts erase the
protection the cache provides. And if you ever run more than one server process,
each has its own cache, multiplying the real call rate.

**The fix:** back the cache with something persistent (the existing JSON data
dir is the natural home, or a small key-value store) so warmth survives a
restart. A shared cache only matters once there's more than one process — not a
single-user concern, but the thing to reach for first if you scale out.

### 3.4 Don't block the server on retries (matters under concurrency)

**Risk today:** `_retry_after`'s wait is a **blocking** `time.sleep` (1.2). With
one user that just pauses their one request. But the MCP server runs on an async
event loop; a blocking sleep inside a request can stall *other* in-flight
requests sharing that loop. The moment there's a second concurrent user, one
person's rate-limit backoff can freeze everyone else's calls for those seconds.

**The fix:** when/if tools become async, swap the blocking sleep for a non-
blocking `await asyncio.sleep(...)` on the async path (the `sleep` callable is
already injected, so the seam exists). Strictly a concurrency concern — ignore it
while it's genuinely one user, but know it's lurking.

### 3.5 Smaller, lower-priority hardening

- **Add jitter to the backoff.** Pure `2 ** attempt` means many clients retry in
  lockstep ("thundering herd"). Adding a small random fraction spreads them out.
  Irrelevant for one user; standard practice at scale.
- **Handle HTTP-date `Retry-After`.** `_retry_after` only parses a numeric
  seconds value (client.py:262-266); the HTTP spec also allows an absolute date.
  Meta usually sends seconds (or nothing), so this is a minor robustness gap, not
  a live bug.
- **Consider caching `validate_account`** if `add_artist` ever gets called in
  bulk. Today it's rare enough not to matter (1.5).

---

## Part 4 — the shortest path, if you only do one thing

The live-docs review (2026-06-17) confirmed the existing rate-limit *classification*
is correct (Platform codes `{4, 17, 32}`, Part 1.3) — so there's no bug to fix
here, contrary to an earlier draft of this doc. The single worthwhile improvement,
even at single-user scale, is observability:

> **Parse `X-App-Usage` in `_get` and log the three percentages** (3.1). It's a
> few lines, it can't break anything (you're only reading a header and logging),
> and it turns the whole rate-limit question from invisible into observable. Once
> you can *see* your usage in the logs, every later decision — cooldowns, cache
> persistence — becomes evidence-driven instead of guesswork.

Everything else is "when usage grows," in roughly this order:
**3.2 (fail fast with a cooldown) → 3.3 (persist the cache) → 3.4 (non-blocking
backoff, once concurrent).**

---

## One-paragraph summary

All Meta traffic funnels through one method, `BusinessDiscoveryClient._get`,
which handles rate limits **reactively**: on a true `429` it retries with
exponential backoff (1s, 2s) up to twice, honouring any `Retry-After` header,
then raises a typed `RateLimitedError`; it also catches Meta's in-body rate-limit
codes `{4, 17, 32}`. The real defence against ever hitting the limit is the
5-minute per-`(handle, limit)` cache on a process-wide singleton client, which
collapses repeated feed/inspiration calls to zero network traffic. For a single
user this is proportionate and correct — traffic is tiny, there's no concurrency,
and failures are graceful. The 2026-06-17 live-docs check **confirmed the code's
classification is right**: Meta states explicitly that Business Discovery is
subject to **Platform Rate Limits** (not Business-Use-Case), so the binding limit
is the app-level `200 × daily-active-users` per rolling hour (your "200/hour"),
the relevant header is `X-App-Usage`, and the rate-limit codes are the Platform
`4/17/32` the code already catches — the BUC code `80002` does *not* apply here
(an earlier draft wrongly claimed it did; retracted). So there is **no bug** to
fix. The one thing the code *doesn't* do is **look at the quota it's spending**:
the `X-App-Usage` percentages are reported on every response and ignored. The
single worthwhile change, even now, is to parse and log that header; beyond that,
scaling up would justify a "rate-limited-until" cooldown, a restart-surviving
cache, and non-blocking backoff once requests run concurrently.
