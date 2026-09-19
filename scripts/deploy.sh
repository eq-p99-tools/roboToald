#!/usr/bin/env bash
# Save current docker image, SQLite databases, and git commit as rollback
# points, then git-pull and rebuild via docker-compose.
#
# The service is stopped only once: after the new image is built, we take a
# consistent SQLite backup, then bring the new container up.
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
# 2. Record current git commit (and branch, if on one) for rollback.
#    Database backup path is filled in after the pre-rollout copy below.
# ---------------------------------------------------------------------------
current_commit="$(git rev-parse HEAD)"
current_branch="$(git rev-parse --abbrev-ref HEAD)"
database_backup=""
printf 'commit=%s\nbranch=%s\ndatabase_backup=%s\n' \
    "$current_commit" "$current_branch" "$database_backup" > "$STATE_FILE"
log "Recorded source state for reference: commit=$current_commit branch=$current_branch"
log "(rollback.sh restores the image only — this is just so you can look up what was deployed)"

# ---------------------------------------------------------------------------
# 3. Pull latest source.
# ---------------------------------------------------------------------------
log "git pull --ff-only"
git pull --ff-only

# ---------------------------------------------------------------------------
# 4. Build the new image without restarting the running container yet.
# ---------------------------------------------------------------------------
log "docker-compose build"
docker-compose build

# ---------------------------------------------------------------------------
# 5. Stop once, back up SQLite, then roll the new image.
# ---------------------------------------------------------------------------
shopt -s nullglob
database_files=(data/*.db data/*.sqlite data/*.sqlite3)
shopt -u nullglob

container_id="$(docker-compose ps -q "$SERVICE" 2>/dev/null || true)"
was_running=false
if [ -n "$container_id" ] && [ "$(docker inspect --format '{{.State.Running}}' "$container_id")" = "true" ]; then
    was_running=true
fi

restart_current_service() {
    trap - ERR
    if [ "$was_running" = "true" ]; then
        log "Restarting previous $SERVICE container after deploy failure"
        docker-compose start "$SERVICE"
    fi
}
trap restart_current_service ERR

if [ "$was_running" = "true" ]; then
    log "Stopping $SERVICE for SQLite backup and rollout"
    docker-compose stop "$SERVICE"
fi

if [ "${#database_files[@]}" -gt 0 ]; then
    backup_name="$(date -u '+%Y%m%dT%H%M%SZ')-${current_commit:0:7}-$$"
    database_backup="$DATABASE_BACKUP_ROOT/$backup_name"
    log "Copying ${#database_files[@]} database(s) to $database_backup"
    mkdir -p "$database_backup"
    cp -- "${database_files[@]}" "$database_backup/"
    printf 'commit=%s\nbranch=%s\ndatabase_backup=%s\n' \
        "$current_commit" "$current_branch" "$database_backup" > "$STATE_FILE"
    log "Recorded database backup: $database_backup"
else
    log "No SQLite databases found under data/ — skipping database backup."
fi

log "docker-compose up -d --no-build"
docker-compose up -d --no-build

trap - ERR

log "Done. Roll back with: ./scripts/rollback.sh"
