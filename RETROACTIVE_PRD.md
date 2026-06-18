# PRD.md — Tattoo Pal (retroactive, illustrative)

> **This is a retroactive PRD, written for illustration — it is not a governing
> document.** Tattoo Pal was built from an implementation plan (`PLAN.md`), a
> technical contract reference (`RESEARCH.md`), process governance (`CLAUDE.md`),
> and an acceptance checklist (`REVIEW.md`). None of those is a product
> requirements document. This file reconstructs what a PRD *would* have said,
> deliberately at product altitude — the **why / for whom / what "good" means** —
> and stays **solution-agnostic** (no MCP, widgets, OAuth, ChatGPT, or file
> layout in the requirements). Its purpose is to show how a PRD differs from the
> build-step context the project was actually given. Where it conflicts with the
> shipped docs, the shipped docs win; this is a teaching artifact.

---

## 1. Summary

A creative companion, used from inside an everyday AI chat, for spending time with
the work of tattoo artists you admire **without** going to Instagram to do it. It
brings their recent work to you one piece at a time — somewhere calm and bounded,
not an endless algorithmic feed — so you can sit with it, react, keep what
resonates, and over time see how your own taste manifests across real work. The
point is less "find the tattoo I'll get" and more "engage with the work I love, on
my own terms."

## 2. Problem & motivation

The friction isn't that people don't know their taste — it's the *channel*. The
only practical way to spend time with the artists they love is Instagram, and
Instagram is not built for simply looking at art. Its feed is engineered to
capture and hold attention: an infinite, algorithmic scroll that turns "I want to
see some tattoo work" into half an hour of being pulled toward whatever keeps you
there. Wanting to explore creative work, and being obligated to do it inside an
attention-extraction machine, are in direct tension — and the machine usually wins.

This companion removes that obligation. It brings an artist's recent work into a
calm, bounded space — one piece at a time, on the user's terms, with no feed to
fall into — so attention stays on the *work*. And because the work arrives
deliberately rather than in a blur, the user can actually notice and deepen their
understanding of **how their taste manifests in real pieces** — exactly what the
scroll works against. That visual, one-at-a-time, "show me something and let me
react" rhythm fits a conversational companion well — *if* the images can be seen
in the conversation and the companion can remember what resonated and reflect it
back.

## 3. Target user

The **individual who wants the work without the platform** — someone who admires
specific tattoo artists and wants to spend time with their work calmly and
intentionally, free of the algorithmic feed. They already have taste; what they
want is to engage with real work on their own terms and deepen their sense of how
that taste shows up. They may be working toward a tattoo or simply developing
their eye; the companion serves the taste, not a booking deadline. They are not a
studio, not a content republisher, and not managing other people's accounts.
Single user, their own taste, their own shortlist.

## 4. Goals & success criteria

