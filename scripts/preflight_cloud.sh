#!/usr/bin/env bash
# preflight_cloud.sh — verify the cloud/server/ Docker image builds cleanly
# AND that its module tree imports without missing deps.
#
# Runs the exact same Dockerfile Railway uses, in the exact same slim image
# (python:3.13-slim), with the exact same `pip install -r requirements.txt`
# step. If a module inside cloud/server/ imports something that's missing
# from cloud/server/requirements.txt, this exits nonzero — before push.
#
# Backstory: the 2026-07-01 downtime was caused exactly by this class of bug
# (staleness.py imported httpx, but httpx wasn't in server requirements). This
# script would have caught it. Run it before pushing anything that touches
# cloud/server/.
#
# Usage:
#     ./scripts/preflight_cloud.sh         # from the repo root
#     make preflight                       # via Makefile
#
# Exit codes:
#   0 — build succeeded AND all critical modules imported
#   1 — Docker not available
#   2 — image build failed
#   3 — import check failed (missing runtime dep, most likely)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_TAG="volthium-preflight:local"

if ! command -v docker >/dev/null 2>&1; then
    cat >&2 <<EOF
error: docker not installed / not on PATH.
This check needs Docker to reproduce the Railway image. On macOS: install
Docker Desktop. On Linux: 'sudo apt install docker.io' or equivalent.
EOF
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    cat >&2 <<EOF
error: docker daemon not running. Start Docker Desktop (macOS) or
'sudo systemctl start docker' (Linux) and re-run.
EOF
    exit 1
fi

echo "==> building cloud/server/Dockerfile as $IMAGE_TAG"
if ! docker build \
        -f "$REPO_ROOT/cloud/server/Dockerfile" \
        -t "$IMAGE_TAG" \
        "$REPO_ROOT" \
        >/tmp/preflight-build.log 2>&1; then
    tail -30 /tmp/preflight-build.log >&2
    echo >&2
    echo "error: docker build failed (last 30 lines above; full log at /tmp/preflight-build.log)" >&2
    exit 2
fi
echo "    build ok"

# Import every module the server loads at startup. `cloud.server.main`
# transitively imports staleness, db, derive, config, wire — so if any of
# those has a missing dep, this test fails with the same error Railway
# would show. Extra explicit imports at the end are belt-and-suspenders in
# case main.py adds lazy imports that skip a top-level `from x import y`.
echo "==> importing cloud.server.main in the image (this reproduces Railway startup)"
if ! docker run --rm \
        -e DATABASE_URL="" \
        --entrypoint python \
        "$IMAGE_TAG" \
        -c "
import cloud.server.main
import cloud.server.staleness
import cloud.server.derive
import cloud.server.db
import cloud.server.config
import cloud.shared.wire
print('cloud/server module tree imports cleanly')
" 2>&1; then
    echo >&2
    echo "error: module import failed inside the built image. See traceback above." >&2
    echo "Most likely cause: a runtime dep is imported by some cloud/server/*.py but not listed in cloud/server/requirements.txt." >&2
    exit 3
fi

echo "==> preflight ok — safe to push"
