#!/bin/sh
set -eu

# Generate a private config so the password never appears in server argv.
: "${REDIS_PASSWORD:?REDIS_PASSWORD is required}"
REDIS_MAXMEMORY=${REDIS_MAXMEMORY:-256mb}
REDIS_MAXMEMORY_POLICY=${REDIS_MAXMEMORY_POLICY:-allkeys-lfu}

case "$REDIS_PASSWORD" in
  *'
'*|*"$(printf '\r')"*)
    printf '%s\n' 'REDIS_PASSWORD must not contain line breaks' >&2
    exit 1
    ;;
esac
case "$REDIS_MAXMEMORY" in
  *[!0-9bkmg]*)
    printf '%s\n' 'REDIS_MAXMEMORY must be a positive size such as 256mb' >&2
    exit 1
    ;;
esac
if ! printf '%s\n' "$REDIS_MAXMEMORY" | grep -Eq '^[1-9][0-9]*(b|kb|mb|gb)$'; then
  printf '%s\n' 'REDIS_MAXMEMORY must be a positive size such as 256mb' >&2
  exit 1
fi
case "$REDIS_MAXMEMORY_POLICY" in
  noeviction|allkeys-lru|allkeys-lfu|allkeys-random|volatile-lru|volatile-lfu|volatile-random|volatile-ttl) ;;
  *) printf '%s\n' 'Invalid REDIS_MAXMEMORY_POLICY' >&2; exit 1 ;;
esac

umask 077
config=$(mktemp /tmp/redis.XXXXXX)
escaped_password=$(printf '%s' "$REDIS_PASSWORD" | sed 's/\\/\\\\/g; s/"/\\"/g')
{
  printf '%s\n' 'bind 0.0.0.0' 'protected-mode yes'
  # Redis is used as a cache. Restarting clears cache data by design.
  printf '%s\n' 'appendonly no' 'save ""'
  printf 'maxmemory %s\n' "$REDIS_MAXMEMORY"
  printf 'maxmemory-policy %s\n' "$REDIS_MAXMEMORY_POLICY"
  printf 'requirepass "%s"\n' "$escaped_password"
} > "$config"
if [ "$(id -u)" = 0 ]; then
  chown redis:redis "$config"
fi
unset escaped_password
exec /usr/local/bin/docker-entrypoint.sh redis-server "$config"
