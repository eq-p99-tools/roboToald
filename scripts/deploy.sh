#!/usr/bin/env bash
# Save current docker image, SQLite databases, and git commit as rollback
# points, then git-pull and rebuild via docker-compose.
#
# Usage (from anywhere):  ./scripts/deploy.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

SERVICE="robotoald"
BACKUP_TAG="robotoald:rollback"
STATE_FILE=".rollback-state"
DATABASE_BACKUP_ROOT="data/backups"

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
# 2. Stop the current service briefly and copy its SQLite databases.
# ---------------------------------------------------------------------------
database_backup=""
shopt -s nullglob
database_files=(data/*.db data/*.sqlite data/*.sqlite3)
shopt -u nullglob

if [ "${#database_files[@]}" -gt 0 ]; then
    backup_name="$(date -u '+%Y%m%dT%H%M%SZ')-$(git rev-parse --short HEAD)-$$"
    database_backup="$DATABASE_BACKUP_ROOT/$backup_name"
    was_running=false
    if [ -n "$container_id" ] && [ "$(docker inspect --format '{{.State.Running}}' "$container_id")" = "true" ]; then
        was_running=true
        log "Stopping $SERVICE for a consistent SQLite backup"
        docker-compose stop "$SERVICE"
    fi

    restart_current_service() {
        trap - ERR
        if [ "$was_running" = "true" ]; then
            log "Restarting $SERVICE after backup failure"
            docker-compose start "$SERVICE"
        fi
    }
    trap restart_current_service ERR

    log "Copying ${#database_files[@]} database(s) to $database_backup"
    mkdir -p "$database_backup"
    cp -- "${database_files[@]}" "$database_backup/"

    trap - ERR
    if [ "$was_running" = "true" ]; then
        docker-compose start "$SERVICE"
    fi
else
    log "No SQLite databases found under data/ — skipping database backup."
fi

# ---------------------------------------------------------------------------
# 3. Record current git commit (and branch, if on one) for rollback.
# ---------------------------------------------------------------------------
current_commit="$(git rev-parse HEAD)"
current_branch="$(git rev-parse --abbrev-ref HEAD)"
printf 'commit=%s\nbranch=%s\ndatabase_backup=%s\n' \
    "$current_commit" "$current_branch" "$database_backup" > "$STATE_FILE"
log "Recorded source state for reference: commit=$current_commit branch=$current_branch"
if [ -n "$database_backup" ]; then
    log "Recorded database backup: $database_backup"
fi
log "(rollback.sh restores the image only — this is just so you can look up what was deployed)"

# ---------------------------------------------------------------------------
# 4. Pull latest source.
# ---------------------------------------------------------------------------
log "git pull --ff-only"
git pull --ff-only

# ---------------------------------------------------------------------------
# 5. Rebuild and restart.
# ---------------------------------------------------------------------------
log "docker-compose up -d --build"
docker-compose up -d --build

log "Done. Roll back with: ./scripts/rollback.sh"
