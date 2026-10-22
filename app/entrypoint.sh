#!/bin/sh
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ -n "${TZ:-}" ] && [ -f "/usr/share/zoneinfo/${TZ}" ]; then
  ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime
  printf '%s\n' "$TZ" > /etc/timezone
fi

mkdir -p /config /data/artwork /cache /music /movies /tv /backups

if [ "$(id -u)" = "0" ] && [ "$PUID" != "0" ]; then
  groupmod -o -g "$PGID" app
  usermod -o -u "$PUID" -g app app
  chown -R app:app /config || true
  [ "$(stat -c %u /data)" = "$(id -u app)" ] || chown -R app:app /data || true
  [ "$(stat -c %u /cache)" = "$(id -u app)" ] || chown -R app:app /cache || true
  chmod 0777 /backups || true
  exec gosu app "$@"
fi

exec "$@"
