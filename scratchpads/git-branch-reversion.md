# Reverting a branch to a pre-build state — keeping the old work as a reference

Distilled, reusable reference for **rewinding a feature branch to an earlier
commit** while (a) keeping the abandoned commits recoverable forever via a tag,
and (b) preserving unrelated uncommitted work in progress.

This is the clean version of what was done on `feat/remote-app` on 2026-06-15,
when the phase-2 build had to be undone and re-run with a different mechanism.

**Verified working: 2026-06-15 (macOS / Apple Silicon host).**

---

## The mental model

A branch name (`feat/remote-app`) is just a **movable pointer to one commit**.
"Reverting the branch" here does *not* mean `git revert` (which adds new commits
that undo old ones). It means **moving the pointer back** to an earlier commit so
the later commits are no longer on the branch.

Three things you usually want at once, and they need three different tools:

1. **Don't lose the abandoned commits** → put a **tag** on the old tip first. A
   tag is a permanent named pointer; the commits stay reachable (and clonable,
   diffable, cherry-pickable) forever, even after the branch moves off them.
2. **Move the branch pointer back** → `git reset` to the target commit.
3. **Decide what happens to the files on disk** → the `--soft` / `--mixed` /
   `--hard` flag of `git reset` controls exactly that (see below). This is where
   you protect unrelated work-in-progress.

> Commits are never really "deleted" by moving a branch — they linger in the
> **reflog** for ~90 days and are reachable by hash. A tag just makes that
> explicit and permanent. Tag anyway; it costs nothing and saves panic.

---

## The reset flags — the one thing to get right

Same "move the pointer to <commit>", three behaviours for your files:

| Flag | Branch ptr | Index (staging) | Working tree (your files) | Use when |
|---|---|---|---|---|
| `--soft`  | → target | left as-is | **untouched** | you want the old commits' changes back as staged edits |
| `--mixed` (default) | → target | reset to target | **untouched** | you want the changes back as *unstaged* edits to sort through |
| `--hard`  | → target | reset to target | **reset to target (changes destroyed)** | you want everything gone, no survivors |

