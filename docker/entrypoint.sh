#!/bin/sh
# Container entrypoint (Docker Compose, Railway, any container host).
# - Puts local storage + chat history on the persistent volume (Railway sets RAILWAY_VOLUME_MOUNT_PATH).
# - Volumes are often mounted root-owned; fix ownership once, then drop to the unprivileged user.
set -e

DATA_DIR="${RAILWAY_VOLUME_MOUNT_PATH:-${DATA_DIR:-/data}}"
export LOCAL_STORAGE_ROOT="${LOCAL_STORAGE_ROOT:-$DATA_DIR/storage}"
export CHECKPOINT_DB="${CHECKPOINT_DB:-$DATA_DIR/checkpoints.sqlite}"
mkdir -p "$DATA_DIR"

if [ "$(id -u)" = "0" ]; then
  APP_UID="$(id -u maverick)"
  if [ "$(stat -c %u "$DATA_DIR")" != "$APP_UID" ]; then
    echo "entrypoint: taking ownership of $DATA_DIR for user maverick"
    chown -R maverick:maverick "$DATA_DIR"
  fi
  if command -v setpriv >/dev/null 2>&1; then
    exec setpriv --reuid=maverick --regid=maverick --init-groups "$@"
  fi
  echo "entrypoint: setpriv not found, running as root" >&2
fi
exec "$@"
