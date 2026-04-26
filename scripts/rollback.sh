#!/usr/bin/env bash
# Roll the running container back to whatever image deploy.sh last saved.
# The git working tree is left untouched — the saved commit/branch from
# .rollback-state is only printed for reference.
#
# Usage (from anywhere):  ./scripts/rollback.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

SERVICE="robotoald"
BACKUP_TAG="robotoald:rollback"
STATE_FILE=".rollback-state"

log() { printf '[rollback] %s\n' "$*"; }

if ! docker image inspect "$BACKUP_TAG" >/dev/null 2>&1; then
    log "No backup image '$BACKUP_TAG' found. Run deploy.sh at least once first."
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. Show the saved commit/branch for reference (no git changes are made).
# ---------------------------------------------------------------------------
if [ -f "$STATE_FILE" ]; then
    saved_commit="$(grep '^commit=' "$STATE_FILE" | cut -d= -f2- || true)"
    saved_branch="$(grep '^branch=' "$STATE_FILE" | cut -d= -f2- || true)"
    log "Saved source state: commit=${saved_commit:-?} branch=${saved_branch:-?}"
    log "(Working tree left as-is. To inspect the rolled-back source: git show $saved_commit)"
else
    log "No state file '$STATE_FILE' found (continuing — only restoring image)."
fi

# ---------------------------------------------------------------------------
# 2. Re-tag the backup image under the name docker-compose expects so that
#    `up` reuses it instead of rebuilding. Compose derives the image name
#    from <project>-<service> (v2) or <project>_<service> (v1); tag both.
# ---------------------------------------------------------------------------
project="$(basename "$PROJECT_DIR" | tr '[:upper:]' '[:lower:]')"
for sep in '-' '_'; do
    target="${project}${sep}${SERVICE}:latest"
    log "Tagging $BACKUP_TAG as $target"
    docker tag "$BACKUP_TAG" "$target"
done

# ---------------------------------------------------------------------------
# 3. Bring the service up using the restored image (no rebuild).
# ---------------------------------------------------------------------------
log "docker-compose up -d --no-build"
docker-compose up -d --no-build

log "Done. Container is now running the previous image; git tree is unchanged."