**`--hard` deletes uncommitted work with no reflog safety net.** If you have
unrelated changes in progress (or aren't 100% sure), use `--mixed` and clean up
deliberately. That's the safe default for "rewind but keep my other edits."

---

## Recipe A — clean rewind, nothing else in progress

The simple case: the branch only has the commits you want gone, and the working
tree is clean.

```bash
# 1. Anchor the abandoned work with a tag (do this BEFORE moving anything).
git tag <keep-name> <old-tip>          # e.g. git tag phase2-oneshot-build dc6a761
#    <old-tip> can be a hash, or just HEAD if you're sitting on it.

# 2. (Optional) anchor the point you're rewinding TO, so future tooling/loops
#    have a stable name for "the baseline".
git tag <base-name> <target>           # e.g. git tag phase2-base d8837a9

# 3. Move the branch pointer back, discarding the commits' file changes too.
git reset --hard <target>              # e.g. git reset --hard d8837a9

# 4. Verify.
git log --oneline -5                   # tip should now be <target>
git tag -l                             # your keep/base tags are listed
```

To get the abandoned work back later: `git checkout <keep-name>`, or branch from
it (`git branch recovered <keep-name>`), or diff it (`git diff <base> <keep-name>`).

---

## Recipe B — rewind but PRESERVE unrelated work-in-progress (what we did)

The real-world case: the branch tip had **two different kinds of change mixed
together** — the build commits we wanted gone, *plus* uncommitted reorg edits we
wanted to keep. `--hard` would have destroyed the reorg. So: `--mixed`, then
surgically restore/remove only the build files.

This works cleanly **only because the two change-sets were disjoint** — verify
that first.

```bash
# 0. SEE what each side touched. List the files the doomed commits changed:
git diff --name-status <target> <old-tip>
#    A = added by those commits, M = modified, D = deleted.
#    And confirm your work-in-progress files are NOT in that list:
git status --short

# 0b. Sanity: confirm files you're keeping are identical at <target> and <old-tip>
#     (i.e. the commits never touched them, so your edits rebase cleanly):
git diff --quiet <target> <old-tip> -- <file-you-keep> ... \
  && echo "identical — safe" || echo "they DIFFER — be careful"

# 1. Tag the abandoned tip (keep it forever) and, optionally, the baseline.
git tag <keep-name> <old-tip>
git tag <base-name> <target>

# 2. MIXED reset: move the branch pointer back, but leave EVERY file on disk
#    exactly as it is. Now the build commits' changes show up as ordinary
#    uncommitted edits, sitting alongside your work-in-progress.
git reset --mixed <target>

# 3. Surgically undo ONLY the build changes:
#    3a. Files the commits MODIFIED (M) — restore the <target> version:
git checkout <target> -- <modified-file> <modified-file> ...
#    3b. Files the commits ADDED (A) — they don't exist at <target>, so
#        `git checkout <target> -- <file>` would error; just delete them:
rm -f <added-file> <added-file> ...
#    3c. Remove now-empty directories the commits introduced:
rmdir <new-dir> 2>/dev/null || true

#    Leave your work-in-progress files alone in all of step 3.

# 4. Verify the tree is now "<target> + only my kept edits". This diff should
#    show ONLY your work-in-progress, nothing from the build:
git diff <target> -- . \
  ':(exclude)<kept-file-1>' ':(exclude)<kept-file-2>' ...
#    (empty output = the only differences from <target> are the paths you excluded)

# 5. Confirm the abandoned work is safe and the baseline still builds:
git show -s --format='%h %s' <keep-name>
# ...then run your test/lint gate to prove the rewound tree is green.
```

### The concrete instance (for reference)

```bash
git tag phase2-oneshot-build dc6a761          # keep the abandoned build
git tag phase2-base          d8837a9          # name the baseline for the loop
git reset --mixed d8837a9                     # rewind ptr, keep all files on disk
git checkout d8837a9 -- .env.example README.md REVIEW.md pyproject.toml uv.lock \
                        src/tattoo_feed/config.py ... tests/test_config.py ...
rm -f Dockerfile.server docker-compose.yml ... src/tattoo_feed/server/auth.py ...
rmdir scripts src/tattoo_feed/server/widgets
git diff d8837a9 -- . ':(exclude).gitignore' ':(exclude)run-loop.sh' ...   # -> empty
```

---

## Gotchas learned the hard way

- **Tag before you reset, always.** Once the branch moves you're relying on the
  reflog and raw hashes; a tag turns "I hope it's still in the reflog" into a
  name you can't lose.
- **`--hard` has no undo for the working tree.** Reflog recovers *commits*, not
  uncommitted edits a `--hard` wiped. Default to `--mixed` when unsure.
- **Filenames with spaces / odd chars** (we had `build_artifacts/Phase 2/`):
  quote them, and prefer letting them sit untracked rather than scripting `rm`
  over them.
- **`[chunk N]`-style markers repeat across builds.** Counting them with
  `git log | grep` caught *phase-1* commits too. Scope every range query to the
  segment you care about: `git log <base>..HEAD`, anchored by the `<base-name>`
  tag from step 1. This is exactly why tagging the baseline pays off.
- **A `--mixed` reset leaves ADDED files as untracked, not deleted.** Step 3b is
  a real `rm`, not a `git checkout`.
- **Prove it, don't assume it.** The `git diff <target> -- . ':(exclude)...'`
  check in step 4 is the difference between "I think the build is gone" and
  "the only diffs from baseline are my four kept files."

---

## Cleaning up the tags later

The keep-tag is cheap to leave in place. When you're sure you'll never want the
abandoned work back:

```bash
git tag -d <keep-name>                 # delete locally
git push origin :refs/tags/<keep-name> # delete on the remote, if you pushed it
```

Until then, leave it — a stale tag costs nothing; a lost branch costs an evening.
