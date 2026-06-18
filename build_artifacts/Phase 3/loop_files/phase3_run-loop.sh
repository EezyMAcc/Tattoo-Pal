#!/usr/bin/env bash
#
# Launch the tattoo-feed dev container for the PHASE 3 build (the auth-wiring
# refactor on branch refactor/auth).
#
#   ./phase3_run-loop.sh           Drop into an interactive shell in the
#                                  container, with this project folder mounted
#                                  at /workspace.
#   ./phase3_run-loop.sh --build   Run the phase-3 build UNATTENDED: execute
#                                  ./phase3_build-loop.sh inside the container,
#                                  which drives the build ONE chunk per fresh
#                                  `claude` process (fresh context per chunk).
#                                  See phase3_build-loop.sh.
#
# Isolation boundary (read this):
#   -v "$PWD":/workspace mounts ONLY the current folder into the container.
#   The container can read and write THIS folder and nothing else on your
#   Mac — not your home directory, not other projects, not system files.
#   Anything the container writes under /workspace appears instantly in this
#   folder on the host, and vice versa, because it is one shared folder, not
#   a copy. Everything outside /workspace inside the container is the
#   image's own throwaway filesystem and is discarded when the container
#   exits (--rm).
#
#   The one other thing passed in from the host is the CLAUDE_CODE_OAUTH_TOKEN
#   environment variable (your Claude Code login) — see below. No host files
#   besides this folder are shared. Per CLAUDE.md "Where the build runs", NO
#   production secrets enter the build container: the phase-3 gate is hermetic
#   and the refactor needs no Instagram / IdP / ngrok credentials.
set -euo pipefail

# Resolve this script's own directory so the mount is correct no matter where
# the script is invoked from.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Claude Code auth: forward CLAUDE_CODE_OAUTH_TOKEN from the host so `claude` is
# logged in inside the (ephemeral, --rm) container without an interactive browser
# login — which does not work well from a container and would not persist anyway.
# Generate it ONCE on the host:  claude setup-token
# then:                          export CLAUDE_CODE_OAUTH_TOKEN=<token>
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    echo "warning: CLAUDE_CODE_OAUTH_TOKEN is not set on the host." >&2
    echo "         'claude' will fall back to an interactive login inside the" >&2
    echo "         container (fiddly, and wiped on exit). To avoid that, run" >&2
    echo "         'claude setup-token' on the host and export the token first." >&2
fi

# Mode selection: default is an interactive shell; --build runs the loop headless.
MODE="${1:-shell}"

# -e CLAUDE_CODE_OAUTH_TOKEN passes the variable through by name (its value comes
# from the host env); if unset, docker simply omits it.
case "$MODE" in
    --build)
        # Non-interactive (no -t): execute the per-chunk loop and exit when it
        # finishes (all chunks committed) or stops (a BLOCKERS.md). Each chunk's
        # transcript is saved to build_artifacts/*.txt (gitignored). For one
        # combined log, tee to a path OUTSIDE this folder so it does not dirty
        # the worktree the loop builds in:
        #     ./phase3_run-loop.sh --build 2>&1 | tee ~/phase3-build.log
        docker run \
            --rm \
            -i \
            -e CLAUDE_CODE_OAUTH_TOKEN \
            -v "$PROJECT_DIR":/workspace \
            -w /workspace \
            tattoo-feed-dev \
            bash -lc './phase3_build-loop.sh'
        ;;
    shell)
        docker run \
            --rm \
            -it \
            -e CLAUDE_CODE_OAUTH_TOKEN \
            -v "$PROJECT_DIR":/workspace \
            -w /workspace \
            tattoo-feed-dev \
            bash
        ;;
    *)
        echo "usage: $0 [--build]" >&2
        echo "  (no args)  interactive shell in the dev container" >&2
        echo "  --build    run the phase-3 build loop unattended" >&2
        exit 2
        ;;
esac
