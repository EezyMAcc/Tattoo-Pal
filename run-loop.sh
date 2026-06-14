#!/usr/bin/env bash
#
# Launch the tattoo-feed dev container interactively.
#
# This does NOT start the /loop build. It just drops you into a shell
# inside the container, with this project folder mounted at /workspace.
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

set -euo pipefail

# Resolve this script's own directory so the mount is correct no matter where
# the script is invoked from.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

docker run \
    --rm \
    -it \
    -v "$PROJECT_DIR":/workspace \
    -w /workspace \
    tattoo-feed-dev \
    bash
