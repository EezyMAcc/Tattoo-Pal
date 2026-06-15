# syntax=docker/dockerfile:1
#
# Dev environment for the tattoo-feed overnight build.
# Everything Claude Code needs to build the project lives in this image:
# git, curl, Node.js (Claude Code is a Node CLI), uv (Python deps), and
# Claude Code itself. The image is a frozen snapshot; the project source is
# NOT baked in — it gets mounted at run time (see run-loop.sh).

# Base layer: a minimal Debian with Python 3.12 already installed.
# "-slim" means stripped down (no build tools / docs) to keep the image small.
FROM python:3.12-slim

# Avoid interactive prompts (e.g. tzdata) during apt installs in a build with
# no human attached.
ENV DEBIAN_FRONTEND=noninteractive

# --- OS-level tools -------------------------------------------------------
# Install git + curl (curl is needed to fetch the Node and uv installers).
# We clean the apt cache in the same RUN so the deleted files never get
# baked into an image layer (each RUN is a layer; deleting in a later layer
# would not shrink the image).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --- Node.js (for Claude Code) -------------------------------------------
# Claude Code is distributed as an npm package, so we need Node + npm.
# NodeSource's setup script wires up their apt repo for Node.js 20 LTS.
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# --- uv (Python package manager) -----------------------------------------
# The project pins deps with uv. The official installer drops the `uv` and
# `uvx` binaries into /root/.local/bin, so we add that to PATH.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# --- Claude Code CLI ------------------------------------------------------
# Installed globally so the `claude` command is on PATH for every container.
RUN npm install -g @anthropic-ai/claude-code

# --- Skip Claude Code's first-run onboarding wizard ----------------------
# /root is throwaway (--rm), so every container looks like a brand-new
# machine: interactive `claude` runs its onboarding/login wizard and ignores
# the CLAUDE_CODE_OAUTH_TOKEN we forward in (which DOES work for headless
# `claude -p`). Pre-seeding onboarding state lets interactive `claude` skip
# the wizard and use the env token. This holds NO credential — only the
# "onboarding done" + workspace-trust flags — so it is safe to bake in.
RUN printf '{"hasCompletedOnboarding":true,"theme":"dark","projects":{"/workspace":{"hasTrustDialogAccepted":true}}}' \
        > /root/.claude.json

# All work happens here. The project folder is mounted onto this path at run
# time, so /workspace == your tattoo-feed folder on the host.
WORKDIR /workspace

# Default to an interactive shell; run-loop.sh overrides what actually runs.
CMD ["bash"]
