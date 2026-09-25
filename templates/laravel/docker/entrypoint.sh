#!/bin/sh
set -eu
umask 027
case "${APP_ENV:-}" in development|staging|production) ;; *) echo "APP_ENV must identify the target environment" >&2; exit 1 ;; esac
if [ "${APP_DEBUG:-false}" != false ]; then
    echo 'Managed runtime requires APP_DEBUG=false' >&2
    exit 1
fi
if [ -n "${APP_KEY_FILE:-}" ]; then
    APP_KEY=$(cat "$APP_KEY_FILE")
    export APP_KEY
fi
if [ -z "${APP_KEY:-}" ]; then
    echo 'APP_KEY must be supplied; startup never generates or rotates keys' >&2
    exit 1
fi
mkdir -p /tmp/laravel/views storage/framework/cache/data
export APP_CONFIG_CACHE=/tmp/laravel/config.php
export VIEW_COMPILED_PATH=/tmp/laravel/views
for directory in storage/app/public storage/framework/cache storage/framework/sessions bootstrap/cache; do
    if [ ! -w "$directory" ]; then
        echo "Required runtime directory is not writable: $directory" >&2
        exit 1
    fi
done
# Each container needs its own bootstrap/cache writable mount, never a shared one.
umask 077
php artisan config:cache
umask 027
exec "$@"