Product-level outcomes (how we'd know it worked), not engineering gates:

1. **Exploration works end-to-end.** A user can run a full session — bring
   together recent work, sit with it one piece at a time, react, and keep what
   resonates — without leaving their chat.
2. **The image is actually seen.** When the companion surfaces a piece of
   inspiration, the user *sees the image in the conversation*, not a link or a
   description.
3. **Curation persists.** Saved pieces and recorded taste survive across
   sessions and can be reloaded later, so the shortlist compounds over time.
4. **It feels trustworthy.** Each saved piece keeps its attribution (which artist,
   where to find the original), and only the intended user can reach their data.
5. **Calm by design.** The experience is bounded and intentional — no infinite
   feed, no engagement-maximising recommendations. The user looks at what they
   asked for and leaves when *they're* done, not when the product decides to
   release them.

A reasonable headline metric: *over repeated sessions a user builds up a
shortlist and a taste record that persist intact and increasingly capture how
their taste manifests across real work — engaged with on their own terms, not a
feed's.*

## 5. Requirements (what the user must be able to do)

Stated as outcomes, not mechanisms.

- **R1 — Choose who to follow.** The user can build and edit the set of artists
  they want to track by naming each one; the companion confirms an artist can be
  tracked or clearly explains why not (e.g. not a reachable professional account).
- **R2 — See a merged, recent view.** The user can ask for a single combined
  stream of recent work across everyone they follow, newest first, without
  visiting each artist separately.
- **R3 — Discover one piece at a time, with the image visible.** The user can ask
  for "something new," see one piece — **image rendered inline in the
  conversation** — react, and ask for the next, without being shown the same
  piece twice.
- **R4 — Save and revisit favourites.** The user can bookmark a piece into a
  personal shortlist and later review that shortlist.
- **R5 — Remember taste, with consent.** The user can record notes about what
  they like; the companion proposes the wording and only saves it once the user
  confirms. The user can reload their taste in a future session.

Non-functional expectations:

- **Attribution travels with content.** Every surfaced or saved piece carries the
  artist's identity and a way back to the original.
- **Respectful of the source.** Inspiration is for personal discovery, not
  republishing; previews are lightweight copies, not full-resolution downloads.
- **Private to its owner.** Only the authorised user can reach their followed
  list, shortlist, and taste notes.
- **Durable.** Curation data is not lost between sessions.

## 6. Scope & non-goals

In scope: personal, read-only discovery and curation for one user.

Explicit non-goals (product decisions, not technical ones):

- **No feed, no algorithm.** The companion deliberately does not optimise for
  engagement or attention: no infinite scroll, no recommendation engine tuned to
  keep the user looking. Surfacing work one piece at a time, only when asked, is
  the point — it is the opposite of the platform it stands in for. *(This is the
  founding motivation, stated as a hard non-goal so it can't quietly erode.)*
- **No publishing.** The product never posts, comments, messages, or otherwise
  writes back to the source — strictly read-and-curate.
- **No video.** Moving content is out of scope; this is about still imagery.
- **No multi-account / multi-user management.** One collector, their own follows.
- **Not a briefing or booking tool.** It helps the user understand their own
  taste; turning that into a brief, a consultation, or a booking with an artist
  happens elsewhere.

## 7. Constraints & assumptions

- **Delivered inside an existing AI chat**, not as a standalone app or website —
  the user is already in a conversation and we meet them there.
- **Depends on the source platform's data access** for an artist's recent public
  work, and on the assumption the user genuinely follows/has rights to view it.
  Worth being honest about the scope of the "without Instagram" promise: the
  companion removes the user's exposure to the *feed and its algorithm*, not the
  system's dependence on Instagram as the data source — the work is still fetched
  from the platform behind the scenes. The win is attentional, not infrastructural.
- **One artist-data source account per deployment** is assumed sufficient for a
  single collector.
- **Discovered constraint (the kind a PRD captures once learned):** not every AI
  chat client will display, inline in the conversation, an image the companion
  returns from a tool. Because R3 ("the image is actually seen") is a hard
  requirement, the *choice of client*
  is constrained to one that can render the image in the conversation. The PRD
  states the need; engineering determines which clients satisfy it. *(This is
  exactly the finding that `RESEARCH.md` recorded and `PLAN.md` then designed
  around — here it appears as a constraint on a requirement, not as a build step.)*

## 8. Open questions & risks

- **Taste capture quality.** Will free-text taste notes be specific enough to
  genuinely reflect the user's taste back to them, or do they need structure to
  surface patterns?
- **Exploration fatigue.** One-at-a-time is calm but slow; is there a point where
  the user wants a grid or batch view (currently a non-goal)?
- **Source-access fragility.** Reliance on an external platform's access is a
  standing risk to R1–R3 if that access changes.
- **Longevity of the shortlist.** Saved pieces point back to originals that may be
  deleted by the artist; how should the product behave when an original disappears?

---

## Appendix — how this differs from what the build was given

For the teaching point that prompted this file:

| This PRD | `PLAN.md` (what the loop got) |
|---|---|
| "The user sees the image inline in the conversation" (R3) | "Chunk 3: return an Apps SDK widget with the image data URL in `_meta`, registered as a `ui://` resource" |
| "Private to its owner" (non-functional) | "Chunk 2: OAuth 2.1 resource server, RFC 9728 metadata, RFC 8707 audience binding" |
| Success = a user completes a discover-and-save session and reloads it later | Success = the gate is green (ruff/mypy/pytest ≥90%) and the eyeball checks pass |
| Names the problem, the user, and the outcome; picks no technology | Names the components, the file layout, and the build order |

A PRD sits **upstream**: it would have fed the tech reference and the
implementation plan, not replaced them. The product intent here was real but, in
the actual build, lived *implicitly* inside `PLAN.md`'s preamble and non-goals
rather than in a document a non-engineer could read on its own.
