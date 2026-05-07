#!/usr/bin/env bash
# Save current docker image + git commit as a rollback point, then
# git-pull and rebuild via docker-compose.
#
# Usage (from anywhere):  ./scripts/deploy.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

SERVICE="robotoald"
BACKUP_TAG="robotoald:rollback"
STATE_FILE=".rollback-state"

log() { printf '[deploy] %s\n' "$*"; }

# ---------------------------------------------------------------------------
# 1. Capture the currently-running image so we can roll back to it later.
# ---------------------------------------------------------------------------
container_id="$(docker-compose ps -q "$SERVICE" 2>/dev/null || true)"
image_id=""
if [ -n "$container_id" ]; then
    image_id="$(docker inspect --format '{{.Image}}' "$container_id" 2>/dev/null || true)"
fi
if [ -z "$image_id" ]; then
    image_id="$(docker-compose images -q "$SERVICE" 2>/dev/null || true)"
fi

if [ -n "$image_id" ]; then
    log "Tagging current image $image_id as $BACKUP_TAG"
    docker tag "$image_id" "$BACKUP_TAG"
else
    log "No existing image found — skipping image backup tag."
fi

# ---------------------------------------------------------------------------
# 2. Record current git commit (and branch, if on one) for rollback.
# ---------------------------------------------------------------------------
current_commit="$(git rev-parse HEAD)"
current_branch="$(git rev-parse --abbrev-ref HEAD)"
printf 'commit=%s\nbranch=%s\n' "$current_commit" "$current_branch" > "$STATE_FILE"
log "Recorded source state for reference: commit=$current_commit branch=$current_branch"
log "(rollback.sh restores the image only — this is just so you can look up what was deployed)"

# ---------------------------------------------------------------------------
# 3. Pull latest source.
# ---------------------------------------------------------------------------
log "git pull --ff-only"
git pull --ff-only

# ---------------------------------------------------------------------------
# 4. Rebuild and restart.
# ---------------------------------------------------------------------------
log "docker-compose up -d --build"
docker-compose up -d --build

log "Done. Roll back with: ./scripts/rollback.sh"
